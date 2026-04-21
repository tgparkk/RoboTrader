"""메트릭 수식 손계산 검증.

실행:
    python -m analysis.research.weighted_score.tests.test_metrics
"""
from __future__ import annotations

import math
import sys

import numpy as np
import pandas as pd

from analysis.research.weighted_score.sim import cost_model, metrics


def _check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[ok]   {msg}")


def _approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def test_cost_model() -> None:
    cm = cost_model.CostModel(one_way_pct=0.28)
    _check(_approx(cm.round_trip_pct, 0.56), "round_trip_pct = 2 * 0.28")
    _check(_approx(cm.apply_round_trip(10.0), 10.0 - 0.56), "10% gross → net 9.44%")
    _check(_approx(cm.apply_one_way(3.0), 3.0 - 0.28), "3% gross one-way → 2.72%")

    # fill adjusted: 1000 * (1 + 0.0028) = 1002.8
    entry = cm.entry_fill_adjusted(1000.0)
    exit_ = cm.exit_fill_adjusted(1000.0)
    _check(_approx(entry, 1002.8, tol=1e-6), "entry fill: 1000 → 1002.80")
    _check(_approx(exit_, 997.2, tol=1e-6), "exit fill: 1000 → 997.20")


def test_mdd_basic() -> None:
    # 자본곡선: 100 → 110 → 90 → 120 → 80
    # 러닝 최대: 100, 110, 110, 120, 120
    # 드로우다운: 0, 0, (110-90)/110=0.1818, 0, (120-80)/120=0.3333
    # MDD = 0.3333
    eq = pd.Series([100.0, 110.0, 90.0, 120.0, 80.0])
    mdd = metrics.compute_mdd(eq)
    _check(_approx(mdd, 1.0 / 3.0, tol=1e-6), f"MDD [100,110,90,120,80] = 1/3 (actual={mdd:.6f})")


def test_mdd_monotonic() -> None:
    eq = pd.Series([100.0, 110.0, 120.0, 130.0])
    _check(metrics.compute_mdd(eq) == 0.0, "monotonic up MDD = 0")

    eq2 = pd.Series([100.0, 80.0, 60.0, 40.0])
    # 러닝 최대 = 100, 드로우다운 = 0, 0.2, 0.4, 0.6 → MDD = 0.6
    _check(_approx(metrics.compute_mdd(eq2), 0.6), "monotonic down MDD = 0.6")


def test_sharpe_zero_variance() -> None:
    rets = pd.Series([0.001, 0.001, 0.001, 0.001])
    s = metrics.compute_sharpe(rets)
    _check(s == 0.0, "constant daily returns → Sharpe = 0 (by convention)")


def test_sharpe_known() -> None:
    # 일간 수익률 평균 0.001, std 0.01 → Sharpe = 0.001/0.01 * sqrt(252) = 0.1 * 15.8745 ≈ 1.587
    rng = np.random.default_rng(42)
    # 정확한 평균/표준편차를 위해 수동 구성
    rets = pd.Series([0.001, 0.011, -0.009, 0.001, 0.011, -0.009])  # mean=0.001, ddof=1
    # 수식: mean=0.001, std_ddof1 = sqrt(sum((r-mean)^2)/(n-1))
    mean = rets.mean()
    std = rets.std(ddof=1)
    expected = mean / std * math.sqrt(252)
    actual = metrics.compute_sharpe(rets)
    _check(_approx(actual, expected, tol=1e-9), f"Sharpe 수식 일치 (expected={expected:.6f})")


def test_annualized_return() -> None:
    # 252영업일 동안 +10% → 연율 10%
    eq = pd.Series([100.0] * 252)
    eq.iloc[-1] = 110.0
    ann = metrics.compute_annualized_return(eq)
    _check(_approx(ann, 0.10, tol=1e-3), f"1년 +10% → 연 10% (actual={ann:.4f})")

    # 126영업일(=0.5년) 동안 +10% → 연율 ≈ 21%
    eq2 = pd.Series([100.0] * 126)
    eq2.iloc[-1] = 110.0
    ann2 = metrics.compute_annualized_return(eq2)
    expected2 = 1.10 ** (252.0 / 126.0) - 1.0  # = 0.21
    _check(_approx(ann2, expected2, tol=1e-6), f"0.5년 +10% → 연 {expected2:.4f}")


def test_calmar_known() -> None:
    # 252일 동안 100 → 150 (가운데 120까지 갔다가 108 내려갔다가 150 도달)
    # MDD = (120 - 108)/120 = 0.1
    # 연수익률 = 0.5
    # Calmar = 0.5 / 0.1 = 5.0
    days = 252
    eq = pd.Series([100.0] * days, dtype=float)
    # 앞부분 120 peak
    eq.iloc[0:100] = np.linspace(100.0, 120.0, 100)
    eq.iloc[100:150] = np.linspace(120.0, 108.0, 50)  # 120 → 108 drawdown 10%
    eq.iloc[150:] = np.linspace(108.0, 150.0, days - 150)

    m = metrics.metrics_from_equity(eq)
    _check(_approx(m.mdd, 0.1, tol=1e-6), f"MDD = 10% (actual={m.mdd:.6f})")
    _check(_approx(m.total_return, 0.5, tol=1e-6), f"총 수익률 50% (actual={m.total_return:.6f})")
    # annualized with n_days=252 → (1.5)^(252/252) - 1 = 0.5
    _check(_approx(m.annualized_return, 0.5, tol=1e-6), f"연수익률 50%")
    _check(_approx(m.calmar, 5.0, tol=1e-6), f"Calmar 5.0 (actual={m.calmar:.6f})")


def test_realized_equity_curve() -> None:
    # 3 거래, 동일 size 1M, 수익률 [+2%, -1%, +3%]
    # pnl: [20,000, -10,000, 30,000] 누적 [20k, 10k, 40k]
    # 초기 자본 1M (prefix) → 1.02M → 1.01M → 1.04M
    trades = pd.DataFrame({
        "exit_date": ["20250501", "20250502", "20250503"],
        "net_pct": [2.0, -1.0, 3.0],
    })
    eq = metrics.realized_equity_curve(trades, initial_capital=1_000_000, size_krw=1_000_000)
    _check(len(eq) == 4, f"start prefix + 3거래일 = 4개 (actual={len(eq)})")
    _check(_approx(eq.iloc[0], 1_000_000), "prefix = 초기자본 1M")
    _check(_approx(eq.iloc[1], 1_020_000), "1거래 후 1.02M")
    _check(_approx(eq.iloc[2], 1_010_000), "2거래 후 1.01M")
    _check(_approx(eq.iloc[3], 1_040_000), "3거래 후 1.04M")


def test_metrics_from_trades_end_to_end() -> None:
    trades = pd.DataFrame({
        "exit_date": ["20250501", "20250502", "20250503", "20250504"],
        "net_pct": [2.0, -1.0, 3.0, -0.5],
    })
    m = metrics.metrics_from_trades(trades, initial_capital=1_000_000, size_krw=1_000_000)
    _check(m.n_trades == 4, f"n_trades=4 (actual={m.n_trades})")
    _check(_approx(m.win_rate, 0.5), f"win_rate = 50% (actual={m.win_rate})")
    _check(_approx(m.avg_trade_pct, (2 - 1 + 3 - 0.5) / 4), "avg_trade_pct = 0.875%")
    # total return = 1.035M / 1M - 1 = 0.035
    _check(_approx(m.total_return, 0.035, tol=1e-9), f"total_return 0.035 (actual={m.total_return})")


def main() -> None:
    print("\n=== cost_model ===")
    test_cost_model()

    print("\n=== MDD basic ===")
    test_mdd_basic()

    print("\n=== MDD monotonic ===")
    test_mdd_monotonic()

    print("\n=== Sharpe ===")
    test_sharpe_zero_variance()
    test_sharpe_known()

    print("\n=== Annualized return ===")
    test_annualized_return()

    print("\n=== Calmar (end-to-end) ===")
    test_calmar_known()

    print("\n=== Realized equity curve ===")
    test_realized_equity_curve()

    print("\n=== Metrics from trades ===")
    test_metrics_from_trades_end_to_end()

    print("\n[SUCCESS] Step 4 메트릭/비용 단위 테스트 통과")


if __name__ == "__main__":
    main()
