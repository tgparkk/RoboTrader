#!/usr/bin/env python3
"""
배치 신호 리플레이 스크립트
날짜 범위를 입력받아 해당 기간의 모든 날짜에 대해 signal_replay를 실행합니다.

사용법:
python batch_signal_replay.py --start 20250826 --end 20250828
python batch_signal_replay.py --start 20250826 --end 20250828 --time-range 9:00-16:00
"""

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
import os


def parse_date(date_str):
    """날짜 문자열을 datetime 객체로 변환"""
    try:
        return datetime.strptime(date_str, '%Y%m%d')
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_str}. Use YYYYMMDD format.")


def generate_date_range(start_date, end_date):
    """시작일부터 종료일까지의 날짜 리스트 생성"""
    dates = []
    current = start_date
    
    while current <= end_date:
        # 주말 제외 (월-금만)
        if current.weekday() < 5:  # 0=Monday, 6=Sunday
            dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)
    
    return dates


def run_signal_replay(date, time_range="9:00-16:00"):
    """지정된 날짜에 대해 signal_replay 실행"""
    # 시간 범위를 파일명 형식으로 변환 (9:00-16:00 -> 9_9_0)
    start_time = time_range.split('-')[0]
    hour = start_time.split(':')[0]
    minute = start_time.split(':')[1] if ':' in start_time else '0'
    time_parts = f"{hour}_{minute}_0"
    
    txt_filename = f"signal_qqw_replay_{date}_{time_parts}.txt"
    
    # 명령어 구성
    cmd = [
        sys.executable, '-m', 'utils.signal_replay',
        '--date', date,
        '--export', 'txt',
        '--txt-path', txt_filename
    ]
    
    print(f"🔄 실행 중: {date} ({txt_filename})")
    print(f"   명령어: {' '.join(cmd)}")
    
    try:
        # subprocess로 명령 실행 (인코딩 문제 해결)
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            cwd=os.getcwd(),
            encoding='utf-8',
            errors='ignore'  # 디코딩 오류 무시
        )
        
        if result.returncode == 0:
            print(f"✅ 완료: {date}")
            if result.stdout and result.stdout.strip():
                print(f"   출력: {result.stdout.strip()}")
        else:
            print(f"❌ 오류: {date} (반환코드: {result.returncode})")
            if result.stderr and result.stderr.strip():
                print(f"   에러: {result.stderr.strip()}")
                
    except Exception as e:
        print(f"❌ 실행 오류 ({date}): {e}")


def main():
    parser = argparse.ArgumentParser(
        description="날짜 범위에 대해 signal_replay를 배치 실행합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python batch_signal_replay.py --start 20250826 --end 20250828
  python batch_signal_replay.py --start 20250826 --end 20250828 --time-range 9:00-15:30
  python batch_signal_replay.py -s 20250826 -e 20250828
        """
    )
    
    parser.add_argument(
        '--start', '-s',
        type=parse_date,
        required=True,
        help='시작 날짜 (YYYYMMDD 형식, 예: 20250826)'
    )
    
    parser.add_argument(
        '--end', '-e', 
        type=parse_date,
        required=True,
        help='종료 날짜 (YYYYMMDD 형식, 예: 20250828)'
    )
    
    parser.add_argument(
        '--time-range', '-t',
        type=str,
        default='9:00-16:00',
        help='시간 범위 (기본값: 9:00-16:00, 예: 9:00-15:30)'
    )
    
    parser.add_argument(
        '--include-weekends',
        action='store_true',
        help='주말 포함 (기본적으로 평일만 처리)'
    )
    
    args = parser.parse_args()
    
    # 날짜 범위 검증
    if args.start > args.end:
        print("❌ 오류: 시작 날짜가 종료 날짜보다 늦습니다.")
        sys.exit(1)
    
    # 날짜 리스트 생성
    if args.include_weekends:
        dates = []
        current = args.start
        while current <= args.end:
            dates.append(current.strftime('%Y%m%d'))
            current += timedelta(days=1)
    else:
        dates = generate_date_range(args.start, args.end)
    
    if not dates:
        print("❌ 처리할 날짜가 없습니다.")
        sys.exit(1)
    
    print(f"📅 처리할 날짜: {len(dates)}개")
    print(f"   범위: {dates[0]} ~ {dates[-1]}")
    print(f"   시간: {args.time_range}")
    print(f"   날짜 목록: {', '.join(dates)}")
    print("=" * 50)
    
    # 각 날짜에 대해 signal_replay 실행
    success_count = 0
    for i, date in enumerate(dates, 1):
        print(f"\n[{i}/{len(dates)}] {date} 처리 중...")
        
        try:
            run_signal_replay(date, args.time_range)
            success_count += 1
        except KeyboardInterrupt:
            print("\n\n⚠️  사용자가 중단했습니다.")
            break
        except Exception as e:
            print(f"❌ 처리 오류 ({date}): {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 배치 처리 완료: {success_count}/{len(dates)}개 성공")
    
    if success_count < len(dates):
        print("⚠️  일부 날짜에서 오류가 발생했습니다. 위의 로그를 확인해주세요.")


if __name__ == '__main__':
    main()