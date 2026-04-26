"""RSI 과매도 반등 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.rsi_oversold import RSIOversoldStrategy
from backtests.strategies.base import Position


def _make_bars(closes, trade_date="20260401"):
    rows = []
    for i, c in enumerate(closes):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c, "high": c * 1.001, "low": c * 0.999,
            "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = RSIOversoldStrategy()
    assert s.name == "rsi_oversold"
    assert s.hold_days == 0
    assert s.rsi_period == 14
    assert s.oversold_threshold == 30.0


def test_prepare_features_has_rsi():
    s = RSIOversoldStrategy()
    closes = [10000.0 + (i % 10 - 5) * 50 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_rsi" in feats.columns
    assert "prev_prev_rsi" in feats.columns
    assert "prev_close" in feats.columns
    # bar 20+ 에서는 RSI 유효
    assert not pd.isna(feats["prev_rsi"].iloc[30])


def test_entry_fires_on_rsi_reversal():
    s = RSIOversoldStrategy(
        rsi_period=14, oversold_threshold=30.0, entry_window_end_bar=240
    )
    # 지속 하락 → RSI 낮음 → 반등
    closes = [10000.0 - i * 50 for i in range(30)]  # 하락
    closes += [8600.0]  # 반등 한 bar
    closes += [8650.0]  # 반등 지속
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    # 반등 지점에서 signal 발생 기대
    orders = [s.entry_signal(feats, bar_idx=i, stock_code="TEST") for i in range(28, 32)]
    assert any(o is not None for o in orders)


def test_entry_no_fire_without_oversold():
    s = RSIOversoldStrategy(oversold_threshold=20.0)  # 아주 낮은 임계
    closes = [10000.0 + (i % 10 - 5) * 10 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    for idx in range(20, 60):
        assert s.entry_signal(feats, bar_idx=idx, stock_code="TEST") is None


def test_exit_tp_sl():
    s = RSIOversoldStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=30, entry_price=8600.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=8800.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=8400.0).reason == "sl"
