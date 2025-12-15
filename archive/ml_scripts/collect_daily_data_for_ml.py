#!/usr/bin/env python3
"""
ML 학습용 일봉 데이터 수집

pattern_data_log에 있는 종목들의 일봉 데이터를 수집하여 cache/daily에 저장합니다.
이후 ml_prepare_dataset_v2.py 실행 시 캐시에서 일봉 데이터를 사용합니다.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Set, Dict
import pickle

sys.path.append(str(Path(__file__).parent))

from api.kis_api_manager import KISAPIManager
from api.kis_market_api import get_inquire_daily_itemchartprice
from utils.logger import setup_logger

logger = setup_logger(__name__)


def extract_stock_codes_from_patterns() -> Dict[str, Set[str]]:
    """
    pattern_data_log에서 종목코드와 날짜 추출

    Returns:
        Dict[stock_code, Set[dates]]: 종목코드별 거래 날짜들
    """
    pattern_log_dir = Path('pattern_data_log')

    if not pattern_log_dir.exists():
        logger.error(f"패턴 로그 디렉토리 없음: {pattern_log_dir}")
        return {}

    stock_dates = {}  # {stock_code: {date1, date2, ...}}

    jsonl_files = sorted(pattern_log_dir.glob('pattern_data_*.jsonl'))
    logger.info(f"패턴 로그 파일 {len(jsonl_files)}개 스캔 중...")

    for jsonl_file in jsonl_files:
        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue

                    pattern = json.loads(line)

                    # 매매 결과가 있는 것만 (학습 데이터로 사용됨)
                    if not pattern.get('trade_result', {}).get('trade_executed', False):
                        continue

                    stock_code = pattern.get('stock_code', '')
                    timestamp = pattern.get('timestamp', '')

                    if not stock_code or not timestamp:
                        continue

                    try:
                        dt = datetime.fromisoformat(timestamp)
                        trade_date = dt.strftime('%Y%m%d')

                        if stock_code not in stock_dates:
                            stock_dates[stock_code] = set()
                        stock_dates[stock_code].add(trade_date)

                    except:
                        continue

        except Exception as e:
            logger.warning(f"{jsonl_file.name} 처리 오류: {e}")

    logger.info(f"추출 완료: {len(stock_dates)}개 종목, 총 {sum(len(dates) for dates in stock_dates.values())}건 거래")

    return stock_dates


def collect_daily_data(stock_code: str, trade_date: str, lookback_days: int = 60) -> bool:
    """
    특정 종목의 일봉 데이터 수집

    Args:
        stock_code: 종목코드
        trade_date: 거래일 (YYYYMMDD)
        lookback_days: 과거 N일 데이터

    Returns:
        bool: 성공 여부
    """
    # 캐시 디렉토리
    cache_dir = Path('cache/daily_data')
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 캐시 파일명
    cache_file = cache_dir / f"{stock_code}_{trade_date}_d{lookback_days}.pkl"

    # 이미 캐시 존재
    if cache_file.exists():
        return True

    # API 호출
    try:
        end_date = datetime.strptime(trade_date, '%Y%m%d')
        start_date = end_date - timedelta(days=lookback_days + 30)  # 여유있게

        df = get_inquire_daily_itemchartprice(
            output_dv="2",
            div_code="J",
            itm_no=stock_code,
            inqr_strt_dt=start_date.strftime('%Y%m%d'),
            inqr_end_dt=trade_date,
            period_code="D",
            adj_prc="1"
        )

        if df is None or len(df) == 0:
            logger.warning(f"{stock_code} {trade_date}: 일봉 데이터 없음")
            return False

        # 데이터 타입 변환
        df = df.copy()
        df['stck_bsop_date'] = df['stck_bsop_date'].astype(str)
        df['stck_oprc'] = pd.to_numeric(df['stck_oprc'], errors='coerce').fillna(0)
        df['stck_hgpr'] = pd.to_numeric(df['stck_hgpr'], errors='coerce').fillna(0)
        df['stck_lwpr'] = pd.to_numeric(df['stck_lwpr'], errors='coerce').fillna(0)
        df['stck_clpr'] = pd.to_numeric(df['stck_clpr'], errors='coerce').fillna(0)
        df['acml_vol'] = pd.to_numeric(df['acml_vol'], errors='coerce').fillna(0)

        # 정렬 및 필터링
        df = df.sort_values('stck_bsop_date').reset_index(drop=True)
        df = df[df['stck_bsop_date'] <= trade_date]
        df = df.tail(lookback_days)

        # 캐시 저장
        with open(cache_file, 'wb') as f:
            pickle.dump(df, f)

        logger.debug(f"✓ {stock_code} {trade_date}: {len(df)}일 저장")
        return True

    except Exception as e:
        logger.warning(f"{stock_code} {trade_date} 수집 오류: {e}")
        return False


def main():
    import pandas as pd
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("ML 학습용 일봉 데이터 수집")
    print("=" * 70)

    # 1. API 초기화
    print("\n📡 API 초기화 중...")
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("❌ API 초기화 실패")
        return
    print("✅ API 초기화 완료")

    # 2. 패턴 로그에서 종목코드 추출
    print("\n📂 패턴 로그 분석 중...")
    stock_dates = extract_stock_codes_from_patterns()

    if not stock_dates:
        print("❌ 수집할 데이터 없음")
        return

    # 종목별 거래 횟수 계산
    stock_counts = [(code, len(dates)) for code, dates in stock_dates.items()]
    stock_counts.sort(key=lambda x: x[1], reverse=True)

    print(f"\n📊 수집 대상:")
    print(f"   총 종목: {len(stock_dates)}개")
    print(f"   총 거래: {sum(count for _, count in stock_counts)}건")
    print(f"\n   상위 10개 종목:")
    for code, count in stock_counts[:10]:
        print(f"      {code}: {count}건")

    # 3. 일봉 데이터 수집
    print(f"\n🔄 일봉 데이터 수집 시작...")

    total = 0
    success = 0
    failed = 0
    cached = 0

    # 캐시 확인
    cache_dir = Path('cache/daily_data')
    existing_caches = set()
    if cache_dir.exists():
        for cache_file in cache_dir.glob('*.pkl'):
            # 파일명: {stock_code}_{date}_d{lookback}.pkl
            parts = cache_file.stem.split('_')
            if len(parts) >= 3:
                code = parts[0]
                date = parts[1]
                existing_caches.add((code, date))

    for stock_code, dates in stock_dates.items():
        for trade_date in sorted(dates):
            total += 1

            # 이미 캐시 존재
            if (stock_code, trade_date) in existing_caches:
                cached += 1
                continue

            # 수집
            if collect_daily_data(stock_code, trade_date, lookback_days=60):
                success += 1
            else:
                failed += 1

            # 진행상황 출력
            if total % 10 == 0:
                print(f"   진행: {total}건 (성공 {success}, 실패 {failed}, 캐시 {cached})")

    # 4. 결과 요약
    print("\n" + "=" * 70)
    print("📈 수집 완료")
    print("=" * 70)
    print(f"총 처리: {total}건")
    print(f"  - 캐시 사용: {cached}건")
    print(f"  - 신규 수집 성공: {success}건")
    print(f"  - 수집 실패: {failed}건")

    success_rate = (cached + success) / total * 100 if total > 0 else 0
    print(f"\n성공률: {success_rate:.1f}%")

    if success > 0 or cached > 0:
        print("\n✅ 다음 명령으로 ML 데이터셋을 재생성하세요:")
        print("   python ml_prepare_dataset_v2.py")


if __name__ == '__main__':
    main()
