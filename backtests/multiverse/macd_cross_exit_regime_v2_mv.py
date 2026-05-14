"""MV-D: macd_cross Exit-side regime v2 멀티버스.

3 family 단독 sweep × 2 baseline param × 4 dataset = ~240 evaluation.

Family A (Trailing): 4 trailing_pct × 2 activate_after = 8 cells
Family B (Reversal): 3 eval_hhmm × 2 threshold × 2 min_hold = 12 cells
Family C (Tiered SL): 3 sl_d1 × 3 sl_d2 = 9 cells (sl_d1=None & sl_d2=None 제외 → 8)
+ off baseline 1 cell
= 29 cells

Spec: docs/superpowers/specs/2026-05-14-macd-cross-exit-regime-v2-design.md (TBD)
"""
import argparse
import csv
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_exit_regime_v2 import (
    MACDCrossExitRegimeV2Strategy,
)


REPORT_DIR = Path("backtests/reports/macd_cross_mv/exit_regime_v2")


# ---------- cell 정의 ----------

OFF_CELL: Dict = {
    "family": "off", "cell_label": "off",
    "trailing_pct": None, "trailing_activate": None,
    "reversal_eval_hhmm": None, "reversal_hist_threshold": None,
    "reversal_min_hold": None,
    "sl_d1_pct": None, "sl_d2_pct": None,
}


def _build_family_a_cells() -> List[Dict]:
    cells = []
    for p in [0.02, 0.03, 0.04, 0.05]:
        for a in [0.0, 0.02]:
            cells.append({
                "family": "trailing",
                "cell_label": f"trail_p{int(p*100):02d}_a{int(a*100):02d}",
                "trailing_pct": p, "trailing_activate": a,
                "reversal_eval_hhmm": None, "reversal_hist_threshold": None,
                "reversal_min_hold": None,
                "sl_d1_pct": None, "sl_d2_pct": None,
            })
    return cells


def _build_family_b_cells() -> List[Dict]:
    cells = []
    for hhmm in [None, 1400, 1500]:
        for thr in [0.0, -1.0]:
            for mh in [1, 2]:
                hhmm_label = "last" if hhmm is None else str(hhmm)
                cells.append({
                    "family": "reversal",
                    "cell_label": f"rev_t{hhmm_label}_b{int(thr):+d}_h{mh}",
                    "trailing_pct": None, "trailing_activate": None,
                    "reversal_eval_hhmm": hhmm,
                    "reversal_hist_threshold": thr,
                    "reversal_min_hold": mh,
                    "sl_d1_pct": None, "sl_d2_pct": None,
                })
    return cells


def _build_family_c_cells() -> List[Dict]:
    cells = []
    for d1 in [None, 0.05, 0.07]:
        for d2 in [None, 0.03, 0.05]:
            if d1 is None and d2 is None:
                continue  # (None, None) → 이미 off cell 에서 측정
            d1_lbl = "X" if d1 is None else f"{int(d1*100):02d}"
            d2_lbl = "X" if d2 is None else f"{int(d2*100):02d}"
            cells.append({
                "family": "tiered_sl",
                "cell_label": f"tsl_d1_{d1_lbl}_d2_{d2_lbl}",
                "trailing_pct": None, "trailing_activate": None,
                "reversal_eval_hhmm": None, "reversal_hist_threshold": None,
                "reversal_min_hold": None,
                "sl_d1_pct": d1, "sl_d2_pct": d2,
            })
    return cells


CELLS: List[Dict] = (
    [OFF_CELL]
    + _build_family_a_cells()
    + _build_family_b_cells()
    + _build_family_c_cells()
)


PARAM_CELLS = [
    {"label": "stage2_best", "fast_period": 14, "slow_period": 34,
     "signal_period": 12, "entry_hhmm_min": 1430},
    {"label": "mva_global_best", "fast_period": 16, "slow_period": 32,
     "signal_period": 12, "entry_hhmm_min": 1430},
]


# ---------- evaluation ----------

REASON_KEYS = (
    "hold_limit", "trailing_stop", "macd_reversal", "sl_d1", "sl_d2", "eod_forced",
)


def _exit_reason_dist(trades) -> Dict[str, float]:
    if not trades:
        return {k: 0.0 for k in REASON_KEYS}
    cnt = Counter(t["reason"] for t in trades)
    total = len(trades)
    return {k: cnt.get(k, 0) / total for k in REASON_KEYS}


def _family_trigger_keys(family: str) -> List[str]:
    if family == "trailing":
        return ["trailing_stop"]
    if family == "reversal":
        return ["macd_reversal"]
    if family == "tiered_sl":
        return ["sl_d1", "sl_d2"]
    return []


def _build_strategy(cell: Dict, param: Dict) -> MACDCrossExitRegimeV2Strategy:
    kw = {k: v for k, v in param.items() if k != "label"}
    if cell["family"] == "off":
        return MACDCrossExitRegimeV2Strategy(family="off", **kw)
    if cell["family"] == "trailing":
        return MACDCrossExitRegimeV2Strategy(
            family="trailing",
            trailing_pct=cell["trailing_pct"],
            trailing_activate_after_pct=cell["trailing_activate"],
            **kw,
        )
    if cell["family"] == "reversal":
        return MACDCrossExitRegimeV2Strategy(
            family="reversal",
            reversal_eval_hhmm=cell["reversal_eval_hhmm"],
            reversal_hist_threshold=cell["reversal_hist_threshold"],
            reversal_min_hold_days=cell["reversal_min_hold"],
            **kw,
        )
    if cell["family"] == "tiered_sl":
        return MACDCrossExitRegimeV2Strategy(
            family="tiered_sl",
            sl_d1_pct=cell["sl_d1_pct"],
            sl_d2_pct=cell["sl_d2_pct"],
            **kw,
        )
    raise ValueError(f"unknown family {cell['family']!r}")


def _evaluate(strategy, dataset: Dataset, initial_capital: float = 10_000_000) -> Dict:
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
    reasons = _exit_reason_dist(result.trades)
    kpis.update({f"reason_{k}": v for k, v in reasons.items()})
    return kpis


def _fields() -> List[str]:
    return [
        "family", "cell_label", "dataset", "param_label",
        "fast_period", "slow_period", "signal_period", "entry_hhmm_min",
        "trailing_pct", "trailing_activate",
        "reversal_eval_hhmm", "reversal_hist_threshold", "reversal_min_hold",
        "sl_d1_pct", "sl_d2_pct",
        "calmar", "return", "mdd", "trades", "win_rate",
        "top1_share", "max_consec_loss", "monthly_trades",
        *(f"reason_{k}" for k in REASON_KEYS),
        "fired_ratio",
    ]


def _row(cell: Dict, param: Dict, ds_name: str, kpis: Dict) -> Dict:
    trigger_keys = _family_trigger_keys(cell["family"])
    fired_ratio = sum(kpis.get(f"reason_{k}", 0.0) for k in trigger_keys)
    return {
        "family": cell["family"], "cell_label": cell["cell_label"],
        "dataset": ds_name, "param_label": param["label"],
        "fast_period": param["fast_period"], "slow_period": param["slow_period"],
        "signal_period": param["signal_period"],
        "entry_hhmm_min": param["entry_hhmm_min"],
        "trailing_pct": cell["trailing_pct"],
        "trailing_activate": cell["trailing_activate"],
        "reversal_eval_hhmm": cell["reversal_eval_hhmm"],
        "reversal_hist_threshold": cell["reversal_hist_threshold"],
        "reversal_min_hold": cell["reversal_min_hold"],
        "sl_d1_pct": cell["sl_d1_pct"],
        "sl_d2_pct": cell["sl_d2_pct"],
        **{k: kpis.get(k) for k in (
            "calmar", "return", "mdd", "trades", "win_rate",
            "top1_share", "max_consec_loss", "monthly_trades",
        )},
        **{f"reason_{k}": kpis.get(f"reason_{k}", 0.0) for k in REASON_KEYS},
        "fired_ratio": fired_ratio,
    }


def main(smoke: bool = False):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    cells = CELLS
    params = PARAM_CELLS
    if smoke:
        # 1 cell × 1 param × 1 dataset 만 — 코드 sanity check
        cells = [OFF_CELL, CELLS[1]]   # off + first trailing cell
        params = [PARAM_CELLS[0]]

    print("[MV-D] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    if smoke:
        datasets = {"fold1": datasets["fold1"]}

    total = len(cells) * len(params) * len(datasets)
    print(f"[MV-D] {len(cells)} cells × {len(params)} params × "
          f"{len(datasets)} datasets = {total} evaluations"
          f"{' (SMOKE)' if smoke else ''}")

    out_path = REPORT_DIR / ("smoke_cells.csv" if smoke else "cells.csv")
    t0 = time.time()
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_fields())
        writer.writeheader()
        for ci, cell in enumerate(cells, 1):
            for param in params:
                for ds_name, ds in datasets.items():
                    strat = _build_strategy(cell, param)
                    kpis = _evaluate(strat, ds)
                    row = _row(cell, param, ds_name, kpis)
                    writer.writerow(row)
            elapsed = time.time() - t0
            print(f"  cell {ci:>2}/{len(cells)} "
                  f"[{cell['family']:>9}/{cell['cell_label']}] "
                  f"({elapsed:.0f}s)")

    print(f"[MV-D] saved → {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="2 cell × 1 param × 1 dataset 빠른 sanity 실행")
    args = parser.parse_args()
    main(smoke=args.smoke)
