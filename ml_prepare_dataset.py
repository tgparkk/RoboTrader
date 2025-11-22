#!/usr/bin/env python3
"""
패턴 데이터 로그에서 ML 학습용 데이터셋 생성

입력: pattern_data_log/*.jsonl
출력: ml_dataset.csv (학습용 피처 + 라벨)
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import numpy as np


def extract_features_from_pattern(pattern_data: Dict) -> Optional[Dict]:
    """패턴 데이터에서 ML 특징(feature) 추출

    Returns:
        Dict: 특징 딕셔너리 또는 None (매매결과 없는 경우)
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

    # 타임스탬프에서 시간 정보 추출
    timestamp_str = pattern_data.get('timestamp', '')
    try:
        dt = datetime.fromisoformat(timestamp_str)
        hour = dt.hour
        minute = dt.minute
        time_in_minutes = hour * 60 + minute  # 9:00 = 540, 15:30 = 930
    except:
        hour = 0
        minute = 0
        time_in_minutes = 0

    # === 신호 특징 ===
    signal_type = signal_info.get('signal_type', 'UNKNOWN')
    confidence = signal_info.get('confidence', 0)

    # === 패턴 특징 ===
    # 1단계: 상승구간
    uptrend = pattern_stages.get('1_uptrend', {})
    uptrend_candles = uptrend.get('candle_count', 0)
    uptrend_gain = float(uptrend.get('price_gain', '0%').replace('%', ''))
    uptrend_max_volume = int(str(uptrend.get('max_volume', '0')).replace(',', ''))

    # 상승구간 캔들 데이터에서 추가 특징
    uptrend_candles_data = uptrend.get('candles', [])
    if uptrend_candles_data:
        uptrend_avg_body = np.mean([abs(c['close'] - c['open']) for c in uptrend_candles_data])
        uptrend_total_volume = sum([c['volume'] for c in uptrend_candles_data])
    else:
        uptrend_avg_body = 0
        uptrend_total_volume = 0

    # 2단계: 하락구간
    decline = pattern_stages.get('2_decline', {})
    decline_candles = decline.get('candle_count', 0)
    decline_pct = float(decline.get('decline_pct', '0%').replace('%', ''))

    decline_candles_data = decline.get('candles', [])
    if decline_candles_data:
        decline_avg_volume = np.mean([c['volume'] for c in decline_candles_data])
    else:
        decline_avg_volume = 0

    # 3단계: 지지구간
    support = pattern_stages.get('3_support', {})
    support_candles = support.get('candle_count', 0)
    support_volatility = float(support.get('price_volatility', '0%').replace('%', ''))
    support_avg_volume_ratio_str = support.get('avg_volume_ratio', '0%')
    support_avg_volume_ratio = float(support_avg_volume_ratio_str.replace('%', ''))

    support_candles_data = support.get('candles', [])
    if support_candles_data:
        support_avg_volume = np.mean([c['volume'] for c in support_candles_data])
    else:
        support_avg_volume = 0

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
    # 거래량 비율
    volume_ratio_decline_to_uptrend = (decline_avg_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    volume_ratio_support_to_uptrend = (support_avg_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    volume_ratio_breakout_to_uptrend = (breakout_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0

    # 가격 변동 비율
    price_gain_to_decline_ratio = (uptrend_gain / abs(decline_pct)) if decline_pct != 0 else 0

    # 캔들 개수 비율
    candle_ratio_support_to_decline = (support_candles / decline_candles) if decline_candles > 0 else 0

    features = {
        # 라벨
        'label': label,
        'profit_rate': profit_rate,
        'sell_reason': trade_result.get('sell_reason', ''),

        # 시간 특징
        'hour': hour,
        'minute': minute,
        'time_in_minutes': time_in_minutes,
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
        'decline_pct': abs(decline_pct),  # 절댓값
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

    print(f"📂 패턴 로그 파일 {len(jsonl_files)}개 발견")

    for jsonl_file in jsonl_files:
        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        pattern = json.loads(line)
                        all_patterns.append(pattern)
        except Exception as e:
            print(f"⚠️ {jsonl_file.name} 로드 오류: {e}")

    print(f"📊 총 {len(all_patterns)}개 패턴 로드 완료")
    return all_patterns


def create_ml_dataset(pattern_log_dir: str = 'pattern_data_log', output_file: str = 'ml_dataset.csv'):
    """ML 데이터셋 생성"""
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("🤖 ML 학습용 데이터셋 생성 시작")
    print("=" * 70)

    # 패턴 데이터 로드
    pattern_log_path = Path(pattern_log_dir)
    if not pattern_log_path.exists():
        print(f"❌ 패턴 로그 디렉토리를 찾을 수 없습니다: {pattern_log_dir}")
        return

    all_patterns = load_all_pattern_data(pattern_log_path)

    # 특징 추출
    print("\n🔧 특징 추출 중...")
    features_list = []

    for i, pattern in enumerate(all_patterns):
        if (i + 1) % 100 == 0:
            print(f"   처리 중... {i+1}/{len(all_patterns)}")

        features = extract_features_from_pattern(pattern)
        if features is not None:
            features_list.append(features)

    if not features_list:
        print("❌ 매매 결과가 있는 패턴이 없습니다.")
        return

    # DataFrame 생성
    df = pd.DataFrame(features_list)

    # 통계 출력
    print("\n" + "=" * 70)
    print("📊 데이터셋 통계")
    print("=" * 70)
    print(f"총 샘플 수: {len(df)}")
    print(f"승리 샘플: {df['label'].sum()} ({df['label'].mean()*100:.1f}%)")
    print(f"패배 샘플: {len(df) - df['label'].sum()} ({(1-df['label'].mean())*100:.1f}%)")
    print(f"\n특징(feature) 수: {len(df.columns) - 5}")  # 라벨 관련 컬럼 제외

    # 시간대별 통계
    print("\n⏰ 시간대별 분포:")
    for hour in sorted(df['hour'].unique()):
        hour_df = df[df['hour'] == hour]
        win_rate = hour_df['label'].mean() * 100
        print(f"   {hour:02d}시: {len(hour_df):3d}건 (승률 {win_rate:.1f}%)")

    # 신호 타입별 통계
    print("\n🎯 신호 타입별 분포:")
    for signal_type in df['signal_type'].unique():
        sig_df = df[df['signal_type'] == signal_type]
        win_rate = sig_df['label'].mean() * 100
        print(f"   {signal_type}: {len(sig_df):3d}건 (승률 {win_rate:.1f}%)")

    # CSV 저장
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 데이터셋 저장 완료: {output_file}")
    print(f"   파일 크기: {Path(output_file).stat().st_size / 1024:.1f} KB")

    # 컬럼 목록 출력
    print("\n📋 특징(feature) 컬럼 목록:")
    feature_cols = [col for col in df.columns if col not in ['label', 'profit_rate', 'sell_reason', 'stock_code', 'pattern_id', 'timestamp']]
    for i, col in enumerate(feature_cols, 1):
        print(f"   {i:2d}. {col}")

    return df


if __name__ == '__main__':
    df = create_ml_dataset()
