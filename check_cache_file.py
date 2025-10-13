#!/usr/bin/env python3
import pickle
import pandas as pd
import sys

stock_code = sys.argv[1] if len(sys.argv) > 1 else "030530"
date_str = sys.argv[2] if len(sys.argv) > 2 else "20251013"

cache_file = f"cache/minute_data/{stock_code}_{date_str}.pkl"

try:
    with open(cache_file, 'rb') as f:
        df = pickle.load(f)
    
    if 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'])
    
    print(f"Total rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    print(f"\nFirst 5:")
    print(df.head())
    print(f"\nLast 5:")
    print(df.tail())
    
    if 'datetime' in df.columns:
        print(f"\nTime range: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
        print(f"Is sorted: {df['datetime'].is_monotonic_increasing}")
        
        # 시간순 정렬 확인
        sorted_df = df.sort_values('datetime')
        print(f"\nAfter sort - First time: {sorted_df['datetime'].iloc[0]}")
        print(f"After sort - Last time: {sorted_df['datetime'].iloc[-1]}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

