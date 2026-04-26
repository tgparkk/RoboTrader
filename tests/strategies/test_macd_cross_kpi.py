"""macd_cross KPI 집계 + 6 게이트 평가 테스트."""
import pandas as pd
import pytest

from core.strategies.macd_cross_kpi import MacdCrossKpi


def _trades(pnls):
    """편의 함수: pnl 시퀀스 → trade rows."""
    return pd.DataFrame({
        "buy_time": pd.date_range("2026-04-01", periods=len(pnls), freq="D"),
        "sell_time": pd.date_range("2026-04-02", periods=len(pnls), freq="D"),
        "pnl": pnls,
    })


def test_empty_trades_returns_zero_metrics():
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([]))
    assert m["trade_count"] == 0
    assert m["return"] == 0.0


def test_metrics_basic():
    """5 trades, 3승 2패, 단순 합산 검증."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([100_000, -50_000, 200_000, -30_000, 80_000]))
    assert m["trade_count"] == 5
    assert m["win_rate"] == pytest.approx(3 / 5)
    assert m["return"] == pytest.approx((100_000 - 50_000 + 200_000 - 30_000 + 80_000) / 10_000_000)
    assert m["max_consec_losses"] == 1


def test_top1_share_calculation():
    """최대 winner 가 net pnl 점유율 계산."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([100, 200, 50, 1000, -50]))
    # net = 1300, top1 = 1000 → share = 1000/1300
    assert m["top1_share"] == pytest.approx(1000 / 1300, rel=1e-6)


def test_max_consec_losses_streak():
    """3연속 손실 streak 검증."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([100, -50, -30, -20, 40]))
    assert m["max_consec_losses"] == 3


def test_gate_pass_all():
    """모든 게이트 통과 케이스."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = {
        "calmar": 35,
        "return": 0.05,
        "mdd": -0.02,  # 2%
        "win_rate": 0.55,
        "top1_share": 0.50,
        "max_consec_losses": 3,
    }
    result = k.evaluate_gates(m)
    assert result["all_pass"] is True
    assert all(v["pass"] for v in result["gates"].values())


def test_gate_fail_calmar():
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = {
        "calmar": 25,  # < 30 fails
        "return": 0.05, "mdd": -0.02, "win_rate": 0.55,
        "top1_share": 0.50, "max_consec_losses": 3,
    }
    result = k.evaluate_gates(m)
    assert result["all_pass"] is False
    assert result["gates"]["calmar"]["pass"] is False


def test_safety_stop_cumulative_loss():
    """누적 -5% 도달 시 safety stop True."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    assert k.should_safety_stop({"return": -0.06, "max_consec_losses": 2}) is True
    assert k.should_safety_stop({"return": -0.04, "max_consec_losses": 2}) is False


def test_safety_stop_consec_losses():
    """연속 5패 도달 시 safety stop True."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    assert k.should_safety_stop({"return": -0.02, "max_consec_losses": 5}) is True
    assert k.should_safety_stop({"return": -0.02, "max_consec_losses": 4}) is False
