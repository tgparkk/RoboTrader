"""엔진 속도 벤치마크 — 합성 데이터로 전략별 실행 시간 측정.

DB 의존 없이 합성 분봉 + 일봉 생성, 각 전략에 대해 BacktestEngine.run() 실행 시간 측정.
"""
import time
from typing import Dict, List

import numpy as np
import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.strategies.orb import ORBStrategy
from backtests.strategies.gap_down_reversal import GapDownReversalStrategy
from backtests.strategies.gap_up_chase import GapUpChaseStrategy
from backtests.strategies.vwap_bounce import VWAPBounceStrategy
from backtests.strategies.bb_lower_bounce import BBLowerBounceStrategy
from backtests.strategies.rsi_oversold import RSIOversoldStrategy
from backtests.strategies.volume_surge import VolumeSurgeStrategy
from backtests.strategies.intraday_pullback import IntradayPullbackStrategy
from backtests.strategies.closing_drift import ClosingDriftStrategy
from backtests.strategies.limit_up_chase import LimitUpChaseStrategy
from backtests.strategies.close_to_open import CloseToOpenStrategy
from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.post_drop_rebound import PostDropReboundStrategy
from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy
from backtests.strategies.macd_cross import MACDCrossStrategy


N_STOCKS = 30
N_DAYS = 22
BARS_PER_DAY = 390


def _generate_synthetic_data(n_stocks: int, n_days: int):
    """무작위 walk 분봉 + 일봉 생성. 각 종목은 독립 random seed."""
    rng = np.random.default_rng(42)
    minute_by_code: Dict[str, pd.DataFrame] = {}
    daily_by_code: Dict[str, pd.DataFrame] = {}

    base_dates = pd.bdate_range("20260101", periods=n_days + 30).strftime("%Y%m%d")
    history_dates = list(base_dates[:30])
    target_dates = list(base_dates[30:30 + n_days])

    for s in range(n_stocks):
        code = f"S{s:04d}"
        # 분봉 (target_dates 만)
        rows = []
        base_price = 10000.0 + s * 100
        for td in target_dates:
            day_open = base_price * (1 + rng.normal(0, 0.005))
            close = day_open
            for i in range(BARS_PER_DAY):
                hh = 9 + i // 60
                mm = i % 60
                close *= (1 + rng.normal(0, 0.0008))
                rows.append({
                    "stock_code": code,
                    "trade_date": td,
                    "trade_time": f"{hh:02d}{mm:02d}00",
                    "open": close * (1 + rng.normal(0, 0.0002)),
                    "high": close * (1 + abs(rng.normal(0, 0.0005))),
                    "low": close * (1 - abs(rng.normal(0, 0.0005))),
                    "close": close,
                    "volume": float(rng.integers(500, 5000)),
                })
        minute_by_code[code] = pd.DataFrame(rows)

        # 일봉 (history_dates + target_dates)
        drows = []
        d_close = base_price
        for d in history_dates + target_dates:
            d_open = d_close
            d_close = d_open * (1 + rng.normal(0, 0.015))
            drows.append({
                "stock_code": code,
                "trade_date": d,
                "open": d_open,
                "high": max(d_open, d_close) * (1 + abs(rng.normal(0, 0.005))),
                "low": min(d_open, d_close) * (1 - abs(rng.normal(0, 0.005))),
                "close": d_close,
                "volume": float(rng.integers(50_000, 500_000)),
            })
        daily_by_code[code] = pd.DataFrame(drows)

    return minute_by_code, daily_by_code


def benchmark_strategy(name: str, strategy, minute_by_code, daily_by_code, universe):
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=100_000_000,
        universe=universe,
        minute_df_by_code=minute_by_code,
        daily_df_by_code=daily_by_code,
    )
    t0 = time.perf_counter()
    result = engine.run()
    elapsed = time.perf_counter() - t0
    n_trades = len(result.trades)
    return elapsed, n_trades


def main():
    print(f"Generating synthetic data: {N_STOCKS} stocks × {N_DAYS} days × "
          f"{BARS_PER_DAY} bars = {N_STOCKS * N_DAYS * BARS_PER_DAY:,} bars")
    minute_by_code, daily_by_code = _generate_synthetic_data(N_STOCKS, N_DAYS)
    universe = list(minute_by_code.keys())
    print(f"Generated {sum(len(df) for df in minute_by_code.values()):,} minute rows")

    strategies = [
        ("orb", ORBStrategy()),
        ("gap_down_reversal", GapDownReversalStrategy()),
        ("gap_up_chase", GapUpChaseStrategy()),
        ("vwap_bounce", VWAPBounceStrategy()),
        ("bb_lower_bounce", BBLowerBounceStrategy()),
        ("rsi_oversold", RSIOversoldStrategy()),
        ("volume_surge", VolumeSurgeStrategy()),
        ("intraday_pullback", IntradayPullbackStrategy()),
        ("closing_drift", ClosingDriftStrategy()),
        ("limit_up_chase", LimitUpChaseStrategy()),
        ("close_to_open", CloseToOpenStrategy()),
        ("breakout_52w", Breakout52wStrategy()),
        ("post_drop_rebound", PostDropReboundStrategy()),
        ("trend_followthrough", TrendFollowthroughStrategy()),
        ("macd_cross", MACDCrossStrategy()),
    ]

    print(f"\n{'strategy':<22} {'elapsed':>10} {'trades':>8}")
    print("-" * 44)
    results = []
    for name, strat in strategies:
        elapsed, n_trades = benchmark_strategy(
            name, strat, minute_by_code, daily_by_code, universe
        )
        print(f"{name:<22} {elapsed:>9.2f}s {n_trades:>8}")
        results.append((name, elapsed, n_trades))

    total = sum(e for _, e, _ in results)
    print(f"\nTotal: {total:.1f}s")
    print(f"Avg per strategy: {total/len(results):.1f}s")
    # Phase 3 추정: 200 trials × 15 strategies = 3,000 runs
    # 단, 각 trial 은 다른 파라미터 → 다른 entry/exit 빈도
    print(f"\nPhase 3 추정 (200 trials × {len(results)} strategies): "
          f"{total * 200:.0f}s = {total * 200 / 3600:.1f}h")


if __name__ == "__main__":
    main()
