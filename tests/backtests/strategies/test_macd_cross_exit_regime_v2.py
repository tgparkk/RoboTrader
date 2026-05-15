"""macd_cross exit_regime_v2 wrapper 단위 테스트 (TDD RED→GREEN).

3 family 트리거:
- A) Trailing stop (high-water 기반)
- B) Intraday MACD reversal 확장 (eval_hhmm + threshold + min_hold)
- C) Hold-day 차등 stop (D+1 vs D+2)

라이브 동등성: family='off' → 기존 MACDCrossStrategy 와 동일.
"""
import pandas as pd
import pytest

from backtests.strategies.base import Position
from backtests.strategies.macd_cross import MACDCrossStrategy
from backtests.strategies.macd_cross_exit_overlay import MACDCrossExitOverlayStrategy
from backtests.strategies.macd_cross_exit_regime_v2 import MACDCrossExitRegimeV2Strategy


# ---------- fixtures ----------

ENTRY_DATES = ["20260331", "20260401", "20260402"]
# warm-up 50 일 + D-1 + D + D+1 + D+2 + D+3 = 55 dates (slow=6 + signal=2 충분)
DAILY_DATES = (
    [f"2026{(1 + (i // 30)):02d}{(i % 30) + 1:02d}" for i in range(50)]
    + ["20260330", "20260331", "20260401", "20260402", "20260403"]
)


def _make_minute_df(trade_dates, base=10000.0):
    """390 bars × N day. all OHLC = base, volume=1000."""
    rows = []
    for td in trade_dates:
        for i in range(390):
            hh = 9 + i // 60
            mm = i % 60
            rows.append({
                "stock_code": "TEST", "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": base, "high": base, "low": base,
                "close": base, "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_daily_df(closes, dates):
    return pd.DataFrame([{
        "stock_code": "TEST", "trade_date": d,
        "open": c, "high": c * 1.005, "low": c * 0.995,
        "close": c, "volume": 100000.0,
    } for d, c in zip(dates, closes)])


def _flat_daily():
    return _make_daily_df([10000.0] * 55, DAILY_DATES)


def _basic_pos():
    return Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                    quantity=10, entry_date="20260331")


# ========== Family A: Trailing stop ==========

def test_familyA_no_trigger_when_no_drawdown():
    """trailing_pct=5%, drawdown 없음 → None."""
    minute = _make_minute_df(ENTRY_DATES)
    s = MACDCrossExitRegimeV2Strategy(family="trailing", trailing_pct=0.05)
    feats = s.prepare_features(minute, _flat_daily())
    out = s.exit_signal(_basic_pos(), feats, bar_idx=500, current_price=10000.0)
    assert out is None


def test_familyA_trigger_when_drawdown_from_peak():
    """peak 10500 후 low 9900 → 9900 ≤ 10500×0.95=9975 → reason='trailing_stop'."""
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[400, "high"] = 10500.0   # peak 형성
    minute.loc[500, "low"] = 9900.0     # drawdown
    s = MACDCrossExitRegimeV2Strategy(family="trailing", trailing_pct=0.05)
    feats = s.prepare_features(minute, _flat_daily())
    out = s.exit_signal(_basic_pos(), feats, bar_idx=500, current_price=9950.0)
    assert out is not None
    assert out.reason == "trailing_stop"


def test_familyA_activate_after_gates_when_below_threshold():
    """activate_after=2%, peak 10100 (+1% 만) → 큰 drawdown 도 미발동."""
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[400, "high"] = 10100.0   # +1% only (activate_after 미충족)
    minute.loc[500, "low"] = 9000.0     # -10% 큰 drawdown
    s = MACDCrossExitRegimeV2Strategy(
        family="trailing", trailing_pct=0.05, trailing_activate_after_pct=0.02,
    )
    feats = s.prepare_features(minute, _flat_daily())
    out = s.exit_signal(_basic_pos(), feats, bar_idx=500, current_price=9100.0)
    assert out is None


def test_familyA_uses_only_past_bars():
    """LOOKAHEAD 강제: bar 600 의 future high=20000 은 bar 500 평가에 반영 금지."""
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[400, "high"] = 10100.0   # 정상 peak (bar_idx < 500)
    minute.loc[600, "high"] = 20000.0   # **미래** spike (bar_idx > 500)
    minute.loc[500, "low"] = 10000.0
    s = MACDCrossExitRegimeV2Strategy(family="trailing", trailing_pct=0.05)
    feats = s.prepare_features(minute, _flat_daily())
    out = s.exit_signal(_basic_pos(), feats, bar_idx=500, current_price=10000.0)
    # 정상 peak=10100, low=10000 > 9595 → None
    # 버그 peak=20000, low=10000 < 19000 → trailing_stop (lookahead 발견)
    assert out is None, "lookahead 발견: bar 600 future high 가 peak 에 포함됨"


def test_familyA_no_trigger_on_entry_bar():
    """entry 봉 자체에서 미트리거 — peak window 비어있음."""
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[355, "low"] = 5000.0     # entry 봉 큰 drawdown
    s = MACDCrossExitRegimeV2Strategy(family="trailing", trailing_pct=0.05)
    feats = s.prepare_features(minute, _flat_daily())
    out = s.exit_signal(_basic_pos(), feats, bar_idx=355, current_price=5000.0)
    assert out is None


# ========== Family B: Intraday MACD reversal 확장 ==========

def test_familyB_last_bar_matches_mv_b_reversal():
    """eval_hhmm=None, threshold=0, min_hold=1 → MV-B intraday_reversal=True 와 동일 결과."""
    minute = _make_minute_df(ENTRY_DATES)
    # closes 끝 5일 급락 → D+1 last bar 의 today_hist 음수
    closes = [10000.0] * 50 + [9000.0] * 5
    daily = _make_daily_df(closes, DAILY_DATES)
    pos = _basic_pos()

    mvb = MACDCrossExitOverlayStrategy(
        intraday_reversal=True, fast_period=3, slow_period=6, signal_period=2,
    )
    v2 = MACDCrossExitRegimeV2Strategy(
        family="reversal", reversal_eval_hhmm=None,
        reversal_hist_threshold=0.0, reversal_min_hold_days=1,
        fast_period=3, slow_period=6, signal_period=2,
    )
    feats_mvb = mvb.prepare_features(minute, daily)
    feats_v2 = v2.prepare_features(minute, daily)

    out_mvb = mvb.exit_signal(pos, feats_mvb, bar_idx=779, current_price=9000.0)
    out_v2 = v2.exit_signal(pos, feats_v2, bar_idx=779, current_price=9000.0)
    assert out_mvb is not None
    assert out_v2 is not None
    assert out_mvb.reason == "macd_reversal"
    assert out_v2.reason == "macd_reversal"


def test_familyB_eval_hhmm_1400_triggers_at_1400_bar():
    """eval_hhmm=1400 → D+1 의 14:00 분봉(bar 690)에서 partial hist ≤ 0 시 trigger."""
    minute = _make_minute_df(ENTRY_DATES)
    # D+1 의 14:00 close 를 큰 폭으로 낮춰 partial today close → MACD hist 음수
    minute.loc[690, "close"] = 7000.0
    # daily 50 base flat → MACD warm-up 평탄
    daily = _make_daily_df([10000.0] * 55, DAILY_DATES)
    s = MACDCrossExitRegimeV2Strategy(
        family="reversal", reversal_eval_hhmm=1400,
        reversal_hist_threshold=0.0, reversal_min_hold_days=1,
        fast_period=3, slow_period=6, signal_period=2,
    )
    feats = s.prepare_features(minute, daily)
    out = s.exit_signal(_basic_pos(), feats, bar_idx=690, current_price=7000.0)
    assert out is not None
    assert out.reason == "macd_reversal"


def test_familyB_min_hold_days_2_skips_d_plus_1():
    """min_hold=2 → D+1 (days_held=1) last bar 에서 negative hist 도 미발동."""
    minute = _make_minute_df(ENTRY_DATES)
    closes = [10000.0] * 50 + [9000.0] * 5
    daily = _make_daily_df(closes, DAILY_DATES)
    s = MACDCrossExitRegimeV2Strategy(
        family="reversal", reversal_eval_hhmm=None,
        reversal_hist_threshold=0.0, reversal_min_hold_days=2,
        fast_period=3, slow_period=6, signal_period=2,
    )
    feats = s.prepare_features(minute, daily)
    # D+1 last bar = 779, days_held=1 < min_hold=2 → 미발동
    out = s.exit_signal(_basic_pos(), feats, bar_idx=779, current_price=9000.0)
    assert out is None


def test_familyB_partial_close_no_today_close_lookahead():
    """LOOKAHEAD 강제: eval_hhmm=1400 의 partial hist 는 bar close 사용, today daily close (EOD) 미사용.

    Setup:
      - bar 690 (D+1 14:00) close = 11000 (intraday 양수)
      - daily close for D+1 = 7000 (EOD 급락) — 만약 implementation 이 today daily close 를 쓰면 hist 음수 → 잘못된 trigger.
      - 정상 implementation 은 bar close 11000 사용 → hist 양수 → None.
    """
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[690, "close"] = 11000.0  # 14:00 partial close 양수
    # daily close for "20260401" (D+1, index 52 in DAILY_DATES) = 7000
    closes = [10000.0] * 52 + [7000.0] + [10000.0] * 2  # closes[52] = D+1 daily close
    daily = _make_daily_df(closes, DAILY_DATES)
    s = MACDCrossExitRegimeV2Strategy(
        family="reversal", reversal_eval_hhmm=1400,
        reversal_hist_threshold=0.0, reversal_min_hold_days=1,
        fast_period=3, slow_period=6, signal_period=2,
    )
    feats = s.prepare_features(minute, daily)
    out = s.exit_signal(_basic_pos(), feats, bar_idx=690, current_price=11000.0)
    assert out is None, (
        "lookahead 발견: 14:00 partial hist 에 today daily close=7000 (EOD) 가 사용됨"
    )


# ========== Family C: Hold-day 차등 stop ==========

def test_familyC_sl_d1_only_active_at_d_plus_1():
    """sl_d1=5%, sl_d2=None — D+1 -6% → sl_d1; D+2 -20% → sl_d2 None → hold_limit fallback."""
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[500, "low"] = 9400.0   # D+1: -6% drop
    minute.loc[780, "low"] = 8000.0   # D+2: -20% drop (sl_d2 None 이라 미적용)
    s = MACDCrossExitRegimeV2Strategy(family="tiered_sl", sl_d1_pct=0.05)
    feats = s.prepare_features(minute, _flat_daily())
    pos = _basic_pos()
    out_d1 = s.exit_signal(pos, feats, bar_idx=500, current_price=9500.0)
    assert out_d1 is not None and out_d1.reason == "sl_d1"
    out_d2 = s.exit_signal(pos, feats, bar_idx=780, current_price=8500.0)
    assert out_d2 is not None and out_d2.reason == "hold_limit"


def test_familyC_sl_d2_tighter_than_d1():
    """sl_d1=7%, sl_d2=3% — D+1 -5% → None (5% < 7%); D+2 -4% → sl_d2 (4% > 3%)."""
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[500, "low"] = 9500.0   # D+1: -5% (sl_d1=7% 미달)
    minute.loc[780, "low"] = 9600.0   # D+2: -4% (sl_d2=3% 초과)
    s = MACDCrossExitRegimeV2Strategy(
        family="tiered_sl", sl_d1_pct=0.07, sl_d2_pct=0.03,
    )
    feats = s.prepare_features(minute, _flat_daily())
    pos = _basic_pos()
    out_d1 = s.exit_signal(pos, feats, bar_idx=500, current_price=9600.0)
    assert out_d1 is None
    out_d2 = s.exit_signal(pos, feats, bar_idx=780, current_price=9650.0)
    assert out_d2 is not None and out_d2.reason == "sl_d2"


def test_familyC_no_stop_on_entry_day():
    """entry day (days_held=0): 큰 drawdown 도 stop 미적용."""
    minute = _make_minute_df(ENTRY_DATES)
    minute.loc[380, "low"] = 5000.0   # D-day 후반 -50% (days_held=0)
    s = MACDCrossExitRegimeV2Strategy(
        family="tiered_sl", sl_d1_pct=0.05, sl_d2_pct=0.03,
    )
    feats = s.prepare_features(minute, _flat_daily())
    out = s.exit_signal(_basic_pos(), feats, bar_idx=380, current_price=5500.0)
    assert out is None


# ========== Common sanity ==========

def test_family_off_matches_base_exit():
    """family='off' → 기존 MACDCrossStrategy 와 동일 (라이브 동등성)."""
    minute = _make_minute_df(ENTRY_DATES)
    daily = _flat_daily()
    base = MACDCrossStrategy()
    v2 = MACDCrossExitRegimeV2Strategy(family="off")
    base.prepare_features(minute, daily)
    v2.prepare_features(minute, daily)
    pos = _basic_pos()
    feats_dummy = pd.DataFrame()
    # D+1 mid bar: 둘 다 None
    assert base.exit_signal(pos, feats_dummy, bar_idx=500, current_price=10000.0) is None
    assert v2.exit_signal(pos, feats_dummy, bar_idx=500, current_price=10000.0) is None
    # D+2 first bar: 둘 다 hold_limit
    out_base = base.exit_signal(pos, feats_dummy, bar_idx=780, current_price=10000.0)
    out_v2 = v2.exit_signal(pos, feats_dummy, bar_idx=780, current_price=10000.0)
    assert out_base.reason == "hold_limit"
    assert out_v2.reason == "hold_limit"


def test_invalid_family_raises():
    """잘못된 family 또는 family 와 active params 불일치 → ValueError."""
    with pytest.raises(ValueError):
        MACDCrossExitRegimeV2Strategy(family="unknown")
    with pytest.raises(ValueError):
        MACDCrossExitRegimeV2Strategy(family="trailing", trailing_pct=None)
    with pytest.raises(ValueError):
        MACDCrossExitRegimeV2Strategy(
            family="tiered_sl", sl_d1_pct=None, sl_d2_pct=None,
        )
