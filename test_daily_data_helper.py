#!/usr/bin/env python3
"""
일봉 데이터 헬퍼 테스트
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.daily_data_helper import (
    ensure_daily_data_for_stock,
    check_daily_data_coverage
)
from utils.logger import setup_logger

logger = setup_logger(__name__)


def test_single_stock():
    """단일 종목 테스트"""
    print("=" * 70)
    print("테스트 1: 단일 종목 일봉 데이터 확보")
    print("=" * 70)

    stock_code = '005930'  # 삼성전자
    print(f"\n종목: {stock_code}")

    success = ensure_daily_data_for_stock(stock_code)

    if success:
        print(f"✅ 성공: {stock_code} 일봉 데이터 확보")
    else:
        print(f"❌ 실패: {stock_code} 일봉 데이터 수집 실패")


def test_coverage_check():
    """커버리지 확인 테스트"""
    print("\n" + "=" * 70)
    print("테스트 2: 일봉 데이터 커버리지 확인")
    print("=" * 70)

    # candidate_stocks에서 최근 종목 조회
    import psycopg2

    conn = psycopg2.connect(host='172.23.208.1', port=5433, dbname='robotrader', user='postgres')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT stock_code
        FROM candidate_stocks
        WHERE selection_date >= CURRENT_DATE - INTERVAL '7 days'
        ORDER BY selection_date DESC
        LIMIT 20
    """)

    stock_codes = [row[0] for row in cursor.fetchall()]
    conn.close()

    if not stock_codes:
        print("⚠️ 최근 7일 후보 종목 없음")
        return

    print(f"\n최근 7일 후보 종목: {len(stock_codes)}개")

    coverage = check_daily_data_coverage(stock_codes)

    print(f"\n📊 커버리지 리포트:")
    print(f"  - 총 종목: {coverage['total']}개")
    print(f"  - 데이터 최신: {coverage['with_data']}개 ({coverage['with_data']/coverage['total']*100:.1f}%)")
    print(f"  - 데이터 없음: {coverage['without_data']}개")
    print(f"  - 데이터 오래됨: {coverage['outdated']}개")

    if coverage['missing_stocks']:
        print(f"\n⚠️ 데이터 없는 종목:")
        for stock in coverage['missing_stocks'][:5]:
            print(f"    - {stock}")
        if len(coverage['missing_stocks']) > 5:
            print(f"    ... 외 {len(coverage['missing_stocks']) - 5}개")

    if coverage['outdated_stocks']:
        print(f"\n⚠️ 데이터 오래된 종목:")
        for stock in coverage['outdated_stocks'][:5]:
            print(f"    - {stock}")
        if len(coverage['outdated_stocks']) > 5:
            print(f"    ... 외 {len(coverage['outdated_stocks']) - 5}개")


def test_data_verification():
    """데이터 검증 테스트"""
    print("\n" + "=" * 70)
    print("테스트 3: 수집된 데이터 검증")
    print("=" * 70)

    from utils.data_cache import DailyDataCache
    from datetime import datetime

    daily_cache = DailyDataCache()
    stock_code = '005930'

    df = daily_cache.load_data(stock_code)

    if df is None or df.empty:
        print(f"⚠️ {stock_code} 데이터 없음")
        return

    print(f"\n종목: {stock_code}")
    print(f"데이터 기간: {df['stck_bsop_date'].min()} ~ {df['stck_bsop_date'].max()}")
    print(f"총 {len(df)}일")
    print(f"\n최근 5일:")
    print(df[['stck_bsop_date', 'stck_clpr', 'acml_vol']].tail(5).to_string(index=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')

    test_single_stock()
    test_coverage_check()
    test_data_verification()

    print("\n" + "=" * 70)
    print("테스트 완료")
    print("=" * 70)
