"""상한가 따라잡기 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.limit_up_chase import LimitUpChaseStrategy
from backtests.strategies.base import Position


def _make_daily_df(prev_close: float):
    """전일 + 당일 일봉."""
    return pd.DataFrame([
        {"stock_code": "TEST", "trade_date": "20260331",
         "open": prev_close, "high": prev_close * 1.01, "low": prev_close * 0.99,
         "close": prev_close, "volume": 100000.0},
        {"stock_code": "TEST", "trade_date": "20260401",
         "open": prev_close, "high": prev_close * 1.30, "low": prev_close,
         "close": prev_close, "volume": 100000.0},
    ])


def _make_minute_df(closes, volumes, trade_date="20260401"):
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
    s = LimitUpChaseStrategy()
    assert s.name == "limit_up_chase"
    assert s.hold_days == 0
    assert s.chase_threshold_pct == 15.0
    assert s.limit_proximity_pct == 27.0


def test_prepare_features_columns():
    s = LimitUpChaseStrategy()
    minute = _make_minute_df([10000.0] * 60, [100.0] * 60)
    daily = _make_daily_df(prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    assert "prev_close" in feats.columns
    assert "price_change_pct" in feats.columns
    assert "vol_ratio" in feats.columns
    assert "close" in feats.columns
    assert "bar_in_day" in feats.columns
    # close 가 전일 동일 → price_change ≈ 0
    assert abs(feats["price_change_pct"].iloc[30]) < 0.01


def test_entry_fires_on_chase_with_volume():
    s = LimitUpChaseStrategy(
        chase_threshold_pct=15.0, limit_proximity_pct=27.0,
        vol_lookback_bars=10, volume_mult=3.0, entry_window_end_bar=240,
    )
    # 점진 상승 → bar 30 에서 +20% 도달 + 거래량 5x
    closes = [10000.0 + i * 30 for i in range(30)]   # 10000→10870 (+8.7%)
    closes += [12000.0]                                # bar 30: +20% 도달
    closes += [12000.0] * 10
    volumes = [100.0] * 30 + [500.0] + [100.0] * 10
    minute = _make_minute_df(closes, volumes)
    daily = _make_daily_df(prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    order = s.entry_signal(feats, bar_idx=30, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_below_chase_threshold():
    s = LimitUpChaseStrategy(chase_threshold_pct=15.0)
    # 현재 close +5% 만 — 임계 미충족
    closes = [10000.0] * 30 + [10500.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [500.0] + [100.0] * 10
    minute = _make_minute_df(closes, volumes)
    daily = _make_daily_df(prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=30, stock_code="TEST") is None


def test_entry_no_fire_above_limit_proximity():
    s = LimitUpChaseStrategy(limit_proximity_pct=27.0)
    # +28% — 한도 직전이라 회피
    closes = [10000.0] * 30 + [12800.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [500.0] + [100.0] * 10
    minute = _make_minute_df(closes, volumes)
    daily = _make_daily_df(prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=30, stock_code="TEST") is None


def test_entry_no_fire_without_volume_surge():
    s = LimitUpChaseStrategy(volume_mult=5.0)
    # 가격은 +20% 도달했으나 거래량 평범
    closes = [10000.0] * 30 + [12000.0] + [10000.0] * 10
    volumes = [100.0] * 41
    minute = _make_minute_df(closes, volumes)
    daily = _make_daily_df(prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=30, stock_code="TEST") is None


def test_entry_no_fire_after_window():
    s = LimitUpChaseStrategy(entry_window_end_bar=30)
    closes = [10000.0] * 50 + [12000.0] + [10000.0] * 10
    volumes = [100.0] * 50 + [500.0] + [100.0] * 10
    minute = _make_minute_df(closes, volumes)
    daily = _make_daily_df(prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=50, stock_code="TEST") is None


def test_exit_tp_sl():
    s = LimitUpChaseStrategy(take_profit_pct=4.0, stop_loss_pct=-2.5)
    pos = Position(stock_code="TEST", entry_bar_idx=30, entry_price=12000.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=12500.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=11650.0).reason == "sl"
