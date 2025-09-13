#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
간단한 손절/익절 거래 분석 스크립트
이미 grep으로 찾은 거래 정보를 기반으로 분석합니다.
"""

import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# 손절/익절 거래 정보 (grep 결과에서 추출)
TRADE_DATA = [
    # 20250901
    ("007820", "20250901", "13:33", "13:47", 4773, 4630, -3.00, "loss"),
    ("054540", "20250901", "10:09", "14:04", 12418, 12045, -3.00, "loss"),
    ("064820", "20250901", "09:45", "10:09", 9902, 9605, -3.00, "loss"),
    ("092870", "20250901", "11:18", "13:21", 3644, 3535, -3.00, "loss"),
    ("234340", "20250901", "11:51", "12:14", 9284, 9563, 3.00, "profit"),
    ("234340", "20250901", "14:03", "14:05", 9518, 9804, 3.00, "profit"),
    ("234340", "20250901", "14:06", "14:31", 9694, 9985, 3.00, "profit"),
    ("234340", "20250901", "14:33", "14:34", 10002, 9702, -3.00, "loss"),
    ("356860", "20250901", "11:12", "13:11", 176140, 170856, -3.00, "loss"),
    ("456160", "20250901", "09:57", "10:26", 6068, 6250, 3.00, "profit"),
    ("456160", "20250901", "10:27", "13:22", 6232, 6045, -3.00, "loss"),
    ("476060", "20250901", "10:03", "11:15", 4865, 4719, -3.00, "loss"),
    ("484810", "20250901", "11:54", "12:22", 1794, 1740, -3.00, "loss"),
    ("095610", "20250901", "12:57", "12:59", 6342, 6532, 3.00, "profit"),
    ("095610", "20250901", "13:00", "13:03", 6476, 6670, 3.00, "profit"),
    ("095610", "20250901", "13:12", "14:51", 6686, 6485, -3.00, "loss"),
    ("214370", "20250901", "13:57", "14:09", 53980, 55599, 3.00, "profit"),
    ("214370", "20250901", "14:09", "14:10", 54780, 56423, 3.00, "profit"),
    ("214370", "20250901", "14:42", "14:52", 58000, 59740, 3.00, "profit"),
    ("214370", "20250901", "14:54", "15:00", 60600, 59800, -1.32, "loss"),
    ("382900", "20250901", "13:09", "13:37", 29470, 28586, -3.00, "loss"),
    ("382900", "20250901", "13:51", "15:00", 28780, 27950, -2.88, "loss"),
    
    # 20250902 - 더 많은 거래 데이터 추가
    ("006800", "20250902", "09:24", "10:04", 10810, 10486, -3.00, "loss"),
    ("006800", "20250902", "12:15", "12:25", 10758, 11081, 3.00, "profit"),
    ("006800", "20250902", "12:27", "12:34", 11106, 11439, 3.00, "profit"),
    ("006800", "20250902", "12:36", "15:00", 11410, 11470, 0.53, "profit"),
    ("054540", "20250902", "10:21", "11:39", 28500, 27645, -3.00, "loss"),
    ("064820", "20250902", "09:39", "09:46", 65740, 67712, 3.00, "profit"),
    ("064820", "20250902", "09:48", "10:02", 67520, 65494, -3.00, "loss"),
    ("090710", "20250902", "09:45", "11:06", 7078, 6866, -3.00, "loss"),
    ("092460", "20250902", "12:30", "13:27", 83220, 80723, -3.00, "loss"),
    ("097230", "20250902", "10:03", "10:04", 5748, 5920, 3.00, "profit"),
    ("097230", "20250902", "10:06", "10:13", 5874, 5698, -3.00, "loss"),
    ("156100", "20250902", "13:39", "15:00", 27710, 27550, -0.58, "loss"),
    ("177350", "20250902", "09:57", "12:02", 4361, 4230, -3.00, "loss"),
    ("234030", "20250902", "09:42", "15:00", 4720, 4650, -1.48, "loss"),
    ("234340", "20250902", "14:21", "15:00", 12774, 12760, -0.11, "loss"),
    ("319400", "20250902", "09:57", "10:04", 1567, 1614, 3.00, "profit"),
    ("319400", "20250902", "10:06", "10:33", 1606, 1558, -3.00, "loss"),
    ("332570", "20250902", "10:03", "10:05", 2885, 2972, 3.00, "profit"),
    ("332570", "20250902", "10:06", "10:07", 3018, 3109, 3.00, "profit"),
    ("332570", "20250902", "10:09", "10:11", 3198, 3294, 3.00, "profit"),
    ("332570", "20250902", "10:18", "10:52", 3356, 3255, -3.00, "loss"),
    ("332570", "20250902", "11:03", "12:55", 3319, 3219, -3.00, "loss"),
    ("456160", "20250902", "11:15", "12:33", 3039, 2948, -3.00, "loss"),
]

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
    def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
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
    def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2) -> tuple:
        """볼린저 밴드"""
        sma = TechnicalIndicators.sma(data, period)
        std = data.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower
    
    @staticmethod
    def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> tuple:
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
    
    def __init__(self, minute_cache_dir: str, daily_cache_dir: str):
        self.minute_cache_dir = minute_cache_dir
        self.daily_cache_dir = daily_cache_dir
        self.trade_data = TRADE_DATA
        
    def load_ohlcv_data(self, stock_code: str, date: str, days_back: int = 30):
        """특정 종목의 OHLCV 데이터 로드 (여러 날짜 포함)"""
        all_data = []
        
        # 거래 날짜부터 역순으로 여러 날짜의 데이터 로드
        trade_date = datetime.strptime(date, "%Y%m%d")
        
        for i in range(days_back):
            check_date = trade_date - timedelta(days=i)
            date_str = check_date.strftime("%Y%m%d")
            cache_file = os.path.join(self.minute_cache_dir, f"{stock_code}_{date_str}.pkl")
            
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'rb') as f:
                        data = pickle.load(f)
                    
                    if isinstance(data, pd.DataFrame) and not data.empty:
                        all_data.append(data)
                        
                except Exception as e:
                    print(f"데이터 로드 실패 {cache_file}: {e}")
                    continue
        
        if not all_data:
            return None
        
        # 모든 데이터를 합치고 날짜순으로 정렬
        combined_data = pd.concat(all_data, ignore_index=True)
        combined_data = combined_data.sort_values('datetime').reset_index(drop=True)
        
        return combined_data
    
    def load_daily_data(self, stock_code: str):
        """생성된 일봉 데이터 로드"""
        daily_file = os.path.join(self.daily_cache_dir, f"{stock_code}_daily.pkl")
        
        if not os.path.exists(daily_file):
            return None
        
        try:
            with open(daily_file, 'rb') as f:
                data = pickle.load(f)
            return data
        except Exception as e:
            print(f"일봉 데이터 로드 실패 {daily_file}: {e}")
            return None
    
    def convert_to_daily_data(self, minute_data):
        """분봉 데이터를 일봉 데이터로 변환"""
        if minute_data.empty:
            return minute_data
        
        # datetime을 기준으로 일별 그룹화
        minute_data['date_only'] = minute_data['datetime_converted'].dt.date
        
        # 일봉 데이터 생성
        daily_data = minute_data.groupby('date_only').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'amount': 'sum'
        }).reset_index()
        
        # datetime 컬럼 추가
        daily_data['datetime_converted'] = pd.to_datetime(daily_data['date_only'])
        
        return daily_data.sort_values('datetime_converted').reset_index(drop=True)
    
    def calculate_indicators_at_trade(self, stock_code: str, date: str, trade_time: str):
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
        if time_col == 'time':
            # time 컬럼이 '090000' 형태인 경우
            ohlcv_data['datetime_converted'] = pd.to_datetime(ohlcv_data['date'].astype(str) + ohlcv_data['time'].astype(str), format='%Y%m%d%H%M%S')
        else:
            ohlcv_data['datetime_converted'] = pd.to_datetime(ohlcv_data[time_col])
        
        # 거래 시간과 가장 가까운 시점 찾기
        trade_datetime = pd.to_datetime(f"{date} {trade_time}", format="%Y%m%d %H:%M")
        
        # 일봉 데이터 로드 (장기 지표용)
        daily_data = self.load_daily_data(stock_code)
        
        # 거래 시간 이전의 분봉 데이터만 사용 (단기 지표용)
        historical_minute_data = ohlcv_data[ohlcv_data['datetime_converted'] <= trade_datetime].copy()
        
        # 거래 날짜 이전의 일봉 데이터만 사용
        trade_date_str = trade_datetime.strftime('%Y%m%d')
        historical_daily_data = daily_data[daily_data['date'] <= trade_date_str].copy()
        
        # 최소 데이터 포인트 확인
        if historical_minute_data.empty or len(historical_minute_data) < 50:
            print(f"분봉 데이터 부족: {stock_code} {date} {trade_time} - {len(historical_minute_data)}개 데이터")
            return {}
        
        if historical_daily_data.empty or len(historical_daily_data) < 2:
            print(f"일봉 데이터 부족: {stock_code} {date} {trade_time} - {len(historical_daily_data)}개 데이터")
            return {}
        
        # 분봉 가격 데이터 추출 (단기 지표용)
        minute_close = historical_minute_data['close']
        minute_high = historical_minute_data['high']
        minute_low = historical_minute_data['low']
        minute_volume = historical_minute_data['volume']
        
        # 일봉 가격 데이터 추출 (장기 지표용)
        daily_close = historical_daily_data['close']
        daily_high = historical_daily_data['high']
        daily_low = historical_daily_data['low']
        daily_volume = historical_daily_data['volume']
        
        indicators = {}
        
        try:
            current_price = minute_close.iloc[-1]
            
            # 장기 지표 (일봉 데이터 사용)
            # MACD (일봉)
            macd_line, signal_line, histogram = TechnicalIndicators.macd(daily_close)
            indicators['macd'] = macd_line.iloc[-1] if not pd.isna(macd_line.iloc[-1]) else 0
            indicators['macd_signal'] = signal_line.iloc[-1] if not pd.isna(signal_line.iloc[-1]) else 0
            indicators['macd_histogram'] = histogram.iloc[-1] if not pd.isna(histogram.iloc[-1]) else 0
            
            # RSI (일봉)
            rsi = TechnicalIndicators.rsi(daily_close)
            indicators['rsi'] = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
            
            # 볼린저 밴드 (일봉)
            bb_upper, bb_middle, bb_lower = TechnicalIndicators.bollinger_bands(daily_close)
            bb_position = (current_price - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1])
            indicators['bb_position'] = bb_position if not pd.isna(bb_position) else 0.5
            
            # 스토캐스틱 (일봉)
            stoch_k, stoch_d = TechnicalIndicators.stochastic(daily_high, daily_low, daily_close)
            indicators['stoch_k'] = stoch_k.iloc[-1] if not pd.isna(stoch_k.iloc[-1]) else 50
            indicators['stoch_d'] = stoch_d.iloc[-1] if not pd.isna(stoch_d.iloc[-1]) else 50
            
            # 이동평균 (일봉) - 데이터가 부족할 때 처리
            if len(daily_close) >= 5:
                sma_5 = TechnicalIndicators.sma(daily_close, 5)
                indicators['sma_5'] = sma_5.iloc[-1] if not pd.isna(sma_5.iloc[-1]) else current_price
            else:
                indicators['sma_5'] = current_price
            
            if len(daily_close) >= 20:
                sma_20 = TechnicalIndicators.sma(daily_close, 20)
                indicators['sma_20'] = sma_20.iloc[-1] if not pd.isna(sma_20.iloc[-1]) else current_price
                indicators['price_vs_sma20'] = (current_price - sma_20.iloc[-1]) / sma_20.iloc[-1] * 100
            else:
                indicators['sma_20'] = current_price
                indicators['price_vs_sma20'] = 0
            
            # ATR (일봉)
            atr = TechnicalIndicators.atr(daily_high, daily_low, daily_close)
            indicators['atr'] = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0
            
            # 단기 지표 (분봉 데이터 사용)
            # 단기 RSI (분봉)
            minute_rsi = TechnicalIndicators.rsi(minute_close, period=14)
            indicators['minute_rsi'] = minute_rsi.iloc[-1] if not pd.isna(minute_rsi.iloc[-1]) else 50
            
            # 단기 이동평균 (분봉)
            minute_sma_20 = TechnicalIndicators.sma(minute_close, 20)
            indicators['minute_sma_20'] = minute_sma_20.iloc[-1] if not pd.isna(minute_sma_20.iloc[-1]) else current_price
            indicators['price_vs_minute_sma20'] = (current_price - minute_sma_20.iloc[-1]) / minute_sma_20.iloc[-1] * 100
            
            # 거래량 분석 (분봉)
            volume_sma = TechnicalIndicators.volume_sma(minute_volume, 20)
            indicators['volume_ratio'] = minute_volume.iloc[-1] / volume_sma.iloc[-1] if volume_sma.iloc[-1] > 0 else 1
            
            # 가격 변동성 (분봉)
            price_change = minute_close.pct_change()
            indicators['volatility'] = price_change.rolling(20).std().iloc[-1] * 100 if not pd.isna(price_change.rolling(20).std().iloc[-1]) else 0
            
            # 추가 지표들
            # 가격 모멘텀 (최근 5일 대비)
            if len(daily_close) >= 5:
                indicators['price_momentum_5d'] = (daily_close.iloc[-1] - daily_close.iloc[-6]) / daily_close.iloc[-6] * 100
            else:
                indicators['price_momentum_5d'] = 0
            
            # 거래량 모멘텀 (최근 5일 평균 대비)
            if len(daily_volume) >= 5:
                recent_volume_avg = daily_volume.tail(5).mean()
                past_volume_avg = daily_volume.tail(10).head(5).mean()
                indicators['volume_momentum'] = (recent_volume_avg - past_volume_avg) / past_volume_avg * 100 if past_volume_avg > 0 else 0
            else:
                indicators['volume_momentum'] = 0
            
        except Exception as e:
            print(f"지표 계산 오류 {stock_code} {date} {trade_time}: {e}")
            return {}
        
        return indicators
    
    def analyze_trades(self):
        """거래 분석 실행"""
        print("기술적 지표 계산 중...")
        
        # 각 거래에 대해 지표 계산
        trade_data = []
        
        for i, (stock_code, date, buy_time, sell_time, buy_price, sell_price, profit_pct, trade_type) in enumerate(self.trade_data):
            if i % 5 == 0:
                print(f"진행률: {i}/{len(self.trade_data)}")
            
            indicators = self.calculate_indicators_at_trade(stock_code, date, buy_time)
            
            if indicators:
                # 보유 시간 계산
                buy_dt = datetime.strptime(f"{date} {buy_time}", "%Y%m%d %H:%M")
                sell_dt = datetime.strptime(f"{date} {sell_time}", "%Y%m%d %H:%M")
                holding_minutes = int((sell_dt - buy_dt).total_seconds() / 60)
                
                trade_record = {
                    'stock_code': stock_code,
                    'date': date,
                    'buy_time': buy_time,
                    'sell_time': sell_time,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'profit_pct': profit_pct,
                    'trade_type': trade_type,
                    'holding_minutes': holding_minutes,
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
                           'atr', 'volume_ratio', 'volatility', 'minute_rsi', 
                           'price_vs_minute_sma20', 'price_momentum_5d', 'volume_momentum']
        
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
        
        profit_values = []
        loss_values = []
        for ind in main_indicators:
            row = comparison_df[comparison_df['indicator'] == ind]
            if not row.empty:
                profit_values.append(row['profit_mean'].iloc[0])
                loss_values.append(row['loss_mean'].iloc[0])
            else:
                profit_values.append(0)
                loss_values.append(0)
        
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
    minute_cache_dir = r"C:\GIT\RoboTrader\cache\minute_data"
    daily_cache_dir = r"C:\GIT\RoboTrader\cache\daily_data"
    
    analyzer = TradeAnalyzer(minute_cache_dir, daily_cache_dir)
    
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
        
        # 주요 인사이트 도출
        print("\n=== 주요 인사이트 ===")
        profit_trades = trade_df[trade_df['trade_type'] == 'profit']
        loss_trades = trade_df[trade_df['trade_type'] == 'loss']
        
        if not profit_trades.empty and not loss_trades.empty:
            print(f"1. RSI 차이: 익절 평균 {profit_trades['rsi'].mean():.1f} vs 손절 평균 {loss_trades['rsi'].mean():.1f}")
            print(f"2. 보유시간 차이: 익절 평균 {profit_trades['holding_minutes'].mean():.1f}분 vs 손절 평균 {loss_trades['holding_minutes'].mean():.1f}분")
            print(f"3. 거래량 비율 차이: 익절 평균 {profit_trades['volume_ratio'].mean():.2f} vs 손절 평균 {loss_trades['volume_ratio'].mean():.2f}")
            print(f"4. 볼린저밴드 위치 차이: 익절 평균 {profit_trades['bb_position'].mean():.3f} vs 손절 평균 {loss_trades['bb_position'].mean():.3f}")
    else:
        print("분석할 데이터가 없습니다.")

if __name__ == "__main__":
    main()
