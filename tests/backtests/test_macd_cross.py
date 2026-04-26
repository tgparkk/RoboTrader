"""macd_cross (MACD 골든크로스) 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.macd_cross import MACDCrossStrategy
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


def _make_daily_df(closes: list, all_dates: list):
    rows = []
    for d, c in zip(all_dates, closes):
        rows.append({
            "stock_code": "TEST", "trade_date": d,
            "open": c, "high": c * 1.005, "low": c * 0.995,
            "close": c, "volume": 100000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = MACDCrossStrategy()
    assert s.name == "macd_cross"
    assert s.hold_days == 2
    assert s.fast_period == 12
    assert s.slow_period == 26
    assert s.signal_period == 9


def test_prepare_features_columns():
    s = MACDCrossStrategy()
    minute = _make_minute_df(["20260331"])
    # 50 일 평탄 → MACD = 0, hist = 0
    closes = [10000.0] * 50
    dates = [f"2026{(2 + (i // 30)):02d}{((i % 30) + 1):02d}" for i in range(50)]
    daily = _make_daily_df(closes, dates + ["20260331"])
    daily = daily.iloc[:50]  # 50 dates
    daily = pd.concat([daily, _make_daily_df([10100.0], ["20260331"])], ignore_index=True)
    feats = s.prepare_features(minute, daily)
    assert "prev_hist" in feats.columns
    assert "prev_prev_hist" in feats.columns
    assert "hhmm" in feats.columns


def test_entry_fires_on_golden_cross():
    """엔트리 로직 단독 검증 — hand-crafted features 로 골든크로스 시나리오 재현."""
    s = MACDCrossStrategy()
    # 14:55 에 prev_prev_hist=-0.1 (음), prev_hist=+0.1 (양) → 직전 세션 cross
    feats = pd.DataFrame({
        "prev_hist": [0.1] * 400,
        "prev_prev_hist": [-0.1] * 400,
        "hhmm": [int(f"{(9 + i // 60):02d}{(i % 60):02d}")
                 for i in range(400)],
    })
    order = s.entry_signal(feats, bar_idx=355, stock_code="TEST")  # ~14:55
    assert order is not None


def test_entry_with_real_macd_computation():
    """실제 MACD 계산 경로가 prev_hist 컬럼을 채우는지 검증 (값 자체는 불검증)."""
    s = MACDCrossStrategy(fast_period=3, slow_period=6, signal_period=2)
    closes = [10000 - i * 100 for i in range(40)] + [6000 + i * 50 for i in range(10)]
    n = len(closes)
    dates = [f"202603{i+1:02d}" if i < 30 else f"202604{i-29:02d}" for i in range(n)]
    daily = _make_daily_df(closes, dates)
    minute = _make_minute_df([dates[-1]])
    feats = s.prepare_features(minute, daily)
    # prev_hist / prev_prev_hist 가 NaN 아니어야 함 (실제 MACD 계산됨)
    assert not pd.isna(feats["prev_hist"].iloc[300])
    assert not pd.isna(feats["prev_prev_hist"].iloc[300])


def test_entry_no_fire_when_no_cross():
    s = MACDCrossStrategy(fast_period=3, slow_period=6, signal_period=2)
    # 평탄 → MACD 0, hist 0 — 명확한 음→양 cross 없음
    closes = [10000.0] * 60
    dates = [f"202603{i+1:02d}" if i < 30 else f"202604{i-29:02d}" for i in range(59)]
    target_date = "20260530"
    daily = _make_daily_df(closes, dates + [target_date])
    minute = _make_minute_df([target_date])
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_entry_no_fire_before_window():
    s = MACDCrossStrategy()
    minute = _make_minute_df(["20260331"])
    closes = [10000.0] * 60
    dates = [f"2026{(1 + i // 30):02d}{(i % 30) + 1:02d}" for i in range(59)]
    daily = _make_daily_df(closes, dates + ["20260331"])
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=60, stock_code="TEST") is None


def test_exit_signal_holds_two_days():
    s = MACDCrossStrategy()
    minute = _make_minute_df(["20260331", "20260401", "20260402"])
    closes = [10000.0] * 60
    dates = [f"2026{(1 + i // 30):02d}{(i % 30) + 1:02d}" for i in range(57)]
    daily = _make_daily_df(closes, dates + ["20260331", "20260401", "20260402"])
    s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    assert s.exit_signal(pos, pd.DataFrame(), bar_idx=390, current_price=10100.0) is None
    out = s.exit_signal(pos, pd.DataFrame(), bar_idx=780, current_price=10200.0)
    assert out is not None
    assert out.reason == "hold_limit"
