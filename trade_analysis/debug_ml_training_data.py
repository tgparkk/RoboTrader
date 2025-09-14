#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ML 학습 데이터 수집 디버깅 스크립트
"""

import sys
import os
from datetime import datetime, timedelta

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from trade_analysis.ml_data_collector import MLDataCollector
from utils.logger import setup_logger

logger = setup_logger(__name__)

def debug_ml_training_data():
    """ML 학습 데이터 수집 디버깅"""
    print("🔍 ML 학습 데이터 수집 디버깅 시작")
    
    # 1. 데이터 수집기 초기화
    print("\n1. 데이터 수집기 초기화")
    collector = MLDataCollector()
    
    # 2. 테스트 날짜 설정
    start_date = "20250901"
    end_date = "20250912"
    print(f"2. 테스트 날짜: {start_date} ~ {end_date}")
    
    # 3. 후보 종목 확인
    print("\n3. 후보 종목 확인")
    candidate_stocks = collector.get_candidate_stocks_by_date(start_date, end_date)
    print(f"   후보 종목 수: {len(candidate_stocks)}")
    
    for date, stocks in candidate_stocks.items():
        print(f"   {date}: {len(stocks)}개 종목")
        for stock in stocks[:3]:  # 처음 3개만 출력
            print(f"     - {stock['stock_code']}: {stock.get('name', 'N/A')}")
    
    # 4. 신호 재현 테스트
    print("\n4. 신호 재현 테스트")
    for date, stocks in candidate_stocks.items():
        print(f"\n   📅 {date} 신호 재현:")
        for stock in stocks[:2]:  # 처음 2개 종목만 테스트
            stock_code = stock['stock_code']
            print(f"     🔍 {stock_code} 신호 재현 중...")
            
            try:
                # 분봉 데이터 로드
                minute_data = collector.load_minute_data(stock_code, date)
                if minute_data is None or minute_data.empty:
                    print(f"       ❌ 분봉 데이터 없음")
                    continue
                
                print(f"       ✅ 분봉 데이터: {len(minute_data)}개")
                
                # 신호 재현
                signals = collector.replay_signals(stock_code, date, minute_data)
                if signals:
                    print(f"       ✅ 신호 {len(signals)}개 발견")
                    for signal in signals[:3]:  # 처음 3개만 출력
                        print(f"         - {signal['time']}: {signal['action']} @{signal['price']} ({signal.get('reason', 'N/A')})")
                else:
                    print(f"       ❌ 신호 없음")
                    
            except Exception as e:
                print(f"       ❌ 오류: {e}")
    
    # 5. 전체 학습 데이터 수집 테스트
    print("\n5. 전체 학습 데이터 수집 테스트")
    try:
        training_data = collector.collect_ml_training_data(start_date, end_date)
        if training_data is not None and not training_data.empty:
            print(f"   ✅ 학습 데이터 수집 성공: {len(training_data)}개")
            print(f"   📊 컬럼: {list(training_data.columns)}")
            print(f"   📈 승패 분포:")
            if 'is_win' in training_data.columns:
                win_count = training_data['is_win'].sum()
                total_count = len(training_data)
                print(f"     - 승: {win_count}개 ({win_count/total_count*100:.1f}%)")
                print(f"     - 패: {total_count-win_count}개 ({(total_count-win_count)/total_count*100:.1f}%)")
        else:
            print("   ❌ 학습 데이터 수집 실패")
    except Exception as e:
        print(f"   ❌ 오류: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_ml_training_data()
