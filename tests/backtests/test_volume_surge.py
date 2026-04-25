"""거래량 급증 추격 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.volume_surge import VolumeSurgeStrategy
from backtests.strategies.base import Position


def _make_bars(closes, volumes, trade_date="20260401"):
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c, "high": c * 1.001, "low": c * 0.999,
            "close": c, "volume": v,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = VolumeSurgeStrategy()
    assert s.name == "volume_surge"
    assert s.hold_days == 0
    assert s.vol_lookback_bars == 10
    assert s.volume_mult == 3.0


def test_prepare_features_columns():
    s = VolumeSurgeStrategy()
    closes = [10000.0] * 60
    volumes = [100.0] * 60
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "vol_ratio" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    assert "bar_in_day" in feats.columns
    # 안정 거래량 → vol_ratio ≈ 1
    assert abs(feats["vol_ratio"].iloc[30] - 1.0) < 0.01


def test_entry_fires_on_volume_surge_with_price_up():
    s = VolumeSurgeStrategy(
        vol_lookback_bars=10, volume_mult=3.0,
        entry_window_start_bar=10, entry_window_end_bar=240,
    )
    closes = [10000.0] * 30 + [10100.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [500.0] + [100.0] * 10  # bar 30: 5x surge
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(feats, bar_idx=30, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_without_volume_surge():
    s = VolumeSurgeStrategy(volume_mult=5.0)
    closes = [10000.0] * 30 + [10100.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [200.0] + [100.0] * 10  # 2x — 5x 기준 미충족
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=30, stock_code="TEST") is None


def test_entry_no_fire_without_price_confirmation():
    s = VolumeSurgeStrategy(volume_mult=3.0)
    closes = [10000.0] * 30 + [9900.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [500.0] + [100.0] * 10
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=30, stock_code="TEST") is None


def test_entry_no_fire_before_warmup():
    s = VolumeSurgeStrategy(vol_lookback_bars=20, entry_window_start_bar=20)
    closes = [10000.0, 10100.0]
    volumes = [100.0, 500.0]
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=1, stock_code="TEST") is None


def test_entry_no_fire_after_window():
    s = VolumeSurgeStrategy(entry_window_end_bar=30)
    closes = [10000.0] * 50 + [10100.0] + [10000.0] * 10
    volumes = [100.0] * 50 + [500.0] + [100.0] * 10
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=50, stock_code="TEST") is None


def test_exit_tp_sl():
    s = VolumeSurgeStrategy(take_profit_pct=3.0, stop_loss_pct=-2.0)
    pos = Position(stock_code="TEST", entry_bar_idx=30, entry_price=10100.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=10500.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=9850.0).reason == "sl"
