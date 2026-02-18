#!/usr/bin/env python3
"""
병합 ML 모델 (ml_model_merged.pkl) 배치 신호 리플레이

기존 batch_signal_replay_ml.py와 동일하지만:
- ml_model_merged.pkl 사용 (AUC 0.7508)
- 최적 threshold 0.6 사용 (77.4% 승률)
- 출력 폴더: signal_replay_log_ml_merged

사용법:
python batch_signal_replay_ml_merged.py -s 20250901 -e 20251226 -o test_results_final
"""

import argparse
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime, timedelta
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count


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
        # 주말 제외
        if current.weekday() < 5:
            dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)

    return dates


def run_signal_replay_ml_merged(date, output_dir, time_range="9:00-16:00", ml_threshold=0.6):
    """
    병합 ML 모델로 signal_replay 실행
    """
    original_cwd = os.getcwd()

    # 출력 디렉토리 생성
    os.makedirs(output_dir, exist_ok=True)

    # 시간 범위를 파일명 형식으로 변환
    start_time = time_range.split('-')[0]
    hour = start_time.split(':')[0]
    minute = start_time.split(':')[1] if ':' in start_time else '0'
    time_parts = f"{hour}_{minute}_0"

    # 임시 파일명 (필터링 전)
    temp_filename = os.path.join(output_dir, f"signal_replay_{date}_{time_parts}_temp.txt")
    # 최종 파일명 (ML 필터링 후)
    final_filename = os.path.join(output_dir, f"signal_ml_merged_replay_{date}_{time_parts}.txt")

    try:
        # 1단계: signal_replay 실행
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
                'message': f"백테스트 오류: {error_msg}",
                'stats': {}
            }

        if not os.path.exists(abs_temp_filename):
            return {
                'date': date,
                'success': False,
                'message': f"백테스트 출력 파일 없음",
                'stats': {}
            }

        # 2단계: 병합 ML 필터 적용 (apply_ml_filter_merged.py 사용)
        abs_final_filename = os.path.abspath(final_filename)
        apply_ml_filter_path = os.path.join(original_cwd, 'apply_ml_filter_merged.py')

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
            # 임시 파일 삭제
            if os.path.exists(abs_temp_filename):
                os.remove(abs_temp_filename)

            # ML 필터 결과 파싱
            stats = {}
            if ml_result.stdout:
                for line in ml_result.stdout.split('\n'):
                    if '총 신호:' in line:
                        try:
                            stats['total'] = int(line.split(':')[1].split('개')[0].strip())
                        except:
                            pass
                    elif '통과:' in line:
                        try:
                            stats['passed'] = int(line.split(':')[1].split('개')[0].strip())
                        except:
                            pass
                    elif '차단:' in line:
                        try:
                            stats['blocked'] = int(line.split(':')[1].split('개')[0].strip())
                        except:
                            pass

            return {
                'date': date,
                'success': True,
                'message': f"완료",
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
    print("=" * 70)
    print("병합 ML 모델 (ml_model_merged.pkl) 배치 신호 리플레이")
    print("=" * 70)

    parser = argparse.ArgumentParser(
        description="병합 ML 모델로 날짜 범위 signal_replay 배치 실행"
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
        "--output", "-o",
        default="signal_replay_log_ml_merged",
        help="출력 디렉토리 (기본: signal_replay_log_ml_merged)"
    )

    parser.add_argument(
        "--time-range",
        default="9:00-16:00",
        help="시간 범위 (기본: 9:00-16:00)"
    )

    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=0.6,  # 최적 임계값
        help="ML 승률 임계값 (기본: 0.6 = 60%%, 병합 모델 최적값)"
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
        help="순차 실행 모드"
    )

    args = parser.parse_args()

    if args.start > args.end:
        print("오류: 시작 날짜가 종료 날짜보다 늦습니다.")
        sys.exit(1)

    # 날짜 범위 생성
    dates = generate_date_range(args.start, args.end)

    if not dates:
        print("오류: 처리할 날짜가 없습니다.")
        sys.exit(1)

    print(f"\n처리 대상: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")
    print(f"시간 범위: {args.time_range}")
    print(f"ML 모델: ml_model_merged.pkl (AUC 0.7508)")
    print(f"ML 임계값: {args.threshold:.1%}")
    print(f"출력 디렉토리: {args.output}")

    if args.sequential:
        print(f"실행 모드: 순차")
    else:
        print(f"실행 모드: 병렬 ({args.workers} 워커)")
    print()

    # 결과 통계
    success_count = 0
    total_signals = 0
    total_passed = 0
    total_blocked = 0

    if args.sequential:
        # 순차 실행
        for i, date in enumerate(dates, 1):
            print(f"[{i}/{len(dates)}] {date} 처리 중...")
            result = run_signal_replay_ml_merged(date, args.output, args.time_range, args.threshold)

            if result['success']:
                success_count += 1
                print(f"   ✓ {result['message']}")
                if result['stats']:
                    stats = result['stats']
                    total_signals += stats.get('total', 0)
                    total_passed += stats.get('passed', 0)
                    total_blocked += stats.get('blocked', 0)
                    print(f"   신호: {stats.get('total', 0)}개, 통과: {stats.get('passed', 0)}개, 차단: {stats.get('blocked', 0)}개")
            else:
                print(f"   ✗ {result['message']}")
            print()
    else:
        # 병렬 실행
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(run_signal_replay_ml_merged, date, args.output, args.time_range, args.threshold): date
                for date in dates
            }

            completed = 0
            for future in as_completed(futures):
                date = futures[future]
                completed += 1

                try:
                    result = future.result()
                    print(f"[{completed}/{len(dates)}] {date}: ", end="")

                    if result['success']:
                        success_count += 1
                        print(f"✓ 완료", end="")
                        if result['stats']:
                            stats = result['stats']
                            total_signals += stats.get('total', 0)
                            total_passed += stats.get('passed', 0)
                            total_blocked += stats.get('blocked', 0)
                            print(f" (신호 {stats.get('total', 0)}개, 통과 {stats.get('passed', 0)}개)")
                        else:
                            print()
                    else:
                        print(f"✗ {result['message']}")

                except Exception as e:
                    print(f"[{completed}/{len(dates)}] {date}: ✗ 예외: {e}")

    print()
    print("=" * 70)
    print(f"배치 실행 완료: {success_count}/{len(dates)}일 성공")

    if total_signals > 0:
        print()
        print(f"전체 통계:")
        print(f"  총 신호: {total_signals}개")
        print(f"  통과: {total_passed}개 ({total_passed/total_signals*100:.1f}%)")
        print(f"  차단: {total_blocked}개 ({total_blocked/total_signals*100:.1f}%)")

    print()
    print("다음 단계:")
    print(f"  python generate_statistics.py --start {dates[0]} --end {dates[-1]} --input-dir {args.output} --output-dir {args.output}")


if __name__ == "__main__":
    main()
