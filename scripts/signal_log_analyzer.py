#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
from collections import defaultdict
import numpy as np

class SignalLogAnalyzer:
    def __init__(self, prev_folder, current_folder):
        self.prev_folder = prev_folder
        self.current_folder = current_folder
        self.prev_data = {}
        self.current_data = {}

    def parse_file(self, file_path):
        """신호 로그 파일을 파싱하여 데이터 추출"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 총 승패 추출
        total_match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', content)
        if total_match:
            total_wins = int(total_match.group(1))
            total_losses = int(total_match.group(2))
        else:
            total_wins = total_losses = 0

        # selection_date 이후 승패 추출
        selection_match = re.search(r'=== selection_date 이후 승패: (\d+)승 (\d+)패 ===', content)
        if selection_match:
            selection_wins = int(selection_match.group(1))
            selection_losses = int(selection_match.group(2))
        else:
            selection_wins = selection_losses = 0

        # 각 종목별 매매 결과 추출
        trades = []

        # 종목별 섹션 찾기
        stock_sections = re.findall(r'=== (\d+) - (\d{8}) 눌림목\(3분\) 신호 재현 ===.*?(?==== |$)', content, re.DOTALL)

        for stock_code, date in stock_sections:
            # 해당 섹션의 내용 추출
            section_pattern = f'=== {stock_code} - {date} 눌림목\\(3분\\) 신호 재현 ===.*?(?==== |$)'
            section_match = re.search(section_pattern, content, re.DOTALL)
            if section_match:
                section_content = section_match.group(0)

                # 체결 시뮬레이션에서 매매 결과 추출
                trade_pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.\d+)%\)'
                trade_matches = re.findall(trade_pattern, section_content)

                for match in trade_matches:
                    buy_time = match[0]
                    buy_signal = match[1]
                    buy_price = int(match[2].replace(',', ''))
                    sell_time = match[3]
                    sell_signal = match[4]
                    sell_price = int(match[5].replace(',', ''))
                    profit_pct = float(match[6])

                    trades.append({
                        'stock_code': stock_code,
                        'date': date,
                        'buy_time': buy_time,
                        'buy_signal': buy_signal,
                        'buy_price': buy_price,
                        'sell_time': sell_time,
                        'sell_signal': sell_signal,
                        'sell_price': sell_price,
                        'profit_pct': profit_pct,
                        'is_win': profit_pct > 0
                    })

        return {
            'total_wins': total_wins,
            'total_losses': total_losses,
            'selection_wins': selection_wins,
            'selection_losses': selection_losses,
            'trades': trades
        }

    def analyze_folder(self, folder_path):
        """폴더 내 모든 파일 분석"""
        results = {}

        for filename in os.listdir(folder_path):
            if filename.startswith('signal_new2_replay_') and filename.endswith('.txt'):
                date_match = re.search(r'(\d{8})', filename)
                if date_match:
                    date = date_match.group(1)
                    file_path = os.path.join(folder_path, filename)
                    results[date] = self.parse_file(file_path)

        return results

    def compare_daily_performance(self):
        """일별 성과 비교"""
        print("=== 일별 성과 비교 ===")
        print(f"{'날짜':<10} {'이전 승률':<10} {'현재 승률':<10} {'이전 거래':<10} {'현재 거래':<10} {'승률 차이':<10}")
        print("-" * 70)

        common_dates = set(self.prev_data.keys()) & set(self.current_data.keys())

        total_prev_wins = 0
        total_prev_losses = 0
        total_current_wins = 0
        total_current_losses = 0

        for date in sorted(common_dates):
            prev = self.prev_data[date]
            current = self.current_data[date]

            prev_total = prev['total_wins'] + prev['total_losses']
            current_total = current['total_wins'] + current['total_losses']

            prev_win_rate = (prev['total_wins'] / prev_total * 100) if prev_total > 0 else 0
            current_win_rate = (current['total_wins'] / current_total * 100) if current_total > 0 else 0

            diff = current_win_rate - prev_win_rate

            print(f"{date:<10} {prev_win_rate:<10.1f} {current_win_rate:<10.1f} {prev_total:<10} {current_total:<10} {diff:<10.1f}")

            total_prev_wins += prev['total_wins']
            total_prev_losses += prev['total_losses']
            total_current_wins += current['total_wins']
            total_current_losses += current['total_losses']

        print("-" * 70)
        total_prev_total = total_prev_wins + total_prev_losses
        total_current_total = total_current_wins + total_current_losses

        overall_prev_rate = (total_prev_wins / total_prev_total * 100) if total_prev_total > 0 else 0
        overall_current_rate = (total_current_wins / total_current_total * 100) if total_current_total > 0 else 0
        overall_diff = overall_current_rate - overall_prev_rate

        print(f"{'전체':<10} {overall_prev_rate:<10.1f} {overall_current_rate:<10.1f} {total_prev_total:<10} {total_current_total:<10} {overall_diff:<10.1f}")
        print()

        return {
            'prev_win_rate': overall_prev_rate,
            'current_win_rate': overall_current_rate,
            'prev_total_trades': total_prev_total,
            'current_total_trades': total_current_total
        }

    def analyze_time_slots(self):
        """시간대별 승률 분석"""
        print("=== 시간대별 승률 분석 ===")

        time_slots = [
            ('09:00', '10:00'),
            ('10:00', '11:00'),
            ('11:00', '12:00'),
            ('13:00', '14:00'),
            ('14:00', '15:00'),
            ('15:00', '15:30')
        ]

        def get_time_slot(time_str):
            hour = int(time_str.split(':')[0])
            minute = int(time_str.split(':')[1])

            if 9 <= hour < 10:
                return '09:00-10:00'
            elif 10 <= hour < 11:
                return '10:00-11:00'
            elif 11 <= hour < 12:
                return '11:00-12:00'
            elif 13 <= hour < 14:
                return '13:00-14:00'
            elif 14 <= hour < 15:
                return '14:00-15:00'
            elif hour == 15 and minute <= 30:
                return '15:00-15:30'
            else:
                return 'Other'

        # 이전 버전 시간대별 분석
        prev_time_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})
        for date_data in self.prev_data.values():
            for trade in date_data['trades']:
                time_slot = get_time_slot(trade['buy_time'])
                if trade['is_win']:
                    prev_time_stats[time_slot]['wins'] += 1
                else:
                    prev_time_stats[time_slot]['losses'] += 1

        # 현재 버전 시간대별 분석
        current_time_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})
        for date_data in self.current_data.values():
            for trade in date_data['trades']:
                time_slot = get_time_slot(trade['buy_time'])
                if trade['is_win']:
                    current_time_stats[time_slot]['wins'] += 1
                else:
                    current_time_stats[time_slot]['losses'] += 1

        print(f"{'시간대':<12} {'이전 승률':<10} {'현재 승률':<10} {'이전 거래':<10} {'현재 거래':<10} {'승률 차이':<10}")
        print("-" * 72)

        all_time_slots = set(prev_time_stats.keys()) | set(current_time_stats.keys())
        for time_slot in sorted(all_time_slots):
            if time_slot == 'Other':
                continue

            prev_stats = prev_time_stats[time_slot]
            current_stats = current_time_stats[time_slot]

            prev_total = prev_stats['wins'] + prev_stats['losses']
            current_total = current_stats['wins'] + current_stats['losses']

            prev_rate = (prev_stats['wins'] / prev_total * 100) if prev_total > 0 else 0
            current_rate = (current_stats['wins'] / current_total * 100) if current_total > 0 else 0

            diff = current_rate - prev_rate

            print(f"{time_slot:<12} {prev_rate:<10.1f} {current_rate:<10.1f} {prev_total:<10} {current_total:<10} {diff:<10.1f}")

        print()

    def analyze_profit_distribution(self):
        """수익률 분포 분석"""
        print("=== 수익률 분포 분석 ===")

        # 이전 버전 수익률 수집
        prev_profits = []
        for date_data in self.prev_data.values():
            for trade in date_data['trades']:
                prev_profits.append(trade['profit_pct'])

        # 현재 버전 수익률 수집
        current_profits = []
        for date_data in self.current_data.values():
            for trade in date_data['trades']:
                current_profits.append(trade['profit_pct'])

        if prev_profits:
            print(f"이전 버전:")
            print(f"  평균 수익률: {np.mean(prev_profits):.2f}%")
            print(f"  표준편차: {np.std(prev_profits):.2f}%")
            print(f"  최대 수익: {max(prev_profits):.2f}%")
            print(f"  최대 손실: {min(prev_profits):.2f}%")

        if current_profits:
            print(f"현재 버전:")
            print(f"  평균 수익률: {np.mean(current_profits):.2f}%")
            print(f"  표준편차: {np.std(current_profits):.2f}%")
            print(f"  최대 수익: {max(current_profits):.2f}%")
            print(f"  최대 손실: {min(current_profits):.2f}%")

        print()

    def run_analysis(self):
        """전체 분석 실행"""
        print("신호 로그 파일 분석 시작...")

        # 데이터 로드
        self.prev_data = self.analyze_folder(self.prev_folder)
        self.current_data = self.analyze_folder(self.current_folder)

        print(f"이전 버전: {len(self.prev_data)}개 파일")
        print(f"현재 버전: {len(self.current_data)}개 파일")
        print()

        # 분석 실행
        overall_stats = self.compare_daily_performance()
        self.analyze_time_slots()
        self.analyze_profit_distribution()

        # 요약
        print("=== 분석 요약 ===")
        print(f"전체 승률 변화: {overall_stats['prev_win_rate']:.1f}% → {overall_stats['current_win_rate']:.1f}% ({overall_stats['current_win_rate'] - overall_stats['prev_win_rate']:+.1f}%)")
        print(f"총 거래 수 변화: {overall_stats['prev_total_trades']} → {overall_stats['current_total_trades']} ({overall_stats['current_total_trades'] - overall_stats['prev_total_trades']:+d})")

if __name__ == "__main__":
    prev_folder = r"D:\GIT\RoboTrader\signal_replay_log_prev"
    current_folder = r"D:\GIT\RoboTrader\signal_replay_log"

    analyzer = SignalLogAnalyzer(prev_folder, current_folder)
    analyzer.run_analysis()