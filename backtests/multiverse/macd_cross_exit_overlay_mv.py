"""MV-B: macd_cross exit overlay 멀티버스.

Spec docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md §4.

best params 고정 (fast=14, slow=34, signal=12, entry=1430). SL × TP × reversal
24 cell 평가. exit_reason 분포까지 기록.
"""
import csv
import itertools
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_exit_overlay import MACDCrossExitOverlayStrategy


REPORT_DIR = Path("backtests/reports/macd_cross_mv/exit_overlay")
BEST_PARAMS_PATH = Path("backtests/reports/stage2/macd_cross_best.json")


SL_GRID = [None, 0.03, 0.05, 0.07]
TP_GRID = [None, 0.05, 0.10]
REVERSAL_GRID = [False, True]


def _exit_reason_dist(trades) -> Dict[str, float]:
    if not trades:
        return {"hold_limit": 0.0, "sl": 0.0, "tp": 0.0, "macd_reversal": 0.0, "eod_forced": 0.0}
    cnt = Counter(t["reason"] for t in trades)
    total = len(trades)
    return {k: cnt.get(k, 0) / total
            for k in ("hold_limit", "sl", "tp", "macd_reversal", "eod_forced")}


def _evaluate_with_reasons(strategy, dataset, initial_capital=10_000_000):
    """evaluate_cell 과 동일하지만 exit_reason 분포 추가 반환."""
    eng = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        universe=dataset.universe,
        minute_df_by_code=dataset.minute_by_code,
        daily_df_by_code=dataset.daily_by_code,
    )
    result = eng.run()
    trading_days = _trading_days_count(dataset.minute_by_code)
    kpis = build_cell_kpis(
        equity=result.equity_curve,
        trades=result.trades,
        trading_days=trading_days,
    )
    kpis.update(_exit_reason_dist(result.trades))
    return kpis


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    best = json.loads(BEST_PARAMS_PATH.read_text(encoding="utf-8"))["best_params"]
    print(f"[MV-B] best params = {best}")

    print("[MV-B] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()

    cells = list(itertools.product(SL_GRID, TP_GRID, REVERSAL_GRID))
    print(f"[MV-B] {len(cells)} cells × {len(datasets)} datasets "
          f"= {len(cells) * len(datasets)} evaluations")

    out_path = REPORT_DIR / "cells.csv"
    fieldnames = [
        "sl_pct", "tp_pct", "intraday_reversal",
        "dataset", "calmar", "return", "mdd", "trades",
        "win_rate", "top1_share", "max_consec_loss", "monthly_trades",
        "reason_hold_limit", "reason_sl", "reason_tp",
        "reason_macd_reversal", "reason_eod_forced",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        t0 = time.time()
        for ci, (sl, tp, rev) in enumerate(cells, 1):
            for ds_name, ds in datasets.items():
                strat = MACDCrossExitOverlayStrategy(
                    sl_pct=sl, tp_pct=tp, intraday_reversal=rev, **best,
                )
                kpis = _evaluate_with_reasons(strat, ds)
                row = {
                    "sl_pct": "off" if sl is None else f"{sl:.2f}",
                    "tp_pct": "off" if tp is None else f"{tp:.2f}",
                    "intraday_reversal": "on" if rev else "off",
                    "dataset": ds_name,
                    **{k: kpis[k] for k in (
                        "calmar", "return", "mdd", "trades", "win_rate",
                        "top1_share", "max_consec_loss", "monthly_trades",
                    )},
                    "reason_hold_limit": kpis["hold_limit"],
                    "reason_sl": kpis["sl"],
                    "reason_tp": kpis["tp"],
                    "reason_macd_reversal": kpis["macd_reversal"],
                    "reason_eod_forced": kpis["eod_forced"],
                }
                writer.writerow(row)
            elapsed = time.time() - t0
            print(f"  cell {ci}/{len(cells)} sl={sl} tp={tp} rev={rev} "
                  f"({elapsed:.0f}s)")

    print(f"[MV-B] saved → {out_path}")


if __name__ == "__main__":
    main()
