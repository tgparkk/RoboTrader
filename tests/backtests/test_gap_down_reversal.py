"""갭다운 역행 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.gap_down_reversal import GapDownReversalStrategy
from backtests.strategies.base import Position


def _make_daily_df(stock_code: str, close_prev: float):
    """전일 close 가 close_prev 인 합성 일봉 (1행, 전일 날짜 20260331)."""
    return pd.DataFrame([{
        "stock_code": stock_code,
        "trade_date": "20260331",
        "open": close_prev,
        "high": close_prev * 1.01,
        "low": close_prev * 0.99,
        "close": close_prev,
        "volume": 100000.0,
    }])


def _make_minute_df(
    stock_code: str,
    trade_date: str,
    n_bars: int,
    open_price: float,
    day_low: float = None,
    rebound_bar: int = None,
    rebound_price: float = None,
):
    """합성 분봉. open_price 에서 시작. bar 0~9 에서 day_low 로 하향, 이후 평탄."""
    if day_low is None:
        day_low = open_price * 0.99
    rows = []
    for i in range(n_bars):
        hh = 9 + i // 60
        mm = i % 60
        if i < 10:
            price = open_price - (open_price - day_low) * (i / 9)
        else:
            price = day_low
        if rebound_bar is not None and i == rebound_bar and rebound_price is not None:
            price = rebound_price
        rows.append({
            "stock_code": stock_code,
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": price,
            "high": price * 1.001,
            "low": price * 0.999,
            "close": price,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_defaults_loadable():
    s = GapDownReversalStrategy()
    assert s.name == "gap_down_reversal"
    assert s.hold_days == 0
    assert s.gap_threshold_pct == -2.0
    assert s.reversal_threshold_pct == 1.0


def test_prepare_features_computes_gap_and_rolling_low():
    s = GapDownReversalStrategy()
    minute = _make_minute_df("TEST", "20260401", n_bars=30, open_price=9800.0, day_low=9700.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    # gap_pct = (9800 - 10000) / 10000 * 100 = -2%
    assert abs(features["gap_pct"].iloc[0] - (-2.0)) < 0.01
    assert "day_low_so_far" in features.columns
    assert features["day_low_so_far"].iloc[15] <= 9700.0
    assert "rebound_pct" in features.columns


def test_entry_signal_fires_when_gap_down_and_rebound():
    s = GapDownReversalStrategy(
        gap_threshold_pct=-2.0, reversal_threshold_pct=1.0, entry_window_end_bar=60
    )
    # open 9800 (-2% gap), day_low 9700, rebound at bar 20 to 9800 (~+1.03%)
    minute = _make_minute_df(
        "TEST", "20260401", n_bars=60, open_price=9800.0,
        day_low=9700.0, rebound_bar=20, rebound_price=9800.0,
    )
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    order = s.entry_signal(features, bar_idx=20, stock_code="TEST")
    assert order is not None


def test_entry_signal_no_fire_without_gap_down():
    s = GapDownReversalStrategy(gap_threshold_pct=-2.0)
    # open 9950 (-0.5% gap) → 갭 기준 미충족
    minute = _make_minute_df("TEST", "20260401", n_bars=60, open_price=9950.0, day_low=9900.0, rebound_bar=20, rebound_price=10000.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    assert s.entry_signal(features, bar_idx=20, stock_code="TEST") is None


def test_entry_signal_no_fire_after_window_end():
    s = GapDownReversalStrategy(entry_window_end_bar=30)
    minute = _make_minute_df("TEST", "20260401", n_bars=100, open_price=9800.0, day_low=9700.0, rebound_bar=50, rebound_price=9800.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    # bar 50 은 window(30) 이후
    assert s.entry_signal(features, bar_idx=50, stock_code="TEST") is None


def test_entry_signal_no_fire_without_rebound():
    s = GapDownReversalStrategy(reversal_threshold_pct=2.0)
    # rebound 0.03% 만 → 2% 기준 미충족
    minute = _make_minute_df("TEST", "20260401", n_bars=60, open_price=9800.0, day_low=9700.0, rebound_bar=20, rebound_price=9703.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    assert s.entry_signal(features, bar_idx=20, stock_code="TEST") is None


def test_exit_signal_tp_sl():
    s = GapDownReversalStrategy(take_profit_pct=3.0, stop_loss_pct=-2.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=20, entry_price=9800.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # +3.5% from 9800 = 10143 → TP
    assert s.exit_signal(pos, features, bar_idx=30, current_price=10143.0).reason == "tp"
    # -2.5% = 9555 → SL
    assert s.exit_signal(pos, features, bar_idx=30, current_price=9555.0).reason == "sl"
