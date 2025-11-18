import sys
sys.path.insert(0, r'D:\GIT\RoboTrader')

import pickle
import pandas as pd

print('='*80)
print('메모리 데이터 vs 캐시 파일 상세 비교 - 001520')
print('='*80)

# 1. 캐시 파일 로드
cache_data = pickle.load(open(r'D:\GIT\RoboTrader\cache\minute_data\001520_20251016.pkl', 'rb'))
print(f'\n1. 캐시 파일 (PKL): {len(cache_data)}개 1분봉')
print('   시작:', cache_data.iloc[0]['time'])
print('   끝:', cache_data.iloc[-1]['time'])

# 2. 메모리 덤프 파일에서 001520 데이터 파싱
memory_data_list = []
in_realtime_section = False
is_001520 = False

with open(r'D:\GIT\RoboTrader\logs\memory_minute_data_20251016_153018.txt', 'r', encoding='utf-8') as f:
    for line in f:
        # 001520 섹션 시작 감지
        if '종목코드: 001520' in line:
            is_001520 = True
            continue

        # 다른 종목 섹션 시작되면 중단
        if is_001520 and '====' in line and '종목코드:' in line:
            break

        # Realtime Data 섹션 감지
        if is_001520 and '[Realtime Data:' in line:
            in_realtime_section = True
            continue

        # 데이터 라인 파싱 (20251016으로 시작)
        if is_001520 and in_realtime_section and line.strip().startswith('20251016'):
            parts = line.split()
            if len(parts) >= 8:
                try:
                    memory_data_list.append({
                        'date': parts[0],
                        'time': parts[1],
                        'close': float(parts[2]),
                        'open': float(parts[3]),
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'volume': float(parts[6])
                    })
                except:
                    pass

memory_data = pd.DataFrame(memory_data_list)
print(f'\n2. 메모리 데이터 (TXT): {len(memory_data)}개 1분봉')
print('   시작:', memory_data.iloc[0]['time'])
print('   끝:', memory_data.iloc[-1]['time'])

# 3. 09:50~09:55 구간 상세 비교
print('\n' + '='*80)
print('3. 09:50~09:55 구간 상세 비교')
print('='*80)

# 캐시 파일 (09:50~09:55)
cache_slice = cache_data[(cache_data['time'] >= '095000') & (cache_data['time'] <= '095500')][['time', 'close', 'volume']]
print('\n캐시 파일 (PKL):')
print(cache_slice.to_string(index=False))

# 메모리 데이터 (09:50~09:55)
memory_slice = memory_data[(memory_data['time'] >= '095000') & (memory_data['time'] <= '095500')][['time', 'close', 'volume']]
print('\n메모리 데이터 (TXT):')
print(memory_slice.to_string(index=False))

# 4. 차이점 분석
print('\n' + '='*80)
print('4. 차이점 분석')
print('='*80)

differences = []
for idx in range(len(cache_slice)):
    cache_row = cache_slice.iloc[idx]
    time_val = cache_row['time']

    # 메모리에서 같은 시간 찾기
    memory_match = memory_slice[memory_slice['time'] == time_val]

    if len(memory_match) > 0:
        memory_row = memory_match.iloc[0]

        close_diff = abs(cache_row['close'] - memory_row['close'])
        volume_diff = abs(cache_row['volume'] - memory_row['volume'])

        if close_diff > 0.01 or volume_diff > 0.01:
            differences.append({
                'time': time_val,
                'cache_close': cache_row['close'],
                'memory_close': memory_row['close'],
                'cache_volume': cache_row['volume'],
                'memory_volume': memory_row['volume'],
                'close_diff': close_diff,
                'volume_diff': volume_diff
            })

if differences:
    print(f'\n차이가 있는 봉: {len(differences)}개')
    for diff in differences:
        print(f"\n시간: {diff['time']}")
        print(f"  종가: 캐시={diff['cache_close']:>8.1f} | 메모리={diff['memory_close']:>8.1f} | 차이={diff['close_diff']:>8.1f}")
        print(f"  거래량: 캐시={diff['cache_volume']:>12,.0f} | 메모리={diff['memory_volume']:>12,.0f} | 차이={diff['volume_diff']:>12,.0f}")
else:
    print('\n차이 없음')

# 5. 09:51 3분봉 계산 비교
print('\n' + '='*80)
print('5. 09:51 3분봉 계산 (09:51~09:53)')
print('='*80)

# 캐시 파일 기준
cache_0951_data = cache_data[(cache_data['time'] >= '095100') & (cache_data['time'] <= '095300')]
cache_3min_open = cache_0951_data.iloc[0]['open']
cache_3min_high = cache_0951_data['high'].max()
cache_3min_low = cache_0951_data['low'].min()
cache_3min_close = cache_0951_data.iloc[-1]['close']
cache_3min_volume = cache_0951_data['volume'].sum()

print('\n캐시 파일 (PKL) 기준:')
print(f'  시가: {cache_3min_open:,.0f}')
print(f'  고가: {cache_3min_high:,.0f}')
print(f'  저가: {cache_3min_low:,.0f}')
print(f'  종가: {cache_3min_close:,.0f}')
print(f'  거래량: {cache_3min_volume:,.0f}')

# 메모리 데이터 기준
memory_0951_data = memory_data[(memory_data['time'] >= '095100') & (memory_data['time'] <= '095300')]
memory_3min_open = memory_0951_data.iloc[0]['open']
memory_3min_high = memory_0951_data['high'].max()
memory_3min_low = memory_0951_data['low'].min()
memory_3min_close = memory_0951_data.iloc[-1]['close']
memory_3min_volume = memory_0951_data['volume'].sum()

print('\n메모리 데이터 (TXT) 기준:')
print(f'  시가: {memory_3min_open:,.0f}')
print(f'  고가: {memory_3min_high:,.0f}')
print(f'  저가: {memory_3min_low:,.0f}')
print(f'  종가: {memory_3min_close:,.0f}')
print(f'  거래량: {memory_3min_volume:,.0f}')

print('\n차이:')
print(f'  시가: {abs(cache_3min_open - memory_3min_open):,.0f}')
print(f'  고가: {abs(cache_3min_high - memory_3min_high):,.0f}')
print(f'  저가: {abs(cache_3min_low - memory_3min_low):,.0f}')
print(f'  종가: {abs(cache_3min_close - memory_3min_close):,.0f}')
print(f'  거래량: {abs(cache_3min_volume - memory_3min_volume):,.0f}')

# 6. 시뮬레이션 리플레이 데이터와 비교
print('\n' + '='*80)
print('6. 시뮬레이션 리플레이 로그 비교')
print('='*80)
print('\n시뮬레이션 리플레이 로그:')
print('  09:51→09:54: 종가:1,189 | 거래량:2,544,215 | 강매수 | 신뢰도:88%')
print('\n캐시 파일 결과:')
print(f'  09:51 3분봉: 종가:{cache_3min_close:,.0f} | 거래량:{cache_3min_volume:,.0f}')
print('\n메모리 데이터 결과:')
print(f'  09:51 3분봉: 종가:{memory_3min_close:,.0f} | 거래량:{memory_3min_volume:,.0f}')

print('\n' + '='*80)
print('결론')
print('='*80)
if abs(cache_3min_volume - 2544215) < 1:
    print('\n캐시 파일은 시뮬레이션과 일치합니다.')
else:
    print(f'\n캐시 파일 거래량 차이: {abs(cache_3min_volume - 2544215):,.0f}')

if abs(memory_3min_volume - 861700) < 1:
    print('메모리 데이터는 09:52 거래량이 누락되어 861,700만 집계되었습니다.')
else:
    print(f'메모리 데이터 거래량: {memory_3min_volume:,.0f}')

print('\n핵심 원인:')
print('  실시간 장중에 09:52의 거래량이 0으로 수집되었습니다.')
print('  장 마감 후 캐시에는 정확한 거래량(1,682,515)이 저장되었습니다.')
print('  이로 인해 실시간 패턴 판단이 달라졌습니다.')

print('\n' + '='*80)
