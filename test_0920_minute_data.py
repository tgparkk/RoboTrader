#!/usr/bin/env python3
"""
09:20을 파라미터로 하는 get_inquire_time_itemchartprice 함수 테스트 (016670)
"""
import pandas as pd
from datetime import datetime

from api.kis_api_manager import KISAPIManager
from api.kis_chart_api import get_inquire_time_itemchartprice
from utils.korean_time import now_kst

def test_0920_minute_data():
    """09:20을 파라미터로 하는 분봉 조회 테스트"""
    
    # API 매니저 초기화 및 인증
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("API 매니저 초기화 실패!")
        return
    
    # 테스트용 종목 (016670)
    test_stock_code = "016670"
    test_time = "092000"  # 09:20:00
    
    print("=" * 70)
    print(f"get_inquire_time_itemchartprice 함수 테스트")
    print(f"종목코드: {test_stock_code}")
    print(f"입력시간: {test_time} (09:20:00)")
    print(f"현재시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    try:
        # get_inquire_time_itemchartprice 직접 호출
        print(f"\nAPI 호출: get_inquire_time_itemchartprice")
        print(f"파라미터:")
        print(f"  - div_code: J (KRX)")
        print(f"  - stock_code: {test_stock_code}")
        print(f"  - input_hour: {test_time}")
        print(f"  - past_data_yn: Y")
        
        output1, output2 = get_inquire_time_itemchartprice(
            div_code="J",
            stock_code=test_stock_code,
            input_hour=test_time,
            past_data_yn="Y"
        )
        
        print(f"\n=== 결과 분석 ===")
        
        # output1 (종목 요약 정보) 분석
        if output1 is not None and not output1.empty:
            print(f"\n[OUTPUT1 - 종목 요약 정보]")
            print(f"컬럼: {list(output1.columns)}")
            for idx, row in output1.iterrows():
                print(f"데이터: {dict(row)}")
        else:
            print(f"\n[OUTPUT1] 데이터 없음")
        
        # output2 (당일 분봉 데이터) 분석  
        if output2 is not None and not output2.empty:
            print(f"\n[OUTPUT2 - 당일 분봉 데이터]")
            print(f"총 데이터 건수: {len(output2)}건")
            print(f"컬럼: {list(output2.columns)}")
            
            # 전체 분봉 시간 목록 출력
            print(f"\n[전체 분봉 시간 목록]")
            for idx, row in output2.iterrows():
                date_info = row.get('date', 'N/A')
                time_info = str(row.get('time', 'N/A')).zfill(6)
                datetime_info = row.get('datetime', 'N/A')
                close_price = row.get('close', 0)
                volume = row.get('volume', 0)
                
                time_formatted = f"{time_info[:2]}:{time_info[2:4]}:{time_info[4:]}"
                print(f"  {idx:2d}: {date_info} {time_formatted} | datetime={datetime_info} | 종가={close_price} | 거래량={volume}")
            
            # 시간 범위 분석
            if len(output2) > 0:
                first_time = str(output2['time'].iloc[0]).zfill(6)
                last_time = str(output2['time'].iloc[-1]).zfill(6)
                print(f"\n[시간 범위 분석]")
                print(f"첫 번째 분봉 시간: {first_time[:2]}:{first_time[2:4]}:{first_time[4:]}")
                print(f"마지막 분봉 시간: {last_time[:2]}:{last_time[2:4]}:{last_time[4:]}")
                print(f"09:20 파라미터로 조회했을 때 받은 데이터 범위")
                
                # 09:20 기준 분석
                before_0920 = 0
                after_0920 = 0
                exactly_0920 = 0
                
                for idx, row in output2.iterrows():
                    time_str = str(row['time']).zfill(6)
                    time_int = int(time_str[:4])  # HHMM
                    
                    if time_int < 920:  # 09:20 이전
                        before_0920 += 1
                    elif time_int == 920:  # 정확히 09:20
                        exactly_0920 += 1
                    else:  # 09:20 이후
                        after_0920 += 1
                
                print(f"09:20 이전 분봉: {before_0920}개")
                print(f"09:20 정각 분봉: {exactly_0920}개")
                print(f"09:20 이후 분봉: {after_0920}개")
                
                # 09:20 분봉 존재 여부 및 위치 확인
                has_0920_candle = any(str(row['time']).zfill(6) == '092000' for _, row in output2.iterrows())
                if has_0920_candle:
                    print(f"\n🔍 09:20:00 분봉이 결과에 포함되어 있습니다!")
                    # 09:20 분봉 찾아서 상세 정보 출력
                    for idx, row in output2.iterrows():
                        if str(row['time']).zfill(6) == '092000':
                            print(f"09:20 분봉 위치: {idx}번째 (0부터 시작)")
                            print(f"09:20 분봉 정보: 종가={row.get('close', 0)} | 거래량={row.get('volume', 0)}")
                            break
                else:
                    print(f"\n❌ 09:20:00 분봉이 결과에 포함되지 않았습니다.")
                    print(f"이는 09:20을 파라미터로 했을 때 09:20 이전 데이터만 반환됨을 의미할 수 있습니다.")
                
        else:
            print(f"\n[OUTPUT2] 데이터 없음")
            
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    test_0920_minute_data()