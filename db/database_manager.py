"""
데이터베이스 관리 모듈
후보 종목 선정 이력 및 관련 데이터 저장/조회
"""
import sqlite3
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
    """데이터베이스 관리자"""
    
    def __init__(self, db_path: str = None):
        self.logger = setup_logger(__name__)
        
        # 데이터베이스 파일 경로 설정
        if db_path is None:
            db_dir = Path(__file__).parent.parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = db_dir / "robotrader.db"
        
        self.db_path = str(db_path)
        self.logger.info(f"데이터베이스 초기화: {self.db_path}")
        
        # 테이블 생성
        self._create_tables()
    
    def _create_tables(self):
        """데이터베이스 테이블 생성"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 후보 종목 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS candidate_stocks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        stock_name VARCHAR(100),
                        selection_date DATETIME NOT NULL,
                        score REAL NOT NULL,
                        reasons TEXT,
                        status VARCHAR(20) DEFAULT 'active',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 종목 가격 데이터 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stock_prices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        date_time DATETIME NOT NULL,
                        open_price REAL,
                        high_price REAL,
                        low_price REAL,
                        close_price REAL,
                        volume INTEGER,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, date_time)
                    )
                ''')
                
                # 매매 기록 테이블
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trading_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(10) NOT NULL,
                        action VARCHAR(10) NOT NULL,
                        quantity INTEGER NOT NULL,
                        price REAL NOT NULL,
                        timestamp DATETIME NOT NULL,
                        profit_loss REAL DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 인덱스 생성
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_candidate_date ON candidate_stocks(selection_date)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_candidate_code ON candidate_stocks(stock_code)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_code_date ON stock_prices(stock_code, date_time)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_trading_code_date ON trading_records(stock_code, timestamp)')
                
                conn.commit()
                self.logger.info("데이터베이스 테이블 생성 완료")
                
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
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 기존 당일 데이터 비활성화
                cursor.execute('''
                    UPDATE candidate_stocks 
                    SET status = 'inactive' 
                    WHERE DATE(selection_date) = DATE(?)
                ''', (selection_date.isoformat(),))
                
                # 새로운 후보 종목 저장
                for candidate in candidates:
                    cursor.execute('''
                        INSERT INTO candidate_stocks 
                        (stock_code, stock_name, selection_date, score, reasons, status)
                        VALUES (?, ?, ?, ?, ?, 'active')
                    ''', (
                        candidate.code,
                        candidate.name,
                        selection_date.isoformat(),
                        candidate.score,
                        candidate.reason
                    ))
                
                conn.commit()
                self.logger.info(f"후보 종목 {len(candidates)}개 저장 완료: {selection_date.strftime('%Y-%m-%d')}")
                return True
                
        except Exception as e:
            self.logger.error(f"후보 종목 저장 실패: {e}")
            return False
    
    def save_price_data(self, stock_code: str, price_data: List[PriceRecord]) -> bool:
        """가격 데이터 저장"""
        try:
            if not price_data:
                return True
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                for record in price_data:
                    cursor.execute('''
                        INSERT OR REPLACE INTO stock_prices 
                        (stock_code, date_time, open_price, high_price, low_price, close_price, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        stock_code,
                        record.date_time.isoformat(),
                        record.open_price,
                        record.high_price,
                        record.low_price,
                        record.close_price,
                        record.volume
                    ))
                
                conn.commit()
                self.logger.debug(f"{stock_code} 가격 데이터 {len(price_data)}개 저장")
                return True
                
        except Exception as e:
            self.logger.error(f"가격 데이터 저장 실패 ({stock_code}): {e}")
            return False
    
    def get_candidate_history(self, days: int = 30) -> pd.DataFrame:
        """후보 종목 선정 이력 조회"""
        try:
            start_date = now_kst() - timedelta(days=days)
            
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT 
                        stock_code,
                        stock_name,
                        selection_date,
                        score,
                        reasons,
                        status
                    FROM candidate_stocks 
                    WHERE selection_date >= ?
                    ORDER BY selection_date DESC, score DESC
                '''
                
                df = pd.read_sql_query(query, conn, params=(start_date.isoformat(),))
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
            
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT 
                        date_time,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume
                    FROM stock_prices 
                    WHERE stock_code = ? AND date_time >= ?
                    ORDER BY date_time ASC
                '''
                
                df = pd.read_sql_query(query, conn, params=(stock_code, start_date.isoformat()))
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
            
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT 
                        c.stock_code,
                        c.stock_name,
                        c.selection_date,
                        c.score,
                        COUNT(p.id) as price_records,
                        AVG(p.close_price) as avg_price,
                        MAX(p.high_price) as max_price,
                        MIN(p.low_price) as min_price
                    FROM candidate_stocks c
                    LEFT JOIN stock_prices p ON c.stock_code = p.stock_code 
                        AND p.date_time >= c.selection_date
                    WHERE c.selection_date >= ?
                    GROUP BY c.id
                    ORDER BY c.selection_date DESC, c.score DESC
                '''
                
                df = pd.read_sql_query(query, conn, params=(start_date.isoformat(),))
                df['selection_date'] = pd.to_datetime(df['selection_date'])
                
                return df
                
        except Exception as e:
            self.logger.error(f"성과 분석 조회 실패: {e}")
            return pd.DataFrame()
    
    def get_daily_candidate_count(self, days: int = 30) -> pd.DataFrame:
        """일별 후보 종목 선정 수"""
        try:
            start_date = now_kst() - timedelta(days=days)
            
            with sqlite3.connect(self.db_path) as conn:
                query = '''
                    SELECT 
                        DATE(selection_date) as date,
                        COUNT(*) as count,
                        AVG(score) as avg_score,
                        MAX(score) as max_score
                    FROM candidate_stocks 
                    WHERE selection_date >= ?
                    GROUP BY DATE(selection_date)
                    ORDER BY date DESC
                '''
                
                df = pd.read_sql_query(query, conn, params=(start_date.isoformat(),))
                df['date'] = pd.to_datetime(df['date'])
                
                return df
                
        except Exception as e:
            self.logger.error(f"일별 통계 조회 실패: {e}")
            return pd.DataFrame()
    
    def cleanup_old_data(self, keep_days: int = 90):
        """오래된 데이터 정리"""
        try:
            cutoff_date = now_kst() - timedelta(days=keep_days)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 오래된 후보 종목 데이터 삭제
                cursor.execute('''
                    DELETE FROM candidate_stocks 
                    WHERE selection_date < ?
                ''', (cutoff_date.isoformat(),))
                
                # 오래된 가격 데이터 삭제
                cursor.execute('''
                    DELETE FROM stock_prices 
                    WHERE date_time < ?
                ''', (cutoff_date.isoformat(),))
                
                conn.commit()
                self.logger.info(f"{keep_days}일 이전 데이터 정리 완료")
                
        except Exception as e:
            self.logger.error(f"데이터 정리 실패: {e}")
    
    def get_database_stats(self) -> Dict[str, int]:
        """데이터베이스 통계"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                stats = {}
                
                # 테이블별 레코드 수
                for table in ['candidate_stocks', 'stock_prices', 'trading_records']:
                    cursor.execute(f'SELECT COUNT(*) FROM {table}')
                    stats[table] = cursor.fetchone()[0]
                
                return stats
                
        except Exception as e:
            self.logger.error(f"통계 조회 실패: {e}")
            return {}