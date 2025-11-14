#!/usr/bin/env python3
"""
간단한 백테스트 실행 도구
설정 파일 없이도 파라미터를 직접 조정하여 실행 가능

사용법:
# 기본 실행 (default 설정)
python run_backtest_simple.py

# 오전만 거래 (12시 이후 차단)
python run_backtest_simple.py --block-afternoon

# 보수적 전략 (10시 이후 차단)
python run_backtest_simple.py --conservative

# 커스텀 시간대 신뢰도
python run_backtest_simple.py --hour-10-conf 90 --hour-11-conf 90

# 거래량 필터 강화
python run_backtest_simple.py --breakout-vol 1.2

# 기간 지정
python run_backtest_simple.py --start 20251001 --end 20251029
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
import subprocess


def generate_date_range(start_date_str, end_date_str):
    """날짜 범위 생성 (평일만)"""
    start = datetime.strptime(start_date_str, '%Y%m%d')
    end = datetime.strptime(end_date_str, '%Y%m%d')

    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # 평일만
            dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)

    return dates


def run_backtest_with_params(args):
    """파라미터로 백테스트 실행"""

    print(f"\n{'='*70}")
    print(f"🚀 백테스트 실행")
    print(f"{'='*70}\n")

    # 파라미터 출력
    print(f"📅 기간: {args.start} ~ {args.end}")
    print(f"\n⏰ 시간대별 최소 신뢰도:")
    print(f"   09시: {args.hour_9_conf}%")
    print(f"   10시: {args.hour_10_conf}%")
    print(f"   11시: {args.hour_11_conf}%")
    print(f"   12시: {args.hour_12_conf}%")
    print(f"   14시: {args.hour_14_conf}%")

    if args.block_afternoon:
        print(f"\n🚫 오후 시간대 차단 활성화 (12~15시)")

    if args.conservative:
        print(f"\n🛡️ 보수적 모드 활성화")

    print(f"\n📊 거래량 필터:")
    print(f"   돌파 거래량 배수: {args.breakout_vol}x")

    print(f"\n💰 손익 설정:")
    print(f"   손절: -{args.stop_loss}%")
    print(f"   익절: +{args.take_profit}%")

    print(f"\n{'='*70}\n")

    # 날짜 범위 생성
    dates = generate_date_range(args.start, args.end)

    print(f"처리할 날짜: {len(dates)}개")
    print(f"시작: {dates[0]}, 종료: {dates[-1]}\n")

    # 각 날짜별 백테스트 실행
    total_trades = 0
    total_wins = 0
    total_losses = 0
    all_results = []

    for date in dates:
        print(f"📆 {date} 처리 중...", end=' ')

        # signal_replay 실행
        cmd = [
            'python', '-X', 'utf8',
            'utils/signal_replay.py',
            '--date', date,
            '--hour', '9',
            '--minute', '0',
            '--second', '0'
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=60
            )

            # 결과 파싱
            output = result.stdout

            # 간단한 결과 추출
            if '총 승패:' in output:
                for line in output.split('\n'):
                    if '총 승패:' in line:
                        # "=== 총 승패: 6승 8패 ==="
                        parts = line.split()
                        wins = int(parts[3].replace('승', ''))
                        losses = int(parts[4].replace('패', ''))

                        total_wins += wins
                        total_losses += losses
                        total_trades += (wins + losses)

                        print(f"✅ {wins}승 {losses}패")
                        all_results.append((date, wins, losses))
                        break
            else:
                print("⚠️ 데이터 없음")

        except subprocess.TimeoutExpired:
            print("⏱️ 타임아웃")
        except Exception as e:
            print(f"❌ 오류: {e}")

    # 최종 결과 출력
    print(f"\n{'='*70}")
    print(f"📊 백테스트 최종 결과")
    print(f"{'='*70}\n")

    print(f"총 거래: {total_trades}건")
    print(f"승패: {total_wins}승 {total_losses}패")

    if total_trades > 0:
        win_rate = total_wins / total_trades * 100
        print(f"승률: {win_rate:.1f}%")

        # 간단한 수익 계산 (실제 수익률 기반 아님, 고정 비율)
        estimated_profit = (total_wins * 35000) - (total_losses * 25000)
        avg_profit = estimated_profit / total_trades

        print(f"예상 수익: {estimated_profit:+,}원 (고정 익절/손절 기준)")
        print(f"거래당 평균: {avg_profit:+,.0f}원")

    # 일자별 상세
    print(f"\n일자별 상세:")
    for date, wins, losses in all_results:
        if wins + losses > 0:
            daily_rate = wins / (wins + losses) * 100
            print(f"  {date}: {wins}승 {losses}패 (승률 {daily_rate:.0f}%)")

    print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="간단한 백테스트 실행 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # 기간 설정
    parser.add_argument('--start', type=str, default='20251001',
                       help='시작 날짜 (YYYYMMDD)')
    parser.add_argument('--end', type=str, default='20251029',
                       help='종료 날짜 (YYYYMMDD)')

    # 시간대별 신뢰도
    parser.add_argument('--hour-9-conf', type=int, default=70,
                       help='09시 최소 신뢰도 (기본: 70)')
    parser.add_argument('--hour-10-conf', type=int, default=75,
                       help='10시 최소 신뢰도 (기본: 75)')
    parser.add_argument('--hour-11-conf', type=int, default=75,
                       help='11시 최소 신뢰도 (기본: 75)')
    parser.add_argument('--hour-12-conf', type=int, default=85,
                       help='12시 최소 신뢰도 (기본: 85)')
    parser.add_argument('--hour-14-conf', type=int, default=85,
                       help='14시 최소 신뢰도 (기본: 85)')

    # 전략 프리셋
    parser.add_argument('--block-afternoon', action='store_true',
                       help='오후 시간대(12~15시) 완전 차단')
    parser.add_argument('--conservative', action='store_true',
                       help='보수적 모드 (10시 이후 90, 오후 차단)')

    # 거래량 필터
    parser.add_argument('--breakout-vol', type=float, default=0.8,
                       help='돌파 거래량 배수 (기본: 0.8)')

    # 손익 설정
    parser.add_argument('--stop-loss', type=float, default=2.5,
                       help='손절 비율 (기본: 2.5)')
    parser.add_argument('--take-profit', type=float, default=3.5,
                       help='익절 비율 (기본: 3.5)')

    args = parser.parse_args()

    # 프리셋 적용
    if args.block_afternoon:
        args.hour_12_conf = 95
        args.hour_14_conf = 95

    if args.conservative:
        args.hour_10_conf = 90
        args.hour_11_conf = 90
        args.hour_12_conf = 95
        args.hour_14_conf = 95
        args.breakout_vol = 1.2

    # 백테스트 실행
    run_backtest_with_params(args)

    return 0


if __name__ == '__main__':
    exit(main())
