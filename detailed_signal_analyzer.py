#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
from collections import defaultdict

def analyze_detailed_differences():
    """두 폴더 간 상세한 차이점 분석"""

    prev_folder = r"D:\GIT\RoboTrader\signal_replay_log_prev"
    current_folder = r"D:\GIT\RoboTrader\signal_replay_log"

    print("=== 상세 차이점 분석 ===\n")

    # 공통 날짜 파일들 찾기
    prev_files = [f for f in os.listdir(prev_folder) if f.startswith('signal_new2_replay_')]
    current_files = [f for f in os.listdir(current_folder) if f.startswith('signal_new2_replay_')]

    common_dates = []
    for prev_file in prev_files:
        date_match = re.search(r'(\d{8})', prev_file)
        if date_match:
            date = date_match.group(1)
            current_file = f"signal_new2_replay_{date}_9_00_0.txt"
            if current_file in current_files:
                common_dates.append((date, prev_file, current_file))

    total_differences = {
        '더_많은_승리': 0,
        '더_적은_승리': 0,
        '더_많은_거래': 0,
        '더_적은_거래': 0,
        '승률_개선': 0,
        '승률_악화': 0
    }

    for date, prev_file, current_file in sorted(common_dates):
        print(f"[{date}] 분석:")

        # 이전 파일 읽기
        with open(os.path.join(prev_folder, prev_file), 'r', encoding='utf-8') as f:
            prev_content = f.read()

        # 현재 파일 읽기
        with open(os.path.join(current_folder, current_file), 'r', encoding='utf-8') as f:
            current_content = f.read()

        # 총 승패 비교
        prev_match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', prev_content)
        current_match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', current_content)

        if prev_match and current_match:
            prev_wins, prev_losses = int(prev_match.group(1)), int(prev_match.group(2))
            current_wins, current_losses = int(current_match.group(1)), int(current_match.group(2))

            prev_total = prev_wins + prev_losses
            current_total = current_wins + current_losses

            prev_rate = (prev_wins / prev_total * 100) if prev_total > 0 else 0
            current_rate = (current_wins / current_total * 100) if current_total > 0 else 0

            print(f"  승패: {prev_wins}승 {prev_losses}패 → {current_wins}승 {current_losses}패")
            print(f"  승률: {prev_rate:.1f}% → {current_rate:.1f}% ({current_rate - prev_rate:+.1f}%)")
            print(f"  거래수: {prev_total} → {current_total} ({current_total - prev_total:+d})")

            # 통계 업데이트
            if current_wins > prev_wins:
                total_differences['더_많은_승리'] += 1
            elif current_wins < prev_wins:
                total_differences['더_적은_승리'] += 1

            if current_total > prev_total:
                total_differences['더_많은_거래'] += 1
            elif current_total < prev_total:
                total_differences['더_적은_거래'] += 1

            if current_rate > prev_rate:
                total_differences['승률_개선'] += 1
            elif current_rate < prev_rate:
                total_differences['승률_악화'] += 1

        # 매매 신호 차이 분석
        prev_trades = extract_trades(prev_content)
        current_trades = extract_trades(current_content)

        if len(prev_trades) != len(current_trades):
            print(f"  [주의] 거래 수 변화: {len(prev_trades)} → {len(current_trades)}")

        print()

    print("=== 전체 요약 ===")
    print(f"승리 증가한 날: {total_differences['더_많은_승리']}일")
    print(f"승리 감소한 날: {total_differences['더_적은_승리']}일")
    print(f"거래 증가한 날: {total_differences['더_많은_거래']}일")
    print(f"거래 감소한 날: {total_differences['더_적은_거래']}일")
    print(f"승률 개선한 날: {total_differences['승률_개선']}일")
    print(f"승률 악화한 날: {total_differences['승률_악화']}일")

def extract_trades(content):
    """매매 결과 추출"""
    trade_pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.\d+)%\)'
    return re.findall(trade_pattern, content)

def analyze_signal_timing():
    """신호 발생 시간 분석"""
    print("\n=== 신호 발생 시간 분석 ===")

    prev_folder = r"D:\GIT\RoboTrader\signal_replay_log_prev"
    current_folder = r"D:\GIT\RoboTrader\signal_replay_log"

    # 시간대별 신호 카운트
    prev_signals = defaultdict(int)
    current_signals = defaultdict(int)

    # 이전 폴더 분석
    for filename in os.listdir(prev_folder):
        if filename.startswith('signal_new2_replay_'):
            filepath = os.path.join(prev_folder, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            trades = extract_trades(content)
            for trade in trades:
                hour = int(trade[0].split(':')[0])
                prev_signals[hour] += 1

    # 현재 폴더 분석
    for filename in os.listdir(current_folder):
        if filename.startswith('signal_new2_replay_'):
            filepath = os.path.join(current_folder, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            trades = extract_trades(content)
            for trade in trades:
                hour = int(trade[0].split(':')[0])
                current_signals[hour] += 1

    print(f"{'시간':<6} {'이전':<6} {'현재':<6} {'차이':<6}")
    print("-" * 30)

    all_hours = sorted(set(prev_signals.keys()) | set(current_signals.keys()))
    for hour in all_hours:
        prev_count = prev_signals[hour]
        current_count = current_signals[hour]
        diff = current_count - prev_count
        print(f"{hour:02d}시   {prev_count:<6} {current_count:<6} {diff:+d}")

if __name__ == "__main__":
    analyze_detailed_differences()
    analyze_signal_timing()