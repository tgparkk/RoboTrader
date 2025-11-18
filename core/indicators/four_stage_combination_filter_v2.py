"""
4단계 조합 필터 V2 - 정밀 필터링

V1의 문제점을 수정:
- 부분 매칭 금지 (완전한 4단계 조합만 필터링)
- 충분한 거래 수(10건 이상) + 실제 손실 조합만 차단
- 과도한 감점 방지
"""

from typing import Dict, Optional, Tuple
import logging


class FourStageCombinationFilterV2:
    """4단계 조합 필터 V2 - 정밀 필터링"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # 🎯 고승률 조합 (거래수 10건 이상, 승률 70% 이상)
        # 분석 결과에서 추출한 실제 데이터
        self.high_win_rate_combinations = [
            # 상승-강함 + 하락-적정 + 지지-매우안정 + 돌파-음봉: 61건, 75.4%
            {
                '상승': '강함(5-7%)',
                '하락': '적정(1.5-2.5%)',
                '지지': '매우안정(<0.8%)',
                '돌파': '음봉',
                'bonus': 10
            },
            # 상승-적정 + 하락-약함 + 지지-안정 + 돌파-적정: 10건, 70%
            {
                '상승': '적정(3-5%)',
                '하락': '약함(<1.5%)',
                '지지': '안정(0.8-1.5%)',
                '돌파': '적정(30-60%)',
                'bonus': 10
            },
            # 상승-강함 + 하락-강함 + 지지-매우안정 + 돌파-음봉: 20건, 70%
            {
                '상승': '강함(5-7%)',
                '하락': '강함(2.5-4%)',
                '지지': '매우안정(<0.8%)',
                '돌파': '음봉',
                'bonus': 10
            },
        ]

        # 🚫 저승률 조합 (거래수 10건 이상, 승률 30% 이하 또는 손실)
        # 완전한 4단계 조합만 차단
        self.low_win_rate_combinations = [
            # 상승-과열 + 하락-급락 + 지지-매우안정 + 돌파-급등: 10건, 0%
            {
                '상승': '과열(7%+)',
                '하락': '급락(4%+)',
                '지지': '매우안정(<0.8%)',
                '돌파': '급등(80%+)',
                'penalty': -50
            },
            # 상승-과열 + 하락-급락 + 지지-매우안정 + 돌파-적정: 21건, 0%
            {
                '상승': '과열(7%+)',
                '하락': '급락(4%+)',
                '지지': '매우안정(<0.8%)',
                '돌파': '적정(30-60%)',
                'penalty': -50
            },
            # 상승-강함 + 하락-급락 + 지지-매우안정 + 돌파-강함: 13건, 0%
            {
                '상승': '강함(5-7%)',
                '하락': '급락(4%+)',
                '지지': '매우안정(<0.8%)',
                '돌파': '강함(60-80%)',
                'penalty': -50
            },
            # 상승-강함 + 하락-급락 + 지지-매우안정 + 돌파-약함: 7건, 0%
            {
                '상승': '강함(5-7%)',
                '하락': '급락(4%+)',
                '지지': '매우안정(<0.8%)',
                '돌파': '약함(<30%)',
                'penalty': -50
            },
            # 상승-적정 + 하락-강함 + 지지-매우안정 + 돌파-음봉: 9건, 0%
            {
                '상승': '적정(3-5%)',
                '하락': '강함(2.5-4%)',
                '지지': '매우안정(<0.8%)',
                '돌파': '음봉',
                'penalty': -50
            },
            # 상승-적정 + 하락-약함 + 지지-안정 + 돌파-음봉: 8건, 0%
            {
                '상승': '적정(3-5%)',
                '하락': '약함(<1.5%)',
                '지지': '안정(0.8-1.5%)',
                '돌파': '음봉',
                'penalty': -50
            },
            # 상승-강함 + 하락-급락 + 지지-매우안정 + 돌파-음봉: 13건, 23.1%
            {
                '상승': '강함(5-7%)',
                '하락': '급락(4%+)',
                '지지': '매우안정(<0.8%)',
                '돌파': '음봉',
                'penalty': -30
            },
            # 상승-과열 + 하락-급락 + 지지-매우안정 + 돌파-약함: 15건, 26.7%
            {
                '상승': '과열(7%+)',
                '하락': '급락(4%+)',
                '지지': '매우안정(<0.8%)',
                '돌파': '약함(<30%)',
                'penalty': -30
            },
        ]

    def classify_pattern_from_debug_info(self, debug_info: Dict) -> Dict[str, str]:
        """
        debug_info에서 4단계 패턴을 분류

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            {'상승': '적정(3-5%)', '하락': '약함(<1.5%)', '지지': '안정(0.8-1.5%)', '돌파': '적정(30-60%)'}
        """
        categories = {}

        # 1단계: 상승 패턴 (상승률 기준)
        uptrend = debug_info.get('uptrend') or debug_info.get('1_uptrend', {})
        price_gain_str = uptrend.get('price_gain', '0%')

        try:
            price_gain = self._parse_percentage(price_gain_str)
        except (ValueError, AttributeError):
            price_gain = 0.0

        if price_gain < 0.03:  # 3% 미만
            categories['상승'] = '약함(<3%)'
        elif 0.03 <= price_gain < 0.05:  # 3-5%
            categories['상승'] = '적정(3-5%)'
        elif 0.05 <= price_gain < 0.07:  # 5-7%
            categories['상승'] = '강함(5-7%)'
        else:  # 7% 이상
            categories['상승'] = '과열(7%+)'

        # 2단계: 하락 패턴 (하락률 기준)
        decline = debug_info.get('decline') or debug_info.get('2_decline', {})
        decline_pct_str = decline.get('decline_pct', '0%')

        try:
            decline_pct = self._parse_percentage(decline_pct_str)
        except (ValueError, AttributeError):
            decline_pct = 0.0

        if decline_pct < 0.015:  # 1.5% 미만
            categories['하락'] = '약함(<1.5%)'
        elif 0.015 <= decline_pct < 0.025:  # 1.5-2.5%
            categories['하락'] = '적정(1.5-2.5%)'
        elif 0.025 <= decline_pct < 0.04:  # 2.5-4%
            categories['하락'] = '강함(2.5-4%)'
        else:  # 4% 이상
            categories['하락'] = '급락(4%+)'

        # 3단계: 지지 패턴 (변동성 기준)
        support = debug_info.get('support') or debug_info.get('3_support', {})
        price_volatility_str = support.get('price_volatility', '0%')

        try:
            price_volatility = self._parse_percentage(price_volatility_str)
        except (ValueError, AttributeError):
            price_volatility = 0.0

        if price_volatility <= 0.008:  # 0.8% 이하
            categories['지지'] = '매우안정(<0.8%)'
        elif 0.008 < price_volatility <= 0.015:  # 0.8-1.5%
            categories['지지'] = '안정(0.8-1.5%)'
        elif 0.015 < price_volatility <= 0.025:  # 1.5-2.5%
            categories['지지'] = '보통(1.5-2.5%)'
        else:  # 2.5% 이상
            categories['지지'] = '불안정(2.5%+)'

        # 4단계: 돌파 패턴 (캔들 몸통 비율로 계산)
        breakout = debug_info.get('breakout') or debug_info.get('4_breakout', {})

        # 캔들 데이터 찾기 (여러 경로 시도)
        candle_data = None
        if 'best_breakout' in debug_info:
            candle_data = debug_info['best_breakout']
        elif 'candle' in breakout:
            candle_data = breakout['candle']

        if candle_data:
            # 캔들 데이터에서 직접 계산
            open_price = candle_data.get('open')
            close_price = candle_data.get('close')
            high_price = candle_data.get('high')
            low_price = candle_data.get('low')

            if all([open_price, close_price, high_price, low_price]):
                # 양봉 여부
                if close_price <= open_price:
                    categories['돌파'] = '음봉'
                else:
                    # 몸통 비율 계산
                    body_size = close_price - open_price
                    total_size = high_price - low_price

                    if total_size > 0:
                        body_ratio = body_size / total_size

                        if body_ratio < 0.3:
                            categories['돌파'] = '약함(<30%)'
                        elif 0.3 <= body_ratio < 0.6:
                            categories['돌파'] = '적정(30-60%)'
                        elif 0.6 <= body_ratio < 0.8:
                            categories['돌파'] = '강함(60-80%)'
                        else:
                            categories['돌파'] = '급등(80%+)'
                    else:
                        categories['돌파'] = '미분류'
            else:
                categories['돌파'] = '미분류'
        else:
            categories['돌파'] = '미분류'

        return categories

    def calculate_bonus_penalty(self, debug_info: Dict) -> Tuple[float, Optional[str]]:
        """
        4단계 조합에 따른 가점/감점 계산

        Args:
            debug_info: SupportPatternAnalyzer의 debug_info

        Returns:
            (가점/감점, 이유)
        """
        if not debug_info:
            return 0.0, None

        # 패턴 분류
        pattern = self.classify_pattern_from_debug_info(debug_info)

        # 미분류가 있으면 필터 적용 안 함
        if '미분류' in pattern.values():
            return 0.0, None

        # 1. 저승률 조합 확인 (우선순위 높음)
        # 완전 매칭만 허용
        for low_combo in self.low_win_rate_combinations:
            if self._exact_match(pattern, low_combo):
                penalty = low_combo.get('penalty', -20)
                reason = f"저승률 조합: {self._format_pattern(pattern)}"
                self.logger.info(f"⚠️ {reason} (감점: {penalty})")
                return penalty, reason

        # 2. 고승률 조합 확인
        # 완전 매칭만 허용
        for high_combo in self.high_win_rate_combinations:
            if self._exact_match(pattern, high_combo):
                bonus = high_combo.get('bonus', 10)
                reason = f"고승률 조합: {self._format_pattern(pattern)}"
                self.logger.info(f"🎯 {reason} (가점: +{bonus})")
                return bonus, reason

        return 0.0, None

    def _exact_match(self, pattern: Dict[str, str], combo: Dict) -> bool:
        """패턴이 조합과 정확히 일치하는지 확인 (모든 4단계 일치 필요)"""
        for key in ['상승', '하락', '지지', '돌파']:
            if pattern.get(key) != combo.get(key):
                return False
        return True

    def _format_pattern(self, pattern: Dict[str, str]) -> str:
        """패턴을 문자열로 포맷팅"""
        return f"{pattern.get('상승', '?')} + {pattern.get('하락', '?')} + {pattern.get('지지', '?')} + {pattern.get('돌파', '?')}"

    def _parse_percentage(self, value) -> float:
        """퍼센트 문자열을 float로 변환 (3.05% -> 0.0305)"""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            value = value.replace('%', '').replace(',', '').strip()
            parsed = float(value)
            # 이미 소수점 형태면 그대로, 아니면 100으로 나누기
            if parsed < 1.0:  # 이미 0.0305 형태
                return parsed
            else:  # 3.05 형태
                return parsed / 100
        return 0.0

    def get_filter_stats(self) -> Dict:
        """필터 통계 정보 반환"""
        return {
            'high_win_rate_combinations_count': len(self.high_win_rate_combinations),
            'low_win_rate_combinations_count': len(self.low_win_rate_combinations),
            'filtering_strategy': '완전한 4단계 조합 매칭 (부분 매칭 금지)',
            'expected_improvement': '정밀 필터링을 통한 오차 최소화',
        }
