# -*- coding: utf-8 -*-
"""
pkl 파일을 DuckDB로 마이그레이션 (종목별 테이블 구조)

테이블 네이밍:
- 분봉: minute_005930
- 일봉: daily_005930

사용법:
    python migrate_pkl_to_duckdb_v2.py
"""

import os
import sys
import pickle
import glob
import time
from pathlib import Path
from collections import defaultdict

import duckdb
import pandas as pd
from tqdm import tqdm

# DB 경로
DB_PATH = Path(__file__).parent / "cache" / "market_data_v2.duckdb"
MINUTE_DATA_DIR = Path(__file__).parent / "cache" / "minute_data"
DAILY_DATA_DIR = Path(__file__).parent / "cache" / "daily"


def get_minute_table_name(stock_code: str) -> str:
    """분봉 테이블명 생성"""
    return f"minute_{stock_code}"


def get_daily_table_name(stock_code: str) -> str:
    """일봉 테이블명 생성"""
    return f"daily_{stock_code}"


def create_minute_table(con: duckdb.DuckDBPyConnection, stock_code: str):
    """분봉 테이블 생성"""
    table_name = get_minute_table_name(stock_code)
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


def create_daily_table(con: duckdb.DuckDBPyConnection, stock_code: str):
    """일봉 테이블 생성"""
    table_name = get_daily_table_name(stock_code)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
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
            PRIMARY KEY (base_date, stck_bsop_date)
        )
    """)
    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON {table_name}(base_date)")


def parse_minute_filename(filename: str) -> tuple:
    """분봉 파일명에서 종목코드와 날짜 추출"""
    basename = os.path.basename(filename).replace('.pkl', '')
    parts = basename.split('_')
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def parse_daily_filename(filename: str) -> tuple:
    """일봉 파일명에서 종목코드와 날짜 추출"""
    basename = os.path.basename(filename).replace('_daily.pkl', '')
    parts = basename.split('_')
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def migrate_minute_data(con: duckdb.DuckDBPyConnection):
    """분봉 데이터 마이그레이션"""
    pkl_files = sorted(glob.glob(str(MINUTE_DATA_DIR / "*.pkl")))
    total = len(pkl_files)

    print(f"\n=== 분봉 데이터 마이그레이션 ===")
    print(f"총 파일 수: {total}")

    # 종목별로 그룹화
    stock_files = defaultdict(list)
    for filepath in pkl_files:
        stock_code, trade_date = parse_minute_filename(filepath)
        if stock_code and trade_date:
            stock_files[stock_code].append((trade_date, filepath))

    print(f"종목 수: {len(stock_files)}")

    success = 0
    errors = []

    for stock_code, files in tqdm(stock_files.items(), desc="분봉 마이그레이션"):
        try:
            # 테이블 생성
            create_minute_table(con, stock_code)
            table_name = get_minute_table_name(stock_code)

            for trade_date, filepath in files:
                try:
                    with open(filepath, 'rb') as f:
                        df = pickle.load(f)

                    # DataFrame 준비
                    df_to_save = df.copy()
                    df_to_save['trade_date'] = trade_date
                    df_to_save['idx'] = df.index

                    # 기존 데이터 삭제 후 삽입
                    con.execute(f"DELETE FROM {table_name} WHERE trade_date = ?", [trade_date])
                    con.execute(f"""
                        INSERT INTO {table_name}
                        SELECT trade_date, idx, date, time, close, open, high, low, volume, amount, datetime
                        FROM df_to_save
                    """)

                    success += 1

                except Exception as e:
                    errors.append((filepath, str(e)))

            con.commit()

        except Exception as e:
            errors.append((stock_code, str(e)))

    print(f"\n분봉 마이그레이션 완료: {success}/{total} 성공")
    print(f"생성된 테이블 수: {len(stock_files)}")
    if errors:
        print(f"에러 {len(errors)}건:")
        for item, err in errors[:5]:
            print(f"  - {item}: {err}")


def migrate_daily_data(con: duckdb.DuckDBPyConnection):
    """일봉 데이터 마이그레이션"""
    pkl_files = sorted(glob.glob(str(DAILY_DATA_DIR / "*_daily.pkl")))
    total = len(pkl_files)

    print(f"\n=== 일봉 데이터 마이그레이션 ===")
    print(f"총 파일 수: {total}")

    # 종목별로 그룹화
    stock_files = defaultdict(list)
    for filepath in pkl_files:
        stock_code, base_date = parse_daily_filename(filepath)
        if stock_code and base_date:
            stock_files[stock_code].append((base_date, filepath))

    print(f"종목 수: {len(stock_files)}")

    success = 0
    errors = []

    for stock_code, files in tqdm(stock_files.items(), desc="일봉 마이그레이션"):
        try:
            # 테이블 생성
            create_daily_table(con, stock_code)
            table_name = get_daily_table_name(stock_code)

            for base_date, filepath in files:
                try:
                    with open(filepath, 'rb') as f:
                        df = pickle.load(f)

                    # DataFrame 준비
                    df_to_save = df.copy()
                    df_to_save['base_date'] = base_date

                    # 필요한 컬럼만 선택
                    required_cols = ['stck_bsop_date', 'stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr',
                                   'acml_vol', 'acml_tr_pbmn', 'flng_cls_code', 'prtt_rate', 'mod_yn',
                                   'prdy_vrss_sign', 'prdy_vrss', 'revl_issu_reas']
                    for col in required_cols:
                        if col not in df_to_save.columns:
                            df_to_save[col] = None

                    # 기존 데이터 삭제 후 삽입
                    con.execute(f"DELETE FROM {table_name} WHERE base_date = ?", [base_date])
                    con.execute(f"""
                        INSERT INTO {table_name}
                        SELECT base_date, stck_bsop_date, stck_clpr, stck_oprc,
                               stck_hgpr, stck_lwpr, acml_vol, acml_tr_pbmn, flng_cls_code,
                               prtt_rate, mod_yn, prdy_vrss_sign, prdy_vrss, revl_issu_reas
                        FROM df_to_save
                    """)

                    success += 1

                except Exception as e:
                    errors.append((filepath, str(e)))

            con.commit()

        except Exception as e:
            errors.append((stock_code, str(e)))

    print(f"\n일봉 마이그레이션 완료: {success}/{total} 성공")
    print(f"생성된 테이블 수: {len(stock_files)}")
    if errors:
        print(f"에러 {len(errors)}건:")
        for item, err in errors[:5]:
            print(f"  - {item}: {err}")


def verify_migration(con: duckdb.DuckDBPyConnection):
    """마이그레이션 검증"""
    print("\n=== 마이그레이션 검증 ===")

    # 테이블 목록 조회
    tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    minute_tables = [t[0] for t in tables if t[0].startswith('minute_')]
    daily_tables = [t[0] for t in tables if t[0].startswith('daily_')]

    print(f"분봉 테이블 수: {len(minute_tables)}")
    print(f"일봉 테이블 수: {len(daily_tables)}")

    # 샘플 테이블 통계
    if minute_tables:
        sample_table = minute_tables[0]
        count = con.execute(f"SELECT COUNT(*) FROM {sample_table}").fetchone()[0]
        dates = con.execute(f"SELECT COUNT(DISTINCT trade_date) FROM {sample_table}").fetchone()[0]
        print(f"\n샘플 테이블 [{sample_table}]: {count}행, {dates}일치 데이터")

    # DB 파일 크기
    db_size = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\nDB 파일 크기: {db_size:.1f}MB")


def main():
    print("=" * 60)
    print("pkl -> DuckDB 마이그레이션 (종목별 테이블)")
    print("=" * 60)
    print(f"DB 경로: {DB_PATH}")

    # 기존 DB 삭제
    if DB_PATH.exists():
        os.remove(DB_PATH)
        print("기존 DB 삭제 완료")

    start_time = time.time()

    # DB 연결
    con = duckdb.connect(str(DB_PATH))

    # 마이그레이션 실행
    migrate_minute_data(con)
    migrate_daily_data(con)

    # 검증
    verify_migration(con)

    con.close()

    elapsed = time.time() - start_time
    print(f"\n총 소요 시간: {elapsed:.1f}초")


if __name__ == "__main__":
    main()
