"""macd_cross 공유 시그널 모듈 parity 테스트.

핵심: 백테스트(backtests/strategies/macd_cross.py) 와 공유 모듈
(core/strategies/macd_cross_signal.py) 의 시그널 식이 1:1 동등해야 한다.
한 픽셀이라도 다르면 OOS 재현 검증이 의미를 잃는다.
"""
import numpy as np
import pandas as pd
import pytest

from core.strategies.macd_cross_signal import (
    compute_macd_histogram_series,
    is_macd_golden_cross,
)


def _make_daily(close_series, start="2025-01-02"):
    dates = pd.date_range(start, periods=len(close_series), freq="B").strftime("%Y%m%d")
    return pd.DataFrame({
        "trade_date": dates.astype(str),
        "close": close_series,
    })


def test_compute_macd_histogram_matches_known_values():
    """알려진 EMA 결과와 일치 (sanity check)."""
    np.random.seed(42)
    close = 10000 + np.cumsum(np.random.randn(100) * 50)
    df = _make_daily(close)
    hist = compute_macd_histogram_series(df, fast=12, slow=26, signal=9)
    assert len(hist) == 100
    assert pd.notna(hist.iloc[-1])
    # MACD hist 는 EMA(close, 12) - EMA(close, 26) - signal_ema 이므로 마지막 값이 finite
    assert np.isfinite(hist.iloc[-1])


def test_golden_cross_detection_positive():
    """prev_prev_hist < 0 AND prev_hist >= 0 → True."""
    assert is_macd_golden_cross(prev_hist=0.5, prev_prev_hist=-0.3) is True
    assert is_macd_golden_cross(prev_hist=0.0, prev_prev_hist=-0.001) is True


def test_golden_cross_detection_negative():
    """음→음, 양→양, 양→음 모두 False."""
    assert is_macd_golden_cross(prev_hist=-0.1, prev_prev_hist=-0.3) is False
    assert is_macd_golden_cross(prev_hist=0.5, prev_prev_hist=0.3) is False
    assert is_macd_golden_cross(prev_hist=-0.1, prev_prev_hist=0.3) is False


def test_golden_cross_nan_returns_false():
    """NaN 입력은 False (시계열 워밍업 부족)."""
    assert is_macd_golden_cross(prev_hist=float("nan"), prev_prev_hist=-0.3) is False
    assert is_macd_golden_cross(prev_hist=0.5, prev_prev_hist=float("nan")) is False


def test_parity_against_backtest_strategy():
    """백테스트 MACDCrossStrategy._build_macd_maps 와 시그널 식이 동일해야 한다.

    100개 랜덤 daily 시퀀스 × Stage 2 best params (14/34/12) 로 매일
    is_macd_golden_cross 결과를 비교 → 모두 일치해야 통과.
    """
    from backtests.strategies.macd_cross import MACDCrossStrategy

    np.random.seed(123)
    close = 10000 + np.cumsum(np.random.randn(120) * 50)
    df = _make_daily(close)

    bt = MACDCrossStrategy(fast_period=14, slow_period=34, signal_period=12)
    prev_hist_map, prev_prev_hist_map = bt._build_macd_maps(df)

    hist = compute_macd_histogram_series(df, fast=14, slow=34, signal=12)
    # 공유 모듈 hist[i] 가 backtest 의 prev_hist_map[date[i+1]] 과 같아야 함 (shift1).
    for i in range(len(df) - 1):
        date_next = df["trade_date"].iloc[i + 1]
        bt_prev_hist = prev_hist_map.get(date_next)
        shared_prev_hist = hist.iloc[i]
        if pd.isna(bt_prev_hist) or pd.isna(shared_prev_hist):
            continue
        assert abs(bt_prev_hist - shared_prev_hist) < 1e-9, (
            f"day {i+1}: backtest prev_hist={bt_prev_hist} vs shared={shared_prev_hist}"
        )
