"""
데이터 캐싱 유틸리티
1분봉/일봉 데이터를 PostgreSQL 기반으로 캐싱하여 관리 편의성 향상

- PostgreSQL을 기본 저장소로 사용 (단일 테이블: minute_candles, daily_candles)
- 기존 pkl 파일도 읽기 가능 (호환성 유지)
- Connection pool 기반 성능 최적화
"""
import os
import pickle
import pandas as pd
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional
from utils.logger import setup_logger

# PostgreSQL connection pool
import psycopg2
import psycopg2.extras
import psycopg2.pool

_pg_pool = None
_pg_pool_lock = threading.Lock()


def _get_pg_pool():
    """PostgreSQL connection pool 획득 (싱글톤)"""
    global _pg_pool
    if _pg_pool is None or _pg_pool.closed:
        with _pg_pool_lock:
            if _pg_pool is None or _pg_pool.closed:
                from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
                _pg_pool = psycopg2.pool.SimpleConnectionPool(
                    minconn=1,
                    maxconn=5,
                    host=PG_HOST,
                    port=PG_PORT,
                    database=PG_DATABASE,
                    user=PG_USER,
                    password=PG_PASSWORD,
                    connect_timeout=10,
                )
    return _pg_pool


def _ensure_cache_tables():
    """캐시 테이블 생성 (최초 1회)"""
    pool = _get_pg_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()

        # 분봉 캐시 테이블 (단일 테이블)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS minute_candles (
                stock_code VARCHAR NOT NULL,
                trade_date VARCHAR NOT NULL,
                idx INTEGER NOT NULL,
                date VARCHAR,
                time VARCHAR,
                close DOUBLE PRECISION,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                volume DOUBLE PRECISION,
                amount DOUBLE PRECISION,
                datetime TIMESTAMP,
                PRIMARY KEY (stock_code, trade_date, idx)
            )
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_minute_candles_code_date ON minute_candles(stock_code, trade_date)')

        # 일봉 캐시 테이블 (단일 테이블)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS daily_candles (
                stock_code VARCHAR NOT NULL,
                stck_bsop_date VARCHAR NOT NULL,
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
                PRIMARY KEY (stock_code, stck_bsop_date)
            )
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_daily_candles_code ON daily_candles(stock_code)')

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# 초기화 플래그
_tables_ensured = False
_tables_lock = threading.Lock()


def _ensure_tables_once():
    """테이블 생성 1회만 실행"""
    global _tables_ensured
    if not _tables_ensured:
        with _tables_lock:
            if not _tables_ensured:
                _ensure_cache_tables()
                _tables_ensured = True


class DataCache:
    """PostgreSQL 기반 분봉 데이터 캐시 관리자

    - 기본적으로 PostgreSQL에서 데이터를 읽고 씀
    - PostgreSQL에 데이터가 없으면 pkl 폴백 로드
    """

    def __init__(self, cache_dir: str = "cache/minute_data", use_duckdb: bool = True):
        self.logger = setup_logger(__name__)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        _ensure_tables_once()

    @classmethod
    def close_all_connections(cls):
        """호환성 유지용 (no-op)"""
        pass

    def _get_cache_file(self, stock_code: str, date_str: str) -> Path:
        """캐시 파일 경로 생성 (pkl 폴백용)"""
        return self.cache_dir / f"{stock_code}_{date_str}.pkl"

    def has_data(self, stock_code: str, date_str: str) -> bool:
        """캐시된 데이터 존재 여부 확인"""
        # PostgreSQL 확인
        try:
            pool = _get_pg_pool()
            conn = pool.getconn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT COUNT(*) FROM minute_candles WHERE stock_code = %s AND trade_date = %s",
                    (stock_code, date_str)
                )
                count = cur.fetchone()[0]
                if count > 0:
                    return True
            finally:
                pool.putconn(conn)
        except Exception:
            pass

        # pkl 폴백
        cache_file = self._get_cache_file(stock_code, date_str)
        return cache_file.exists()

    def save_data(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """1분봉 데이터를 PostgreSQL에 저장"""
        try:
            if df_minute is None or df_minute.empty:
                return True

            return self._save_to_pg(stock_code, date_str, df_minute)

        except Exception as e:
            self.logger.error(f"캐시 저장 실패 ({stock_code}, {date_str}): {e}")
            return False

    def _save_to_pg(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """PostgreSQL에 저장"""
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()

            # 기존 데이터 삭제
            cur.execute("DELETE FROM minute_candles WHERE stock_code = %s AND trade_date = %s",
                        (stock_code, date_str))

            # DataFrame 준비
            df_to_save = df_minute.copy().reset_index(drop=True)

            rows = []
            for idx, row in df_to_save.iterrows():
                dt_val = row.get('datetime', None)
                if dt_val is not None and hasattr(dt_val, 'strftime'):
                    dt_str = dt_val.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    dt_str = str(dt_val) if dt_val is not None else None

                rows.append((
                    stock_code,
                    date_str,
                    int(idx),
                    str(row.get('date', '')) if pd.notna(row.get('date', None)) else None,
                    str(row.get('time', '')) if pd.notna(row.get('time', None)) else None,
                    float(row.get('close', 0)) if pd.notna(row.get('close', 0)) else 0,
                    float(row.get('open', 0)) if pd.notna(row.get('open', 0)) else 0,
                    float(row.get('high', 0)) if pd.notna(row.get('high', 0)) else 0,
                    float(row.get('low', 0)) if pd.notna(row.get('low', 0)) else 0,
                    float(row.get('volume', 0)) if pd.notna(row.get('volume', 0)) else 0,
                    float(row.get('amount', 0)) if pd.notna(row.get('amount', 0)) else 0,
                    dt_str,
                ))

            if rows:
                psycopg2.extras.execute_batch(
                    cur,
                    '''INSERT INTO minute_candles
                    (stock_code, trade_date, idx, date, time, close, open, high, low, volume, amount, datetime)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    rows,
                    page_size=500,
                )

            conn.commit()
            self.logger.debug(f"[{stock_code}] PG 저장 완료 ({len(df_minute)}개)")
            return True

        except Exception as e:
            conn.rollback()
            self.logger.warning(f"PG 저장 실패, pkl로 폴백: {e}")
            return self._save_to_pkl(stock_code, date_str, df_minute)
        finally:
            pool.putconn(conn)

    def _save_to_pkl(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """pkl 파일로 저장 (폴백)"""
        cache_file = self._get_cache_file(stock_code, date_str)
        with open(cache_file, 'wb') as f:
            pickle.dump(df_minute, f, protocol=pickle.HIGHEST_PROTOCOL)
        self.logger.debug(f"[{stock_code}] pkl 저장 완료 ({len(df_minute)}개)")
        return True

    def load_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """캐시된 1분봉 데이터 로드"""
        try:
            # PostgreSQL 먼저
            df = self._load_from_pg(stock_code, date_str)
            if df is not None:
                return df

            # pkl 폴백
            return self._load_from_pkl(stock_code, date_str)

        except Exception as e:
            self.logger.error(f"캐시 로드 실패 ({stock_code}, {date_str}): {e}")
            return None

    def _load_from_pg(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """PostgreSQL에서 로드"""
        try:
            pool = _get_pg_pool()
            conn = pool.getconn()
            try:
                df = pd.read_sql_query(
                    '''SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s
                    ORDER BY idx''',
                    conn,
                    params=(stock_code, date_str)
                )

                if df.empty:
                    return None

                df.set_index('idx', inplace=True)
                #self.logger.debug(f"[{stock_code}] PG에서 로드 ({len(df)}개)")
                return df
            finally:
                pool.putconn(conn)
        except Exception as e:
            self.logger.debug(f"PG 로드 실패: {e}")
            return None

    def _load_from_pkl(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """pkl 파일에서 로드 (폴백)"""
        cache_file = self._get_cache_file(stock_code, date_str)

        if not cache_file.exists():
            return None

        with open(cache_file, 'rb') as f:
            df_minute = pickle.load(f)

        #self.logger.debug(f"[{stock_code}] pkl에서 로드 ({len(df_minute)}개)")
        return df_minute

    def clear_cache(self, stock_code: str = None, date_str: str = None):
        """캐시 정리"""
        try:
            pool = _get_pg_pool()
            conn = pool.getconn()
            try:
                cur = conn.cursor()
                if stock_code and date_str:
                    cur.execute("DELETE FROM minute_candles WHERE stock_code = %s AND trade_date = %s",
                                (stock_code, date_str))
                    self.logger.info(f"PG 데이터 삭제: {stock_code}_{date_str}")
                elif stock_code:
                    cur.execute("DELETE FROM minute_candles WHERE stock_code = %s", (stock_code,))
                    self.logger.info(f"PG 종목 데이터 삭제: {stock_code}")
                else:
                    cur.execute("DELETE FROM minute_candles")
                    self.logger.info("PG 전체 분봉 데이터 삭제")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                pool.putconn(conn)

            # pkl 파일도 삭제
            if stock_code and date_str:
                cache_file = self._get_cache_file(stock_code, date_str)
                if cache_file.exists():
                    cache_file.unlink()
            else:
                for cache_file in self.cache_dir.glob("*.pkl"):
                    cache_file.unlink()
                self.logger.info(f"전체 pkl 캐시 정리 완료: {self.cache_dir}")

        except Exception as e:
            self.logger.error(f"캐시 정리 실패: {e}")

    def get_cache_size(self) -> dict:
        """캐시 크기 정보"""
        try:
            result = {
                'total_tables': 0,
                'total_records': 0,
                'total_size_mb': 0,
                'cache_dir': str(self.cache_dir),
                'storage': 'postgresql'
            }

            pool = _get_pg_pool()
            conn = pool.getconn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(DISTINCT stock_code) FROM minute_candles")
                result['total_tables'] = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM minute_candles")
                result['total_records'] = cur.fetchone()[0]
            finally:
                pool.putconn(conn)

            return result

        except Exception as e:
            self.logger.error(f"캐시 크기 확인 실패: {e}")
            return {'total_tables': 0, 'total_records': 0, 'total_size_mb': 0, 'cache_dir': str(self.cache_dir), 'storage': 'error'}

    def __enter__(self):
        """Context Manager 진입"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager 종료"""
        pass


class DailyDataCache:
    """PostgreSQL 기반 일봉 데이터 캐시 관리자

    - 기본적으로 PostgreSQL에서 데이터를 읽고 씀
    - pkl 폴백 지원
    """

    def __init__(self, cache_dir: str = "cache/daily", use_duckdb: bool = True):
        self.logger = setup_logger(__name__)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        _ensure_tables_once()

    @classmethod
    def close_all_connections(cls):
        """호환성 유지용 (no-op)"""
        pass

    def _get_cache_file(self, stock_code: str, date_str: str) -> Path:
        """캐시 파일 경로 생성 (pkl 폴백용)"""
        return self.cache_dir / f"{stock_code}_{date_str}_daily.pkl"

    def has_data(self, stock_code: str, min_records: int = 50) -> bool:
        """캐시된 일봉 데이터 존재 여부 확인 (최소 레코드 수 기준)"""
        # PostgreSQL 확인
        try:
            pool = _get_pg_pool()
            conn = pool.getconn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM daily_candles WHERE stock_code = %s", (stock_code,))
                count = cur.fetchone()[0]
                if count >= min_records:
                    return True
            finally:
                pool.putconn(conn)
        except Exception:
            pass

        return False

    def save_data(self, stock_code: str, df_daily: pd.DataFrame) -> bool:
        """일봉 데이터를 PostgreSQL에 저장"""
        try:
            if df_daily is None or df_daily.empty:
                return True

            return self._save_to_pg(stock_code, df_daily)

        except Exception as e:
            self.logger.error(f"일봉 캐시 저장 실패 ({stock_code}): {e}")
            return False

    def _save_to_pg(self, stock_code: str, df_daily: pd.DataFrame) -> bool:
        """PostgreSQL에 저장"""
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor()

            cols = ['stck_bsop_date', 'stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr',
                    'acml_vol', 'acml_tr_pbmn', 'flng_cls_code', 'prtt_rate', 'mod_yn',
                    'prdy_vrss_sign', 'prdy_vrss', 'revl_issu_reas']

            df_to_save = df_daily.copy()
            for col in cols:
                if col not in df_to_save.columns:
                    df_to_save[col] = ''

            rows = []
            dates = []
            for _, row in df_to_save.iterrows():
                date_val = str(row.get('stck_bsop_date', ''))
                if not date_val:
                    continue
                dates.append(date_val)
                rows.append((
                    stock_code,
                    date_val,
                    str(row.get('stck_clpr', '')),
                    str(row.get('stck_oprc', '')),
                    str(row.get('stck_hgpr', '')),
                    str(row.get('stck_lwpr', '')),
                    str(row.get('acml_vol', '')),
                    str(row.get('acml_tr_pbmn', '')),
                    str(row.get('flng_cls_code', '')),
                    str(row.get('prtt_rate', '')),
                    str(row.get('mod_yn', '')),
                    str(row.get('prdy_vrss_sign', '')),
                    str(row.get('prdy_vrss', '')),
                    str(row.get('revl_issu_reas', '')),
                ))

            if rows:
                # 기존 날짜 데이터 삭제
                if dates:
                    cur.execute(
                        "DELETE FROM daily_candles WHERE stock_code = %s AND stck_bsop_date = ANY(%s)",
                        (stock_code, dates)
                    )

                psycopg2.extras.execute_batch(
                    cur,
                    '''INSERT INTO daily_candles
                    (stock_code, stck_bsop_date, stck_clpr, stck_oprc, stck_hgpr, stck_lwpr,
                     acml_vol, acml_tr_pbmn, flng_cls_code, prtt_rate, mod_yn,
                     prdy_vrss_sign, prdy_vrss, revl_issu_reas)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    rows,
                    page_size=500,
                )

            conn.commit()
            self.logger.debug(f"[{stock_code}] 일봉 PG 저장 완료 ({len(df_daily)}개)")
            return True

        except Exception as e:
            conn.rollback()
            self.logger.warning(f"일봉 PG 저장 실패: {e}")
            return False
        finally:
            pool.putconn(conn)

    def load_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """캐시된 일봉 데이터 로드"""
        try:
            # PostgreSQL 먼저
            df = self._load_from_pg(stock_code)
            if df is not None:
                return df

            # pkl 폴백
            return self._load_from_pkl(stock_code)

        except Exception as e:
            self.logger.error(f"일봉 캐시 로드 실패 ({stock_code}): {e}")
            return None

    def _load_from_pg(self, stock_code: str) -> Optional[pd.DataFrame]:
        """PostgreSQL에서 로드"""
        try:
            pool = _get_pg_pool()
            conn = pool.getconn()
            try:
                df = pd.read_sql_query(
                    '''SELECT stck_bsop_date, stck_clpr, stck_oprc, stck_hgpr, stck_lwpr,
                              acml_vol, acml_tr_pbmn, flng_cls_code, prtt_rate, mod_yn,
                              prdy_vrss_sign, prdy_vrss, revl_issu_reas
                    FROM daily_candles
                    WHERE stock_code = %s
                    ORDER BY stck_bsop_date''',
                    conn,
                    params=(stock_code,)
                )

                if df.empty:
                    return None

                #self.logger.debug(f"[{stock_code}] 일봉 PG에서 로드 ({len(df)}개)")
                return df
            finally:
                pool.putconn(conn)
        except Exception as e:
            self.logger.debug(f"일봉 PG 로드 실패: {e}")
            return None

    def _load_from_pkl(self, stock_code: str) -> Optional[pd.DataFrame]:
        """pkl 파일에서 로드 (최신 파일)"""
        pkl_files = list(self.cache_dir.glob(f"{stock_code}_*_daily.pkl"))
        if not pkl_files:
            return None

        latest_file = max(pkl_files, key=lambda f: f.stat().st_mtime)
        with open(latest_file, 'rb') as f:
            df_daily = pickle.load(f)

        #self.logger.debug(f"[{stock_code}] 일봉 pkl에서 로드 ({len(df_daily)}개)")
        return df_daily

    def __enter__(self):
        """Context Manager 진입"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager 종료"""
        pass
