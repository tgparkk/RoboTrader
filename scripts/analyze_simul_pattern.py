#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시뮬레이션이 실제로 사용한 440110 패턴 재구성 및 ML 예측 비교
"""

import json
import sys
import io

# Windows 콘솔 UTF-8 출력 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 시뮬레이션 로그에서 패턴 정보 추출
# 10:06:22 | 상승구간: 인덱스0~8 +5.9% | 하락구간: 인덱스9~12 -0.7% | 지지구간: 인덱스13~13 1개봉 | 돌파양봉: 인덱스21 신뢰도88.0%

# 시뮬레이션 로그 분석
print("=" * 80)
print("시뮬레이션 로그 분석")
print("=" * 80)

simul_log = """
10:03→10:06: 종가:27,150 | 거래량:44,095 | 🟢강매수 | 신뢰도:88%
"""

print("\n시뮬레이션:")
print(f"  - 10:03→10:06 3분봉에서 패턴 감지")
print(f"  - 신뢰도: 88%")
print(f"  - ML 예측: 50.0%")

print("\n실시간:")
print(f"  - 10:06:22에 패턴 감지")
print(f"  - 신뢰도: 88%")
print(f"  - 상승구간: 인덱스0~8 +5.9%")
print(f"  - 하락구간: 인덱스9~12 -0.7%")
print(f"  - 지지구간: 인덱스13~13 1개봉")
print(f"  - 돌파양봉: 인덱스21")
print(f"  - ML 예측: 44.7%")

print("\n" + "=" * 80)
print("패턴 데이터 로그 확인")
print("=" * 80)

from pathlib import Path

pattern_file = Path("pattern_data_log/pattern_data_20251127.jsonl")
patterns_440110_10_03 = []

if pattern_file.exists():
    with open(pattern_file, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            if data.get('stock_code') == '440110':
                signal_time = data.get('signal_time', '')
                if '10:03' in signal_time:
                    patterns_440110_10_03.append(data)

print(f"\n10:03 패턴 개수: {len(patterns_440110_10_03)}개")

# 각 패턴의 pattern_stages 확인
for i, pattern in enumerate(patterns_440110_10_03):
    print(f"\n패턴 {i+1}:")
    print(f"  log_timestamp: {pattern['log_timestamp']}")

    stages = pattern.get('pattern_stages', {})
    uptrend = stages.get('1_uptrend', {})
    decline = stages.get('2_decline', {})
    support = stages.get('3_support', {})
    breakout = stages.get('4_breakout', {})

    print(f"  상승: {uptrend.get('start_idx')}~{uptrend.get('end_idx')} ({uptrend.get('candle_count')}개) +{uptrend.get('price_gain')}")
    print(f"  하락: {decline.get('start_idx')}~{decline.get('end_idx')} ({decline.get('candle_count')}개) {decline.get('decline_pct')}")
    print(f"  지지: {support.get('start_idx')}~{support.get('end_idx')} ({support.get('candle_count')}개)")
    print(f"  돌파: idx {breakout.get('idx')}")

# 첫 번째 패턴으로 ML 예측 테스트
if patterns_440110_10_03:
    print("\n" + "=" * 80)
    print("첫 번째 패턴으로 ML 예측 테스트")
    print("=" * 80)

    pattern = patterns_440110_10_03[0]

    # 시뮬 ML
    from utils.signal_replay_ml import extract_features_from_pattern, load_ml_model
    import pandas as pd

    model, feature_names = load_ml_model()
    simul_features = extract_features_from_pattern(pattern)
    simul_feature_values = [simul_features.get(fname, 0) for fname in feature_names]
    simul_X = pd.DataFrame([simul_feature_values], columns=feature_names)
    simul_prob = model.predict(simul_X, num_iteration=model.best_iteration)[0]

    # 실시간 ML
    from core.ml_predictor import MLPredictor

    predictor = MLPredictor()
    predictor.load_model()
    realtime_features_df = predictor.extract_features_from_pattern(pattern)
    realtime_prob = predictor.model.predict(
        realtime_features_df,
        num_iteration=predictor.model.best_iteration
    )[0]

    print(f"\n시뮬ML 예측: {simul_prob*100:.1f}%")
    print(f"실시간ML 예측: {realtime_prob*100:.1f}%")
    print(f"차이: {abs(simul_prob - realtime_prob)*100:.1f}%p")

    # 특성 비교
    realtime_features = realtime_features_df.to_dict('records')[0]

    print("\n주요 특성 비교:")
    key_features = ['hour', 'minute', 'confidence', 'uptrend_candles', 'uptrend_gain',
                    'decline_candles', 'decline_pct', 'support_candles', 'breakout_volume']

    for fname in key_features:
        simul_val = simul_features.get(fname, 0)
        realtime_val = realtime_features.get(fname, 0)
        diff = abs(simul_val - realtime_val)
        diff_marker = " [DIFF]" if diff > 0.01 else ""
        print(f"  {fname:20s}: 시뮬={simul_val:10.2f} vs 실시간={realtime_val:10.2f}{diff_marker}")

print("\n" + "=" * 80)
