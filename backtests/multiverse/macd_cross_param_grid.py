"""MV-A: macd_cross 파라미터 fine grid 멀티버스.

Spec docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md §3.

각 cell × dataset 평가 결과를 cells.csv 에 long-format 으로 저장.
heatmap PNG 와 summary.md 는 plot_macd_cross_mv.py 가 생성.
"""
import csv
import itertools
import time
from pathlib import Path
from typing import Dict

from backtests.multiverse.macd_cross_mv_common import (
    Dataset, evaluate_cell, load_all_datasets,
)
from backtests.strategies.macd_cross import MACDCrossStrategy


REPORT_DIR = Path("backtests/reports/macd_cross_mv/param_grid")


PARAM_GRID = {
    "fast_period": [8, 10, 12, 14, 16],
    "slow_period": [24, 28, 32, 34, 36, 40],
    "signal_period": [9, 10, 11, 12],
    "entry_hhmm_min": [1430, 1440, 1450],
}


def _enumerate_cells():
    keys = list(PARAM_GRID.keys())
    for combo in itertools.product(*[PARAM_GRID[k] for k in keys]):
        params = dict(zip(keys, combo))
        if params["slow_period"] <= params["fast_period"]:
            continue
        yield params


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("[MV-A] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    cells = list(_enumerate_cells())
    print(f"[MV-A] {len(cells)} cells × {len(datasets)} datasets "
          f"= {len(cells) * len(datasets)} evaluations")

    out_path = REPORT_DIR / "cells.csv"
    fieldnames = [
        "fast_period", "slow_period", "signal_period", "entry_hhmm_min",
        "dataset", "calmar", "return", "mdd", "trades",
        "win_rate", "top1_share", "max_consec_loss", "monthly_trades",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        t0 = time.time()
        for ci, params in enumerate(cells, 1):
            for ds_name, ds in datasets.items():
                strategy = MACDCrossStrategy(**params)
                kpis = evaluate_cell(strategy=strategy, dataset=ds)
                row = {**params, "dataset": ds_name, **kpis}
                writer.writerow(row)
            if ci % 20 == 0 or ci == len(cells):
                elapsed = time.time() - t0
                print(f"  cell {ci}/{len(cells)} ({elapsed:.0f}s elapsed, "
                      f"{elapsed / ci * (len(cells) - ci):.0f}s eta)")

    print(f"[MV-A] saved → {out_path}")


if __name__ == "__main__":
    main()
