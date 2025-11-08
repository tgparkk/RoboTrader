"""
패턴 조합 필터 - 마이너스 수익 조합 제외

analyze_negative_profit_combinations.py 분석 결과를 바탕으로
손실이 큰 패턴 조합을 제외합니다.

변경 이력:
- v1: 11개 조합 제외 (백테스트: +31.3%, 실제: +2.3%)
- v2: TOP 5 조합만 제외 (손실이 가장 큰 5개, 총 -39.16%)
- v3: 거래 10건 이상만 제외 (4개, 총 97건, -25.42% 손실) ← 현재
"""

from typing import Dict, Optional
import logging


class PatternCombinationFilter:
    """4단계 패턴 조합 필터 - 거래 10건 이상 & 마이너스 수익 조합 제외"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # 제외할 조합 (거래 10건 이상 & 총 수익 마이너스)
        # analyze_negative_profit_combinations.py 분석 결과 기반
        self.excluded_combinations = [
            # 조합 1: 약함(<4%) + 깊음(>2.5%) + 짧음(≤2)
            # 49건, 승률 44.9%, 총 -9.20%
            {
                '상승강도': '약함(<4%)',
                '하락정도': '깊음(>2.5%)',
                '지지길이': '짧음(≤2)',
            },

            # 조합 2: 약함(<4%) + 보통(1.5-2.5%) + 짧음(≤2)
            # 21건, 승률 47.6%, 총 -3.85%
            {
                '상승강도': '약함(<4%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '짧음(≤2)',
            },

            # 조합 3: 보통(4-6%) + 보통(1.5-2.5%) + 보통(3-4)
            # 17건, 승률 47.1%, 총 -6.86%
            {
                '상승강도': '보통(4-6%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '보통(3-4)',
            },

            # 조합 4: 보통(4-6%) + 보통(1.5-2.5%) + 짧음(≤2)
            # 10건, 승률 50.0%, 총 -5.51%
            {
                '상승강도': '보통(4-6%)',
                '하락정도': '보통(1.5-2.5%)',
                '지지길이': '짧음(≤2)',
            },
        ]

    def categorize_pattern(self, debug_info: Dict) -> Dict[str, str]:
        """
        4단계 패턴을 카테고리로 분류

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            카테고리 딕셔너리 (상승강도, 하락정도, 지지길이)
        """
        categories = {}

        # 1단계: 상승 강도 (가격 상승률)
        uptrend = debug_info.get('1_uptrend') or debug_info.get('uptrend', {})
        price_gain_str = uptrend.get('price_gain', '0%')

        # 문자열 '%' 제거 후 float 변환
        try:
            uptrend_gain = float(price_gain_str.replace('%', ''))
        except (ValueError, AttributeError):
            uptrend_gain = 0.0

        if uptrend_gain < 4.0:
            categories['상승강도'] = '약함(<4%)'
        elif uptrend_gain < 6.0:
            categories['상승강도'] = '보통(4-6%)'
        else:
            categories['상승강도'] = '강함(>6%)'

        # 2단계: 하락 정도
        decline = debug_info.get('2_decline') or debug_info.get('decline', {})
        decline_pct_str = decline.get('decline_pct', '0%')

        # 문자열 '%' 제거 후 float 변환
        try:
            decline_pct = float(decline_pct_str.replace('%', ''))
        except (ValueError, AttributeError):
            decline_pct = 0.0

        if decline_pct < 1.5:
            categories['하락정도'] = '얕음(<1.5%)'
        elif decline_pct < 2.5:
            categories['하락정도'] = '보통(1.5-2.5%)'
        else:
            categories['하락정도'] = '깊음(>2.5%)'

        # 3단계: 지지 길이 (캔들 수)
        support = debug_info.get('3_support') or debug_info.get('support', {})
        support_candles = support.get('candle_count', 0)

        if support_candles <= 2:
            categories['지지길이'] = '짧음(≤2)'
        elif support_candles <= 4:
            categories['지지길이'] = '보통(3-4)'
        else:
            categories['지지길이'] = '김(>4)'

        return categories

    def should_exclude(self, debug_info: Dict) -> tuple[bool, Optional[str]]:
        """
        패턴 조합이 제외 대상인지 확인

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            (제외 여부, 제외 이유)
        """
        if not debug_info:
            return False, None

        # 패턴 카테고리 분류
        pattern_category = self.categorize_pattern(debug_info)

        # 제외 조합과 매칭
        for excluded_combo in self.excluded_combinations:
            match = True
            for key in ['상승강도', '하락정도', '지지길이']:
                if excluded_combo.get(key) != pattern_category.get(key):
                    match = False
                    break

            if match:
                # 패배 조합 - 제외
                reason = (
                    f"패배 조합: "
                    f"{pattern_category['상승강도']} + "
                    f"{pattern_category['하락정도']} + "
                    f"{pattern_category['지지길이']}"
                )
                self.logger.info(f"🚫 {reason}")
                return True, reason

        # 제외 조합이 아님 - 허용
        return False, None

    def get_filter_stats(self) -> Dict:
        """
        필터 통계 정보 반환

        Returns:
            필터 통계
        """
        return {
            'excluded_combinations_count': len(self.excluded_combinations),
            'filter_type': 'exclude_negative_combinations',
            'excluded_total_trades': 97,
            'excluded_total_loss': '-25.42%',
            'version': 'v3',
        }
