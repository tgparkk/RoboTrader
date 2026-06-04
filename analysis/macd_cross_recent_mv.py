"""macd_cross 멀티버스 5~6월 확장 검증 (손절 + 레짐).

기존 하니스(backtests/multiverse/macd_cross_*)는 OOS_TEST_END=20260424 까지만
평가한다. 정작 사용자가 우려하는 5~6월 손실 구간이 빠져 있어, 동일 방법론
(Stage2 universe, 미래참조 금지, 엔진 마찰)으로 'recent'(20260425~20260604)
데이터셋을 추가해 SL(10% 포함)·레짐 신호를 재검증한다.

대조용으로 oos(20260301~20260424)도 같이 평가해 이전 summary 수치 재현성 확인.
"""
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.common.data_loader import (
    load_minute_df, load_daily_df, load_index_df,
)
from backtests.multiverse.universe import select_top_universe
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, _trading_days_count,
)
from backtests.strategies.macd_cross_exit_overlay import MACDCrossExitOverlayStrategy
from backtests.strategies.macd_cross_regime_filter import MACDCrossRegimeFilterStrategy

BEST = {"fast_period": 14, "slow_period": 34, "signal_period": 12, "entry_hhmm_min": 1430}
DAILY_START = "20250101"

WINDOWS = [
    ("oos",    "20260301", "20260424"),   # 대조 (이전 summary 와 비교)
    ("recent", "20260425", "20260604"),   # 신규 — 5~6월 손실 구간
]

SL_GRID = [None, 0.03, 0.05, 0.07, 0.10]   # 10% (광역 재난손절) 추가
REGIME_CELLS = [
    {"label": "off",            "enabled": False, "signal_type": "ma20_below_prev", "threshold": None},
    {"label": "5d_drop_-2pct",  "enabled": True,  "signal_type": "5d_return_drop",  "threshold": -0.02},
    {"label": "5d_drop_-3pct",  "enabled": True,  "signal_type": "5d_return_drop",  "threshold": -0.03},
    {"label": "20d_neg_-3pct",  "enabled": True,  "signal_type": "20d_return_neg",  "threshold": -0.03},
]


def build_datasets() -> Dict[str, Dataset]:
    uni = select_top_universe(
        fold_train_start="20250301", fold_test_end="20260228",
        n_stocks=30, min_days_present=120,
    )
    full_start = min(w[1] for w in WINDOWS)
    full_end = max(w[2] for w in WINDOWS)
    minute_df = load_minute_df(uni, full_start, full_end)
    daily_df = load_daily_df(uni, DAILY_START, full_end)
    def _norm_index(code):
        raw = load_index_df(code, DAILY_START, full_end)
        return pd.DataFrame({
            "trade_date": raw["trade_date"].astype(str),
            "close": raw["close"].astype(float),
        }).sort_values("trade_date").reset_index(drop=True)
    kospi_norm = _norm_index("KS11")
    kosdaq_norm = _norm_index("KQ11")

    minute_full = {c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True) for c in uni}
    daily_full = {c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True) for c in uni}

    out: Dict[str, Dataset] = {}
    for name, start, end in WINDOWS:
        m_by = {
            c: minute_full[c][
                (minute_full[c]["trade_date"] >= start) & (minute_full[c]["trade_date"] <= end)
            ].reset_index(drop=True) for c in uni
        }
        d_by = {c: daily_full[c][daily_full[c]["trade_date"] <= end].reset_index(drop=True) for c in uni}
        nonempty = [c for c in uni if len(m_by[c]) > 0]
        out[name] = Dataset(
            name=name, minute_start=start, minute_end=end, daily_start=DAILY_START,
            minute_by_code={c: m_by[c] for c in nonempty},
            daily_by_code={c: d_by[c] for c in nonempty},
            universe=nonempty, kospi_daily_df=kospi_norm,
        )
        out[name].kosdaq_daily_df = kosdaq_norm  # 동적 부착 (regime 비교용)
        print(f"  {name}: {start}~{end}, {len(nonempty)} stocks, {_trading_days_count(m_by)} days")
    return out


def evaluate(strategy, ds: Dataset) -> Dict:
    eng = BacktestEngine(
        strategy=strategy, initial_capital=10_000_000,
        universe=ds.universe, minute_df_by_code=ds.minute_by_code,
        daily_df_by_code=ds.daily_by_code,
    )
    result = eng.run()
    return build_cell_kpis(
        equity=result.equity_curve, trades=result.trades,
        trading_days=_trading_days_count(ds.minute_by_code),
    )


def fmt(k: Dict) -> str:
    return (f"calmar={k['calmar']:>+8.2f}  ret={k['return']:>+7.2%}  "
            f"mdd={k['mdd']:>+6.2%}  win={k['win_rate']:>5.1%}  "
            f"trades={k['trades']:>3}  top1={k['top1_share']:>+6.2f}  "
            f"maxloss={k['max_consec_loss']:>2}")


def main():
    print("[recent-mv] datasets 로드...")
    ds = build_datasets()

    for name in ("oos", "recent"):
        d = ds[name]
        print(f"\n{'='*100}\n[{name}] {d.minute_start}~{d.minute_end}\n{'='*100}")

        print("\n-- SL sweep (tp=off, reversal=off) --")
        base = None
        for sl in SL_GRID:
            strat = MACDCrossExitOverlayStrategy(sl_pct=sl, tp_pct=None, intraday_reversal=False, **BEST)
            k = evaluate(strat, d)
            if sl is None:
                base = k
            tag = "off " if sl is None else f"{sl:.0%}"
            dret = "" if base is None or sl is None else f"  Δret={k['return']-base['return']:>+6.2%}"
            print(f"  SL={tag}: {fmt(k)}{dret}")

        for idx_label, idx_df in (("KOSPI/KS11", d.kospi_daily_df),
                                  ("KOSDAQ/KQ11", d.kosdaq_daily_df)):
            print(f"\n-- regime filter on {idx_label} (signal-based entry block) --")
            for rc in REGIME_CELLS:
                strat = MACDCrossRegimeFilterStrategy(
                    regime_filter_enabled=rc["enabled"],
                    kospi_daily_df=idx_df if rc["enabled"] else None,
                    signal_type=rc["signal_type"], signal_threshold=rc["threshold"], **BEST,
                )
                k = evaluate(strat, d)
                print(f"  {rc['label']:<16}: {fmt(k)}")


if __name__ == "__main__":
    main()
