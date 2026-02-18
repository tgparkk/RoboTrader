"""
데이터베이스 관리 모듈 (DuckDB 기반)
후보 종목 선정 이력 및 관련 데이터 저장/조회
"""
import duckdb
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
    """데이터베이스 관리자 (DuckDB 기반)

    - 거래 기록 전용 DuckDB (시세 캐시와 분리)
    - 싱글톤 연결 관리
    """

    _instance: Optional['DatabaseManager'] = None
    _conn: Optional[duckdb.DuckDBPyConnection] = None

    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)

        # 데이터베이스 파일 경로 설정
        if db_path is None:
            db_dir = Path(__file__).parent
            db_dir.mkdir(exist_ok=True)
            db_path = db_dir / "robotrader_trades.duckdb"

        self.db_path = str(db_path)
        self.logger.info(f"데이터베이스 초기화 (DuckDB): {self.db_path}")

        # 테이블 생성
        self._create_tables()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """DuckDB 연결 반환 (싱글톤)"""
        if DatabaseManager._conn is None or DatabaseManager._conn is None:
            try:
                DatabaseManager._conn = duckdb.connect(self.db_path)
            except Exception:
                # 이미 열린 연결이 있으면 새로 연결
                DatabaseManager._conn = duckdb.connect(self.db_path)
        return DatabaseManager._conn

    def _execute(self, query: str, params: tuple = None):
        """쿼리 실행 헬퍼"""
        conn = self._get_connection()
        if params:
            return conn.execute(query, params)
        return conn.execute(query)

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
            result = self._execute(
                '''
                SELECT COUNT(1)
                FROM real_trading_records
                WHERE stock_code = ?
                  AND action = 'SELL'
                  AND profit_loss < 0
                  AND timestamp >= ? AND timestamp < ?
                ''',
                (stock_code, start_str, next_str),
            )
            row = result.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception as e:
            self.logger.error(f"실거래 당일 손실 카운트 조회 실패({stock_code}): {e}")
            return 0

    def _create_tables(self):
        """데이터베이스 테이블 생성"""
        try:
            conn = self._get_connection()

            # 후보 종목 테이블
            conn.execute('''
                CREATE TABLE IF NOT EXISTS candidate_stocks (
                    id INTEGER PRIMARY KEY,
                    stock_code VARCHAR NOT NULL,
                    stock_name VARCHAR,
                    selection_date TIMESTAMP NOT NULL,
                    score DOUBLE NOT NULL,
                    reasons VARCHAR,
                    status VARCHAR DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 시퀀스 생성 (AUTOINCREMENT 대체)
            try:
                conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_candidate_stocks START 1")
            except Exception:
                pass

            # 종목 가격 데이터 테이블
            conn.execute('''
                CREATE TABLE IF NOT EXISTS stock_prices (
                    id INTEGER PRIMARY KEY,
                    stock_code VARCHAR NOT NULL,
                    date_time TIMESTAMP NOT NULL,
                    open_price DOUBLE,
                    high_price DOUBLE,
                    low_price DOUBLE,
                    close_price DOUBLE,
                    volume BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, date_time)
                )
            ''')

            try:
                conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_stock_prices START 1")
            except Exception:
                pass

            # 가상 매매 기록 테이블
            conn.execute('''
                CREATE TABLE IF NOT EXISTS virtual_trading_records (
                    id INTEGER PRIMARY KEY,
                    stock_code VARCHAR NOT NULL,
                    stock_name VARCHAR,
                    action VARCHAR NOT NULL,
                    quantity INTEGER NOT NULL,
                    price DOUBLE NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    strategy VARCHAR,
                    reason VARCHAR,
                    is_test BOOLEAN DEFAULT TRUE,
                    profit_loss DOUBLE DEFAULT 0,
                    profit_rate DOUBLE DEFAULT 0,
                    buy_record_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            try:
                conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_virtual_trading START 1")
            except Exception:
                pass

            # 실거래 매매 기록 테이블
            conn.execute('''
                CREATE TABLE IF NOT EXISTS real_trading_records (
                    id INTEGER PRIMARY KEY,
                    stock_code VARCHAR NOT NULL,
                    stock_name VARCHAR,
                    action VARCHAR NOT NULL,
                    quantity INTEGER NOT NULL,
                    price DOUBLE NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    strategy VARCHAR,
                    reason VARCHAR,
                    profit_loss DOUBLE DEFAULT 0,
                    profit_rate DOUBLE DEFAULT 0,
                    buy_record_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            try:
                conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_real_trading START 1")
            except Exception:
                pass

            # 매매 기록 테이블 (기존)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS trading_records (
                    id INTEGER PRIMARY KEY,
                    stock_code VARCHAR NOT NULL,
                    action VARCHAR NOT NULL,
                    quantity INTEGER NOT NULL,
                    price DOUBLE NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    profit_loss DOUBLE DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            try:
                conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_trading_records START 1")
            except Exception:
                pass

            # 인덱스 생성 (DuckDB는 자동 인덱싱이 강력하지만 명시적으로도 가능)
            # DuckDB doesn't support CREATE INDEX IF NOT EXISTS on all versions,
            # so we wrap in try/except
            index_statements = [
                'CREATE INDEX IF NOT EXISTS idx_candidate_date ON candidate_stocks(selection_date)',
                'CREATE INDEX IF NOT EXISTS idx_candidate_code ON candidate_stocks(stock_code)',
                'CREATE INDEX IF NOT EXISTS idx_price_code_date ON stock_prices(stock_code, date_time)',
                'CREATE INDEX IF NOT EXISTS idx_trading_code_date ON trading_records(stock_code, timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_virtual_trading_code_date ON virtual_trading_records(stock_code, timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_virtual_trading_action ON virtual_trading_records(action)',
                'CREATE INDEX IF NOT EXISTS idx_real_trading_code_date ON real_trading_records(stock_code, timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_real_trading_action ON real_trading_records(action)',
            ]
            for stmt in index_statements:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass

            self.logger.info("데이터베이스 테이블 생성 완료 (DuckDB)")

        except Exception as e:
            self.logger.error(f"테이블 생성 실패: {e}")
            raise

    def _next_id(self, seq_name: str) -> int:
        """시퀀스에서 다음 ID 가져오기"""
        try:
            result = self._execute(f"SELECT nextval('{seq_name}')")
            return result.fetchone()[0]
        except Exception:
            # 시퀀스 실패 시 max+1 폴백
            table_map = {
                'seq_candidate_stocks': 'candidate_stocks',
                'seq_stock_prices': 'stock_prices',
                'seq_virtual_trading': 'virtual_trading_records',
                'seq_real_trading': 'real_trading_records',
                'seq_trading_records': 'trading_records',
            }
            table = table_map.get(seq_name, 'candidate_stocks')
            try:
                result = self._execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}")
                return result.fetchone()[0]
            except Exception:
                return 1

    def save_candidate_stocks(self, candidates: List[CandidateStock], selection_date: datetime = None) -> bool:
        """후보 종목 목록 저장"""
        try:
            if not candidates:
                self.logger.warning("저장할 후보 종목이 없습니다")
                return True

            if selection_date is None:
                selection_date = now_kst()

            conn = self._get_connection()

            # 당일 이미 저장된 종목 조회
            target_date = selection_date.strftime('%Y-%m-%d')
            result = conn.execute('''
                SELECT DISTINCT stock_code FROM candidate_stocks
                WHERE CAST(selection_date AS DATE) = ?
            ''', (target_date,))

            existing_stocks = {row[0] for row in result.fetchall()}

            new_candidates = 0
            duplicate_candidates = 0

            for candidate in candidates:
                if candidate.code not in existing_stocks:
                    new_id = self._next_id('seq_candidate_stocks')
                    conn.execute('''
                        INSERT INTO candidate_stocks
                        (id, stock_code, stock_name, selection_date, score, reasons, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                    ''', (
                        new_id,
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

            if new_candidates > 0:
                self.logger.info(f"✅ 새로운 후보 종목 {new_candidates}개 저장 완료")
                self.logger.info(f"   전체 후보: {len(candidates)}개, 날짜: {selection_date.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                self.logger.info(f"📝 모든 후보 종목이 당일 이미 저장되어 있음 ({len(candidates)}개 모두 중복)")

            return True

        except Exception as e:
            self.logger.error(f"후보 종목 저장 실패: {e}")
            return False

    def save_price_data(self, stock_code: str, price_data: List[PriceRecord]) -> bool:
        """가격 데이터 저장"""
        try:
            if not price_data:
                return True

            conn = self._get_connection()

            for record in price_data:
                new_id = self._next_id('seq_stock_prices')
                # DuckDB: INSERT OR REPLACE → DELETE then INSERT
                conn.execute('''
                    DELETE FROM stock_prices WHERE stock_code = ? AND date_time = ?
                ''', (stock_code, record.date_time.strftime('%Y-%m-%d %H:%M:%S')))
                conn.execute('''
                    INSERT INTO stock_prices
                    (id, stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    new_id,
                    stock_code,
                    record.date_time.strftime('%Y-%m-%d %H:%M:%S'),
                    record.open_price,
                    record.high_price,
                    record.low_price,
                    record.close_price,
                    record.volume,
                    now_kst().strftime('%Y-%m-%d %H:%M:%S')
                ))

            self.logger.debug(f"{stock_code} 가격 데이터 {len(price_data)}개 저장")
            return True

        except Exception as e:
            self.logger.error(f"가격 데이터 저장 실패 ({stock_code}): {e}")
            return False

    def save_minute_data(self, stock_code: str, date_str: str, df_minute: pd.DataFrame) -> bool:
        """1분봉 데이터를 기존 stock_prices 테이블에 저장"""
        try:
            if df_minute is None or df_minute.empty:
                return True

            conn = self._get_connection()

            start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
            end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"

            conn.execute('''
                DELETE FROM stock_prices
                WHERE stock_code = ?
                AND date_time >= ?
                AND date_time <= ?
            ''', (stock_code, start_datetime, end_datetime))

            for _, row in df_minute.iterrows():
                new_id = self._next_id('seq_stock_prices')
                conn.execute('''
                    INSERT INTO stock_prices
                    (id, stock_code, date_time, open_price, high_price, low_price, close_price, volume, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    new_id,
                    stock_code,
                    row['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
                    row['open'],
                    row['high'],
                    row['low'],
                    row['close'],
                    row['volume'],
                    now_kst().strftime('%Y-%m-%d %H:%M:%S')
                ))

            self.logger.debug(f"{stock_code} 1분봉 데이터 {len(df_minute)}개 저장 ({date_str})")
            return True

        except Exception as e:
            self.logger.error(f"1분봉 데이터 저장 실패 ({stock_code}, {date_str}): {e}")
            return False

    def get_minute_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """1분봉 데이터를 기존 stock_prices 테이블에서 조회"""
        try:
            conn = self._get_connection()
            start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
            end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"

            df = conn.execute('''
                SELECT date_time, open_price, high_price, low_price, close_price, volume
                FROM stock_prices
                WHERE stock_code = ?
                AND date_time >= ?
                AND date_time <= ?
                ORDER BY date_time
            ''', (stock_code, start_datetime, end_datetime)).fetchdf()

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

        except Exception as e:
            self.logger.error(f"1분봉 데이터 조회 실패 ({stock_code}, {date_str}): {e}")
            return None

    def has_minute_data(self, stock_code: str, date_str: str) -> bool:
        """해당 종목의 해당 날짜 1분봉 데이터가 DB에 있는지 확인"""
        try:
            start_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
            end_datetime = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 23:59:59"

            result = self._execute('''
                SELECT COUNT(1) FROM stock_prices
                WHERE stock_code = ?
                AND date_time >= ?
                AND date_time <= ?
            ''', (stock_code, start_datetime, end_datetime))

            count = result.fetchone()[0]
            return count > 0

        except Exception as e:
            self.logger.error(f"1분봉 데이터 존재 확인 실패 ({stock_code}, {date_str}): {e}")
            return False

    def get_candidate_history(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 선정 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()

            df = conn.execute('''
                SELECT
                    stock_code, stock_name, selection_date, score, reasons, status
                FROM candidate_stocks
                WHERE selection_date >= ?
                ORDER BY selection_date DESC, score DESC
            ''', (start_date.strftime('%Y-%m-%d %H:%M:%S'),)).fetchdf()

            df['selection_date'] = pd.to_datetime(df['selection_date'])
            self.logger.info(f"후보 종목 이력 {len(df)}건 조회 ({days}일)")
            return df

        except Exception as e:
            self.logger.error(f"후보 종목 이력 조회 실패: {e}")
            return pd.DataFrame()

    def get_price_history(self, stock_code: str, days: int = 30) -> pd.DataFrame:
        """종목별 가격 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()

            df = conn.execute('''
                SELECT date_time, open_price, high_price, low_price, close_price, volume
                FROM stock_prices
                WHERE stock_code = ? AND date_time >= ?
                ORDER BY date_time ASC
            ''', (stock_code, start_date.strftime('%Y-%m-%d %H:%M:%S'))).fetchdf()

            df['date_time'] = pd.to_datetime(df['date_time'])
            self.logger.debug(f"{stock_code} 가격 이력 {len(df)}건 조회")
            return df

        except Exception as e:
            self.logger.error(f"가격 이력 조회 실패 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_candidate_performance(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 성과 분석"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()

            df = conn.execute('''
                SELECT
                    c.stock_code, c.stock_name, c.selection_date, c.score,
                    COUNT(p.id) as price_records,
                    AVG(p.close_price) as avg_price,
                    MAX(p.high_price) as max_price,
                    MIN(p.low_price) as min_price
                FROM candidate_stocks c
                LEFT JOIN stock_prices p ON c.stock_code = p.stock_code
                    AND p.date_time >= c.selection_date
                WHERE c.selection_date >= ?
                GROUP BY c.id, c.stock_code, c.stock_name, c.selection_date, c.score
                ORDER BY c.selection_date DESC, c.score DESC
            ''', (start_date.strftime('%Y-%m-%d %H:%M:%S'),)).fetchdf()

            df['selection_date'] = pd.to_datetime(df['selection_date'])
            return df

        except Exception as e:
            self.logger.error(f"성과 분석 조회 실패: {e}")
            return pd.DataFrame()

    def get_daily_candidate_count(self, days: int = 30) -> pd.DataFrame:
        """일별 후보 종목 선정 수"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()

            df = conn.execute('''
                SELECT
                    CAST(selection_date AS DATE) as date,
                    COUNT(*) as count,
                    AVG(score) as avg_score,
                    MAX(score) as max_score
                FROM candidate_stocks
                WHERE selection_date >= ?
                GROUP BY CAST(selection_date AS DATE)
                ORDER BY date DESC
            ''', (start_date.strftime('%Y-%m-%d %H:%M:%S'),)).fetchdf()

            df['date'] = pd.to_datetime(df['date'])
            return df

        except Exception as e:
            self.logger.error(f"일별 통계 조회 실패: {e}")
            return pd.DataFrame()

    def cleanup_old_data(self, keep_days: int = 90):
        """오래된 데이터 정리"""
        try:
            cutoff_date = now_kst() - timedelta(days=keep_days)
            cutoff_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
            conn = self._get_connection()

            conn.execute('DELETE FROM candidate_stocks WHERE selection_date < ?', (cutoff_str,))
            conn.execute('DELETE FROM stock_prices WHERE date_time < ?', (cutoff_str,))

            self.logger.info(f"{keep_days}일 이전 데이터 정리 완료")

        except Exception as e:
            self.logger.error(f"데이터 정리 실패: {e}")

    def get_database_stats(self) -> Dict[str, int]:
        """데이터베이스 통계"""
        try:
            conn = self._get_connection()
            stats = {}

            for table in ['candidate_stocks', 'stock_prices', 'trading_records', 'virtual_trading_records', 'real_trading_records']:
                try:
                    result = conn.execute(f'SELECT COUNT(*) FROM {table}')
                    stats[table] = result.fetchone()[0]
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
            new_id = self._next_id('seq_real_trading')
            conn.execute('''
                INSERT INTO real_trading_records
                (id, stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, created_at)
                VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?)
            ''', (
                new_id, stock_code, stock_name, quantity, price,
                timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                now_kst().strftime('%Y-%m-%d %H:%M:%S')
            ))
            self.logger.info(f"✅ 실거래 매수 기록 저장: {stock_code} {quantity}주 @{price:,.0f}")
            return new_id
        except Exception as e:
            self.logger.error(f"실거래 매수 기록 저장 실패: {e}")
            return None

    def save_real_sell(self, stock_code: str, stock_name: str, price: float,
                       quantity: int, strategy: str = '', reason: str = '',
                       buy_record_id: Optional[int] = None, timestamp: datetime = None) -> bool:
        """실거래 매도 기록 저장 (손익 계산 포함)"""
        try:
            if timestamp is None:
                timestamp = now_kst()

            conn = self._get_connection()

            buy_price = None
            if buy_record_id:
                result = conn.execute('''
                    SELECT price FROM real_trading_records
                    WHERE id = ? AND action = 'BUY'
                ''', (buy_record_id,))
                row = result.fetchone()
                if row:
                    buy_price = float(row[0])

            profit_loss = 0.0
            profit_rate = 0.0
            if buy_price and buy_price > 0:
                profit_loss = (price - buy_price) * quantity
                profit_rate = (price - buy_price) / buy_price * 100.0

            new_id = self._next_id('seq_real_trading')
            conn.execute('''
                INSERT INTO real_trading_records
                (id, stock_code, stock_name, action, quantity, price, timestamp, strategy, reason,
                 profit_loss, profit_rate, buy_record_id, created_at)
                VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                new_id, stock_code, stock_name, quantity, price,
                timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                profit_loss, profit_rate, buy_record_id,
                now_kst().strftime('%Y-%m-%d %H:%M:%S')
            ))

            self.logger.info(
                f"✅ 실거래 매도 기록 저장: {stock_code} {quantity}주 @{price:,.0f} 손익 {profit_loss:+,.0f}원 ({profit_rate:+.2f}%)"
            )
            return True
        except Exception as e:
            self.logger.error(f"실거래 매도 기록 저장 실패: {e}")
            return False

    def get_last_open_real_buy(self, stock_code: str) -> Optional[int]:
        """해당 종목의 미매칭 매수(가장 최근) ID 조회"""
        try:
            result = self._execute('''
                SELECT b.id
                FROM real_trading_records b
                WHERE b.stock_code = ? AND b.action = 'BUY'
                  AND NOT EXISTS (
                    SELECT 1 FROM real_trading_records s
                    WHERE s.buy_record_id = b.id AND s.action = 'SELL'
                  )
                ORDER BY b.timestamp DESC
                LIMIT 1
            ''', (stock_code,))
            row = result.fetchone()
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
            new_id = self._next_id('seq_virtual_trading')
            conn.execute('''
                INSERT INTO virtual_trading_records
                (id, stock_code, stock_name, action, quantity, price, timestamp, strategy, reason, is_test, created_at)
                VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, TRUE, ?)
            ''', (new_id, stock_code, stock_name, quantity, price,
                  timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                  now_kst().strftime('%Y-%m-%d %H:%M:%S')))

            self.logger.info(f"🔥 가상 매수 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - {strategy}")
            return new_id

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

            result = conn.execute('''
                SELECT price FROM virtual_trading_records
                WHERE id = ? AND action = 'BUY'
            ''', (buy_record_id,))

            buy_result = result.fetchone()
            if not buy_result:
                self.logger.error(f"매수 기록을 찾을 수 없음: ID {buy_record_id}")
                return False

            buy_price = buy_result[0]
            profit_loss = (price - buy_price) * quantity
            profit_rate = ((price - buy_price) / buy_price) * 100

            new_id = self._next_id('seq_virtual_trading')
            conn.execute('''
                INSERT INTO virtual_trading_records
                (id, stock_code, stock_name, action, quantity, price, timestamp, strategy, reason,
                 is_test, profit_loss, profit_rate, buy_record_id, created_at)
                VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, ?, TRUE, ?, ?, ?, ?)
            ''', (new_id, stock_code, stock_name, quantity, price,
                  timestamp.strftime('%Y-%m-%d %H:%M:%S'), strategy, reason,
                  profit_loss, profit_rate, buy_record_id,
                  now_kst().strftime('%Y-%m-%d %H:%M:%S')))

            profit_sign = "+" if profit_loss >= 0 else ""
            self.logger.info(f"📉 가상 매도 기록 저장: {stock_code}({stock_name}) {quantity}주 @{price:,.0f}원 - "
                           f"손익: {profit_sign}{profit_loss:,.0f}원 ({profit_rate:+.2f}%) - {strategy}")
            return True

        except Exception as e:
            self.logger.error(f"가상 매도 기록 저장 실패: {e}")
            return False

    def get_virtual_open_positions(self) -> pd.DataFrame:
        """미체결 가상 포지션 조회"""
        try:
            conn = self._get_connection()
            df = conn.execute('''
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
            ''').fetchdf()

            if not df.empty:
                df['buy_time'] = pd.to_datetime(df['buy_time'])

            return df

        except Exception as e:
            self.logger.error(f"미체결 포지션 조회 실패: {e}")
            return pd.DataFrame()

    def get_virtual_trading_history(self, days: int = 30, include_open: bool = True) -> pd.DataFrame:
        """가상 매매 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            conn = self._get_connection()

            if include_open:
                df = conn.execute('''
                    SELECT
                        id, stock_code, stock_name, action, quantity, price,
                        timestamp, strategy, reason, profit_loss, profit_rate, buy_record_id
                    FROM virtual_trading_records
                    WHERE timestamp >= ? AND is_test = TRUE
                    ORDER BY timestamp DESC
                ''', (start_date.strftime('%Y-%m-%d %H:%M:%S'),)).fetchdf()
            else:
                df = conn.execute('''
                    SELECT
                        s.stock_code, s.stock_name,
                        b.price as buy_price, b.timestamp as buy_time, b.reason as buy_reason,
                        s.price as sell_price, s.timestamp as sell_time, s.reason as sell_reason,
                        s.strategy, s.quantity, s.profit_loss, s.profit_rate
                    FROM virtual_trading_records s
                    JOIN virtual_trading_records b ON s.buy_record_id = b.id
                    WHERE s.action = 'SELL'
                        AND s.timestamp >= ?
                        AND s.is_test = TRUE
                    ORDER BY s.timestamp DESC
                ''', (start_date.strftime('%Y-%m-%d %H:%M:%S'),)).fetchdf()

            if not df.empty:
                if include_open:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                else:
                    df['buy_time'] = pd.to_datetime(df['buy_time'])
                    df['sell_time'] = pd.to_datetime(df['sell_time'])

            return df

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

    @classmethod
    def close_connection(cls):
        """DuckDB 연결 닫기"""
        if cls._conn is not None:
            try:
                cls._conn.close()
            except Exception:
                pass
            cls._conn = None
