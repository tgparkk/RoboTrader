# -*- coding: utf-8 -*-
"""
수정 전후 비교 분석
"""
import os
import re
from collections import Counter

def analyze_logs(log_prefix):
    """로그 파일 분석"""
    all_trades = []

    # 모든 로그 파일 찾기
    log_dir = 'signal_replay_log'
    if not os.path.exists(log_dir):
        print(f"{log_dir} 폴더가 없습니다.")
        return None

    files = [f for f in os.listdir(log_dir) if f.startswith(log_prefix)]

    if not files:
        print(f"{log_prefix}로 시작하는 파일이 없습니다.")
        return None

    for filename in files:
        filepath = os.path.join(log_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line in lines:
                if line.strip().startswith('🔴') or line.strip().startswith('🟢'):
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        is_win = line.strip().startswith('🟢')
                        stock = parts[1]
                        time = parts[2]
                        hour = int(time.split(':')[0])

                        all_trades.append({
                            'win': is_win,
                            'hour': hour,
                            'stock': stock,
                            'time': time
                        })
        except Exception as e:
            print(f"Error reading {filepath}: {e}")

    return all_trades

def print_stats(trades, title):
    """통계 출력"""
    if not trades:
        print(f"\n{title}: 데이터 없음")
        return

    wins = [t for t in trades if t['win']]
    losses = [t for t in trades if not t['win']]

    total = len(trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total * 100 if total > 0 else 0

    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    print(f"총 거래: {total}건")
    print(f"승리: {win_count}건")
    print(f"손실: {loss_count}건")
    print(f"승률: {win_rate:.1f}%")

    # 시간대별
    print(f"\n시간대별 분석:")
    hour_wins = Counter([t['hour'] for t in wins])
    hour_losses = Counter([t['hour'] for t in losses])

    for hour in sorted(set([t['hour'] for t in trades])):
        h_wins = hour_wins.get(hour, 0)
        h_losses = hour_losses.get(hour, 0)
        h_total = h_wins + h_losses
        h_rate = h_wins / h_total * 100 if h_total > 0 else 0

        rating = "우수" if h_rate >= 60 else "보통" if h_rate >= 50 else "나쁨"
        print(f"{hour:02d}시: 승{h_wins:3d} 패{h_losses:3d} 합계{h_total:3d} 승률{h_rate:5.1f}% [{rating}]")

def compare():
    """비교 분석"""
    print("="*60)
    print("수정 전후 비교 분석")
    print("="*60)

    # signal_replay_log_before_10_11_filter 폴더가 있으면 그걸 사용
    before_dir = 'signal_replay_log_before_10_11_filter'
    after_dir = 'signal_replay_log'

    if os.path.exists(before_dir):
        print(f"\n[수정 전] {before_dir} 폴더 분석")
        # 임시로 폴더 교체
        import shutil
        temp_dir = 'signal_replay_log_temp'
        if os.path.exists(after_dir):
            shutil.move(after_dir, temp_dir)
        shutil.copytree(before_dir, after_dir)

        before_trades = analyze_logs('signal_new2_replay_')
        print_stats(before_trades, "수정 전")

        # 폴더 복구
        shutil.rmtree(after_dir)
        if os.path.exists(temp_dir):
            shutil.move(temp_dir, after_dir)
    else:
        print(f"\n'{before_dir}' 폴더가 없습니다.")
        print("수정 전 데이터를 백업하려면:")
        print(f"  ren signal_replay_log {before_dir}")
        print(f"  mkdir signal_replay_log")
        before_trades = None

    print(f"\n[수정 후] {after_dir} 폴더 분석")
    after_trades = analyze_logs('signal_new2_replay_')
    print_stats(after_trades, "수정 후")

    # 비교
    if before_trades and after_trades:
        print(f"\n{'='*60}")
        print("변화 요약")
        print(f"{'='*60}")

        before_total = len(before_trades)
        after_total = len(after_trades)
        before_wins = len([t for t in before_trades if t['win']])
        after_wins = len([t for t in after_trades if t['win']])
        before_rate = before_wins / before_total * 100 if before_total > 0 else 0
        after_rate = after_wins / after_total * 100 if after_total > 0 else 0

        print(f"총 거래: {before_total}건 → {after_total}건 ({after_total - before_total:+d})")
        print(f"승률: {before_rate:.1f}% → {after_rate:.1f}% ({after_rate - before_rate:+.1f}%p)")

        # 10~11시 비교
        before_10_11 = [t for t in before_trades if 10 <= t['hour'] < 12]
        after_10_11 = [t for t in after_trades if 10 <= t['hour'] < 12]

        print(f"\n10~11시 거래:")
        print(f"  수정 전: {len(before_10_11)}건")
        print(f"  수정 후: {len(after_10_11)}건 ({len(after_10_11) - len(before_10_11):+d})")
        if len(before_10_11) > 0:
            reduction = (len(before_10_11) - len(after_10_11)) / len(before_10_11) * 100
            print(f"  감소율: {reduction:.1f}%")

if __name__ == '__main__':
    compare()
