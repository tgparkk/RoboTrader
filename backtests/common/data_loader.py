"""PostgreSQL 데이터 로더 — minute_candles / daily_prices / 지수.

데이터 위치:
- 분봉: robotrader.minute_candles (native 컬럼)
- 종목 일봉: robotrader_quant.daily_prices (2,495 종목, 2023-06~) — 표준 컬럼
- 지수 일봉 (KS11/KQ11): robotrader.daily_candles (KIS raw 컬럼)

날짜 정규화: quant DB 의 date 는 DATE (YYYY-MM-DD) → 분봉/지수 와 동일한 YYYYMMDD 문자열로 변환.
"""
from contextlib import contextmanager
from typing import List

import pandas as pd
import psycopg2

from config.settings import (
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD,
)
try:
    from config.settings import PG_DATABASE_QUANT
except ImportError:
    PG_DATABASE_QUANT = "robotrader_quant"


@contextmanager
def _conn(database: str = None):
    c = psycopg2.connect(
        host=PG_HOST, port=PG_PORT,
        database=database or PG_DATABASE,
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
    """일봉 데이터 (robotrader_quant.daily_prices, 2,495 종목 커버).

    Args:
        codes: 종목 코드 리스트
        start_date, end_date: 'YYYYMMDD' 형식 (분봉과 동일)

    Returns:
        trade_date 가 'YYYYMMDD' 문자열로 정규화된 DataFrame.
    """
    if not codes:
        return pd.DataFrame()
    # YYYYMMDD → YYYY-MM-DD 변환 (quant DB 는 DATE 타입)
    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    # date 는 TEXT (YYYY-MM-DD) — REPLACE 로 하이픈 제거 후 YYYYMMDD 반환
    sql = """
        SELECT stock_code,
               REPLACE(date, '-', '') AS trade_date,
               open, high, low, close, volume,
               trading_value AS amount
        FROM daily_prices
        WHERE stock_code = ANY(%s)
          AND date >= %s
          AND date <= %s
        ORDER BY stock_code, date
    """
    with _conn(PG_DATABASE_QUANT) as c:
        df = pd.read_sql(sql, c, params=(list(codes), sd, ed))
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
