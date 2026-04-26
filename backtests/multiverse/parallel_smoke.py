"""Stage 1 parallel infrastructure smoke — Windows multiprocessing 검증.

20 trials × volume_surge × 4 workers on 5 stocks.
Sequential vs parallel 시간 비교.
"""
import time

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import Fold
from backtests.multiverse.stage1_parallel import run_stage1_parallel
from backtests.multiverse.stage1_coarse import summarize_trials
from backtests.strategies.volume_surge import VolumeSurgeStrategy


UNIVERSE = ["005930", "000660", "035720", "035420", "068270"]


def main():
    fold = Fold(
        name="smoke",
        train_start="20260101",
        train_end="20260228",
        test_start="20260301",
        test_end="20260331",
        universe=UNIVERSE,
    )
    minute_df = load_minute_df(UNIVERSE, fold.train_start, fold.test_end)
    daily_df = load_daily_df(UNIVERSE, fold.daily_history_start, fold.test_end)
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in UNIVERSE
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in UNIVERSE
    }
    print(f"loaded minute={len(minute_df):,} daily={len(daily_df):,}")

    n_trials = 20

    # Sequential baseline
    t0 = time.perf_counter()
    seq = run_stage1_parallel(
        VolumeSurgeStrategy, fold, n_trials=n_trials, n_workers=1, seed=42,
        minute_by_code=minute_by_code, daily_by_code=daily_by_code,
    )
    t_seq = time.perf_counter() - t0
    print(f"\n[sequential 1 worker] {n_trials} trials = {t_seq:.1f}s "
          f"({t_seq/n_trials:.2f}s/trial)")

    # Parallel 4 workers
    t0 = time.perf_counter()
    par = run_stage1_parallel(
        VolumeSurgeStrategy, fold, n_trials=n_trials, n_workers=4, seed=42,
        minute_by_code=minute_by_code, daily_by_code=daily_by_code,
    )
    t_par = time.perf_counter() - t0
    print(f"[parallel 4 workers] {n_trials} trials = {t_par:.1f}s "
          f"({t_par/n_trials:.2f}s/trial) speedup {t_seq/t_par:.1f}x")

    # 동일성 확인 (같은 seed → 같은 trial params → 같은 결과)
    seq_calmars = [r.test_metrics.get("calmar", float("nan")) for r in seq]
    par_calmars = [r.test_metrics.get("calmar", float("nan")) for r in par]
    eq = all(
        (s == p) or (s != s and p != p)  # NaN match
        for s, p in zip(seq_calmars, par_calmars)
    )
    print(f"[determinism] seq vs par results identical: {eq}")
    print(f"[summary] {summarize_trials(par)}")


if __name__ == "__main__":
    main()
