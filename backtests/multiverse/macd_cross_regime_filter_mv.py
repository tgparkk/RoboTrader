"""MV-C: macd_cross regime filter 멀티버스.

Spec docs/superpowers/specs/2026-05-09-macd-cross-fold2-regime-filter-design.md.

2 params (Stage 2 best 14/34, MV-A globally best 16/32) × 2 filter (off, on)
× 4 dataset (fold1/fold2/fold3/oos) = 16 evaluation. cells.csv 에 block_days
까지 기록.
"""
import csv
import time
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_regime_filter import (
    MACDCrossRegimeFilterStrategy,
)


REPORT_DIR = Path("backtests/reports/macd_cross_mv/regime_filter")

PARAM_CELLS = [
    {"label": "stage2_best",
     "fast_period": 14, "slow_period": 34,
     "signal_period": 12, "entry_hhmm_min": 1430},
    {"label": "mva_global_best",
     "fast_period": 16, "slow_period": 32,
     "signal_period": 12, "entry_hhmm_min": 1430},
]
FILTER_FLAGS = [False, True]


def _count_block_days(
    kospi_daily_df: Optional[pd.DataFrame],
    dataset: Dataset,
    ma_period: int,
) -> int:
    """dataset 영업일 중 filter 가 차단했을 일수.

    엔진과 별도로 KOSPI 신호를 재계산해 dataset 의 minute trade_date set 과
    intersect. 차단 일수만 카운트.
    """
    if kospi_daily_df is None:
        return 0
    ks = kospi_daily_df.sort_values("trade_date").copy()
    ks["ma"] = ks["close"].rolling(ma_period).mean()
    ks["below_prev"] = (ks["close"] < ks["ma"]).shift(1).fillna(False)
    ds_dates = set()
    for df_min in dataset.minute_by_code.values():
        if not df_min.empty:
            ds_dates.update(df_min["trade_date"].astype(str).unique())
    sub = ks[ks["trade_date"].astype(str).isin(ds_dates)]
    return int(sub["below_prev"].sum())


def _evaluate(strategy, dataset, ma_period, initial_capital=10_000_000) -> Dict:
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
    if strategy.regime_filter_enabled:
        kpis["block_days"] = _count_block_days(
            strategy.kospi_daily_df, dataset, ma_period,
        )
    else:
        kpis["block_days"] = 0
    return kpis


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("[MV-C] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    total_cells = len(PARAM_CELLS) * len(FILTER_FLAGS) * len(datasets)
    print(f"[MV-C] {total_cells} evaluation 시작")

    out_path = REPORT_DIR / "cells.csv"
    fieldnames = [
        "param_label", "fast_period", "slow_period", "signal_period",
        "entry_hhmm_min", "filter", "dataset",
        "calmar", "return", "mdd", "trades", "win_rate",
        "top1_share", "max_consec_loss", "monthly_trades", "block_days",
    ]
    t0 = time.time()
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for params in PARAM_CELLS:
            label = params["label"]
            params_no_label = {k: v for k, v in params.items() if k != "label"}
            for filter_on in FILTER_FLAGS:
                for ds_name, ds in datasets.items():
                    strat = MACDCrossRegimeFilterStrategy(
                        regime_filter_enabled=filter_on,
                        kospi_daily_df=ds.kospi_daily_df if filter_on else None,
                        ma_period=20,
                        **params_no_label,
                    )
                    kpis = _evaluate(strat, ds, ma_period=20)
                    row = {
                        "param_label": label,
                        **params_no_label,
                        "filter": "on" if filter_on else "off",
                        "dataset": ds_name,
                        **{k: kpis[k] for k in (
                            "calmar","return","mdd","trades","win_rate",
                            "top1_share","max_consec_loss","monthly_trades",
                            "block_days",
                        )},
                    }
                    writer.writerow(row)
                    print(f"  {label} filter={'on' if filter_on else 'off'} {ds_name}: "
                          f"calmar={kpis['calmar']:.2f} block={kpis['block_days']} "
                          f"trades={kpis['trades']}")
    elapsed = time.time() - t0
    print(f"[MV-C] saved → {out_path} ({elapsed:.0f}s)")


if __name__ == "__main__":
    main()
