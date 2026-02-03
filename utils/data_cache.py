"""
데이터 캐싱 유틸리티
1분봉 데이터를 DuckDB 기반으로 캐싱하여 관리 편의성 향상

- DuckDB를 기본 저장소로 사용
- 기존 pkl 파일도 읽기 가능 (호환성 유지)
- Thread-local 연결 풀링으로 성능 최적화
- 쓰기 작업은 글로벌 Lock으로 동시성 보호
"""
import os
import pickle
import pandas as pd
import duckdb
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional
from utils.logger import setup_logger


# DuckDB 파일 경로
DB_PATH = Path(__file__).parent.parent / "cache" / "market_data_v2.duckdb"

# 글로벌 쓰기 Lock (DuckDB는 단일 Writer만 허용)
_write_lock = threading.Lock()


class DataCache:
    """DuckDB 기반 데이터 캐시 관리자

    - 기본적으로 DuckDB에서 데이터를 읽고 씀
    - DuckDB에 데이터가 없으면 pkl 파일에서 폴백 로드 (호환성)
    - Thread-local 연결 풀링으로 성능 최적화
    """

    # 스레드별 DuckDB 연결 저장소
    _thread_local = threading.local()

    def __init__(self, cache_dir: str = "cache/minute_data", use_duckdb: bool = True):
        self.logger = setup_logger(__name__)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.use_duckdb = use_duckdb and DB_PATH.exists()

        if self.use_duckdb:
            self._init_db()

    def _init_db(self):
        """DuckDB 연결 확인 (종목별 테이블 구조 사용)"""
        try:
            con = duckdb.connect(str(DB_PATH), read_only=True)
            con.close()
        except Exception as e:
            self.logger.warning(f"DuckDB 초기화 실패, pkl 모드로 전환: {e}")
            self.use_duckdb = False

    def _get_connection(self):
        """스레드별 DuckDB 연결 반환 (재사용)

        각 스레드마다 하나의 연결을 유지하여 연결 생성 오버헤드 제거
        """
        if not hasattr(self._thread_local, 'connection') or self._thread_local.connection is None:
            self._thread_local.connection = duckdb.connect(str(DB_PATH), read_only=True)
        return self._thread_local.connection

    def _get_table_name(self, stock_code: str) -> str:
        """종목별 테이블명 생성"""
        return f"minute_{stock_code}"

    def _create_table_if_not_exists(self, con: duckdb.DuckDBPyConnection, stock_code: str):
        """종목별 테이블 생성"""
        table_name = self._get_table_name(stock_code)
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
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
                PRIMARY KEY (trade_date, idx)
            )
        """)
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON {table_name}(trade_date)")

    def _get_cache_file(self, stock_code: str, date_str: str) -> Path:
        """캐시 파일 경로 생성 (pkl 폴백용)"""
        return self.cache_dir / f"{stock_code}_{date_str}.pkl"

    def has_data(self, stock_code: str, date_str: str) -> bool:
        """캐시된 데이터 존재 여부 확인 - 연결 풀링 사용"""
        if self.use_duckdb:
            try:
                table_name = self._get_table_name(stock_code)
                con = self._get_connection()  # 재사용되는 연결
                # 테이블 존재 여부 확인
                tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name = ?", [table_name]).fetchall()
                if not tables:
                    return False

                count = con.execute(f"""
                    SELECT COUNT(*) FROM {table_name}
                    WHERE trade_date = ?
                """, [date_str]).fetchone()[0]
                # con.close() 제거 - 연결 유지
                if count > 0:
                    return True
            except:
                pass

        # pkl 폴백
        cache_file = self._get_cache_file(stock_code, date_str)
        return cache_file.exists()

    def save_data(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """1분봉 데이터를 DuckDB에 저장"""
        try:
            if df_minute is None or df_minute.empty:
                return True

            if self.use_duckdb:
                return self._save_to_duckdb(stock_code, date_str, df_minute)
            else:
                return self._save_to_pkl(stock_code, date_str, df_minute)

        except Exception as e:
            self.logger.error(f"캐시 저장 실패 ({stock_code}, {date_str}): {e}")
            return False

    def _save_to_duckdb(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """DuckDB에 저장 (종목별 테이블) - 글로벌 Lock으로 동시성 보호"""
        # 글로벌 Lock 획득 (DuckDB는 단일 Writer만 허용)
        with _write_lock:
            try:
                table_name = self._get_table_name(stock_code)
                con = duckdb.connect(str(DB_PATH))

                # WAL 모드 활성화 (동시 읽기 성능 향상)
                try:
                    con.execute("PRAGMA wal_autocheckpoint=1000")
                except:
                    pass  # DuckDB 버전에 따라 지원 안될 수 있음

                # 테이블 생성 (없으면)
                self._create_table_if_not_exists(con, stock_code)

                # DataFrame 준비 (인덱스 리셋으로 중복 방지)
                df_to_save = df_minute.copy().reset_index(drop=True)
                df_to_save['trade_date'] = date_str
                df_to_save['idx'] = range(len(df_to_save))

                # 트랜잭션으로 DELETE + INSERT 원자적 실행
                con.execute("BEGIN TRANSACTION")
                try:
                    # 기존 데이터 삭제
                    con.execute(f"""
                        DELETE FROM {table_name} WHERE trade_date = ?
                    """, [date_str])

                    # 삽입
                    con.execute(f"""
                        INSERT INTO {table_name}
                        SELECT trade_date, idx, date, time, close, open, high, low, volume, amount, datetime
                        FROM df_to_save
                    """)
                    con.execute("COMMIT")
                except Exception as inner_e:
                    con.execute("ROLLBACK")
                    raise inner_e
                finally:
                    con.close()

                self.logger.debug(f"[{stock_code}] DuckDB 저장 완료 ({len(df_minute)}개)")
                return True

            except Exception as e:
                self.logger.warning(f"DuckDB 저장 실패, pkl로 폴백: {e}")
                return self._save_to_pkl(stock_code, date_str, df_minute)

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
            # DuckDB에서 먼저 시도
            if self.use_duckdb:
                df = self._load_from_duckdb(stock_code, date_str)
                if df is not None:
                    return df

            # pkl 폴백
            return self._load_from_pkl(stock_code, date_str)

        except Exception as e:
            self.logger.error(f"캐시 로드 실패 ({stock_code}, {date_str}): {e}")
            return None

    def _load_from_duckdb(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """DuckDB에서 로드 (종목별 테이블) - 연결 풀링 사용"""
        try:
            table_name = self._get_table_name(stock_code)
            con = self._get_connection()  # 재사용되는 연결

            # 테이블 존재 여부 확인
            tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name = ?", [table_name]).fetchall()
            if not tables:
                return None

            df = con.execute(f"""
                SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                FROM {table_name}
                WHERE trade_date = ?
                ORDER BY idx
            """, [date_str]).fetchdf()
            # con.close() 제거 - 연결 유지

            if df.empty:
                return None

            df.set_index('idx', inplace=True)
            self.logger.debug(f"[{stock_code}] DuckDB에서 로드 ({len(df)}개)")
            return df

        except Exception as e:
            self.logger.debug(f"DuckDB 로드 실패: {e}")
            return None

    def _load_from_pkl(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """pkl 파일에서 로드 (폴백)"""
        cache_file = self._get_cache_file(stock_code, date_str)

        if not cache_file.exists():
            return None

        with open(cache_file, 'rb') as f:
            df_minute = pickle.load(f)

        self.logger.debug(f"[{stock_code}] pkl에서 로드 ({len(df_minute)}개)")
        return df_minute

    def clear_cache(self, stock_code: str = None, date_str: str = None):
        """캐시 정리 (종목별 테이블) - 글로벌 Lock으로 동시성 보호"""
        try:
            if self.use_duckdb:
                with _write_lock:
                    con = duckdb.connect(str(DB_PATH))
                    try:
                        if stock_code and date_str:
                            table_name = self._get_table_name(stock_code)
                            # 테이블 존재 여부 확인
                            tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name = ?", [table_name]).fetchall()
                            if tables:
                                con.execute(f"DELETE FROM {table_name} WHERE trade_date = ?", [date_str])
                            self.logger.info(f"DuckDB 데이터 삭제: {stock_code}_{date_str}")
                        elif stock_code:
                            table_name = self._get_table_name(stock_code)
                            tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name = ?", [table_name]).fetchall()
                            if tables:
                                con.execute(f"DROP TABLE {table_name}")
                            self.logger.info(f"DuckDB 테이블 삭제: {table_name}")
                        else:
                            # 모든 minute_ 테이블 삭제
                            tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'minute_%'").fetchall()
                            for (table_name,) in tables:
                                con.execute(f"DROP TABLE {table_name}")
                            self.logger.info(f"DuckDB 전체 분봉 테이블 삭제 ({len(tables)}개)")
                    finally:
                        con.close()

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
        """캐시 크기 정보 (종목별 테이블)"""
        try:
            result = {
                'total_tables': 0,
                'total_records': 0,
                'total_size_mb': 0,
                'cache_dir': str(self.cache_dir),
                'storage': 'unknown'
            }

            if self.use_duckdb and DB_PATH.exists():
                con = self._get_connection()  # 재사용되는 연결
                # 분봉 테이블 수
                tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'minute_%'").fetchall()
                result['total_tables'] = len(tables)

                # 전체 레코드 수 (샘플링으로 추정)
                total_records = 0
                for (table_name,) in tables[:10]:  # 샘플 10개로 추정
                    count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    total_records += count
                if tables:
                    result['total_records'] = int(total_records * len(tables) / min(10, len(tables)))

                # con.close() 제거 - 연결 유지
                result['total_size_mb'] = round(DB_PATH.stat().st_size / (1024 * 1024), 2)
                result['storage'] = 'duckdb'
            else:
                for cache_file in self.cache_dir.glob("*.pkl"):
                    result['total_tables'] += 1
                    result['total_size_mb'] += cache_file.stat().st_size / (1024 * 1024)
                result['total_size_mb'] = round(result['total_size_mb'], 2)
                result['storage'] = 'pkl'

            return result

        except Exception as e:
            self.logger.error(f"캐시 크기 확인 실패: {e}")
            return {'total_tables': 0, 'total_records': 0, 'total_size_mb': 0, 'cache_dir': str(self.cache_dir), 'storage': 'error'}

    def __enter__(self):
        """Context Manager 진입"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager 종료 - 스레드 로컬 연결 정리"""
        if hasattr(self._thread_local, 'connection') and self._thread_local.connection is not None:
            try:
                self._thread_local.connection.close()
                self._thread_local.connection = None
            except Exception as e:
                self.logger.warning(f"연결 정리 실패: {e}")


class DailyDataCache:
    """DuckDB 기반 일봉 데이터 캐시 관리자

    - 기본적으로 DuckDB에서 데이터를 읽고 씀
    - DuckDB에 데이터가 없으면 pkl 파일에서 폴백 로드 (호환성)
    - Thread-local 연결 풀링으로 성능 최적화
    """

    # 스레드별 DuckDB 연결 저장소
    _thread_local = threading.local()

    def __init__(self, cache_dir: str = "cache/daily", use_duckdb: bool = True):
        self.logger = setup_logger(__name__)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.use_duckdb = use_duckdb and DB_PATH.exists()

    def _get_connection(self):
        """스레드별 DuckDB 연결 반환 (재사용)

        각 스레드마다 하나의 연결을 유지하여 연결 생성 오버헤드 제거
        """
        if not hasattr(self._thread_local, 'connection') or self._thread_local.connection is None:
            self._thread_local.connection = duckdb.connect(str(DB_PATH), read_only=True)
        return self._thread_local.connection

    def _get_table_name(self, stock_code: str) -> str:
        """종목별 테이블명 생성"""
        return f"daily_{stock_code}"

    def _create_table_if_not_exists(self, con: duckdb.DuckDBPyConnection, stock_code: str):
        """종목별 일봉 테이블 생성"""
        table_name = self._get_table_name(stock_code)
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                stck_bsop_date VARCHAR PRIMARY KEY,
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
                revl_issu_reas VARCHAR
            )
        """)

    def _get_cache_file(self, stock_code: str, date_str: str) -> Path:
        """캐시 파일 경로 생성 (pkl 폴백용)"""
        return self.cache_dir / f"{stock_code}_{date_str}_daily.pkl"

    def has_data(self, stock_code: str, min_records: int = 50) -> bool:
        """캐시된 일봉 데이터 존재 여부 확인 (최소 레코드 수 기준) - 연결 풀링 사용"""
        if self.use_duckdb:
            try:
                table_name = self._get_table_name(stock_code)
                con = self._get_connection()  # 재사용되는 연결
                tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name = ?", [table_name]).fetchall()
                if not tables:
                    return False

                count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                # con.close() 제거 - 연결 유지
                if count >= min_records:
                    return True
            except:
                pass
        return False

    def save_data(self, stock_code: str, df_daily: pd.DataFrame) -> bool:
        """일봉 데이터를 DuckDB에 저장 (전체 교체)"""
        try:
            if df_daily is None or df_daily.empty:
                return True

            if self.use_duckdb:
                return self._save_to_duckdb(stock_code, df_daily)
            else:
                return self._save_to_pkl(stock_code, df_daily)

        except Exception as e:
            self.logger.error(f"일봉 캐시 저장 실패 ({stock_code}): {e}")
            return False

    def _save_to_duckdb(self, stock_code: str, df_daily: pd.DataFrame) -> bool:
        """DuckDB에 저장 (종목별 테이블) - 글로벌 Lock으로 동시성 보호"""
        # 글로벌 Lock 획득 (DuckDB는 단일 Writer만 허용)
        with _write_lock:
            try:
                table_name = self._get_table_name(stock_code)
                con = duckdb.connect(str(DB_PATH))

                # WAL 모드 활성화 (동시 읽기 성능 향상)
                try:
                    con.execute("PRAGMA wal_autocheckpoint=1000")
                except:
                    pass  # DuckDB 버전에 따라 지원 안될 수 있음

                # 테이블 생성 (없으면)
                self._create_table_if_not_exists(con, stock_code)

                # DataFrame에서 필요한 컬럼만 선택
                cols = ['stck_bsop_date', 'stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr',
                        'acml_vol', 'acml_tr_pbmn', 'flng_cls_code', 'prtt_rate', 'mod_yn',
                        'prdy_vrss_sign', 'prdy_vrss', 'revl_issu_reas']

                df_to_save = df_daily.copy()
                # 없는 컬럼은 빈 문자열로 추가
                for col in cols:
                    if col not in df_to_save.columns:
                        df_to_save[col] = ''

                # 트랜잭션으로 MERGE (중복 제거 + 과거 데이터 보존)
                con.execute("BEGIN TRANSACTION")
                try:
                    # 기존 날짜 데이터는 삭제 (업데이트)
                    con.execute(f"""
                        DELETE FROM {table_name}
                        WHERE stck_bsop_date IN (
                            SELECT DISTINCT stck_bsop_date FROM df_to_save
                        )
                    """)

                    # 신규 데이터 삽입
                    con.execute(f"""
                        INSERT INTO {table_name}
                        SELECT stck_bsop_date, stck_clpr, stck_oprc, stck_hgpr, stck_lwpr,
                               acml_vol, acml_tr_pbmn, flng_cls_code, prtt_rate, mod_yn,
                               prdy_vrss_sign, prdy_vrss, revl_issu_reas
                        FROM df_to_save
                    """)
                    con.execute("COMMIT")
                except Exception as inner_e:
                    con.execute("ROLLBACK")
                    raise inner_e
                finally:
                    con.close()

                self.logger.debug(f"[{stock_code}] 일봉 DuckDB 저장 완료 ({len(df_daily)}개)")
                return True

            except Exception as e:
                self.logger.warning(f"일봉 DuckDB 저장 실패: {e}")
                return False

    def _save_to_pkl(self, stock_code: str, df_daily: pd.DataFrame) -> bool:
        """pkl 파일로 저장 (폴백)"""
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        cache_file = self._get_cache_file(stock_code, date_str)
        with open(cache_file, 'wb') as f:
            pickle.dump(df_daily, f, protocol=pickle.HIGHEST_PROTOCOL)
        self.logger.debug(f"[{stock_code}] 일봉 pkl 저장 완료 ({len(df_daily)}개)")
        return True

    def load_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """캐시된 일봉 데이터 로드"""
        try:
            if self.use_duckdb:
                df = self._load_from_duckdb(stock_code)
                if df is not None:
                    return df

            # pkl 폴백 (최신 파일 찾기)
            return self._load_from_pkl(stock_code)

        except Exception as e:
            self.logger.error(f"일봉 캐시 로드 실패 ({stock_code}): {e}")
            return None

    def _load_from_duckdb(self, stock_code: str) -> Optional[pd.DataFrame]:
        """DuckDB에서 로드 - 연결 풀링 사용"""
        try:
            table_name = self._get_table_name(stock_code)
            con = self._get_connection()  # 재사용되는 연결

            tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_name = ?", [table_name]).fetchall()
            if not tables:
                return None

            df = con.execute(f"""
                SELECT * FROM {table_name}
                ORDER BY stck_bsop_date
            """).fetchdf()
            # con.close() 제거 - 연결 유지

            if df.empty:
                return None

            self.logger.debug(f"[{stock_code}] 일봉 DuckDB에서 로드 ({len(df)}개)")
            return df

        except Exception as e:
            self.logger.debug(f"일봉 DuckDB 로드 실패: {e}")
            return None

    def _load_from_pkl(self, stock_code: str) -> Optional[pd.DataFrame]:
        """pkl 파일에서 로드 (최신 파일)"""
        pkl_files = list(self.cache_dir.glob(f"{stock_code}_*_daily.pkl"))
        if not pkl_files:
            return None

        # 가장 최신 파일 선택
        latest_file = max(pkl_files, key=lambda f: f.stat().st_mtime)
        with open(latest_file, 'rb') as f:
            df_daily = pickle.load(f)

        self.logger.debug(f"[{stock_code}] 일봉 pkl에서 로드 ({len(df_daily)}개)")
        return df_daily

    def __enter__(self):
        """Context Manager 진입"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager 종료 - 스레드 로컬 연결 정리"""
        if hasattr(self._thread_local, 'connection') and self._thread_local.connection is not None:
            try:
                self._thread_local.connection.close()
                self._thread_local.connection = None
            except Exception as e:
                self.logger.warning(f"연결 정리 실패: {e}")
