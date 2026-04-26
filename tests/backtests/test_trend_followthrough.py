"""trend_followthrough (5일 고점 돌파) 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy
from backtests.strategies.base import Position


def _make_minute_df(trade_dates, afternoon_close_per_day=None):
    rows = []
    for d_idx, td in enumerate(trade_dates):
        ac = afternoon_close_per_day[d_idx] if afternoon_close_per_day else 10000.0
        for i in range(390):
            hh = 9 + i // 60
            mm = i % 60
            close = ac if i >= 300 else 10000.0
            rows.append({
                "stock_code": "TEST",
                "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": close, "high": close * 1.001, "low": close * 0.999,
                "close": close, "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_daily_df(history_highs: list, target_dates: list):
    """history_highs 는 과거 N일 high 값 리스트 (가장 오래된 → 최근순)."""
    rows = []
    for i, h in enumerate(history_highs):
        rows.append({
            "stock_code": "TEST", "trade_date": f"2026031{i+1:01d}",
            "open": h * 0.99, "high": h, "low": h * 0.97, "close": h * 0.98,
            "volume": 100000.0,
        })
    for td in target_dates:
        rows.append({
            "stock_code": "TEST", "trade_date": td,
            "open": 10000.0, "high": 10100.0, "low": 9900.0, "close": 10000.0,
            "volume": 100000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = TrendFollowthroughStrategy()
    assert s.name == "trend_followthrough"
    assert s.hold_days == 2
    assert s.lookback_days == 5


def test_prepare_features_columns():
    s = TrendFollowthroughStrategy(lookback_days=5)
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10600.0])
    daily = _make_daily_df([10500, 10400, 10300, 10200, 10100], ["20260331"])
    feats = s.prepare_features(minute, daily)
    assert "prev_high" in feats.columns
    assert "close" in feats.columns
    assert "hhmm" in feats.columns


def test_entry_fires_on_5d_high_break():
    s = TrendFollowthroughStrategy(lookback_days=5, buffer_pct=0.0)
    # 5일 high = max(10500..10100) = 10500. 분봉 close 10600 → 돌파
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10600.0])
    daily = _make_daily_df([10500, 10400, 10300, 10200, 10100], ["20260331"])
    feats = s.prepare_features(minute, daily)
    order = s.entry_signal(feats, bar_idx=350, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_below_high():
    s = TrendFollowthroughStrategy(lookback_days=5)
    # 분봉 close 10300 < 5일 high 10500
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10300.0])
    daily = _make_daily_df([10500, 10400, 10300, 10200, 10100], ["20260331"])
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_entry_no_fire_before_window():
    s = TrendFollowthroughStrategy(lookback_days=5)
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10600.0])
    daily = _make_daily_df([10500, 10400, 10300, 10200, 10100], ["20260331"])
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=60, stock_code="TEST") is None


def test_exit_signal_holds_two_days():
    s = TrendFollowthroughStrategy()
    minute = _make_minute_df(["20260331", "20260401", "20260402"],
                             afternoon_close_per_day=[10600.0, 10600.0, 10600.0])
    daily = _make_daily_df([10500, 10400, 10300, 10200, 10100],
                           ["20260331", "20260401", "20260402"])
    s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10600.0,
                   quantity=10, entry_date="20260331")
    assert s.exit_signal(pos, pd.DataFrame(), bar_idx=390, current_price=10700.0) is None
    out = s.exit_signal(pos, pd.DataFrame(), bar_idx=780, current_price=10800.0)
    assert out is not None
    assert out.reason == "hold_limit"
