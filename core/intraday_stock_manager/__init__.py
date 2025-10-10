"""
장중 종목 선정 및 과거 분봉 데이터 관리

리팩토링된 모듈형 구조:
- StockRepository: 종목 저장소 관리
- DataValidator: 데이터 검증
- DataProvider: 데이터 조회/분석
- MinuteDataCollector: 분봉 데이터 수집
- IntradayStockManager: Facade 패턴으로 전체 조율
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open
from api.kis_chart_api import get_inquire_time_itemchartprice, get_div_code_for_stock
from api.kis_market_api import get_inquire_price
from core.realtime_data_logger import log_intraday_data
from core.dynamic_batch_calculator import DynamicBatchCalculator
from core.minute_data_collector import MinuteDataCollector

from .stock_data import StockMinuteData
from .stock_repository import StockRepository
from .data_validator import DataValidator
from .data_provider import DataProvider


# 하위 호환성을 위해 StockMinuteData를 최상위 레벨에서 노출
__all__ = ['IntradayStockManager', 'StockMinuteData']


logger = setup_logger(__name__)


class IntradayStockManager:
    """
    장중 종목 선정 및 과거 분봉 데이터 관리 클래스 (Facade)
    
    주요 기능:
    1. 조건검색으로 선정된 종목의 과거 분봉 데이터 수집
    2. 메모리에서 효율적인 데이터 관리
    3. 실시간 분봉 데이터 업데이트
    4. 데이터 분석을 위한 편의 함수 제공
    """
    
    def __init__(self, api_manager):
        """
        초기화
        
        Args:
            api_manager: KIS API 매니저 인스턴스
        """
        self.api_manager = api_manager
        self.logger = setup_logger(__name__)
        
        # 설정
        self.market_open_time = "090000"
        self.max_stocks = 80
        
        # 컴포넌트 초기화
        self.repository = StockRepository(max_stocks=self.max_stocks)
        self.collector = MinuteDataCollector()
        self.validator = DataValidator()
        self.provider = DataProvider(self.repository, self.collector)
        self.batch_calculator = DynamicBatchCalculator()
        
        # 하위 호환성을 위한 속성 (기존 코드에서 직접 접근하는 경우 대비)
        self._lock = self.repository._lock
        
        self.logger.info("🎯 장중 종목 관리자 초기화 완료 (모듈형 구조)")
    
    # ==================== 하위 호환성 속성 ====================
    
    @property
    def selected_stocks(self) -> Dict[str, StockMinuteData]:
        """하위 호환성: selected_stocks 직접 접근"""
        return self.repository._stocks
    
    @property
    def selection_history(self) -> List[Dict[str, Any]]:
        """하위 호환성: selection_history 직접 접근"""
        return self.repository._selection_history
    
    # ==================== 공개 API 메서드 ====================
    
    async def add_selected_stock(self, stock_code: str, stock_name: str, 
                                selection_reason: str = "") -> bool:
        """
        조건검색으로 선정된 종목 추가 (비동기)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            selection_reason: 선정 사유
            
        Returns:
            bool: 추가 성공 여부
        """
        try:
            current_time = now_kst()
            
            # 이미 존재하는 종목인지 확인
            if self.repository.exists(stock_code):
                return True
            
            # 최대 관리 종목 수 체크
            if self.repository.get_stock_count() >= self.max_stocks:
                self.logger.warning(f"⚠️ 최대 관리 종목 수({self.max_stocks})에 도달. 추가 불가")
                return False
            
            # 장 시간 체크
            if not is_market_open():
                self.logger.warning(f"⚠️ 장 시간이 아님. {stock_code} 추가 보류")
            
            # 종목 데이터 객체 생성
            stock_data = StockMinuteData(
                stock_code=stock_code,
                stock_name=stock_name,
                selected_time=current_time
            )
            
            # 저장소에 추가
            if not self.repository.add_stock(stock_data):
                return False
            
            # 선정 이력 기록
            self.repository.add_selection_history(
                stock_code, stock_name, current_time, selection_reason
            )
            
            # 과거 데이터 수집
            self.logger.info(f"📈 {stock_code} 과거 데이터 수집 시작... (선정시간: {current_time.strftime('%H:%M:%S')})")
            success = await self._collect_historical_data(stock_code)
            
            # 09:05 이전 선정이고 데이터 부족한 경우 플래그 설정
            if not success and (current_time.hour == 9 and current_time.minute < 5):
                self.logger.warning(f"⚠️ {stock_code} 09:05 이전 데이터 부족, batch_update에서 재시도 필요")
                self.repository.update_stock(stock_code, data_complete=False)
                success = True  # 종목은 추가하되 데이터는 나중에 재수집
            
            if success:
                return True
            else:
                # 데이터 수집 실패 시 종목 제거
                self.repository.remove_stock(stock_code)
                self.logger.error(f"❌ {stock_code} 과거 데이터 수집 실패로 종목 추가 취소")
                return False
        
        except Exception as e:
            # 오류 시 종목 제거
            self.repository.remove_stock(stock_code)
            self.logger.error(f"❌ {stock_code} 종목 추가 오류: {e}")
            return False
    
    async def _collect_historical_data(self, stock_code: str) -> bool:
        """
        당일 08:00부터 선정시점까지의 전체 분봉 데이터 수집 (래퍼 함수)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 수집 성공 여부
        """
        try:
            stock_data = self.repository.get_stock(stock_code)
            if stock_data is None:
                return False
            
            selected_time = stock_data.selected_time
            
            # 재수집기를 사용하여 전체 과거 데이터 수집
            filtered_data = await self.collector.collect_full_historical_data(stock_code, selected_time)
            
            if filtered_data is None or filtered_data.empty:
                # 실패 시 폴백 방식으로 재시도
                return await self._collect_historical_data_fallback(stock_code)
            
            # 일봉 데이터 수집
            daily_data = await self.collector.collect_daily_data_for_ml(stock_code)
            
            # 저장소 업데이트
            self.repository.update_stock(
                stock_code,
                historical_data=filtered_data,
                daily_data=daily_data,
                data_complete=True,
                last_update=now_kst()
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 전체 거래시간 분봉 데이터 수집 오류: {e}")
            # 오류 시 기존 방식으로 폴백
            return await self._collect_historical_data_fallback(stock_code)
    
    async def _collect_historical_data_fallback(self, stock_code: str) -> bool:
        """
        과거 분봉 데이터 수집 폴백 함수 (기존 방식)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 수집 성공 여부
        """
        try:
            stock_data = self.repository.get_stock(stock_code)
            if stock_data is None:
                return False
            
            selected_time = stock_data.selected_time
            
            self.logger.warning(f"🔄 {stock_code} 폴백 방식으로 과거 분봉 데이터 수집")
            
            # 선정 시간까지의 당일 분봉 데이터 조회 (기존 방식)
            target_hour = selected_time.strftime("%H%M%S")
            
            # 당일분봉조회 API 사용 (최대 30건)
            div_code = get_div_code_for_stock(stock_code)
            
            result = get_inquire_time_itemchartprice(
                div_code=div_code,
                stock_code=stock_code,
                input_hour=target_hour,
                past_data_yn="Y"
            )
            
            if result is None:
                # 실패 시 1분씩 앞으로 이동하여 재시도
                try:
                    selected_time_dt = datetime.strptime(target_hour, "%H%M%S")
                    new_time_dt = selected_time_dt + timedelta(minutes=1)
                    new_target_hour = new_time_dt.strftime("%H%M%S")
                    
                    # 장 마감 시간(15:30) 초과 시 현재 시간으로 조정
                    if new_target_hour > "153000":
                        new_target_hour = now_kst().strftime("%H%M%S")
                    
                    self.logger.warning(f"🔄 {stock_code} 조회 실패, 시간 조정하여 재시도: {target_hour} → {new_target_hour}")
                    
                    # 조정된 시간으로 재시도
                    result = get_inquire_time_itemchartprice(
                        div_code=div_code,
                        stock_code=stock_code,
                        input_hour=new_target_hour,
                        past_data_yn="Y"
                    )
                    
                    if result is not None:
                        # 성공 시 selected_time 업데이트
                        new_selected_time = selected_time.replace(
                            hour=new_time_dt.hour,
                            minute=new_time_dt.minute,
                            second=new_time_dt.second
                        )
                        self.repository.update_stock(stock_code, selected_time=new_selected_time)
                        self.logger.info(f"✅ {stock_code} 시간 조정으로 조회 성공, selected_time 업데이트: {new_selected_time.strftime('%H:%M:%S')}")
                
                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 시간 조정 중 오류: {e}")
                
                if result is None:
                    self.logger.error(f"❌ {stock_code} 폴백 분봉 데이터 조회 실패 (시간 조정 후에도 실패)")
                    return False
            
            summary_df, chart_df = result
            
            if chart_df.empty:
                self.logger.warning(f"⚠️ {stock_code} 폴백 분봉 데이터 없음")
                # 빈 DataFrame이라도 저장
                self.repository.update_stock(stock_code, historical_data=pd.DataFrame(), data_complete=True)
                return True
            
            # 선정 시점 이전 데이터만 필터링
            if 'datetime' in chart_df.columns:
                # 선정 시간을 timezone-naive로 변환하여 pandas datetime64[ns]와 비교
                selected_time_naive = selected_time.replace(tzinfo=None)
                historical_data = chart_df[chart_df['datetime'] <= selected_time_naive].copy()
            else:
                historical_data = chart_df.copy()
            
            # 저장소 업데이트
            self.repository.update_stock(
                stock_code,
                historical_data=historical_data,
                data_complete=True,
                last_update=now_kst()
            )
            
            # 데이터 분석
            data_count = len(historical_data)
            if data_count > 0:
                start_time = historical_data.iloc[0].get('time', 'N/A') if 'time' in historical_data.columns else 'N/A'
                end_time = historical_data.iloc[-1].get('time', 'N/A') if 'time' in historical_data.columns else 'N/A'
                
                self.logger.info(f"✅ {stock_code} 폴백 분봉 수집 완료: {data_count}건 ({start_time} ~ {end_time})")
                self.logger.warning(f"⚠️ 제한된 데이터 범위 (API 제한으로 최대 30분봉)")
            else:
                self.logger.info(f"ℹ️ {stock_code} 폴백 방식도 데이터 없음")
            
            return True
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 폴백 분봉 데이터 수집 오류: {e}")
            return False
    
    async def update_realtime_data(self, stock_code: str) -> bool:
        """
        실시간 분봉 데이터 업데이트 (매수 판단용)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 업데이트 성공 여부
        """
        try:
            stock_data = self.repository.get_stock(stock_code)
            if stock_data is None:
                return False
            
            # 1. 현재 보유한 전체 데이터 확인 (historical + realtime)
            combined_data = self.provider.get_combined_chart_data(stock_code)
            
            # 2. 08-09시부터 데이터가 충분한지 체크
            if not self.validator.check_sufficient_base_data(combined_data, stock_code):
                # 기본 데이터가 부족하면 전체 재수집
                self.logger.warning(f"⚠️ {stock_code} 기본 데이터 부족, 전체 재수집 시도")
                return await self._collect_historical_data(stock_code)
            
            # 3. 최신 분봉 1개만 수집
            current_time = now_kst()
            latest_minute_data = await self._get_latest_minute_bar(stock_code, current_time)
            
            if latest_minute_data is None:
                # 장초반 구간에서 실시간 업데이트 실패 시 전체 재수집 시도
                current_hour = current_time.strftime("%H%M")
                if current_hour <= "0915":  # 09:15 이전까지 확장
                    self.logger.warning(f"⚠️ {stock_code} 장초반 실시간 업데이트 실패, 전체 재수집 시도")
                    return await self._collect_historical_data(stock_code)
                else:
                    # 장초반이 아니면 최신 데이터 수집 실패 - 기존 데이터 유지
                    self.logger.debug(f"📊 {stock_code} 최신 분봉 수집 실패, 기존 데이터 유지")
                    return True
            
            # 4. 기존 realtime_data에 최신 데이터 추가/업데이트
            current_realtime = stock_data.realtime_data.copy()
            
            # 새로운 데이터를 realtime_data에 추가
            if current_realtime.empty:
                updated_realtime = latest_minute_data
            else:
                # 중복 제거하면서 병합 (최신 데이터 우선)
                updated_realtime = pd.concat([current_realtime, latest_minute_data], ignore_index=True)
                if 'datetime' in updated_realtime.columns:
                    # keep='last': 동일 시간이면 최신 데이터 유지
                    updated_realtime = updated_realtime.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime').reset_index(drop=True)
                elif 'time' in updated_realtime.columns:
                    updated_realtime = updated_realtime.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
            
            # 저장소 업데이트
            self.repository.update_stock(
                stock_code,
                realtime_data=updated_realtime,
                last_update=current_time
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 실시간 분봉 업데이트 오류: {e}")
            return False
    
    async def _get_latest_minute_bar(self, stock_code: str, current_time: datetime) -> Optional[pd.DataFrame]:
        """
        완성된 최신 분봉 1개 수집 (미완성 봉 제외)
        
        Args:
            stock_code: 종목코드
            current_time: 현재 시간
            
        Returns:
            pd.DataFrame: 완성된 최신 분봉 1개 또는 None
        """
        try:
            # 완성된 마지막 분봉 시간 계산
            current_minute_start = current_time.replace(second=0, microsecond=0)
            last_completed_minute = current_minute_start - timedelta(minutes=1)
            target_hour = last_completed_minute.strftime("%H%M%S")
            
            # 분봉 API로 완성된 데이터 조회
            div_code = get_div_code_for_stock(stock_code)
            
            result = get_inquire_time_itemchartprice(
                div_code=div_code,
                stock_code=stock_code,
                input_hour=target_hour,
                past_data_yn="N"  # 최신 데이터만
            )
            
            if result is None:
                return None
            
            summary_df, chart_df = result
            
            if chart_df.empty:
                return None
            
            # 요청한 시간의 완성된 분봉 데이터만 선택
            latest_data = chart_df.tail(1).copy()
            
            return latest_data
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 최신 분봉 수집 오류: {e}")
            return None
    
    async def batch_update_realtime_data(self):
        """모든 관리 종목의 실시간 데이터 일괄 업데이트 (분봉 + 현재가)"""
        try:
            # 15:30 장 마감 시 메모리 데이터 자동 저장
            current_time = now_kst()
            if current_time.hour == 15 and current_time.minute == 30:
                if not hasattr(self, '_data_saved_today'):
                    self._save_minute_data_to_file()
                    self._data_saved_today = True  # 하루에 한 번만 저장
            
            stock_codes = self.repository.get_all_stock_codes()
            
            if not stock_codes:
                return
            
            # data_complete = False인 종목 재수집 (09:05 이전 선정 종목)
            incomplete_stocks = []
            for code in stock_codes:
                stock_data = self.repository.get_stock(code)
                if stock_data and not stock_data.data_complete:
                    incomplete_stocks.append(code)
            
            if incomplete_stocks:
                self.logger.info(f"🔄 미완성 데이터 재수집 시작: {len(incomplete_stocks)}개 종목")
                for stock_code in incomplete_stocks:
                    try:
                        success = await self._collect_historical_data(stock_code)
                        if success:
                            self.logger.info(f"✅ {stock_code} 미완성 데이터 재수집 성공")
                        else:
                            self.logger.warning(f"⚠️ {stock_code} 미완성 데이터 재수집 실패")
                    except Exception as e:
                        self.logger.error(f"❌ {stock_code} 재수집 오류: {e}")
            
            # 데이터 품질 모니터링 초기화
            total_stocks = len(stock_codes)
            successful_minute_updates = 0
            successful_price_updates = 0
            failed_updates = 0
            quality_issues = []
            
            # 동적 배치 크기 계산
            batch_size, batch_delay = self.batch_calculator.calculate_optimal_batch(total_stocks)
            
            for i in range(0, len(stock_codes), batch_size):
                batch = stock_codes[i:i + batch_size]
                
                # 분봉 데이터와 현재가 정보를 동시에 업데이트
                minute_tasks = [self.update_realtime_data(code) for code in batch]
                price_tasks = [self._update_current_price_data(code) for code in batch]
                
                # 분봉 데이터 업데이트
                minute_results = await asyncio.gather(*minute_tasks, return_exceptions=True)
                
                # 현재가 데이터 업데이트 (분봉 업데이트와 독립적으로)
                price_results = await asyncio.gather(*price_tasks, return_exceptions=True)
                
                # 배치 결과 품질 검사
                for j, (minute_result, price_result) in enumerate(zip(minute_results, price_results)):
                    stock_code = batch[j]
                    
                    # 종목명 가져오기
                    stock_data = self.repository.get_stock(stock_code)
                    stock_name = stock_data.stock_name if stock_data else None
                    
                    # 분봉 데이터 결과 처리
                    if isinstance(minute_result, Exception):
                        failed_updates += 1
                        quality_issues.append(f"{stock_code}: 분봉 업데이트 실패 - {str(minute_result)[:50]}")
                    else:
                        successful_minute_updates += 1
                        # 데이터 품질 검사
                        if stock_data:
                            all_data = pd.concat([stock_data.historical_data, stock_data.realtime_data], ignore_index=True)
                            quality_check = self.validator.check_data_quality(stock_code, all_data)
                            if quality_check['has_issues']:
                                quality_issues.extend([f"{stock_code}: {issue}" for issue in quality_check['issues']])
                                
                                # 분봉 누락 감지 시 누락된 분봉만 재수집
                                for issue in quality_check['issues']:
                                    if '분봉 누락' in issue:
                                        self.logger.warning(f"⚠️ {stock_code} 분봉 누락 감지, 재수집 시도: {issue}")
                                        try:
                                            # 비동기 재수집 스케줄링
                                            asyncio.create_task(self._recollect_missing_bars_if_needed(stock_code, quality_check))
                                        except Exception as retry_err:
                                            self.logger.error(f"❌ {stock_code} 재수집 스케줄링 실패: {retry_err}")
                                        break
                    
                    # 현재가 데이터 결과 처리
                    if isinstance(price_result, Exception):
                        quality_issues.append(f"{stock_code}: 현재가 업데이트 실패 - {str(price_result)[:30]}")
                    else:
                        successful_price_updates += 1
                    
                    # 실시간 데이터 로깅 (분봉 또는 현재가 업데이트 성공 시)
                    if stock_name and (not isinstance(minute_result, Exception) or not isinstance(price_result, Exception)):
                        try:
                            # 분봉 데이터 준비
                            minute_data = None
                            if not isinstance(minute_result, Exception) and stock_data:
                                realtime_data = stock_data.realtime_data
                                if realtime_data is not None and not realtime_data.empty:
                                    minute_data = realtime_data.tail(3)
                            
                            # 현재가 데이터 준비
                            price_data = None
                            if not isinstance(price_result, Exception) and stock_data:
                                current_price_info = stock_data.current_price_info
                                if current_price_info:
                                    price_data = {
                                        'current_price': current_price_info.get('current_price', 0),
                                        'change_rate': current_price_info.get('change_rate', 0),
                                        'volume': current_price_info.get('volume', 0),
                                        'high_price': current_price_info.get('high_price', 0),
                                        'low_price': current_price_info.get('low_price', 0),
                                        'open_price': current_price_info.get('open_price', 0)
                                    }
                            
                            # 실시간 데이터 로깅 호출
                            log_intraday_data(stock_code, stock_name, minute_data, price_data, None)
                        
                        except Exception:
                            # 로깅 오류가 메인 로직에 영향을 주지 않도록 조용히 처리
                            pass
                
                # 동적 배치 지연 시간 적용 (API 제한 준수)
                if i + batch_size < len(stock_codes):
                    await asyncio.sleep(batch_delay)
            
            # 데이터 품질 리포트
            minute_success_rate = (successful_minute_updates / total_stocks) * 100 if total_stocks > 0 else 0
            price_success_rate = (successful_price_updates / total_stocks) * 100 if total_stocks > 0 else 0
            
            if minute_success_rate < 90 or price_success_rate < 80:  # 성공률 기준
                self.logger.warning(f"⚠️ 실시간 데이터 품질 경고: 분봉 {minute_success_rate:.1f}% ({successful_minute_updates}/{total_stocks}), "
                                  f"현재가 {price_success_rate:.1f}% ({successful_price_updates}/{total_stocks})")
            
            if quality_issues:
                # 품질 문제가 5개 이상이면 상위 5개만 로깅
                issues_to_log = quality_issues[:5]
                self.logger.warning(f"🔍 데이터 품질 이슈 {len(quality_issues)}건: {'; '.join(issues_to_log)}")
                if len(quality_issues) > 5:
                    self.logger.warning(f"   (총 {len(quality_issues)}건 중 상위 5건만 표시)")
            else:
                self.logger.debug(f"✅ 실시간 데이터 업데이트 완료: 분봉 {successful_minute_updates}/{total_stocks} ({minute_success_rate:.1f}%), "
                                f"현재가 {successful_price_updates}/{total_stocks} ({price_success_rate:.1f}%)")
        
        except Exception as e:
            self.logger.error(f"❌ 실시간 데이터 일괄 업데이트 오류: {e}")
    
    async def _recollect_missing_bars_if_needed(self, stock_code: str, quality_check: dict) -> bool:
        """
        품질 검사 결과에서 누락된 분봉이 있으면 재수집
        
        Args:
            stock_code: 종목코드
            quality_check: 품질 검사 결과
            
        Returns:
            bool: 재수집 성공 여부
        """
        try:
            missing_times = quality_check.get('missing_times', [])
            
            if not missing_times:
                return True
            
            # 누락이 많으면 (10개 이상) 전체 재수집
            if len(missing_times) > 10:
                self.logger.warning(f"⚠️ {stock_code} 누락 분봉 많음({len(missing_times)}개), 전체 재수집")
                return await self._collect_historical_data(stock_code)
            
            # 적은 누락은 해당 분봉만 재수집
            new_data = await self.collector.collect_missing_minute_bars(stock_code, missing_times)
            
            if new_data is None or new_data.empty:
                return False
            
            # 수집된 데이터를 realtime_data에 병합
            stock_data = self.repository.get_stock(stock_code)
            if stock_data:
                current_realtime = stock_data.realtime_data.copy()
                updated_realtime = self.collector.merge_minute_data(current_realtime, new_data)
                self.repository.update_stock(
                    stock_code,
                    realtime_data=updated_realtime,
                    last_update=now_kst()
                )
            
            return True
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 누락 분봉 재수집 판단 오류: {e}")
            return False
    
    async def _update_current_price_data(self, stock_code: str) -> bool:
        """
        종목별 현재가 정보 업데이트 (매도 판단용)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 업데이트 성공 여부
        """
        try:
            current_price_info = self.get_current_price_for_sell(stock_code)
            
            if current_price_info is None:
                return False
            
            # 저장소 업데이트
            self.repository.update_stock(stock_code, current_price_info=current_price_info)
            
            return True
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 현재가 정보 업데이트 오류: {e}")
            return False
    
    def get_current_price_for_sell(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        매도 판단용 실시간 현재가 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Dict: 현재가 정보 또는 None
        """
        try:
            # J (KRX) 시장으로 현재가 조회
            price_data = get_inquire_price(div_code="J", itm_no=stock_code)
            
            if price_data is None or price_data.empty:
                self.logger.debug(f"❌ {stock_code} 현재가 조회 실패 (매도용)")
                return None
            
            # 첫 번째 행의 데이터 추출
            row = price_data.iloc[0]
            
            # 주요 현재가 정보 추출
            current_price_info = {
                'stock_code': stock_code,
                'current_price': float(row.get('stck_prpr', 0)),  # 현재가
                'change_rate': float(row.get('prdy_ctrt', 0)),   # 전일대비율
                'change_price': float(row.get('prdy_vrss', 0)),  # 전일대비
                'volume': int(row.get('acml_vol', 0)),           # 누적거래량
                'high_price': float(row.get('stck_hgpr', 0)),    # 고가
                'low_price': float(row.get('stck_lwpr', 0)),     # 저가
                'open_price': float(row.get('stck_oprc', 0)),    # 시가
                'prev_close': float(row.get('stck_sdpr', 0)),    # 전일종가
                'market_cap': int(row.get('hts_avls', 0)),       # 시가총액
                'update_time': now_kst()
            }
            
            return current_price_info
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 매도용 현재가 조회 오류: {e}")
            return None
    
    def get_cached_current_price(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        캐시된 현재가 정보 조회 (매도 판단에서 사용)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Dict: 캐시된 현재가 정보 또는 None
        """
        try:
            stock_data = self.repository.get_stock(stock_code)
            return stock_data.current_price_info if stock_data else None
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 캐시된 현재가 조회 오류: {e}")
            return None
    
    def get_stock_data(self, stock_code: str) -> Optional[StockMinuteData]:
        """
        종목의 전체 데이터 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            StockMinuteData: 종목 데이터 또는 None
        """
        return self.repository.get_stock(stock_code)
    
    def get_combined_chart_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        종목의 당일 전체 차트 데이터 조회 (08:00~현재, 완성된 봉만)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 당일 전체 차트 데이터
        """
        return self.provider.get_combined_chart_data(stock_code)
    
    def get_combined_chart_data_with_realtime(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        종목의 당일 전체 차트 데이터 조회 (완성된 봉 + 실시간 진행중인 봉)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 당일 전체 차트 데이터 (실시간 포함)
        """
        return self.provider.get_combined_chart_data_with_realtime(stock_code)
    
    def get_stock_analysis(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        종목 분석 정보 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Dict: 분석 정보
        """
        return self.provider.get_stock_analysis(stock_code)
    
    def get_all_stocks_summary(self) -> Dict[str, Any]:
        """
        모든 관리 종목 요약 정보
        
        Returns:
            Dict: 전체 요약 정보
        """
        return self.provider.get_all_stocks_summary()
    
    def remove_stock(self, stock_code: str) -> bool:
        """
        종목 제거
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 제거 성공 여부
        """
        return self.repository.remove_stock(stock_code)
    
    def _save_minute_data_to_file(self):
        """
        메모리에 있는 모든 종목의 분봉 데이터를 텍스트 파일로 저장 (15:30 장 마감 시)
        """
        try:
            current_time = now_kst()
            filename = f"memory_minute_data_{current_time.strftime('%Y%m%d_%H%M%S')}.txt"
            
            stock_codes = self.repository.get_all_stock_codes()
            
            if not stock_codes:
                self.logger.info("💾 저장할 종목 없음")
                return
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"=" * 100 + "\n")
                f.write(f"메모리 분봉 데이터 덤프 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"=" * 100 + "\n\n")
                f.write(f"총 종목 수: {len(stock_codes)}개\n\n")
                
                for stock_code in stock_codes:
                    stock_data = self.repository.get_stock(stock_code)
                    if stock_data is None:
                        continue
                    
                    stock_name = stock_data.stock_name
                    selected_time = stock_data.selected_time.strftime('%H:%M:%S')
                    historical_data = stock_data.historical_data.copy() if not stock_data.historical_data.empty else pd.DataFrame()
                    realtime_data = stock_data.realtime_data.copy() if not stock_data.realtime_data.empty else pd.DataFrame()
                    
                    f.write(f"\n{'=' * 100}\n")
                    f.write(f"종목코드: {stock_code} | 종목명: {stock_name} | 선정시간: {selected_time}\n")
                    f.write(f"{'=' * 100}\n\n")
                    
                    # Historical Data
                    f.write(f"[Historical Data: {len(historical_data)}건]\n")
                    if not historical_data.empty:
                        f.write(historical_data.to_string(index=False) + "\n")
                    else:
                        f.write("데이터 없음\n")
                    
                    f.write(f"\n[Realtime Data: {len(realtime_data)}건]\n")
                    if not realtime_data.empty:
                        f.write(realtime_data.to_string(index=False) + "\n")
                    else:
                        f.write("데이터 없음\n")
                    
                    # Combined Data
                    combined_data = self.provider.get_combined_chart_data(stock_code)
                    f.write(f"\n[Combined Data (당일만): {len(combined_data) if combined_data is not None else 0}건]\n")
                    if combined_data is not None and not combined_data.empty:
                        f.write(combined_data.to_string(index=False) + "\n")
                    else:
                        f.write("데이터 없음\n")
            
            self.logger.info(f"💾 메모리 분봉 데이터 저장 완료: {filename} ({len(stock_codes)}개 종목)")
        
        except Exception as e:
            self.logger.error(f"❌ 메모리 분봉 데이터 저장 실패: {e}")

