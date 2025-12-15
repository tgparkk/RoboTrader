#!/usr/bin/env python3
"""
ML 필터 적용 전후 성과 비교 분석

기능:
1. 원본 백테스트 결과 분석 (signal_replay_log/)
2. ML 필터 적용 결과 분석 (signal_replay_log_ml/)
3. 승률, 평균 수익률, 총 수익 등 비교
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import re
import glob
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict


def parse_signal_line(line: str) -> Dict:
    """신호 라인 파싱"""
    # 예: 🟢 487240 09:33 매수 → +0.57% [ML: 86.7%]
    # 예: 🔴 307950 10:06 매수 → -2.50% [ML: 62.0%]

    # 승패 여부
    is_win = '🟢' in line

    # 종목코드, 시간, 수익률 추출
    match = re.search(r'(\d{6})\s+(\d{2}:\d{2})\s+매수\s+→\s+([-+]\d+\.\d+)%', line)
    if not match:
        return None

    stock_code = match.group(1)
    time_str = match.group(2)
    profit_rate = float(match.group(3))

    # ML 확률 추출 (있는 경우)
    ml_prob = None
    ml_match = re.search(r'\[ML:\s+([\d.]+)%\]', line)
    if ml_match:
        ml_prob = float(ml_match.group(1))

    return {
        'is_win': is_win,
        'stock_code': stock_code,
        'time': time_str,
        'profit_rate': profit_rate,
        'ml_prob': ml_prob
    }


def analyze_file(file_path: str) -> Dict:
    """단일 파일 분석"""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    signals = []
    for line in lines:
        if line.startswith('#'):  # 필터링된 신호 제외
            continue

        signal = parse_signal_line(line)
        if signal:
            signals.append(signal)

    if not signals:
        return {
            'total': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0.0,
            'avg_profit': 0.0,
            'total_profit': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0
        }

    wins = [s for s in signals if s['is_win']]
    losses = [s for s in signals if not s['is_win']]

    win_profits = [s['profit_rate'] for s in wins]
    loss_profits = [s['profit_rate'] for s in losses]
    all_profits = [s['profit_rate'] for s in signals]

    return {
        'total': len(signals),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(signals) * 100 if signals else 0,
        'avg_profit': sum(all_profits) / len(all_profits) if all_profits else 0,
        'total_profit': sum(all_profits),
        'avg_win': sum(win_profits) / len(win_profits) if win_profits else 0,
        'avg_loss': sum(loss_profits) / len(loss_profits) if loss_profits else 0
    }


def analyze_directory(dir_path: str, pattern: str) -> Tuple[Dict, List[Dict]]:
    """디렉토리 내 모든 파일 분석"""
    files = glob.glob(f"{dir_path}/{pattern}")

    total_stats = {
        'total': 0,
        'wins': 0,
        'losses': 0,
        'total_profit': 0.0
    }

    daily_results = []

    for file in sorted(files):
        stats = analyze_file(file)

        if stats['total'] > 0:
            total_stats['total'] += stats['total']
            total_stats['wins'] += stats['wins']
            total_stats['losses'] += stats['losses']
            total_stats['total_profit'] += stats['total_profit']

            # 날짜 추출
            date_match = re.search(r'(\d{8})', Path(file).name)
            date = date_match.group(1) if date_match else 'unknown'

            daily_results.append({
                'date': date,
                'file': Path(file).name,
                **stats
            })

    # 전체 통계 계산
    if total_stats['total'] > 0:
        total_stats['win_rate'] = total_stats['wins'] / total_stats['total'] * 100
        total_stats['avg_profit'] = total_stats['total_profit'] / total_stats['total']
    else:
        total_stats['win_rate'] = 0.0
        total_stats['avg_profit'] = 0.0

    return total_stats, daily_results


def print_comparison(original_stats: Dict, ml_stats: Dict):
    """비교 결과 출력"""
    print("\n" + "=" * 80)
    print("📊 ML 필터 적용 전후 성과 비교")
    print("=" * 80)

    print("\n┌─────────────────────┬──────────────────┬──────────────────┬──────────────────┐")
    print("│ 항목                │ 원본 (필터 없음) │ ML 필터 적용 후  │ 변화량           │")
    print("├─────────────────────┼──────────────────┼──────────────────┼──────────────────┤")

    # 총 신호 수
    total_diff = ml_stats['total'] - original_stats['total']
    total_diff_pct = total_diff / original_stats['total'] * 100 if original_stats['total'] > 0 else 0
    print(f"│ 총 신호 수          │ {original_stats['total']:>14}개 │ {ml_stats['total']:>14}개 │ {total_diff:+15.0f}개 │")

    # 승리 수
    wins_diff = ml_stats['wins'] - original_stats['wins']
    print(f"│ 승리 거래           │ {original_stats['wins']:>14}개 │ {ml_stats['wins']:>14}개 │ {wins_diff:+15.0f}개 │")

    # 패배 수
    losses_diff = ml_stats['losses'] - original_stats['losses']
    print(f"│ 패배 거래           │ {original_stats['losses']:>14}개 │ {ml_stats['losses']:>14}개 │ {losses_diff:+15.0f}개 │")

    print("├─────────────────────┼──────────────────┼──────────────────┼──────────────────┤")

    # 승률
    wr_diff = ml_stats['win_rate'] - original_stats['win_rate']
    wr_symbol = "📈" if wr_diff > 0 else "📉" if wr_diff < 0 else "➡️"
    print(f"│ 승률                │ {original_stats['win_rate']:>13.1f}%  │ {ml_stats['win_rate']:>13.1f}%  │ {wr_symbol} {wr_diff:+11.1f}%p │")

    # 평균 수익률
    ap_diff = ml_stats['avg_profit'] - original_stats['avg_profit']
    ap_symbol = "📈" if ap_diff > 0 else "📉" if ap_diff < 0 else "➡️"
    print(f"│ 평균 수익률         │ {original_stats['avg_profit']:>13.2f}%  │ {ml_stats['avg_profit']:>13.2f}%  │ {ap_symbol} {ap_diff:+11.2f}%p │")

    # 총 수익률
    tp_diff = ml_stats['total_profit'] - original_stats['total_profit']
    tp_symbol = "📈" if tp_diff > 0 else "📉" if tp_diff < 0 else "➡️"
    print(f"│ 총 수익률           │ {original_stats['total_profit']:>13.2f}%  │ {ml_stats['total_profit']:>13.2f}%  │ {tp_symbol} {tp_diff:+11.2f}%  │")

    print("└─────────────────────┴──────────────────┴──────────────────┴──────────────────┘")

    # 개선 효과 분석
    print("\n" + "=" * 80)
    print("📈 ML 필터 효과 분석")
    print("=" * 80)

    if wr_diff > 0:
        print(f"✅ 승률이 {wr_diff:.1f}%p 향상되었습니다!")
    elif wr_diff < 0:
        print(f"⚠️  승률이 {abs(wr_diff):.1f}%p 하락했습니다.")
    else:
        print(f"➡️  승률 변화가 없습니다.")

    if ap_diff > 0:
        print(f"✅ 평균 수익률이 {ap_diff:.2f}%p 향상되었습니다!")
    elif ap_diff < 0:
        print(f"⚠️  평균 수익률이 {abs(ap_diff):.2f}%p 하락했습니다.")
    else:
        print(f"➡️  평균 수익률 변화가 없습니다.")

    # 필터링 효과
    blocked = original_stats['total'] - ml_stats['total']
    blocked_pct = blocked / original_stats['total'] * 100 if original_stats['total'] > 0 else 0

    print(f"\n🚫 ML 필터가 {blocked}개 신호를 차단했습니다 ({blocked_pct:.1f}%)")

    # 차단된 신호 중 패배 비율 추정
    prevented_losses = original_stats['losses'] - ml_stats['losses']
    if blocked > 0:
        prevented_loss_rate = prevented_losses / blocked * 100 if blocked > 0 else 0
        print(f"   → 차단된 신호 중 약 {prevented_losses}개가 패배 거래였을 것으로 추정 ({prevented_loss_rate:.1f}%)")

    print("\n" + "=" * 80)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='ML 필터 적용 전후 성과 비교')
    parser.add_argument('--original-dir', default='signal_replay_log',
                       help='원본 백테스트 결과 디렉토리')
    parser.add_argument('--ml-dir', default='signal_replay_log_ml',
                       help='ML 필터 적용 결과 디렉토리')
    parser.add_argument('--detail', action='store_true',
                       help='일별 상세 결과 출력')

    args = parser.parse_args()

    print("🔍 백테스트 결과 분석 중...")

    # 원본 분석
    print(f"\n📂 원본 분석: {args.original_dir}")
    original_stats, original_daily = analyze_directory(args.original_dir, 'signal_new2_replay_*.txt')
    print(f"   분석 완료: {len(original_daily)}일, {original_stats['total']}개 신호")

    # ML 필터 적용 결과 분석
    print(f"\n📂 ML 필터 분석: {args.ml_dir}")
    ml_stats, ml_daily = analyze_directory(args.ml_dir, 'signal_ml_replay_*.txt')
    print(f"   분석 완료: {len(ml_daily)}일, {ml_stats['total']}개 신호")

    # 비교 결과 출력
    print_comparison(original_stats, ml_stats)

    # 일별 상세 결과 (옵션)
    if args.detail and original_daily and ml_daily:
        print("\n" + "=" * 80)
        print("📅 일별 상세 비교")
        print("=" * 80)

        # 날짜별 매칭
        original_by_date = {d['date']: d for d in original_daily}
        ml_by_date = {d['date']: d for d in ml_daily}

        all_dates = sorted(set(original_by_date.keys()) | set(ml_by_date.keys()))

        print("\n날짜       | 원본 신호 | ML 신호 | 원본 승률 | ML 승률 | 승률 변화")
        print("-" * 75)

        for date in all_dates[:10]:  # 최근 10일만 출력
            orig = original_by_date.get(date, {'total': 0, 'win_rate': 0})
            ml = ml_by_date.get(date, {'total': 0, 'win_rate': 0})

            wr_diff = ml['win_rate'] - orig['win_rate']
            wr_symbol = "📈" if wr_diff > 5 else "📉" if wr_diff < -5 else "➡️"

            print(f"{date} | {orig['total']:>7}개 | {ml['total']:>6}개 | "
                  f"{orig['win_rate']:>7.1f}% | {ml['win_rate']:>6.1f}% | "
                  f"{wr_symbol} {wr_diff:+6.1f}%p")


if __name__ == "__main__":
    main()
