#!/usr/bin/env python3
"""
test_results 폴더의 동적 손익비 시뮬레이션 결과를 ML 학습 데이터셋으로 변환

입력: test_results/signal_new2_replay_*.txt (동적 손익비 적용된 시뮬)
출력: ml_dataset_dynamic_pl.csv (학습용 피처 + 라벨)

사용법:
    python prepare_ml_from_test_results.py
"""

import re
import os
import json
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Optional


# 설정
TEST_RESULTS_DIR = "test_results"
PATTERN_LOG_DIR = "pattern_data_log"
CACHE_DIR = "cache/minute_data"
OUTPUT_FILE = "ml_dataset_dynamic_pl.csv"


def parse_trade_line(line: str) -> Optional[Dict]:
    """
    거래 결과 라인 파싱
    예: 🟢 000390(삼화페인트) 09:33 매수 → +7.00%
    """
    # 승리 패턴 (🟢)
    win_match = re.search(r'🟢\s+(\d+)\((.+?)\)\s+(\d{2}:\d{2})\s+매수\s+→\s+\+?([\d.]+)%', line)
    if win_match:
        return {
            'stock_code': win_match.group(1),
            'stock_name': win_match.group(2),
            'buy_time': win_match.group(3),
            'profit_rate': float(win_match.group(4)),
            'result': 'win'
        }

    # 손실 패턴 (🔴)
    loss_match = re.search(r'🔴\s+(\d+)\((.+?)\)\s+(\d{2}:\d{2})\s+매수\s+→\s+([+-]?[\d.]+)%', line)
    if loss_match:
        return {
            'stock_code': loss_match.group(1),
            'stock_name': loss_match.group(2),
            'buy_time': loss_match.group(3),
            'profit_rate': float(loss_match.group(4)),
            'result': 'loss'
        }

    return None


def parse_simulation_file(file_path: str) -> List[Dict]:
    """시뮬레이션 파일에서 모든 거래 결과 추출"""
    date_match = re.search(r'signal_new2_replay_(\d{8})_', file_path)
    if not date_match:
        return []

    trade_date = date_match.group(1)
    trades = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                trade = parse_trade_line(line)
                if trade:
                    trade['date'] = trade_date
                    trades.append(trade)
    except Exception as e:
        print(f"파일 파싱 오류 {file_path}: {e}")
        return []

    return trades


def load_pattern_data(stock_code: str, trade_date: str, signal_time: str) -> Optional[Dict]:
    """
    pattern_data_log에서 해당 거래의 패턴 정보 로드

    Args:
        stock_code: 종목코드
        trade_date: YYYYMMDD
        signal_time: HH:MM
    """
    pattern_file = os.path.join(PATTERN_LOG_DIR, f"pattern_data_{trade_date}.jsonl")

    if not os.path.exists(pattern_file):
        return None

    try:
        # UTF-8 실패 시 CP949로 재시도
        encodings = ['utf-8', 'cp949', 'utf-8-sig']

        for encoding in encodings:
            try:
                with open(pattern_file, 'r', encoding=encoding) as f:
                    for line in f:
                        if line.strip():
                            try:
                                pattern = json.loads(line)
                                if pattern.get('stock_code') == stock_code:
                                    # 신호 시간 매칭 (YYYY-MM-DD HH:MM:SS 형식에서 HH:MM만 추출)
                                    pattern_signal_time = pattern.get('signal_time', '')
                                    # "2025-12-22 09:33:00" → "09:33"와 매칭
                                    if len(pattern_signal_time) >= 16:
                                        time_part = pattern_signal_time[11:16]  # "09:33"
                                        if time_part == signal_time:
                                            return pattern
                            except json.JSONDecodeError:
                                continue
                break  # 성공하면 루프 종료
            except UnicodeDecodeError:
                continue  # 다음 인코딩 시도

    except Exception as e:
        print(f"패턴 로그 로드 오류 {pattern_file}: {e}")

    return None


def extract_features_from_pattern(pattern_stages: Dict, signal_info: Dict) -> Dict:
    """패턴 4단계 정보에서 ML 피처 추출"""
    features = {}

    def safe_float(value, default=0.0):
        """안전한 float 변환"""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value.replace('%', '').replace(',', ''))
        return default

    # 1단계: 상승구간
    uptrend = pattern_stages.get('1_uptrend', {})
    features['uptrend_candles'] = uptrend.get('candle_count', 0)
    features['uptrend_gain'] = safe_float(uptrend.get('price_gain', 0))
    features['uptrend_max_volume'] = safe_float(uptrend.get('max_volume', 0))
    features['uptrend_avg_volume'] = safe_float(uptrend.get('volume_avg', 0))

    # 2단계: 하락구간
    decline = pattern_stages.get('2_decline', {})
    features['decline_candles'] = decline.get('candle_count', 0)
    features['decline_pct'] = safe_float(decline.get('decline_pct', 0))
    features['decline_avg_volume'] = safe_float(decline.get('avg_volume', 0))

    # 3단계: 지지구간
    support = pattern_stages.get('3_support', {})
    features['support_candles'] = support.get('candle_count', 0)
    features['support_avg_volume'] = safe_float(support.get('avg_volume', 0))
    features['support_volatility'] = safe_float(support.get('price_volatility', 0))

    # 4단계: 돌파양봉
    breakout = pattern_stages.get('4_breakout', {})
    breakout_candle = breakout.get('candle', {})
    features['breakout_volume'] = safe_float(breakout_candle.get('volume', 0))
    features['breakout_close'] = safe_float(breakout_candle.get('close', 0))

    # === 거래량 비율 특징 (핵심) ===
    if features['uptrend_max_volume'] > 0:
        # 지지 거래량 비율 (상승 최대 거래량 대비)
        features['support_volume_ratio'] = features['support_avg_volume'] / features['uptrend_max_volume']
    else:
        features['support_volume_ratio'] = 0

    if features['uptrend_avg_volume'] > 0:
        # 하락 시 거래량 비율 (상승 평균 거래량 대비)
        features['decline_volume_ratio'] = features['decline_avg_volume'] / features['uptrend_avg_volume']
    else:
        features['decline_volume_ratio'] = 0

    # === 패턴 분류 (동적 손익비 시스템과 동일) ===
    # 지지 거래량 분류
    if features['support_volume_ratio'] < 0.15:
        features['support_volume_class'] = 'very_low'
    elif features['support_volume_ratio'] < 0.25:
        features['support_volume_class'] = 'low'
    elif features['support_volume_ratio'] < 0.50:
        features['support_volume_class'] = 'normal'
    else:
        features['support_volume_class'] = 'high'

    # 하락 거래량 분류
    if features['decline_volume_ratio'] < 0.3:
        features['decline_volume_class'] = 'strong_decrease'
    elif features['decline_volume_ratio'] < 0.6:
        features['decline_volume_class'] = 'normal_decrease'
    else:
        features['decline_volume_class'] = 'weak_decrease'

    # 신호 정보
    features['confidence'] = signal_info.get('confidence', 0)

    return features


def process_all_simulations():
    """모든 시뮬레이션 파일 처리"""
    all_data = []

    # test_results 폴더의 모든 시뮬 파일
    sim_files = sorted(Path(TEST_RESULTS_DIR).glob("signal_new2_replay_*.txt"))

    print(f"총 {len(sim_files)}개 시뮬레이션 파일 발견")

    for sim_file in sim_files:
        print(f"\n처리 중: {sim_file.name}")

        # 거래 결과 파싱
        trades = parse_simulation_file(str(sim_file))
        print(f"  - {len(trades)}건 거래 발견")

        # 각 거래에 대해 패턴 정보 매칭
        matched = 0
        for trade in trades:
            # 패턴 데이터 로드
            pattern = load_pattern_data(
                trade['stock_code'],
                trade['date'],
                trade['buy_time']
            )

            if pattern is None:
                continue

            # 패턴 특징 추출
            pattern_stages = pattern.get('pattern_stages', {})
            signal_info = pattern.get('signal_info', {})

            features = extract_features_from_pattern(pattern_stages, signal_info)

            # 라벨 추가
            features['label'] = 1 if trade['result'] == 'win' else 0
            features['profit_rate'] = trade['profit_rate']
            features['stock_code'] = trade['stock_code']
            features['stock_name'] = trade['stock_name']
            features['date'] = trade['date']
            features['buy_time'] = trade['buy_time']

            # 시간 특징
            hour, minute = map(int, trade['buy_time'].split(':'))
            features['hour'] = hour
            features['minute'] = minute
            features['time_in_minutes'] = hour * 60 + minute
            features['is_morning'] = 1 if hour < 12 else 0

            all_data.append(features)
            matched += 1

        print(f"  - {matched}건 패턴 매칭 성공")

    return pd.DataFrame(all_data)


def main():
    print("=" * 80)
    print("test_results --> ML 데이터셋 변환 시작")
    print("=" * 80)

    # 데이터 처리
    df = process_all_simulations()

    if len(df) == 0:
        print("\n[경고] 데이터가 없습니다!")
        return

    # 데이터 저장
    df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
    print(f"\n[완료] ML 데이터셋 저장 완료: {OUTPUT_FILE}")
    print(f"   총 {len(df)}건 (승리 {df['label'].sum()}건, 패배 {len(df) - df['label'].sum()}건)")

    # 통계 출력
    print("\n" + "=" * 80)
    print("[통계] 데이터셋 통계")
    print("=" * 80)

    print(f"\n총 거래 건수: {len(df)}")
    print(f"  - 승리: {df['label'].sum()}건 ({df['label'].mean()*100:.1f}%)")
    print(f"  - 패배: {len(df) - df['label'].sum()}건 ({(1-df['label'].mean())*100:.1f}%)")

    print(f"\n평균 수익률: {df['profit_rate'].mean():.2f}%")
    print(f"  - 승리 시: {df[df['label']==1]['profit_rate'].mean():.2f}%")
    print(f"  - 패배 시: {df[df['label']==0]['profit_rate'].mean():.2f}%")

    # 패턴 조합별 통계
    print("\n=== 패턴 조합별 승률 ===")
    pattern_stats = df.groupby(['support_volume_class', 'decline_volume_class']).agg({
        'label': ['count', 'mean', 'sum'],
        'profit_rate': 'mean'
    }).round(2)
    pattern_stats.columns = ['count', 'win_rate', 'win_count', 'avg_profit']
    pattern_stats['win_rate'] = (pattern_stats['win_rate'] * 100).round(1)
    print(pattern_stats.to_string())

    # 시간대별 통계
    print("\n=== 시간대별 승률 ===")
    time_stats = df.groupby('hour').agg({
        'label': ['count', 'mean'],
        'profit_rate': 'mean'
    }).round(2)
    time_stats.columns = ['count', 'win_rate', 'avg_profit']
    time_stats['win_rate'] = (time_stats['win_rate'] * 100).round(1)
    print(time_stats.to_string())

    print("\n" + "=" * 80)
    print(f"[완료] ML 모델 학습에 {OUTPUT_FILE}를 사용하세요.")
    print("=" * 80)


if __name__ == "__main__":
    main()
