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


def test_tp_triggers_when_high_breaks_threshold():
    minute = _make_minute_df(["20260331", "20260401"])
    minute.loc[400, "high"] = 10600.0  # +6%
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])
    s = MACDCrossExitOverlayStrategy(tp_pct=0.05)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=10500.0)
    assert out is not None
    assert out.reason == "tp"


def test_sl_takes_priority_over_tp_in_same_bar():
    """한 분봉에서 low/high 둘 다 트리거 시 SL 우선 (보수적)."""
    minute = _make_minute_df(["20260331", "20260401"])
    minute.loc[400, "high"] = 10600.0  # +6% TP=5% 트리거
    minute.loc[400, "low"] = 9300.0    # -7% SL=5% 트리거
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])
    s = MACDCrossExitOverlayStrategy(sl_pct=0.05, tp_pct=0.05)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=10000.0)
    assert out is not None
    assert out.reason == "sl"  # SL 우선


def test_intraday_reversal_at_last_bar_of_d_plus_1():
    """D+1 의 last bar 에서 today_hist<0 → reason='macd_reversal'."""
    # 일봉을 일부러 하락시켜 D+1 의 hist 가 음수가 되도록
    minute = _make_minute_df(["20260331", "20260401"])
    closes = [10000.0] * 50 + [9000.0] * 5  # 끝에 급락 → D+1 hist 음수 가능
    dates = [f"2026{(2 + (i // 30)):02d}{(i % 30) + 1:02d}" for i in range(50)]
    dates += ["20260331", "20260401"] + [f"202604{i+2:02d}" for i in range(3)]
    # closes 길이 55, dates 55 매핑
    daily = _make_daily_df(closes, dates)

    s = MACDCrossExitOverlayStrategy(intraday_reversal=True,
                                      fast_period=3, slow_period=6, signal_period=2)
    feats = s.prepare_features(minute, daily)

    # D+1 의 last bar = bar_idx 779 (390 + 389)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")

    # today_hist 가 음수인지 사전 확인 (테스트 진단용)
    today_hist_at_d1 = feats["today_hist"].iloc[779]
    assert today_hist_at_d1 < 0, f"테스트 setup 실패: today_hist={today_hist_at_d1}"

    out = s.exit_signal(pos, feats, bar_idx=779, current_price=9000.0)
    assert out is not None
    assert out.reason == "macd_reversal"


def test_intraday_reversal_skipped_on_entry_day():
    """진입일 (D) last bar 에서 today_hist<0 이어도 미발동 — D+1 부터만."""
    minute = _make_minute_df(["20260331", "20260401"])
    closes = [10000.0] * 50 + [9000.0] * 5
    dates = [f"2026{(2 + (i // 30)):02d}{(i % 30) + 1:02d}" for i in range(50)]
    dates += ["20260331", "20260401"] + [f"202604{i+2:02d}" for i in range(3)]
    daily = _make_daily_df(closes, dates)

    s = MACDCrossExitOverlayStrategy(intraday_reversal=True,
                                      fast_period=3, slow_period=6, signal_period=2)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    # D 의 last bar = 389
    out = s.exit_signal(pos, feats, bar_idx=389, current_price=10000.0)
    assert out is None  # 진입일에는 미발동


def test_intraday_reversal_skipped_mid_day():
    """D+1 의 mid-day bar 에서는 미발동 — last bar of day 만 평가."""
    minute = _make_minute_df(["20260331", "20260401"])
    closes = [10000.0] * 50 + [9000.0] * 5
    dates = [f"2026{(2 + (i // 30)):02d}{(i % 30) + 1:02d}" for i in range(50)]
    dates += ["20260331", "20260401"] + [f"202604{i+2:02d}" for i in range(3)]
    daily = _make_daily_df(closes, dates)

    s = MACDCrossExitOverlayStrategy(intraday_reversal=True,
                                      fast_period=3, slow_period=6, signal_period=2)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    # D+1 의 mid bar = 500 (last bar 779 가 아님)
    out = s.exit_signal(pos, feats, bar_idx=500, current_price=9000.0)
    assert out is None
