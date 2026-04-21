"""매트릭스 기반 고속 시뮬레이션 엔진.

`sim/engine.py` 의 기능을 축약한 drop-in 대안. Phase A/B 그리드 탐색에 사용.

**제약 (v1)**:
- trailing stop 미지원
- score_exit_threshold (점수 반전 청산) 미지원
- time_exit_bars 는 지원
- 기타(SL/TP/MaxHold/EOS)는 동일

**시계열 무결성 보장**:
- 피처 matrix 는 이미 shift(1) 적용된 값을 그대로 사용
- score 계산은 분봉 t 시점 정보만 사용
- 진입 시 exit_bar 는 forward-looking scan (엔진 기존 로직과 동등)
- 포지션 슬롯 관리는 chronological 작은 루프

**성능 핵심**:
- pandas.loc 조회 제거 → numpy 매트릭스 row 인덱싱
- 진입 시점에 SL/TP/MaxHold 의 exit_bar 를 바로 결정 (매 bar 점검 불필요)
- 빈 슬롯이 있을 때만 entry mask 연산
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from analysis.research.weighted_score.sim import metrics as mtr
from analysis.research.weighted_score.sim.cost_model import CostModel, DEFAULT_COST
from analysis.research.weighted_score.sim.portfolio import Trade
from analysis.research.weighted_score.strategy.weighted_score import WeightedScoreStrategy


REQUIRED_BAR_COLS = ("trade_date", "idx", "time", "open", "high", "low", "close")


# ---------------- SimContext ----------------


@dataclass
class SimContext:
    """여러 trial 에서 재사용 가능한 전처리 데이터.

    feature_mat 은 피처명 → (N, K) float 매트릭스. NaN 가능.
    """
    timeline_dates: np.ndarray      # shape (N,), dtype='<U8'
    timeline_idx: np.ndarray        # shape (N,), int
    timeline_time: np.ndarray       # shape (N,), dtype='<U6'
    day_group: np.ndarray           # shape (N,), int  — 같은 날짜 묶음 인덱스
    stock_codes: list[str]          # length K
    feature_names: list[str]
    close_mat: np.ndarray           # (N, K)
    high_mat: np.ndarray
    low_mat: np.ndarray
    feature_mats: dict[str, np.ndarray]  # name -> (N, K)
    valid_mask: np.ndarray          # (N, K) bool, True = 가격 데이터 존재


def build_context(
    stock_data: dict[str, pd.DataFrame],
    dates: list[str],
    feature_names: list[str],
) -> SimContext:
    """종목별 분봉+피처 DF 를 매트릭스로 변환.

    dates 는 포함 거래일. 각 종목은 REQUIRED_BAR_COLS + feature_names 를 가져야 함.
    timeline 은 모든 종목에서 나타난 (date, idx) 의 union 을 정렬한 것.
    """
    if not stock_data:
        raise ValueError("stock_data is empty")
    if not dates:
        raise ValueError("dates is empty")

    date_set = set(dates)
    # 1) union of (date, idx) across stocks
    pair_set: set[tuple[str, int]] = set()
    filtered: dict[str, pd.DataFrame] = {}
    for code, df in stock_data.items():
        missing = [c for c in REQUIRED_BAR_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"{code}: missing bar cols {missing}")
        miss_f = [f for f in feature_names if f not in df.columns]
        if miss_f:
            raise ValueError(f"{code}: missing feature cols {miss_f}")
        sub = df[df["trade_date"].isin(date_set)]
        if sub.empty:
            continue
        filtered[code] = sub
        pair_set.update(zip(sub["trade_date"], sub["idx"].astype(int)))

    if not filtered:
        raise ValueError("no stock has data in dates")

    sorted_pairs = sorted(pair_set, key=lambda p: (p[0], p[1]))
    timeline_dates = np.array([p[0] for p in sorted_pairs], dtype="<U8")
    timeline_idx = np.array([p[1] for p in sorted_pairs], dtype=np.int32)
    N = len(sorted_pairs)

    # (date, idx) → row index
    row_of: dict[tuple[str, int], int] = {p: i for i, p in enumerate(sorted_pairs)}

    stock_codes = sorted(filtered.keys())
    K = len(stock_codes)

    close_mat = np.full((N, K), np.nan, dtype=np.float64)
    high_mat = np.full((N, K), np.nan, dtype=np.float64)
    low_mat = np.full((N, K), np.nan, dtype=np.float64)
    timeline_time = np.array(["000000"] * N, dtype="<U6")
    feature_mats: dict[str, np.ndarray] = {
        f: np.full((N, K), np.nan, dtype=np.float64) for f in feature_names
    }

    for k, code in enumerate(stock_codes):
        df = filtered[code]
        dates_col = df["trade_date"].to_numpy()
        idx_col = df["idx"].astype(int).to_numpy()
        time_col = df["time"].astype(str).to_numpy()
        close = df["close"].to_numpy(dtype=np.float64)
        high = df["high"].to_numpy(dtype=np.float64)
        low = df["low"].to_numpy(dtype=np.float64)
        feat_arrs = {f: df[f].to_numpy(dtype=np.float64) for f in feature_names}
        for i in range(len(df)):
            r = row_of[(dates_col[i], idx_col[i])]
            close_mat[r, k] = close[i]
            high_mat[r, k] = high[i]
            low_mat[r, k] = low[i]
            # timeline_time 은 bar 의 time 을 넣는데 종목마다 같다고 가정
            if timeline_time[r] == "000000":
                timeline_time[r] = time_col[i]
            for f, arr in feat_arrs.items():
                feature_mats[f][r, k] = arr[i]

    valid_mask = ~np.isnan(close_mat)

    # day_group: 같은 날짜의 연속 bar 그룹 번호
    day_group = np.zeros(N, dtype=np.int32)
    g = 0
    for i in range(1, N):
        if timeline_dates[i] != timeline_dates[i - 1]:
            g += 1
        day_group[i] = g

    return SimContext(
        timeline_dates=timeline_dates,
        timeline_idx=timeline_idx,
        timeline_time=timeline_time,
        day_group=day_group,
        stock_codes=stock_codes,
        feature_names=list(feature_names),
        close_mat=close_mat,
        high_mat=high_mat,
        low_mat=low_mat,
        feature_mats=feature_mats,
        valid_mask=valid_mask,
    )


# ---------------- Score 계산 ----------------


def compute_score_matrix(
    ctx: SimContext,
    weights: dict[str, float],
) -> np.ndarray:
    """가중치 벡터로 score matrix (N, K) 계산. NaN 전파.

    weights 는 ctx.feature_names 의 일부/전체. 미등록 피처는 에러.
    """
    score = np.zeros_like(ctx.close_mat)
    nan_mask = np.zeros_like(ctx.close_mat, dtype=bool)
    for name, w in weights.items():
        if name not in ctx.feature_mats:
            raise ValueError(f"unknown feature: {name}")
        if w == 0.0:
            continue
        mat = ctx.feature_mats[name]
        score += w * mat
        nan_mask |= np.isnan(mat)
    # 가격 없는 곳도 NaN
    nan_mask |= ~ctx.valid_mask
    score[nan_mask] = np.nan
    return score


# ---------------- 진입별 Exit 사전계산 ----------------


def _compute_exit(
    stock_idx: int,
    entry_bar: int,
    entry_price: float,
    ctx: SimContext,
    sl_mult: float,          # 1 + SL_pct/100 (음)
    tp_mult: float,          # 1 + TP_pct/100 (양)
    max_holding_days: int,
    time_exit_bars: Optional[int],
) -> tuple[int, str, float]:
    """진입 후 청산 bar/reason/price 결정 (비용 미반영 raw 가격).

    우선순위: SL → TP → TIME → MAX_HOLD → EOS.
    같은 bar 에서 SL/TP 가 동시 조건이면 SL 우선 (보수적).
    """
    N = len(ctx.timeline_dates)
    sl_price = entry_price * sl_mult
    tp_price = entry_price * tp_mult

    # MAX_HOLD 청산 bar = (entry 후) max_holding_days 번째 새 날짜의 첫 bar.
    # slow engine 과 동일: trading_days_held 가 max_holding_days 에 도달하는 첫 bar.
    entry_day_group = int(ctx.day_group[entry_bar])
    target_day_group = entry_day_group + max_holding_days
    # day_group >= target_day_group 인 첫 bar
    mh_bar = int(np.searchsorted(ctx.day_group, target_day_group, side="left"))
    if mh_bar >= N:
        mh_bar = N - 1  # target_day_group 이 없으면 EOS 로 처리됨

    scan_end = mh_bar
    if time_exit_bars is not None:
        scan_end = min(scan_end, entry_bar + time_exit_bars)
    if scan_end >= N:
        scan_end = N - 1

    if scan_end <= entry_bar:
        # 청산 불가 — 다음 bar 가 없으면 진입 bar 에서 강제 종료
        return entry_bar, "EOS", ctx.close_mat[entry_bar, stock_idx]

    hs = ctx.high_mat[entry_bar + 1 : scan_end + 1, stock_idx]
    ls = ctx.low_mat[entry_bar + 1 : scan_end + 1, stock_idx]

    # 결측 bar 처리: SL/TP 조건에서 NaN 비교는 False → 자동으로 스킵됨
    sl_hits = ls <= sl_price
    tp_hits = hs >= tp_price

    sl_first = int(np.argmax(sl_hits)) if sl_hits.any() else -1
    tp_first = int(np.argmax(tp_hits)) if tp_hits.any() else -1

    if sl_first == -1 and tp_first == -1:
        # 스캔 구간 내 SL/TP 미발동 → 청산 시점은 scan_end
        # 그 이유가 time_exit 인지 max_hold 인지 구분
        if time_exit_bars is not None and scan_end == entry_bar + time_exit_bars:
            reason = "TIME"
        else:
            reason = "MAX_HOLD"
        exit_bar = scan_end
        return exit_bar, reason, ctx.close_mat[exit_bar, stock_idx]

    if sl_first == -1:
        exit_bar = entry_bar + 1 + tp_first
        return exit_bar, "TP", tp_price
    if tp_first == -1:
        exit_bar = entry_bar + 1 + sl_first
        return exit_bar, "SL", sl_price
    # 둘 다 있으면 먼저 발동 (동률이면 SL)
    if sl_first <= tp_first:
        return entry_bar + 1 + sl_first, "SL", sl_price
    return entry_bar + 1 + tp_first, "TP", tp_price


# ---------------- 메인 시뮬 ----------------


@dataclass
class FastSimResult:
    trades: pd.DataFrame
    equity_curve: pd.Series
    metrics: mtr.PerfMetrics
    n_entries_evaluated: int
    n_trades: int


def simulate_fast(
    ctx: SimContext,
    strategy: WeightedScoreStrategy,
    initial_capital: float,
    size_krw: float,
    max_positions: int,
    cost_model: CostModel = DEFAULT_COST,
) -> FastSimResult:
    """fast path. trailing / score_flip 은 무시됨 (policy 에 있어도 경고 없이 skip)."""
    N = len(ctx.timeline_dates)
    K = len(ctx.stock_codes)

    policy = strategy.exit_policy
    sl_mult = 1.0 + policy.stop_loss_pct / 100.0
    tp_mult = 1.0 + policy.take_profit_pct / 100.0
    max_holding_days = policy.max_holding_days
    time_exit_bars = policy.time_exit_bars

    # 1) score matrix
    score_mat = compute_score_matrix(ctx, strategy.weights)

    # 2) entry mask
    entry_mask = score_mat > strategy.entry_threshold  # NaN 는 False

    # 3) 포트폴리오 상태
    # open_positions: stock_idx -> dict(entry_bar, exit_bar, exit_price, exit_reason, entry_score)
    open_positions: dict[int, dict] = {}
    trades: list[Trade] = []
    n_entries_evaluated = 0

    # 4) bar 루프
    for t in range(N):
        # (a) 이 bar 에 청산 예정인 포지션 처리
        to_close = [k for k, p in open_positions.items() if p["exit_bar"] == t]
        for k in to_close:
            p = open_positions.pop(k)
            raw_exit_price = p["exit_price"]
            effective_exit = cost_model.exit_fill_adjusted(raw_exit_price)
            gross = (effective_exit / p["entry_price"] - 1.0) * 100.0
            pnl = size_krw * gross / 100.0
            trades.append(
                Trade(
                    stock_code=ctx.stock_codes[k],
                    entry_date=str(ctx.timeline_dates[p["entry_bar"]]),
                    entry_idx=int(ctx.timeline_idx[p["entry_bar"]]),
                    entry_time=str(ctx.timeline_time[p["entry_bar"]]),
                    entry_price=p["entry_price"],
                    entry_score=p["entry_score"],
                    exit_date=str(ctx.timeline_dates[t]),
                    exit_idx=int(ctx.timeline_idx[t]),
                    exit_time=str(ctx.timeline_time[t]),
                    exit_price=effective_exit,
                    exit_reason=p["exit_reason"],
                    size_krw=size_krw,
                    bars_held=t - p["entry_bar"],
                    trading_days_held=int(ctx.day_group[t]) - int(ctx.day_group[p["entry_bar"]]),
                    gross_pct=gross,
                    net_pct=gross,
                    pnl_krw=pnl,
                )
            )

        # (b) 마지막 bar 에서 미청산 강제 청산
        if t == N - 1 and open_positions:
            for k, p in list(open_positions.items()):
                raw_exit_price = ctx.close_mat[t, k]
                if np.isnan(raw_exit_price):
                    continue
                effective_exit = cost_model.exit_fill_adjusted(raw_exit_price)
                gross = (effective_exit / p["entry_price"] - 1.0) * 100.0
                pnl = size_krw * gross / 100.0
                trades.append(
                    Trade(
                        stock_code=ctx.stock_codes[k],
                        entry_date=str(ctx.timeline_dates[p["entry_bar"]]),
                        entry_idx=int(ctx.timeline_idx[p["entry_bar"]]),
                        entry_time=str(ctx.timeline_time[p["entry_bar"]]),
                        entry_price=p["entry_price"],
                        entry_score=p["entry_score"],
                        exit_date=str(ctx.timeline_dates[t]),
                        exit_idx=int(ctx.timeline_idx[t]),
                        exit_time=str(ctx.timeline_time[t]),
                        exit_price=effective_exit,
                        exit_reason="EOS",
                        size_krw=size_krw,
                        bars_held=t - p["entry_bar"],
                        trading_days_held=int(ctx.day_group[t]) - int(ctx.day_group[p["entry_bar"]]),
                        gross_pct=gross,
                        net_pct=gross,
                        pnl_krw=pnl,
                    )
                )
                open_positions.pop(k)

        # (c) 진입 평가 — 슬롯 비어있을 때만
        if len(open_positions) >= max_positions:
            continue
        mask_row = entry_mask[t]
        # 이미 보유 중인 종목 제외
        if open_positions:
            mask_row = mask_row.copy()
            for k in open_positions:
                mask_row[k] = False
        if not mask_row.any():
            continue
        candidates = np.where(mask_row)[0]
        scores = score_mat[t, candidates]
        # 정렬 (score desc, stock_code asc)
        order = np.argsort(-scores, kind="stable")
        # stable sort + 보조 키로 stock_code 보장: 같은 score 에서 stock_idx 오름차순(= code 정렬 순)
        for pos in order:
            if len(open_positions) >= max_positions:
                break
            k = int(candidates[pos])
            raw_entry_price = ctx.close_mat[t, k]
            if np.isnan(raw_entry_price):
                continue
            effective_entry = cost_model.entry_fill_adjusted(raw_entry_price)
            exit_bar, exit_reason, exit_price_raw = _compute_exit(
                stock_idx=k,
                entry_bar=t,
                entry_price=effective_entry,
                ctx=ctx,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                max_holding_days=max_holding_days,
                time_exit_bars=time_exit_bars,
            )
            open_positions[k] = {
                "entry_bar": t,
                "entry_price": effective_entry,
                "entry_score": float(score_mat[t, k]),
                "exit_bar": exit_bar,
                "exit_price": exit_price_raw,
                "exit_reason": exit_reason,
            }
            n_entries_evaluated += 1

    # 5) DF/metrics
    trades_df = pd.DataFrame([t.to_dict() for t in trades])
    if not trades_df.empty:
        trades_df = trades_df.sort_values(["exit_date", "exit_idx", "stock_code"]).reset_index(drop=True)

    equity = mtr.realized_equity_curve(trades_df, initial_capital, size_krw)
    perf = mtr.metrics_from_equity(equity, trades_df=trades_df)

    return FastSimResult(
        trades=trades_df,
        equity_curve=equity,
        metrics=perf,
        n_entries_evaluated=n_entries_evaluated,
        n_trades=len(trades),
    )
