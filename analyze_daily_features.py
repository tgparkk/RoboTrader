#!/usr/bin/env python3
"""
어드밴스 필터 개선을 위한 일봉 기반 특징 분석

signal_replay_log_advanced의 승/패 거래와 일봉 데이터를 결합하여
일봉 기반 특징을 추출하고 승률 개선에 유효한 필터 조건을 발굴합니다.
"""

import sys
import re
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from utils.data_cache import DailyDataCache


def parse_replay_log(log_path: Path) -> list:
    """signal_replay_log 파일 파싱하여 거래 정보 추출"""
    trades = []

    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 날짜 추출 (파일명에서)
    # signal_new2_replay_YYYYMMDD_9_00_0.txt
    match = re.search(r'replay_(\d{8})_', log_path.name)
    if not match:
        return trades
    trade_date = match.group(1)

    # 종목별 블록 찾기
    stock_blocks = re.split(r'\n={20,}\n', content)

    for block in stock_blocks:
        # 종목코드와 이름 추출
        stock_match = re.search(r'📊 (\d{6})\s*\(([^)]+)\)', block)
        if not stock_match:
            continue

        stock_code = stock_match.group(1)
        stock_name = stock_match.group(2)

        # 승패 결과 추출
        result_match = re.search(r'결과:\s*(승리|손실)', block)
        if not result_match:
            continue

        is_win = result_match.group(1) == '승리'

        # 매수 시간 추출
        buy_match = re.search(r'매수.*?(\d{2}:\d{2})', block)
        buy_time = buy_match.group(1) if buy_match else None

        # 수익률 추출
        profit_match = re.search(r'수익률:\s*([+-]?\d+\.?\d*)%', block)
        profit_pct = float(profit_match.group(1)) if profit_match else 0

        trades.append({
            'trade_date': trade_date,
            'stock_code': stock_code,
            'stock_name': stock_name,
            'is_win': is_win,
            'buy_time': buy_time,
            'profit_pct': profit_pct
        })

    return trades


def load_all_trades(log_dir: Path) -> pd.DataFrame:
    """모든 리플레이 로그에서 거래 정보 로드"""
    all_trades = []

    log_files = sorted(log_dir.glob('signal_*_replay_*.txt'))
    print(f"로그 파일 {len(log_files)}개 발견")

    for log_file in log_files:
        trades = parse_replay_log(log_file)
        all_trades.extend(trades)

    df = pd.DataFrame(all_trades)
    print(f"총 {len(df)}건 거래 로드")
    return df


def calculate_daily_features(daily_df: pd.DataFrame, trade_date: str) -> dict:
    """일봉 데이터에서 특징 추출 (거래일 기준 과거 20일)"""
    if daily_df is None or daily_df.empty:
        return None

    # 숫자 변환
    daily_df = daily_df.copy()
    for col in ['stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'acml_vol']:
        daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce')

    # 거래일 이전 데이터만 (당일 제외)
    daily_df = daily_df[daily_df['stck_bsop_date'] < trade_date].copy()
    daily_df = daily_df.sort_values('stck_bsop_date').tail(20)

    if len(daily_df) < 5:
        return None

    features = {}

    # 1. 20일 가격 위치 (현재가가 20일 범위 내 어디인지)
    high_20d = daily_df['stck_hgpr'].max()
    low_20d = daily_df['stck_lwpr'].min()
    last_close = daily_df['stck_clpr'].iloc[-1]

    if high_20d > low_20d:
        features['price_position_20d'] = (last_close - low_20d) / (high_20d - low_20d)
    else:
        features['price_position_20d'] = 0.5

    # 2. 5일 추세 (선형회귀 기울기)
    if len(daily_df) >= 5:
        recent_5 = daily_df['stck_clpr'].tail(5).values
        x = np.arange(5)
        if np.std(recent_5) > 0:
            slope = np.polyfit(x, recent_5, 1)[0]
            features['trend_5d'] = slope / recent_5.mean() * 100  # 백분율로 정규화
        else:
            features['trend_5d'] = 0

    # 3. 이동평균선 관계
    if len(daily_df) >= 20:
        ma5 = daily_df['stck_clpr'].tail(5).mean()
        ma10 = daily_df['stck_clpr'].tail(10).mean()
        ma20 = daily_df['stck_clpr'].tail(20).mean()

        features['ma5_above_ma10'] = 1 if ma5 > ma10 else 0
        features['ma5_above_ma20'] = 1 if ma5 > ma20 else 0
        features['ma10_above_ma20'] = 1 if ma10 > ma20 else 0

        # 골든크로스 점수 (0~3)
        features['ma_alignment'] = features['ma5_above_ma10'] + features['ma5_above_ma20'] + features['ma10_above_ma20']

    # 4. 거래량 비율 (전일 거래량 / 20일 평균)
    if len(daily_df) >= 2:
        vol_ma20 = daily_df['acml_vol'].mean()
        last_vol = daily_df['acml_vol'].iloc[-1]
        if vol_ma20 > 0:
            features['volume_ratio_20d'] = last_vol / vol_ma20
        else:
            features['volume_ratio_20d'] = 1.0

    # 5. 연속 상승일 수
    consecutive_up = 0
    closes = daily_df['stck_clpr'].values
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            consecutive_up += 1
        else:
            break
    features['consecutive_up_days'] = consecutive_up

    # 6. 20일 변동성 (일중 변동폭 평균)
    daily_df['daily_range'] = (daily_df['stck_hgpr'] - daily_df['stck_lwpr']) / daily_df['stck_lwpr'] * 100
    features['volatility_20d'] = daily_df['daily_range'].mean()

    # 7. 전일 대비 등락률
    if len(daily_df) >= 2:
        prev_close = daily_df['stck_clpr'].iloc[-2]
        if prev_close > 0:
            features['prev_day_change'] = (last_close - prev_close) / prev_close * 100
        else:
            features['prev_day_change'] = 0

    return features


def analyze_feature_impact(trades_df: pd.DataFrame, feature_name: str, thresholds: list) -> pd.DataFrame:
    """특정 특징의 임계값별 승률 분석"""
    results = []

    for threshold in thresholds:
        # 임계값 이상/이하 그룹 분리
        above = trades_df[trades_df[feature_name] >= threshold]
        below = trades_df[trades_df[feature_name] < threshold]

        if len(above) >= 10:  # 최소 샘플 수
            above_winrate = above['is_win'].mean() * 100
            results.append({
                'threshold': f'>= {threshold}',
                'count': len(above),
                'winrate': above_winrate,
                'avg_profit': above['profit_pct'].mean()
            })

        if len(below) >= 10:
            below_winrate = below['is_win'].mean() * 100
            results.append({
                'threshold': f'< {threshold}',
                'count': len(below),
                'winrate': below_winrate,
                'avg_profit': below['profit_pct'].mean()
            })

    return pd.DataFrame(results)


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("어드밴스 필터 개선: 일봉 기반 특징 분석")
    print("=" * 70)

    # 1. 거래 데이터 로드
    print("\n[1/4] 거래 데이터 로드 중...")

    # signal_replay_log_advanced 또는 signal_replay_log 사용
    log_dir = Path('signal_replay_log_advanced')
    if not log_dir.exists():
        log_dir = Path('signal_replay_log')

    trades_df = load_all_trades(log_dir)

    if trades_df.empty:
        print("거래 데이터가 없습니다.")
        return

    print(f"기본 승률: {trades_df['is_win'].mean() * 100:.1f}% ({len(trades_df)}건)")

    # 2. 일봉 데이터 결합
    print("\n[2/4] 일봉 데이터 결합 중...")
    daily_cache = DailyDataCache()

    feature_data = []
    missing_count = 0

    for idx, row in trades_df.iterrows():
        stock_code = row['stock_code']
        trade_date = row['trade_date']

        # 일봉 데이터 로드
        daily_df = daily_cache.load_data(stock_code)

        # 특징 추출
        features = calculate_daily_features(daily_df, trade_date)

        if features:
            features['stock_code'] = stock_code
            features['trade_date'] = trade_date
            features['is_win'] = row['is_win']
            features['profit_pct'] = row['profit_pct']
            feature_data.append(features)
        else:
            missing_count += 1

    print(f"특징 추출 완료: {len(feature_data)}건 (일봉 누락: {missing_count}건)")

    if not feature_data:
        print("분석할 데이터가 없습니다.")
        return

    features_df = pd.DataFrame(feature_data)

    # 3. 특징별 승률 분석
    print("\n[3/4] 특징별 승률 분석 중...")
    print("=" * 70)

    base_winrate = features_df['is_win'].mean() * 100
    print(f"\n기준 승률: {base_winrate:.1f}% ({len(features_df)}건)\n")

    # 분석할 특징과 임계값
    feature_thresholds = {
        'price_position_20d': [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        'trend_5d': [-2, -1, 0, 1, 2],
        'ma_alignment': [0, 1, 2, 3],
        'volume_ratio_20d': [0.5, 0.8, 1.0, 1.5, 2.0],
        'consecutive_up_days': [0, 1, 2, 3, 4],
        'volatility_20d': [2, 3, 4, 5, 6],
        'prev_day_change': [-2, -1, 0, 1, 2, 3],
    }

    all_results = {}

    for feature_name, thresholds in feature_thresholds.items():
        if feature_name not in features_df.columns:
            continue

        print(f"\n### {feature_name} ###")

        # 기본 통계
        print(f"평균: {features_df[feature_name].mean():.2f}, "
              f"중앙값: {features_df[feature_name].median():.2f}, "
              f"표준편차: {features_df[feature_name].std():.2f}")

        # 임계값별 분석
        for threshold in thresholds:
            above = features_df[features_df[feature_name] >= threshold]
            below = features_df[features_df[feature_name] < threshold]

            if len(above) >= 20:
                above_winrate = above['is_win'].mean() * 100
                diff = above_winrate - base_winrate
                marker = "✓" if diff > 3 else ("✗" if diff < -3 else " ")
                print(f"  >= {threshold:5.1f}: {above_winrate:5.1f}% ({len(above):3d}건) {diff:+5.1f}%p {marker}")

        all_results[feature_name] = features_df[feature_name].describe()

    # 4. 유효한 필터 조건 추천
    print("\n" + "=" * 70)
    print("[4/4] 추천 필터 조건")
    print("=" * 70)

    # 복합 필터 테스트
    print("\n### 복합 필터 테스트 ###")

    # 조건 1: 가격위치 >= 60% AND 이평선 정배열 >= 2
    if 'price_position_20d' in features_df.columns and 'ma_alignment' in features_df.columns:
        filtered = features_df[
            (features_df['price_position_20d'] >= 0.6) &
            (features_df['ma_alignment'] >= 2)
        ]
        if len(filtered) >= 10:
            winrate = filtered['is_win'].mean() * 100
            print(f"가격위치>=60% & 이평선>=2: {winrate:.1f}% ({len(filtered)}건) {winrate - base_winrate:+.1f}%p")

    # 조건 2: 5일 추세 상승 AND 거래량 비율 >= 1.0
    if 'trend_5d' in features_df.columns and 'volume_ratio_20d' in features_df.columns:
        filtered = features_df[
            (features_df['trend_5d'] > 0) &
            (features_df['volume_ratio_20d'] >= 1.0)
        ]
        if len(filtered) >= 10:
            winrate = filtered['is_win'].mean() * 100
            print(f"추세상승 & 거래량>=1.0: {winrate:.1f}% ({len(filtered)}건) {winrate - base_winrate:+.1f}%p")

    # 조건 3: 연속 상승 >= 1 AND 가격위치 >= 50%
    if 'consecutive_up_days' in features_df.columns and 'price_position_20d' in features_df.columns:
        filtered = features_df[
            (features_df['consecutive_up_days'] >= 1) &
            (features_df['price_position_20d'] >= 0.5)
        ]
        if len(filtered) >= 10:
            winrate = filtered['is_win'].mean() * 100
            print(f"연속상승>=1 & 가격위치>=50%: {winrate:.1f}% ({len(filtered)}건) {winrate - base_winrate:+.1f}%p")

    # 조건 4: 전일 상승 AND 이평선 정배열 >= 2
    if 'prev_day_change' in features_df.columns and 'ma_alignment' in features_df.columns:
        filtered = features_df[
            (features_df['prev_day_change'] > 0) &
            (features_df['ma_alignment'] >= 2)
        ]
        if len(filtered) >= 10:
            winrate = filtered['is_win'].mean() * 100
            print(f"전일상승 & 이평선>=2: {winrate:.1f}% ({len(filtered)}건) {winrate - base_winrate:+.1f}%p")

    # 5. 결과 저장
    output_file = 'daily_features_analysis_report.txt'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("일봉 기반 특징 분석 결과\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"분석 대상: {len(features_df)}건\n")
        f.write(f"기준 승률: {base_winrate:.1f}%\n\n")

        for feature_name, stats in all_results.items():
            f.write(f"\n{feature_name}:\n")
            f.write(str(stats) + "\n")

    print(f"\n분석 결과가 {output_file}에 저장되었습니다.")


if __name__ == '__main__':
    main()
