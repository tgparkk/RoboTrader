#!/usr/bin/env python3
import sys
import json
sys.stdout.reconfigure(encoding='utf-8')

# apply_ml_filter.py 함수 import
from apply_ml_filter import load_ml_model, extract_features_from_pattern
import pandas as pd

# ML 모델 로드
print('ML 모델 로딩 중...')
model, feature_names = load_ml_model()
print(f'✅ 모델 로드 완료 ({len(feature_names)}개 특성)\n')

# 수정된 007810 패턴 로드
with open('pattern_data_log/pattern_data_20251201.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('stock_code') == '007810':
            print('=== 007810 ML 예측 (apply_ml_filter 사용) ===')
            print(f"signal_time: {data.get('signal_time')}")

            # apply_ml_filter와 동일한 특성 추출
            features_dict = extract_features_from_pattern(data)

            print(f"\n주요 특성:")
            print(f"  hour={features_dict.get('hour')}, minute={features_dict.get('minute')}")
            print(f"  uptrend_candles={features_dict.get('uptrend_candles')}")
            print(f"  uptrend_gain={features_dict.get('uptrend_gain'):.4f}")
            print(f"  uptrend_max_volume={features_dict.get('uptrend_max_volume'):.0f}")
            print(f"  decline_pct={features_dict.get('decline_pct'):.2f}")
            print(f"  decline_avg_volume={features_dict.get('decline_avg_volume'):.0f}")

            # DataFrame 변환
            feature_values = [features_dict.get(fname, 0) for fname in feature_names]
            features_df = pd.DataFrame([feature_values], columns=feature_names)

            # ML 예측
            ml_prob = model.predict(features_df, num_iteration=model.best_iteration)[0]

            print(f'\n🎯 ML 예측: {ml_prob:.1%}')

            if ml_prob >= 0.50:
                print('✅ 통과 (>=50%)')
            else:
                print('❌ 차단 (<50%)')

            print('\n📊 비교:')
            print(f'  실시간 ML: 61.3% (minute=21) ✅ 통과')
            print(f'  시뮬 ML(최종): {ml_prob:.1%} (minute={features_dict.get("minute")}) {"✅ 통과" if ml_prob >= 0.50 else "❌ 차단"}')

            break
