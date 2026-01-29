#!/usr/bin/env python3
"""
어드밴스 필터 분석을 위한 일봉 데이터 수집

candidate_stocks의 모든 종목에 대해 과거 일봉 데이터를 수집하여
DuckDB daily_{stock_code} 테이블에 저장합니다.
"""

import sys
import time
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.kis_api_manager import KISAPIManager
from api.kis_market_api import get_inquire_daily_itemchartprice
from utils.data_cache import DailyDataCache
from utils.logger import setup_logger

logger = setup_logger(__name__)


def get_unique_stocks_from_candidates() -> list:
    """candidate_stocks에서 고유 종목 목록 추출"""
    db_path = Path(__file__).parent.parent / "data" / "robotrader.db"

    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query(
        "SELECT DISTINCT stock_code FROM candidate_stocks ORDER BY stock_code",
        conn
    )
    conn.close()

    return df['stock_code'].tolist()


def get_existing_daily_data_info(daily_cache: DailyDataCache, stock_code: str) -> tuple:
    """기존 일봉 데이터의 최신 날짜와 레코드 수 확인"""
    df = daily_cache.load_data(stock_code)
    if df is None or df.empty:
        return None, 0

    max_date = df['stck_bsop_date'].max()
    return max_date, len(df)


def collect_daily_data(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """일봉 데이터 수집"""
    try:
        df = get_inquire_daily_itemchartprice(
            output_dv="2",  # output2 (상세 데이터)
            div_code="J",
            itm_no=stock_code,
            inqr_strt_dt=start_date,
            inqr_end_dt=end_date
        )
        return df
    except Exception as e:
        logger.warning(f"{stock_code} 일봉 수집 오류: {e}")
        return None


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("어드밴스 필터 분석용 일봉 데이터 수집")
    print("=" * 70)

    # 1. API 초기화
    print("\n[1/4] API 초기화 중...")
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("API 초기화 실패")
        return
    print("API 초기화 완료")

    # 2. 종목 목록 추출
    print("\n[2/4] candidate_stocks에서 종목 목록 추출 중...")
    stocks = get_unique_stocks_from_candidates()
    print(f"수집 대상: {len(stocks)}개 종목")

    # 3. 날짜 범위 설정 (2025-08-01 ~ 오늘)
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = "20250801"  # candidate_stocks 시작일 이전
    print(f"수집 기간: {start_date} ~ {end_date}")

    # 4. 일봉 데이터 수집
    print("\n[3/4] 일봉 데이터 수집 중...")
    daily_cache = DailyDataCache()

    success = 0
    failed = 0
    skipped = 0

    for i, stock_code in enumerate(stocks, 1):
        # 기존 데이터 확인
        existing_date, existing_count = get_existing_daily_data_info(daily_cache, stock_code)

        # 최신 데이터가 있으면 스킵 (오늘 또는 어제 데이터)
        today = datetime.now().strftime('%Y%m%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

        if existing_date and existing_date >= yesterday:
            skipped += 1
            if i % 100 == 0 or i == len(stocks):
                print(f"  진행: {i}/{len(stocks)} (성공: {success}, 스킵: {skipped}, 실패: {failed})")
            continue

        # API 호출
        df = collect_daily_data(stock_code, start_date, end_date)

        if df is not None and not df.empty:
            # DuckDB에 저장
            if daily_cache.save_data(stock_code, df):
                success += 1
            else:
                failed += 1
        else:
            failed += 1

        # 진행상황 출력
        if i % 50 == 0 or i == len(stocks):
            print(f"  진행: {i}/{len(stocks)} (성공: {success}, 스킵: {skipped}, 실패: {failed})")

        # API 호출 제한 준수
        time.sleep(0.05)

    # 5. 결과 요약
    print("\n[4/4] 수집 완료")
    print("=" * 70)
    print(f"총 종목: {len(stocks)}개")
    print(f"  - 신규 수집: {success}개")
    print(f"  - 스킵 (최신): {skipped}개")
    print(f"  - 실패: {failed}개")

    success_rate = (success + skipped) / len(stocks) * 100 if stocks else 0
    print(f"\n성공률: {success_rate:.1f}%")

    if success > 0 or skipped > 0:
        print("\n다음 단계: python analyze_daily_features.py")


if __name__ == '__main__':
    main()
