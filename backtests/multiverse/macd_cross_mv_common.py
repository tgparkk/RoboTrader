"""macd_cross 멀티버스 공통 유틸 — KPI extras, dataset 로더, cell evaluator."""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

import pandas as pd

from backtests.common.metrics import (
    compute_calmar,
    compute_max_drawdown,
    compute_win_rate,
)


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
