# -*- coding: utf-8 -*-
"""
DuckDB 기반 캐시 데이터 관리 유틸리티

pkl 파일 대신 DuckDB를 사용하여 분봉/일봉 데이터를 관리합니다.
- 읽기/쓰기 인터페이스 제공
- 기존 pkl 코드와 호환되는 DataFrame 반환
"""

import os
import duckdb
import pandas as pd
from typing import Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# DB 파일 경로
DB_PATH = Path(__file__).parent.parent / "cache" / "market_data.duckdb"


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """DuckDB 연결 반환"""
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def init_db():
    """DB 스키마 초기화 (테이블 생성)"""
    con = get_connection()

    # 분봉 데이터 테이블
    con.execute("""
        CREATE TABLE IF NOT EXISTS minute_data (
            stock_code VARCHAR NOT NULL,
            trade_date VARCHAR NOT NULL,
            idx INTEGER NOT NULL,
            date VARCHAR,
            time VARCHAR,
            close DOUBLE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            volume DOUBLE,
            amount DOUBLE,
            datetime TIMESTAMP,
            PRIMARY KEY (stock_code, trade_date, idx)
        )
    """)

    # 일봉 데이터 테이블
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_data (
            stock_code VARCHAR NOT NULL,
            base_date VARCHAR NOT NULL,
            stck_bsop_date VARCHAR,
            stck_clpr VARCHAR,
            stck_oprc VARCHAR,
            stck_hgpr VARCHAR,
            stck_lwpr VARCHAR,
            acml_vol VARCHAR,
            acml_tr_pbmn VARCHAR,
            flng_cls_code VARCHAR,
            prtt_rate VARCHAR,
            mod_yn VARCHAR,
            prdy_vrss_sign VARCHAR,
            prdy_vrss VARCHAR,
            revl_issu_reas VARCHAR,
            PRIMARY KEY (stock_code, base_date, stck_bsop_date)
        )
    """)

    # 인덱스 생성
    con.execute("CREATE INDEX IF NOT EXISTS idx_minute_stock_date ON minute_data(stock_code, trade_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_daily_stock_date ON daily_data(stock_code, base_date)")

    con.close()
    logger.info(f"DB 초기화 완료: {DB_PATH}")


def get_minute_data(stock_code: str, trade_date: str) -> Optional[pd.DataFrame]:
    """
    분봉 데이터 조회 (기존 pkl 인터페이스와 동일한 DataFrame 반환)

    Args:
        stock_code: 종목코드 (예: "005930")
        trade_date: 거래일 (예: "20250918")

    Returns:
        DataFrame 또는 None (데이터 없음)
    """
    try:
        con = get_connection(read_only=True)
        df = con.execute("""
            SELECT idx, date, time, close, open, high, low, volume, amount, datetime
            FROM minute_data
            WHERE stock_code = ? AND trade_date = ?
            ORDER BY idx
        """, [stock_code, trade_date]).fetchdf()
        con.close()

        if df.empty:
            return None

        # 기존 pkl 형식과 동일하게 인덱스 설정
        df.set_index('idx', inplace=True)
        return df

    except Exception as e:
        logger.error(f"분봉 데이터 조회 실패 [{stock_code}_{trade_date}]: {e}")
        return None


def save_minute_data(stock_code: str, trade_date: str, df: pd.DataFrame) -> bool:
    """
    분봉 데이터 저장

    Args:
        stock_code: 종목코드
        trade_date: 거래일
        df: 분봉 DataFrame

    Returns:
        성공 여부
    """
    try:
        con = get_connection()

        # 기존 데이터 삭제
        con.execute("""
            DELETE FROM minute_data WHERE stock_code = ? AND trade_date = ?
        """, [stock_code, trade_date])

        # DataFrame 준비
        df_to_save = df.copy()
        df_to_save['stock_code'] = stock_code
        df_to_save['trade_date'] = trade_date
        df_to_save['idx'] = df.index

        # 삽입
        con.execute("""
            INSERT INTO minute_data
            SELECT stock_code, trade_date, idx, date, time, close, open, high, low, volume, amount, datetime
            FROM df_to_save
        """)

        con.close()
        return True

    except Exception as e:
        logger.error(f"분봉 데이터 저장 실패 [{stock_code}_{trade_date}]: {e}")
        return False


def get_daily_data(stock_code: str, base_date: str) -> Optional[pd.DataFrame]:
    """
    일봉 데이터 조회

    Args:
        stock_code: 종목코드
        base_date: 기준일 (파일명의 날짜)

    Returns:
        DataFrame 또는 None
    """
    try:
        con = get_connection(read_only=True)
        df = con.execute("""
            SELECT stck_bsop_date, stck_clpr, stck_oprc, stck_hgpr, stck_lwpr,
                   acml_vol, acml_tr_pbmn, flng_cls_code, prtt_rate, mod_yn,
                   prdy_vrss_sign, prdy_vrss, revl_issu_reas
            FROM daily_data
            WHERE stock_code = ? AND base_date = ?
            ORDER BY stck_bsop_date DESC
        """, [stock_code, base_date]).fetchdf()
        con.close()

        if df.empty:
            return None

        return df

    except Exception as e:
        logger.error(f"일봉 데이터 조회 실패 [{stock_code}_{base_date}]: {e}")
        return None


def save_daily_data(stock_code: str, base_date: str, df: pd.DataFrame) -> bool:
    """
    일봉 데이터 저장
    """
    try:
        con = get_connection()

        # 기존 데이터 삭제
        con.execute("""
            DELETE FROM daily_data WHERE stock_code = ? AND base_date = ?
        """, [stock_code, base_date])

        # DataFrame 준비
        df_to_save = df.copy()
        df_to_save['stock_code'] = stock_code
        df_to_save['base_date'] = base_date

        # 삽입
        con.execute("""
            INSERT INTO daily_data
            SELECT stock_code, base_date, stck_bsop_date, stck_clpr, stck_oprc,
                   stck_hgpr, stck_lwpr, acml_vol, acml_tr_pbmn, flng_cls_code,
                   prtt_rate, mod_yn, prdy_vrss_sign, prdy_vrss, revl_issu_reas
            FROM df_to_save
        """)

        con.close()
        return True

    except Exception as e:
        logger.error(f"일봉 데이터 저장 실패 [{stock_code}_{base_date}]: {e}")
        return False


def list_minute_data(stock_code: Optional[str] = None) -> list:
    """저장된 분봉 데이터 목록 조회"""
    con = get_connection(read_only=True)

    if stock_code:
        result = con.execute("""
            SELECT DISTINCT stock_code, trade_date
            FROM minute_data
            WHERE stock_code = ?
            ORDER BY trade_date
        """, [stock_code]).fetchall()
    else:
        result = con.execute("""
            SELECT DISTINCT stock_code, trade_date
            FROM minute_data
            ORDER BY stock_code, trade_date
        """).fetchall()

    con.close()
    return result


def get_db_stats() -> dict:
    """DB 통계 조회"""
    con = get_connection(read_only=True)

    minute_count = con.execute("SELECT COUNT(DISTINCT stock_code || trade_date) FROM minute_data").fetchone()[0]
    daily_count = con.execute("SELECT COUNT(DISTINCT stock_code || base_date) FROM daily_data").fetchone()[0]
    minute_rows = con.execute("SELECT COUNT(*) FROM minute_data").fetchone()[0]
    daily_rows = con.execute("SELECT COUNT(*) FROM daily_data").fetchone()[0]

    con.close()

    db_size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0

    return {
        'minute_data_count': minute_count,
        'daily_data_count': daily_count,
        'minute_rows': minute_rows,
        'daily_rows': daily_rows,
        'db_size_mb': db_size / (1024 * 1024)
    }


if __name__ == "__main__":
    # 테스트
    init_db()
    stats = get_db_stats()
    print(f"DB 통계: {stats}")
