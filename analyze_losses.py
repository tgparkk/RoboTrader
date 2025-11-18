# -*- coding: utf-8 -*-
"""
손실 거래 상세 분석
"""
import re
import os
from collections import Counter, defaultdict

def analyze_loss_trades():
    """손실 거래 분석"""

    # 최근 데이터 분석
    dates = ['20251027', '20251028', '20251029']
    all_losses = []
    all_wins = []

    for date in dates:
        log_file = f'signal_replay_log/signal_new2_replay_{date}_9_00_0.txt'

        if not os.path.exists(log_file):
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

    print("="*60)
    print("손실/승리 거래 분석 (최근 3일)")
    print("="*60)

    print(f"\n총 손실 거래: {len(all_losses)}건")
    print(f"총 승리 거래: {len(all_wins)}건")
    print(f"승률: {len(all_wins)/(len(all_wins)+len(all_losses))*100:.1f}%")

    # 시간대별 분석
    print("\n시간대별 손실 분포:")
    loss_hours = Counter([l['hour'] for l in all_losses])
    win_hours = Counter([w['hour'] for w in all_wins])

    for hour in sorted(set(list(loss_hours.keys()) + list(win_hours.keys()))):
        losses = loss_hours.get(hour, 0)
        wins = win_hours.get(hour, 0)
        total = wins + losses
        win_rate = wins/total*100 if total > 0 else 0
        print(f"{hour:02d}시: 승{wins}건 패{losses}건 (승률 {win_rate:.1f}%)")

    # 손실 크기 분석
    print("\n손실 크기 분석:")
    big_losses = [l for l in all_losses if l['profit'] <= -2.0]
    small_losses = [l for l in all_losses if -2.0 < l['profit'] < 0]
    print(f"큰 손실 (-2.0% 이하): {len(big_losses)}건")
    print(f"작은 손실 (-2.0% ~ 0%): {len(small_losses)}건")

    # 손절 도달 비율
    stop_loss_count = len([l for l in all_losses if l['profit'] <= -2.5])
    print(f"손절 도달 (-2.5%): {stop_loss_count}건 ({stop_loss_count/len(all_losses)*100:.1f}%)")

    # 개별 손실 거래 상세
    print("\n손실 거래 상세:")
    for loss in sorted(all_losses, key=lambda x: x['profit']):
        print(f"{loss['date'][-4:]} {loss['time']} {loss['stock']} {loss['profit']:+.2f}%")

    return all_losses, all_wins

if __name__ == '__main__':
    analyze_loss_trades()
