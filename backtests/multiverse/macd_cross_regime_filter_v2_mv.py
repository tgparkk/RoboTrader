"""MV-C v2: macd_cross regime filter 대체 신호 멀티버스.

Spec docs/superpowers/specs/2026-05-13-macd-cross-fold2-regime-filter-v2-design.md.

10 signal cells × 2 params × 4 datasets = 80 evaluation.
"""
import csv
import time
from pathlib import Path
from typing import Dict, List

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_regime_filter import (
    MACDCrossRegimeFilterStrategy,
)


REPORT_DIR = Path("backtests/reports/macd_cross_mv/regime_filter_v2")

SIGNAL_CELLS: List[Dict] = [
    {"label": "off",                "enabled": False, "signal_type": "ma20_below_prev",    "threshold": None},
    {"label": "ma20_below_prev",    "enabled": True,  "signal_type": "ma20_below_prev",    "threshold": None},
    {"label": "ma20_and_ma5_below", "enabled": True,  "signal_type": "ma20_and_ma5_below", "threshold": None},
    {"label": "5d_drop_-1pct",      "enabled": True,  "signal_type": "5d_return_drop",     "threshold": -0.01},
    {"label": "5d_drop_-2pct",      "enabled": True,  "signal_type": "5d_return_drop",     "threshold": -0.02},
    {"label": "5d_drop_-3pct",      "enabled": True,  "signal_type": "5d_return_drop",     "threshold": -0.03},
    {"label": "5d_drop_-5pct",      "enabled": True,  "signal_type": "5d_return_drop",     "threshold": -0.05},
    {"label": "20d_neg_0pct",       "enabled": True,  "signal_type": "20d_return_neg",     "threshold":  0.0 },
    {"label": "20d_neg_-3pct",      "enabled": True,  "signal_type": "20d_return_neg",     "threshold": -0.03},
    {"label": "20d_neg_-5pct",      "enabled": True,  "signal_type": "20d_return_neg",     "threshold": -0.05},
]

PARAM_CELLS = [
    {"label": "stage2_best",     "fast_period": 14, "slow_period": 34,
     "signal_period": 12, "entry_hhmm_min": 1430},
    {"label": "mva_global_best", "fast_period": 16, "slow_period": 32,
     "signal_period": 12, "entry_hhmm_min": 1430},
]


def _count_block_days(strategy, dataset: Dataset) -> int:
    """dataset 영업일 중 filter 가 entry 차단했을 일수."""
    if not strategy.regime_filter_enabled or strategy.kospi_daily_df is None:
        return 0
    ks_sorted = strategy.kospi_daily_df.sort_values("trade_date").reset_index(drop=True)
    below_prev = strategy.compute_block_series(ks_sorted)
    block_map = dict(zip(ks_sorted["trade_date"].astype(str), below_prev))
    ds_dates = set()
    for df_min in dataset.minute_by_code.values():
        if not df_min.empty:
            ds_dates.update(df_min["trade_date"].astype(str).unique())
    return int(sum(1 for d in ds_dates if block_map.get(d, False)))


def _evaluate(strategy, dataset: Dataset, initial_capital=10_000_000) -> Dict:
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
    kpis["block_days"] = _count_block_days(strategy, dataset)
    return kpis


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("[MV-C v2] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    total = len(SIGNAL_CELLS) * len(PARAM_CELLS) * len(datasets)
    print(f"[MV-C v2] {total} evaluation 시작")

    out = REPORT_DIR / "cells.csv"
    fields = [
        "signal_label", "signal_type", "signal_threshold", "filter_enabled",
        "param_label", "fast_period", "slow_period", "signal_period", "entry_hhmm_min",
        "dataset", "calmar", "return", "mdd", "trades", "win_rate",
        "top1_share", "max_consec_loss", "monthly_trades", "block_days",
    ]
    t0 = time.time()
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for sc in SIGNAL_CELLS:
            for pc in PARAM_CELLS:
                p = {k: v for k, v in pc.items() if k != "label"}
                for ds_name, ds in datasets.items():
                    strat = MACDCrossRegimeFilterStrategy(
                        regime_filter_enabled=sc["enabled"],
                        kospi_daily_df=ds.kospi_daily_df if sc["enabled"] else None,
                        signal_type=sc["signal_type"],
                        signal_threshold=sc["threshold"],
                        **p,
                    )
                    kpis = _evaluate(strat, ds)
                    writer.writerow({
                        "signal_label": sc["label"],
                        "signal_type": sc["signal_type"],
                        "signal_threshold": sc["threshold"],
                        "filter_enabled": sc["enabled"],
                        "param_label": pc["label"],
                        **p,
                        "dataset": ds_name,
                        **{k: kpis[k] for k in (
                            "calmar", "return", "mdd", "trades", "win_rate",
                            "top1_share", "max_consec_loss", "monthly_trades",
                            "block_days",
                        )},
                    })
                    print(f"  {sc['label']:<22} {pc['label']:<16} {ds_name}: "
                          f"calmar={kpis['calmar']:>+7.2f} "
                          f"block={kpis['block_days']:>3} trades={kpis['trades']}")
    print(f"[MV-C v2] saved → {out} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
