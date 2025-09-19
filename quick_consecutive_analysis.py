"""
빠른 연속 신호 패턴 분석
"""

import re
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from collections import defaultdict

def extract_signals():
    """신호 추출"""
    signal_log_dir = Path("signal_replay_log")
    all_signals = []

    for log_file in sorted(signal_log_dir.glob("signal_new2_replay_*.txt")):
        print(f"Processing {log_file.name}")

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 날짜 추출
            date_match = re.search(r'(\d{8})', log_file.name)
            if not date_match:
                continue
            trade_date = date_match.group(1)

            # 각 종목별 신호 추출
            stock_sections = re.split(r'=== (\d{6}) - \d{8}', content)[1:]

            for i in range(0, len(stock_sections), 2):
                if i + 1 >= len(stock_sections):
                    break

                stock_code = stock_sections[i]
                section_content = stock_sections[i + 1]

                # 체결 결과 추출
                simulation_matches = re.findall(
                    r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([0-9,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([0-9,]+) \(([+-]\d+\.\d+)%\)',
                    section_content
                )

                for match in simulation_matches:
                    buy_time, signal_type, buy_price_str, sell_time, sell_reason, sell_price_str, return_pct_str = match

                    signal = {
                        'stock_code': stock_code,
                        'date': trade_date,
                        'signal_time': buy_time,
                        'return_pct': float(return_pct_str),
                        'is_win': float(return_pct_str) > 0,
                        'datetime': f"{trade_date} {buy_time}"
                    }

                    all_signals.append(signal)

        except Exception as e:
            print(f"Error processing {log_file.name}: {e}")
            continue

    return all_signals

def analyze_signal_order():
    """신호 순서별 분석"""
    signals = extract_signals()
    print(f"총 {len(signals)}개 신호 추출")

    # 종목별로 그룹화하고 시간순 정렬
    stock_signals = defaultdict(list)
    for signal in signals:
        stock_signals[signal['stock_code']].append(signal)

    # 각 종목별로 시간순 정렬하고 순서 부여
    for stock_code in stock_signals:
        stock_signals[stock_code].sort(key=lambda x: x['datetime'])
        for i, signal in enumerate(stock_signals[stock_code]):
            signal['order'] = i + 1

    # 순서별 통계
    order_stats = defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []})

    for signals_list in stock_signals.values():
        for signal in signals_list:
            order = min(signal['order'], 6)  # 6번째 이후는 6+로 그룹화
            order_key = f"{order}번째" if order <= 5 else "6번째+"

            order_stats[order_key]['total'] += 1
            if signal['is_win']:
                order_stats[order_key]['wins'] += 1
            order_stats[order_key]['returns'].append(signal['return_pct'])

    print("\n=== 신호 순서별 승률 ===")
    for order in sorted(order_stats.keys()):
        stats = order_stats[order]
        win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
        avg_return = np.mean(stats['returns']) if stats['returns'] else 0

        print(f"{order:8}: 승률 {win_rate:5.1f}% ({stats['wins']:3}/{stats['total']:3}) "
              f"평균수익률 {avg_return:6.2f}%")

    return order_stats

def analyze_consecutive_patterns():
    """연속 승패 패턴 분석"""
    signals = extract_signals()

    # 종목별로 그룹화하고 시간순 정렬
    stock_signals = defaultdict(list)
    for signal in signals:
        stock_signals[signal['stock_code']].append(signal)

    for stock_code in stock_signals:
        stock_signals[stock_code].sort(key=lambda x: x['datetime'])

    # 연속 패턴 분석
    pattern_stats = {
        'after_wins': defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []}),
        'after_losses': defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []})
    }

    for signals_list in stock_signals.values():
        if len(signals_list) < 2:
            continue

        consecutive_wins = 0
        consecutive_losses = 0

        for i, signal in enumerate(signals_list):
            if signal['is_win']:
                consecutive_wins += 1
                consecutive_losses = 0
            else:
                consecutive_losses += 1
                consecutive_wins = 0

            # 다음 신호가 있다면 분석
            if i + 1 < len(signals_list):
                next_signal = signals_list[i + 1]

                # 연속 승리 후
                if consecutive_wins > 0:
                    win_key = f"{min(consecutive_wins, 3)}연승후"
                    pattern_stats['after_wins'][win_key]['total'] += 1
                    if next_signal['is_win']:
                        pattern_stats['after_wins'][win_key]['wins'] += 1
                    pattern_stats['after_wins'][win_key]['returns'].append(next_signal['return_pct'])

                # 연속 패배 후
                if consecutive_losses > 0:
                    loss_key = f"{min(consecutive_losses, 3)}연패후"
                    pattern_stats['after_losses'][loss_key]['total'] += 1
                    if next_signal['is_win']:
                        pattern_stats['after_losses'][loss_key]['wins'] += 1
                    pattern_stats['after_losses'][loss_key]['returns'].append(next_signal['return_pct'])

    print("\n=== 연속 승리 후 다음 신호 승률 ===")
    for pattern in sorted(pattern_stats['after_wins'].keys()):
        stats = pattern_stats['after_wins'][pattern]
        win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
        avg_return = np.mean(stats['returns']) if stats['returns'] else 0

        print(f"{pattern:8}: 승률 {win_rate:5.1f}% ({stats['wins']:3}/{stats['total']:3}) "
              f"평균수익률 {avg_return:6.2f}%")

    print("\n=== 연속 패배 후 다음 신호 승률 ===")
    for pattern in sorted(pattern_stats['after_losses'].keys()):
        stats = pattern_stats['after_losses'][pattern]
        win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
        avg_return = np.mean(stats['returns']) if stats['returns'] else 0

        print(f"{pattern:8}: 승률 {win_rate:5.1f}% ({stats['wins']:3}/{stats['total']:3}) "
              f"평균수익률 {avg_return:6.2f}%")

def analyze_same_day_signals():
    """같은 날 여러 신호 분석"""
    signals = extract_signals()

    # 날짜별 신호 개수 분석
    daily_signals = defaultdict(list)
    for signal in signals:
        daily_signals[signal['date']].append(signal)

    # 같은 날 신호 개수별 승률
    signal_count_stats = defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []})

    for date, day_signals in daily_signals.items():
        signal_count = len(day_signals)
        count_key = f"{min(signal_count, 10)}개" if signal_count <= 10 else "10개+"

        for signal in day_signals:
            signal_count_stats[count_key]['total'] += 1
            if signal['is_win']:
                signal_count_stats[count_key]['wins'] += 1
            signal_count_stats[count_key]['returns'].append(signal['return_pct'])

    print("\n=== 하루 신호 개수별 승률 ===")
    for count in sorted(signal_count_stats.keys(), key=lambda x: int(x[0])):
        stats = signal_count_stats[count]
        win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
        avg_return = np.mean(stats['returns']) if stats['returns'] else 0

        print(f"하루{count:4}: 승률 {win_rate:5.1f}% ({stats['wins']:3}/{stats['total']:3}) "
              f"평균수익률 {avg_return:6.2f}%")

def main():
    print("연속 신호 패턴 분석 시작...")

    # 1. 신호 순서별 분석
    analyze_signal_order()

    # 2. 연속 승패 패턴 분석
    analyze_consecutive_patterns()

    # 3. 같은 날 신호 개수별 분석
    analyze_same_day_signals()

    print("\n분석 완료!")

if __name__ == "__main__":
    main()