#!/usr/bin/env python3
"""
signal_replay_log 폴더의 고정 손익비 시뮬레이션 결과를 ML 학습 데이터셋으로 변환

입력: signal_replay_log/signal_new2_replay_*.txt (고정 3.5:2.5 손익비 시뮬)
출력: ml_dataset_fixed.csv (학습용 피처 + 라벨)

사용법:
    python prepare_ml_dataset_fixed.py
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
TEST_RESULTS_DIR = "signal_replay_log"  # 고정 손익비 시뮬 결과
PATTERN_LOG_DIR = "pattern_data_log"  # 고정 손익비 패턴 로그
CACHE_DIR = "cache/minute_data"
OUTPUT_FILE = "ml_dataset_fixed.csv"


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
    """패턴 4단계 정보에서 ML 피처 추출 + 동적 손익비 목표값 추가"""
    from config.dynamic_profit_loss_config import DynamicProfitLossConfig

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

    def calculate_avg_body_pct(candles: list) -> float:
        """캔들 리스트에서 평균 몸통 크기 계산"""
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

    # 1단계: 상승구간
    uptrend = pattern_stages.get('1_uptrend', {})
    uptrend_candles_list = uptrend.get('candles', [])
    features['uptrend_candles'] = uptrend.get('candle_count', len(uptrend_candles_list))
    features['uptrend_gain'] = safe_float(uptrend.get('price_gain', 0))
    features['uptrend_max_volume'] = safe_float(uptrend.get('max_volume', 0))

    # uptrend_avg_body: 평균 몸통 크기 (기존 모델 특성)
    features['uptrend_avg_body'] = calculate_avg_body_pct(uptrend_candles_list)

    # uptrend_total_volume: 총 거래량 (기존 모델 특성)
    total_volume = uptrend.get('total_volume')
    if total_volume is None:
        total_volume = sum(c.get('volume', 0) for c in uptrend_candles_list)
    features['uptrend_total_volume'] = safe_float(total_volume)

    # 2단계: 하락구간
    decline = pattern_stages.get('2_decline', {})
    features['decline_candles'] = decline.get('candle_count', 0)
    features['decline_pct'] = safe_float(decline.get('decline_pct', 0))
    features['decline_avg_volume'] = safe_float(decline.get('avg_volume', 0))

    # 3단계: 지지구간
    support = pattern_stages.get('3_support', {})
    features['support_candles'] = support.get('candle_count', 0)
    features['support_volatility'] = safe_float(support.get('price_volatility', 0))
    features['support_avg_volume_ratio'] = safe_float(support.get('avg_volume_ratio', 1.0))
    features['support_avg_volume'] = safe_float(support.get('avg_volume', 0))

    # 4단계: 돌파양봉
    breakout = pattern_stages.get('4_breakout', {})
    breakout_candle = breakout.get('candle', {})
    features['breakout_volume'] = safe_float(breakout_candle.get('volume', 0))

    # breakout_body: 몸통 크기 퍼센트 (기존 모델 특성)
    open_p = breakout_candle.get('open', 0)
    close_p = breakout_candle.get('close', 0)
    if open_p > 0:
        features['breakout_body'] = abs((close_p - open_p) / open_p * 100)
    else:
        features['breakout_body'] = 0.0

    # breakout_range: 범위 크기 (기존 모델 특성)
    high_p = breakout_candle.get('high', 0)
    low_p = breakout_candle.get('low', 0)
    if low_p > 0:
        features['breakout_range'] = (high_p - low_p) / low_p * 100
    else:
        features['breakout_range'] = 0.0

    # === 비율 특성 계산 (기존 모델과 동일한 5개) ===
    volume_ratio_decline_to_uptrend = (
        features['decline_avg_volume'] / features['uptrend_max_volume']
        if features['uptrend_max_volume'] > 0 else 0
    )
    volume_ratio_support_to_uptrend = (
        features['support_avg_volume'] / features['uptrend_max_volume']
        if features['uptrend_max_volume'] > 0 else 0
    )
    volume_ratio_breakout_to_uptrend = (
        features['breakout_volume'] / features['uptrend_max_volume']
        if features['uptrend_max_volume'] > 0 else 0
    )
    price_gain_to_decline_ratio = (
        features['uptrend_gain'] / features['decline_pct']
        if features['decline_pct'] > 0 else 0
    )
    candle_ratio_support_to_decline = (
        features['support_candles'] / features['decline_candles']
        if features['decline_candles'] > 0 else 0
    )

    features['volume_ratio_decline_to_uptrend'] = volume_ratio_decline_to_uptrend
    features['volume_ratio_support_to_uptrend'] = volume_ratio_support_to_uptrend
    features['volume_ratio_breakout_to_uptrend'] = volume_ratio_breakout_to_uptrend
    features['price_gain_to_decline_ratio'] = price_gain_to_decline_ratio
    features['candle_ratio_support_to_decline'] = candle_ratio_support_to_decline

    # 신호 정보
    signal_type = signal_info.get('signal_type', 'STRONG_BUY')
    features['signal_type'] = signal_type  # LabelEncoding은 학습 시 처리
    features['confidence'] = signal_info.get('confidence', 0)

    # 고정 손익비 모드에서는 target_stop_loss, target_take_profit 불필요
    # (항상 고정값 3.5:2.5 사용)

    return features


def process_all_simulations():
    """모든 시뮬레이션 파일 처리"""
    all_data = []

    # 동적 손익비 시뮬 결과만 사용
    sim_files = sorted(Path(TEST_RESULTS_DIR).glob("signal_new2_replay_*.txt"))
    print(f"{TEST_RESULTS_DIR}: {len(sim_files)}개 파일")
    print(f"\n총 {len(sim_files)}개 시뮬레이션 파일 발견")

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
