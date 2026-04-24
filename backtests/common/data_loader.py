"""PostgreSQL 데이터 로더 — minute_candles / daily_candles.

스키마:
- minute_candles: native 컬럼 (time → trade_time 리네임)
- daily_candles: KIS raw 컬럼을 CAST 로 숫자화 + 표준 이름으로 alias
"""
from contextlib import contextmanager
from typing import List

import pandas as pd
import psycopg2

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD


@contextmanager
def _conn():
    c = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    try:
        yield c
    finally:
        c.close()


def load_minute_df(
    codes: List[str], start_date: str, end_date: str
) -> pd.DataFrame:
    """분봉 데이터. date 포맷: 'YYYYMMDD'. 빈 codes 는 빈 DataFrame 반환."""
    if not codes:
        return pd.DataFrame()
    sql = """
        SELECT stock_code, trade_date,
               time AS trade_time,
               open, high, low, close, volume, amount
        FROM minute_candles
        WHERE stock_code = ANY(%s)
          AND trade_date >= %s
          AND trade_date <= %s
        ORDER BY stock_code, trade_date, time
    """
    with _conn() as c:
        df = pd.read_sql(sql, c, params=(list(codes), start_date, end_date))
    return df


def load_daily_df(
    codes: List[str], start_date: str, end_date: str
) -> pd.DataFrame:
    """일봉 데이터. KIS raw VARCHAR 컬럼을 DOUBLE 로 캐스팅 + 표준 이름 부여."""
    if not codes:
        return pd.DataFrame()
    sql = """
        SELECT stock_code,
               stck_bsop_date AS trade_date,
               CAST(stck_oprc AS DOUBLE PRECISION) AS open,
               CAST(stck_hgpr AS DOUBLE PRECISION) AS high,
               CAST(stck_lwpr AS DOUBLE PRECISION) AS low,
               CAST(stck_clpr AS DOUBLE PRECISION) AS close,
               CAST(acml_vol AS DOUBLE PRECISION) AS volume,
               CAST(acml_tr_pbmn AS DOUBLE PRECISION) AS amount
        FROM daily_candles
        WHERE stock_code = ANY(%s)
          AND stck_bsop_date >= %s
          AND stck_bsop_date <= %s
        ORDER BY stock_code, stck_bsop_date
    """
    with _conn() as c:
        df = pd.read_sql(sql, c, params=(list(codes), start_date, end_date))
    return df


def load_index_df(
    index_code: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """지수 일봉 (KS11=KOSPI, KQ11=KOSDAQ). daily_candles 에 저장됨."""
    sql = """
        SELECT stck_bsop_date AS trade_date,
               CAST(stck_oprc AS DOUBLE PRECISION) AS open,
               CAST(stck_hgpr AS DOUBLE PRECISION) AS high,
               CAST(stck_lwpr AS DOUBLE PRECISION) AS low,
               CAST(stck_clpr AS DOUBLE PRECISION) AS close
        FROM daily_candles
        WHERE stock_code = %s
          AND stck_bsop_date >= %s
          AND stck_bsop_date <= %s
        ORDER BY stck_bsop_date
    """
    with _conn() as c:
        df = pd.read_sql(sql, c, params=(index_code, start_date, end_date))
    return df
