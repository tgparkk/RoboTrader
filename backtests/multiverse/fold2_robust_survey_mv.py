"""MV-E: fold2-robust 진입 전략 발굴 멀티버스.

7 strategy × ~270 cells × 4 datasets = ~1080 evaluation.

Spec: docs/superpowers/specs/2026-05-14-fold2-robust-survey-design.md
Plan: docs/superpowers/plans/2026-05-14-fold2-robust-survey.md
"""
import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Type

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.base import StrategyBase
from backtests.strategies.bb_lower_bounce import BBLowerBounceStrategy
from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.closing_drift import ClosingDriftStrategy
from backtests.strategies.gap_down_reversal import GapDownReversalStrategy
from backtests.strategies.rsi_oversold import RSIOversoldStrategy
from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy
from backtests.strategies.vwap_bounce import VWAPBounceStrategy


REPORT_DIR = Path("backtests/reports/fold2_robust_survey")


# ---------- cell 정의 ----------

def _gap_down_reversal_cells() -> List[Dict]:
    cells = []
    for gap in [-1.0, -1.5, -2.0, -3.0]:
        for rev in [0.5, 1.0, 1.5]:
            for tp in [1.5, 2.5, 3.5, 5.0]:
                cells.append({
                    "strategy_name": "gap_down_reversal",
                    "cell_label": f"gap{gap:+.1f}_rev{rev:.1f}_tp{tp:.1f}",
                    "kwargs": {
                        "gap_threshold_pct": gap,
                        "reversal_threshold_pct": rev,
                        "take_profit_pct": tp,
                    },
                })
    return cells


def _rsi_oversold_cells() -> List[Dict]:
    cells = []
    for ov in [20.0, 25.0, 30.0, 35.0]:
        for tp in [1.5, 2.0, 3.0]:
            for sl in [-1.0, -1.5, -2.0, -2.5]:
                cells.append({
                    "strategy_name": "rsi_oversold",
                    "cell_label": f"ov{ov:.0f}_tp{tp:.1f}_sl{sl:.1f}",
                    "kwargs": {
                        "oversold_threshold": ov,
                        "take_profit_pct": tp,
                        "stop_loss_pct": sl,
                    },
                })
    return cells


def _bb_lower_bounce_cells() -> List[Dict]:
    cells = []
    for ns in [1.5, 2.0, 2.5]:
        for tp in [1.5, 2.5, 3.5]:
            for sl in [-1.0, -1.5, -2.0, -2.5]:
                cells.append({
                    "strategy_name": "bb_lower_bounce",
                    "cell_label": f"ns{ns:.1f}_tp{tp:.1f}_sl{sl:.1f}",
                    "kwargs": {
                        "bb_num_std": ns,
                        "take_profit_pct": tp,
                        "stop_loss_pct": sl,
                    },
                })
    return cells


def _vwap_bounce_cells() -> List[Dict]:
    cells = []
    for dev in [-0.5, -1.0, -1.5, -2.0]:
        for tp in [1.5, 2.0, 3.0]:
            for sl in [-1.0, -1.5, -2.0, -2.5]:
                cells.append({
                    "strategy_name": "vwap_bounce",
                    "cell_label": f"dev{dev:.1f}_tp{tp:.1f}_sl{sl:.1f}",
                    "kwargs": {
                        "vwap_deviation_pct": dev,
                        "take_profit_pct": tp,
                        "stop_loss_pct": sl,
                    },
                })
    return cells


def _closing_drift_cells() -> List[Dict]:
    cells = []
    windows = [(1400, 1420), (1430, 1450), (1400, 1500)]
    for body in [0.5, 1.0, 2.0]:
        for decl in [-1.5, -2.5, -3.5]:
            for (hs, he) in windows:
                cells.append({
                    "strategy_name": "closing_drift",
                    "cell_label": f"body{body:.1f}_decl{decl:.1f}_w{hs}_{he}",
                    "kwargs": {
                        "min_prev_body_pct": body,
                        "max_day_decline_pct": decl,
                        "entry_hhmm_start": hs,
                        "entry_hhmm_end": he,
                    },
                })
    return cells


def _breakout_52w_cells() -> List[Dict]:
    cells = []
    for lb in [60, 120, 252]:
        for bf in [0.0, 0.3, 0.6]:
            for hh in [1430, 1450, 1500]:
                cells.append({
                    "strategy_name": "breakout_52w",
                    "cell_label": f"lb{lb}_bf{bf:.1f}_hh{hh}",
                    "kwargs": {
                        "lookback_days": lb,
                        "buffer_pct": bf,
                        "entry_hhmm_min": hh,
                    },
                })
    return cells


def _trend_followthrough_cells() -> List[Dict]:
    cells = []
    for lb in [3, 5, 10, 20]:
        for bf in [0.0, 0.3, 0.6]:
            for hh in [1430, 1450, 1500]:
                cells.append({
                    "strategy_name": "trend_followthrough",
                    "cell_label": f"lb{lb}_bf{bf:.1f}_hh{hh}",
                    "kwargs": {
                        "lookback_days": lb,
                        "buffer_pct": bf,
                        "entry_hhmm_min": hh,
                    },
                })
    return cells


STRATEGY_CLASSES: Dict[str, Type[StrategyBase]] = {
    "gap_down_reversal": GapDownReversalStrategy,
    "rsi_oversold": RSIOversoldStrategy,
    "bb_lower_bounce": BBLowerBounceStrategy,
    "vwap_bounce": VWAPBounceStrategy,
    "closing_drift": ClosingDriftStrategy,
    "breakout_52w": Breakout52wStrategy,
    "trend_followthrough": TrendFollowthroughStrategy,
}


CELLS: List[Dict] = (
    _gap_down_reversal_cells()
    + _rsi_oversold_cells()
    + _bb_lower_bounce_cells()
    + _vwap_bounce_cells()
    + _closing_drift_cells()
    + _breakout_52w_cells()
    + _trend_followthrough_cells()
)


# ---------- evaluation ----------

REASON_KEYS = ("hold_limit", "tp", "sl", "eod_forced")


def _exit_reason_dist(trades) -> Dict[str, float]:
    if not trades:
        return {k: 0.0 for k in REASON_KEYS}
    cnt = Counter(t["reason"] for t in trades)
    total = len(trades)
    return {k: cnt.get(k, 0) / total for k in REASON_KEYS}


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
    kpis.update({f"reason_{k}": v for k, v in _exit_reason_dist(result.trades).items()})
    return kpis


def _fields() -> List[str]:
    return [
        "strategy_name", "cell_label", "dataset", "param_json",
        "calmar", "return", "mdd", "trades", "win_rate",
        "top1_share", "max_consec_loss", "monthly_trades",
        *(f"reason_{k}" for k in REASON_KEYS),
    ]


def main(smoke: bool = False):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    cells = CELLS
    if smoke:
        # 4 strategy 의 첫 cell 만 (offset = 누적 길이)
        offsets = [0, 48, 96, 132]  # gap_down, rsi, bb, vwap 의 시작 idx
        cells = [CELLS[i] for i in offsets]

    print("[MV-E] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    if smoke:
        datasets = {"fold1": datasets["fold1"]}

    total = len(cells) * len(datasets)
    print(f"[MV-E] {len(cells)} cells × {len(datasets)} datasets = {total} evaluations"
          f"{' (SMOKE)' if smoke else ''}")

    out_path = REPORT_DIR / ("smoke_cells.csv" if smoke else "cells.csv")
    t0 = time.time()
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_fields())
        writer.writeheader()
        for ci, cell in enumerate(cells, 1):
            cls = STRATEGY_CLASSES[cell["strategy_name"]]
            for ds_name, ds in datasets.items():
                strat = cls(**cell["kwargs"])
                kpis = _evaluate(strat, ds)
                row = {
                    "strategy_name": cell["strategy_name"],
                    "cell_label": cell["cell_label"],
                    "dataset": ds_name,
                    "param_json": json.dumps(cell["kwargs"], separators=(",", ":")),
                    **{k: kpis.get(k) for k in (
                        "calmar", "return", "mdd", "trades", "win_rate",
                        "top1_share", "max_consec_loss", "monthly_trades",
                    )},
                    **{f"reason_{k}": kpis.get(f"reason_{k}", 0.0) for k in REASON_KEYS},
                }
                writer.writerow(row)
            elapsed = time.time() - t0
            print(f"  cell {ci:>3}/{len(cells)} "
                  f"[{cell['strategy_name']:>20}/{cell['cell_label']}] "
                  f"({elapsed:.0f}s)")

    print(f"[MV-E] saved → {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="4 cell × 1 dataset 빠른 sanity 실행")
    args = parser.parse_args()
    main(smoke=args.smoke)
