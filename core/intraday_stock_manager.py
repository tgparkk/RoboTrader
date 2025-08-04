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
    get_full_trading_day_data_async
)


logger = setup_logger(__name__)


@dataclass
class StockMinuteData:
    """종목별 분봉 데이터 클래스"""
    stock_code: str
    stock_name: str
    selected_time: datetime
    historical_data: pd.DataFrame = field(default_factory=pd.DataFrame)
    realtime_data: pd.DataFrame = field(default_factory=pd.DataFrame)
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
                    self.logger.debug(f"📊 {stock_code}({stock_name}): 이미 관리 중인 종목")
                    return True
                
                # 최대 관리 종목 수 체크
                if len(self.selected_stocks) >= self.max_stocks:
                    self.logger.warning(f"⚠️ 최대 관리 종목 수({self.max_stocks})에 도달. 추가 불가")
                    return False
                
                # 장 시간 체크
                if not is_market_open():
                    self.logger.warning(f"⚠️ 장 시간이 아님. {stock_code} 추가 보류")
                    return False
                
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
        선정 시점 이전의 과거 분봉 데이터 수집 (전체 거래시간)
        
        장중에 종목이 선정되었을 때 09:00부터 선정시점까지의 모든 분봉 데이터를 수집합니다.
        기존 API 제한(30건 또는 120건)을 극복하여 전체 거래시간 데이터를 확보합니다.
        
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
            
            # 새로운 전체 거래시간 데이터 수집 함수 사용
            target_date = selected_time.strftime("%Y%m%d")
            target_hour = selected_time.strftime("%H%M%S")
            
            # 전체 거래시간 분봉 데이터 수집 (09:00부터 선정시점까지)
            historical_data = await get_full_trading_day_data_async(
                stock_code=stock_code,
                target_date=target_date,
                selected_time=target_hour
            )
            
            if historical_data is None:
                self.logger.error(f"❌ {stock_code} 전체 거래시간 분봉 데이터 조회 실패")
                # 실패 시 기존 방식으로 폴백
                return await self._collect_historical_data_fallback(stock_code)
            
            if historical_data.empty:
                self.logger.warning(f"⚠️ {stock_code} 전체 거래시간 분봉 데이터 없음")
                # 빈 DataFrame이라도 저장
                with self._lock:
                    if stock_code in self.selected_stocks:
                        self.selected_stocks[stock_code].historical_data = pd.DataFrame()
                        self.selected_stocks[stock_code].data_complete = True
                return True
            
            # 선정 시점 이전 데이터만 필터링 (추가 안전장치)
            if 'datetime' in historical_data.columns:
                # 선정 시간을 timezone-naive로 변환하여 pandas datetime64[ns]와 비교
                selected_time_naive = selected_time.replace(tzinfo=None)
                filtered_data = historical_data[historical_data['datetime'] <= selected_time_naive].copy()
            elif 'time' in historical_data.columns:
                # time 컬럼을 이용한 필터링
                selected_time_str = selected_time.strftime("%H%M%S")
                historical_data['time_str'] = historical_data['time'].astype(str).str.zfill(6)
                filtered_data = historical_data[historical_data['time_str'] <= selected_time_str].copy()
                filtered_data = filtered_data.drop('time_str', axis=1)
            else:
                # 시간 컬럼이 없으면 전체 데이터 사용
                filtered_data = historical_data.copy()
            
            # 메모리에 저장
            with self._lock:
                if stock_code in self.selected_stocks:
                    self.selected_stocks[stock_code].historical_data = filtered_data
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
                
                self.logger.info(f"✅ {stock_code} 전체 거래시간 분봉 수집 성공!")
                self.logger.info(f"   데이터 범위: {start_time} ~ {end_time} ({time_range_minutes}분)")
                self.logger.info(f"   총 분봉 수: {data_count}건")
                
                # 09:00 이전 데이터가 있는지 확인
                if start_time and start_time < "090000":
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
            result = get_inquire_time_itemchartprice(
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
            
            result = get_inquire_time_itemchartprice(
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
        종목의 과거 + 실시간 결합 차트 데이터 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 결합된 차트 데이터
        """
        try:
            with self._lock:
                if stock_code not in self.selected_stocks:
                    return None
                    
                stock_data = self.selected_stocks[stock_code]
                historical_data = stock_data.historical_data.copy()
                realtime_data = stock_data.realtime_data.copy()
            
            # 두 데이터 결합
            if historical_data.empty and realtime_data.empty:
                return pd.DataFrame()
            elif historical_data.empty:
                combined_data = realtime_data
            elif realtime_data.empty:
                combined_data = historical_data
            else:
                combined_data = pd.concat([historical_data, realtime_data], ignore_index=True)
            
            # 시간순 정렬
            if 'datetime' in combined_data.columns:
                combined_data = combined_data.sort_values('datetime').reset_index(drop=True)
            elif 'date' in combined_data.columns and 'time' in combined_data.columns:
                combined_data = combined_data.sort_values(['date', 'time']).reset_index(drop=True)
            
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
            
            # 동시 업데이트 (배치 크기 증가로 효율성 향상)
            batch_size = 20  # 배치 크기 증가
            for i in range(0, len(stock_codes), batch_size):
                batch = stock_codes[i:i + batch_size]
                tasks = [self.update_realtime_data(code) for code in batch]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # API 호출 간격 조절 (더 빠른 업데이트)
                if i + batch_size < len(stock_codes):
                    await asyncio.sleep(0.2)  # 간격 단축
            
        except Exception as e:
            self.logger.error(f"❌ 실시간 데이터 일괄 업데이트 오류: {e}")