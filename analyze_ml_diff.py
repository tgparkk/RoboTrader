#!/usr/bin/env python3
"""
실시간 ML vs 시뮬레이션 ML 차이 분석 스크립트
"""

import json
import sys

# 440110의 10:03 패턴 데이터
pattern_440110_realtime = {
    "pattern_stages": {
        "1_uptrend": {
            "start_idx": 0,
            "end_idx": 8,
            "candle_count": 9,
            "max_volume": "93,000",
            "price_gain": "5.94%",
        },
        "2_decline": {
            "start_idx": 9,
            "end_idx": 12,
            "candle_count": 4,
            "decline_pct": "0.75%",
        },
        "3_support": {
            "start_idx": 13,
            "end_idx": 13,
            "candle_count": 1,
            "price_volatility": "0.000%",
            "avg_volume_ratio": "20.5%",
        },
        "4_breakout": {
            "idx": 21,
            "volume": 44095.0,
        }
    },
    "signal_info": {
        "signal_type": "STRONG_BUY",
        "confidence": 88.0
    },
    "signal_time": "2025-11-27 10:03:00"
}

def safe_float(value, default=0.0):
    """문자열을 float으로 안전하게 변환"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.replace(',', '').replace('%', '').strip()
        try:
            return float(value)
        except:
            return default
    return default

def extract_features_realtime(pattern):
    """실시간 ML 특성 추출 (core/ml_predictor.py 방식)"""
    from datetime import datetime

    pattern_stages = pattern.get('pattern_stages', {})
    signal_info = pattern.get('signal_info', {})

    # 시간 정보
    signal_time_str = pattern.get('signal_time', '')
    if signal_time_str:
        try:
            signal_time = datetime.strptime(signal_time_str, '%Y-%m-%d %H:%M:%S')
            hour = signal_time.hour
            minute = signal_time.minute
        except:
            hour, minute = 0, 0
    else:
        hour, minute = 0, 0

    # 상승 구간
    uptrend = pattern_stages.get('1_uptrend', {})
    uptrend_candles = uptrend.get('candle_count', 0)
    uptrend_gain = safe_float(uptrend.get('price_gain', 0.0))
    uptrend_max_volume = safe_float(uptrend.get('max_volume', 0))

    # 하락 구간
    decline = pattern_stages.get('2_decline', {})
    decline_candles = decline.get('candle_count', 0)
    decline_pct = abs(safe_float(decline.get('decline_pct', 0.0)))

    # 지지 구간
    support = pattern_stages.get('3_support', {})
    support_candles = support.get('candle_count', 0)
    support_volatility = safe_float(support.get('price_volatility', 0.0))
    support_avg_volume_ratio = safe_float(support.get('avg_volume_ratio', 1.0))

    # 돌파 구간
    breakout = pattern_stages.get('4_breakout', {})
    breakout_volume = safe_float(breakout.get('volume', 0))

    # 신호 정보
    signal_type = signal_info.get('signal_type', '')
    signal_type_encoded = 1 if signal_type == 'STRONG_BUY' else 0
    confidence = safe_float(signal_info.get('confidence', 0.0))

    features = {
        'hour': hour,
        'minute': minute,
        'time_in_minutes': hour * 60 + minute,
        'is_morning': 1 if hour < 12 else 0,
        'signal_type': signal_type_encoded,
        'confidence': confidence,

        'uptrend_candles': uptrend_candles,
        'uptrend_gain': uptrend_gain,
        'uptrend_max_volume': uptrend_max_volume,

        'decline_candles': decline_candles,
        'decline_pct': decline_pct,

        'support_candles': support_candles,
        'support_volatility': support_volatility,
        'support_avg_volume_ratio': support_avg_volume_ratio,

        'breakout_volume': breakout_volume,
    }

    return features

# 특성 추출
features = extract_features_realtime(pattern_440110_realtime)

print("=" * 80)
print("440110 실시간 패턴 특성 추출 결과")
print("=" * 80)
print(f"\n시간 정보:")
print(f"  hour: {features['hour']}")
print(f"  minute: {features['minute']}")
print(f"  time_in_minutes: {features['time_in_minutes']}")
print(f"  is_morning: {features['is_morning']}")

print(f"\n신호 정보:")
print(f"  signal_type: {features['signal_type']}")
print(f"  confidence: {features['confidence']}")

print(f"\n상승 구간:")
print(f"  uptrend_candles: {features['uptrend_candles']}")
print(f"  uptrend_gain: {features['uptrend_gain']}")
print(f"  uptrend_max_volume: {features['uptrend_max_volume']}")

print(f"\n하락 구간:")
print(f"  decline_candles: {features['decline_candles']}")
print(f"  decline_pct: {features['decline_pct']}")

print(f"\n지지 구간:")
print(f"  support_candles: {features['support_candles']}")
print(f"  support_volatility: {features['support_volatility']}")
print(f"  support_avg_volume_ratio: {features['support_avg_volume_ratio']}")

print(f"\n돌파 구간:")
print(f"  breakout_volume: {features['breakout_volume']}")

print("\n" + "=" * 80)
print("실시간 ML 예측: 44.7%")
print("시뮬ML 예측: 50.0%")
print("차이: +5.3%p")
print("=" * 80)
