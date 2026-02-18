"""
장중 자동 분봉 API 테스트 스크립트
- 오늘(2026-01-27) 화요일에만 실행
- 10:30, 12:00, 14:00에 자동 테스트
- 봇과 독립적으로 실행 가능
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.korean_time import now_kst
from test_minute_api_response import initialize_api, test_minute_api_response


def should_run_today():
    """오늘 실행 가능한지 확인 (2026-01-27만)"""
    current = now_kst()
    target_date = "20260127"
    current_date = current.strftime("%Y%m%d")

    return current_date == target_date


def is_market_hours():
    """장중 시간인지 확인 (장 시작 전도 포함)"""
    current = now_kst()
    hour = current.hour

    # 평일 여부 확인
    if current.weekday() >= 5:  # 토(5), 일(6)
        return False

    # 06:00 ~ 15:30 (장 시작 전부터 포함)
    # 테스트를 위해 새벽부터 허용
    if hour < 6:
        return False

    if hour >= 16:
        return False

    return True


def get_next_test_time():
    """다음 테스트 실행 시간 계산"""
    current = now_kst()

    # 테스트 실행 시간: 10:30, 12:00, 14:00
    test_times = [
        current.replace(hour=10, minute=30, second=0, microsecond=0),
        current.replace(hour=12, minute=0, second=0, microsecond=0),
        current.replace(hour=14, minute=0, second=0, microsecond=0),
    ]

    # 현재 시간 이후의 다음 테스트 시간 찾기
    for test_time in test_times:
        if current < test_time:
            return test_time

    # 오늘 모든 테스트 완료
    return None


def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("장중 자동 분봉 API 테스트")
    print("=" * 80)
    print(f"현재 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 날짜 확인
    if not should_run_today():
        print("[종료] 오늘은 테스트 실행일(2026-01-27)이 아닙니다.")
        return

    print("[OK] 오늘은 테스트 실행일입니다.")
    print()

    # API 인증
    print("API 인증 중...")
    if not initialize_api():
        print("[ERROR] API 인증 실패")
        return

    print()

    # 테스트 실행 기록
    completed_tests = []

    while True:
        current_time = now_kst()

        # 장 마감 후인지 확인 (16:00 이후)
        if current_time.hour >= 16:
            print(f"[{current_time.strftime('%H:%M:%S')}] 장 마감 시간입니다. 테스트를 종료합니다.")
            break

        # 평일이 아니면 종료
        if current_time.weekday() >= 5:
            print(f"[{current_time.strftime('%H:%M:%S')}] 오늘은 주말입니다. 테스트를 종료합니다.")
            break

        # 다음 테스트 시간 확인
        next_test = get_next_test_time()

        if next_test is None:
            print(f"[{current_time.strftime('%H:%M:%S')}] 오늘 모든 테스트가 완료되었습니다.")
            break

        # 다음 테스트까지 대기
        wait_seconds = (next_test - current_time).total_seconds()

        if wait_seconds > 0:
            next_test_str = next_test.strftime('%H:%M')

            # 이미 완료된 테스트인지 확인
            if next_test_str in completed_tests:
                print(f"[{current_time.strftime('%H:%M:%S')}] {next_test_str} 테스트는 이미 완료되었습니다.")
                time.sleep(60)  # 1분 대기
                continue

            print(f"[{current_time.strftime('%H:%M:%S')}] 다음 테스트: {next_test_str} (약 {int(wait_seconds/60)}분 대기)")
            print()

            # 1분마다 상태 출력
            while wait_seconds > 0:
                time.sleep(min(60, wait_seconds))
                wait_seconds = (next_test - now_kst()).total_seconds()

                if wait_seconds > 60:
                    print(f"[{now_kst().strftime('%H:%M:%S')}] {next_test_str} 테스트까지 약 {int(wait_seconds/60)}분 남음...")

        # 테스트 실행
        current_time = now_kst()
        test_time_str = current_time.strftime('%H:%M')

        print()
        print("=" * 80)
        print(f"테스트 실행: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        print()

        try:
            # 테스트 실행
            test_minute_api_response()

            # 완료 기록
            completed_tests.append(test_time_str)

            print()
            print(f"[OK] {test_time_str} 테스트 완료")
            print()

        except KeyboardInterrupt:
            print()
            print("[중단] 사용자가 테스트를 중단했습니다.")
            break
        except Exception as e:
            print()
            print(f"[ERROR] 테스트 실행 중 오류: {e}")
            import traceback
            traceback.print_exc()
            print()

        # 다음 테스트까지 대기 (최소 5분)
        time.sleep(300)

    # 최종 요약
    print()
    print("=" * 80)
    print("테스트 종료 요약")
    print("=" * 80)
    print(f"완료된 테스트: {len(completed_tests)}건")
    if completed_tests:
        for test_time in completed_tests:
            print(f"  - {test_time}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[중단] 프로그램을 종료합니다.")
    except Exception as e:
        print(f"\n[ERROR] 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
