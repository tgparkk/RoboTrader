"""볼린저 하단 반등 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.bb_lower_bounce import BBLowerBounceStrategy
from backtests.strategies.base import Position


def _make_bars(closes, trade_date="20260401"):
    rows = []
    for i, c in enumerate(closes):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c, "high": c * 1.001, "low": c * 0.999,
            "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = BBLowerBounceStrategy()
    assert s.name == "bb_lower_bounce"
    assert s.hold_days == 0
    assert s.bb_period == 20
    assert s.bb_num_std == 2.0


def test_prepare_features_has_bb_columns():
    s = BBLowerBounceStrategy()
    closes = [10000.0 + (i % 10 - 5) * 10 for i in range(100)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_lower" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    # 초반 20 bars 는 NaN (min_periods=20)
    assert pd.isna(feats["prev_lower"].iloc[15])
    assert not pd.isna(feats["prev_lower"].iloc[50])


def test_entry_fires_on_bb_lower_bounce():
    s = BBLowerBounceStrategy(bb_period=20, bb_num_std=2.0, entry_window_end_bar=240)
    closes = [10000.0] * 41 + [9800.0] * 5 + [9850.0] + [10000.0] * 10
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(feats, bar_idx=46, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_without_lower_band_break():
    s = BBLowerBounceStrategy()
    closes = [10000.0] * 60
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=50, stock_code="TEST") is None


def test_entry_no_fire_without_rebound():
    s = BBLowerBounceStrategy()
    closes = [10000.0] * 40 + [9900, 9800, 9700, 9600, 9500, 9400, 9300, 9200]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=46, stock_code="TEST") is None


def test_exit_tp_sl():
    s = BBLowerBounceStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=46, entry_price=9850.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=60, current_price=10050.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=60, current_price=9700.0).reason == "sl"
