"""ORB (Opening Range Breakout) 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.orb import ORBStrategy
from backtests.strategies.base import Position, EntryOrder, ExitOrder


def _make_day_bars(
    trade_date: str,
    n_bars: int,
    base_price: float = 10000.0,
    or_high_delta: float = 50.0,
    breakout_bar: int = None,
    breakout_delta: float = 100.0,
):
    """합성 분봉.

    - bar 0 ~ 29: opening range (base_price ± or_high_delta)
    - bar 30 이후: base_price 중심
    - breakout_bar 가 지정되면 해당 bar 의 close 를 base_price + breakout_delta 로 설정
    """
    rows = []
    for i in range(n_bars):
        if i < 30:
            high = base_price + or_high_delta
            low = base_price - or_high_delta
            close = base_price
        else:
            high = base_price + 10
            low = base_price - 10
            close = base_price
        if breakout_bar is not None and i == breakout_bar:
            close = base_price + breakout_delta
            high = close + 5
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_orb_defaults_loadable():
    s = ORBStrategy()
    assert s.name == "orb"
    assert s.hold_days == 0
    assert s.opening_window_min == 30
    assert s.breakout_buffer_pct == 0.2
    assert s.take_profit_pct == 3.0
    assert s.stop_loss_pct == -2.0


def test_orb_prepare_features_creates_or_high_low():
    s = ORBStrategy()
    df = _make_day_bars("20260401", n_bars=100, base_price=10000.0, or_high_delta=50.0)
    features = s.prepare_features(df, pd.DataFrame())
    assert "or_high" in features.columns
    assert "or_low" in features.columns
    assert "close" in features.columns
    # opening range 구간 (bar 0~29) 은 or_high/or_low 가 NaN
    assert features["or_high"].iloc[15] != features["or_high"].iloc[15]  # NaN
    # bar 30 이후 or_high = 10050 (base + 50)
    assert features["or_high"].iloc[50] == 10050.0
    assert features["or_low"].iloc[50] == 9950.0


def test_orb_entry_signal_fires_on_breakout():
    s = ORBStrategy()
    # bar 50 에서 10150 으로 breakout (OR high 10050 × 1.002 = 10070.1 초과)
    df = _make_day_bars(
        "20260401", n_bars=100, base_price=10000.0,
        or_high_delta=50.0, breakout_bar=50, breakout_delta=150.0,
    )
    features = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(features, bar_idx=50, stock_code="TEST")
    assert order is not None
    assert order.stock_code == "TEST"


def test_orb_entry_signal_ignored_during_or_window():
    s = ORBStrategy()
    df = _make_day_bars("20260401", n_bars=100, base_price=10000.0, breakout_bar=10, breakout_delta=200.0)
    features = s.prepare_features(df, pd.DataFrame())
    # OR 구간 내 (bar 10) 은 진입 불가
    assert s.entry_signal(features, bar_idx=10, stock_code="TEST") is None


def test_orb_entry_signal_ignored_after_entry_window():
    s = ORBStrategy(entry_end_bar=120)
    df = _make_day_bars("20260401", n_bars=200, base_price=10000.0, breakout_bar=150, breakout_delta=200.0)
    features = s.prepare_features(df, pd.DataFrame())
    # 진입 마감(120) 이후인 bar 150 에서는 breakout 이어도 신호 미발동
    assert s.entry_signal(features, bar_idx=150, stock_code="TEST") is None


def test_orb_entry_signal_requires_breakout_above_buffer():
    s = ORBStrategy(breakout_buffer_pct=1.0)  # 1% 이상 뚫어야 함
    # OR high = 10050. 1% buffer = 10150.5. breakout close = 10100 은 buffer 못 넘김
    df = _make_day_bars("20260401", n_bars=100, breakout_bar=50, breakout_delta=100.0)
    features = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(features, bar_idx=50, stock_code="TEST") is None


def test_orb_exit_signal_tp():
    s = ORBStrategy(take_profit_pct=3.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=50, entry_price=10000.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # +3.5% → TP
    order = s.exit_signal(pos, features, bar_idx=60, current_price=10350.0)
    assert order is not None
    assert order.reason == "tp"


def test_orb_exit_signal_sl():
    s = ORBStrategy(stop_loss_pct=-2.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=50, entry_price=10000.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # -2.5% → SL
    order = s.exit_signal(pos, features, bar_idx=60, current_price=9750.0)
    assert order is not None
    assert order.reason == "sl"


def test_orb_exit_signal_eod_force_exit():
    """당일 청산 강제: hold_days=0 이므로 엔진이 최종 bar 에서 eod_forced 처리."""
    s = ORBStrategy()
    pos = Position(
        stock_code="TEST", entry_bar_idx=100, entry_price=10000.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 400})
    order = s.exit_signal(pos, features, bar_idx=380, current_price=10020.0)
    assert order is None  # TP/SL 없으면 엔진에 위임
