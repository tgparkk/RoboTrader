"""갭업 추격 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.gap_up_chase import GapUpChaseStrategy
from backtests.strategies.base import Position


BARS_PER_TRADING_DAY = 390


def _make_daily_df(stock_code: str, close_prev: float, avg_bar_vol: float = 100.0):
    """전일 일봉 + 과거 5일 (daily volume = avg_bar_vol × 390, realistic total)."""
    rows = []
    dates = ["20260326", "20260327", "20260328", "20260329", "20260330", "20260331"]
    for d in dates:
        rows.append({
            "stock_code": stock_code,
            "trade_date": d,
            "open": close_prev,
            "high": close_prev * 1.01,
            "low": close_prev * 0.99,
            "close": close_prev,
            "volume": avg_bar_vol * BARS_PER_TRADING_DAY,  # realistic daily total
        })
    return pd.DataFrame(rows)


def _make_minute_df(
    stock_code: str,
    trade_date: str,
    n_bars: int,
    open_price: float,
    high_volume_bar: int = None,
    high_volume_mult: float = 5.0,
    base_vol: float = 100.0,
):
    rows = []
    for i in range(n_bars):
        hh = 9 + i // 60
        mm = i % 60
        vol = base_vol
        if high_volume_bar is not None and i == high_volume_bar:
            vol = base_vol * high_volume_mult
        rows.append({
            "stock_code": stock_code,
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": open_price,
            "high": open_price * 1.002,
            "low": open_price * 0.998,
            "close": open_price,
            "volume": vol,
        })
    return pd.DataFrame(rows)


def test_defaults_loadable():
    s = GapUpChaseStrategy()
    assert s.name == "gap_up_chase"
    assert s.hold_days == 0
    assert s.gap_threshold_pct == 3.0
    assert s.volume_mult == 2.0


def test_prepare_features_computes_gap_and_volume_ratio():
    s = GapUpChaseStrategy()
    minute = _make_minute_df("TEST", "20260401", n_bars=30, open_price=10300.0, base_vol=100.0)
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_bar_vol=100.0)
    features = s.prepare_features(minute, daily)
    # gap = (10300 - 10000) / 10000 * 100 = +3%
    assert abs(features["gap_pct"].iloc[0] - 3.0) < 0.01
    assert "vol_ratio" in features.columns
    assert "close" in features.columns
    assert "bar_in_day" in features.columns
    # daily_avg_vol / 390 = 100. bar_vol = 100 → vol_ratio = 1.0
    assert abs(features["vol_ratio"].iloc[10] - 1.0) < 0.01


def test_entry_signal_fires_on_gap_up_and_volume_surge():
    s = GapUpChaseStrategy(
        gap_threshold_pct=3.0, volume_mult=2.0, entry_window_end_bar=30
    )
    # open 10300 (+3% gap), bar 15 거래량 5× → vol_ratio 5.0 → 매수
    minute = _make_minute_df(
        "TEST", "20260401", n_bars=30, open_price=10300.0,
        high_volume_bar=15, high_volume_mult=5.0, base_vol=100.0,
    )
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_bar_vol=100.0)
    features = s.prepare_features(minute, daily)
    order = s.entry_signal(features, bar_idx=15, stock_code="TEST")
    assert order is not None


def test_entry_signal_no_fire_without_gap_up():
    s = GapUpChaseStrategy(gap_threshold_pct=3.0)
    # open 10100 (+1% gap) → 3% 기준 미충족
    minute = _make_minute_df(
        "TEST", "20260401", n_bars=30, open_price=10100.0,
        high_volume_bar=15, high_volume_mult=5.0, base_vol=100.0,
    )
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_bar_vol=100.0)
    features = s.prepare_features(minute, daily)
    assert s.entry_signal(features, bar_idx=15, stock_code="TEST") is None


def test_entry_signal_no_fire_without_volume_surge():
    s = GapUpChaseStrategy(volume_mult=5.0)
    # bar 15 vol 2× (200/100 = 2.0) → 5.0 기준 미충족
    minute = _make_minute_df(
        "TEST", "20260401", n_bars=30, open_price=10300.0,
        high_volume_bar=15, high_volume_mult=2.0, base_vol=100.0,
    )
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_bar_vol=100.0)
    features = s.prepare_features(minute, daily)
    assert s.entry_signal(features, bar_idx=15, stock_code="TEST") is None


def test_entry_signal_no_fire_after_window():
    s = GapUpChaseStrategy(entry_window_end_bar=15)
    minute = _make_minute_df(
        "TEST", "20260401", n_bars=60, open_price=10300.0,
        high_volume_bar=30, high_volume_mult=5.0, base_vol=100.0,
    )
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_bar_vol=100.0)
    features = s.prepare_features(minute, daily)
    assert s.entry_signal(features, bar_idx=30, stock_code="TEST") is None


def test_exit_signal_tp_sl():
    s = GapUpChaseStrategy(take_profit_pct=4.0, stop_loss_pct=-2.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=15, entry_price=10300.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # +4.5% from 10300 ≈ 10763 → TP
    assert s.exit_signal(pos, features, bar_idx=30, current_price=10763.0).reason == "tp"
    # -2.5% ≈ 10042 → SL
    assert s.exit_signal(pos, features, bar_idx=30, current_price=10042.0).reason == "sl"
