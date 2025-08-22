"""
눌림목 캔들패턴 지표 (3분봉 권장)
주가 상승 후 저거래 조정(기준 거래량의 1/4) → 회복 양봉에서 거래량 회복 → 이등분선 지지/회복 확인
손절: 진입 양봉 저가 0.2% 이탈, 또는 이등분선 기준 아래로 0.2% 이탈, 또는 지지 저점 이탈
익절: 매수가 대비 +3%
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
import logging
from utils.logger import setup_logger
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
from core.indicators.bisector_line import BisectorLine


class SignalType(Enum):
    """신호 타입"""
    STRONG_BUY = "STRONG_BUY"
    CAUTIOUS_BUY = "CAUTIOUS_BUY" 
    WAIT = "WAIT"
    AVOID = "AVOID"
    SELL = "SELL"


class BisectorStatus(Enum):
    """이등분선 상태"""
    HOLDING = "HOLDING"        # 현재가 >= 이등분선
    NEAR_SUPPORT = "NEAR_SUPPORT"  # 이등분선 ± 0.5% 범위
    BROKEN = "BROKEN"          # 현재가 < 이등분선 - 0.5%


class RiskSignal(Enum):
    """위험 신호 타입"""
    LARGE_BEARISH_VOLUME = "LARGE_BEARISH_VOLUME"  # 장대음봉 + 대량거래량
    BISECTOR_BREAK = "BISECTOR_BREAK"              # 이등분선 이탈
    ENTRY_LOW_BREAK = "ENTRY_LOW_BREAK"            # 변곡캔들 저가 이탈
    SUPPORT_BREAK = "SUPPORT_BREAK"                # 지지 저점 이탈
    TARGET_REACHED = "TARGET_REACHED"              # 목표 수익 달성


@dataclass
class SignalStrength:
    """신호 강도 정보"""
    signal_type: SignalType
    confidence: float          # 0-100 신뢰도
    target_profit: float       # 목표 수익률
    reasons: List[str]         # 신호 근거
    volume_ratio: float        # 거래량 비율
    bisector_status: BisectorStatus  # 이등분선 상태


@dataclass
class VolumeAnalysis:
    """거래량 분석 결과"""
    baseline_volume: float     # 기준 거래량 (당일 최대량)
    current_volume: float      # 현재 거래량
    avg_recent_volume: float   # 최근 평균 거래량
    volume_ratio: float        # 현재/기준 비율
    volume_trend: str         # 'increasing', 'decreasing', 'stable'
    is_volume_surge: bool     # 거래량 급증 여부
    is_low_volume: bool       # 저거래량 여부 (기준의 25% 이하)
    is_moderate_volume: bool  # 보통거래량 여부 (25-50%)
    is_high_volume: bool      # 고거래량 여부 (기준의 50% 이상)


@dataclass
class CandleAnalysis:
    """캔들 분석 결과"""
    is_bullish: bool             # 양봉 여부
    body_size: float             # 캔들 실체 크기
    body_pct: float              # 실체 크기 비율 (%)
    current_candle_size: float   # 현재 캔들 크기 (high-low)
    avg_recent_candle_size: float # 최근 평균 캔들 크기
    candle_trend: str           # 'expanding', 'shrinking', 'stable'
    is_small_candle: bool       # 작은 캔들 여부
    is_large_candle: bool       # 큰 캔들 여부
    is_meaningful_body: bool    # 의미있는 실체 크기 (0.5% 이상)


class PullbackCandlePattern:
    """눌림목 캔들패턴 분석기"""
    
    @staticmethod
    def calculate_daily_baseline_volume(data: pd.DataFrame) -> pd.Series:
        """당일 기준거래량 계산 (당일 최대 거래량을 실시간 추적)"""
        try:
            if 'datetime' in data.columns:
                dates = pd.to_datetime(data['datetime']).dt.normalize()
            else:
                dates = pd.to_datetime(data.index).normalize()
            
            # 당일 누적 최대 거래량
            daily_max = data['volume'].groupby(dates).cummax()
            return daily_max
            
        except Exception:
            # 날짜 정보가 없으면 전체 기간 중 최대값 사용
            return pd.Series([data['volume'].max()] * len(data), index=data.index)
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10) -> VolumeAnalysis:
        """거래량 분석 (개선된 기준거래량 사용)"""
        if 'volume' not in data.columns or len(data) < period:
            return VolumeAnalysis(0, 0, 0, 0, 'stable', False, False, False, False)
        
        volumes = data['volume'].values
        current_volume = volumes[-1]
        
        # 기준 거래량: 당일 최대 거래량 (실시간)
        baseline_volumes = PullbackCandlePattern.calculate_daily_baseline_volume(data)
        baseline_volume = baseline_volumes.iloc[-1]
        
        # 최근 평균 거래량
        avg_recent_volume = np.mean(volumes[-period:])
        
        # 거래량 비율 계산
        volume_ratio = current_volume / baseline_volume if baseline_volume > 0 else 0
        
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
        
        # 거래량 상태 분석 (제시된 로직에 따라)
        is_volume_surge = current_volume > avg_recent_volume * 1.5
        is_low_volume = volume_ratio <= 0.25      # 25% 이하: 매우 적음
        is_moderate_volume = 0.25 < volume_ratio <= 0.50  # 25-50%: 보통
        is_high_volume = volume_ratio > 0.50      # 50% 이상: 과다
        
        return VolumeAnalysis(
            baseline_volume=baseline_volume,
            current_volume=current_volume,
            avg_recent_volume=avg_recent_volume,
            volume_ratio=volume_ratio,
            volume_trend=volume_trend,
            is_volume_surge=is_volume_surge,
            is_low_volume=is_low_volume,
            is_moderate_volume=is_moderate_volume,
            is_high_volume=is_high_volume
        )
    
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
    def is_valid_turning_candle(current_candle: pd.Series, volume_analysis: VolumeAnalysis, 
                               candle_analysis: CandleAnalysis) -> bool:
        """변곡캔들 검증 (제시된 로직 적용)"""
        # 1. 양봉 확인
        if not candle_analysis.is_bullish:
            return False
            
        # 2. 거래량 증가 확인 (이전봉 대비 또는 평균 대비)
        if not (volume_analysis.volume_trend == 'increasing' or 
                volume_analysis.current_volume > volume_analysis.avg_recent_volume):
            return False
            
        # 3. 캔들 크기 의미있음 (실체 0.5% 이상)
        if not candle_analysis.is_meaningful_body:
            return False
            
        return True
    
    @staticmethod
    def get_bisector_status(current_price: float, bisector_line: float) -> BisectorStatus:
        """지지선 상태 판단 (제시된 로직 적용)"""
        if bisector_line is None or pd.isna(bisector_line) or bisector_line == 0:
            return BisectorStatus.BROKEN
        
        diff_pct = (current_price - bisector_line) / bisector_line
        
        if diff_pct >= 0.005:  # +0.5% 이상
            return BisectorStatus.HOLDING
        elif diff_pct >= -0.005:  # ±0.5% 범위  
            return BisectorStatus.NEAR_SUPPORT
        else:  # -0.5% 미만
            return BisectorStatus.BROKEN
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위에 있는지 확인 (기존 호환성)"""
        try:
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            current_price = data['close'].iloc[-1]
            bl = bisector_line.iloc[-1]
            
            status = PullbackCandlePattern.get_bisector_status(current_price, bl)
            return status in [BisectorStatus.HOLDING, BisectorStatus.NEAR_SUPPORT]
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
    def check_risk_signals(current: pd.Series, bisector_line: float, entry_low: Optional[float], 
                          recent_low: float, entry_price: Optional[float], 
                          volume_analysis: VolumeAnalysis, candle_analysis: CandleAnalysis) -> List[RiskSignal]:
        """위험 신호 최우선 체크 (제시된 로직 적용)"""
        risk_signals = []
        
        # 1. 장대음봉 + 대량거래량 (50% 이상)
        if (not candle_analysis.is_bullish and 
            candle_analysis.is_large_candle and 
            volume_analysis.is_high_volume):
            risk_signals.append(RiskSignal.LARGE_BEARISH_VOLUME)
        
        # 2. 이등분선 이탈 (0.2% 기준)
        if bisector_line is not None and current['close'] < bisector_line * 0.998:
            risk_signals.append(RiskSignal.BISECTOR_BREAK)
        
        # 3. 변곡캔들 저가 이탈 (0.2% 기준)
        if entry_low is not None and current['close'] <= entry_low * 0.998:
            risk_signals.append(RiskSignal.ENTRY_LOW_BREAK)
        
        # 4. 지지 저점 이탈
        if current['close'] < recent_low:
            risk_signals.append(RiskSignal.SUPPORT_BREAK)
        
        # 5. 목표 수익 3% 달성
        if entry_price is not None and current['close'] >= entry_price * 1.03:
            risk_signals.append(RiskSignal.TARGET_REACHED)
        
        return risk_signals
    
    @staticmethod
    def check_prior_uptrend(data: pd.DataFrame, min_gain: float = 0.05) -> bool:
        """선행 상승 확인 (당일 시가 대비 5% 이상 상승했었는지)"""
        if len(data) < 1:
            return False
        
        try:
            # 당일 데이터에서 시가와 고점 추출
            if 'datetime' in data.columns:
                dates = pd.to_datetime(data['datetime']).dt.normalize()
                today = dates.iloc[-1]  # 현재(마지막) 캔들의 날짜
                
                # 당일 데이터만 필터링
                today_data = data[dates == today]
                
                if len(today_data) == 0:
                    return False
                
                # 당일 시가 (첫 번째 캔들의 시가)
                day_open = today_data['open'].iloc[0]
                # 당일 고점 (당일 중 최대 고가)
                day_high = today_data['high'].max()
                
            else:
                # datetime 정보가 없으면 전체 데이터를 당일로 간주
                day_open = data['open'].iloc[0]
                day_high = data['high'].max()
            
            # 당일 시가 대비 고점 상승률 계산
            if day_open > 0:
                gain_pct = (day_high - day_open) / day_open
                return gain_pct >= min_gain  # 5% 이상 상승했었는지
            
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
    def generate_confidence_signal(bisector_status: BisectorStatus, volume_analysis: VolumeAnalysis, 
                                 has_turning_candle: bool, prior_uptrend: bool) -> SignalStrength:
        """조건에 따른 신뢰도별 신호 생성 (제시된 로직 적용)"""
        score = 0
        reasons = []
        
        # 이등분선 상태 점수
        if bisector_status == BisectorStatus.HOLDING:
            score += 30
            reasons.append('이등분선 안정 지지')
        elif bisector_status == BisectorStatus.NEAR_SUPPORT:
            score += 15
            reasons.append('이등분선 근접')
        else:  # BROKEN
            score -= 20
            reasons.append('이등분선 이탈 위험')
        
        # 거래량 상태 점수
        if volume_analysis.is_low_volume:  # 25% 이하
            score += 25
            reasons.append('매물부담 매우 적음')
        elif volume_analysis.is_moderate_volume:  # 25-50%
            score += 10
            reasons.append('매물부담 보통')
        else:  # 50% 이상
            score -= 15
            reasons.append('매물부담 과다')
        
        # 변곡캔들 점수
        if has_turning_candle:
            score += 25
            reasons.append('변곡캔들 출현')
        else:
            score -= 10
            reasons.append('변곡캔들 미출현')
        
        # 선행 상승 점수
        if prior_uptrend:
            score += 20
            reasons.append('선행 상승 확인')
        else:
            score -= 10
            reasons.append('선행 상승 부족')
        
        # 신뢰도별 분류 (제시된 로직 적용)
        if score >= 80:
            return SignalStrength(
                signal_type=SignalType.STRONG_BUY,
                confidence=score,
                target_profit=0.025,  # 2.5% 목표 (기존 3% → 2.5%)
                reasons=reasons,
                volume_ratio=volume_analysis.volume_ratio,
                bisector_status=bisector_status
            )
        elif score >= 60:
            return SignalStrength(
                signal_type=SignalType.CAUTIOUS_BUY,
                confidence=score,
                target_profit=0.02,  # 2.0% 목표 (기존 2% → 2.0%)
                reasons=reasons,
                volume_ratio=volume_analysis.volume_ratio,
                bisector_status=bisector_status
            )
        elif score >= 40:
            return SignalStrength(
                signal_type=SignalType.WAIT,
                confidence=score,
                target_profit=0,
                reasons=reasons,
                volume_ratio=volume_analysis.volume_ratio,
                bisector_status=bisector_status
            )
        else:
            return SignalStrength(
                signal_type=SignalType.AVOID,
                confidence=score,
                target_profit=0,
                reasons=reasons,
                volume_ratio=volume_analysis.volume_ratio,
                bisector_status=bisector_status
            )
    
    @staticmethod
    def analyze_pullback_quality(data: pd.DataFrame, baseline_volumes: pd.Series, 
                                period: int = 3) -> bool:
        """조정 품질 검증 (제시된 로직 적용)"""
        if len(data) < period + 1:
            return False
        
        # 최근 period개 봉의 조정 품질 확인
        recent_data = data.iloc[-period:]
        recent_baseline = baseline_volumes.iloc[-period:]
        
        # 1. 거래량 급감 확인 (기준거래량 25% 이하 비중 >= 2/3)
        low_vol_count = sum(recent_data['volume'] <= recent_baseline * 0.25)
        low_vol_ratio = low_vol_count / len(recent_data)
        
        # 2. 천천히 하락 확인 (하락봉 비중 >= 1/2)
        price_changes = recent_data['close'].diff().iloc[1:]  # 첫 번째는 NaN이므로 제외
        down_count = sum(price_changes < 0)
        down_ratio = down_count / len(price_changes) if len(price_changes) > 0 else 0
        
        # 3. 장대음봉 없음 확인 (캔들 축소 비중 >= 1/2)
        avg_candle_size = (data['high'] - data['low']).iloc[-10:].mean()  # 최근 10봉 평균
        small_candle_count = sum((recent_data['high'] - recent_data['low']) <= avg_candle_size * 0.8)
        small_candle_ratio = small_candle_count / len(recent_data)
        
        # 제시된 기준 적용
        return (low_vol_ratio >= 2/3 and 
                down_ratio >= 0.5 and 
                small_candle_ratio >= 0.5)
    
    @staticmethod
    def check_pullback_recovery_signal(data: pd.DataFrame, baseline_volumes: pd.Series, 
                                      lookback: int = 3) -> bool:
        """눌림목 회복 신호 확인: 1/4 수준 조정 중 거래량 회복 + 양봉"""
        if len(data) < lookback + 1:
            return False
        
        try:
            # 현재 캔들과 이전 캔들들 분리
            current_candle = data.iloc[-1]
            previous_candles = data.iloc[-(lookback+1):-1]  # 현재 제외한 최근 3봉
            
            current_baseline = baseline_volumes.iloc[-1]
            previous_baselines = baseline_volumes.iloc[-(lookback+1):-1]
            
            if len(previous_candles) == 0:
                return False
            
            # 1. 이전 캔들들이 기준거래량 1/4 수준으로 조정되었는지 확인
            low_volume_mask = previous_candles['volume'] <= previous_baselines * 0.25
            low_volume_ratio = low_volume_mask.sum() / len(previous_candles)
            
            # 최소 2/3 이상이 1/4 이하로 조정되어야 함
            if low_volume_ratio < 2/3:
                return False
            
            # 2. 현재 캔들이 회복 신호인지 확인
            # 조건 1: 양봉
            is_bullish = current_candle['close'] > current_candle['open']
            
            # 조건 2: 거래량이 기준거래량 1/4 이상으로 회복
            volume_recovered = current_candle['volume'] > current_baseline * 0.25
            
            # 두 조건 모두 만족해야 매수 신호
            return is_bullish and volume_recovered
            
        except Exception:
            return False
    
    @staticmethod
    def generate_improved_signals(
        data: pd.DataFrame,
        entry_price: Optional[float] = None,
        entry_low: Optional[float] = None,
        debug: bool = False,
        logger: Optional[logging.Logger] = None
    ) -> Tuple[SignalStrength, List[RiskSignal]]:
        """개선된 눌림목 패턴 신호 생성 (제시된 로직 적용)
        
        Returns:
            Tuple[SignalStrength, List[RiskSignal]]: (신호 강도, 위험 신호 목록)
        """
        try:
            if data is None or data.empty or len(data) < 10:
                return (SignalStrength(SignalType.AVOID, 0, 0, ['데이터 부족'], 0, BisectorStatus.BROKEN), [])

            # 1. 데이터 수집 및 기본 계산
            current = data.iloc[-1]
            
            # 이등분선 계산
            bisector_line_series = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            bisector_line = bisector_line_series.iloc[-1] if not bisector_line_series.empty else None
            
            # 기준거래량 계산 (당일 실시간)
            baseline_volumes = PullbackCandlePattern.calculate_daily_baseline_volume(data)
            
            # 최근 저점
            recent_low = PullbackCandlePattern.find_recent_low(data)
            
            # 2. 분석 실행
            volume_analysis = PullbackCandlePattern.analyze_volume(data)
            candle_analysis = PullbackCandlePattern.analyze_candle(data)
            
            # 3. 위험신호 체크 (최우선)
            risk_signals = PullbackCandlePattern.check_risk_signals(
                current, bisector_line, entry_low, recent_low, entry_price, 
                volume_analysis, candle_analysis
            )
            
            # 위험신호가 있으면 즉시 매도 신호 반환
            if risk_signals:
                if debug and logger:
                    logger.info(f"위험신호 감지: {[r.value for r in risk_signals]}")
                return (SignalStrength(SignalType.SELL, 100, 0, 
                                     [f'위험신호: {r.value}' for r in risk_signals], 
                                     volume_analysis.volume_ratio, 
                                     PullbackCandlePattern.get_bisector_status(current['close'], bisector_line)), 
                       risk_signals)
            
            # 4. 선행 상승 확인
            prior_uptrend = PullbackCandlePattern.check_prior_uptrend(data)
            
            # 5. 조정 품질 분석
            good_pullback = PullbackCandlePattern.analyze_pullback_quality(data, baseline_volumes)
            
            # 6. 지지선 상태 확인
            bisector_status = PullbackCandlePattern.get_bisector_status(current['close'], bisector_line)
            
            # 7. 변곡캔들 감지
            has_turning_candle = PullbackCandlePattern.is_valid_turning_candle(
                current, volume_analysis, candle_analysis
            )
            
            # 8. 필수 조건 체크: 눌림목 회복 신호 확인
            has_recovery_signal = PullbackCandlePattern.check_pullback_recovery_signal(data, baseline_volumes)
            
            # 눌림목 회복 신호가 없으면 매수 신호 금지
            if not has_recovery_signal:
                signal_strength = SignalStrength(
                    signal_type=SignalType.WAIT,
                    confidence=30,
                    target_profit=0,
                    reasons=['눌림목 회복 신호 없음 (1/4 조정 후 거래량 회복 + 양봉 필요)'],
                    volume_ratio=volume_analysis.volume_ratio,
                    bisector_status=bisector_status
                )
            else:
                # 9. 신호 생성 (제시된 로직 적용)
                signal_strength = PullbackCandlePattern.generate_confidence_signal(
                    bisector_status, volume_analysis, has_turning_candle, prior_uptrend
                )
                
                # 조정 품질이 나쁘면 신뢰도 차감
                if not good_pullback and signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                    signal_strength.confidence -= 15
                    signal_strength.reasons.append('조정 품질 미흡')
                    
                    # 신뢰도 재분류
                    if signal_strength.confidence < 60:
                        signal_strength.signal_type = SignalType.WAIT if signal_strength.confidence >= 40 else SignalType.AVOID
            
            # 이등분선 이탈 상태에서는 매수 금지
            if bisector_status == BisectorStatus.BROKEN:
                signal_strength.signal_type = SignalType.AVOID
                signal_strength.reasons.append('이등분선 이탈로 매수 금지')
            
            if debug and logger:
                logger.info(f"신호: {signal_strength.signal_type.value}, 신뢰도: {signal_strength.confidence:.1f}%, "
                           f"거래량비율: {volume_analysis.volume_ratio:.1%}, 이등분선: {bisector_status.value}")
            
            return (signal_strength, risk_signals)
            
        except Exception as e:
            if logger:
                logger.error(f"개선된 신호 생성 오류: {e}")
            return (SignalStrength(SignalType.AVOID, 0, 0, [f'오류: {str(e)}'], 0, BisectorStatus.BROKEN), [])
    
    @staticmethod
    def generate_trading_signals(
        data: pd.DataFrame,
        *,
        enable_candle_shrink_expand: bool = False,
        enable_divergence_precondition: bool = False,
        enable_overhead_supply_filter: bool = False,
        candle_expand_multiplier: float = 1.10,
        overhead_lookback: int = 10,
        overhead_threshold_hits: int = 2,
        debug: bool = False,
        logger: Optional[logging.Logger] = None,
        log_level: int = logging.INFO,
        use_improved_logic: bool = True,  # 새로운 로직 사용 여부

    ) -> pd.DataFrame:
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
            
            # 개선된 로직 사용 옵션
            if use_improved_logic:
                return PullbackCandlePattern._generate_signals_with_improved_logic(
                    df, debug, logger, log_level
                )

            # 기존 로직은 더 이상 사용되지 않음 (use_improved_logic=True가 기본값)
            # 하위 호환성을 위해 빈 DataFrame 반환
            return pd.DataFrame(index=df.index)

        except Exception as e:
            print(f"눌림목 캔들패턴 신호 생성 오류: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def _generate_signals_with_improved_logic(
        data: pd.DataFrame, 
        debug: bool = False, 
        logger: Optional[logging.Logger] = None,
        log_level: int = logging.INFO
    ) -> pd.DataFrame:
        """개선된 로직을 기존 DataFrame 형식으로 변환"""
        try:
            # 이등분선 계산
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            
            # 결과 DataFrame 초기화 (기존 형식 유지 + 신호 강도 정보 추가)
            signals = pd.DataFrame(index=data.index)
            signals['buy_pullback_pattern'] = False
            signals['buy_bisector_recovery'] = False  
            signals['sell_bisector_break'] = False
            signals['sell_support_break'] = False
            signals['stop_entry_low_break'] = False
            signals['take_profit_3pct'] = False
            signals['bisector_line'] = bisector_line
            # 신호 강도 정보 컬럼 추가
            signals['signal_type'] = ''
            signals['confidence'] = 0.0
            signals['target_profit'] = 0.0
            
            # 포지션 시뮬레이션 변수
            in_position = False
            entry_price = None
            entry_low = None
            
            # 각 시점에서 신호 계산
            for i in range(10, len(data)):  # 최소 10개 데이터 필요
                current_data = data.iloc[:i+1]
                
                # 개선된 신호 생성
                signal_strength, risk_signals = PullbackCandlePattern.generate_improved_signals(
                    current_data, entry_price, entry_low, debug, logger
                )
                
                if not in_position:
                    # 매수 신호 확인
                    if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                        # 신뢰도에 따라 다른 신호 생성
                        if signal_strength.signal_type == SignalType.STRONG_BUY:
                            signals.iloc[i, signals.columns.get_loc('buy_pullback_pattern')] = True
                        else:  # CAUTIOUS_BUY
                            signals.iloc[i, signals.columns.get_loc('buy_bisector_recovery')] = True
                        
                        # 신호 강도 정보 저장
                        signals.iloc[i, signals.columns.get_loc('signal_type')] = signal_strength.signal_type.value
                        signals.iloc[i, signals.columns.get_loc('confidence')] = signal_strength.confidence
                        signals.iloc[i, signals.columns.get_loc('target_profit')] = signal_strength.target_profit
                        
                        in_position = True
                        entry_price = float(current_data['close'].iloc[-1])
                        entry_low = float(current_data['low'].iloc[-1])
                        
                        if debug and logger:
                            logger.log(log_level, f"매수 신호: {signal_strength.signal_type.value} "
                                     f"신뢰도: {signal_strength.confidence:.1f}% 가격: {entry_price}")
                else:
                    # 매도 신호 확인
                    if risk_signals:
                        for risk in risk_signals:
                            if risk == RiskSignal.BISECTOR_BREAK:
                                signals.iloc[i, signals.columns.get_loc('sell_bisector_break')] = True
                            elif risk == RiskSignal.SUPPORT_BREAK:
                                signals.iloc[i, signals.columns.get_loc('sell_support_break')] = True
                            elif risk == RiskSignal.ENTRY_LOW_BREAK:
                                signals.iloc[i, signals.columns.get_loc('stop_entry_low_break')] = True
                            elif risk == RiskSignal.TARGET_REACHED:
                                signals.iloc[i, signals.columns.get_loc('take_profit_3pct')] = True
                        
                        in_position = False
                        entry_price = None
                        entry_low = None
                        
                        if debug and logger:
                            logger.log(log_level, f"매도 신호: {[r.value for r in risk_signals]}")
            
            return signals
            
        except Exception as e:
            if logger:
                logger.error(f"개선된 로직 변환 오류: {e}")
            return pd.DataFrame()

    @staticmethod
    def generate_sell_signals(
        data: pd.DataFrame,
        entry_low: Optional[float] = None,
        support_lookback: int = 5,
        bisector_leeway: float = 0.002,
    ) -> pd.DataFrame:
        """눌림목 캔들패턴 - 매도 신호 전용 계산 (현재 상태 기반, in_position 비의존)

        반환 컬럼:
        - sell_bisector_break: 종가가 이등분선 대비 0.2% 하회
        - sell_support_break: 종가가 직전 구간의 최근 저점(lookback) 하회(현재 캔들 제외)
        - stop_entry_low_break: 종가가 진입 양봉의 저가 대비 0.2% 하회 (entry_low 제공 시)
        - bisector_line: 이등분선 값(보조)
        """
        try:
            if data is None or data.empty:
                return pd.DataFrame()

            required_cols = ['open', 'high', 'low', 'close']
            if not all(col in data.columns for col in required_cols):
                return pd.DataFrame(index=data.index)

            df = data.copy()

            # 이등분선 계산
            bl = BisectorLine.calculate_bisector_line(df['high'], df['low'])

            # 최근 저점(현재 캔들 제외: 직전 N봉 기준)
            recent_low_prev = df['low'].shift(1).rolling(window=max(1, support_lookback), min_periods=1).min()

            # 매도 신호 계산
            sell_bisector_break = (df['close'] < bl * (1 - bisector_leeway)).fillna(False)
            sell_support_break = (df['close'] < recent_low_prev).fillna(False)

            # 진입 저가 기반 손절 (entry_low 제공 시)
            if entry_low is not None:
                stop_entry_low_break = (df['close'] < entry_low * (1 - bisector_leeway)).fillna(False)
            else:
                stop_entry_low_break = pd.Series(False, index=df.index)

            out = pd.DataFrame(index=df.index)
            out['sell_bisector_break'] = sell_bisector_break.fillna(False)
            out['sell_support_break'] = sell_support_break.fillna(False)
            out['stop_entry_low_break'] = stop_entry_low_break.fillna(False)
            out['bisector_line'] = bl

            return out

        except Exception as e:
            print(f"눌림목 캔들패턴 매도 신호 계산 오류: {e}")
            return pd.DataFrame(index=(data.index if data is not None else None))
    
