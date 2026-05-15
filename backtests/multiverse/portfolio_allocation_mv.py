"""MV-F: Portfolio Allocation 멀티버스.

Stage 1: 3 strategy × 4 fold equity 시계열 NPY 캐시 (12 NPY).
Stage 2: simplex weight grid 66 cells × 4 fold = 264 portfolio metric.

Spec: docs/superpowers/specs/2026-05-14-portfolio-allocation-design.md
Plan: docs/superpowers/plans/2026-05-14-portfolio-allocation.md
"""
import argparse
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.common.metrics import compute_calmar, compute_max_drawdown
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, load_all_datasets, _trading_days_count,
)
from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.macd_cross import MACDCrossStrategy
from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy


REPORT_DIR = Path("backtests/reports/portfolio_allocation")
EQUITY_CACHE_DIR = REPORT_DIR / "equity_cache"


STRATEGY_BUILDERS = {
    "macd_cross": lambda: MACDCrossStrategy(
        fast_period=14, slow_period=34, signal_period=12, entry_hhmm_min=1430,
    ),
    "breakout_52w": lambda: Breakout52wStrategy(
        lookback_days=60, buffer_pct=0.0,
        entry_hhmm_min=1500, entry_hhmm_max=1500,
    ),
    "trend_followthrough": lambda: TrendFollowthroughStrategy(
        lookback_days=3, buffer_pct=0.6,
        entry_hhmm_min=1430, entry_hhmm_max=1500,
    ),
}


def run_stage1(
    datasets: Dict[str, Dataset], initial_capital: float = 10_000_000,
) -> Dict[Tuple[str, str], int]:
    """3 strategy × N fold sim 후 equity NPY 저장.

    Returns:
        {(strategy, fold): trading_days} — Stage 2 calmar 계산용.
    """
    EQUITY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    trading_days_map: Dict[Tuple[str, str], int] = {}
    t0 = time.time()
    for sname, builder in STRATEGY_BUILDERS.items():
        for ds_name, ds in datasets.items():
            eng = BacktestEngine(
                strategy=builder(),
                initial_capital=initial_capital,
                universe=ds.universe,
                minute_df_by_code=ds.minute_by_code,
                daily_df_by_code=ds.daily_by_code,
            )
            result = eng.run()
            equity = result.equity_curve.values.astype(float)
            np.save(EQUITY_CACHE_DIR / f"{sname}_{ds_name}.npy", equity)
            td = _trading_days_count(ds.minute_by_code)
            trading_days_map[(sname, ds_name)] = td
            elapsed = time.time() - t0
            print(f"  stage1 {sname:>22} {ds_name}: "
                  f"equity[0]={equity[0]:.0f} equity[-1]={equity[-1]:.0f} "
                  f"trades={len(result.trades)} ({elapsed:.0f}s)")
    return trading_days_map


def simplex_weights(step: float = 0.1) -> List[Tuple[float, float, float]]:
    """w1+w2+w3=1 인 simplex grid. step=0.1 → 66 cells."""
    n = int(round(1.0 / step))
    weights = []
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            weights.append((i / n, j / n, k / n))
    return weights


def load_equity_cache() -> Dict[Tuple[str, str], np.ndarray]:
    """equity_cache/ 에서 모든 NPY 로드."""
    eq: Dict[Tuple[str, str], np.ndarray] = {}
    for sname in STRATEGY_BUILDERS:
        for fname in ("fold1", "fold2", "fold3", "oos"):
            path = EQUITY_CACHE_DIR / f"{sname}_{fname}.npy"
            if path.exists():
                eq[(sname, fname)] = np.load(path)
    return eq


def run_stage2(
    eq: Dict[Tuple[str, str], np.ndarray],
    trading_days_map: Dict[Tuple[str, str], int],
    folds: Tuple[str, ...] = ("fold1", "fold2", "fold3", "oos"),
    initial_capital: float = 10_000_000,
) -> pd.DataFrame:
    """simplex weight grid × fold 의 portfolio metric 계산."""
    weights = simplex_weights(step=0.1)
    rows = []
    for (w_m, w_b, w_t) in weights:
        for fold in folds:
            if ("macd_cross", fold) not in eq:
                continue
            macd_eq = eq[("macd_cross", fold)]
            brk_eq = eq[("breakout_52w", fold)]
            trn_eq = eq[("trend_followthrough", fold)]
            n = min(len(macd_eq), len(brk_eq), len(trn_eq))
            macd_ret = macd_eq[:n] / macd_eq[0]
            brk_ret = brk_eq[:n] / brk_eq[0]
            trn_ret = trn_eq[:n] / trn_eq[0]
            port_eq = initial_capital * (
                w_m * macd_ret + w_b * brk_ret + w_t * trn_ret
            )
            port_eq_series = pd.Series(port_eq)
            td = trading_days_map.get(("macd_cross", fold), 0)
            rows.append({
                "w_macd": round(w_m, 2),
                "w_breakout": round(w_b, 2),
                "w_trend": round(w_t, 2),
                "fold": fold,
                "portfolio_calmar": compute_calmar(port_eq_series, td),
                "portfolio_return": float(port_eq[-1] / port_eq[0] - 1),
                "portfolio_mdd": compute_max_drawdown(port_eq_series),
                "macd_calmar": compute_calmar(pd.Series(macd_eq[:n]), td),
                "breakout_calmar": compute_calmar(pd.Series(brk_eq[:n]), td),
                "trend_calmar": compute_calmar(pd.Series(trn_eq[:n]), td),
            })
    return pd.DataFrame(rows)


def main(stage: str = "all", smoke: bool = False):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    td_map: Dict[Tuple[str, str], int] = {}
    if stage in ("all", "stage1"):
        print("[MV-F] datasets 로드...")
        datasets = load_all_datasets()
        if smoke:
            datasets = {"fold1": datasets["fold1"]}
        td_map = run_stage1(datasets)
    else:
        print("[MV-F] stage2 only — datasets 로드 (trading_days 재구성용)...")
        datasets = load_all_datasets()
        td_map = {
            (s, f): _trading_days_count(datasets[f].minute_by_code)
            for s in STRATEGY_BUILDERS for f in datasets
        }

    if stage in ("all", "stage2"):
        eq = load_equity_cache()
        if smoke:
            eq = {k: v for k, v in eq.items() if k[1] == "fold1"}
        if not eq:
            print("[MV-F] equity cache 비어있음 — stage1 먼저 실행 필요")
            return
        folds_present = sorted({k[1] for k in eq.keys()})
        df = run_stage2(eq, td_map, folds=tuple(folds_present))
        out_path = REPORT_DIR / ("smoke_cells.csv" if smoke else "cells.csv")
        df.to_csv(out_path, index=False)
        print(f"[MV-F] stage2 saved → {out_path} ({len(df)} rows)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=["all", "stage1", "stage2"], default="all",
    )
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    main(stage=args.stage, smoke=args.smoke)
