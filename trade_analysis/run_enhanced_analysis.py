"""
향상된 분석 실행 스크립트
1. 데이터 수집 확장
2. 향상된 특성 추출
3. 머신러닝 모델 학습
4. 필터 규칙 생성
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from trade_analysis.data_collection_automation import DataCollectionAutomation
from trade_analysis.enhanced_pattern_analyzer import EnhancedPatternAnalyzer
from utils.logger import setup_logger

def main():
    """향상된 분석 실행"""
    logger = setup_logger(__name__)
    
    try:
        logger.info("🚀 향상된 패턴 분석 시작")
        
        # 1. 데이터 수집 확장 (선택사항)
        collect_new_data = input("새로운 데이터를 수집하시겠습니까? (y/n): ").lower() == 'y'
        
        if collect_new_data:
            logger.info("📊 확장된 데이터 수집 시작...")
            collector = DataCollectionAutomation(logger)
            
            # 3개월 데이터 수집
            start_date = "20240601"  # 6월 1일
            end_date = "20250917"    # 9월 17일
            
            stock_data, index_data = collector.collect_market_data(start_date, end_date)
            logger.info(f"✅ 데이터 수집 완료: {len(stock_data)}개 종목, {len(index_data)}개 지수")
        
        # 2. 향상된 패턴 분석
        logger.info("🔍 향상된 패턴 분석 시작...")
        analyzer = EnhancedPatternAnalyzer(logger)
        
        # 분석 실행
        results = analyzer.analyze_patterns()
        
        if results:
            # 3. 결과 출력
            print("\n" + "="*80)
            print("📊 향상된 일봉 기반 승리/패배 패턴 분석 결과")
            print("="*80)
            print(f"총 패턴 수: {results['total_patterns']}")
            print(f"승리 패턴: {results['win_patterns']}")
            print(f"패배 패턴: {results['loss_patterns']}")
            print(f"전체 승률: {results['win_rate']:.1%}")
            print(f"총 특성 수: {results['total_features']}")
            print(f"유의한 특성 수: {results['significant_features']}")
            
            # 상위 특성 출력
            print("\n🔝 상위 특성:")
            for i, feature_info in enumerate(results['top_features'][:15], 1):
                feature = feature_info['feature']
                analysis = feature_info['analysis']
                print(f"{i:2d}. {feature}")
                print(f"    승리 평균: {analysis['win_mean']:.3f}")
                print(f"    패배 평균: {analysis['loss_mean']:.3f}")
                print(f"    차이: {analysis['difference']:+.3f}")
                print(f"    가중치: {analysis['normalized_weight']:.3f}")
                print(f"    유의성: {'✅' if analysis['significance'] else '❌'}")
                print(f"    효과크기: {analysis['effect_size']:.3f}")
                print()
            
            # 머신러닝 모델 결과
            if 'ml_model' in results and results['ml_model']:
                ml_result = results['ml_model']
                print("🤖 머신러닝 모델 성능:")
                print(f"  - 교차검증 평균: {ml_result['cv_mean']:.3f} ± {ml_result['cv_std']:.3f}")
                print(f"  - 정확도: {ml_result['accuracy']:.3f}")
                print(f"  - 선택된 특성 수: {ml_result['n_features']}")
                print()
                
                # 특성 중요도 출력
                if 'feature_importance' in ml_result:
                    print("🎯 특성 중요도 (상위 10개):")
                    sorted_features = sorted(
                        ml_result['feature_importance'].items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                    for i, (feature, importance) in enumerate(sorted_features[:10], 1):
                        print(f"  {i:2d}. {feature}: {importance:.3f}")
                    print()
            
            # 필터 규칙 생성 및 출력
            filter_rules = analyzer.generate_enhanced_filter_rules(results)
            if filter_rules:
                print("🎯 생성된 향상된 필터 규칙:")
                for feature, rule in filter_rules.items():
                    print(f"• {rule['description']} (가중치: {rule['weight']:.3f})")
                print()
            
            # 4. 개선 제안
            print("💡 개선 제안:")
            if results['significant_features'] < 5:
                print("  - 유의한 특성이 부족합니다. 더 많은 데이터 수집이 필요합니다.")
            if results['win_rate'] < 0.5:
                print("  - 승률이 낮습니다. 필터 규칙을 더 엄격하게 적용하세요.")
            if results['total_patterns'] < 200:
                print("  - 패턴 수가 부족합니다. 더 긴 기간의 데이터를 수집하세요.")
            
            print("\n✅ 향상된 분석 완료!")
            
        else:
            logger.error("❌ 분석할 데이터가 없습니다.")
            
    except Exception as e:
        logger.error(f"향상된 분석 실행 실패: {e}")
        raise

if __name__ == "__main__":
    main()
