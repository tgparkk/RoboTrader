"""backtests.common.feature_audit 단위 테스트."""
import numpy as np
import pandas as pd
import pytest

from backtests.common.feature_audit import audit_no_lookahead, LookAheadDetected


def test_clean_feature_passes():
    """shift(1) 사용한 깨끗한 피처 → 감사 통과."""
    def prepare(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({
            "prev_close": df["close"].shift(1),
            "prev_volume": df["volume"].shift(1),
        }, index=df.index)

    df = pd.DataFrame({
        "close": [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "volume": [1000.0, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900],
    })
    audit_no_lookahead(prepare, df)  # 예외 없이 통과


def test_lookahead_detected_direct_index():
    """같은 시점의 값을 직접 쓰면 감사 실패."""
    def leaky(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"close_same": df["close"]}, index=df.index)

    df = pd.DataFrame({"close": [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    with pytest.raises(LookAheadDetected):
        audit_no_lookahead(leaky, df)


def test_lookahead_detected_future_window():
    """미래 데이터 참조 (shift(-1)) 감지."""
    def leaky(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"next_close": df["close"].shift(-1)}, index=df.index)

    df = pd.DataFrame({"close": [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    with pytest.raises(LookAheadDetected):
        audit_no_lookahead(leaky, df)


def test_lookahead_detected_full_mean():
    """전체 평균 broadcast = look-ahead."""
    def leaky(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {"mean_close": [df["close"].mean()] * len(df)}, index=df.index
        )

    df = pd.DataFrame({"close": [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    with pytest.raises(LookAheadDetected):
        audit_no_lookahead(leaky, df)


def test_rolling_window_with_shift_passes():
    """rolling(5).mean().shift(1) → 통과."""
    def prepare(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {"ma5_prev": df["close"].rolling(5).mean().shift(1)}, index=df.index
        )

    df = pd.DataFrame({"close": [float(x) for x in range(100, 130)]})
    audit_no_lookahead(prepare, df)


def test_rolling_without_shift_fails():
    """rolling(5).mean() shift 없음 → look-ahead (t 포함)."""
    def leaky(df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {"ma5": df["close"].rolling(5).mean()}, index=df.index
        )

    df = pd.DataFrame({"close": [float(x) for x in range(100, 130)]})
    with pytest.raises(LookAheadDetected):
        audit_no_lookahead(leaky, df)


def test_raises_on_too_small_df():
    def prepare(df):
        return df
    df = pd.DataFrame({"close": [1.0, 2, 3]})
    with pytest.raises(ValueError):
        audit_no_lookahead(prepare, df)
