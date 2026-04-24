"""VWAP 반등 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.vwap_bounce import VWAPBounceStrategy
from backtests.strategies.base import Position


def _make_bars(trade_date: str, closes, volumes=None):
    if volumes is None:
        volumes = [1000.0] * len(closes)
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c,
            "high": c * 1.001,
            "low": c * 0.999,
            "close": c,
            "volume": v,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = VWAPBounceStrategy()
    assert s.name == "vwap_bounce"
    assert s.hold_days == 0
    assert s.vwap_deviation_pct == -1.0
    assert s.take_profit_pct == 2.0


def test_prepare_features_produces_vwap_columns():
    s = VWAPBounceStrategy()
    closes = [10000.0] * 100
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_vwap" in feats.columns
    assert "deviation_pct" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    # 안정 가격 → deviation 0 근접
    assert abs(feats["deviation_pct"].iloc[50]) < 0.01


def test_entry_fires_on_deviation_and_rebound():
    s = VWAPBounceStrategy(
        vwap_deviation_pct=-1.0, rebound_min_bars=3, entry_window_end_bar=240
    )
    closes = [10000.0] * 30 + [9800.0] * 5 + [9850.0] + [10000.0] * 10
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(feats, bar_idx=35, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_without_deviation():
    s = VWAPBounceStrategy(vwap_deviation_pct=-2.0)
    closes = [10000.0] * 30 + [9950.0] * 5 + [9960.0] + [10000.0] * 10
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=35, stock_code="TEST") is None


def test_entry_no_fire_without_rebound():
    s = VWAPBounceStrategy(vwap_deviation_pct=-1.0)
    closes = [10000.0] * 30 + [9800.0, 9790.0, 9780.0, 9770.0, 9760.0, 9750.0] + [9700.0] * 10
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=35, stock_code="TEST") is None


def test_exit_tp_sl():
    s = VWAPBounceStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=35, entry_price=9850.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=10050.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=9700.0).reason == "sl"
