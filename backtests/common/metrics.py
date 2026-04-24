"""성과 지표 계산 — Calmar·Sharpe·MDD·PF·Win%."""
import math
from typing import Dict

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252


def compute_max_drawdown(equity: pd.Series) -> float:
    """최대 낙폭. 음수 또는 0 반환."""
    if len(equity) < 2:
        return 0.0
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return float(drawdown.min())


def compute_sharpe(daily_returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """연환산 Sharpe ratio. 일별 수익률 시리즈 입력."""
    if len(daily_returns) < 2:
        return 0.0
    excess = daily_returns - risk_free_rate / TRADING_DAYS_PER_YEAR
    std = excess.std(ddof=1)
    if std == 0 or math.isnan(std):
        return 0.0
    return float(excess.mean() / std * math.sqrt(TRADING_DAYS_PER_YEAR))


def compute_calmar(equity: pd.Series, trading_days: int) -> float:
    """연환산 수익률 / |MDD|. MDD=0 시 NaN."""
    if len(equity) < 2 or trading_days <= 0:
        return float("nan")
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    annualized = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / trading_days) - 1
    mdd = compute_max_drawdown(equity)
    if mdd == 0.0:
        return float("nan")
    return float(annualized / abs(mdd))


def compute_profit_factor(trade_pnls: pd.Series) -> float:
    """수익 합 / 손실 절대합. 손실 없으면 +inf."""
    if len(trade_pnls) == 0:
        return float("nan")
    profits = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    if losses == 0:
        return float("inf") if profits > 0 else float("nan")
    return float(profits / losses)


def compute_win_rate(trade_pnls: pd.Series) -> float:
    """승률 = 수익 거래 / 전체 거래."""
    if len(trade_pnls) == 0:
        return 0.0
    wins = (trade_pnls > 0).sum()
    return float(wins / len(trade_pnls))


def compute_all_metrics(
    equity: pd.Series,
    trade_pnls: pd.Series,
    trading_days: int,
) -> Dict[str, float]:
    """모든 지표를 한 번에 계산해 딕셔너리로 반환."""
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) >= 2 else 0.0
    daily_returns = equity.pct_change().dropna()
    return {
        "calmar": compute_calmar(equity, trading_days),
        "sharpe": compute_sharpe(daily_returns),
        "mdd": compute_max_drawdown(equity),
        "profit_factor": compute_profit_factor(trade_pnls),
        "win_rate": compute_win_rate(trade_pnls),
        "total_trades": int(len(trade_pnls)),
        "total_return": total_return,
    }
