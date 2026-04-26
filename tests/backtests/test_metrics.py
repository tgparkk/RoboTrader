"""backtests.common.metrics 단위 테스트."""
import math

import numpy as np
import pandas as pd
import pytest

from backtests.common.metrics import (
    compute_calmar,
    compute_sharpe,
    compute_max_drawdown,
    compute_profit_factor,
    compute_win_rate,
    compute_all_metrics,
)


def test_max_drawdown_simple():
    # 100 → 120 → 80 → 150. Peak=120 에서 80 으로 떨어짐 = (80-120)/120 = -33.33%
    equity = pd.Series([100, 120, 80, 150])
    mdd = compute_max_drawdown(equity)
    assert math.isclose(mdd, -0.3333, abs_tol=1e-3)


def test_max_drawdown_no_drawdown():
    equity = pd.Series([100, 110, 120, 130])
    assert compute_max_drawdown(equity) == 0.0


def test_sharpe_basic():
    # 일간 수익률 평균 0.001, 표준편차 0.01 → 연환산 Sharpe = 0.001/0.01 * sqrt(252)
    returns = pd.Series([0.001] * 100 + [-0.001] * 100)  # 평균 0, 절대값 0.001
    # 실제로는 평균 0 이라 Sharpe ≈ 0
    sharpe = compute_sharpe(returns)
    assert abs(sharpe) < 0.1


def test_sharpe_positive_drift():
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.001, 0.01, 252))
    sharpe = compute_sharpe(returns)
    # 연 252일, 기대값 0.001 × 252 = 25% 수익, std 0.01×sqrt(252) ≈ 15.8% → Sharpe ≈ 1.58
    assert 1.0 < sharpe < 2.5


def test_calmar_positive():
    # equity 가 단조증가면 MDD=0 이라 Calmar=NaN. 중간에 drawdown 넣어야 함
    equity = pd.Series([100, 105, 102, 108, 105, 110])  # MDD ≈ -2.86% (105→102)
    calmar = compute_calmar(equity, trading_days=6)
    # 양수이고 합리적 범위
    assert calmar > 0


def test_calmar_zero_mdd_is_nan():
    """MDD 가 0이면 정의 불가 → NaN 반환 (inf 대신)."""
    equity = pd.Series([100, 110, 120])
    calmar = compute_calmar(equity, trading_days=3)
    assert math.isnan(calmar)


def test_profit_factor_basic():
    # 수익 거래 합 200, 손실 거래 합 -100 → PF = 2.0
    trade_pnls = pd.Series([100, 50, 50, -40, -60])
    pf = compute_profit_factor(trade_pnls)
    assert math.isclose(pf, 2.0, abs_tol=1e-6)


def test_profit_factor_no_losses():
    trade_pnls = pd.Series([100, 50, 30])
    pf = compute_profit_factor(trade_pnls)
    assert math.isinf(pf)


def test_win_rate_basic():
    trade_pnls = pd.Series([100, -50, 30, -20, 10])
    # 3승 2패 → 60%
    assert compute_win_rate(trade_pnls) == 0.6


def test_win_rate_empty():
    assert compute_win_rate(pd.Series([], dtype=float)) == 0.0


def test_compute_all_metrics_returns_dict():
    equity = pd.Series([100, 105, 102, 108, 105, 110])
    trade_pnls = pd.Series([5, -3, 6, -3, 5])
    m = compute_all_metrics(equity, trade_pnls, trading_days=6)
    assert set(m.keys()) >= {
        "calmar", "sharpe", "mdd", "profit_factor",
        "win_rate", "total_trades", "total_return",
    }
    assert m["total_trades"] == 5
    assert math.isclose(m["total_return"], 0.10, abs_tol=1e-6)
