#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""메모리 분봉 데이터 파싱 테스트"""

import re
import pandas as pd
from pathlib import Path

def extract_stock_data_simple(file_path: str, stock_code: str) -> pd.DataFrame:
    """특정 종목의 분봉 데이터를 직접 추출"""

    lines = []
    in_target_stock = False
    found_header = False

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            # 종목 시작 감지
            if f'[{stock_code}]' in line:
                in_target_stock = True
                continue

            # 다음 종목 시작 시 종료
            if in_target_stock and line.startswith('[') and stock_code not in line:
                break

            # 헤더 라인 감지 (date time close open high low volume amount datetime)
            if in_target_stock and 'date' in line and 'time' in line and 'close' in line:
                found_header = True
                continue

            # 데이터 라인 수집
            if in_target_stock and found_header and line.strip():
                # --- 나 === 무시
                if line.startswith('---') or line.startswith('==='):
                    continue
                # 숫자로 시작하는 라인만 (데이터 행)
                if re.match(r'^\s*\d+\s+', line):
                    lines.append(line.strip())

    if not lines:
        return None

    # DataFrame 생성
    data_rows = []
    for line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            continue

        # 인덱스를 제외한 데이터 부분 (9개 컬럼)
        values = parts[1].split()
        # 9개 또는 10개 컬럼 모두 허용 (datetime이 2개로 분리될 수 있음)
        if len(values) >= 9:
            # datetime이 "2025-11-27 09:00:00" 처럼 공백으로 분리된 경우 합치기
            if len(values) == 10:
                # 마지막 2개를 합쳐서 datetime으로
                values = values[:8] + [values[8] + ' ' + values[9]]
            data_rows.append(values[:9])

    if not data_rows:
        return None

    # DataFrame 생성
    columns = ['date', 'time', 'close', 'open', 'high', 'low', 'volume', 'amount', 'datetime']
    df = pd.DataFrame(data_rows, columns=columns)

    # 데이터 타입 변환
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['open'] = pd.to_numeric(df['open'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

    # datetime 컬럼 생성 (date + time)
    df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], format='%Y%m%d %H%M%S')

    return df

# 테스트
stock_code = '440110'
memory_file = 'memory_minute_data_20251127_153018.txt'

print(f"[테스트] {stock_code} 분봉 데이터 추출")
df = extract_stock_data_simple(memory_file, stock_code)

if df is not None:
    print(f"[OK] 성공: {len(df)}건 추출")
    print(f"   시간 범위: {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]}")
    print(f"\n첫 5행:")
    print(df[['datetime', 'close', 'open', 'high', 'low', 'volume']].head())

    # 10:03, 10:06 시간대 확인
    print(f"\n10:03~10:06 데이터:")
    target_times = df[(df['datetime'] >= '2025-11-27 10:03:00') &
                      (df['datetime'] <= '2025-11-27 10:06:00')]
    print(target_times[['datetime', 'close', 'volume']])
else:
    print(f"[X] 실패: {stock_code} 데이터를 찾을 수 없습니다")
