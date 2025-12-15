#!/usr/bin/env python3
"""
ML 학습용 일봉 데이터 수집 전용 스크립트

pattern_data_log에 있는 종목들의 일봉 데이터를 수집합니다.

사용법:
python save_daily_data_for_ml.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Set
import pandas as pd

from utils.logger import setup_logger
from api.kis_api_manager import KISAPIManager
from api.kis_market_api import get_inquire_daily_itemchartprice


class DailyDataCollector:
    """일봉 데이터 수집기"""

    def __init__(self):
        self.logger = setup_logger(__name__)
        self.api_manager = None

        # 캐시 디렉토리
        self.cache_dir = Path("cache")
        self.daily_dir = self.cache_dir / "daily_data"

        # 디렉토리 생성
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def initialize_api(self) -> bool:
        """API 매니저 초기화"""
        try:
            self.logger.info("API 매니저 초기화 중...")
            self.api_manager = KISAPIManager()

            if not self.api_manager.initialize():
                self.logger.error("API 초기화 실패")
                return False

            self.logger.info("API 매니저 초기화 완료")
            return True

        except Exception as e:
            self.logger.error(f"API 초기화 오류: {e}")
            return False

    def extract_stock_dates_from_patterns(self) -> Dict[str, Set[str]]:
        """
        pattern_data_log에서 종목코드와 거래일 추출

        Returns:
            Dict[stock_code, Set[dates]]: 종목코드별 거래 날짜 집합
        """
        pattern_log_dir = Path('pattern_data_log')

        if not pattern_log_dir.exists():
            self.logger.error(f"패턴 로그 디렉토리 없음: {pattern_log_dir}")
            return {}

        stock_dates = {}

        jsonl_files = sorted(pattern_log_dir.glob('pattern_data_*.jsonl'))
        self.logger.info(f"패턴 로그 파일 {len(jsonl_files)}개 스캔 중...")

        for jsonl_file in jsonl_files:
            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue

                        pattern = json.loads(line)

                        # None 체크
                        if pattern is None:
                            continue

                        # 매매 결과가 있는 것만
                        trade_result = pattern.get('trade_result')
                        if trade_result is None or not trade_result.get('trade_executed', False):
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
                self.logger.warning(f"{jsonl_file.name} 처리 오류: {e}")

        total_trades = sum(len(dates) for dates in stock_dates.values())
        self.logger.info(f"추출 완료: {len(stock_dates)}개 종목, {total_trades}건 거래")

        return stock_dates

    def save_daily_data(self, stock_code: str, trade_date: str, days_back: int = 60) -> bool:
        """
        종목의 일봉 데이터 저장

        Args:
            stock_code: 종목코드
            trade_date: 거래일 (YYYYMMDD)
            days_back: 과거 N일 데이터

        Returns:
            bool: 저장 성공 여부
        """
        try:
            # 캐시 파일명
            cache_file = self.daily_dir / f"{stock_code}_{trade_date}_d{days_back}.pkl"

            # 이미 존재하면 스킵
            if cache_file.exists():
                return True

            # 날짜 계산
            target_date_obj = datetime.strptime(trade_date, '%Y%m%d')
            start_date_obj = target_date_obj - timedelta(days=days_back + 30)

            start_date = start_date_obj.strftime('%Y%m%d')
            end_date = trade_date

            # API 호출
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",
                div_code="J",
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",
                adj_prc="1"
            )

            if daily_data is None or daily_data.empty:
                self.logger.warning(f"{stock_code} {trade_date}: 일봉 데이터 없음")
                return False

            # 데이터 타입 변환 및 정렬
            daily_data = daily_data.copy()
            daily_data['stck_bsop_date'] = daily_data['stck_bsop_date'].astype(str)
            daily_data['stck_oprc'] = pd.to_numeric(daily_data['stck_oprc'], errors='coerce').fillna(0)
            daily_data['stck_hgpr'] = pd.to_numeric(daily_data['stck_hgpr'], errors='coerce').fillna(0)
            daily_data['stck_lwpr'] = pd.to_numeric(daily_data['stck_lwpr'], errors='coerce').fillna(0)
            daily_data['stck_clpr'] = pd.to_numeric(daily_data['stck_clpr'], errors='coerce').fillna(0)
            daily_data['acml_vol'] = pd.to_numeric(daily_data['acml_vol'], errors='coerce').fillna(0)

            # 정렬 및 필터링
            daily_data = daily_data.sort_values('stck_bsop_date').reset_index(drop=True)
            daily_data = daily_data[daily_data['stck_bsop_date'] <= trade_date]
            daily_data = daily_data.tail(days_back)

            # 저장
            with open(cache_file, 'wb') as f:
                pickle.dump(daily_data, f)

            self.logger.debug(f"저장 완료: {stock_code} {trade_date} ({len(daily_data)}일)")
            return True

        except Exception as e:
            self.logger.warning(f"{stock_code} {trade_date} 수집 오류: {e}")
            return False

    async def collect_all_daily_data(self) -> Dict:
        """모든 일봉 데이터 수집"""
        try:
            # 1. API 초기화
            if not self.initialize_api():
                return {
                    'success': False,
                    'error': 'API 초기화 실패'
                }

            # 2. 종목 및 날짜 추출
            stock_dates = self.extract_stock_dates_from_patterns()

            if not stock_dates:
                return {
                    'success': False,
                    'error': '수집할 데이터 없음'
                }

            # 종목별 거래 횟수
            stock_counts = [(code, len(dates)) for code, dates in stock_dates.items()]
            stock_counts.sort(key=lambda x: x[1], reverse=True)

            print(f"\n수집 대상:")
            print(f"  총 종목: {len(stock_dates)}개")
            print(f"  총 거래: {sum(count for _, count in stock_counts)}건")
            print(f"\n  상위 10개 종목:")
            for code, count in stock_counts[:10]:
                print(f"    {code}: {count}건")

            # 3. 캐시 확인
            existing_caches = set()
            for cache_file in self.daily_dir.glob('*.pkl'):
                parts = cache_file.stem.split('_')
                if len(parts) >= 3:
                    code = parts[0]
                    date = parts[1]
                    existing_caches.add((code, date))

            # 4. 일봉 데이터 수집
            print(f"\n일봉 데이터 수집 시작...")

            total = 0
            success = 0
            failed = 0
            cached = 0

            for stock_code, dates in stock_dates.items():
                for trade_date in sorted(dates):
                    total += 1

                    # 캐시 존재
                    if (stock_code, trade_date) in existing_caches:
                        cached += 1
                        continue

                    # 수집
                    if self.save_daily_data(stock_code, trade_date, days_back=60):
                        success += 1
                    else:
                        failed += 1

                    # 진행상황
                    if total % 10 == 0:
                        print(f"  진행: {total}건 (성공 {success}, 실패 {failed}, 캐시 {cached})")

            return {
                'success': True,
                'total': total,
                'success_count': success,
                'failed': failed,
                'cached': cached
            }

        except Exception as e:
            self.logger.error(f"일봉 데이터 수집 오류: {e}")
            return {
                'success': False,
                'error': str(e)
            }


def main():
    print("=" * 70)
    print("ML 학습용 일봉 데이터 수집")
    print("=" * 70)

    collector = DailyDataCollector()

    # 비동기 실행
    result = asyncio.run(collector.collect_all_daily_data())

    # 결과 출력
    print("\n" + "=" * 70)
    print("수집 완료")
    print("=" * 70)

    if result['success']:
        print(f"총 처리: {result['total']}건")
        print(f"  - 캐시 사용: {result['cached']}건")
        print(f"  - 신규 수집 성공: {result['success_count']}건")
        print(f"  - 수집 실패: {result['failed']}건")

        success_rate = (result['cached'] + result['success_count']) / result['total'] * 100 if result['total'] > 0 else 0
        print(f"\n성공률: {success_rate:.1f}%")

        if result['success_count'] > 0 or result['cached'] > 0:
            print("\n다음 명령으로 ML 데이터셋을 재생성하세요:")
            print("  python ml_prepare_dataset_v2.py")
            print("  python ml_train_model_v2.py")
    else:
        print(f"오류: {result.get('error', '알 수 없는 오류')}")


if __name__ == '__main__':
    main()
