"""
데이터 수집 자동화 스크립트
더 많은 기간과 종목의 데이터를 수집하여 분석 품질 향상
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import pickle
import json
import logging
from typing import List, Dict, Optional
import time

from api.kis_market_api import get_inquire_daily_itemchartprice
from utils.logger import setup_logger
from utils.korean_time import now_kst

class DataCollectionAutomation:
    """데이터 수집 자동화"""
    
    def __init__(self, logger=None):
        self.logger = logger or setup_logger(__name__)
        self.cache_dir = Path("cache/daily_data")
        self.cache_dir.mkdir(exist_ok=True)
        
    def collect_extended_data(self, start_date: str, end_date: str, stock_codes: List[str]):
        """확장된 기간의 데이터 수집"""
        try:
            self.logger.info(f" 확장된 데이터 수집 시작: {start_date} ~ {end_date}")
            
            # 1. 날짜 범위 생성
            date_range = self._generate_date_range(start_date, end_date)
            self.logger.info(f"📅 수집할 날짜: {len(date_range)}개")
            
            # 2. 종목별 데이터 수집
            collected_data = {}
            for i, stock_code in enumerate(stock_codes, 1):
                self.logger.info(f" [{i}/{len(stock_codes)}] {stock_code} 데이터 수집 중...")
                
                try:
                    # 일봉 데이터 수집
                    daily_data = self._collect_daily_data(stock_code, date_range)
                    if daily_data is not None and not daily_data.empty:
                        collected_data[stock_code] = daily_data
                        self.logger.info(f"✅ {stock_code}: {len(daily_data)}개 일봉 데이터 수집 완료")
                    else:
                        self.logger.warning(f"⚠️ {stock_code}: 데이터 수집 실패")
                    
                    # API 호출 제한 고려
                    time.sleep(0.1)
                    
                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 데이터 수집 실패: {e}")
                    continue
            
            # 3. 데이터 저장
            self._save_collected_data(collected_data)
            
            # 4. 수집 통계 생성
            stats = self._generate_collection_stats(collected_data)
            self.logger.info(f" 수집 완료: {stats}")
            
            return collected_data
            
        except Exception as e:
            self.logger.error(f"데이터 수집 실패: {e}")
            return {}
    
    def _generate_date_range(self, start_date: str, end_date: str) -> List[str]:
        """날짜 범위 생성"""
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        
        date_range = []
        current_dt = start_dt
        
        while current_dt <= end_dt:
            # 주말 제외
            if current_dt.weekday() < 5:
                date_range.append(current_dt.strftime("%Y%m%d"))
            current_dt += timedelta(days=1)
        
        return date_range
    
    def _collect_daily_data(self, stock_code: str, date_range: List[str]) -> Optional[pd.DataFrame]:
        """종목별 일봉 데이터 수집"""
        try:
            all_data = []
            
            for date in date_range:
                try:
                    # API 호출
                    data = get_inquire_daily_itemchartprice(
                        stock_code=stock_code,
                        period_code="D",
                        adj_price="1",
                        start_date=date,
                        end_date=date
                    )
                    
                    if data and not data.empty:
                        all_data.append(data)
                    
                    # API 호출 제한
                    time.sleep(0.05)
                    
                except Exception as e:
                    self.logger.debug(f"날짜 {date} 데이터 수집 실패: {e}")
                    continue
            
            if not all_data:
                return None
            
            # 데이터 결합
            combined_data = pd.concat(all_data, ignore_index=True)
            combined_data = combined_data.drop_duplicates().sort_values('stck_bsop_date')
            
            return combined_data
            
        except Exception as e:
            self.logger.error(f"일봉 데이터 수집 실패 {stock_code}: {e}")
            return None
    
    def _save_collected_data(self, collected_data: Dict[str, pd.DataFrame]):
        """수집된 데이터 저장"""
        try:
            for stock_code, data in collected_data.items():
                file_path = self.cache_dir / f"{stock_code}_daily.pkl"
                with open(file_path, 'wb') as f:
                    pickle.dump(data, f)
            
            self.logger.info(f"💾 {len(collected_data)}개 종목 데이터 저장 완료")
            
        except Exception as e:
            self.logger.error(f"데이터 저장 실패: {e}")
    
    def _generate_collection_stats(self, collected_data: Dict[str, pd.DataFrame]) -> Dict:
        """수집 통계 생성"""
        stats = {
            'total_stocks': len(collected_data),
            'total_records': sum(len(data) for data in collected_data.values()),
            'avg_records_per_stock': 0,
            'date_range': {},
            'success_rate': 0
        }
        
        if collected_data:
            stats['avg_records_per_stock'] = stats['total_records'] / len(collected_data)
            
            # 날짜 범위 계산
            all_dates = set()
            for data in collected_data.values():
                if 'stck_bsop_date' in data.columns:
                    all_dates.update(data['stck_bsop_date'].astype(str))
            
            if all_dates:
                stats['date_range'] = {
                    'start': min(all_dates),
                    'end': max(all_dates),
                    'total_days': len(all_dates)
                }
        
        return stats
    
    def collect_market_data(self, start_date: str, end_date: str):
        """시장 전체 데이터 수집"""
        try:
            self.logger.info(" 시장 전체 데이터 수집 시작")
            
            # 1. 주요 종목 리스트 로드
            stock_codes = self._load_major_stocks()
            self.logger.info(f" 수집 대상 종목: {len(stock_codes)}개")
            
            # 2. 데이터 수집
            collected_data = self.collect_extended_data(start_date, end_date, stock_codes)
            
            # 3. 시장 지수 데이터 수집
            index_data = self._collect_index_data(start_date, end_date)
            
            # 4. 결과 저장
            self._save_market_data(collected_data, index_data)
            
            return collected_data, index_data
            
        except Exception as e:
            self.logger.error(f"시장 데이터 수집 실패: {e}")
            return {}, {}
    
    def _load_major_stocks(self) -> List[str]:
        """주요 종목 리스트 로드"""
        try:
            # 기존 종목 리스트 로드
            stock_list_file = Path("stock_list.json")
            if stock_list_file.exists():
                with open(stock_list_file, 'r', encoding='utf-8') as f:
                    stock_data = json.load(f)
                    return [stock['code'] for stock in stock_data if 'code' in stock]
            
            # 기본 종목 리스트
            return [
                "005930", "000660", "035420", "207940", "006400",  # 삼성전자, SK하이닉스, 네이버, 삼성바이오로직스, 삼성SDI
                "051910", "068270", "323410", "000270", "035720",  # LG화학, 셀트리온, 카카오뱅크, 기아, 카카오
                "066570", "003550", "017670", "096770", "018260",  # LG전자, LG, SK텔레콤, SK이노베이션, 삼성물산
                "034730", "003490", "015760", "000720", "012330",  # SK, 대우건설, 한국전력, 현대건설, 현대모비스
                "066970", "000810", "003410", "161890", "105560"   # 엘앤에프, 삼성화재, 신세계, 한화솔루션, KB금융
            ]
            
        except Exception as e:
            self.logger.error(f"종목 리스트 로드 실패: {e}")
            return []
    
    def _collect_index_data(self, start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
        """지수 데이터 수집"""
        try:
            index_codes = {
                "KOSPI": "0001",      # KOSPI
                "KOSDAQ": "1001",     # KOSDAQ
                "KOSPI200": "0002"    # KOSPI200
            }
            
            index_data = {}
            for name, code in index_codes.items():
                try:
                    data = get_inquire_daily_itemchartprice(
                        stock_code=code,
                        period_code="D",
                        adj_price="1",
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    if data is not None and not data.empty:
                        index_data[name] = data
                        self.logger.info(f"✅ {name} 지수 데이터 수집 완료: {len(data)}개")
                    
                    time.sleep(0.1)
                    
                except Exception as e:
                    self.logger.error(f"❌ {name} 지수 데이터 수집 실패: {e}")
                    continue
            
            return index_data
            
        except Exception as e:
            self.logger.error(f"지수 데이터 수집 실패: {e}")
            return {}
    
    def _save_market_data(self, stock_data: Dict[str, pd.DataFrame], index_data: Dict[str, pd.DataFrame]):
        """시장 데이터 저장"""
        try:
            # 종목 데이터 저장
            for stock_code, data in stock_data.items():
                file_path = self.cache_dir / f"{stock_code}_daily.pkl"
                with open(file_path, 'wb') as f:
                    pickle.dump(data, f)
            
            # 지수 데이터 저장
            index_dir = Path("cache/index_data")
            index_dir.mkdir(exist_ok=True)
            
            for index_name, data in index_data.items():
                file_path = index_dir / f"{index_name}_daily.pkl"
                with open(file_path, 'wb') as f:
                    pickle.dump(data, f)
            
            self.logger.info(f" 시장 데이터 저장 완료: {len(stock_data)}개 종목, {len(index_data)}개 지수")
            
        except Exception as e:
            self.logger.error(f"시장 데이터 저장 실패: {e}")


def main():
    """메인 실행 함수"""
    logger = setup_logger(__name__)
    
    # 데이터 수집 자동화 실행
    collector = DataCollectionAutomation(logger)
    
    # 1. 확장된 기간 데이터 수집 (3개월)
    start_date = "20240601"  # 6월 1일
    end_date = "20250917"    # 9월 17일
    
    logger.info(f" 확장된 데이터 수집 시작: {start_date} ~ {end_date}")
    
    # 2. 시장 전체 데이터 수집
    stock_data, index_data = collector.collect_market_data(start_date, end_date)
    
    # 3. 수집 결과 요약
    logger.info(" 수집 결과 요약:")
    logger.info(f"  - 종목 데이터: {len(stock_data)}개")
    logger.info(f"  - 지수 데이터: {len(index_data)}개")
    
    if stock_data:
        total_records = sum(len(data) for data in stock_data.values())
        logger.info(f"  - 총 레코드 수: {total_records:,}개")
        logger.info(f"  - 평균 레코드/종목: {total_records // len(stock_data):,}개")


if __name__ == "__main__":
    main()
