"""종가 위치 필터 작동 테스트"""
import sys
import pickle
import pandas as pd

sys.path.insert(0, 'd:/GIT/RoboTrader')

from core.indicators.pullback.support_pattern_analyzer import SupportPatternAnalyzer
from core.indicators.pullback_pattern_validator import PullbackPatternValidator
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# 테스트할 종목 (오늘 거래된 종목들)
test_symbols = [
    '001750', '003380', '005680', '007810', '014940',
    '025820', '033830', '036810', '052020', '057880',
    '089970', '102280', '140430', '174900', '243880'
]

print('='*100)
print('종가 위치 필터 작동 테스트')
print('='*100)
print()

tested = 0
filtered = 0
passed = 0

for symbol in test_symbols:
    try:
        # 데이터 로드
        with open(f'd:/GIT/RoboTrader/cache/minute_data/{symbol}_20251111.pkl', 'rb') as f:
            df = pickle.load(f)

        # 3분봉 변환
        df_3min = df.set_index('datetime').resample('3min', label='right', closed='right').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        # 패턴 분석
        analyzer = SupportPatternAnalyzer()
        result = analyzer.analyze(df_3min)

        if not result.has_pattern:
            continue

        tested += 1

        # debug_info 가져오기
        support_pattern_result = {
            'has_support_pattern': result.has_pattern,
            'confidence': result.confidence,
            'debug_info': analyzer.get_debug_info(df_3min)
        }

        # 검증
        validator = PullbackPatternValidator(logger=logger)
        quality = validator.validate_pattern(df_3min, support_pattern_result)

        # best_breakout 확인
        debug_info = support_pattern_result['debug_info']

        if 'best_breakout' in debug_info:
            bb = debug_info['best_breakout']
            candle_range = bb['high'] - bb['low']
            close_pos = (bb['close'] - bb['low']) / candle_range if candle_range > 0 else 0

            if quality.is_clear:
                passed += 1
                print(f"✅ {symbol}: 통과 - 종가위치 {close_pos:.1%} (high={bb['high']}, low={bb['low']}, close={bb['close']})")
            else:
                filtered += 1
                print(f"🚫 {symbol}: 필터링 - 종가위치 {close_pos:.1%} < 55% (제외 이유: {quality.exclude_reason})")
        else:
            print(f"⚠️  {symbol}: best_breakout 없음")

    except Exception as e:
        pass

print()
print('='*100)
print(f'테스트 결과')
print('='*100)
print(f'패턴 발견: {tested}건')
print(f'필터 통과: {passed}건')
print(f'필터 차단: {filtered}건')
if tested > 0:
    print(f'필터링 비율: {filtered/tested*100:.1f}%')
