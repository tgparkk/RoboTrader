"""
자동 데이터 수집 통합 분석 실행 스크립트
일봉 데이터가 없으면 자동으로 수집한 후 분석 수행
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from trade_analysis.enhanced_analyzer_with_auto_collection import EnhancedAnalyzerWithAutoCollection
from utils.logger import setup_logger

def main():
    """자동 데이터 수집 통합 분석 실행"""
    logger = setup_logger(__name__)
    
    try:
        logger.info("🚀 자동 데이터 수집 통합 분석 시작")
        
        # 분석기 초기화
        analyzer = EnhancedAnalyzerWithAutoCollection(logger)
        
        # 분석 실행 (자동 데이터 수집 포함)
        results = analyzer.analyze_with_auto_collection(
            log_dir="signal_replay_log",
            start_date="20240601",  # 6월 1일부터
            end_date="20250917"     # 9월 17일까지
        )
        
        if results:
            # 결과 출력
            print("\n" + "="*80)
            print("📊 자동 데이터 수집 통합 향상된 패턴 분석 결과")
            print("="*80)
            print(f"총 패턴 수: {results['total_patterns']}")
            print(f"승리 패턴: {results['win_patterns']}")
            print(f"패배 패턴: {results['loss_patterns']}")
            print(f"전체 승률: {results['win_rate']:.1%}")
            print(f"처리된 종목: {results['processed_stocks']}개")
            print(f"건너뜀: {results['skipped_logs']}건")
        if 'total_features' in results:
            print(f"총 특성 수: {results['total_features']}")
        if 'significant_features' in results:
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
            
            # 데이터 수집 결과
            if 'collection_results' in results:
                collection_results = results['collection_results']
                successful_collections = sum(collection_results.values())
                total_collections = len(collection_results)
                print(f"📈 데이터 수집 결과: {successful_collections}/{total_collections}개 성공")
                
                if successful_collections < total_collections:
                    failed_stocks = [stock for stock, success in collection_results.items() if not success]
                    print(f"❌ 수집 실패한 종목: {len(failed_stocks)}개")
                    if len(failed_stocks) <= 10:
                        print(f"   {', '.join(failed_stocks)}")
                    else:
                        print(f"   {', '.join(failed_stocks[:10])} ... (총 {len(failed_stocks)}개)")
            
            # 품질 보고서
            if 'quality_report' in results:
                quality_report = results['quality_report']
                good_quality_count = sum(1 for report in quality_report.values() 
                                       if report['status'] == 'ok' and report['quality_score'] > 0.5)
                print(f"📊 데이터 품질: {good_quality_count}/{len(quality_report)}개 종목 양호")
            
            # 개선 제안
            print("\n💡 개선 제안:")
            if results['significant_features'] < 5:
                print("  - 유의한 특성이 부족합니다. 더 많은 데이터 수집이 필요합니다.")
            if results['win_rate'] < 0.5:
                print("  - 승률이 낮습니다. 필터 규칙을 더 엄격하게 적용하세요.")
            if results['total_patterns'] < 200:
                print("  - 패턴 수가 부족합니다. 더 긴 기간의 데이터를 수집하세요.")
            if results['skipped_logs'] > results['total_patterns']:
                print("  - 건너뜀 비율이 높습니다. 일봉 데이터 수집을 개선하세요.")
            
            print("\n✅ 자동 데이터 수집 통합 분석 완료!")
            
        else:
            logger.error("❌ 분석할 데이터가 없습니다.")
            
    except Exception as e:
        logger.error(f"자동 데이터 수집 통합 분석 실행 실패: {e}")
        raise

if __name__ == "__main__":
    main()
