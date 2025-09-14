#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KIS API 인증 테스트 스크립트
"""

import sys
import os

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from api.kis_auth import auth, get_access_token
from api.kis_market_api import get_inquire_daily_itemchartprice
from utils.korean_time import now_kst
from datetime import timedelta

def test_kis_auth():
    """KIS API 인증 테스트"""
    print("🔐 KIS API 인증 테스트 시작")
    
    try:
        # 1. 인증 실행
        print("1. 인증 실행 중...")
        auth_result = auth()
        print(f"   인증 결과: {auth_result}")
        
        # 2. 토큰 확인
        print("2. 토큰 확인 중...")
        token = get_access_token()
        if token:
            print(f"   토큰 획득 성공: {token[:20]}...")
        else:
            print("   ❌ 토큰 획득 실패")
            return False
        
        # 3. API 호출 테스트
        print("3. API 호출 테스트 중...")
        end_date = now_kst().strftime("%Y%m%d")
        start_date = (now_kst() - timedelta(days=10)).strftime("%Y%m%d")
        
        daily_data = get_inquire_daily_itemchartprice(
            output_dv="2",
            div_code="J",
            itm_no="054540",  # 삼성전자
            inqr_strt_dt=start_date,
            inqr_end_dt=end_date,
            period_code="D",
            adj_prc="1"
        )
        
        if daily_data is not None and not daily_data.empty:
            print(f"   ✅ API 호출 성공: {len(daily_data)}개 데이터")
            return True
        else:
            print("   ❌ API 호출 실패")
            return False
            
    except Exception as e:
        print(f"   ❌ 인증 테스트 실패: {e}")
        return False

if __name__ == "__main__":
    success = test_kis_auth()
    if success:
        print("\n✅ KIS API 인증 성공!")
    else:
        print("\n❌ KIS API 인증 실패!")
