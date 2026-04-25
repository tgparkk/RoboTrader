"""Stage 2 orchestrator — Stage 1 통과 전략에 대해 Optuna TPE 1000 trials × 3 fold.

CLI:
  python -m backtests.multiverse.run_stage2 --strategies macd_cross,close_to_open
  python -m backtests.multiverse.run_stage2 --strategies all --n-trials 1000

기본: Stage 1 v2 통과 전략 자동 선정 (n_pass > 0).
"""
import argparse
import time
from pathlib import Path
from typing import List, Type

import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import STAGE2_FOLDS, stage2_data_range
from backtests.multiverse.stage2_fine import run_stage2_for_strategy
from backtests.multiverse.stage2_parallel import run_stage2_parallel
from backtests.multiverse.universe import select_top_universe
from backtests.strategies.base import StrategyBase
# 모든 전략 import
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


STRATEGY_MAP = {
    s.name: s for s in [
        ORBStrategy, GapDownReversalStrategy, GapUpChaseStrategy,
        VWAPBounceStrategy, BBLowerBounceStrategy, RSIOversoldStrategy,
        VolumeSurgeStrategy, IntradayPullbackStrategy, ClosingDriftStrategy,
        LimitUpChaseStrategy, CloseToOpenStrategy, Breakout52wStrategy,
        PostDropReboundStrategy, TrendFollowthroughStrategy, MACDCrossStrategy,
    ]
}


def auto_select_candidates(stage1_dir: Path) -> List[str]:
    """Stage 1 v2 통과 trial 이 있는 전략 자동 선정."""
    summary_path = stage1_dir / "regate_summary.csv"
    if not summary_path.exists():
        return []
    df = pd.read_csv(summary_path)
    return df[df["v2_pass"] > 0]["strategy"].tolist()


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--strategies", default="auto",
                   help="comma-separated names, 'all', or 'auto' (Stage 1 v2 pass)")
    p.add_argument("--n-trials", type=int, default=1000)
    p.add_argument("--n-workers", type=int, default=1,
                   help="Optuna sqlite-shared workers (1=sequential, 8=full parallel)")
    p.add_argument("--universe-size", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--stage1-dir", default="backtests/reports/stage1/fold1")
    return p.parse_args()


def main():
    args = parse_args()

    if args.strategies == "auto":
        names = auto_select_candidates(Path(args.stage1_dir))
        print(f"Auto-selected {len(names)} strategies from Stage 1 v2: {names}")
    elif args.strategies == "all":
        names = list(STRATEGY_MAP.keys())
    else:
        names = [n.strip() for n in args.strategies.split(",")]

    strategies = [STRATEGY_MAP[n] for n in names if n in STRATEGY_MAP]
    if not strategies:
        print("No strategies selected — exit")
        return

    print(f"=== Stage 2 Fine Search ===")
    print(f"Strategies: {[s.name for s in strategies]}")
    print(f"Trials/strategy: {args.n_trials}")
    print(f"Folds: {[f.name for f in STAGE2_FOLDS]}")
    for f in STAGE2_FOLDS:
        print(f"  {f.name}: train {f.train_start}~{f.train_end} "
              f"test {f.test_start}~{f.test_end}")

    # Universe
    print(f"\nSelecting top-{args.universe_size} universe (Fold 1 train start ~ Fold 3 test end)...")
    d_start, d_end = stage2_data_range()
    universe = select_top_universe(
        fold_train_start=d_start, fold_test_end=d_end,
        n_stocks=args.universe_size,
        min_days_present=120,
    )
    print(f"Universe: {universe}")

    # 데이터 한 번 로드
    daily_history_start = f"{int(d_start[:4]) - 1}{d_start[4:]}"
    t0 = time.perf_counter()
    minute_df = load_minute_df(universe, d_start, d_end)
    daily_df = load_daily_df(universe, daily_history_start, d_end)
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    print(f"Loaded {len(minute_df):,} minute / {len(daily_df):,} daily rows in {time.perf_counter()-t0:.1f}s")

    out_dir = Path("backtests/reports/stage2")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for strat_cls in strategies:
        print(f"\n--- {strat_cls.name} ---")
        t0 = time.perf_counter()
        if args.n_workers <= 1:
            study = run_stage2_for_strategy(
                strategy_class=strat_cls,
                n_trials=args.n_trials,
                seed=args.seed,
                folds=STAGE2_FOLDS,
                minute_by_code=minute_by_code,
                daily_by_code=daily_by_code,
                storage_dir=out_dir,
            )
        else:
            study = run_stage2_parallel(
                strategy_class=strat_cls,
                n_trials=args.n_trials,
                n_workers=args.n_workers,
                seed=args.seed,
                folds=STAGE2_FOLDS,
                minute_by_code=minute_by_code,
                daily_by_code=daily_by_code,
                storage_dir=out_dir,
            )
        elapsed = time.perf_counter() - t0
        valid = [t for t in study.trials if t.value and t.value > -1e5]
        if valid:
            best = max(valid, key=lambda t: t.value)
            print(f"  best Calmar (3-fold avg) = {best.value:.2f}  "
                  f"valid trials = {len(valid)}/{args.n_trials}  "
                  f"elapsed = {elapsed:.0f}s")
            summary.append({
                "strategy": strat_cls.name,
                "best_avg_calmar": best.value,
                "n_valid": len(valid),
                "n_trials": len(study.trials),
                "elapsed_s": round(elapsed, 1),
            })
        else:
            print(f"  no valid trials  elapsed = {elapsed:.0f}s")
            summary.append({
                "strategy": strat_cls.name,
                "best_avg_calmar": float("nan"),
                "n_valid": 0,
                "n_trials": len(study.trials),
                "elapsed_s": round(elapsed, 1),
            })

    s_df = pd.DataFrame(summary).sort_values("best_avg_calmar", ascending=False)
    s_df.to_csv(out_dir / "summary.csv", index=False)
    print(f"\n=== Summary saved to {out_dir / 'summary.csv'} ===")
    print(s_df.to_string(index=False))


if __name__ == "__main__":
    main()
