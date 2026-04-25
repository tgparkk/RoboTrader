"""close_to_open (강한 종가 매수 → 익일 시가 매도) 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.close_to_open import CloseToOpenStrategy
from backtests.strategies.base import Position


def _make_minute_df(trade_dates, n_bars_per_day=390, base_open=10000.0,
                    afternoon_close_per_day=None):
    """여러 거래일 분봉 DF."""
    rows = []
    for d_idx, td in enumerate(trade_dates):
        ac = (afternoon_close_per_day[d_idx]
              if afternoon_close_per_day else base_open)
        for i in range(n_bars_per_day):
            hh = 9 + i // 60
            mm = i % 60
            close = ac if i >= 300 else base_open
            rows.append({
                "stock_code": "TEST",
                "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": close, "high": close * 1.001, "low": close * 0.999,
                "close": close, "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_daily_df(trade_dates, prev_close: float, today_close: float):
    rows = [{
        "stock_code": "TEST", "trade_date": "20260330",
        "open": prev_close, "high": prev_close, "low": prev_close,
        "close": prev_close, "volume": 100000.0,
    }]
    for td in trade_dates:
        rows.append({
            "stock_code": "TEST", "trade_date": td,
            "open": prev_close, "high": today_close * 1.01, "low": prev_close * 0.99,
            "close": today_close, "volume": 100000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = CloseToOpenStrategy()
    assert s.name == "close_to_open"
    assert s.hold_days == 1
    assert s.min_change_pct == 3.0
    assert s.entry_hhmm_min == 1450


def test_prepare_features_columns():
    s = CloseToOpenStrategy()
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10500.0])
    daily = _make_daily_df(["20260331"], prev_close=10000.0, today_close=10500.0)
    feats = s.prepare_features(minute, daily)
    assert "today_change_pct" in feats.columns
    assert "hhmm" in feats.columns
    assert "close" in feats.columns


def test_entry_fires_at_1450_with_strong_close():
    s = CloseToOpenStrategy(min_change_pct=3.0)
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10500.0])  # +5%
    daily = _make_daily_df(["20260331"], prev_close=10000.0, today_close=10500.0)
    feats = s.prepare_features(minute, daily)
    # bar 350 = 14:50
    order = s.entry_signal(feats, bar_idx=350, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_before_window():
    s = CloseToOpenStrategy()
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10500.0])
    daily = _make_daily_df(["20260331"], prev_close=10000.0, today_close=10500.0)
    feats = s.prepare_features(minute, daily)
    # bar 60 (10:00) — 진입 윈도우 이전
    assert s.entry_signal(feats, bar_idx=60, stock_code="TEST") is None


def test_entry_no_fire_with_weak_close():
    s = CloseToOpenStrategy(min_change_pct=3.0)
    # +1% 만 — 임계 미충족
    minute = _make_minute_df(["20260331"], afternoon_close_per_day=[10100.0])
    daily = _make_daily_df(["20260331"], prev_close=10000.0, today_close=10100.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_exit_signal_holds_one_day():
    s = CloseToOpenStrategy()
    minute = _make_minute_df(["20260331", "20260401"],
                             afternoon_close_per_day=[10500.0, 10500.0])
    daily = _make_daily_df(["20260331", "20260401"], prev_close=10000.0,
                           today_close=10500.0)
    s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10500.0,
                   quantity=10, entry_date="20260331")
    # 같은 날 (bar 380) — 청산 안 함
    assert s.exit_signal(pos, pd.DataFrame(), bar_idx=380, current_price=10510.0) is None
    # 다음 날 첫 bar (bar 390) — 청산
    out = s.exit_signal(pos, pd.DataFrame(), bar_idx=390, current_price=10550.0)
    assert out is not None
    assert out.reason == "hold_limit"
