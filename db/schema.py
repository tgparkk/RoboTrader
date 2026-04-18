"""데이터베이스 스키마 정의 (PostgreSQL).

CREATE TABLE / CREATE INDEX DDL만 담는다. 실제 실행은 DatabaseManager가 담당.
"""
from typing import List


CREATE_TABLES_SQL: List[str] = [
    # 후보 종목 테이블
    '''
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
    ''',

    # 종목 가격 데이터 테이블
    '''
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
    ''',

    # 가상 매매 기록 테이블
    '''
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
    ''',

    # 실거래 매매 기록 테이블
    '''
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
    ''',

    # 매매 기록 테이블 (기존)
    '''
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
    ''',

    # NXT 프리마켓 스냅샷 테이블
    '''
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
    ''',
]


CREATE_INDEXES_SQL: List[str] = [
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


def init_schema(conn) -> None:
    """주어진 psycopg2 connection으로 테이블과 인덱스를 생성한다.

    호출자가 connection lifecycle(커밋/롤백/반환)을 책임진다.
    인덱스 생성 실패는 조용히 무시 (기존 동작 유지).
    """
    cur = conn.cursor()
    for stmt in CREATE_TABLES_SQL:
        cur.execute(stmt)
    for stmt in CREATE_INDEXES_SQL:
        try:
            cur.execute(stmt)
        except Exception:
            pass
