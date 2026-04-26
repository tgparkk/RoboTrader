"""Stage 1 인프라 smoke run — 1 전략 × 5 trials on 5 stocks.

목적: end-to-end 동작 검증 (sample → run → gates → save).
실제 Stage 1 (200 trials) 은 별도 스크립트.
"""
import time
from pathlib import Path

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import SMOKE_FOLD, Fold
from backtests.multiverse.stage1_coarse import (
    run_stage1_for_strategy, save_trials, summarize_trials,
)
from backtests.strategies.volume_surge import VolumeSurgeStrategy
from backtests.strategies.vwap_bounce import VWAPBounceStrategy
from backtests.strategies.intraday_pullback import IntradayPullbackStrategy


UNIVERSE = ["005930", "000660", "035720", "035420", "068270"]
N_TRIALS = 5


def main():
    fold = Fold(
        name="smoke",
        train_start="20260101",
        train_end="20260228",
        test_start="20260301",
        test_end="20260331",
        universe=UNIVERSE,
    )
    print(f"Fold: train {fold.train_start}~{fold.train_end}, "
          f"test {fold.test_start}~{fold.test_end}, "
          f"universe={UNIVERSE}, trials={N_TRIALS}")

    # 데이터 로드 (한 번만)
    t0 = time.perf_counter()
    minute_df = load_minute_df(UNIVERSE, fold.train_start, fold.test_end)
    daily_df = load_daily_df(UNIVERSE, fold.daily_history_start, fold.test_end)
    print(f"loaded in {time.perf_counter()-t0:.1f}s "
          f"minute={len(minute_df):,} daily={len(daily_df):,}")
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in UNIVERSE
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in UNIVERSE
    }

    out_dir = Path("backtests/reports/stage1_smoke")
    strategies = [
        VolumeSurgeStrategy,
        VWAPBounceStrategy,
        IntradayPullbackStrategy,
    ]

    print(f"\n{'strategy':<22} {'trials':>7} {'pass':>5} "
          f"{'best_calmar':>12} {'best_return':>12} {'best_trades':>12} {'elapsed':>9}")
    print("-" * 85)

    for strat_cls in strategies:
        t0 = time.perf_counter()
        results = run_stage1_for_strategy(
            strategy_class=strat_cls,
            fold=fold,
            n_trials=N_TRIALS,
            seed=42,
            minute_by_code=minute_by_code,
            daily_by_code=daily_by_code,
        )
        elapsed = time.perf_counter() - t0
        summary = summarize_trials(results)
        out_path = out_dir / f"{strat_cls.name}_trials.csv"
        save_trials(results, out_path)
        bp = summary.get("best_calmar")
        br = summary.get("best_test_return")
        bt = summary.get("best_test_trades")
        print(
            f"{strat_cls.name:<22} {summary['n_trials']:>7d} {summary['n_pass']:>5d} "
            f"{bp if bp is None else f'{bp:>12.2f}':>12} "
            f"{br if br is None else f'{br:>12.2%}':>12} "
            f"{bt:>12d} "
            f"{elapsed:>8.1f}s"
        )

    print(f"\nResults saved to {out_dir}/")


if __name__ == "__main__":
    main()
