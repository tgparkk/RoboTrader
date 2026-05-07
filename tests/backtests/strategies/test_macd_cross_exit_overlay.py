"""macd_cross exit overlay wrapper 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.base import Position
from backtests.strategies.macd_cross import MACDCrossStrategy
from backtests.strategies.macd_cross_exit_overlay import MACDCrossExitOverlayStrategy


def _make_minute_df(trade_dates, close_per_day=None, base=10000.0):
    """390 bars × N day. close_per_day[i] 가 None 이면 base 사용."""
    rows = []
    for d_idx, td in enumerate(trade_dates):
        c = (close_per_day[d_idx] if close_per_day else base)
        for i in range(390):
            hh = 9 + i // 60
            mm = i % 60
            rows.append({
                "stock_code": "TEST", "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": c, "high": c * 1.001, "low": c * 0.999,
                "close": c, "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_daily_df(closes, dates):
    return pd.DataFrame([{
        "stock_code": "TEST", "trade_date": d,
        "open": c, "high": c * 1.005, "low": c * 0.995,
        "close": c, "volume": 100000.0,
    } for d, c in zip(dates, closes)])


def test_no_overlay_matches_base_exit():
    """모든 overlay off → base 와 동일하게 hold_days=2 까지 None 반환."""
    minute = _make_minute_df(["20260331", "20260401", "20260402"])
    closes = [10000.0] * 60
    dates = [f"2026{(1 + i // 30):02d}{(i % 30) + 1:02d}" for i in range(57)]
    daily = _make_daily_df(closes, dates + ["20260331", "20260401", "20260402"])

    base = MACDCrossStrategy()
    wrap = MACDCrossExitOverlayStrategy(sl_pct=None, tp_pct=None, intraday_reversal=False)
    base.prepare_features(minute, daily)
    wrap.prepare_features(minute, daily)

    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    feats_dummy = pd.DataFrame()
    # D+1 동안 (bar 390~779) 둘 다 None
    assert base.exit_signal(pos, feats_dummy, bar_idx=500, current_price=10000.0) is None
    assert wrap.exit_signal(pos, feats_dummy, bar_idx=500, current_price=10000.0) is None
    # D+2 (bar 780+) 둘 다 hold_limit
    base_out = base.exit_signal(pos, feats_dummy, bar_idx=780, current_price=10000.0)
    wrap_out = wrap.exit_signal(pos, feats_dummy, bar_idx=780, current_price=10000.0)
    assert base_out.reason == "hold_limit"
    assert wrap_out.reason == "hold_limit"


def test_sl_triggers_when_low_breaks_threshold():
    """SL=5%, 보유 중 low 가 entry × 0.94 까지 떨어지면 reason='sl'."""
    minute = _make_minute_df(["20260331", "20260401"])
    # entry 가격 10000, low 9400 = -6% (5% 깨짐)
    minute.loc[400, "low"] = 9400.0
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])

    s = MACDCrossExitOverlayStrategy(sl_pct=0.05)
    s.prepare_features(minute, daily)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=9500.0)
    assert out is not None
    assert out.reason == "sl"


def test_sl_no_trigger_when_low_above_threshold():
    """SL=5%, low 가 9600 (4% 하락) 이면 미발동."""
    minute = _make_minute_df(["20260331", "20260401"])
    minute.loc[400, "low"] = 9600.0
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])

    s = MACDCrossExitOverlayStrategy(sl_pct=0.05)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=9700.0)
    assert out is None
