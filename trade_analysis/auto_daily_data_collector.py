"""
자동 일봉 데이터 수집기
분석에 필요한 종목의 일봉 데이터가 없으면 자동으로 수집
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime, timedelta
import logging
from pathlib import Path
import pickle
import json
import time
import re

from api.kis_market_api import get_inquire_daily_itemchartprice
from api.kis_auth import auth
from utils.logger import setup_logger
from utils.korean_time import now_kst

class AutoDailyDataCollector:
    """자동 일봉 데이터 수집기"""
    
    def __init__(self, logger=None):
        self.logger = logger or setup_logger(__name__)
        self.cache_dir = Path("cache/daily_data")
        self.cache_dir.mkdir(exist_ok=True)
        self.collected_count = 0
        self.failed_count = 0
        self.is_authenticated = False
        
    def collect_missing_daily_data(self, stock_codes: List[str], start_date: str = None, end_date: str = None) -> Dict[str, bool]:
        """누락된 일봉 데이터 수집"""
        try:
            # KIS 인증 확인 및 실행
            if not self._ensure_authenticated():
                self.logger.error("❌ KIS 인증 실패로 데이터 수집을 중단합니다.")
                return {}
            
            if start_date is None:
                start_date = "20240601"  # 6월 1일부터
            if end_date is None:
                end_date = now_kst().strftime("%Y%m%d")  # 오늘까지
            
            self.logger.info(f"🔍 누락된 일봉 데이터 수집 시작: {start_date} ~ {end_date}")
            self.logger.info(f"📊 대상 종목: {len(stock_codes)}개")
            
            # 1. 누락된 종목 확인
            missing_stocks = self._find_missing_stocks(stock_codes, start_date, end_date)
            self.logger.info(f"📋 누락된 종목: {len(missing_stocks)}개")
            
            if not missing_stocks:
                self.logger.info("✅ 모든 종목의 일봉 데이터가 존재합니다.")
                return {}
            
            # 2. 누락된 종목의 일봉 데이터 수집
            collection_results = {}
            for i, stock_code in enumerate(missing_stocks, 1):
                self.logger.info(f"📈 [{i}/{len(missing_stocks)}] {stock_code} 일봉 데이터 수집 중...")
                
                try:
                    success = self._collect_single_stock_daily_data(stock_code, start_date, end_date)
                    collection_results[stock_code] = success
                    
                    if success:
                        self.collected_count += 1
                        self.logger.info(f"✅ {stock_code} 수집 완료")
                    else:
                        self.failed_count += 1
                        self.logger.warning(f"⚠️ {stock_code} 수집 실패")
                    
                    # API 호출 제한 고려
                    time.sleep(0.1)
                    
                except Exception as e:
                    self.failed_count += 1
                    collection_results[stock_code] = False
                    self.logger.error(f"❌ {stock_code} 수집 실패: {e}")
                    continue
            
            # 3. 수집 결과 요약
            self._log_collection_summary(collection_results)
            
            return collection_results
            
        except Exception as e:
            self.logger.error(f"일봉 데이터 수집 실패: {e}")
            return {}
    
    def _find_missing_stocks(self, stock_codes: List[str], start_date: str, end_date: str) -> List[str]:
        """누락된 종목 찾기"""
        missing_stocks = []
        
        for stock_code in stock_codes:
            try:
                # 기존 일봉 데이터 확인
                daily_file = self.cache_dir / f"{stock_code}_daily.pkl"
                
                if not daily_file.exists():
                    missing_stocks.append(stock_code)
                    continue
                
                # 데이터 유효성 확인
                with open(daily_file, 'rb') as f:
                    data = pickle.load(f)
                
                if data is None or data.empty:
                    missing_stocks.append(stock_code)
                    continue
                
                # 날짜 범위 확인
                if 'stck_bsop_date' in data.columns:
                    data['date'] = pd.to_datetime(data['stck_bsop_date'])
                    min_date = data['date'].min()
                    max_date = data['date'].max()
                    
                    start_dt = pd.to_datetime(start_date)
                    end_dt = pd.to_datetime(end_date)
                    
                    # 필요한 날짜 범위가 포함되어 있는지 확인
                    if min_date > start_dt or max_date < end_dt:
                        missing_stocks.append(stock_code)
                        self.logger.debug(f"📅 {stock_code} 날짜 범위 부족: {min_date.date()} ~ {max_date.date()}")
                
            except Exception as e:
                self.logger.debug(f"📋 {stock_code} 데이터 확인 실패: {e}")
                missing_stocks.append(stock_code)
        
        return missing_stocks
    
    def _collect_single_stock_daily_data(self, stock_code: str, start_date: str, end_date: str) -> bool:
        """단일 종목 일봉 데이터 수집"""
        try:
            # API 호출 (output_dv="2"로 설정하여 전체 데이터 조회)
            data = get_inquire_daily_itemchartprice(
                itm_no=stock_code,
                period_code="D",
                adj_prc="1",
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                output_dv="2"  # 전체 데이터 조회
            )
            
            if data is None or data.empty:
                self.logger.debug(f"📊 {stock_code} API 응답 없음")
                return False
            
            # 데이터 정리
            cleaned_data = self._clean_daily_data(data)
            
            if cleaned_data is None or cleaned_data.empty:
                self.logger.debug(f"🧹 {stock_code} 데이터 정리 실패")
                return False
            
            # 데이터 저장
            daily_file = self.cache_dir / f"{stock_code}_daily.pkl"
            with open(daily_file, 'wb') as f:
                pickle.dump(cleaned_data, f)
            
            self.logger.debug(f"💾 {stock_code} 데이터 저장 완료: {len(cleaned_data)}건")
            return True
            
        except Exception as e:
            self.logger.debug(f"📈 {stock_code} 수집 실패: {e}")
            return False
    
    def _clean_daily_data(self, data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """일봉 데이터 정리"""
        try:
            if data is None or data.empty:
                return None
            
            # 필수 컬럼 확인
            required_columns = ['stck_bsop_date', 'stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'acml_vol']
            missing_columns = [col for col in required_columns if col not in data.columns]
            
            if missing_columns:
                self.logger.debug(f"📋 필수 컬럼 누락: {missing_columns}")
                return None
            
            # 데이터 타입 변환
            cleaned_data = data.copy()
            
            # 날짜 변환
            cleaned_data['date'] = pd.to_datetime(cleaned_data['stck_bsop_date'])
            
            # 가격 데이터 변환
            price_columns = ['stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr']
            for col in price_columns:
                cleaned_data[col] = pd.to_numeric(cleaned_data[col], errors='coerce')
            
            # 거래량 변환
            cleaned_data['acml_vol'] = pd.to_numeric(cleaned_data['acml_vol'], errors='coerce')
            
            # 컬럼명 정리
            cleaned_data = cleaned_data.rename(columns={
                'stck_clpr': 'close',
                'stck_oprc': 'open',
                'stck_hgpr': 'high',
                'stck_lwpr': 'low',
                'acml_vol': 'volume'
            })
            
            # 유효하지 않은 데이터 제거
            cleaned_data = cleaned_data.dropna(subset=['date', 'close', 'open', 'high', 'low', 'volume'])
            
            # 날짜순 정렬
            cleaned_data = cleaned_data.sort_values('date').reset_index(drop=True)
            
            # 중복 제거
            cleaned_data = cleaned_data.drop_duplicates(subset=['date']).reset_index(drop=True)
            
            return cleaned_data
            
        except Exception as e:
            self.logger.debug(f"🧹 데이터 정리 실패: {e}")
            return None
    
    def _log_collection_summary(self, collection_results: Dict[str, bool]):
        """수집 결과 요약 로그"""
        total_stocks = len(collection_results)
        successful_stocks = sum(collection_results.values())
        failed_stocks = total_stocks - successful_stocks
        
        self.logger.info("\n" + "="*60)
        self.logger.info("📊 일봉 데이터 수집 결과 요약")
        self.logger.info("="*60)
        self.logger.info(f"총 대상 종목: {total_stocks}개")
        self.logger.info(f"수집 성공: {successful_stocks}개")
        self.logger.info(f"수집 실패: {failed_stocks}개")
        self.logger.info(f"성공률: {successful_stocks/total_stocks*100:.1f}%")
        
        if failed_stocks > 0:
            self.logger.info("\n❌ 수집 실패한 종목:")
            for stock_code, success in collection_results.items():
                if not success:
                    self.logger.info(f"  - {stock_code}")
        
        self.logger.info("="*60)
    
    def _log_quality_report(self, quality_report: Dict[str, Dict]):
        """품질 보고서 로그 출력"""
        try:
            total_stocks = len(quality_report)
            ok_stocks = sum(1 for report in quality_report.values() if report['status'] == 'ok')
            missing_stocks = sum(1 for report in quality_report.values() if report['status'] == 'missing')
            error_stocks = sum(1 for report in quality_report.values() if report['status'] == 'error')
            
            self.logger.info("\n" + "="*60)
            self.logger.info("📊 데이터 품질 검증 결과")
            self.logger.info("="*60)
            self.logger.info(f"총 종목: {total_stocks}개")
            self.logger.info(f"정상: {ok_stocks}개")
            self.logger.info(f"누락: {missing_stocks}개")
            self.logger.info(f"오류: {error_stocks}개")
            
            if ok_stocks > 0:
                avg_quality = sum(report['quality_score'] for report in quality_report.values() 
                                if report['status'] == 'ok') / ok_stocks
                self.logger.info(f"평균 품질 점수: {avg_quality:.2f}")
            
            self.logger.info("="*60)
            
        except Exception as e:
            self.logger.error(f"품질 보고서 출력 실패: {e}")
    
    def _ensure_authenticated(self) -> bool:
        """KIS 인증 상태 확인 및 인증 실행"""
        try:
            if self.is_authenticated:
                return True
            
            self.logger.info("🔐 KIS API 인증 시작...")
            
            # KIS 인증 실행
            if auth():
                self.is_authenticated = True
                self.logger.info("✅ KIS API 인증 성공")
                return True
            else:
                self.logger.error("❌ KIS API 인증 실패")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ KIS 인증 오류: {e}")
            return False
    
    def collect_from_trade_logs(self, log_dir: str = "signal_replay_log") -> Dict[str, bool]:
        """거래 로그에서 종목 추출하여 일봉 데이터 수집"""
        try:
            self.logger.info("📋 거래 로그에서 종목 추출 중...")
            
            # 1. 거래 로그에서 종목 추출
            stock_codes = self._extract_stocks_from_logs(log_dir)
            self.logger.info(f"📊 추출된 종목: {len(stock_codes)}개")
            
            if not stock_codes:
                self.logger.warning("거래 로그에서 종목을 찾을 수 없습니다.")
                return {}
            
            # 2. 일봉 데이터 수집
            collection_results = self.collect_missing_daily_data(stock_codes)
            
            return collection_results
            
        except Exception as e:
            self.logger.error(f"거래 로그 기반 수집 실패: {e}")
            return {}
    
    def _extract_stocks_from_logs(self, log_dir: str) -> Set[str]:
        """거래 로그에서 종목코드 추출"""
        stock_codes = set()
        log_path = Path(log_dir)
        
        if not log_path.exists():
            self.logger.warning(f"로그 디렉토리가 존재하지 않습니다: {log_dir}")
            return stock_codes
        
        for log_file in log_path.glob("*.txt"):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 종목코드 추출 (=== 6자리숫자 - 패턴)
                matches = re.findall(r'=== (\d{6}) -', content)
                stock_codes.update(matches)
                
            except Exception as e:
                self.logger.debug(f"로그 파일 읽기 실패 {log_file.name}: {e}")
                continue
        
        return stock_codes
    
    def verify_data_quality(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """데이터 품질 검증"""
        try:
            self.logger.info("🔍 데이터 품질 검증 시작...")
            
            quality_report = {}
            
            for stock_code in stock_codes:
                try:
                    daily_file = self.cache_dir / f"{stock_code}_daily.pkl"
                    
                    if not daily_file.exists():
                        quality_report[stock_code] = {
                            'status': 'missing',
                            'records': 0,
                            'date_range': None,
                            'quality_score': 0.0
                        }
                        continue
                    
                    with open(daily_file, 'rb') as f:
                        data = pickle.load(f)
                    
                    if data is None or data.empty:
                        quality_report[stock_code] = {
                            'status': 'empty',
                            'records': 0,
                            'date_range': None,
                            'quality_score': 0.0
                        }
                        continue
                    
                    # 데이터 품질 평가
                    records = len(data)
                    date_range = None
                    quality_score = 0.0
                    
                    if 'date' in data.columns:
                        dates = pd.to_datetime(data['date'])
                        date_range = {
                            'start': dates.min().strftime('%Y-%m-%d'),
                            'end': dates.max().strftime('%Y-%m-%d'),
                            'days': len(dates.unique())
                        }
                        
                        # 품질 점수 계산
                        quality_score = min(1.0, records / 100)  # 100건 이상이면 1.0
                    
                    quality_report[stock_code] = {
                        'status': 'ok',
                        'records': records,
                        'date_range': date_range,
                        'quality_score': quality_score
                    }
                    
                except Exception as e:
                    quality_report[stock_code] = {
                        'status': 'error',
                        'records': 0,
                        'date_range': None,
                        'quality_score': 0.0,
                        'error': str(e)
                    }
            
            # 품질 보고서 출력
            self._log_quality_report(quality_report)
            
            return quality_report
            
        except Exception as e:
            self.logger.error(f"데이터 품질 검증 실패: {e}")
            return {}


def main():
    """메인 실행 함수"""
    logger = setup_logger(__name__)
    
    # 자동 일봉 데이터 수집기 실행
    collector = AutoDailyDataCollector(logger)
    
    # 1. 거래 로그에서 종목 추출하여 일봉 데이터 수집
    logger.info("🚀 자동 일봉 데이터 수집 시작")
    
    collection_results = collector.collect_from_trade_logs()
    
    if collection_results:
        # 2. 수집된 종목들의 데이터 품질 검증
        collected_stocks = [stock for stock, success in collection_results.items() if success]
        
        if collected_stocks:
            quality_report = collector.verify_data_quality(collected_stocks)
            
            # 3. 품질이 좋은 데이터만 필터링
            good_quality_stocks = [
                stock for stock, report in quality_report.items() 
                if report['status'] == 'ok' and report['quality_score'] > 0.5
            ]
            
            logger.info(f"✅ 품질이 좋은 데이터: {len(good_quality_stocks)}개 종목")
            
            # 4. 분석 가능한 종목 리스트 저장
            with open('analysis_ready_stocks.json', 'w', encoding='utf-8') as f:
                json.dump(good_quality_stocks, f, ensure_ascii=False, indent=2)
            
            logger.info("💾 분석 가능한 종목 리스트 저장 완료: analysis_ready_stocks.json")
    
    logger.info("🏁 자동 일봉 데이터 수집 완료")


if __name__ == "__main__":
    main()
