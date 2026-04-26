"""weighted_score full adapter 단위 테스트 (합성 데이터 + 실제 params.json)."""
import pandas as pd
import pytest

from backtests.strategies.weighted_score_full import WeightedScoreFull
from backtests.strategies.base import Position


def _make_minute_df(stock_code: str, n_days: int, bars_per_day: int = 20):
    """합성 분봉 DF — n_days 거래일, 각 날 bars_per_day 개 분봉.

    trade_date: 20260301, 20260302, ... (매일 1일씩 증가, YYYYMMDD 8자리)
    """
    rows = []
    for d in range(n_days):
        date = f"202603{d + 1:02d}"  # 20260301 .. 20260331
        for b in range(bars_per_day):
            hh = 9 + b // 60
            mm = b % 60
            rows.append({
                "stock_code": stock_code,
                "trade_date": date,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": 10000.0 + d * 100 + b,
                "high": 10005.0 + d * 100 + b,
                "low": 9995.0 + d * 100 + b,
                "close": 10000.0 + d * 100 + b,
                "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_daily_df(stock_code: str, n_days: int = 60):
    """합성 일봉 — 충분한 과거 (지표 계산용 최소 30일+)."""
    rows = []
    start_date = pd.Timestamp("2026-01-01")
    for d in range(n_days):
        date = (start_date + pd.Timedelta(days=d)).strftime("%Y%m%d")
        price = 10000.0 + d * 10
        rows.append({
            "stock_code": stock_code,
            "trade_date": date,
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 100000.0,
        })
    return pd.DataFrame(rows)


def test_adapter_loads_trial837_params():
    s = WeightedScoreFull()
    assert s.name == "weighted_score_full"
    assert s.params.meta.get("trial_number") == 837
    assert s.params.max_positions == 3
    assert abs(s.params.threshold_abs - (-0.35)) < 0.01


def test_adapter_prepare_features_returns_score_column():
    s = WeightedScoreFull()
    minute_df = _make_minute_df("005930", n_days=5, bars_per_day=20)
    daily_df = _make_daily_df("005930", n_days=60)
    # 지수 데이터 없이 호출
    features = s.prepare_features(
        df_minute=minute_df,
        df_daily=daily_df,
        df_kospi=pd.DataFrame(),
        df_kosdaq=pd.DataFrame(),
    )
    assert "score" in features.columns
    assert len(features) == len(minute_df)


def test_adapter_entry_signal_never_fires_on_nan():
    s = WeightedScoreFull()
    # 데이터가 적어 피처 대부분 NaN → score NaN → entry 0건
    minute_df = _make_minute_df("005930", n_days=1, bars_per_day=5)
    daily_df = _make_daily_df("005930", n_days=10)
    features = s.prepare_features(
        df_minute=minute_df, df_daily=daily_df,
        df_kospi=pd.DataFrame(), df_kosdaq=pd.DataFrame(),
    )
    for idx in range(len(features)):
        order = s.entry_signal(features, bar_idx=idx, stock_code="005930")
        assert order is None


def test_adapter_exit_signal_tp_via_current_price():
    s = WeightedScoreFull()
    pos = Position(
        stock_code="005930", entry_bar_idx=100, entry_price=10000.0,
        quantity=10, entry_date="20260301",
    )
    features = pd.DataFrame({"score": [float("nan")] * 1000})
    # 현재가 10900 (+9%) → TP (+8.02%) 발동
    order = s.exit_signal(pos, features, bar_idx=150, current_price=10900.0)
    assert order is not None
    assert order.reason == "tp"


def test_adapter_exit_signal_sl_via_current_price():
    s = WeightedScoreFull()
    pos = Position(
        stock_code="005930", entry_bar_idx=100, entry_price=10000.0,
        quantity=10, entry_date="20260301",
    )
    features = pd.DataFrame({"score": [float("nan")] * 1000})
    # 현재가 9500 (-5%) → SL (-3.84%) 발동
    order = s.exit_signal(pos, features, bar_idx=150, current_price=9500.0)
    assert order is not None
    assert order.reason == "sl"


def test_adapter_exit_signal_hold_limit_via_trading_day_count():
    """5 거래일 경과 시 hold_limit."""
    s = WeightedScoreFull()
    # 6 거래일 × 10 bars/day = 60 bars
    minute_df = _make_minute_df("005930", n_days=6, bars_per_day=10)
    features = s.prepare_features(
        df_minute=minute_df,
        df_daily=_make_daily_df("005930", n_days=30),
        df_kospi=pd.DataFrame(),
        df_kosdaq=pd.DataFrame(),
    )
    # 진입: idx 5 (day 0, 20260301)
    pos = Position(
        stock_code="005930", entry_bar_idx=5,
        entry_price=10000.0, quantity=10, entry_date="20260301",
    )
    # idx 55 = day 5 (20260306), 5 거래일 경과 → hold_limit
    order = s.exit_signal(pos, features, bar_idx=55, current_price=10050.0)
    assert order is not None
    assert order.reason == "hold_limit"
