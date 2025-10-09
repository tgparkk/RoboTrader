"""
장중 종목 선정 및 과거 분봉 데이터 관리
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
from dataclasses import dataclass, field
import threading
from collections import defaultdict

from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open
from api.kis_chart_api import (
    get_inquire_time_itemchartprice,
    get_inquire_time_dailychartprice,
    get_full_trading_day_data_async,
    get_div_code_for_stock
)
from api.kis_market_api import get_inquire_daily_itemchartprice, get_inquire_price
from core.indicators.price_box import PriceBox
from core.realtime_data_logger import log_intraday_data
from core.realtime_candle_builder import get_realtime_candle_builder
from core.dynamic_batch_calculator import DynamicBatchCalculator


logger = setup_logger(__name__)


@dataclass
class StockMinuteData:
    """종목별 분봉 데이터 클래스"""
    stock_code: str
    stock_name: str
    selected_time: datetime
    historical_data: pd.DataFrame = field(default_factory=pd.DataFrame)  # 오늘 분봉 데이터
    realtime_data: pd.DataFrame = field(default_factory=pd.DataFrame)    # 실시간 분봉 데이터
    daily_data: pd.DataFrame = field(default_factory=pd.DataFrame)       # 과거 29일 일봉 데이터 (가격박스용)
    current_price_info: Optional[Dict[str, Any]] = None                  # 매도용 실시간 현재가 정보
    last_update: Optional[datetime] = None
    data_complete: bool = False
    
    def __post_init__(self):
        """초기화 후 처리"""
        if self.last_update is None:
            self.last_update = self.selected_time


class IntradayStockManager:
    """
    장중 종목 선정 및 과거 분봉 데이터 관리 클래스
    
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
        
        # 메모리 저장소
        self.selected_stocks: Dict[str, StockMinuteData] = {}  # stock_code -> StockMinuteData
        self.selection_history: List[Dict[str, Any]] = []  # 선정 이력
        
        # 설정
        self.market_open_time = "090000"  # 장 시작 시간
        self.max_stocks = 80  # 최대 관리 종목 수

        # 동기화
        self._lock = threading.RLock()

        # 🆕 동적 배치 계산기
        self.batch_calculator = DynamicBatchCalculator()

        self.logger.info("🎯 장중 종목 관리자 초기화 완료")
    
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
            with self._lock:
                current_time = now_kst()
                
                # 이미 존재하는 종목인지 확인
                if stock_code in self.selected_stocks:
                    #self.logger.debug(f"📊 {stock_code}({stock_name}): 이미 관리 중인 종목")
                    return True
                
                # 최대 관리 종목 수 체크
                if len(self.selected_stocks) >= self.max_stocks:
                    self.logger.warning(f"⚠️ 최대 관리 종목 수({self.max_stocks})에 도달. 추가 불가")
                    return False
                
                # 장 시간 체크
                if not is_market_open():
                    self.logger.warning(f"⚠️ 장 시간이 아님. {stock_code} 추가 보류")
                    #return False
                
                # 종목 데이터 객체 생성
                stock_data = StockMinuteData(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selected_time=current_time
                )
                
                # 메모리에 추가
                self.selected_stocks[stock_code] = stock_data
                
                # 선정 이력 기록
                self.selection_history.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'selected_time': current_time,
                    'selection_reason': selection_reason,
                    'market_time': current_time.strftime('%H:%M:%S')
                })
                
                #self.logger.debug(f"✅ {stock_code}({stock_name}) 장중 선정 완료 - "
                #               f"시간: {current_time.strftime('%H:%M:%S')}")
            
            # 🔥 과거 데이터 수집 (09:05 이전에도 시도)
            current_time = now_kst()
            self.logger.info(f"📈 {stock_code} 과거 데이터 수집 시작... (선정시간: {current_time.strftime('%H:%M:%S')})")
            success = await self._collect_historical_data(stock_code)

            # 09:05 이전 선정이고 데이터 부족한 경우 플래그 설정
            if not success and (current_time.hour == 9 and current_time.minute < 5):
                self.logger.warning(f"⚠️ {stock_code} 09:05 이전 데이터 부족, batch_update에서 재시도 필요")
                # data_complete = False로 설정하여 나중에 재시도
                with self._lock:
                    if stock_code in self.selected_stocks:
                        self.selected_stocks[stock_code].data_complete = False
                success = True  # 종목은 추가하되 데이터는 나중에 재수집
            
            if success:
                #self.logger.info(f"✅ {stock_code} 과거 데이터 수집 완료 및 종목 추가 성공")
                return True
            else:
                # 데이터 수집 실패 시 종목 제거
                with self._lock:
                    if stock_code in self.selected_stocks:
                        del self.selected_stocks[stock_code]
                self.logger.error(f"❌ {stock_code} 과거 데이터 수집 실패로 종목 추가 취소")
                return False
                
        except Exception as e:
            # 오류 시 종목 제거
            with self._lock:
                if stock_code in self.selected_stocks:
                    del self.selected_stocks[stock_code]
            self.logger.error(f"❌ {stock_code} 종목 추가 오류: {e}")
            return False
    
    async def _collect_historical_data(self, stock_code: str) -> bool:
        """
        당일 08:00부터 선정시점까지의 전체 분봉 데이터 수집
        
        장중에 종목이 선정되었을 때 08:00부터 선정시점까지의 모든 분봉 데이터를 수집합니다.
        NXT 거래소 종목(08:30~15:30)과 KRX 종목(09:00~15:30) 모두 지원.
        이를 통해 시뮬레이션과 동일한 조건의 데이터로 신호를 생성할 수 있습니다.
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 수집 성공 여부
        """
        try:
            with self._lock:
                if stock_code not in self.selected_stocks:
                    return False
                    
                stock_data = self.selected_stocks[stock_code]
                selected_time = stock_data.selected_time
            
            self.logger.info(f"📈 {stock_code} 전체 거래시간 분봉 데이터 수집 시작")
            self.logger.info(f"   선정 시간: {selected_time.strftime('%H:%M:%S')}")
            
            # 당일 09:00부터 선정시점까지의 전체 거래시간 데이터 수집
            target_date = selected_time.strftime("%Y%m%d")
            target_hour = selected_time.strftime("%H%M%S")

            # 🔥 중요: 미래 데이터 수집 방지 - 선정 시점까지만 수집
            # (이전 로직: 09:10 이전 선정 시 09:15까지 수집 → 미래 데이터 포함!)
            self.logger.info(f"📈 {stock_code} 과거 데이터 수집: 09:00 ~ {selected_time.strftime('%H:%M:%S')}")

            historical_data = await get_full_trading_day_data_async(
                stock_code=stock_code,
                target_date=target_date,
                selected_time=target_hour,  # 선정 시점까지만!
                start_time="090000"  # 09:00부터 시작 (KRX 정규장만)
            )
            
            if historical_data is None or historical_data.empty:
                # 실패 시 1분씩 앞으로 이동하여 재시도
                from datetime import datetime, timedelta
                try:
                    selected_time_dt = datetime.strptime(target_hour, "%H%M%S")
                    new_time_dt = selected_time_dt + timedelta(minutes=1)
                    new_target_hour = new_time_dt.strftime("%H%M%S")
                    
                    # 장 마감 시간(15:30) 초과 시 현재 시간으로 조정
                    if new_target_hour > "153000":
                        new_target_hour = now_kst().strftime("%H%M%S")
                    
                    self.logger.warning(f"🔄 {stock_code} 전체 데이터 조회 실패, 시간 조정하여 재시도: {target_hour} → {new_target_hour}")
                    
                    # 조정된 시간으로 재시도
                    historical_data = await get_full_trading_day_data_async(
                        stock_code=stock_code,
                        target_date=target_date,
                        selected_time=new_target_hour,
                        start_time="090000"
                    )
                    
                    if historical_data is not None and not historical_data.empty:
                        # 성공 시 selected_time 업데이트
                        with self._lock:
                            if stock_code in self.selected_stocks:
                                new_selected_time = selected_time.replace(
                                    hour=new_time_dt.hour,
                                    minute=new_time_dt.minute,
                                    second=new_time_dt.second
                                )
                                self.selected_stocks[stock_code].selected_time = new_selected_time
                                self.logger.info(f"✅ {stock_code} 시간 조정으로 전체 데이터 조회 성공, selected_time 업데이트: {new_selected_time.strftime('%H:%M:%S')}")
                    
                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 전체 데이터 시간 조정 중 오류: {e}")
                
                if historical_data is None or historical_data.empty:
                    self.logger.error(f"❌ {stock_code} 당일 전체 분봉 데이터 조회 실패 (시간 조정 후에도 실패)")
                    # 실패 시 기존 방식으로 폴백
                    return await self._collect_historical_data_fallback(stock_code)
            
            # 데이터 정렬 및 정리 (시간 순서)
            if 'datetime' in historical_data.columns:
                historical_data = historical_data.sort_values('datetime').reset_index(drop=True)
                # 선정 시간을 timezone-naive로 변환하여 pandas datetime64[ns]와 비교
                selected_time_naive = selected_time.replace(tzinfo=None)
                filtered_data = historical_data[historical_data['datetime'] <= selected_time_naive].copy()
            elif 'time' in historical_data.columns:
                historical_data = historical_data.sort_values('time').reset_index(drop=True)
                # time 컬럼을 이용한 필터링
                selected_time_str = selected_time.strftime("%H%M%S")
                historical_data['time_str'] = historical_data['time'].astype(str).str.zfill(6)
                filtered_data = historical_data[historical_data['time_str'] <= selected_time_str].copy()
                if 'time_str' in filtered_data.columns:
                    filtered_data = filtered_data.drop('time_str', axis=1)
            else:
                # 시간 컬럼이 없으면 전체 데이터 사용
                filtered_data = historical_data.copy()

            # 🆕 1분봉 연속성 검증: 09:00부터 순서대로 1분 간격으로 있어야 함
            if not filtered_data.empty:
                validation_result = self._validate_minute_data_continuity(filtered_data, stock_code)
                if not validation_result['valid']:
                    self.logger.error(f"❌ {stock_code} 1분봉 연속성 검증 실패: {validation_result['reason']}")
                    # 데이터가 불완전하면 폴백 방식으로 재시도
                    return await self._collect_historical_data_fallback(stock_code)
            
            # 📊 ML용 일봉 데이터 수집 
            daily_data = await self._collect_daily_data_for_ml(stock_code)
            
            # 메모리에 저장
            with self._lock:
                if stock_code in self.selected_stocks:
                    self.selected_stocks[stock_code].historical_data = filtered_data
                    self.selected_stocks[stock_code].daily_data = daily_data  # 빈 DataFrame 저장
                    self.selected_stocks[stock_code].data_complete = True
                    self.selected_stocks[stock_code].last_update = now_kst()
            
            # 데이터 분석 및 로깅
            data_count = len(filtered_data)
            if data_count > 0:
                if 'time' in filtered_data.columns:
                    start_time = filtered_data.iloc[0].get('time', 'N/A')
                    end_time = filtered_data.iloc[-1].get('time', 'N/A')
                elif 'datetime' in filtered_data.columns:
                    start_dt = filtered_data.iloc[0].get('datetime')
                    end_dt = filtered_data.iloc[-1].get('datetime')
                    start_time = start_dt.strftime('%H%M%S') if start_dt else 'N/A'
                    end_time = end_dt.strftime('%H%M%S') if end_dt else 'N/A'
                else:
                    start_time = end_time = 'N/A'
                
                # 시간 범위 계산
                time_range_minutes = self._calculate_time_range_minutes(start_time, end_time)
                
                self.logger.info(f"✅ {stock_code} 당일 전체 분봉 수집 성공! (09:00~{selected_time.strftime('%H:%M')})")
                self.logger.info(f"   총 데이터: {data_count}건")
                self.logger.info(f"   시간 범위: {start_time} ~ {end_time} ({time_range_minutes}분)")
                
                # 3분봉 변환 예상 개수 계산
                expected_3min_count = data_count // 3
                self.logger.info(f"   예상 3분봉: {expected_3min_count}개 (최소 5개 필요)")
                
                if expected_3min_count >= 5:
                    self.logger.info(f"   ✅ 신호 생성 조건 충족!")
                else:
                    self.logger.warning(f"   ⚠️ 3분봉 데이터 부족 위험: {expected_3min_count}/5")
                
                # 09:00부터 데이터가 시작되는지 확인  
                if start_time and start_time >= "090000":
                    self.logger.info(f"   📊 정규장 데이터: {start_time}부터")
                
            else:
                self.logger.info(f"ℹ️ {stock_code} 선정 시점 이전 분봉 데이터 없음")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 전체 거래시간 분봉 데이터 수집 오류: {e}")
            # 오류 시 기존 방식으로 폴백
            return await self._collect_historical_data_fallback(stock_code)
    
    async def _collect_historical_data_fallback(self, stock_code: str) -> bool:
        """
        과거 분봉 데이터 수집 폴백 함수 (기존 방식)
        
        전체 거래시간 수집이 실패했을 때 사용하는 기존 API 방식
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 수집 성공 여부
        """
        try:
            with self._lock:
                if stock_code not in self.selected_stocks:
                    return False
                    
                stock_data = self.selected_stocks[stock_code]
                selected_time = stock_data.selected_time
            
            self.logger.warning(f"🔄 {stock_code} 폴백 방식으로 과거 분봉 데이터 수집")
            
            # 선정 시간까지의 당일 분봉 데이터 조회 (기존 방식)
            target_hour = selected_time.strftime("%H%M%S")
            
            # 당일분봉조회 API 사용 (최대 30건)
            # 종목별 적절한 시장 구분 코드 사용
            div_code = get_div_code_for_stock(stock_code)
            
            result = get_inquire_time_itemchartprice(
                div_code=div_code,
                stock_code=stock_code,
                input_hour=target_hour,
                past_data_yn="Y"
            )
            
            if result is None:
                # 실패 시 1분씩 앞으로 이동하여 재시도
                from datetime import datetime, timedelta
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
                        with self._lock:
                            if stock_code in self.selected_stocks:
                                new_selected_time = selected_time.replace(
                                    hour=new_time_dt.hour,
                                    minute=new_time_dt.minute,
                                    second=new_time_dt.second
                                )
                                self.selected_stocks[stock_code].selected_time = new_selected_time
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
                with self._lock:
                    if stock_code in self.selected_stocks:
                        self.selected_stocks[stock_code].historical_data = pd.DataFrame()
                        self.selected_stocks[stock_code].data_complete = True
                return True
            
            # 선정 시점 이전 데이터만 필터링
            if 'datetime' in chart_df.columns:
                # 선정 시간을 timezone-naive로 변환하여 pandas datetime64[ns]와 비교
                selected_time_naive = selected_time.replace(tzinfo=None)
                historical_data = chart_df[chart_df['datetime'] <= selected_time_naive].copy()
            else:
                historical_data = chart_df.copy()
            
            # 메모리에 저장
            with self._lock:
                if stock_code in self.selected_stocks:
                    self.selected_stocks[stock_code].historical_data = historical_data
                    self.selected_stocks[stock_code].data_complete = True
                    self.selected_stocks[stock_code].last_update = now_kst()
            
            # 데이터 분석
            data_count = len(historical_data)
            if data_count > 0:
                start_time = historical_data.iloc[0].get('time', 'N/A') if 'time' in historical_data.columns else 'N/A'
                end_time = historical_data.iloc[-1].get('time', 'N/A') if 'time' in historical_data.columns else 'N/A'
                
                self.logger.info(f"✅ {stock_code} 폴백 분봉 수집 완료: {data_count}건 "
                               f"({start_time} ~ {end_time})")
                self.logger.warning(f"⚠️ 제한된 데이터 범위 (API 제한으로 최대 30분봉)")
            else:
                self.logger.info(f"ℹ️ {stock_code} 폴백 방식도 데이터 없음")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 폴백 분봉 데이터 수집 오류: {e}")
            return False
    
    def _calculate_time_range_minutes(self, start_time: str, end_time: str) -> int:
        """
        시작 시간과 종료 시간 사이의 분 수 계산

        Args:
            start_time: 시작시간 (HHMMSS 형식)
            end_time: 종료시간 (HHMMSS 형식)

        Returns:
            int: 시간 범위 (분)
        """
        try:
            if not start_time or not end_time or start_time == 'N/A' or end_time == 'N/A':
                return 0

            # 시간 문자열을 6자리로 맞춤
            start_time = str(start_time).zfill(6)
            end_time = str(end_time).zfill(6)

            start_hour = int(start_time[:2])
            start_minute = int(start_time[2:4])
            end_hour = int(end_time[:2])
            end_minute = int(end_time[2:4])

            start_total_minutes = start_hour * 60 + start_minute
            end_total_minutes = end_hour * 60 + end_minute

            return max(0, end_total_minutes - start_total_minutes)

        except (ValueError, IndexError):
            return 0

    def _validate_minute_data_continuity(self, data: pd.DataFrame, stock_code: str) -> dict:
        """
        1분봉 데이터 연속성 검증

        09:00부터 순서대로 1분 간격으로 데이터가 있는지 확인

        Args:
            data: 1분봉 DataFrame
            stock_code: 종목코드 (로깅용)

        Returns:
            dict: {'valid': bool, 'reason': str, 'missing_times': list}
        """
        try:
            if data.empty:
                return {'valid': False, 'reason': '데이터 없음', 'missing_times': []}

            # datetime 컬럼 확인 및 변환
            if 'datetime' in data.columns:
                data_copy = data.copy()
                data_copy['datetime'] = pd.to_datetime(data_copy['datetime'])

                # 첫 봉이 09:00인지 확인
                first_time = data_copy['datetime'].iloc[0]
                if first_time.hour != 9 or first_time.minute != 0:
                    return {
                        'valid': False,
                        'reason': f'첫 봉이 09:00 아님 (실제: {first_time.strftime("%H:%M")})',
                        'missing_times': []
                    }

                # 각 봉 사이의 시간 간격 계산 (초 단위)
                time_diffs = data_copy['datetime'].diff().dt.total_seconds().fillna(0)

                # 1분봉이므로 간격이 정확히 60초여야 함 (첫 봉은 0이므로 제외)
                invalid_gaps = time_diffs[1:][(time_diffs[1:] != 60.0) & (time_diffs[1:] != 0.0)]

                if len(invalid_gaps) > 0:
                    # 불연속 구간 발견
                    gap_indices = invalid_gaps.index.tolist()
                    missing_times = []
                    for idx in gap_indices[:5]:  # 최대 5개만 표시
                        prev_time = data_copy.loc[idx-1, 'datetime']
                        curr_time = data_copy.loc[idx, 'datetime']
                        gap_minutes = int(time_diffs[idx] / 60)
                        missing_times.append(f"{prev_time.strftime('%H:%M')}→{curr_time.strftime('%H:%M')} ({gap_minutes}분 간격)")

                    return {
                        'valid': False,
                        'reason': f'불연속 구간 {len(invalid_gaps)}개 발견',
                        'missing_times': missing_times
                    }

                # 모든 검증 통과
                return {'valid': True, 'reason': 'OK', 'missing_times': []}

            elif 'time' in data.columns:
                # time 컬럼 기반 검증
                data_copy = data.copy()
                data_copy['time_int'] = data_copy['time'].astype(str).str.zfill(6).str[:4].astype(int)

                # 첫 봉이 0900인지 확인
                if data_copy['time_int'].iloc[0] != 900:
                    return {
                        'valid': False,
                        'reason': f'첫 봉이 09:00 아님 (실제: {data_copy["time_int"].iloc[0]})',
                        'missing_times': []
                    }

                # 시간 간격 계산
                time_diffs = data_copy['time_int'].diff().fillna(0)

                # 1분 간격 (0900→0901=1, 0959→1000=41 등 처리 필요)
                invalid_gaps = []
                missing_times = []

                for i in range(1, len(data_copy)):
                    prev_time = data_copy['time_int'].iloc[i-1]
                    curr_time = data_copy['time_int'].iloc[i]

                    # 예상 다음 시간 계산
                    prev_hour = prev_time // 100
                    prev_min = prev_time % 100

                    if prev_min == 59:
                        expected_next = (prev_hour + 1) * 100
                    else:
                        expected_next = prev_time + 1

                    if curr_time != expected_next:
                        invalid_gaps.append(i)
                        if len(missing_times) < 5:
                            missing_times.append(f"{prev_time:04d}→{curr_time:04d}")

                if invalid_gaps:
                    return {
                        'valid': False,
                        'reason': f'불연속 구간 {len(invalid_gaps)}개 발견',
                        'missing_times': missing_times
                    }

                return {'valid': True, 'reason': 'OK', 'missing_times': []}

            else:
                # 시간 컬럼이 없으면 검증 불가
                return {'valid': True, 'reason': '시간컬럼없음(검증생략)', 'missing_times': []}

        except Exception as e:
            self.logger.error(f"❌ {stock_code} 연속성 검증 오류: {e}")
            return {'valid': True, 'reason': f'검증오류(통과처리): {str(e)}', 'missing_times': []}
    
    async def update_realtime_data(self, stock_code: str) -> bool:
        """
        실시간 분봉 데이터 업데이트 (매수 판단용)
        
        1. 08-09시부터 분봉 데이터가 충분한지 체크
        2. 데이터가 충분하면 최신 분봉 1개만 수집하여 추가
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 업데이트 성공 여부
        """
        try:
            with self._lock:
                if stock_code not in self.selected_stocks:
                    return False
                    
                stock_data = self.selected_stocks[stock_code]
            
            # 1. 현재 보유한 전체 데이터 확인 (historical + realtime)
            combined_data = self.get_combined_chart_data(stock_code)
            
            # 2. 08-09시부터 데이터가 충분한지 체크
            if not self._check_sufficient_base_data(combined_data, stock_code):
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
            with self._lock:
                if stock_code in self.selected_stocks:
                    current_realtime = self.selected_stocks[stock_code].realtime_data.copy()
                    
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
                    
                    self.selected_stocks[stock_code].realtime_data = updated_realtime
                    self.selected_stocks[stock_code].last_update = current_time
            
            #self.logger.debug(f"✅ {stock_code} 최신 분봉 1건 업데이트 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 실시간 분봉 업데이트 오류: {e}")
            return False
    
    def _check_sufficient_base_data(self, combined_data: Optional[pd.DataFrame], stock_code: str) -> bool:
        """
        09시부터 분봉 데이터가 충분한지 간단 체크

        Args:
            combined_data: 결합된 차트 데이터
            stock_code: 종목코드 (로깅용)

        Returns:
            bool: 기본 데이터 충분 여부
        """
        try:
            from utils.korean_time import now_kst

            if combined_data is None or combined_data.empty:
                self.logger.debug(f"❌ {stock_code} 데이터 없음")
                return False

            # 1. 당일 데이터인지 먼저 확인
            today_str = now_kst().strftime('%Y%m%d')

            # date 컬럼으로 당일 데이터만 필터링
            if 'date' in combined_data.columns:
                today_data = combined_data[combined_data['date'].astype(str) == today_str].copy()
                if today_data.empty:
                    self.logger.debug(f"❌ {stock_code} 당일 데이터 없음 (전일 데이터만 존재)")
                    return False
                combined_data = today_data
            elif 'datetime' in combined_data.columns:
                try:
                    combined_data['date_str'] = pd.to_datetime(combined_data['datetime']).dt.strftime('%Y%m%d')
                    today_data = combined_data[combined_data['date_str'] == today_str].copy()
                    if today_data.empty:
                        self.logger.debug(f"❌ {stock_code} 당일 데이터 없음 (전일 데이터만 존재)")
                        return False
                    combined_data = today_data.drop('date_str', axis=1)
                except Exception:
                    pass

            data_count = len(combined_data)

            # 최소 데이터 개수 체크 (3분봉 최소 5개 = 15분봉 필요)
            if data_count < 5:
                self.logger.debug(f"❌ {stock_code} 데이터 부족: {data_count}/15")
                return False

            # 시작 시간 체크 (09:00대 시작 확인)
            if 'time' in combined_data.columns:
                start_time_str = str(combined_data.iloc[0]['time']).zfill(6)
                start_hour = int(start_time_str[:2])

                # 09시 시작 확인
                if start_hour != 9:
                    self.logger.debug(f"❌ {stock_code} 시작 시간 문제: {start_time_str} (09시 아님)")
                    return False

            elif 'datetime' in combined_data.columns:
                start_dt = combined_data.iloc[0]['datetime']
                if hasattr(start_dt, 'hour'):
                    start_hour = start_dt.hour
                    # 09시 시작 확인
                    if start_hour != 9:
                        self.logger.debug(f"❌ {stock_code} 시작 시간 문제: {start_hour}시 (09시 아님)")
                        return False

            #self.logger.debug(f"✅ {stock_code} 기본 데이터 충분: {data_count}개")
            return True

        except Exception as e:
            self.logger.warning(f"⚠️ {stock_code} 기본 데이터 체크 오류: {e}")
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
            from datetime import timedelta
            
            # 🆕 완성된 마지막 분봉 시간 계산
            # 현재 시각이 10:01:30이면 10:00분봉(10:00:00~10:00:59)을 요청
            # 현재 진행중인 분의 이전 분이 완성된 마지막 분봉
            current_minute_start = current_time.replace(second=0, microsecond=0)
            last_completed_minute = current_minute_start - timedelta(minutes=1)
            target_hour = last_completed_minute.strftime("%H%M%S")
            
            #self.logger.debug(f"📊 {stock_code} 완성된 분봉 요청: {target_hour} (현재: {current_time.strftime('%H%M%S')})")
            
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
            
            # 로깅: 실제 수집된 데이터 시간 확인
            '''
            if 'time' in latest_data.columns and not latest_data.empty:
                actual_time = str(latest_data['time'].iloc[0]).zfill(6)
                self.logger.debug(f"✅ {stock_code} 완성된 분봉 수집: {actual_time} (요청: {target_hour})")
            '''
            
            return latest_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 최신 분봉 수집 오류: {e}")
            return None
    
    def get_current_price_for_sell(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        매도 판단용 실시간 현재가 조회
        
        기존 가격 조회 API (/uapi/domestic-stock/v1/quotations/inquire-price)를 사용하여
        매도 판단에 필요한 실시간 현재가 정보를 제공합니다.
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Dict: 현재가 정보 또는 None
                - current_price: 현재가
                - change_rate: 전일대비율
                - volume: 거래량
                - high: 고가
                - low: 저가 등
        """
        try:
            # J (KRX) 시장으로 현재가 조회
            price_data = get_inquire_price(div_code="J", itm_no=stock_code)
            
            if price_data is None or price_data.empty:
                self.logger.debug(f"❌ {stock_code} 현재가 조회 실패 (매도용)")
                return None
            
            # 첫 번째 행의 데이터 추출
            row = price_data.iloc[0]
            
            # 주요 현재가 정보 추출 (필드명은 실제 API 응답에 따라 조정 필요)
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
            
            #self.logger.debug(f"📈 {stock_code} 현재가 조회 완료 (매도용): {current_price_info['current_price']:,.0f}원 "
            #                f"({current_price_info['change_rate']:+.2f}%)")
            
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
            with self._lock:
                if stock_code not in self.selected_stocks:
                    return None
                    
                stock_data = self.selected_stocks[stock_code]
                return stock_data.current_price_info
                
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
        with self._lock:
            return self.selected_stocks.get(stock_code)
    
    def get_combined_chart_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        종목의 당일 전체 차트 데이터 조회 (08:00~현재, 완성된 봉만)
        
        종목 선정 시 수집한 historical_data와 실시간으로 업데이트되는 realtime_data를 결합하여
        당일 전체 분봉 데이터를 반환합니다. API 30건 제한을 우회하여 전체 거래시간 데이터 제공.
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 당일 전체 차트 데이터 (완성된 봉만)
        """
        try:
            from utils.korean_time import now_kst
            
            with self._lock:
                if stock_code not in self.selected_stocks:
                    self.logger.debug(f"❌ {stock_code} 선정된 종목 아님")
                    return None
                
                stock_data = self.selected_stocks[stock_code]
                historical_data = stock_data.historical_data.copy() if not stock_data.historical_data.empty else pd.DataFrame()
                realtime_data = stock_data.realtime_data.copy() if not stock_data.realtime_data.empty else pd.DataFrame()
            
            # historical_data와 realtime_data 결합
            if historical_data.empty and realtime_data.empty:
                self.logger.error(f"❌ {stock_code} 과거 및 실시간 데이터 모두 없음")
                return None
            elif historical_data.empty:
                combined_data = realtime_data.copy()
                self.logger.error(f"📊 {stock_code} 실시간 데이터만 사용: {len(combined_data)}건")
                return None
            elif realtime_data.empty:
                combined_data = historical_data.copy()
                self.logger.error(f"📊 {stock_code} 과거 데이터만 사용: {len(combined_data)}건")
                
                # 데이터 부족 시 자동 수집 시도
                if len(combined_data) < 15:
                    try:
                        from trade_analysis.data_sufficiency_checker import collect_minute_data_from_api, save_minute_data_to_cache
                        from utils.korean_time import now_kst
                        
                        today = now_kst().strftime('%Y%m%d')
                        self.logger.info(f"🔄 {stock_code} 데이터 부족으로 자동 수집 시도...")
                        
                        # API에서 직접 분봉 데이터 수집
                        minute_data = collect_minute_data_from_api(stock_code, today)
                        if minute_data is not None and not minute_data.empty:
                            # 캐시에 저장
                            save_minute_data_to_cache(stock_code, today, minute_data)
                            
                            # historical_data에 추가
                            with self._lock:
                                if stock_code in self.selected_stocks:
                                    self.selected_stocks[stock_code].historical_data = minute_data
                                    self.selected_stocks[stock_code].data_complete = True
                                    self.selected_stocks[stock_code].last_update = now_kst()
                            
                            # 수정된 데이터로 다시 결합
                            combined_data = minute_data.copy()
                            self.logger.info(f"✅ {stock_code} 자동 수집 완료: {len(combined_data)}개")
                        else:
                            self.logger.warning(f"❌ {stock_code} 자동 수집 실패")
                            return None
                            
                    except Exception as e:
                        self.logger.error(f"❌ {stock_code} 자동 수집 중 오류: {e}")
                        return None
            else:
                combined_data = pd.concat([historical_data, realtime_data], ignore_index=True)
                #self.logger.debug(f"📊 {stock_code} 과거+실시간 데이터 결합: {len(historical_data)}+{len(realtime_data)}={len(combined_data)}건")

            if combined_data.empty:
                return None

            # 🆕 당일 데이터만 필터링 (API 오류로 전날 데이터 섞일 수 있음)
            today_str = now_kst().strftime('%Y%m%d')
            before_filter_count = len(combined_data)

            if 'date' in combined_data.columns:
                combined_data = combined_data[combined_data['date'].astype(str) == today_str].copy()
            elif 'datetime' in combined_data.columns:
                combined_data['date_str'] = pd.to_datetime(combined_data['datetime']).dt.strftime('%Y%m%d')
                combined_data = combined_data[combined_data['date_str'] == today_str].copy()
                combined_data = combined_data.drop('date_str', axis=1)

            if before_filter_count != len(combined_data):
                removed = before_filter_count - len(combined_data)
                self.logger.warning(f"⚠️ {stock_code} 당일 외 데이터 {removed}건 제거: {before_filter_count} → {len(combined_data)}건")

            if combined_data.empty:
                self.logger.error(f"❌ {stock_code} 당일 데이터 없음 (전일 데이터만 존재)")
                return None

            # 중복 제거 (같은 시간대 데이터가 있을 수 있음)
            before_count = len(combined_data)
            if 'datetime' in combined_data.columns:
                combined_data = combined_data.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime').reset_index(drop=True)
            elif 'time' in combined_data.columns:
                combined_data = combined_data.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)

            if before_count != len(combined_data):
                #self.logger.debug(f"📊 {stock_code} 중복 제거: {before_count} → {len(combined_data)}건")
                pass
            
            # 완성된 봉 필터링은 TimeFrameConverter.convert_to_3min_data()에서 처리됨
            
            # 시간순 정렬
            if 'datetime' in combined_data.columns:
                combined_data = combined_data.sort_values('datetime').reset_index(drop=True)
            elif 'date' in combined_data.columns and 'time' in combined_data.columns:
                combined_data = combined_data.sort_values(['date', 'time']).reset_index(drop=True)
            
            # 데이터 수집 현황 로깅
            '''
            if not combined_data.empty:
                data_count = len(combined_data)
                if 'time' in combined_data.columns:
                    start_time = combined_data.iloc[0]['time']
                    end_time = combined_data.iloc[-1]['time']
                    self.logger.debug(f"📊 {stock_code} 당일 전체 데이터: {data_count}건 ({start_time}~{end_time})")
                else:
                    self.logger.debug(f"📊 {stock_code} 당일 전체 데이터: {data_count}건")
            '''
            
            return combined_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 결합 차트 데이터 생성 오류: {e}")
            return None
    
    def get_combined_chart_data_with_realtime(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        종목의 당일 전체 차트 데이터 조회 (완성된 봉 + 실시간 진행중인 봉)
        
        기존 get_combined_chart_data()에 현재가 API를 이용한 실시간 생성 1분봉을 추가하여
        3분봉 매매 판단 시 지연을 최소화합니다.
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 당일 전체 차트 데이터 (완성된 봉 + 실시간 진행중인 봉)
        """
        try:
            # 기존 완성된 분봉 데이터 가져오기
            completed_data = self.get_combined_chart_data(stock_code)
            if completed_data is None or completed_data.empty:
                return completed_data
            
            # 실시간 캔들 빌더를 통해 누락된 완성 분봉 보완 + 진행중인 1분봉 추가
            candle_builder = get_realtime_candle_builder()
            enhanced_data = candle_builder.fill_missing_candles_and_combine(stock_code, completed_data)
            
            # 종목명 가져오기 (로깅용)
            stock_name = ""
            with self._lock:
                if stock_code in self.selected_stocks:
                    stock_name = self.selected_stocks[stock_code].stock_name
            
            # 실시간 데이터가 추가되었는지 로깅
            if len(enhanced_data) > len(completed_data):
                self.logger.debug(f"🔄 {stock_code}({stock_name}) 실시간 1분봉 추가: {len(completed_data)} → {len(enhanced_data)}건")
            
            return enhanced_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 실시간 포함 차트 데이터 생성 오류: {e}")
            # 오류 시 기존 완성된 데이터라도 반환
            return self.get_combined_chart_data(stock_code)
    
    def get_stock_analysis(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        종목 분석 정보 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Dict: 분석 정보
        """
        try:
            combined_data = self.get_combined_chart_data(stock_code)
            
            if combined_data is None or combined_data.empty:
                return None
            
            with self._lock:
                if stock_code not in self.selected_stocks:
                    return None
                    
                stock_data = self.selected_stocks[stock_code]
            
            # 기본 정보
            analysis = {
                'stock_code': stock_code,
                'stock_name': stock_data.stock_name,
                'selected_time': stock_data.selected_time,
                'data_complete': stock_data.data_complete,
                'last_update': stock_data.last_update,
                'total_minutes': len(combined_data),
                'historical_minutes': len(stock_data.historical_data),
                'realtime_minutes': len(stock_data.realtime_data)
            }
            
            # 가격 분석 (close 컬럼이 있는 경우)
            if 'close' in combined_data.columns and len(combined_data) > 0:
                prices = combined_data['close']
                
                analysis.update({
                    'first_price': float(prices.iloc[0]) if len(prices) > 0 else 0,
                    'current_price': float(prices.iloc[-1]) if len(prices) > 0 else 0,
                    'high_price': float(prices.max()),
                    'low_price': float(prices.min()),
                    'price_change': float(prices.iloc[-1] - prices.iloc[0]) if len(prices) > 1 else 0,
                    'price_change_rate': float((prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0] * 100) if len(prices) > 1 and prices.iloc[0] > 0 else 0
                })
            
            # 거래량 분석 (volume 컬럼이 있는 경우)
            if 'volume' in combined_data.columns:
                volumes = combined_data['volume']
                analysis.update({
                    'total_volume': int(volumes.sum()),
                    'avg_volume': int(volumes.mean()) if len(volumes) > 0 else 0,
                    'max_volume': int(volumes.max()) if len(volumes) > 0 else 0
                })
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 분석 정보 생성 오류: {e}")
            return None
    
    def get_all_stocks_summary(self) -> Dict[str, Any]:
        """
        모든 관리 종목 요약 정보
        
        Returns:
            Dict: 전체 요약 정보
        """
        try:
            with self._lock:
                stock_codes = list(self.selected_stocks.keys())
            
            summary = {
                'total_stocks': len(stock_codes),
                'max_stocks': self.max_stocks,
                'current_time': now_kst().strftime('%Y-%m-%d %H:%M:%S'),
                'stocks': []
            }
            
            for stock_code in stock_codes:
                analysis = self.get_stock_analysis(stock_code)
                if analysis:
                    summary['stocks'].append({
                        'stock_code': stock_code,
                        'stock_name': analysis['stock_name'],
                        'selected_time': analysis['selected_time'].strftime('%H:%M:%S'),
                        'data_complete': analysis['data_complete'],
                        'total_minutes': analysis['total_minutes'],
                        'price_change_rate': analysis.get('price_change_rate', 0)
                    })
            
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ 전체 요약 정보 생성 오류: {e}")
            return {}
    
    def remove_stock(self, stock_code: str) -> bool:
        """
        종목 제거
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 제거 성공 여부
        """
        try:
            with self._lock:
                if stock_code in self.selected_stocks:
                    stock_name = self.selected_stocks[stock_code].stock_name
                    del self.selected_stocks[stock_code]
                    self.logger.info(f"🗑️ {stock_code}({stock_name}) 관리 목록에서 제거")
                    return True
                else:
                    return False
                    
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 제거 오류: {e}")
            return False
    

    
    async def batch_update_realtime_data(self):
        """
        모든 관리 종목의 실시간 데이터 일괄 업데이트 (분봉 + 현재가)
        """
        try:
            from utils.korean_time import now_kst

            # 🆕 15:30 장 마감 시 메모리 데이터 자동 저장
            current_time = now_kst()
            if current_time.hour == 15 and current_time.minute == 30:
                if not hasattr(self, '_data_saved_today'):
                    self._save_minute_data_to_file()
                    self._data_saved_today = True  # 하루에 한 번만 저장

            with self._lock:
                stock_codes = list(self.selected_stocks.keys())

            if not stock_codes:
                return

            # 🆕 data_complete = False인 종목 재수집 (09:05 이전 선정 종목)
            incomplete_stocks = []
            with self._lock:
                for code in stock_codes:
                    stock_data = self.selected_stocks.get(code)
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

            # 🆕 동적 배치 크기 계산
            batch_size, batch_delay = self.batch_calculator.calculate_optimal_batch(total_stocks)

            for i in range(0, len(stock_codes), batch_size):
                batch = stock_codes[i:i + batch_size]
                
                # 🆕 분봉 데이터와 현재가 정보를 동시에 업데이트
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
                    stock_name = None
                    with self._lock:
                        if stock_code in self.selected_stocks:
                            stock_name = self.selected_stocks[stock_code].stock_name
                    
                    # 분봉 데이터 결과 처리
                    if isinstance(minute_result, Exception):
                        failed_updates += 1
                        quality_issues.append(f"{stock_code}: 분봉 업데이트 실패 - {str(minute_result)[:50]}")
                    else:
                        successful_minute_updates += 1
                        # 데이터 품질 검사
                        quality_check = self._check_data_quality(stock_code)
                        if quality_check['has_issues']:
                            quality_issues.extend([f"{stock_code}: {issue}" for issue in quality_check['issues']])

                            # 🆕 분봉 누락 감지 시 즉시 전체 재수집
                            for issue in quality_check['issues']:
                                if '분봉 누락' in issue:
                                    self.logger.warning(f"⚠️ {stock_code} 분봉 누락 감지, 전체 재수집 시도: {issue}")
                                    try:
                                        # 비동기 재수집 스케줄링 (현재 루프 블로킹 방지)
                                        asyncio.create_task(self._collect_historical_data(stock_code))
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
                            if not isinstance(minute_result, Exception):
                                with self._lock:
                                    if stock_code in self.selected_stocks:
                                        realtime_data = self.selected_stocks[stock_code].realtime_data
                                        if realtime_data is not None and not realtime_data.empty:
                                            # 최근 3분봉 데이터만 로깅
                                            minute_data = realtime_data.tail(3)
                            
                            # 현재가 데이터 준비
                            price_data = None
                            if not isinstance(price_result, Exception):
                                with self._lock:
                                    if stock_code in self.selected_stocks:
                                        current_price_info = self.selected_stocks[stock_code].current_price_info
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
                            
                        except Exception as log_error:
                            # 로깅 오류가 메인 로직에 영향을 주지 않도록 조용히 처리
                            pass
                
                # 🆕 동적 배치 지연 시간 적용 (API 제한 준수)
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
            
            # 메모리에 현재가 정보 저장
            with self._lock:
                if stock_code in self.selected_stocks:
                    self.selected_stocks[stock_code].current_price_info = current_price_info
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 현재가 정보 업데이트 오류: {e}")
            return False
    
    def _check_data_quality(self, stock_code: str) -> dict:
        """실시간 데이터 품질 검사"""
        try:
            with self._lock:
                stock_data = self.selected_stocks.get(stock_code)
            
            if not stock_data:
                return {'has_issues': True, 'issues': ['데이터 없음']}
            
            # historical_data와 realtime_data를 합쳐서 전체 분봉 데이터 생성
            all_data = pd.concat([stock_data.historical_data, stock_data.realtime_data], ignore_index=True)
            if all_data.empty:
                return {'has_issues': True, 'issues': ['데이터 없음']}
            
            issues = []
            # DataFrame을 dict 형태로 변환하여 기존 로직과 호환
            data = all_data.to_dict('records')
            
            # 1. 데이터 양 검사 (최소 5개 이상)
            if len(data) < 5:
                issues.append(f'데이터 부족 ({len(data)}개)')
            
            # 2. 시간 순서 및 연속성 검사 (전체 데이터)
            if len(data) >= 2:
                times = [row['time'] for row in data]
                # 순서 확인
                if times != sorted(times):
                    issues.append('시간 순서 오류')

                # 🆕 1분 간격 연속성 확인 (중간 누락 감지)
                for i in range(1, len(times)):
                    try:
                        prev_time_str = str(times[i-1]).zfill(6)
                        curr_time_str = str(times[i]).zfill(6)

                        prev_hour = int(prev_time_str[:2])
                        prev_min = int(prev_time_str[2:4])
                        curr_hour = int(curr_time_str[:2])
                        curr_min = int(curr_time_str[2:4])

                        # 예상 다음 시간 계산
                        if prev_min == 59:
                            expected_hour = prev_hour + 1
                            expected_min = 0
                        else:
                            expected_hour = prev_hour
                            expected_min = prev_min + 1

                        # 1분 간격이 아니면 누락
                        if curr_hour != expected_hour or curr_min != expected_min:
                            issues.append(f'분봉 누락: {prev_time_str}→{curr_time_str}')
                            break  # 첫 번째 누락만 보고
                    except Exception:
                        pass
            
            # 3. 가격 이상치 검사 (최근 데이터 기준)
            if len(data) >= 2:
                current_price = data[-1].get('close', 0)
                prev_price = data[-2].get('close', 0)
                
                if current_price > 0 and prev_price > 0:
                    price_change = abs(current_price - prev_price) / prev_price
                    if price_change > 0.3:  # 30% 이상 변동시 이상치로 판단
                        issues.append(f'가격 급변동 ({price_change*100:.1f}%)')
            
            # 4. 데이터 지연 검사 (최신 데이터가 5분 이상 오래된 경우)
            if data:
                from utils.korean_time import now_kst
                latest_time_str = str(data[-1].get('time', '000000')).zfill(6)
                current_time = now_kst()
                
                try:
                    latest_hour = int(latest_time_str[:2])
                    latest_minute = int(latest_time_str[2:4])
                    latest_time = current_time.replace(hour=latest_hour, minute=latest_minute, second=0, microsecond=0)
                    
                    time_diff = (current_time - latest_time).total_seconds()
                    if time_diff > 300:  # 5분 이상 지연
                        issues.append(f'데이터 지연 ({time_diff/60:.1f}분)')
                except Exception:
                    issues.append('시간 파싱 오류')
            
            # 5. 당일 날짜 검증
            date_issues = self._validate_today_data(all_data)
            if date_issues:
                issues.extend(date_issues)

            return {'has_issues': bool(issues), 'issues': issues}

        except Exception as e:
            return {'has_issues': True, 'issues': [f'품질검사 오류: {str(e)[:30]}']}

    def _validate_today_data(self, data: pd.DataFrame) -> List[str]:
        """당일 데이터인지 검증"""
        issues = []

        try:
            from utils.korean_time import now_kst
            today_str = now_kst().strftime('%Y%m%d')

            # 1. date 컬럼이 있는 경우 (YYYYMMDD 형태)
            if 'date' in data.columns:
                unique_dates = data['date'].unique()
                wrong_dates = [d for d in unique_dates if str(d) != today_str]
                if wrong_dates:
                    issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')

            # 2. datetime 컬럼이 있는 경우
            elif 'datetime' in data.columns:
                # datetime 컬럼에서 날짜 추출
                try:
                    data_dates = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d').unique()
                    wrong_dates = [d for d in data_dates if d != today_str]
                    if wrong_dates:
                        issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')
                except Exception:
                    # datetime 파싱 실패시 무시
                    pass

            # 3. stck_bsop_date 컬럼이 있는 경우 (KIS API 응답)
            elif 'stck_bsop_date' in data.columns:
                unique_dates = data['stck_bsop_date'].unique()
                wrong_dates = [d for d in unique_dates if str(d) != today_str]
                if wrong_dates:
                    issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')

        except Exception as e:
            issues.append(f'날짜 검증 오류: {str(e)[:30]}')

        return issues

    async def _collect_daily_data_for_ml(self, stock_code: str) -> pd.DataFrame:
        """
        ML 예측용 일봉 데이터 수집 (100일치)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 일봉 데이터 (100일치) 
        """
        try:
            self.logger.info(f"📈 {stock_code} ML용 일봉 데이터 수집 시작 (100일)")
            
            # 기존 API를 사용하여 일봉 데이터 수집
            from api.kis_market_api import get_inquire_daily_itemchartprice
            from datetime import timedelta
            from utils.korean_time import now_kst
            
            # 100일치 일봉 데이터 수집
            end_date = now_kst().strftime("%Y%m%d")
            start_date = (now_kst() - timedelta(days=100)).strftime("%Y%m%d")
            
            daily_data = get_inquire_daily_itemchartprice(
                div_code="J",
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",  # 일봉
                adj_prc="0"  # 수정주가
            )
            
            if daily_data is not None and not daily_data.empty:
                self.logger.info(f"✅ {stock_code} 일봉 데이터 수집 성공: {len(daily_data)}일치")
                return daily_data
            else:
                self.logger.warning(f"⚠️ {stock_code} 일봉 데이터 수집 실패 - 빈 데이터")
                return pd.DataFrame()
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 일봉 데이터 수집 오류: {e}")
            return pd.DataFrame()

    def _save_minute_data_to_file(self):
        """
        메모리에 있는 모든 종목의 분봉 데이터를 텍스트 파일로 저장 (15:30 장 마감 시)
        """
        try:
            from utils.korean_time import now_kst

            current_time = now_kst()
            filename = f"memory_minute_data_{current_time.strftime('%Y%m%d_%H%M%S')}.txt"

            with self._lock:
                stock_codes = list(self.selected_stocks.keys())

            if not stock_codes:
                self.logger.info("💾 저장할 종목 없음")
                return

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"=" * 100 + "\n")
                f.write(f"메모리 분봉 데이터 덤프 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"=" * 100 + "\n\n")
                f.write(f"총 종목 수: {len(stock_codes)}개\n\n")

                for stock_code in stock_codes:
                    with self._lock:
                        if stock_code not in self.selected_stocks:
                            continue

                        stock_data = self.selected_stocks[stock_code]
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
                    combined_data = self.get_combined_chart_data(stock_code)
                    f.write(f"\n[Combined Data (당일만): {len(combined_data) if combined_data is not None else 0}건]\n")
                    if combined_data is not None and not combined_data.empty:
                        f.write(combined_data.to_string(index=False) + "\n")
                    else:
                        f.write("데이터 없음\n")

            self.logger.info(f"💾 메모리 분봉 데이터 저장 완료: {filename} ({len(stock_codes)}개 종목)")

        except Exception as e:
            self.logger.error(f"❌ 메모리 분봉 데이터 저장 실패: {e}")

