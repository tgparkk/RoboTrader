"""
눌림목 캔들패턴 지표 (3분봉 권장) - 리팩토링된 버전
주가 상승 후 저거래 조정(기준 거래량의 1/4) → 회복 양봉에서 거래량 회복 → 이등분선 지지/회복 확인
손절: 진입 양봉 저가 0.2% 이탈, 또는 이등분선 기준 아래로 0.2% 이탈, 또는 지지 저점 이탈
익절: 매수가 대비 +3%
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, List
import logging
from utils.logger import setup_logger
from datetime import datetime

from core.indicators.bisector_line import BisectorLine
from core.indicators.pullback_utils import (
    SignalType, BisectorStatus, RiskSignal, SignalStrength, 
    VolumeAnalysis, CandleAnalysis, PullbackUtils
)
from core.indicators.pullback.volume_analyzer import VolumeAnalyzer


class PullbackCandlePattern:
    """눌림목 캔들패턴 분석기 (리팩토링된 버전)"""
    
    # 기본 유틸리티 메서드들 - PullbackUtils로 위임
    @staticmethod
    def calculate_daily_baseline_volume(data: pd.DataFrame) -> pd.Series:
        """당일 기준거래량 계산"""
        return PullbackUtils.calculate_daily_baseline_volume(data)
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10) -> VolumeAnalysis:
        """거래량 분석"""
        return PullbackUtils.analyze_volume(data, period)
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10) -> CandleAnalysis:
        """캔들 분석"""
        return PullbackUtils.analyze_candle(data, period)
    
    @staticmethod
    def get_bisector_status(current_price: float, bisector_line: float) -> BisectorStatus:
        """이등분선 상태 판단"""
        return PullbackUtils.get_bisector_status(current_price, bisector_line)
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위 위치 확인"""
        return PullbackUtils.check_price_above_bisector(data)
    
    @staticmethod
    def check_price_trend(data: pd.DataFrame, period: int = 10) -> str:
        """주가 추세 확인"""
        return PullbackUtils.check_price_trend(data, period)
    
    @staticmethod
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기"""
        return PullbackUtils.find_recent_low(data, period)
    
    @staticmethod
    def check_prior_uptrend(data: pd.DataFrame, min_gain: float = 0.05) -> bool:
        """선행 상승 확인"""
        return PullbackUtils.check_prior_uptrend(data, min_gain)
    
    # 핵심 비즈니스 로직 메서드들
    @staticmethod
    def _analyze_volume_pattern(data: pd.DataFrame, baseline_volumes: pd.Series, period: int = 3) -> dict:
        """거래량 패턴 분석 (PullbackCandlePattern 전용)"""
        return VolumeAnalyzer._analyze_volume_pattern_internal(data, baseline_volumes, period)
    
    @staticmethod
    def is_valid_turning_candle(current_candle: pd.Series, volume_analysis: VolumeAnalysis, 
                              candle_analysis: CandleAnalysis, bisector_line: float = None, 
                              min_body_pct: float = 0.5, debug: bool = False, logger = None) -> bool:
        """변곡캔들 유효성 검증 (제시된 로직에 따른 강화)"""
        
        # 1. 양봉 조건
        if not candle_analysis.is_bullish:
            return False
        
        # 2. 의미있는 실체 크기 (0.5% 이상)
        if not candle_analysis.is_meaningful_body:
            return False
        
        # 3. 이등분선 근접/상승 돌파 (선택사항)
        if bisector_line is not None:
            bisector_status = PullbackUtils.get_bisector_status(current_candle['close'], bisector_line)
            if bisector_status == BisectorStatus.BROKEN:
                return False
        
        return True
    
    @staticmethod
    def _analyze_volume_pattern(data: pd.DataFrame, baseline_volumes: pd.Series, period: int = 3) -> dict:
        """거래량 패턴 분석 (공통 함수)"""
        
        if len(data) < period + 1 or len(baseline_volumes) < len(data):
            return {
                'consecutive_low_count': 0,
                'current_vs_threshold': 0,
                'avg_low_volume_ratio': 0,
                'volume_trend': 'stable'
            }
        
        try:
            # 현재 캔들 정보
            current_volume = data['volume'].iloc[-1]
            current_baseline = baseline_volumes.iloc[-1]
            
            # 직전 period개 캔들 분석 (현재 제외)
            recent_data = data.iloc[-period-1:-1]  # 현재 캔들 제외
            recent_baselines = baseline_volumes.iloc[-period-1:-1]
            
            # 연속 저거래량 개수 계산
            volume_ratios = recent_data['volume'] / recent_baselines
            low_volume_threshold = 0.25  # 25%
            
            consecutive_low_count = 0
            for ratio in volume_ratios.iloc[::-1]:  # 최근부터 거슬러 올라감
                if ratio <= low_volume_threshold:
                    consecutive_low_count += 1
                else:
                    break
            
            # 현재 캔들의 거래량 비율
            current_vs_threshold = current_volume / current_baseline if current_baseline > 0 else 0
            
            # 저거래량 구간 평균 비율
            avg_low_volume_ratio = volume_ratios.mean() if len(volume_ratios) > 0 else 0
            
            # 거래량 추세
            if len(volume_ratios) >= 2:
                recent_trend = volume_ratios.iloc[-2:].values
                if recent_trend[-1] > recent_trend[-2]:
                    volume_trend = 'increasing'
                elif recent_trend[-1] < recent_trend[-2]:
                    volume_trend = 'decreasing'
                else:
                    volume_trend = 'stable'
            else:
                volume_trend = 'stable'
            
            return {
                'consecutive_low_count': consecutive_low_count,
                'current_vs_threshold': current_vs_threshold,
                'avg_low_volume_ratio': avg_low_volume_ratio,
                'volume_trend': volume_trend
            }
            
        except Exception:
            return {
                'consecutive_low_count': 0,
                'current_vs_threshold': 0,
                'avg_low_volume_ratio': 0,
                'volume_trend': 'stable'
            }
    
    @staticmethod
    def analyze_pullback_quality(data: pd.DataFrame, baseline_volumes: pd.Series, 
                               min_pullback_candles: int = 5, 
                               low_volume_threshold: float = 0.25) -> dict:
        """눌림목 품질 분석"""
        
        if len(data) < min_pullback_candles + 1:
            return {'quality_score': 0, 'has_quality_pullback': False}
        
        # 공통 거래량 패턴 분석 활용
        volume_info = PullbackCandlePattern._analyze_volume_pattern(data, baseline_volumes, min_pullback_candles)
        
        quality_score = 0
        
        # 1. 연속 저거래량 개수 (가중치 40%)
        consecutive_score = min(volume_info['consecutive_low_count'] / min_pullback_candles, 1.0) * 40
        quality_score += consecutive_score
        
        # 2. 저거래량 수준 (가중치 30%)
        avg_ratio = volume_info['avg_low_volume_ratio']
        volume_score = max(0, (low_volume_threshold - avg_ratio) / low_volume_threshold) * 30
        quality_score += volume_score
        
        # 3. 가격 안정성 (가중치 30%)
        try:
            recent_closes = data['close'].iloc[-min_pullback_candles-1:-1]
            price_volatility = recent_closes.std() / recent_closes.mean() if recent_closes.mean() > 0 else 1
            stability_score = max(0, (0.05 - price_volatility) / 0.05) * 30  # 5% 기준
            quality_score += stability_score
        except:
            stability_score = 0
        
        has_quality_pullback = (
            volume_info['consecutive_low_count'] >= min_pullback_candles and 
            quality_score >= 60
        )
        
        return {
            'quality_score': quality_score,
            'has_quality_pullback': has_quality_pullback,
            'consecutive_low_count': volume_info['consecutive_low_count'],
            'avg_volume_ratio': avg_ratio
        }
    
    @staticmethod
    def generate_improved_signals(
        data: pd.DataFrame,
        stock_code: str = "UNKNOWN",
        debug: bool = False
    ) -> Optional[SignalStrength]:
        """개선된 신호 생성 로직 (통합)"""
        
        if len(data) < 10:
            return None
        
        logger = setup_logger(f"pullback_pattern_{stock_code}")
        logger._stock_code = stock_code
        
        try:
            # 기본 분석
            baseline_volumes = PullbackUtils.calculate_daily_baseline_volume(data)
            volume_analysis = PullbackUtils.analyze_volume(data)
            candle_analysis = PullbackUtils.analyze_candle(data)
            current = data.iloc[-1]
            
            # 이등분선 분석
            try:
                bisector_line_series = BisectorLine.calculate_bisector_line(data['high'], data['low'])
                bisector_line = bisector_line_series.iloc[-1] if bisector_line_series is not None else None
            except:
                bisector_line = None
            
            # 위험 신호 우선 체크
            if bisector_line is not None:
                recent_low = PullbackUtils.find_recent_low(data) or 0
                risk_signals = PullbackUtils.check_risk_signals(
                    current, bisector_line, None, recent_low, None, volume_analysis, candle_analysis
                )
                
                if risk_signals:
                    return SignalStrength(SignalType.AVOID, 0, 0, 
                                        [f"위험신호: {', '.join([rs.value for rs in risk_signals])}"],
                                        volume_analysis.volume_ratio,
                                        PullbackUtils.get_bisector_status(current['close'], bisector_line))
            
            # 1. 선행 상승 확인
            has_prior_uptrend = PullbackUtils.check_prior_uptrend(data)
            
            # 2. 눌림목 품질 분석
            pullback_quality = PullbackCandlePattern.analyze_pullback_quality(data, baseline_volumes)
            
            # 3. 회피 조건 체크 (완화된 버전)
            has_selling_pressure = PullbackCandlePattern.check_heavy_selling_pressure(data, baseline_volumes)
            has_bearish_restriction = PullbackCandlePattern.check_bearish_volume_restriction(data, baseline_volumes)
            bisector_volume_ok = PullbackCandlePattern.check_bisector_breakout_volume(data)
            
            # 회피 조건 처리 (스마트 회피 - 복합적 위험도 판단)
            risk_score = 0
            if has_selling_pressure:
                risk_score += 30  # 매물부담 위험도
            if has_bearish_restriction:
                risk_score += 25  # 음봉 거래량 제한 위험도
            if not bisector_volume_ok:
                risk_score += 15  # 이등분선 돌파 거래량 부족
            
            # 위험도가 50 이상일 때만 회피 (기존: 하나만 있어도 회피)
            if risk_score >= 50:
                avoid_result = PullbackUtils.handle_avoid_conditions(
                    has_selling_pressure, has_bearish_restriction, bisector_volume_ok,
                    current, volume_analysis, bisector_line, data, debug, logger
                )
                if avoid_result:
                    return avoid_result
            
            # 4. 매수 신호 계산
            is_recovery_candle = candle_analysis.is_bullish
            volume_recovers = PullbackUtils.check_volume_recovery(data)
            has_retrace = PullbackUtils.check_low_volume_retrace(data)
            crosses_bisector_up = PullbackUtils.check_bisector_cross_up(data) if bisector_line else False
            has_overhead_supply = PullbackUtils.check_overhead_supply(data)
            
            bisector_status = PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN
            
            # 이등분선 아래 신호 차단 (점수 높아도 무조건 회피)
            if bisector_line and current['close'] < bisector_line:
                return SignalStrength(SignalType.AVOID, 0, 0,
                                    ["이등분선아래위치-매수금지"],
                                    volume_analysis.volume_ratio,
                                    BisectorStatus.BROKEN)
            
            # 신호 강도 계산
            signal_strength = PullbackUtils.calculate_signal_strength(
                volume_analysis, bisector_status, is_recovery_candle, volume_recovers,
                has_retrace, crosses_bisector_up, has_overhead_supply
            )
            
            # 필수 조건 검증 (눌림목 전용 - 강화된 버전)
            mandatory_failed = []
            
            # 1. 선행상승 - 가장 중요한 조건 (눌림목의 핵심)
            if not has_prior_uptrend:
                mandatory_failed.append("선행상승미충족")
            
            # 2. 회복양봉 - 두 번째로 중요한 조건
            if not is_recovery_candle:
                mandatory_failed.append("회복양봉미충족")
            
            # 3. 거래량회복 - 세 번째로 중요한 조건
            if not volume_recovers:
                mandatory_failed.append("거래량회복미충족")
            
            # 눌림목의 핵심 조건 (선행상승 + 회복양봉) 미충족시 무조건 회피
            if not has_prior_uptrend or not is_recovery_candle:
                return SignalStrength(SignalType.AVOID, 0, 0,
                                    [f"눌림목핵심조건미충족: {', '.join(mandatory_failed[:2])}"],
                                    volume_analysis.volume_ratio,
                                    PullbackUtils.get_bisector_status(current['close'], bisector_line))
            
            # 선택적 조건들 (완화된 검증)
            optional_failed = []
            
            if not pullback_quality['has_quality_pullback']:
                optional_failed.append("눌림목품질미충족")
                
            if bisector_line and current['close'] < bisector_line * 0.998:  # 이등분선 0.2% 이상 이탈
                optional_failed.append("이등분선이탈")
            
            # 선택적 조건 2개 이상 미충족시에만 페널티 적용 (회피하지 않음)
            if len(optional_failed) >= 2:
                signal_strength.confidence *= 0.8  # 페널티 적용
                signal_strength.reasons.append(f"선택조건미충족(-): {', '.join(optional_failed)}")
            elif len(optional_failed) == 1:
                signal_strength.confidence *= 0.9  # 약간의 페널티만
                signal_strength.reasons.append(f"선택조건미충족(-): {optional_failed[0]}")
                
            # 거래량 회복 미충족시 페널티만 적용 (회피하지 않음)
            if not volume_recovers:
                signal_strength.confidence *= 0.85
                signal_strength.reasons.append("거래량회복미충족(-)")
                
            # 대량 매물 출현 후 미회복 종목 차단
            high_volume_decline_filter = PullbackCandlePattern.check_high_volume_decline_recovery(data, baseline_volumes)
            if high_volume_decline_filter['should_avoid']:
                return SignalStrength(SignalType.AVOID, 0, 0,
                                    [f"대량매물미회복: {high_volume_decline_filter['reason']}"],
                                    volume_analysis.volume_ratio,
                                    PullbackUtils.get_bisector_status(current['close'], bisector_line))
            
            # 최종 신호 검증 (신뢰도 기준 - 눌림목 전용)
            if signal_strength.confidence < 45:  # 눌림목 전용 기준: 45%
                return SignalStrength(SignalType.AVOID, 0, 0,
                                    [f"신뢰도부족({signal_strength.confidence:.0f}%)"] + signal_strength.reasons,
                                    volume_analysis.volume_ratio,
                                    signal_strength.bisector_status)
            
            # 매수 신호 발생시 3/5가 계산
            if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                # 가장 최근 매수 신호 캔들 찾기
                last_buy_idx = len(data) - 1  # 기본값: 현재 캔들
                
                # 진짜 신호 캔들 찾기 (현재 캔들이 회복 캔들이라면)
                if is_recovery_candle and volume_recovers:
                    # 현재 캔들이 신호 캔들
                    sig_high = float(data['high'].iloc[-1])
                    sig_low = float(data['low'].iloc[-1])
                    
                    # 3/5 구간 가격 (60% 지점) 계산
                    three_fifths_price = sig_low + (sig_high - sig_low) * 0.6
                    
                    if three_fifths_price > 0 and sig_low <= three_fifths_price <= sig_high:
                        signal_strength.buy_price = three_fifths_price
                        signal_strength.entry_low = sig_low
                        if debug and logger:
                            logger.info(f"📊 3/5가 계산 완료: {three_fifths_price:,.0f}원 (H:{sig_high:,.0f}, L:{sig_low:,.0f})")
                            #logger.info(f"📈 전날 대비 상승률: {daily_gain_pct:.1f}%")
                    else:
                        # 3/5가 계산 실패시 현재가 사용
                        signal_strength.buy_price = float(current['close'])
                        signal_strength.entry_low = float(current['low'])
                else:
                    # 신호 캔들을 찾을 수 없으면 현재가 사용
                    signal_strength.buy_price = float(current['close'])
                    signal_strength.entry_low = float(current['low'])
            
            return signal_strength
            
        except Exception as e:
            if debug and logger:
                logger.error(f"신호 생성 중 오류: {e}")
            return None
    
    # 기존 호환성을 위한 메서드들
    @staticmethod
    def check_heavy_selling_pressure(data: pd.DataFrame, baseline_volumes: pd.Series) -> bool:
        """매물 부담 확인"""
        if len(data) < 10:
            return False
        
        try:
            # 최근 5개 봉 중 3% 상승 후 하락하면서 고거래량인 경우가 있는지 확인
            recent_data = data.iloc[-5:].copy()
            for i in range(1, len(recent_data)):
                prev_close = recent_data.iloc[i-1]['close']
                curr = recent_data.iloc[i]
                
                # 3% 상승 달성
                if curr['high'] >= prev_close * 1.03:
                    # 그 후 하락
                    if curr['close'] < curr['open']:
                        # 고거래량 (50% 이상)
                        volume_ratio = curr['volume'] / baseline_volumes.iloc[-5+i] if baseline_volumes.iloc[-5+i] > 0 else 0
                        if volume_ratio > 0.5:
                            return True
            return False
        except:
            return False
    
    @staticmethod
    def check_bearish_volume_restriction(data: pd.DataFrame, baseline_volumes: pd.Series) -> bool:
        """음봉 거래량 제한 확인 (엄격한 조건만 적용)"""
        if len(data) < 2:
            return False
        
        try:
            current_volume = data['volume'].iloc[-1]
            current_is_bullish = data['close'].iloc[-1] > data['open'].iloc[-1]
            
            # 현재 양봉이 아니면 제한 없음
            if not current_is_bullish:
                return False
            
            # 최근 15봉 내에서만 확인 (더 짧은 윈도우)
            recent_data = data.tail(16)  # 현재봉 + 과거 15봉
            recent_bearish = recent_data[recent_data['close'] < recent_data['open']]
            
            if len(recent_bearish) == 0:
                return False
            
            # 최근 15봉 내 최대 음봉 거래량
            max_recent_bearish_volume = recent_bearish['volume'].max()
            
            # 베이스라인 거래량 기준
            baseline_volume = baseline_volumes.iloc[-1] if len(baseline_volumes) > 0 else current_volume
            
            # 더 엄격한 조건: 음봉 거래량이 베이스라인의 2배 이상이고, 
            # 현재 양봉 거래량이 그보다 작을 때만 제한
            if max_recent_bearish_volume > baseline_volume * 2.0:
                return current_volume <= max_recent_bearish_volume
            
            return False
            
        except:
            return False
    
    @staticmethod
    def check_high_volume_decline_recovery(data: pd.DataFrame, baseline_volumes: pd.Series) -> dict:
        """대량 매물 출현 후 회복 여부 확인"""
        if len(data) < 10 or len(baseline_volumes) < 10:
            return {'should_avoid': False, 'reason': '데이터부족'}
        
        try:
            # 전체 캔들 분석 (고거래량 하락은 하루 중 언제든 발생할 수 있음)
            recent_data = data.copy()
            recent_baseline = baseline_volumes
            
            # 대량 음봉 찾기 (기준거래량 50% 이상 + 하락)
            high_volume_declines = []
            
            for i in range(len(recent_data)):
                candle = recent_data.iloc[i]
                baseline_vol = recent_baseline.iloc[i] if i < len(recent_baseline) else 0
                
                # 음봉인지 확인
                is_bearish = candle['close'] < candle['open']
                # 대량거래인지 확인 (기준거래량 50% 이상)
                is_high_volume = candle['volume'] >= baseline_vol * 0.5 if baseline_vol > 0 else False
                
                if is_bearish and is_high_volume:
                    decline_pct = (candle['close'] - candle['open']) / candle['open'] * 100 if candle['open'] > 0 else 0
                    high_volume_declines.append({
                        'index': i,
                        'decline_pct': abs(decline_pct),
                        'low_price': candle['low'],
                        'volume_ratio': candle['volume'] / baseline_vol if baseline_vol > 0 else 0
                    })
            
            # 2개 이상의 대량 음봉이 있는지 확인
            if len(high_volume_declines) < 2:
                return {'should_avoid': False, 'reason': f'대량음봉부족({len(high_volume_declines)}개)'}
            
            # 가장 심각한 하락폭들 선별 (상위 2개)
            top_declines = sorted(high_volume_declines, key=lambda x: x['decline_pct'], reverse=True)[:2]
            total_decline_required = sum([d['decline_pct'] for d in top_declines])
            lowest_point = min([d['low_price'] for d in high_volume_declines])
            
            # 현재가가 하락폭만큼 회복했는지 확인
            current_price = recent_data['close'].iloc[-1]
            recovery_from_low = (current_price - lowest_point) / lowest_point * 100
            
            # 회복 기준: 총 하락폭의 70% 이상 회복해야 거래 허용
            recovery_threshold = total_decline_required * 0.7
            
            if recovery_from_low < recovery_threshold:
                reason = f"하락{total_decline_required:.1f}% vs 회복{recovery_from_low:.1f}% (기준{recovery_threshold:.1f}%)"
                return {'should_avoid': True, 'reason': reason}
            
            return {'should_avoid': False, 'reason': '회복충분'}
            
        except Exception as e:
            # 오류 발생시 안전하게 거래 허용
            return {'should_avoid': False, 'reason': f'분석오류: {str(e)}'}
    
    @staticmethod
    def check_bisector_breakout_volume(data: pd.DataFrame) -> bool:
        """이등분선 돌파 거래량 확인"""
        if len(data) < 2:
            return True  # 기본값
        
        try:
            current_volume = data['volume'].iloc[-1]
            prev_volume = data['volume'].iloc[-2]
            
            # 직전 봉의 2배 이상
            return current_volume >= prev_volume * 2
        except:
            return True
    
    # 기존 메서드들 (단순화된 버전)
    @staticmethod
    def generate_trading_signals(
        data: pd.DataFrame,
        *,
        enable_candle_shrink_expand: bool = False,
        enable_divergence_precondition: bool = False,
        enable_overhead_supply_filter: bool = False,
        use_improved_logic: bool = True,
        candle_expand_multiplier: float = 1.10,
        overhead_lookback: int = 10,
        overhead_threshold_hits: int = 2,
        debug: bool = False,
        logger: Optional[logging.Logger] = None,
        log_level: int = 20,  # logging.INFO = 20
        stock_code: str = "UNKNOWN"
    ) -> pd.DataFrame:
        """거래 신호 생성 (기존 호환성 유지)"""
        # 호환성을 위해 기존 파라미터들을 받지만 새로운 로직에서는 일부만 사용
        # 중복 호출 제거: _generate_signals_with_improved_logic 내부에서 이미 generate_improved_signals를 호출함
        
        # 원본 로직을 따라 DataFrame 형태로 신호 생성
        return PullbackCandlePattern._generate_signals_with_improved_logic(
            data, debug, logger, log_level, stock_code
        )
    
    @staticmethod
    def _generate_signals_with_improved_logic(
        data: pd.DataFrame, 
        debug: bool = False, 
        logger: Optional[logging.Logger] = None,
        log_level: int = 20,
        stock_code: str = "UNKNOWN"
    ) -> pd.DataFrame:
        """개선된 로직을 기존 DataFrame 형식으로 변환 (원본 호환)"""
        try:
            # 이등분선 계산
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            
            # 결과 DataFrame 초기화 (기존 형식 유지)
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
            for i in range(5, len(data)):  # 최소 5개 데이터 필요
                current_data = data.iloc[:i+1]
                
                # 개선된 신호 생성 (새 인터페이스 사용)
                signal_strength = PullbackCandlePattern.generate_improved_signals(
                    current_data, stock_code, debug
                )
                
                if signal_strength is None:
                    continue
                
                # 위험 신호 확인 (매도 우선)
                if in_position:
                    risk_signals = PullbackUtils.detect_risk_signals(
                        current_data, entry_price, entry_low
                    )
                    
                    for risk in risk_signals:
                        if risk == RiskSignal.BISECTOR_BREAK:
                            signals.iloc[i, signals.columns.get_loc('sell_bisector_break')] = True
                            in_position = False
                        elif risk == RiskSignal.SUPPORT_BREAK:
                            signals.iloc[i, signals.columns.get_loc('sell_support_break')] = True
                            in_position = False
                        elif risk == RiskSignal.ENTRY_LOW_BREAK:
                            signals.iloc[i, signals.columns.get_loc('stop_entry_low_break')] = True
                            in_position = False
                        elif risk == RiskSignal.TARGET_REACHED:
                            signals.iloc[i, signals.columns.get_loc('take_profit_3pct')] = True
                            in_position = False
                
                if not in_position:
                    # 매수 신호 확인
                    if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                        # 신호 근거에 따라 다른 컬럼 사용
                        if signal_strength.signal_type == SignalType.STRONG_BUY:
                            signals.iloc[i, signals.columns.get_loc('buy_pullback_pattern')] = True
                        else:  # CAUTIOUS_BUY
                            signals.iloc[i, signals.columns.get_loc('buy_bisector_recovery')] = True
                        
                        # 신호 강도 정보 저장
                        signals.iloc[i, signals.columns.get_loc('signal_type')] = signal_strength.signal_type.value
                        signals.iloc[i, signals.columns.get_loc('confidence')] = signal_strength.confidence
                        signals.iloc[i, signals.columns.get_loc('target_profit')] = signal_strength.target_profit
                        
                        # 포지션 진입
                        in_position = True
                        entry_price = current_data.iloc[-1]['close']
                        entry_low = current_data.iloc[-1]['low']
                        
                        if debug and logger:
                            logger.info(f"[{stock_code}] 매수신호: {signal_strength.signal_type.value} "
                                      f"(신뢰도: {signal_strength.confidence:.0f}%)")
            
            return signals
            
        except Exception as e:
            if debug and logger:
                logger.error(f"신호 생성 중 오류: {e}")
            # 빈 DataFrame 반환
            return pd.DataFrame(index=data.index, columns=[
                'buy_pullback_pattern', 'buy_bisector_recovery', 'sell_bisector_break'
            ])
    
    @staticmethod
    def generate_sell_signals(data: pd.DataFrame, entry_price: float, entry_low: float, 
                            stock_code: str = "UNKNOWN", debug: bool = False) -> List[RiskSignal]:
        """매도 신호 생성"""
        return PullbackUtils.detect_risk_signals(data, entry_price, entry_low)