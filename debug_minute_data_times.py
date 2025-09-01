#!/usr/bin/env python3
"""
1분봉 데이터의 시간 정보 디버깅 스크립트
"""
import asyncio
from datetime import datetime
import pandas as pd

from core.intraday_stock_manager import IntradayStockManager
from api.kis_api_manager import KISAPIManager
from utils.korean_time import now_kst
from utils.logger import setup_logger

logger = setup_logger(__name__)

async def debug_minute_data_times():
    """1분봉 데이터의 시간 정보 확인"""
    
    # API 매니저 초기화
    api_manager = KISAPIManager()
    
    # 테스트용 종목 (삼성전자)
    test_stock_code = "005930"
    
    print("=" * 60)
    print(f"📊 1분봉 데이터 시간 정보 분석 - {test_stock_code}")
    print(f"현재 시간: {now_kst().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    try:
        # 1. 직접 API 호출로 원본 데이터 확인
        from api.kis_chart_api import get_realtime_minute_data
        raw_data = get_realtime_minute_data(test_stock_code)
        
        if raw_data is not None and not raw_data.empty:
            print("\n🔍 **API 원본 데이터 시간 정보**")
            print(f"총 데이터 건수: {len(raw_data)}건")
            
            # 원본 컬럼 확인
            print(f"사용 가능한 컬럼: {list(raw_data.columns)}")
            
            # 시간 관련 컬럼 상세 분석
            if 'stck_bsop_date' in raw_data.columns:
                print(f"\n📅 stck_bsop_date (영업일자): {raw_data['stck_bsop_date'].iloc[0]} ~ {raw_data['stck_bsop_date'].iloc[-1]}")
            
            if 'stck_cntg_hour' in raw_data.columns:
                first_time = str(raw_data['stck_cntg_hour'].iloc[0]).zfill(6)
                last_time = str(raw_data['stck_cntg_hour'].iloc[-1]).zfill(6)
                print(f"⏰ stck_cntg_hour (체결시간): {first_time} ~ {last_time}")
                print(f"   → {first_time[:2]}:{first_time[2:4]}:{first_time[4:]} ~ {last_time[:2]}:{last_time[2:4]}:{last_time[4:]}")
            
            if 'datetime' in raw_data.columns:
                print(f"🕐 변환된 datetime: {raw_data['datetime'].iloc[0]} ~ {raw_data['datetime'].iloc[-1]}")
            
            if 'date' in raw_data.columns and 'time' in raw_data.columns:
                print(f"📊 표준화된 date: {raw_data['date'].iloc[0]} ~ {raw_data['date'].iloc[-1]}")
                first_time = str(raw_data['time'].iloc[0]).zfill(6)
                last_time = str(raw_data['time'].iloc[-1]).zfill(6)
                print(f"📊 표준화된 time: {first_time} ~ {last_time}")
            
            # 최신 5개 분봉 상세 정보
            print(f"\n📋 **최신 5개 분봉 상세 정보**")
            latest_5 = raw_data.tail(5)
            for idx, row in latest_5.iterrows():
                date_info = row.get('date', row.get('stck_bsop_date', 'N/A'))
                time_info = str(row.get('time', row.get('stck_cntg_hour', 'N/A'))).zfill(6)
                close_price = row.get('close', row.get('stck_prpr', 0))
                volume = row.get('volume', row.get('cntg_vol', 0))
                
                if 'datetime' in row:
                    dt_str = pd.Timestamp(row['datetime']).strftime('%H:%M:%S')
                else:
                    dt_str = f"{time_info[:2]}:{time_info[2:4]}:{time_info[4:]}"
                    
                print(f"  {dt_str} | 날짜={date_info} | 시간={time_info} | 종가={close_price:,} | 거래량={volume:,}")
        
        # 2. IntradayStockManager를 통한 결합 데이터 확인
        print(f"\n🔄 **IntradayStockManager 결합 데이터 확인**")
        
        manager = IntradayStockManager(api_manager)
        
        # 테스트 종목을 임시로 추가
        await manager.add_selected_stock(test_stock_code, "삼성전자", "디버깅용")
        
        # 결합된 데이터 가져오기
        combined_data = manager.get_combined_chart_data(test_stock_code)
        
        if combined_data is not None and not combined_data.empty:
            print(f"결합 데이터 총 건수: {len(combined_data)}건")
            
            if 'datetime' in combined_data.columns:
                print(f"시간 범위: {combined_data['datetime'].iloc[0]} ~ {combined_data['datetime'].iloc[-1]}")
            elif 'time' in combined_data.columns:
                first_time = str(combined_data['time'].iloc[0]).zfill(6)
                last_time = str(combined_data['time'].iloc[-1]).zfill(6)
                print(f"시간 범위: {first_time[:2]}:{first_time[2:4]} ~ {last_time[:2]}:{last_time[2:4]}")
            
            # 마지막 10분봉 시간 확인
            print(f"\n📋 **마지막 10개 분봉 시간 확인**")
            latest_10 = combined_data.tail(10)
            for idx, row in latest_10.iterrows():
                if 'datetime' in row:
                    dt_str = pd.Timestamp(row['datetime']).strftime('%H:%M:%S')
                elif 'time' in row:
                    time_info = str(row['time']).zfill(6)
                    dt_str = f"{time_info[:2]}:{time_info[2:4]}:{time_info[4:]}"
                else:
                    dt_str = "N/A"
                
                close_price = row.get('close', 0)
                volume = row.get('volume', 0)
                print(f"  {dt_str} | 종가={close_price:,} | 거래량={volume:,}")
        
        # 3. 현재 시간과 마지막 데이터 시간 비교
        print(f"\n⏰ **시간 지연 분석**")
        current_time = now_kst()
        print(f"현재 시간: {current_time.strftime('%H:%M:%S')}")
        
        if combined_data is not None and not combined_data.empty:
            if 'datetime' in combined_data.columns:
                last_data_time = pd.Timestamp(combined_data['datetime'].iloc[-1])
                time_diff = (current_time - last_data_time.replace(tzinfo=current_time.tzinfo)).total_seconds() / 60
                print(f"마지막 데이터 시간: {last_data_time.strftime('%H:%M:%S')}")
                print(f"지연 시간: {time_diff:.1f}분")
                
                if time_diff > 2:
                    print(f"⚠️ 지연 경고: {time_diff:.1f}분 지연 (2분 이상)")
                elif time_diff > 1:
                    print(f"🟡 약간 지연: {time_diff:.1f}분")
                else:
                    print(f"✅ 정상: {time_diff:.1f}분 지연")
        
    except Exception as e:
        logger.error(f"❌ 디버깅 중 오류: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("디버깅 완료")

if __name__ == "__main__":
    asyncio.run(debug_minute_data_times())