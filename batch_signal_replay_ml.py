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
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime, timedelta
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count

# ML 설정 불러오기
from config.ml_settings import MLSettings


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


def run_signal_replay_ml(date, time_range="9:00-16:00", ml_threshold=0.5):
    """
    지정된 날짜에 대해 ML 필터가 적용된 signal_replay 실행

    Returns:
        dict: {
            'date': str,
            'success': bool,
            'message': str,
            'stats': dict  # 총 신호, 통과, 차단 수
        }
    """
    # 현재 작업 디렉토리 저장
    original_cwd = os.getcwd()

    # signal_replay_log_ml 폴더 생성 (절대 경로)
    log_dir = os.path.join(original_cwd, "signal_replay_log_ml")
    os.makedirs(log_dir, exist_ok=True)

    # 시간 범위를 파일명 형식으로 변환 (9:00-16:00 -> 9_9_0)
    start_time = time_range.split('-')[0]
    hour = start_time.split(':')[0]
    minute = start_time.split(':')[1] if ':' in start_time else '0'
    time_parts = f"{hour}_{minute}_0"

    # 임시 파일명 (필터링 전)
    temp_filename = os.path.join(log_dir, f"signal_replay_{date}_{time_parts}_temp.txt")
    # 최종 파일명 (필터링 후)
    final_filename = os.path.join(log_dir, f"signal_ml_replay_{date}_{time_parts}.txt")

    try:
        # 1단계: 일반 signal_replay 실행 (절대 경로 사용)
        abs_temp_filename = os.path.abspath(temp_filename)

        cmd = [
            sys.executable, '-m', 'utils.signal_replay',
            '--date', date,
            '--export', 'txt',
            '--txt-path', abs_temp_filename
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=original_cwd,
            encoding='utf-8',
            errors='ignore'
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "알 수 없는 오류"
            return {
                'date': date,
                'success': False,
                'message': f"백테스트 오류 (코드: {result.returncode}): {error_msg}",
                'stats': {}
            }

        # 임시 파일이 생성되었는지 확인 (절대 경로로)
        if not os.path.exists(abs_temp_filename):
            return {
                'date': date,
                'success': False,
                'message': f"백테스트 출력 파일 없음: {abs_temp_filename}",
                'stats': {}
            }

        # 2단계: ML 필터 적용 (절대 경로 사용)
        abs_final_filename = os.path.abspath(final_filename)
        apply_ml_filter_path = os.path.join(original_cwd, 'apply_ml_filter.py')

        ml_cmd = [
            sys.executable, apply_ml_filter_path,
            abs_temp_filename,
            '--output', abs_final_filename,
            '--threshold', str(ml_threshold)
        ]

        ml_result = subprocess.run(
            ml_cmd,
            capture_output=True,
            text=True,
            cwd=original_cwd,
            encoding='utf-8',
            errors='ignore'
        )

        if ml_result.returncode == 0:
            # 임시 파일 삭제 (절대 경로로)
            if os.path.exists(abs_temp_filename):
                os.remove(abs_temp_filename)

            # ML 필터 결과 파싱
            stats = {}
            if ml_result.stdout:
                for line in ml_result.stdout.split('\n'):
                    if '총 신호:' in line:
                        stats['total'] = int(line.split(':')[1].split('개')[0].strip())
                    elif '통과:' in line:
                        stats['passed'] = int(line.split(':')[1].split('개')[0].strip())
                    elif '차단:' in line:
                        stats['blocked'] = int(line.split(':')[1].split('개')[0].strip())

            return {
                'date': date,
                'success': True,
                'message': f"완료: {final_filename}",
                'stats': stats
            }
        else:
            error_msg = ml_result.stderr.strip() if ml_result.stderr else "알 수 없는 오류"
            return {
                'date': date,
                'success': False,
                'message': f"ML 필터 오류: {error_msg}",
                'stats': {}
            }

    except Exception as e:
        return {
            'date': date,
            'success': False,
            'message': f"실행 오류: {str(e)}",
            'stats': {}
        }


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

    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=None,
        help=f"ML 승률 임계값 (기본: config/ml_settings.py의 ML_THRESHOLD = {MLSettings.ML_THRESHOLD})"
    )

    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=min(4, cpu_count()),
        help=f"병렬 처리 워커 수 (기본: min(4, CPU 코어 수={cpu_count()}))"
    )

    parser.add_argument(
        "--sequential",
        action="store_true",
        help="순차 실행 모드 (병렬 처리 비활성화)"
    )

    args = parser.parse_args()

    # threshold가 지정되지 않으면 설정 파일에서 가져오기
    if args.threshold is None:
        args.threshold = MLSettings.ML_THRESHOLD
        print(f"ℹ️  ML 임계값을 config/ml_settings.py에서 로드: {args.threshold}")

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
    print(f"🎯 ML 임계값: {args.threshold:.1%}")

    if args.sequential:
        print(f"🔄 실행 모드: 순차 실행")
    else:
        print(f"⚡ 실행 모드: 병렬 실행 ({args.workers} 워커)")
    print()

    # 결과 통계
    success_count = 0
    total_signals = 0
    total_passed = 0
    total_blocked = 0

    if args.sequential:
        # 순차 실행 모드
        for i, date in enumerate(dates, 1):
            print(f"[{i}/{len(dates)}] 🤖 ML 필터 적용: {date}")
            result = run_signal_replay_ml(date, args.time_range, args.threshold)

            if result['success']:
                success_count += 1
                print(f"   ✅ {result['message']}")
                if result['stats']:
                    stats = result['stats']
                    total_signals += stats.get('total', 0)
                    total_passed += stats.get('passed', 0)
                    total_blocked += stats.get('blocked', 0)
                    print(f"   총 신호: {stats.get('total', 0)}개")
                    print(f"   통과: {stats.get('passed', 0)}개")
                    print(f"   차단: {stats.get('blocked', 0)}개")
            else:
                print(f"   ❌ {result['message']}")
            print()
    else:
        # 병렬 실행 모드
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            # 작업 제출
            futures = {
                executor.submit(run_signal_replay_ml, date, args.time_range, args.threshold): date
                for date in dates
            }

            # 완료된 작업 처리
            completed = 0
            for future in as_completed(futures):
                date = futures[future]
                completed += 1

                try:
                    result = future.result()
                    print(f"[{completed}/{len(dates)}] {date}: ", end="")

                    if result['success']:
                        success_count += 1
                        print(f"✅ 완료", end="")
                        if result['stats']:
                            stats = result['stats']
                            total_signals += stats.get('total', 0)
                            total_passed += stats.get('passed', 0)
                            total_blocked += stats.get('blocked', 0)
                            print(f" (신호 {stats.get('total', 0)}개, 통과 {stats.get('passed', 0)}개, 차단 {stats.get('blocked', 0)}개)")
                        else:
                            print()
                    else:
                        print(f"❌ {result['message']}")

                except Exception as e:
                    print(f"[{completed}/{len(dates)}] {date}: ❌ 예외 발생: {e}")

    print()
    print("=" * 60)
    print(f"🏁 배치 실행 완료: {success_count}/{len(dates)}일 성공")

    if total_signals > 0:
        print()
        print(f"📊 전체 통계:")
        print(f"   총 신호: {total_signals}개")
        print(f"   통과: {total_passed}개 ({total_passed/total_signals*100:.1f}%)")
        print(f"   차단: {total_blocked}개 ({total_blocked/total_signals*100:.1f}%)")

    if success_count < len(dates):
        print()
        print("⚠️ 일부 날짜에서 오류가 발생했습니다. 로그를 확인해주세요.")


if __name__ == "__main__":
    main()