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
from core.indicators.pullback_utils import (
    SignalType, BisectorStatus, RiskSignal, SignalStrength, 
    VolumeAnalysis, CandleAnalysis, PullbackUtils
)


# Enums and dataclasses are now imported from pullback_utils


class PullbackCandlePattern:
    """눌림목 캔들패턴 분석기"""
    
    @staticmethod
    def calculate_daily_baseline_volume(data: pd.DataFrame) -> pd.Series:
        """당일 기준거래량 계산 - PullbackUtils로 위임"""
        return PullbackUtils.calculate_daily_baseline_volume(data)
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10) -> VolumeAnalysis:
        """거래량 분석 (개선된 기준거래량 사용) - PullbackUtils로 위임"""
        return PullbackUtils.analyze_volume(data, period)
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10) -> CandleAnalysis:
        """캔들 분석 (변곡캔들 검증 로직 강화) - PullbackUtils로 위임"""
        return PullbackUtils.analyze_candle(data, period)
    
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
        """지지선 상태 판단 (제시된 로직 적용) - PullbackUtils로 위임"""
        return PullbackUtils.get_bisector_status(current_price, bisector_line)
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위에 있는지 확인 (기존 호환성) - PullbackUtils로 위임"""
        return PullbackUtils.check_price_above_bisector(data)
    
    @staticmethod
    def check_price_trend(data: pd.DataFrame, period: int = 10) -> str:
        """주가 추세 확인 - PullbackUtils로 위임"""
        return PullbackUtils.check_price_trend(data, period)
    
    @staticmethod
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기 (최근 5개 봉) - PullbackUtils로 위임"""
        return PullbackUtils.find_recent_low(data, period)
    
    @staticmethod
    def check_risk_signals(current: pd.Series, bisector_line: float, entry_low: Optional[float], 
                          recent_low: float, entry_price: Optional[float], 
                          volume_analysis: VolumeAnalysis, candle_analysis: CandleAnalysis) -> List[RiskSignal]:
        """위험 신호 최우선 체크 (제시된 로직 적용) - PullbackUtils로 위임"""
        return PullbackUtils.check_risk_signals(current, bisector_line, entry_low, 
                                               recent_low, entry_price, volume_analysis, candle_analysis)
    
    @staticmethod
    def check_prior_uptrend(data: pd.DataFrame, min_gain: float = 0.05) -> bool:
        """선행 상승 확인 (당일 시가 대비 5% 이상 상승했었는지) - PullbackUtils로 위임"""
        return PullbackUtils.check_prior_uptrend(data, min_gain)
    
    @staticmethod
    def generate_confidence_signal(bisector_status: BisectorStatus, volume_analysis: VolumeAnalysis, 
                                 has_turning_candle: bool, prior_uptrend: bool, data: pd.DataFrame = None, 
                                 bisector_line: pd.Series = None, started_below_bisector: bool = False) -> SignalStrength:
        """조건에 따른 신뢰도별 신호 생성 (제시된 로직 적용)"""
        score = 0
        reasons = []
        
        # 09:30 이후 이등분선 완전 이탈 체크
        bisector_fully_broken_after_0930 = False
        if data is not None and bisector_line is not None and 'datetime' in data.columns:
            try:
                # 09:30 이후 데이터 필터링
                data_times = pd.to_datetime(data['datetime'])
                today = data_times.iloc[-1].date()
                time_0930 = pd.Timestamp.combine(today, pd.Timestamp('09:30:00').time())
                
                after_0930_mask = data_times >= time_0930
                after_0930_data = data[after_0930_mask]
                after_0930_bisector = bisector_line[after_0930_mask]
                
                # 09:30 이후 봉이 완전히 이등분선 아래로 내려간 경우 체크
                for i in range(len(after_0930_data)):
                    candle = after_0930_data.iloc[i]
                    bisector_value = after_0930_bisector.iloc[i] if i < len(after_0930_bisector) else 0
                    
                    # 봉 전체(고가, 저가, 시가, 종가)가 모두 이등분선 아래인 경우
                    if bisector_value > 0 and (candle['high'] < bisector_value and 
                                              candle['low'] < bisector_value and
                                              candle['open'] < bisector_value and
                                              candle['close'] < bisector_value):
                        bisector_fully_broken_after_0930 = True
                        break
                        
            except Exception:
                pass  # 시간 파싱 실패시 무시
        
        # 이등분선 상태 점수
        if bisector_status == BisectorStatus.HOLDING:
            score += 20
            reasons.append('이등분선 안정 지지')
        elif bisector_status == BisectorStatus.NEAR_SUPPORT:
            score += 10
            reasons.append('이등분선 근접')
        else:  # BROKEN
            score -= 25
            reasons.append('이등분선 이탈 위험')
        
        # 거래량 상태 점수
        if volume_analysis.is_low_volume:  # 25% 이하
            score += 30
            reasons.append('매물부담 매우 적음')
        elif volume_analysis.is_moderate_volume:  # 25-50%
            score += 10
            reasons.append('매물부담 보통')
        else:  # 50% 이상
            score -= 30
            reasons.append('매물부담 과다')
        
        # 변곡캔들 점수
        if has_turning_candle:
            score += 20
            reasons.append('변곡캔들 출현')
        else:
            score -= 30
            reasons.append('변곡캔들 미출현')
        
        # 선행 상승 점수
        if prior_uptrend:
            score += 20
            reasons.append('선행 상승 확인')
        else:
            score -= 10
            reasons.append('선행 상승 부족')
        
        # 09:30 이후 이등분선 완전 이탈시 STRONG_BUY 방지
        if bisector_fully_broken_after_0930 and score >= 90:
            score = 89  # 90점 미만으로 제한
            reasons.append('09:30 이후 이등분선 완전 이탈로 신호 강도 제한')
        
        # 목표 수익률 설정 (이등분선 아래/걸침 시작 시 1.5%)
        strong_buy_target = 0.015 if started_below_bisector else 0.025  # 1.5% vs 2.5%
        cautious_buy_target = 0.015 if started_below_bisector else 0.02  # 1.5% vs 2.0%
        
        # 신뢰도별 분류 (제시된 로직 적용)
        if score >= 85:
            return SignalStrength(
                signal_type=SignalType.STRONG_BUY,
                confidence=score,
                target_profit=strong_buy_target,
                reasons=reasons + (['이등분선 아래 시작으로 목표 1.5%'] if started_below_bisector else []),
                volume_ratio=volume_analysis.volume_ratio,
                bisector_status=bisector_status
            )
        elif score >= 70:
            return SignalStrength(
                signal_type=SignalType.CAUTIOUS_BUY,
                confidence=score,
                target_profit=cautious_buy_target,
                reasons=reasons + (['이등분선 아래 시작으로 목표 1.5%'] if started_below_bisector else []),
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
    def check_heavy_selling_pressure(data: pd.DataFrame, baseline_volumes: pd.Series) -> bool:
        """
        눌림목 하락 과정에서 매물부담 체크
        
        조건:
        1. 3% 이상 상승한 구간이 있었는지 확인
        2. 상승 후 하락(눌림목) 과정에서 거래량 60% 이상인 봉이 있는지 확인
        3. 🆕 단, 5봉 이상 조정 중이면 매물부담을 무시하고 매수 허용
        
        Args:
            data: 3분봉 데이터
            baseline_volumes: 기준 거래량
            
        Returns:
            bool: True이면 매물부담으로 매수 제외
        """
        try:
            if len(data) < 5:  # 최소 데이터 필요
                return False
            
            # 1. 당일 데이터 범위 확정
            if 'datetime' in data.columns:
                try:
                    # datetime 컬럼이 있는 경우 당일 데이터 필터링
                    dates = pd.to_datetime(data['datetime']).dt.date
                    today = dates.iloc[-1]  # 현재(마지막) 캔들의 날짜
                    
                    # 당일 데이터만 필터링
                    today_mask = dates == today
                    today_data = data[today_mask].reset_index(drop=True)
                    today_baselines = baseline_volumes[today_mask].reset_index(drop=True)
                    
                    if len(today_data) < 5:
                        return False
                        
                except Exception:
                    # datetime 처리 실패시 전체 데이터를 당일로 간주
                    today_data = data.copy()
                    today_baselines = baseline_volumes.copy()
            else:
                # datetime 컬럼이 없으면 전체 데이터를 당일로 간주
                today_data = data.copy()
                today_baselines = baseline_volumes.copy()
            
            # 2. 당일 시작점부터 3% 이상 상승 구간 찾기
            start_price = today_data['open'].iloc[0]  # 당일 시가
            high_point_idx = None
            high_price = None
            
            for i in range(len(today_data)):
                current_high = today_data['high'].iloc[i]
                # 당일 시가 대비 상승률 계산
                gain_rate = (current_high - start_price) / start_price if start_price > 0 else 0
                
                if gain_rate >= 0.03:  # 3% 이상 상승
                    high_point_idx = i
                    high_price = current_high
                    break
            
            if high_point_idx is None:
                return False  # 3% 상승 구간이 없으면 매물부담 체크 안함
            
            # 3. 고점 이후 하락 과정에서 고거래량 체크
            pullback_data = today_data.iloc[high_point_idx:]
            pullback_baselines = today_baselines.iloc[high_point_idx:]
            
            # 🆕 조정 기간 확인 - 5봉 이상 조정 중이면 매물부담 무시
            pullback_length = len(pullback_data)
            if pullback_length >= 5:
                # 5봉 이상 조정 중이면 매물부담을 무시하고 매수 허용
                return False
            
            # baseline_volumes 갱신 시점을 추적하여 갱신된 시점부터만 체크
            prev_baseline = None
            baseline_updated_idx = None
            
            for i in range(len(pullback_baselines)):
                current_baseline = pullback_baselines.iloc[i]
                
                # baseline_volumes가 갱신되었는지 확인 (이전 값과 다르면 갱신)
                if prev_baseline is not None and current_baseline != prev_baseline:
                    baseline_updated_idx = i
                    break
                prev_baseline = current_baseline
            
            # baseline이 갱신된 시점이 없다면 전체 구간 체크, 있다면 갱신 시점부터만 체크
            check_start_idx = baseline_updated_idx if baseline_updated_idx is not None else 0
            
            # 갱신된 시점부터 하락봉이면서 고거래량인지 체크
            for i in range(check_start_idx, len(pullback_data)):
                candle = pullback_data.iloc[i]
                current_baseline = pullback_baselines.iloc[i] if i < len(pullback_baselines) else 0
                
                # 음봉이면서 고거래량인지 체크 (양봉은 제외)
                is_declining = candle['close'] < candle['open']  # 양봉에서는 매물부담 감지하지 않음
                high_volume = candle['volume'] >= current_baseline * 0.6 if current_baseline > 0 else False
                
                if is_declining and high_volume:
                    return True  # 매물부담 감지 (5봉 미만 조정에서만)
            
            return False
            
        except Exception:
            return False
    
    @staticmethod
    def check_bearish_volume_restriction(data: pd.DataFrame, baseline_volumes: pd.Series) -> bool:
        """
        음봉의 최대 거래량 제한 체크
        
        조건:
        1. 당일 음봉 중 최대 거래량을 찾음
        2. 해당 음봉 이전에 더 큰 거래량의 양봉이 있으면 제한 무시
        3. 그렇지 않으면 그 거래량보다 큰 양봉이 나올 때까지 거래 제한
        
        Args:
            data: 3분봉 데이터
            baseline_volumes: 기준 거래량 (사용하지 않음)
            
        Returns:
            bool: True이면 거래 제한 (매수 금지)
        """
        try:
            if len(data) < 2:
                return False
            
            # 당일 데이터 필터링
            if 'datetime' in data.columns:
                try:
                    dates = pd.to_datetime(data['datetime']).dt.date
                    today = dates.iloc[-1]
                    today_mask = dates == today
                    today_data = data[today_mask].reset_index(drop=True)
                    
                    if len(today_data) < 2:
                        return False
                except Exception:
                    today_data = data.copy()
            else:
                today_data = data.copy()
            
            # 음봉들의 거래량 찾기
            is_bearish = today_data['close'] < today_data['open']
            bearish_data = today_data[is_bearish]
            
            if len(bearish_data) == 0:
                return False  # 음봉이 없으면 제한 없음
            
            # 당일 음봉 중 최대 거래량 찾기
            max_bearish_volume = bearish_data['volume'].max()
            max_bearish_idx = bearish_data['volume'].idxmax()
            max_bearish_candle = bearish_data.loc[max_bearish_idx]
            
            # 원본 데이터에서 해당 음봉의 인덱스 찾기
            max_bearish_original_idx = None
            for i, row in today_data.iterrows():
                if (row['volume'] == max_bearish_candle['volume'] and 
                    row['close'] == max_bearish_candle['close'] and
                    row['open'] == max_bearish_candle['open']):
                    max_bearish_original_idx = i
                    break
            
            if max_bearish_original_idx is None:
                return False
            
            # 최대 음봉 이전에 이미 더 큰 거래량의 양봉이 있었는지 체크
            for i in range(0, max_bearish_original_idx):
                prev_candle = today_data.iloc[i]
                
                # 양봉이면서 최대 음봉 거래량보다 큰지 체크
                is_bullish = prev_candle['close'] > prev_candle['open']
                has_larger_volume = prev_candle['volume'] > max_bearish_volume
                
                if is_bullish and has_larger_volume:
                    # 이전에 이미 더 큰 양봉이 있었으므로 제한 무시
                    return False
            
            # 최대 음봉 이후의 봉들을 체크하여 더 큰 거래량의 양봉이 나타났는지 확인
            for i in range(max_bearish_original_idx + 1, len(today_data)):
                next_candle = today_data.iloc[i]
                
                # 양봉이면서 최대 음봉 거래량보다 큰지 체크
                is_bullish = next_candle['close'] > next_candle['open']
                has_larger_volume = next_candle['volume'] > max_bearish_volume
                
                if is_bullish and has_larger_volume:
                    # 제한 해제 조건 만족
                    return False
            
            # 현재 봉이 음봉이지만 상승으로 판단되는 경우 제한 해제
            current_candle = today_data.iloc[-1]
            if len(today_data) >= 2:
                prev_candle = today_data.iloc[-2]
                
                # 현재 봉이 음봉인 경우에만 체크
                if current_candle['close'] < current_candle['open']:
                    # 조건 1: 현재 봉이 직전봉보다 위에 있는 경우 (고가 비교)
                    higher_than_prev = current_candle['high'] > prev_candle['high']
                    
                    # 조건 2: 음봉의 종가가 직전봉(양봉)의 시가와 종가의 중간보다 위에 있는 경우
                    prev_mid_price = (prev_candle['open'] + prev_candle['close']) / 2
                    close_above_prev_mid = current_candle['close'] > prev_mid_price
                    
                    # 조건 3: 직전봉의 종가보다 음봉의 시가가 높은 경우
                    open_higher_than_prev_close = current_candle['open'] > prev_candle['close']
                    
                    # 세 조건 중 하나라도 만족하면 상승으로 판단
                    if higher_than_prev or close_above_prev_mid or open_higher_than_prev_close:
                        return False
            
            # 최대 음봉 거래량보다 큰 양봉이 아직 없음 - 거래 제한
            return True
            
        except Exception:
            return False
    
    @staticmethod
    def check_bisector_breakout_volume(data: pd.DataFrame) -> bool:
        """
        이등분선 돌파 양봉의 거래량 조건 체크
        
        조건:
        1. 현재 봉이 양봉이고 이등분선을 넘어섬 (이전 봉은 이등분선 아래)
        2. 현재 봉의 거래량이 직전 봉 거래량의 2배 이상
        
        Args:
            data: 3분봉 데이터
            
        Returns:
            bool: True이면 조건 만족, False이면 조건 불만족
        """
        try:
            if len(data) < 2:
                return True  # 데이터 부족시 제한하지 않음
            
            # 이등분선 계산
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            if bisector_line is None or len(bisector_line) < 2:
                return True  # 이등분선 계산 실패시 제한하지 않음
            
            current_candle = data.iloc[-1]
            previous_candle = data.iloc[-2]
            current_bisector = bisector_line.iloc[-1]
            previous_bisector = bisector_line.iloc[-2]
            
            # 현재 봉이 양봉인지 확인
            is_current_bullish = current_candle['close'] > current_candle['open']
            
            # 이등분선 돌파 확인: 이전 봉은 아래, 현재 봉은 위
            previous_below_bisector = previous_candle['close'] < previous_bisector
            current_above_bisector = current_candle['close'] > current_bisector
            
            # 이등분선 돌파 양봉인 경우
            if is_current_bullish and previous_below_bisector and current_above_bisector:
                # 거래량 조건 체크: 현재 봉 거래량이 직전 봉의 2배 이상
                current_volume = current_candle['volume']
                previous_volume = previous_candle['volume']
                
                if previous_volume > 0 and current_volume >= previous_volume * 2.0:
                    return True  # 거래량 조건 만족
                else:
                    return False  # 거래량 조건 불만족
            
            # 이등분선 돌파가 아니면 제한하지 않음
            return True
            
        except Exception:
            return True  # 오류 시 제한하지 않음
    
    @staticmethod
    def check_pullback_recovery_signal(data: pd.DataFrame, baseline_volumes: pd.Series, 
                                      lookback: int = 3) -> Tuple[bool, bool]:
        """눌림목 회복 신호 확인: 이등분선 지지 + 양봉 + 거래량 증가 + 캔들 개선
        
        Returns:
            Tuple[bool, bool]: (회복신호여부, 비슷한조정캔들여부)
        """
        if len(data) < lookback + 1:
            return (False, False)
        
        try:
            # 현재 캔들과 이전 캔들들 분리
            current_candle = data.iloc[-1]
            
            # 1. 먼저 저거래량 돌파 신호 확인 (중복 로직 제거)
            has_low_volume_breakout = PullbackUtils.check_low_volume_breakout_signal(data, baseline_volumes)
            if not has_low_volume_breakout:
                return (False, False)
            
            # 2. 이등분선 계산 확인  
            bisector_line_series = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            current_bisector = bisector_line_series.iloc[-1] if not bisector_line_series.empty else None
            
            if current_bisector is None:
                return (False, False)
            
            # 현재 캔들이 이등분선 위에 있는지 확인
            current_above_bisector = current_candle['close'] > current_bisector
            
            # 당일 이등분선 아래로 내려간 적이 있는지 확인
            has_been_below_bisector_today = False
            if 'datetime' in data.columns:
                try:
                    dates = pd.to_datetime(data['datetime']).dt.date
                    today = dates.iloc[-1]
                    today_mask = dates == today
                    today_data = data[today_mask]
                    today_bisector = bisector_line_series[today_mask]
                    
                    # 당일 중 한 번이라도 이등분선 아래로 내려간 적이 있는지 확인
                    for i in range(len(today_data)):
                        if i < len(today_bisector):
                            candle_close = today_data.iloc[i]['close']
                            bisector_value = today_bisector.iloc[i]
                            if candle_close < bisector_value:
                                has_been_below_bisector_today = True
                                break
                except:
                    # 날짜 파싱 실패시 현재 상태로 판단
                    has_been_below_bisector_today = not current_above_bisector
            else:
                # datetime 컬럼이 없으면 현재 상태로 판단
                has_been_below_bisector_today = not current_above_bisector
            
            # 현재 이등분선 아래이거나 당일 아래로 내려간 적이 있으면 특별 조건 확인
            if not current_above_bisector or has_been_below_bisector_today:
                # 직전 캔들 대비 거래량이 2배 이상이고 1% 이상 상승한 경우에만 허용
                prev_candle = data.iloc[-2]
                volume_2x_increased = current_candle['volume'] >= prev_candle['volume'] * 2.0
                price_1pct_increase = current_candle['close'] >= prev_candle['close'] * 1.01
                
                # 두 조건을 모두 만족해야 함
                if not (volume_2x_increased and price_1pct_increase):
                    return (False, False)
            
            # 3. 추가 조건들은 check_low_volume_breakout_signal에서 이미 확인됨 (양봉, 거래량 등)
            # 여기서는 눌림목 특화 조건만 확인
            
            # 6. 직전 캔들 최소 두개가 조정되는 상황인지 확인 (필수 조건)
            if len(data) >= 3:  # 현재 + 직전 2개 = 최소 3개 필요
                # 직전 두 캔들 가져오기
                prev_candle_1 = data.iloc[-2]  # 바로 직전
                prev_candle_2 = data.iloc[-3]  # 그 전
                
                # 캔들 크기 계산 (high - low)
                prev_size_1 = prev_candle_1['high'] - prev_candle_1['low']
                prev_size_2 = prev_candle_2['high'] - prev_candle_2['low']
                
                # 캔들 중간가 계산 (시가+종가)/2
                prev_mid_1 = (prev_candle_1['open'] + prev_candle_1['close']) / 2
                prev_mid_2 = (prev_candle_2['open'] + prev_candle_2['close']) / 2
                
                # 비슷한 크기 조건: 크기 차이가 20% 이내
                size_diff_pct = abs(prev_size_1 - prev_size_2) / max(prev_size_1, prev_size_2) if max(prev_size_1, prev_size_2) > 0 else 0
                similar_size = size_diff_pct <= 0.20
                
                # 비슷한 가격 조건: 중간가 차이가 2% 이내
                price_diff_pct = abs(prev_mid_1 - prev_mid_2) / max(prev_mid_1, prev_mid_2) if max(prev_mid_1, prev_mid_2) > 0 else 0
                similar_price = price_diff_pct <= 0.02
                
                # 두 조건을 모두 만족해야 함 (필수 조건)
                has_similar_adjustment = similar_size and similar_price
                
                # 필수 조건이므로 만족하지 않으면 False 반환
                if not has_similar_adjustment:
                    return (False, False)
                
                return (True, has_similar_adjustment)
            else:
                return (False, False)  # 3개 미만인 경우 조건 확인 불가로 실패
            
        except Exception:
            return (False, False)
    
    @staticmethod
    def check_daily_start_below_bisector_restriction(data: pd.DataFrame) -> Tuple[bool, bool]:
        """
        당일 시작이 이등분선 근처/아래인 경우 하루 종일 매물부담 체크
        
        조건:
        1. 당일 첫 캔들(09:00)이 이등분선 아래이거나 걸침
        2. 해당 조건이면 하루 종일 매물부담으로 매수 제외
        
        Args:
            data: 3분봉 데이터
            
        Returns:
            Tuple[bool, bool]: (매물부담 제한 여부, 이등분선 아래/걸림 여부)
        """
        try:
            if len(data) < 2:
                return (False, False)
            
            # datetime 컬럼이 없으면 시간 체크 불가
            if 'datetime' not in data.columns:
                return (False, False)
            
            # 당일 데이터 필터링
            dates = pd.to_datetime(data['datetime'])
            today = dates.iloc[-1].date()
            today_mask = dates.dt.date == today
            today_data = data[today_mask].reset_index(drop=True)
            
            if len(today_data) < 2:
                return (False, False)
            
            # 당일 첫 캔들(09:00) 찾기
            first_candle = today_data.iloc[0]
            
            # 이등분선 계산 (당일 데이터만 사용)
            bisector_line = BisectorLine.calculate_bisector_line(today_data['high'], today_data['low'])
            if bisector_line is None or len(bisector_line) == 0:
                return (False, False)
            
            first_bisector = bisector_line.iloc[0]
            
            # 첫 캔들이 이등분선 아래이거나 걸치는지 확인
            # 걸친다는 것은: 시가나 종가 중 하나가 이등분선 아래에 있는 경우
            candle_below_or_crossing = (first_candle['open'] <= first_bisector or 
                                       first_candle['close'] <= first_bisector)
            
            # 매물부담 제한: 이등분선 아래/걸침이면 하루 종일 제한
            restriction_active = candle_below_or_crossing
            
            return (restriction_active, candle_below_or_crossing)
            
        except Exception:
            return (False, False)
    
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
            if data is None or data.empty or len(data) < 5:
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
                    # 현재 봉 정보 추가 (시간 포함)
                    candle_time = ""
                    if 'datetime' in data.columns:
                        try:
                            dt = pd.to_datetime(current['datetime'])
                            candle_time = f" {dt.strftime('%H:%M')}"
                        except:
                            candle_time = ""
                    
                    current_candle_info = f"봉:{len(data)}개{candle_time} 종가:{current['close']:,.0f}원"
                    logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                               f"위험신호 감지: {[r.value for r in risk_signals]}")
                return (SignalStrength(SignalType.SELL, 100, 0, 
                                     [f'위험신호: {r.value}' for r in risk_signals], 
                                     volume_analysis.volume_ratio, 
                                     PullbackCandlePattern.get_bisector_status(current['close'], bisector_line)), 
                       risk_signals)
            
            # 4. 눌림목 과정 매물부담 체크 (매수 제외 조건)
            has_selling_pressure = PullbackCandlePattern.check_heavy_selling_pressure(data, baseline_volumes)
            
            # 5. 음봉 대량 거래량 제한 체크 (매수 제외 조건)
            has_bearish_volume_restriction = PullbackCandlePattern.check_bearish_volume_restriction(data, baseline_volumes)
            
            # 6. 이등분선 돌파 양봉 거래량 조건 체크 (매수 제외 조건)
            bisector_breakout_volume_ok = PullbackCandlePattern.check_bisector_breakout_volume(data)
            
            # 회피 조건들 처리
            avoid_result = PullbackUtils.handle_avoid_conditions(
                has_selling_pressure, has_bearish_volume_restriction, bisector_breakout_volume_ok,
                current, volume_analysis, bisector_line, data, debug, logger
            )
            if avoid_result is not None:
                return (avoid_result, [])
            
            # 7. 선행 상승 확인
            prior_uptrend = PullbackCandlePattern.check_prior_uptrend(data)
            
            # 8. 조정 품질 분석
            good_pullback = PullbackCandlePattern.analyze_pullback_quality(data, baseline_volumes)
            
            # 9. 지지선 상태 확인
            bisector_status = PullbackCandlePattern.get_bisector_status(current['close'], bisector_line)
            
            # 10. 변곡캔들 체크는 check_pullback_recovery_signal에서 처리됨
            has_turning_candle = True  # 회복 신호에서 이미 캔들 품질 확인함
            
            # 11. 필수 조건 체크: 눌림목 회복 신호 확인 (내부에서 저거래량 신호도 함께 확인)
            has_recovery_signal, has_similar_adjustment = PullbackCandlePattern.check_pullback_recovery_signal(data, baseline_volumes)
            
            # check_pullback_recovery_signal 내부에서 이미 저거래량 조건을 확인하므로 중복 호출 제거
            has_any_recovery_signal = has_recovery_signal
            
            # 회복 신호가 없으면 매수 신호 금지
            if not has_any_recovery_signal:
                signal_strength = SignalStrength(
                    signal_type=SignalType.WAIT,
                    confidence=30,
                    target_profit=0,
                    reasons=['눌림목 회복 신호 없음 (저거래량 조정 후 회복 양봉 필요)'],
                    volume_ratio=volume_analysis.volume_ratio,
                    bisector_status=bisector_status
                )
            else:
                # 12. 신호 생성 (제시된 로직 적용)
                signal_strength = PullbackCandlePattern.generate_confidence_signal(
                    bisector_status, volume_analysis, has_turning_candle, prior_uptrend, 
                    data, bisector_line_series, False
                )
                
                # 눌림목 회복 신호가 이미 저거래량 조건을 포함하므로 별도 보너스는 불필요
                
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
                # 현재 봉 정보 추가 (시간 포함)
                candle_time = ""
                if 'datetime' in data.columns:
                    try:
                        dt = pd.to_datetime(current['datetime'])
                        candle_time = f" {dt.strftime('%H:%M')}"
                    except:
                        candle_time = ""
                
                # 기준 거래량 정보 추가
                baseline_vol = volume_analysis.baseline_volume
                baseline_info = f", 기준거래량: {baseline_vol:,.0f}주" if baseline_vol > 0 else ""
                
                current_candle_info = f"봉:{len(data)}개{candle_time} 종가:{current['close']:,.0f}원"
                logger.info(f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                           f"신호: {signal_strength.signal_type.value}, 신뢰도: {signal_strength.confidence:.1f}%, "
                           f"거래량비율: {volume_analysis.volume_ratio:.1%}, 이등분선: {bisector_status.value}{baseline_info}")
            
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
            if data is None or data.empty or len(data) < 5:
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
            for i in range(5, len(data)):  # 최소 5개 데이터 필요
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
                            # 현재 봉 정보 추가 (시간 포함)
                            candle_time = ""
                            if 'datetime' in current_data.columns:
                                try:
                                    dt = pd.to_datetime(current_data['datetime'].iloc[-1])
                                    candle_time = f" {dt.strftime('%H:%M')}"
                                except:
                                    candle_time = ""
                            
                            current_candle_info = f"봉:{i+1}개{candle_time} 종가:{entry_price:,.0f}원"
                            logger.log(log_level, f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                                     f"매수 신호: {signal_strength.signal_type.value} "
                                     f"신뢰도: {signal_strength.confidence:.1f}% 가격: {entry_price:,.0f}원")
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
                            # 현재 봉 정보 추가 (시간 포함)
                            candle_time = ""
                            if 'datetime' in current_data.columns:
                                try:
                                    dt = pd.to_datetime(current_data['datetime'].iloc[-1])
                                    candle_time = f" {dt.strftime('%H:%M')}"
                                except:
                                    candle_time = ""
                            
                            current_candle_info = f"봉:{i+1}개{candle_time} 종가:{current_data['close'].iloc[-1]:,.0f}원"
                            logger.log(log_level, f"[{getattr(logger, '_stock_code', 'UNKNOWN')}] {current_candle_info} | "
                                     f"매도 신호: {[r.value for r in risk_signals]}")
            
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
    
