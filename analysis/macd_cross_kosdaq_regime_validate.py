"""KOSDAQ(KQ11) 기반 macd_cross 레짐필터 풀-fold 검증.

기존 regime_filter_v2 는 KOSPI(KS11) 기준 → 5~6월 KOSDAQ 약세 손실을 못 가림
(analysis/macd_cross_recent_mv.py 발견). 본 러너는 동일 신호를 KOSDAQ 기준으로
fold1/2/3 + oos + recent 전체에서 평가해 채택 가능성(강건성)을 판정한다.

판정 기준 (per-signal, vs off baseline, return 기준):
  - 나쁜장 완화: 음(-)수익 dataset 에서 Δret > 0
  - 좋은장 미악화: 양(+)수익 dataset 에서 Δret >= -0.5%p (작은 비용 허용)
"""
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.common.data_loader import load_minute_df, load_daily_df, load_index_df
from backtests.multiverse.universe import select_top_universe
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, _trading_days_count, load_all_datasets,
)
from backtests.strategies.macd_cross_regime_filter import MACDCrossRegimeFilterStrategy

BEST = {"fast_period": 14, "slow_period": 34, "signal_period": 12, "entry_hhmm_min": 1430}
DAILY_START = "20250101"
RECENT_START, RECENT_END = "20260425", "20260604"

SIGNALS = [
    {"label": "off",           "enabled": False, "signal_type": "5d_return_drop", "threshold": None},
    {"label": "5d_drop_-1pct", "enabled": True,  "signal_type": "5d_return_drop", "threshold": -0.01},
    {"label": "5d_drop_-2pct", "enabled": True,  "signal_type": "5d_return_drop", "threshold": -0.02},
    {"label": "5d_drop_-3pct", "enabled": True,  "signal_type": "5d_return_drop", "threshold": -0.03},
    {"label": "20d_neg_-3pct", "enabled": True,  "signal_type": "20d_return_neg", "threshold": -0.03},
]


def _norm_index(code: str, end: str) -> pd.DataFrame:
    raw = load_index_df(code, DAILY_START, end)
    return pd.DataFrame({
        "trade_date": raw["trade_date"].astype(str),
        "close": raw["close"].astype(float),
    }).sort_values("trade_date").reset_index(drop=True)


def build_recent(universe: List[str], kosdaq_df: pd.DataFrame) -> Dataset:
    minute_df = load_minute_df(universe, RECENT_START, RECENT_END)
    daily_df = load_daily_df(universe, DAILY_START, RECENT_END)
    m_full = {c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True) for c in universe}
    d_full = {c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True) for c in universe}
    m_by = {
        c: m_full[c][(m_full[c]["trade_date"] >= RECENT_START) & (m_full[c]["trade_date"] <= RECENT_END)]
            .reset_index(drop=True) for c in universe
    }
    d_by = {c: d_full[c][d_full[c]["trade_date"] <= RECENT_END].reset_index(drop=True) for c in universe}
    nonempty = [c for c in universe if len(m_by[c]) > 0]
    ds = Dataset(
        name="recent", minute_start=RECENT_START, minute_end=RECENT_END, daily_start=DAILY_START,
        minute_by_code={c: m_by[c] for c in nonempty}, daily_by_code={c: d_by[c] for c in nonempty},
        universe=nonempty, kospi_daily_df=kosdaq_df,
    )
    return ds


def evaluate(strategy, ds: Dataset) -> Dict:
    eng = BacktestEngine(
        strategy=strategy, initial_capital=10_000_000, universe=ds.universe,
        minute_df_by_code=ds.minute_by_code, daily_df_by_code=ds.daily_by_code,
    )
    result = eng.run()
    return build_cell_kpis(
        equity=result.equity_curve, trades=result.trades,
        trading_days=_trading_days_count(ds.minute_by_code),
    )


def main():
    print("[kosdaq-regime] fold1/2/3/oos 로드...")
    datasets = load_all_datasets()  # fold1/2/3/oos, minute~20260424
    uni = list(next(iter(datasets.values())).universe)
    # 전체 universe (fold 별 nonempty 합집합) 확보 위해 select_top_universe 재호출
    full_uni = select_top_universe(
        fold_train_start="20250301", fold_test_end="20260228",
        n_stocks=30, min_days_present=120,
    )
    kosdaq_full = _norm_index("KQ11", RECENT_END)

    print("[kosdaq-regime] recent 로드...")
    datasets["recent"] = build_recent(full_uni, kosdaq_full)

    # 모든 dataset 의 regime index 를 KOSDAQ 로 교체
    for name, ds in datasets.items():
        ds.kospi_daily_df = kosdaq_full  # KOSDAQ 기준으로 통일

    ds_order = ["fold1", "fold2", "fold3", "oos", "recent"]
    ds_order = [d for d in ds_order if d in datasets]

    # 평가
    results: Dict[str, Dict[str, Dict]] = {}  # signal -> dataset -> kpi
    for sig in SIGNALS:
        results[sig["label"]] = {}
        for name in ds_order:
            ds = datasets[name]
            strat = MACDCrossRegimeFilterStrategy(
                regime_filter_enabled=sig["enabled"],
                kospi_daily_df=ds.kospi_daily_df if sig["enabled"] else None,
                signal_type=sig["signal_type"], signal_threshold=sig["threshold"], **BEST,
            )
            results[sig["label"]][name] = evaluate(strat, ds)

    # 출력: return 매트릭스
    print("\n" + "=" * 90)
    print("RETURN by signal × dataset (KOSDAQ/KQ11 regime)")
    print("=" * 90)
    hdr = f"{'signal':<16}" + "".join(f"{n:>12}" for n in ds_order)
    print(hdr)
    for sig in SIGNALS:
        row = f"{sig['label']:<16}"
        for name in ds_order:
            row += f"{results[sig['label']][name]['return']:>+11.2%} "
        print(row)

    # Δret vs off
    print("\n" + "=" * 90)
    print("Δreturn vs off  (양수=개선)   [trades in brackets]")
    print("=" * 90)
    print(hdr)
    off = results["off"]
    for sig in SIGNALS:
        if sig["label"] == "off":
            continue
        row = f"{sig['label']:<16}"
        for name in ds_order:
            d = results[sig["label"]][name]["return"] - off[name]["return"]
            tr = results[sig["label"]][name]["trades"]
            row += f"{d:>+8.2%}[{tr:>2}] "
        print(row)

    # 판정
    print("\n" + "=" * 90)
    print("판정 (나쁜장 완화 + 좋은장 미악화)")
    print("=" * 90)
    for sig in SIGNALS:
        if sig["label"] == "off":
            continue
        bad_ok, good_ok, notes = True, True, []
        for name in ds_order:
            base = off[name]["return"]
            d = results[sig["label"]][name]["return"] - base
            if base < 0:  # 나쁜장
                if d <= 0:
                    bad_ok = False
                notes.append(f"{name}(bad Δ{d:+.1%})")
            else:  # 좋은장
                if d < -0.005:
                    good_ok = False
                notes.append(f"{name}(good Δ{d:+.1%})")
        verdict = "PASS" if (bad_ok and good_ok) else ("PARTIAL" if (bad_ok or good_ok) else "FAIL")
        print(f"  {sig['label']:<16} {verdict:<8} bad_ok={bad_ok} good_ok={good_ok}")


if __name__ == "__main__":
    main()
