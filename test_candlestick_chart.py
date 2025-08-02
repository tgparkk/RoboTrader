"""
분봉조회 API 테스트 및 캔들차트 시각화
"""
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import asyncio
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

# 한글 폰트 설정
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

logger = setup_logger(__name__)


def test_minute_data_api(stock_code: str = "005930"):
    """
    분봉조회 API 테스트 함수
    
    Args:
        stock_code: 테스트할 종목코드 (기본값: 삼성전자)
    """
    logger.info(f"[테스트] {stock_code} 분봉조회 API 테스트 시작")
    
    # 1. 일별분봉조회 (최근 60분)
    print("\n=== 1. 최근 60분 분봉 데이터 조회 ===")
    recent_data = get_recent_minute_data(stock_code, minutes=60)
    if recent_data is not None and not recent_data.empty:
        print(f"[성공] 최근 60분 데이터: {len(recent_data)}건")
        print(recent_data.head())
        print(f"컬럼: {list(recent_data.columns)}")
    else:
        print("[실패] 최근 분봉 데이터 조회 실패")
    
    # 2. 당일분봉조회 (실시간)
    print("\n=== 2. 당일 실시간 분봉 데이터 조회 ===")
    today_data = get_realtime_minute_data(stock_code)
    if today_data is not None and not today_data.empty:
        print(f"[성공] 당일 실시간 데이터: {len(today_data)}건")
        print(today_data.head())
        print(f"컬럼: {list(today_data.columns)}")
    else:
        print("[실패] 당일 분봉 데이터 조회 실패")
    
    # 3. 직접 API 호출 테스트
    print("\n=== 3. 직접 API 호출 테스트 ===")
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
        print(f"[성공] 직접 API 호출 성공")
        print(f"요약 정보: {summary_df.shape if not summary_df.empty else 'Empty'}")
        print(f"차트 데이터: {chart_df.shape if not chart_df.empty else 'Empty'}")
        
        if not chart_df.empty:
            print("\n차트 데이터 샘플:")
            print(chart_df.head())
            return chart_df
    else:
        print("[실패] 직접 API 호출 실패")
    
    # 가장 성공한 데이터 반환
    if recent_data is not None and not recent_data.empty:
        return recent_data
    elif today_data is not None and not today_data.empty:
        return today_data
    else:
        return None


def create_candlestick_chart(df: pd.DataFrame, stock_code: str = "005930", title: str = "주식 캔들차트"):
    """
    캔들차트 생성 함수
    
    Args:
        df: 분봉 데이터 DataFrame
        stock_code: 종목코드
        title: 차트 제목
    """
    if df is None or df.empty:
        logger.error("[오류] 차트 데이터가 없습니다")
        return
    
    logger.info(f"[차트] {stock_code} 캔들차트 생성 시작")
    
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
        logger.error(f"[오류] 필수 컬럼 누락: {missing_columns}")
        print(f"사용 가능한 컬럼: {list(chart_df.columns)}")
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
                start=now_kst() - timedelta(minutes=len(chart_df)-1),
                periods=len(chart_df),
                freq='1min'
            )
    
    # 데이터 타입 변환
    for col in required_columns:
        chart_df[col] = pd.to_numeric(chart_df[col], errors='coerce')
    
    # NaN 값 제거
    chart_df = chart_df.dropna(subset=required_columns + ['datetime'])
    
    if chart_df.empty:
        logger.error("[오류] 유효한 데이터가 없습니다")
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
    
    # 2. 거래량 차트 (있는 경우)
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
    filename = f"candlestick_chart_{stock_code}_{now_kst().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    logger.info(f"[저장] 캔들차트 저장: {filename}")
    
    # 차트 표시
    plt.show()
    
    return filename


def main():
    """메인 실행 함수"""
    print("[시작] 분봉조회 API 테스트 및 캔들차트 시각화 시작")
    
    # 테스트할 종목코드 (삼성전자)
    stock_code = "005930"
    
    try:
        # 1. API 테스트
        chart_data = test_minute_data_api(stock_code)
        
        if chart_data is not None and not chart_data.empty:
            print(f"\n[성공] {stock_code} 데이터 조회 성공: {len(chart_data)}건")
            
            # 2. 캔들차트 생성
            filename = create_candlestick_chart(
                chart_data, 
                stock_code, 
                f"삼성전자({stock_code}) 분봉 차트"
            )
            
            if filename:
                print(f"[완료] 캔들차트 생성 완료: {filename}")
            else:
                print("[실패] 캔들차트 생성 실패")
        else:
            print("[실패] 분봉 데이터를 가져올 수 없습니다.")
            print("[안내] 해결 방안:")
            print("   1. 장중 시간에 실행해보세요")
            print("   2. 다른 종목코드로 시도해보세요")
            print("   3. API 인증 설정을 확인해보세요")
            
    except Exception as e:
        logger.error(f"[오류] 테스트 실행 오류: {e}")
        print(f"오류 발생: {e}")


if __name__ == "__main__":
    main()