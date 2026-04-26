"""엔진 핫패스 프로파일 — prepare_features vs main loop 시간 분리."""
import cProfile
import pstats
import time

from backtests.common.engine import BacktestEngine
from backtests.strategies.volume_surge import VolumeSurgeStrategy
from backtests.benchmark_engine import _generate_synthetic_data


def profile_run():
    minute_by_code, daily_by_code = _generate_synthetic_data(30, 22)
    universe = list(minute_by_code.keys())
    strategy = VolumeSurgeStrategy()

    # prepare_features 측정 (engine.run() 시작 후 전 단계)
    t0 = time.perf_counter()
    feats = {
        c: strategy.prepare_features(minute_by_code[c], daily_by_code[c])
        for c in universe
    }
    t_prep = time.perf_counter() - t0

    # engine.run 전체 측정
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=100_000_000,
        universe=universe,
        minute_df_by_code=minute_by_code,
        daily_df_by_code=daily_by_code,
    )
    t0 = time.perf_counter()
    profiler = cProfile.Profile()
    profiler.enable()
    result = engine.run()
    profiler.disable()
    t_total = time.perf_counter() - t0

    print(f"prepare_features (외부 측정): {t_prep:.2f}s")
    print(f"engine.run (전체): {t_total:.2f}s")
    print(f"main loop estimated: {t_total - t_prep:.2f}s")
    print(f"trades: {len(result.trades)}\n")

    print("--- cProfile top 20 by cumtime ---")
    stats = pstats.Stats(profiler).sort_stats("cumulative")
    stats.print_stats(20)


if __name__ == "__main__":
    profile_run()
