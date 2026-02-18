#!/usr/bin/env python3
"""
12월-1월(12-1월) 데이터로 ML 학습용 데이터셋 생성

입력: pattern_data_log/pattern_data_202512*.jsonl, pattern_data_202601*.jsonl
출력: ml_dataset_dec_jan.csv
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import numpy as np
import sys

sys.stdout.reconfigure(encoding='utf-8')

# ml_prepare_dataset.py의 함수들을 임포트
import os
import importlib.util
spec = importlib.util.spec_from_file_location("ml_prepare_dataset",
    os.path.join(os.path.dirname(__file__), "ml_prepare_dataset.py"))
ml_prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ml_prepare)

extract_features_from_pattern = ml_prepare.extract_features_from_pattern


def load_dec_jan_pattern_data(pattern_log_dir: Path) -> List[Dict]:
    """12월, 1월 패턴 로그 파일에서 데이터 로드"""
    all_patterns = []

    # 12월, 1월 파일만 필터링
    jsonl_files = []
    for month in ['202512', '202601']:
        jsonl_files.extend(sorted(pattern_log_dir.glob(f'pattern_data_{month}*.jsonl')))

    print(f"📂 12월-1월 패턴 로그 파일 {len(jsonl_files)}개 발견")

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


def create_ml_dataset_dec_jan(pattern_log_dir: str = 'pattern_data_log',
                                output_file: str = 'ml_dataset_dec_jan.csv'):
    """12월-1월 ML 데이터셋 생성"""
    print("=" * 70)
    print("🤖 12월-1월 ML 학습용 데이터셋 생성")
    print("=" * 70)

    # 패턴 데이터 로드
    pattern_log_path = Path(pattern_log_dir)
    if not pattern_log_path.exists():
        print(f"❌ 패턴 로그 디렉토리를 찾을 수 없습니다: {pattern_log_dir}")
        return

    all_patterns = load_dec_jan_pattern_data(pattern_log_path)

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
    print(f"\n특징(feature) 수: {len(df.columns) - 5}")

    # 월별 통계
    print("\n📅 월별 분포:")
    df['month'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m')
    for month in sorted(df['month'].unique()):
        month_df = df[df['month'] == month]
        win_rate = month_df['label'].mean() * 100
        print(f"   {month}: {len(month_df):3d}건 (승률 {win_rate:.1f}%)")

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
    df.drop('month', axis=1, inplace=True)  # 임시 컬럼 제거
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 데이터셋 저장 완료: {output_file}")
    print(f"   파일 크기: {Path(output_file).stat().st_size / 1024:.1f} KB")

    # 컬럼 목록 출력
    print("\n📋 특징(feature) 컬럼 목록:")
    feature_cols = [col for col in df.columns if col not in ['label', 'profit_rate', 'sell_reason', 'stock_code', 'pattern_id', 'timestamp']]
    for i, col in enumerate(feature_cols, 1):
        is_new = '🆕' if col in [
            'uptrend_volume_std', 'decline_volume_std', 'support_volume_std',
            'uptrend_bullish_ratio', 'decline_depth', 'recovery_rate',
            'breakout_body_ratio', 'uptrend_gain_per_candle',
            'decline_loss_per_candle', 'total_pattern_candles', 'volume_concentration'
        ] else '  '
        print(f"   {is_new} {i:2d}. {col}")

    return df


if __name__ == '__main__':
    df = create_ml_dataset_dec_jan()
