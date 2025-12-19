# -*- coding: utf-8 -*-
"""
빠른 전략 비교 도구
generate_statistics.py를 활용한 간단한 비교

사용법:
python quick_compare.py
"""

import subprocess
import sys


def run_statistics(start_date, end_date, label=""):
    """통계 생성 및 결과 파싱"""
    print(f"\n{'='*60}")
    print(f"[{label}] 백테스트 실행 중...")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"{'='*60}\n")

    cmd = [
        'python', '-X', 'utf8',
        'generate_statistics.py',
        '--start', start_date,
        '--end', end_date
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')

    if result.returncode != 0:
        print(f"오류 발생: {result.stderr}")
        return None

    # 결과 파싱
    output = result.stdout
    lines = output.split('\n')

    stats = {}
    for line in lines:
        if '총 거래:' in line:
            parts = line.split()
            stats['trades'] = int(parts[2].replace('개', ''))
        elif '승률:' in line and '%' in line:
            parts = line.split()
            stats['win_rate'] = float(parts[2].replace('%', ''))
        elif '총 수익금:' in line:
            parts = line.split()
            profit_str = parts[3].replace('원', '').replace(',', '')
            stats['profit'] = int(profit_str)
        elif '거래당 평균:' in line:
            parts = line.split()
            avg_str = parts[3].replace('원', '').replace(',', '')
            stats['avg'] = int(avg_str)

    return stats


def main():
    print("\n" + "="*60)
    print("빠른 전략 비교 도구")
    print("="*60)

    # 현재 전략 (기본)
    print("\n[1/3] 현재 전략 (기본 설정) 테스트 중...")
    baseline = run_statistics('20251001', '20251029', "기본 전략")

    if not baseline:
        print("기본 전략 실행 실패")
        return 1

    print(f"\n결과:")
    print(f"  총 거래: {baseline.get('trades', 0)}건")
    print(f"  승률: {baseline.get('win_rate', 0):.1f}%")
    print(f"  총 수익: {baseline.get('profit', 0):+,}원")
    print(f"  거래당 평균: {baseline.get('avg', 0):+,}원")

    # TODO: 다른 전략들도 테스트
    # 현재는 generate_statistics.py가 파라미터를 받지 않으므로
    # signal_replay.py를 수정해야 함

    print("\n" + "="*60)
    print("비교 완료!")
    print("="*60 + "\n")

    return 0


if __name__ == '__main__':
    sys.exit(main())
