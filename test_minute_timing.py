#!/usr/bin/env python3
"""
간단한 1분봉 데이터 시간 확인 스크립트 (인증 포함)
"""
import pandas as pd
from datetime import datetime

from api.kis_api_manager import KISAPIManager
from api.kis_chart_api import get_realtime_minute_data
from utils.korean_time import now_kst

def test_minute_timing():
    """간단한 1분봉 데이터 시간 정보 확인"""
    
    # API 매니저 초기화 및 인증
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("API 매니저 초기화 실패!")
        return
    
    # 테스트용 종목 (삼성전자)
    test_stock_code = "005930"
    
    print("=" * 60)
    print(f"1분봉 데이터 시간 정보 분석 - {test_stock_code}")
    print(f"현재 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    try:
        # 직접 API 호출로 원본 데이터 확인
        print("\nAPI 호출 중...")
        raw_data = get_realtime_minute_data(test_stock_code)
        
        if raw_data is not None and not raw_data.empty:
            print(f"\n데이터 수신 성공!")
            print(f"총 데이터 건수: {len(raw_data)}건")
            print(f"사용 가능한 컬럼: {list(raw_data.columns)}")
            
            # 시간 관련 컬럼 확인
            if 'date' in raw_data.columns and 'time' in raw_data.columns:
                first_date = raw_data['date'].iloc[0]
                last_date = raw_data['date'].iloc[-1]
                first_time = str(raw_data['time'].iloc[0]).zfill(6)
                last_time = str(raw_data['time'].iloc[-1]).zfill(6)
                
                print(f"\n영업일자: {first_date} ~ {last_date}")
                print(f"체결시간: {first_time[:2]}:{first_time[2:4]}:{first_time[4:]} ~ {last_time[:2]}:{last_time[2:4]}:{last_time[4:]}")
            
            if 'datetime' in raw_data.columns:
                first_dt = raw_data['datetime'].iloc[0]
                last_dt = raw_data['datetime'].iloc[-1]
                print(f"변환된 datetime: {first_dt} ~ {last_dt}")
            
            # 최신 10개 분봉 상세 정보
            print(f"\n**최신 10개 분봉 시간 정보**")
            print("시간       | 종가     | 거래량     | 원본시간")
            print("-" * 50)
            
            latest_10 = raw_data.tail(10)
            for idx, row in latest_10.iterrows():
                # 시간 정보
                if 'datetime' in row and pd.notna(row['datetime']):
                    dt_str = pd.Timestamp(row['datetime']).strftime('%H:%M:%S')
                elif 'time' in row:
                    time_info = str(row['time']).zfill(6)
                    dt_str = f"{time_info[:2]}:{time_info[2:4]}:{time_info[4:]}"
                else:
                    dt_str = "N/A"
                
                # 가격/거래량 정보
                close_price = row.get('close', 0)
                volume = row.get('volume', 0)
                
                # 원본 시간 정보 (API 원본)
                orig_date = row.get('date', row.get('stck_bsop_date', 'N/A'))
                orig_time = str(row.get('time', row.get('stck_cntg_hour', 'N/A'))).zfill(6)
                
                print(f"{dt_str} | {close_price:8,.0f} | {volume:10,.0f} | {orig_date}_{orig_time}")
            
            # 현재 시간과 마지막 데이터 시간 비교
            print(f"\n**지연 시간 분석**")
            current_time = now_kst()
            print(f"현재 시간: {current_time.strftime('%H:%M:%S')}")
            
            if 'datetime' in raw_data.columns:
                last_data_time = pd.Timestamp(raw_data['datetime'].iloc[-1])
                if pd.notna(last_data_time):
                    # 타임존 처리
                    if last_data_time.tz is None:
                        last_data_time = last_data_time.tz_localize('Asia/Seoul')
                    elif last_data_time.tz != current_time.tz:
                        last_data_time = last_data_time.tz_convert('Asia/Seoul')
                    
                    time_diff = (current_time - last_data_time).total_seconds() / 60
                    print(f"마지막 데이터 시간: {last_data_time.strftime('%H:%M:%S')}")
                    print(f"지연 시간: {time_diff:.1f}분")
                    
                    # 분봉 라벨링 설명
                    print(f"\n**분봉 라벨링 해석**")
                    print(f"마지막 분봉 시간: {last_data_time.strftime('%H:%M')}")
                    print(f"이 분봉은 {(last_data_time - pd.Timedelta(minutes=1)).strftime('%H:%M')}~{last_data_time.strftime('%H:%M')} 기간의 데이터입니다")
                    
                    # 10:13:00에 대한 설명
                    example_time = pd.Timestamp('2025-09-01 10:13:00').tz_localize('Asia/Seoul')
                    print(f"\n예시: 10:13:00에 API를 호출하면:")
                    print(f"- 가장 최신 완성된 분봉: 10:12 (10:11~10:12 기간)")
                    print(f"- 10:13 분봉은 아직 진행중이므로 포함되지 않음")
            
            # API 요청 시간 추가 정보
            print(f"\n**API 요청 정보**")
            print(f"요청 시간: {current_time.strftime('%H:%M:%S')}")
            print(f"요청 종목: {test_stock_code} (삼성전자)")
            print(f"수신 건수: {len(raw_data)}건")
            
        else:
            print("데이터 수신 실패 또는 빈 데이터")
            
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    test_minute_timing()