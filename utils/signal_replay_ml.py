#!/usr/bin/env python3
"""
🤖 ML 필터가 적용된 신호 재현 스크립트

기존 signal_replay.py의 결과에 ML 모델을 적용하여
승률이 낮은 신호를 필터링합니다.

사용법:
python -m utils.signal_replay_ml --date 20250901 --export txt --txt-path signal_replay_log_ml/signal_ml_replay_20250901_9_00_0.txt
"""

import sys
import os
import argparse
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

# 프로젝트 루트 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 기존 signal_replay 모듈 임포트
from utils import signal_replay

# ML 모델 로드
ML_MODEL_PATH = Path("ml_model.pkl")


def load_ml_model():
    """ML 모델 로드"""
    if not ML_MODEL_PATH.exists():
        print(f"⚠️  ML 모델 파일을 찾을 수 없습니다: {ML_MODEL_PATH}")
        print(f"   ml_train_model.py를 먼저 실행하여 모델을 학습시켜주세요.")
        return None

    try:
        with open(ML_MODEL_PATH, 'rb') as f:
            model_data = pickle.load(f)

        model = model_data['model']
        feature_names = model_data['feature_names']

        print(f"✅ ML 모델 로드 완료 ({len(feature_names)}개 특성)")
        return model, feature_names

    except Exception as e:
        print(f"❌ ML 모델 로드 실패: {e}")
        return None


def extract_features_from_pattern(pattern_info: dict) -> dict:
    """
    패턴 정보에서 ML 모델 입력 특성 추출

    Args:
        pattern_info: signal_replay에서 분석한 패턴 정보

    Returns:
        특성 딕셔너리
    """
    try:
        # signal_replay의 디버그 정보에서 특성 추출
        debug_info = pattern_info.get('debug_info', {})

        # 시간 정보
        signal_time = pattern_info.get('signal_time', '')  # "HH:MM:SS"
        if signal_time:
            hour, minute, _ = map(int, signal_time.split(':'))
            time_in_minutes = hour * 60 + minute
            is_morning = 1 if hour < 12 else 0
        else:
            hour, minute, time_in_minutes, is_morning = 0, 0, 0, 0

        # 신호 정보
        signal_type = pattern_info.get('signal_type', '')
        signal_type_encoded = 1 if signal_type == 'STRONG_BUY' else 0
        confidence = pattern_info.get('confidence', 0.0)

        # 4단계 패턴 정보
        uptrend = debug_info.get('uptrend', {})
        decline = debug_info.get('decline', {})
        support = debug_info.get('support', {})
        breakout = debug_info.get('breakout', {})

        features = {
            'hour': hour,
            'minute': minute,
            'time_in_minutes': time_in_minutes,
            'is_morning': is_morning,

            'signal_type': signal_type_encoded,
            'confidence': confidence,

            # 상승 구간
            'uptrend_candles': uptrend.get('candle_count', 0),
            'uptrend_gain': uptrend.get('gain_pct', 0.0),
            'uptrend_max_volume': uptrend.get('max_volume', 0),
            'uptrend_avg_body': uptrend.get('avg_body_pct', 0.0),
            'uptrend_total_volume': uptrend.get('volume_sum', 0),

            # 하락 구간
            'decline_candles': decline.get('candle_count', 0),
            'decline_pct': abs(decline.get('decline_pct', 0.0)),
            'decline_avg_volume': decline.get('avg_volume', 0),

            # 지지 구간
            'support_candles': support.get('candle_count', 0),
            'support_volatility': support.get('volatility', 0.0),
            'support_avg_volume_ratio': support.get('avg_volume_ratio_vs_uptrend', 1.0),
            'support_avg_volume': support.get('avg_volume', 0),

            # 돌파 구간
            'breakout_volume': breakout.get('volume', 0),
            'breakout_body': breakout.get('body_pct', 0.0),
            'breakout_range': breakout.get('range_pct', 0.0),
        }

        # 비율 특성 계산
        uptrend_max_vol = features['uptrend_max_volume']
        decline_avg_vol = features['decline_avg_volume']
        support_avg_vol = features['support_avg_volume']
        breakout_vol = features['breakout_volume']

        features['volume_ratio_decline_to_uptrend'] = (
            decline_avg_vol / uptrend_max_vol if uptrend_max_vol > 0 else 0
        )
        features['volume_ratio_support_to_uptrend'] = (
            support_avg_vol / uptrend_max_vol if uptrend_max_vol > 0 else 0
        )
        features['volume_ratio_breakout_to_uptrend'] = (
            breakout_vol / uptrend_max_vol if uptrend_max_vol > 0 else 0
        )

        decline_pct = features['decline_pct']
        features['price_gain_to_decline_ratio'] = (
            features['uptrend_gain'] / decline_pct if decline_pct > 0 else 0
        )

        decline_candles = features['decline_candles']
        features['candle_ratio_support_to_decline'] = (
            features['support_candles'] / decline_candles if decline_candles > 0 else 0
        )

        return features

    except Exception as e:
        print(f"⚠️  특성 추출 실패: {e}")
        return {}


def predict_win_probability(model, feature_names, pattern_info: dict) -> float:
    """
    패턴의 승률 예측

    Returns:
        승률 (0.0 ~ 1.0)
    """
    try:
        # 특성 추출
        features = extract_features_from_pattern(pattern_info)

        if not features:
            return 0.5  # 기본값

        # DataFrame으로 변환 (모델이 기대하는 형식)
        feature_values = [features.get(fname, 0) for fname in feature_names]
        X = pd.DataFrame([feature_values], columns=feature_names)

        # 예측 (승률)
        win_prob = model.predict_proba(X)[0][1]  # 클래스 1 (승리)의 확률

        return win_prob

    except Exception as e:
        print(f"⚠️  예측 실패: {e}")
        return 0.5  # 기본값


def apply_ml_filter(original_results: dict, model_tuple, threshold: float = 0.5) -> dict:
    """
    원본 결과에 ML 필터 적용

    Args:
        original_results: signal_replay 결과
        model_tuple: (model, feature_names)
        threshold: 승률 임계값 (이 값 이하면 필터링)

    Returns:
        필터링된 결과
    """
    if model_tuple is None:
        print("⚠️  ML 모델 없이 원본 결과 반환")
        return original_results

    model, feature_names = model_tuple

    filtered_results = {}
    total_signals = 0
    filtered_count = 0

    for stock_code, stock_data in original_results.items():
        signals = stock_data.get('signals', [])
        filtered_signals = []

        for signal in signals:
            total_signals += 1

            # ML 예측
            win_prob = predict_win_probability(model, feature_names, signal)

            # 임계값 이상만 통과
            if win_prob >= threshold:
                signal['ml_win_probability'] = win_prob
                filtered_signals.append(signal)
            else:
                filtered_count += 1
                print(f"   🚫 필터링: {stock_code} {signal.get('signal_time', 'N/A')} (승률 {win_prob:.1%})")

        # 필터링된 신호가 있으면 추가
        if filtered_signals:
            filtered_results[stock_code] = stock_data.copy()
            filtered_results[stock_code]['signals'] = filtered_signals

    print(f"\n📊 ML 필터링 결과:")
    print(f"   총 신호: {total_signals}개")
    print(f"   통과: {total_signals - filtered_count}개")
    print(f"   차단: {filtered_count}개 ({filtered_count/total_signals*100 if total_signals > 0 else 0:.1f}%)")

    return filtered_results


def main():
    """메인 함수"""
    print("=" * 70)
    print("🤖 ML 필터 적용 신호 재현")
    print("=" * 70)

    # 1. ML 모델 로드
    print("\n📦 ML 모델 로딩 중...")
    model_tuple = load_ml_model()

    # 2. 기존 signal_replay 실행
    print("\n🔄 기존 신호 재현 실행 중...")

    # signal_replay의 main()을 직접 호출하는 대신
    # sys.argv를 그대로 전달하여 독립 실행
    # (signal_replay.py가 argparse를 사용하므로)

    # 임시로 기존 스크립트 실행
    print("\n⚠️  현재 버전에서는 signal_replay.py를 먼저 실행하고")
    print("   그 결과를 ML 필터링하는 방식으로 작동합니다.")
    print("\n사용법:")
    print("   1. python utils/signal_replay.py --date 20250901 --export txt")
    print("   2. 그 결과를 ml_model.pkl로 필터링")
    print("\n통합 버전은 추후 업데이트 예정입니다.")

    sys.exit(0)


if __name__ == "__main__":
    main()
