"""
데이터 처리 및 지표 계산 전용 클래스
"""
import asyncio
import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Any
from utils.logger import setup_logger
from api.kis_chart_api import get_inquire_time_dailychartprice
from core.indicators.price_box import PriceBox
from core.indicators.bisector_line import BisectorLine
from core.indicators.bollinger_bands import BollingerBands
from core.indicators.multi_bollinger_bands import MultiBollingerBands


class DataProcessor:
    """데이터 처리 및 지표 계산 전용 클래스"""
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.logger.info("데이터 처리기 초기화 완료")
    
    async def get_historical_chart_data(self, stock_code: str, target_date: str) -> Optional[pd.DataFrame]:
        """
        특정 날짜의 전체 분봉 데이터 조회 (분할 조회로 전체 거래시간 커버)
        
        Args:
            stock_code: 종목코드
            target_date: 조회 날짜 (YYYYMMDD)
            
        Returns:
            pd.DataFrame: 전체 거래시간 분봉 데이터 (09:00~15:30)
        """
        try:
            self.logger.info(f"{stock_code} {target_date} 전체 분봉 데이터 조회 시작")
            
            # 분할 조회로 전체 거래시간 데이터 수집
            all_data = []
            
            # 15:30부터 거슬러 올라가면서 조회 (API는 최신 데이터부터 제공)
            # 1회 호출당 최대 120분 데이터 → 4번 호출로 전체 커버 (390분)
            time_points = ["153000", "143000", "123000", "103000", "093000"]  # 15:30, 14:30, 12:30, 10:30, 09:30
            
            for i, end_time in enumerate(time_points):
                try:
                    self.logger.info(f"{stock_code} 분봉 데이터 조회 {i+1}/5: {end_time[:2]}:{end_time[2:4]}까지")
                    result = await asyncio.to_thread(
                        get_inquire_time_dailychartprice,
                        stock_code=stock_code,
                        input_date=target_date,
                        input_hour=end_time,
                        past_data_yn="Y"
                    )
                    
                    if result is None:
                        self.logger.warning(f"{stock_code} {end_time} 시점 분봉 데이터 조회 실패")
                        continue
                    
                    summary_df, chart_df = result
                    
                    if chart_df.empty:
                        self.logger.warning(f"{stock_code} {end_time} 시점 분봉 데이터 없음")
                        continue
                    
                    # 데이터 검증
                    required_columns = ['open', 'high', 'low', 'close', 'volume']
                    missing_columns = [col for col in required_columns if col not in chart_df.columns]
                    
                    if missing_columns:
                        self.logger.warning(f"{stock_code} {end_time} 필수 컬럼 누락: {missing_columns}")
                        continue
                    
                    # 숫자 데이터 타입 변환
                    for col in required_columns:
                        chart_df[col] = pd.to_numeric(chart_df[col], errors='coerce')
                    
                    # 유효하지 않은 데이터 제거
                    chart_df = chart_df.dropna(subset=required_columns)
                    
                    if not chart_df.empty:
                        # 시간 범위 정보 추가 로깅
                        if 'time' in chart_df.columns:
                            time_col = 'time'
                        elif 'datetime' in chart_df.columns:
                            time_col = 'datetime'
                        else:
                            time_col = None
                            
                        if time_col:
                            first_time = chart_df[time_col].iloc[0]
                            last_time = chart_df[time_col].iloc[-1]
                            self.logger.info(f"{stock_code} {end_time} 시점 데이터 수집 완료: {len(chart_df)}건 ({first_time} ~ {last_time})")
                        else:
                            self.logger.info(f"{stock_code} {end_time} 시점 데이터 수집 완료: {len(chart_df)}건")
                            
                        all_data.append(chart_df)
                    
                    # API 호출 간격 조절
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    self.logger.error(f"{stock_code} {end_time} 시점 분봉 데이터 조회 중 오류: {e}")
                    continue
            
            # 수집된 모든 데이터 결합
            if not all_data:
                self.logger.error(f"{stock_code} {target_date} 모든 시간대 분봉 데이터 조회 실패")
                return None
            
            # 데이터프레임 결합 및 정렬
            combined_df = pd.concat(all_data, ignore_index=True)
            
            # 시간순 정렬 (오름차순)
            if 'datetime' in combined_df.columns:
                combined_df = combined_df.sort_values('datetime').reset_index(drop=True)
            elif 'time' in combined_df.columns:
                combined_df = combined_df.sort_values('time').reset_index(drop=True)
            
            # 중복 데이터 제거 (최신 데이터 유지)
            before_count = len(combined_df)
            if 'datetime' in combined_df.columns:
                combined_df = combined_df.drop_duplicates(subset=['datetime'], keep='last')
            elif 'time' in combined_df.columns:
                combined_df = combined_df.drop_duplicates(subset=['time'], keep='last')
            
            # 중복 제거 후 다시 시간순 정렬 (중요!)
            if 'datetime' in combined_df.columns:
                combined_df = combined_df.sort_values('datetime').reset_index(drop=True)
            elif 'time' in combined_df.columns:
                combined_df = combined_df.sort_values('time').reset_index(drop=True)
            
            after_count = len(combined_df)
            if before_count != after_count:
                self.logger.warning(f"중복 시간 데이터 제거: {before_count} → {after_count}")
            
            # 타겟 날짜 데이터만 필터링 (전날 데이터 제거)
            before_filter_count = len(combined_df)
            if 'datetime' in combined_df.columns:
                # datetime 컬럼이 있는 경우 날짜 필터링
                combined_df['date_str'] = pd.to_datetime(combined_df['datetime']).dt.strftime('%Y%m%d')
                combined_df = combined_df[combined_df['date_str'] == target_date].drop('date_str', axis=1)
            elif 'time' in combined_df.columns:
                # time 컬럼이 있는 경우 (YYYYMMDDHHMM 형식)
                combined_df['date_str'] = combined_df['time'].astype(str).str[:8]
                combined_df = combined_df[combined_df['date_str'] == target_date].drop('date_str', axis=1)
            
            after_filter_count = len(combined_df)
            if before_filter_count != after_filter_count:
                self.logger.info(f"날짜 필터링 완료: {before_filter_count} → {after_filter_count} (target_date: {target_date})")
            
            # 최종 데이터 검증
            if not combined_df.empty:
                time_col = 'time' if 'time' in combined_df.columns else 'datetime'
                if time_col in combined_df.columns:
                    first_time = combined_df[time_col].iloc[0]
                    last_time = combined_df[time_col].iloc[-1]
                    self.logger.info(f"{stock_code} {target_date} 최종 데이터 범위: {first_time} ~ {last_time}")
                    
                    # 13:30 이후 데이터 존재 확인
                    if time_col == 'time':
                        afternoon_data = combined_df[combined_df[time_col].astype(str).str[:4].astype(int) >= 1330]
                    else:
                        afternoon_data = combined_df[combined_df[time_col].dt.hour * 100 + combined_df[time_col].dt.minute >= 1330]
                    
                    if not afternoon_data.empty:
                        self.logger.info(f"{stock_code} 13:30 이후 데이터: {len(afternoon_data)}건")
                    else:
                        self.logger.warning(f"{stock_code} 13:30 이후 데이터 없음!")
            
            self.logger.info(f"{stock_code} {target_date} 전체 분봉 데이터 조합 완료: {len(combined_df)}건")
            return combined_df
            
        except Exception as e:
            self.logger.error(f"{stock_code} {target_date} 분봉 데이터 조회 오류: {e}")
            return None
    
    def get_timeframe_data(self, stock_code: str, target_date: str, timeframe: str, base_data: pd.DataFrame = None) -> Optional[pd.DataFrame]:
        """
        지정된 시간프레임의 데이터 조회/변환
        
        Args:
            stock_code: 종목코드
            target_date: 날짜
            timeframe: 시간프레임 ("1min", "3min")
            base_data: 기본 1분봉 데이터 (제공되면 재사용)
            
        Returns:
            pd.DataFrame: 시간프레임 데이터
        """
        try:
            # 1분봉 데이터를 기본으로 조회 (base_data가 제공되지 않은 경우에만)
            if base_data is None:
                base_data = asyncio.run(self.get_historical_chart_data(stock_code, target_date))
            
            if base_data is None or base_data.empty:
                self.logger.error(f"❌ {timeframe} 변환 실패: 기본 1분봉 데이터가 없음")
                return None
            
            self.logger.error(f"🔍 {timeframe} 변환 입력 확인:")
            self.logger.error(f"   - 입력 1분봉 개수: {len(base_data)}")
            self.logger.error(f"   - 시간 범위: {base_data.iloc[0].get('datetime', base_data.iloc[0].get('time', 'N/A'))} ~ {base_data.iloc[-1].get('datetime', base_data.iloc[-1].get('time', 'N/A'))}")
            
            if timeframe == "1min":
                return base_data
            elif timeframe == "3min":
                # 1분봉을 3분봉으로 변환
                return self._resample_to_3min(base_data)
            elif timeframe == "5min":
                # 1분봉을 5분봉으로 변환 (HTS와 동일한 방식)
                self.logger.error(f"   ➡️ 5분봉 변환 시작...")
                result = self._resample_to_5min(base_data)
                if result is not None:
                    self.logger.error(f"   ✅ 5분봉 변환 완료: {len(result)}개")
                else:
                    self.logger.error(f"   ❌ 5분봉 변환 결과 None")
                return result
            else:
                self.logger.warning(f"지원하지 않는 시간프레임: {timeframe}")
                return base_data
                
        except Exception as e:
            self.logger.error(f"시간프레임 데이터 조회 오류: {e}")
            return None
    
    def _resample_to_3min(self, data: pd.DataFrame) -> pd.DataFrame:
        """1분봉을 3분봉으로 변환"""
        try:
            if 'datetime' not in data.columns:
                return data
            
            # datetime을 인덱스로 설정
            data = data.set_index('datetime')
            
            # 3분봉으로 리샘플링
            resampled = data.resample('3T').agg({
                'open': 'first',
                'high': 'max', 
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            })
            
            # NaN 제거 후 인덱스 리셋
            resampled = resampled.dropna().reset_index()
            
            return resampled
            
        except Exception as e:
            self.logger.error(f"3분봉 변환 오류: {e}")
            return data
    
    def _resample_to_5min(self, data: pd.DataFrame) -> pd.DataFrame:
        """1분봉을 5분봉으로 변환 (정확한 5분 간격)"""
        try:
            if data is None or len(data) < 1:
                return data
            
            data = data.copy()
            
            # 시간 컬럼을 datetime으로 변환
            if 'datetime' in data.columns:
                data['datetime'] = pd.to_datetime(data['datetime'])
            elif 'time' in data.columns:
                # time 컬럼 형식 확인 및 변환
                time_str = data['time'].astype(str).str.zfill(6)  # HHMMSS 형식으로 맞춤
                data['datetime'] = pd.to_datetime('2024-01-01 ' + 
                                                time_str.str[:2] + ':' + 
                                                time_str.str[2:4] + ':' + 
                                                time_str.str[4:6])
            else:
                self.logger.error("datetime 또는 time 컬럼이 없습니다")
                return data
            
            # 시간순 정렬
            data = data.sort_values('datetime').reset_index(drop=True)
            
            self.logger.error(f"🚨 5분봉 변환 상세 디버깅:")
            self.logger.error(f"   📊 입력 데이터:")
            self.logger.error(f"   - 총 데이터 개수: {len(data)}")
            self.logger.error(f"   - 시간 범위: {data['datetime'].iloc[0]} ~ {data['datetime'].iloc[-1]}")
            self.logger.error(f"   - 전체 시간 span: {(data['datetime'].iloc[-1] - data['datetime'].iloc[0]).total_seconds() / 60:.1f}분")
            
            # 전체 시간 분포 확인
            time_spread = []
            for i in range(0, len(data), max(1, len(data)//20)):  # 20개 샘플
                dt = data['datetime'].iloc[i]
                time_spread.append(dt.strftime('%H:%M:%S'))
            self.logger.error(f"   - 시간 샘플 (20개): {time_spread}")
            
            # 시간 간격 분석
            if len(data) > 1:
                time_diffs = data['datetime'].diff().dropna()
                unique_intervals = time_diffs.value_counts().head(5)
                self.logger.error(f"   - 시간 간격 분포: {unique_intervals.to_dict()}")
            
            # 5분 그룹핑 전 상세 분석
            self.logger.error(f"   🔄 5분 그룹핑 과정:")
            data['group_time'] = data['datetime'].dt.floor('5min')  # 5분 단위로 내림
            
            unique_groups = data['group_time'].unique()
            sorted_groups = sorted(unique_groups)
            self.logger.error(f"   - 유니크 5분봉 그룹: {len(unique_groups)}개")
            self.logger.error(f"   - 첫 10개 그룹: {[g.strftime('%H:%M:%S') for g in sorted_groups[:10]]}")
            self.logger.error(f"   - 마지막 10개 그룹: {[g.strftime('%H:%M:%S') for g in sorted_groups[-10:]]}")
            
            # 이론적으로 있어야 할 5분봉들 확인
            expected_times = []
            start_time = pd.Timestamp('2024-01-01 09:00:00')
            for i in range(78):  # 09:00 ~ 15:30 = 78개
                time_str = (start_time + pd.Timedelta(minutes=i*5)).strftime('%H:%M:%S')
                expected_times.append(time_str)
            
            actual_times = [g.strftime('%H:%M:%S') for g in sorted_groups]
            missing_times = set(expected_times) - set(actual_times)
            extra_times = set(actual_times) - set(expected_times)
            
            if missing_times:
                self.logger.error(f"   ❌ 누락된 5분봉: {sorted(list(missing_times))}")
            if extra_times:
                self.logger.error(f"   ➕ 추가된 5분봉: {sorted(list(extra_times))}")
            if len(actual_times) == 77:
                self.logger.error(f"   🔍 77개 vs 78개 문제: 이론적 78개, 실제 {len(actual_times)}개")
            
            # 각 그룹당 데이터 개수 확인
            group_counts = data['group_time'].value_counts().sort_index()
            self.logger.error(f"   - 각 5분봉 그룹당 1분봉 개수:")
            for i, (group_time, count) in enumerate(group_counts.head(10).items()):
                self.logger.error(f"     {group_time.strftime('%H:%M:%S')}: {count}개 1분봉")
            
            if len(group_counts) != len(unique_groups):
                self.logger.error(f"   ⚠️ 그룹 개수 불일치: unique={len(unique_groups)}, counts={len(group_counts)}")
            
            # 그룹별로 OHLCV 계산
            grouped = data.groupby('group_time').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min', 
                'close': 'last',
                'volume': 'sum'
            }).reset_index()
            
            # datetime과 time 컬럼 추가
            grouped['datetime'] = grouped['group_time']
            grouped['time'] = grouped['datetime'].dt.strftime('%H%M%S')
            grouped = grouped.drop('group_time', axis=1)
            
            self.logger.error(f"🎯 5분봉 변환 최종 결과:")
            self.logger.error(f"   - 입력 1분봉: {len(data)}개")
            self.logger.error(f"   - 출력 5분봉: {len(grouped)}개")
            self.logger.error(f"   - 이론적 5분봉 개수: {(data['datetime'].iloc[-1] - data['datetime'].iloc[0]).total_seconds() / 60 / 5:.1f}개")
            
            if not grouped.empty:
                self.logger.error(f"   - 5분봉 시간 범위: {grouped['datetime'].iloc[0]} ~ {grouped['datetime'].iloc[-1]}")
                self.logger.error(f"   - 전체 5분봉 시간들: {grouped['time'].tolist()}")
                
                # 연속성 확인
                if len(grouped) > 1:
                    time_diffs = grouped['datetime'].diff().dropna()
                    intervals = [f'{td.total_seconds()/60:.0f}분' for td in time_diffs]
                    self.logger.error(f"   - 5분봉 간격들: {intervals}")
                    
                    # 5분 간격이 아닌 것들 찾기
                    non_5min_gaps = time_diffs[time_diffs != pd.Timedelta(minutes=5)]
                    if not non_5min_gaps.empty:
                        self.logger.error(f"   ⚠️ 비정상 간격 발견:")
                        for i, gap in enumerate(non_5min_gaps):
                            gap_minutes = gap.total_seconds() / 60
                            self.logger.error(f"     {i+1}: {gap_minutes:.0f}분 간격")
                else:
                    self.logger.error("   ⚠️ 5분봉이 1개만 생성됨 - 이것이 문제!")
                    
                # 마지막으로 각 5분봉의 OHLCV 값 확인 (처음 5개)
                self.logger.error(f"   - 처음 5개 5분봉 OHLCV:")
                for i in range(min(5, len(grouped))):
                    row = grouped.iloc[i]
                    self.logger.error(f"     {row['time']}: O={row['open']:.0f}, H={row['high']:.0f}, L={row['low']:.0f}, C={row['close']:.0f}, V={row['volume']}")
            else:
                self.logger.error("   ❌ 5분봉 결과가 비어있음!")
            
            return grouped
            
        except Exception as e:
            self.logger.error(f"❌ 5분봉 변환 오류: {e}")
            import traceback
            traceback.print_exc()
            return data
    
    def calculate_indicators_with_daily_data(self, data: pd.DataFrame, strategy, 
                                            daily_data: Optional[pd.DataFrame] = None,
                                            current_price: Optional[float] = None) -> Dict[str, Any]:
        """
        일봉 데이터를 포함한 지표 계산 (가격박스용)
        
        Args:
            data: 분봉 가격 데이터
            strategy: 거래 전략
            daily_data: 과거 29일 일봉 데이터
            current_price: 현재 가격
            
        Returns:
            Dict: 계산된 지표 데이터
        """
        try:
            indicators_data = {}
            
            if 'close' not in data.columns:
                self.logger.warning("가격 데이터에 'close' 컬럼이 없음")
                return {}
            
            for indicator_name in strategy.indicators:
                if indicator_name == "price_box":
                    # 가격박스 계산 (일봉 데이터 우선 사용)
                    try:
                        if daily_data is not None and not daily_data.empty and current_price is not None:
                            # 일봉 + 분봉 조합으로 정확한 곡선 형태 가격박스 계산
                            # 1. 일봉 29일 + 현재가로 기준점 계산
                            reference_result = PriceBox.calculate_price_box_with_daily_data(daily_data, current_price)
                            self.logger.info(f"📊 일봉 기준 가격박스: 중심선={reference_result['center_line']:.2f}, 상한선={reference_result['upper_band']:.2f}, 하한선={reference_result['lower_band']:.2f}")
                            
                            # 2. 일봉 데이터와 분봉 데이터 조합하여 30일 데이터 생성
                            combined_prices = self._combine_daily_and_intraday_data(daily_data, data, current_price)
                            
                            # 3. 조합된 데이터로 실시간 가격박스 계산 (곡선 형태)
                            if combined_prices is not None and len(combined_prices) >= 30:
                                price_box_result = PriceBox.calculate_price_box(combined_prices, period=30)
                                if price_box_result and 'center_line' in price_box_result:
                                    # HTS와 동일하게 시프트 없이 현재 시점 기준으로 계산
                                    indicators_data["price_box"] = {
                                        'center': price_box_result['center_line'],
                                        'resistance': price_box_result['upper_band'], 
                                        'support': price_box_result['lower_band']
                                    }
                                    self.logger.info(f"✅ 일봉+분봉 조합 가격박스 계산 성공 (곡선 형태, HTS 방식)")
                                else:
                                    # 조합 실패 시 일봉 기준 수평선 사용
                                    data_len = len(data)
                                    indicators_data["price_box"] = {
                                        'center': pd.Series([reference_result['center_line']] * data_len, index=data.index),
                                        'resistance': pd.Series([reference_result['upper_band']] * data_len, index=data.index),
                                        'support': pd.Series([reference_result['lower_band']] * data_len, index=data.index)
                                    }
                                    self.logger.warning("일봉+분봉 조합 실패, 일봉 기준 수평선 사용")
                            else:
                                # 데이터 부족 시 일봉 기준 수평선 사용
                                data_len = len(data)
                                indicators_data["price_box"] = {
                                    'center': pd.Series([reference_result['center_line']] * data_len, index=data.index),
                                    'resistance': pd.Series([reference_result['upper_band']] * data_len, index=data.index),
                                    'support': pd.Series([reference_result['lower_band']] * data_len, index=data.index)
                                }
                                self.logger.warning("조합 데이터 부족, 일봉 기준 수평선 사용")
                        else:
                            # 폴백: 기존 방식 (분봉 데이터만 사용)
                            price_box_result = PriceBox.calculate_price_box(data['close'])
                            if price_box_result and 'center_line' in price_box_result:
                                indicators_data["price_box"] = {
                                    'center': price_box_result['center_line'],
                                    'resistance': price_box_result['upper_band'],
                                    'support': price_box_result['lower_band']
                                }
                            self.logger.warning("가격박스 계산: 일봉 데이터 없음, 분봉 방식 사용")
                    except Exception as e:
                        self.logger.error(f"가격박스 계산 오류: {e}")
                
                elif indicator_name == "bisector_line":
                    # 이등분선 계산
                    try:
                        if 'high' in data.columns and 'low' in data.columns:
                            bisector_values = BisectorLine.calculate_bisector_line(data['high'], data['low'])
                            if bisector_values is not None:
                                indicators_data["bisector_line"] = {
                                    'line_values': bisector_values
                                }
                    except Exception as e:
                        self.logger.error(f"이등분선 계산 오류: {e}")
                
                elif indicator_name == "bollinger_bands":
                    # 볼린저밴드 계산
                    try:
                        bb_result = BollingerBands.calculate_bollinger_bands(data['close'])
                        if bb_result and 'center_line' in bb_result:
                            indicators_data["bollinger_bands"] = bb_result
                    except Exception as e:
                        self.logger.error(f"볼린저밴드 계산 오류: {e}")
                
                elif indicator_name == "multi_bollinger_bands":
                    # 다중 볼린저밴드 계산
                    try:
                        from core.indicators.multi_bollinger_bands import MultiBollingerBands
                        multi_bb = MultiBollingerBands.calculate_multi_bollinger_bands(data['close'])
                        if multi_bb:
                            indicators_data["multi_bollinger_bands"] = multi_bb
                    except Exception as e:
                        self.logger.error(f"다중 볼린저밴드 계산 오류: {e}")
            
            return indicators_data
            
        except Exception as e:
            self.logger.error(f"지표 계산 오류: {e}")
            return {}
    
    def _combine_daily_and_intraday_data(self, daily_data: pd.DataFrame, intraday_data: pd.DataFrame, 
                                       current_price: Optional[float] = None) -> Optional[pd.Series]:
        """
        일봉 데이터와 분봉 데이터를 조합하여 30일 가격 시리즈 생성
        
        Args:
            daily_data: 과거 일봉 데이터 (29일)
            intraday_data: 당일 분봉 데이터 
            current_price: 현재 가격 (선택사항)
            
        Returns:
            pd.Series: 조합된 30일 가격 시리즈 (29일 일봉 종가 + 당일 분봉 종가들)
        """
        try:
            # 1. 일봉 종가 추출 (29일)
            close_col = None
            for col in ['stck_clpr', 'close', 'Close', 'CLOSE', 'clpr']:
                if col in daily_data.columns:
                    close_col = col
                    break
            
            if close_col is None:
                self.logger.warning("일봉 데이터에서 종가 컬럼을 찾을 수 없음")
                return None
            
            daily_closes = pd.to_numeric(daily_data[close_col], errors='coerce').dropna()
            
            if len(daily_closes) < 88:
                self.logger.warning(f"일봉 데이터 부족: {len(daily_closes)}일 (9시부터 TMA30 계산을 위해 최소 88일 필요)")
                return None
            
            # 최근 88일 선택 (당일 9시 첫 분봉부터 TMA30 계산 가능하도록)
            daily_closes = daily_closes.tail(88)
            
            # 2. 분봉 종가 추출 (당일)
            if 'close' not in intraday_data.columns:
                self.logger.warning("분봉 데이터에 'close' 컬럼이 없음")
                return None
            
            intraday_closes = pd.to_numeric(intraday_data['close'], errors='coerce').dropna()
            
            if len(intraday_closes) == 0:
                self.logger.warning("유효한 분봉 종가 데이터가 없음")
                return None
            
            # 3. 데이터 조합: [29일 일봉 종가] + [당일 분봉 종가들]
            # 29일 일봉 종가를 리스트로 변환
            daily_list = daily_closes.tolist()
            
            # 당일 분봉 종가를 리스트로 변환
            intraday_list = intraday_closes.tolist()
            
            # 조합
            combined_list = daily_list + intraday_list
            
            # pandas Series로 변환 (인덱스는 분봉 데이터와 동일하게 맞춤)
            # 마지막 분봉 개수만큼 인덱스 사용
            if len(intraday_list) > 0:
                # 분봉 데이터 길이에 맞춰 전체 조합 데이터를 슬라이싱
                combined_series = pd.Series(combined_list, index=range(len(combined_list)))
                
                # 분봉 인덱스에 맞게 마지막 부분만 추출하여 반환
                intraday_length = len(intraday_data)
                if len(combined_series) >= intraday_length:
                    result_series = pd.Series(combined_list[-intraday_length:], index=intraday_data.index)
                else:
                    # 데이터가 부족한 경우 사용 가능한 모든 데이터 사용
                    result_series = pd.Series(combined_list, index=intraday_data.index[:len(combined_list)])
                
                self.logger.info(f"✅ 일봉+분봉 데이터 조합 성공: 일봉 {len(daily_list)}일 (과거 88일) + 분봉 {len(intraday_list)}개 = 총 {len(combined_list)}개")
                return result_series
            else:
                return None
            
        except Exception as e:
            self.logger.error(f"일봉+분봉 데이터 조합 오류: {e}")
            return None
    
    def calculate_indicators(self, data: pd.DataFrame, strategy) -> Dict[str, Any]:
        """
        전략에 따른 지표 계산
        
        Args:
            data: 가격 데이터
            strategy: 거래 전략
            
        Returns:
            Dict: 계산된 지표 데이터
        """
        try:
            indicators_data = {}
            
            if 'close' not in data.columns:
                self.logger.warning("가격 데이터에 'close' 컬럼이 없음")
                return {}
            
            for indicator_name in strategy.indicators:
                if indicator_name == "price_box":
                    # 가격박스 계산
                    try:
                        price_box_result = PriceBox.calculate_price_box(data['close'])
                        if price_box_result and 'center_line' in price_box_result:
                            indicators_data["price_box"] = {
                                'center': price_box_result['center_line'],
                                'resistance': price_box_result['upper_band'],
                                'support': price_box_result['lower_band']
                            }
                    except Exception as e:
                        self.logger.error(f"가격박스 계산 오류: {e}")
                
                elif indicator_name == "bisector_line":
                    # 이등분선 계산
                    try:
                        if 'high' in data.columns and 'low' in data.columns:
                            bisector_values = BisectorLine.calculate_bisector_line(data['high'], data['low'])
                            if bisector_values is not None:
                                indicators_data["bisector_line"] = {
                                    'line_values': bisector_values
                                }
                    except Exception as e:
                        self.logger.error(f"이등분선 계산 오류: {e}")
                
                elif indicator_name == "bollinger_bands":
                    # 볼린저밴드 계산
                    try:
                        bb_result = BollingerBands.calculate_bollinger_bands(data['close'])
                        if bb_result and 'upper_band' in bb_result:
                            indicators_data["bollinger_bands"] = {
                                'upper': bb_result['upper_band'],
                                'middle': bb_result['sma'],
                                'lower': bb_result['lower_band']
                            }
                    except Exception as e:
                        self.logger.error(f"볼린저밴드 계산 오류: {e}")
                
                elif indicator_name == "multi_bollinger_bands":
                    # 다중 볼린저밴드 계산
                    try:
                        # MultiBollingerBands.generate_trading_signals 사용
                        signals_df = MultiBollingerBands.generate_trading_signals(data['close'])
                        
                        if not signals_df.empty:
                            # 각 기간별 데이터 추출
                            multi_bb_data = {}
                            for period in [50, 40, 30, 20]:
                                sma_key = f'sma_{period}'
                                upper_key = f'upper_{period}'
                                lower_key = f'lower_{period}'
                                
                                if all(key in signals_df.columns for key in [sma_key, upper_key, lower_key]):
                                    multi_bb_data[sma_key] = signals_df[sma_key]
                                    multi_bb_data[upper_key] = signals_df[upper_key]
                                    multi_bb_data[lower_key] = signals_df[lower_key]
                            
                            # 상한선 밀집도와 이등분선 추가
                            if 'upper_convergence' in signals_df.columns:
                                multi_bb_data['upper_convergence'] = signals_df['upper_convergence']
                            
                            if 'bisector_line' in signals_df.columns:
                                multi_bb_data['bisector_line'] = signals_df['bisector_line']
                            
                            indicators_data["multi_bollinger_bands"] = multi_bb_data
                            
                    except Exception as e:
                        self.logger.error(f"다중 볼린저밴드 계산 오류: {e}")
            
            return indicators_data
            
        except Exception as e:
            self.logger.error(f"지표 계산 오류: {e}")
            return {}
    
    def validate_and_clean_data(self, data: pd.DataFrame, target_date: str = None) -> pd.DataFrame:
        """데이터 검증 및 중복 제거"""
        try:
            if data.empty:
                return data
                
            # 날짜 필터링 (target_date가 제공된 경우)
            if target_date:
                original_count = len(data)
                if 'datetime' in data.columns:
                    # datetime 컬럼이 있는 경우
                    data['date_str'] = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d')
                    data = data[data['date_str'] == target_date].drop('date_str', axis=1)
                elif 'time' in data.columns:
                    # time 컬럼이 있는 경우 (YYYYMMDDHHMM 형식)
                    data['date_str'] = data['time'].astype(str).str[:8]
                    data = data[data['date_str'] == target_date].drop('date_str', axis=1)
                
                if len(data) != original_count:
                    self.logger.info(f"날짜 필터링 완료: {original_count} → {len(data)} (target_date: {target_date})")
            
            if 'time' not in data.columns:
                return data
            
            # 시간 중복 제거
            original_count = len(data)
            cleaned_data = data.drop_duplicates(subset=['time'], keep='first')
            
            if len(cleaned_data) != original_count:
                self.logger.warning(f"중복 시간 데이터 제거: {original_count} → {len(cleaned_data)}")
            
            # 시간 순 정렬
            cleaned_data = cleaned_data.sort_values('time')
            
            # 인덱스 재설정
            cleaned_data = cleaned_data.reset_index(drop=True)
            
            return cleaned_data
            
        except Exception as e:
            self.logger.error(f"데이터 검증 오류: {e}")
            return data