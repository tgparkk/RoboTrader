# -*- coding: utf-8 -*-
"""
데이터 수집 테스트 - 시간 모킹으로 장중 상황 시뮬레이션

10:00:10부터 시작해서 10초씩 시간을 증가시키면서
실제 데이터 수집 흐름을 테스트합니다.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from unittest.mock import patch

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from core.intraday_stock_manager import IntradayStockManager
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger
from utils.korean_time import now_kst, KST

logger = setup_logger(__name__)


class TimeSimulator:
    """시간 시뮬레이터 - now_kst()를 가짜 시간으로 대체"""

    def __init__(self, start_time: datetime):
        """
        Args:
            start_time: 시뮬레이션 시작 시간 (예: 2025-10-13 10:00:10)
        """
        self.current_time = start_time
        self.original_now_kst = now_kst

    def get_time(self):
        """현재 시뮬레이션 시간 반환"""
        return self.current_time

    def advance(self, seconds: int = 10):
        """시간을 N초 전진"""
        self.current_time += timedelta(seconds=seconds)

    def __enter__(self):
        """Context manager 진입"""
        return self

    def __exit__(self, *args):
        """Context manager 종료"""
        pass


async def test_with_time_simulation():
    """
    시간 모킹으로 10:00:10부터 데이터 수집 테스트
    """

    print("=" * 80)
    print("[시간 시뮬레이션 테스트] 10:00:10 시작")
    print("=" * 80)
    print()

    # 테스트 설정
    test_stock_code = "005930"
    test_stock_name = "삼성전자"

    # 시뮬레이션 시작 시간: 오늘 10:00:10
    today = datetime.now(KST)
    sim_start_time = today.replace(hour=10, minute=0, second=10, microsecond=0)

    print(f"[설정]")
    print(f"   테스트 종목: {test_stock_code} ({test_stock_name})")
    print(f"   시뮬레이션 시작: {sim_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   실제 현재 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # API 초기화
    print("[1단계] API 초기화")
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("[실패] API 초기화 실패")
        return False
    print("[성공] API 초기화 완료")
    print()

    # 시간 시뮬레이터 생성
    time_sim = TimeSimulator(sim_start_time)

    # now_kst()를 모킹하여 시뮬레이션 시간 반환
    with patch('utils.korean_time.now_kst', side_effect=lambda: time_sim.get_time()):
        with patch('core.intraday_stock_manager.now_kst', side_effect=lambda: time_sim.get_time()):

            # IntradayStockManager 초기화
            print("[2단계] IntradayStockManager 초기화")
            intraday_manager = IntradayStockManager(api_manager)
            print("[성공] 초기화 완료")
            print()

            # ========================================
            # 단계 1: 10:00:10에 종목 선정
            # ========================================
            print("=" * 80)
            print(f"[단계 1] 종목 선정 - {time_sim.get_time().strftime('%H:%M:%S')}")
            print("=" * 80)
            print()

            print(f"[시뮬레이션 시간] {time_sim.get_time().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"[작업] 종목 선정 시작...")

            # 주의: is_market_open() 함수도 모킹해야 함
            with patch('core.intraday_stock_manager.is_market_open', return_value=True):
                success = await intraday_manager.add_selected_stock(
                    stock_code=test_stock_code,
                    stock_name=test_stock_name,
                    selection_reason="시간 시뮬레이션 테스트"
                )

            if not success:
                print("[실패] 종목 선정 실패")
                return False

            print("[성공] 종목 선정 완료")
            print()

            # 초기 데이터 확인
            print("[확인] 초기 수집 데이터:")
            combined_data = intraday_manager.get_combined_chart_data(test_stock_code)

            if combined_data is None or combined_data.empty:
                print("   [경고] 데이터 없음 (API 응답 없거나 장 마감 후)")
                print("   [정보] 장중에 테스트하거나 API 응답을 모킹해야 합니다")
                print()
            else:
                print(f"   총 분봉: {len(combined_data)}개")

                if 'date' in combined_data.columns:
                    today_str = time_sim.get_time().strftime("%Y%m%d")
                    today_data = combined_data[combined_data['date'].astype(str) == today_str]
                    prev_day_count = len(combined_data) - len(today_data)

                    print(f"   당일 데이터: {len(today_data)}개")
                    if prev_day_count > 0:
                        print(f"   [경고] 전날 데이터: {prev_day_count}개")
                    else:
                        print(f"   [성공] 전날 데이터 없음")

                if 'time' in combined_data.columns and len(combined_data) > 0:
                    first_time = str(int(combined_data['time'].iloc[0])).zfill(6)
                    last_time = str(int(combined_data['time'].iloc[-1])).zfill(6)
                    print(f"   시간 범위: {first_time[:2]}:{first_time[2:4]} ~ {last_time[:2]}:{last_time[2:4]}")

                    # 예상: 09:00 ~ 09:59 (60개)
                    expected_last = "095900"
                    if last_time == expected_last:
                        print(f"   [성공] 예상대로 09:59까지 수집됨 (10:00은 진행중)")
                    else:
                        print(f"   [정보] 마지막 분봉: {last_time[:2]}:{last_time[2:4]}")

            print()

            # ========================================
            # 단계 2: 시간을 10초씩 증가시키며 업데이트
            # ========================================
            print("=" * 80)
            print("[단계 2] 시간 경과 시뮬레이션 (10초 간격, 10:00:10 ~ 15:18:00)")
            print("=" * 80)
            print()

            # 10:00:10 → 15:18:00까지 계산
            # 시작: 10:00:10, 종료: 15:18:00
            # 총 시간: 5시간 17분 50초 = 317분 50초 = 19070초
            # 10초 간격: 19070 / 10 = 1907회

            end_time = today.replace(hour=15, minute=18, second=0, microsecond=0)
            total_seconds = (end_time - sim_start_time).total_seconds()
            update_count = int(total_seconds / 10)

            print(f"[설정]")
            print(f"   시작 시간: {sim_start_time.strftime('%H:%M:%S')}")
            print(f"   종료 시간: {end_time.strftime('%H:%M:%S')}")
            print(f"   총 업데이트 횟수: {update_count}회 (10초 간격)")
            print(f"   예상 소요 시간: 약 {update_count * 0.1 / 60:.1f}분 (API 호출 간격 0.1초)")
            print()
            print("[자동 진행] 2초 후 시작합니다...")
            await asyncio.sleep(2)
            print()

            # 진행상황 표시를 위한 설정
            show_interval = max(1, update_count // 100)  # 최대 100번만 출력
            data_snapshots = []  # 주요 시점의 데이터 저장
            prev_day_count = 0

            for i in range(update_count):
                # 시간 10초 전진
                time_sim.advance(10)
                current_sim_time = time_sim.get_time()

                # 매분 정각(00초)마다 또는 일정 간격마다 출력
                should_print = (
                    current_sim_time.second == 0 or  # 매분 정각
                    i % show_interval == 0 or  # 일정 간격
                    i == update_count - 1  # 마지막
                )

                if should_print:
                    print(f"[진행 {i+1:4d}/{update_count}] {current_sim_time.strftime('%H:%M:%S')}", end="")

                # 실시간 데이터 업데이트
                with patch('core.intraday_stock_manager.is_market_open', return_value=True):
                    update_success = await intraday_manager.update_realtime_data(test_stock_code)

                # 업데이트 후 데이터 확인
                updated_data = intraday_manager.get_combined_chart_data(test_stock_code)

                if should_print:
                    if updated_data is not None and not updated_data.empty:
                        today_str = time_sim.get_time().strftime("%Y%m%d")

                        if 'date' in updated_data.columns:
                            today_data = updated_data[updated_data['date'].astype(str) == today_str]
                            prev_day_count = len(updated_data) - len(today_data)

                            status = " OK " if prev_day_count == 0 else " NG "
                            print(f" | {status} | 총:{len(updated_data):3d}개 (당일:{len(today_data):3d}, 전날:{prev_day_count:2d})")

                            if prev_day_count > 0:
                                print(f"      [경고] 전날 데이터 {prev_day_count}개 혼입 발견!")
                        else:
                            print(f" | 총:{len(updated_data):3d}개")
                    else:
                        print(f" | [경고] 데이터 없음")

                # 주요 시점 데이터 스냅샷 저장
                milestone_times = ["10:01:00", "11:00:00", "12:00:00", "13:00:00", "14:00:00", "15:00:00", "15:18:00"]
                if current_sim_time.strftime('%H:%M:%S') in milestone_times:
                    if updated_data is not None and not updated_data.empty:
                        data_snapshots.append({
                            'time': current_sim_time.strftime('%H:%M:%S'),
                            'total_count': len(updated_data),
                            'has_prev_day': prev_day_count > 0 if 'date' in updated_data.columns else None
                        })

                # API 호출 제한 고려
                await asyncio.sleep(0.1)  # 0.1초 대기

            # 주요 시점 요약
            print()
            print("=" * 80)
            print("[주요 시점 데이터 요약]")
            print("=" * 80)
            for snapshot in data_snapshots:
                status = "OK" if snapshot['has_prev_day'] == False else "NG" if snapshot['has_prev_day'] == True else "?"
                print(f"   {snapshot['time']} | {status} | 총 {snapshot['total_count']}개")
            print()

            # ========================================
            # 단계 3: 최종 결과
            # ========================================
            print("=" * 80)
            print("[단계 3] 최종 결과")
            print("=" * 80)
            print()

            final_data = intraday_manager.get_combined_chart_data(test_stock_code)

            if final_data is not None and not final_data.empty:
                today_str = time_sim.get_time().strftime("%Y%m%d")

                print(f"[최종 데이터]")
                print(f"   총 분봉: {len(final_data)}개")

                if 'date' in final_data.columns:
                    today_data = final_data[final_data['date'].astype(str) == today_str]
                    prev_day_count = len(final_data) - len(today_data)

                    print(f"   당일 데이터: {len(today_data)}개")
                    print(f"   전날 데이터: {prev_day_count}개")

                    if prev_day_count == 0:
                        print(f"   [성공] 전날 데이터 필터링 완벽!")
                    else:
                        print(f"   [실패] 전날 데이터 {prev_day_count}개 혼입됨")

                if 'time' in final_data.columns and len(final_data) > 0:
                    first_time = str(int(final_data['time'].iloc[0])).zfill(6)
                    last_time = str(int(final_data['time'].iloc[-1])).zfill(6)
                    print(f"   시간 범위: {first_time[:2]}:{first_time[2:4]} ~ {last_time[:2]}:{last_time[2:4]}")

                # 3분봉 변환 테스트
                print()
                print("[3분봉 변환 테스트]")
                from core.timeframe_converter import TimeFrameConverter

                data_3min = TimeFrameConverter.convert_to_3min_data(final_data)

                if data_3min is not None and not data_3min.empty:
                    print(f"   [성공] 3분봉 {len(data_3min)}개 생성")

                    if 'datetime' in data_3min.columns and len(data_3min) >= 3:
                        data_3min['datetime'] = pd.to_datetime(data_3min['datetime'])
                        recent_3min = data_3min.tail(3)
                        print(f"   최근 3개 3분봉:")
                        for idx, row in recent_3min.iterrows():
                            time_str = row['datetime'].strftime('%H:%M')
                            print(f"      {time_str} | C:{row['close']:,.0f} V:{row['volume']:,}")
                else:
                    print(f"   [실패] 3분봉 변환 실패")
            else:
                print("[경고] 최종 데이터 없음")

            print()
            print("=" * 80)
            print("[테스트 완료]")
            print("=" * 80)

            return True


async def main():
    """메인 함수"""
    try:
        print()
        print("=" * 80)
        print("시간 시뮬레이션 데이터 수집 테스트")
        print("=" * 80)
        print()

        print("[주의사항]")
        print("   1. 이 테스트는 시간을 10:00:10부터 시작하여 모킹합니다")
        print("   2. 실제 API 호출이 발생하므로 실제 데이터가 반환됩니다")
        print("   3. 장 마감 후에는 API에서 당일 전체 데이터를 반환할 수 있습니다")
        print("   4. 가장 정확한 테스트는 장중(09:00~15:30)에 실행하는 것입니다")
        print()

        user_input = input("계속하시겠습니까? (y/n): ")
        if user_input.lower() != 'y':
            print("테스트 취소")
            return

        print()

        # 테스트 실행
        success = await test_with_time_simulation()

        print()
        if success:
            print("[결과] 테스트 완료")
        else:
            print("[결과] 테스트 실패")

    except KeyboardInterrupt:
        print()
        print("[취소] 사용자가 중단")
    except Exception as e:
        logger.error(f"[오류] 테스트 실행 실패: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
