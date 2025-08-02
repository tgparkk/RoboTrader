"""
한국 주식시장 시간에 맞춘 분봉 캔들차트 시각화
장시간: 09:00~15:30 (평일 기준)
"""
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
from datetime import datetime, timedelta, time
import numpy as np
import random
import sys
import os

# 프로젝트 루트 디렉토리를 Python 경로에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_chart_api import (
    get_inquire_time_dailychartprice,
    get_recent_minute_data,
    get_today_minute_data,
    get_realtime_minute_data
)

# 백엔드를 Agg로 설정 (GUI 없이 이미지만 저장)
import matplotlib
matplotlib.use('Agg')

# 폰트 설정
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

logger = setup_logger(__name__)

# 한국 주식시장 거래시간 설정
MARKET_OPEN_TIME = time(9, 0)    # 09:00
MARKET_CLOSE_TIME = time(15, 30) # 15:30
MARKET_MINUTES = 390  # 09:00~15:30 = 6시간 30분 = 390분


def get_latest_trading_day():
    """
    최근 거래일 (평일) 반환
    
    Returns:
        datetime: 최근 거래일
    """
    today = datetime.now()
    
    # 토요일(5) 또는 일요일(6)이면 금요일로 조정
    if today.weekday() == 5:  # 토요일
        return today - timedelta(days=1)
    elif today.weekday() == 6:  # 일요일
        return today - timedelta(days=2)
    else:  # 평일
        return today


def generate_market_minute_data(stock_code: str = "005930", trading_date: datetime = None, base_price: int = 80000):
    """
    실제 장시간(09:00~15:30)에 맞춘 분봉 데이터 생성
    
    Args:
        stock_code: 종목코드
        trading_date: 거래일 (기본값: 최근 거래일)
        base_price: 기준 가격
        
    Returns:
        pd.DataFrame: 장시간 분봉 데이터
    """
    if trading_date is None:
        trading_date = get_latest_trading_day()
    
    print(f"[Market Data] Creating market hours data for {stock_code}")
    print(f"Trading date: {trading_date.strftime('%Y-%m-%d %A')}")
    print(f"Market hours: {MARKET_OPEN_TIME} ~ {MARKET_CLOSE_TIME} ({MARKET_MINUTES} minutes)")
    
    # 거래시간 09:00~15:30 분봉 시간 생성
    market_open = datetime.combine(trading_date.date(), MARKET_OPEN_TIME)
    times = [market_open + timedelta(minutes=i) for i in range(MARKET_MINUTES)]
    
    # 가격 데이터 생성
    prices = []
    current_price = base_price
    
    # 하루 전체 트렌드 설정 (상승/하락/횡보)
    daily_trend = random.choice(['up', 'down', 'sideways'])
    trend_strength = random.uniform(0.5, 2.0)  # 트렌드 강도 (%)
    
    print(f"Daily trend: {daily_trend} (strength: {trend_strength:.1f}%)")
    
    for i, current_time in enumerate(times):
        # 시간대별 특성 반영
        hour = current_time.hour
        minute = current_time.minute
        
        # 장 초반(9-10시): 변동성 큼
        if hour == 9:
            volatility = 0.008  # 0.8%
        # 점심시간 전후(11-13시): 거래량 감소, 변동성 작음
        elif 11 <= hour <= 13:
            volatility = 0.003  # 0.3%
        # 장 마감 전(14-15시): 변동성 증가
        elif hour >= 14:
            volatility = 0.006  # 0.6%
        else:
            volatility = 0.005  # 0.5%
        
        # 일일 트렌드 반영 (더 현실적으로 조정)
        if daily_trend == 'up':
            trend_factor = trend_strength * (i / MARKET_MINUTES) / 1000  # 1000으로 나누어 더 작게
        elif daily_trend == 'down':
            trend_factor = -trend_strength * (i / MARKET_MINUTES) / 1000
        else:  # sideways
            trend_factor = 0
        
        # 가격 변동 계산 (더 현실적으로)
        random_change = random.uniform(-volatility, volatility)
        total_change_rate = trend_factor + random_change
        
        # 가격 변동을 더 작게 제한
        max_change_rate = 0.01  # 최대 1% 변동
        total_change_rate = max(-max_change_rate, min(max_change_rate, total_change_rate))
        
        price_change = int(current_price * total_change_rate)
        current_price = max(1000, current_price + price_change)  # 최소 1000원 보장
        
        # OHLC 데이터 생성
        open_price = current_price
        high_price = open_price + random.randint(0, int(open_price * volatility/2))
        low_price = open_price - random.randint(0, int(open_price * volatility/2))
        close_price = random.randint(low_price, high_price)
        
        # 거래량 생성 (시간대별 특성 반영)
        if hour == 9:  # 장 시작: 거래량 많음
            base_volume = random.randint(10000, 80000)
        elif 11 <= hour <= 13:  # 점심시간: 거래량 적음
            base_volume = random.randint(1000, 20000)
        elif hour >= 14:  # 장 마감 전: 거래량 증가
            base_volume = random.randint(5000, 60000)
        else:
            base_volume = random.randint(3000, 40000)
        
        prices.append({
            'datetime': current_time,
            'date': current_time.strftime('%Y%m%d'),
            'time': current_time.strftime('%H%M%S'),
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': base_volume
        })
        
        current_price = close_price
    
    df = pd.DataFrame(prices)
    
    # 통계 출력
    first_price = df['open'].iloc[0]
    last_price = df['close'].iloc[-1]
    price_change = last_price - first_price
    change_rate = (price_change / first_price * 100)
    
    print(f"[Market Data] Generated {len(df)} minute candles")
    print(f"Price range: {df['low'].min():,} ~ {df['high'].max():,}")
    print(f"Daily change: {price_change:+,.0f} ({change_rate:+.2f}%)")
    print(f"Total volume: {df['volume'].sum():,}")
    
    return df


def create_market_candlestick_chart(df: pd.DataFrame, stock_code: str = "005930", title: str = "Stock Market Hours Chart"):
    """
    장시간에 맞춘 캔들차트 생성
    
    Args:
        df: 분봉 데이터 DataFrame
        stock_code: 종목코드
        title: 차트 제목
    """
    if df is None or df.empty:
        print("[Error] No chart data available")
        return
    
    print(f"[Chart] Creating market hours candlestick chart for {stock_code}")
    
    # 데이터 준비
    chart_df = df.copy()
    
    # 컬럼명 확인 및 표준화
    column_mapping = {
        'stck_prpr': 'close',
        'stck_oprc': 'open', 
        'stck_hgpr': 'high',
        'stck_lwpr': 'low',
        'cntg_vol': 'volume',
        'stck_bsop_date': 'date',
        'stck_cntg_hour': 'time'
    }
    
    # 존재하는 컬럼만 리네임
    for old_col, new_col in column_mapping.items():
        if old_col in chart_df.columns:
            chart_df = chart_df.rename(columns={old_col: new_col})
    
    # 필수 컬럼 확인
    required_columns = ['open', 'high', 'low', 'close']
    missing_columns = [col for col in required_columns if col not in chart_df.columns]
    
    if missing_columns:
        print(f"[Error] Missing required columns: {missing_columns}")
        return
    
    # 데이터 타입 변환
    for col in required_columns:
        chart_df[col] = pd.to_numeric(chart_df[col], errors='coerce')
    
    # NaN 값 제거
    chart_df = chart_df.dropna(subset=required_columns + ['datetime'])
    
    if chart_df.empty:
        print("[Error] No valid data available")
        return
    
    # 시간순 정렬
    chart_df = chart_df.sort_values('datetime').reset_index(drop=True)
    
    print(f"[Chart] Chart data prepared: {len(chart_df)} candles")
    print(f"Time range: {chart_df['datetime'].min().strftime('%H:%M')} ~ {chart_df['datetime'].max().strftime('%H:%M')}")
    
    # 차트 생성
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 12), height_ratios=[3, 1])
    
    # 거래일 정보
    trading_date = chart_df['datetime'].iloc[0].strftime('%Y-%m-%d (%A)')
    
    # 1. 캔들스틱 차트
    ax1.set_title(f'{title} - {stock_code} - {trading_date}', fontsize=16, fontweight='bold')
    
    # 각 캔들에 대해 처리
    for i, row in chart_df.iterrows():
        date = row['datetime']
        open_price = row['open']
        high_price = row['high']
        low_price = row['low']
        close_price = row['close']
        
        # 캔들 색상 결정 (상승: 빨강, 하락: 파랑)
        color = 'red' if close_price >= open_price else 'blue'
        
        # 고가-저가 선 (심지)
        ax1.plot([date, date], [low_price, high_price], color='black', linewidth=0.8)
        
        # 캔들 몸체
        candle_height = abs(close_price - open_price)
        candle_bottom = min(open_price, close_price)
        
        # 캔들 너비
        width = pd.Timedelta(minutes=0.8)
        
        rect = Rectangle((date - width/2, candle_bottom), width, candle_height,
                        facecolor=color, edgecolor='black', alpha=0.7, linewidth=0.3)
        ax1.add_patch(rect)
    
    # 차트 스타일 설정
    ax1.set_ylabel('Price (KRW)', fontsize=12)
    ax1.grid(True, alpha=0.3)
    
    # X축 시간 설정: 09:00~15:30 고정
    start_time = chart_df['datetime'].iloc[0].replace(hour=9, minute=0, second=0)
    end_time = chart_df['datetime'].iloc[0].replace(hour=15, minute=30, second=0)
    ax1.set_xlim(start_time, end_time)
    
    # X축 레이블: 1시간 간격
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax1.xaxis.set_minor_locator(mdates.MinuteLocator(interval=30))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=0, ha='center')
    
    # 장시간 구분선 표시
    lunch_start = start_time.replace(hour=12, minute=0)
    lunch_end = start_time.replace(hour=13, minute=0)
    ax1.axvspan(lunch_start, lunch_end, alpha=0.1, color='gray', label='Lunch Break')
    
    # 가격 범위 설정
    price_range = chart_df[['high', 'low']].max().max() - chart_df[['high', 'low']].min().min()
    padding = price_range * 0.02
    ax1.set_ylim(chart_df['low'].min() - padding, chart_df['high'].max() + padding)
    
    # 2. 거래량 차트
    if 'volume' in chart_df.columns:
        volumes = pd.to_numeric(chart_df['volume'], errors='coerce').fillna(0)
        colors = ['red' if close >= open else 'blue' 
                 for close, open in zip(chart_df['close'], chart_df['open'])]
        
        ax2.bar(chart_df['datetime'], volumes, color=colors, alpha=0.7, width=pd.Timedelta(minutes=0.8))
        ax2.set_ylabel('Volume', fontsize=12)
        ax2.grid(True, alpha=0.3)
        
        # X축 설정 (가격 차트와 동일)
        ax2.set_xlim(start_time, end_time)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax2.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax2.xaxis.set_minor_locator(mdates.MinuteLocator(interval=30))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=0, ha='center')
        
        # 점심시간 표시
        ax2.axvspan(lunch_start, lunch_end, alpha=0.1, color='gray')
    else:
        ax2.text(0.5, 0.5, 'No Volume Data', ha='center', va='center', transform=ax2.transAxes)
        ax2.set_ylabel('Volume', fontsize=12)
    
    ax2.set_xlabel('Market Hours (09:00 ~ 15:30)', fontsize=12)
    
    # 통계 정보 추가
    if len(chart_df) > 0:
        first_price = chart_df['open'].iloc[0]
        last_price = chart_df['close'].iloc[-1]
        high_price = chart_df['high'].max()
        low_price = chart_df['low'].min()
        price_change = last_price - first_price
        change_rate = (price_change / first_price * 100) if first_price > 0 else 0
        
        stats_text = f'Open: {first_price:,.0f} | Close: {last_price:,.0f} | High: {high_price:,.0f} | Low: {low_price:,.0f}\n'
        stats_text += f'Change: {price_change:+,.0f} ({change_rate:+.2f}%) | Volume: {chart_df["volume"].sum():,.0f} | Candles: {len(chart_df)}'
        
        fig.suptitle(stats_text, fontsize=11, y=0.02)
    
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.08)
    
    # 차트 저장
    date_str = chart_df['datetime'].iloc[0].strftime('%Y%m%d')
    filename = f"market_hours_chart_{stock_code}_{date_str}.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"[Saved] Market hours chart saved: {filename}")
    
    # 메모리 정리
    plt.close(fig)
    
    return filename


def main():
    """메인 실행 함수"""
    print("[Start] Market hours candlestick chart test")
    
    # 테스트할 종목코드 (삼성전자)
    stock_code = "005930"
    
    try:
        # 최근 거래일 확인
        trading_day = get_latest_trading_day()
        print(f"\nTrading day: {trading_day.strftime('%Y-%m-%d %A')}")
        
        # 1. API 테스트 (실제 데이터)
        print("\n=== Real API Test ===")
        chart_data = None
        
        # API가 작동한다면 실제 데이터 사용
        try:
            chart_data = get_recent_minute_data(stock_code, minutes=390)  # 전체 장시간
            if chart_data is not None and not chart_data.empty:
                print(f"[Success] Real market data retrieved: {len(chart_data)} records")
        except:
            print("[Info] API not available, using dummy data")
        
        # 2. 더미 데이터로 테스트
        if chart_data is None or chart_data.empty:
            print("\n=== Market Hours Dummy Data Test ===")
            chart_data = generate_market_minute_data(stock_code, trading_day, base_price=80000)
            
            if chart_data is not None and not chart_data.empty:
                print(f"\n[Success] Market hours dummy data generated: {len(chart_data)} records")
                
                # 3. 장시간 캔들차트 생성
                filename = create_market_candlestick_chart(
                    chart_data, 
                    stock_code, 
                    f"Samsung Electronics ({stock_code}) Market Hours"
                )
                
                if filename:
                    print(f"[Complete] Market hours chart created: {filename}")
                    
                    # 분석 결과
                    print("\n=== Market Analysis ===")
                    first_price = chart_data['open'].iloc[0]
                    last_price = chart_data['close'].iloc[-1]
                    high_price = chart_data['high'].max()
                    low_price = chart_data['low'].min()
                    total_volume = chart_data['volume'].sum()
                    
                    price_change = last_price - first_price
                    change_rate = (price_change / first_price * 100)
                    
                    print(f"- Opening: {first_price:,}")
                    print(f"- Closing: {last_price:,}")
                    print(f"- High: {high_price:,}")
                    print(f"- Low: {low_price:,}")
                    print(f"- Daily change: {price_change:+,.0f} ({change_rate:+.2f}%)")
                    print(f"- Total volume: {total_volume:,}")
                    print(f"- Trading hours: 09:00 ~ 15:30 ({MARKET_MINUTES} minutes)")
                    
                    # 시간대별 거래량 분석
                    chart_data['hour'] = chart_data['datetime'].dt.hour
                    hourly_volume = chart_data.groupby('hour')['volume'].sum()
                    print("\n- Hourly volume:")
                    for hour, vol in hourly_volume.items():
                        print(f"  {hour:02d}:00 ~ {hour:02d}:59: {vol:,}")
                        
                else:
                    print("[Failed] Market hours chart creation failed")
            else:
                print("[Failed] Market hours dummy data generation failed")
            
    except Exception as e:
        print(f"Error occurred: {e}")


if __name__ == "__main__":
    main()