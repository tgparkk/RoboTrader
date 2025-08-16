"""
차트 렌더링 전용 클래스
PostMarketChartGenerator에서 차트 그리기 로직을 분리
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from pathlib import Path
from utils.logger import setup_logger
from utils.korean_time import now_kst


class ChartRenderer:
    """차트 렌더링 전용 클래스"""
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        
        # 차트 설정
        plt.rcParams['font.family'] = ['Malgun Gothic', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
        self.logger.info("차트 렌더러 초기화 완료")
    
    def create_strategy_chart(self, stock_code: str, stock_name: str, target_date: str,
                             strategy, data: pd.DataFrame, 
                             indicators_data: Dict[str, Any], selection_reason: str,
                             chart_suffix: str = "", timeframe: str = "1min",
                             trade_simulation_results: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
        """전략별 차트 생성"""
        try:
            # 시간프레임 저장 (다른 메서드에서 사용)
            self.current_timeframe = timeframe
            
            # 서브플롯 설정 (가격 + 거래량)
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), 
                                         gridspec_kw={'height_ratios': [3, 1]})
            
            # Axis 클리어 (중복 방지)
            ax1.clear()
            ax2.clear()
            
            # 데이터 검증 및 중복 제거
            cleaned_data = self._validate_and_clean_data(data, target_date)
            
            # 기본 캔들스틱 차트
            self._draw_candlestick(ax1, cleaned_data)
            
            # 전략별 지표 표시
            self._draw_strategy_indicators(ax1, cleaned_data, strategy, indicators_data)
            
            # 체결 시뮬레이션 결과 기반 매수/매도 신호 표시
            if trade_simulation_results:
                self._draw_simulation_signals(ax1, cleaned_data, trade_simulation_results)
            else:
                # 폴백: 기존 신호 표시 방식
                self._draw_buy_signals(ax1, cleaned_data, strategy)
                self._draw_sell_signals(ax1, cleaned_data, strategy)
            
            # 거래량 차트
            self._draw_volume_chart(ax2, cleaned_data)
            
            # 차트 제목 및 설정
            title = f"{stock_code} {stock_name} - {strategy.name} ({strategy.timeframe})"
            if selection_reason:
                title += f"\n{selection_reason}"
            
            ax1.set_title(title, fontsize=14, fontweight='bold', pad=20)
            ax1.set_ylabel('가격 (원)', fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.legend(loc='upper left')
            
            ax2.set_ylabel('거래량', fontsize=12)
            ax2.set_xlabel('시간', fontsize=12)
            ax2.grid(True, alpha=0.3)
            
            # 08:00~09:00 구간 회색 배경 표시 (데이터 없는 구간)
            self._draw_no_data_background(ax1, ax2, cleaned_data, strategy.timeframe)
            
            # X축 시간 레이블 설정 (08:00 ~ 15:30)
            self._set_time_axis_labels(ax1, ax2, cleaned_data, strategy.timeframe)
            
            plt.tight_layout()
            
            # 파일 저장
            timestamp = now_kst().strftime("%Y%m%d_%H%M%S")
            suffix_part = f"_{chart_suffix}" if chart_suffix else ""
            filename = f"strategy_chart_{stock_code}_{strategy.timeframe}_{target_date}{suffix_part}_{timestamp}.png"
            filepath = Path(filename)
            
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"전략 차트 생성 실패: {e}")
            plt.close()
            return None
    
    def create_basic_chart(self, stock_code: str, stock_name: str, 
                          chart_df: pd.DataFrame, target_date: str,
                          selection_reason: str = "") -> Optional[str]:
        """기본 차트 생성 (폴백용)"""
        try:
            # 데이터 검증 및 날짜 필터링
            chart_df = self._validate_and_clean_data(chart_df, target_date)
            
            if chart_df.empty:
                self.logger.error(f"기본 차트 생성 실패: 데이터 없음 ({stock_code})")
                return None
            
            fig, ax = plt.subplots(1, 1, figsize=(12, 8))
            
            if 'close' in chart_df.columns:
                ax.plot(chart_df['close'], label='가격', linewidth=2)
                ax.set_title(f"{stock_code} {stock_name} - {target_date}")
                ax.set_ylabel('가격 (원)')
                ax.grid(True, alpha=0.3)
                ax.legend()
                
                # 기본 차트도 시간축 설정
                self._set_basic_time_axis_labels(ax, chart_df)
            
            timestamp = now_kst().strftime("%Y%m%d_%H%M%S")
            filename = f"basic_chart_{stock_code}_{target_date}_{timestamp}.png"
            filepath = Path(filename)
            
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"기본 차트 생성 오류: {e}")
            plt.close()
            return None
    
    def _draw_candlestick(self, ax, data: pd.DataFrame):
        """캔들스틱 차트 그리기 - 실제 데이터 인덱스 기준"""
        try:
            # 🚨 디버깅: 캔들 그리기 입력 데이터 확인
            timeframe = getattr(self, 'current_timeframe', '1min')
            self.logger.error(f"🎨 캔들스틱 그리기 시작:")
            self.logger.error(f"   - timeframe: {timeframe}")
            self.logger.error(f"   - 입력 데이터 개수: {len(data)}")
            if not data.empty:
                self.logger.error(f"   - 데이터 시간 범위: {data.iloc[0].get('time', 'N/A')} ~ {data.iloc[-1].get('time', 'N/A')}")
                # 처음 20개와 마지막 20개 시간 확인
                first_20_times = data['time'].head(20).tolist() if 'time' in data.columns else []
                last_20_times = data['time'].tail(20).tolist() if 'time' in data.columns else []
                self.logger.error(f"   - 처음 20개 시간: {first_20_times}")
                self.logger.error(f"   - 마지막 20개 시간: {last_20_times}")
            
            # 시간 기반 x 위치 계산
            x_positions = self._calculate_x_positions(data)
            self.logger.error(f"   - X 위치 개수: {len(x_positions)}")
            self.logger.error(f"   - X 위치 범위: {min(x_positions) if x_positions else 'N/A'} ~ {max(x_positions) if x_positions else 'N/A'}")
            
            # 캔들스틱 그리기
            drawn_candles = 0
            for idx, (_, row) in enumerate(data.iterrows()):
                x = x_positions[idx]
                open_price = row['open']
                high_price = row['high']
                low_price = row['low']
                close_price = row['close']
                
                # 캔들 색상 결정
                color = 'red' if close_price >= open_price else 'blue'
                
                # High-Low 선 (심지) - 캔들과 같은 색
                ax.plot([x, x], [low_price, high_price], color=color, linewidth=0.8)
                
                # 캔들 몸통
                candle_height = abs(close_price - open_price)
                candle_bottom = min(open_price, close_price)
                
                if candle_height > 0:
                    # 상승봉(빨간색) / 하락봉(파란색)
                    if close_price >= open_price:
                        # 상승봉 - 빨간색 채움
                        candle = Rectangle((x - 0.4, candle_bottom), 0.8, candle_height,
                                         facecolor='red', edgecolor='darkred', linewidth=0.5, alpha=0.9)
                    else:
                        # 하락봉 - 파란색 채움
                        candle = Rectangle((x - 0.4, candle_bottom), 0.8, candle_height,
                                         facecolor='blue', edgecolor='darkblue', linewidth=0.5, alpha=0.9)
                    ax.add_patch(candle)
                else:
                    # 시가와 종가가 같은 경우 (십자선)
                    line_color = 'red' if close_price >= open_price else 'blue'
                    ax.plot([x - 0.4, x + 0.4], [close_price, close_price], 
                           color=line_color, linewidth=1.5)
                
                drawn_candles += 1
            
            self.logger.error(f"   - 실제 그려진 캔들 개수: {drawn_candles}")
            if drawn_candles != len(data):
                self.logger.error(f"   ⚠️ 데이터({len(data)})와 그려진 캔들({drawn_candles}) 개수 불일치!")
                           
        except Exception as e:
            self.logger.error(f"캔들스틱 그리기 오류: {e}")
    
    def _draw_strategy_indicators(self, ax, data: pd.DataFrame, strategy, 
                                 indicators_data: Dict[str, Any]):
        """전략별 지표 그리기"""
        try:
            for indicator_name in strategy.indicators:
                if indicator_name in indicators_data:
                    indicator_data = indicators_data[indicator_name]
                    
                    if indicator_name == "price_box":
                        self._draw_price_box(ax, indicator_data, data)
                    elif indicator_name == "bisector_line":
                        self._draw_bisector_line(ax, indicator_data, data)
                    elif indicator_name == "bollinger_bands":
                        self._draw_bollinger_bands(ax, indicator_data, data)
                    elif indicator_name == "multi_bollinger_bands":
                        self._draw_multi_bollinger_bands(ax, indicator_data, data)
                        
        except Exception as e:
            self.logger.error(f"지표 그리기 오류: {e}")
    
    def _draw_buy_signals(self, ax, data: pd.DataFrame, strategy):
        """매수 신호 표시 (빨간색 화살표) - 정확한 x 위치 기준"""
        try:
            # 별도 모듈에서 매수 신호 계산
            from .signal_calculator import SignalCalculator
            signal_calc = SignalCalculator()
            buy_signals = signal_calc.calculate_buy_signals(data, strategy)
            
            if buy_signals is not None and buy_signals.any():
                # 시간 기반 x 위치 계산
                x_positions = self._calculate_x_positions(data)
                
                # 매수 신호가 있는 지점 찾기
                signal_indices = buy_signals[buy_signals].index
                signal_x_positions = []
                signal_prices = []
                
                for idx in signal_indices:
                    data_idx = data.index.get_loc(idx)
                    if data_idx < len(x_positions):
                        signal_x_positions.append(x_positions[data_idx])
                        signal_prices.append(data.loc[idx, 'close'])
                
                if signal_x_positions:
                    # 빨간색 화살표로 표시
                    ax.scatter(signal_x_positions, signal_prices, 
                              color='red', s=150, marker='^', 
                              label='매수신호', zorder=10, edgecolors='darkred', linewidth=2)
                    
                    self.logger.info(f"매수 신호 {len(signal_x_positions)}개 표시됨")
            
        except Exception as e:
            self.logger.error(f"매수 신호 표시 오류: {e}")
    
    def _draw_sell_signals(self, ax, data: pd.DataFrame, strategy):
        """매도/손절/익절 신호 표시 (파란/검정 화살표)"""
        try:
            # 눌림목 캔들패턴 전략인 경우만 상세 매도 신호 표시
            if "pullback_candle_pattern" in strategy.indicators and all(col in data.columns for col in ['open','high','low','close','volume']):
                from core.indicators.pullback_candle_pattern import PullbackCandlePattern
                signals = PullbackCandlePattern.generate_trading_signals(data)
                if signals is None or signals.empty:
                    return

                x_positions = self._calculate_x_positions(data)
                def scatter_mask(mask, color, label, marker='v'):
                    if mask.any():
                        idxs = mask[mask].index
                        xs, ys = [], []
                        for idx in idxs:
                            pos = data.index.get_loc(idx)
                            if pos < len(x_positions):
                                xs.append(x_positions[pos])
                                ys.append(data.loc[idx, 'close'])
                        if xs:
                            ax.scatter(xs, ys, color=color, s=130, marker=marker, label=label, zorder=10)

                if 'stop_entry_low_break' in signals.columns:
                    scatter_mask(signals['stop_entry_low_break'], 'black', '손절(0.2%)')
                scatter_mask(signals['sell_bisector_break'], 'blue', '이등분선 이탈')
                scatter_mask(signals['sell_support_break'], 'purple', '지지 저점 이탈')
                if 'take_profit_3pct' in signals.columns:
                    scatter_mask(signals['take_profit_3pct'], 'green', '익절(+3%)', marker='^')

        except Exception as e:
            self.logger.error(f"매도 신호 표시 오류: {e}")

    def _draw_simulation_signals(self, ax, data: pd.DataFrame, trades: List[Dict[str, Any]]):
        """체결 시뮬레이션 결과 기반 매수/매도 신호 표시"""
        try:
            if not trades:
                self.logger.info("체결 시뮬레이션 결과 없음")
                return
            
            # 시간 기반 x 위치 계산
            x_positions = self._calculate_x_positions(data)
            
            buy_signals_x = []
            buy_signals_y = []
            sell_signals_x = []
            sell_signals_y = []
            
            # 데이터의 시간 컬럼 확인
            if 'time' not in data.columns and 'datetime' not in data.columns:
                self.logger.warning("time 또는 datetime 컬럼이 없어 체결 시뮬레이션 신호 표시 불가")
                return
            
            for trade in trades:
                try:
                    # 매수 신호 처리
                    buy_time_str = trade.get('buy_time', '')
                    buy_price = trade.get('buy_price', 0.0)
                    
                    if buy_time_str and buy_price > 0:
                        try:
                            # 시간 문자열을 HH:MM 형식으로 파싱 (09:18 형식)
                            hour, minute = buy_time_str.split(':')
                            
                            # 3분봉 캔들 시간으로 변환 (매수 시간을 포함하는 캔들 찾기)
                            hour_int = int(hour)
                            minute_int = int(minute)
                            
                            # 3분봉 캔들의 시작 시간 계산 (09:00 기준으로 3분 단위로 나누기)
                            total_minutes_from_start = (hour_int - 9) * 60 + minute_int
                            candle_index = total_minutes_from_start // 3
                            candle_start_minute = candle_index * 3
                            
                            candle_hour = 9 + candle_start_minute // 60
                            candle_min = candle_start_minute % 60
                            
                            buy_time_hhmm = f"{candle_hour:02d}{candle_min:02d}00"  # HHMMSS 형식으로 변환
                            
                            self.logger.debug(f"매수 시간 변환: {buy_time_str} -> {buy_time_hhmm}")
                            
                            # 데이터에서 time 컬럼 기준으로 매칭
                            if 'time' in data.columns:
                                time_values = data['time'].astype(str).str.zfill(6)
                                matching_indices = data[time_values == buy_time_hhmm].index
                            elif 'datetime' in data.columns:
                                # datetime에서 시간 부분 추출하여 매칭
                                data_times = pd.to_datetime(data['datetime']).dt.strftime('%H%M%S')
                                matching_indices = data[data_times == buy_time_hhmm].index
                            else:
                                matching_indices = []
                            
                            if len(matching_indices) > 0:
                                idx = matching_indices[0]
                                data_idx = data.index.get_loc(idx)
                                if data_idx < len(x_positions):
                                    buy_signals_x.append(x_positions[data_idx])
                                    buy_signals_y.append(buy_price)
                                    self.logger.debug(f"매수 신호 매칭: {buy_time_str} -> 데이터 인덱스 {data_idx}")
                                else:
                                    self.logger.warning(f"매수 신호 X축 범위 초과: {buy_time_str} -> 인덱스 {data_idx}, X축 길이: {len(x_positions)}")
                            else:
                                self.logger.warning(f"매수 신호 시간 매칭 실패: {buy_time_str} -> {buy_time_hhmm}")
                        except Exception as e:
                            self.logger.warning(f"매수 시간 파싱 오류: {buy_time_str} - {e}")
                    
                    # 매도 신호 처리
                    sell_time_str = trade.get('sell_time', '')
                    sell_price = trade.get('sell_price', 0.0)
                    
                    if sell_time_str and sell_price > 0:
                        try:
                            # 시간 문자열을 HH:MM 형식으로 파싱 (09:23 형식)
                            hour, minute = sell_time_str.split(':')
                            
                            # 3분봉 캔들 시간으로 변환 (매도 시간을 포함하는 캔들 찾기)
                            hour_int = int(hour)
                            minute_int = int(minute)
                            
                            # 3분봉 캔들의 시작 시간 계산 (09:00 기준으로 3분 단위로 나누기)
                            # 09:00부터 시작하는 3분 간격: 09:00, 09:03, 09:06, 09:09, 09:12, 09:15, 09:18, 09:21, 09:24, ...
                            total_minutes_from_start = (hour_int - 9) * 60 + minute_int
                            candle_index = total_minutes_from_start // 3
                            candle_start_minute = candle_index * 3
                            
                            candle_hour = 9 + candle_start_minute // 60
                            candle_min = candle_start_minute % 60
                            
                            sell_time_hhmm = f"{candle_hour:02d}{candle_min:02d}00"  # HHMMSS 형식으로 변환
                            
                            self.logger.debug(f"매도 시간 변환: {sell_time_str} -> {sell_time_hhmm}")
                            
                            # 데이터에서 time 컬럼 기준으로 매칭
                            if 'time' in data.columns:
                                time_values = data['time'].astype(str).str.zfill(6)
                                matching_indices = data[time_values == sell_time_hhmm].index
                            elif 'datetime' in data.columns:
                                # datetime에서 시간 부분 추출하여 매칭
                                data_times = pd.to_datetime(data['datetime']).dt.strftime('%H%M%S')
                                matching_indices = data[data_times == sell_time_hhmm].index
                            else:
                                matching_indices = []
                            
                            if len(matching_indices) > 0:
                                idx = matching_indices[0]
                                data_idx = data.index.get_loc(idx)
                                if data_idx < len(x_positions):
                                    sell_signals_x.append(x_positions[data_idx])
                                    sell_signals_y.append(sell_price)
                                    self.logger.debug(f"매도 신호 매칭: {sell_time_str} -> 데이터 인덱스 {data_idx}")
                                else:
                                    self.logger.warning(f"매도 신호 X축 범위 초과: {sell_time_str} -> 인덱스 {data_idx}, X축 길이: {len(x_positions)}")
                            else:
                                self.logger.warning(f"매도 신호 시간 매칭 실패: {sell_time_str} -> {sell_time_hhmm}")
                        except Exception as e:
                            self.logger.warning(f"매도 시간 파싱 오류: {sell_time_str} - {e}")
                    
                except Exception as e:
                    self.logger.warning(f"체결 시뮬레이션 신호 처리 오류: {e}")
                    continue
            
            # 매수 신호 표시 (빨간색 위 화살표)
            if buy_signals_x:
                ax.scatter(buy_signals_x, buy_signals_y, 
                          color='red', s=150, marker='^', 
                          label=f'매수신호({len(buy_signals_x)}개)', zorder=10, 
                          edgecolors='darkred', linewidth=2)
                self.logger.info(f"체결 시뮬레이션 매수 신호 {len(buy_signals_x)}개 표시됨")
            
            # 매도 신호 표시 (파란색 아래 화살표)
            if sell_signals_x:
                ax.scatter(sell_signals_x, sell_signals_y, 
                          color='blue', s=150, marker='v', 
                          label=f'매도신호({len(sell_signals_x)}개)', zorder=10, 
                          edgecolors='darkblue', linewidth=2)
                self.logger.info(f"체결 시뮬레이션 매도 신호 {len(sell_signals_x)}개 표시됨")
            
        except Exception as e:
            self.logger.error(f"체결 시뮬레이션 신호 표시 오류: {e}")

    def _draw_price_box(self, ax, box_data, data: pd.DataFrame):
        """가격박스 그리기 - 정확한 x 위치 기준"""
        try:
            if 'resistance' in box_data and 'support' in box_data:
                # 시간 기반 x 위치 계산
                x_positions = self._calculate_x_positions(data)
                
                # 데이터 길이 맞추기
                data_len = len(data)
                
                # 가격박스 라인들 그리기
                if 'resistance' in box_data:
                    resistance_data = self._align_data_length(box_data['resistance'], data_len, data)
                    ax.plot(x_positions, resistance_data, color='red', linestyle='--', 
                           alpha=0.8, label='박스상한선', linewidth=1.5)
                
                if 'support' in box_data:
                    support_data = self._align_data_length(box_data['support'], data_len, data)
                    ax.plot(x_positions, support_data, color='purple', linestyle='--', 
                           alpha=0.8, label='박스하한선', linewidth=1.5)
                
                # 중심선 (앞의 두 선보다 굵게)
                if 'center' in box_data and box_data['center'] is not None:
                    center_data = self._align_data_length(box_data['center'], data_len, data)
                    ax.plot(x_positions, center_data, color='green', linestyle='-', 
                           alpha=0.9, label='박스중심선', linewidth=2.5)
                
                # 박스 영역 채우기
                if 'resistance' in box_data and 'support' in box_data:
                    resistance_fill = self._align_data_length(box_data['resistance'], data_len, data)
                    support_fill = self._align_data_length(box_data['support'], data_len, data)
                    
                    ax.fill_between(x_positions, resistance_fill, support_fill,
                                   alpha=0.1, color='gray', label='가격박스')
                    
        except Exception as e:
            self.logger.error(f"가격박스 그리기 오류: {e}")
    
    def _draw_bisector_line(self, ax, bisector_data, data: pd.DataFrame):
        """이등분선 그리기 - 정확한 x 위치 기준"""
        try:
            if 'line_values' in bisector_data:
                # 시간 기반 x 위치 계산
                x_positions = self._calculate_x_positions(data)
                
                # 데이터 길이 맞추기
                data_len = len(data)
                line_values = self._align_data_length(bisector_data['line_values'], data_len, data)
                
                ax.plot(x_positions, line_values, color='blue', linestyle='-', 
                       alpha=0.8, label='이등분선', linewidth=2)
        except Exception as e:
            self.logger.error(f"이등분선 그리기 오류: {e}")
    
    def _draw_bollinger_bands(self, ax, bb_data, data: pd.DataFrame):
        """볼린저밴드 그리기 - 정확한 x 위치 기준"""
        try:
            if all(k in bb_data for k in ['upper', 'middle', 'lower']):
                # 시간 기반 x 위치 계산
                x_positions = self._calculate_x_positions(data)
                
                # 데이터 길이 맞추기
                data_len = len(data)
                
                upper_data = self._align_data_length(bb_data['upper'], data_len, data)
                middle_data = self._align_data_length(bb_data['middle'], data_len, data)
                lower_data = self._align_data_length(bb_data['lower'], data_len, data)
                
                ax.plot(x_positions, upper_data, color='red', linestyle='-', alpha=0.6, label='볼린저 상단')
                ax.plot(x_positions, middle_data, color='blue', linestyle='-', alpha=0.8, label='볼린저 중심')
                ax.plot(x_positions, lower_data, color='red', linestyle='-', alpha=0.6, label='볼린저 하단')
                
                # 밴드 영역 채우기
                ax.fill_between(x_positions, upper_data, lower_data,
                               alpha=0.1, color='blue', label='볼린저밴드')
        except Exception as e:
            self.logger.error(f"볼린저밴드 그리기 오류: {e}")
    
    def _draw_multi_bollinger_bands(self, ax, multi_bb_data, data: pd.DataFrame):
        """다중 볼린저밴드 그리기 - 정확한 x 위치 기준"""
        try:
            # 시간 기반 x 위치 계산
            x_positions = self._calculate_x_positions(data)
            data_len = len(data)
            
            # 다중 볼린저밴드 색상 및 기간 설정
            colors = ['red', 'orange', 'green', 'blue']
            periods = [50, 40, 30, 20]
            
            for i, period in enumerate(periods):
                if i < len(colors):
                    color = colors[i]
                    
                    # 각 기간별 데이터 키 확인
                    sma_key = f'sma_{period}'
                    upper_key = f'upper_{period}'
                    lower_key = f'lower_{period}'
                    
                    if period in [50, 40, 30]:
                        # 상한선만 그리기 (50, 40, 30 기간)
                        if upper_key in multi_bb_data:
                            upper_data = self._align_data_length(multi_bb_data[upper_key], data_len, data)
                            ax.plot(x_positions, upper_data, color=color, linestyle='--', 
                                   alpha=0.8, label=f'상한선({period})', linewidth=1.5)
                    
                    elif period == 20:
                        # 20 기간은 중심선, 상한선, 하한선 모두 그리기
                        if sma_key in multi_bb_data:
                            sma_data = self._align_data_length(multi_bb_data[sma_key], data_len, data)
                            ax.plot(x_positions, sma_data, color=color, linestyle='-', 
                                   alpha=0.9, label=f'중심선({period})', linewidth=2)
                        
                        if upper_key in multi_bb_data:
                            upper_data = self._align_data_length(multi_bb_data[upper_key], data_len, data)
                            ax.plot(x_positions, upper_data, color=color, linestyle='--', 
                                   alpha=0.8, label=f'상한선({period})', linewidth=1.5)
                        
                        if lower_key in multi_bb_data:
                            lower_data = self._align_data_length(multi_bb_data[lower_key], data_len, data)
                            ax.plot(x_positions, lower_data, color=color, linestyle='--', 
                                   alpha=0.8, label=f'하한선({period})', linewidth=1.5)
            
            # 이등분선 그리기 (다중볼린저밴드에 포함된 경우)
            if 'bisector_line' in multi_bb_data:
                bisector_data = self._align_data_length(multi_bb_data['bisector_line'], data_len, data)
                ax.plot(x_positions, bisector_data, color='purple', linestyle=':', 
                       alpha=0.8, label='이등분선', linewidth=2)
            
            # 상한선 밀집 구간 표시 (있는 경우)
            if 'upper_convergence' in multi_bb_data:
                convergence_data = self._align_data_length(multi_bb_data['upper_convergence'], data_len, data)
                
                # 밀집 구간 배경 표시 (안전한 인덱스 범위 체크)
                max_len = min(len(convergence_data), len(x_positions))
                for i in range(max_len):
                    try:
                        # 안전한 데이터 접근
                        if hasattr(convergence_data, 'iloc'):
                            convergence_value = convergence_data.iloc[i]
                        else:
                            convergence_value = convergence_data[i]
                        
                        if convergence_value and i < len(x_positions):
                            x_start = x_positions[i] - 0.4
                            x_end = x_positions[i] + 0.4
                            ax.axvspan(x_start, x_end, alpha=0.2, color='yellow')
                    except (IndexError, KeyError):
                        # 인덱스 오류 시 무시
                        continue
                        
        except Exception as e:
            self.logger.error(f"다중 볼린저밴드 그리기 오류: {e}")
    
    def _draw_volume_chart(self, ax, data: pd.DataFrame):
        """거래량 차트 그리기 - 정확한 x 위치 기준"""
        try:
            # 시간 기반 x 위치 계산
            x_positions = self._calculate_x_positions(data)
            
            # 거래량 차트 그리기
            for idx, (_, row) in enumerate(data.iterrows()):
                x = x_positions[idx]
                volume = row['volume']
                close_price = row['close']
                open_price = row['open']
                
                # 거래량 색상 (캔들과 동일)
                if close_price >= open_price:
                    color = 'red'
                    alpha = 0.7
                else:
                    color = 'blue' 
                    alpha = 0.7
                    
                ax.bar(x, volume, color=color, alpha=alpha, width=0.8, 
                      edgecolor='none')
                
        except Exception as e:
            self.logger.error(f"거래량 차트 그리기 오류: {e}")
    
    def _align_data_length(self, data_series, target_len: int, reference_data: pd.DataFrame):
        """데이터 길이를 맞추는 헬퍼 함수"""
        try:
            if len(data_series) > target_len:
                return data_series.iloc[:target_len]
            elif len(data_series) < target_len:
                return data_series.reindex(reference_data.index, method='ffill')
            return data_series
        except Exception:
            return data_series
    
    def _validate_and_clean_data(self, data: pd.DataFrame, target_date: str = None) -> pd.DataFrame:
        """데이터 검증 및 중복 제거"""
        try:
            timeframe = getattr(self, 'current_timeframe', '1min')
            self.logger.error(f"🔍 데이터 검증 시작 ({timeframe}):")
            self.logger.error(f"   - 입력 데이터: {len(data)}개")
            self.logger.error(f"   - target_date: {target_date}")
            
            if data.empty:
                return data
                
            # 날짜 필터링 (target_date가 제공된 경우)
            if target_date:
                original_count = len(data)
                if 'datetime' in data.columns:
                    # datetime 컬럼이 있는 경우
                    data['date_str'] = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d')
                    self.logger.error(f"   - datetime 기반 날짜 필터링")
                    data = data[data['date_str'] == target_date].drop('date_str', axis=1)
                elif 'time' in data.columns:
                    # time 컬럼이 있는 경우 - 형식 확인
                    time_samples = data['time'].head(5).astype(str).tolist()
                    self.logger.error(f"   - time 컬럼 샘플: {time_samples}")
                    
                    # time이 HHMMSS 형식인지 YYYYMMDDHHMM 형식인지 확인
                    first_time = str(data['time'].iloc[0])
                    if len(first_time) <= 6:
                        # HHMMSS 형식 - datetime 컬럼을 기준으로 필터링
                        self.logger.error(f"   - time이 HHMMSS 형식, datetime 컬럼으로 날짜 필터링")
                        if 'datetime' in data.columns:
                            data['date_str'] = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d')
                            data = data[data['date_str'] == target_date].drop('date_str', axis=1)
                        else:
                            self.logger.error(f"   - datetime 컬럼 없음, 날짜 필터링 스킵")
                    else:
                        # YYYYMMDDHHMM 형식
                        self.logger.error(f"   - time이 YYYYMMDDHHMM 형식")
                        data['date_str'] = data['time'].astype(str).str[:8]
                        data = data[data['date_str'] == target_date].drop('date_str', axis=1)
                
                if len(data) != original_count:
                    self.logger.error(f"   - 날짜 필터링 결과: {original_count} → {len(data)} (target_date: {target_date})")
                    if len(data) < original_count // 2:
                        self.logger.error(f"   ⚠️ 데이터가 절반 이상 사라짐! 날짜 필터링 문제 의심")
                else:
                    self.logger.error(f"   - 날짜 필터링: 변화 없음")
            
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
    
    def _calculate_x_positions(self, data: pd.DataFrame, timeframe: str = None) -> list:
        """
        시간프레임에 따른 x 위치 계산
        - 1분봉: 09:00부터의 실제 분 단위 인덱스 (0, 1, 2, 3...)
        - 5분봉: 연속 인덱스 (0, 1, 2, 3...) - 캔들들이 이어지도록
        - 3분봉: 연속 인덱스 (0, 1, 2, 3...) - 캔들들이 이어지도록
        """
        # timeframe이 지정되지 않으면 클래스 변수 사용
        if timeframe is None:
            timeframe = getattr(self, 'current_timeframe', '1min')
            
        # time 또는 datetime 컬럼 확인
        if 'time' in data.columns:
            time_values = data['time'].astype(str).str.zfill(6)
        elif 'datetime' in data.columns:
            # datetime에서 시간 부분 추출 (HHMMSS 형식)
            time_values = pd.to_datetime(data['datetime']).dt.strftime('%H%M%S')
        else:
            self.logger.error(f"❌ {timeframe}: 시간 컬럼 없음. 사용 가능한 컬럼: {list(data.columns)}")
            return list(range(len(data)))
        # 데이터의 실제 시작 시간을 감지하여 기준점 설정
        if len(time_values) > 0:
            first_time = time_values.iloc[0] if hasattr(time_values, 'iloc') else time_values[0]
            if len(str(first_time)) == 6:
                try:
                    first_hour = int(str(first_time)[:2])
                    first_minute = int(str(first_time)[2:4])
                    # 데이터가 09:00 이후에 시작하면 09:00 기준, 그렇지 않으면 08:00 기준
                    if first_hour >= 9:
                        start_minutes = 9 * 60  # 09:00 = 540분 (KRX 전용)
                        self.logger.debug(f"📊 KRX 시간 기준 설정: 09:00 시작 (첫 데이터: {first_time})")
                    else:
                        start_minutes = 8 * 60   # 08:00 = 480분 (NXT 포함)
                        self.logger.debug(f"📊 NXT 시간 기준 설정: 08:00 시작 (첫 데이터: {first_time})")
                except ValueError:
                    start_minutes = 8 * 60  # 기본값
                    self.logger.warning(f"시간 파싱 실패, 기본값 08:00 사용")
            else:
                start_minutes = 8 * 60  # 기본값
        else:
            start_minutes = 8 * 60  # 기본값
        
        x_positions = []
        prev_x_pos = -1
        
        if timeframe == "1min":
            # 1분봉은 실제 시간 기반 인덱스 (기존 방식)
            for i, time_str in enumerate(time_values):
                if len(time_str) == 6:
                    try:
                        hour = int(time_str[:2])
                        minute = int(time_str[2:4])
                        current_minutes = hour * 60 + minute
                        
                        # 08:00부터의 분 단위 인덱스 계산 (연속)
                        x_pos = current_minutes - start_minutes
                        
                        # 중복되거나 이상한 x 위치 방지
                        if x_pos == prev_x_pos:
                            x_pos = prev_x_pos + 1
                        elif x_pos < prev_x_pos:
                            x_pos = prev_x_pos + 1
                        
                        x_positions.append(x_pos)
                        prev_x_pos = x_pos
                        
                    except ValueError:
                        x_pos = prev_x_pos + 1 if prev_x_pos >= 0 else i
                        x_positions.append(x_pos)
                        prev_x_pos = x_pos
                else:
                    x_pos = prev_x_pos + 1 if prev_x_pos >= 0 else i
                    x_positions.append(x_pos)
                    prev_x_pos = x_pos
                    
            # 디버깅 로그 (중복 확인)
            unique_positions = len(set(x_positions))
            total_positions = len(x_positions)
            if unique_positions != total_positions:
                self.logger.warning(f"X 위치 중복 감지: {total_positions}개 중 {unique_positions}개 고유값")
                
            return x_positions
        else:
            # 5분봉, 3분봉: 실제 시간 기반 인덱스 계산
            timeframe_minutes = int(timeframe.replace('min', ''))
            
            for i, time_str in enumerate(time_values):
                if len(time_str) == 6:
                    try:
                        hour = int(time_str[:2])
                        minute = int(time_str[2:4])
                        current_minutes = hour * 60 + minute
                        
                        # 08:00부터의 시간 기준으로 계산
                        minutes_from_start = current_minutes - start_minutes
                        
                        # timeframe에 맞는 인덱스 계산 (3분봉이면 3분 단위로)
                        x_pos = minutes_from_start // timeframe_minutes
                        
                        # 중복 방지
                        if x_pos == prev_x_pos:
                            x_pos = prev_x_pos + 1
                        elif x_pos < prev_x_pos:
                            x_pos = prev_x_pos + 1
                        
                        x_positions.append(x_pos)
                        prev_x_pos = x_pos
                        
                    except ValueError:
                        x_pos = prev_x_pos + 1 if prev_x_pos >= 0 else i
                        x_positions.append(x_pos)
                        prev_x_pos = x_pos
                else:
                    x_pos = prev_x_pos + 1 if prev_x_pos >= 0 else i
                    x_positions.append(x_pos)
                    prev_x_pos = x_pos
            
            # 성공 로그
            if x_positions:
                self.logger.info(f"✅ {timeframe} 시간 기반 X축 계산 완료: {min(x_positions)} ~ {max(x_positions)} ({len(x_positions)}개)")
            else:
                self.logger.error(f"❌ {timeframe} X 위치 계산 실패")
            
            return x_positions
    
    def _set_time_axis_labels(self, ax1, ax2, data: pd.DataFrame, timeframe: str):
        """X축 시간 레이블 설정 - 08:00~15:30 연속 거래시간 기반"""
        try:
            data_len = len(data)
            if data_len == 0:
                return
            
            # 실제 데이터의 시간 정보 확인
            if 'time' not in data.columns and 'datetime' not in data.columns:
                self.logger.warning("시간 정보가 없어 기본 인덱스 사용")
                return
            
            # 시간 컬럼 선택 및 변환
            if 'time' in data.columns:
                time_values = data['time'].astype(str).str.zfill(6)  # HHMMSS 형태로 변환
                def parse_time(time_str):
                    if len(time_str) == 6:
                        hour = int(time_str[:2])
                        minute = int(time_str[2:4])
                        return hour, minute
                    return 9, 0  # 기본값
            elif 'datetime' in data.columns:
                def parse_time(dt):
                    if pd.isna(dt):
                        return 9, 0
                    return dt.hour, dt.minute
                time_values = data['datetime']
            
            # 시간 간격 설정 (timeframe에 따라)
            if timeframe == "5min":
                interval_minutes = 5  # 5분봉은 5분 간격으로 표시
            else:
                interval_minutes = 30  # 1분봉, 3분봉은 30분 간격으로 표시
            
            # 시간 레이블과 위치 생성
            time_labels = []
            x_positions = []
            
            # 실제 데이터에서 첫 번째와 마지막 시간 확인
            if len(time_values) > 0:
                first_hour, first_minute = parse_time(time_values.iloc[0])
                last_hour, last_minute = parse_time(time_values.iloc[-1])
                
                self.logger.debug(f"데이터 시간 범위: {first_hour:02d}:{first_minute:02d} ~ {last_hour:02d}:{last_minute:02d}")
            
            # 데이터의 실제 시작 시간에 따른 거래시간 계산
            if len(time_values) > 0:
                first_hour, first_minute = parse_time(time_values.iloc[0])
                # 09:00 이후 시작하면 KRX (09:00~15:30 = 6.5시간), 그렇지 않으면 NXT 포함 (08:00~15:30 = 7.5시간)
                if first_hour >= 9:
                    start_hour = 9
                    total_trading_minutes = 390  # 09:00~15:30 = 6.5시간 * 60분
                    self.logger.debug(f"📊 KRX 시간축 설정: 09:00~15:30 ({total_trading_minutes}분)")
                else:
                    start_hour = 8  
                    total_trading_minutes = 450  # 08:00~15:30 = 7.5시간 * 60분
                    self.logger.debug(f"📊 NXT 시간축 설정: 08:00~15:30 ({total_trading_minutes}분)")
            else:
                start_hour = 8
                total_trading_minutes = 450  # 기본값
            
            if timeframe == "1min":
                total_candles = total_trading_minutes  # 390개 캔들
                step = interval_minutes  # 30분 간격 (또는 5분)
            elif timeframe == "5min":
                total_candles = len(data) if len(data) > 0 else total_trading_minutes // 5  # 실제 5분봉 개수
                step = max(1, len(data) // 10)  # 5분봉은 전체 개수의 1/10로 간격 설정
            else:  # 3min
                total_candles = total_trading_minutes // 3  # 130개 캔들
                step = interval_minutes // 3  # 10개 캔들 간격
            
            # 시작 시간부터 15:30까지 30분 간격으로 레이블 생성
            start_minutes = start_hour * 60  # 동적 시작 시간
            end_minutes = 15 * 60 + 30  # 15:30 = 930분
            
            current_time_minutes = start_minutes
            while current_time_minutes <= end_minutes:
                hour = current_time_minutes // 60
                minute = current_time_minutes % 60
                
                # 해당 시간의 데이터 인덱스 계산 (연속)
                real_data_start_minutes = start_hour * 60  # 실제 데이터 시작 시간
                
                if timeframe == "1min":
                    if current_time_minutes < real_data_start_minutes:
                        data_index = current_time_minutes - real_data_start_minutes  # 음수 인덱스
                    else:
                        data_index = current_time_minutes - real_data_start_minutes  # 0부터 시작
                elif timeframe == "5min":
                    if current_time_minutes < real_data_start_minutes:
                        data_index = (current_time_minutes - real_data_start_minutes) // 5  # 음수 인덱스
                    else:
                        data_index = (current_time_minutes - real_data_start_minutes) // 5
                        if data_index >= len(data):
                            break
                else:  # 3min
                    if current_time_minutes < real_data_start_minutes:
                        data_index = (current_time_minutes - real_data_start_minutes) // 3  # 음수 인덱스
                    else:
                        data_index = (current_time_minutes - real_data_start_minutes) // 3
                        if data_index >= len(data):
                            break
                
                time_label = f"{hour:02d}:{minute:02d}"
                time_labels.append(time_label)
                x_positions.append(data_index)
                
                current_time_minutes += interval_minutes
            
            # X축 레이블 설정
            if x_positions and time_labels:
                ax1.set_xticks(x_positions)
                ax1.set_xticklabels(time_labels, rotation=45, fontsize=10)
                ax2.set_xticks(x_positions)
                ax2.set_xticklabels(time_labels, rotation=45, fontsize=10)
                
                # X축 범위 설정 
                if timeframe == "5min" or timeframe == "3min":
                    # 5분봉/3분봉은 실제 데이터 길이에 맞춤
                    ax1.set_xlim(-0.5, len(data) - 0.5)
                    ax2.set_xlim(-0.5, len(data) - 0.5)
                else:
                    # 1분봉은 전체 거래시간 기준
                    ax1.set_xlim(-0.5, total_candles - 0.5)
                    ax2.set_xlim(-0.5, total_candles - 0.5)
                
                self.logger.debug(f"시간축 설정 완료: {len(x_positions)}개 레이블")
            
        except Exception as e:
            self.logger.error(f"시간 축 레이블 설정 오류: {e}")
            # 오류 시 기본 인덱스 레이블 사용
            if len(data) > 0:
                x_ticks = range(0, len(data), max(1, len(data) // 10))
                ax1.set_xticks(x_ticks)
                ax1.set_xticklabels([str(i) for i in x_ticks])
                ax2.set_xticks(x_ticks)
                ax2.set_xticklabels([str(i) for i in x_ticks])
    
    def _set_basic_time_axis_labels(self, ax, data: pd.DataFrame):
        """기본 차트용 X축 시간 레이블 설정 - 08:00~15:30 연속 거래시간 기준"""
        try:
            data_len = len(data)
            if data_len == 0:
                return
            
            # 실제 데이터의 시간 정보 확인
            if 'time' not in data.columns and 'datetime' not in data.columns:
                self.logger.warning("시간 정보가 없어 기본 인덱스 사용")
                return
            
            # 시간 컬럼 선택 및 변환
            if 'time' in data.columns:
                time_values = data['time'].astype(str).str.zfill(6)  # HHMMSS 형태로 변환
                def parse_time(time_str):
                    if len(time_str) == 6:
                        hour = int(time_str[:2])
                        minute = int(time_str[2:4])
                        return hour, minute
                    return 9, 0  # 기본값
            elif 'datetime' in data.columns:
                def parse_time(dt):
                    if pd.isna(dt):
                        return 9, 0
                    return dt.hour, dt.minute
                time_values = data['datetime']
            
            # 30분 간격으로 시간 레이블 생성
            interval_minutes = 30
            time_labels = []
            x_positions = []
            
            # 전체 거래시간 기준 (08:00~15:30 = 7.5시간 * 60분 = 450분)
            total_trading_minutes = 450  # 08:00~15:30 연속 거래
            total_candles = total_trading_minutes  # 1분봉 기준 390개 캔들
            
            # 08:00부터 15:30까지 30분 간격으로 레이블 생성
            start_minutes = 8 * 60  # 08:00 = 480분
            end_minutes = 15 * 60 + 30  # 15:30 = 930분
            
            current_time_minutes = start_minutes
            while current_time_minutes <= end_minutes:
                hour = current_time_minutes // 60
                minute = current_time_minutes % 60
                
                # 해당 시간의 데이터 인덱스 계산 (연속, 1분봉 기준)
                data_index = current_time_minutes - start_minutes  # 분 단위
                
                time_label = f"{hour:02d}:{minute:02d}"
                time_labels.append(time_label)
                x_positions.append(data_index)
                
                current_time_minutes += interval_minutes
            
            # X축 레이블 설정
            if x_positions and time_labels:
                ax.set_xticks(x_positions)
                ax.set_xticklabels(time_labels, rotation=45, fontsize=10)
                # 전체 거래시간 범위로 설정 (08:00~15:30)
                # 08:00~09:00 구간 포함하여 X축 범위 확장
                timeframe_minutes = int(time_labels[0].replace('분', '')) if time_labels and '분' in time_labels[0] else 3
                no_data_positions = 60 // timeframe_minutes  # 08:00~09:00 = 60분
                ax.set_xlim(-no_data_positions - 0.5, total_candles - 0.5)
            
        except Exception as e:
            self.logger.error(f"기본 차트 시간 축 레이블 설정 오류: {e}")
            # 오류 시 기본 인덱스 레이블 사용
            if len(data) > 0:
                x_ticks = range(0, len(data), max(1, len(data) // 10))
                ax.set_xticks(x_ticks)
                ax.set_xticklabels([str(i) for i in x_ticks])
    
    def _draw_no_data_background(self, ax1, ax2, data: pd.DataFrame, timeframe: str):
        """08:00~09:00 구간에 회색 배경 표시 (데이터 없는 구간)"""
        try:
            if data.empty:
                return
                
            # 1분 = 1위치, 3분 = 3위치 등으로 계산
            timeframe_minutes = int(timeframe.replace('min', ''))
            
            # 08:00~09:00 = 60분 구간
            no_data_minutes = 60
            no_data_positions = no_data_minutes // timeframe_minutes
            
            # 실제 데이터 시작 시간 확인
            if 'time' in data.columns:
                first_time_str = str(data['time'].iloc[0]).zfill(6)
                first_hour = int(first_time_str[:2])
                if first_hour >= 9:  # 09:00 이후부터 데이터 시작
                    # 08:00~09:00 구간 회색 배경
                    ax1.axvspan(-no_data_positions, 0, alpha=0.2, color='lightgray', label='거래시간 외')
                    ax2.axvspan(-no_data_positions, 0, alpha=0.2, color='lightgray')
                    
                    # 텍스트 표시
                    ax1.text(-no_data_positions/2, ax1.get_ylim()[1] * 0.95, 
                            '08:00~09:00\n거래시간 외', 
                            ha='center', va='top', fontsize=10, alpha=0.7)
            
        except Exception as e:
            self.logger.debug(f"데이터 없는 구간 배경 표시 오류: {e}")
            # 오류 시 무시하고 계속 진행