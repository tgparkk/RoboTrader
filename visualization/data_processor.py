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
                return None
            
            if timeframe == "1min":
                return base_data
            elif timeframe == "3min":
                # 1분봉을 3분봉으로 변환
                return self._resample_to_3min(base_data)
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