"""MACDCrossRegimeFilterStrategy unit tests — KOSPI MA20 regime filter wrapper."""
import numpy as np
import pandas as pd
import pytest

from backtests.strategies.macd_cross_regime_filter import (
    MACDCrossRegimeFilterStrategy,
)


def _mock_minute_df():
    """5일치 분봉 mock — golden cross 환경 가정 (간단 fixture)."""
    rows = []
    for d in range(5):
        date = f"2025090{d+1}"
        for m in range(1430, 1432):  # 14:30 ~ 14:31 두 봉
            rows.append({
                "stock_code": "000001",
                "trade_date": date,
                "trade_time": f"{m // 100:02d}{m % 100:02d}00",
                "open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1005.0,
                "volume": 1000,
            })
    return pd.DataFrame(rows)


def _mock_daily_df():
    """5일치 daily mock — MACD hist 양수 (golden cross 사전조건)."""
    return pd.DataFrame({
        "trade_date": [f"2025090{d+1}" for d in range(5)],
        "close": [1000, 1005, 1010, 1015, 1020],  # 단조 증가 → MACD>0
    })


def test_filter_off_matches_base_no_kospi_needed():
    """regime_filter_enabled=False 면 kospi_daily_df 없이도 정상 — base 동등."""
    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=False,
        fast_period=14, slow_period=34, signal_period=12,
    )
    feat = strat.prepare_features(_mock_minute_df(), _mock_daily_df())
    # base 가 만든 컬럼만 존재해야 함
    assert "kospi_below_ma20" not in feat.columns
    assert "prev_hist" in feat.columns


def test_filter_on_without_kospi_df_raises():
    """regime_filter_enabled=True + kospi_daily_df=None 시 ValueError."""
    with pytest.raises(ValueError, match="kospi_daily_df"):
        MACDCrossRegimeFilterStrategy(
            regime_filter_enabled=True,
            kospi_daily_df=None,
        )
