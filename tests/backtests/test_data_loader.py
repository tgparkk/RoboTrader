"""backtests.common.data_loader 단위 테스트.

실제 DB 접속 필요 (PG_HOST:5433 robotrader). DB 접속 불가 시 스킵.
"""
import pandas as pd
import pytest
import psycopg2

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from backtests.common.data_loader import (
    load_minute_df,
    load_daily_df,
    load_index_df,
)


def _db_available() -> bool:
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD, connect_timeout=2,
        )
        conn.close()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="DB 접속 불가")


@requires_db
def test_load_minute_df_returns_standardized_columns():
    """minute_candles 에서 로드 시 표준 컬럼 반환."""
    df = load_minute_df(codes=["005930"], start_date="20260401", end_date="20260402")
    assert isinstance(df, pd.DataFrame)
    expected_cols = {"stock_code", "trade_date", "trade_time", "open", "high", "low", "close", "volume"}
    assert expected_cols.issubset(df.columns), f"실제 컬럼: {df.columns.tolist()}"


@requires_db
def test_load_minute_df_filters_by_date():
    df = load_minute_df(codes=["005930"], start_date="20260401", end_date="20260402")
    if not df.empty:
        assert df["trade_date"].min() >= "20260401"
        assert df["trade_date"].max() <= "20260402"


@requires_db
def test_load_minute_df_empty_on_future_date():
    df = load_minute_df(codes=["005930"], start_date="20300101", end_date="20300102")
    assert len(df) == 0


@requires_db
def test_load_minute_df_empty_codes():
    df = load_minute_df(codes=[], start_date="20260401", end_date="20260401")
    assert df.empty


@requires_db
def test_load_daily_df_returns_standardized_columns():
    df = load_daily_df(codes=["005930"], start_date="20250101", end_date="20250131")
    if df.empty:
        pytest.skip("daily_candles 에 해당 기간 데이터 없음")
    expected = {"stock_code", "trade_date", "open", "high", "low", "close", "volume"}
    assert expected.issubset(df.columns), f"실제 컬럼: {df.columns.tolist()}"


@requires_db
def test_load_daily_df_numeric_columns():
    """daily_candles 는 VARCHAR 로 저장돼 있으므로 CAST 후 숫자형이어야 함."""
    df = load_daily_df(codes=["005930"], start_date="20250101", end_date="20250131")
    if df.empty:
        pytest.skip("데이터 없음")
    for col in ["open", "high", "low", "close", "volume"]:
        assert pd.api.types.is_numeric_dtype(df[col]), f"{col} 이 숫자형 아님"


@requires_db
def test_load_index_df_kospi():
    df = load_index_df(index_code="KS11", start_date="20250101", end_date="20250131")
    assert not df.empty, "KS11 인덱스 데이터 없음"
    assert {"trade_date", "open", "high", "low", "close"}.issubset(df.columns)
    for col in ["open", "high", "low", "close"]:
        assert pd.api.types.is_numeric_dtype(df[col])


@requires_db
def test_load_index_df_kosdaq():
    df = load_index_df(index_code="KQ11", start_date="20250101", end_date="20250131")
    assert not df.empty, "KQ11 인덱스 데이터 없음"
