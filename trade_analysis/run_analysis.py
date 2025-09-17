#!/usr/bin/env python3
"""
분석 스크립트 실행 도우미
간편한 실행을 위한 래퍼 스크립트
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from analysis_script import StockAnalysisScript
from utils.logger import setup_logger

logger = setup_logger(__name__)


def run_quick_analysis(days: int = 7, use_api: bool = False):
    """빠른 분석 실행 (최근 N일)"""
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    print(f"🚀 빠른 분석 실행: {start_date} ~ {end_date}")
    print(f"   API 사용: {'예' if use_api else '아니오'}")
    
    analyzer = StockAnalysisScript()
    result = analyzer.run_analysis(
        start_date=start_date,
        end_date=end_date,
        use_api=use_api,
        profit_threshold=5.0
    )
    
    if 'error' in result:
        print(f"❌ 분석 실패: {result['error']}")
        return False
    else:
        print("✅ 분석 완료!")
        print(f"   결과 저장 위치: {analyzer.output_dir}")
        return True


def run_custom_analysis():
    """사용자 정의 분석 실행"""
    print("=== 사용자 정의 분석 ===")
    
    # 시작 날짜 입력
    while True:
        start_date = input("시작 날짜를 입력하세요 (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(start_date, '%Y-%m-%d')
            break
        except ValueError:
            print("❌ 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.")
    
    # 종료 날짜 입력
    while True:
        end_date = input("종료 날짜를 입력하세요 (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(end_date, '%Y-%m-%d')
            break
        except ValueError:
            print("❌ 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.")
    
    # API 사용 여부
    use_api_input = input("API를 사용하시겠습니까? (y/N): ").strip().lower()
    use_api = use_api_input in ['y', 'yes']
    
    # 수익률 임계값
    while True:
        try:
            profit_threshold = float(input("수익률 임계값을 입력하세요 (%): ").strip())
            break
        except ValueError:
            print("❌ 숫자를 입력하세요.")
    
    print(f"\n🚀 분석 시작: {start_date} ~ {end_date}")
    print(f"   API 사용: {'예' if use_api else '아니오'}")
    print(f"   수익률 임계값: {profit_threshold}%")
    
    analyzer = StockAnalysisScript()
    result = analyzer.run_analysis(
        start_date=start_date,
        end_date=end_date,
        use_api=use_api,
        profit_threshold=profit_threshold
    )
    
    if 'error' in result:
        print(f"❌ 분석 실패: {result['error']}")
        return False
    else:
        print("✅ 분석 완료!")
        print(f"   결과 저장 위치: {analyzer.output_dir}")
        return True


def main():
    """메인 메뉴"""
    print("=== 주식 분석 스크립트 ===")
    print("1. 빠른 분석 (최근 7일, API 사용 안함)")
    print("2. 빠른 분석 (최근 7일, API 사용)")
    print("3. 빠른 분석 (최근 30일, API 사용 안함)")
    print("4. 사용자 정의 분석")
    print("5. 종료")
    
    while True:
        choice = input("\n선택하세요 (1-5): ").strip()
        
        if choice == '1':
            run_quick_analysis(days=7, use_api=False)
            break
        elif choice == '2':
            run_quick_analysis(days=7, use_api=True)
            break
        elif choice == '3':
            run_quick_analysis(days=30, use_api=False)
            break
        elif choice == '4':
            run_custom_analysis()
            break
        elif choice == '5':
            print("👋 종료합니다.")
            break
        else:
            print("❌ 올바른 선택지를 입력하세요 (1-5)")


if __name__ == "__main__":
    main()
