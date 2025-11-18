import sys
sys.path.insert(0, r'D:\GIT\RoboTrader')

import pickle
import pandas as pd
from datetime import datetime

# 캐시 파일 로드
data = pickle.load(open(r'D:\GIT\RoboTrader\cache\minute_data\001520_20251016.pkl', 'rb'))

# 09:54:36 시점의 데이터 (09:54:13에 095300이 추가되어 52개)
data_52 = data.head(52)

print('='*60)
print('원래 버그 로직 설명')
print('='*60)

# datetime 변환
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

print(f'\n1. 입력 데이터: 52개 1분봉')
print(f'   시간 범위: {data_52.iloc[0]["time"]} ~ {data_52.iloc[-1]["time"]}')

print(f'\n2. 리샘플링 결과: {len(resampled)}개 3분봉')
print('   마지막 5개 3분봉:')
print(resampled[['datetime', 'close', 'volume']].tail(5))

# 09:54:36 시점
mock_time = datetime(2025, 10, 16, 9, 54, 36)
current_3min_floor = pd.Timestamp(mock_time).floor('3min')

print(f'\n3. 현재 시간: {mock_time}')
print(f'   current_3min_floor: {current_3min_floor}')

# 버그 로직
print('\n4. 버그 로직 적용 (< 사용):')
print(f'   조건: resampled["datetime"] < {current_3min_floor}')
completed_bug = resampled[resampled['datetime'] < current_3min_floor].copy()
print(f'   결과: {len(completed_bug)}개 3분봉')
print('   마지막 3개:')
print(completed_bug[['datetime', 'close', 'volume']].tail(3))

# 수정된 로직
print('\n5. 수정된 로직 적용 (<= 사용):')
last_completed_3min = current_3min_floor - pd.Timedelta(minutes=3)
print(f'   last_completed_3min: {last_completed_3min}')
print(f'   조건: resampled["datetime"] <= {last_completed_3min}')
completed_fixed = resampled[resampled['datetime'] <= last_completed_3min].copy()
print(f'   결과: {len(completed_fixed)}개 3분봉')
print('   마지막 3개:')
print(completed_fixed[['datetime', 'close', 'volume']].tail(3))

print('\n6. 차이점:')
if len(completed_bug) != len(completed_fixed):
    print(f'   버그 로직: 09:51:00 봉 누락!')
    print(f'   수정 로직: 09:51:00 봉 포함됨!')
    print(f'   09:51:00 봉 정보: 종가={completed_fixed.iloc[-1]["close"]}, 거래량={completed_fixed.iloc[-1]["volume"]:,.0f}')
else:
    print('   차이 없음 (???)')

print('\n' + '='*60)
