import sys
sys.path.insert(0, r'D:\GIT\RoboTrader')

import pickle
import pandas as pd

print('='*80)
print('전체 데이터 비교 - 001520 (09:00~15:00)')
print('='*80)

# 1. 캐시 파일 로드
cache_data = pickle.load(open(r'D:\GIT\RoboTrader\cache\minute_data\001520_20251016.pkl', 'rb'))

# 당일 데이터만 필터링 (09:00~15:00)
cache_today = cache_data[cache_data['date'] == '20251016'].copy()
cache_today = cache_today[(cache_today['time'] >= '090000') & (cache_today['time'] <= '150000')]

print(f'\n1. 캐시 파일: {len(cache_today)}개 1분봉 (09:00~15:00)')

# 2. 메모리 덤프 파일에서 001520 Realtime Data 파싱
memory_data_list = []
in_realtime_section = False
is_001520 = False
skip_next_section = False

with open(r'D:\GIT\RoboTrader\logs\memory_minute_data_20251016_153018.txt', 'r', encoding='utf-8') as f:
    for line in f:
        # 001520 섹션 시작 감지
        if '종목코드: 001520' in line:
            is_001520 = True
            in_realtime_section = False
            skip_next_section = False
            continue

        # 다른 종목 섹션 시작되면 중단
        if is_001520 and '====' in line and '종목코드:' in line and '001520' not in line:
            break

        # Realtime Data 섹션 감지
        if is_001520 and '[Realtime Data:' in line:
            if not skip_next_section:
                in_realtime_section = True
            skip_next_section = True
            continue

        # 데이터 라인 파싱 (20251016으로 시작하고 Realtime 섹션인 경우만)
        if is_001520 and in_realtime_section and line.strip().startswith('20251016'):
            parts = line.split()
            if len(parts) >= 8:
                try:
                    time_val = parts[1]
                    # 09:00~15:00 범위만
                    if '090000' <= time_val <= '150000':
                        memory_data_list.append({
                            'date': parts[0],
                            'time': time_val,
                            'close': float(parts[2]),
                            'open': float(parts[3]),
                            'high': float(parts[4]),
                            'low': float(parts[5]),
                            'volume': float(parts[6])
                        })
                except:
                    pass

memory_data = pd.DataFrame(memory_data_list)

# 중복 제거 (첫 번째 것만 유지)
memory_data = memory_data.drop_duplicates(subset=['time'], keep='first')

print(f'2. 메모리 데이터: {len(memory_data)}개 1분봉 (09:00~15:00)')

# 3. 시간별로 비교
print('\n' + '='*80)
print('3. 차이점 분석')
print('='*80)

differences = []
close_diffs = []
volume_diffs = []

# 캐시의 모든 시간에 대해 비교
for idx, cache_row in cache_today.iterrows():
    time_val = cache_row['time']

    # 메모리에서 같은 시간 찾기
    memory_match = memory_data[memory_data['time'] == time_val]

    if len(memory_match) == 0:
        differences.append({
            'time': time_val,
            'issue': '메모리에 없음',
            'cache_close': cache_row['close'],
            'memory_close': None,
            'cache_volume': cache_row['volume'],
            'memory_volume': None
        })
    else:
        memory_row = memory_match.iloc[0]

        close_diff = abs(cache_row['close'] - memory_row['close'])
        volume_diff = abs(cache_row['volume'] - memory_row['volume'])

        if close_diff > 0.01 or volume_diff > 0.01:
            differences.append({
                'time': time_val,
                'issue': '데이터 불일치',
                'cache_close': cache_row['close'],
                'memory_close': memory_row['close'],
                'cache_volume': cache_row['volume'],
                'memory_volume': memory_row['volume'],
                'close_diff': close_diff,
                'volume_diff': volume_diff
            })

            if close_diff > 0.01:
                close_diffs.append({
                    'time': time_val,
                    'cache': cache_row['close'],
                    'memory': memory_row['close'],
                    'diff': close_diff
                })

            if volume_diff > 0.01:
                volume_diffs.append({
                    'time': time_val,
                    'cache': cache_row['volume'],
                    'memory': memory_row['volume'],
                    'diff': volume_diff
                })

# 메모리에만 있고 캐시에 없는 시간
for idx, memory_row in memory_data.iterrows():
    time_val = memory_row['time']
    cache_match = cache_today[cache_today['time'] == time_val]

    if len(cache_match) == 0:
        differences.append({
            'time': time_val,
            'issue': '캐시에 없음',
            'cache_close': None,
            'memory_close': memory_row['close'],
            'cache_volume': None,
            'memory_volume': memory_row['volume']
        })

print(f'\n총 차이점: {len(differences)}개')

if len(differences) > 0:
    print('\n차이점 상세:')
    for i, diff in enumerate(differences[:20], 1):  # 최대 20개만 표시
        print(f"\n[{i}] 시간: {diff['time']}")
        print(f"    문제: {diff['issue']}")
        if diff['cache_close'] is not None and diff['memory_close'] is not None:
            print(f"    종가: 캐시={diff['cache_close']:>8.1f} | 메모리={diff['memory_close']:>8.1f} | 차이={diff.get('close_diff', 0):>8.1f}")
            print(f"    거래량: 캐시={diff['cache_volume']:>12,.0f} | 메모리={diff['memory_volume']:>12,.0f} | 차이={diff.get('volume_diff', 0):>12,.0f}")
        else:
            print(f"    종가: 캐시={diff['cache_close']} | 메모리={diff['memory_close']}")
            print(f"    거래량: 캐시={diff['cache_volume']} | 메모리={diff['memory_volume']}")

    if len(differences) > 20:
        print(f'\n... 외 {len(differences) - 20}개 더')
else:
    print('\n모든 데이터가 일치합니다!')

# 4. 통계 요약
print('\n' + '='*80)
print('4. 통계 요약')
print('='*80)

print(f'\n총 비교 대상: {len(cache_today)}개 1분봉')
print(f'차이가 있는 봉: {len(differences)}개')
print(f'일치하는 봉: {len(cache_today) - len([d for d in differences if d["issue"] == "데이터 불일치"])}개')

if close_diffs:
    print(f'\n종가 차이:')
    print(f'  차이 있는 봉: {len(close_diffs)}개')
    max_close_diff = max(close_diffs, key=lambda x: x['diff'])
    print(f'  최대 차이: {max_close_diff["time"]} (캐시={max_close_diff["cache"]:.1f}, 메모리={max_close_diff["memory"]:.1f}, 차이={max_close_diff["diff"]:.1f})')

if volume_diffs:
    print(f'\n거래량 차이:')
    print(f'  차이 있는 봉: {len(volume_diffs)}개')
    max_volume_diff = max(volume_diffs, key=lambda x: x['diff'])
    print(f'  최대 차이: {max_volume_diff["time"]} (캐시={max_volume_diff["cache"]:,.0f}, 메모리={max_volume_diff["memory"]:,.0f}, 차이={max_volume_diff["diff"]:,.0f})')

# 5. 09:52 특별 체크
print('\n' + '='*80)
print('5. 09:52 특별 확인')
print('='*80)

cache_0952 = cache_today[cache_today['time'] == '095200']
memory_0952 = memory_data[memory_data['time'] == '095200']

if len(cache_0952) > 0 and len(memory_0952) > 0:
    print(f'\n캐시: close={cache_0952.iloc[0]["close"]:.1f}, volume={cache_0952.iloc[0]["volume"]:,.0f}')
    print(f'메모리: close={memory_0952.iloc[0]["close"]:.1f}, volume={memory_0952.iloc[0]["volume"]:,.0f}')

    if cache_0952.iloc[0]['volume'] != memory_0952.iloc[0]['volume']:
        print('\n09:52의 거래량 차이가 가장 큰 문제입니다!')
        print(f'차이: {abs(cache_0952.iloc[0]["volume"] - memory_0952.iloc[0]["volume"]):,.0f}')
else:
    print('\n09:52 데이터를 찾을 수 없습니다.')

print('\n' + '='*80)
