"""
패턴 조합 필터 - 4단계 패턴 데이터 기반 필터링

analyze_4stage_patterns.py 분석 결과를 바탕으로
각 단계별 최적 조건을 종합적으로 적용합니다.

분석 결과 (전체 7,582건):
- 1단계: 보통 길이 상승(6-10봉) - 승률 51.8%
- 2단계: 보통 길이 하락(3-4봉) - 승률 59.8% ⭐
- 3단계: 짧은 지지(≤2봉) - 거래량 비율 17.8%
- 4단계: 양봉 돌파 - 평균수익 0.31%
"""

from typing import Dict, Optional
import logging


class PatternCombinationFilter:
    """4단계 패턴 조합 필터 - 데이터 기반 다층 필터링"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # 필터링 기준 (데이터 분석 기반)
        self.enable_stage_filters = True  # 단계별 필터 활성화

    def analyze_4stage_pattern(self, debug_info: Dict) -> Dict:
        """
        4단계 패턴 상세 분석

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            각 단계별 분석 결과
        """
        analysis = {}

        # === 1단계: 상승 구간 분석 ===
        uptrend = debug_info.get('1_uptrend') or debug_info.get('uptrend', {})
        candle_count_1 = uptrend.get('candle_count', 0)

        if candle_count_1 <= 5:
            analysis['상승길이'] = '짧음(≤5봉)'
            analysis['상승길이_점수'] = -1  # 불리 (승률 44.4%)
        elif candle_count_1 <= 10:
            analysis['상승길이'] = '보통(6-10봉)'
            analysis['상승길이_점수'] = 1  # 유리 (승률 51.8%)
        else:
            analysis['상승길이'] = '김(>10봉)'
            analysis['상승길이_점수'] = 0  # 보통 (승률 51.2%)

        # === 2단계: 하락 구간 분석 (핵심!) ===
        decline = debug_info.get('2_decline') or debug_info.get('decline', {})
        candle_count_2 = decline.get('candle_count', 0)

        if candle_count_2 <= 2:
            analysis['하락길이'] = '짧음(≤2봉)'
            analysis['하락길이_점수'] = 0  # 보통 (승률 48.6%)
        elif candle_count_2 <= 4:
            analysis['하락길이'] = '보통(3-4봉)'
            analysis['하락길이_점수'] = 2  # 매우 유리 (승률 59.8% ⭐)
        else:
            analysis['하락길이'] = '김(>4봉)'
            analysis['하락길이_점수'] = -2  # 매우 불리 (승률 40.7%, 손실)

        # === 3단계: 지지 구간 분석 ===
        support = debug_info.get('3_support') or debug_info.get('support', {})
        candle_count_3 = support.get('candle_count', 0)
        vol_ratio_str = support.get('avg_volume_ratio', '0%')

        # 거래량 비율 추출
        try:
            vol_ratio = float(vol_ratio_str.replace('%', ''))
        except:
            vol_ratio = None

        if candle_count_3 <= 2:
            analysis['지지길이'] = '짧음(≤2봉)'
        elif candle_count_3 <= 4:
            analysis['지지길이'] = '보통(3-4봉)'
        else:
            analysis['지지길이'] = '김(>4봉)'

        # 거래량 분석 (중요!)
        if vol_ratio is not None:
            analysis['거래량비율'] = vol_ratio

            # 데이터 분석 결과: 거래량 많을수록 좋음
            if vol_ratio < 10:
                analysis['거래량_점수'] = -1  # 불리 (승률 47%, 수익 0.21%)
            elif vol_ratio < 20:
                analysis['거래량_점수'] = 0  # 보통 (승률 50.2%, 수익 0.34%)
            elif vol_ratio < 40:
                analysis['거래량_점수'] = 1  # 유리 (승률 48~56%)
            else:
                analysis['거래량_점수'] = 2  # 매우 유리 (승률 73.4%, 수익 1.57%)
        else:
            analysis['거래량비율'] = None
            analysis['거래량_점수'] = 0

        # === 4단계: 돌파 구간 분석 ===
        breakout = debug_info.get('4_breakout') or debug_info.get('breakout', {})
        candle = breakout.get('candle', {})

        open_price = candle.get('open', 0)
        close_price = candle.get('close', 0)

        if close_price > open_price:
            analysis['돌파형태'] = '양봉'
            analysis['돌파_점수'] = 1  # 유리 (평균수익 0.31%)
        elif close_price < open_price:
            analysis['돌파형태'] = '음봉'
            analysis['돌파_점수'] = 0  # 보통 (평균수익 0.20%)
        else:
            analysis['돌파형태'] = '평봉'
            analysis['돌파_점수'] = -1  # 불리 (평균수익 0.07%)

        # 종합 점수 계산
        total_score = (
            analysis.get('상승길이_점수', 0) +
            analysis.get('하락길이_점수', 0) * 2 +  # 하락길이가 가장 중요!
            analysis.get('거래량_점수', 0) +
            analysis.get('돌파_점수', 0)
        )

        analysis['종합점수'] = total_score

        return analysis

    def should_exclude(self, debug_info: Dict) -> tuple[bool, Optional[str]]:
        """
        패턴이 제외 대상인지 확인 (다층 필터링)

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            (제외 여부, 제외 이유)
        """
        if not debug_info:
            return True, "debug_info 없음"

        # 4단계 패턴 상세 분석
        analysis = self.analyze_4stage_pattern(debug_info)

        if not self.enable_stage_filters:
            return False, None

        # === 필수 차단 조건 (하이브리드 필터) ===

        # 1. 긴 하락(>4봉) 차단 (승률 40.7%, 손실)
        if analysis.get('하락길이_점수', 0) == -2:
            reason = f"차단: 긴 하락 {analysis['하락길이']} (승률 40.7%, 손실)"
            self.logger.info(f"🚫 {reason}")
            return True, reason

        # 2. 짧은 상승(≤5봉) 차단 (승률 44.9%)
        if analysis.get('상승길이_점수', 0) == -1:
            reason = f"차단: 짧은 상승 {analysis['상승길이']} (승률 44.9%, 급등 추격)"
            self.logger.info(f"🚫 {reason}")
            return True, reason

        # 3. 하락 3-4봉 아니면 차단 (짧은 하락 ≤2봉은 48.4% 승률)
        if analysis.get('하락길이_점수', 0) != 2:
            reason = f"차단: {analysis['하락길이']} (하락 3-4봉만 허용, 승률 59.3%)"
            self.logger.info(f"🚫 {reason}")
            return True, reason

        # === 최선 패턴 보너스 점수 ===

        bonus_score = 0
        bonus_reasons = []

        # 하락 3-4봉 (이미 위에서 확인됨, 여기 도달했다면 3-4봉)
        bonus_score += 3
        bonus_reasons.append("하락3-4봉(+3)")

        # 거래량 40%+ (승률 74.3%)
        vol_ratio = analysis.get('거래량비율', 0)
        if vol_ratio and vol_ratio >= 40:
            bonus_score += 2
            bonus_reasons.append("거래량40%+(+2)")
        elif vol_ratio and vol_ratio >= 20:
            bonus_score += 1
            bonus_reasons.append("거래량20-40%(+1)")

        # 상승 6-10봉 (승률 54.4%)
        if analysis.get('상승길이_점수', 0) == 1:
            bonus_score += 1
            bonus_reasons.append("상승6-10봉(+1)")

        # 양봉 돌파 (승률 50.8%)
        if analysis.get('돌파_점수', 0) == 1:
            bonus_score += 1
            bonus_reasons.append("양봉돌파(+1)")

        # === 보너스 점수로 필터링 ===

        # 최소 4점 이상 필요 (기본 3점 + 추가 1점 이상)
        if bonus_score < 4:
            reason = (
                f"차단: 보너스 점수 부족 (점수: {bonus_score}/4): "
                f"상승{analysis['상승길이']}, "
                f"거래량{analysis.get('거래량비율', 'N/A')}%, "
                f"{analysis['돌파형태']}"
            )
            self.logger.info(f"🚫 {reason}")
            return True, reason

        # 통과
        reason = (
            f"✅ 패턴 허용 (보너스: {bonus_score}점 - {', '.join(bonus_reasons)}): "
            f"상승{analysis['상승길이']}, "
            f"하락{analysis['하락길이']}, "
            f"거래량{analysis.get('거래량비율', 'N/A')}%, "
            f"{analysis['돌파형태']}"
        )
        self.logger.info(reason)
        return False, None

    def categorize_pattern(self, debug_info: Dict) -> Dict[str, str]:
        """
        기존 호환성 유지를 위한 패턴 분류 (사용 안함)
        """
        return {}

    def get_filter_stats(self) -> Dict:
        """
        필터 통계 정보 반환

        Returns:
            필터 통계
        """
        return {
            'filter_mode': '4-stage-analysis',
            'filter_type': 'multi-layer',
            'stage1_criteria': '상승길이 (6-10봉 선호)',
            'stage2_criteria': '하락길이 (3-4봉 필수, >4봉 차단)',
            'stage3_criteria': '거래량비율 (15%+ 선호)',
            'stage4_criteria': '돌파형태 (양봉 선호, 평봉 차단)',
            'expected_improvement': '59.8% 승률 (하락 3-4봉 조건)',
        }


# ==============================================================================
# 🚫 [주석처리] 기존 필터들
# ==============================================================================
"""
# [버전 1] 블랙리스트 방식 (11개 조합 제외)
self.excluded_combinations = [
    {'상승강도': '약함(<4%)', '하락정도': '보통(1.5-2.5%)', '지지길이': '짧음(≤2)'},
    {'상승강도': '강함(>6%)', '하락정도': '얕음(<1.5%)', '지지길이': '보통(3-4)'},
    ... (생략)
]

# [버전 2] 화이트리스트 방식 (승률 60% 이상 4개 조합만 허용)
self.allowed_combinations = [
    {'상승강도': '강함(>6%)', '하락정도': '보통(1.5-2.5%)', '지지길이': '김(>4)'},  # 75% 승률
    {'상승강도': '강함(>6%)', '하락정도': '얕음(<1.5%)', '지지길이': '김(>4)'},  # 75% 승률
    {'상승강도': '보통(4-6%)', '하락정도': '얕음(<1.5%)', '지지길이': '김(>4)'},  # 71.9% 승률
    {'상승강도': '약함(<4%)', '하락정도': '얕음(<1.5%)', '지지길이': '보통(3-4)'},  # 68.1% 승률
]
# 문제점: 거래가 너무 적음 (359건, 4.8%)

# [버전 3] 현재 버전 - 4단계 상세 분석 기반
# - 각 단계별 최적 조건 적용
# - 점수 기반 종합 판단
# - 핵심: 하락 3-4봉 (승률 59.8%)
"""
