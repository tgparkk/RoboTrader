"""
시간봉 변환 유틸리티 클래스
1분봉 데이터를 다양한 시간봉(3분, 5분 등)으로 변환하는 기능 제공
"""
import pandas as pd
from typing import Optional
from utils.logger import setup_logger


class TimeFrameConverter:
    """시간봉 변환 전용 클래스"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
    
    @staticmethod
    def convert_to_timeframe(data: pd.DataFrame, timeframe_minutes: int) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 지정된 시간봉으로 변환
        
        Args:
            data: 1분봉 DataFrame (open, high, low, close, volume 컬럼 필요)
            timeframe_minutes: 변환할 시간봉 (분 단위, 예: 3, 5, 15, 30)
            
        Returns:
            변환된 시간봉 DataFrame 또는 None
        """
        logger = setup_logger(__name__)
        
        try:
            if data is None or len(data) < timeframe_minutes:
                return None
            
            df = data.copy()
            
            # datetime 컬럼 확인 및 변환
            if 'datetime' not in df.columns:
                if 'date' in df.columns and 'time' in df.columns:
                    df['datetime'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str))
                elif 'time' in df.columns:
                    # time 컬럼만 있는 경우 임시 날짜 추가
                    time_str = df['time'].astype(str).str.zfill(6)
                    df['datetime'] = pd.to_datetime('2024-01-01 ' + 
                                                  time_str.str[:2] + ':' + 
                                                  time_str.str[2:4] + ':' + 
                                                  time_str.str[4:6])
                else:
                    # datetime 컬럼이 없으면 순차적으로 생성 (09:00부터)
                    df['datetime'] = pd.date_range(start='09:00', periods=len(df), freq='1min')
            
            # datetime을 인덱스로 설정
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
            
            # 지정된 시간봉으로 리샘플링
            resampled = df.resample(f'{timeframe_minutes}T').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            })
            
            # NaN 제거 후 인덱스 리셋
            resampled = resampled.dropna().reset_index()

            # 확정 봉만 사용: 마지막 행은 진행 중일 수 있으므로 제외
            if resampled is not None and len(resampled) >= 1:
                resampled = resampled.iloc[:-1] if len(resampled) > 0 else resampled
            
            logger.debug(f"📊 {timeframe_minutes}분봉 변환: {len(data)}개 → {len(resampled)}개")
            
            return resampled
            
        except Exception as e:
            logger.error(f"❌ {timeframe_minutes}분봉 변환 오류: {e}")
            return None
    
    @staticmethod
    def convert_to_3min_data(data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 3분봉으로 변환 (기존 호환성 유지)
        
        Args:
            data: 1분봉 DataFrame
            
        Returns:
            3분봉 DataFrame 또는 None
        """
        return TimeFrameConverter.convert_to_timeframe(data, 3)
    
    @staticmethod
    def convert_to_5min_data_hts_style(data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 5분봉으로 변환 (HTS 방식)
        기존 _convert_to_5min_data와 동일한 로직
        
        Args:
            data: 1분봉 DataFrame
            
        Returns:
            5분봉 DataFrame 또는 None
        """
        logger = setup_logger(__name__)
        
        try:
            if data is None or len(data) < 5:
                return None
            
            # 시간 컬럼 확인 및 변환
            if 'datetime' in data.columns:
                data = data.copy()
                data['datetime'] = pd.to_datetime(data['datetime'])
                data = data.set_index('datetime')
            elif 'date' in data.columns and 'time' in data.columns:
                data = data.copy()
                # date와 time을 datetime으로 결합
                data['datetime'] = pd.to_datetime(data['date'].astype(str) + ' ' + data['time'].astype(str))
                data = data.set_index('datetime')
            else:
                # datetime 인덱스가 없으면 인덱스를 생성
                data = data.copy()
                data.index = pd.date_range(start='08:00', periods=len(data), freq='1min')
            
            # HTS와 동일하게 시간 기준 5분봉으로 그룹핑
            data_5min_list = []
            
            # 시간을 분 단위로 변환 (08:00 = 0분 기준, NXT 거래소 지원)
            if hasattr(data.index, 'hour'):
                data['minutes_from_8am'] = (data.index.hour - 8) * 60 + data.index.minute
            else:
                # datetime 인덱스가 아닌 경우 순차적으로 처리
                data['minutes_from_8am'] = range(len(data))
            
            # 5분 단위로 그룹핑 (0-4분→그룹0, 5-9분→그룹1, ...)
            # 하지만 실제로는 5분간의 데이터를 포함해야 함
            grouped = data.groupby(data['minutes_from_8am'] // 5)
            
            for group_id, group in grouped:
                if len(group) > 0:
                    # 5분봉 시간은 해당 구간의 끝 + 1분 (5분간 포함)
                    # 예: 08:00~08:04 → 08:05, 08:05~08:09 → 08:10
                    base_minute = group_id * 5
                    end_minute = base_minute + 5  # 5분 후가 캔들 시간
                    
                    # 08:00 기준으로 계산한 절대 시간
                    target_hour = 8 + (end_minute // 60)
                    target_min = end_minute % 60
                    
                    # 실제 5분봉 시간 생성 (구간 끝 + 1분)
                    if hasattr(data.index, 'date') and len(data.index) > 0:
                        base_date = data.index[0].date()
                        from datetime import time
                        end_time = pd.Timestamp.combine(base_date, time(hour=target_hour, minute=target_min, second=0))
                    else:
                        # 인덱스가 datetime이 아닌 경우 기본값 사용
                        end_time = pd.Timestamp(f'2023-01-01 {target_hour:02d}:{target_min:02d}:00')
                    
                    # 15:30을 넘지 않도록 제한
                    if target_hour > 15 or (target_hour == 15 and target_min > 30):
                        if hasattr(data.index, 'date') and len(data.index) > 0:
                            base_date = data.index[0].date()
                            from datetime import time
                            end_time = pd.Timestamp.combine(base_date, time(hour=15, minute=30, second=0))
                        else:
                            end_time = pd.Timestamp('2023-01-01 15:30:00')
                    
                    data_5min_list.append({
                        'datetime': end_time,
                        'open': group['open'].iloc[0],
                        'high': group['high'].max(),
                        'low': group['low'].min(), 
                        'close': group['close'].iloc[-1],
                        'volume': group['volume'].sum()
                    })
            
            data_5min = pd.DataFrame(data_5min_list)
            
            logger.debug(f"📊 HTS 방식 5분봉 변환: {len(data)}개 → {len(data_5min)}개 완료")
            if not data_5min.empty:
                logger.debug(f"시간 범위: {data_5min['datetime'].iloc[0]} ~ {data_5min['datetime'].iloc[-1]}")
            
            return data_5min
            
        except Exception as e:
            logger.error(f"❌ 5분봉 변환 오류: {e}")
            return None
    
    @staticmethod
    def convert_to_5min_data(data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        1분봉 데이터를 5분봉으로 변환 (표준 리샘플링 방식)
        
        Args:
            data: 1분봉 DataFrame
            
        Returns:
            5분봉 DataFrame 또는 None
        """
        return TimeFrameConverter.convert_to_timeframe(data, 5)