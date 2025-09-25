"""
눌림목 패턴 검증기 - 불명확한 패턴 필터링
413630 등 패배 사례를 바탕으로 불명확한 눌림목 패턴 식별 및 제외
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging
from utils.korean_time import now_kst

@dataclass
class PatternQuality:
    """패턴 품질 평가 결과"""
    is_clear: bool
    confidence_score: float  # 0-100점
    weak_points: List[str]
    strength_points: List[str]
    exclude_reason: Optional[str] = None

class PullbackPatternValidator:
    """눌림목 패턴 검증기 - 불명확한 패턴 제외"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # 🎯 413630 실패 분석 기반 강화된 기준 설정
        self.quality_thresholds = {
            # 상승 구간 품질
            'min_uptrend_strength': 5.0,  # 최소 5% 상승 (기존 3% → 5%)
            'min_uptrend_duration': 2,    # 최소 2개 캔들
            'max_uptrend_duration': 12,   # 최대 12개 캔들 (너무 길면 추세 약화)

            # 하락 구간 품질
            'min_decline_pct': 1.5,       # 최소 1.5% 하락
            'max_decline_pct': 8.0,       # 최대 8% 하락 (과도한 하락은 패턴 파괴)
            'min_decline_duration': 1,    # 최소 1개 캔들
            'max_decline_duration': 8,    # 최대 8개 캔들

            # 지지 구간 품질
            'max_support_volatility': 1.5, # 최대 1.5% 변동성 (기존 2.5% → 1.5%)
            'min_support_duration': 1,     # 최소 1개 캔들
            'max_support_duration': 6,     # 최대 6개 캔들
            'max_support_volume_ratio': 0.15, # 기준거래량의 15% 이하 (기존 25% → 15%)

            # 돌파 양봉 품질
            'min_breakout_volume_increase': 20.0, # 직전봉 대비 20% 이상 거래량 증가 (기존 1% → 20%)
            'min_breakout_body_pct': 1.0,         # 최소 1% 몸통
            'min_price_breakout_pct': 0.5,        # 지지 구간 최고가 대비 0.5% 이상 돌파

            # 전체 패턴 품질
            'min_total_confidence': 50.0,         # 최소 50점 (100점 만점) - 완화
            'max_pattern_duration': 25,           # 전체 패턴 최대 25개 캔들
        }

    def validate_pattern(self, data: pd.DataFrame, support_pattern_result: Dict) -> PatternQuality:
        """
        눌림목 패턴 품질 검증

        Args:
            data: 3분봉 데이터
            support_pattern_result: SupportPatternAnalyzer 분석 결과

        Returns:
            PatternQuality: 패턴 품질 평가 결과
        """
        try:
            if not support_pattern_result.get('has_support_pattern', False):
                self.logger.info(f"🚫 지지 패턴 없음 - 매수 차단")
                return PatternQuality(
                    is_clear=False,
                    confidence_score=0.0,
                    weak_points=["지지 패턴 없음"],
                    strength_points=[],
                    exclude_reason="기본 패턴 조건 미충족"
                )

            # 🚨 패턴 신뢰도가 극도로 낮으면 차단 (임계값 완화: 60% → 40%)
            pattern_confidence = support_pattern_result.get('confidence', 0.0)
            if pattern_confidence < 40.0:
                self.logger.info(f"🚫 패턴 신뢰도 극도로 낮음: {pattern_confidence:.1f}% < 40%")
                return PatternQuality(
                    is_clear=False,
                    confidence_score=0.0,
                    weak_points=[f"패턴 신뢰도 부족 {pattern_confidence:.1f}%"],
                    strength_points=[],
                    exclude_reason=f"패턴 신뢰도 부족 ({pattern_confidence:.1f}% < 40%)"
                )

            debug_info = support_pattern_result.get('debug_info', {})
            if not debug_info:
                # 디버그 정보 없으면 기본 점수로 통과 (완화된 조건)
                self.logger.debug(f"⚠️ 디버그 정보 없음 - 기본 점수로 평가")
                return PatternQuality(
                    is_clear=True,
                    confidence_score=50.0,  # 기본 통과 점수
                    weak_points=["디버그 정보 없음"],
                    strength_points=["기본 패턴 조건 충족"],
                    exclude_reason=None
                )

            weak_points = []
            strength_points = []
            confidence_score = 0.0

            # 1. 상승 구간 품질 검증 (25점 만점)
            uptrend_score = self._validate_uptrend_quality(debug_info, weak_points, strength_points)
            confidence_score += uptrend_score

            # 2. 하락 구간 품질 검증 (20점 만점)
            decline_score = self._validate_decline_quality(debug_info, weak_points, strength_points)
            confidence_score += decline_score

            # 3. 지지 구간 품질 검증 (25점 만점)
            support_score = self._validate_support_quality(debug_info, weak_points, strength_points)
            confidence_score += support_score

            # 4. 돌파 양봉 품질 검증 (30점 만점)
            breakout_score = self._validate_breakout_quality(debug_info, weak_points, strength_points)
            confidence_score += breakout_score

            # 5. 전체 패턴 연속성 검증 (추가 점수/감점)
            continuity_score = self._validate_pattern_continuity(debug_info, weak_points, strength_points)
            confidence_score += continuity_score

            # 6. 최종 판정
            is_clear = confidence_score >= self.quality_thresholds['min_total_confidence']
            exclude_reason = None if is_clear else f"신뢰도 부족 ({confidence_score:.1f}점 < {self.quality_thresholds['min_total_confidence']}점)"

            # 7. 413630 타입 패턴 특별 검증 (추가 안전장치)
            if is_clear:
                is_413630_type = self._check_413630_failure_pattern(debug_info, data)
                if is_413630_type:
                    is_clear = False
                    exclude_reason = "413630 유형의 불안정 패턴으로 제외"
                    weak_points.append("413630 유형 실패 패턴")

            result = PatternQuality(
                is_clear=is_clear,
                confidence_score=confidence_score,
                weak_points=weak_points,
                strength_points=strength_points,
                exclude_reason=exclude_reason
            )

            # 로깅
            if is_clear:
                self.logger.info(f"✅ 눌림목 패턴 품질 검증 통과: {confidence_score:.1f}점")
                self.logger.debug(f"   강점: {', '.join(strength_points[:3])}")
            else:
                self.logger.info(f"❌ 눌림목 패턴 품질 검증 실패: {exclude_reason}")
                self.logger.debug(f"   약점: {', '.join(weak_points[:3])}")

            return result

        except Exception as e:
            self.logger.error(f"패턴 품질 검증 오류: {e}")
            return PatternQuality(
                is_clear=False,
                confidence_score=0.0,
                weak_points=[f"검증 오류: {str(e)}"],
                strength_points=[],
                exclude_reason="검증 프로세스 오류"
            )

    def _validate_uptrend_quality(self, debug_info: Dict, weak_points: List[str], strength_points: List[str]) -> float:
        """상승 구간 품질 검증 (25점 만점)"""
        score = 0.0

        uptrend = debug_info.get('best_uptrend')
        if not uptrend:
            weak_points.append("상승 구간 정보 없음")
            return 0.0

        # 상승률 검증 (15점) - 기준 완화
        price_gain = uptrend.get('price_gain', 0) * 100
        if price_gain >= 5.0:  # 5% 이상이면 높은 점수
            score += 15
            strength_points.append(f"강한 상승률 {price_gain:.1f}%")
        elif price_gain >= 2.0:  # 2% 이상이면 기본 점수
            score += 10
            strength_points.append(f"적정 상승률 {price_gain:.1f}%")
        elif price_gain >= 1.0:  # 1% 이상이면 일부 점수
            score += 5
            strength_points.append(f"약한 상승률 {price_gain:.1f}%")
        else:
            weak_points.append(f"매우 약한 상승률 {price_gain:.1f}%")

        # 상승 기간 검증 (5점)
        duration = uptrend.get('end_idx', 0) - uptrend.get('start_idx', 0) + 1
        if self.quality_thresholds['min_uptrend_duration'] <= duration <= self.quality_thresholds['max_uptrend_duration']:
            score += 5
            strength_points.append(f"적정 상승기간 {duration}봉")
        else:
            weak_points.append(f"부적정 상승기간 {duration}봉")

        # 상승 구간 거래량 검증 (5점)
        volume_avg = uptrend.get('volume_avg', 0)
        max_volume = uptrend.get('max_volume', 1)
        if volume_avg >= max_volume * 0.7:  # 평균 거래량이 최대의 70% 이상
            score += 5
            strength_points.append("상승구간 거래량 충분")
        else:
            weak_points.append("상승구간 거래량 부족")

        return score

    def _validate_decline_quality(self, debug_info: Dict, weak_points: List[str], strength_points: List[str]) -> float:
        """하락 구간 품질 검증 (20점 만점)"""
        score = 0.0

        decline = debug_info.get('best_decline')
        if not decline:
            weak_points.append("하락 구간 정보 없음")
            return 0.0

        # 하락률 검증 (10점)
        decline_pct = decline.get('decline_pct', 0) * 100
        if self.quality_thresholds['min_decline_pct'] <= decline_pct <= self.quality_thresholds['max_decline_pct']:
            score += 10
            strength_points.append(f"적정 하락률 {decline_pct:.1f}%")
        else:
            weak_points.append(f"부적정 하락률 {decline_pct:.1f}%")

        # 하락 구간 거래량 검증 (10점)
        volume_ratio = decline.get('avg_volume_ratio', 1.0)
        if volume_ratio <= 0.3:  # 기준거래량의 30% 이하
            score += 10
            strength_points.append(f"하락구간 거래량 감소 {volume_ratio:.1%}")
        else:
            weak_points.append(f"하락구간 거래량 과다 {volume_ratio:.1%}")

        return score

    def _validate_support_quality(self, debug_info: Dict, weak_points: List[str], strength_points: List[str]) -> float:
        """지지 구간 품질 검증 (25점 만점)"""
        score = 0.0

        support = debug_info.get('best_support')
        if not support:
            weak_points.append("지지 구간 정보 없음")
            return 0.0

        # 가격 안정성 검증 (15점)
        volatility = support.get('price_volatility', 999) * 100
        if volatility <= self.quality_thresholds['max_support_volatility']:
            score += 15
            strength_points.append(f"안정적 지지 변동성 {volatility:.2f}%")
        else:
            weak_points.append(f"불안정한 지지 변동성 {volatility:.2f}%")

        # 지지 구간 거래량 검증 (10점)
        volume_ratio = support.get('avg_volume_ratio', 1.0)
        if volume_ratio <= self.quality_thresholds['max_support_volume_ratio']:
            score += 10
            strength_points.append(f"지지구간 저거래량 {volume_ratio:.1%}")
        else:
            weak_points.append(f"지지구간 거래량 과다 {volume_ratio:.1%}")

        return score

    def _validate_breakout_quality(self, debug_info: Dict, weak_points: List[str], strength_points: List[str]) -> float:
        """돌파 양봉 품질 검증 (30점 만점)"""
        score = 0.0

        breakout = debug_info.get('best_breakout')
        if not breakout:
            weak_points.append("돌파 양봉 정보 없음")
            return 0.0

        # 거래량 증가 검증 (15점) - 기준 완화
        volume_increase = breakout.get('volume_ratio_vs_prev', 1.0) * 100
        if volume_increase >= 50.0:  # 50% 이상이면 만점
            score += 15
            strength_points.append(f"강한 돌파 거래량 {volume_increase:.0f}%")
        elif volume_increase >= 20.0:  # 20% 이상이면 기본 점수
            score += 10
            strength_points.append(f"적정 돌파 거래량 {volume_increase:.0f}%")
        elif volume_increase >= 5.0:  # 5% 이상이면 일부 점수
            score += 5
            strength_points.append(f"약한 돌파 거래량 {volume_increase:.0f}%")
        else:
            weak_points.append(f"돌파 거래량 매우 부족 {volume_increase:.0f}%")

        # 몸통 크기 검증 (10점)
        body_increase = breakout.get('body_increase_vs_support', 0) * 100
        if body_increase >= self.quality_thresholds['min_breakout_body_pct']:
            score += 10
            strength_points.append(f"돌파양봉 몸통 {body_increase:.1f}%")
        else:
            weak_points.append(f"돌파양봉 몸통 부족 {body_increase:.1f}%")

        # 가격 돌파력 검증 (5점)
        breakout_idx = breakout.get('idx', -1)
        if breakout_idx >= 0:
            score += 5
            strength_points.append("가격 돌파 확인")
        else:
            weak_points.append("가격 돌파 불분명")

        return score

    def _validate_pattern_continuity(self, debug_info: Dict, weak_points: List[str], strength_points: List[str]) -> float:
        """패턴 연속성 검증 (추가/감점 최대 ±10점)"""
        score = 0.0

        try:
            uptrend = debug_info.get('best_uptrend', {})
            decline = debug_info.get('best_decline', {})
            support = debug_info.get('best_support', {})
            breakout = debug_info.get('best_breakout', {})

            # 각 구간의 연속성 확인
            uptrend_end = uptrend.get('end_idx', -1)
            decline_start = decline.get('start_idx', -1)
            decline_end = decline.get('end_idx', -1)
            support_start = support.get('start_idx', -1)
            support_end = support.get('end_idx', -1)
            breakout_idx = breakout.get('idx', -1)

            gaps = 0
            if uptrend_end >= 0 and decline_start >= 0 and decline_start - uptrend_end > 1:
                gaps += 1
            if decline_end >= 0 and support_start >= 0 and support_start - decline_end > 1:
                gaps += 1
            if support_end >= 0 and breakout_idx >= 0 and breakout_idx - support_end > 1:
                gaps += 1

            if gaps == 0:
                score += 5
                strength_points.append("완벽한 패턴 연속성")
            elif gaps <= 1:
                score += 2
                strength_points.append("양호한 패턴 연속성")
            else:
                score -= 5
                weak_points.append(f"패턴 연속성 부족 ({gaps}개 구간 단절)")

        except Exception as e:
            weak_points.append("패턴 연속성 확인 실패")

        return score

    def _check_413630_failure_pattern(self, debug_info: Dict, data: pd.DataFrame) -> bool:
        """413630 유형의 실패 패턴 특별 검증"""
        try:
            # 413630의 특징: 약한 상승 + 급한 하락 + 불안정한 지지 + 허약한 돌파
            uptrend = debug_info.get('best_uptrend', {})
            decline = debug_info.get('best_decline', {})
            support = debug_info.get('best_support', {})
            breakout = debug_info.get('best_breakout', {})

            risk_factors = 0

            # 1. 매우 약한 상승률만 차단 (3% 미만)
            price_gain = uptrend.get('price_gain', 0) * 100
            if price_gain < 3.0:  # 3% 미만은 위험
                risk_factors += 1
                self.logger.debug(f"위험 요인: 매우 약한 상승률 {price_gain:.1f}%")

            # 2. 지지 구간 과도한 변동성만 차단 (2.0% 이상)
            volatility = support.get('price_volatility', 0) * 100
            if volatility >= 2.0:  # 1.0% → 2.0%로 완화
                risk_factors += 1
                self.logger.debug(f"위험 요인: 지지구간 과도한 불안정 {volatility:.2f}%")

            # 3. 돌파 거래량 심각하게 부족한 경우만 차단 (10% 미만)
            volume_increase = breakout.get('volume_ratio_vs_prev', 1.0) * 100
            if volume_increase < 10.0:  # 30% → 10%로 완화
                risk_factors += 1
                self.logger.debug(f"위험 요인: 돌파 거래량 심각 부족 {volume_increase:.0f}%")

            # 4. 전체 패턴 기간이 극도로 짧은 경우만 차단 (8개 캔들 미만)
            total_candles = len(data)
            if total_candles < 8:  # 15개 → 8개로 완화
                risk_factors += 1
                self.logger.debug(f"위험 요인: 패턴 기간 극도로 부족 {total_candles}개")

            # 🆕 5. 상승-하락-지지 단계 연속성 부족
            if uptrend and decline and support:
                uptrend_end = uptrend.get('end_idx', -1)
                decline_start = decline.get('start_idx', -1)
                support_start = support.get('start_idx', -1)

                # 각 단계 사이에 gap이 있으면 위험
                if (decline_start - uptrend_end > 2) or (support_start - decline.get('end_idx', -1) > 2):
                    risk_factors += 1
                    self.logger.debug(f"위험 요인: 패턴 연속성 부족")

            # 위험 요인 4개 이상이면 413630 타입으로 판정 (매우 완화)
            is_risky = risk_factors >= 4  # 2개 → 4개로 완화 (거의 차단하지 않음)

            if is_risky:
                self.logger.info(f"🚨 413630 타입 극도로 불량한 패턴 감지: {risk_factors}개 위험 요인")

            return is_risky

        except Exception as e:
            self.logger.debug(f"413630 패턴 검증 오류: {e}")
            return False  # 오류 시 안전하게 통과 처리

    def get_validation_summary(self, quality: PatternQuality) -> str:
        """검증 결과 요약 문자열 반환"""
        if quality.is_clear:
            return f"✅ 품질검증통과 ({quality.confidence_score:.0f}점)"
        else:
            return f"❌ 품질검증실패: {quality.exclude_reason}"