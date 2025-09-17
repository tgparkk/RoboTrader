"""
기존 데이터를 활용한 분석 실행
KIS API 인증 없이 기존 캐시 데이터로 분석 수행
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from trade_analysis.daily_pattern_analyzer import DailyPatternAnalyzer
from utils.logger import setup_logger

def main():
    """기존 데이터를 활용한 분석 실행"""
    logger = setup_logger(__name__)
    
    try:
        logger.info("🚀 기존 데이터를 활용한 패턴 분석 시작")
        
        # 기존 분석기 사용 (API 호출 없이)
        analyzer = DailyPatternAnalyzer(logger)
        
        # 분석 실행
        results = analyzer.analyze_patterns()
        
        if results:
            # 결과 출력
            print("\n" + "="*80)
            print("📊 기존 데이터를 활용한 패턴 분석 결과")
            print("="*80)
            print(f"총 패턴 수: {results['total_patterns']}")
            print(f"승리 패턴: {results['win_patterns']}")
            print(f"패배 패턴: {results['loss_patterns']}")
            print(f"전체 승률: {results['win_rate']:.1%}")
            
            # 상위 특성 출력
            if 'top_features' in results:
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
                    print()
            
            # 개선 제안
            print("\n💡 개선 제안:")
            if results['win_rate'] < 0.5:
                print("  - 승률이 낮습니다. 필터 규칙을 더 엄격하게 적용하세요.")
            if results['total_patterns'] < 200:
                print("  - 패턴 수가 부족합니다. 더 긴 기간의 데이터를 수집하세요.")
            
            print("\n✅ 기존 데이터 분석 완료!")
            
        else:
            logger.error("❌ 분석할 데이터가 없습니다.")
            
    except Exception as e:
        logger.error(f"기존 데이터 분석 실행 실패: {e}")
        raise

if __name__ == "__main__":
    main()
