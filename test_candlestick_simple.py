"""
분봉조회 API 테스트용 더미 데이터로 캔들차트 시각화
"""
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import numpy as np
import random

# 한글 폰트 설정
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False


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
    print(f"[더미데이터] {stock_code} {minutes}분 더미 데이터 생성 시작 (기준가: {base_price:,}원)")
    
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
    print(f"[더미데이터] 생성 완료: {len(df)}개 캔들")
    print(f"가격 범위: {df['low'].min():,}원 ~ {df['high'].max():,}원")
    
    return df


def create_candlestick_chart(df: pd.DataFrame, stock_code: str = "005930", title: str = "주식 캔들차트"):
    """
    캔들차트 생성 함수
    
    Args:
        df: 분봉 데이터 DataFrame
        stock_code: 종목코드
        title: 차트 제목
    """
    if df is None or df.empty:
        print("[오류] 차트 데이터가 없습니다")
        return
    
    print(f"[차트] {stock_code} 캔들차트 생성 시작")
    
    # 데이터 준비
    chart_df = df.copy()
    
    # 필수 컬럼 확인
    required_columns = ['open', 'high', 'low', 'close']
    missing_columns = [col for col in required_columns if col not in chart_df.columns]
    
    if missing_columns:
        print(f"[오류] 필수 컬럼 누락: {missing_columns}")
        print(f"사용 가능한 컬럼: {list(chart_df.columns)}")
        return
    
    # 데이터 타입 변환
    for col in required_columns:
        chart_df[col] = pd.to_numeric(chart_df[col], errors='coerce')
    
    # NaN 값 제거
    chart_df = chart_df.dropna(subset=required_columns + ['datetime'])
    
    if chart_df.empty:
        print("[오류] 유효한 데이터가 없습니다")
        return
    
    # 시간순 정렬
    chart_df = chart_df.sort_values('datetime').reset_index(drop=True)
    
    print(f"[차트] 차트 데이터 준비 완료: {len(chart_df)}개 캔들")
    print(f"시간 범위: {chart_df['datetime'].min()} ~ {chart_df['datetime'].max()}")
    
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
    
    # 차트 스타일 설정
    ax1.set_ylabel('가격 (원)', fontsize=12)
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
        ax2.set_ylabel('거래량', fontsize=12)
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax2.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
    else:
        ax2.text(0.5, 0.5, '거래량 데이터 없음', ha='center', va='center', transform=ax2.transAxes)
        ax2.set_ylabel('거래량', fontsize=12)
    
    ax2.set_xlabel('시간', fontsize=12)
    
    # 통계 정보 추가
    if len(chart_df) > 0:
        first_price = chart_df['open'].iloc[0]
        last_price = chart_df['close'].iloc[-1]
        high_price = chart_df['high'].max()
        low_price = chart_df['low'].min()
        price_change = last_price - first_price
        change_rate = (price_change / first_price * 100) if first_price > 0 else 0
        
        stats_text = f'시가: {first_price:,.0f}원 | 종가: {last_price:,.0f}원 | 고가: {high_price:,.0f}원 | 저가: {low_price:,.0f}원\n'
        stats_text += f'변동: {price_change:+,.0f}원 ({change_rate:+.2f}%) | 데이터: {len(chart_df)}개 캔들'
        
        fig.suptitle(stats_text, fontsize=10, y=0.02)
    
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.1)
    
    # 차트 저장
    filename = f"candlestick_chart_{stock_code}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"[저장] 캔들차트 저장: {filename}")
    
    # 차트 표시
    plt.show()
    
    return filename


def test_with_dummy_data():
    """더미 데이터로 캔들차트 테스트"""
    print("[시작] 더미 데이터 캔들차트 테스트 시작")
    
    # 테스트할 종목코드 (삼성전자)
    stock_code = "005930"
    
    try:
        # 1. 더미 데이터 생성
        chart_data = generate_dummy_minute_data(stock_code, minutes=60, base_price=80000)
        
        if chart_data is not None and not chart_data.empty:
            print(f"\n[성공] {stock_code} 더미 데이터 생성 성공: {len(chart_data)}건")
            print("\n데이터 샘플:")
            print(chart_data.head())
            
            # 2. 캔들차트 생성
            filename = create_candlestick_chart(
                chart_data, 
                stock_code, 
                f"삼성전자({stock_code}) 더미 분봉 차트"
            )
            
            if filename:
                print(f"[완료] 캔들차트 생성 완료: {filename}")
                print("\n[분석 결과]")
                print(f"- 첫 가격: {chart_data['open'].iloc[0]:,}원")
                print(f"- 마지막 가격: {chart_data['close'].iloc[-1]:,}원")
                print(f"- 최고가: {chart_data['high'].max():,}원")
                print(f"- 최저가: {chart_data['low'].min():,}원")
                print(f"- 총 거래량: {chart_data['volume'].sum():,}주")
                
                price_change = chart_data['close'].iloc[-1] - chart_data['open'].iloc[0]
                change_rate = (price_change / chart_data['open'].iloc[0] * 100)
                print(f"- 변동: {price_change:+,.0f}원 ({change_rate:+.2f}%)")
            else:
                print("[실패] 캔들차트 생성 실패")
        else:
            print("[실패] 더미 데이터 생성 실패")
            
    except Exception as e:
        print(f"오류 발생: {e}")


if __name__ == "__main__":
    test_with_dummy_data()