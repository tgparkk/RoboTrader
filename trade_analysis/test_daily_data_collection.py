#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
일봉 데이터 수집 테스트 스크립트
"""

import sys
import os
from datetime import datetime, timedelta

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from api.kis_market_api import get_inquire_daily_itemchartprice
from utils.korean_time import now_kst

def test_daily_data_collection():
    """일봉 데이터 수집 테스트"""
    print("🧪 일봉 데이터 수집 테스트 시작")
    
    # 테스트할 종목 (신호 로그에서 확인된 종목)
    test_stocks = ['054540', '248070', '382900']
    
    for stock_code in test_stocks:
        print(f"\n📊 {stock_code} 일봉 데이터 수집 테스트")
        
        try:
            # 60일 일봉 데이터 수집
            end_date = now_kst().strftime("%Y%m%d")
            start_date = (now_kst() - timedelta(days=70)).strftime("%Y%m%d")  # 여유분 추가
            
            print(f"   기간: {start_date} ~ {end_date}")
            
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",  # 상세 데이터
                div_code="J",   # 주식
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",  # 일봉
                adj_prc="1"     # 원주가
            )
            
            if daily_data is None:
                print(f"   ❌ {stock_code} 일봉 데이터 조회 실패 (None)")
                continue
            elif daily_data.empty:
                print(f"   ❌ {stock_code} 일봉 데이터 조회 실패 (빈 데이터)")
                continue
            else:
                print(f"   ✅ {stock_code} 일봉 데이터 조회 성공: {len(daily_data)}개")
                print(f"   컬럼: {list(daily_data.columns)}")
                print(f"   최신 데이터: {daily_data.iloc[-1]['stck_bsop_date'] if 'stck_bsop_date' in daily_data.columns else 'N/A'}")
                
        except Exception as e:
            print(f"   ❌ {stock_code} 일봉 데이터 수집 오류: {e}")

def test_minute_data_loading():
    """분봉 데이터 로딩 테스트"""
    print("\n🧪 분봉 데이터 로딩 테스트")
    
    import pickle
    from pathlib import Path
    
    minute_cache_dir = Path("cache/minute_data")
    
    if not minute_cache_dir.exists():
        print("   ❌ 분봉 캐시 디렉토리가 없습니다")
        return
    
    # 분봉 파일 목록 확인
    minute_files = list(minute_cache_dir.glob("*.pkl"))
    print(f"   📁 분봉 캐시 파일 개수: {len(minute_files)}")
    
    if minute_files:
        # 첫 번째 파일 테스트
        test_file = minute_files[0]
        print(f"   테스트 파일: {test_file.name}")
        
        try:
            with open(test_file, 'rb') as f:
                minute_data = pickle.load(f)
            
            print(f"   ✅ 분봉 데이터 로드 성공: {len(minute_data)}개")
            print(f"   컬럼: {list(minute_data.columns)}")
            
        except Exception as e:
            print(f"   ❌ 분봉 데이터 로드 실패: {e}")

if __name__ == "__main__":
    test_daily_data_collection()
    test_minute_data_loading()
