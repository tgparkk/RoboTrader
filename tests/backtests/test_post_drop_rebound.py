"""post_drop_rebound (낙주 반등) 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.post_drop_rebound import PostDropReboundStrategy
from backtests.strategies.base import Position


def _make_minute_df(trade_dates, bars_per_day=390, today_volumes=None):
    rows = []
    for d_idx, td in enumerate(trade_dates):
        vol = today_volumes[d_idx] if today_volumes else 1000.0
        for i in range(bars_per_day):
            hh = 9 + i // 60
            mm = i % 60
            rows.append({
                "stock_code": "TEST",
                "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": 10000.0, "high": 10100.0, "low": 9900.0,
                "close": 10000.0, "volume": vol,
            })
    return pd.DataFrame(rows)


def _make_daily_df(prev_returns_pct: list, target_dates: list, base_vol: float = 100000.0):
    """전일 returns 시퀀스 + target dates."""
    rows = []
    close = 10000.0
    base_dates = [f"2026031{i}" for i in range(1, 10)]  # 9 history days
    for i, d in enumerate(base_dates):
        rows.append({
            "stock_code": "TEST", "trade_date": d,
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": base_vol,
        })
    # 낙폭 day
    drop = prev_returns_pct[0] / 100.0
    new_close = close * (1.0 + drop)
    rows.append({
        "stock_code": "TEST", "trade_date": "20260330",
        "open": close, "high": close * 1.005, "low": new_close * 0.99,
        "close": new_close, "volume": base_vol,
    })
    # target dates (오늘부터)
    for d in target_dates:
        rows.append({
            "stock_code": "TEST", "trade_date": d,
            "open": new_close, "high": new_close * 1.02, "low": new_close * 0.99,
            "close": new_close * 1.01, "volume": base_vol,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = PostDropReboundStrategy()
    assert s.name == "post_drop_rebound"
    assert s.hold_days == 2
    assert s.max_prev_return_pct == -5.0
    assert s.vol_mult == 2.0


def test_prepare_features_columns():
    s = PostDropReboundStrategy()
    minute = _make_minute_df(["20260331"], today_volumes=[5000.0])
    daily = _make_daily_df(prev_returns_pct=[-6.0], target_dates=["20260331"])
    feats = s.prepare_features(minute, daily)
    assert "prev_return_pct" in feats.columns
    assert "vol_ratio" in feats.columns
    assert "hhmm" in feats.columns


def test_entry_fires_on_drop_with_volume():
    s = PostDropReboundStrategy(max_prev_return_pct=-5.0, vol_mult=2.0)
    # 전일 -6% (≤ -5%) + 당일 누적 분봉 거래량이 5일 평균(100000) 의 2배 이상
    # 분봉 1000.0 × 350 bars = 350,000 (>200,000) ✓
    minute = _make_minute_df(["20260331"], today_volumes=[1000.0])
    daily = _make_daily_df(prev_returns_pct=[-6.0], target_dates=["20260331"])
    feats = s.prepare_features(minute, daily)
    order = s.entry_signal(feats, bar_idx=350, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_with_mild_drop():
    s = PostDropReboundStrategy(max_prev_return_pct=-5.0)
    # 전일 -2% — 임계 미충족
    minute = _make_minute_df(["20260331"], today_volumes=[2000.0])
    daily = _make_daily_df(prev_returns_pct=[-2.0], target_dates=["20260331"])
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_entry_no_fire_without_volume():
    s = PostDropReboundStrategy(max_prev_return_pct=-5.0, vol_mult=5.0)
    # 분봉 100 × 350 = 35000 < 5×100000 = 500000
    minute = _make_minute_df(["20260331"], today_volumes=[100.0])
    daily = _make_daily_df(prev_returns_pct=[-6.0], target_dates=["20260331"])
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_exit_signal_holds_two_days():
    s = PostDropReboundStrategy()
    minute = _make_minute_df(["20260331", "20260401", "20260402"],
                             today_volumes=[1000.0, 1000.0, 1000.0])
    daily = _make_daily_df(prev_returns_pct=[-6.0],
                           target_dates=["20260331", "20260401", "20260402"])
    s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    assert s.exit_signal(pos, pd.DataFrame(), bar_idx=390, current_price=10100.0) is None
    out = s.exit_signal(pos, pd.DataFrame(), bar_idx=780, current_price=10200.0)
    assert out is not None
    assert out.reason == "hold_limit"
