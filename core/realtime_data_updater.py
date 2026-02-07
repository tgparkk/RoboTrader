"""
실시간 분봉 데이터 업데이트 모듈

IntradayStockManager에서 분리된 실시간 데이터 업데이트 로직
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from utils.logger import setup_logger
from utils.korean_time import now_kst
from config.market_hours import MarketHours
from api.kis_chart_api import (
    get_inquire_time_itemchartprice,
    get_div_code_for_stock
)


class RealtimeDataUpdater:
    """
    실시간 분봉 데이터 업데이트 담당 클래스

    책임:
    - 실시간 분봉 데이터 업데이트
    - 기본 데이터 충분성 체크
    - 최신 분봉 수집
    """

    def __init__(self, manager):
        """
        초기화

        Args:
            manager: IntradayStockManager 인스턴스 (의존성 주입)
        """
        self.manager = manager
        self.logger = manager.logger
        self._lock = manager._lock

    async def update_realtime_data(self, stock_code: str) -> bool:
        """
        실시간 분봉 데이터 업데이트 (매수 판단용) + 전날 데이터 이중 검증

        Args:
            stock_code: 종목코드

        Returns:
            bool: 업데이트 성공 여부
        """
        try:
            with self._lock:
                if stock_code not in self.manager.selected_stocks:
                    return False

                stock_data = self.manager.selected_stocks[stock_code]

            # 1. 현재 보유한 전체 데이터 확인 (historical + realtime)
            combined_data = self.manager.get_combined_chart_data(stock_code)

            # 2. 09시부터 데이터가 충분한지 체크
            if not self._check_sufficient_base_data(combined_data, stock_code):
                # 재수집 전에 selected_time을 현재 시간으로 업데이트 (5분 경과 후)
                with self._lock:
                    if stock_code in self.manager.selected_stocks:
                        current_time = now_kst()
                        old_time = self.manager.selected_stocks[stock_code].selected_time

                        # 선정 후 5분 이상 경과했는데 데이터 부족이면 selected_time 업데이트
                        elapsed_minutes = (current_time - old_time).total_seconds() / 60
                        if elapsed_minutes >= 5:
                            self.manager.selected_stocks[stock_code].selected_time = current_time
                            self.logger.info(
                                f"[시간갱신] {stock_code} 데이터 부족 지속 (선정 후 {elapsed_minutes:.0f}분), "
                                f"selected_time 업데이트: {old_time.strftime('%H:%M:%S')} -> {current_time.strftime('%H:%M:%S')}"
                            )

                # 기본 데이터가 부족하면 전체 재수집
                self.logger.warning(f"[경고] {stock_code} 기본 데이터 부족, 전체 재수집 시도")
                return await self.manager._historical_collector.collect_historical_data(stock_code)

            # 3. 최신 분봉 1개만 수집 (전날 데이터 필터링 포함)
            current_time = now_kst()
            latest_minute_data = await self._get_latest_minute_bar(stock_code, current_time)

            if latest_minute_data is None:
                # 장초반 구간에서 실시간 업데이트 실패 시 전체 재수집 시도
                current_hour = current_time.strftime("%H%M")
                if current_hour <= "0915":  # 09:15 이전까지 확장
                    self.logger.warning(f"[경고] {stock_code} 장초반 실시간 업데이트 실패, 전체 재수집 시도")
                    return await self.manager._historical_collector.collect_historical_data(stock_code)
                else:
                    # 장초반이 아니면 최신 데이터 수집 실패 - 기존 데이터 유지
                    self.logger.debug(f"[정보] {stock_code} 최신 분봉 수집 실패, 기존 데이터 유지")
                    return True

            # 2차 검증: 병합 전 추가 당일 데이터 확인
            today_str = current_time.strftime("%Y%m%d")
            latest_minute_data = self._validate_today_data_in_latest(latest_minute_data, today_str, stock_code)

            if latest_minute_data is None or latest_minute_data.empty:
                self.logger.error(f"[실패] {stock_code} 2차 검증 실패 - 전날 데이터만 존재")
                return False

            # 4. 기존 realtime_data에 최신 데이터 추가/업데이트
            with self._lock:
                if stock_code in self.manager.selected_stocks:
                    current_realtime = self.manager.selected_stocks[stock_code].realtime_data.copy()
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

                        if 'datetime' in updated_realtime.columns:
                            updated_realtime = updated_realtime.drop_duplicates(
                                subset=['datetime'],
                                keep='last'
                            ).sort_values('datetime').reset_index(drop=True)
                        elif 'time' in updated_realtime.columns:
                            updated_realtime = updated_realtime.drop_duplicates(
                                subset=['time'],
                                keep='last'
                            ).sort_values('time').reset_index(drop=True)

                    # 3차 검증: 저장 직전 최종 당일 데이터 확인
                    updated_realtime = self._final_today_validation(updated_realtime, today_str, stock_code)

                    if updated_realtime is None or updated_realtime.empty:
                        self.logger.error(f"[실패] {stock_code} 3차 검증 실패 - realtime_data가 비었음")
                        return False

                    # 최종 저장
                    self.manager.selected_stocks[stock_code].realtime_data = updated_realtime
                    self.manager.selected_stocks[stock_code].last_update = current_time

            return True

        except Exception as e:
            self.logger.error(f"[오류] {stock_code} 실시간 분봉 업데이트 오류: {e}")
            return False

    def _check_sufficient_base_data(self, combined_data: Optional[pd.DataFrame], stock_code: str) -> bool:
        """
        시장 시작시간부터 분봉 데이터가 충분한지 간단 체크

        Args:
            combined_data: 결합된 차트 데이터
            stock_code: 종목코드 (로깅용)

        Returns:
            bool: 기본 데이터 충분 여부
        """
        try:
            if combined_data is None or combined_data.empty:
                self.logger.debug(f"[실패] {stock_code} 데이터 없음")
                return False

            # 1. 당일 데이터인지 먼저 확인
            current_time = now_kst()
            today_str = current_time.strftime('%Y%m%d')

            # 동적 시장 시작 시간 가져오기
            market_hours = MarketHours.get_market_hours('KRX', current_time)
            market_open = market_hours['market_open']
            expected_start_hour = market_open.hour

            # date 컬럼으로 당일 데이터만 필터링
            if 'date' in combined_data.columns:
                today_data = combined_data[combined_data['date'].astype(str) == today_str].copy()
                if today_data.empty:
                    self.logger.debug(f"[실패] {stock_code} 당일 데이터 없음 (전일 데이터만 존재)")
                    return False
                combined_data = today_data
            elif 'datetime' in combined_data.columns:
                try:
                    combined_data['date_str'] = pd.to_datetime(combined_data['datetime']).dt.strftime('%Y%m%d')
                    today_data = combined_data[combined_data['date_str'] == today_str].copy()
                    if today_data.empty:
                        self.logger.debug(f"[실패] {stock_code} 당일 데이터 없음 (전일 데이터만 존재)")
                        return False
                    combined_data = today_data.drop('date_str', axis=1)
                except Exception:
                    pass

            data_count = len(combined_data)

            # 최소 데이터 개수 체크 (3분봉 최소 5개 = 15분봉 필요)
            if data_count < 5:
                self.logger.debug(f"[실패] {stock_code} 데이터 부족: {data_count}/15")
                return False

            # 시작 시간 체크 (장 시작 5분 이내 데이터 존재 확인)
            expected_start_min = market_open.minute

            if 'time' in combined_data.columns:
                start_time_str = str(combined_data.iloc[0]['time']).zfill(6)
                start_hour = int(start_time_str[:2])
                start_min = int(start_time_str[2:4])

                if start_hour != expected_start_hour:
                    self.logger.debug(f"[실패] {stock_code} 시작 시간 문제: {start_time_str} ({expected_start_hour}시 아님)")
                    return False

                # 장 시작 5분 이내 데이터가 있어야 함 (예: 09:05 이전)
                if start_min > expected_start_min + 5:
                    self.logger.debug(
                        f"[실패] {stock_code} 초반 데이터 누락: 첫 봉 {start_time_str} "
                        f"(장 시작 {expected_start_hour:02d}:{expected_start_min:02d} 후 {start_min - expected_start_min}분)"
                    )
                    return False

            elif 'datetime' in combined_data.columns:
                start_dt = combined_data.iloc[0]['datetime']
                if hasattr(start_dt, 'hour'):
                    start_hour = start_dt.hour
                    start_min = start_dt.minute if hasattr(start_dt, 'minute') else 0
                    if start_hour != expected_start_hour:
                        self.logger.debug(f"[실패] {stock_code} 시작 시간 문제: {start_hour}시 ({expected_start_hour}시 아님)")
                        return False
                    if start_min > expected_start_min + 5:
                        self.logger.debug(
                            f"[실패] {stock_code} 초반 데이터 누락: 첫 봉 {start_hour:02d}:{start_min:02d} "
                            f"(장 시작 후 {start_min - expected_start_min}분)"
                        )
                        return False

            return True

        except Exception as e:
            self.logger.warning(f"[경고] {stock_code} 기본 데이터 체크 오류: {e}")
            return False

    async def _get_latest_minute_bar(self, stock_code: str, current_time: datetime) -> Optional[pd.DataFrame]:
        """
        완성된 최신 분봉 1개 수집 (미완성 봉 제외) + 전날 데이터 필터링 강화

        Args:
            stock_code: 종목코드
            current_time: 현재 시간

        Returns:
            pd.DataFrame: 완성된 최신 분봉 1개 또는 None
        """
        try:
            # 완성된 마지막 분봉 시간 계산
            current_minute_start = current_time.replace(second=0, microsecond=0)
            last_completed_minute = current_minute_start - timedelta(minutes=1)
            target_hour = last_completed_minute.strftime("%H%M%S")

            # 당일 날짜 (검증용)
            today_str = current_time.strftime("%Y%m%d")

            # 분봉 API로 완성된 데이터 조회
            div_code = get_div_code_for_stock(stock_code)

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

            # 전날 데이터 필터링 (최우선)
            chart_df = self._filter_today_in_chart(chart_df, today_str, stock_code, target_hour)

            if chart_df is None or chart_df.empty:
                return None

            # 최근 2개 분봉 추출 (선정 시점과 첫 업데이트 사이의 누락 방지)
            if 'time' in chart_df.columns and len(chart_df) > 0:
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
                prev_time = prev_hour * 10000 + prev_min * 100

                # 요청 시간과 1분 전 시간의 분봉 추출 (최대 2개)
                target_times = [prev_time, target_time]
                matched_data = chart_df_sorted[chart_df_sorted['time'].isin(target_times)]

                if not matched_data.empty:
                    latest_data = matched_data.copy()
                else:
                    latest_data = chart_df_sorted.tail(2).copy()
            else:
                latest_data = chart_df.copy()

            return latest_data

        except Exception as e:
            self.logger.error(f"[오류] {stock_code} 최신 분봉 수집 오류: {e}")
            return None

    def _filter_today_in_chart(self, chart_df: pd.DataFrame, today_str: str,
                               stock_code: str, target_hour: str) -> Optional[pd.DataFrame]:
        """차트 데이터에서 당일 데이터만 필터링"""
        before_filter_count = len(chart_df)

        if 'date' in chart_df.columns:
            chart_df = chart_df[chart_df['date'].astype(str) == today_str].copy()

            if before_filter_count != len(chart_df):
                removed = before_filter_count - len(chart_df)
                self.logger.warning(
                    f"[경고] {stock_code} 실시간 업데이트에서 전날 데이터 {removed}건 감지 및 제거: "
                    f"{before_filter_count} -> {len(chart_df)}건 (요청: {target_hour})"
                )

            if chart_df.empty:
                self.logger.error(
                    f"[실패] {stock_code} 전날 데이터만 반환됨 - 실시간 업데이트 중단 (요청: {target_hour})"
                )
                return None

        elif 'datetime' in chart_df.columns:
            chart_df['_date_str'] = pd.to_datetime(chart_df['datetime']).dt.strftime('%Y%m%d')
            chart_df = chart_df[chart_df['_date_str'] == today_str].copy()

            if '_date_str' in chart_df.columns:
                chart_df = chart_df.drop('_date_str', axis=1)

            if before_filter_count != len(chart_df):
                removed = before_filter_count - len(chart_df)
                self.logger.warning(
                    f"[경고] {stock_code} 실시간 업데이트에서 전날 데이터 {removed}건 감지 및 제거: "
                    f"{before_filter_count} -> {len(chart_df)}건 (요청: {target_hour})"
                )

            if chart_df.empty:
                self.logger.error(
                    f"[실패] {stock_code} 전날 데이터만 반환됨 - 실시간 업데이트 중단 (요청: {target_hour})"
                )
                return None
        else:
            self.logger.warning(
                f"[경고] {stock_code} date/datetime 컬럼 없음 - 전날 데이터 검증 불가 (요청: {target_hour})"
            )

        return chart_df

    def _validate_today_data_in_latest(self, data: pd.DataFrame, today_str: str,
                                        stock_code: str) -> Optional[pd.DataFrame]:
        """최신 데이터의 당일 검증"""
        before_validation_count = len(data)

        if 'date' in data.columns:
            data = data[data['date'].astype(str) == today_str].copy()

            if before_validation_count != len(data):
                removed = before_validation_count - len(data)
                self.logger.error(
                    f"[경고] {stock_code} 병합 전 2차 검증에서 전날 데이터 {removed}건 추가 발견 및 제거!"
                )

        elif 'datetime' in data.columns:
            data['_date_str'] = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d')
            data = data[data['_date_str'] == today_str].copy()

            if '_date_str' in data.columns:
                data = data.drop('_date_str', axis=1)

            if before_validation_count != len(data):
                removed = before_validation_count - len(data)
                self.logger.error(
                    f"[경고] {stock_code} 병합 전 2차 검증에서 전날 데이터 {removed}건 추가 발견 및 제거!"
                )

        return data

    def _final_today_validation(self, data: pd.DataFrame, today_str: str,
                                stock_code: str) -> Optional[pd.DataFrame]:
        """저장 직전 최종 당일 데이터 확인"""
        before_final_count = len(data)

        if 'date' in data.columns:
            data = data[data['date'].astype(str) == today_str].copy()
        elif 'datetime' in data.columns:
            data['_date_str'] = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d')
            data = data[data['_date_str'] == today_str].copy()

            if '_date_str' in data.columns:
                data = data.drop('_date_str', axis=1)

        if before_final_count != len(data):
            removed = before_final_count - len(data)
            self.logger.error(
                f"[경고] {stock_code} 저장 전 3차 검증에서 전날 데이터 {removed}건 최종 제거!"
            )

        return data
