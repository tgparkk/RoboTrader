#!/usr/bin/env python3
"""
039200 10:06 신호의 ML 예측값을 계산하는 테스트 스크립트
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import pickle
import pandas as pd
from pathlib import Path

# 패턴 데이터 로드
with open('pattern_data_log/pattern_data_20251126.jsonl', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 039200 10:06 패턴 찾기
target_pattern = None
for line in lines:
    data = json.loads(line)
    if data['stock_code'] == '039200' and data['signal_time'] == '2025-11-26 10:06:00':
        target_pattern = data
        break

if not target_pattern:
    print("❌ 패턴을 찾을 수 없습니다")
    exit(1)

print(f"✅ 패턴 발견: {target_pattern['stock_code']} {target_pattern['signal_time']}")
print()

# ML 모델 로드
model_path = Path("ml_model_stratified.pkl")
with open(model_path, 'rb') as f:
    model_data = pickle.load(f)

model = model_data['model']
feature_names = model_data['feature_names']

print(f"✅ ML 모델 로드 완료: {len(feature_names)}개 특성")
print()

# 특성 추출 (apply_ml_filter.py 로직 사용)
from apply_ml_filter import extract_features_from_pattern

features = extract_features_from_pattern(target_pattern)

print("📊 추출된 특성:")
for key, value in features.items():
    print(f"  {key}: {value}")
print()

# DataFrame으로 변환
feature_values = [features.get(fname, 0) for fname in feature_names]
X = pd.DataFrame([feature_values], columns=feature_names)

# 예측
win_prob = model.predict(X.values, num_iteration=model.best_iteration)[0]

print(f"🎯 ML 예측 결과: {win_prob * 100:.1f}%")
print()

# 실시간 거래 로그와 비교
print("📝 비교:")
print(f"  실시간 거래 (로그): 34.6%")
print(f"  패턴 로그 재계산: {win_prob * 100:.1f}%")
print(f"  차이: {abs(win_prob * 100 - 34.6):.1f}%p")
