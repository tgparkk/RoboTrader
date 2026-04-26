"""장중 눌림목 (20EMA) 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.intraday_pullback import IntradayPullbackStrategy
from backtests.strategies.base import Position


def _make_bars(closes, trade_date="20260401", lows=None):
    rows = []
    for i, c in enumerate(closes):
        hh = 9 + i // 60
        mm = i % 60
        low = lows[i] if lows is not None else c * 0.999
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c, "high": c * 1.001, "low": low,
            "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = IntradayPullbackStrategy()
    assert s.name == "intraday_pullback"
    assert s.hold_days == 0
    assert s.ema_period == 20
    assert s.pullback_lookback_bars == 5


def test_prepare_features_columns():
    s = IntradayPullbackStrategy()
    closes = [10000.0 + i * 5 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_ema" in feats.columns
    assert "recent_low" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    assert "bar_in_day" in feats.columns
    assert not pd.isna(feats["prev_ema"].iloc[40])


def test_entry_fires_on_pullback_and_rebound():
    s = IntradayPullbackStrategy(
        ema_period=20, pullback_lookback_bars=5,
        proximity_pct=2.0, entry_window_end_bar=240,
    )
    # 장기 상승 후 EMA 근접 눌림 → 반등
    closes = [10000.0 + i * 25 for i in range(20)]
    closes += [10500.0] * 10
    closes += [10350.0, 10340.0, 10330.0, 10320.0]
    closes += [10360.0]
    closes += [10500.0] * 10
    # low 도 같이 내려가도록 (recent_low 가 EMA 에 닿게)
    lows = [c * 0.998 for c in closes]
    df = _make_bars(closes, lows=lows)
    feats = s.prepare_features(df, pd.DataFrame())
    rebound_idx = 34
    orders = [
        s.entry_signal(feats, bar_idx=i, stock_code="TEST")
        for i in range(rebound_idx, rebound_idx + 5)
    ]
    assert any(o is not None for o in orders), \
        "반등 시점에서 매수 신호가 발생해야 함"


def test_entry_no_fire_in_downtrend():
    s = IntradayPullbackStrategy()
    closes = [10500.0 - i * 30 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    for idx in range(30, 60):
        assert s.entry_signal(feats, bar_idx=idx, stock_code="TEST") is None


def test_entry_no_fire_without_pullback():
    s = IntradayPullbackStrategy(proximity_pct=0.1)
    closes = [10000.0 + i * 30 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    for idx in range(30, 60):
        order = s.entry_signal(feats, bar_idx=idx, stock_code="TEST")
        if order is not None:
            r = feats.iloc[idx]
            ratio = (r["recent_low"] - r["prev_ema"]) / r["prev_ema"] * 100
            assert ratio <= 0.1, f"bar {idx} pullback proximity {ratio:.2f}%"


def test_exit_tp_sl():
    s = IntradayPullbackStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=30, entry_price=10000.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=10250.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=9800.0).reason == "sl"
