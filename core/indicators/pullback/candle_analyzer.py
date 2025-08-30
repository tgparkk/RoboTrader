"""
캔들 분석 모듈
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from .types import CandleAnalysis


class CandleAnalyzer:
    """캔들 분석 클래스"""
    
    @staticmethod
    def is_recovery_candle(data: pd.DataFrame, index: int) -> bool:
        """회복 양봉 여부 확인"""
        if index < 0 or index >= len(data):
            return False
        
        candle = data.iloc[index]
        return candle['close'] > candle['open']  # 양봉
    
    @staticmethod
    def analyze_candle_size(data: pd.DataFrame, period: int = 20) -> Dict[str, float]:
        """캔들 크기 분석"""
        if len(data) < period:
            return {'body_ratio': 0, 'total_range': 0, 'expansion_ratio': 1.0}
        
        recent_data = data.iloc[-period:]
        current_candle = data.iloc[-1]
        
        # 캔들 몸체 크기
        current_body = abs(current_candle['close'] - current_candle['open'])
        current_range = current_candle['high'] - current_candle['low']
        
        # 몸체 비율 (전체 범위 대비)
        body_ratio = current_body / current_range if current_range > 0 else 0
        
        # 최근 평균 범위
        avg_range = (recent_data['high'] - recent_data['low']).mean()
        
        # 확대 비율
        expansion_ratio = current_range / avg_range if avg_range > 0 else 1.0
        
        return {
            'body_ratio': body_ratio,
            'total_range': current_range,
            'expansion_ratio': expansion_ratio
        }
    
    @staticmethod
    def check_overhead_supply(data: pd.DataFrame, lookback: int = 10, threshold_hits: int = 2) -> bool:
        """머리 위 물량 확인"""
        if len(data) < lookback + 1:
            return False
        
        current_high = data['high'].iloc[-1]
        
        # 과거 lookback 기간의 고가들 중 현재 고가보다 높은 것들
        past_highs = data['high'].iloc[-lookback-1:-1]  # 현재 제외
        overhead_levels = past_highs[past_highs > current_high * 1.01]  # 1% 이상 높은 수준
        
        # 임계값 이상의 머리 위 물량이 있는지 확인
        return len(overhead_levels) >= threshold_hits
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10) -> CandleAnalysis:
        """캔들 분석 (변곡캔들 검증 로직 강화)"""
        if len(data) < period:
            return CandleAnalysis(False, 0, 0, 0, 0, 'stable', False, False, False)
        
        current = data.iloc[-1]
        
        # 기본 캔들 정보
        is_bullish = current['close'] > current['open']
        body_size = abs(current['close'] - current['open'])
        
        # 캔들 실체 크기 비율 계산 (평균가 기준)
        avg_price = (current['high'] + current['low'] + current['close'] + current['open']) / 4
        body_pct = (body_size / avg_price) * 100 if avg_price > 0 else 0
        
        # 캔들 크기 계산 (high - low)
        candle_sizes = data['high'].values - data['low'].values
        current_candle_size = candle_sizes[-1]
        avg_recent_candle_size = np.mean(candle_sizes[-period:])
        
        # 캔들 크기 추세 분석
        if len(candle_sizes) >= 3:
            recent_3 = candle_sizes[-3:]
            if recent_3[-1] > recent_3[-2] > recent_3[-3]:
                candle_trend = 'expanding'
            elif recent_3[-1] < recent_3[-2] < recent_3[-3]:
                candle_trend = 'shrinking'
            else:
                candle_trend = 'stable'
        else:
            candle_trend = 'stable'
        
        # 캔들 크기 상태
        is_small_candle = current_candle_size < avg_recent_candle_size * 0.7
        is_large_candle = current_candle_size > avg_recent_candle_size * 1.3
        
        # 의미있는 실체 크기 검증 (제시된 로직: 0.5% 이상)
        is_meaningful_body = body_pct >= 0.5
        
        return CandleAnalysis(
            is_bullish=is_bullish,
            body_size=body_size,
            body_pct=body_pct,
            current_candle_size=current_candle_size,
            avg_recent_candle_size=avg_recent_candle_size,
            candle_trend=candle_trend,
            is_small_candle=is_small_candle,
            is_large_candle=is_large_candle,
            is_meaningful_body=is_meaningful_body
        )

    @staticmethod
    def check_prior_uptrend(data: pd.DataFrame, min_gain: float = 0.05) -> bool:
        """
        선행 상승 확인 (개선된 버전)
        
        조건:
        1. 당일 시가 대비 최고가가 min_gain 이상 상승 (기존 로직)
        2. 연속된 N개 봉의 누적 상승률이 min_gain 이상 (신규 추가)
        
        Args:
            data: 분봉 데이터
            min_gain: 최소 상승률 (기본값: 5%)
            
        Returns:
            bool: 선행 상승 조건 만족 여부
        """
        if len(data) < 1:
            return False
        
        try:
            # 당일 데이터 추출
            if 'datetime' in data.columns:
                dates = pd.to_datetime(data['datetime']).dt.normalize()
                today = dates.iloc[-1]
                today_data = data[dates == today].reset_index(drop=True)
                
                if len(today_data) == 0:
                    return False
            else:
                # datetime 정보가 없으면 전체 데이터를 당일로 간주
                today_data = data.copy()
            
            # 방법 1: 기존 로직 - 당일 시가 대비 최고가
            day_open = today_data['open'].iloc[0]
            day_high = today_data['high'].max()
            
            if day_open > 0:
                single_point_gain = (day_high - day_open) / day_open
                if single_point_gain >= min_gain:
                    return True  # 기존 조건 만족
            
            # 방법 2: 신규 로직 - 연속된 N개 봉의 누적 상승률
            # 다중 범위 체크: 3봉, 5봉, 7봉
            check_ranges = [3, 5, 7]
            
            for window_size in check_ranges:
                if len(today_data) < window_size:
                    continue
                
                # 슬라이딩 윈도우로 각 구간의 누적 상승률 체크
                for start_idx in range(len(today_data) - window_size + 1):
                    end_idx = start_idx + window_size - 1
                    
                    # 구간 시작가와 구간 내 최고가 비교
                    segment_start_price = today_data['open'].iloc[start_idx]
                    segment_high = today_data['high'].iloc[start_idx:end_idx+1].max()
                    
                    if segment_start_price > 0:
                        segment_gain = (segment_high - segment_start_price) / segment_start_price
                        
                        # 연속 상승 조건 추가 체크 (선택사항)
                        # 구간 내에서 지속적으로 상승하는 패턴인지 확인
                        segment_data = today_data.iloc[start_idx:end_idx+1]
                        is_sustained_uptrend = CandleAnalyzer._check_sustained_uptrend(segment_data)
                        
                        # 누적 상승률이 조건 만족하고, 지속적 상승 패턴인 경우
                        if segment_gain >= min_gain and is_sustained_uptrend:
                            return True
            
            return False
            
        except Exception:
            # 오류 시 기존 로직으로 폴백
            if len(data) >= 10:
                start_price = data['close'].iloc[-10]
                current_price = data['close'].iloc[-1]
                gain_pct = (current_price - start_price) / start_price if start_price > 0 else 0
                return gain_pct >= min_gain
            return False
    
    @staticmethod
    def _check_sustained_uptrend(segment_data: pd.DataFrame) -> bool:
        """
        구간 내 지속적 상승 패턴 확인
        
        조건:
        1. 최소 60% 이상의 봉이 상승 방향
        2. 큰 하락봉(2% 이상 하락)이 없음
        
        Args:
            segment_data: 구간 데이터
            
        Returns:
            bool: 지속적 상승 패턴 여부
        """
        try:
            if len(segment_data) < 2:
                return True  # 데이터 부족시 허용
            
            # 1. 상승 봉의 비율 체크
            price_changes = segment_data['close'].diff().iloc[1:]  # 첫 번째 NaN 제외
            if len(price_changes) == 0:
                return True
            
            up_count = (price_changes > 0).sum()
            up_ratio = up_count / len(price_changes)
            
            # 60% 이상이 상승 방향이어야 함
            if up_ratio < 0.6:
                return False
            
            # 2. 큰 하락봉 체크 (개별 봉의 하락률 2% 이상)
            for _, candle in segment_data.iterrows():
                open_price = candle['open']
                close_price = candle['close']
                
                if open_price > 0:
                    candle_change = (close_price - open_price) / open_price
                    # 개별 봉이 2% 이상 하락하면 지속적 상승 패턴 아님
                    if candle_change <= -0.02:
                        return False
            
            return True
            
        except Exception:
            return True  # 오류 시 허용

    @staticmethod
    def check_price_trend(data: pd.DataFrame, period: int = 10) -> str:
        """주가 추세 확인"""
        if len(data) < period:
            return 'stable'
        
        closes = data['close'].values
        recent_closes = closes[-period:]
        
        # 선형 회귀로 추세 판단
        x = np.arange(len(recent_closes))
        slope = np.polyfit(x, recent_closes, 1)[0]
        
        if slope > 0:
            return 'uptrend'
        elif slope < 0:
            return 'downtrend'
        else:
            return 'stable'
    
    @staticmethod
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기 (최근 5개 봉)"""
        if len(data) < period:
            return None
        
        recent_lows = data['low'].values[-period:]
        return np.min(recent_lows)