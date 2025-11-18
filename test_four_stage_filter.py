"""4단계 조합 필터 테스트"""

import sys
import logging
from core.indicators.four_stage_combination_filter import FourStageCombinationFilter

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# 실제 debug_info 샘플 (pattern_data_log에서 가져온 구조)
debug_info_sample = {
    'uptrend': {
        'start_idx': 0,
        'end_idx': 5,
        'candle_count': 6,
        'price_gain': '3.05%',  # 문자열 형태
        'max_volume': '58,464',
    },
    'decline': {
        'start_idx': 6,
        'end_idx': 7,
        'candle_count': 2,
        'decline_pct': '1.29%',  # 문자열 형태
    },
    'support': {
        'start_idx': 8,
        'end_idx': 9,
        'candle_count': 2,
        'price_volatility': '0.000%',  # 문자열 형태
    },
    'breakout': {
        'idx': 21,
        'body_size': None,  # null
        'volume': None,  # null
    },
    # best_breakout은 없음!
}

# 필터 테스트
print("="*80)
print("[4단계 조합 필터 테스트]")
print("="*80)

filter = FourStageCombinationFilter(logger=logger)

# 1. 패턴 분류 테스트
print("\n[1. 패턴 분류 테스트]")
pattern = filter.classify_pattern_from_debug_info(debug_info_sample)
print(f"분류 결과: {pattern}")

# 2. 가점/감점 계산 테스트
print("\n[2. 가점/감점 계산 테스트]")
bonus_penalty, reason = filter.calculate_bonus_penalty(debug_info_sample)
print(f"가점/감점: {bonus_penalty}")
print(f"이유: {reason}")

# 3. 돌파 캔들 데이터 추가 테스트
print("\n[3. best_breakout 추가 테스트]")
debug_info_with_candle = debug_info_sample.copy()
debug_info_with_candle['best_breakout'] = {
    'open': 5310.0,
    'close': 5340.0,  # 양봉
    'high': 5350.0,
    'low': 5310.0,
}

pattern2 = filter.classify_pattern_from_debug_info(debug_info_with_candle)
print(f"분류 결과 (캔들 추가): {pattern2}")

bonus_penalty2, reason2 = filter.calculate_bonus_penalty(debug_info_with_candle)
print(f"가점/감점: {bonus_penalty2}")
print(f"이유: {reason2}")

# 4. 저승률 조합 테스트 (돌파 음봉)
print("\n[4. 저승률 조합 테스트 (음봉)]")
debug_info_bearish = debug_info_sample.copy()
debug_info_bearish['best_breakout'] = {
    'open': 5340.0,
    'close': 5310.0,  # 음봉
    'high': 5350.0,
    'low': 5310.0,
}

pattern3 = filter.classify_pattern_from_debug_info(debug_info_bearish)
print(f"분류 결과 (음봉): {pattern3}")

bonus_penalty3, reason3 = filter.calculate_bonus_penalty(debug_info_bearish)
print(f"가점/감점: {bonus_penalty3}")
print(f"이유: {reason3}")

print("\n" + "="*80)
print("[테스트 완료]")
print("="*80)
