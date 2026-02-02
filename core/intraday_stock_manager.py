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
from config.market_hours import MarketHours
from api.kis_market_api import get_inquire_price
from core.realtime_data_logger import log_intraday_data
from core.dynamic_batch_calculator import DynamicBatchCalculator
from core.intraday_data_utils import validate_minute_data_continuity
from core.post_market_data_saver import PostMarketDataSaver


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
        self.max_stocks = 80  # 최대 관리 종목 수

        # 동기화
        self._lock = threading.RLock()

        # 동적 배치 계산기
        self.batch_calculator = DynamicBatchCalculator()

        # 장 마감 후 데이터 저장기
        self.data_saver = PostMarketDataSaver()

        # 헬퍼 클래스 초기화 (리팩토링)
        from core.historical_data_collector import HistoricalDataCollector
        from core.realtime_data_updater import RealtimeDataUpdater
        from core.data_quality_checker import DataQualityChecker

        self._historical_collector = HistoricalDataCollector(self)
        self._realtime_updater = RealtimeDataUpdater(self)
        self._quality_checker = DataQualityChecker(self)

        self.logger.info("[초기화] 장중 종목 관리자 초기화 완료")
    
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

            # 🆕 시장 시작 5분 이내 선정이고 데이터 부족한 경우 플래그 설정 (동적 시간 적용)
            market_hours = MarketHours.get_market_hours('KRX', current_time)
            market_open = market_hours['market_open']
            open_hour = market_open.hour
            open_minute = market_open.minute

            is_early_selection = (current_time.hour == open_hour and current_time.minute < open_minute + 5)

            if not success and is_early_selection:
                self.logger.warning(f"⚠️ {stock_code} 시장 시작 5분 이내 데이터 부족, batch_update에서 재시도 필요")
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
        """당일 전체 분봉 데이터 수집 (HistoricalDataCollector 위임)"""
        return await self._historical_collector.collect_historical_data(stock_code)
    
    async def _collect_historical_data_fallback(self, stock_code: str) -> bool:
        """과거 분봉 데이터 수집 폴백 (HistoricalDataCollector 위임)"""
        return await self._historical_collector.collect_historical_data_fallback(stock_code)
    
    def _validate_minute_data_continuity(self, data: pd.DataFrame, stock_code: str) -> dict:
        """1분봉 데이터 연속성 검증 (래퍼 함수)"""
        return validate_minute_data_continuity(data, stock_code, self.logger)
    
    async def update_realtime_data(self, stock_code: str) -> bool:
        """실시간 분봉 데이터 업데이트 (RealtimeDataUpdater 위임)"""
        return await self._realtime_updater.update_realtime_data(stock_code)
    
    def _check_sufficient_base_data(self, combined_data: Optional[pd.DataFrame], stock_code: str) -> bool:
        """기본 데이터 충분성 체크 (RealtimeDataUpdater 위임)"""
        return self._realtime_updater._check_sufficient_base_data(combined_data, stock_code)

    async def _get_latest_minute_bar(self, stock_code: str, current_time: datetime) -> Optional[pd.DataFrame]:
        """최신 분봉 수집 (RealtimeDataUpdater 위임)"""
        return await self._realtime_updater._get_latest_minute_bar(stock_code, current_time)
    
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
        종목의 당일 전체 차트 데이터 조회 (09:00~현재, 완성된 봉만)
        
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
                self.logger.debug(f"📊 {stock_code} 과거 데이터만 사용: {len(combined_data)}건 (realtime_data 아직 없음)")
                
                # 데이터 부족 시 자동 수집 시도
                if len(combined_data) < 15:
                    try:
                        from trade_analysis.data_sufficiency_checker import collect_minute_data_from_api
                        from utils.korean_time import now_kst
                        
                        today = now_kst().strftime('%Y%m%d')
                        self.logger.info(f"🔄 {stock_code} 데이터 부족으로 자동 수집 시도...")
                        
                        # API에서 직접 분봉 데이터 수집
                        minute_data = collect_minute_data_from_api(stock_code, today)
                        if minute_data is not None and not minute_data.empty:
                            # 🆕 캐시 저장 제거 (15:30 장 마감 시에만 저장)
                            # 메모리에만 저장
                            
                            # historical_data에 추가
                            with self._lock:
                                if stock_code in self.selected_stocks:
                                    self.selected_stocks[stock_code].historical_data = minute_data
                                    self.selected_stocks[stock_code].data_complete = True
                                    self.selected_stocks[stock_code].last_update = now_kst()
                            
                            # 수정된 데이터로 다시 결합
                            combined_data = minute_data.copy()
                            self.logger.info(f"✅ {stock_code} 자동 수집 완료: {len(combined_data)}개 (메모리에만 저장)")
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
                #self.logger.warning(f"⚠️ {stock_code} 당일 외 데이터 {removed}건 제거: {before_filter_count} → {len(combined_data)}건")

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

            # 🆕 장 마감 시 메모리 데이터 자동 저장 (분봉 + 일봉) - 동적 시간 적용
            current_time = now_kst()
            market_hours = MarketHours.get_market_hours('KRX', current_time)
            market_close = market_hours['market_close']
            close_hour = market_close.hour
            close_minute = market_close.minute

            if current_time.hour == close_hour and current_time.minute >= close_minute:
                if not hasattr(self, '_data_saved_today'):
                    self.logger.info(f"🔔 {close_hour}:{close_minute:02d} 장 마감 데이터 저장 시작...")
                    # PostMarketDataSaver를 통해 모든 데이터 저장
                    self.data_saver.save_all_data(self)
                    self._data_saved_today = True  # 하루에 한 번만 저장
                    self.logger.info(f"✅ {close_hour}:{close_minute:02d} 장 마감 데이터 저장 완료")

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
                                        # 🔥 핵심: selected_time을 현재 시간으로 업데이트하여 재수집 시 현재까지 데이터 수집
                                        with self._lock:
                                            if stock_code in self.selected_stocks:
                                                current_time = now_kst()
                                                old_time = self.selected_stocks[stock_code].selected_time
                                                self.selected_stocks[stock_code].selected_time = current_time
                                                self.logger.info(
                                                    f"⏰ {stock_code} selected_time 업데이트: "
                                                    f"{old_time.strftime('%H:%M:%S')} → {current_time.strftime('%H:%M:%S')}"
                                                )

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
                #self.logger.debug(f"✅ 실시간 데이터 업데이트 완료: 분봉 {successful_minute_updates}/{total_stocks} ({minute_success_rate:.1f}%), "
                #                f"현재가 {successful_price_updates}/{total_stocks} ({price_success_rate:.1f}%)")
                pass
            
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
        """실시간 데이터 품질 검사 (DataQualityChecker 위임)"""
        return self._quality_checker.check_data_quality(stock_code)

    def _validate_today_data(self, data: pd.DataFrame) -> List[str]:
        """당일 데이터인지 검증"""
        from core.intraday_data_utils import validate_today_data
        return validate_today_data(data)


    def _save_minute_data_to_cache(self):
        """
        [DEPRECATED] 이 메서드는 더 이상 사용되지 않습니다.
        대신 PostMarketDataSaver.save_minute_data_to_cache() 사용

        메모리에 있는 모든 종목의 분봉 데이터를 cache/minute_data에 pickle로 저장
        시뮬레이션 데이터와 비교용 (15:30 장 마감 시)
        """
        self.logger.warning("⚠️ _save_minute_data_to_cache는 deprecated입니다. PostMarketDataSaver를 사용하세요.")
        return self.data_saver.save_minute_data_to_cache(self)

    def _save_minute_data_to_file(self):
        """
        [DEPRECATED] 이 메서드는 더 이상 사용되지 않습니다.
        대신 PostMarketDataSaver.save_minute_data_to_file() 사용

        메모리에 있는 모든 종목의 분봉 데이터를 텍스트 파일로 저장 (15:30 장 마감 시)
        """
        self.logger.warning("⚠️ _save_minute_data_to_file은 deprecated입니다. PostMarketDataSaver를 사용하세요.")
        return self.data_saver.save_minute_data_to_file(self)

