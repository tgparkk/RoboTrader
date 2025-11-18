# -*- coding: utf-8 -*-
"""
데이터 수집 테스트 스크립트 - 오전 10시 시점 시뮬레이션

목적:
1. 특정 종목의 09:00~10:00 데이터 수집 테스트
2. 전날 데이터 필터링 검증
3. realtime_data 업데이트 프로세스 확인
4. 3단계 검증 로직 동작 확인
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from core.intraday_stock_manager import IntradayStockManager
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)


async def test_data_collection_at_10am():
    """
    오전 10시 시점의 데이터 수집 테스트
    """

    print("=" * 80)
    print("[데이터 수집 테스트] 오전 10시 시점 시뮬레이션")
    print("=" * 80)
    print()

    # 테스트할 종목 (삼성전자)
    test_stock_code = "005930"
    test_stock_name = "삼성전자"

    print(f"[대상] 테스트 종목: {test_stock_code} ({test_stock_name})")
    print(f"[시간] 현재 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # API 초기화
    print("[초기화] API 매니저 초기화 중...")
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("[실패] API 초기화 실패")
        return False
    print("[성공] API 초기화 완료")
    print()

    # IntradayStockManager 초기화
    print("[초기화] IntradayStockManager 초기화 중...")
    intraday_manager = IntradayStockManager(api_manager)
    print("[성공] IntradayStockManager 초기화 완료")
    print()

    # ========================================
    # 1단계: 종목 선정 및 초기 데이터 수집
    # ========================================
    print("=" * 80)
    print("[단계 1] 종목 선정 및 초기 데이터 수집")
    print("=" * 80)
    print()

    # 09:30 선정으로 시뮬레이션 (충분한 과거 데이터 확보)
    simulated_selection_time = now_kst().replace(hour=9, minute=30, second=0, microsecond=0)

    print(f"[시뮬레이션] 종목 선정 시점: {simulated_selection_time.strftime('%H:%M:%S')}")
    print(f"   (주의: 실제로는 현재 시간으로 선정됩니다)")

    success = await intraday_manager.add_selected_stock(
        stock_code=test_stock_code,
        stock_name=test_stock_name,
        selection_reason="테스트 선정"
    )

    if not success:
        print(f"[실패] 종목 선정 실패")
        return False

    print(f"[성공] 종목 선정 완료")
    print()

    # 초기 수집 데이터 확인
    print("[확인] 초기 수집 데이터:")
    combined_data = intraday_manager.get_combined_chart_data(test_stock_code)

    if combined_data is None or combined_data.empty:
        print("[실패] 초기 데이터 없음")
        return False

    print(f"   - 총 분봉 개수: {len(combined_data)}개")

    if 'date' in combined_data.columns:
        unique_dates = combined_data['date'].unique()
        print(f"   - 포함된 날짜: {unique_dates}")

        today_str = now_kst().strftime("%Y%m%d")
        today_data = combined_data[combined_data['date'].astype(str) == today_str]
        print(f"   - 당일 데이터: {len(today_data)}개")

        if len(combined_data) != len(today_data):
            prev_day_count = len(combined_data) - len(today_data)
            print(f"   [경고] 전날 데이터 {prev_day_count}개 발견!")
        else:
            print(f"   [확인] 전날 데이터 없음 (필터링 정상)")

    if 'time' in combined_data.columns:
        first_time = str(int(combined_data['time'].iloc[0])).zfill(6)
        last_time = str(int(combined_data['time'].iloc[-1])).zfill(6)
        print(f"   - 시간 범위: {first_time[:2]}:{first_time[2:4]} ~ {last_time[:2]}:{last_time[2:4]}")

    print()

    # ========================================
    # 2단계: 실시간 업데이트 시뮬레이션 (10:00 기준)
    # ========================================
    print("=" * 80)
    print("[단계 2] 실시간 업데이트 (10:00 시뮬레이션)")
    print("=" * 80)
    print()

    print("[진행] 실시간 데이터 업데이트 시작...")
    print("   (실제 API 호출 - 현재 시간 기준 최신 분봉 수집)")
    print()

    # 실시간 업데이트 실행
    update_success = await intraday_manager.update_realtime_data(test_stock_code)

    if not update_success:
        print("[경고] 실시간 업데이트 실패 (데이터가 없거나 전날 데이터만 반환됨)")
    else:
        print("[성공] 실시간 업데이트 완료")

    print()

    # 업데이트 후 데이터 확인
    print("[확인] 업데이트 후 데이터:")
    updated_combined_data = intraday_manager.get_combined_chart_data(test_stock_code)

    if updated_combined_data is None or updated_combined_data.empty:
        print("[실패] 업데이트 후 데이터 없음")
        return False

    print(f"   - 총 분봉 개수: {len(updated_combined_data)}개")

    if 'date' in updated_combined_data.columns:
        unique_dates = updated_combined_data['date'].unique()
        print(f"   - 포함된 날짜: {unique_dates}")

        today_str = now_kst().strftime("%Y%m%d")
        today_data = updated_combined_data[updated_combined_data['date'].astype(str) == today_str]
        print(f"   - 당일 데이터: {len(today_data)}개")

        if len(updated_combined_data) != len(today_data):
            prev_day_count = len(updated_combined_data) - len(today_data)
            print(f"   [실패] 전날 데이터 {prev_day_count}개 여전히 존재! (필터링 실패)")
        else:
            print(f"   [성공] 전날 데이터 없음 (필터링 성공)")

    if 'time' in updated_combined_data.columns:
        first_time = str(int(updated_combined_data['time'].iloc[0])).zfill(6)
        last_time = str(int(updated_combined_data['time'].iloc[-1])).zfill(6)
        print(f"   - 시간 범위: {first_time[:2]}:{first_time[2:4]} ~ {last_time[:2]}:{last_time[2:4]}")

        # 최근 5개 분봉 시간 표시
        recent_times = [str(int(t)).zfill(6) for t in updated_combined_data['time'].tail(5).tolist()]
        print(f"   - 최근 5개 분봉: {', '.join([f'{t[:2]}:{t[2:4]}' for t in recent_times])}")

    print()

    # ========================================
    # 3단계: 데이터 품질 검증
    # ========================================
    print("=" * 80)
    print("[단계 3] 데이터 품질 검증")
    print("=" * 80)
    print()

    # 3분봉 변환 테스트
    from core.timeframe_converter import TimeFrameConverter

    print("[진행] 3분봉 변환 중...")
    data_3min = TimeFrameConverter.convert_to_3min_data(updated_combined_data)

    if data_3min is None or data_3min.empty:
        print("[실패] 3분봉 변환 실패")
    else:
        print(f"[성공] 3분봉 변환 완료: {len(data_3min)}개")

        if 'datetime' in data_3min.columns:
            data_3min['datetime'] = pd.to_datetime(data_3min['datetime'])
            first_time = data_3min['datetime'].iloc[0].strftime('%H:%M')
            last_time = data_3min['datetime'].iloc[-1].strftime('%H:%M')
            print(f"   - 시간 범위: {first_time} ~ {last_time}")

            # 최근 5개 3분봉 표시
            recent_3min = data_3min.tail(5)
            print(f"   - 최근 5개 3분봉:")
            for idx, row in recent_3min.iterrows():
                time_str = row['datetime'].strftime('%H:%M')
                print(f"      {time_str} | O:{row['open']:,.0f} H:{row['high']:,.0f} L:{row['low']:,.0f} C:{row['close']:,.0f} V:{row['volume']:,}")

    print()

    # ========================================
    # 4단계: 종합 결과
    # ========================================
    print("=" * 80)
    print("[종합 결과]")
    print("=" * 80)
    print()

    result = {
        "initial_collection": success,
        "realtime_update": update_success,
        "final_data_count": len(updated_combined_data) if updated_combined_data is not None else 0,
        "conversion_3min": data_3min is not None and not data_3min.empty
    }

    all_success = all(result.values())

    print("[테스트 결과]")
    print(f"   [초기 데이터 수집] {'성공' if result['initial_collection'] else '실패'}")
    print(f"   [실시간 업데이트] {'성공' if result['realtime_update'] else '실패'}")
    print(f"   [최종 데이터 개수] {result['final_data_count']}개")
    print(f"   [3분봉 변환] {'성공' if result['conversion_3min'] else '실패'}")
    print()

    if all_success:
        print("[최종 결과] 모든 테스트 성공!")
    else:
        print("[최종 결과] 일부 테스트 실패")

    print()
    print("=" * 80)

    return all_success


async def test_multiple_updates():
    """
    연속적인 업데이트 테스트 (10:00 ~ 10:05 시뮬레이션)
    """
    print()
    print("=" * 80)
    print("[연속 업데이트 테스트] 5회")
    print("=" * 80)
    print()

    test_stock_code = "005930"
    test_stock_name = "삼성전자"

    # API 및 매니저 초기화
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("[실패] API 초기화 실패")
        return False

    intraday_manager = IntradayStockManager(api_manager)

    # 종목 선정
    await intraday_manager.add_selected_stock(
        stock_code=test_stock_code,
        stock_name=test_stock_name,
        selection_reason="연속 테스트"
    )

    print(f"[종목] {test_stock_code} ({test_stock_name})")
    print(f"[시작 시간] {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 5회 연속 업데이트
    for i in range(1, 6):
        print(f"[업데이트 {i}/5]...")

        update_success = await intraday_manager.update_realtime_data(test_stock_code)
        combined_data = intraday_manager.get_combined_chart_data(test_stock_code)

        if combined_data is not None and not combined_data.empty:
            today_str = now_kst().strftime("%Y%m%d")

            if 'date' in combined_data.columns:
                today_data = combined_data[combined_data['date'].astype(str) == today_str]
                prev_day_count = len(combined_data) - len(today_data)

                status = "[정상]" if prev_day_count == 0 else "[경고]"
                print(f"   {status} 총 {len(combined_data)}개 (당일: {len(today_data)}개, 전날: {prev_day_count}개)")
            else:
                print(f"   [정보] 총 {len(combined_data)}개 (날짜 검증 불가)")
        else:
            print(f"   [경고] 데이터 없음")

        # 3초 대기 (실제 환경 시뮬레이션)
        if i < 5:
            await asyncio.sleep(3)

    print()
    print("[성공] 연속 업데이트 테스트 완료")
    print()


async def main():
    """메인 함수"""
    try:
        # 기본 테스트
        success = await test_data_collection_at_10am()

        # 추가 질문
        print()
        print("=" * 80)
        user_input = input("연속 업데이트 테스트도 진행하시겠습니까? (y/n): ")

        if user_input.lower() == 'y':
            await test_multiple_updates()

        print()
        print("=" * 80)
        print("테스트 종료")
        print("=" * 80)

        return success

    except KeyboardInterrupt:
        print()
        print("[경고] 사용자가 테스트를 중단했습니다.")
        return False
    except Exception as e:
        logger.error(f"[오류] 테스트 중 오류 발생: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    asyncio.run(main())
