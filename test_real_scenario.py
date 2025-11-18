import sys
sys.path.insert(0, r'D:\GIT\RoboTrader')

import pickle
import pandas as pd
from datetime import datetime
from unittest.mock import patch

# 캐시 파일 로드 (전체 데이터)
full_data = pickle.load(open(r'D:\GIT\RoboTrader\cache\minute_data\001520_20251016.pkl', 'rb'))

print('='*80)
print('실제 시나리오 재현: 09:54:36 시점에 52개 1분봉 데이터')
print('='*80)

# 실제 실시간에서는 09:00부터 시작하지만,
# 로그를 보면 "당일 외 데이터 115건 제거: 172 → 57건" 이라고 나옴
# 즉, 172개에서 115개를 제거해서 57개가 되었다는 뜻
# 그런데 realtime_data는 52개였다고 함

# 09:54:13에 095300이 추가되어 52개가 됨
# 즉, 09:02부터 09:53까지 = 52개

# 하지만 실제 데이터를 확인해보니 full_data는 09:00부터 시작
# 실시간에서는 09:02부터 시작했을 가능성

# 일단 09:02~09:53 = 52분 = 52개로 가정
# index: 090000(0), 090100(1), 090200(2), ..., 095300(53)
# 09:02~09:53 = index 2~53 = 52개

data_52 = full_data.iloc[2:54].copy()  # 090200~095300 = 52개

print(f'\n1. 실시간 데이터 (52개):')
print(f'   시작: {data_52.iloc[0]["time"]}')
print(f'   끝: {data_52.iloc[-1]["time"]}')
print(f'   개수: {len(data_52)}')

# datetime 변환 및 3분봉 변환 (버그 코드 시뮬레이션)
df = data_52.copy()
df['datetime'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str))
df = df.set_index('datetime')

# floor 방식으로 3분봉 생성
df['floor_3min'] = df.index.floor('3min')
resampled = df.groupby('floor_3min').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}).reset_index()
resampled = resampled.rename(columns={'floor_3min': 'datetime'})

print(f'\n2. 3분봉 변환 결과: {len(resampled)}개')
print('   마지막 5개:')
for idx, row in resampled.tail(5).iterrows():
    print(f'   {row["datetime"].strftime("%H:%M")} | 종가:{row["close"]:>6.0f} | 거래량:{row["volume"]:>10.0f}')

# 09:54:36 시점
mock_time = datetime(2025, 10, 16, 9, 54, 36)
current_3min_floor = pd.Timestamp(mock_time).floor('3min')

print(f'\n3. 현재 시간: {mock_time.strftime("%H:%M:%S")}')
print(f'   current_3min_floor: {current_3min_floor.strftime("%H:%M")}')

# === 버그 로직 ===
print('\n4. 버그 로직 (< 사용):')
print(f'   조건: datetime < {current_3min_floor.strftime("%H:%M")}')
completed_bug = resampled[resampled['datetime'] < current_3min_floor].copy()
print(f'   결과: {len(completed_bug)}개 3분봉')
print('   마지막 3개:')
for idx, row in completed_bug.tail(3).iterrows():
    print(f'   {row["datetime"].strftime("%H:%M")} | 종가:{row["close"]:>6.0f} | 거래량:{row["volume"]:>10.0f}')

# === 수정된 로직 ===
print('\n5. 수정 로직 (<= last_completed 사용):')
last_completed_3min = current_3min_floor - pd.Timedelta(minutes=3)
print(f'   last_completed_3min: {last_completed_3min.strftime("%H:%M")}')
print(f'   조건: datetime <= {last_completed_3min.strftime("%H:%M")}')
completed_fixed = resampled[resampled['datetime'] <= last_completed_3min].copy()
print(f'   결과: {len(completed_fixed)}개 3분봉')
print('   마지막 3개:')
for idx, row in completed_fixed.tail(3).iterrows():
    print(f'   {row["datetime"].strftime("%H:%M")} | 종가:{row["close"]:>6.0f} | 거래량:{row["volume"]:>10.0f}')

# === 차이점 분석 ===
print('\n6. 차이점:')
print(f'   버그 로직: {len(completed_bug)}개')
print(f'   수정 로직: {len(completed_fixed)}개')

if len(completed_bug) != len(completed_fixed):
    diff_count = len(completed_fixed) - len(completed_bug)
    print(f'   ⚠️ {diff_count}개 차이 발생!')

    if diff_count > 0:
        missing = completed_fixed.tail(diff_count)
        print('\n   버그 로직에서 누락된 봉:')
        for idx, row in missing.iterrows():
            print(f'   {row["datetime"].strftime("%H:%M")} | 종가:{row["close"]:>6.0f} | 거래량:{row["volume"]:>10.0f}')
else:
    print('   ✓ 차이 없음')

# === 09:51 봉 확인 ===
print('\n7. 09:51 3분봉 포함 여부:')
bar_0951_bug = completed_bug[completed_bug['datetime'] == pd.Timestamp('2025-10-16 09:51:00')]
bar_0951_fixed = completed_fixed[completed_fixed['datetime'] == pd.Timestamp('2025-10-16 09:51:00')]

print(f'   버그 로직: {"포함됨 ✓" if len(bar_0951_bug) > 0 else "누락됨 ✗"}')
if len(bar_0951_bug) > 0:
    print(f'      종가: {bar_0951_bug.iloc[0]["close"]:.0f}, 거래량: {bar_0951_bug.iloc[0]["volume"]:,.0f}')

print(f'   수정 로직: {"포함됨 ✓" if len(bar_0951_fixed) > 0 else "누락됨 ✗"}')
if len(bar_0951_fixed) > 0:
    print(f'      종가: {bar_0951_fixed.iloc[0]["close"]:.0f}, 거래량: {bar_0951_fixed.iloc[0]["volume"]:,.0f}')

print('\n' + '='*80)

# 추가: 09:54 봉이 리샘플링에 포함되었는지 확인
print('\n8. 09:54 3분봉 (진행중인 봉):')
bar_0954 = resampled[resampled['datetime'] == pd.Timestamp('2025-10-16 09:54:00')]
if len(bar_0954) > 0:
    print(f'   리샘플링에 포함됨')
    print(f'   종가: {bar_0954.iloc[0]["close"]:.0f}, 거래량: {bar_0954.iloc[0]["volume"]:,.0f}')
    print(f'   버그 로직: {"포함됨" if len(completed_bug[completed_bug["datetime"] == pd.Timestamp("2025-10-16 09:54:00")]) > 0 else "제외됨 ✓"}')
    print(f'   수정 로직: {"포함됨" if len(completed_fixed[completed_fixed["datetime"] == pd.Timestamp("2025-10-16 09:54:00")]) > 0 else "제외됨 ✓"}')
else:
    print(f'   리샘플링에 없음 (데이터 부족)')

print('\n' + '='*80)
