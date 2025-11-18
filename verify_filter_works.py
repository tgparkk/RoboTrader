"""종가 위치 필터 정상 작동 검증"""
import sys
import pickle
import pandas as pd

sys.path.insert(0, 'd:/GIT/RoboTrader')

from core.indicators.pullback.support_pattern_analyzer import SupportPatternAnalyzer

# 과거 데이터 중 패턴이 있었던 날짜로 테스트
test_date = '20251107'
test_symbols = [
    '001750', '003380', '005680', '007810', '014940',
    '025820', '033830', '036810', '052020', '057880',
    '089970', '102280', '140430', '174900', '243880',
    '263750', '900290', '950130'
]

print('='*100)
print(f'best_breakout 데이터 생성 확인 ({test_date})')
print('='*100)
print()

found = 0

for symbol in test_symbols:
    try:
        # 데이터 로드
        pkl_path = f'd:/GIT/RoboTrader/cache/minute_data/{symbol}_{test_date}.pkl'
        with open(pkl_path, 'rb') as f:
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

        if result.has_pattern and result.breakout_candle:
            # debug_info 가져오기
            debug_info = analyzer.get_debug_info(df_3min)

            # best_breakout 확인
            if 'best_breakout' in debug_info:
                bb = debug_info['best_breakout']

                # 모든 필수 키가 있는지 확인
                required_keys = ['high', 'low', 'close', 'open', 'volume']
                has_all = all(k in bb for k in required_keys)

                if has_all and bb['high'] > 0 and bb['low'] > 0:
                    candle_range = bb['high'] - bb['low']
                    close_pos = (bb['close'] - bb['low']) / candle_range if candle_range > 0 else 0

                    status = "✅ 통과" if close_pos >= 0.55 else "🚫 필터링"

                    print(f"{status} {symbol}: 종가위치 {close_pos:.1%}")
                    print(f"   high={bb['high']:,.0f}, low={bb['low']:,.0f}, close={bb['close']:,.0f}")
                    print(f"   volume={bb['volume']:,.0f}, volume_ratio={bb.get('volume_ratio_vs_prev', 0)*100:.0f}%")
                    print()

                    found += 1

                    if found >= 5:  # 5개만 출력
                        break

    except FileNotFoundError:
        continue
    except Exception as e:
        continue

print('='*100)
if found > 0:
    print(f'✅ best_breakout 데이터 정상 생성 확인! ({found}개 패턴)')
    print('종가 위치 필터가 정상 작동할 것입니다.')
else:
    print('⚠️  패턴을 찾지 못했습니다. 다른 날짜로 테스트 필요')
print('='*100)
