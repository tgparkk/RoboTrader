#!/usr/bin/env python3
import sys
import json
import pickle
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

# apply_ml_filter.py 함수 import
exec(open('apply_ml_filter.py', encoding='utf-8').read())

# ML 모델 로드
model, feature_names = load_ml_model()

# 수정된 007810 패턴 로드
with open('pattern_data_log/pattern_data_20251201.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('stock_code') == '007810':
            print('=== 007810 ML 예측 (수정된 데이터) ===')
            print(f"signal_time: {data.get('signal_time')}")

            # 특성 추출
            features_dict = extract_features_from_pattern(data)

            # DataFrame 변환
            feature_values = [features_dict.get(fname, 0) for fname in feature_names]
            features_df = pd.DataFrame([feature_values], columns=feature_names)

            # ML 예측
            ml_prob = model.predict(features_df, num_iteration=model.best_iteration)[0]

            print(f'ML 예측: {ml_prob:.1%}')
            print(f'hour: {features_dict.get("hour")}, minute: {features_dict.get("minute")}')
            print(f'uptrend_candles: {features_dict.get("uptrend_candles")}')
            print(f'uptrend_gain: {features_dict.get("uptrend_gain"):.4f}')
            print(f'decline_pct: {features_dict.get("decline_pct"):.2f}')

            if ml_prob >= 0.50:
                print('\n결과: ✅ 통과 (>=50%)')
            else:
                print('\n결과: ❌ 차단 (<50%)')

            print('\n비교:')
            print('  실시간 ML: 61.3% (minute=21)')
            print(f'  시뮬 ML(수정 전): 37.8% (minute=18)')
            print(f'  시뮬 ML(수정 후): {ml_prob:.1%} (minute={features_dict.get("minute")})')

            break
