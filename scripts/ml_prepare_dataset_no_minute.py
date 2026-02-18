#!/usr/bin/env python3
"""
패턴 데이터 로그에서 ML 학습용 데이터셋 생성
- 기간: 09/01 ~ 01/16 전체
- 제외 피처: minute, time_in_minutes (과적합 방지)
- 포함 피처: hour, is_morning (시간대 정보)

입력: pattern_data_log/*.jsonl
출력: ml_dataset_no_minute.csv
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import numpy as np
import sys

sys.stdout.reconfigure(encoding='utf-8')


def safe_float_from_percent(value, default=0.0):
    """퍼센트 문자열 또는 숫자를 float로 안전하게 변환"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.replace('%', ''))
    return default


def safe_int_from_str(value, default=0):
    """문자열이나 숫자를 int로 안전하게 변환"""
    if value is None:
        return default
    try:
        return int(float(str(value).replace(',', '')))
    except:
        return default


def extract_features_from_pattern(pattern_data: Dict) -> Optional[Dict]:
    """패턴 데이터에서 ML 특징(feature) 추출
    - minute, time_in_minutes 제외
    - hour, is_morning 포함
    """
    # 매매 결과가 없으면 스킵 (라벨이 없음)
    trade_result = pattern_data.get('trade_result')
    if trade_result is None or not trade_result.get('trade_executed', False):
        return None

    # 라벨 (승/패)
    profit_rate = trade_result.get('profit_rate', 0)
    label = 1 if profit_rate > 0 else 0  # 1=승리, 0=패배

    # 기본 정보
    signal_info = pattern_data.get('signal_info', {})
    pattern_stages = pattern_data.get('pattern_stages', {})

    # 타임스탬프에서 시간 정보 추출 (hour, is_morning만 사용)
    # signal_time 또는 log_timestamp 사용
    timestamp_str = pattern_data.get('signal_time') or pattern_data.get('log_timestamp') or pattern_data.get('timestamp', '')
    try:
        dt = datetime.fromisoformat(timestamp_str)
        hour = dt.hour
    except:
        hour = 0

    # === 신호 특징 ===
    signal_type = signal_info.get('signal_type', 'UNKNOWN')
    confidence = signal_info.get('confidence', 0)

    # === 패턴 특징 ===
    # 1단계: 상승구간
    uptrend = pattern_stages.get('1_uptrend', {})
    uptrend_candles = uptrend.get('candle_count', 0)
    uptrend_gain = safe_float_from_percent(uptrend.get('price_gain', '0%'))
    uptrend_max_volume = safe_int_from_str(uptrend.get('max_volume', '0'))

    # 상승구간 캔들 데이터에서 추가 특징
    uptrend_candles_data = uptrend.get('candles', [])
    if uptrend_candles_data:
        uptrend_avg_body = np.mean([abs(c['close'] - c['open']) for c in uptrend_candles_data])
        uptrend_total_volume = sum([c['volume'] for c in uptrend_candles_data])
        uptrend_volume_std = np.std([c['volume'] for c in uptrend_candles_data])
        uptrend_bullish_ratio = sum([1 for c in uptrend_candles_data if c['close'] > c['open']]) / len(uptrend_candles_data)
        uptrend_max_price = max([c['high'] for c in uptrend_candles_data])
    else:
        uptrend_avg_body = 0
        uptrend_total_volume = 0
        uptrend_volume_std = 0
        uptrend_bullish_ratio = 0
        uptrend_max_price = 0

    # 2단계: 하락구간
    decline = pattern_stages.get('2_decline', {})
    decline_candles = decline.get('candle_count', 0)
    decline_pct = safe_float_from_percent(decline.get('decline_pct', '0%'))

    decline_candles_data = decline.get('candles', [])
    if decline_candles_data:
        decline_avg_volume = np.mean([c['volume'] for c in decline_candles_data])
        decline_volume_std = np.std([c['volume'] for c in decline_candles_data])
        decline_min_price = min([c['low'] for c in decline_candles_data])
    else:
        decline_avg_volume = 0
        decline_volume_std = 0
        decline_min_price = 0

    # 3단계: 지지구간
    support = pattern_stages.get('3_support', {})
    support_candles = support.get('candle_count', 0)
    support_volatility = safe_float_from_percent(support.get('price_volatility', '0%'))
    support_avg_volume_ratio = safe_float_from_percent(support.get('avg_volume_ratio', '0%'))

    support_candles_data = support.get('candles', [])
    if support_candles_data:
        support_avg_volume = np.mean([c['volume'] for c in support_candles_data])
        support_volume_std = np.std([c['volume'] for c in support_candles_data])
        support_min_price = min([c['low'] for c in support_candles_data])
    else:
        support_avg_volume = 0
        support_volume_std = 0
        support_min_price = 0

    # 4단계: 돌파양봉
    breakout = pattern_stages.get('4_breakout', {})
    breakout_candle = breakout.get('candle', {})
    if breakout_candle:
        breakout_volume = breakout_candle.get('volume', 0)
        breakout_body = abs(breakout_candle.get('close', 0) - breakout_candle.get('open', 0))
        breakout_high = breakout_candle.get('high', 0)
        breakout_low = breakout_candle.get('low', 0)
        breakout_range = breakout_high - breakout_low
    else:
        breakout_volume = 0
        breakout_body = 0
        breakout_range = 0

    # === 파생 특징 ===
    volume_ratio_decline_to_uptrend = (decline_avg_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    volume_ratio_support_to_uptrend = (support_avg_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    volume_ratio_breakout_to_uptrend = (breakout_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    price_gain_to_decline_ratio = (uptrend_gain / abs(decline_pct)) if decline_pct != 0 else 0
    candle_ratio_support_to_decline = (support_candles / decline_candles) if decline_candles > 0 else 0

    # 하락 깊이
    decline_depth = 0
    if uptrend_max_price > 0 and decline_min_price > 0:
        decline_depth = (uptrend_max_price - decline_min_price) / uptrend_max_price

    # 회복률
    recovery_rate = 0
    if support_min_price > 0 and breakout_candle:
        breakout_close = breakout_candle.get('close', 0)
        if breakout_close > 0:
            recovery_rate = (breakout_close - support_min_price) / support_min_price

    # 돌파양봉 몸통 비율
    breakout_body_ratio = breakout_body / breakout_range if breakout_range > 0 else 0

    # 상승/하락 속도
    uptrend_gain_per_candle = uptrend_gain / uptrend_candles if uptrend_candles > 0 else 0
    decline_loss_per_candle = abs(decline_pct) / decline_candles if decline_candles > 0 else 0

    # 전체 패턴 길이
    total_pattern_candles = uptrend_candles + decline_candles + support_candles + 1

    # 거래량 집중도
    volume_concentration = 0
    if uptrend_candles_data:
        uptrend_volume_avg = np.mean([c['volume'] for c in uptrend_candles_data])
        volume_concentration = uptrend_max_volume / uptrend_volume_avg if uptrend_volume_avg > 0 else 0

    # === 새로운 패턴 품질 피처 (6개) ===

    # 1. 돌파양봉 직전 캔들과의 거래량 비교
    breakout_vol_vs_prev_candle = 0
    breakout_idx = breakout.get('idx', 0)
    # 지지구간의 마지막 캔들이 직전 캔들
    if support_candles_data and breakout_volume > 0:
        prev_candle_volume = support_candles_data[-1]['volume']
        if prev_candle_volume > 0:
            breakout_vol_vs_prev_candle = breakout_volume / prev_candle_volume

    # 2. 지지구간 저점 일관성 (낮을수록 견고한 지지)
    support_low_consistency = 0
    if support_candles_data and len(support_candles_data) > 1:
        support_lows = [c['low'] for c in support_candles_data]
        avg_low = np.mean(support_lows)
        if avg_low > 0:
            support_low_consistency = np.std(support_lows) / avg_low  # CV (변동계수)

    # 3. 상승구간 연속 양봉 최대 개수
    uptrend_consecutive_bullish = 0
    if uptrend_candles_data:
        current_streak = 0
        max_streak = 0
        for c in uptrend_candles_data:
            if c['close'] > c['open']:  # 양봉
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        uptrend_consecutive_bullish = max_streak

    # 4. 하락구간 음봉 비율
    decline_bearish_ratio = 0
    if decline_candles_data:
        bearish_count = sum([1 for c in decline_candles_data if c['close'] < c['open']])
        decline_bearish_ratio = bearish_count / len(decline_candles_data)

    # 5. 지지구간 거래량이 기준거래량(상승구간 최대)의 1/4 이하인지
    support_vol_below_quarter = 0
    if uptrend_max_volume > 0 and support_avg_volume > 0:
        support_vol_below_quarter = 1 if support_avg_volume <= (uptrend_max_volume / 4) else 0

    # 6. 돌파봉 몸통이 지지구간 평균 몸통보다 큰지
    breakout_body_vs_support_avg = 0
    if support_candles_data and breakout_body > 0:
        support_avg_body = np.mean([abs(c['close'] - c['open']) for c in support_candles_data])
        if support_avg_body > 0:
            breakout_body_vs_support_avg = breakout_body / support_avg_body

    features = {
        # 라벨
        'label': label,
        'profit_rate': profit_rate,
        'sell_reason': trade_result.get('sell_reason', ''),

        # 시간 특징 (hour, is_morning만 포함 - minute, time_in_minutes 제외)
        'hour': hour,
        'is_morning': 1 if hour < 12 else 0,

        # 신호 특징
        'signal_type': signal_type,
        'confidence': confidence,

        # 패턴 특징 - 상승구간
        'uptrend_candles': uptrend_candles,
        'uptrend_gain': uptrend_gain,
        'uptrend_max_volume': uptrend_max_volume,
        'uptrend_avg_body': uptrend_avg_body,
        'uptrend_total_volume': uptrend_total_volume,

        # 패턴 특징 - 하락구간
        'decline_candles': decline_candles,
        'decline_pct': abs(decline_pct),
        'decline_avg_volume': decline_avg_volume,

        # 패턴 특징 - 지지구간
        'support_candles': support_candles,
        'support_volatility': support_volatility,
        'support_avg_volume_ratio': support_avg_volume_ratio,
        'support_avg_volume': support_avg_volume,

        # 패턴 특징 - 돌파양봉
        'breakout_volume': breakout_volume,
        'breakout_body': breakout_body,
        'breakout_range': breakout_range,

        # 파생 특징
        'volume_ratio_decline_to_uptrend': volume_ratio_decline_to_uptrend,
        'volume_ratio_support_to_uptrend': volume_ratio_support_to_uptrend,
        'volume_ratio_breakout_to_uptrend': volume_ratio_breakout_to_uptrend,
        'price_gain_to_decline_ratio': price_gain_to_decline_ratio,
        'candle_ratio_support_to_decline': candle_ratio_support_to_decline,

        # 새로운 특징
        'uptrend_volume_std': uptrend_volume_std,
        'decline_volume_std': decline_volume_std,
        'support_volume_std': support_volume_std,
        'uptrend_bullish_ratio': uptrend_bullish_ratio,
        'decline_depth': decline_depth,
        'recovery_rate': recovery_rate,
        'breakout_body_ratio': breakout_body_ratio,
        'uptrend_gain_per_candle': uptrend_gain_per_candle,
        'decline_loss_per_candle': decline_loss_per_candle,
        'total_pattern_candles': total_pattern_candles,
        'volume_concentration': volume_concentration,

        # 패턴 품질 피처 (신규 6개)
        'breakout_vol_vs_prev_candle': breakout_vol_vs_prev_candle,  # 돌파봉/직전봉 거래량 비율
        'support_low_consistency': support_low_consistency,          # 지지구간 저점 일관성 (낮을수록 좋음)
        'uptrend_consecutive_bullish': uptrend_consecutive_bullish,  # 상승구간 연속 양봉 최대
        'decline_bearish_ratio': decline_bearish_ratio,              # 하락구간 음봉 비율
        'support_vol_below_quarter': support_vol_below_quarter,      # 지지구간 거래량 <= 기준의 1/4
        'breakout_body_vs_support_avg': breakout_body_vs_support_avg, # 돌파봉 몸통/지지구간 평균 몸통

        # 메타데이터
        'stock_code': pattern_data.get('stock_code', ''),
        'pattern_id': pattern_data.get('pattern_id', ''),
        'timestamp': timestamp_str,
    }

    return features


def load_all_pattern_data(pattern_log_dir: Path) -> List[Dict]:
    """모든 패턴 로그 파일에서 데이터 로드"""
    all_patterns = []

    jsonl_files = sorted(pattern_log_dir.glob('pattern_data_*.jsonl'))

    print(f"패턴 로그 파일 {len(jsonl_files)}개 발견")

    for jsonl_file in jsonl_files:
        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        pattern = json.loads(line)
                        all_patterns.append(pattern)
        except Exception as e:
            print(f"  {jsonl_file.name} 로드 오류: {e}")

    print(f"총 {len(all_patterns)}개 패턴 로드 완료")
    return all_patterns


def create_ml_dataset(pattern_log_dir: str = 'pattern_data_log', output_file: str = 'ml_dataset_no_minute.csv'):
    """ML 데이터셋 생성 (중복 제거)"""
    print("=" * 70)
    print("ML 학습용 데이터셋 생성")
    print("- 제외 피처: minute, time_in_minutes")
    print("- 포함 피처: hour, is_morning")
    print("- 중복 제거: 종목+날짜+시간(분) 기준 첫 번째만 사용")
    print("=" * 70)

    # 패턴 데이터 로드
    pattern_log_path = Path(pattern_log_dir)
    if not pattern_log_path.exists():
        print(f"패턴 로그 디렉토리를 찾을 수 없습니다: {pattern_log_dir}")
        return

    all_patterns = load_all_pattern_data(pattern_log_path)

    # 특징 추출 (중복 제거)
    print("\n특징 추출 중 (중복 제거)...")
    features_list = []
    seen_keys = set()  # 중복 체크용: (종목코드, 날짜, 시간분)
    duplicate_count = 0

    for i, pattern in enumerate(all_patterns):
        if (i + 1) % 500 == 0:
            print(f"   처리 중... {i+1}/{len(all_patterns)}")

        # trade_executed가 True인 것만 처리
        trade_result = pattern.get('trade_result')
        if trade_result is None or not trade_result.get('trade_executed', False):
            continue

        # 중복 체크: pattern_id에서 종목코드_날짜_시간(분까지만) 추출
        pattern_id = pattern.get('pattern_id', '')
        # 예: 004310_20260116_093000 -> 004310_20260116_0930
        if len(pattern_id) >= 18:
            dedup_key = pattern_id[:18]  # 종목코드_날짜_시분 (초 제외)
        else:
            dedup_key = pattern_id

        if dedup_key in seen_keys:
            duplicate_count += 1
            continue
        seen_keys.add(dedup_key)

        features = extract_features_from_pattern(pattern)
        if features is not None:
            features_list.append(features)

    print(f"   중복 제거: {duplicate_count}건 스킵됨")

    if not features_list:
        print("매매 결과가 있는 패턴이 없습니다.")
        return

    # DataFrame 생성
    df = pd.DataFrame(features_list)

    # 통계 출력
    print("\n" + "=" * 70)
    print("데이터셋 통계")
    print("=" * 70)
    print(f"총 샘플 수: {len(df)}")
    print(f"승리 샘플: {df['label'].sum()} ({df['label'].mean()*100:.1f}%)")
    print(f"패배 샘플: {len(df) - df['label'].sum()} ({(1-df['label'].mean())*100:.1f}%)")

    # 피처 수 계산 (메타 컬럼 제외)
    meta_cols = ['label', 'profit_rate', 'sell_reason', 'stock_code', 'pattern_id', 'timestamp']
    feature_cols = [col for col in df.columns if col not in meta_cols]
    print(f"\n특징(feature) 수: {len(feature_cols)}")

    # 시간대별 통계
    print("\n시간대별 분포:")
    for hour in sorted(df['hour'].unique()):
        hour_df = df[df['hour'] == hour]
        win_rate = hour_df['label'].mean() * 100
        print(f"   {hour:02d}시: {len(hour_df):4d}건 (승률 {win_rate:.1f}%)")

    # 신호 타입별 통계
    print("\n신호 타입별 분포:")
    for signal_type in df['signal_type'].unique():
        sig_df = df[df['signal_type'] == signal_type]
        win_rate = sig_df['label'].mean() * 100
        print(f"   {signal_type}: {len(sig_df):4d}건 (승률 {win_rate:.1f}%)")

    # CSV 저장
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n데이터셋 저장 완료: {output_file}")
    print(f"   파일 크기: {Path(output_file).stat().st_size / 1024:.1f} KB")

    # 컬럼 목록 출력
    print("\n특징(feature) 컬럼 목록:")
    for i, col in enumerate(feature_cols, 1):
        print(f"   {i:2d}. {col}")

    return df


if __name__ == '__main__':
    df = create_ml_dataset()
