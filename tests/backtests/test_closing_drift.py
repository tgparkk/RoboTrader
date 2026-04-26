"""종가 드리프트 (오버나이트) 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.closing_drift import ClosingDriftStrategy
from backtests.strategies.base import Position


def _make_minute_df(
    trade_date: str,
    n_bars: int,
    open_price: float,
    decline_low: float = None,
    afternoon_close: float = None,
):
    """09:00 시작 분봉.

    - i=0: open_price (시가)
    - 60 ≤ i < 240: decline_low 까지 점진 하락 (제공된 경우)
    - i >= 300 (14:00): afternoon_close 로 close 고정 (제공된 경우)
    - 그 외: 시가 근방
    """
    rows = []
    for i in range(n_bars):
        hh = 9 + i // 60
        mm = i % 60
        if i == 0:
            close = open_price
        elif decline_low is not None and 60 <= i < 240:
            close = open_price - (open_price - decline_low) * ((i - 60) / 180)
        elif afternoon_close is not None and i >= 300:
            close = afternoon_close
        else:
            close = open_price * (1.0 - 0.0001 * (i % 5))
        # low: 만약 decline_low 가 있으면 해당 구간엔 더 깊이 갈 수 있게
        if decline_low is not None and 60 <= i < 240:
            low = min(close * 0.999, decline_low)
        else:
            low = close * 0.999
        high = close * 1.001
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": close, "high": high, "low": low,
            "close": close, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def _make_daily_df(stock_code: str, prev_open: float, prev_close: float):
    """전일 + 당일 일봉 (당일은 plain placeholder)."""
    return pd.DataFrame([
        {"stock_code": stock_code, "trade_date": "20260331",
         "open": prev_open, "high": prev_close * 1.01, "low": prev_open * 0.99,
         "close": prev_close, "volume": 100000.0},
        {"stock_code": stock_code, "trade_date": "20260401",
         "open": 10000.0, "high": 10100.0, "low": 9900.0,
         "close": 10000.0, "volume": 100000.0},
    ])


def _multi_day_minute_df(base_open: float = 10000.0):
    dfs = []
    for d in ["20260401", "20260402"]:
        dfs.append(_make_minute_df(d, n_bars=390, open_price=base_open,
                                    afternoon_close=base_open * 1.005))
    return pd.concat(dfs, ignore_index=True)


def test_defaults():
    s = ClosingDriftStrategy()
    assert s.name == "closing_drift"
    assert s.hold_days == 1
    assert s.entry_hhmm_start == 1400
    assert s.entry_hhmm_end == 1420
    assert s.min_prev_body_pct == 1.0


def test_prepare_features_columns():
    s = ClosingDriftStrategy()
    minute = _make_minute_df("20260401", n_bars=390, open_price=10000.0,
                             afternoon_close=10100.0)
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    assert "prev_body_pct" in feats.columns
    assert "day_open" in feats.columns
    assert "day_low_pct" in feats.columns
    assert "vwap" in feats.columns
    assert "close" in feats.columns
    assert "hhmm" in feats.columns
    # prev_body = (9900 - 9800)/9800 * 100 = +1.0204%
    assert abs(feats["prev_body_pct"].iloc[0] - 1.0204) < 0.01


def test_entry_fires_at_1400_with_signal():
    s = ClosingDriftStrategy(min_prev_body_pct=1.0, max_day_decline_pct=-3.0)
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9800.0,         # 시가 대비 -2% (≥ -3% 통과)
        afternoon_close=10100.0,    # 14:00 이후 +1% (시가 위, VWAP 위 가능)
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    # bar 305 = 14:05 → 진입 윈도우 내
    order = s.entry_signal(feats, bar_idx=305, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_outside_time_window():
    s = ClosingDriftStrategy()
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9800.0, afternoon_close=10100.0,
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    # bar 60 (10:00) — 진입 윈도우 이전
    assert s.entry_signal(feats, bar_idx=60, stock_code="TEST") is None
    # bar 350 (14:50) — 진입 윈도우(14:20) 이후
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_entry_no_fire_with_weak_prev_body():
    s = ClosingDriftStrategy(min_prev_body_pct=1.0)
    minute = _make_minute_df("20260401", n_bars=390, open_price=10000.0,
                             decline_low=9800.0, afternoon_close=10100.0)
    # 전일 양봉 0.5% — 1% 기준 미충족
    daily = _make_daily_df("TEST", prev_open=9950.0, prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=305, stock_code="TEST") is None


def test_entry_no_fire_with_deep_decline():
    s = ClosingDriftStrategy(max_day_decline_pct=-3.0)
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9500.0,         # 시가 대비 -5% (< -3% 실패)
        afternoon_close=10100.0,
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=305, stock_code="TEST") is None


def test_entry_no_fire_below_day_open():
    s = ClosingDriftStrategy()
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9800.0,
        afternoon_close=9950.0,     # 시가 미복귀
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=305, stock_code="TEST") is None


def test_exit_signal_holds_until_next_day():
    s = ClosingDriftStrategy()
    multi = _multi_day_minute_df()
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    s.prepare_features(multi, daily)  # _last_df_minute 캐시
    pos = Position(stock_code="TEST", entry_bar_idx=305, entry_price=10100.0,
                   quantity=10, entry_date="20260401")
    # 같은 날 (bar 350) — 청산 안 함
    assert s.exit_signal(pos, pd.DataFrame(), bar_idx=350, current_price=10120.0) is None
    # 다음 날 첫 bar (bar 390 = 20260402 09:00) — hold_limit 청산
    out = s.exit_signal(pos, pd.DataFrame(), bar_idx=390, current_price=10150.0)
    assert out is not None
    assert out.reason == "hold_limit"
