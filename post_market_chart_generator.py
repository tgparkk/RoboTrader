"""
장 마감 후 선정 종목 차트 생성기
"""
import asyncio
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # GUI가 없는 백엔드 설정 (비동기 환경에서 안전)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
import sys
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_chart_api import (
    get_inquire_time_dailychartprice,
    get_historical_minute_data
)
from api.kis_api_manager import KISAPIManager
from core.candidate_selector import CandidateSelector
from core.intraday_stock_manager import IntradayStockManager
from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.indicators.price_box import PriceBox
from core.indicators.bisector_line import BisectorLine
from core.indicators.bollinger_bands import BollingerBands
from core.indicators.multi_bollinger_bands import MultiBollingerBands


@dataclass
class TradingStrategy:
    """거래 전략 설정"""
    name: str
    timeframe: str  # "1min" or "3min"
    indicators: List[str]
    description: str


class TradingStrategyConfig:
    """거래 전략 설정 관리"""
    
    STRATEGIES = {
        "strategy1": TradingStrategy(
            name="가격박스+이등분선",
            timeframe="1min",
            indicators=["price_box", "bisector_line"],
            description="가격박스 지지/저항선과 이등분선을 활용한 매매"
        ),
        "strategy2": TradingStrategy(
            name="다중볼린저밴드+이등분선", 
            timeframe="1min",
            indicators=["multi_bollinger_bands", "bisector_line"],
            description="다중 볼린저밴드와 이등분선을 활용한 매매"
        ),
        "strategy3": TradingStrategy(
            name="다중볼린저밴드",
            timeframe="1min", 
            indicators=["multi_bollinger_bands"],
            description="여러 기간의 볼린저밴드를 활용한 매매"
        )
    }
    
    @classmethod
    def get_strategy(cls, strategy_name: str) -> Optional[TradingStrategy]:
        """전략 정보 조회"""
        return cls.STRATEGIES.get(strategy_name)
    
    @classmethod
    def get_all_strategies(cls) -> Dict[str, TradingStrategy]:
        """모든 전략 정보 조회"""
        return cls.STRATEGIES


@dataclass  
class ChartData:
    """차트 데이터와 전략 정보"""
    stock_code: str
    stock_name: str
    timeframe: str
    strategy: TradingStrategy
    price_data: pd.DataFrame
    indicators_data: Dict[str, Any] = field(default_factory=dict)


class PostMarketChartGenerator:
    """
    장 마감 후 선정 종목 차트 생성 클래스
    
    주요 기능:
    1. 조건검색으로 선정된 종목 조회
    2. 특정 날짜의 분봉 데이터로 캔들스틱 차트 생성
    3. 장중 선정 종목들의 일괄 차트 생성
    """
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.api_manager = None
        self.candidate_selector = None
        self.intraday_manager = None
        
        # 차트 설정
        plt.rcParams['font.family'] = ['Malgun Gothic', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
        # 지표 인스턴스 초기화
        self.price_box_indicator = PriceBox()
        self.bisector_indicator = BisectorLine()
        self.bollinger_indicator = BollingerBands()
        self.multi_bollinger_indicator = MultiBollingerBands()
        
        self.logger.info("장 마감 후 차트 생성기 초기화 완료")
    
    def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            # API 매니저 초기화
            self.api_manager = KISAPIManager()
            if not self.api_manager.initialize():
                self.logger.error("API 매니저 초기화 실패")
                return False
            
            # 후보 선정기 초기화
            self.candidate_selector = CandidateSelector(
                config=None,  # 설정은 나중에 로드
                api_manager=self.api_manager
            )
            
            # 장중 종목 관리자 초기화
            self.intraday_manager = IntradayStockManager(self.api_manager)
            
            self.logger.info("시스템 초기화 성공")
            return True
            
        except Exception as e:
            self.logger.error(f"시스템 초기화 오류: {e}")
            return False
    
    def get_condition_search_stocks(self, condition_seq: str = "0") -> List[Dict[str, Any]]:
        """
        조건검색 종목 조회 (실제 조건검색 결과 사용)
        
        Args:
            condition_seq: 조건검색 시퀀스
            
        Returns:
            List[Dict]: 조건검색 결과 종목 리스트
        """
        try:
            if not self.candidate_selector:
                self.logger.error("후보 선정기가 초기화되지 않음")
                return []
            
            # 실제 조건검색 결과 조회
            condition_results = self.candidate_selector.get_condition_search_candidates(seq=condition_seq)
            
            if condition_results:
                self.logger.info(f"조건검색 {condition_seq}번 결과: {len(condition_results)}개 종목")
                return condition_results
            else:
                self.logger.info(f"조건검색 {condition_seq}번: 해당 종목 없음")
                return []
            
        except Exception as e:
            self.logger.error(f"조건검색 종목 조회 오류: {e}")
            return []
    
    def calculate_indicators(self, data: pd.DataFrame, strategy: TradingStrategy) -> Dict[str, Any]:
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
                        multi_bb_data = {}
                        periods = [20, 30, 40, 50]  # MultiBollingerBands.PERIODS
                        
                        for period in periods:
                            bb_result = BollingerBands.calculate_bollinger_bands(data['close'], period=period)
                            if bb_result and 'upper_band' in bb_result:
                                multi_bb_data[f"{period}"] = {
                                    'upper': bb_result['upper_band'],
                                    'middle': bb_result['sma'],
                                    'lower': bb_result['lower_band']
                                }
                        
                        if multi_bb_data:
                            indicators_data["multi_bollinger_bands"] = multi_bb_data
                            
                    except Exception as e:
                        self.logger.error(f"다중 볼린저밴드 계산 오류: {e}")
            
            return indicators_data
            
        except Exception as e:
            self.logger.error(f"지표 계산 오류: {e}")
            return {}
    
    def get_timeframe_data(self, stock_code: str, target_date: str, timeframe: str) -> Optional[pd.DataFrame]:
        """
        지정된 시간프레임의 데이터 조회
        
        Args:
            stock_code: 종목코드
            target_date: 날짜
            timeframe: 시간프레임 ("1min", "3min")
            
        Returns:
            pd.DataFrame: 시간프레임 데이터
        """
        try:
            # 1분봉 데이터를 기본으로 조회
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
            time_points = ["153000", "133000", "113000", "093000"]  # 15:30, 13:30, 11:30, 09:30
            
            for i, end_time in enumerate(time_points):
                try:
                    self.logger.info(f"{stock_code} 분봉 데이터 조회 {i+1}/4: {end_time[:2]}:{end_time[2:4]}까지")
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
                        all_data.append(chart_df)
                        self.logger.info(f"{stock_code} {end_time} 시점 데이터 수집 완료: {len(chart_df)}건")
                    
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
            
            # 중복 데이터 제거
            if 'datetime' in combined_df.columns:
                combined_df = combined_df.drop_duplicates(subset=['datetime'], keep='first')
            elif 'time' in combined_df.columns:
                combined_df = combined_df.drop_duplicates(subset=['time'], keep='first')
            
            self.logger.info(f"{stock_code} {target_date} 전체 분봉 데이터 조합 완료: {len(combined_df)}건")
            return combined_df
            
        except Exception as e:
            self.logger.error(f"{stock_code} {target_date} 분봉 데이터 조회 오류: {e}")
            return None
    
    def _create_chart_sync(self, stock_code: str, stock_name: str, 
                          chart_df: pd.DataFrame, target_date: str,
                          selection_reason: str = "") -> Optional[str]:
        """동기 차트 생성 함수 (전략 기반)"""
        try:
            if chart_df.empty:
                self.logger.error("차트 데이터가 비어있음")
                return None
            
            self.logger.info(f"{stock_code} {target_date} 전략 기반 차트 생성 시작")
            
            # 모든 전략에 대해 차트 생성 (3개 전략)
            strategies = TradingStrategyConfig.get_all_strategies()
            
            for strategy_key, strategy in strategies.items():
                try:
                    # 전략별 시간프레임 데이터 조회
                    timeframe_data = self.get_timeframe_data(stock_code, target_date, strategy.timeframe)
                    
                    if timeframe_data is None or timeframe_data.empty:
                        self.logger.warning(f"{strategy.name} - 데이터 없음")
                        continue
                    
                    # 전략별 지표 계산
                    indicators_data = self.calculate_indicators(timeframe_data, strategy)
                    
                    # 차트 생성
                    chart_path = self._create_strategy_chart(
                        stock_code, stock_name, target_date, strategy, 
                        timeframe_data, indicators_data, selection_reason
                    )
                    
                    if chart_path:
                        self.logger.info(f"✅ {strategy.name} 차트 생성: {chart_path}")
                        return chart_path  # 첫 번째 성공한 차트 반환
                    
                except Exception as e:
                    self.logger.error(f"{strategy.name} 차트 생성 오류: {e}")
                    continue
            
            # 모든 전략이 실패한 경우 기본 차트 생성
            return self._create_basic_chart(stock_code, stock_name, chart_df, target_date, selection_reason)
            
        except Exception as e:
            self.logger.error(f"전략 기반 차트 생성 오류: {e}")
            plt.close()
            return None
    
    def _create_strategy_chart(self, stock_code: str, stock_name: str, target_date: str,
                              strategy: TradingStrategy, data: pd.DataFrame, 
                              indicators_data: Dict[str, Any], selection_reason: str) -> Optional[str]:
        """전략별 차트 생성"""
        try:
            # 서브플롯 설정 (가격 + 거래량)
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), 
                                         gridspec_kw={'height_ratios': [3, 1]})
            
            # 기본 캔들스틱 차트
            self._draw_candlestick(ax1, data)
            
            # 전략별 지표 표시
            self._draw_strategy_indicators(ax1, data, strategy, indicators_data)
            
            # 매수 신호 표시 (빨간색 화살표)
            self._draw_buy_signals(ax1, data, strategy)
            
            # 거래량 차트
            self._draw_volume_chart(ax2, data)
            
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
            
            # X축 시간 레이블 설정 (09:00 ~ 15:30)
            self._set_time_axis_labels(ax1, ax2, data, strategy.timeframe)
            
            plt.tight_layout()
            
            # 파일 저장
            timestamp = now_kst().strftime("%Y%m%d_%H%M%S")
            filename = f"strategy_chart_{stock_code}_{strategy.timeframe}_{target_date}_{timestamp}.png"
            filepath = Path(filename)
            
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()
            
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"전략 차트 생성 실패: {e}")
            plt.close()
            return None
    
    def _draw_candlestick(self, ax, data: pd.DataFrame):
        """캔들스틱 차트 그리기"""
        try:
            for idx, row in data.iterrows():
                x = idx
                open_price = row['open']
                high_price = row['high']
                low_price = row['low']
                close_price = row['close']
                
                # 캔들 색상 결정
                color = 'red' if close_price >= open_price else 'blue'
                
                # High-Low 선 (캔들과 같은 색으로)
                ax.plot([x, x], [low_price, high_price], color=color, linewidth=1)
                
                # 캔들 몸통
                candle_height = abs(close_price - open_price)
                candle_bottom = min(open_price, close_price)
                
                if candle_height > 0:
                    candle = Rectangle((x - 0.3, candle_bottom), 0.6, candle_height,
                                     facecolor=color, edgecolor=color, alpha=0.8)
                    ax.add_patch(candle)
                else:
                    # 시가와 종가가 같은 경우 (십자선)
                    ax.plot([x - 0.3, x + 0.3], [close_price, close_price], 
                           color=color, linewidth=2)
                           
        except Exception as e:
            self.logger.error(f"캔들스틱 그리기 오류: {e}")
    
    def _draw_strategy_indicators(self, ax, data: pd.DataFrame, strategy: TradingStrategy, 
                                 indicators_data: Dict[str, Any]):
        """전략별 지표 그리기"""
        try:
            for indicator_name in strategy.indicators:
                if indicator_name in indicators_data:
                    indicator_data = indicators_data[indicator_name]
                    
                    if indicator_name == "price_box":
                        self._draw_price_box(ax, indicator_data)
                    elif indicator_name == "bisector_line":
                        self._draw_bisector_line(ax, indicator_data)
                    elif indicator_name == "bollinger_bands":
                        self._draw_bollinger_bands(ax, indicator_data)
                    elif indicator_name == "multi_bollinger_bands":
                        self._draw_multi_bollinger_bands(ax, indicator_data)
                        
        except Exception as e:
            self.logger.error(f"지표 그리기 오류: {e}")
    
    def _draw_buy_signals(self, ax, data: pd.DataFrame, strategy: TradingStrategy):
        """매수 신호 표시 (빨간색 화살표)"""
        try:
            # 전략별 매수 신호 계산
            buy_signals = self._calculate_buy_signals(data, strategy)
            
            if buy_signals is not None and buy_signals.any():
                # 매수 신호가 있는 지점의 가격
                buy_prices = data.loc[buy_signals, 'close']
                buy_indices = data.index[buy_signals]
                
                # 빨간색 화살표로 표시
                ax.scatter(buy_indices, buy_prices, 
                          color='red', s=150, marker='^', 
                          label='매수신호', zorder=10, edgecolors='darkred', linewidth=2)
                
                self.logger.info(f"매수 신호 {buy_signals.sum()}개 표시됨")
            
        except Exception as e:
            self.logger.error(f"매수 신호 표시 오류: {e}")
    
    def _calculate_buy_signals(self, data: pd.DataFrame, strategy: TradingStrategy) -> pd.Series:
        """전략별 매수 신호 계산"""
        try:
            buy_signals = pd.Series(False, index=data.index)
            
            # 전략별 매수 신호 계산
            for indicator_name in strategy.indicators:
                if indicator_name == "price_box":
                    # 가격박스 매수 신호
                    price_signals = PriceBox.generate_trading_signals(data['close'])
                    if 'buy_signal' in price_signals.columns:
                        buy_signals |= price_signals['buy_signal']
                
                elif indicator_name == "bollinger_bands":
                    # 볼린저밴드 매수 신호
                    bb_signals = BollingerBands.generate_trading_signals(data['close'])
                    if 'buy_signal' in bb_signals.columns:
                        buy_signals |= bb_signals['buy_signal']
                
                elif indicator_name == "multi_bollinger_bands":
                    # 다중 볼린저밴드 매수 신호
                    if 'volume' in data.columns:
                        multi_bb_signals = MultiBollingerBands.generate_trading_signals(
                            data['close'], data['volume'])
                    else:
                        multi_bb_signals = MultiBollingerBands.generate_trading_signals(data['close'])
                    
                    if 'buy_signal' in multi_bb_signals.columns:
                        buy_signals |= multi_bb_signals['buy_signal']
                
                elif indicator_name == "bisector_line":
                    # 이등분선 기반 매수 신호 (OHLC 데이터 필요)
                    if all(col in data.columns for col in ['open', 'high', 'low', 'close']):
                        bisector_signals = BisectorLine.generate_trading_signals(data)
                        # 이등분선의 경우 tradable_zone을 매수 신호로 사용
                        if 'tradable_zone' in bisector_signals.columns:
                            buy_signals |= bisector_signals['tradable_zone']
            
            return buy_signals
            
        except Exception as e:
            self.logger.error(f"매수 신호 계산 오류: {e}")
            return pd.Series(False, index=data.index)
    
    def _draw_price_box(self, ax, box_data):
        """가격박스 그리기"""
        try:
            if 'resistance' in box_data and 'support' in box_data:
                # 가격박스는 시간에 따라 변하는 값이므로 plot() 사용
                ax.plot(box_data['resistance'], color='red', linestyle='--', 
                       alpha=0.7, label='저항선', linewidth=1.5)
                ax.plot(box_data['support'], color='blue', linestyle='--', 
                       alpha=0.7, label='지지선', linewidth=1.5)
                
                # 중심선도 있다면 추가
                if 'center' in box_data and box_data['center'] is not None:
                    ax.plot(box_data['center'], color='orange', linestyle='-', 
                           alpha=0.6, label='중심선', linewidth=1)
        except Exception as e:
            self.logger.error(f"가격박스 그리기 오류: {e}")
    
    def _draw_bisector_line(self, ax, bisector_data):
        """이등분선 그리기"""
        try:
            if 'line_values' in bisector_data:
                ax.plot(bisector_data['line_values'], color='blue', linestyle='-', 
                       alpha=0.8, label='이등분선', linewidth=2)
        except Exception as e:
            self.logger.error(f"이등분선 그리기 오류: {e}")
    
    def _draw_bollinger_bands(self, ax, bb_data):
        """볼린저밴드 그리기"""
        try:
            if all(k in bb_data for k in ['upper', 'middle', 'lower']):
                ax.plot(bb_data['upper'], color='red', linestyle='-', alpha=0.6, label='볼린저 상단')
                ax.plot(bb_data['middle'], color='blue', linestyle='-', alpha=0.8, label='볼린저 중심')
                ax.plot(bb_data['lower'], color='red', linestyle='-', alpha=0.6, label='볼린저 하단')
        except Exception as e:
            self.logger.error(f"볼린저밴드 그리기 오류: {e}")
    
    def _draw_multi_bollinger_bands(self, ax, multi_bb_data):
        """다중 볼린저밴드 그리기"""
        try:
            colors = ['orange', 'purple', 'brown']
            for i, (period, bb_data) in enumerate(multi_bb_data.items()):
                if i < len(colors) and all(k in bb_data for k in ['upper', 'middle', 'lower']):
                    color = colors[i]
                    ax.plot(bb_data['upper'], color=color, linestyle='--', alpha=0.5, 
                           label=f'BB{period} 상단')
                    ax.plot(bb_data['lower'], color=color, linestyle='--', alpha=0.5, 
                           label=f'BB{period} 하단')
        except Exception as e:
            self.logger.error(f"다중 볼린저밴드 그리기 오류: {e}")
    
    def _draw_volume_chart(self, ax, data: pd.DataFrame):
        """거래량 차트 그리기"""
        try:
            for idx, row in data.iterrows():
                x = idx
                volume = row['volume']
                close_price = row['close']
                open_price = row['open']
                
                color = 'red' if close_price >= open_price else 'blue'
                ax.bar(x, volume, color=color, alpha=0.6, width=0.6)
                
        except Exception as e:
            self.logger.error(f"거래량 차트 그리기 오류: {e}")
    
    def _set_time_axis_labels(self, ax1, ax2, data: pd.DataFrame, timeframe: str):
        """X축 시간 레이블 설정 (09:00 ~ 15:30)"""
        try:
            data_len = len(data)
            if data_len == 0:
                return
            
            # 전체 거래시간 데이터 검증
            expected_len_1min = 390  # 09:00~15:30 = 6.5시간 * 60분
            expected_len_3min = 130  # 390분 / 3분
            
            if timeframe == "1min" and data_len < expected_len_1min:
                self.logger.warning(f"1분봉 데이터 부족: {data_len}/{expected_len_1min}")
            elif timeframe == "3min" and data_len < expected_len_3min:
                self.logger.warning(f"3분봉 데이터 부족: {data_len}/{expected_len_3min}")
            
            # 시간프레임에 따른 간격 설정
            if timeframe == "1min":
                # 1분봉: 390분 (09:00~15:30) -> 30분 간격으로 표시
                interval_minutes = 30
                total_trading_minutes = 390  # 6.5시간 * 60분
            else:  # 3min
                # 3분봉: 130개 캔들 -> 15개 간격으로 표시  
                interval_minutes = 45  # 15 * 3분
                total_trading_minutes = 390
            
            # 시간 레이블 생성
            time_labels = []
            x_positions = []
            
            # 09:00부터 15:30까지의 시간 레이블 생성
            start_hour = 9
            start_minute = 0
            end_hour = 15
            end_minute = 30
            
            # 현재 시간을 추적
            current_hour = start_hour
            current_minute = start_minute
            
            # 데이터 길이에 따른 시간 간격 계산
            if timeframe == "1min":
                # 1분봉: 데이터 인덱스가 곧 분단위
                positions_interval = interval_minutes  # 30분 간격
            else:  # 3min
                # 3분봉: 3분마다 하나의 캔들
                positions_interval = interval_minutes // 3  # 15개 캔들 간격
            
            # 전체 거래시간 기준으로 레이블 생성 (09:00 ~ 15:30)
            current_minutes = start_hour * 60 + start_minute  # 09:00 = 540분
            end_minutes = end_hour * 60 + end_minute  # 15:30 = 930분
            
            while current_minutes <= end_minutes:
                hour = current_minutes // 60
                minute = current_minutes % 60
                
                if timeframe == "1min":
                    # 1분봉: 분단위 인덱스
                    data_index = current_minutes - (start_hour * 60 + start_minute)
                else:  # 3min
                    # 3분봉: 3분 단위 인덱스
                    data_index = (current_minutes - (start_hour * 60 + start_minute)) // 3
                
                # 전체 거래시간 레이블 표시 (데이터 유무와 관계없이)
                time_label = f"{hour:02d}:{minute:02d}"
                time_labels.append(time_label)
                x_positions.append(data_index)
                
                # 다음 시간으로 이동
                current_minutes += interval_minutes
            
            # X축 레이블 설정
            if x_positions and time_labels:
                ax1.set_xticks(x_positions)
                ax1.set_xticklabels(time_labels, rotation=45, fontsize=10)
                ax2.set_xticks(x_positions)
                ax2.set_xticklabels(time_labels, rotation=45, fontsize=10)
                
                # X축 범위 설정 (전체 거래시간: 09:00~15:30)
                if timeframe == "1min":
                    # 1분봉: 390분 (6.5시간 * 60분)
                    max_index = 389  # 0부터 389까지 = 390분
                else:  # 3min
                    # 3분봉: 130개 캔들 (390분 / 3분)
                    max_index = 129  # 0부터 129까지 = 130개
                
                ax1.set_xlim(-0.5, max_index + 0.5)
                ax2.set_xlim(-0.5, max_index + 0.5)
            
        except Exception as e:
            self.logger.error(f"시간 축 레이블 설정 오류: {e}")
    
    def _set_basic_time_axis_labels(self, ax, data: pd.DataFrame):
        """기본 차트용 X축 시간 레이블 설정 (09:00 ~ 15:30)"""
        try:
            data_len = len(data)
            if data_len == 0:
                return
            
            # 전체 거래시간 데이터 검증 (기본 차트는 1분봉)
            expected_len = 390  # 09:00~15:30 = 6.5시간 * 60분
            if data_len < expected_len:
                self.logger.warning(f"1분봉 데이터 부족: {data_len}/{expected_len}")
            
            # 1분봉 기준으로 설정 (기본 차트는 1분봉 사용)
            interval_minutes = 30  # 30분 간격으로 표시
            
            # 시간 레이블 생성
            time_labels = []
            x_positions = []
            
            # 09:00부터 15:30까지의 시간 레이블 생성
            start_hour = 9
            start_minute = 0
            end_hour = 15
            end_minute = 30
            
            # 전체 거래시간 기준으로 레이블 생성 (09:00 ~ 15:30)
            current_minutes = start_hour * 60 + start_minute  # 09:00 = 540분
            end_minutes = end_hour * 60 + end_minute  # 15:30 = 930분
            
            while current_minutes <= end_minutes:
                hour = current_minutes // 60
                minute = current_minutes % 60
                
                # 1분봉: 분단위 인덱스
                data_index = current_minutes - (start_hour * 60 + start_minute)
                
                # 전체 거래시간 레이블 표시 (데이터 유무와 관계없이)
                time_label = f"{hour:02d}:{minute:02d}"
                time_labels.append(time_label)
                x_positions.append(data_index)
                
                # 다음 시간으로 이동 (30분 간격)
                current_minutes += interval_minutes
            
            # X축 레이블 설정
            if x_positions and time_labels:
                ax.set_xticks(x_positions)
                ax.set_xticklabels(time_labels, rotation=45, fontsize=10)
                
                # X축 범위 설정 (전체 거래시간: 09:00~15:30)
                # 1분봉: 390분 (6.5시간 * 60분)
                max_index = 389  # 0부터 389까지 = 390분
                ax.set_xlim(-0.5, max_index + 0.5)
                
        except Exception as e:
            self.logger.error(f"기본 차트 시간 축 레이블 설정 오류: {e}")
    
    def _create_basic_chart(self, stock_code: str, stock_name: str, 
                           chart_df: pd.DataFrame, target_date: str,
                           selection_reason: str = "") -> Optional[str]:
        """기본 차트 생성 (폴백용)"""
        try:
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
    
    async def create_post_market_candlestick_chart(self, stock_code: str, stock_name: str, 
                                           chart_df: pd.DataFrame, target_date: str,
                                           selection_reason: str = "") -> Optional[str]:
        """
        장 마감 후 캔들스틱 차트 생성 (비동기 래퍼)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            chart_df: 차트 데이터
            target_date: 대상 날짜
            selection_reason: 선정 사유
            
        Returns:
            str: 저장된 파일 경로
        """
        try:
            # 동기 차트 생성을 별도 스레드에서 실행
            result = await asyncio.to_thread(
                self._create_chart_sync, stock_code, stock_name, chart_df, target_date, selection_reason
            )
            return result
        except Exception as e:
            self.logger.error(f"장 마감 후 캔들스틱 차트 생성 오류: {e}")
            return None
    
    async def generate_charts_for_selected_stocks(self, target_date: str = "20250801") -> Dict[str, Any]:
        """
        선정된 종목들의 차트 일괄 생성
        
        Args:
            target_date: 대상 날짜 (YYYYMMDD)
            
        Returns:
            Dict: 생성 결과
        """
        try:
            self.logger.info(f"{target_date} 선정 종목 차트 일괄 생성 시작")
            
            # 조건검색 종목 조회
            selected_stocks = self.get_condition_search_stocks()
            
            if not selected_stocks:
                self.logger.warning("선정된 종목이 없습니다")
                return {'success': False, 'message': '선정된 종목이 없습니다'}
            
            results = {
                'target_date': target_date,
                'total_stocks': len(selected_stocks),
                'success_count': 0,
                'failed_count': 0,
                'chart_files': [],
                'stock_results': []
            }
            
            # 각 종목별 차트 생성
            for stock_data in selected_stocks:
                stock_code = stock_data.get('code', '')
                stock_name = stock_data.get('name', '')
                change_rate = stock_data.get('chgrate', '')
                
                if not stock_code:
                    continue
                
                try:
                    # 분봉 데이터 조회
                    chart_df = await self.get_historical_chart_data(stock_code, target_date)
                    
                    if chart_df is None or chart_df.empty:
                        self.logger.warning(f"⚠️ {stock_code} 데이터 없음")
                        results['stock_results'].append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': False,
                            'error': '데이터 없음'
                        })
                        results['failed_count'] += 1
                        continue
                    
                    # 차트 생성
                    selection_reason = f"조건검색 급등주 (등락률: {change_rate}%)"
                    chart_file = await self.create_post_market_candlestick_chart(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        chart_df=chart_df,
                        target_date=target_date,
                        selection_reason=selection_reason
                    )
                    
                    if chart_file:
                        results['chart_files'].append(chart_file)
                        results['stock_results'].append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': True,
                            'chart_file': chart_file,
                            'data_count': len(chart_df),
                            'change_rate': change_rate
                        })
                        results['success_count'] += 1
                        self.logger.info(f"✅ {stock_code} 차트 생성 성공")
                    else:
                        results['stock_results'].append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': False,
                            'error': '차트 생성 실패'
                        })
                        results['failed_count'] += 1
                        self.logger.error(f"❌ {stock_code} 차트 생성 실패")
                
                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 처리 중 오류: {e}")
                    results['stock_results'].append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'success': False,
                        'error': str(e)
                    })
                    results['failed_count'] += 1
            
            # 결과 요약
            success_rate = f"{results['success_count']}/{results['total_stocks']}"
            results['summary'] = f"차트 생성 완료: {success_rate} ({results['success_count']/results['total_stocks']*100:.1f}%)"
            
            self.logger.info(f"차트 일괄 생성 완료: {results['summary']}")
            return results
            
        except Exception as e:
            self.logger.error(f"차트 일괄 생성 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    async def generate_post_market_charts_for_intraday_stocks(self, intraday_manager, telegram_integration=None) -> Dict[str, Any]:
        """
        장중 선정된 종목들의 장 마감 후 차트 생성 (main.py 로직 통합)
        
        Args:
            intraday_manager: IntradayStockManager 인스턴스
            telegram_integration: 텔레그램 통합 객체 (선택사항)
            
        Returns:
            Dict: 차트 생성 결과
        """
        try:
            current_time = now_kst()
            
            # 장 마감 시간 체크 (15:30 이후)
            market_close_hour = 15
            market_close_minute = 30
            
            if current_time.hour < market_close_hour or (current_time.hour == market_close_hour and current_time.minute < market_close_minute):
                self.logger.debug("아직 장 마감 시간이 아님 - 차트 생성 건너뛰기")
                return {'success': False, 'message': '아직 장 마감 시간이 아님'}
            
            # 주말이나 공휴일 체크
            if current_time.weekday() >= 5:  # 토요일(5), 일요일(6)
                self.logger.debug("주말 - 차트 생성 건너뛰기")
                return {'success': False, 'message': '주말'}
            
            self.logger.info("🎨 장 마감 후 선정 종목 차트 생성 시작")
            
            # 장중 선정된 종목들 조회
            selected_stocks = []
            
            # IntradayStockManager에서 선정된 종목들 가져오기
            summary = intraday_manager.get_all_stocks_summary()
            
            if summary.get('total_stocks', 0) > 0:
                for stock_info in summary.get('stocks', []):
                    stock_code = stock_info.get('stock_code', '')
                    
                    # 종목 상세 정보 조회
                    stock_data = intraday_manager.get_stock_data(stock_code)
                    if stock_data:
                        selected_stocks.append({
                            'code': stock_code,
                            'name': stock_data.stock_name,
                            'chgrate': f"+{stock_info.get('price_change_rate', 0):.1f}",
                            'selection_reason': f"장중 선정 종목 ({stock_data.selected_time.strftime('%H:%M')} 선정)"
                        })
            
            if not selected_stocks:
                self.logger.info("ℹ️ 오늘 선정된 종목이 없어 차트 생성을 건너뜁니다")
                return {'success': False, 'message': '선정된 종목이 없음'}
            
            # 당일 날짜로 차트 생성
            target_date = current_time.strftime("%Y%m%d")
            
            self.logger.info(f"📊 {len(selected_stocks)}개 선정 종목의 {target_date} 차트 생성 중...")
            
            # 각 종목별 차트 생성
            success_count = 0
            chart_files = []
            stock_results = []
            
            for stock_data in selected_stocks:
                stock_code = stock_data.get('code', '')
                stock_name = stock_data.get('name', '')
                selection_reason = stock_data.get('selection_reason', '')
                
                try:
                    self.logger.info(f"📈 {stock_code}({stock_name}) 차트 생성 중...")
                    
                    # 분봉 데이터 조회
                    chart_df = await self.get_historical_chart_data(stock_code, target_date)
                    
                    if chart_df is None or chart_df.empty:
                        self.logger.warning(f"⚠️ {stock_code} 데이터 없음")
                        stock_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': False,
                            'error': '데이터 없음'
                        })
                        continue
                    
                    # 차트 생성
                    chart_file = await self.create_post_market_candlestick_chart(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        chart_df=chart_df,
                        target_date=target_date,
                        selection_reason=selection_reason
                    )
                    
                    if chart_file:
                        chart_files.append(chart_file)
                        success_count += 1
                        stock_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': True,
                            'chart_file': chart_file
                        })
                        self.logger.info(f"✅ {stock_code} 차트 생성 성공: {chart_file}")
                    else:
                        stock_results.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': False,
                            'error': '차트 생성 실패'
                        })
                        self.logger.error(f"❌ {stock_code} 차트 생성 실패")
                
                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 처리 중 오류: {e}")
                    stock_results.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'success': False,
                        'error': str(e)
                    })
            
            # 결과 반환
            total_stocks = len(selected_stocks)
            return {
                'success': success_count > 0,
                'success_count': success_count,
                'total_stocks': total_stocks,
                'chart_files': chart_files,
                'stock_results': stock_results,
                'message': f"차트 생성 완료: {success_count}/{total_stocks}개 성공"
            }
            
        except Exception as e:
            self.logger.error(f"❌ 장 마감 후 차트 생성 오류: {e}")
            return {'success': False, 'error': str(e)}


def main():
    """테스트용 메인 함수"""
    try:
        print("장 마감 후 차트 생성기 테스트")
        generator = PostMarketChartGenerator()
        if generator.initialize():
            print("초기화 성공")
        else:
            print("초기화 실패")
    except Exception as e:
        print(f"메인 실행 오류: {e}")


if __name__ == "__main__":
    main()
