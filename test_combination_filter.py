#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
패턴 조합 필터 테스트

마이너스 수익 조합이 올바르게 필터링되는지 확인
"""

from core.indicators.pattern_combination_filter import PatternCombinationFilter


def test_filter():
    """필터 테스트"""
    filter = PatternCombinationFilter()

    print("=" * 80)
    print("패턴 조합 필터 테스트")
    print("=" * 80)

    # 필터 통계
    stats = filter.get_filter_stats()
    print("\n[필터 통계]")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 80)
    print("테스트 케이스")
    print("=" * 80)

    # 테스트 케이스 1: 제외 대상 (약함 + 보통 + 짧음)
    # 실제 debug_info 구조에 맞게 수정
    test_case_1 = {
        'uptrend': {'price_gain': '3.5%'},
        'decline': {'decline_pct': '2.0%'},
        'support': {'candle_count': 2},
    }

    should_exclude, reason = filter.should_exclude(test_case_1)
    print(f"\n[테스트 1] 약함(3.5%) + 보통(2.0%) + 짧음(2개)")
    print(f"  제외 여부: {should_exclude}")
    print(f"  이유: {reason}")

    # 테스트 케이스 2: 제외 대상 (강함 + 얕음 + 보통)
    test_case_2 = {
        'uptrend': {'price_gain': '7.0%'},
        'decline': {'decline_pct': '1.0%'},
        'support': {'candle_count': 3},
    }

    should_exclude, reason = filter.should_exclude(test_case_2)
    print(f"\n[테스트 2] 강함(7.0%) + 얕음(1.0%) + 보통(3개)")
    print(f"  제외 여부: {should_exclude}")
    print(f"  이유: {reason}")

    # 테스트 케이스 3: 통과 (보통 + 보통 + 짧음) - 최고 성과 조합
    test_case_3 = {
        'uptrend': {'price_gain': '5.0%'},
        'decline': {'decline_pct': '2.0%'},
        'support': {'candle_count': 2},
    }

    should_exclude, reason = filter.should_exclude(test_case_3)
    print(f"\n[테스트 3] 보통(5.0%) + 보통(2.0%) + 짧음(2개)")
    print(f"  제외 여부: {should_exclude}")
    print(f"  이유: {reason if reason else 'N/A (통과)'}")

    # 테스트 케이스 4: 통과 (강함 + 보통 + 짧음)
    test_case_4 = {
        'uptrend': {'price_gain': '6.5%'},
        'decline': {'decline_pct': '2.0%'},
        'support': {'candle_count': 1},
    }

    should_exclude, reason = filter.should_exclude(test_case_4)
    print(f"\n[테스트 4] 강함(6.5%) + 보통(2.0%) + 짧음(1개)")
    print(f"  제외 여부: {should_exclude}")
    print(f"  이유: {reason if reason else 'N/A (통과)'}")

    # 테스트 케이스 5: 제외 대상 (강함 + 깊음 + 짧음)
    test_case_5 = {
        'uptrend': {'price_gain': '8.0%'},
        'decline': {'decline_pct': '3.0%'},
        'support': {'candle_count': 2},
    }

    should_exclude, reason = filter.should_exclude(test_case_5)
    print(f"\n[테스트 5] 강함(8.0%) + 깊음(3.0%) + 짧음(2개)")
    print(f"  제외 여부: {should_exclude}")
    print(f"  이유: {reason}")

    print("\n" + "=" * 80)
    print("제외 조합 목록")
    print("=" * 80)

    for i, combo in enumerate(filter.excluded_combinations, 1):
        print(f"\n{i}. {combo['상승강도']} + {combo['하락정도']} + {combo['지지길이']}")

    print("\n" + "=" * 80)
    print("테스트 완료!")
    print("=" * 80)


if __name__ == '__main__':
    test_filter()
