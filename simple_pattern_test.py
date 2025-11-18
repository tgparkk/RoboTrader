"""
간단한 패턴 검증기 테스트
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

import pandas as pd
import numpy as np

# 가상의 3분봉 데이터 생성 (413630과 유사한 패턴)
def create_test_data():
    # 약한 상승 -> 하락 -> 지지 -> 약한 돌파 패턴 (413630 스타일)
    data = {
        'datetime': pd.date_range('2025-09-25 09:00:00', periods=20, freq='3T'),
        'open': [3000, 3010, 3020, 3030, 3040, 3050, 3045, 3040, 3035, 3030,
                 3025, 3020, 3015, 3020, 3025, 3030, 3035, 3040, 3045, 3050],
        'high': [3015, 3025, 3035, 3045, 3055, 3065, 3050, 3045, 3040, 3035,
                 3030, 3025, 3020, 3025, 3030, 3035, 3040, 3045, 3050, 3055],
        'low':  [2995, 3005, 3015, 3025, 3035, 3045, 3035, 3030, 3025, 3020,
                 3015, 3010, 3005, 3010, 3015, 3020, 3025, 3030, 3035, 3040],
        'close':[3010, 3020, 3030, 3040, 3050, 3060, 3040, 3035, 3030, 3025,
                 3020, 3015, 3020, 3025, 3030, 3035, 3040, 3045, 3050, 3055],
        'volume':[1000, 1200, 1500, 1800, 2000, 2200, 800, 600, 500, 400,
                  300, 250, 200, 300, 400, 500, 600, 700, 800, 900]
    }

    df = pd.DataFrame(data)
    return df

def test_pattern_validator():
    print("=" * 50)
    print("패턴 검증기 간단 테스트")
    print("=" * 50)

    try:
        from core.indicators.pullback_candle_pattern import PullbackCandlePattern
        from core.indicators.pullback_pattern_validator import PullbackPatternValidator

        # 테스트 데이터 생성
        test_data = create_test_data()
        print(f"테스트 데이터 생성: {len(test_data)}개 3분봉")

        # 지지 패턴 분석
        support_pattern_result = PullbackCandlePattern.analyze_support_pattern(test_data, debug=True)

        print("\n=== 지지 패턴 분석 결과 ===")
        print(f"has_support_pattern: {support_pattern_result.get('has_support_pattern', False)}")
        print(f"confidence: {support_pattern_result.get('confidence', 0):.1f}%")

        debug_info = support_pattern_result.get('debug_info', {})
        print(f"debug_info 존재: {len(debug_info) > 0}")

        if debug_info:
            uptrend = debug_info.get('best_uptrend', {})
            decline = debug_info.get('best_decline', {})
            support = debug_info.get('best_support', {})
            breakout = debug_info.get('best_breakout', {})

            print(f"\n상승구간: {uptrend.get('price_gain', 0)*100:.1f}% 상승")
            print(f"하락구간: {decline.get('decline_pct', 0)*100:.1f}% 하락")
            print(f"지지구간: 변동성 {support.get('price_volatility', 0)*100:.2f}%")
            print(f"돌파양봉: 거래량 증가 {breakout.get('volume_ratio_vs_prev', 1.0)*100:.0f}%")

        # 패턴 검증기 테스트
        validator = PullbackPatternValidator()
        pattern_quality = validator.validate_pattern(test_data, support_pattern_result)

        print("\n=== 패턴 검증 결과 ===")
        print(f"통과 여부: {'통과' if pattern_quality.is_clear else '차단'}")
        print(f"신뢰도 점수: {pattern_quality.confidence_score:.1f}점")

        if not pattern_quality.is_clear:
            print(f"차단 사유: {pattern_quality.exclude_reason}")
            print(f"약점: {pattern_quality.weak_points}")
        else:
            print(f"강점: {pattern_quality.strength_points}")

        # 더 강한 패턴 테스트
        print("\n" + "=" * 50)
        print("강한 패턴 테스트")
        print("=" * 50)

        # 강한 패턴 데이터 생성
        strong_data = create_strong_pattern_data()
        print(f"강한 패턴 데이터 생성: {len(strong_data)}개 3분봉")

        support_pattern_result2 = PullbackCandlePattern.analyze_support_pattern(strong_data, debug=True)
        pattern_quality2 = validator.validate_pattern(strong_data, support_pattern_result2)

        print(f"강한 패턴 검증 결과: {'통과' if pattern_quality2.is_clear else '차단'}")
        print(f"강한 패턴 신뢰도: {pattern_quality2.confidence_score:.1f}점")

        if not pattern_quality2.is_clear:
            print(f"강한 패턴 차단 사유: {pattern_quality2.exclude_reason}")

    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()

def create_strong_pattern_data():
    # 강한 상승 -> 적절한 하락 -> 안정적 지지 -> 강한 돌파
    data = {
        'datetime': pd.date_range('2025-09-25 09:00:00', periods=20, freq='3T'),
        'open': [3000, 3020, 3050, 3080, 3120, 3150, 3140, 3130, 3120, 3110,
                 3105, 3100, 3095, 3100, 3105, 3110, 3120, 3140, 3160, 3180],
        'high': [3025, 3055, 3085, 3125, 3155, 3185, 3145, 3135, 3125, 3115,
                 3110, 3105, 3100, 3105, 3110, 3120, 3130, 3150, 3170, 3190],
        'low':  [2995, 3015, 3045, 3075, 3115, 3145, 3125, 3115, 3105, 3095,
                 3090, 3085, 3080, 3085, 3090, 3100, 3110, 3130, 3150, 3170],
        'close':[3020, 3050, 3080, 3120, 3150, 3180, 3130, 3120, 3110, 3100,
                 3100, 3095, 3100, 3105, 3110, 3120, 3140, 3160, 3180, 3200],
        'volume':[1000, 1500, 2000, 2500, 3000, 3500, 1000, 800, 600, 500,
                  400, 300, 350, 400, 500, 800, 1200, 1800, 2500, 3000]
    }

    df = pd.DataFrame(data)
    return df

if __name__ == "__main__":
    test_pattern_validator()