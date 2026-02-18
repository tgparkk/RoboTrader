#!/usr/bin/env python3
"""
일봉 필터 옵션별 시뮬레이션 비교 분석

각 필터 옵션별로:
1. 시뮬레이션 실행 → 일별 거래 분포 확인
2. 적절한 투자 비율 결정 (1/n)
3. 수익금 계산 및 비교
"""

import sys
import re
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from utils.data_cache import DailyDataCache


# 일봉 특징 계산 함수 (analyze_daily_features.py에서 복사)
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

    # 1. 20일 가격 위치
    high_20d = daily_df['stck_hgpr'].max()
    low_20d = daily_df['stck_lwpr'].min()
    last_close = daily_df['stck_clpr'].iloc[-1]

    if high_20d > low_20d:
        features['price_position_20d'] = (last_close - low_20d) / (high_20d - low_20d)
    else:
        features['price_position_20d'] = 0.5

    # 2. 거래량 비율
    if len(daily_df) >= 2:
        vol_ma20 = daily_df['acml_vol'].mean()
        last_vol = daily_df['acml_vol'].iloc[-1]
        if vol_ma20 > 0:
            features['volume_ratio_20d'] = last_vol / vol_ma20
        else:
            features['volume_ratio_20d'] = 1.0

    # 3. 연속 상승일 수
    consecutive_up = 0
    closes = daily_df['stck_clpr'].values
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            consecutive_up += 1
        else:
            break
    features['consecutive_up_days'] = consecutive_up

    # 4. 전일 대비 등락률
    if len(daily_df) >= 2:
        prev_close = daily_df['stck_clpr'].iloc[-2]
        if prev_close > 0:
            features['prev_day_change'] = (last_close - prev_close) / prev_close * 100
        else:
            features['prev_day_change'] = 0

    return features


def parse_replay_log(log_path: Path) -> list:
    """signal_replay_log 파일 파싱하여 거래 정보 추출"""
    trades = []

    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 날짜 추출
    match = re.search(r'replay_(\d{8})_', log_path.name)
    if not match:
        return trades
    trade_date = match.group(1)

    # 매수 라인 파싱
    trade_lines = re.findall(r'[🔴🟢]\s*(\d{6})\(([^)]+)\)\s*(\d{2}:\d{2})\s*매수\s*→\s*([+-]\d+\.?\d*)%', content)

    for stock_code, stock_name, buy_time, profit_str in trade_lines:
        profit_pct = float(profit_str)
        is_win = profit_pct > 0

        trades.append({
            'trade_date': trade_date,
            'stock_code': stock_code,
            'stock_name': stock_name,
            'is_win': is_win,
            'buy_time': buy_time,
            'profit_pct': profit_pct
        })

    return trades


def apply_daily_filter(features: dict, filter_option: str) -> bool:
    """일봉 필터 적용 (True = 통과, False = 차단)"""
    # 'none' 옵션은 일봉 데이터 유무와 관계없이 모두 통과
    if filter_option == 'none':
        return True

    # 다른 필터는 일봉 데이터 필요
    if features is None:
        return False
    elif filter_option == 'prev_day_up':
        return features.get('prev_day_change', -999) >= 0.0
    elif filter_option == 'consecutive_1day':
        return features.get('consecutive_up_days', 0) >= 1
    elif filter_option == 'balanced':
        return (features.get('consecutive_up_days', 0) >= 1 and
                features.get('price_position_20d', 0) >= 0.5)
    elif filter_option == 'consecutive_2days':
        return features.get('consecutive_up_days', 0) >= 2
    elif filter_option == 'volume_surge':
        return features.get('volume_ratio_20d', 0) >= 1.5
    else:
        return True


def analyze_filter_option(log_dir: Path, filter_option: str, daily_cache: DailyDataCache) -> dict:
    """특정 필터 옵션으로 시뮬레이션 분석"""
    print(f"\n{'='*70}")
    print(f"필터 옵션: {filter_option}")
    print(f"{'='*70}")

    # 거래 로드
    all_trades = []
    log_files = sorted(log_dir.glob('signal_*_replay_*.txt'))

    for log_file in log_files:
        trades = parse_replay_log(log_file)
        all_trades.extend(trades)

    # 일봉 데이터와 결합 + 필터 적용
    filtered_trades = []
    daily_trade_count = defaultdict(int)
    daily_max_concurrent = {}

    for trade in all_trades:
        stock_code = trade['stock_code']
        trade_date = trade['trade_date']

        # 일봉 데이터 로드
        daily_df = daily_cache.load_data(stock_code)
        features = calculate_daily_features(daily_df, trade_date)

        # 필터 적용
        if apply_daily_filter(features, filter_option):
            filtered_trades.append(trade)
            daily_trade_count[trade_date] += 1

    # 일별 최대 거래 수 분석
    max_trades_per_day = max(daily_trade_count.values()) if daily_trade_count else 0
    avg_trades_per_day = np.mean(list(daily_trade_count.values())) if daily_trade_count else 0

    # 승률 계산
    total = len(filtered_trades)
    wins = sum(1 for t in filtered_trades if t['is_win'])
    winrate = (wins / total * 100) if total > 0 else 0

    # 수익률 계산
    total_profit = sum(t['profit_pct'] for t in filtered_trades)
    avg_profit = total_profit / total if total > 0 else 0

    result = {
        'filter_option': filter_option,
        'total_trades': total,
        'wins': wins,
        'losses': total - wins,
        'winrate': winrate,
        'total_profit_pct': total_profit,
        'avg_profit_pct': avg_profit,
        'max_trades_per_day': max_trades_per_day,
        'avg_trades_per_day': avg_trades_per_day,
        'trading_days': len(daily_trade_count),
        'daily_trade_count': daily_trade_count,  # 추가
    }

    print(f"총 거래: {total}건")
    print(f"승패: {wins}승 {total-wins}패")
    print(f"승률: {winrate:.1f}%")
    print(f"평균 수익률: {avg_profit:.2f}%")
    print(f"일별 최대 거래: {max_trades_per_day}건")
    print(f"일별 평균 거래: {avg_trades_per_day:.1f}건")

    # 일별 거래 분포 출력
    trade_counts = list(daily_trade_count.values())
    p90 = int(np.percentile(trade_counts, 90)) if trade_counts else 0
    p95 = int(np.percentile(trade_counts, 95)) if trade_counts else 0
    print(f"일별 거래 분포: 평균 {avg_trades_per_day:.1f}, 90%ile {p90}, 95%ile {p95}, 최대 {max_trades_per_day}")

    return result


def calculate_optimal_investment(daily_trade_count: dict, total_profit_pct: float, total_trades: int, total_capital: float = 10000000) -> dict:
    """최적 투자 비율 계산 (분포 기반 + 고정 금액)"""
    trade_counts = list(daily_trade_count.values())

    if not trade_counts:
        return {}

    max_trades = max(trade_counts)
    avg_trades = np.mean(trade_counts)

    # 백분위수 기반 계산
    p90 = int(np.percentile(trade_counts, 90))
    p95 = int(np.percentile(trade_counts, 95))

    # 각 기준별 계산
    results = {}

    # 1. 고정 금액 투자 (기존 시뮬 방식: 매번 200만원, 무제한 자본)
    fixed_investment = 2_000_000  # 건당 200만원 고정
    fixed_profit = total_profit_pct / 100 * fixed_investment
    results['fixed_investment'] = fixed_investment
    results['fixed_profit'] = fixed_profit
    results['fixed_total_required'] = 0  # 고정 금액이므로 총 필요 자본 계산 안 함

    # 2. 고정 1/5 투자 (총 1천만원, 건당 200만원, 최대 5건 동시)
    fixed_5_investment = 2_000_000  # 건당 200만원
    max_concurrent = 5  # 최대 동시 5건

    # 일별 거래수가 5건 초과인 경우를 고려한 실제 거래 가능 수 계산
    actual_trades_count = 0
    actual_profit_pct = 0
    exceed_days_5 = 0

    for date, count in daily_trade_count.items():
        if count > max_concurrent:
            actual_trades_count += max_concurrent
            exceed_days_5 += 1
        else:
            actual_trades_count += count

    # 전체 거래 중 실제 가능한 비율로 수익 계산
    if total_trades > 0:
        trade_ratio = actual_trades_count / total_trades
        actual_profit_pct = total_profit_pct * trade_ratio
    else:
        actual_profit_pct = 0

    fixed_5_profit = actual_profit_pct / 100 * fixed_5_investment
    exceed_rate_5 = exceed_days_5 / len(trade_counts) * 100 if trade_counts else 0

    results['fixed_5_investment'] = fixed_5_investment
    results['fixed_5_profit'] = fixed_5_profit
    results['fixed_5_actual_trades'] = actual_trades_count
    results['fixed_5_exceed_days'] = exceed_days_5
    results['fixed_5_exceed_rate'] = exceed_rate_5
    results['fixed_5_missed_trades'] = total_trades - actual_trades_count

    # 2. 백분위수 기반 분산 투자
    for name, n_trades in [('max', max_trades), ('p95', p95), ('p90', p90)]:
        n = max(int(n_trades * 1.1), 1)  # 10% 안전 마진
        investment_per_trade = total_capital / n
        total_profit_amount = total_profit_pct / 100 * investment_per_trade  # 고정 투자금

        # 초과 거래 발생 일수 (투자금 부족한 날)
        exceed_days = sum(1 for c in trade_counts if c > n_trades)
        exceed_rate = exceed_days / len(trade_counts) * 100 if trade_counts else 0

        results[f'{name}_n'] = n
        results[f'{name}_investment'] = investment_per_trade
        results[f'{name}_profit'] = total_profit_amount
        results[f'{name}_exceed_days'] = exceed_days
        results[f'{name}_exceed_rate'] = exceed_rate

    results['max_trades'] = max_trades
    results['avg_trades'] = avg_trades
    results['p90_trades'] = p90
    results['p95_trades'] = p95

    return results


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("일봉 필터 옵션별 시뮬레이션 비교")
    print("=" * 70)

    # 로그 디렉토리
    log_dir = Path('signal_replay_log_advanced')
    if not log_dir.exists():
        log_dir = Path('signal_replay_log')

    # 일봉 캐시
    daily_cache = DailyDataCache()

    # 총 투자금
    total_capital = 10_000_000  # 1천만원

    # 필터 옵션들
    filter_options = [
        'none',              # 베이스라인
        'prev_day_up',       # 전일 상승
        'consecutive_1day',  # 연속 상승 1일
        'balanced',          # 연속 상승 + 가격위치
        'consecutive_2days', # 연속 상승 2일
        'volume_surge',      # 거래량 급증
    ]

    # 각 옵션별 분석
    results = []
    for option in filter_options:
        result = analyze_filter_option(log_dir, option, daily_cache)
        investment = calculate_optimal_investment(
            result['daily_trade_count'],
            result['total_profit_pct'],
            result['total_trades'],
            total_capital
        )

        # daily_trade_count는 DataFrame에 포함하지 않음
        result_without_dict = {k: v for k, v in result.items() if k != 'daily_trade_count'}
        combined = {**result_without_dict, **investment}
        results.append(combined)

    # 비교 테이블 출력
    print("\n" + "=" * 70)
    print("종합 비교")
    print("=" * 70)

    df = pd.DataFrame(results)

    print("\n### 거래 및 승률 ###")
    print(df[['filter_option', 'total_trades', 'wins', 'losses', 'winrate']].to_string(index=False))

    print("\n### 일별 거래 분포 ###")
    print(df[['filter_option', 'avg_trades', 'p90_trades', 'p95_trades', 'max_trades']].to_string(index=False))

    print("\n### 기존 시뮬 방식 (건당 고정 200만원, 무제한 자본) ###")
    print(df[['filter_option', 'total_trades', 'winrate', 'fixed_investment', 'fixed_profit']].to_string(index=False))

    print("\n### 1천만원 1/5 방식 (건당 200만원, 최대 5건 동시) ###")
    print(df[['filter_option', 'fixed_5_actual_trades', 'fixed_5_missed_trades', 'winrate', 'fixed_5_profit', 'fixed_5_exceed_rate']].to_string(index=False))

    print("\n### 투자 전략 비교 (90 percentile 기준) ###")
    print(df[['filter_option', 'p90_n', 'p90_investment', 'p90_profit', 'p90_exceed_rate']].to_string(index=False))

    print("\n### 투자 전략 비교 (95 percentile 기준) ###")
    print(df[['filter_option', 'p95_n', 'p95_investment', 'p95_profit', 'p95_exceed_rate']].to_string(index=False))

    print("\n### 투자 전략 비교 (max 기준) ###")
    print(df[['filter_option', 'max_n', 'max_investment', 'max_profit', 'max_exceed_rate']].to_string(index=False))

    # 최적 옵션 추천
    print("\n" + "=" * 70)
    print("추천")
    print("=" * 70)

    best_profit_fixed = df.loc[df['fixed_profit'].idxmax()]
    best_profit_fixed_5 = df.loc[df['fixed_5_profit'].idxmax()]
    best_profit_p90 = df.loc[df['p90_profit'].idxmax()]
    best_winrate = df.loc[df['winrate'].idxmax()]

    print(f"\n### 기존 시뮬 방식 (고정 200만원, 무제한 자본) 최고 수익 ###")
    print(f"필터: {best_profit_fixed['filter_option']}")
    print(f"  - 총 수익: {best_profit_fixed['fixed_profit']:,.0f}원")
    print(f"  - 승률: {best_profit_fixed['winrate']:.1f}%")
    print(f"  - 거래: {best_profit_fixed['total_trades']:.0f}건")
    print(f"  - 건당 투자: {best_profit_fixed['fixed_investment']:,.0f}원 (고정)")

    print(f"\n### 1천만원 1/5 방식 (건당 200만원, 최대 5건) 최고 수익 ###")
    print(f"필터: {best_profit_fixed_5['filter_option']}")
    print(f"  - 총 수익: {best_profit_fixed_5['fixed_5_profit']:,.0f}원")
    print(f"  - 승률: {best_profit_fixed_5['winrate']:.1f}%")
    print(f"  - 실제 거래: {best_profit_fixed_5['fixed_5_actual_trades']:.0f}건 (놓친: {best_profit_fixed_5['fixed_5_missed_trades']:.0f}건)")
    print(f"  - 건당 투자: {best_profit_fixed_5['fixed_5_investment']:,.0f}원 (고정, 최대 5건)")
    print(f"  - 초과 발생: {best_profit_fixed_5['fixed_5_exceed_rate']:.1f}% 일수")

    print(f"\n### 금액 비중 조정 (90%ile) 최고 수익 ###")
    print(f"필터: {best_profit_p90['filter_option']}")
    print(f"  - 총 수익: {best_profit_p90['p90_profit']:,.0f}원")
    print(f"  - 승률: {best_profit_p90['winrate']:.1f}%")
    print(f"  - 거래: {best_profit_p90['total_trades']:.0f}건")
    print(f"  - 투자 비율: 1/{best_profit_p90['p90_n']:.0f} ({best_profit_p90['p90_investment']:,.0f}원/거래)")
    print(f"  - 초과 발생: {best_profit_p90['p90_exceed_rate']:.1f}% 일수")
    print(f"  - 고정 금액 대비: {(best_profit_p90['p90_profit'] / best_profit_p90['fixed_profit'] - 1) * 100:+.1f}%")

    print(f"\n### 최고 승률 ###")
    print(f"필터: {best_winrate['filter_option']}")
    print(f"  - 승률: {best_winrate['winrate']:.1f}%")
    print(f"  - 고정 금액 수익: {best_winrate['fixed_profit']:,.0f}원")
    print(f"  - 90%ile 수익: {best_winrate['p90_profit']:,.0f}원")
    print(f"  - 거래: {best_winrate['total_trades']:.0f}건")

    # 결과 저장
    output_file = 'daily_filter_comparison_report.txt'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("일봉 필터 옵션별 비교 분석\n")
        f.write("=" * 50 + "\n\n")
        f.write(df.to_string(index=False))

    print(f"\n상세 결과가 {output_file}에 저장되었습니다.")


if __name__ == '__main__':
    main()
