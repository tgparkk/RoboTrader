import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Tuple, Optional


class VolumeBollingerBands:
    """
    거래량 볼린저밴드 지표
    
    중심선: avg(ma(v,n,단순),period)
    상한선: avg(ma(v,n,단순),period) + d1*stdev((ma(v,n,단순),period)
    하한선: avg(ma(v,n,단순),period) - d1*stdev((ma(v,n,단순),period)
    
    기본값: period=20, d1=2, n=3
    """
    
    @staticmethod
    def calculate_volume_ma(volume_data: pd.Series, ma_period: int = 3) -> pd.Series:
        """
        거래량의 단순이동평균 계산 (Static Method)
        
        Parameters:
        - volume_data: 거래량 데이터 (pandas Series)
        - ma_period: 이동평균 기간 (기본값: 3)
        
        Returns:
        - 거래량 이동평균 (pandas Series)
        """
        return volume_data.rolling(window=ma_period, min_periods=1).mean()
    
    @staticmethod
    def calculate_bollinger_bands(volume_data: pd.Series, period: int = 20, 
                                multiplier: float = 2.0, ma_period: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        거래량 볼린저밴드 계산 (Static Method)
        
        Parameters:
        - volume_data: 거래량 데이터 (pandas Series)
        - period: 볼린저밴드 계산 기간 (기본값: 20)
        - multiplier: 표준편차 배수 (기본값: 2.0)
        - ma_period: 거래량 이동평균 기간 (기본값: 3)
        
        Returns:
        - Tuple[중심선, 상한선, 하한선] (각각 pandas Series)
        """
        # 1단계: 거래량 이동평균 계산
        volume_ma = VolumeBollingerBands.calculate_volume_ma(volume_data, ma_period)
        
        # 2단계: 거래량 이동평균의 이동평균(중심선) 계산
        center_line = volume_ma.rolling(window=period, min_periods=1).mean()
        
        # 3단계: 거래량 이동평균의 표준편차 계산
        std_dev = volume_ma.rolling(window=period, min_periods=1).std()
        
        # 4단계: 상한선, 하한선 계산
        upper_band = center_line + (multiplier * std_dev)
        lower_band = center_line - (multiplier * std_dev)
        
        return center_line, upper_band, lower_band
    
    @staticmethod
    def analyze_volume_state(current_volume: float, center_line: float, 
                           upper_band: float, lower_band: float) -> dict:
        """
        현재 거래량 상태 분석 (Static Method)
        
        Parameters:
        - current_volume: 현재 거래량
        - center_line: 볼린저밴드 중심선 값
        - upper_band: 볼린저밴드 상한선 값
        - lower_band: 볼린저밴드 하한선 값
        
        Returns:
        - 거래량 상태 정보 (dict)
        """
        state = {
            'volume': current_volume,
            'center_line': center_line,
            'upper_band': upper_band,
            'lower_band': lower_band,
            'position': None,
            'breakout': False,
            'interpretation': None
        }
        
        # 거래량 위치 판단
        if current_volume >= upper_band:
            state['position'] = 'above_upper'
            state['breakout'] = True
            state['interpretation'] = '거래량 상한선 돌파 - 높은 거래량'
        elif current_volume <= lower_band:
            state['position'] = 'below_lower'
            state['interpretation'] = '거래량 하한선 아래 - 매우 낮은 거래량'
        elif current_volume < center_line:
            state['position'] = 'below_center'
            state['interpretation'] = '평균 이하의 거래량'
        else:
            state['position'] = 'above_center'
            state['interpretation'] = '평균 이상의 거래량'
        
        return state
    
    @staticmethod
    def is_volume_concentrated(upper_band: pd.Series, lower_band: pd.Series, 
                             lookback: int = 5, threshold: float = 0.3) -> bool:
        """
        거래량 볼린저밴드가 밀집된 상태인지 판단 (Static Method)
        
        Parameters:
        - upper_band: 상한선 데이터
        - lower_band: 하한선 데이터
        - lookback: 확인할 기간 (기본값: 5)
        - threshold: 밀집 판단 임계값 (기본값: 0.3)
        
        Returns:
        - 밀집 상태 여부 (bool)
        """
        if len(upper_band) < lookback or len(lower_band) < lookback:
            return False
        
        # 최근 lookback 기간의 밴드 폭 계산
        recent_band_width = (upper_band.iloc[-lookback:] - lower_band.iloc[-lookback:])
        avg_band_width = recent_band_width.mean()
        
        # 전체 기간의 평균 밴드 폭 대비 비율
        total_band_width = (upper_band - lower_band).mean()
        concentration_ratio = avg_band_width / total_band_width
        
        return concentration_ratio < threshold
    
    @staticmethod
    def get_signals(volume_data: pd.Series, period: int = 20, multiplier: float = 2.0, 
                   ma_period: int = 3) -> pd.DataFrame:
        """
        거래량 볼린저밴드 신호 생성 (Static Method)
        
        Parameters:
        - volume_data: 거래량 데이터
        - period: 볼린저밴드 계산 기간 (기본값: 20)
        - multiplier: 표준편차 배수 (기본값: 2.0)
        - ma_period: 거래량 이동평균 기간 (기본값: 3)
        
        Returns:
        - 신호 데이터프레임
        """
        center_line, upper_band, lower_band = VolumeBollingerBands.calculate_bollinger_bands(
            volume_data, period, multiplier, ma_period)
        
        signals = pd.DataFrame(index=volume_data.index)
        signals['volume'] = volume_data
        signals['volume_ma'] = VolumeBollingerBands.calculate_volume_ma(volume_data, ma_period)
        signals['center_line'] = center_line
        signals['upper_band'] = upper_band
        signals['lower_band'] = lower_band
        
        # 신호 생성
        signals['upper_breakout'] = volume_data > upper_band
        signals['lower_breakout'] = volume_data < lower_band
        signals['below_center'] = volume_data < center_line
        signals['band_width'] = upper_band - lower_band
        
        return signals
    
    @staticmethod
    def plot_volume_bollinger_bands(volume_data: pd.Series, price_data: Optional[pd.Series] = None,
                                   period: int = 20, multiplier: float = 2.0, ma_period: int = 3,
                                   title: str = "거래량 볼린저밴드", figsize: Tuple[int, int] = (15, 10),
                                   save_path: Optional[str] = None) -> None:
        """
        거래량 볼린저밴드 차트 그리기 (Static Method)
        
        Parameters:
        - volume_data: 거래량 데이터
        - price_data: 주가 데이터 (선택사항)
        - period: 볼린저밴드 계산 기간
        - multiplier: 표준편차 배수
        - ma_period: 거래량 이동평균 기간
        - title: 차트 제목
        - figsize: 차트 크기
        - save_path: 저장 경로 (선택사항)
        """
        center_line, upper_band, lower_band = VolumeBollingerBands.calculate_bollinger_bands(
            volume_data, period, multiplier, ma_period)
        
        # 서브플롯 설정
        if price_data is not None:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, gridspec_kw={'height_ratios': [2, 1]})
            
            # 주가 차트
            ax1.plot(volume_data.index, price_data, 'k-', linewidth=1, label='주가')
            ax1.set_title(f'{title} - 주가')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # 거래량 볼린저밴드 차트
            volume_ax = ax2
        else:
            fig, volume_ax = plt.subplots(1, 1, figsize=figsize)
        
        # 거래량 볼린저밴드 그리기
        volume_ax.bar(volume_data.index, volume_data, alpha=0.6, color='blue', label='거래량')
        volume_ax.plot(volume_data.index, center_line, 'r-', linewidth=2, label='중심선')
        volume_ax.plot(volume_data.index, upper_band, 'g--', linewidth=1.5, label='상한선')
        volume_ax.plot(volume_data.index, lower_band, 'g--', linewidth=1.5, label='하한선')
        
        # 밴드 영역 채우기
        volume_ax.fill_between(volume_data.index, upper_band, lower_band, alpha=0.1, color='green')
        
        # 상한선 돌파 포인트 표시
        breakout_points = volume_data > upper_band
        if breakout_points.any():
            volume_ax.scatter(volume_data.index[breakout_points], 
                            volume_data[breakout_points], 
                            color='red', s=50, marker='^', label='상한선 돌파', zorder=5)
        
        volume_ax.set_title(f'{title} - 거래량')
        volume_ax.set_ylabel('거래량')
        volume_ax.legend()
        volume_ax.grid(True, alpha=0.3)
        
        # x축 날짜 포맷
        if hasattr(volume_data.index, 'to_pydatetime'):
            volume_ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            volume_ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(volume_data)//10)))
            plt.setp(volume_ax.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"차트가 저장되었습니다: {save_path}")
        
        plt.show()

    def __init__(self, period: int = 20, multiplier: float = 2.0, ma_period: int = 3):
        """
        기존 인스턴스 방식도 유지 (하위 호환성)
        
        Parameters:
        - period: 볼린저밴드 계산 기간 (기본값: 20)
        - multiplier: 표준편차 배수 (기본값: 2.0)
        - ma_period: 거래량 이동평균 기간 (기본값: 3)
        """
        self.period = period
        self.multiplier = multiplier
        self.ma_period = ma_period
    
    def calculate_volume_ma(self, volume_data: pd.Series) -> pd.Series:
        """인스턴스 메서드 (Static Method 호출)"""
        return VolumeBollingerBands.calculate_volume_ma(volume_data, self.ma_period)
    
    def calculate_bollinger_bands(self, volume_data: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """인스턴스 메서드 (Static Method 호출)"""
        return VolumeBollingerBands.calculate_bollinger_bands(volume_data, self.period, self.multiplier, self.ma_period)
    
    def get_signals(self, volume_data: pd.Series) -> pd.DataFrame:
        """인스턴스 메서드 (Static Method 호출)"""
        return VolumeBollingerBands.get_signals(volume_data, self.period, self.multiplier, self.ma_period)