"""macd_cross 멀티버스 공통 유틸 — KPI extras, dataset 로더, cell evaluator."""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.common.metrics import (
    compute_calmar,
    compute_max_drawdown,
    compute_win_rate,
)
from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import STAGE2_FOLDS
from backtests.multiverse.universe import select_top_universe
from backtests.strategies.base import StrategyBase


def compute_top1_share(trade_pnls: pd.Series) -> float:
    """단일 최대 P&L / 전체 net 합 (signed). PHASE6 OOS 와 동일 정의.

    분모는 net (signed) sum 이므로 sum<0 일 때 share 도 음수가 될 수 있다.
    거래 0 또는 sum=0 시 0.0 반환.
    """
    if len(trade_pnls) == 0:
        return 0.0
    total = float(trade_pnls.sum())
    if total == 0:
        return 0.0
    return float(trade_pnls.max() / total)


def compute_max_consec_loss(trade_pnls: Iterable[float]) -> int:
    """시간순 trade pnl 시퀀스에서 음수 연속 카운트 최댓값.

    pnl == 0 은 streak 를 끊는 (loss 가 아님) 것으로 처리.
    """
    max_run = 0
    cur_run = 0
    for p in trade_pnls:
        if p < 0:
            cur_run += 1
            if cur_run > max_run:
                max_run = cur_run
        else:
            cur_run = 0
    return max_run


@dataclass
class Dataset:
    """단일 평가 dataset — fold1/fold2/fold3/oos."""

    name: str
    minute_start: str
    minute_end: str
    daily_start: str
    minute_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    daily_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    universe: List[str] = field(default_factory=list)
    kospi_daily_df: Optional[pd.DataFrame] = None  # 신규 (regime filter 용)


def build_cell_kpis(
    equity: pd.Series,
    trades: List[Dict],
    trading_days: int,
) -> Dict[str, float]:
    """단일 cell × dataset 평가 결과 → KPI dict.

    Args:
        equity: 매 bar 의 cm.available_cash + 보유포지션 가치 시계열.
        trades: BacktestResult.trades — 각 원소는 {"pnl": float, ...} 형태.
        trading_days: dataset 의 영업일수 (monthly_trades 계산용).

    Returns:
        {calmar, return, mdd, trades, win_rate, top1_share, max_consec_loss, monthly_trades}

        calmar 은 MDD=0 (drawdown 없음) 또는 trading_days<=0 시 nan. 다운스트림 (Task 9-10 러너)
        에서 평균 집계 시 nan 처리 필요.
    """
    if trades:
        pnl_raw = pd.Series([t["pnl"] for t in trades], dtype=float)
        pnl_series = pnl_raw.dropna()
    else:
        pnl_series = pd.Series(dtype=float)

    if len(equity) >= 2:
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    else:
        total_return = 0.0

    return {
        "calmar": compute_calmar(equity, trading_days),
        "return": total_return,
        "mdd": compute_max_drawdown(equity),
        "trades": int(len(trades)),
        "win_rate": compute_win_rate(pnl_series),
        "top1_share": compute_top1_share(pnl_series),
        "max_consec_loss": compute_max_consec_loss(pnl_series.tolist()),
        "monthly_trades": (
            float(len(trades) * 21 / trading_days)
            if trading_days > 0
            else 0.0
        ),
    }


# OOS hold-out 정의 (Stage 2 fold 와 동일 universe 캐시 사용)
OOS_TEST_START = "20260301"
OOS_TEST_END = "20260424"


def _trading_days_count(minute_by_code: Dict[str, pd.DataFrame]) -> int:
    """모든 종목 분봉의 unique trade_date 수 — dataset 의 영업일수 추정."""
    all_dates = set()
    for df in minute_by_code.values():
        if not df.empty:
            all_dates.update(df["trade_date"].unique().tolist())
    return len(all_dates)


def load_all_datasets() -> Dict[str, Dataset]:
    """4 dataset 일괄 로드 — Stage 2 와 동일 universe 사용.

    분봉 1회 광역 로드 (2025-03 ~ 2026-04) 후 dataset 별 슬라이스.
    daily 도 동일 (2025-01 ~ 2026-04, MACD warm-up 충분).

    Returns:
        {"fold1": Dataset, "fold2": Dataset, "fold3": Dataset, "oos": Dataset}
    """
    # 1. universe — Stage 2 캐시 재사용
    universe = select_top_universe(
        fold_train_start="20250301",
        fold_test_end="20260228",
        n_stocks=30,
        min_days_present=120,
    )

    # 2. 광역 로드 (1회)
    minute_start = STAGE2_FOLDS[0].test_start  # 20250901 — fold1 시작
    minute_end = OOS_TEST_END                    # 20260424
    daily_start = "20250101"

    print(f"[load_all_datasets] universe={len(universe)}, "
          f"minute {minute_start}~{minute_end}, daily {daily_start}~{minute_end}")

    minute_df = load_minute_df(universe, minute_start, minute_end)
    daily_df = load_daily_df(universe, daily_start, minute_end)

    # 3. 종목별 dict
    minute_full = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_full = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }

    # 4. dataset 4개 만들기
    datasets: Dict[str, Dataset] = {}
    fold_specs = [
        ("fold1", STAGE2_FOLDS[0].test_start, STAGE2_FOLDS[0].test_end),
        ("fold2", STAGE2_FOLDS[1].test_start, STAGE2_FOLDS[1].test_end),
        ("fold3", STAGE2_FOLDS[2].test_start, STAGE2_FOLDS[2].test_end),
        ("oos", OOS_TEST_START, OOS_TEST_END),
    ]
    for name, start, end in fold_specs:
        m_by = {
            c: minute_full[c][
                (minute_full[c]["trade_date"] >= start)
                & (minute_full[c]["trade_date"] <= end)
            ].reset_index(drop=True)
            for c in universe
        }
        # daily 는 warm-up 위해 dataset 시작일 이전 모두 포함
        d_by = {
            c: daily_full[c][daily_full[c]["trade_date"] <= end].reset_index(drop=True)
            for c in universe
        }
        nonempty = [c for c in universe if len(m_by[c]) > 0]
        datasets[name] = Dataset(
            name=name,
            minute_start=start, minute_end=end,
            daily_start=daily_start,
            minute_by_code={c: m_by[c] for c in nonempty},
            daily_by_code={c: d_by[c] for c in nonempty},
            universe=nonempty,
        )
        print(f"  {name}: {start}~{end}, "
              f"{len(nonempty)}/{len(universe)} stocks, "
              f"{_trading_days_count(m_by)} trading days")

    # 신규: KOSPI 일봉 1회 로드 (모든 dataset 공유)
    from backtests.common.data_loader import load_index_df
    kospi_raw = load_index_df("KS11", daily_start, minute_end)
    kospi_norm = pd.DataFrame({
        "trade_date": kospi_raw["trade_date"].astype(str),
        "close": kospi_raw["close"].astype(float),
    }).sort_values("trade_date").reset_index(drop=True)

    for ds_name in datasets:
        datasets[ds_name].kospi_daily_df = kospi_norm

    return datasets


def evaluate_cell(
    strategy: StrategyBase,
    dataset: Dataset,
    initial_capital: float = 10_000_000,
) -> Dict[str, float]:
    """단일 cell × dataset 평가. engine 실행 + KPI 빌드.

    Returns:
        build_cell_kpis 와 동일 dict.
    """
    eng = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        universe=dataset.universe,
        minute_df_by_code=dataset.minute_by_code,
        daily_df_by_code=dataset.daily_by_code,
    )
    result = eng.run()
    trading_days = _trading_days_count(dataset.minute_by_code)
    return build_cell_kpis(
        equity=result.equity_curve,
        trades=result.trades,
        trading_days=trading_days,
    )
