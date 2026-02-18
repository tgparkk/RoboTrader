"""
분봉 API 응답 테스트 스크립트
past_data_yn="Y" vs "N" 비교 및 실제 반환 데이터 확인
"""
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from api.kis_chart_api import get_inquire_time_itemchartprice
from utils.korean_time import now_kst
from datetime import datetime, timedelta
import pandas as pd


def initialize_api():
    """API 인증 초기화"""
    from api.kis_auth import auth

    # auth() 함수는 config.settings의 전역 변수를 자동으로 사용
    result = auth(svr='prod', product='01')

    if result:
        print("API 인증 완료")
        return True
    else:
        print("API 인증 실패")
        return False


def test_minute_api_response():
    """분봉 API 응답 테스트"""

    # 테스트 종목: 삼성전자
    test_stock = "005930"

    # 현재 시간 기준으로 완성된 분봉 시간 계산
    current_time = now_kst()

    # 장중 시간이 아니면 최근 거래일의 특정 시간 사용
    if current_time.hour < 9 or current_time.hour >= 16:
        # 전일 14:30 사용
        test_time = current_time.replace(hour=14, minute=30, second=0, microsecond=0)
        if current_time.hour < 9:
            test_time = test_time - timedelta(days=1)
    else:
        # 현재 시간에서 2분 전 (완성된 분봉)
        test_time = current_time - timedelta(minutes=2)
        test_time = test_time.replace(second=0, microsecond=0)

    input_hour = test_time.strftime("%H%M%S")

    print("=" * 80)
    print("분봉 API 응답 테스트")
    print("=" * 80)
    print(f"테스트 종목: {test_stock} (삼성전자)")
    print(f"요청 시간: {input_hour}")
    print(f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 테스트 1: past_data_yn="Y" (과거 데이터 포함)
    print("-" * 80)
    print("테스트 1: past_data_yn='Y' (과거 데이터 포함)")
    print("-" * 80)

    result_y = get_inquire_time_itemchartprice(
        div_code="J",
        stock_code=test_stock,
        input_hour=input_hour,
        past_data_yn="Y"
    )

    if result_y:
        summary_y, chart_y = result_y
        print(f"[OK] 반환된 데이터: {len(chart_y)}건")

        if not chart_y.empty:
            print()
            print("[DATA] 반환된 분봉 시간 범위:")

            if 'time' in chart_y.columns:
                times = chart_y['time'].apply(lambda x: str(int(x)).zfill(6))
                print(f"  첫 번째: {times.iloc[0]}")
                print(f"  마지막: {times.iloc[-1]}")
                print(f"  총 {len(chart_y)}개 분봉")

                # 시간 간격 분석
                if len(chart_y) > 1:
                    time_list = times.tolist()
                    print()
                    print("  전체 시간 목록:")
                    for i, t in enumerate(time_list):
                        if i % 10 == 0 and i > 0:
                            print()
                        print(f"    {t}", end="")
                    print()

            print()
            print("[SAMPLE] 데이터 샘플 (최근 5개):")
            display_cols = ['time', 'close', 'volume'] if 'time' in chart_y.columns else ['datetime', 'close', 'volume']
            available_cols = [col for col in display_cols if col in chart_y.columns]
            print(chart_y[available_cols].tail(5).to_string(index=False))
    else:
        print("[FAIL] 데이터 조회 실패")

    print()

    # 테스트 2: past_data_yn="N" (과거 데이터 제외)
    print("-" * 80)
    print("테스트 2: past_data_yn='N' (과거 데이터 제외)")
    print("-" * 80)

    result_n = get_inquire_time_itemchartprice(
        div_code="J",
        stock_code=test_stock,
        input_hour=input_hour,
        past_data_yn="N"
    )

    if result_n:
        summary_n, chart_n = result_n
        print(f"[OK] 반환된 데이터: {len(chart_n)}건")

        if not chart_n.empty:
            print()
            print("[DATA] 반환된 분봉 시간 범위:")

            if 'time' in chart_n.columns:
                times = chart_n['time'].apply(lambda x: str(int(x)).zfill(6))
                print(f"  첫 번째: {times.iloc[0]}")
                print(f"  마지막: {times.iloc[-1]}")
                print(f"  총 {len(chart_n)}개 분봉")

                # 시간 간격 분석
                if len(chart_n) > 1:
                    time_list = times.tolist()
                    print()
                    print("  전체 시간 목록:")
                    for i, t in enumerate(time_list):
                        if i % 10 == 0 and i > 0:
                            print()
                        print(f"    {t}", end="")
                    print()

            print()
            print("[SAMPLE] 데이터 샘플 (최근 5개):")
            display_cols = ['time', 'close', 'volume'] if 'time' in chart_n.columns else ['datetime', 'close', 'volume']
            available_cols = [col for col in display_cols if col in chart_n.columns]
            print(chart_n[available_cols].tail(5).to_string(index=False))
    else:
        print("[FAIL] 데이터 조회 실패")

    print()

    # 비교 분석
    print("-" * 80)
    print("[COMPARE] 비교 분석")
    print("-" * 80)

    if result_y and result_n:
        chart_y_len = len(chart_y) if result_y else 0
        chart_n_len = len(chart_n) if result_n else 0

        print(f"past_data_yn='Y': {chart_y_len}건")
        print(f"past_data_yn='N': {chart_n_len}건")
        print(f"차이: {chart_y_len - chart_n_len}건")
        print()

        if chart_y_len > 0 and chart_n_len > 0:
            # 시간 범위 비교
            if 'time' in chart_y.columns and 'time' in chart_n.columns:
                time_y_first = str(int(chart_y['time'].iloc[0])).zfill(6)
                time_y_last = str(int(chart_y['time'].iloc[-1])).zfill(6)
                time_n_first = str(int(chart_n['time'].iloc[0])).zfill(6)
                time_n_last = str(int(chart_n['time'].iloc[-1])).zfill(6)

                print("시간 범위 비교:")
                print(f"  Y: {time_y_first} ~ {time_y_last}")
                print(f"  N: {time_n_first} ~ {time_n_last}")
                print()

                # 동일 시간 데이터 비교
                if time_y_last == time_n_last:
                    print("[OK] 마지막 분봉 시간 동일")

                    # 종가 비교
                    if 'close' in chart_y.columns and 'close' in chart_n.columns:
                        close_y = chart_y['close'].iloc[-1]
                        close_n = chart_n['close'].iloc[-1]

                        if close_y == close_n:
                            print(f"[OK] 마지막 분봉 종가 동일: {close_y:,}원")
                        else:
                            print(f"[WARN] 마지막 분봉 종가 다름: Y={close_y:,}원 vs N={close_n:,}원")
                else:
                    print("[WARN] 마지막 분봉 시간 다름")

    print()
    print("=" * 80)
    print("테스트 완료")
    print("=" * 80)

    # 결론
    print()
    print("[RESULT] 결론:")
    if result_y and result_n:
        chart_y_len = len(chart_y) if result_y else 0
        chart_n_len = len(chart_n) if result_n else 0

        if chart_y_len > chart_n_len:
            print(f"  - past_data_yn='Y'는 {chart_y_len}개를 반환 (과거 데이터 포함)")
            print(f"  - past_data_yn='N'는 {chart_n_len}개를 반환 (요청 시점 데이터만)")
            print(f"  - 실시간 업데이트 시 'Y' 사용하면 이미 있는 데이터까지 중복 수신")
        elif chart_y_len == chart_n_len:
            print(f"  - 두 옵션 모두 {chart_y_len}개 반환 (동일)")
            print()
            print("[NOTE] 추가 설명:")
            if current_time.hour < 9 or current_time.hour >= 16:
                print("  - 현재 장 마감 시간 이후이므로 Y/N 차이가 나타나지 않습니다.")
                print("  - 장중(09:00~15:30)에 테스트하면 차이를 확인할 수 있습니다.")
            print("  - API 문서: 'Y'는 과거 데이터 포함, 'N'은 요청 시점 이후만 반환")
            print("  - 현재 코드는 'Y'를 사용하여 최대 30개까지 가져옵니다.")
            print("  - 중복 제거는 drop_duplicates(keep='last')로 처리됩니다.")
        else:
            print(f"  - 예상과 다른 결과 (Y={chart_y_len}, N={chart_n_len})")


if __name__ == "__main__":
    try:
        # API 인증 먼저 수행
        if not initialize_api():
            print("API 인증 실패")
            sys.exit(1)

        print()
        test_minute_api_response()
    except KeyboardInterrupt:
        print("\n\n테스트 중단됨")
    except Exception as e:
        print(f"\n[ERROR] 오류 발생: {e}")
        import traceback
        traceback.print_exc()
