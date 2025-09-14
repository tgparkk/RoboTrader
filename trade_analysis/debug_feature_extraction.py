#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
특성 추출 과정 디버깅 스크립트
"""

import sys
import os
from datetime import datetime, timedelta

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from trade_analysis.ml_data_collector import MLDataCollector
from trade_analysis.ml_feature_engineer import MLFeatureEngineer
from utils.logger import setup_logger

logger = setup_logger(__name__)

def debug_feature_extraction():
    """특성 추출 과정 디버깅"""
    print("🔍 특성 추출 과정 디버깅 시작")
    
    # 1. 데이터 수집기 초기화
    print("\n1. 데이터 수집기 초기화")
    collector = MLDataCollector()
    
    # 2. 특성 엔지니어 초기화
    print("2. 특성 엔지니어 초기화")
    feature_engineer = MLFeatureEngineer()
    
    # 3. 테스트 날짜 설정
    start_date = "20250901"
    end_date = "20250912"
    print(f"3. 테스트 기간: {start_date} ~ {end_date}")
    
    # 4. 후보 종목 조회
    print("\n4. 후보 종목 조회")
    candidate_stocks = collector.get_candidate_stocks_by_date(start_date, end_date)
    print(f"   후보 종목 개수: {len(candidate_stocks)}")
    
    if not candidate_stocks:
        print("   ❌ 후보 종목이 없습니다")
        return
    
    # 5. 첫 번째 종목으로 테스트
    first_date = list(candidate_stocks.keys())[0]
    first_stock = candidate_stocks[first_date][0]
    test_stock = first_stock['stock_code']
    test_date = first_date
    print(f"\n5. 테스트 종목: {test_stock} ({test_date})")
    print(f"   종목 정보: {first_stock}")
    
    # 6. 분봉 데이터 로드 테스트
    print("\n6. 분봉 데이터 로드 테스트")
    minute_data = collector.load_minute_data(test_stock, test_date)
    if minute_data is not None:
        print(f"   ✅ 분봉 데이터 로드 성공: {len(minute_data)}개")
        print(f"   컬럼: {list(minute_data.columns)}")
    else:
        print("   ❌ 분봉 데이터 로드 실패")
        return
    
    # 7. 일봉 데이터 수집 테스트
    print("\n7. 일봉 데이터 수집 테스트")
    daily_data = collector.collect_daily_data(test_stock, 60)
    if daily_data is not None:
        print(f"   ✅ 일봉 데이터 수집 성공: {len(daily_data)}개")
        print(f"   컬럼: {list(daily_data.columns)}")
    else:
        print("   ❌ 일봉 데이터 수집 실패")
        return
    
    # 8. 특성 추출 테스트
    print("\n8. 특성 추출 테스트")
    try:
        # 테스트용 거래 정보 생성
        test_trade = {
            'stock_code': test_stock,
            'date': test_date,
            'buy_time': '12:12',
            'sell_time': '12:42',
            'buy_price': 52200,
            'sell_price': 53766,
            'profit_rate': 3.0,
            'is_win': True
        }
        
        features = feature_engineer.extract_comprehensive_features(
            minute_data=minute_data,
            daily_data=daily_data,
            trade=test_trade
        )
        
        if features is not None:
            print(f"   ✅ 특성 추출 성공: {len(features)}개 특성")
            print(f"   특성 목록: {list(features.keys())}")
        else:
            print("   ❌ 특성 추출 실패")
            
    except Exception as e:
        print(f"   ❌ 특성 추출 오류: {e}")
        import traceback
        traceback.print_exc()
    
    # 9. 전체 학습 데이터 수집 테스트
    print("\n9. 전체 학습 데이터 수집 테스트")
    try:
        training_data = collector.collect_ml_training_data(start_date, end_date)
        print(f"   학습 데이터 개수: {len(training_data) if training_data is not None else 0}")
        
        if training_data is not None and len(training_data) > 0:
            print(f"   ✅ 학습 데이터 수집 성공")
            print(f"   첫 번째 샘플 특성: {list(training_data[0].keys())}")
        else:
            print("   ❌ 학습 데이터 수집 실패")
            
    except Exception as e:
        print(f"   ❌ 학습 데이터 수집 오류: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_feature_extraction()
