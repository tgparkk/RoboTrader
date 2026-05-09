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


def test_kospi_below_ma20_signal_with_shift1():
    """전일 (D-1) close < MA20 시 진입일 (D) 의 kospi_below_ma20=True.

    KOSPI 30일치 mock: 처음 25일 상승 (close>MA20), 마지막 5일 급락 (close<MA20).
    분봉은 D 일에만 1개. shift(1) 적용으로:
      - D 일 = 25일째 (최초 close<MA20) → MA20 은 D-1 까지로 계산 → D-1 (24일째) close
        가 MA20 위였다면 kospi_below_ma20[D]=False
      - D 일 = 26일째 → D-1 (25일째) close 가 MA20 아래였다면 kospi_below_ma20[D]=True
    """
    # KOSPI 30일치
    n = 30
    closes = list(range(1000, 1000 + 25)) + list(range(1024, 1024 - 5, -1))
    kospi = pd.DataFrame({
        "trade_date": [f"202509{d+1:02d}" for d in range(n)],
        "close": closes,
    })
    # 분봉: D=26일째 (index 25) — D-1=25일째 (closes[24]=1024 = peak, MA20 약간 아래?)
    # 실제로는 D-1 (25일째 = closes[24]=1024) 와 MA20[D-1] 비교. 데이터 의존이지만 핵심은 shift(1).
    target_date = "20250926"  # 26일째
    df_min = pd.DataFrame([{
        "stock_code": "000001",
        "trade_date": target_date,
        "trade_time": "143100",
        "open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1005.0,
        "volume": 1000,
    }])
    df_daily = pd.DataFrame({
        "trade_date": [target_date],
        "close": [1024.0],
    })

    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True,
        kospi_daily_df=kospi,
        ma_period=20,
        fast_period=14, slow_period=34, signal_period=12,
    )
    feat = strat.prepare_features(df_min, df_daily)
    assert "kospi_below_ma20" in feat.columns
    # D-1 = 25일째 close=1024 vs MA20[1..20일째 평균=1009.5]=close>MA20 → False
    # D=26일째 close=1023 — 그러나 D 의 신호는 D-1 의 결과 → False
    assert feat["kospi_below_ma20"].iloc[0] == False  # 첫 분봉

    # 다른 날짜 — D=29일째 → D-1=28일째 close 가 MA20 아래일 가능성
    df_min2 = pd.DataFrame([{
        "stock_code": "000001",
        "trade_date": "20250929",  # 29일째 (index 28)
        "trade_time": "143100",
        "open": 1020.0, "high": 1025.0, "low": 1015.0, "close": 1020.0,
        "volume": 1000,
    }])
    feat2 = strat.prepare_features(df_min2, df_daily)
    # closes[27]=1021, closes[27-19:27+1]=avg of closes[8..27]
    expected_ma20_d_minus_1 = sum(closes[8:28]) / 20
    expected_close_d_minus_1 = closes[27]  # D-1 = 28일째 (index 27)
    expected_below = expected_close_d_minus_1 < expected_ma20_d_minus_1
    assert feat2["kospi_below_ma20"].iloc[0] == expected_below


def test_warmup_insufficient_returns_false():
    """KOSPI lookback 부족 (<20봉) 시 below_prev=False (안전, no block)."""
    kospi = pd.DataFrame({
        "trade_date": [f"2025090{d+1}" for d in range(5)],
        "close": [1000, 990, 980, 970, 960],  # 5봉만 — MA20 NaN
    })
    df_min = pd.DataFrame([{
        "stock_code": "000001",
        "trade_date": "20250905",
        "trade_time": "143100",
        "open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1005.0,
        "volume": 1000,
    }])
    df_daily = pd.DataFrame({"trade_date": ["20250905"], "close": [1000.0]})
    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True,
        kospi_daily_df=kospi,
        fast_period=14, slow_period=34, signal_period=12,
    )
    feat = strat.prepare_features(df_min, df_daily)
    # NaN MA20 → fillna(False) → 안전
    assert feat["kospi_below_ma20"].iloc[0] == False
