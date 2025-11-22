"""
최종 검증: 시뮬레이션 vs 실시간 ML 특성 추출 동일성
"""
import pandas as pd
from core.ml_predictor import MLPredictor

# 동일한 테스트 데이터
test_pattern_simulation = {
    'signal_time': '2025-11-22 10:30:00',
    'signal_info': {
        'signal_type': 'STRONG_BUY',
        'confidence': 85.0
    },
    'pattern_stages': {
        '1_uptrend': {
            'candle_count': 5,
            'price_gain': 0.05,
            'max_volume': 2000,
            'candles': [
                {'open': 100, 'close': 101, 'volume': 1000},
                {'open': 101, 'close': 102, 'volume': 1200},
                {'open': 102, 'close': 103, 'volume': 1500},
                {'open': 103, 'close': 104, 'volume': 1800},
                {'open': 104, 'close': 105, 'volume': 2000}
            ]
        },
        '2_decline': {
            'candle_count': 3,
            'decline_pct': 0.02,
            'candles': [
                {'open': 104, 'close': 103, 'volume': 800},
                {'open': 103, 'close': 102, 'volume': 600},
                {'open': 102, 'close': 101.5, 'volume': 500}
            ]
        },
        '3_support': {
            'candle_count': 3,
            'price_volatility': 0.005,
            'avg_volume_ratio': 0.15,
            'candles': [
                {'open': 102, 'close': 102, 'volume': 300},
                {'open': 102, 'close': 102, 'volume': 250},
                {'open': 102, 'close': 102, 'volume': 280}
            ]
        },
        '4_breakout': {
            'candle': {
                'open': 103, 'close': 104.5, 'high': 105, 'low': 102, 'volume': 900
            }
        }
    }
}

test_pattern_realtime = {
    'signal_time': '2025-11-22 10:30:00',
    'signal_info': {
        'signal_type': 'STRONG_BUY',
        'confidence': 85.0
    },
    'debug_info': {
        'uptrend': {
            'bar_count': 5,
            'gain_pct': 0.05,
            'max_volume_numeric': 2000,
            'avg_volume': 1500,
            'total_volume': 7500,
            'avg_body_pct': 0.9805806829  # 정확한 계산값!
        },
        'decline': {
            'bar_count': 3,
            'decline_pct': 0.02,
            'avg_volume': 633.33,
            'avg_body_pct': 0.9662375533  # 정확한 계산값!
        },
        'support': {
            'bar_count': 3,
            'candle_count': 3,
            'price_volatility': 0.005,
            'avg_volume_ratio': 0.15,
            'avg_volume': 276.67,
            'avg_body_pct': 0.4901960784  # 정확한 계산값!
        },
        'breakout': {
            'volume': 900,
            'body_pct': 1.4563106796,  # 정확한 계산값!
            'gain_pct': 1.46
        },
        'best_breakout': {
            'high': 105, 'low': 102, 'close': 104.5, 'open': 103, 'volume': 900
        }
    }
}

print("=" * 80)
print("최종 검증: 시뮬레이션 vs 실시간 ML 특성 추출")
print("=" * 80)

predictor = MLPredictor()
predictor.load_model()

# 시뮬레이션 특성 추출
print("\n[1] 시뮬레이션 데이터 (pattern_stages)")
sim_features = predictor.extract_features_from_pattern(test_pattern_simulation)
print(f"  uptrend_avg_body: {sim_features['uptrend_avg_body'].iloc[0]:.4f}%")
print(f"  decline_candles: {sim_features['decline_candles'].iloc[0]:.0f}")
print(f"  breakout_body: {sim_features['breakout_body'].iloc[0]:.4f}%")

# 실시간 특성 추출
print("\n[2] 실시간 데이터 (debug_info)")
real_features = predictor.extract_features_from_pattern(test_pattern_realtime)
print(f"  uptrend_avg_body: {real_features['uptrend_avg_body'].iloc[0]:.4f}%")
print(f"  decline_candles: {real_features['decline_candles'].iloc[0]:.0f}")
print(f"  breakout_body: {real_features['breakout_body'].iloc[0]:.4f}%")

# ML 예측 비교
sim_trade, sim_prob = predictor.should_trade(test_pattern_simulation, threshold=0.5)
real_trade, real_prob = predictor.should_trade(test_pattern_realtime, threshold=0.5)

print("\n" + "=" * 80)
print("ML 예측 결과 비교")
print("=" * 80)
print(f"시뮬레이션: 거래={sim_trade}, 승률={sim_prob:.1%}")
print(f"실시간:     거래={real_trade}, 승률={real_prob:.1%}")

# 특성 값 차이 계산
print("\n" + "=" * 80)
print("주요 특성 차이 분석")
print("=" * 80)

key_features = ['uptrend_avg_body', 'uptrend_total_volume', 'decline_candles',
                'support_candles', 'breakout_body', 'breakout_range']

max_diff = 0
for feat in key_features:
    sim_val = sim_features[feat].iloc[0]
    real_val = real_features[feat].iloc[0]
    diff = abs(sim_val - real_val)
    diff_pct = (diff / sim_val * 100) if sim_val != 0 else 0

    print(f"{feat:25s}: 시뮬={sim_val:12.2f}, 실시간={real_val:12.2f}, 차이={diff:8.2f} ({diff_pct:5.1f}%)")
    max_diff = max(max_diff, diff_pct)

print("\n" + "=" * 80)
if max_diff < 5:
    print("✅ 검증 성공! 시뮬레이션과 실시간 ML 특성이 거의 동일합니다.")
    print(f"   최대 차이: {max_diff:.2f}%")
else:
    print(f"⚠️  경고: 최대 차이가 {max_diff:.2f}%로 5%를 초과합니다.")
print("=" * 80)
