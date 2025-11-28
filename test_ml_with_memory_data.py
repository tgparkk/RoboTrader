#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
메모리 분봉 데이터를 사용한 ML 시뮬레이션 테스트

실시간 거래가 사용한 in-memory 데이터로 ML 예측을 재현합니다.
"""

import sys
import io
import re
import pandas as pd
from pathlib import Path
from datetime import datetime

# Windows 콘솔 UTF-8 출력 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def parse_memory_data(file_path: str) -> dict:
    """메모리 덤프 파일에서 종목별 분봉 데이터 파싱

    Returns:
        {stock_code: DataFrame} 딕셔너리
    """
    stock_data = {}
    current_stock = None
    current_lines = []
    in_data_section = False

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')

            # 종목 코드 시작 패턴: [440110] 분봉 데이터: 389건
            match = re.match(r'\[(\d{6})\] 분봉 데이터: (\d+)건', line)
            if match:
                # 이전 종목 데이터 저장
                if current_stock and current_lines:
                    df = parse_dataframe_lines(current_lines)
                    if df is not None:
                        stock_data[current_stock] = df

                # 새 종목 시작
                current_stock = match.group(1)
                current_lines = []
                in_data_section = False
                continue

            # 구분선 감지
            if line.startswith('---'):
                in_data_section = True
                continue

            # 빈 줄 또는 === 무시
            if line.startswith('===') or line.strip() == '':
                continue

            # 데이터 라인 수집
            if current_stock and in_data_section:
                current_lines.append(line)

        # 마지막 종목 데이터 저장
        if current_stock and current_lines:
            df = parse_dataframe_lines(current_lines)
            if df is not None:
                stock_data[current_stock] = df

    return stock_data

def parse_dataframe_lines(lines: list) -> pd.DataFrame:
    """DataFrame 텍스트 라인을 파싱"""
    try:
        # 첫 줄은 헤더 (컬럼명)
        if not lines:
            return None

        header_line = lines[0]
        # 공백으로 구분된 컬럼명 추출
        columns = header_line.split()

        # 데이터 라인 파싱
        rows = []
        for line in lines[1:]:
            # 인덱스와 데이터 분리 (첫 번째 공백 이후가 데이터)
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                continue

            # 데이터 부분을 공백으로 분리
            values = parts[1].split()
            if len(values) == len(columns):
                rows.append(values)

        if not rows:
            return None

        # DataFrame 생성
        df = pd.DataFrame(rows, columns=columns)

        # 데이터 타입 변환
        numeric_cols = ['close', 'open', 'high', 'low', 'volume', 'amount']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # datetime 변환
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])

        return df

    except Exception as e:
        print(f"DataFrame 파싱 오류: {e}")
        return None

def convert_to_3min_candles(df_1min: pd.DataFrame) -> pd.DataFrame:
    """1분봉을 3분봉으로 변환"""
    if df_1min is None or df_1min.empty:
        return pd.DataFrame()

    # datetime 인덱스로 설정
    df_1min = df_1min.set_index('datetime')

    # 3분봉 리샘플링
    df_3min = pd.DataFrame({
        'open': df_1min['open'].resample('3T').first(),
        'high': df_1min['high'].resample('3T').max(),
        'low': df_1min['low'].resample('3T').min(),
        'close': df_1min['close'].resample('3T').last(),
        'volume': df_1min['volume'].resample('3T').sum()
    })

    df_3min = df_3min.dropna()
    df_3min = df_3min.reset_index()

    return df_3min

def generate_pattern_signals(df_3min: pd.DataFrame, stock_code: str):
    """3분봉 데이터로 패턴 신호 생성"""
    from core.indicators.pullback_candle_pattern import PullbackCandlePattern

    pattern = PullbackCandlePattern()
    signals, signal_strength = pattern.generate_trading_signals(
        df_3min,
        debug_logs=False,
        stock_code=stock_code
    )

    return signals, signal_strength

def test_ml_prediction_for_signal(signal_time: str, stock_code: str, signals: pd.DataFrame, df_3min: pd.DataFrame):
    """특정 시간의 신호에 대해 ML 예측 실행"""
    from core.ml_predictor import MLPredictor
    from core.pattern_data_logger import PatternDataLogger

    # 신호 시간에 해당하는 행 찾기
    signal_row = signals[signals['datetime'].dt.strftime('%H:%M:%S') == signal_time]

    if signal_row.empty:
        print(f"[X] {signal_time} 신호를 찾을 수 없습니다")
        return None

    signal_row = signal_row.iloc[0]

    # 패턴 정보 생성 (pattern_data_logger 방식)
    logger_obj = PatternDataLogger()
    pattern_info = logger_obj._build_pattern_info(
        stock_code=stock_code,
        signal_type=signal_row.get('signal_type', ''),
        confidence=signal_row.get('confidence', 0),
        signal_time=signal_row['datetime'],
        debug_info=signal_row.get('debug_info', {})
    )

    # ML 예측
    predictor = MLPredictor()
    if not predictor.load_model():
        print("[X] ML 모델 로드 실패")
        return None

    features_df = predictor.extract_features_from_pattern(pattern_info)
    prob = predictor.model.predict(
        features_df,
        num_iteration=predictor.model.best_iteration
    )[0]

    return prob, pattern_info

# ========== 메인 실행 ==========

print("=" * 80)
print("메모리 분봉 데이터로 ML 시뮬레이션 테스트")
print("=" * 80)

# 1. 메모리 데이터 파싱
memory_file = Path("memory_minute_data_20251127_153018.txt")
if not memory_file.exists():
    print(f"[X] {memory_file} 파일을 찾을 수 없습니다")
    sys.exit(1)

print(f"\n[1] 메모리 데이터 파싱 중...")
stock_data = parse_memory_data(memory_file)
print(f"    총 {len(stock_data)}개 종목 로드 완료")

# 2. 440110 종목 데이터 확인
stock_code = '440110'
if stock_code not in stock_data:
    print(f"[X] {stock_code} 종목 데이터를 찾을 수 없습니다")
    print(f"    로드된 종목: {list(stock_data.keys())}")
    sys.exit(1)

df_1min = stock_data[stock_code]
print(f"\n[2] {stock_code} 1분봉 데이터: {len(df_1min)}건")
print(f"    시간 범위: {df_1min['datetime'].iloc[0]} ~ {df_1min['datetime'].iloc[-1]}")

# 3. 3분봉 변환
print(f"\n[3] 3분봉 변환 중...")
df_3min = convert_to_3min_candles(df_1min)
print(f"    3분봉 데이터: {len(df_3min)}건")

# 4. 패턴 신호 생성
print(f"\n[4] 패턴 신호 생성 중...")
signals, signal_strength = generate_pattern_signals(df_3min, stock_code)

if signals.empty:
    print(f"[X] 신호가 생성되지 않았습니다")
    sys.exit(1)

print(f"    생성된 신호: {len(signals)}개")

# 5. 10:03 신호에 대한 ML 예측
print(f"\n[5] 10:03 신호 ML 예측 테스트")
print("-" * 80)

signal_time = "10:03:00"
result = test_ml_prediction_for_signal(signal_time, stock_code, signals, df_3min)

if result:
    prob, pattern_info = result
    print(f"\n🎯 메모리 데이터 ML 예측: {prob*100:.1f}%")
    print(f"    신호 시간: {pattern_info['signal_time']}")
    print(f"    신뢰도: {pattern_info['signal_info']['confidence']}")
else:
    print(f"\n[X] ML 예측 실패")

# 6. 실시간 로그와 비교
print("\n" + "=" * 80)
print("📊 비교 결과")
print("=" * 80)
print(f"\n실시간 거래 (10:06:22): ML 44.7% ❌ 차단")
print(f"시뮬레이션 (3분봉):   ML 50.0% ✅ 통과")
print(f"메모리 데이터 (3분봉): ML {prob*100:.1f}%")
print("\n" + "=" * 80)
