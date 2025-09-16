#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매매 분석을 위한 데이터 수집기
- 날짜별 후보 종목 조회 (DB 또는 신호 로그에서)
- 분봉/일봉 데이터 자동 수집 (캐시 우선, 없으면 API 호출)
- 완전한 데이터셋 구성
"""

import os
import sys
import sqlite3
import pickle
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import logging
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from api.kis_api_manager import KISAPIManager
from utils.korean_time import now_kst
from utils.logger import setup_logger

logger = setup_logger(__name__)

class AnalysisDataCollector:
    """매매 분석을 위한 데이터 수집기"""

    def __init__(self,
                 db_path: str = "data/robotrader.db",
                 minute_cache_dir: str = "cache/minute_data",
                 daily_cache_dir: str = "cache/daily_data",
                 signal_log_dir: str = "signal_replay_log"):
        self.db_path = db_path
        self.minute_cache_dir = Path(minute_cache_dir)
        self.daily_cache_dir = Path(daily_cache_dir)
        self.signal_log_dir = Path(signal_log_dir)

        # API 매니저 초기화
        self.api_manager = None
        try:
            self.api_manager = KISAPIManager()
            if self.api_manager.initialize():
                logger.info("KIS API 매니저 초기화 성공")
            else:
                logger.warning("KIS API 매니저 초기화 실패 - 캐시 전용 모드로 동작")
                self.api_manager = None
        except Exception as e:
            logger.warning(f"KIS API 매니저 초기화 오류: {e} - 캐시 전용 모드로 동작")
            self.api_manager = None

        # 캐시 디렉토리 생성
        self.minute_cache_dir.mkdir(parents=True, exist_ok=True)
        self.daily_cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"분석 데이터 수집기 초기화 완료")
        logger.info(f"   - DB: {db_path}")
        logger.info(f"   - 분봉 캐시: {self.minute_cache_dir}")
        logger.info(f"   - 일봉 캐시: {self.daily_cache_dir}")
        logger.info(f"   - 신호 로그: {self.signal_log_dir}")
        logger.info(f"   - API 상태: {'활성' if self.api_manager else '비활성 (캐시만)'}")

    def get_candidate_stocks_by_date_range(self, start_date: str, end_date: str) -> Dict[str, List[Dict]]:
        """날짜 범위의 후보 종목 조회"""
        try:
            # 1. 먼저 데이터베이스에서 조회 시도
            if os.path.exists(self.db_path):
                stocks_from_db = self._get_stocks_from_database(start_date, end_date)
                if stocks_from_db:
                    return stocks_from_db

            # 2. 데이터베이스에 데이터가 없으면 신호 로그에서 추출
            logger.info("데이터베이스에 데이터가 없습니다. 신호 로그에서 종목 정보를 추출합니다.")
            return self._extract_stocks_from_logs(start_date, end_date)

        except Exception as e:
            logger.error(f"후보 종목 조회 실패: {e}")
            return {}

    def _get_stocks_from_database(self, start_date: str, end_date: str) -> Dict[str, List[Dict]]:
        """데이터베이스에서 후보 종목 조회"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 먼저 테이블 존재 여부 확인
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='candidate_stocks'")
                if not cursor.fetchone():
                    logger.info("candidate_stocks 테이블이 존재하지 않습니다.")
                    return {}

                cursor.execute("""
                    SELECT stock_code, stock_name, selection_date, selection_reason
                    FROM candidate_stocks
                    WHERE DATE(selection_date) BETWEEN ? AND ?
                    ORDER BY selection_date, stock_code
                """, (start_date, end_date))

                results = cursor.fetchall()

                if not results:
                    logger.info(f"데이터베이스에서 {start_date}~{end_date} 기간의 후보 종목을 찾을 수 없습니다.")
                    return {}

                # 날짜별로 그룹화
                stocks_by_date = {}
                for row in results:
                    stock_code, stock_name, selection_date, selection_reason = row
                    date_str = selection_date.split(' ')[0] if ' ' in selection_date else selection_date

                    if date_str not in stocks_by_date:
                        stocks_by_date[date_str] = []

                    stocks_by_date[date_str].append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'selection_date': selection_date,
                        'selection_reason': selection_reason
                    })

                logger.info(f"데이터베이스에서 {start_date}~{end_date} 기간 후보 종목 {len(results)}개 조회")
                return stocks_by_date

        except Exception as e:
            logger.error(f"데이터베이스 조회 실패: {e}")
            return {}

    def _extract_stocks_from_logs(self, start_date: str, end_date: str) -> Dict[str, List[Dict]]:
        """신호 로그에서 종목 정보 추출"""
        stocks_by_date = {}

        try:
            # 날짜 범위에 해당하는 로그 파일들 찾기
            start_dt = datetime.strptime(start_date, '%Y%m%d')
            end_dt = datetime.strptime(end_date, '%Y%m%d')

            for log_file in self.signal_log_dir.glob("signal_new2_replay_*.txt"):
                # 파일명에서 날짜 추출
                match = re.search(r'(\d{8})', log_file.name)
                if not match:
                    continue

                file_date_str = match.group(1)
                file_date = datetime.strptime(file_date_str, '%Y%m%d')

                if not (start_dt <= file_date <= end_dt):
                    continue

                # 로그 파일에서 종목코드 추출
                stocks = self._parse_stocks_from_log_file(log_file, file_date_str)
                if stocks:
                    stocks_by_date[file_date_str] = stocks
                    logger.info(f"{file_date_str}: {len(stocks)}개 종목 추출")

            total_stocks = sum(len(stocks) for stocks in stocks_by_date.values())
            logger.info(f"신호 로그에서 총 {total_stocks}개 종목 추출")

        except Exception as e:
            logger.error(f"신호 로그 파싱 실패: {e}")

        return stocks_by_date

    def _parse_stocks_from_log_file(self, log_file: Path, date_str: str) -> List[Dict]:
        """개별 로그 파일에서 종목 정보 추출"""
        stocks = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # "=== 종목코드 -" 패턴으로 종목 추출
            pattern = r'=== (\d{6}) -'
            matches = re.findall(pattern, content)

            for stock_code in set(matches):  # 중복 제거
                stocks.append({
                    'stock_code': stock_code,
                    'stock_name': f"종목_{stock_code}",
                    'selection_date': date_str,
                    'selection_reason': 'from_log'
                })

        except Exception as e:
            logger.error(f"로그 파일 파싱 실패 ({log_file}): {e}")

        return stocks

    def collect_daily_data(self, stock_code: str, days: int = 60) -> Optional[pd.DataFrame]:
        """일봉 데이터 수집 (캐시 우선, 없으면 API 호출)"""
        cache_file = self.daily_cache_dir / f"{stock_code}_daily.pkl"

        # 1. 캐시 확인
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)

                # 한국투자증권 API 형태인지 확인
                if isinstance(cached_data, pd.DataFrame) and 'stck_bsop_date' in cached_data.columns:
                    # 컬럼명 변환
                    daily_data = cached_data.rename(columns={
                        'stck_bsop_date': 'date',
                        'stck_clpr': 'close',
                        'stck_oprc': 'open',
                        'stck_hgpr': 'high',
                        'stck_lwpr': 'low',
                        'acml_vol': 'volume'
                    })

                    # 데이터 타입 변환
                    numeric_cols = ['close', 'open', 'high', 'low', 'volume']
                    for col in numeric_cols:
                        if col in daily_data.columns:
                            daily_data[col] = pd.to_numeric(daily_data[col], errors='coerce')

                    # 날짜 인덱스 설정
                    daily_data['date'] = pd.to_datetime(daily_data['date'], format='%Y%m%d')
                    daily_data = daily_data.set_index('date').sort_index()

                    # 데이터가 충분한지 확인
                    if len(daily_data) >= 10:
                        logger.info(f"[{stock_code}] 캐시된 일봉 데이터 사용: {len(daily_data)}일")
                        return daily_data

            except Exception as e:
                logger.warning(f"[{stock_code}] 일봉 캐시 로드 실패: {e}")

        # 2. API 호출
        try:
            if not self.api_manager:
                logger.warning(f"[{stock_code}] API 매니저가 없습니다. 캐시된 데이터만 사용 가능합니다.")
                return None

            logger.info(f"[{stock_code}] API로 일봉 데이터 수집 중...")

            api_data = self.api_manager.get_daily_data(stock_code, days)

            if api_data is None or api_data.empty:
                logger.warning(f"[{stock_code}] API에서 일봉 데이터를 가져올 수 없습니다.")
                return None

            # 캐시 저장
            try:
                with open(cache_file, 'wb') as f:
                    pickle.dump(api_data, f)
                logger.info(f"[{stock_code}] 일봉 데이터를 캐시에 저장했습니다.")
            except Exception as e:
                logger.warning(f"[{stock_code}] 일봉 캐시 저장 실패: {e}")

            # 데이터 변환 후 반환
            if 'stck_bsop_date' in api_data.columns:
                daily_data = api_data.rename(columns={
                    'stck_bsop_date': 'date',
                    'stck_clpr': 'close',
                    'stck_oprc': 'open',
                    'stck_hgpr': 'high',
                    'stck_lwpr': 'low',
                    'acml_vol': 'volume'
                })

                numeric_cols = ['close', 'open', 'high', 'low', 'volume']
                for col in numeric_cols:
                    if col in daily_data.columns:
                        daily_data[col] = pd.to_numeric(daily_data[col], errors='coerce')

                daily_data['date'] = pd.to_datetime(daily_data['date'], format='%Y%m%d')
                daily_data = daily_data.set_index('date').sort_index()

                logger.info(f"[{stock_code}] API 일봉 데이터 수집 완료: {len(daily_data)}일")
                return daily_data

        except Exception as e:
            logger.error(f"[{stock_code}] API 일봉 데이터 수집 실패: {e}")

        return None

    def collect_minute_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """분봉 데이터 수집 (캐시 우선, 없으면 API 호출)"""
        cache_file = self.minute_cache_dir / f"{stock_code}_{date_str}.pkl"

        # 1. 캐시 확인
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)

                if isinstance(cached_data, pd.DataFrame) and len(cached_data) > 0:
                    logger.info(f"[{stock_code}] {date_str} 캐시된 분봉 데이터 사용: {len(cached_data)}분")
                    return cached_data

            except Exception as e:
                logger.warning(f"[{stock_code}] {date_str} 분봉 캐시 로드 실패: {e}")

        # 2. API 호출
        try:
            if not self.api_manager:
                logger.warning(f"[{stock_code}] {date_str} API 매니저가 없습니다. 캐시된 데이터만 사용 가능합니다.")
                return None

            logger.info(f"[{stock_code}] {date_str} API로 분봉 데이터 수집 중...")

            # 1분봉 데이터 수집
            api_data = self.api_manager.get_minute_data(stock_code, date_str)

            if api_data is None or api_data.empty:
                logger.warning(f"[{stock_code}] {date_str} API에서 분봉 데이터를 가져올 수 없습니다.")
                return None

            # 캐시 저장
            try:
                with open(cache_file, 'wb') as f:
                    pickle.dump(api_data, f)
                logger.info(f"[{stock_code}] {date_str} 분봉 데이터를 캐시에 저장했습니다.")
            except Exception as e:
                logger.warning(f"[{stock_code}] {date_str} 분봉 캐시 저장 실패: {e}")

            logger.info(f"[{stock_code}] {date_str} API 분봉 데이터 수집 완료: {len(api_data)}분")
            return api_data

        except Exception as e:
            logger.error(f"[{stock_code}] {date_str} API 분봉 데이터 수집 실패: {e}")

        return None

    def collect_complete_dataset(self, start_date: str, end_date: str) -> Dict[str, Dict]:
        """완전한 데이터셋 수집 (분봉 + 일봉)"""
        logger.info(f"=== 완전한 데이터셋 수집: {start_date} ~ {end_date} ===")

        # 1. 후보 종목 조회
        stocks_by_date = self.get_candidate_stocks_by_date_range(start_date, end_date)

        if not stocks_by_date:
            logger.warning("수집할 종목이 없습니다.")
            return {}

        # 2. 모든 종목 리스트 생성
        all_stocks = set()
        for date_stocks in stocks_by_date.values():
            all_stocks.update(stock['stock_code'] for stock in date_stocks)

        logger.info(f"총 {len(all_stocks)}개의 고유 종목 발견")

        # 3. 데이터 수집 결과
        dataset = {}

        for date_str, date_stocks in stocks_by_date.items():
            logger.info(f"\n=== {date_str} 데이터 수집 ({len(date_stocks)}개 종목) ===")

            dataset[date_str] = {
                'stocks': date_stocks,
                'data': {}
            }

            for stock_info in date_stocks:
                stock_code = stock_info['stock_code']
                logger.info(f"[{stock_code}] 데이터 수집 중...")

                stock_data = {
                    'stock_info': stock_info,
                    'daily_data': None,
                    'minute_data': None,
                    'complete': False
                }

                # 일봉 데이터 수집
                daily_data = self.collect_daily_data(stock_code)
                if daily_data is not None:
                    stock_data['daily_data'] = daily_data
                    logger.info(f"[{stock_code}] ✅ 일봉 데이터 수집 완료")
                else:
                    logger.warning(f"[{stock_code}] ❌ 일봉 데이터 수집 실패")

                # 분봉 데이터 수집
                minute_data = self.collect_minute_data(stock_code, date_str)
                if minute_data is not None:
                    stock_data['minute_data'] = minute_data
                    logger.info(f"[{stock_code}] ✅ 분봉 데이터 수집 완료")
                else:
                    logger.warning(f"[{stock_code}] ❌ 분봉 데이터 수집 실패")

                # 완전성 체크
                stock_data['complete'] = (stock_data['daily_data'] is not None and
                                        stock_data['minute_data'] is not None)

                dataset[date_str]['data'][stock_code] = stock_data

                if stock_data['complete']:
                    logger.info(f"[{stock_code}] ✅ 완전한 데이터셋 수집 완료")
                else:
                    logger.warning(f"[{stock_code}] ⚠️ 불완전한 데이터셋")

        # 4. 수집 결과 요약
        self._print_collection_summary(dataset)

        return dataset

    def _print_collection_summary(self, dataset: Dict[str, Dict]):
        """데이터 수집 결과 요약"""
        logger.info(f"\n{'='*60}")
        logger.info("📊 데이터 수집 결과 요약")
        logger.info(f"{'='*60}")

        total_stocks = 0
        complete_stocks = 0
        daily_only = 0
        minute_only = 0
        no_data = 0

        for date_str, date_data in dataset.items():
            date_total = len(date_data['data'])
            date_complete = sum(1 for stock_data in date_data['data'].values() if stock_data['complete'])
            date_daily_only = sum(1 for stock_data in date_data['data'].values()
                                if stock_data['daily_data'] is not None and stock_data['minute_data'] is None)
            date_minute_only = sum(1 for stock_data in date_data['data'].values()
                                 if stock_data['daily_data'] is None and stock_data['minute_data'] is not None)
            date_no_data = sum(1 for stock_data in date_data['data'].values()
                             if stock_data['daily_data'] is None and stock_data['minute_data'] is None)

            logger.info(f"{date_str}: 전체 {date_total}개, 완전 {date_complete}개, "
                       f"일봉만 {date_daily_only}개, 분봉만 {date_minute_only}개, 없음 {date_no_data}개")

            total_stocks += date_total
            complete_stocks += date_complete
            daily_only += date_daily_only
            minute_only += date_minute_only
            no_data += date_no_data

        logger.info(f"{'-'*60}")
        logger.info(f"📈 전체 집계:")
        logger.info(f"   총 종목: {total_stocks}개")
        logger.info(f"   완전한 데이터: {complete_stocks}개 ({complete_stocks/total_stocks*100:.1f}%)")
        logger.info(f"   일봉만: {daily_only}개 ({daily_only/total_stocks*100:.1f}%)")
        logger.info(f"   분봉만: {minute_only}개 ({minute_only/total_stocks*100:.1f}%)")
        logger.info(f"   데이터 없음: {no_data}개 ({no_data/total_stocks*100:.1f}%)")
        logger.info(f"{'='*60}")

def main():
    """테스트 실행"""
    collector = AnalysisDataCollector()

    # 09/08-09/16 기간 데이터 수집 테스트
    dataset = collector.collect_complete_dataset("20250908", "20250916")

    print(f"\n수집된 날짜: {list(dataset.keys())}")

if __name__ == "__main__":
    main()