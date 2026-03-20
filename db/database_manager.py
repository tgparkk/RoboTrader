"""
데이터베이스 관리 모듈 (PostgreSQL 기반)
후보 종목 선정 이력 및 관련 데이터 저장/조회
"""
import psycopg2
import psycopg2.extras
import psycopg2.pool
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from core.candidate_selector import CandidateStock
from utils.logger import setup_logger
from utils.korean_time import now_kst


@dataclass
class CandidateRecord:
    """후보 종목 기록"""
    id: int
    stock_code: str
    stock_name: str
    selection_date: datetime
    score: float
    reasons: str
    status: str = 'active'


@dataclass
class PriceRecord:
    """가격 기록"""
    stock_code: str
    date_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int


class DatabaseManager:
    """데이터베이스 관리자 (PostgreSQL 기반)

    - PostgreSQL connection pool 사용
    - 기존 DuckDB API와 동일한 인터페이스 유지
    """

    _instance: Optional['DatabaseManager'] = None
    _pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)

        # PostgreSQL 접속 정보
        from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
        self._pg_host = PG_HOST
        self._pg_port = PG_PORT
        self._pg_database = PG_DATABASE
        self._pg_user = PG_USER
        self._pg_password = PG_PASSWORD

        self.logger.info(f"데이터베이스 초기화 (PostgreSQL): {self._pg_host}:{self._pg_port}/{self._pg_database}")

        # Connection pool 초기화
        self._init_pool()

        # 테이블 생성
        self._create_tables()

    def _init_pool(self):
        """Connection pool 초기화 (싱글톤)"""
        if DatabaseManager._pool is None or DatabaseManager._pool.closed:
            try:
                DatabaseManager._pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    host=self._pg_host,
                    port=self._pg_port,
                    database=self._pg_database,
                    user=self._pg_user,
                    password=self._pg_password,
                    connect_timeout=10,
                )
                self.logger.info("PostgreSQL connection pool 초기화 완료")
            except Exception as e:
                self.logger.error(f"PostgreSQL connection pool 초기화 실패: {e}")
                raise

    def _get_connection(self):
        """Pool에서 연결 획득"""
        if DatabaseManager._pool is None or DatabaseManager._pool.closed:
            self._init_pool()
        return DatabaseManager._pool.getconn()

    def _put_connection(self, conn):
        """Pool에 연결 반환"""
        if DatabaseManager._pool is not None and not DatabaseManager._pool.closed:
            DatabaseManager._pool.putconn(conn)

    def _execute(self, query: str, params: tuple = None):
        """쿼리 실행 헬퍼 — INSERT/UPDATE/DELETE용 (결과 반환 없음)"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    def _fetchone(self, query: str, params: tuple = None):
        """쿼리 실행 후 fetchone 결과 반환"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            return cur.fetchone()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    def _fetchall(self, query: str, params: tuple = None):
        """쿼리 실행 후 fetchall 결과 반환"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            return cur.fetchall()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_connection(conn)

    def _get_today_range_strings(self) -> tuple:
        """KST 기준 오늘의 시작과 내일 시작 시간 문자열(YYYY-MM-DD HH:MM:SS)을 반환."""
        try:
            today = now_kst().date()
            from datetime import datetime, time, timedelta
            start_dt = datetime.combine(today, time(hour=0, minute=0, second=0))
            next_dt = start_dt + timedelta(days=1)
            return (
                start_dt.strftime('%Y-%m-%d %H:%M:%S'),
                next_dt.strftime('%Y-%m-%d %H:%M:%S'),
            )
        except Exception:
            return ("1970-01-01 00:00:00", "2100-01-01 00:00:00")

    def get_today_real_loss_count(self, stock_code: str) -> int:
        """해당 종목의 실거래 기준, 오늘 발생한 손실 매도 건수 반환."""
        try:
            start_str, next_str = self._get_today_range_strings()
            row = self._fetchone(
                '''
                SELECT COUNT(1)
                FROM real_trading_records
                WHERE stock_code = %s
                  AND action = 'SELL'
                  AND profit_loss < 0
                  AND timestamp >= %s AND timestamp < %s
                ''',
                (stock_code, start_str, next_str),
            )
            return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            self.logger.error(f"실거래 당일 손실 카운트 조회 실패({stock_code}): {e}")
            return 0

    def _create_tables(self):
        """데이터베이스 테이블 생성"""
        try:
            conn = self._get_connection()
            try:
                cur = conn.cursor()

                # 후보 종목 테이블
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS candidate_stocks (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR NOT NULL,
                        stock_name VARCHAR,
                        selection_date TIMESTAMP NOT NULL,
                        score DOUBLE PRECISION NOT NULL,
                        reasons VARCHAR,
                        status VARCHAR DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 종목 가격 데이터 테이블
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS stock_prices (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR NOT NULL,
                        date_time TIMESTAMP NOT NULL,
                        open_price DOUBLE PRECISION,
                        high_price DOUBLE PRECISION,
                        low_price DOUBLE PRECISION,
                        close_price DOUBLE PRECISION,
                        volume BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, date_time)
                    )
                ''')

                # 가상 매매 기록 테이블
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS virtual_trading_records (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR NOT NULL,
                        stock_name VARCHAR,
                        action VARCHAR NOT NULL,
                        quantity INTEGER NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        strategy VARCHAR,
                        reason VARCHAR,
                        is_test BOOLEAN DEFAULT TRUE,
                        profit_loss DOUBLE PRECISION DEFAULT 0,
                        profit_rate DOUBLE PRECISION DEFAULT 0,
                        buy_record_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 실거래 매매 기록 테이블
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS real_trading_records (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR NOT NULL,
                        stock_name VARCHAR,
                        action VARCHAR NOT NULL,
                        quantity INTEGER NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        strategy VARCHAR,
                        reason VARCHAR,
                        profit_loss DOUBLE PRECISION DEFAULT 0,
                        profit_rate DOUBLE PRECISION DEFAULT 0,
                        fee_amount DOUBLE PRECISION DEFAULT 0,
                        net_profit DOUBLE PRECISION DEFAULT 0,
                        net_profit_rate DOUBLE PRECISION DEFAULT 0,
                        buy_record_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # 매매 기록 테이블 (기존)
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS trading_records (
                        id SERIAL PRIMARY KEY,
                        stock_code VARCHAR NOT NULL,
                        action VARCHAR NOT NULL,
                        quantity INTEGER NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        profit_loss DOUBLE PRECISION DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # NXT 프리마켓 스냅샷 테이블
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS nxt_snapshots (
                        id SERIAL PRIMARY KEY,
                        trade_date VARCHAR(8) NOT NULL,
                        snapshot_time TIMESTAMP NOT NULL,
                        snapshot_seq INTEGER NOT NULL,
                        avg_change_pct DOUBLE PRECISION,
                        up_count INTEGER,
                        down_count INTEGER,
                        unchanged_count INTEGER,
                        total_volume BIGINT,
                        sentiment_score DOUBLE PRECISION,
                        market_sentiment VARCHAR(20),
                        expected_gap_pct DOUBLE PRECISION,
                        circuit_breaker BOOLEAN DEFAULT FALSE,
                        circuit_breaker_reason VARCHAR,
                        recommended_max_positions INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(trade_date, snapshot_seq)
                    )
                ''')

                # 인덱스 생성
                index_statements = [
                    'CREATE INDEX IF NOT EXISTS idx_candidate_date ON candidate_stocks(selection_date)',
                    'CREATE INDEX IF NOT EXISTS idx_candidate_code ON candidate_stocks(stock_code)',
                    'CREATE INDEX IF NOT EXISTS idx_price_code_date ON stock_prices(stock_code, date_time)',
                    'CREATE INDEX IF NOT EXISTS idx_trading_code_date ON trading_records(stock_code, timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_virtual_trading_code_date ON virtual_trading_records(stock_code, timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_virtual_trading_action ON virtual_trading_records(action)',
                    'CREATE INDEX IF NOT EXISTS idx_real_trading_code_date ON real_trading_records(stock_code, timestamp)',
                    'CREATE INDEX IF NOT EXISTS idx_real_trading_action ON real_trading_records(action)',
                    'CREATE INDEX IF NOT EXISTS idx_nxt_snapshots_date ON nxt_snapshots(trade_date)',
                ]
                for stmt in index_statements:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass

                conn.commit()
                self.logger.info("데이터베이스 테이블 생성 완료 (PostgreSQL)")

            except Exception as e:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"테이블 생성 실패: {e}")
            raise

    def save_candidate_stocks(self, candidates: List[CandidateStock], selection_date: datetime = None) -> bool:
        """후보 종목 목록 저장"""
        try:
            if not candidates:
                self.logger.warning("저장할 후보 종목이 없습니다")
                return True

            if selection_date is None:
                selection_date = now_kst()

            conn = self._get_connection()
            try:
                cur = conn.cursor()

                # 당일 이미 저장된 종목 조회
                target_date = selection_date.strftime('%Y-%m-%d')
                cur.execute('''
                    SELECT DISTINCT stock_code FROM candidate_stocks
                    WHERE CAST(selection_date AS DATE) = %s
                ''', (target_date,))

                existing_stocks = {row[0] for row in cur.fetchall()}

                new_candidates = 0
                duplicate_candidates = 0

                for candidate in candidates:
                    if candidate.code not in existing_stocks:
                        cur.execute('''
                            INSERT INTO candidate_stocks
                            (stock_code, stock_name, selection_date, score, reasons, status, created_at)
                            VALUES (%s, %s, %s, %s, %s, 'active', %s)
                        ''', (
                            candidate.code,
                            candidate.name,
                            selection_date.strftime('%Y-%m-%d %H:%M:%S'),
                            candidate.score,
                            candidate.reason,
                            now_kst().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                        new_candidates += 1
                        existing_stocks.add(candidate.code)
                    else:
                        duplicate_candidates += 1

                conn.commit()

                if new_candidates > 0:
                    self.logger.info(f"✅ 새로운 후보 종목 {new_candidates}개 저장 완료")
                    self.logger.info(f"   전체 후보: {len(candidates)}개, 날짜: {selection_date.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    self.logger.info(f"📝 모든 후보 종목이 당일 이미 저장되어 있음 ({len(candidates)}개 모두 중복)")

                return True

            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"후보 종목 저장 실패: {e}")
            return False

    def save_price_data(self, stock_code: str, price_data: List[PriceRecord]) -> bool:
        """가격 데이터 저장"""
        try:
            if not price_data:
                return True

            conn = self._get_connection()
            try:
                cur = conn.cursor()

                for record in price_data:
                    cur.execute('''
                        DELETE FROM stock_prices WHERE stock_code = %s AND date_time = %s
                    ''', (stock_code, record.date_time.strftime('%Y-%m-%d %H:%M:%S')))
                    cur.execute('''
                        INSERT INTO stock_prices
                        (stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        stock_code,
                        record.date_time.strftime('%Y-%m-%d %H:%M:%S'),
                        record.open_price,
                        record.high_price,
                        record.low_price,
                        record.close_price,
                        record.volume,
                        now_kst().strftime('%Y-%m-%d %H:%M:%S')
                    ))

                conn.commit()
                self.logger.debug(f"{stock_code} 가격 데이터 {len(price_data)}개 저장")
                return True

            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"가격 데이터 저장 실패 ({stock_code}): {e}")
            return False

    def save_minute_data(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """1분봉 데이터를 기존 stock_prices 테이블에 저장"""
        try:
            if df_minute is None or df_minute.empty:
                return True

            conn = self._get_connection()
            try:
                cur = conn.cursor()

                start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
                end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"

                cur.execute('''
                    DELETE FROM stock_prices
                    WHERE stock_code = %s
                    AND date_time >= %s
                    AND date_time <= %s
                ''', (stock_code, start_datetime, end_datetime))

                rows = []
                for _, row in df_minute.iterrows():
                    rows.append((
                        stock_code,
                        row['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
                        row['open'],
                        row['high'],
                        row['low'],
                        row['close'],
                        row['volume'],
                        now_kst().strftime('%Y-%m-%d %H:%M:%S')
                    ))

                if rows:
                    psycopg2.extras.execute_batch(
                        cur,
                        '''INSERT INTO stock_prices
                        (stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                        rows,
                        page_size=500,
                    )

                conn.commit()
                self.logger.debug(f"{stock_code} 1분봉 데이터 {len(df_minute)}개 저장 ({date_str})")
                return True

            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"1분봉 데이터 저장 실패 ({stock_code}, {date_str}): {e}")
            return False

    def get_minute_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """1분봉 데이터를 기존 stock_prices 테이블에서 조회"""
        try:
            conn = self._get_connection()
            try:
                start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
                end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"

                df = pd.read_sql_query('''
                    SELECT date_time, open_price, high_price, low_price, close_price, volume
                    FROM stock_prices
                    WHERE stock_code = %s
                    AND date_time >= %s
                    AND date_time <= %s
                    ORDER BY date_time
                ''', conn, params=(stock_code, start_datetime, end_datetime))

                if df.empty:
                    return None

                df['datetime'] = pd.to_datetime(df['date_time'])
                df = df.drop('date_time', axis=1)

                df = df.rename(columns={
                    'open_price': 'open',
                    'high_price': 'high',
                    'low_price': 'low',
                    'close_price': 'close'
                })

                self.logger.debug(f"{stock_code} 1분봉 데이터 {len(df)}개 조회 ({date_str})")
                return df

            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"1분봉 데이터 조회 실패 ({stock_code}, {date_str}): {e}")
            return None

    def has_minute_data(self, stock_code: str, date_str: str) -> bool:
        """해당 종목의 해당 날짜 1분봉 데이터가 DB에 있는지 확인"""
        try:
            start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
            end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"

            row = self._fetchone('''
                SELECT COUNT(1) FROM stock_prices
                WHERE stock_code = %s
                AND date_time >= %s
                AND date_time <= %s
            ''', (stock_code, start_datetime, end_datetime))

            count = row[0]
            return count > 0

        except Exception as e:
            self.logger.error(f"1분봉 데이터 존재 확인 실패 ({stock_code}, {date_str}): {e}")
            return False

    def get_candidate_history(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 선정 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()
            try:
                df = pd.read_sql_query('''
                    SELECT
                        stock_code, stock_name, selection_date, score, reasons, status
                    FROM candidate_stocks
                    WHERE selection_date >= %s
                    ORDER BY selection_date DESC, score DESC
                ''', conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))

                df['selection_date'] = pd.to_datetime(df['selection_date'])
                self.logger.info(f"후보 종목 이력 {len(df)}건 조회 ({days}일)")
                return df
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"후보 종목 이력 조회 실패: {e}")
            return pd.DataFrame()

    def get_price_history(self, stock_code: str, days: int = 30) -> pd.DataFrame:
        """종목별 가격 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()
            try:
                df = pd.read_sql_query('''
                    SELECT date_time, open_price, high_price, low_price, close_price, volume
                    FROM stock_prices
                    WHERE stock_code = %s AND date_time >= %s
                    ORDER BY date_time ASC
                ''', conn, params=(stock_code, start_date.strftime('%Y-%m-%d %H:%M:%S')))

                df['date_time'] = pd.to_datetime(df['date_time'])
                self.logger.debug(f"{stock_code} 가격 이력 {len(df)}건 조회")
                return df
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"가격 이력 조회 실패 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_candidate_performance(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 성과 분석"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()
            try:
                df = pd.read_sql_query('''
                    SELECT
                        c.stock_code, c.stock_name, c.selection_date, c.score,
                        COUNT(p.id) as price_records,
                        AVG(p.close_price) as avg_price,
                        MAX(p.high_price) as max_price,
                        MIN(p.low_price) as min_price
                    FROM candidate_stocks c
                    LEFT JOIN stock_prices p ON c.stock_code = p.stock_code
                        AND p.date_time >= c.selection_date
                    WHERE c.selection_date >= %s
                    GROUP BY c.id, c.stock_code, c.stock_name, c.selection_date, c.score
                    ORDER BY c.selection_date DESC, c.score DESC
                ''', conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))

                df['selection_date'] = pd.to_datetime(df['selection_date'])
                return df
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"성과 분석 조회 실패: {e}")
            return pd.DataFrame()

    def get_daily_candidate_count(self, days: int = 30) -> pd.DataFrame:
        """일별 후보 종목 선정 수"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()
            try:
                df = pd.read_sql_query('''
                    SELECT
                        CAST(selection_date AS DATE) as date,
                        COUNT(*) as count,
                        AVG(score) as avg_score,
                        MAX(score) as max_score
                    FROM candidate_stocks
                    WHERE selection_date >= %s
                    GROUP BY CAST(selection_date AS DATE)
                    ORDER BY date DESC
                ''', conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))

                df['date'] = pd.to_datetime(df['date'])
                return df
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"일별 통계 조회 실패: {e}")
            return pd.DataFrame()

    def cleanup_old_data(self, keep_days: int = 90):
        """오래된 데이터 정리"""
        try:
            cutoff_date = now_kst() - timedelta(days=keep_days)
            cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')

            self._execute('DELETE FROM candidate_stocks WHERE selection_date < %s', (cutoff_str,))
            self._execute('DELETE FROM stock_prices WHERE date_time < %s', (cutoff_str,))

            self.logger.info(f"{keep_days}일 이전 데이터 정리 완료")

        except Exception as e:
            self.logger.error(f"데이터 정리 실패: {e}")

    def get_database_stats(self) -> Dict[str, int]:
        """데이터베이스 통계"""
        try:
            stats = {}
            for table in ['candidate_stocks', 'stock_prices', 'trading_records', 'virtual_trading_records', 'real_trading_records']:
                try:
                    row = self._fetchone(f'SELECT COUNT(*) FROM {table}')
                    stats[table] = row[0]
                except Exception:
                    stats[table] = 0
            return stats

        except Exception as e:
            self.logger.error(f"통계 조회 실패: {e}")
            return {}

    # ============================
    # 실거래 저장/조회 API
    # ============================
    def save_real_buy(self, stock_code: str, stock_name: str, price: float,
                      quantity: int, strategy: str = '', reason: str = '',
                      timestamp: datetime = None) -> Optional[int]:
        """실거래 매수 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO real_trading_records
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, created_at)
                    VALUES (%s, %s, 'BUY', %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    stock_code, stock_name, quantity, price,
                    timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                    now_kst().strftime('%Y-%m-%d %H:%M:%S')
                ))
                new_id = cur.fetchone()[0]
                conn.commit()
                self.logger.info(f"✅ 실거래 매수 기록 저장: {stock_code} {quantity}주 @{price:,.0f}")
                return new_id
            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)
        except Exception as e:
            self.logger.error(f"실거래 매수 기록 저장 실패: {e}")
            return None

    def save_real_sell(self, stock_code: str, stock_name: str, price: float,
                       quantity: int, strategy: str = '', reason: str = '',
                       buy_record_id: Optional[int] = None, timestamp: datetime = None,
                       tax_rate: float = 0.0018, commission_rate: float = 0.00014) -> bool:
        """실거래 매도 기록 저장 (손익 + 수수료/세금 계산 포함)"""
        try:
            if timestamp is None:
                timestamp = now_kst()

            conn = self._get_connection()
            try:
                cur = conn.cursor()

                buy_price = None
                if buy_record_id:
                    cur.execute('''
                        SELECT price FROM real_trading_records
                        WHERE id = %s AND action = 'BUY'
                    ''', (buy_record_id,))
                    row = cur.fetchone()
                    if row:
                        buy_price = float(row[0])

                profit_loss = 0.0
                profit_rate = 0.0
                fee_amount = 0.0
                net_profit = 0.0
                net_profit_rate = 0.0
                if buy_price and buy_price > 0:
                    buy_amount = buy_price * quantity
                    sell_amount = price * quantity
                    profit_loss = (price - buy_price) * quantity
                    profit_rate = (price - buy_price) / buy_price * 100.0
                    # 수수료: 거래세(매도금액) + 증권사 수수료(매수+매도금액)
                    tax = sell_amount * tax_rate
                    commission = (buy_amount + sell_amount) * commission_rate
                    fee_amount = round(tax + commission)
                    net_profit = profit_loss - fee_amount
                    net_profit_rate = net_profit / buy_amount * 100.0

                cur.execute('''
                    INSERT INTO real_trading_records
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason,
                     profit_loss, profit_rate, fee_amount, net_profit, net_profit_rate,
                     buy_record_id, created_at)
                    VALUES (%s, %s, 'SELL', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    stock_code, stock_name, quantity, price,
                    timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                    profit_loss, profit_rate, fee_amount, net_profit, net_profit_rate,
                    buy_record_id,
                    now_kst().strftime('%Y-%m-%d %H:%M:%S')
                ))
                conn.commit()

                self.logger.info(
                    f"✅ 실거래 매도 기록 저장: {stock_code} {quantity}주 @{price:,.0f} "
                    f"손익 {profit_loss:+,.0f}원 ({profit_rate:+.2f}%) → 수수료 {fee_amount:,.0f}원 → 실손익 {net_profit:+,.0f}원 ({net_profit_rate:+.2f}%)"
                )
                return True
            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)
        except Exception as e:
            self.logger.error(f"실거래 매도 기록 저장 실패: {e}")
            return False

    def get_last_open_real_buy(self, stock_code: str) -> Optional[int]:
        """해당 종목의 미매칭 매수(가장 최근) ID 조회"""
        try:
            row = self._fetchone('''
                SELECT b.id
                FROM real_trading_records b
                WHERE b.stock_code = %s AND b.action = 'BUY'
                  AND NOT EXISTS (
                    SELECT 1 FROM real_trading_records s
                    WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                  )
                ORDER BY b.timestamp DESC
                LIMIT 1
            ''', (stock_code,))
            return int(row[0]) if row else None
        except Exception as e:
            self.logger.error(f"실거래 미매칭 매수 조회 실패: {e}")
            return None

    def save_virtual_buy(self, stock_code: str, stock_name: str, price: float,
                        quantity: int, strategy: str, reason: str,
                        timestamp: datetime = None) -> Optional[int]:
        """가상 매수 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()

            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO virtual_trading_records
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, is_test, created_at)
                    VALUES (%s, %s, 'BUY', %s, %s, %s, %s, %s, TRUE, %s)
                    RETURNING id
                ''', (stock_code, stock_name, quantity, price,
                      timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                      now_kst().strftime('%Y-%m-%d %H:%M:%S')))
                new_id = cur.fetchone()[0]
                conn.commit()

                self.logger.info(f"🔥 가상 매수 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - {strategy}")
                return new_id

            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"가상 매수 기록 저장 실패: {e}")
            return None

    def save_virtual_sell(self, stock_code: str, stock_name: str, price: float,
                         quantity: int, strategy: str, reason: str,
                         buy_record_id: int, timestamp: datetime = None) -> bool:
        """가상 매도 기록 저장"""
        try:
            if timestamp is None:
                timestamp = now_kst()

            conn = self._get_connection()
            try:
                cur = conn.cursor()

                cur.execute('''
                    SELECT price FROM virtual_trading_records
                    WHERE id = %s AND action = 'BUY'
                ''', (buy_record_id,))

                buy_result = cur.fetchone()
                if not buy_result:
                    self.logger.error(f"매수 기록을 찾을 수 없음: ID {buy_record_id}")
                    return False

                buy_price = buy_result[0]
                profit_loss = (price - buy_price) * quantity
                profit_rate = ((price - buy_price) / buy_price) * 100

                cur.execute('''
                    INSERT INTO virtual_trading_records
                    (stock_code, stock_name, action, quantity, price, timestamp, strategy, reason,
                     is_test, profit_loss, profit_rate, buy_record_id, created_at)
                    VALUES (%s, %s, 'SELL', %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
                ''', (stock_code, stock_name, quantity, price,
                      timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                      profit_loss, profit_rate, buy_record_id,
                      now_kst().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()

                profit_sign = "+" if profit_loss >= 0 else ""
                self.logger.info(f"📉 가상 매도 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - "
                               f"손익: {profit_sign}{profit_loss:,.0f}원 ({profit_rate:+.2f}%) - {strategy}")
                return True

            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"가상 매도 기록 저장 실패: {e}")
            return False

    def get_virtual_open_positions(self) -> pd.DataFrame:
        """미체결 가상 포지션 조회"""
        try:
            conn = self._get_connection()
            try:
                df = pd.read_sql_query('''
                    SELECT
                        b.id, b.stock_code, b.stock_name, b.quantity,
                        b.price as buy_price, b.timestamp as buy_time,
                        b.strategy, b.reason as buy_reason
                    FROM virtual_trading_records b
                    WHERE b.action = 'BUY'
                        AND b.is_test = TRUE
                        AND NOT EXISTS (
                            SELECT 1 FROM virtual_trading_records s
                            WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                        )
                    ORDER BY b.timestamp DESC
                ''', conn)

                if not df.empty:
                    df['buy_time'] = pd.to_datetime(df['buy_time'])

                return df
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"미체결 포지션 조회 실패: {e}")
            return pd.DataFrame()

    def get_virtual_trading_history(self, days: int = 30, include_open: bool = True) -> pd.DataFrame:
        """가상 매매 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()
            try:
                if include_open:
                    df = pd.read_sql_query('''
                        SELECT
                            id, stock_code, stock_name, action, quantity, price,
                            timestamp, strategy, reason, profit_loss, profit_rate, buy_record_id
                        FROM virtual_trading_records
                        WHERE timestamp >= %s AND is_test = TRUE
                        ORDER BY timestamp DESC
                    ''', conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))
                else:
                    df = pd.read_sql_query('''
                        SELECT
                            s.stock_code, s.stock_name,
                            b.price as buy_price, b.timestamp as buy_time, b.reason as buy_reason,
                            s.price as sell_price, s.timestamp as sell_time, s.reason as sell_reason,
                            s.strategy, s.quantity, s.profit_loss, s.profit_rate
                        FROM virtual_trading_records s
                        JOIN virtual_trading_records b ON s.buy_record_id = b.id
                        WHERE s.action = 'SELL'
                            AND s.timestamp >= %s
                            AND s.is_test = TRUE
                        ORDER BY s.timestamp DESC
                    ''', conn, params=(start_date.strftime('%Y-%m-%d %H:%M:%S'),))

                if not df.empty:
                    if include_open:
                        df['timestamp'] = pd.to_datetime(df['timestamp'])
                    else:
                        df['buy_time'] = pd.to_datetime(df['buy_time'])
                        df['sell_time'] = pd.to_datetime(df['sell_time'])

                return df
            finally:
                self._put_connection(conn)

        except Exception as e:
            self.logger.error(f"가상 매매 이력 조회 실패: {e}")
            return pd.DataFrame()

    def get_virtual_trading_stats(self, days: int = 30) -> Dict[str, Any]:
        """가상 매매 통계"""
        try:
            completed_trades = self.get_virtual_trading_history(days=days, include_open=False)
            open_positions = self.get_virtual_open_positions()

            stats = {
                'total_trades': len(completed_trades),
                'open_positions': len(open_positions),
                'win_rate': 0,
                'total_profit': 0,
                'avg_profit_rate': 0,
                'max_profit': 0,
                'max_loss': 0,
                'strategies': {}
            }

            if not completed_trades.empty:
                winning_trades = completed_trades[completed_trades['profit_loss'] > 0]
                stats['win_rate'] = len(winning_trades) / len(completed_trades) * 100
                stats['total_profit'] = completed_trades['profit_loss'].sum()
                stats['avg_profit_rate'] = completed_trades['profit_rate'].mean()
                stats['max_profit'] = completed_trades['profit_loss'].max()
                stats['max_loss'] = completed_trades['profit_loss'].min()

                for strategy in completed_trades['strategy'].unique():
                    strategy_trades = completed_trades[completed_trades['strategy'] == strategy]
                    strategy_wins = strategy_trades[strategy_trades['profit_loss'] > 0]
                    stats['strategies'][strategy] = {
                        'total_trades': len(strategy_trades),
                        'win_rate': len(strategy_wins) / len(strategy_trades) * 100 if len(strategy_trades) > 0 else 0,
                        'total_profit': strategy_trades['profit_loss'].sum(),
                        'avg_profit_rate': strategy_trades['profit_rate'].mean()
                    }

            return stats

        except Exception as e:
            self.logger.error(f"가상 매매 통계 조회 실패: {e}")
            return {}

    # ============================
    # NXT 프리마켓 스냅샷 저장/조회
    # ============================
    def save_nxt_snapshot(self, trade_date: str, snapshot_seq: int,
                          snapshot_time: datetime, avg_change_pct: float,
                          up_count: int, down_count: int, unchanged_count: int,
                          total_volume: int) -> bool:
        """NXT 프리마켓 스냅샷 저장 (수집 시점마다 호출)"""
        try:
            self._execute('''
                INSERT INTO nxt_snapshots
                (trade_date, snapshot_seq, snapshot_time, avg_change_pct,
                 up_count, down_count, unchanged_count, total_volume, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_date, snapshot_seq) DO UPDATE SET
                    snapshot_time = EXCLUDED.snapshot_time,
                    avg_change_pct = EXCLUDED.avg_change_pct,
                    up_count = EXCLUDED.up_count,
                    down_count = EXCLUDED.down_count,
                    unchanged_count = EXCLUDED.unchanged_count,
                    total_volume = EXCLUDED.total_volume
            ''', (
                trade_date, snapshot_seq,
                snapshot_time.strftime('%Y-%m-%d %H:%M:%S'),
                avg_change_pct, up_count, down_count, unchanged_count,
                total_volume,
                now_kst().strftime('%Y-%m-%d %H:%M:%S'),
            ))
            return True
        except Exception as e:
            self.logger.error(f"NXT 스냅샷 저장 실패: {e}")
            return False

    def save_nxt_report_summary(self, trade_date: str,
                                 sentiment_score: float, market_sentiment: str,
                                 expected_gap_pct: float, circuit_breaker: bool,
                                 circuit_breaker_reason: str,
                                 recommended_max_positions: int) -> bool:
        """NXT 리포트 요약을 마지막 스냅샷에 업데이트"""
        try:
            self._execute('''
                UPDATE nxt_snapshots SET
                    sentiment_score = %s,
                    market_sentiment = %s,
                    expected_gap_pct = %s,
                    circuit_breaker = %s,
                    circuit_breaker_reason = %s,
                    recommended_max_positions = %s
                WHERE trade_date = %s
                  AND snapshot_seq = (
                      SELECT MAX(snapshot_seq) FROM nxt_snapshots WHERE trade_date = %s
                  )
            ''', (
                sentiment_score, market_sentiment, expected_gap_pct,
                circuit_breaker, circuit_breaker_reason or '',
                recommended_max_positions,
                trade_date, trade_date,
            ))
            return True
        except Exception as e:
            self.logger.error(f"NXT 리포트 요약 저장 실패: {e}")
            return False

    def get_nxt_history(self, days: int = 30) -> 'pd.DataFrame':
        """NXT 스냅샷 이력 조회 (일별 마지막 스냅샷 = 리포트 요약)"""
        try:
            conn = self._get_connection()
            try:
                df = pd.read_sql_query('''
                    SELECT n.*
                    FROM nxt_snapshots n
                    INNER JOIN (
                        SELECT trade_date, MAX(snapshot_seq) as max_seq
                        FROM nxt_snapshots
                        GROUP BY trade_date
                    ) latest ON n.trade_date = latest.trade_date
                                AND n.snapshot_seq = latest.max_seq
                    WHERE n.trade_date >= %s
                    ORDER BY n.trade_date DESC
                ''', conn, params=(
                    (now_kst() - timedelta(days=days)).strftime('%Y%m%d'),
                ))
                return df
            finally:
                self._put_connection(conn)
        except Exception as e:
            self.logger.error(f"NXT 이력 조회 실패: {e}")
            return pd.DataFrame()

    @classmethod
    def close_connection(cls):
        """PostgreSQL connection pool 닫기"""
        if cls._pool is not None:
            try:
                cls._pool.closeall()
            except Exception:
                pass
            cls._pool = None
