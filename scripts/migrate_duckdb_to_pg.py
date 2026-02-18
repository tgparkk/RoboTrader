"""
DuckDB → PostgreSQL 데이터 마이그레이션 스크립트

1. 매매 기록 DB (db/robotrader_trades.duckdb) → PostgreSQL robotrader DB
   - candidate_stocks, stock_prices, virtual_trading_records, real_trading_records, trading_records
2. 시세 캐시 DB (cache/market_data_v2.duckdb) → PostgreSQL robotrader DB
   - minute_{code} 테이블들 → minute_candles 단일 테이블
   - daily_{code} 테이블들 → daily_candles 단일 테이블

사용법: cd /d D:\GIT\RoboTrader && python scripts/migrate_duckdb_to_pg.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb
import psycopg2
import psycopg2.extras
from pathlib import Path
from datetime import datetime

# 경로
TRADES_DB = Path(__file__).parent.parent / "db" / "robotrader_trades.duckdb"
CACHE_DB = Path(__file__).parent.parent / "cache" / "market_data_v2.duckdb"

# PostgreSQL 접속 정보
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD


def get_pg_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD
    )


def migrate_trades_db():
    """매매 기록 DB 마이그레이션"""
    if not TRADES_DB.exists():
        print(f"[SKIP] 매매 기록 DB 없음: {TRADES_DB}")
        return

    print(f"[START] 매매 기록 DB 마이그레이션: {TRADES_DB}")
    duck = duckdb.connect(str(TRADES_DB), read_only=True)
    pg = get_pg_conn()
    cur = pg.cursor()

    tables = ['candidate_stocks', 'stock_prices', 'virtual_trading_records', 'real_trading_records', 'trading_records']

    for table in tables:
        try:
            # DuckDB에서 데이터 조회
            df = duck.execute(f"SELECT * FROM {table}").fetchdf()
            if df.empty:
                print(f"  [{table}] 데이터 없음 (스킵)")
                continue

            # id 컬럼 제외 (PostgreSQL SERIAL 사용)
            cols = [c for c in df.columns if c != 'id']
            if not cols:
                continue

            placeholders = ', '.join(['%s'] * len(cols))
            col_names = ', '.join(cols)
            insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"

            import numpy as np
            import pandas as _pd
            rows = []
            for _, row in df.iterrows():
                row_data = []
                for c in cols:
                    val = row[c]
                    if hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    else:
                        try:
                            if _pd.isna(val):
                                val = None
                        except (TypeError, ValueError):
                            pass
                    row_data.append(val)
                rows.append(tuple(row_data))

            psycopg2.extras.execute_batch(cur, insert_sql, rows, page_size=500)
            pg.commit()
            print(f"  [{table}] {len(rows)}건 마이그레이션 완료")

        except Exception as e:
            pg.rollback()
            print(f"  [{table}] 마이그레이션 실패: {e}")

    duck.close()
    pg.close()
    print("[DONE] 매매 기록 DB 마이그레이션 완료")


def migrate_cache_db():
    """시세 캐시 DB 마이그레이션 (3.8GB — 시간이 오래 걸릴 수 있음)"""
    if not CACHE_DB.exists():
        print(f"[SKIP] 시세 캐시 DB 없음: {CACHE_DB}")
        return

    print(f"[START] 시세 캐시 DB 마이그레이션: {CACHE_DB}")
    duck = duckdb.connect(str(CACHE_DB), read_only=True)
    pg = get_pg_conn()
    cur = pg.cursor()

    # 모든 테이블 조회
    tables = duck.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
    minute_tables = [t[0] for t in tables if t[0].startswith('minute_')]
    daily_tables = [t[0] for t in tables if t[0].startswith('daily_')]

    print(f"  분봉 테이블: {len(minute_tables)}개, 일봉 테이블: {len(daily_tables)}개")

    # 분봉 마이그레이션
    migrated = 0
    for table_name in minute_tables:
        try:
            stock_code = table_name[len('minute_'):]
            df = duck.execute(f"SELECT * FROM {table_name}").fetchdf()
            if df.empty:
                continue

            rows = []
            for _, row in df.iterrows():
                dt_val = row.get('datetime', None)
                if dt_val is not None and hasattr(dt_val, 'strftime'):
                    dt_str = dt_val.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    dt_str = str(dt_val) if dt_val is not None else None

                rows.append((
                    stock_code,
                    str(row.get('trade_date', '')),
                    int(row.get('idx', 0)),
                    str(row.get('date', '')) if row.get('date') is not None else None,
                    str(row.get('time', '')) if row.get('time') is not None else None,
                    float(row.get('close', 0)) if row.get('close') is not None else 0,
                    float(row.get('open', 0)) if row.get('open') is not None else 0,
                    float(row.get('high', 0)) if row.get('high') is not None else 0,
                    float(row.get('low', 0)) if row.get('low') is not None else 0,
                    float(row.get('volume', 0)) if row.get('volume') is not None else 0,
                    float(row.get('amount', 0)) if row.get('amount') is not None else 0,
                    dt_str,
                ))

            if rows:
                psycopg2.extras.execute_batch(
                    cur,
                    '''INSERT INTO minute_candles
                    (stock_code, trade_date, idx, date, time, close, open, high, low, volume, amount, datetime)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (stock_code, trade_date, idx) DO NOTHING''',
                    rows,
                    page_size=1000,
                )
                pg.commit()

            migrated += 1
            if migrated % 100 == 0:
                print(f"  분봉 {migrated}/{len(minute_tables)} 테이블 완료...")

        except Exception as e:
            pg.rollback()
            print(f"  [minute_{stock_code}] 실패: {e}")

    print(f"  분봉 마이그레이션 완료: {migrated}/{len(minute_tables)} 테이블")

    # 일봉 마이그레이션
    migrated = 0
    for table_name in daily_tables:
        try:
            stock_code = table_name[len('daily_'):]
            df = duck.execute(f"SELECT * FROM {table_name}").fetchdf()
            if df.empty:
                continue

            rows = []
            for _, row in df.iterrows():
                rows.append((
                    stock_code,
                    str(row.get('stck_bsop_date', '')),
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
                psycopg2.extras.execute_batch(
                    cur,
                    '''INSERT INTO daily_candles
                    (stock_code, stck_bsop_date, stck_clpr, stck_oprc, stck_hgpr, stck_lwpr,
                     acml_vol, acml_tr_pbmn, flng_cls_code, prtt_rate, mod_yn,
                     prdy_vrss_sign, prdy_vrss, revl_issu_reas)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (stock_code, stck_bsop_date) DO NOTHING''',
                    rows,
                    page_size=1000,
                )
                pg.commit()

            migrated += 1
            if migrated % 100 == 0:
                print(f"  일봉 {migrated}/{len(daily_tables)} 테이블 완료...")

        except Exception as e:
            pg.rollback()
            print(f"  [daily_{stock_code}] 실패: {e}")

    print(f"  일봉 마이그레이션 완료: {migrated}/{len(daily_tables)} 테이블")

    duck.close()
    pg.close()
    print("[DONE] 시세 캐시 DB 마이그레이션 완료")


if __name__ == '__main__':
    print("=" * 60)
    print("DuckDB → PostgreSQL 마이그레이션")
    print("=" * 60)

    if '--trades-only' in sys.argv:
        migrate_trades_db()
    elif '--cache-only' in sys.argv:
        migrate_cache_db()
    else:
        migrate_trades_db()
        print()
        migrate_cache_db()
