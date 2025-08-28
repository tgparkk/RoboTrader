"""
눌림목 캔들패턴 유틸리티 함수들
PullbackCandlePattern 클래스에서 분리된 정적 메서드들
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, List
import logging
from dataclasses import dataclass
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


@dataclass
class VolumeAnalysis:
    """거래량 분석 결과"""
    baseline_volume: float       # 기준 거래량
    current_volume: float        # 현재 거래량
    avg_recent_volume: float     # 최근 평균 거래량
    volume_ratio: float          # 거래량 비율
    volume_trend: str           # 거래량 추세
    is_volume_surge: bool       # 거래량 급증
    is_low_volume: bool         # 낮은 거래량 (25% 이하)
    is_moderate_volume: bool    # 보통 거래량 (25-50%)
    is_high_volume: bool        # 높은 거래량 (50% 이상)


class PullbackUtils:
    """눌림목 캔들패턴 유틸리티 함수들"""
    
    @staticmethod
    def calculate_daily_baseline_volume(data: pd.DataFrame) -> pd.Series:
        """당일 기준거래량 계산 (당일 최대 거래량을 실시간 추적)"""
        try:
            if 'datetime' in data.columns:
                dates = pd.to_datetime(data['datetime']).dt.normalize()
            else:
                dates = pd.to_datetime(data.index).normalize()
            
            # 당일 누적 최대 거래량 (양봉/음봉 구분없이)
            daily_baseline = data['volume'].groupby(dates).cummax()
            
            return daily_baseline
            
        except Exception:
            # 날짜 정보가 없으면 전체 기간 중 최대값 사용
            max_vol = data['volume'].max()
            return pd.Series([max_vol] * len(data), index=data.index)
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10) -> VolumeAnalysis:
        """거래량 분석 (개선된 기준거래량 사용)"""
        if 'volume' not in data.columns or len(data) < period:
            return VolumeAnalysis(0, 0, 0, 0, 'stable', False, False, False, False)
        
        volumes = data['volume'].values
        current_volume = volumes[-1]
        
        # 기준 거래량: 당일 최대 거래량 (실시간)
        baseline_volumes = PullbackUtils.calculate_daily_baseline_volume(data)
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
    def analyze_price_trend(data: pd.DataFrame, period: int = 10) -> Dict[str, float]:
        """가격 트렌드 분석"""
        if len(data) < period:
            return {'trend_strength': 0, 'volatility': 0, 'momentum': 0}
        
        closes = data['close'].values[-period:]
        
        # 트렌드 강도 (선형 회귀 기울기)
        x = np.arange(len(closes))
        slope = np.polyfit(x, closes, 1)[0]
        trend_strength = slope / closes[0] if closes[0] > 0 else 0
        
        # 변동성 (표준편차/평균)
        volatility = np.std(closes) / np.mean(closes) if np.mean(closes) > 0 else 0
        
        # 모멘텀 (최근/이전 비율)
        momentum = (closes[-1] / closes[0] - 1) if closes[0] > 0 else 0
        
        return {
            'trend_strength': trend_strength,
            'volatility': volatility,
            'momentum': momentum
        }
    
    @staticmethod
    def check_low_volume_retrace(data: pd.DataFrame, lookback: int = 3, volume_threshold: float = 0.25) -> bool:
        """저거래량 조정 확인"""
        if len(data) < lookback + 1:
            return False
        
        # 기준 거래량
        baseline_volumes = PullbackUtils.calculate_daily_baseline_volume(data)
        baseline = baseline_volumes.iloc[-1] if not baseline_volumes.empty else data['volume'].iloc[-lookback-1:]
        
        # 최근 lookback개 캔들의 거래량과 가격 변화 확인
        recent_data = data.iloc[-lookback:]
        
        # 모든 캔들이 저거래량인지 확인
        low_volume_all = (recent_data['volume'] < baseline * volume_threshold).all()
        
        # 가격이 하락 추세인지 확인
        price_changes = recent_data['close'].diff().fillna(0)
        downtrend_all = (price_changes.iloc[1:] <= 0).all() if len(price_changes) > 1 else False
        
        return low_volume_all and downtrend_all
    
    @staticmethod
    def is_recovery_candle(data: pd.DataFrame, index: int) -> bool:
        """회복 양봉 여부 확인"""
        if index < 0 or index >= len(data):
            return False
        
        candle = data.iloc[index]
        return candle['close'] > candle['open']  # 양봉
    
    @staticmethod
    def check_volume_recovery(data: pd.DataFrame, retrace_lookback: int = 3) -> bool:
        """거래량 회복 여부 확인"""
        if len(data) <= retrace_lookback:
            return False
        
        current_volume = data['volume'].iloc[-1]
        
        # 조정 기간 동안의 최대 거래량
        retrace_volumes = data['volume'].iloc[-retrace_lookback-1:-1]  # 현재 제외하고 직전 retrace_lookback개
        max_retrace_volume = retrace_volumes.max() if len(retrace_volumes) > 0 else 0
        
        # 최근 평균 거래량
        recent_avg_volume = data['volume'].iloc[-10:].mean() if len(data) >= 10 else current_volume
        
        # 거래량 회복 조건: 조정 기간 최대값 초과 또는 최근 평균 초과
        return current_volume > max_retrace_volume or current_volume > recent_avg_volume
    
    @staticmethod
    def analyze_bisector_status(data: pd.DataFrame, tolerance: float = 0.005) -> BisectorStatus:
        """이등분선 지지/저항 상태 분석"""
        if len(data) < 5:
            return BisectorStatus.BROKEN
        
        try:
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            if bisector_line is None or bisector_line.empty:
                return BisectorStatus.BROKEN
            
            current_price = data['close'].iloc[-1]
            current_bisector = bisector_line.iloc[-1]
            
            if pd.isna(current_bisector) or current_bisector <= 0:
                return BisectorStatus.BROKEN
            
            # 이등분선 대비 현재가 위치
            price_ratio = current_price / current_bisector
            
            if price_ratio >= (1.0 + tolerance):
                return BisectorStatus.HOLDING
            elif price_ratio >= (1.0 - tolerance):
                return BisectorStatus.NEAR_SUPPORT
            else:
                return BisectorStatus.BROKEN
                
        except Exception:
            return BisectorStatus.BROKEN
    
    @staticmethod
    def check_bisector_cross_up(data: pd.DataFrame, tolerance: float = 0.002) -> bool:
        """이등분선 상향 돌파 확인 (허용 오차 0.2%)"""
        if len(data) < 2:
            return False
        
        try:
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            if bisector_line is None or len(bisector_line) < 2:
                return False
            
            current_candle = data.iloc[-1]
            current_bisector = bisector_line.iloc[-1]
            
            if pd.isna(current_bisector) or current_bisector <= 0:
                return False
            
            # 현재 캔들이 이등분선을 상향 돌파했는지 확인
            open_price = current_candle['open']
            close_price = current_candle['close']
            
            # 허용 오차를 고려한 돌파 확인
            bisector_with_tolerance = current_bisector * (1.0 - tolerance)
            
            # 시가가 이등분선(허용오차 포함) 이하이고, 종가가 이등분선 이상인 경우
            crosses_up = (open_price <= bisector_with_tolerance and 
                         close_price >= current_bisector)
            
            return crosses_up
            
        except Exception:
            return False
    
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
    def calculate_signal_strength(
        volume_analysis: VolumeAnalysis,
        bisector_status: BisectorStatus,
        is_recovery_candle: bool,
        volume_recovers: bool,
        has_retrace: bool,
        crosses_bisector_up: bool,
        has_overhead_supply: bool
    ) -> SignalStrength:
        """신호 강도 계산"""
        
        reasons = []
        confidence = 0
        signal_type = SignalType.WAIT
        
        # 기본 조건들 점수화
        if is_recovery_candle:
            confidence += 20
            reasons.append("회복양봉")
        
        if volume_recovers:
            confidence += 25
            reasons.append("거래량회복")
        
        if has_retrace:
            confidence += 15
            reasons.append("저거래조정")
        
        # 이등분선 상태에 따른 점수
        if bisector_status == BisectorStatus.HOLDING:
            confidence += 20
            reasons.append("이등분선지지")
        elif bisector_status == BisectorStatus.NEAR_SUPPORT:
            confidence += 10
            reasons.append("이등분선근접")
        
        if crosses_bisector_up:
            confidence += 15
            reasons.append("이등분선돌파")
        
        # 거래량 상태에 따른 보너스
        if volume_analysis.is_volume_surge:
            confidence += 10
            reasons.append("거래량급증")
        
        # 페널티
        if has_overhead_supply:
            confidence -= 15
            reasons.append("머리위물량(-)")
        
        if bisector_status == BisectorStatus.BROKEN:
            confidence -= 20
            reasons.append("이등분선이탈(-)")
        
        # 신호 타입 결정
        if confidence >= 80:
            signal_type = SignalType.STRONG_BUY
            target_profit = 0.025  # 2.5%
        elif confidence >= 60:
            signal_type = SignalType.CAUTIOUS_BUY
            target_profit = 0.02   # 2.0%
        elif confidence >= 40:
            signal_type = SignalType.WAIT
            target_profit = 0.015  # 1.5%
        else:
            signal_type = SignalType.AVOID
            target_profit = 0.01   # 1.0%
        
        return SignalStrength(
            signal_type=signal_type,
            confidence=max(0, min(100, confidence)),
            target_profit=target_profit,
            reasons=reasons,
            volume_ratio=volume_analysis.volume_ratio,
            bisector_status=bisector_status
        )
    
    @staticmethod
    def detect_risk_signals(
        data: pd.DataFrame,
        entry_price: Optional[float] = None,
        entry_low: Optional[float] = None,
        target_profit_rate: float = 0.02
    ) -> List[RiskSignal]:
        """위험 신호 감지"""
        risk_signals = []
        
        if len(data) == 0:
            return risk_signals
        
        current_candle = data.iloc[-1]
        current_price = current_candle['close']
        
        # 목표 수익 달성
        if entry_price and current_price >= entry_price * (1 + target_profit_rate):
            risk_signals.append(RiskSignal.TARGET_REACHED)
        
        # 이등분선 이탈
        try:
            bisector_status = PullbackUtils.analyze_bisector_status(data)
            if bisector_status == BisectorStatus.BROKEN:
                risk_signals.append(RiskSignal.BISECTOR_BREAK)
        except Exception:
            pass
        
        # 진입 양봉 저가 이탈 (0.2% 허용오차)
        if entry_low and current_price < entry_low * 0.998:
            risk_signals.append(RiskSignal.ENTRY_LOW_BREAK)
        
        # 장대 음봉 + 대량 거래량
        volume_analysis = PullbackUtils.analyze_volume(data)
        is_large_bearish = (
            current_candle['close'] < current_candle['open'] and  # 음봉
            abs(current_candle['close'] - current_candle['open']) > 
            (current_candle['high'] - current_candle['low']) * 0.6 and  # 장대
            volume_analysis.is_volume_surge  # 대량거래량
        )
        
        if is_large_bearish:
            risk_signals.append(RiskSignal.LARGE_BEARISH_VOLUME)
        
        # 지지 저점 이탈 (최근 10개 중 최저점)
        if len(data) >= 10:
            recent_lows = data['low'].iloc[-10:]
            support_level = recent_lows.min()
            if current_price < support_level * 0.998:  # 0.2% 허용오차
                risk_signals.append(RiskSignal.SUPPORT_BREAK)
        
        return risk_signals
    
    @staticmethod
    def format_signal_info(signal_strength: SignalStrength, additional_info: Dict = None) -> str:
        """신호 정보 포맷팅"""
        signal_map = {
            SignalType.STRONG_BUY: "🔥 강매수",
            SignalType.CAUTIOUS_BUY: "⚡ 매수",
            SignalType.WAIT: "⏸️ 대기",
            SignalType.AVOID: "❌ 회피",
            SignalType.SELL: "🔻 매도"
        }
        
        signal_text = signal_map.get(signal_strength.signal_type, "❓ 불명")
        reasons_text = " | ".join(signal_strength.reasons[:3])  # 상위 3개만
        
        info = f"{signal_text} (신뢰도: {signal_strength.confidence:.0f}%, "
        info += f"목표: {signal_strength.target_profit*100:.1f}%)\n"
        info += f"근거: {reasons_text}"
        
        if additional_info:
            for key, value in additional_info.items():
                info += f" | {key}: {value}"
        
        return info
    
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
            
            status = PullbackUtils.get_bisector_status(current_price, bl)
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
                          volume_analysis: VolumeAnalysis, candle_analysis) -> List[RiskSignal]:
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
    def analyze_candle(data: pd.DataFrame, period: int = 10):
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
    def handle_avoid_conditions(has_selling_pressure: bool, has_bearish_volume_restriction: bool, 
                              bisector_breakout_volume_ok: bool, current: pd.Series,
                              volume_analysis: VolumeAnalysis, bisector_line: float,
                              data: pd.DataFrame = None, debug: bool = False, logger = None) -> Optional[SignalStrength]:
        """회피 조건들 처리 (lines 684-751 from pullback_candle_pattern.py)"""
        
        if has_selling_pressure:
            if debug and logger:
                candle_time = ""
                if 'datetime' in current.index:
                    try:
                        dt = pd.to_datetime(current['datetime'])
                        candle_time = f" {dt.strftime('%H:%M')}"
                    except:
                        candle_time = ""
                
                # 기준 거래량 정보 추가
                baseline_vol = volume_analysis.baseline_volume
                baseline_info = f", 기준거래량: {baseline_vol:,.0f}주" if baseline_vol > 0 else ""
                
                candle_count = len(data) if data is not None else "N/A"
                current_candle_info = f"봉:{candle_count}개{candle_time} 종가:{current['close']:,.0f}원"
                logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                           f"눌림목 과정 매물부담 감지 - 매수 제외{baseline_info}")
            
            return SignalStrength(SignalType.AVOID, 0, 0, 
                                ['눌림목 과정 매물부담 (3% 상승 후 하락시 고거래량)'], 
                                volume_analysis.volume_ratio, 
                                PullbackUtils.get_bisector_status(current['close'], bisector_line))
        
        if has_bearish_volume_restriction:
            if debug and logger:
                candle_time = ""
                if 'datetime' in current.index:
                    try:
                        dt = pd.to_datetime(current['datetime'])
                        candle_time = f" {dt.strftime('%H:%M')}"
                    except:
                        candle_time = ""
                
                # 기준 거래량 정보 추가
                baseline_vol = volume_analysis.baseline_volume
                baseline_info = f", 기준거래량: {baseline_vol:,.0f}주" if baseline_vol > 0 else ""
                
                candle_count = len(data) if data is not None else "N/A"
                current_candle_info = f"봉:{candle_count}개{candle_time} 종가:{current['close']:,.0f}원"
                logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                           f"음봉 최대거래량 제한 - 매수 제외{baseline_info}")
            
            return SignalStrength(SignalType.AVOID, 0, 0, 
                                ['음봉 최대거래량 제한 (당일 최대 음봉 거래량보다 큰 양봉 출현 대기 중)'], 
                                volume_analysis.volume_ratio, 
                                PullbackUtils.get_bisector_status(current['close'], bisector_line))
        
        if not bisector_breakout_volume_ok:
            if debug and logger:
                candle_time = ""
                if 'datetime' in current.index:
                    try:
                        dt = pd.to_datetime(current['datetime'])
                        candle_time = f" {dt.strftime('%H:%M')}"
                    except:
                        candle_time = ""
                
                # 기준 거래량 정보 추가
                baseline_vol = volume_analysis.baseline_volume
                baseline_info = f", 기준거래량: {baseline_vol:,.0f}주" if baseline_vol > 0 else ""
                
                candle_count = len(data) if data is not None else "N/A"
                current_candle_info = f"봉:{candle_count}개{candle_time} 종가:{current['close']:,.0f}원"
                logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                           f"이등분선 돌파 거래량 부족 - 매수 제외{baseline_info}")
            
            return SignalStrength(SignalType.AVOID, 0, 0, 
                                ['이등분선 돌파 거래량 부족 (직전 봉 거래량의 2배 이상 필요)'], 
                                volume_analysis.volume_ratio, 
                                PullbackUtils.get_bisector_status(current['close'], bisector_line))
        
        return None
    
    @staticmethod
    def check_low_volume_breakout_signal(data: pd.DataFrame, baseline_volumes: pd.Series,
                                       min_low_volume_candles: int = 2,
                                       volume_threshold: float = 0.3) -> bool:
        """
        저거래량 조정 후 회복 양봉 신호 확인
        
        조건:
        - 기준거래량의 1/4 수준으로 연속 5개 이상 거래
        - 1/4 수준을 넘는 직전봉보다 위에 있는 양봉 출현
        
        Args:
            data: 3분봉 데이터
            baseline_volumes: 기준거래량 시리즈
            min_low_volume_candles: 최소 저거래량 캔들 개수 (기본 5개)
            volume_threshold: 저거래량 기준 (기준거래량의 25%)
            
        Returns:
            bool: 저거래량 회복 신호 여부
        """
        if len(data) < min_low_volume_candles + 1 or len(baseline_volumes) < len(data):
            return False
        
        try:
            # 현재 캔들과 이전 캔들들
            current_candle = data.iloc[-1]
            
            # 현재 캔들이 양봉인지 확인
            if current_candle['close'] <= current_candle['open']:
                return False
            
            # 연속 저거래량 구간 찾기
            low_volume_count = 0
            prev_candle_idx = -2  # 직전봉부터 시작
            
            # 직전봉부터 역순으로 저거래량 캔들 개수 확인
            for i in range(len(data) - 2, -1, -1):  # 현재 캔들 제외하고 역순
                candle = data.iloc[i]
                baseline = baseline_volumes.iloc[i]
                
                # 기준거래량의 1/4 이하인지 확인
                if candle['volume'] <= baseline * volume_threshold:
                    low_volume_count += 1
                else:
                    break  # 연속성이 깨지면 중단
            
            # 최소 개수 이상의 연속 저거래량 캔들이 있는지 확인
            if low_volume_count < min_low_volume_candles:
                return False
            
            # 직전봉 정보
            prev_candle = data.iloc[-2]
            prev_baseline = baseline_volumes.iloc[-2]
            
            # 현재 캔들의 거래량이 1/4 수준을 넘는지 확인
            current_baseline = baseline_volumes.iloc[-1]
            if current_candle['volume'] <= current_baseline * volume_threshold:
                return False
            
            # 현재 캔들이 직전봉보다 위에 있는지 확인
            # 직전캔들이 음봉이면 시가보다 높은지, 직전캔들이 양봉이면 종가보다 높은지 확인
            prev_is_bearish = prev_candle['close'] < prev_candle['open']
            
            if prev_is_bearish:
                # 직전봉이 음봉인 경우: 현재 캔들의 종가가 직전봉의 시가보다 높은지 확인
                if current_candle['close'] <= prev_candle['open']:
                    return False
            else:
                # 직전봉이 양봉인 경우: 현재 캔들의 종가가 직전봉의 종가보다 높은지 확인
                if current_candle['close'] <= prev_candle['close']:
                    return False
            
            return True
            
        except Exception:
            return False