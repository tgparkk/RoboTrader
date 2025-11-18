"""
단일 거래 테스트 - 441270, 20250901, 11:09
"""
import sys
import pandas as pd
from pathlib import Path
import pickle

from core.indicators.pullback_candle_pattern import PullbackCandlePattern

# 데이터 로드
data_file = Path("cache/minute_data/441270_20250901.pkl")

if not data_file.exists():
    print(f"Data file not found: {data_file}")
    sys.exit(1)

with open(data_file, 'rb') as f:
    data = pickle.load(f)

print(f"Total data length: {len(data)}")
print(f"Data columns: {data.columns.tolist()}")
print(f"\nFirst 5 rows:")
print(data.head())

# 11:09 시점 찾기
data['datetime'] = pd.to_datetime(data['datetime'])

buy_time = "11:09"
buy_hour, buy_minute = 11, 9

# 해당 시간 찾기
buy_idx = None
for idx, row in data.iterrows():
    candle_time = pd.to_datetime(row['datetime'])
    if candle_time.hour == buy_hour and candle_time.minute == buy_minute:
        buy_idx = idx
        break

if buy_idx is None:
    print(f"\n[ERROR] Could not find 11:09 candle")
    print(f"\nAvailable times around 11:00:")
    for idx, row in data.iterrows():
        candle_time = pd.to_datetime(row['datetime'])
        if 10 <= candle_time.hour <= 12:
            print(f"  {candle_time.strftime('%H:%M')}")
    sys.exit(1)

print(f"\n[OK] Found buy time at index: {buy_idx}")

# 매수 시점까지의 데이터
data_until_buy = data.loc[:buy_idx].copy()

print(f"Data until buy: {len(data_until_buy)} candles")
print(f"\nLast 5 candles before buy:")
print(data_until_buy.tail())

# 4단계 패턴 분석
print(f"\n[*] Running analyze_support_pattern...")
pattern_info = PullbackCandlePattern.analyze_support_pattern(data_until_buy, debug=True)

print(f"\n[*] Pattern result:")
print(f"  has_support_pattern: {pattern_info.get('has_support_pattern')}")
print(f"  confidence: {pattern_info.get('confidence')}")
print(f"  reasons: {pattern_info.get('reasons')}")

debug_info = pattern_info.get('debug_info', {})
print(f"\n[*] Debug info keys: {debug_info.keys()}")

if 'uptrend' in debug_info:
    print(f"\n  Uptrend: {debug_info['uptrend']}")
if 'decline' in debug_info:
    print(f"  Decline: {debug_info['decline']}")
if 'support' in debug_info:
    print(f"  Support: {debug_info['support']}")
if 'breakout' in debug_info:
    print(f"  Breakout: {debug_info['breakout']}")
