"""breakout_52w (52주 신고가 돌파) 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.base import Position


def _make_minute_df(trade_dates, n_bars_per_day=390, afternoon_close_per_day=None):
    rows = []
    for d_idx, td in enumerate(trade_dates):
        ac = afternoon_close_per_day[d_idx] if afternoon_close_per_day else 10000.0
        for i in range(n_bars_per_day):
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


def _make_daily_df(history_high: float, today_high: float, n_history_days: int = 100):
    """과거 N일 daily + 오늘 1 row."""
    rows = []
    for i in range(n_history_days):
        rows.append({
            "stock_code": "TEST", "trade_date": f"202509{i:02d}"[:8] if i < 30 else f"202510{(i-29):02d}",
            "open": history_high * 0.95, "high": history_high,
            "low": history_high * 0.9, "close": history_high * 0.97,
            "volume": 100000.0,
        })
    rows.append({
        "stock_code": "TEST", "trade_date": "20260331",
        "open": history_high * 0.97, "high": today_high,
        "low": history_high * 0.95, "close": today_high,
        "volume": 100000.0,
    })
    return pd.DataFrame(rows)


def test_defaults():
    s = Breakout52wStrategy()
    assert s.name == "breakout_52w"
    assert s.hold_days == 2
    assert s.lookback_days == 252
    assert s.buffer_pct == 0.0


def test_prepare_features_columns():
    s = Breakout52wStrategy(lookback_days=20)
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[11000.0])
    daily = _make_daily_df(history_high=10500.0, today_high=11000.0,
                           n_history_days=30)
    feats = s.prepare_features(minute, daily)
    assert "prev_high" in feats.columns
    assert "close" in feats.columns
    assert "hhmm" in feats.columns


def test_entry_fires_on_breakout():
    s = Breakout52wStrategy(lookback_days=20, buffer_pct=0.0)
    # 분봉 close (11000) > prev_high (10500)
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[11000.0])
    daily = _make_daily_df(history_high=10500.0, today_high=11000.0,
                           n_history_days=30)
    feats = s.prepare_features(minute, daily)
    order = s.entry_signal(feats, bar_idx=350, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_below_high():
    s = Breakout52wStrategy(lookback_days=20)
    # 분봉 close (10300) < prev_high (10500)
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10300.0])
    daily = _make_daily_df(history_high=10500.0, today_high=10300.0,
                           n_history_days=30)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_entry_no_fire_before_window():
    s = Breakout52wStrategy(lookback_days=20)
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[11000.0])
    daily = _make_daily_df(history_high=10500.0, today_high=11000.0,
                           n_history_days=30)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=60, stock_code="TEST") is None


def test_exit_signal_holds_two_days():
    s = Breakout52wStrategy(lookback_days=20)
    minute = _make_minute_df(["20260331", "20260401", "20260402"],
                             afternoon_close_per_day=[11000.0, 11000.0, 11000.0])
    daily = _make_daily_df(history_high=10500.0, today_high=11000.0,
                           n_history_days=30)
    s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=11000.0,
                   quantity=10, entry_date="20260331")
    # 1일 경과 (bar 390 = 20260401 09:00) — 청산 안 함
    assert s.exit_signal(pos, pd.DataFrame(), bar_idx=390, current_price=11100.0) is None
    # 2일 경과 (bar 780 = 20260402 09:00) — 청산
    out = s.exit_signal(pos, pd.DataFrame(), bar_idx=780, current_price=11200.0)
    assert out is not None
    assert out.reason == "hold_limit"
