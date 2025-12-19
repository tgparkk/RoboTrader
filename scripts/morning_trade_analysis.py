#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
09:00-12:00 시간대 매수 신호 분석 스크립트
"""

import os
import re
import glob
from datetime import datetime, time
from collections import defaultdict
import statistics

def parse_time(time_str):
    """시간 문자열을 시간 객체로 변환"""
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except:
        return None

def is_morning_time(time_obj):
    """09:00-12:00 시간대인지 확인"""
    if time_obj is None:
        return False
    return time(9, 0) <= time_obj < time(12, 0)

def get_hour_range(time_obj):
    """시간대 구간 반환"""
    if time_obj is None:
        return None
    hour = time_obj.hour
    if 9 <= hour < 10:
        return "09:00-10:00"
    elif 10 <= hour < 11:
        return "10:00-11:00"
    elif 11 <= hour < 12:
        return "11:00-12:00"
    return None

def parse_signal_file(file_path):
    """신호 파일을 파싱하여 거래 정보 추출"""
    trades = []

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 날짜 추출
    date_match = re.search(r'signal_new2_replay_(\d{8})', file_path)
    if not date_match:
        return trades

    date_str = date_match.group(1)

    # 각 종목별 섹션을 분리
    sections = re.split(r'=== (\d{6}) - (\d{8}) 눌림목\(3분\) 신호 재현 ===', content)

    for i in range(1, len(sections), 3):
        if i + 2 >= len(sections):
            break

        stock_code = sections[i]
        stock_date = sections[i + 1]
        section_content = sections[i + 2]

        # 체결 시뮬레이션 섹션 찾기
        simulation_match = re.search(r'체결 시뮬레이션:(.*?)(?=매수 못한 기회:|🔍 상세 3분봉 분석|$)',
                                   section_content, re.DOTALL)

        if simulation_match:
            simulation_content = simulation_match.group(1)

            # 매수/매도 거래 찾기
            trade_pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.\d+)%\)'

            for match in re.finditer(trade_pattern, simulation_content):
                buy_time_str = match.group(1)
                buy_signal = match.group(2)
                buy_price = int(match.group(3).replace(',', ''))
                sell_time_str = match.group(4)
                sell_signal = match.group(5)
                sell_price = int(match.group(6).replace(',', ''))
                profit_pct = float(match.group(7))

                buy_time = parse_time(buy_time_str)
                sell_time = parse_time(sell_time_str)

                # 09:00-12:00 시간대 매수만 필터링
                if is_morning_time(buy_time):
                    trades.append({
                        'date': date_str,
                        'stock_code': stock_code,
                        'buy_time': buy_time_str,
                        'buy_signal': buy_signal,
                        'buy_price': buy_price,
                        'sell_time': sell_time_str,
                        'sell_signal': sell_signal,
                        'sell_price': sell_price,
                        'profit_pct': profit_pct,
                        'hour_range': get_hour_range(buy_time),
                        'is_win': profit_pct > 0
                    })

    return trades

def analyze_trades(trades, version_name):
    """거래 데이터 분석"""
    print(f"\n{'='*60}")
    print(f"[분석] {version_name} 분석 결과")
    print(f"{'='*60}")

    if not trades:
        print("[오류] 09:00-12:00 시간대 거래 기록이 없습니다.")
        return {}

    # 전체 통계
    total_trades = len(trades)
    wins = sum(1 for t in trades if t['is_win'])
    losses = total_trades - wins
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    profit_pcts = [t['profit_pct'] for t in trades]
    avg_profit = statistics.mean(profit_pcts)

    print(f"\n[통계] 전체 09:00-12:00 시간대 거래 통계:")
    print(f"   총 거래수: {total_trades}건")
    print(f"   승수: {wins}건")
    print(f"   패수: {losses}건")
    print(f"   승률: {win_rate:.1f}%")
    print(f"   평균 수익률: {avg_profit:.2f}%")

    # 시간대별 분석
    hour_stats = defaultdict(lambda: {'trades': [], 'wins': 0, 'total': 0})

    for trade in trades:
        hour_range = trade['hour_range']
        hour_stats[hour_range]['trades'].append(trade)
        hour_stats[hour_range]['total'] += 1
        if trade['is_win']:
            hour_stats[hour_range]['wins'] += 1

    print(f"\n[시간별] 시간대별 상세 분석:")
    for hour_range in ["09:00-10:00", "10:00-11:00", "11:00-12:00"]:
        if hour_range in hour_stats:
            stats = hour_stats[hour_range]
            total = stats['total']
            wins = stats['wins']
            win_rate = (wins / total * 100) if total > 0 else 0
            profits = [t['profit_pct'] for t in stats['trades']]
            avg_profit = statistics.mean(profits) if profits else 0

            print(f"   {hour_range}: {total}건 | {wins}승 {total-wins}패 | 승률 {win_rate:.1f}% | 평균 {avg_profit:.2f}%")
        else:
            print(f"   {hour_range}: 0건")

    # 일별 분석
    daily_stats = defaultdict(lambda: {'trades': [], 'wins': 0, 'total': 0})

    for trade in trades:
        date = trade['date']
        daily_stats[date]['trades'].append(trade)
        daily_stats[date]['total'] += 1
        if trade['is_win']:
            daily_stats[date]['wins'] += 1

    print(f"\n[일별] 일별 오전 시간대 성과:")
    for date in sorted(daily_stats.keys()):
        stats = daily_stats[date]
        total = stats['total']
        wins = stats['wins']
        win_rate = (wins / total * 100) if total > 0 else 0
        profits = [t['profit_pct'] for t in stats['trades']]
        avg_profit = statistics.mean(profits) if profits else 0

        # 날짜 포맷팅
        formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        print(f"   {formatted_date}: {total}건 | {wins}승 {total-wins}패 | 승률 {win_rate:.1f}% | 평균 {avg_profit:.2f}%")

    # 수익률 분포
    print(f"\n[수익률] 수익률 분포:")
    positive_profits = [p for p in profit_pcts if p > 0]
    negative_profits = [p for p in profit_pcts if p < 0]

    if positive_profits:
        print(f"   양수 수익률: 평균 {statistics.mean(positive_profits):.2f}% | 최대 {max(positive_profits):.2f}%")
    if negative_profits:
        print(f"   음수 수익률: 평균 {statistics.mean(negative_profits):.2f}% | 최소 {min(negative_profits):.2f}%")

    # 상세 거래 기록 (최근 10건)
    print(f"\n[거래기록] 최근 거래 기록 (최대 10건):")
    recent_trades = sorted(trades, key=lambda x: (x['date'], x['buy_time']), reverse=True)[:10]

    for trade in recent_trades:
        formatted_date = f"{trade['date'][:4]}-{trade['date'][4:6]}-{trade['date'][6:8]}"
        status = "[승]" if trade['is_win'] else "[패]"
        print(f"   {formatted_date} {trade['buy_time']} {trade['stock_code']} "
              f"@{trade['buy_price']:,} → {trade['sell_time']} @{trade['sell_price']:,} "
              f"({trade['profit_pct']:+.2f}%) {status}")

    return {
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_profit': avg_profit,
        'hour_stats': dict(hour_stats),
        'daily_stats': dict(daily_stats),
        'trades': trades
    }

def compare_versions(prev_stats, current_stats):
    """이전 버전과 현재 버전 비교"""
    print(f"\n{'='*60}")
    print(f"[비교] 버전 비교 분석")
    print(f"{'='*60}")

    if not prev_stats or not current_stats:
        print("[오류] 비교할 데이터가 부족합니다.")
        return

    print(f"\n[지표] 주요 지표 변화:")

    # 거래수 비교
    trade_diff = current_stats['total_trades'] - prev_stats['total_trades']
    print(f"   총 거래수: {prev_stats['total_trades']} → {current_stats['total_trades']} ({trade_diff:+d})")

    # 승률 비교
    win_rate_diff = current_stats['win_rate'] - prev_stats['win_rate']
    print(f"   승률: {prev_stats['win_rate']:.1f}% → {current_stats['win_rate']:.1f}% ({win_rate_diff:+.1f}%p)")

    # 평균 수익률 비교
    profit_diff = current_stats['avg_profit'] - prev_stats['avg_profit']
    print(f"   평균 수익률: {prev_stats['avg_profit']:.2f}% → {current_stats['avg_profit']:.2f}% ({profit_diff:+.2f}%p)")

    # 시간대별 비교
    print(f"\n[시간별] 시간대별 승률 변화:")
    for hour_range in ["09:00-10:00", "10:00-11:00", "11:00-12:00"]:
        prev_hr = prev_stats['hour_stats'].get(hour_range, {'wins': 0, 'total': 0})
        curr_hr = current_stats['hour_stats'].get(hour_range, {'wins': 0, 'total': 0})

        prev_rate = (prev_hr['wins'] / prev_hr['total'] * 100) if prev_hr['total'] > 0 else 0
        curr_rate = (curr_hr['wins'] / curr_hr['total'] * 100) if curr_hr['total'] > 0 else 0
        rate_diff = curr_rate - prev_rate

        print(f"   {hour_range}: {prev_rate:.1f}% → {curr_rate:.1f}% ({rate_diff:+.1f}%p)")

def main():
    """메인 실행 함수"""
    print("[시작] 09:00-12:00 시간대 매수 신호 분석을 시작합니다...")

    # 이전 버전 로그 분석
    prev_log_dir = r"D:\GIT\RoboTrader\signal_replay_log_prev"
    prev_files = glob.glob(os.path.join(prev_log_dir, "signal_new2_replay_*.txt"))

    print(f"\n[처리] 이전 버전 로그 파일 {len(prev_files)}개 처리 중...")
    prev_trades = []
    for file_path in prev_files:
        trades = parse_signal_file(file_path)
        prev_trades.extend(trades)

    prev_stats = analyze_trades(prev_trades, "이전 버전 (signal_replay_log_prev)")

    # 현재 버전 로그 분석
    current_log_dir = r"D:\GIT\RoboTrader\signal_replay_log"
    current_files = glob.glob(os.path.join(current_log_dir, "signal_new2_replay_*.txt"))

    print(f"\n[처리] 현재 버전 로그 파일 {len(current_files)}개 처리 중...")
    current_trades = []
    for file_path in current_files:
        trades = parse_signal_file(file_path)
        current_trades.extend(trades)

    current_stats = analyze_trades(current_trades, "현재 버전 (signal_replay_log)")

    # 버전 비교
    compare_versions(prev_stats, current_stats)

    print(f"\n[완료] 분석 완료!")
    print(f"   이전 버전 오전 거래: {len(prev_trades)}건")
    print(f"   현재 버전 오전 거래: {len(current_trades)}건")

if __name__ == "__main__":
    main()