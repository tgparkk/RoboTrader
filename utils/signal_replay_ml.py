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

# ML 모델 로드 (실시간 거래와 동일한 모델 사용)
ML_MODEL_PATH = Path("ml_model_stratified.pkl")


def load_ml_model():
    """ML 모델 로드 (실시간 거래와 동일한 stratified 모델)"""
    if not ML_MODEL_PATH.exists():
        print(f"⚠️  ML 모델 파일을 찾을 수 없습니다: {ML_MODEL_PATH}")
        print(f"   ml_train_model.py를 먼저 실행하여 모델을 학습시켜주세요.")
        return None

    try:
        with open(ML_MODEL_PATH, 'rb') as f:
            model_data = pickle.load(f)

        model = model_data['model']
        feature_names = model_data['feature_names']

        print(f"✅ ML 모델 로드 완료: {ML_MODEL_PATH.name}")
        print(f"   - 특성 수: {len(feature_names)}개")
        print(f"   - 버전: {model_data.get('version', 'N/A')}")
        print(f"   - 설명: {model_data.get('description', 'N/A')}")
        return model, feature_names

    except Exception as e:
        print(f"❌ ML 모델 로드 실패: {e}")
        return None


def safe_float(value, default=0.0):
    """문자열을 float으로 안전하게 변환"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # "3.52%" -> 3.52, "162,154" -> 162154
        value = value.replace(',', '').replace('%', '').strip()
        try:
            return float(value)
        except:
            return default
    return default


def calculate_avg_volume_from_candles(candles: list) -> float:
    """캔들 리스트에서 평균 거래량 계산"""
    if not candles:
        return 0.0
    volumes = [c.get('volume', 0) for c in candles]
    return sum(volumes) / len(volumes) if volumes else 0.0


def calculate_avg_body_pct(candles: list) -> float:
    """캔들 리스트에서 평균 몸통 비율 계산"""
    if not candles:
        return 0.0
    body_pcts = []
    for c in candles:
        open_p = c.get('open', 0)
        close_p = c.get('close', 0)
        if open_p > 0:
            body_pct = abs((close_p - open_p) / open_p * 100)
            body_pcts.append(body_pct)
    return sum(body_pcts) / len(body_pcts) if body_pcts else 0.0


def extract_features_from_pattern(pattern_info: dict) -> dict:
    """
    패턴 정보에서 ML 모델 입력 특성 추출
    (apply_ml_filter.py와 동일한 로직 사용 - pattern_stages 구조 기반)

    Args:
        pattern_info: 패턴 데이터 (pattern_stages 구조)

    Returns:
        특성 딕셔너리
    """
    try:
        from datetime import datetime

        # 신호 시간 정보
        signal_time_str = pattern_info.get('signal_time', '')
        if signal_time_str:
            try:
                # "2025-11-26 09:30:00" 또는 "09:30:00" 형식 지원
                if ' ' in signal_time_str:
                    signal_time = datetime.strptime(signal_time_str, '%Y-%m-%d %H:%M:%S')
                else:
                    hour, minute, _ = map(int, signal_time_str.split(':'))
                    signal_time = None

                if signal_time:
                    hour = signal_time.hour
                    minute = signal_time.minute
            except:
                hour, minute = 0, 0
        else:
            hour, minute = 0, 0

        # 신호 정보
        signal_info = pattern_info.get('signal_info', {})
        signal_type = signal_info.get('signal_type', pattern_info.get('signal_type', ''))
        signal_type_encoded = 1 if signal_type == 'STRONG_BUY' else 0
        confidence = safe_float(signal_info.get('confidence', pattern_info.get('confidence', 0.0)))

        # 패턴 구간 정보 (pattern_stages 사용)
        pattern_stages = pattern_info.get('pattern_stages', {})

        # 상승 구간
        uptrend = pattern_stages.get('1_uptrend', {})
        uptrend_candles = uptrend.get('candle_count', 0)
        uptrend_gain = safe_float(uptrend.get('price_gain', 0.0))
        uptrend_max_volume_str = uptrend.get('max_volume', '0')
        uptrend_max_volume = safe_float(uptrend_max_volume_str)

        # 상승 구간 캔들에서 평균 계산
        uptrend_candles_list = uptrend.get('candles', [])
        uptrend_avg_body = calculate_avg_body_pct(uptrend_candles_list)
        uptrend_total_volume = sum(c.get('volume', 0) for c in uptrend_candles_list)

        # 하락 구간
        decline = pattern_stages.get('2_decline', {})
        decline_candles = decline.get('candle_count', 0)
        decline_pct = abs(safe_float(decline.get('decline_pct', 0.0)))
        decline_candles_list = decline.get('candles', [])
        decline_avg_volume = calculate_avg_volume_from_candles(decline_candles_list)

        # 지지 구간
        support = pattern_stages.get('3_support', {})
        support_candles = support.get('candle_count', 0)
        support_volatility = safe_float(support.get('price_volatility', 0.0))
        support_avg_volume_ratio = safe_float(support.get('avg_volume_ratio', 1.0))
        support_candles_list = support.get('candles', [])
        support_avg_volume = calculate_avg_volume_from_candles(support_candles_list)

        # 돌파 구간
        breakout = pattern_stages.get('4_breakout', {})
        if breakout and breakout.get('candle'):
            breakout_candle = breakout.get('candle', {})
            breakout_volume = breakout_candle.get('volume', 0)

            # 몸통 크기 계산
            open_p = breakout_candle.get('open', 0)
            close_p = breakout_candle.get('close', 0)
            if open_p > 0:
                breakout_body = abs((close_p - open_p) / open_p * 100)
            else:
                breakout_body = 0.0

            # 범위 크기 계산
            high_p = breakout_candle.get('high', 0)
            low_p = breakout_candle.get('low', 0)
            if low_p > 0:
                breakout_range = (high_p - low_p) / low_p * 100
            else:
                breakout_range = 0.0
        else:
            breakout_volume, breakout_body, breakout_range = 0, 0.0, 0.0

        # 비율 특성 계산
        volume_ratio_decline_to_uptrend = (
            decline_avg_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        )
        volume_ratio_support_to_uptrend = (
            support_avg_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        )
        volume_ratio_breakout_to_uptrend = (
            breakout_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        )
        price_gain_to_decline_ratio = (
            uptrend_gain / decline_pct if decline_pct > 0 else 0
        )
        candle_ratio_support_to_decline = (
            support_candles / decline_candles if decline_candles > 0 else 0
        )

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
            'uptrend_avg_body': uptrend_avg_body,
            'uptrend_total_volume': uptrend_total_volume,

            'decline_candles': decline_candles,
            'decline_pct': decline_pct,
            'decline_avg_volume': decline_avg_volume,

            'support_candles': support_candles,
            'support_volatility': support_volatility,
            'support_avg_volume_ratio': support_avg_volume_ratio,
            'support_avg_volume': support_avg_volume,

            'breakout_volume': breakout_volume,
            'breakout_body': breakout_body,
            'breakout_range': breakout_range,

            'volume_ratio_decline_to_uptrend': volume_ratio_decline_to_uptrend,
            'volume_ratio_support_to_uptrend': volume_ratio_support_to_uptrend,
            'volume_ratio_breakout_to_uptrend': volume_ratio_breakout_to_uptrend,
            'price_gain_to_decline_ratio': price_gain_to_decline_ratio,
            'candle_ratio_support_to_decline': candle_ratio_support_to_decline,
        }

        return features

    except Exception as e:
        print(f"⚠️  특성 추출 실패: {e}")
        import traceback
        traceback.print_exc()
        return {}


def predict_win_probability(model, feature_names, pattern_info: dict) -> float:
    """
    패턴의 승률 예측 (실시간 거래와 동일한 방식)

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

        # 🔍 디버그: 특성 벡터 로깅 (440110 종목만)
        stock_code = pattern_info.get('stock_code', '')
        if stock_code == '440110':
            print(f"[시뮬ML] {stock_code} 특성 벡터:")
            for col in X.columns:
                print(f"  {col}: {X[col].iloc[0]}")

        # 예측 (실시간 거래와 동일: LightGBM의 predict 사용)
        # ml_model_stratified.pkl은 LightGBM Booster이므로 predict() 사용
        win_prob = model.predict(X, num_iteration=model.best_iteration)[0]

        return float(win_prob)

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

            # ML 예측 (패턴 로그에 저장된 값이 있으면 우선 사용)
            # signal_info 안에 ml_prob가 있는지 확인
            signal_info = signal.get('signal_info', {})
            if signal_info.get('ml_prob') is not None:
                win_prob = float(signal_info['ml_prob'])
                print(f"   ✅ 로그의 ML 값 사용: {stock_code} {signal.get('signal_time', 'N/A')} (승률 {win_prob:.1%})")
            elif 'ml_prob' in signal:  # 하위 호환성
                win_prob = float(signal['ml_prob'])
                print(f"   ✅ 로그의 ML 값 사용: {stock_code} {signal.get('signal_time', 'N/A')} (승률 {win_prob:.1%})")
            else:
                win_prob = predict_win_probability(model, feature_names, signal)
                print(f"   🔄 새로 계산: {stock_code} {signal.get('signal_time', 'N/A')} (승률 {win_prob:.1%})")

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
