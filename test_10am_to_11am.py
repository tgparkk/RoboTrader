# -*- coding: utf-8 -*-
"""
10시~11시 데이터 수집 테스트 (간단 버전)

시나리오:
1. 10:00:10 - 종목 선정 → 09:00~09:59 수집 (60개)
2. 10:00:10 ~ 11:00:00 - 10초씩 시간 증가하며 업데이트
3. 11:00:00 - 최종 확인 → 09:00~10:59 총 120개 예상
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from unittest.mock import patch

sys.path.append(str(Path(__file__).parent))

from core.intraday_stock_manager import IntradayStockManager
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger
from utils.korean_time import KST

logger = setup_logger(__name__)


class TimeSimulator:
    """시간 시뮬레이터"""
    def __init__(self, start_time: datetime):
        self.current_time = start_time

    def get_time(self):
        return self.current_time

    def advance(self, seconds: int = 10):
        self.current_time += timedelta(seconds=seconds)


async def test_10am_to_11am():
    """10시~11시 데이터 수집 테스트"""

    print("=" * 80)
    print("10:00 ~ 11:00 데이터 수집 테스트")
    print("=" * 80)
    print()

    # 설정
    test_stock_code = "005930"
    test_stock_name = "삼성전자"

    # 시작 시간: 오늘 10:00:10
    today = datetime.now(KST)
    start_time = today.replace(hour=10, minute=0, second=10, microsecond=0)
    end_time = today.replace(hour=11, minute=0, second=0, microsecond=0)

    print(f"[설정]")
    print(f"  종목: {test_stock_code} ({test_stock_name})")
    print(f"  시작: {start_time.strftime('%H:%M:%S')}")
    print(f"  종료: {end_time.strftime('%H:%M:%S')}")
    print(f"  실제 현재 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # API 초기화
    print("[1] API 초기화...")
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("  [실패] API 초기화 실패")
        return False
    print("  [완료]")
    print()

    # 시간 시뮬레이터
    time_sim = TimeSimulator(start_time)

    # now_kst() 모킹
    with patch('utils.korean_time.now_kst', side_effect=lambda: time_sim.get_time()):
        with patch('core.intraday_stock_manager.now_kst', side_effect=lambda: time_sim.get_time()):
            with patch('core.intraday_stock_manager.is_market_open', return_value=True):

                # IntradayStockManager 초기화
                print("[2] IntradayStockManager 초기화...")
                intraday_manager = IntradayStockManager(api_manager)
                print("  [완료]")
                print()

                # 종목 선정 (10:00:10)
                print("=" * 80)
                print(f"[3] 종목 선정 - {time_sim.get_time().strftime('%H:%M:%S')}")
                print("=" * 80)

                success = await intraday_manager.add_selected_stock(
                    stock_code=test_stock_code,
                    stock_name=test_stock_name,
                    selection_reason="10-11시 테스트"
                )

                if not success:
                    print("  [실패] 종목 선정 실패")
                    return False

                # 초기 데이터 확인
                initial_data = intraday_manager.get_combined_chart_data(test_stock_code)

                if initial_data is None or initial_data.empty:
                    print("  [경고] 초기 데이터 없음")
                else:
                    today_str = time_sim.get_time().strftime("%Y%m%d")

                    if 'date' in initial_data.columns:
                        today_count = len(initial_data[initial_data['date'].astype(str) == today_str])
                        prev_count = len(initial_data) - today_count

                        print(f"  총 {len(initial_data)}개 (당일: {today_count}, 전날: {prev_count})")

                        if prev_count > 0:
                            print(f"  [경고] 전날 데이터 {prev_count}개 발견!")

                    if 'time' in initial_data.columns:
                        first = str(int(initial_data['time'].iloc[0])).zfill(6)
                        last = str(int(initial_data['time'].iloc[-1])).zfill(6)
                        print(f"  시간 범위: {first[:2]}:{first[2:4]} ~ {last[:2]}:{last[2:4]}")

                        # 예상: 09:59까지
                        if last == "095900":
                            print(f"  [성공] 예상대로 09:59까지 수집 (10:00은 진행중)")
                        else:
                            print(f"  [정보] 마지막 분봉: {last[:2]}:{last[2:4]}")

                print()

                # 시간 경과 시뮬레이션
                print("=" * 80)
                print("[4] 시간 경과 (10:00:10 ~ 11:00:00, 10초 간격)")
                print("=" * 80)
                print()

                total_seconds = (end_time - start_time).total_seconds()
                update_count = int(total_seconds / 10)

                print(f"  업데이트 횟수: {update_count}회")
                print(f"  예상 소요 시간: 약 {update_count * 0.1 / 60:.1f}분")
                print()

                # 주요 시점 기록
                milestones = {
                    "10:01:00": None,
                    "10:10:00": None,
                    "10:20:00": None,
                    "10:30:00": None,
                    "10:40:00": None,
                    "10:50:00": None,
                    "11:00:00": None
                }

                prev_day_detected = False

                for i in range(update_count):
                    # 시간 전진
                    time_sim.advance(10)
                    current = time_sim.get_time()

                    # 업데이트
                    await intraday_manager.update_realtime_data(test_stock_code)

                    # 데이터 확인
                    data = intraday_manager.get_combined_chart_data(test_stock_code)

                    # 매분 정각에 출력
                    if current.second == 0:
                        if data is not None and not data.empty:
                            today_str = current.strftime("%Y%m%d")

                            if 'date' in data.columns:
                                today_count = len(data[data['date'].astype(str) == today_str])
                                prev_count = len(data) - today_count

                                status = "OK" if prev_count == 0 else "NG"
                                print(f"  [{current.strftime('%H:%M:%S')}] {status} | 총:{len(data):3d} (당일:{today_count:3d}, 전날:{prev_count:2d})")

                                if prev_count > 0 and not prev_day_detected:
                                    print(f"    [경고] 전날 데이터 혼입 발견!")
                                    prev_day_detected = True
                            else:
                                print(f"  [{current.strftime('%H:%M:%S')}] 총:{len(data):3d}개")

                            # 마일스톤 기록
                            time_key = current.strftime('%H:%M:%S')
                            if time_key in milestones:
                                milestones[time_key] = len(data)

                    # API 제한
                    await asyncio.sleep(0.1)

                print()

                # 최종 결과
                print("=" * 80)
                print("[5] 최종 결과")
                print("=" * 80)
                print()

                final_data = intraday_manager.get_combined_chart_data(test_stock_code)

                if final_data is None or final_data.empty:
                    print("  [실패] 최종 데이터 없음")
                    return False

                today_str = time_sim.get_time().strftime("%Y%m%d")

                print(f"[데이터 현황]")
                print(f"  총 분봉: {len(final_data)}개")

                if 'date' in final_data.columns:
                    today_count = len(final_data[final_data['date'].astype(str) == today_str])
                    prev_count = len(final_data) - today_count

                    print(f"  당일: {today_count}개")
                    print(f"  전날: {prev_count}개")

                    if prev_count == 0:
                        print(f"  [성공] 전날 데이터 필터링 완벽!")
                    else:
                        print(f"  [실패] 전날 데이터 {prev_count}개 혼입")

                if 'time' in final_data.columns:
                    first = str(int(final_data['time'].iloc[0])).zfill(6)
                    last = str(int(final_data['time'].iloc[-1])).zfill(6)
                    print(f"  시간 범위: {first[:2]}:{first[2:4]} ~ {last[:2]}:{last[2:4]}")

                    # 예상: 09:00 ~ 10:59 (120개)
                    expected_count = 120
                    if len(final_data) == expected_count:
                        print(f"  [성공] 예상대로 {expected_count}개 수집!")
                    else:
                        print(f"  [정보] 예상: {expected_count}개, 실제: {len(final_data)}개")

                print()
                print("[주요 시점별 데이터 개수]")
                for time_key, count in milestones.items():
                    if count is not None:
                        print(f"  {time_key}: {count:3d}개")

                print()

                # 3분봉 변환 테스트
                print("[3분봉 변환]")
                from core.timeframe_converter import TimeFrameConverter
                data_3min = TimeFrameConverter.convert_to_3min_data(final_data)

                if data_3min is not None and not data_3min.empty:
                    print(f"  [성공] 3분봉 {len(data_3min)}개 생성")
                    expected_3min = 120 // 3  # 40개
                    if len(data_3min) == expected_3min:
                        print(f"  [성공] 예상대로 {expected_3min}개!")
                else:
                    print(f"  [실패] 3분봉 변환 실패")

                print()
                print("=" * 80)
                print("[테스트 완료]")
                print("=" * 80)

                return True


async def main():
    try:
        print()
        success = await test_10am_to_11am()
        print()

        if success:
            print("[결과] 테스트 성공!")
        else:
            print("[결과] 테스트 실패")

    except KeyboardInterrupt:
        print()
        print("[중단] 사용자 취소")
    except Exception as e:
        print()
        print(f"[오류] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
