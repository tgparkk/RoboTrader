#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
from collections import defaultdict
import numpy as np

def analyze_performance_insights():
    """성과 개선사항과 문제점 분석"""

    prev_folder = r"D:\GIT\RoboTrader\signal_replay_log_prev"
    current_folder = r"D:\GIT\RoboTrader\signal_replay_log"

    print("=== 성과 분석 및 개선사항 ===\n")

    # 전체 통계 수집
    prev_stats = collect_overall_stats(prev_folder)
    current_stats = collect_overall_stats(current_folder)

    print("1. 전체 성과 비교")
    print(f"   총 거래 수: {prev_stats['total_trades']} → {current_stats['total_trades']} ({current_stats['total_trades'] - prev_stats['total_trades']:+d})")
    print(f"   총 승리 수: {prev_stats['total_wins']} → {current_stats['total_wins']} ({current_stats['total_wins'] - prev_stats['total_wins']:+d})")
    print(f"   전체 승률: {prev_stats['win_rate']:.1f}% → {current_stats['win_rate']:.1f}% ({current_stats['win_rate'] - prev_stats['win_rate']:+.1f}%)")
    print(f"   평균 수익률: {prev_stats['avg_profit']:.2f}% → {current_stats['avg_profit']:.2f}% ({current_stats['avg_profit'] - prev_stats['avg_profit']:+.2f}%)")
    print()

    print("2. 주요 변화점 분석")

    # 거래 수 감소 분석
    trade_decrease = prev_stats['total_trades'] - current_stats['total_trades']
    if trade_decrease > 0:
        print(f"   [감소] 거래 수 {trade_decrease}건 감소 - 더 보수적인 신호 생성")
    elif trade_decrease < 0:
        print(f"   [증가] 거래 수 {abs(trade_decrease)}건 증가 - 더 적극적인 신호 생성")
    else:
        print(f"   [유지] 거래 수 변화 없음")

    # 승률 변화 분석
    win_rate_change = current_stats['win_rate'] - prev_stats['win_rate']
    if win_rate_change > 1:
        print(f"   [개선] 승률 {win_rate_change:.1f}%p 개선 - 신호 품질 향상")
    elif win_rate_change < -1:
        print(f"   [악화] 승률 {abs(win_rate_change):.1f}%p 악화 - 신호 품질 저하")
    else:
        print(f"   [유지] 승률 유사한 수준 유지")

    print()

    # 시간대별 상세 분석
    print("3. 시간대별 성과 변화")
    analyze_hourly_performance(prev_folder, current_folder)

    # 손실 패턴 분석
    print("\n4. 손실 패턴 분석")
    analyze_loss_patterns(prev_folder, current_folder)

    # 수익 패턴 분석
    print("\n5. 수익 패턴 분석")
    analyze_profit_patterns(prev_folder, current_folder)

def collect_overall_stats(folder_path):
    """폴더 전체 통계 수집"""
    total_trades = 0
    total_wins = 0
    all_profits = []

    for filename in os.listdir(folder_path):
        if filename.startswith('signal_new2_replay_'):
            filepath = os.path.join(folder_path, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # 총 승패 추출
            match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', content)
            if match:
                wins = int(match.group(1))
                losses = int(match.group(2))
                total_trades += wins + losses
                total_wins += wins

            # 개별 거래 수익률 추출
            trade_pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.\d+)%\)'
            trades = re.findall(trade_pattern, content)
            for trade in trades:
                profit_pct = float(trade[6])
                all_profits.append(profit_pct)

    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    avg_profit = np.mean(all_profits) if all_profits else 0

    return {
        'total_trades': total_trades,
        'total_wins': total_wins,
        'win_rate': win_rate,
        'avg_profit': avg_profit,
        'all_profits': all_profits
    }

def analyze_hourly_performance(prev_folder, current_folder):
    """시간대별 성과 분석"""

    def get_hourly_stats(folder_path):
        hourly_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profits': []})

        for filename in os.listdir(folder_path):
            if filename.startswith('signal_new2_replay_'):
                filepath = os.path.join(folder_path, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                trade_pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.\d+)%\)'
                trades = re.findall(trade_pattern, content)

                for trade in trades:
                    hour = int(trade[0].split(':')[0])
                    profit_pct = float(trade[6])

                    hourly_stats[hour]['profits'].append(profit_pct)
                    if profit_pct > 0:
                        hourly_stats[hour]['wins'] += 1
                    else:
                        hourly_stats[hour]['losses'] += 1

        return hourly_stats

    prev_hourly = get_hourly_stats(prev_folder)
    current_hourly = get_hourly_stats(current_folder)

    print(f"   {'시간':<6} {'이전승률':<8} {'현재승률':<8} {'거래변화':<8} {'평균수익변화':<12}")
    print("   " + "-" * 50)

    all_hours = sorted(set(prev_hourly.keys()) | set(current_hourly.keys()))
    for hour in all_hours:
        prev_stats = prev_hourly[hour]
        current_stats = current_hourly[hour]

        prev_total = prev_stats['wins'] + prev_stats['losses']
        current_total = current_stats['wins'] + current_stats['losses']

        prev_rate = (prev_stats['wins'] / prev_total * 100) if prev_total > 0 else 0
        current_rate = (current_stats['wins'] / current_total * 100) if current_total > 0 else 0

        prev_avg_profit = np.mean(prev_stats['profits']) if prev_stats['profits'] else 0
        current_avg_profit = np.mean(current_stats['profits']) if current_stats['profits'] else 0

        trade_change = current_total - prev_total
        profit_change = current_avg_profit - prev_avg_profit

        print(f"   {hour:02d}시   {prev_rate:<8.1f} {current_rate:<8.1f} {trade_change:<8d} {profit_change:<12.2f}")

def analyze_loss_patterns(prev_folder, current_folder):
    """손실 패턴 분석"""

    def get_loss_stats(folder_path):
        losses = []
        loss_reasons = defaultdict(int)

        for filename in os.listdir(folder_path):
            if filename.startswith('signal_new2_replay_'):
                filepath = os.path.join(folder_path, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                trade_pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.\d+)%\)'
                trades = re.findall(trade_pattern, content)

                for trade in trades:
                    profit_pct = float(trade[6])
                    sell_reason = trade[4]

                    if profit_pct < 0:
                        losses.append(profit_pct)
                        loss_reasons[sell_reason] += 1

        return losses, loss_reasons

    prev_losses, prev_reasons = get_loss_stats(prev_folder)
    current_losses, current_reasons = get_loss_stats(current_folder)

    print(f"   평균 손실률: {np.mean(prev_losses):.2f}% → {np.mean(current_losses):.2f}%")
    print(f"   손실 거래 수: {len(prev_losses)} → {len(current_losses)}")

    print("\n   손실 사유별 분석:")
    all_reasons = set(prev_reasons.keys()) | set(current_reasons.keys())
    for reason in sorted(all_reasons):
        prev_count = prev_reasons[reason]
        current_count = current_reasons[reason]
        print(f"     {reason}: {prev_count} → {current_count} ({current_count - prev_count:+d})")

def analyze_profit_patterns(prev_folder, current_folder):
    """수익 패턴 분석"""

    def get_profit_stats(folder_path):
        profits = []
        profit_reasons = defaultdict(int)

        for filename in os.listdir(folder_path):
            if filename.startswith('signal_new2_replay_'):
                filepath = os.path.join(folder_path, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                trade_pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.\d+)%\)'
                trades = re.findall(trade_pattern, content)

                for trade in trades:
                    profit_pct = float(trade[6])
                    sell_reason = trade[4]

                    if profit_pct > 0:
                        profits.append(profit_pct)
                        profit_reasons[sell_reason] += 1

        return profits, profit_reasons

    prev_profits, prev_reasons = get_profit_stats(prev_folder)
    current_profits, current_reasons = get_profit_stats(current_folder)

    print(f"   평균 수익률: {np.mean(prev_profits):.2f}% → {np.mean(current_profits):.2f}%")
    print(f"   수익 거래 수: {len(prev_profits)} → {len(current_profits)}")

    print("\n   수익 실현 사유별 분석:")
    all_reasons = set(prev_reasons.keys()) | set(current_reasons.keys())
    for reason in sorted(all_reasons):
        prev_count = prev_reasons[reason]
        current_count = current_reasons[reason]
        print(f"     {reason}: {prev_count} → {current_count} ({current_count - prev_count:+d})")

if __name__ == "__main__":
    analyze_performance_insights()