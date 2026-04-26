"""Out-of-sample 검증 — Stage 2 best params 로 미관측 기간 (2026-03~04) 백테스트.

OOS Calmar 가 Stage 2 avg Calmar 의 50% 이상 (즉 over-fitting 비율 < 2배) 이고,
Stage 2 게이트 5/5 통과해야 실거래 후보.
"""
import json
from pathlib import Path

import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.common.engine import BacktestEngine
from backtests.multiverse.fold import Fold
from backtests.multiverse.universe import select_top_universe
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


STRATEGY_MAP = {s.name: s for s in [
    ORBStrategy, GapDownReversalStrategy, GapUpChaseStrategy,
    VWAPBounceStrategy, BBLowerBounceStrategy, RSIOversoldStrategy,
    VolumeSurgeStrategy, IntradayPullbackStrategy, ClosingDriftStrategy,
    LimitUpChaseStrategy, CloseToOpenStrategy, Breakout52wStrategy,
    PostDropReboundStrategy, TrendFollowthroughStrategy, MACDCrossStrategy,
]}


# OOS 기간 — Stage 2 fold3 test_end(20260228) 이후
OOS_FOLD = Fold(
    name="oos",
    train_start="20251101", train_end="20260228",   # OOS 라 train 의미 없으나 스키마상 필요
    test_start="20260301", test_end="20260424",
)


def main():
    stage2_dir = Path("backtests/reports/stage2")
    best_files = sorted(stage2_dir.glob("*_best.json"))
    if not best_files:
        print(f"no best.json in {stage2_dir}")
        return

    # universe — Stage 2 와 동일하게 30 종목 (cache hit 가능성)
    universe = select_top_universe(
        fold_train_start="20250301", fold_test_end="20260228",
        n_stocks=30, min_days_present=120,
    )
    print(f"OOS universe ({len(universe)}): {universe[:10]}...")
    print(f"OOS period: {OOS_FOLD.test_start} ~ {OOS_FOLD.test_end}")

    # OOS minute + 1년 history daily
    minute_df = load_minute_df(universe, OOS_FOLD.test_start, OOS_FOLD.test_end)
    daily_df = load_daily_df(universe, "20250101", OOS_FOLD.test_end)
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    print(f"loaded {len(minute_df):,} OOS minute / {len(daily_df):,} daily rows\n")

    rows = []
    print(f"{'strategy':<22} {'stage2_avg':>10} {'oos_calmar':>10} "
          f"{'oos_ret':>9} {'oos_mdd':>8} {'oos_win%':>8} {'trades':>7} {'ratio':>7}")
    print("-" * 90)
    for f in best_files:
        name = f.stem.replace("_best", "")
        if name not in STRATEGY_MAP:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        params = d["best_params"]
        stage2_avg = d["best_value"]

        nonempty = [c for c in universe if len(minute_by_code[c]) > 0]
        eng = BacktestEngine(
            strategy=STRATEGY_MAP[name](**params),
            initial_capital=100_000_000,
            universe=nonempty,
            minute_df_by_code={c: minute_by_code[c] for c in nonempty},
            daily_df_by_code={c: daily_by_code[c] for c in nonempty},
        )
        try:
            r = eng.run()
            m = r.metrics
        except Exception as e:
            print(f"{name:<22} ERROR: {type(e).__name__}: {e}")
            continue
        ratio = m.get("calmar", float("nan")) / stage2_avg if stage2_avg else float("nan")
        rows.append({
            "strategy": name,
            "stage2_avg_calmar": stage2_avg,
            "oos_calmar": m.get("calmar"),
            "oos_return": m.get("total_return"),
            "oos_mdd": m.get("mdd"),
            "oos_win_rate": m.get("win_rate"),
            "oos_trades": m.get("total_trades"),
            "oos_to_stage2_ratio": ratio,
            "oos_pass_50pct_test": (
                ratio >= 0.5 if pd.notna(ratio) else False
            ),
            "oos_calmar_above_5": (
                m.get("calmar", float("-inf")) >= 5
            ),
        })
        print(
            f"{name:<22} {stage2_avg:>10.2f} "
            f"{m.get('calmar', 0):>10.2f} "
            f"{m.get('total_return', 0):>8.2%} "
            f"{m.get('mdd', 0):>7.2%} "
            f"{m.get('win_rate', 0):>7.1%} "
            f"{m.get('total_trades', 0):>7d} "
            f"{ratio:>7.2f}"
        )

    df = pd.DataFrame(rows)
    out_path = stage2_dir / "oos_summary.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")

    print("\n=== OOS 통과 (ratio ≥ 0.5 + Calmar ≥ 5) ===")
    passing = df[df["oos_pass_50pct_test"] & df["oos_calmar_above_5"]]
    if passing.empty:
        print("(없음)")
    else:
        for _, r in passing.iterrows():
            print(f"  {r['strategy']}: stage2 {r['stage2_avg_calmar']:.1f} → "
                  f"OOS {r['oos_calmar']:.1f} ({r['oos_to_stage2_ratio']*100:.0f}%) "
                  f"return {r['oos_return']:.1%}")


if __name__ == "__main__":
    main()
