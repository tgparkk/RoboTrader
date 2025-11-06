#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
실제 debug_info 구조로 필터 테스트
"""

from core.indicators.pattern_combination_filter import PatternCombinationFilter
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_with_real_structure():
    """실제 get_debug_info() 반환 구조로 테스트"""

    print("=" * 80)
    print("실제 debug_info 구조로 필터 테스트")
    print("=" * 80)

    filter = PatternCombinationFilter(logger=logger)

    # 실제 get_debug_info() 반환 구조 (uptrend, decline, support)
    test_cases = [
        {
            'name': '제외 대상: 약함(<4%) + 보통(1.5-2.5%) + 짧음(≤2)',
            'debug_info': {
                'uptrend': {
                    'price_gain': '3.5%',
                    'max_volume': '88060'
                },
                'decline': {
                    'decline_pct': '2.0%',
                    'candle_count': 2
                },
                'support': {
                    'candle_count': 2,
                    'avg_volume_ratio': '13.3%'
                }
            },
            'expected': True
        },
        {
            'name': '통과: 보통(4-6%) + 보통(1.5-2.5%) + 짧음(≤2) - 최고 성과',
            'debug_info': {
                'uptrend': {
                    'price_gain': '4.33%',
                    'max_volume': '88060'
                },
                'decline': {
                    'decline_pct': '1.13%',
                    'candle_count': 2
                },
                'support': {
                    'candle_count': 2,
                    'avg_volume_ratio': '13.3%'
                }
            },
            'expected': False
        },
        {
            'name': '제외 대상: 강함(>6%) + 깊음(>2.5%) + 짧음(≤2)',
            'debug_info': {
                'uptrend': {
                    'price_gain': '8.0%',
                    'max_volume': '100000'
                },
                'decline': {
                    'decline_pct': '3.0%',
                    'candle_count': 2
                },
                'support': {
                    'candle_count': 2,
                    'avg_volume_ratio': '10.0%'
                }
            },
            'expected': True
        }
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"테스트 {i}: {test['name']}")
        print(f"{'='*80}")

        # 패턴 카테고리 분류
        categories = filter.categorize_pattern(test['debug_info'])
        print(f"\n분류 결과:")
        print(f"  상승강도: {categories.get('상승강도', 'N/A')}")
        print(f"  하락정도: {categories.get('하락정도', 'N/A')}")
        print(f"  지지길이: {categories.get('지지길이', 'N/A')}")

        # 필터 적용
        should_exclude, reason = filter.should_exclude(test['debug_info'])

        print(f"\n필터 결과:")
        print(f"  제외 여부: {should_exclude}")
        print(f"  제외 이유: {reason}")
        print(f"  예상 결과: {test['expected']}")

        if should_exclude == test['expected']:
            print(f"  [OK] 테스트 통과")
        else:
            print(f"  [FAIL] 테스트 실패!")

    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)


if __name__ == '__main__':
    test_with_real_structure()
