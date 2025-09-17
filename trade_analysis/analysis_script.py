#!/usr/bin/env python3
"""
주식 분석 스크립트
날짜 범위별 후보 종목 데이터를 수집하고 승리/패배 종목 간 차이점을 시각화
"""
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any
import sys
import warnings

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from data_collector import AnalysisDataCollector
from data_loader import AnalysisDataLoader
from utils.logger import setup_logger

# 경고 메시지 숨기기
warnings.filterwarnings('ignore')

# 한글 폰트 설정
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

logger = setup_logger(__name__)


class StockAnalysisScript:
    """주식 분석 스크립트"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.collector = AnalysisDataCollector()
        self.loader = AnalysisDataLoader()
        
        # 결과 저장 디렉토리
        self.output_dir = Path(__file__).parent / "analysis_results"
        self.output_dir.mkdir(exist_ok=True)
        
        self.logger.info("주식 분석 스크립트 초기화 완료")
    
    def run_analysis(self, start_date: str, end_date: str, use_api: bool = True, 
                    profit_threshold: float = 5.0) -> Dict[str, Any]:
        """
        전체 분석 실행
        
        Args:
            start_date: 시작 날짜 (YYYY-MM-DD)
            end_date: 종료 날짜 (YYYY-MM-DD)
            use_api: API 사용 여부
            profit_threshold: 수익률 임계값 (%)
            
        Returns:
            Dict: 분석 결과
        """
        self.logger.info(f"분석 시작: {start_date} ~ {end_date}")
        
        # 1. 데이터 수집
        self.logger.info("1단계: 데이터 수집")
        collected_data = self.collector.collect_analysis_data(start_date, end_date, use_api)
        
        if collected_data['candidate_stocks'].empty:
            self.logger.warning("수집된 후보 종목이 없습니다.")
            return {'error': 'no_candidates'}
        
        # 2. 분석용 데이터셋 생성
        self.logger.info("2단계: 분석용 데이터셋 생성")
        analysis_df = self.loader.create_analysis_dataset(collected_data)
        
        if analysis_df.empty:
            self.logger.warning("분석용 데이터셋 생성 실패")
            return {'error': 'dataset_creation_failed'}
        
        # 3. 승리/패배 종목 분류
        self.logger.info("3단계: 승리/패배 종목 분류")
        classified_df = self._classify_stocks(analysis_df, profit_threshold)
        
        # 4. 차이점 분석
        self.logger.info("4단계: 차이점 분석")
        difference_analysis = self._analyze_differences(classified_df)
        
        # 5. 시각화
        self.logger.info("5단계: 시각화")
        visualization_results = self._create_visualizations(classified_df, difference_analysis)
        
        # 6. 결과 저장
        self.logger.info("6단계: 결과 저장")
        self._save_results(classified_df, difference_analysis, visualization_results)
        
        return {
            'classified_data': classified_df,
            'difference_analysis': difference_analysis,
            'visualization_results': visualization_results,
            'collection_stats': collected_data['collection_stats']
        }
    
    def _classify_stocks(self, analysis_df: pd.DataFrame, profit_threshold: float) -> pd.DataFrame:
        """승리/패배 종목 분류"""
        df = analysis_df.copy()
        
        # 수익률 기준으로 분류
        df['is_winner'] = df['price_change_rate'] >= profit_threshold
        df['is_loser'] = df['price_change_rate'] <= -profit_threshold
        df['is_neutral'] = (df['price_change_rate'] > -profit_threshold) & (df['price_change_rate'] < profit_threshold)
        
        # 분류 결과 통계
        winner_count = df['is_winner'].sum()
        loser_count = df['is_loser'].sum()
        neutral_count = df['is_neutral'].sum()
        
        self.logger.info(f"종목 분류 결과:")
        self.logger.info(f"  승리 종목: {winner_count}개 ({winner_count/len(df)*100:.1f}%)")
        self.logger.info(f"  패배 종목: {loser_count}개 ({loser_count/len(df)*100:.1f}%)")
        self.logger.info(f"  중립 종목: {neutral_count}개 ({neutral_count/len(df)*100:.1f}%)")
        
        return df
    
    def _analyze_differences(self, classified_df: pd.DataFrame) -> Dict[str, Any]:
        """승리/패배 종목 간 차이점 분석"""
        analysis = {}
        
        # 승리/패배 종목 분리
        winners = classified_df[classified_df['is_winner']]
        losers = classified_df[classified_df['is_loser']]
        
        if winners.empty or losers.empty:
            self.logger.warning("승리 또는 패배 종목이 없어 차이점 분석을 수행할 수 없습니다.")
            return analysis
        
        # 수치형 컬럼들
        numeric_columns = [
            'score', 'price_change_rate', 'volatility', 'rsi', 'ma5', 'ma20',
            'up_days', 'down_days', 'max_consecutive_up', 'max_consecutive_down',
            'total_volume', 'avg_volume', 'minute_volatility'
        ]
        
        # 존재하는 컬럼만 선택
        available_columns = [col for col in numeric_columns if col in classified_df.columns]
        
        differences = {}
        for col in available_columns:
            if col in winners.columns and col in losers.columns:
                winner_mean = winners[col].mean()
                loser_mean = losers[col].mean()
                
                # 통계적 유의성 검정 (간단한 t-test)
                try:
                    from scipy import stats
                    t_stat, p_value = stats.ttest_ind(winners[col].dropna(), losers[col].dropna())
                    
                    differences[col] = {
                        'winner_mean': float(winner_mean),
                        'loser_mean': float(loser_mean),
                        'difference': float(winner_mean - loser_mean),
                        'difference_pct': float((winner_mean - loser_mean) / abs(loser_mean) * 100) if loser_mean != 0 else 0,
                        't_statistic': float(t_stat),
                        'p_value': float(p_value),
                        'is_significant': p_value < 0.05
                    }
                except:
                    differences[col] = {
                        'winner_mean': float(winner_mean),
                        'loser_mean': float(loser_mean),
                        'difference': float(winner_mean - loser_mean),
                        'difference_pct': float((winner_mean - loser_mean) / abs(loser_mean) * 100) if loser_mean != 0 else 0,
                        't_statistic': None,
                        'p_value': None,
                        'is_significant': False
                    }
        
        analysis['differences'] = differences
        analysis['summary'] = {
            'winner_count': len(winners),
            'loser_count': len(losers),
            'significant_differences': sum(1 for d in differences.values() if d.get('is_significant', False))
        }
        
        self.logger.info(f"차이점 분석 완료: {analysis['summary']['significant_differences']}개 유의한 차이 발견")
        
        return analysis
    
    def _create_visualizations(self, classified_df: pd.DataFrame, difference_analysis: Dict[str, Any]) -> Dict[str, str]:
        """시각화 생성"""
        results = {}
        
        try:
            # 1. 수익률 분포 히스토그램
            fig, ax = plt.subplots(figsize=(12, 6))
            
            winners = classified_df[classified_df['is_winner']]
            losers = classified_df[classified_df['is_loser']]
            neutrals = classified_df[classified_df['is_neutral']]
            
            if not winners.empty:
                ax.hist(winners['price_change_rate'], bins=20, alpha=0.7, label=f'승리 ({len(winners)}개)', color='green')
            if not losers.empty:
                ax.hist(losers['price_change_rate'], bins=20, alpha=0.7, label=f'패배 ({len(losers)}개)', color='red')
            if not neutrals.empty:
                ax.hist(neutrals['price_change_rate'], bins=20, alpha=0.7, label=f'중립 ({len(neutrals)}개)', color='gray')
            
            ax.set_xlabel('수익률 (%)')
            ax.set_ylabel('종목 수')
            ax.set_title('수익률 분포')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            chart_path = self.output_dir / f"profit_distribution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            plt.savefig(chart_path, dpi=300, bbox_inches='tight')
            plt.close()
            results['profit_distribution'] = str(chart_path)
            
            # 2. 주요 지표 비교 박스플롯
            if 'differences' in difference_analysis:
                significant_metrics = [k for k, v in difference_analysis['differences'].items() 
                                     if v.get('is_significant', False) and k in classified_df.columns]
                
                if significant_metrics:
                    n_metrics = min(6, len(significant_metrics))  # 최대 6개 지표
                    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
                    axes = axes.flatten()
                    
                    for i, metric in enumerate(significant_metrics[:n_metrics]):
                        if i >= len(axes):
                            break
                            
                        ax = axes[i]
                        
                        # 박스플롯 데이터 준비
                        winner_data = winners[metric].dropna()
                        loser_data = losers[metric].dropna()
                        
                        if not winner_data.empty and not loser_data.empty:
                            data_to_plot = [winner_data, loser_data]
                            labels = ['승리', '패배']
                            
                            bp = ax.boxplot(data_to_plot, labels=labels, patch_artist=True)
                            bp['boxes'][0].set_facecolor('lightgreen')
                            bp['boxes'][1].set_facecolor('lightcoral')
                            
                            ax.set_title(f'{metric}')
                            ax.grid(True, alpha=0.3)
                    
                    # 빈 subplot 제거
                    for i in range(n_metrics, len(axes)):
                        axes[i].remove()
                    
                    plt.tight_layout()
                    chart_path = self.output_dir / f"metrics_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                    plt.close()
                    results['metrics_comparison'] = str(chart_path)
            
            # 3. 상관관계 히트맵
            numeric_cols = classified_df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 1:
                fig, ax = plt.subplots(figsize=(12, 10))
                
                correlation_matrix = classified_df[numeric_cols].corr()
                if HAS_SEABORN:
                    sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', center=0, 
                               square=True, ax=ax, fmt='.2f')
                else:
                    # seaborn이 없는 경우 matplotlib으로 대체
                    im = ax.imshow(correlation_matrix, cmap='coolwarm', aspect='auto')
                    ax.set_xticks(range(len(correlation_matrix.columns)))
                    ax.set_yticks(range(len(correlation_matrix.index)))
                    ax.set_xticklabels(correlation_matrix.columns, rotation=45)
                    ax.set_yticklabels(correlation_matrix.index)
                    plt.colorbar(im, ax=ax)
                
                ax.set_title('지표 간 상관관계')
                plt.tight_layout()
                chart_path = self.output_dir / f"correlation_heatmap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                plt.close()
                results['correlation_heatmap'] = str(chart_path)
            
            # 4. 점수별 수익률 산점도
            if 'score' in classified_df.columns and 'price_change_rate' in classified_df.columns:
                fig, ax = plt.subplots(figsize=(12, 8))
                
                # 승리/패배/중립별로 다른 색상
                colors = ['red' if x else 'green' if y else 'gray' 
                         for x, y in zip(classified_df['is_loser'], classified_df['is_winner'])]
                
                scatter = ax.scatter(classified_df['score'], classified_df['price_change_rate'], 
                                   c=colors, alpha=0.6, s=50)
                
                ax.set_xlabel('선정 점수')
                ax.set_ylabel('수익률 (%)')
                ax.set_title('선정 점수 vs 수익률')
                ax.grid(True, alpha=0.3)
                
                # 범례 추가
                from matplotlib.patches import Patch
                legend_elements = [Patch(facecolor='green', label='승리'),
                                 Patch(facecolor='red', label='패배'),
                                 Patch(facecolor='gray', label='중립')]
                ax.legend(handles=legend_elements)
                
                plt.tight_layout()
                chart_path = self.output_dir / f"score_vs_profit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                plt.savefig(chart_path, dpi=300, bbox_inches='tight')
                plt.close()
                results['score_vs_profit'] = str(chart_path)
            
            self.logger.info(f"시각화 생성 완료: {len(results)}개 차트")
            
        except Exception as e:
            self.logger.error(f"시각화 생성 실패: {e}")
        
        return results
    
    def _save_results(self, classified_df: pd.DataFrame, difference_analysis: Dict[str, Any], 
                     visualization_results: Dict[str, str]):
        """결과 저장"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # 1. 분류된 데이터 저장
            csv_path = self.output_dir / f"classified_stocks_{timestamp}.csv"
            classified_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            self.logger.info(f"분류된 데이터 저장: {csv_path}")
            
            # 2. 차이점 분석 결과 저장
            if 'differences' in difference_analysis:
                diff_df = pd.DataFrame(difference_analysis['differences']).T
                diff_csv_path = self.output_dir / f"difference_analysis_{timestamp}.csv"
                diff_df.to_csv(diff_csv_path, encoding='utf-8-sig')
                self.logger.info(f"차이점 분석 결과 저장: {diff_csv_path}")
            
            # 3. 요약 보고서 생성
            self._create_summary_report(classified_df, difference_analysis, visualization_results, timestamp)
            
        except Exception as e:
            self.logger.error(f"결과 저장 실패: {e}")
    
    def _create_summary_report(self, classified_df: pd.DataFrame, difference_analysis: Dict[str, Any], 
                              visualization_results: Dict[str, str], timestamp: str):
        """요약 보고서 생성"""
        try:
            report_path = self.output_dir / f"analysis_report_{timestamp}.txt"
            
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("=== 주식 분석 보고서 ===\n\n")
                f.write(f"생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # 기본 통계
                f.write("=== 기본 통계 ===\n")
                f.write(f"전체 종목 수: {len(classified_df)}\n")
                f.write(f"승리 종목: {classified_df['is_winner'].sum()}개 ({classified_df['is_winner'].mean()*100:.1f}%)\n")
                f.write(f"패배 종목: {classified_df['is_loser'].sum()}개 ({classified_df['is_loser'].mean()*100:.1f}%)\n")
                f.write(f"중립 종목: {classified_df['is_neutral'].sum()}개 ({classified_df['is_neutral'].mean()*100:.1f}%)\n\n")
                
                # 수익률 통계
                f.write("=== 수익률 통계 ===\n")
                f.write(f"평균 수익률: {classified_df['price_change_rate'].mean():.2f}%\n")
                f.write(f"중간값 수익률: {classified_df['price_change_rate'].median():.2f}%\n")
                f.write(f"최고 수익률: {classified_df['price_change_rate'].max():.2f}%\n")
                f.write(f"최저 수익률: {classified_df['price_change_rate'].min():.2f}%\n\n")
                
                # 차이점 분석
                if 'differences' in difference_analysis:
                    f.write("=== 주요 차이점 ===\n")
                    significant_diffs = {k: v for k, v in difference_analysis['differences'].items() 
                                       if v.get('is_significant', False)}
                    
                    for metric, diff in significant_diffs.items():
                        f.write(f"{metric}:\n")
                        f.write(f"  승리 종목 평균: {diff['winner_mean']:.2f}\n")
                        f.write(f"  패배 종목 평균: {diff['loser_mean']:.2f}\n")
                        f.write(f"  차이: {diff['difference']:.2f} ({diff['difference_pct']:.1f}%)\n")
                        f.write(f"  p-value: {diff['p_value']:.4f}\n\n")
                
                # 생성된 차트
                f.write("=== 생성된 차트 ===\n")
                for chart_name, chart_path in visualization_results.items():
                    f.write(f"{chart_name}: {chart_path}\n")
            
            self.logger.info(f"요약 보고서 생성: {report_path}")
            
        except Exception as e:
            self.logger.error(f"요약 보고서 생성 실패: {e}")


def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(description="주식 분석 스크립트")
    parser.add_argument('--start-date', type=str, required=True, help='시작 날짜 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='종료 날짜 (YYYY-MM-DD)')
    parser.add_argument('--use-api', action='store_true', help='API 사용 여부')
    parser.add_argument('--profit-threshold', type=float, default=5.0, help='수익률 임계값 (%)')
    
    args = parser.parse_args()
    
    # 날짜 형식 검증
    try:
        datetime.strptime(args.start_date, '%Y-%m-%d')
        datetime.strptime(args.end_date, '%Y-%m-%d')
    except ValueError:
        print("❌ 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.")
        return
    
    # 분석 실행
    analyzer = StockAnalysisScript()
    result = analyzer.run_analysis(
        start_date=args.start_date,
        end_date=args.end_date,
        use_api=args.use_api,
        profit_threshold=args.profit_threshold
    )
    
    if 'error' in result:
        print(f"❌ 분석 실패: {result['error']}")
    else:
        print("✅ 분석 완료!")
        print(f"  결과 저장 위치: {analyzer.output_dir}")
        
        if 'collection_stats' in result:
            stats = result['collection_stats']
            print(f"  수집 통계:")
            print(f"    후보 종목: {stats['total_candidates']}개")
            print(f"    일봉 성공률: {stats['daily_success_rate']:.1f}%")
            print(f"    분봉 성공률: {stats['minute_success_rate']:.1f}%")


if __name__ == "__main__":
    main()
