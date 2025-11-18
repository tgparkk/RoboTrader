# -*- coding: utf-8 -*-
"""
전체 기간 손실/승리 패턴 분석 (2025.09.01 ~ 2025.10.29)
"""
import re
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

def generate_dates(start_str, end_str):
    """날짜 범위 생성"""
    start = datetime.strptime(start_str, '%Y%m%d')
    end = datetime.strptime(end_str, '%Y%m%d')

    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # 평일만
            dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)

    return dates

def analyze_full_period():
    """전체 기간 분석"""

    dates = generate_dates('20250901', '20251029')

    all_losses = []
    all_wins = []
    missing_dates = []

    print("데이터 수집 중...")

    for date in dates:
        log_file = f'signal_replay_log/signal_new2_replay_{date}_9_00_0.txt'

        if not os.path.exists(log_file):
            missing_dates.append(date)
            continue

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line in lines:
                # 손실 거래
                if line.strip().startswith('🔴'):
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        stock = parts[1]
                        time = parts[2]
                        profit_str = parts[-1].replace('%', '').replace('(', '').replace(')', '')

                        try:
                            profit = float(profit_str)
                            hour = int(time.split(':')[0])

                            all_losses.append({
                                'date': date,
                                'stock': stock,
                                'time': time,
                                'hour': hour,
                                'profit': profit
                            })
                        except:
                            pass

                # 승리 거래
                elif line.strip().startswith('🟢'):
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        stock = parts[1]
                        time = parts[2]
                        profit_str = parts[-1].replace('%', '').replace('(', '').replace(')', '').replace('+', '')

                        try:
                            profit = float(profit_str)
                            hour = int(time.split(':')[0])

                            all_wins.append({
                                'date': date,
                                'stock': stock,
                                'time': time,
                                'hour': hour,
                                'profit': profit
                            })
                        except:
                            pass
        except Exception as e:
            print(f"Error reading {log_file}: {e}")

    print("\n" + "="*70)
    print("전체 기간 분석 (2025.09.01 ~ 2025.10.29)")
    print("="*70)

    print(f"\n분석 일수: {len(dates)}일 (평일)")
    print(f"데이터 있는 날: {len(dates) - len(missing_dates)}일")
    if missing_dates:
        print(f"데이터 없는 날: {len(missing_dates)}일")

    print(f"\n총 손실 거래: {len(all_losses)}건")
    print(f"총 승리 거래: {len(all_wins)}건")
    print(f"총 거래: {len(all_wins) + len(all_losses)}건")
    print(f"승률: {len(all_wins)/(len(all_wins)+len(all_losses))*100:.1f}%")

    # 시간대별 분석
    print("\n" + "="*70)
    print("시간대별 승패 분석")
    print("="*70)

    loss_hours = Counter([l['hour'] for l in all_losses])
    win_hours = Counter([w['hour'] for w in all_wins])

    print(f"\n{'시간':4} | {'승리':>4} | {'패배':>4} | {'합계':>4} | {'승률':>6} | {'평가':8}")
    print("-" * 50)

    hour_stats = []
    for hour in sorted(set(list(loss_hours.keys()) + list(win_hours.keys()))):
        losses = loss_hours.get(hour, 0)
        wins = win_hours.get(hour, 0)
        total = wins + losses
        win_rate = wins/total*100 if total > 0 else 0

        # 평가
        if win_rate >= 60:
            rating = "✅ 우수"
        elif win_rate >= 50:
            rating = "⚠️ 보통"
        else:
            rating = "❌ 나쁨"

        print(f"{hour:02d}시 | {wins:4d} | {losses:4d} | {total:4d} | {win_rate:5.1f}% | {rating}")

        hour_stats.append({
            'hour': hour,
            'wins': wins,
            'losses': losses,
            'total': total,
            'win_rate': win_rate
        })

    # 손실 크기 분석
    print("\n" + "="*70)
    print("손실 크기 분석")
    print("="*70)

    big_losses = [l for l in all_losses if l['profit'] <= -2.0]
    small_losses = [l for l in all_losses if -2.0 < l['profit'] < 0]
    stop_losses = [l for l in all_losses if l['profit'] <= -2.5]

    print(f"\n큰 손실 (-2.0% 이하): {len(big_losses):3d}건 ({len(big_losses)/len(all_losses)*100:.1f}%)")
    print(f"작은 손실 (-2.0% ~ 0%): {len(small_losses):3d}건 ({len(small_losses)/len(all_losses)*100:.1f}%)")
    print(f"손절 도달 (-2.5%):     {len(stop_losses):3d}건 ({len(stop_losses)/len(all_losses)*100:.1f}%)")

    # 승리 크기 분석
    print("\n" + "="*70)
    print("승리 크기 분석")
    print("="*70)

    big_wins = [w for w in all_wins if w['profit'] >= 3.0]
    medium_wins = [w for w in all_wins if 1.0 <= w['profit'] < 3.0]
    small_wins = [w for w in all_wins if 0 < w['profit'] < 1.0]

    print(f"\n큰 승리 (+3.0% 이상):  {len(big_wins):3d}건 ({len(big_wins)/len(all_wins)*100:.1f}%)")
    print(f"중간 승리 (+1~3%):     {len(medium_wins):3d}건 ({len(medium_wins)/len(all_wins)*100:.1f}%)")
    print(f"작은 승리 (+0~1%):     {len(small_wins):3d}건 ({len(small_wins)/len(all_wins)*100:.1f}%)")

    # 월별 분석
    print("\n" + "="*70)
    print("월별 분석")
    print("="*70)

    monthly_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

    for w in all_wins:
        month = w['date'][:6]  # YYYYMM
        monthly_stats[month]['wins'] += 1

    for l in all_losses:
        month = l['date'][:6]
        monthly_stats[month]['losses'] += 1

    print(f"\n{'월':8} | {'승리':>4} | {'패배':>4} | {'승률':>6}")
    print("-" * 35)

    for month in sorted(monthly_stats.keys()):
        wins = monthly_stats[month]['wins']
        losses = monthly_stats[month]['losses']
        total = wins + losses
        win_rate = wins/total*100 if total > 0 else 0

        month_str = f"{month[:4]}.{month[4:]}"
        print(f"{month_str:8} | {wins:4d} | {losses:4d} | {win_rate:5.1f}%")

    # 핵심 인사이트
    print("\n" + "="*70)
    print("🎯 핵심 인사이트")
    print("="*70)

    # 가장 나쁜 시간대
    worst_hours = sorted(hour_stats, key=lambda x: x['win_rate'])[:3]
    print("\n가장 나쁜 시간대 TOP 3:")
    for i, h in enumerate(worst_hours, 1):
        print(f"{i}. {h['hour']:02d}시: 승률 {h['win_rate']:.1f}% ({h['wins']}승 {h['losses']}패)")

    # 가장 좋은 시간대
    best_hours = sorted(hour_stats, key=lambda x: x['win_rate'], reverse=True)[:3]
    print("\n가장 좋은 시간대 TOP 3:")
    for i, h in enumerate(best_hours, 1):
        print(f"{i}. {h['hour']:02d}시: 승률 {h['win_rate']:.1f}% ({h['wins']}승 {h['losses']}패)")

    # 개선 제안
    print("\n" + "="*70)
    print("💡 데이터 기반 개선 제안")
    print("="*70)

    print("\n1. 시간대 필터링:")
    for h in hour_stats:
        if h['win_rate'] < 45 and h['total'] >= 10:
            print(f"   - {h['hour']:02d}시 차단 또는 신뢰도 90+ (승률 {h['win_rate']:.1f}%, {h['total']}건)")

    print("\n2. 거래 집중 시간대:")
    for h in best_hours[:2]:
        if h['win_rate'] >= 60:
            print(f"   - {h['hour']:02d}시 집중 (승률 {h['win_rate']:.1f}%)")

    # 예상 개선 효과
    print("\n" + "="*70)
    print("📊 예상 개선 효과 (나쁜 시간대 차단시)")
    print("="*70)

    # 승률 45% 미만 시간대 제거
    bad_hours_set = set([h['hour'] for h in hour_stats if h['win_rate'] < 45 and h['total'] >= 10])

    remaining_wins = len([w for w in all_wins if w['hour'] not in bad_hours_set])
    remaining_losses = len([l for l in all_losses if l['hour'] not in bad_hours_set])
    remaining_total = remaining_wins + remaining_losses

    if remaining_total > 0:
        new_win_rate = remaining_wins / remaining_total * 100

        print(f"\n현재:")
        print(f"  총 거래: {len(all_wins) + len(all_losses)}건")
        print(f"  승률: {len(all_wins)/(len(all_wins)+len(all_losses))*100:.1f}%")

        print(f"\n나쁜 시간대 차단 후:")
        print(f"  총 거래: {remaining_total}건 (-{len(all_wins) + len(all_losses) - remaining_total}건)")
        print(f"  승률: {new_win_rate:.1f}% (+{new_win_rate - len(all_wins)/(len(all_wins)+len(all_losses))*100:.1f}%p)")
        print(f"  제거된 손실: {len(all_losses) - remaining_losses}건")

    print("\n" + "="*70)

    return hour_stats, all_wins, all_losses

if __name__ == '__main__':
    analyze_full_period()
