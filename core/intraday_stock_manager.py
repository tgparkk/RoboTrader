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
from api.kis_market_api import get_inquire_daily_itemchartprice


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
        self.max_stocks = 50  # 최대 관리 종목 수
        
        # 동기화
        self._lock = threading.RLock()
        
        self.logger.info("🎯 장중 종목 관리자 초기화 완료")
    
    def add_selected_stock(self, stock_code: str, stock_name: str, 
                          selection_reason: str = "") -> bool:
        """
        조건검색으로 선정된 종목 추가
        
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
                
                self.logger.info(f"✅ {stock_code}({stock_name}) 장중 선정 완료 - "
                               f"시간: {current_time.strftime('%H:%M:%S')}")
                
                # 비동기로 과거 데이터 수집 시작
                asyncio.create_task(self._collect_historical_data(stock_code))
                
                return True
                
        except Exception as e:
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
            
            self.logger.info(f"📈 {stock_code} 당일 전체 데이터 수집 시작 (08:00 ~ {target_hour})")
            
            historical_data = await get_full_trading_day_data_async(
                stock_code=stock_code,
                target_date=target_date,
                selected_time=target_hour,
                start_time="080000"  # 08:00부터 시작 (NXT 거래소 지원)
            )
            
            if historical_data is None or historical_data.empty:
                self.logger.error(f"❌ {stock_code} 당일 전체 분봉 데이터 조회 실패")
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
            
            # 과거 29일 일봉 데이터 수집 (가격박스 계산용)
            daily_data = await self._collect_daily_data_for_price_box(stock_code)
            
            # 메모리에 저장
            with self._lock:
                if stock_code in self.selected_stocks:
                    self.selected_stocks[stock_code].historical_data = filtered_data
                    self.selected_stocks[stock_code].daily_data = daily_data if daily_data is not None else pd.DataFrame()
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
                self.logger.info(f"   예상 3분봉: {expected_3min_count}개 (최소 10개 필요)")
                
                if expected_3min_count >= 10:
                    self.logger.info(f"   ✅ 신호 생성 조건 충족!")
                else:
                    self.logger.warning(f"   ⚠️ 3분봉 데이터 부족 위험: {expected_3min_count}/10")
                
                # 09:00부터 데이터가 시작되는지 확인
                if start_time and start_time <= "090100":
                    self.logger.info(f"   📊 프리마켓 데이터 포함: {start_time}부터")
                elif start_time and start_time >= "090000":
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
                self.logger.error(f"❌ {stock_code} 폴백 분봉 데이터 조회 실패")
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
    
    async def update_realtime_data(self, stock_code: str) -> bool:
        """
        실시간 분봉 데이터 업데이트
        
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
                selected_time = stock_data.selected_time
            
            # 현재 시간까지의 당일 분봉 데이터 조회
            current_time = now_kst()
            target_hour = current_time.strftime("%H%M%S")
            
            # 종목별 적절한 시장 구분 코드 사용
            div_code = get_div_code_for_stock(stock_code)
            
            result = get_inquire_time_itemchartprice(
                div_code=div_code,
                stock_code=stock_code,
                input_hour=target_hour,
                past_data_yn="Y"
            )
            
            if result is None:
                return False
            
            summary_df, chart_df = result
            
            if chart_df.empty:
                return True
            
            # 선정 시점 이후 데이터만 추출 (실시간 데이터)
            if 'datetime' in chart_df.columns:
                # 선정 시간을 timezone-naive로 변환하여 pandas datetime64[ns]와 비교
                selected_time_naive = selected_time.replace(tzinfo=None)
                realtime_data = chart_df[chart_df['datetime'] > selected_time_naive].copy()
            else:
                # datetime 컬럼이 없으면 시간 비교로 대체
                realtime_data = chart_df.copy()
            
            # 메모리에 업데이트
            with self._lock:
                if stock_code in self.selected_stocks:
                    self.selected_stocks[stock_code].realtime_data = realtime_data
                    self.selected_stocks[stock_code].last_update = current_time
            
            self.logger.debug(f"📊 {stock_code} 실시간 분봉 업데이트: {len(realtime_data)}건")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 실시간 분봉 업데이트 오류: {e}")
            return False
    
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
                self.logger.debug(f"❌ {stock_code} 과거 및 실시간 데이터 모두 없음")
                return None
            elif historical_data.empty:
                combined_data = realtime_data.copy()
                self.logger.debug(f"📊 {stock_code} 실시간 데이터만 사용: {len(combined_data)}건")
            elif realtime_data.empty:
                combined_data = historical_data.copy()
                self.logger.debug(f"📊 {stock_code} 과거 데이터만 사용: {len(combined_data)}건")
            else:
                combined_data = pd.concat([historical_data, realtime_data], ignore_index=True)
                self.logger.debug(f"📊 {stock_code} 과거+실시간 데이터 결합: {len(historical_data)}+{len(realtime_data)}={len(combined_data)}건")
            
            if combined_data.empty:
                return None
            
            # 중복 제거 (같은 시간대 데이터가 있을 수 있음)
            before_count = len(combined_data)
            if 'datetime' in combined_data.columns:
                combined_data = combined_data.drop_duplicates(subset=['datetime']).sort_values('datetime').reset_index(drop=True)
            elif 'time' in combined_data.columns:
                combined_data = combined_data.drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
            
            if before_count != len(combined_data):
                self.logger.debug(f"📊 {stock_code} 중복 제거: {before_count} → {len(combined_data)}건")
            
            # 완성된 봉만 사용 (현재 진행 중인 1분봉 제외)
            current_time = now_kst()
            combined_data = self._filter_completed_candles_only(combined_data, current_time)
            
            # 시간순 정렬
            if 'datetime' in combined_data.columns:
                combined_data = combined_data.sort_values('datetime').reset_index(drop=True)
            elif 'date' in combined_data.columns and 'time' in combined_data.columns:
                combined_data = combined_data.sort_values(['date', 'time']).reset_index(drop=True)
            
            # 데이터 수집 현황 로깅
            if not combined_data.empty:
                data_count = len(combined_data)
                if 'time' in combined_data.columns:
                    start_time = combined_data.iloc[0]['time']
                    end_time = combined_data.iloc[-1]['time']
                    self.logger.debug(f"📊 {stock_code} 당일 전체 데이터: {data_count}건 ({start_time}~{end_time})")
                else:
                    self.logger.debug(f"📊 {stock_code} 당일 전체 데이터: {data_count}건")
            
            return combined_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 결합 차트 데이터 생성 오류: {e}")
            return None
    
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
        모든 관리 종목의 실시간 데이터 일괄 업데이트 (1분마다)
        """
        try:
            with self._lock:
                stock_codes = list(self.selected_stocks.keys())
            
            if not stock_codes:
                return
            
            # 데이터 품질 모니터링 초기화
            total_stocks = len(stock_codes)
            successful_updates = 0
            failed_updates = 0
            quality_issues = []
            
            # 동시 업데이트 (배치 크기 증가로 효율성 향상)
            batch_size = 20  # 배치 크기 증가
            for i in range(0, len(stock_codes), batch_size):
                batch = stock_codes[i:i + batch_size]
                tasks = [self.update_realtime_data(code) for code in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 배치 결과 품질 검사
                for j, result in enumerate(results):
                    stock_code = batch[j]
                    if isinstance(result, Exception):
                        failed_updates += 1
                        quality_issues.append(f"{stock_code}: 업데이트 실패 - {str(result)[:50]}")
                    else:
                        # 데이터 품질 검사
                        quality_check = self._check_data_quality(stock_code)
                        if quality_check['has_issues']:
                            quality_issues.extend([f"{stock_code}: {issue}" for issue in quality_check['issues']])
                        successful_updates += 1
                
                # API 호출 간격 조절 (더 빠른 업데이트)
                if i + batch_size < len(stock_codes):
                    await asyncio.sleep(0.2)  # 간격 단축
            
            # 데이터 품질 리포트
            success_rate = (successful_updates / total_stocks) * 100 if total_stocks > 0 else 0
            
            if success_rate < 90:  # 성공률이 90% 미만이면 경고
                self.logger.warning(f"⚠️ 실시간 데이터 품질 경고: 성공률 {success_rate:.1f}% ({successful_updates}/{total_stocks})")
                
            if quality_issues:
                # 품질 문제가 5개 이상이면 상위 5개만 로깅
                issues_to_log = quality_issues[:5]
                self.logger.warning(f"🔍 데이터 품질 이슈 {len(quality_issues)}건: {'; '.join(issues_to_log)}")
                if len(quality_issues) > 5:
                    self.logger.warning(f"   (총 {len(quality_issues)}건 중 상위 5건만 표시)")
            else:
                self.logger.debug(f"✅ 실시간 데이터 업데이트 완료: {successful_updates}/{total_stocks} ({success_rate:.1f}%)")
            
        except Exception as e:
            self.logger.error(f"❌ 실시간 데이터 일괄 업데이트 오류: {e}")
    
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
            
            # 1. 데이터 양 검사 (최소 10개 이상)
            if len(data) < 10:
                issues.append(f'데이터 부족 ({len(data)}개)')
            
            # 2. 시간 순서 검사 (최근 5개 데이터)
            if len(data) >= 5:
                recent_times = [row['time'] for row in data[-5:]]
                if recent_times != sorted(recent_times):
                    issues.append('시간 순서 오류')
            
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
            
            return {'has_issues': bool(issues), 'issues': issues}
            
        except Exception as e:
            return {'has_issues': True, 'issues': [f'품질검사 오류: {str(e)[:30]}']}
    
    async def _collect_daily_data_for_price_box(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        가격박스 계산을 위한 과거 29일 일봉 데이터 수집
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 29일 일봉 데이터 (None: 실패)
        """
        try:
            # 29일 전 날짜 계산 (영업일 기준으로 여유있게 40일 전부터)
            from datetime import timedelta
            end_date = now_kst().strftime("%Y%m%d")
            start_date = (now_kst() - timedelta(days=40)).strftime("%Y%m%d")
            
            self.logger.info(f"📊 {stock_code} 일봉 데이터 수집 시작 ({start_date} ~ {end_date})")
            
            # 일봉 데이터 조회
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",  # 상세 데이터
                div_code="J",   # 주식
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",  # 일봉
                adj_prc="1"     # 원주가
            )
            
            if daily_data is None or daily_data.empty:
                self.logger.warning(f"⚠️ {stock_code} 일봉 데이터 조회 실패 또는 빈 데이터")
                return None
            
            # 최근 29일 데이터만 선택 (오늘 제외)
            if len(daily_data) > 29:
                daily_data = daily_data.head(29)
            
            # 데이터 정렬 (오래된 날짜부터)
            if 'stck_bsop_date' in daily_data.columns:
                daily_data = daily_data.sort_values('stck_bsop_date', ascending=True)
            
            self.logger.info(f"✅ {stock_code} 일봉 데이터 수집 성공! ({len(daily_data)}일)")
            
            return daily_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 일봉 데이터 수집 오류: {e}")
            return None
    
    def _filter_completed_candles_only(self, chart_data: pd.DataFrame, current_time: datetime) -> pd.DataFrame:
        """
        완성된 캔들만 필터링 (진행 중인 1분봉 제외)
        
        시뮬레이션과의 일관성을 위해 현재 진행 중인 1분봉을 제외하고
        완전히 완성된 1분봉만 반환합니다.
        
        Args:
            chart_data: 원본 차트 데이터
            current_time: 현재 시간
            
        Returns:
            완성된 캔들만 포함한 데이터프레임
        """
        try:
            if chart_data.empty:
                return chart_data
            
            # 현재 분의 시작 시간 (초, 마이크로초 제거)
            current_minute_start = current_time.replace(second=0, microsecond=0)
            
            # datetime 컬럼이 있는 경우
            if 'datetime' in chart_data.columns:
                # 한국시간(KST) 유지하면서 안전한 타입 변환
                chart_data_copy = chart_data.copy()
                
                # 현재 시간이 KST이므로 같은 타임존으로 맞춤
                if hasattr(current_time, 'tzinfo') and current_time.tzinfo is not None:
                    # current_time이 KST를 가지고 있으면 그대로 사용
                    current_minute_start_pd = pd.Timestamp(current_minute_start).tz_convert(current_time.tzinfo)
                else:
                    # KST 타임존이 없으면 naive로 처리
                    current_minute_start_pd = pd.Timestamp(current_minute_start)
                
                # datetime 컬럼을 pandas Timestamp로 변환 (기존 타임존 정보 보존)
                try:
                    chart_data_copy['datetime'] = pd.to_datetime(chart_data_copy['datetime'])
                    
                    # 타임존 정보가 있는 경우 일치시키기
                    if hasattr(current_minute_start_pd, 'tz') and current_minute_start_pd.tz is not None:
                        if chart_data_copy['datetime'].dt.tz is None:
                            # 차트 데이터가 naive이면 KST로 가정
                            from utils.korean_time import KST
                            chart_data_copy['datetime'] = chart_data_copy['datetime'].dt.tz_localize(KST)
                    else:
                        # 비교 기준이 naive이면 차트 데이터도 naive로 변환
                        if chart_data_copy['datetime'].dt.tz is not None:
                            chart_data_copy['datetime'] = chart_data_copy['datetime'].dt.tz_localize(None)
                            current_minute_start_pd = pd.Timestamp(current_minute_start.replace(tzinfo=None))
                            
                except Exception as e:
                    # 변환 실패시 문자열 비교로 대체
                    self.logger.warning(f"datetime 타입 변환 실패, 문자열 비교 사용: {e}")
                    return chart_data
                
                # 현재 진행 중인 1분봉 제외 (완성되지 않았으므로)
                completed_data = chart_data_copy[chart_data_copy['datetime'] < current_minute_start_pd].copy()
                
                excluded_count = len(chart_data) - len(completed_data)
                if excluded_count > 0:
                    self.logger.debug(f"📊 미완성 봉 {excluded_count}개 제외 (진행 중인 1분봉)")
                
                return completed_data
            
            # time 컬럼만 있는 경우
            elif 'time' in chart_data.columns:
                # 이전 분의 시간 문자열 생성
                prev_minute = current_minute_start - timedelta(minutes=1)
                prev_time_str = prev_minute.strftime('%H%M%S')
                
                # time을 문자열로 변환하여 비교
                chart_data_copy = chart_data.copy()
                chart_data_copy['time_str'] = chart_data_copy['time'].astype(str).str.zfill(6)
                completed_data = chart_data_copy[chart_data_copy['time_str'] <= prev_time_str].copy()
                
                # time_str 컬럼 제거
                if 'time_str' in completed_data.columns:
                    completed_data = completed_data.drop('time_str', axis=1)
                
                excluded_count = len(chart_data) - len(completed_data)
                if excluded_count > 0:
                    self.logger.debug(f"📊 미완성 봉 {excluded_count}개 제외 (진행 중인 1분봉)")
                
                return completed_data
            
            # 시간 컬럼이 없으면 원본 반환
            else:
                self.logger.warning("시간 컬럼을 찾을 수 없어 원본 데이터 반환")
                return chart_data
                
        except Exception as e:
            self.logger.error(f"완성된 캔들 필터링 오류: {e}")
            return chart_data  # 오류 시 원본 반환