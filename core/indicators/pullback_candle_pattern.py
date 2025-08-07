"""
눌림목 캔들패턴 지표
주가 상승 + 거래량 하락 → 조정 → 거래량 증가 + 캔들 확대 패턴 감지
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class VolumeAnalysis:
    """거래량 분석 결과"""
    baseline_volume: float  # 기준 거래량 (당일 최대량)
    current_volume: float   # 현재 거래량
    avg_recent_volume: float  # 최근 평균 거래량
    volume_trend: str      # 'increasing', 'decreasing', 'stable'
    is_volume_surge: bool  # 거래량 급증 여부
    is_low_volume: bool    # 저거래량 여부 (기준의 1/4 이하)
    is_high_volume: bool   # 고거래량 여부 (기준의 1/2 이상)


@dataclass
class CandleAnalysis:
    """캔들 분석 결과"""
    current_candle_size: float    # 현재 캔들 크기 (high-low)
    avg_recent_candle_size: float # 최근 평균 캔들 크기
    candle_trend: str            # 'expanding', 'shrinking', 'stable'
    is_small_candle: bool        # 작은 캔들 여부
    is_large_candle: bool        # 큰 캔들 여부


class PullbackCandlePattern:
    """눌림목 캔들패턴 분석기"""
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10) -> VolumeAnalysis:
        """거래량 분석"""
        if 'volume' not in data.columns or len(data) < period:
            return VolumeAnalysis(0, 0, 0, 'stable', False, False, False)
        
        volumes = data['volume'].values
        current_volume = volumes[-1]
        
        # 기준 거래량: 당일 최대 거래량 (최근 50봉 중)
        baseline_volume = np.max(volumes[-min(50, len(volumes)):])
        
        # 최근 평균 거래량
        avg_recent_volume = np.mean(volumes[-period:])
        
        # 거래량 추세 분석
        if len(volumes) >= 3:
            recent_3 = volumes[-3:]
            if recent_3[-1] > recent_3[-2] > recent_3[-3]:
                volume_trend = 'increasing'
            elif recent_3[-1] < recent_3[-2] < recent_3[-3]:
                volume_trend = 'decreasing'
            else:
                volume_trend = 'stable'
        else:
            volume_trend = 'stable'
        
        # 거래량 상태 분석
        is_volume_surge = current_volume > avg_recent_volume * 1.5
        is_low_volume = current_volume < baseline_volume * 0.25  # 기준의 1/4 이하
        is_high_volume = current_volume > baseline_volume * 0.5  # 기준의 1/2 이상
        
        return VolumeAnalysis(
            baseline_volume=baseline_volume,
            current_volume=current_volume,
            avg_recent_volume=avg_recent_volume,
            volume_trend=volume_trend,
            is_volume_surge=is_volume_surge,
            is_low_volume=is_low_volume,
            is_high_volume=is_high_volume
        )
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10) -> CandleAnalysis:
        """캔들 분석"""
        if len(data) < period:
            return CandleAnalysis(0, 0, 'stable', False, False)
        
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
        
        return CandleAnalysis(
            current_candle_size=current_candle_size,
            avg_recent_candle_size=avg_recent_candle_size,
            candle_trend=candle_trend,
            is_small_candle=is_small_candle,
            is_large_candle=is_large_candle
        )
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위에 있는지 확인"""
        try:
            from core.indicators.bisector_line import BisectorLine
            bisector_signals = BisectorLine.generate_trading_signals(data)
            return bisector_signals['bullish_zone'].iloc[-1]
        except:
            return False
    
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
    def find_recent_low(data: pd.DataFrame, period: int = 20) -> Optional[float]:
        """최근 저점 찾기"""
        if len(data) < period:
            return None
        
        recent_lows = data['low'].values[-period:]
        return np.min(recent_lows)
    
    @staticmethod
    def generate_trading_signals(data: pd.DataFrame) -> pd.DataFrame:
        """눌림목 캔들패턴 매매 신호 생성"""
        try:
            if len(data) < 20:
                return pd.DataFrame()
            
            # 기본 신호 DataFrame 생성
            signals = pd.DataFrame(index=data.index)
            signals['buy_pullback_pattern'] = False
            signals['buy_bisector_recovery'] = False
            signals['sell_bisector_break'] = False
            signals['sell_support_break'] = False
            signals['sell_high_volume'] = False
            
            # 각 시점별로 신호 계산
            for i in range(19, len(data)):  # 최소 20개 데이터 필요
                current_data = data.iloc[:i+1]
                
                # 거래량 및 캔들 분석
                volume_analysis = PullbackCandlePattern.analyze_volume(current_data)
                candle_analysis = PullbackCandlePattern.analyze_candle(current_data)
                
                # 주가 추세 및 이등분선 위치
                price_trend = PullbackCandlePattern.check_price_trend(current_data)
                above_bisector = PullbackCandlePattern.check_price_above_bisector(current_data)
                recent_low = PullbackCandlePattern.find_recent_low(current_data)
                
                current_price = current_data['close'].iloc[-1]
                current_low = current_data['low'].iloc[-1]
                
                # === 매수 신호 1: 눌림목 캔들패턴 ===
                # 조건 1: 주가가 이등분선 위에 있음
                # 조건 2: 최근 거래량이 증가 추세
                # 조건 3: 캔들이 확대 추세
                # 조건 4: 현재 거래량이 저거래량에서 벗어남
                if (above_bisector and 
                    volume_analysis.volume_trend == 'increasing' and
                    candle_analysis.candle_trend == 'expanding' and
                    not volume_analysis.is_low_volume and
                    volume_analysis.current_volume > volume_analysis.avg_recent_volume):
                    signals.loc[current_data.index[-1], 'buy_pullback_pattern'] = True
                
                # === 매수 신호 2: 이등분선 회복 패턴 ===
                # 이등분선 이탈 후 다시 돌파하면서 거래량 증가
                if (above_bisector and 
                    volume_analysis.volume_trend == 'increasing' and
                    volume_analysis.is_volume_surge):
                    # 최근에 이등분선 아래에 있었는지 확인
                    if i >= 23:  # 3개 전 데이터 확인 가능
                        prev_data = data.iloc[:i-2]
                        prev_above_bisector = PullbackCandlePattern.check_price_above_bisector(prev_data)
                        if not prev_above_bisector:
                            signals.loc[current_data.index[-1], 'buy_bisector_recovery'] = True
                
                # === 매도 신호 1: 이등분선 이탈 ===
                if not above_bisector:
                    signals.loc[current_data.index[-1], 'sell_bisector_break'] = True
                
                # === 매도 신호 2: 지지 저점 이탈 ===
                if recent_low and current_low < recent_low * 0.99:  # 1% 아래로 이탈
                    signals.loc[current_data.index[-1], 'sell_support_break'] = True
                
                # === 매도 신호 3: 고거래량 하락 ===
                if (volume_analysis.is_high_volume and 
                    price_trend == 'downtrend'):
                    signals.loc[current_data.index[-1], 'sell_high_volume'] = True
            
            return signals
            
        except Exception as e:
            print(f"눌림목 캔들패턴 신호 생성 오류: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def get_pattern_info(data: pd.DataFrame) -> Dict:
        """현재 패턴 정보 반환"""
        try:
            if len(data) < 20:
                return {}
            
            volume_analysis = PullbackCandlePattern.analyze_volume(data)
            candle_analysis = PullbackCandlePattern.analyze_candle(data)
            price_trend = PullbackCandlePattern.check_price_trend(data)
            above_bisector = PullbackCandlePattern.check_price_above_bisector(data)
            
            return {
                'price_trend': price_trend,
                'above_bisector': above_bisector,
                'volume_trend': volume_analysis.volume_trend,
                'candle_trend': candle_analysis.candle_trend,
                'baseline_volume': volume_analysis.baseline_volume,
                'current_volume': volume_analysis.current_volume,
                'volume_ratio': volume_analysis.current_volume / volume_analysis.baseline_volume if volume_analysis.baseline_volume > 0 else 0,
                'is_low_volume': volume_analysis.is_low_volume,
                'is_high_volume': volume_analysis.is_high_volume,
                'current_candle_size': candle_analysis.current_candle_size,
                'avg_candle_size': candle_analysis.avg_recent_candle_size,
                'is_small_candle': candle_analysis.is_small_candle,
                'is_large_candle': candle_analysis.is_large_candle
            }
            
        except Exception as e:
            print(f"패턴 정보 분석 오류: {e}")
            return {}