"""Full Stage 1 sweep — 15 전략 × 200 trials × 30 종목 × Fold 1.

CLI 옵션:
  --strategies <name1,name2,...>  : 전략 부분집합 (default: all 15)
  --n-trials N                    : trials/strategy (default: 200)
  --n-workers N                   : 병렬 workers (default: 8)
  --universe-size N               : 상위 N 종목 (default: 30)
  --fold {fold1, smoke}           : 사용 fold (default: fold1)

결과:
  backtests/reports/stage1/<fold_name>/<strategy>_trials.csv
  backtests/reports/stage1/<fold_name>/summary.csv
"""
import argparse
import time
from pathlib import Path
from typing import List, Type

import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import STAGE1_FOLD1, SMOKE_FOLD, Fold
from backtests.multiverse.stage1_coarse import (
    save_trials, summarize_trials,
)
from backtests.multiverse.stage1_parallel import run_stage1_parallel
from backtests.multiverse.universe import select_top_universe
from backtests.strategies.base import StrategyBase
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


ALL_STRATEGIES: List[Type[StrategyBase]] = [
    ORBStrategy, GapDownReversalStrategy, GapUpChaseStrategy,
    VWAPBounceStrategy, BBLowerBounceStrategy, RSIOversoldStrategy,
    VolumeSurgeStrategy, IntradayPullbackStrategy, ClosingDriftStrategy,
    LimitUpChaseStrategy,
    CloseToOpenStrategy, Breakout52wStrategy, PostDropReboundStrategy,
    TrendFollowthroughStrategy, MACDCrossStrategy,
]


FOLDS = {"fold1": STAGE1_FOLD1, "smoke": SMOKE_FOLD}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--strategies", default="all",
                   help="comma-separated strategy names, or 'all'")
    p.add_argument("--n-trials", type=int, default=200)
    p.add_argument("--n-workers", type=int, default=8)
    p.add_argument("--universe-size", type=int, default=30)
    p.add_argument("--fold", choices=list(FOLDS.keys()), default="fold1")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def filter_strategies(name_filter: str) -> List[Type[StrategyBase]]:
    if name_filter == "all":
        return ALL_STRATEGIES
    wanted = {n.strip() for n in name_filter.split(",")}
    return [s for s in ALL_STRATEGIES if s.name in wanted]


def main():
    args = parse_args()
    fold = FOLDS[args.fold]

    print(f"=== Stage 1 Coarse Sweep ===")
    print(f"Fold: {fold.name}  train {fold.train_start}~{fold.train_end}  "
          f"test {fold.test_start}~{fold.test_end}")
    strategies = filter_strategies(args.strategies)
    print(f"Strategies: {[s.name for s in strategies]}  trials/strat={args.n_trials}  "
          f"workers={args.n_workers}")

    # Universe 선정
    print(f"Selecting top-{args.universe_size} universe...")
    universe = select_top_universe(
        fold_train_start=fold.train_start,
        fold_test_end=fold.test_end,
        n_stocks=args.universe_size,
        min_days_present=int((
            int(fold.test_end[:4]) * 12 + int(fold.test_end[4:6]) -
            int(fold.train_start[:4]) * 12 - int(fold.train_start[4:6])
        ) * 21 * 0.7),  # 기간의 70% 이상 거래
    )
    print(f"Universe ({len(universe)}): {universe}")

    fold = Fold(
        name=fold.name, train_start=fold.train_start, train_end=fold.train_end,
        test_start=fold.test_start, test_end=fold.test_end, universe=universe,
    )

    # 데이터 로드 (한 번만)
    t0 = time.perf_counter()
    minute_df = load_minute_df(universe, fold.train_start, fold.test_end)
    daily_df = load_daily_df(universe, fold.daily_history_start, fold.test_end)
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    print(f"Loaded data in {time.perf_counter()-t0:.1f}s "
          f"minute={len(minute_df):,} daily={len(daily_df):,}")

    out_dir = Path(f"backtests/reports/stage1/{fold.name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []

    for strat_cls in strategies:
        print(f"\n--- {strat_cls.name} ---")
        t0 = time.perf_counter()
        results = run_stage1_parallel(
            strategy_class=strat_cls,
            fold=fold,
            n_trials=args.n_trials,
            n_workers=args.n_workers,
            seed=args.seed,
            minute_by_code=minute_by_code,
            daily_by_code=daily_by_code,
        )
        elapsed = time.perf_counter() - t0
        save_trials(results, out_dir / f"{strat_cls.name}_trials.csv")

        s = summarize_trials(results)
        summary_rows.append({
            "strategy": strat_cls.name,
            "n_trials": s["n_trials"],
            "n_pass": s["n_pass"],
            "best_calmar": s.get("best_calmar"),
            "best_test_return": s.get("best_test_return"),
            "best_test_trades": s.get("best_test_trades"),
            "elapsed_s": round(elapsed, 1),
        })
        bc = s.get("best_calmar")
        br = s.get("best_test_return")
        bt = s.get("best_test_trades", 0)
        print(
            f"  {strat_cls.name:<22} pass={s['n_pass']}/{s['n_trials']}  "
            f"best_calmar={bc:.2f}  ret={br:.2%}  trades={bt}  elapsed={elapsed:.0f}s"
        )

    # Summary CSV
    summary_df = pd.DataFrame(summary_rows).sort_values(
        "best_calmar", ascending=False
    )
    summary_df.to_csv(out_dir / "summary.csv", index=False)
    print(f"\n=== Summary saved to {out_dir / 'summary.csv'} ===")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
