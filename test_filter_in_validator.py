#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PullbackPatternValidator에서 필터가 실제로 작동하는지 테스트
"""

from core.indicators.pullback_pattern_validator import PullbackPatternValidator
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)

def test_validator_filter():
    """Validator에서 필터 작동 테스트"""

    print("=" * 80)
    print("PullbackPatternValidator 필터 작동 테스트")
    print("=" * 80)

    validator = PullbackPatternValidator()

    # 필터가 초기화되었는지 확인
    if hasattr(validator, 'combination_filter'):
        print("\n[OK] combination_filter 초기화됨")
    else:
        print("\n[ERROR] combination_filter 초기화 안됨")
        return

    # 테스트 케이스 1: 제외 대상 (약함 + 보통 + 짧음)
    support_pattern_result_1 = {
        'has_support_pattern': True,
        'confidence': 85.0,
        'debug_info': {
            '1_uptrend': {'price_gain': '3.5%'},
            '2_decline': {'decline_pct': '2.0%'},
            '3_support': {'candle_count': 2}
        }
    }

    print("\n" + "=" * 80)
    print("테스트 1: 약함(<4%) + 보통(1.5-2.5%) + 짧음(≤2) - 제외 대상")
    print("=" * 80)

    result_1 = validator.validate_pattern(None, support_pattern_result_1)
    print(f"\n판정: {'차단' if not result_1.is_clear else '통과'}")
    print(f"신뢰도: {result_1.confidence_score}")
    print(f"제외 이유: {result_1.exclude_reason}")

    # 테스트 케이스 2: 통과 (보통 + 보통 + 짧음) - 최고 성과 조합
    support_pattern_result_2 = {
        'has_support_pattern': True,
        'confidence': 85.0,
        'debug_info': {
            '1_uptrend': {'price_gain': '5.0%'},
            '2_decline': {'decline_pct': '2.0%'},
            '3_support': {'candle_count': 2}
        }
    }

    print("\n" + "=" * 80)
    print("테스트 2: 보통(4-6%) + 보통(1.5-2.5%) + 짧음(≤2) - 통과 예상")
    print("=" * 80)

    result_2 = validator.validate_pattern(None, support_pattern_result_2)
    print(f"\n판정: {'차단' if not result_2.is_clear else '통과'}")
    print(f"신뢰도: {result_2.confidence_score}")
    print(f"제외 이유: {result_2.exclude_reason}")

    # 테스트 케이스 3: 제외 대상 (강함 + 깊음 + 짧음)
    support_pattern_result_3 = {
        'has_support_pattern': True,
        'confidence': 85.0,
        'debug_info': {
            '1_uptrend': {'price_gain': '8.0%'},
            '2_decline': {'decline_pct': '3.0%'},
            '3_support': {'candle_count': 2}
        }
    }

    print("\n" + "=" * 80)
    print("테스트 3: 강함(>6%) + 깊음(>2.5%) + 짧음(≤2) - 제외 대상")
    print("=" * 80)

    result_3 = validator.validate_pattern(None, support_pattern_result_3)
    print(f"\n판정: {'차단' if not result_3.is_clear else '통과'}")
    print(f"신뢰도: {result_3.confidence_score}")
    print(f"제외 이유: {result_3.exclude_reason}")

    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)


if __name__ == '__main__':
    test_validator_filter()
