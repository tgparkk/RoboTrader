#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
손절/익절 거래 분석 스크립트
로그 파일에서 거래 정보를 추출하고 기술적 지표를 계산하여 차이점을 분석합니다.
"""

import os
import re
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import matplotlib.pyplot as plt
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

@dataclass
class TradeInfo:
    """거래 정보를 저장하는 클래스"""
    stock_code: str
    date: str
    buy_time: str
    sell_time: str
    buy_price: float
    sell_price: float
    profit_pct: float
    trade_type: str  # 'profit' or 'loss'
    holding_minutes: int

class TechnicalIndicators:
    """기술적 지표 계산 클래스"""
    
    @staticmethod
    def sma(data: pd.Series, period: int) -> pd.Series:
        """단순이동평균"""
        return data.rolling(window=period).mean()
    
    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        """지수이동평균"""
        return data.ewm(span=period).mean()
    
    @staticmethod
    def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD 지표"""
        ema_fast = TechnicalIndicators.ema(data, fast)
        ema_slow = TechnicalIndicators.ema(data, slow)
        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        """RSI 지표"""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """볼린저 밴드"""
        sma = TechnicalIndicators.sma(data, period)
        std = data.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower
    
    @staticmethod
    def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """스토캐스틱 지표"""
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
        d_percent = k_percent.rolling(window=d_period).mean()
        return k_percent, d_percent
    
    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Average True Range"""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
    
    @staticmethod
    def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
        """거래량 이동평균"""
        return volume.rolling(window=period).mean()

class TradeAnalyzer:
    """거래 분석 클래스"""
    
    def __init__(self, log_dir: str, cache_dir: str):
        self.log_dir = log_dir
        self.cache_dir = cache_dir
        self.trades: List[TradeInfo] = []
        self.indicators_data: Dict[str, pd.DataFrame] = {}
        
    def parse_log_files(self) -> List[TradeInfo]:
        """로그 파일들을 파싱하여 거래 정보를 추출"""
        trades = []
        
        # 로그 파일 목록 가져오기
        log_files = [f for f in os.listdir(self.log_dir) if f.endswith('.txt')]
        
        for log_file in log_files:
            print(f"파싱 중: {log_file}")
            file_path = os.path.join(self.log_dir, log_file)
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 날짜 추출 (파일명에서)
            date_match = re.search(r'(\d{8})', log_file)
            if not date_match:
                continue
            date = date_match.group(1)
            
            # 종목별로 섹션 분리
            sections = re.split(r'^=== \d{6} - \d{8}', content, flags=re.MULTILINE)
            
            for i, section in enumerate(sections):
                if '체결 시뮬레이션:' in section:
                    print(f"체결 시뮬레이션 섹션 발견! (섹션 {i})")
                    # 거래 정보 추출
                    trade_lines = re.findall(
                        r'(\d{2}:\d{2})\s+매수.*?@([0-9,]+).*?(\d{2}:\d{2})\s+매도.*?@([0-9,]+).*?([+-][0-9.]+%)',
                        section
                    )
                    print(f"거래 라인 수: {len(trade_lines)}")
                    
                    # 종목 코드 추출 (섹션 내용에서 직접 찾기)
                    stock_code_match = re.search(r'=== (\d{6}) - \d{8}', section)
                    if not stock_code_match:
                        # 섹션에 종목 코드가 없으면 이전 섹션에서 찾기
                        if i > 0:
                            prev_section = sections[i-1]
                            stock_code_match = re.search(r'=== (\d{6}) - \d{8}', prev_section)
                            if not stock_code_match:
                                continue
                            stock_code = stock_code_match.group(1)
                        else:
                            # 첫 번째 섹션의 경우 전체 내용에서 찾기
                            stock_code_match = re.search(r'=== (\d{6}) - \d{8}', content)
                            if not stock_code_match:
                                continue
                            stock_code = stock_code_match.group(1)
                    else:
                        stock_code = stock_code_match.group(1)
                    
                    for trade in trade_lines:
                        print(f"거래 처리 중: {trade}")
                        buy_time, buy_price_str, sell_time, sell_price_str, profit_pct_str = trade
                        
                        # 가격에서 콤마 제거
                        buy_price = float(buy_price_str.replace(',', ''))
                        sell_price = float(sell_price_str.replace(',', ''))
                        profit_pct = float(profit_pct_str.replace('%', '').replace('+', ''))
                        
                        # 거래 유형 결정 (수익률에 따라)
                        trade_type_str = 'profit' if profit_pct > 0 else 'loss'
                        
                        # 보유 시간 계산
                        buy_dt = datetime.strptime(f"{date} {buy_time}", "%Y%m%d %H:%M")
                        sell_dt = datetime.strptime(f"{date} {sell_time}", "%Y%m%d %H:%M")
                        holding_minutes = int((sell_dt - buy_dt).total_seconds() / 60)
                        
                        trade_info = TradeInfo(
                            stock_code=stock_code,
                            date=date,
                            buy_time=buy_time,
                            sell_time=sell_time,
                            buy_price=buy_price,
                            sell_price=sell_price,
                            profit_pct=profit_pct,
                            trade_type=trade_type_str,
                            holding_minutes=holding_minutes
                        )
                        trades.append(trade_info)
                        print(f"거래 추가됨: {stock_code} {buy_time} -> {sell_time} {profit_pct}%")
        
        self.trades = trades
        print(f"총 {len(trades)}개의 거래를 추출했습니다.")
        return trades
    
    def load_ohlcv_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """특정 종목의 OHLCV 데이터 로드"""
        cache_file = os.path.join(self.cache_dir, f"{stock_code}_{date}.pkl")
        
        if not os.path.exists(cache_file):
            return None
        
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            
            # 데이터가 DataFrame인지 확인
            if isinstance(data, pd.DataFrame):
                return data
            else:
                # 다른 형태의 데이터라면 변환 시도
                return pd.DataFrame(data)
                
        except Exception as e:
            print(f"데이터 로드 실패 {cache_file}: {e}")
            return None
    
    def calculate_indicators_at_trade(self, stock_code: str, date: str, trade_time: str) -> Dict:
        """거래 시점에서의 기술적 지표 계산"""
        ohlcv_data = self.load_ohlcv_data(stock_code, date)
        
        if ohlcv_data is None or ohlcv_data.empty:
            return {}
        
        # 컬럼명 정규화
        if 'time' in ohlcv_data.columns:
            time_col = 'time'
        elif 'datetime' in ohlcv_data.columns:
            time_col = 'datetime'
        else:
            time_col = ohlcv_data.columns[0]
        
        # 시간 컬럼을 datetime으로 변환
        ohlcv_data[time_col] = pd.to_datetime(ohlcv_data[time_col])
        
        # 거래 시간과 가장 가까운 시점 찾기
        trade_datetime = pd.to_datetime(f"{date} {trade_time}", format="%Y%m%d %H:%M")
        
        # 거래 시간 이전의 데이터만 사용 (미래 데이터 사용 방지)
        historical_data = ohlcv_data[ohlcv_data[time_col] <= trade_datetime].copy()
        
        if historical_data.empty or len(historical_data) < 50:
            return {}
        
        # 가격 데이터 추출
        close_prices = historical_data['close'] if 'close' in historical_data.columns else historical_data.iloc[:, -1]
        
        # OHLC 데이터 추출
        high_prices = historical_data['high'] if 'high' in historical_data.columns else close_prices
        low_prices = historical_data['low'] if 'low' in historical_data.columns else close_prices
        volume = historical_data['volume'] if 'volume' in historical_data.columns else pd.Series([1] * len(historical_data))
        
        indicators = {}
        
        try:
            # MACD
            macd_line, signal_line, histogram = TechnicalIndicators.macd(close_prices)
            indicators['macd'] = macd_line.iloc[-1] if not pd.isna(macd_line.iloc[-1]) else 0
            indicators['macd_signal'] = signal_line.iloc[-1] if not pd.isna(signal_line.iloc[-1]) else 0
            indicators['macd_histogram'] = histogram.iloc[-1] if not pd.isna(histogram.iloc[-1]) else 0
            
            # RSI
            rsi = TechnicalIndicators.rsi(close_prices)
            indicators['rsi'] = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
            
            # 볼린저 밴드
            bb_upper, bb_middle, bb_lower = TechnicalIndicators.bollinger_bands(close_prices)
            current_price = close_prices.iloc[-1]
            bb_position = (current_price - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1])
            indicators['bb_position'] = bb_position if not pd.isna(bb_position) else 0.5
            
            # 스토캐스틱
            stoch_k, stoch_d = TechnicalIndicators.stochastic(high_prices, low_prices, close_prices)
            indicators['stoch_k'] = stoch_k.iloc[-1] if not pd.isna(stoch_k.iloc[-1]) else 50
            indicators['stoch_d'] = stoch_d.iloc[-1] if not pd.isna(stoch_d.iloc[-1]) else 50
            
            # 이동평균
            sma_5 = TechnicalIndicators.sma(close_prices, 5)
            sma_20 = TechnicalIndicators.sma(close_prices, 20)
            indicators['sma_5'] = sma_5.iloc[-1] if not pd.isna(sma_5.iloc[-1]) else current_price
            indicators['sma_20'] = sma_20.iloc[-1] if not pd.isna(sma_20.iloc[-1]) else current_price
            indicators['price_vs_sma20'] = (current_price - sma_20.iloc[-1]) / sma_20.iloc[-1] * 100
            
            # ATR
            atr = TechnicalIndicators.atr(high_prices, low_prices, close_prices)
            indicators['atr'] = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0
            
            # 거래량 분석
            volume_sma = TechnicalIndicators.volume_sma(volume)
            indicators['volume_ratio'] = volume.iloc[-1] / volume_sma.iloc[-1] if volume_sma.iloc[-1] > 0 else 1
            
            # 가격 변동성
            price_change = close_prices.pct_change()
            indicators['volatility'] = price_change.rolling(20).std().iloc[-1] * 100 if not pd.isna(price_change.rolling(20).std().iloc[-1]) else 0
            
        except Exception as e:
            print(f"지표 계산 오류 {stock_code} {date} {trade_time}: {e}")
            return {}
        
        return indicators
    
    def analyze_trades(self):
        """거래 분석 실행"""
        if not self.trades:
            self.parse_log_files()
        
        print("기술적 지표 계산 중...")
        
        # 각 거래에 대해 지표 계산
        trade_data = []
        
        for i, trade in enumerate(self.trades):
            if i % 10 == 0:
                print(f"진행률: {i}/{len(self.trades)}")
            
            indicators = self.calculate_indicators_at_trade(trade.stock_code, trade.date, trade.buy_time)
            
            if indicators:
                trade_record = {
                    'stock_code': trade.stock_code,
                    'date': trade.date,
                    'buy_time': trade.buy_time,
                    'sell_time': trade.sell_time,
                    'buy_price': trade.buy_price,
                    'sell_price': trade.sell_price,
                    'profit_pct': trade.profit_pct,
                    'trade_type': trade.trade_type,
                    'holding_minutes': trade.holding_minutes,
                    **indicators
                }
                trade_data.append(trade_record)
        
        self.trade_df = pd.DataFrame(trade_data)
        print(f"분석 완료: {len(trade_data)}개 거래 데이터")
        
        return self.trade_df
    
    def create_comparison_report(self):
        """손절/익절 거래 비교 리포트 생성"""
        if not hasattr(self, 'trade_df') or self.trade_df.empty:
            print("분석 데이터가 없습니다. 먼저 analyze_trades()를 실행하세요.")
            return
        
        df = self.trade_df
        
        # 손절/익절 분리
        profit_trades = df[df['trade_type'] == 'profit']
        loss_trades = df[df['trade_type'] == 'loss']
        
        print(f"\n=== 거래 현황 ===")
        print(f"총 거래 수: {len(df)}")
        print(f"익절 거래: {len(profit_trades)} ({len(profit_trades)/len(df)*100:.1f}%)")
        print(f"손절 거래: {len(loss_trades)} ({len(loss_trades)/len(df)*100:.1f}%)")
        
        # 기술적 지표 비교
        indicator_columns = ['macd', 'macd_signal', 'macd_histogram', 'rsi', 'bb_position', 
                           'stoch_k', 'stoch_d', 'sma_5', 'sma_20', 'price_vs_sma20', 
                           'atr', 'volume_ratio', 'volatility']
        
        comparison_data = []
        
        for indicator in indicator_columns:
            if indicator in df.columns:
                profit_mean = profit_trades[indicator].mean()
                loss_mean = loss_trades[indicator].mean()
                difference = profit_mean - loss_mean
                
                comparison_data.append({
                    'indicator': indicator,
                    'profit_mean': profit_mean,
                    'loss_mean': loss_mean,
                    'difference': difference,
                    'profit_std': profit_trades[indicator].std(),
                    'loss_std': loss_trades[indicator].std()
                })
        
        comparison_df = pd.DataFrame(comparison_data)
        
        print(f"\n=== 기술적 지표 비교 ===")
        print(comparison_df.round(4))
        
        # 시각화
        self.create_comparison_charts(comparison_df)
        
        return comparison_df
    
    def create_comparison_charts(self, comparison_df):
        """비교 차트 생성"""
        # 한글 폰트 설정
        plt.rcParams['font.family'] = 'Malgun Gothic'
        plt.rcParams['axes.unicode_minus'] = False
        
        # 지표별 비교 차트
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        fig.suptitle('손절 vs 익절 거래 - 기술적 지표 비교', fontsize=16)
        
        # 1. 주요 지표 비교 (막대 차트)
        ax1 = axes[0, 0]
        main_indicators = ['macd', 'rsi', 'bb_position', 'stoch_k']
        x_pos = np.arange(len(main_indicators))
        width = 0.35
        
        profit_values = [comparison_df[comparison_df['indicator'] == ind]['profit_mean'].iloc[0] 
                        for ind in main_indicators if len(comparison_df[comparison_df['indicator'] == ind]) > 0]
        loss_values = [comparison_df[comparison_df['indicator'] == ind]['loss_mean'].iloc[0] 
                      for ind in main_indicators if len(comparison_df[comparison_df['indicator'] == ind]) > 0]
        
        ax1.bar(x_pos - width/2, profit_values, width, label='익절', alpha=0.8)
        ax1.bar(x_pos + width/2, loss_values, width, label='손절', alpha=0.8)
        ax1.set_xlabel('지표')
        ax1.set_ylabel('평균값')
        ax1.set_title('주요 지표 평균값 비교')
        ax1.set_xticks(x_pos)
        ax1.set_xticklabels(main_indicators, rotation=45)
        ax1.legend()
        
        # 2. RSI 분포
        ax2 = axes[0, 1]
        df = self.trade_df
        profit_rsi = df[df['trade_type'] == 'profit']['rsi']
        loss_rsi = df[df['trade_type'] == 'loss']['rsi']
        
        ax2.hist(profit_rsi, bins=20, alpha=0.7, label='익절', density=True)
        ax2.hist(loss_rsi, bins=20, alpha=0.7, label='손절', density=True)
        ax2.set_xlabel('RSI')
        ax2.set_ylabel('밀도')
        ax2.set_title('RSI 분포 비교')
        ax2.legend()
        
        # 3. 보유 시간 비교
        ax3 = axes[1, 0]
        profit_holding = df[df['trade_type'] == 'profit']['holding_minutes']
        loss_holding = df[df['trade_type'] == 'loss']['holding_minutes']
        
        ax3.boxplot([profit_holding, loss_holding], labels=['익절', '손절'])
        ax3.set_ylabel('보유 시간 (분)')
        ax3.set_title('보유 시간 비교')
        
        # 4. 거래량 비율 비교
        ax4 = axes[1, 1]
        profit_volume = df[df['trade_type'] == 'profit']['volume_ratio']
        loss_volume = df[df['trade_type'] == 'loss']['volume_ratio']
        
        ax4.boxplot([profit_volume, loss_volume], labels=['익절', '손절'])
        ax4.set_ylabel('거래량 비율')
        ax4.set_title('거래량 비율 비교')
        
        plt.tight_layout()
        plt.savefig('trade_comparison_analysis.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        print("\n차트가 'trade_comparison_analysis.png'로 저장되었습니다.")

def main():
    """메인 실행 함수"""
    log_dir = r"C:\GIT\RoboTrader\새 폴더 (2)"
    cache_dir = r"C:\GIT\RoboTrader\cache\minute_data"
    
    analyzer = TradeAnalyzer(log_dir, cache_dir)
    
    # 거래 분석 실행
    trade_df = analyzer.analyze_trades()
    
    if not trade_df.empty:
        # 비교 리포트 생성
        comparison_df = analyzer.create_comparison_report()
        
        # 결과 저장
        trade_df.to_csv('trade_analysis_results.csv', index=False, encoding='utf-8-sig')
        comparison_df.to_csv('indicator_comparison.csv', index=False, encoding='utf-8-sig')
        
        print("\n분석 결과가 다음 파일로 저장되었습니다:")
        print("- trade_analysis_results.csv: 전체 거래 분석 결과")
        print("- indicator_comparison.csv: 지표별 비교 결과")
        print("- trade_comparison_analysis.png: 시각화 차트")
    else:
        print("분석할 데이터가 없습니다.")

if __name__ == "__main__":
    main()
