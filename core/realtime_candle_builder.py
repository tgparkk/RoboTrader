#!/usr/bin/env python3
"""
실시간 1분봉 생성기 - 현재가 API를 이용해서 진행 중인 1분봉을 실시간으로 생성
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
from dataclasses import dataclass, field
import threading

from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open
from api.kis_market_api import get_inquire_price


logger = setup_logger(__name__)


@dataclass
class RealtimeCandle:
    """실시간 생성 중인 1분봉 데이터"""
    stock_code: str
    start_time: datetime  # 분봉 시작 시간 (예: 10:05:00)
    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    close_price: float = 0  # 현재가 (계속 업데이트)
    volume: int = 0
    last_update: Optional[datetime] = None
    is_complete: bool = False


class RealtimeCandleBuilder:
    """
    실시간 1분봉 생성기
    
    현재가 API를 이용해서 진행 중인 1분봉을 실시간으로 생성하여
    3분봉 매매 판단 시 지연을 최소화합니다.
    """
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        
        # 종목별 실시간 생성 중인 1분봉 캐시
        self._realtime_candles: Dict[str, RealtimeCandle] = {}
        
        # 동기화
        self._lock = threading.RLock()
        
        self.logger.info("🕐 실시간 1분봉 생성기 초기화 완료")
    
    def get_missing_completed_candle(self, stock_code: str, target_minute: datetime, stock_name: str = "") -> Optional[pd.DataFrame]:
        """
        API 지연으로 누락된 완성 1분봉 데이터 생성
        
        이미 완성되었지만 API에서 아직 제공되지 않은 1분봉을 현재가 API로 추정 생성
        
        Args:
            stock_code: 종목코드
            target_minute: 목표 분봉 시간 (예: 10:05:00)
            stock_name: 종목명 (로깅용)
            
        Returns:
            pd.DataFrame: 추정 생성된 완성 1분봉 (1행) 또는 None
        """
        try:
            if not is_market_open():
                return None
                
            current_time = now_kst()
            
            # 목표 분봉이 이미 완성된 시간인지 확인 (현재시간이 목표분+1분 이후)
            target_end = target_minute + timedelta(minutes=1)
            if current_time < target_end:
                # 아직 완성되지 않은 분봉은 생성하지 않음
                return None
            
            with self._lock:
                cache_key = f"{stock_code}_{target_minute.strftime('%H%M')}"
                
                # 이미 생성한 캐시가 있으면 반환
                if cache_key in self._realtime_candles:
                    cached_candle = self._realtime_candles[cache_key]
                    if cached_candle.is_complete:
                        return self._candle_to_dataframe(cached_candle)
                
                # 새로운 완성 추정 캔들 생성
                return self._create_completed_candle_estimation(stock_code, target_minute, cache_key)
                    
        except Exception as e:
            self.logger.error(f"❌ {stock_code} API 지연 분봉 생성 오류: {e}")
            return None

    def get_current_minute_candle(self, stock_code: str, stock_name: str = "") -> Optional[pd.DataFrame]:
        """
        현재 진행 중인 1분봉 데이터 조회/생성 (기존 방식 유지)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명 (로깅용)
            
        Returns:
            pd.DataFrame: 현재 진행 중인 1분봉 (1행) 또는 None
        """
        try:
            if not is_market_open():
                return None
                
            current_time = now_kst()
            
            # 현재 분의 시작 시간 계산 (예: 10:05:30 → 10:05:00)
            minute_start = current_time.replace(second=0, microsecond=0)
            
            with self._lock:
                # 기존 캐시된 캔들이 있는지 확인
                if stock_code in self._realtime_candles:
                    cached_candle = self._realtime_candles[stock_code]
                    
                    # 같은 분봉이면 업데이트, 다른 분봉이면 새로 생성
                    if cached_candle.start_time == minute_start:
                        return self._update_candle(stock_code, cached_candle)
                    else:
                        # 이전 분봉은 완료 처리하고 새 분봉 시작
                        cached_candle.is_complete = True
                        return self._create_new_candle(stock_code, minute_start)
                else:
                    # 새로운 종목의 첫 캔들 생성
                    return self._create_new_candle(stock_code, minute_start)
                    
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 실시간 1분봉 생성 오류: {e}")
            return None
    
    def _create_new_candle(self, stock_code: str, minute_start: datetime) -> Optional[pd.DataFrame]:
        """새로운 실시간 1분봉 생성"""
        try:
            # 현재가 API 호출
            price_info = get_inquire_price(stock_code)
            if not price_info:
                return None
            
            current_price = float(price_info.get('stck_prpr', 0))  # 주식 현재가
            if current_price <= 0:
                return None
            
            # 새 캔들 생성 (시가=고가=저가=종가=현재가로 시작)
            new_candle = RealtimeCandle(
                stock_code=stock_code,
                start_time=minute_start,
                open_price=current_price,
                high_price=current_price,
                low_price=current_price,
                close_price=current_price,
                volume=int(price_info.get('acml_vol', 0)),  # 누적거래량
                last_update=now_kst()
            )
            
            self._realtime_candles[stock_code] = new_candle
            
            self.logger.debug(f"🆕 {stock_code} 새 실시간 1분봉 생성: {minute_start.strftime('%H:%M')} @{current_price:,}")
            
            return self._candle_to_dataframe(new_candle)
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 새 실시간 1분봉 생성 오류: {e}")
            return None
    
    def _update_candle(self, stock_code: str, candle: RealtimeCandle) -> Optional[pd.DataFrame]:
        """기존 실시간 1분봉 업데이트"""
        try:
            # 현재가 API 호출
            price_info = get_inquire_price(stock_code)
            if not price_info:
                return self._candle_to_dataframe(candle)  # API 실패 시 기존 데이터 반환
            
            current_price = float(price_info.get('stck_prpr', 0))
            current_volume = int(price_info.get('acml_vol', 0))
            
            if current_price <= 0:
                return self._candle_to_dataframe(candle)
            
            # 가격 업데이트
            candle.close_price = current_price
            candle.high_price = max(candle.high_price, current_price)
            candle.low_price = min(candle.low_price, current_price)
            candle.volume = current_volume
            candle.last_update = now_kst()
            
            self.logger.debug(f"🔄 {stock_code} 실시간 1분봉 업데이트: {candle.start_time.strftime('%H:%M')} @{current_price:,} (H:{candle.high_price:,} L:{candle.low_price:,})")
            
            return self._candle_to_dataframe(candle)
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 실시간 1분봉 업데이트 오류: {e}")
            return self._candle_to_dataframe(candle)  # 오류 시 기존 데이터 반환
    
    def _create_completed_candle_estimation(self, stock_code: str, target_minute: datetime, cache_key: str) -> Optional[pd.DataFrame]:
        """완성된 1분봉 추정 생성 (API 지연 대응)"""
        try:
            # 현재가 API 호출
            price_info = get_inquire_price(stock_code)
            if not price_info:
                return None
            
            current_price = float(price_info.get('stck_prpr', 0))  # 주식 현재가
            if current_price <= 0:
                return None
            
            # 완성된 캔들로 추정 생성 (시가=고가=저가=종가=현재가)
            # 실제로는 해당 분봉의 OHLC가 다를 수 있지만, API 지연 대응을 위한 근사치
            estimated_candle = RealtimeCandle(
                stock_code=stock_code,
                start_time=target_minute,
                open_price=current_price,  # 추정: 현재가로 설정
                high_price=current_price,  # 추정: 현재가로 설정
                low_price=current_price,   # 추정: 현재가로 설정
                close_price=current_price,
                volume=int(price_info.get('acml_vol', 0)),  # 누적거래량
                last_update=now_kst(),
                is_complete=True  # 이미 완성된 시간대이므로 완성으로 표시
            )
            
            self._realtime_candles[cache_key] = estimated_candle
            
            self.logger.debug(f"⚡ {stock_code} API 지연 분봉 추정 생성: {target_minute.strftime('%H:%M')} @{current_price:,} (완성됨)")
            
            return self._candle_to_dataframe(estimated_candle)
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 완성 분봉 추정 생성 오류: {e}")
            return None
    
    def _candle_to_dataframe(self, candle: RealtimeCandle) -> pd.DataFrame:
        """RealtimeCandle을 DataFrame으로 변환"""
        try:
            data = {
                'datetime': [candle.start_time],
                'date': [candle.start_time.strftime('%Y%m%d')],
                'time': [candle.start_time.strftime('%H%M%S')],
                'open': [candle.open_price],
                'high': [candle.high_price],
                'low': [candle.low_price],
                'close': [candle.close_price],
                'volume': [candle.volume],
                'is_realtime': [True],  # 실시간 생성된 캔들임을 표시
                'is_complete': [candle.is_complete]
            }
            
            return pd.DataFrame(data)
            
        except Exception as e:
            self.logger.error(f"❌ 캔들 DataFrame 변환 오류: {e}")
            return pd.DataFrame()
    
    def fill_missing_candles_and_combine(self, stock_code: str, historical_data: pd.DataFrame) -> pd.DataFrame:
        """
        과거 분봉 데이터 + API 지연으로 누락된 완성 분봉 + 현재 진행 중인 실시간 분봉 결합
        
        Args:
            stock_code: 종목코드
            historical_data: 과거 완성된 분봉 데이터 (API에서 받은 것)
            
        Returns:
            pd.DataFrame: 완전한 분봉 데이터 (누락 분봉 보완 + 실시간 분봉)
        """
        try:
            if historical_data is None or historical_data.empty:
                return pd.DataFrame()
            
            current_time = now_kst()
            result_data = historical_data.copy()
            
            # 1. API 지연으로 누락된 완성 분봉들을 탐지하고 추가
            if 'datetime' in result_data.columns:
                last_data_time = pd.to_datetime(result_data['datetime'].iloc[-1])
                
                # 마지막 데이터 시간부터 현재까지 1분 간격으로 누락된 분봉 확인
                check_time = last_data_time + timedelta(minutes=1)
                
                while check_time + timedelta(minutes=1) <= current_time:  # 완성된 분봉만
                    # 해당 시간의 분봉이 이미 존재하는지 확인
                    existing = result_data[pd.to_datetime(result_data['datetime']) == check_time]
                    
                    if existing.empty:
                        # 누락된 완성 분봉을 추정 생성
                        missing_candle = self.get_missing_completed_candle(stock_code, check_time)
                        if missing_candle is not None and not missing_candle.empty:
                            result_data = pd.concat([result_data, missing_candle], ignore_index=True)
                            self.logger.info(f"⚡ {stock_code} 누락 분봉 보완: {check_time.strftime('%H:%M')}")
                    
                    check_time += timedelta(minutes=1)
            
            # 2. 현재 진행 중인 1분봉 추가 (기존 로직)
            current_candle = self.get_current_minute_candle(stock_code)
            if current_candle is not None and not current_candle.empty:
                result_data = pd.concat([result_data, current_candle], ignore_index=True)
            
            # 3. 시간순 정렬
            if 'datetime' in result_data.columns:
                result_data = result_data.sort_values('datetime').reset_index(drop=True)
            
            added_count = len(result_data) - len(historical_data)
            if added_count > 0:
                self.logger.debug(f"📊 {stock_code} 데이터 보완: 원본 {len(historical_data)}건 + 추가 {added_count}건 = 총 {len(result_data)}건")
            
            return result_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 누락 분봉 보완 오류: {e}")
            return historical_data  # 오류 시 원본 데이터 반환

    def combine_with_historical_data(self, stock_code: str, historical_data: pd.DataFrame) -> pd.DataFrame:
        """
        과거 분봉 데이터 + 현재 진행 중인 실시간 1분봉 결합 (기존 방식)
        
        Args:
            stock_code: 종목코드
            historical_data: 과거 완성된 분봉 데이터
            
        Returns:
            pd.DataFrame: 과거 데이터 + 실시간 현재 분봉
        """
        try:
            if historical_data is None or historical_data.empty:
                return pd.DataFrame()
            
            # 현재 진행 중인 1분봉 가져오기
            current_candle = self.get_current_minute_candle(stock_code)
            
            if current_candle is None or current_candle.empty:
                return historical_data
            
            # 과거 데이터와 현재 진행 중인 캔들 결합
            combined_data = pd.concat([historical_data, current_candle], ignore_index=True)
            
            # 시간순 정렬
            if 'datetime' in combined_data.columns:
                combined_data = combined_data.sort_values('datetime').reset_index(drop=True)
            
            self.logger.debug(f"📊 {stock_code} 데이터 결합: 과거 {len(historical_data)}건 + 실시간 1건 = 총 {len(combined_data)}건")
            
            return combined_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 데이터 결합 오류: {e}")
            return historical_data  # 오류 시 과거 데이터만 반환
    
    def cleanup_old_candles(self, hours_threshold: int = 1):
        """오래된 실시간 캔들 정리"""
        try:
            with self._lock:
                current_time = now_kst()
                threshold_time = current_time - timedelta(hours=hours_threshold)
                
                old_codes = []
                for stock_code, candle in self._realtime_candles.items():
                    if candle.last_update and candle.last_update < threshold_time:
                        old_codes.append(stock_code)
                
                for code in old_codes:
                    del self._realtime_candles[code]
                    
                if old_codes:
                    self.logger.info(f"🗑️ 실시간 캔들 정리: {len(old_codes)}개 종목 제거")
                    
        except Exception as e:
            self.logger.error(f"❌ 실시간 캔들 정리 오류: {e}")


# 전역 인스턴스 (싱글톤 패턴)
_realtime_candle_builder = None


def get_realtime_candle_builder() -> RealtimeCandleBuilder:
    """실시간 캔들 빌더 인스턴스 가져오기 (싱글톤)"""
    global _realtime_candle_builder
    if _realtime_candle_builder is None:
        _realtime_candle_builder = RealtimeCandleBuilder()
    return _realtime_candle_builder