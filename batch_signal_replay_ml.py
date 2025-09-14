#!/usr/bin/env python3
"""
🤖 ML 필터 적용된 배치 신호 리플레이 스크립트
날짜 범위를 입력받아 해당 기간의 모든 날짜에 대해 ML 필터가 적용된 signal_replay를 실행합니다.

사용법:
python batch_signal_replay_ml.py --start 20250901 --end 20250912
python batch_signal_replay_ml.py -s 20250901 -e 20250912
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


def run_signal_replay_ml(date, time_range="9:00-16:00"):
    """지정된 날짜에 대해 ML 필터가 적용된 signal_replay 실행"""
    # signal_replay_log 폴더 생성
    log_dir = "signal_replay_log"
    os.makedirs(log_dir, exist_ok=True)
    
    # 시간 범위를 파일명 형식으로 변환 (9:00-16:00 -> 9_9_0)
    start_time = time_range.split('-')[0]
    hour = start_time.split(':')[0]
    minute = start_time.split(':')[1] if ':' in start_time else '0'
    time_parts = f"{hour}_{minute}_0"
    
    # ML 필터 적용된 결과 파일명
    txt_filename = os.path.join(log_dir, f"signal_ml_replay_{date}_{time_parts}.txt")
    
    # 명령어 구성 (signal_replay_ml.py 사용)
    cmd = [
        sys.executable, '-m', 'utils.signal_replay_ml',
        '--date', date,
        '--export', 'txt',
        '--txt-path', txt_filename
    ]
    
    print(f"🤖 ML 필터 적용 실행: {date}")
    print(f"   출력 파일: {txt_filename}")
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
    print("🤖 ML 필터 적용된 배치 신호 리플레이 시스템")
    print("=" * 60)
    
    parser = argparse.ArgumentParser(
        description="🤖 ML 필터가 적용된 날짜 범위 signal_replay 배치 실행",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python batch_signal_replay_ml.py --start 20250901 --end 20250912
  python batch_signal_replay_ml.py -s 20250901 -e 20250912
  python batch_signal_replay_ml.py -s 20250901 -e 20250912 --time-range 9:00-15:30

기능:
  - 각 날짜마다 ML 예측기를 사용하여 매수 신호 필터링
  - 승률이 낮은 신호는 자동으로 차단
  - ML 예측 결과가 로그에 상세하게 표시됨
  - 결과 파일명에 'ml' 표시로 일반 버전과 구분
        """
    )
    
    parser.add_argument(
        "--start", "-s", 
        type=parse_date, 
        required=True,
        help="시작 날짜 (YYYYMMDD)"
    )
    
    parser.add_argument(
        "--end", "-e", 
        type=parse_date, 
        required=True,
        help="종료 날짜 (YYYYMMDD)"
    )
    
    parser.add_argument(
        "--time-range", 
        default="9:00-16:00",
        help="시간 범위 (기본: 9:00-16:00)"
    )
    
    args = parser.parse_args()
    
    if args.start > args.end:
        print("❌ 시작 날짜가 종료 날짜보다 늦습니다.")
        sys.exit(1)
    
    # 날짜 범위 생성
    dates = generate_date_range(args.start, args.end)
    
    if not dates:
        print("❌ 처리할 날짜가 없습니다 (주말 제외)")
        sys.exit(1)
    
    print(f"📅 처리 대상: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")
    print(f"⏰ 시간 범위: {args.time_range}")
    print()
    
    # 각 날짜에 대해 실행
    success_count = 0
    for i, date in enumerate(dates, 1):
        print(f"[{i}/{len(dates)}] ", end="")
        try:
            run_signal_replay_ml(date, args.time_range)
            success_count += 1
        except KeyboardInterrupt:
            print(f"\n⚠️ 사용자 중단")
            break
        except Exception as e:
            print(f"❌ 예외 발생 ({date}): {e}")
        print()  # 구분선
    
    print("=" * 60)
    print(f"🏁 배치 실행 완료: {success_count}/{len(dates)}일 성공")
    
    if success_count < len(dates):
        print("⚠️ 일부 날짜에서 오류가 발생했습니다. 로그를 확인해주세요.")


if __name__ == "__main__":
    main()