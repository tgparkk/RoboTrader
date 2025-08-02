"""
분봉조회 API 테스트 및 캔들차트 시각화 (최종 버전)
"""
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
from datetime import datetime, timedelta
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

# 폰트 설정 (영어만 사용)
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

logger = setup_logger(__name__)


def generate_dummy_minute_data(stock_code: str = "005930", minutes: int = 60, base_price: int = 80000):
    """
    테스트용 더미 분봉 데이터 생성
    
    Args:
        stock_code: 종목코드
        minutes: 생성할 분봉 개수
        base_price: 기준 가격
        
    Returns:
        pd.DataFrame: 더미 분봉 데이터
    """
    print(f"[Dummy Data] Creating {minutes} minute data for {stock_code} (Base price: {base_price:,})")
    
    # 시간 데이터 생성
    start_time = datetime.now() - timedelta(minutes=minutes-1)
    times = [start_time + timedelta(minutes=i) for i in range(minutes)]
    
    # 가격 데이터 생성 (랜덤 워크)
    prices = []
    current_price = base_price
    
    for i in range(minutes):
        # 가격 변동 (-1% ~ +1%)
        change_rate = random.uniform(-0.01, 0.01)
        price_change = int(current_price * change_rate)
        current_price += price_change
        
        # OHLC 데이터 생성
        open_price = current_price
        high_price = open_price + random.randint(0, int(open_price * 0.005))  # 최대 0.5% 상승
        low_price = open_price - random.randint(0, int(open_price * 0.005))   # 최대 0.5% 하락
        close_price = random.randint(low_price, high_price)
        volume = random.randint(1000, 50000)  # 거래량
        
        prices.append({
            'datetime': times[i],
            'open': open_price,
            'high': high_price, 
            'low': low_price,
            'close': close_price,
            'volume': volume
        })
        
        current_price = close_price
    
    df = pd.DataFrame(prices)
    print(f"[Success] Generated {len(df)} candles")
    print(f"Price range: {df['low'].min():,} ~ {df['high'].max():,}")
    
    return df


def test_minute_data_api(stock_code: str = "005930"):
    """
    분봉조회 API 테스트 함수
    
    Args:
        stock_code: 테스트할 종목코드 (기본값: 삼성전자)
    """
    print(f"[API Test] Testing minute data API for {stock_code}")
    
    try:
        # 1. 일별분봉조회 (최근 60분)
        print("\n=== 1. Recent 60-minute data query ===")
        recent_data = get_recent_minute_data(stock_code, minutes=60)
        if recent_data is not None and not recent_data.empty:
            print(f"[Success] Recent 60-minute data: {len(recent_data)} records")
            print("Sample data:")
            print(recent_data.head())
            print(f"Columns: {list(recent_data.columns)}")
            return recent_data
        else:
            print("[Failed] Recent minute data query failed")
        
        # 2. 당일분봉조회 (실시간)
        print("\n=== 2. Today's realtime minute data query ===")
        today_data = get_realtime_minute_data(stock_code)
        if today_data is not None and not today_data.empty:
            print(f"[Success] Today's realtime data: {len(today_data)} records")
            print("Sample data:")
            print(today_data.head())
            print(f"Columns: {list(today_data.columns)}")
            return today_data
        else:
            print("[Failed] Today's minute data query failed")
        
        # 3. 직접 API 호출 테스트
        print("\n=== 3. Direct API call test ===")
        current_date = now_kst().strftime("%Y%m%d")
        current_hour = now_kst().strftime("%H%M%S")
        
        result = get_inquire_time_dailychartprice(
            stock_code=stock_code,
            input_date=current_date,
            input_hour=current_hour,
            past_data_yn="Y"
        )
        
        if result:
            summary_df, chart_df = result
            print(f"[Success] Direct API call successful")
            print(f"Summary info: {summary_df.shape if not summary_df.empty else 'Empty'}")
            print(f"Chart data: {chart_df.shape if not chart_df.empty else 'Empty'}")
            
            if not chart_df.empty:
                print("\nChart data sample:")
                print(chart_df.head())
                return chart_df
        else:
            print("[Failed] Direct API call failed")
        
        return None
        
    except Exception as e:
        print(f"[Error] API test error: {e}")
        return None


def create_candlestick_chart(df: pd.DataFrame, stock_code: str = "005930", title: str = "Stock Candlestick Chart"):
    """
    캔들차트 생성 함수
    
    Args:
        df: 분봉 데이터 DataFrame
        stock_code: 종목코드
        title: 차트 제목
    """
    if df is None or df.empty:
        print("[Error] No chart data available")
        return
    
    print(f"[Chart] Creating candlestick chart for {stock_code}")
    
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
        print(f"Available columns: {list(chart_df.columns)}")
        return
    
    # datetime 컬럼 생성 (없는 경우)
    if 'datetime' not in chart_df.columns:
        if 'date' in chart_df.columns and 'time' in chart_df.columns:
            chart_df['datetime'] = pd.to_datetime(
                chart_df['date'].astype(str) + ' ' + 
                chart_df['time'].astype(str).str.zfill(6),
                format='%Y%m%d %H%M%S',
                errors='coerce'
            )
        else:
            # 인덱스를 시간으로 사용
            chart_df['datetime'] = pd.date_range(
                start=datetime.now() - timedelta(minutes=len(chart_df)-1),
                periods=len(chart_df),
                freq='1min'
            )
    
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
    print(f"Time range: {chart_df['datetime'].min()} ~ {chart_df['datetime'].max()}")
    
    # 차트 생성
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10), height_ratios=[3, 1])
    
    # 1. 캔들스틱 차트
    ax1.set_title(f'{title} - {stock_code}', fontsize=16, fontweight='bold')
    
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
        ax1.plot([date, date], [low_price, high_price], color='black', linewidth=1)
        
        # 캔들 몸체
        candle_height = abs(close_price - open_price)
        candle_bottom = min(open_price, close_price)
        
        # 캔들 너비 (시간 간격에 따라 조정)
        width = pd.Timedelta(minutes=0.8)
        
        rect = Rectangle((date - width/2, candle_bottom), width, candle_height,
                        facecolor=color, edgecolor='black', alpha=0.7, linewidth=0.5)
        ax1.add_patch(rect)
    
    # 차트 스타일 설정 (영어로 변경)
    ax1.set_ylabel('Price (KRW)', fontsize=12)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
    
    # 가격 범위 설정 (여백 추가)
    price_range = chart_df[['high', 'low']].max().max() - chart_df[['high', 'low']].min().min()
    padding = price_range * 0.05
    ax1.set_ylim(chart_df['low'].min() - padding, chart_df['high'].max() + padding)
    
    # 2. 거래량 차트
    if 'volume' in chart_df.columns:
        volumes = pd.to_numeric(chart_df['volume'], errors='coerce').fillna(0)
        colors = ['red' if close >= open else 'blue' 
                 for close, open in zip(chart_df['close'], chart_df['open'])]
        
        ax2.bar(chart_df['datetime'], volumes, color=colors, alpha=0.7, width=pd.Timedelta(minutes=0.8))
        ax2.set_ylabel('Volume', fontsize=12)
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax2.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
    else:
        ax2.text(0.5, 0.5, 'No Volume Data', ha='center', va='center', transform=ax2.transAxes)
        ax2.set_ylabel('Volume', fontsize=12)
    
    ax2.set_xlabel('Time', fontsize=12)
    
    # 통계 정보 추가 (영어로 변경)
    if len(chart_df) > 0:
        first_price = chart_df['open'].iloc[0]
        last_price = chart_df['close'].iloc[-1]
        high_price = chart_df['high'].max()
        low_price = chart_df['low'].min()
        price_change = last_price - first_price
        change_rate = (price_change / first_price * 100) if first_price > 0 else 0
        
        stats_text = f'Open: {first_price:,.0f} | Close: {last_price:,.0f} | High: {high_price:,.0f} | Low: {low_price:,.0f}\n'
        stats_text += f'Change: {price_change:+,.0f} ({change_rate:+.2f}%) | Candles: {len(chart_df)}'
        
        fig.suptitle(stats_text, fontsize=10, y=0.02)
    
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.1)
    
    # 차트 저장
    filename = f"candlestick_chart_{stock_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"[Saved] Candlestick chart saved: {filename}")
    
    # 메모리 정리
    plt.close(fig)
    
    return filename


def main():
    """메인 실행 함수"""
    print("[Start] Minute data API test and candlestick visualization")
    
    # 테스트할 종목코드 (삼성전자)
    stock_code = "005930"
    
    try:
        # 1. API 테스트
        print("\n=== API Test ===")
        chart_data = test_minute_data_api(stock_code)
        
        if chart_data is not None and not chart_data.empty:
            print(f"\n[Success] {stock_code} API data retrieved: {len(chart_data)} records")
            
            # 2. 캔들차트 생성
            filename = create_candlestick_chart(
                chart_data, 
                stock_code, 
                f"Samsung Electronics ({stock_code}) Minute Chart"
            )
            
            if filename:
                print(f"[Complete] Candlestick chart created: {filename}")
            else:
                print("[Failed] Candlestick chart creation failed")
        else:
            print("[Failed] Unable to retrieve minute data from API")
            
            # API 실패 시 더미 데이터로 테스트
            print("\n=== Dummy Data Test ===")
            chart_data = generate_dummy_minute_data(stock_code, minutes=60, base_price=80000)
            
            if chart_data is not None and not chart_data.empty:
                print(f"\n[Success] {stock_code} dummy data generated: {len(chart_data)} records")
                
                # 캔들차트 생성
                filename = create_candlestick_chart(
                    chart_data, 
                    stock_code, 
                    f"Samsung Electronics ({stock_code}) Dummy Minute Chart"
                )
                
                if filename:
                    print(f"[Complete] Dummy candlestick chart created: {filename}")
                    print("\n[Analysis Results]")
                    print(f"- First price: {chart_data['open'].iloc[0]:,}")
                    print(f"- Last price: {chart_data['close'].iloc[-1]:,}")
                    print(f"- High price: {chart_data['high'].max():,}")
                    print(f"- Low price: {chart_data['low'].min():,}")
                    print(f"- Total volume: {chart_data['volume'].sum():,}")
                    
                    price_change = chart_data['close'].iloc[-1] - chart_data['open'].iloc[0]
                    change_rate = (price_change / chart_data['open'].iloc[0] * 100)
                    print(f"- Change: {price_change:+,.0f} ({change_rate:+.2f}%)")
                else:
                    print("[Failed] Dummy candlestick chart creation failed")
            else:
                print("[Failed] Dummy data generation failed")
            
    except Exception as e:
        print(f"Error occurred: {e}")


if __name__ == "__main__":
    main()