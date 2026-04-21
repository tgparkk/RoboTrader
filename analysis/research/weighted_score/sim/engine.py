"""분봉 루프 시뮬레이션 엔진.

입력:
- WeightedScoreStrategy (가중치 + 임계치 + ExitPolicy)
- stock_data: 종목 → DF (분봉 + 피처). 컬럼 최소: trade_date, idx, time, open, high, low, close
  그리고 strategy.feature_names 에 해당하는 피처 컬럼.
- dates: 시뮬레이션 대상 거래일 (정렬된 YYYYMMDD 리스트)
- 기타: initial_capital, size_krw, max_positions, CostModel

출력: SimResult (trades DataFrame + equity curve + 메타정보)

동작:
1. 각 (date, idx) 시간 step 마다
   a) 보유 포지션 exit 평가 (SL/TP/trail/time/max_hold/score)
   b) 미보유 + 슬롯 여유 시, score > threshold 후보를 내림차순 정렬하여 슬롯 채움
2. dates 의 마지막 날 마지막 바에서도 미청산 포지션이 있으면 EOS 로 강제 청산

동시 진입 우선순위: (score desc, stock_code asc) — 결정론.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from analysis.research.weighted_score.sim import metrics as mtr
from analysis.research.weighted_score.sim.cost_model import CostModel, DEFAULT_COST
from analysis.research.weighted_score.sim.portfolio import Portfolio, Trade
from analysis.research.weighted_score.strategy.weighted_score import WeightedScoreStrategy


@dataclass
class SimResult:
    trades: pd.DataFrame
    equity_curve: pd.Series
    metrics: mtr.PerfMetrics
    n_bars_processed: int
    dates: list[str]


REQUIRED_BAR_COLS = ("trade_date", "idx", "time", "open", "high", "low", "close")


def _validate_stock_df(code: str, df: pd.DataFrame, feature_names: list[str]) -> None:
    missing = [c for c in REQUIRED_BAR_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{code}: missing bar columns {missing}")
    missing_f = [n for n in feature_names if n not in df.columns]
    if missing_f:
        raise ValueError(f"{code}: missing feature columns {missing_f}")


def _prepare_stock(
    code: str,
    df: pd.DataFrame,
    strategy: WeightedScoreStrategy,
    dates: list[str],
) -> Optional[pd.DataFrame]:
    """종목 DF 를 시뮬레이션용으로 전처리. score 를 한 번에 계산해 컬럼으로 추가.

    반환: 관심 dates 로 필터된 DF (trade_date, idx 정렬, score 포함) 또는 None.
    """
    _validate_stock_df(code, df, strategy.feature_names)
    date_set = set(dates)
    sub = df[df["trade_date"].isin(date_set)].copy()
    if sub.empty:
        return None
    sub = sub.sort_values(["trade_date", "idx"]).reset_index(drop=True)
    sub["score"] = strategy.score_frame(sub)
    return sub


def simulate(
    strategy: WeightedScoreStrategy,
    stock_data: dict[str, pd.DataFrame],
    dates: list[str],
    initial_capital: float,
    size_krw: float,
    max_positions: int,
    cost_model: CostModel = DEFAULT_COST,
    progress_every: Optional[int] = None,
) -> SimResult:
    if not dates:
        raise ValueError("dates must be non-empty")
    dates_sorted = sorted(dates)

    # 1) 각 종목 DF 에 score 추가 + 관심 날짜로 필터
    prepared: dict[str, pd.DataFrame] = {}
    for code, df in stock_data.items():
        p = _prepare_stock(code, df, strategy, dates_sorted)
        if p is not None:
            prepared[code] = p

    if not prepared:
        raise ValueError("no stock has data in given dates")

    # 2) 각 종목 (trade_date, idx) 로 인덱싱 — O(1) 조회
    indexed: dict[str, pd.DataFrame] = {
        code: df.set_index(["trade_date", "idx"])
        for code, df in prepared.items()
    }

    portfolio = Portfolio(
        max_positions=max_positions,
        size_krw=size_krw,
        cost_model=cost_model,
    )

    n_bars_processed = 0

    # 3) 날짜별 메인 루프
    last_date = dates_sorted[-1]
    for date in dates_sorted:
        # 이 날짜의 모든 idx 수집 (종목별 상이할 수 있으므로 union)
        idx_set: set[int] = set()
        for df in prepared.values():
            mask = df["trade_date"] == date
            if mask.any():
                idx_set.update(df.loc[mask, "idx"].tolist())
        if not idx_set:
            continue
        idx_list = sorted(idx_set)

        # 날짜 단위 캐시 (종목별 해당 날짜의 idx→row 빠른 접근)
        day_slices: dict[str, pd.DataFrame] = {
            code: idxed.xs(date, level="trade_date", drop_level=False)
            if date in idxed.index.get_level_values("trade_date")
            else pd.DataFrame()
            for code, idxed in indexed.items()
        }

        is_last_date = (date == last_date)

        for i, idx in enumerate(idx_list):
            is_last_bar = is_last_date and (i == len(idx_list) - 1)

            # 이 minute 에 bar 가 있는 종목들
            bars_this_minute: dict[str, pd.Series] = {}
            for code, day_df in day_slices.items():
                if day_df.empty:
                    continue
                # day_df 의 index 는 (trade_date, idx). idx 로 바로 접근
                try:
                    row = day_df.loc[(date, idx)]
                except KeyError:
                    continue
                # .loc 로 다중 일치면 DataFrame, 단일이면 Series
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                bars_this_minute[code] = row

            if not bars_this_minute:
                continue

            # (a) 포지션 업데이트 + exit 평가
            to_close: list[tuple[str, str, float]] = []
            for code, pos in list(portfolio.positions.items()):
                if code not in bars_this_minute:
                    continue  # 이 bar 에 데이터 없음 (건너뜀 — 다음 bar 에 재평가)
                bar = bars_this_minute[code]
                high = float(bar["high"])
                low = float(bar["low"])
                close = float(bar["close"])
                score = float(bar["score"]) if not pd.isna(bar["score"]) else float("nan")

                pos.update_bar(date, high)
                result = Portfolio.evaluate_exit(
                    pos, high, low, close, score, strategy.exit_policy
                )
                if result is not None:
                    reason, exit_price = result
                    to_close.append((code, reason, exit_price))
                elif is_last_bar:
                    # 최종 바 강제 청산
                    to_close.append((code, "EOS", close))

            for code, reason, exit_price in to_close:
                bar = bars_this_minute[code]
                portfolio.close_position(
                    stock_code=code,
                    date=date,
                    idx=int(idx),
                    time=str(bar["time"]),
                    exit_price_raw=exit_price,
                    reason=reason,
                )

            # (b) 진입 평가 (남은 슬롯)
            if portfolio.has_slot():
                candidates: list[tuple[float, str, pd.Series]] = []
                for code, bar in bars_this_minute.items():
                    if portfolio.is_holding(code):
                        continue
                    score = bar["score"]
                    if pd.isna(score):
                        continue
                    if strategy.is_entry_signal(float(score)):
                        candidates.append((float(score), code, bar))
                # 정렬: (score desc, stock_code asc)
                candidates.sort(key=lambda x: (-x[0], x[1]))
                for score, code, bar in candidates:
                    if not portfolio.has_slot():
                        break
                    portfolio.try_enter(
                        stock_code=code,
                        date=date,
                        idx=int(idx),
                        time=str(bar["time"]),
                        price=float(bar["close"]),
                        score=score,
                    )

            n_bars_processed += 1

            if progress_every and n_bars_processed % progress_every == 0:
                print(
                    f"  [{date} idx={idx}] processed {n_bars_processed:,} bar-iters, "
                    f"open={portfolio.n_open()} closed={len(portfolio.closed_trades)}"
                )

    # 4) 결과 정리
    trades_dicts = [t.to_dict() for t in portfolio.closed_trades]
    trades_df = pd.DataFrame(trades_dicts)
    if not trades_df.empty:
        trades_df = trades_df.sort_values(["exit_date", "exit_idx", "stock_code"]).reset_index(drop=True)

    equity = mtr.realized_equity_curve(trades_df, initial_capital, size_krw)
    perf = mtr.metrics_from_equity(equity, trades_df=trades_df)

    return SimResult(
        trades=trades_df,
        equity_curve=equity,
        metrics=perf,
        n_bars_processed=n_bars_processed,
        dates=dates_sorted,
    )
