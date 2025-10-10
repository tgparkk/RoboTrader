"""
분봉 데이터 수집/재수집 전담 클래스

IntradayStockManager에서 분봉 데이터 수집 관련 로직을 분리
"""
import asyncio
import pickle
from pathlib import Path
from typing import List, Optional, Dict
import pandas as pd
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_chart_api import (
    get_inquire_time_itemchartprice,
    get_full_trading_day_data_async,
    get_div_code_for_stock
)
from api.kis_market_api import get_inquire_daily_itemchartprice


class MinuteDataCollector:
    """분봉 데이터 수집/재수집 전담 클래스"""

    def __init__(self):
        self.logger = setup_logger(__name__)
        # 캐시 디렉토리
        self.minute_cache_dir = Path("cache/minute_data")
        self.minute_cache_dir.mkdir(parents=True, exist_ok=True)

    async def collect_missing_minute_bars(self, stock_code: str, missing_time_strs: List[str]) -> Optional[pd.DataFrame]:
        """
        누락된 특정 시간의 분봉들을 수집

        Args:
            stock_code: 종목코드
            missing_time_strs: 누락된 시간 목록 (HHMMSS 형식)

        Returns:
            pd.DataFrame: 수집된 분봉 데이터 또는 None
        """
        try:
            if not missing_time_strs:
                return None

            self.logger.info(f"🔄 {stock_code} 누락 분봉 재수집 시작: {len(missing_time_strs)}개 ({missing_time_strs[0]}~{missing_time_strs[-1]})")

            div_code = get_div_code_for_stock(stock_code)

            # 각 누락 시간에 대해 분봉 수집
            collected_data = []
            for time_str in missing_time_strs:
                try:
                    result = get_inquire_time_itemchartprice(
                        div_code=div_code,
                        stock_code=stock_code,
                        input_hour=time_str,
                        past_data_yn="N"
                    )

                    if result is not None:
                        _, chart_df = result
                        if not chart_df.empty:
                            # 해당 시간의 데이터만 필터링
                            target_data = chart_df[chart_df['time'].astype(str).str.zfill(6) == time_str].copy()
                            if not target_data.empty:
                                collected_data.append(target_data)

                    # API 호출 간격 (초당 20회 제한)
                    await asyncio.sleep(0.05)

                except Exception as e:
                    self.logger.warning(f"⚠️ {stock_code} {time_str} 분봉 수집 실패: {e}")
                    continue

            if not collected_data:
                self.logger.warning(f"❌ {stock_code} 누락 분봉 수집 실패")
                return None

            # 수집된 데이터 병합
            new_data = pd.concat(collected_data, ignore_index=True)
            self.logger.info(f"✅ {stock_code} 누락 분봉 재수집 완료: {len(new_data)}개")

            return new_data

        except Exception as e:
            self.logger.error(f"❌ {stock_code} 누락 분봉 재수집 오류: {e}")
            return None

    def _calculate_time_range_minutes(self, start_time: str, end_time: str) -> int:
        """
        시작 시간과 종료 시간 사이의 분 수 계산

        Args:
            start_time: 시작 시간 (HHMMSS)
            end_time: 종료 시간 (HHMMSS)

        Returns:
            int: 분 수
        """
        try:
            start_hour = int(start_time[:2]) if len(start_time) >= 2 else 0
            start_min = int(start_time[2:4]) if len(start_time) >= 4 else 0
            end_hour = int(end_time[:2]) if len(end_time) >= 2 else 0
            end_min = int(end_time[2:4]) if len(end_time) >= 4 else 0

            start_total_min = start_hour * 60 + start_min
            end_total_min = end_hour * 60 + end_min

            return end_total_min - start_total_min
        except Exception:
            return 0

    async def collect_full_historical_data(self, stock_code: str, selected_time: datetime, retry_with_adjusted_time: bool = True) -> Optional[pd.DataFrame]:
        """
        당일 08:00부터 선정시점까지의 전체 분봉 데이터 수집

        Args:
            stock_code: 종목코드
            selected_time: 종목 선정 시간
            retry_with_adjusted_time: 실패 시 시간 조정하여 재시도 여부

        Returns:
            pd.DataFrame: 수집된 분봉 데이터 또는 None
        """
        try:
            self.logger.info(f"📈 {stock_code} 전체 거래시간 분봉 데이터 수집 시작")
            self.logger.info(f"   선정 시간: {selected_time.strftime('%H:%M:%S')}")

            # 당일 09:00부터 선정시점까지의 전체 거래시간 데이터 수집
            target_date = selected_time.strftime("%Y%m%d")
            target_hour = selected_time.strftime("%H%M%S")

            # 전체 거래시간 데이터 수집 (async 버전 사용)
            historical_data = await get_full_trading_day_data_async(
                stock_code=stock_code,
                target_date=target_date,
                selected_time=target_hour,
                start_time="090000"
            )

            # 실패 시 시간 조정하여 재시도
            if (historical_data is None or historical_data.empty) and retry_with_adjusted_time:
                from datetime import timedelta
                try:
                    selected_time_dt = datetime.strptime(target_hour, "%H%M%S")
                    new_time_dt = selected_time_dt + timedelta(minutes=1)
                    new_target_hour = new_time_dt.strftime("%H%M%S")

                    # 장 마감 시간(15:30) 초과 시 현재 시간으로 조정
                    if new_target_hour > "153000":
                        new_target_hour = now_kst().strftime("%H%M%S")

                    self.logger.warning(f"🔄 {stock_code} 전체 데이터 조회 실패, 시간 조정하여 재시도: {target_hour} → {new_target_hour}")

                    # 조정된 시간으로 재시도
                    historical_data = await get_full_trading_day_data_async(
                        stock_code=stock_code,
                        target_date=target_date,
                        selected_time=new_target_hour,
                        start_time="090000"
                    )

                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 전체 데이터 시간 조정 중 오류: {e}")

            if historical_data is None or historical_data.empty:
                self.logger.error(f"❌ {stock_code} 당일 전체 분봉 데이터 조회 실패")
                return None

            # 데이터 정렬 및 정리 (시간 순서)
            if 'datetime' in historical_data.columns:
                historical_data = historical_data.sort_values('datetime').reset_index(drop=True)
                # 선정 시간을 timezone-naive로 변환하여 pandas datetime64[ns]와 비교
                selected_time_naive = selected_time.replace(tzinfo=None)
                filtered_data = historical_data[historical_data['datetime'] <= selected_time_naive].copy()
            elif 'time' in historical_data.columns:
                historical_data = historical_data.sort_values('time').reset_index(drop=True)
                # time 컬럼을 이용한 필터링
                selected_time_str = selected_time.strftime("%H%M%S")
                historical_data['time_str'] = historical_data['time'].astype(str).str.zfill(6)
                filtered_data = historical_data[historical_data['time_str'] <= selected_time_str].copy()
                if 'time_str' in filtered_data.columns:
                    filtered_data = filtered_data.drop('time_str', axis=1)
            else:
                # 시간 컬럼이 없으면 전체 데이터 사용
                filtered_data = historical_data.copy()

            # 1분봉 연속성 검증
            validation_result = self._validate_minute_data_continuity(filtered_data, stock_code)
            if not validation_result['valid']:
                self.logger.error(f"❌ {stock_code} 1분봉 연속성 검증 실패: {validation_result['reason']}")
                return None

            data_count = len(filtered_data)
            if data_count > 0:
                if 'time' in filtered_data.columns:
                    start_time = str(filtered_data.iloc[0].get('time', 'N/A'))
                    end_time = str(filtered_data.iloc[-1].get('time', 'N/A'))
                elif 'datetime' in filtered_data.columns:
                    start_dt = filtered_data.iloc[0].get('datetime')
                    end_dt = filtered_data.iloc[-1].get('datetime')
                    start_time = start_dt.strftime('%H%M%S') if start_dt else 'N/A'
                    end_time = end_dt.strftime('%H%M%S') if end_dt else 'N/A'
                else:
                    start_time = end_time = 'N/A'

                # 시간 범위 계산
                time_range_minutes = self._calculate_time_range_minutes(start_time, end_time)

                self.logger.info(f"✅ {stock_code} 당일 전체 분봉 수집 성공! (09:00~{selected_time.strftime('%H:%M')})")
                self.logger.info(f"   총 데이터: {data_count}건")
                self.logger.info(f"   시간 범위: {start_time} ~ {end_time} ({time_range_minutes}분)")

                # 3분봉 변환 예상 개수 계산
                expected_3min_count = data_count // 3
                self.logger.info(f"   예상 3분봉: {expected_3min_count}개 (최소 5개 필요)")

                if expected_3min_count >= 5:
                    self.logger.info(f"   ✅ 신호 생성 조건 충족!")
                else:
                    self.logger.warning(f"   ⚠️ 3분봉 데이터 부족 위험: {expected_3min_count}/5")

                # 09:00부터 데이터가 시작되는지 확인
                if start_time and start_time >= "090000":
                    self.logger.info(f"   📊 정규장 데이터: {start_time}부터")

            return filtered_data

        except Exception as e:
            self.logger.error(f"❌ {stock_code} 전체 거래시간 분봉 데이터 수집 오류: {e}")
            return None

    def _validate_minute_data_continuity(self, minute_data: pd.DataFrame, stock_code: str) -> dict:
        """
        1분봉 데이터 연속성 검증

        Args:
            minute_data: 분봉 데이터
            stock_code: 종목코드 (로깅용)

        Returns:
            dict: {'valid': bool, 'reason': str}
        """
        try:
            if minute_data.empty:
                return {'valid': False, 'reason': '데이터 없음'}

            # time 컬럼 확인
            if 'time' not in minute_data.columns:
                return {'valid': False, 'reason': 'time 컬럼 없음'}

            times = minute_data['time'].tolist()

            # 최소 데이터 개수 확인
            if len(times) < 5:
                return {'valid': False, 'reason': f'데이터 부족 ({len(times)}개)'}

            # 시작 시간 확인 (09:00 시작)
            first_time_str = str(times[0]).zfill(6)
            first_hour = int(first_time_str[:2])

            if first_hour != 9:
                return {'valid': False, 'reason': f'시작 시간 오류 ({first_time_str})'}

            # 1분 간격 연속성 확인
            for i in range(1, len(times)):
                prev_time_str = str(times[i-1]).zfill(6)
                curr_time_str = str(times[i]).zfill(6)

                prev_hour = int(prev_time_str[:2])
                prev_min = int(prev_time_str[2:4])
                curr_hour = int(curr_time_str[:2])
                curr_min = int(curr_time_str[2:4])

                # 예상 다음 시간 계산
                if prev_min == 59:
                    expected_hour = prev_hour + 1
                    expected_min = 0
                else:
                    expected_hour = prev_hour
                    expected_min = prev_min + 1

                # 1분 간격이 아니면 누락
                if curr_hour != expected_hour or curr_min != expected_min:
                    # 🆕 15:18 이후 누락은 장 마감 후라 정상 (체크 생략)
                    prev_time_int = prev_hour * 100 + prev_min
                    if prev_time_int >= 1518:
                        break  # 15:18 이후는 체크 안함
                    
                    # 🆕 누락 개수 계산 (1개는 HTS 데이터 없을 가능성 - 허용, 2개 이상만 에러)
                    missing_count = 0
                    check_hour, check_min = expected_hour, expected_min
                    while check_hour < curr_hour or (check_hour == curr_hour and check_min < curr_min):
                        missing_count += 1
                        # 다음 분으로 이동
                        if check_min == 59:
                            check_hour += 1
                            check_min = 0
                        else:
                            check_min += 1
                        # 무한 루프 방지
                        if missing_count > 60:
                            break
                    
                    # 1개 누락은 HTS 자체에 데이터 없을 가능성 - 허용 (디버그 로그만)
                    if missing_count == 1:
                        self.logger.debug(f"{stock_code} 소규모 분봉 누락(1개): {prev_time_str}→{curr_time_str} (HTS 데이터 없음 가능)")
                        continue  # 다음 체크 진행
                    else:
                        # 2개 이상 연속 누락은 에러
                        return {'valid': False, 'reason': f'분봉 누락: {prev_time_str}→{curr_time_str} ({missing_count}개)'}

            return {'valid': True, 'reason': ''}

        except Exception as e:
            return {'valid': False, 'reason': f'검증 오류: {str(e)}'}

    def merge_minute_data(self, existing_data: pd.DataFrame, new_data: pd.DataFrame) -> pd.DataFrame:
        """
        기존 분봉 데이터와 새 데이터를 병합

        Args:
            existing_data: 기존 데이터
            new_data: 새로 수집한 데이터

        Returns:
            pd.DataFrame: 병합된 데이터
        """
        try:
            if existing_data.empty:
                return new_data

            if new_data.empty:
                return existing_data

            # 병합 후 중복 제거
            merged = pd.concat([existing_data, new_data], ignore_index=True)

            if 'time' in merged.columns:
                merged = merged.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
            elif 'datetime' in merged.columns:
                merged = merged.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime').reset_index(drop=True)

            return merged

        except Exception as e:
            self.logger.error(f"데이터 병합 오류: {e}")
            return existing_data

    def get_combined_chart_data(self, historical_data: pd.DataFrame, realtime_data: pd.DataFrame,
                                selected_time: datetime, stock_code: str = "") -> Optional[pd.DataFrame]:
        """
        historical_data와 realtime_data를 결합 (완성된 봉만)

        Args:
            historical_data: 과거 분봉 데이터
            realtime_data: 실시간 분봉 데이터
            selected_time: 선정 시간
            stock_code: 종목코드 (로깅용)

        Returns:
            pd.DataFrame: 결합된 분봉 데이터
        """
        try:
            # 1. historical_data와 realtime_data 병합
            if historical_data.empty and realtime_data.empty:
                return pd.DataFrame()

            if realtime_data.empty:
                combined = historical_data.copy()
            elif historical_data.empty:
                combined = realtime_data.copy()
            else:
                combined = pd.concat([historical_data, realtime_data], ignore_index=True)

                # 중복 제거 (time 기준)
                if 'time' in combined.columns:
                    combined = combined.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
                elif 'datetime' in combined.columns:
                    combined = combined.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime').reset_index(drop=True)

            # 2. 미완성 분봉 제거 (현재 진행중인 분)
            current_time = now_kst()
            current_minute_start = current_time.replace(second=0, microsecond=0)

            if 'datetime' in combined.columns:
                combined['datetime'] = pd.to_datetime(combined['datetime'])
                # timezone-aware datetime을 naive로 변환
                current_minute_naive = current_minute_start.replace(tzinfo=None)
                # 현재 진행중인 분 제외
                combined = combined[combined['datetime'] < current_minute_naive].copy()
            elif 'time' in combined.columns:
                # time 컬럼이 있는 경우 (HHMMSS 형식)
                current_time_str = current_minute_start.strftime("%H%M%S")
                combined['time_str'] = combined['time'].astype(str).str.zfill(6)
                combined = combined[combined['time_str'] < current_time_str].copy()
                if 'time_str' in combined.columns:
                    combined = combined.drop('time_str', axis=1)

            return combined

        except Exception as e:
            self.logger.error(f"분봉 데이터 결합 오류 ({stock_code}): {e}")
            return pd.DataFrame()

    def save_minute_data_to_cache(self, stock_code: str, date_str: str, data: pd.DataFrame) -> bool:
        """
        분봉 데이터를 캐시에 저장

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)
            data: 분봉 데이터

        Returns:
            bool: 저장 성공 여부
        """
        try:
            cache_file = self.minute_cache_dir / f"{stock_code}_{date_str}.pkl"
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            self.logger.debug(f"💾 {stock_code} {date_str} 분봉 캐시 저장")
            return True
        except Exception as e:
            self.logger.error(f"분봉 캐시 저장 실패 ({stock_code}, {date_str}): {e}")
            return False

    def load_minute_data_from_cache(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """
        캐시에서 분봉 데이터 로드

        Args:
            stock_code: 종목코드
            date_str: 날짜 (YYYYMMDD)

        Returns:
            pd.DataFrame: 분봉 데이터 또는 None
        """
        try:
            cache_file = self.minute_cache_dir / f"{stock_code}_{date_str}.pkl"
            if not cache_file.exists():
                return None

            with open(cache_file, 'rb') as f:
                data = pickle.load(f)

            if isinstance(data, pd.DataFrame) and not data.empty:
                self.logger.debug(f"💾 {stock_code} {date_str} 분봉 캐시 로드")
                return data
            return None
        except Exception as e:
            self.logger.error(f"분봉 캐시 로드 실패 ({stock_code}, {date_str}): {e}")
            return None

    async def collect_daily_data_for_ml(self, stock_code: str, days: int = 100) -> pd.DataFrame:
        """
        ML 예측용 일봉 데이터 수집

        Args:
            stock_code: 종목코드
            days: 수집할 일봉 개수

        Returns:
            pd.DataFrame: 일봉 데이터
        """
        try:
            # 일봉 API 호출 (최근 100일)
            result = get_inquire_daily_itemchartprice(
                itm_no=stock_code,
                period_code="D"
            )

            if result is None or len(result) != 2:
                self.logger.warning(f"⚠️ {stock_code} 일봉 데이터 조회 실패")
                return pd.DataFrame()

            summary_df, chart_df = result

            if chart_df.empty:
                self.logger.warning(f"⚠️ {stock_code} 일봉 데이터 없음")
                return pd.DataFrame()

            self.logger.debug(f"✅ {stock_code} 일봉 데이터 수집: {len(chart_df)}건")
            return chart_df

        except Exception as e:
            self.logger.error(f"일봉 데이터 수집 오류 ({stock_code}): {e}")
            return pd.DataFrame()
