#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
440110 패턴에 대한 실시간ML vs 시뮬ML 특성 벡터 비교
"""

import json
import sys
import io
from pathlib import Path

# Windows 콘솔 UTF-8 출력 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 1. 시뮬레이션 ML 실행
print("=" * 80)
print("시뮬레이션 ML 특성 추출")
print("=" * 80)

# pattern_data_log에서 440110 패턴 읽기
pattern_file = Path("pattern_data_log/pattern_data_20251127.jsonl")
pattern_440110 = None

if pattern_file.exists():
    with open(pattern_file, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            if data.get('stock_code') == '440110':
                signal_time = data.get('signal_time', '')
                if '10:03' in signal_time or '10:07' in signal_time:
                    pattern_440110 = data
                    break

if pattern_440110 is None:
    print("[X] 440110 패턴 데이터를 찾을 수 없습니다")
    sys.exit(1)

print(f"[OK] 패턴 발견: {pattern_440110['signal_time']}")

# 시뮬레이션 ML 방식으로 특성 추출
from utils.signal_replay_ml import extract_features_from_pattern, load_ml_model

model, feature_names = load_ml_model()
if model is None:
    print("[X] ML 모델 로드 실패")
    sys.exit(1)

print("\n시뮬레이션 특성 추출 중...")
simul_features = extract_features_from_pattern(pattern_440110)

print("\n" + "=" * 80)
print("실시간 ML 특성 추출")
print("=" * 80)

# 실시간 ML 방식으로 특성 추출
from core.ml_predictor import MLPredictor

predictor = MLPredictor()
if not predictor.load_model():
    print("[X] 실시간 ML 모델 로드 실패")
    sys.exit(1)

print("\n실시간 특성 추출 중...")
realtime_features_df = predictor.extract_features_from_pattern(pattern_440110)
realtime_features = realtime_features_df.to_dict('records')[0]

print("\n" + "=" * 80)
print("📊 특성 비교 결과")
print("=" * 80)

# 특성 비교
print("\n%-35s %15s %15s %15s" % ("특성명", "시뮬ML", "실시간ML", "차이"))
print("-" * 80)

differences = []
for fname in feature_names:
    simul_val = simul_features.get(fname, 0)
    realtime_val = realtime_features.get(fname, 0)
    diff = abs(simul_val - realtime_val)

    diff_marker = "[DIFF]" if diff > 0.01 else ""
    print("%-35s %15.6f %15.6f %15.6f %s" % (
        fname, simul_val, realtime_val, diff, diff_marker
    ))

    if diff > 0.01:
        differences.append((fname, simul_val, realtime_val, diff))

print("\n" + "=" * 80)
print("차이가 나는 특성")
print("=" * 80)

if differences:
    print(f"\n총 {len(differences)}개 특성이 차이남:")
    for fname, simul_val, realtime_val, diff in differences:
        print(f"  - {fname}")
        print(f"    시뮬ML: {simul_val:.6f}")
        print(f"    실시간ML: {realtime_val:.6f}")
        print(f"    차이: {diff:.6f}")
else:
    print("\n[OK] 모든 특성이 동일합니다!")

# 실제 예측값 비교
print("\n" + "=" * 80)
print("ML 예측값 비교")
print("=" * 80)

import pandas as pd

# 시뮬ML 예측
simul_feature_values = [simul_features.get(fname, 0) for fname in feature_names]
simul_X = pd.DataFrame([simul_feature_values], columns=feature_names)
simul_prob = model.predict(simul_X, num_iteration=model.best_iteration)[0]

# 실시간ML 예측
realtime_prob = predictor.model.predict(
    realtime_features_df,
    num_iteration=predictor.model.best_iteration
)[0]

print(f"\n시뮬ML 예측: {simul_prob*100:.1f}%")
print(f"실시간ML 예측: {realtime_prob*100:.1f}%")
print(f"차이: {abs(simul_prob - realtime_prob)*100:.1f}%p")

print("\n" + "=" * 80)
