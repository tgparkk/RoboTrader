#!/usr/bin/env python3
"""
메인 프로그램에서 데이터 충분성 검사 사용 예제
"""

from data_sufficiency_checker import check_and_collect_data, ensure_sufficient_minute_data
from utils.korean_time import now_kst

def main():
    """메인 프로그램에서 사용하는 예제"""
    
    # 현재 시간
    current_time = now_kst()
    today = current_time.strftime('%Y%m%d')
    current_hour = current_time.hour
    current_minute = current_time.minute
    
    print(f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"오늘 날짜: {today}")
    
    # 테스트할 종목들
    test_stocks = ["042520", "000660", "001270"]
    
    for stock_code in test_stocks:
        print(f"\n🔍 {stock_code} 데이터 확인 중...")
        
        # 방법 1: 간단한 사용법
        result = check_and_collect_data(stock_code, today, 15)
        print(f"  결과: {'✅ 충분' if result else '❌ 부족'}")
        
        # 방법 2: 상세한 사용법
        # result = ensure_sufficient_minute_data(stock_code, today, 15, True)
        # print(f"  상세 결과: {'✅ 충분' if result else '❌ 부족'}")


def check_stock_before_trading(stock_code: str, required_count: int = 15) -> bool:
    """
    매매 전 종목 데이터 확인 (메인 프로그램에서 사용)
    
    Args:
        stock_code: 종목코드
        required_count: 필요한 최소 분봉 개수
        
    Returns:
        bool: 데이터가 충분한지 여부
    """
    try:
        today = now_kst().strftime('%Y%m%d')
        
        print(f"🔍 매수 판단 시작: {stock_code}")
        
        # 데이터 충분성 확인 및 필요시 수집
        result = check_and_collect_data(stock_code, today, required_count)
        
        if result:
            print(f"✅ {stock_code} 데이터 충분: 매매 가능")
        else:
            print(f"❌ {stock_code} 데이터 부족: 매매 불가")
        
        return result
        
    except Exception as e:
        print(f"❌ {stock_code} 데이터 확인 중 오류: {e}")
        return False


if __name__ == "__main__":
    # 예제 실행
    main()
    
    print("\n" + "="*50)
    print("매매 전 데이터 확인 예제")
    print("="*50)
    
    # 매매 전 데이터 확인 예제
    check_stock_before_trading("042520", 15)
    check_stock_before_trading("000660", 15)
