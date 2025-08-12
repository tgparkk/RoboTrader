"""
눌림목 캔들패턴 지표 (3분봉 권장)
주가 상승 후 저거래 조정(기준 거래량의 1/4) → 회복 양봉에서 거래량 회복 → 이등분선 지지/회복 확인
손절: 진입 양봉 저가 0.2% 이탈, 또는 이등분선 기준 아래로 0.2% 이탈, 또는 지지 저점 이탈
익절: 매수가 대비 +3%
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from core.indicators.bisector_line import BisectorLine


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
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기 (최근 5개 봉)"""
        if len(data) < period:
            return None
        
        recent_lows = data['low'].values[-period:]
        return np.min(recent_lows)
    
    @staticmethod
    def generate_trading_signals(data: pd.DataFrame) -> pd.DataFrame:
        """눌림목 캔들패턴 매매 신호 생성 (3분봉 권장)

        반환 컬럼:
        - buy_pullback_pattern: 저거래 조정 후 회복 양봉 매수
        - buy_bisector_recovery: 이등분선 회복/상향 돌파 매수
        - sell_bisector_break: 이등분선 기준 아래로 0.2% 이탈
        - sell_support_break: 최근 저점 이탈
        - stop_entry_low_break: 진입 양봉 저가 0.2% 이탈
        - take_profit_3pct: 매수가 대비 +3% 도달
        - bisector_line: 이등분선 값(보조)
        """
        try:
            if data is None or data.empty or len(data) < 10:
                return pd.DataFrame()

            df = data.copy()
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                return pd.DataFrame()

            # 이등분선(누적 고/저가 기반)
            bisector_line = BisectorLine.calculate_bisector_line(df['high'], df['low'])

            signals = pd.DataFrame(index=df.index)
            signals['buy_pullback_pattern'] = False
            signals['buy_bisector_recovery'] = False
            signals['sell_bisector_break'] = False
            signals['sell_support_break'] = False
            signals['stop_entry_low_break'] = False
            signals['take_profit_3pct'] = False
            signals['bisector_line'] = bisector_line

            # 파라미터 (완화 적용)
            retrace_lookback = 2      # 저거래 조정 연속 봉 (기존 3 → 2)
            low_vol_ratio = 0.25      # 기준 거래량의 25% 
            stop_leeway = 0.002       # 0.2%
            take_profit = 0.03        # +3%

            # 기준 거래량(최근 50봉 최대)을 시계열로 계산
            rolling_baseline = df['volume'].rolling(window=min(50, len(df)), min_periods=1).max()

            # 포지션 추적(차트 표시용 시뮬레이션)
            in_position = False
            entry_price = None
            entry_low = None

            for i in range(len(df)):
                if i < retrace_lookback + 2:
                    continue

                current = df.iloc[i]
                bl = bisector_line.iloc[i] if not pd.isna(bisector_line.iloc[i]) else None
                # 위/아래 판단 (pullback 용도): 종가가 이등분선 이상이면 위로 간주
                above_bisector = (bl is not None) and (current['close'] >= bl)
                # 이등분선 회복(매수) 엄격 조건: 종가가 이등분선을 '넘어야' 함(>)
                crosses_bisector_up = (bl is not None) and (current['open'] <= bl and current['close'] > bl)

                # 최근 저점(최근 5봉 저가 최저)
                recent_low = float(df['low'].iloc[max(0, i-5):i+1].min())

                # 최근 N봉 저거래 하락 조정
                window = df.iloc[i - retrace_lookback:i]
                baseline_now = rolling_baseline.iloc[i]
                low_volume_all = (window['volume'] < baseline_now * low_vol_ratio).all()
                downtrend_all = (window['close'].diff().fillna(0) < 0).iloc[1:].all()
                is_low_volume_retrace = low_volume_all and downtrend_all

                # 회복 양봉 + 거래량 회복
                is_bullish = current['close'] > current['open']
                max_low_vol = float(window['volume'].max())
                avg_recent_vol = float(df['volume'].iloc[max(0, i-10):i].mean()) if i > 0 else 0.0
                volume_recovers = (current['volume'] > max_low_vol) or (current['volume'] > avg_recent_vol)

                # 대안 진입 조건: "직전 강한 양봉의 1/2 구간 되돌림" 확인
                # 최근 6개의 봉에서 강한 양봉(몸통이 최근 평균 대비 크고, 거래량이 평균 이상)을 찾음
                recent_start = max(0, i-12)
                recent_range = df.iloc[recent_start:i]
                half_retrace_ok = False
                if len(recent_range) > 0:
                    recent_candle_size = (recent_range['high'] - recent_range['low']).mean()
                    recent_vol_mean = recent_range['volume'].mean()
                    impulse_idx = None
                    for j in range(i-1, recent_start-1, -1):
                        if j < 0:
                            break
                        open_j = float(df['open'].iloc[j])
                        close_j = float(df['close'].iloc[j])
                        high_j = float(df['high'].iloc[j])
                        low_j = float(df['low'].iloc[j])
                        vol_j = float(df['volume'].iloc[j])
                        body = abs(close_j - open_j)
                        size = high_j - low_j
                        # 완화: 최근 평균 대비 0.8배 이상 몸통, 거래량 0.8배 이상
                        if close_j > open_j and size > 0 and body >= recent_candle_size * 0.8 and vol_j >= recent_vol_mean * 0.8:
                            impulse_idx = j
                            break
                    if impulse_idx is not None:
                        ih = float(df['high'].iloc[impulse_idx])
                        il = float(df['low'].iloc[impulse_idx])
                        half_point = il + (ih - il) * 0.5
                        # 현재 캔들이 절반값 근처이거나, 저가가 하회 후 회복해 종가가 절반 이상
                        eps = max(half_point * 0.01, 1.0)  # 1.0% 또는 1원 허용 (완화)
                        cur_low = float(current['low'])
                        cur_close = float(current['close'])
                        if (abs(cur_close - half_point) <= eps) or (cur_low <= half_point <= cur_close):
                            half_retrace_ok = True

                if not in_position:
                    # 매수 신호 1: 저거래 조정 후 회복 양봉(+이등분선 지지/회복)
                    # 또는 강한 양봉의 1/2 되돌림 + 회복 양봉(+이등분선 지지/회복)
                    # 완화: 1/2 되돌림 케이스에서는 거래량 회복(volume_recovers)을 필수에서 제외
                    if (
                        (is_low_volume_retrace and is_bullish and volume_recovers and (above_bisector or crosses_bisector_up))
                        or
                        (half_retrace_ok and is_bullish and (above_bisector or crosses_bisector_up))
                    ):
                        signals.iloc[i, signals.columns.get_loc('buy_pullback_pattern')] = True
                        in_position = True
                        entry_price = float(current['close'])
                        entry_low = float(current['low'])
                        continue

                    # 매수 신호 2: 이등분선 회복 양봉(종가가 이등분선을 넘어야 함) + 거래량 회복
                    if is_bullish and crosses_bisector_up and volume_recovers:
                        signals.iloc[i, signals.columns.get_loc('buy_bisector_recovery')] = True
                        in_position = True
                        entry_price = float(current['close'])
                        entry_low = float(current['low'])
                        continue
                else:
                    # 손절/익절 신호
                    # 이등분선 이탈: 이등분선 기준 아래로 0.2% 이탈 시 매도
                    if bl is not None and current['close'] < bl * (1.0 - 0.002):
                        signals.iloc[i, signals.columns.get_loc('sell_bisector_break')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

                    if current['close'] < recent_low:
                        signals.iloc[i, signals.columns.get_loc('sell_support_break')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

                    if entry_low is not None and current['close'] <= entry_low * (1.0 - stop_leeway):
                        signals.iloc[i, signals.columns.get_loc('stop_entry_low_break')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

                    if entry_price is not None and current['close'] >= entry_price * (1.0 + take_profit):
                        signals.iloc[i, signals.columns.get_loc('take_profit_3pct')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

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