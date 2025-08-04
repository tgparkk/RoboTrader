import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Tuple, Optional, Dict
from datetime import datetime, timedelta


class PriceBox:
    """
    가격박스 지표 (1분봉 활용 권장)
    
    매매법:
    - 주가 하락시: 박스하한선에서 지지 확인 후 매수 또는 박스중심선 돌파시 매수
    - 주가 상승시: 박스상한선에서 매도
    - 박스하한선에서 10분 내외 반응 없으면 즉각 손절
    - 첫 박스하한선이 가장 확률 높은 자리
    
    계산법:
    1. 삼각 이동평균(30일) → 박스중심선
    2. 조건부 편차 계산 (상승/하락 구분)
    3. 박스 상/하한선 = 중심선 ± (평균편차 + 2*표준편차)
    """
    
    @staticmethod
    def triangular_moving_average(prices: pd.Series, period: int = 30) -> pd.Series:
        """
        삼각 이동평균 계산 (Static Method)
        
        Parameters:
        - prices: 가격 데이터 (pandas Series)
        - period: 이동평균 기간 (기본값: 30)
        
        Returns:
        - 삼각 이동평균 (pandas Series)
        """
        # 첫 번째 단순 이동평균
        sma1 = prices.rolling(window=period, min_periods=1).mean()
        
        # 두 번째 단순 이동평균 (삼각 이동평균)
        tma = sma1.rolling(window=period, min_periods=1).mean()
        
        return tma
    
    @staticmethod
    def calculate_conditional_deviations(prices: pd.Series, center_line: pd.Series) -> Dict[str, pd.Series]:
        """
        조건부 편차 계산 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - center_line: 중심선 (삼각 이동평균)
        
        Returns:
        - 상승/하락 편차 통계값들
        """
        # 전체 편차 계산
        deviation = prices - center_line
        
        # 상승 편차 (이평선보다 높은 값들만)
        upward_mask = deviation > 0
        upward_deviations = deviation[upward_mask]
        
        # 하락 편차 (이평선보다 낮은 값들만)  
        downward_mask = deviation < 0
        downward_deviations = deviation[downward_mask]
        
        # 롤링 윈도우로 동적 계산
        window = min(30, len(prices))
        
        avg_up_series = pd.Series(index=prices.index, dtype=float)
        std_up_series = pd.Series(index=prices.index, dtype=float)
        avg_down_series = pd.Series(index=prices.index, dtype=float)
        std_down_series = pd.Series(index=prices.index, dtype=float)
        
        for i in range(len(prices)):
            start_idx = max(0, i - window + 1)
            end_idx = i + 1
            
            # 현재 윈도우의 편차들
            window_deviation = deviation.iloc[start_idx:end_idx]
            window_upward = window_deviation[window_deviation > 0]
            window_downward = window_deviation[window_deviation < 0]
            
            # 상승 편차 통계
            if len(window_upward) > 0:
                avg_up_series.iloc[i] = window_upward.mean()
                std_up_series.iloc[i] = window_upward.std() if len(window_upward) > 1 else 0
            else:
                avg_up_series.iloc[i] = 0
                std_up_series.iloc[i] = 0
            
            # 하락 편차 통계
            if len(window_downward) > 0:
                avg_down_series.iloc[i] = window_downward.mean()
                std_down_series.iloc[i] = window_downward.std() if len(window_downward) > 1 else 0
            else:
                avg_down_series.iloc[i] = 0
                std_down_series.iloc[i] = 0
        
        return {
            'avg_up': avg_up_series,
            'std_up': std_up_series,
            'avg_down': avg_down_series,
            'std_down': std_down_series,
            'deviation': deviation
        }
    
    @staticmethod
    def calculate_price_box(prices: pd.Series, period: int = 30, 
                          std_multiplier: float = 2.0) -> Dict[str, pd.Series]:
        """
        가격박스 계산 (Static Method)
        
        Parameters:
        - prices: 종가 데이터
        - period: 삼각 이동평균 기간 (기본값: 30)
        - std_multiplier: 표준편차 배수 (기본값: 2.0)
        
        Returns:
        - 박스 중심선, 상한선, 하한선
        """
        # 1단계: 삼각 이동평균 계산 (박스중심선)
        center_line = PriceBox.triangular_moving_average(prices, period)
        
        # 2단계: 조건부 편차 계산
        deviation_data = PriceBox.calculate_conditional_deviations(prices, center_line)
        
        # 3단계: 박스 상/하한선 계산
        upper_band = center_line + deviation_data['avg_up'] + std_multiplier * deviation_data['std_up']
        lower_band = center_line + deviation_data['avg_down'] - std_multiplier * deviation_data['std_down']
        
        return {
            'center_line': center_line,
            'upper_band': upper_band,
            'lower_band': lower_band,
            'avg_up': deviation_data['avg_up'],
            'std_up': deviation_data['std_up'],
            'avg_down': deviation_data['avg_down'],
            'std_down': deviation_data['std_down']
        }
    
    @staticmethod
    def detect_support_resistance(prices: pd.Series, lower_band: pd.Series, upper_band: pd.Series,
                                 center_line: pd.Series, tolerance_pct: float = 0.5) -> Dict[str, pd.Series]:
        """
        지지/저항 확인 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - lower_band: 박스하한선
        - upper_band: 박스상한선
        - center_line: 박스중심선
        - tolerance_pct: 허용 오차 (%)
        
        Returns:
        - 지지/저항 신호들
        """
        tolerance = tolerance_pct / 100
        
        # 하한선 근처 (지지구간)
        near_lower = abs(prices - lower_band) / lower_band <= tolerance
        
        # 상한선 근처 (저항구간)
        near_upper = abs(prices - upper_band) / upper_band <= tolerance
        
        # 중심선 근처
        near_center = abs(prices - center_line) / center_line <= tolerance
        
        # 하한선 터치 (지지선 근처 도달)
        lower_touch = prices <= lower_band * (1 + tolerance)
        
        # 하한선에서 지지 확인 (터치 후 반등)
        support_confirmed = pd.Series(False, index=prices.index)
        for i in range(2, len(prices)):
            # 최근 3봉 중 하한선 터치가 있고, 현재 가격이 하한선보다 높으면 지지 확인
            recent_touch = lower_touch.iloc[i-2:i+1].any()
            current_above_support = prices.iloc[i] > lower_band.iloc[i] * (1 + tolerance)
            if recent_touch and current_above_support:
                support_confirmed.iloc[i] = True
        
        # 하한선에서 반등 (즉시 반등, 기존 로직 유지)
        support_bounce = (prices.shift(1) <= lower_band * (1 + tolerance)) & (prices > lower_band * (1 + tolerance))
        
        # 상한선에서 하락 (저항 확인)
        resistance_reject = (prices.shift(1) >= upper_band * (1 - tolerance)) & (prices < upper_band * (1 - tolerance))
        
        # 중심선 돌파 (상향)
        center_breakout_up = (prices.shift(1) <= center_line) & (prices > center_line)
        center_breakout_down = (prices.shift(1) >= center_line) & (prices < center_line)
        
        # 중심선 이탈 (하향) - 손절 신호용
        center_break_down = (prices.shift(1) >= center_line) & (prices < center_line)
        
        return {
            'near_lower': near_lower,
            'near_upper': near_upper,
            'near_center': near_center,
            'lower_touch': lower_touch,
            'support_confirmed': support_confirmed,
            'support_bounce': support_bounce,
            'resistance_reject': resistance_reject,
            'center_breakout_up': center_breakout_up,
            'center_breakout_down': center_breakout_down,
            'center_break_down': center_break_down
        }
    
    @staticmethod
    def detect_first_box_touch(prices: pd.Series, lower_band: pd.Series, upper_band: pd.Series,
                              lookback_period: int = 120) -> Dict[str, pd.Series]:
        """
        첫 박스 터치 감지 (Static Method) - 더 엄격한 조건
        
        Parameters:
        - prices: 가격 데이터
        - lower_band: 박스하한선
        - upper_band: 박스상한선
        - lookback_period: 첫 터치 확인 기간 (2시간으로 증가)
        
        Returns:
        - 첫 박스 터치 신호들
        """
        first_lower_touch = pd.Series(False, index=prices.index)
        first_upper_touch = pd.Series(False, index=prices.index)
        
        for i in range(lookback_period, len(prices)):
            # 과거 lookback_period 동안 하한선 터치 여부 확인 (더 엄격한 조건)
            past_lower_touches = (prices.iloc[i-lookback_period:i] <= lower_band.iloc[i-lookback_period:i] * 1.002).any()
            current_lower_touch = prices.iloc[i] <= lower_band.iloc[i] * 1.002
            
            # 과거에 터치 없고 현재 터치하면서 반등 조건도 만족해야 함
            if not past_lower_touches and current_lower_touch:
                # 추가 조건: 다음 몇 봉에서 실제 반등이 있는지 확인 (미래 정보 사용하지 않음)
                # 대신 현재 봉에서 하한선 근처에서 마감되는지만 확인
                if prices.iloc[i] > lower_band.iloc[i] * 0.998:  # 하한선 아래 0.2% 이내
                    first_lower_touch.iloc[i] = True
            
            # 상한선도 동일 로직 (더 엄격한 조건)
            past_upper_touches = (prices.iloc[i-lookback_period:i] >= upper_band.iloc[i-lookback_period:i] * 0.998).any()
            current_upper_touch = prices.iloc[i] >= upper_band.iloc[i] * 0.998
            
            if not past_upper_touches and current_upper_touch:
                if prices.iloc[i] < upper_band.iloc[i] * 1.002:
                    first_upper_touch.iloc[i] = True
        
        return {
            'first_lower_touch': first_lower_touch,
            'first_upper_touch': first_upper_touch
        }
    
    @staticmethod
    def generate_trading_signals(prices: pd.Series, timestamps: Optional[pd.Index] = None,
                               period: int = 30, std_multiplier: float = 2.0,
                               stop_loss_minutes: int = 10) -> pd.DataFrame:
        """
        가격박스 기반 트레이딩 신호 생성 (Static Method)
        
        Parameters:
        - prices: 종가 데이터
        - timestamps: 시간 인덱스 (선택사항)
        - period: 삼각 이동평균 기간
        - std_multiplier: 표준편차 배수
        - stop_loss_minutes: 손절 시간 (분)
        
        Returns:
        - 신호 데이터프레임
        """
        if timestamps is None:
            timestamps = prices.index
        
        signals = pd.DataFrame(index=timestamps)
        signals['price'] = prices
        
        # 가격박스 계산
        box_data = PriceBox.calculate_price_box(prices, period, std_multiplier)
        signals['center_line'] = box_data['center_line']
        signals['upper_band'] = box_data['upper_band']
        signals['lower_band'] = box_data['lower_band']
        
        # 지지/저항 감지
        support_resistance = PriceBox.detect_support_resistance(
            prices, box_data['lower_band'], box_data['upper_band'], box_data['center_line'])
        
        for key, value in support_resistance.items():
            signals[key] = value
        
        # 첫 박스 터치 감지
        first_touch = PriceBox.detect_first_box_touch(
            prices, box_data['lower_band'], box_data['upper_band'])
        
        signals['first_lower_touch'] = first_touch['first_lower_touch']
        signals['first_upper_touch'] = first_touch['first_upper_touch']
        
        # 매수 신호
        # 1. 첫 하한선 터치 (가장 확률 높은 자리) - 즉시 매수
        signals['buy_first_touch'] = signals['first_lower_touch']
        
        # 2. 하한선에서 즉시 반등 매수 (리스크 높음)
        signals['buy_support_bounce'] = signals['support_bounce']
        
        # 3. 안전한 매수: 지지 확인 후 중심선 돌파 (권장)
        # 지지가 확인된 상태에서 중심선을 돌파하는 경우
        signals['buy_safe'] = pd.Series(False, index=signals.index)
        for i in range(10, len(signals)):  # 최소 10봉 이후부터 확인
            # 최근 10봉 내에 지지 확인이 있었고, 현재 중심선 돌파하는 경우
            recent_support_confirmed = signals['support_confirmed'].iloc[i-10:i].any()
            current_center_breakout = signals['center_breakout_up'].iloc[i]
            
            if recent_support_confirmed and current_center_breakout:
                signals['buy_safe'].iloc[i] = True
        
        # 매도 신호
        # 상한선에서 매도
        signals['sell_resistance'] = signals['resistance_reject']
        
        # 박스 폭 계산 (매수신호 필터링에 사용되므로 먼저 계산)
        signals['box_width'] = signals['upper_band'] - signals['lower_band']
        signals['box_width_pct'] = (signals['box_width'] / signals['center_line']) * 100
        
        # 통합 매수신호 (매우 엄격한 조건)
        signals['buy_signal'] = (
            signals['buy_first_touch'] |           # 첫 터치 (가장 확률 높음)
            signals['buy_safe']                    # 지지확인 후 중심선 돌파 (안전)
        )
        
        # 추가 필터링: 박스 폭이 너무 좁거나 넓으면 제외
        box_width_filter = (signals['box_width_pct'] > 1.0) & (signals['box_width_pct'] < 8.0)
        signals['buy_signal'] = signals['buy_signal'] & box_width_filter
        
        signals['sell_signal'] = signals['sell_resistance']
        
        # 손절 로직 추가
        # 1. 시간 기반 손절 (10분 내외 반응 없으면 손절)
        if hasattr(timestamps, 'to_pydatetime'):
            signals['time_based_stop_loss'] = PriceBox.calculate_time_based_stop_loss(
                signals, stop_loss_minutes)
        else:
            signals['time_based_stop_loss'] = False
            
        # 2. 가격 기반 손절 로직
        signals['stop_loss_signal'] = PriceBox.calculate_price_based_stop_loss(signals)
        
        # 박스 위치 분석
        signals['price_position'] = 'middle'
        signals.loc[signals['near_lower'], 'price_position'] = 'lower_zone'
        signals.loc[signals['near_upper'], 'price_position'] = 'upper_zone'
        signals.loc[signals['near_center'], 'price_position'] = 'center_zone'
        
        return signals
    
    @staticmethod
    def calculate_price_based_stop_loss(signals: pd.DataFrame) -> pd.Series:
        """
        가격 기반 손절 계산 (Static Method)
        - 중심선 이탈 시 손절
        - 직전 저점 이탈 시 손절  
        - 매수가 대비 -3% 손실 시 손절
        
        Parameters:
        - signals: 신호 데이터프레임
        
        Returns:
        - 가격 기반 손절 신호
        """
        stop_loss_signal = pd.Series(False, index=signals.index)
        buy_positions = {}  # 매수 포지션 추적 {매수시점: 매수가격}
        
        for i in range(len(signals)):
            current_price = signals['price'].iloc[i]
            
            # 매수 신호 발생 시 포지션 추가
            if signals['buy_signal'].iloc[i]:
                buy_positions[i] = current_price
            
            # 기존 포지션에 대한 손절 체크
            positions_to_remove = []
            for buy_idx, buy_price in buy_positions.items():
                # 1. 중심선 이탈 손절
                center_line_value = signals['center_line'].iloc[i]
                if current_price < center_line_value:
                    stop_loss_signal.iloc[i] = True
                    positions_to_remove.append(buy_idx)
                    continue
                    
                # 2. 직전 저점 이탈 손절 (매수 이후 최저점 계산)
                if i > buy_idx + 2:  # 최소 2봉 이후부터 체크
                    recent_low = signals['price'].iloc[buy_idx:i].min()
                    if current_price < recent_low * 0.99:  # 직전 저점 1% 하회
                        stop_loss_signal.iloc[i] = True
                        positions_to_remove.append(buy_idx)
                        continue
                
                # 3. -3% 손실 손절
                if current_price < buy_price * 0.97:
                    stop_loss_signal.iloc[i] = True
                    positions_to_remove.append(buy_idx)
                    continue
            
            # 손절된 포지션 제거
            for buy_idx in positions_to_remove:
                del buy_positions[buy_idx]
                
            # 매도 신호 발생 시 모든 포지션 정리
            if signals['sell_signal'].iloc[i]:
                buy_positions.clear()
        
        return stop_loss_signal
    
    @staticmethod
    def calculate_time_based_stop_loss(signals: pd.DataFrame, 
                                     stop_loss_minutes: int = 10) -> pd.Series:
        """
        시간 기반 손절 계산 (Static Method)
        
        Parameters:
        - signals: 신호 데이터프레임
        - stop_loss_minutes: 손절 시간 (분)
        
        Returns:
        - 시간 기반 손절 신호
        """
        stop_loss_signal = pd.Series(False, index=signals.index)
        
        buy_times = signals.index[signals['buy_signal']]
        
        for buy_time in buy_times:
            # 매수 후 stop_loss_minutes 이후 시점
            stop_time = buy_time + timedelta(minutes=stop_loss_minutes)
            
            # 해당 시점까지 상승 반응이 없으면 손절
            mask = (signals.index > buy_time) & (signals.index <= stop_time)
            
            if mask.any():
                period_data = signals[mask]
                # 중심선 돌파나 상당한 상승이 없으면 손절
                no_reaction = not (
                    period_data['center_breakout_up'].any() or
                    (period_data['price'] > period_data['center_line'] * 1.01).any()
                )
                
                if no_reaction and stop_time in signals.index:
                    stop_loss_signal[stop_time] = True
        
        return stop_loss_signal
    
    @staticmethod
    def plot_price_box(prices: pd.Series, signals: Optional[pd.DataFrame] = None,
                      title: str = "가격박스 분석", figsize: Tuple[int, int] = (15, 10),
                      save_path: Optional[str] = None) -> None:
        """
        가격박스 차트 그리기 (Static Method)
        
        Parameters:
        - prices: 가격 데이터
        - signals: 신호 데이터 (선택사항)
        - title: 차트 제목
        - figsize: 차트 크기
        - save_path: 저장 경로 (선택사항)
        """
        if signals is None:
            signals = PriceBox.generate_trading_signals(prices)
        
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        
        # 가격 차트
        ax.plot(signals.index, signals['price'], 'k-', linewidth=1, label='가격')
        
        # 가격박스 라인들
        ax.plot(signals.index, signals['center_line'], 'b-', linewidth=2, label='박스중심선')
        ax.plot(signals.index, signals['upper_band'], 'r--', linewidth=1.5, label='박스상한선')
        ax.plot(signals.index, signals['lower_band'], 'g--', linewidth=1.5, label='박스하한선')
        
        # 박스 영역 채우기
        ax.fill_between(signals.index, signals['upper_band'], signals['lower_band'], 
                       alpha=0.1, color='blue', label='가격박스')
        
        # 매수 신호
        buy_points = signals['buy_signal']
        if buy_points.any():
            ax.scatter(signals.index[buy_points], signals['price'][buy_points],
                      color='green', s=100, marker='^', label='매수신호', zorder=5)
        
        # 매도 신호
        sell_points = signals['sell_signal']
        if sell_points.any():
            ax.scatter(signals.index[sell_points], signals['price'][sell_points],
                      color='red', s=100, marker='v', label='매도신호', zorder=5)
        
        # 첫 터치 신호 (특별 표시)
        first_touch_points = signals['first_lower_touch']
        if first_touch_points.any():
            ax.scatter(signals.index[first_touch_points], signals['price'][first_touch_points],
                      color='gold', s=150, marker='*', label='첫 하한선터치', zorder=6)
        
        # 손절 신호
        if 'stop_loss_signal' in signals.columns:
            stop_loss_points = signals['stop_loss_signal']
            if stop_loss_points.any():
                ax.scatter(signals.index[stop_loss_points], signals['price'][stop_loss_points],
                          color='orange', s=80, marker='x', label='손절신호', zorder=5)
        
        # 시간 기반 손절 (추가 표시)
        if 'time_based_stop_loss' in signals.columns:
            time_stop_points = signals['time_based_stop_loss']
            if time_stop_points.any():
                ax.scatter(signals.index[time_stop_points], signals['price'][time_stop_points],
                          color='purple', s=60, marker='s', label='시간손절', zorder=5)
        
        ax.set_title(f'{title}')
        ax.set_ylabel('가격')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # x축 날짜 포맷 (1분봉 기준)
        if hasattr(signals.index, 'to_pydatetime'):
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, len(signals)//20)))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"차트가 저장되었습니다: {save_path}")
        
        plt.show()

    def __init__(self, period: int = 30, std_multiplier: float = 2.0, stop_loss_minutes: int = 10):
        """
        기존 인스턴스 방식도 유지 (하위 호환성)
        
        Parameters:
        - period: 삼각 이동평균 기간 (기본값: 30)
        - std_multiplier: 표준편차 배수 (기본값: 2.0)
        - stop_loss_minutes: 손절 시간 (분, 기본값: 10)
        """
        self.period = period
        self.std_multiplier = std_multiplier
        self.stop_loss_minutes = stop_loss_minutes
    
    def generate_signals(self, prices: pd.Series, timestamps: Optional[pd.Index] = None) -> pd.DataFrame:
        """인스턴스 메서드 (Static Method 호출)"""
        return PriceBox.generate_trading_signals(
            prices, timestamps, self.period, self.std_multiplier, self.stop_loss_minutes)