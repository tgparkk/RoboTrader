import sys
sys.path.insert(0, r'D:\GIT\RoboTrader')

import pickle
import pandas as pd
from core.timeframe_converter import TimeFrameConverter
from datetime import datetime
from unittest.mock import patch

# 캐시 파일 로드
data = pickle.load(open(r'D:\GIT\RoboTrader\cache\minute_data\001520_20251016.pkl', 'rb'))

print('='*60)
print('테스트: 54개 1분봉 (09:00~09:53)을 3분봉으로 변환')
print('='*60)

# 54개 1분봉 (09:00~09:53) - index 0~53
data_54 = data.head(54)
print(f'\n입력 데이터: {len(data_54)}개 1분봉')
print(f'시간 범위: {data_54.iloc[0]["time"]} ~ {data_54.iloc[-1]["time"]}')

# 09:54:36 시점 시뮬레이션
mock_time = datetime(2025, 10, 16, 9, 54, 36)
print(f'\n현재 시간 (mock): {mock_time}')

with patch('utils.korean_time.now_kst', return_value=mock_time):
    result = TimeFrameConverter.convert_to_3min_data(data_54)

print(f'\n결과: {len(result)}개 3분봉 생성')
print('\n마지막 5개 3분봉:')
print(result.tail(5)[['datetime', 'open', 'high', 'low', 'close', 'volume']])

print('\n09:51:00 3분봉 확인:')
bar_0951 = result[result['datetime'] == pd.Timestamp('2025-10-16 09:51:00')]
if len(bar_0951) > 0:
    print('OK 09:51:00 3min bar included!')
    print(bar_0951[['datetime', 'open', 'high', 'low', 'close', 'volume']])

    # 검증
    expected_close = 1189.0
    expected_volume = 2544215.0
    actual_close = bar_0951.iloc[0]['close']
    actual_volume = bar_0951.iloc[0]['volume']

    close_match = 'OK' if abs(actual_close - expected_close) < 1 else 'FAIL'
    volume_match = 'OK' if abs(actual_volume - expected_volume) < 1 else 'FAIL'
    print(f'\nClose: {actual_close} (expected: {expected_close}) - {close_match}')
    print(f'Volume: {actual_volume:,.0f} (expected: {expected_volume:,.0f}) - {volume_match}')
else:
    print('FAIL: 09:51:00 3min bar missing!')

print('\n'+'='*60)
print('테스트 완료!')
print('='*60)
