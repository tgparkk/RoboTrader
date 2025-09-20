"""
빠른 신호 테스트 - 실제 시그널 재생 없이 조건만 확인
"""

import sys
import os
sys.path.append(os.getcwd())

from core.indicators.pullback_candle_pattern import analyze_daily_pattern_strength
from datetime import datetime

def test_time_conditions():
    """시간대별 조건 테스트"""
    print("시간대별 조건 테스트")
    print("="*50)

    # 현재 시각
    current_time = datetime.now()
    print(f"현재 시각: {current_time.hour}시 {current_time.minute}분")

    # 샘플 일봉 분석
    daily_pattern = analyze_daily_pattern_strength("036570", "20250919")
    daily_strength = daily_pattern['strength']
    is_ideal_daily = daily_pattern['ideal_pattern']

    print(f"일봉 강도: {daily_strength}")
    print(f"이상적 패턴: {is_ideal_daily}")

    # 시간대별 조건 적용
    if 12 <= current_time.hour < 14:  # 오후시간
        min_confidence = 85
        if daily_strength < 60:
            min_confidence = 95
        elif is_ideal_daily:
            min_confidence = 80
        time_category = "오후시간 (매우 엄격)"
    elif 9 <= current_time.hour < 10:  # 개장시간
        min_confidence = 70
        if daily_strength >= 70:
            min_confidence = 65
        elif daily_strength < 40:
            min_confidence = 80
        time_category = "개장시간 (관대)"
    else:  # 오전/늦은시간
        min_confidence = 75
        if is_ideal_daily and daily_strength >= 70:
            min_confidence = 70
        elif daily_strength < 50:
            min_confidence = 85
        if 14 <= current_time.hour < 15:
            time_category = "늦은시간 (기본)"
        else:
            time_category = "오전시간 (기본)"

    print(f"적용된 조건: {time_category}")
    print(f"최소 신뢰도 요구: {min_confidence}%")

    # 일반적인 패턴 신뢰도와 비교
    typical_confidence = 75
    if typical_confidence >= min_confidence:
        print(f"✅ 신호 발생 가능 (패턴신뢰도 {typical_confidence}% >= 요구 {min_confidence}%)")
    else:
        print(f"❌ 신호 차단됨 (패턴신뢰도 {typical_confidence}% < 요구 {min_confidence}%)")

    return min_confidence

if __name__ == "__main__":
    test_time_conditions()