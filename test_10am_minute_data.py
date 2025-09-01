#!/usr/bin/env python3
"""
10:00를 파라미터로 하는 get_inquire_time_itemchartprice 함수 테스트
"""
import pandas as pd
from datetime import datetime

from api.kis_api_manager import KISAPIManager
from api.kis_chart_api import get_inquire_time_itemchartprice
from utils.korean_time import now_kst

def test_10am_minute_data():
    """10:00를 파라미터로 하는 분봉 조회 테스트"""
    
    # API 매니저 초기화 및 인증
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("API 매니저 초기화 실패!")
        return
    
    # 테스트용 종목 (삼성전자)
    test_stock_code = "005930"
    test_time = "100000"  # 10:00:00
    
    print("=" * 70)
    print(f"get_inquire_time_itemchartprice 함수 테스트")
    print(f"종목코드: {test_stock_code}")
    print(f"입력시간: {test_time} (10:00:00)")
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
            
            # 시간 관련 컬럼 확인
            time_columns = []
            for col in output2.columns:
                if any(keyword in col.lower() for keyword in ['time', 'hour', 'date', 'bsop']):
                    time_columns.append(col)
            
            print(f"시간 관련 컬럼: {time_columns}")
            
            # 처음 5개와 마지막 5개 분봉 데이터 표시
            print(f"\n[처음 5개 분봉]")
            first_5 = output2.head(5)
            for idx, row in first_5.iterrows():
                # 주요 컬럼들만 출력
                time_info = ""
                price_info = ""
                volume_info = ""
                
                # 시간 정보 추출
                for col in time_columns:
                    if col in row:
                        time_info += f"{col}={row[col]} "
                
                # 가격 정보 추출
                price_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr']
                for col in price_cols:
                    if col in row:
                        price_info += f"{col}={row[col]} "
                
                # 거래량 정보 추출
                volume_cols = ['cntg_vol', 'acml_vol']
                for col in volume_cols:
                    if col in row:
                        volume_info += f"{col}={row[col]} "
                
                print(f"  {idx}: {time_info}| {price_info}| {volume_info}")
            
            print(f"\n[마지막 5개 분봉]")
            last_5 = output2.tail(5)
            for idx, row in last_5.iterrows():
                # 동일한 방식으로 출력
                time_info = ""
                price_info = ""
                volume_info = ""
                
                for col in time_columns:
                    if col in row:
                        time_info += f"{col}={row[col]} "
                
                price_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr']
                for col in price_cols:
                    if col in row:
                        price_info += f"{col}={row[col]} "
                
                volume_cols = ['cntg_vol', 'acml_vol']
                for col in volume_cols:
                    if col in row:
                        volume_info += f"{col}={row[col]} "
                
                print(f"  {idx}: {time_info}| {price_info}| {volume_info}")
            
            # 시간 범위 분석
            if 'stck_cntg_hour' in output2.columns:
                first_time = str(output2['stck_cntg_hour'].iloc[0]).zfill(6)
                last_time = str(output2['stck_cntg_hour'].iloc[-1]).zfill(6)
                print(f"\n[시간 범위 분석]")
                print(f"첫 번째 분봉 시간: {first_time[:2]}:{first_time[2:4]}:{first_time[4:]}")
                print(f"마지막 분봉 시간: {last_time[:2]}:{last_time[2:4]}:{last_time[4:]}")
                print(f"10:00 파라미터로 조회했을 때 받은 데이터 범위")
                
                # 10:00 이전/이후 데이터 분석
                before_10am = 0
                after_10am = 0
                exactly_10am = 0
                
                for idx, row in output2.iterrows():
                    hour_str = str(row['stck_cntg_hour']).zfill(6)
                    hour_int = int(hour_str[:4])  # HHMM
                    
                    if hour_int < 1000:  # 10:00 이전
                        before_10am += 1
                    elif hour_int == 1000:  # 정확히 10:00
                        exactly_10am += 1
                    else:  # 10:00 이후
                        after_10am += 1
                
                print(f"10:00 이전 분봉: {before_10am}개")
                print(f"10:00 정각 분봉: {exactly_10am}개")
                print(f"10:00 이후 분봉: {after_10am}개")
                
        else:
            print(f"\n[OUTPUT2] 데이터 없음")
            
    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    test_10am_minute_data()