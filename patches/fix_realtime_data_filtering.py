"""
realtime_data 업데이트 시 전날 데이터 필터링 누락 문제 해결 패치

문제점:
- update_realtime_data() 함수에서 최신 분봉을 수집할 때 전날 데이터 검증이 없음
- API가 전날 데이터를 반환하는 경우 그대로 realtime_data에 추가되어 매매 신호 오류 발생 가능

해결 방안:
1. _get_latest_minute_bar() 함수에서 수집 직후 당일 데이터 검증 추가
2. update_realtime_data() 함수에서 병합 전 추가 검증
3. 로깅 강화로 전날 데이터 혼입 즉시 탐지

적용 방법:
이 파일의 함수들을 core/intraday_stock_manager.py의 IntradayStockManager 클래스에 복사하여 교체
"""

from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_chart_api import get_inquire_time_itemchartprice, get_div_code_for_stock


logger = setup_logger(__name__)


async def _get_latest_minute_bar_patched(self, stock_code: str, current_time: datetime) -> Optional[pd.DataFrame]:
    """
    완성된 최신 분봉 1개 수집 (미완성 봉 제외) + 전날 데이터 필터링 강화

    🆕 개선 사항:
    1. API 응답 직후 당일 데이터 검증
    2. 전날 데이터 감지 시 즉시 반환 중단
    3. 상세 로깅으로 문제 추적 용이

    Args:
        stock_code: 종목코드
        current_time: 현재 시간

    Returns:
        pd.DataFrame: 완성된 최신 분봉 1개 또는 None (전날 데이터 감지 시 None)
    """
    try:
        # 🆕 완성된 마지막 분봉 시간 계산
        current_minute_start = current_time.replace(second=0, microsecond=0)
        last_completed_minute = current_minute_start - timedelta(minutes=1)
        target_hour = last_completed_minute.strftime("%H%M%S")

        # 당일 날짜 (검증용)
        today_str = current_time.strftime("%Y%m%d")

        # 분봉 API로 완성된 데이터 조회
        div_code = get_div_code_for_stock(stock_code)

        # 🆕 매분 1개 분봉만 가져오기
        result = get_inquire_time_itemchartprice(
            div_code=div_code,
            stock_code=stock_code,
            input_hour=target_hour,
            past_data_yn="Y"
        )

        if result is None:
            return None

        summary_df, chart_df = result

        if chart_df.empty:
            return None

        # ========================================
        # 🔥 CRITICAL FIX: 전날 데이터 필터링 (최우선)
        # ========================================
        before_filter_count = len(chart_df)

        if 'date' in chart_df.columns:
            # date 컬럼으로 당일 데이터만 필터링
            chart_df = chart_df[chart_df['date'].astype(str) == today_str].copy()

            if before_filter_count != len(chart_df):
                removed = before_filter_count - len(chart_df)
                self.logger.warning(
                    f"🚨 {stock_code} 실시간 업데이트에서 전날 데이터 {removed}건 감지 및 제거: "
                    f"{before_filter_count} → {len(chart_df)}건 (요청: {target_hour})"
                )

            if chart_df.empty:
                self.logger.error(
                    f"❌ {stock_code} 전날 데이터만 반환됨 - 실시간 업데이트 중단 (요청: {target_hour})"
                )
                return None

        elif 'datetime' in chart_df.columns:
            # datetime 컬럼으로 당일 데이터만 필터링
            chart_df['_date_str'] = pd.to_datetime(chart_df['datetime']).dt.strftime('%Y%m%d')
            chart_df = chart_df[chart_df['_date_str'] == today_str].copy()

            if '_date_str' in chart_df.columns:
                chart_df = chart_df.drop('_date_str', axis=1)

            if before_filter_count != len(chart_df):
                removed = before_filter_count - len(chart_df)
                self.logger.warning(
                    f"🚨 {stock_code} 실시간 업데이트에서 전날 데이터 {removed}건 감지 및 제거: "
                    f"{before_filter_count} → {len(chart_df)}건 (요청: {target_hour})"
                )

            if chart_df.empty:
                self.logger.error(
                    f"❌ {stock_code} 전날 데이터만 반환됨 - 실시간 업데이트 중단 (요청: {target_hour})"
                )
                return None
        else:
            # date/datetime 컬럼이 없는 경우 경고만 표시
            self.logger.warning(
                f"⚠️ {stock_code} date/datetime 컬럼 없음 - 전날 데이터 검증 불가 (요청: {target_hour})"
            )

        # ========================================
        # 최근 2개 분봉 추출 (선정 시점과 첫 업데이트 사이의 누락 방지)
        # ========================================
        if 'time' in chart_df.columns and len(chart_df) > 0:
            # 시간순 정렬
            chart_df_sorted = chart_df.sort_values('time')
            target_time = int(target_hour)

            # 1분 전 시간 계산
            prev_hour = int(target_hour[:2])
            prev_min = int(target_hour[2:4])
            if prev_min == 0:
                prev_hour = prev_hour - 1
                prev_min = 59
            else:
                prev_min = prev_min - 1
            prev_time = prev_hour * 10000 + prev_min * 100  # HHMMSS 형식

            # 요청 시간과 1분 전 시간의 분봉 추출 (최대 2개)
            target_times = [prev_time, target_time]
            matched_data = chart_df_sorted[chart_df_sorted['time'].isin(target_times)]

            if not matched_data.empty:
                latest_data = matched_data.copy()
                #collected_times = [str(int(t)).zfill(6) for t in latest_data['time'].tolist()]
                #self.logger.debug(
                #    f"✅ {stock_code} 분봉 수집: {', '.join(collected_times)} "
                #    f"({len(latest_data)}개, 요청: {target_hour}, 당일 검증 완료)"
                #)
            else:
                # 일치하는 데이터가 없으면 최신 2개 사용
                latest_data = chart_df_sorted.tail(2).copy()
                #collected_times = [str(int(t)).zfill(6) for t in latest_data['time'].tolist()]
                #self.logger.debug(
                #    f"✅ {stock_code} 분봉 수집: {', '.join(collected_times)} "
                #    f"(요청: {target_hour}, 최신 {len(latest_data)}개, 당일 검증 완료)"
                #)
        else:
            latest_data = chart_df.copy()
            if latest_data.empty:
                self.logger.warning(f"⚠️ {stock_code} API 응답 빈 데이터 (요청: {target_hour})")

        return latest_data

    except Exception as e:
        self.logger.error(f"❌ {stock_code} 최신 분봉 수집 오류: {e}")
        return None


async def update_realtime_data_patched(self, stock_code: str) -> bool:
    """
    실시간 분봉 데이터 업데이트 (매수 판단용) + 전날 데이터 이중 검증

    🆕 개선 사항:
    1. _get_latest_minute_bar에서 1차 필터링
    2. 병합 전 2차 당일 데이터 검증
    3. realtime_data 저장 후 3차 검증 (품질 보증)

    Args:
        stock_code: 종목코드

    Returns:
        bool: 업데이트 성공 여부
    """
    try:
        with self._lock:
            if stock_code not in self.selected_stocks:
                return False

            stock_data = self.selected_stocks[stock_code]

        # 1. 현재 보유한 전체 데이터 확인 (historical + realtime)
        combined_data = self.get_combined_chart_data(stock_code)

        # 2. 08-09시부터 데이터가 충분한지 체크
        if not self._check_sufficient_base_data(combined_data, stock_code):
            # 기본 데이터가 부족하면 전체 재수집
            self.logger.warning(f"⚠️ {stock_code} 기본 데이터 부족, 전체 재수집 시도")
            return await self._collect_historical_data(stock_code)

        # 3. 최신 분봉 1개만 수집 (🔥 전날 데이터 필터링 포함)
        current_time = now_kst()
        latest_minute_data = await self._get_latest_minute_bar(stock_code, current_time)

        if latest_minute_data is None:
            # 장초반 구간에서 실시간 업데이트 실패 시 전체 재수집 시도
            current_hour = current_time.strftime("%H%M")
            if current_hour <= "0915":  # 09:15 이전까지 확장
                self.logger.warning(f"⚠️ {stock_code} 장초반 실시간 업데이트 실패, 전체 재수집 시도")
                return await self._collect_historical_data(stock_code)
            else:
                # 장초반이 아니면 최신 데이터 수집 실패 - 기존 데이터 유지
                self.logger.debug(f"📊 {stock_code} 최신 분봉 수집 실패, 기존 데이터 유지")
                return True

        # ========================================
        # 🔥 2차 검증: 병합 전 추가 당일 데이터 확인
        # ========================================
        today_str = current_time.strftime("%Y%m%d")
        before_validation_count = len(latest_minute_data)

        if 'date' in latest_minute_data.columns:
            latest_minute_data = latest_minute_data[
                latest_minute_data['date'].astype(str) == today_str
            ].copy()

            if before_validation_count != len(latest_minute_data):
                removed = before_validation_count - len(latest_minute_data)
                self.logger.error(
                    f"🚨 {stock_code} 병합 전 2차 검증에서 전날 데이터 {removed}건 추가 발견 및 제거!"
                )

            if latest_minute_data.empty:
                self.logger.error(f"❌ {stock_code} 2차 검증 실패 - 전날 데이터만 존재")
                return False

        elif 'datetime' in latest_minute_data.columns:
            latest_minute_data['_date_str'] = pd.to_datetime(
                latest_minute_data['datetime']
            ).dt.strftime('%Y%m%d')
            latest_minute_data = latest_minute_data[
                latest_minute_data['_date_str'] == today_str
            ].copy()

            if '_date_str' in latest_minute_data.columns:
                latest_minute_data = latest_minute_data.drop('_date_str', axis=1)

            if before_validation_count != len(latest_minute_data):
                removed = before_validation_count - len(latest_minute_data)
                self.logger.error(
                    f"🚨 {stock_code} 병합 전 2차 검증에서 전날 데이터 {removed}건 추가 발견 및 제거!"
                )

            if latest_minute_data.empty:
                self.logger.error(f"❌ {stock_code} 2차 검증 실패 - 전날 데이터만 존재")
                return False

        # 4. 기존 realtime_data에 최신 데이터 추가/업데이트
        with self._lock:
            if stock_code in self.selected_stocks:
                current_realtime = self.selected_stocks[stock_code].realtime_data.copy()
                before_count = len(current_realtime)

                # 새로운 데이터를 realtime_data에 추가
                if current_realtime.empty:
                    updated_realtime = latest_minute_data
                else:
                    # 중복 제거하면서 병합 (최신 데이터 우선)
                    updated_realtime = pd.concat(
                        [current_realtime, latest_minute_data],
                        ignore_index=True
                    )
                    before_merge_count = len(updated_realtime)

                    if 'datetime' in updated_realtime.columns:
                        # keep='last': 동일 시간이면 최신 데이터 유지
                        updated_realtime = updated_realtime.drop_duplicates(
                            subset=['datetime'],
                            keep='last'
                        ).sort_values('datetime').reset_index(drop=True)
                    elif 'time' in updated_realtime.columns:
                        updated_realtime = updated_realtime.drop_duplicates(
                            subset=['time'],
                            keep='last'
                        ).sort_values('time').reset_index(drop=True)

                    # 중복 제거 결과 로깅
                    after_merge_count = len(updated_realtime)
                    if before_merge_count != after_merge_count:
                        removed = before_merge_count - after_merge_count
                        self.logger.debug(
                            f"   {stock_code} 중복 제거: {before_merge_count} → "
                            f"{after_merge_count} ({removed}개 중복)"
                        )

                # ========================================
                # 🔥 3차 검증: 저장 직전 최종 당일 데이터 확인
                # ========================================
                before_final_count = len(updated_realtime)

                if 'date' in updated_realtime.columns:
                    updated_realtime = updated_realtime[
                        updated_realtime['date'].astype(str) == today_str
                    ].copy()
                elif 'datetime' in updated_realtime.columns:
                    updated_realtime['_date_str'] = pd.to_datetime(
                        updated_realtime['datetime']
                    ).dt.strftime('%Y%m%d')
                    updated_realtime = updated_realtime[
                        updated_realtime['_date_str'] == today_str
                    ].copy()

                    if '_date_str' in updated_realtime.columns:
                        updated_realtime = updated_realtime.drop('_date_str', axis=1)

                if before_final_count != len(updated_realtime):
                    removed = before_final_count - len(updated_realtime)
                    self.logger.error(
                        f"🚨 {stock_code} 저장 전 3차 검증에서 전날 데이터 {removed}건 최종 제거!"
                    )

                if updated_realtime.empty:
                    self.logger.error(f"❌ {stock_code} 3차 검증 실패 - realtime_data가 비었음")
                    return False

                # 최종 저장
                self.selected_stocks[stock_code].realtime_data = updated_realtime
                self.selected_stocks[stock_code].last_update = current_time

                # 업데이트 결과 로깅
                after_count = len(updated_realtime)
                new_added = after_count - before_count
                if new_added > 0:
                    # 최근 추가된 분봉 시간 표시
                    if 'time' in updated_realtime.columns and new_added <= 3:
                        recent_times = [
                            str(int(t)).zfill(6)
                            for t in updated_realtime['time'].tail(new_added).tolist()
                        ]
                        #self.logger.debug(
                        #    f"✅ {stock_code} realtime_data 업데이트 (3단계 검증 완료): "
                        #    f"{before_count} → {after_count} (+{new_added}개: {', '.join(recent_times)})"
                        #)
                    else:
                        #self.logger.debug(
                        #    f"✅ {stock_code} realtime_data 업데이트 (3단계 검증 완료): "
                        #    f"{before_count} → {after_count} (+{new_added}개)"
                        #)
                        pass    # 너무 많은 로깅으로 인한 성능 저하 방지

        return True

    except Exception as e:
        self.logger.error(f"❌ {stock_code} 실시간 분봉 업데이트 오류: {e}")
        return False


# ========================================
# 패치 적용 방법 가이드
# ========================================
"""
1. core/intraday_stock_manager.py 파일 열기

2. _get_latest_minute_bar 함수 찾기 (약 649줄)
   - 기존 함수를 주석 처리하거나 삭제
   - 위의 _get_latest_minute_bar_patched 함수 내용으로 교체
   - 함수명을 _get_latest_minute_bar로 변경

3. update_realtime_data 함수 찾기 (약 487줄)
   - 기존 함수를 주석 처리하거나 삭제
   - 위의 update_realtime_data_patched 함수 내용으로 교체
   - 함수명을 update_realtime_data로 변경

4. 변경 사항 테스트
   - 실시간 거래 전 시뮬레이션으로 검증
   - 로그에서 "🚨 전날 데이터" 메시지 모니터링
   - get_combined_chart_data()로 최종 데이터 확인

5. 롤백 방법
   - git을 사용하는 경우: git checkout core/intraday_stock_manager.py
   - 백업을 만들어둔 경우: 백업 파일로 복원
"""

# ========================================
# 주요 개선 사항 요약
# ========================================
"""
✅ 3단계 방어 체계 구축:
   1단계: API 응답 직후 필터링 (_get_latest_minute_bar)
   2단계: 병합 전 재검증 (update_realtime_data)
   3단계: 저장 직전 최종 확인 (update_realtime_data)

✅ 상세 로깅:
   - 전날 데이터 감지 시 🚨 표시
   - 제거된 데이터 개수 명시
   - 검증 단계별 결과 기록

✅ 조기 반환:
   - 전날 데이터만 있는 경우 즉시 중단
   - API 호출 낭비 방지
   - 오류 전파 차단

✅ 안전성 향상:
   - 빈 DataFrame 체크 추가
   - date/datetime 컬럼 모두 지원
   - 컬럼 없는 경우 경고 표시
"""
