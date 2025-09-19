"""
종합 승패 분석기 - 향상된 일봉 특성 포함

기존 분석에 더 구체적이고 코드화 가능한 일봉 특성들을 추가하여
실전에서 활용 가능한 매매 규칙을 도출합니다.
"""

import os
import re
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
import matplotlib.pyplot as plt
from dataclasses import dataclass
import json

# 향상된 일봉 분석기 임포트
from enhanced_daily_analyzer import EnhancedDailyAnalyzer

@dataclass
class TradeResult:
    """매매 결과 데이터 클래스"""
    stock_code: str
    date: str
    signal_time: str
    signal_type: str
    buy_price: float
    sell_price: float
    return_pct: float
    is_win: bool
    sell_reason: str

class ComprehensiveWinLossAnalyzer:
    """종합 승패 분석기"""

    def __init__(self):
        self.logger = self._setup_logger()
        self.signal_log_dir = Path("signal_replay_log")
        self.cache_dir = Path("cache")
        self.minute_data_dir = self.cache_dir / "minute_data"
        self.daily_data_dir = self.cache_dir / "daily"
        self.output_dir = Path("comprehensive_analysis_results")
        self.output_dir.mkdir(exist_ok=True)

        # 향상된 일봉 분석기
        self.daily_analyzer = EnhancedDailyAnalyzer()

        # 매매 결과 저장
        self.trade_results: List[TradeResult] = []

    def _setup_logger(self):
        """로거 설정"""
        import logging
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def extract_trade_results_from_logs(self) -> List[TradeResult]:
        """signal replay log에서 매매 결과 추출"""
        trade_results = []

        for log_file in self.signal_log_dir.glob("signal_new2_replay_*.txt"):
            self.logger.info(f"Processing {log_file.name}")

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 날짜 추출 (파일명에서)
                date_match = re.search(r'(\d{8})', log_file.name)
                if not date_match:
                    continue
                trade_date = date_match.group(1)

                # 각 종목별 매매 결과 추출
                stock_sections = re.split(r'=== (\d{6}) - \d{8}', content)[1:]

                for i in range(0, len(stock_sections), 2):
                    if i + 1 >= len(stock_sections):
                        break

                    stock_code = stock_sections[i]
                    section_content = stock_sections[i + 1]

                    # 체결 시뮬레이션에서 매매 결과 추출
                    simulation_matches = re.findall(
                        r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([0-9,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([0-9,]+) \(([+-]\d+\.\d+)%\)',
                        section_content
                    )

                    for match in simulation_matches:
                        buy_time, signal_type, buy_price_str, sell_time, sell_reason, sell_price_str, return_pct_str = match

                        buy_price = float(buy_price_str.replace(',', ''))
                        sell_price = float(sell_price_str.replace(',', ''))
                        return_pct = float(return_pct_str)
                        is_win = return_pct > 0

                        trade_result = TradeResult(
                            stock_code=stock_code,
                            date=trade_date,
                            signal_time=buy_time,
                            signal_type=signal_type,
                            buy_price=buy_price,
                            sell_price=sell_price,
                            return_pct=return_pct,
                            is_win=is_win,
                            sell_reason=sell_reason
                        )

                        trade_results.append(trade_result)

            except Exception as e:
                self.logger.error(f"Error processing {log_file.name}: {e}")
                continue

        self.logger.info(f"Extracted {len(trade_results)} trade results")
        return trade_results

    def load_minute_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """분봉 데이터 로드"""
        file_path = self.minute_data_dir / f"{stock_code}_{date}.pkl"
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'rb') as f:
                df = pickle.load(f)
            return df
        except Exception as e:
            self.logger.error(f"Error loading minute data {file_path}: {e}")
            return None

    def calculate_minute_features(self, minute_df: pd.DataFrame, signal_time: str) -> Dict[str, float]:
        """분봉 특성 계산 (기존과 동일)"""
        if minute_df is None or minute_df.empty:
            return {}

        try:
            # 신호 시점 찾기
            signal_hour, signal_min = map(int, signal_time.split(':'))
            signal_time_str = f"{signal_hour:02d}{signal_min:02d}00"

            signal_idx = minute_df[minute_df['time'] == signal_time_str].index
            if len(signal_idx) == 0:
                return {}

            signal_idx = signal_idx[0]

            # 기준 거래량 (당일 최대 거래량)
            base_volume = minute_df['volume'].max()

            # 현재 거래량 비율
            current_volume = minute_df.loc[signal_idx, 'volume']
            volume_ratio = current_volume / base_volume if base_volume > 0 else 0

            # 최근 5분봉의 캔들 크기 변화 추세
            recent_candles = minute_df.loc[max(0, signal_idx-4):signal_idx]
            candle_sizes = (recent_candles['high'] - recent_candles['low']) / recent_candles['close']
            candle_size_trend = np.polyfit(range(len(candle_sizes)), candle_sizes, 1)[0] if len(candle_sizes) > 1 else 0

            # 이등분선 계산 (당일 고점과 저점의 중간)
            day_high = minute_df['high'].max()
            day_low = minute_df['low'].min()
            bisector = (day_high + day_low) / 2
            current_price = minute_df.loc[signal_idx, 'close']
            bisector_position = (current_price - bisector) / bisector if bisector > 0 else 0

            # 거래량 급감 비율 (최근 10분봉 평균 대비 현재)
            recent_volume_avg = minute_df.loc[max(0, signal_idx-9):signal_idx-1, 'volume'].mean()
            volume_decrease_ratio = current_volume / recent_volume_avg if recent_volume_avg > 0 else 1

            return {
                'minute_volume_ratio': volume_ratio,
                'minute_candle_size_trend': candle_size_trend,
                'minute_bisector_position': bisector_position,
                'minute_volume_decrease_ratio': volume_decrease_ratio
            }

        except Exception as e:
            self.logger.error(f"Error calculating minute features: {e}")
            return {}

    def analyze_all_trades(self):
        """모든 매매 종합 분석"""
        self.logger.info("Starting comprehensive trade analysis with enhanced daily features")

        # 매매 결과 추출
        self.trade_results = self.extract_trade_results_from_logs()

        analysis_data = []

        for trade in self.trade_results:
            # 분봉 데이터 로드 및 특성 계산
            minute_df = self.load_minute_data(trade.stock_code, trade.date)

            if minute_df is None:
                self.logger.warning(f"No minute data for {trade.stock_code}_{trade.date}")
                continue

            minute_features = self.calculate_minute_features(minute_df, trade.signal_time)

            # 향상된 일봉 특성 계산
            daily_features = self.daily_analyzer.extract_all_daily_features(trade.stock_code, trade.date)

            # 모든 특성 통합
            all_features = {
                'stock_code': trade.stock_code,
                'date': trade.date,
                'signal_time': trade.signal_time,
                'return_pct': trade.return_pct,
                'is_win': trade.is_win,
                'sell_reason': trade.sell_reason,
                **minute_features,
                **daily_features
            }

            analysis_data.append(all_features)

        # DataFrame 생성
        df = pd.DataFrame(analysis_data)

        if df.empty:
            self.logger.error("No analysis data generated")
            return

        # 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV 저장
        csv_path = self.output_dir / f"comprehensive_analysis_{timestamp}.csv"
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        self.logger.info(f"Analysis data saved to {csv_path}")

        # 승패 비교 분석
        self.compare_win_loss_patterns(df, timestamp)

        return df

    def compare_win_loss_patterns(self, df: pd.DataFrame, timestamp: str):
        """승패 패턴 비교 분석"""
        wins = df[df['is_win'] == True]
        losses = df[df['is_win'] == False]

        self.logger.info(f"Analyzing {len(wins)} wins vs {len(losses)} losses")

        # 수치형 컬럼만 선택
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        feature_cols = [col for col in numeric_cols if col not in ['return_pct', 'is_win']]

        # 승패별 평균 비교
        comparison_results = []

        for col in feature_cols:
            if col in wins.columns and col in losses.columns:
                win_data = wins[col].dropna()
                loss_data = losses[col].dropna()

                if len(win_data) == 0 or len(loss_data) == 0:
                    continue

                win_mean = win_data.mean()
                loss_mean = loss_data.mean()
                difference = win_mean - loss_mean

                # t-test (간단한 유의성 검정)
                from scipy import stats
                try:
                    t_stat, p_value = stats.ttest_ind(win_data, loss_data)
                except:
                    t_stat, p_value = 0, 1

                comparison_results.append({
                    'feature': col,
                    'win_mean': win_mean,
                    'loss_mean': loss_mean,
                    'difference': difference,
                    'p_value': p_value,
                    'significant': p_value < 0.05,
                    'win_count': len(win_data),
                    'loss_count': len(loss_data)
                })

        # 결과 정렬 (유의성 우선, 차이 크기 순)
        comparison_results.sort(key=lambda x: (x['significant'], abs(x['difference'])), reverse=True)

        # 결과 저장
        comparison_df = pd.DataFrame(comparison_results)
        comparison_path = self.output_dir / f"feature_comparison_{timestamp}.csv"
        comparison_df.to_csv(comparison_path, index=False, encoding='utf-8-sig')

        # 시각화
        self.create_comprehensive_visualization(df, comparison_results, timestamp)

        # 실전 매매 규칙 생성
        self.generate_trading_rules(comparison_results, timestamp)

        # 요약 보고서
        self.generate_comprehensive_report(comparison_results, timestamp, len(wins), len(losses))

    def create_comprehensive_visualization(self, df: pd.DataFrame, comparison_results: List[Dict], timestamp: str):
        """종합 시각화 생성"""
        plt.rcParams['font.family'] = 'DejaVu Sans'

        # 유의미한 특성들만 선택
        significant_features = [r for r in comparison_results if r['significant']][:12]

        if len(significant_features) < 2:
            self.logger.warning("Not enough significant features for visualization")
            return

        fig, axes = plt.subplots(3, 4, figsize=(24, 18))
        axes = axes.flatten()

        for i, feature_info in enumerate(significant_features):
            if i >= 12:
                break

            feature = feature_info['feature']
            wins = df[df['is_win'] == True][feature].dropna()
            losses = df[df['is_win'] == False][feature].dropna()

            axes[i].hist(wins, alpha=0.7, label=f'Wins (n={len(wins)})', bins=20, color='green', density=True)
            axes[i].hist(losses, alpha=0.7, label=f'Losses (n={len(losses)})', bins=20, color='red', density=True)

            # 평균선 표시
            axes[i].axvline(wins.mean(), color='green', linestyle='--', alpha=0.8)
            axes[i].axvline(losses.mean(), color='red', linestyle='--', alpha=0.8)

            axes[i].set_title(f'{feature}\np={feature_info["p_value"]:.3f}', fontsize=10)
            axes[i].legend(fontsize=8)
            axes[i].grid(True, alpha=0.3)

        # 빈 subplot 숨기기
        for i in range(len(significant_features), 12):
            axes[i].set_visible(False)

        plt.tight_layout()
        viz_path = self.output_dir / f"comprehensive_features_{timestamp}.png"
        plt.savefig(viz_path, dpi=300, bbox_inches='tight')
        plt.close()

        self.logger.info(f"Comprehensive visualization saved to {viz_path}")

    def generate_trading_rules(self, comparison_results: List[Dict], timestamp: str):
        """실전 매매 규칙 생성"""
        rules_path = self.output_dir / f"trading_rules_{timestamp}.py"

        # 유의미한 차이가 있는 특성들
        significant_features = [r for r in comparison_results if r['significant']]

        with open(rules_path, 'w', encoding='utf-8') as f:
            f.write('"""\n')
            f.write('AI 분석 기반 실전 매매 규칙\n')
            f.write(f'생성일시: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write('"""\n\n')

            f.write('def check_winning_conditions(minute_features, daily_features):\n')
            f.write('    """\n')
            f.write('    승리 확률이 높은 조건들을 체크\n')
            f.write('    \n')
            f.write('    Args:\n')
            f.write('        minute_features: 분봉 특성 딕셔너리\n')
            f.write('        daily_features: 일봉 특성 딕셔너리\n')
            f.write('    \n')
            f.write('    Returns:\n')
            f.write('        float: 승리 확률 점수 (0-100)\n')
            f.write('    """\n')
            f.write('    score = 0\n')
            f.write('    max_score = 0\n\n')

            for i, feature in enumerate(significant_features[:10]):  # 상위 10개만
                feature_name = feature['feature']
                win_mean = feature['win_mean']
                loss_mean = feature['loss_mean']
                difference = feature['difference']

                f.write(f'    # {i+1}. {feature_name}\n')
                f.write(f'    # 승리평균: {win_mean:.4f}, 패배평균: {loss_mean:.4f}\n')

                if 'minute_' in feature_name:
                    var_source = 'minute_features'
                elif 'daily_' in feature_name:
                    var_source = 'daily_features'
                else:
                    var_source = 'daily_features'  # 기본값

                if difference > 0:  # 승리 시 더 높은 값
                    threshold = win_mean * 0.8  # 승리 평균의 80%를 임계값으로
                    f.write(f'    if {var_source}.get("{feature_name}", 0) >= {threshold:.4f}:\n')
                    f.write(f'        score += {abs(difference)*1000:.1f}  # 가중치\n')
                else:  # 승리 시 더 낮은 값
                    threshold = win_mean * 1.2  # 승리 평균의 120%를 임계값으로
                    f.write(f'    if {var_source}.get("{feature_name}", 999) <= {threshold:.4f}:\n')
                    f.write(f'        score += {abs(difference)*1000:.1f}  # 가중치\n')

                f.write(f'    max_score += {abs(difference)*1000:.1f}\n\n')

            f.write('    # 정규화된 점수 반환 (0-100)\n')
            f.write('    return (score / max_score * 100) if max_score > 0 else 0\n\n')

            # 간단한 사용 예시
            f.write('def should_buy(minute_features, daily_features, threshold=60):\n')
            f.write('    """\n')
            f.write('    매수 여부 결정\n')
            f.write('    \n')
            f.write('    Args:\n')
            f.write('        threshold: 최소 점수 (기본값: 60)\n')
            f.write('    \n')
            f.write('    Returns:\n')
            f.write('        bool: 매수 여부\n')
            f.write('    """\n')
            f.write('    win_probability = check_winning_conditions(minute_features, daily_features)\n')
            f.write('    return win_probability >= threshold\n\n')

            # 핵심 규칙 요약
            f.write('"""\n')
            f.write('핵심 매매 규칙 요약:\n\n')
            for i, feature in enumerate(significant_features[:5]):
                direction = "높을 때" if feature['difference'] > 0 else "낮을 때"
                f.write(f'{i+1}. {feature["feature"]}: 승리 시 {direction} 유리\n')
            f.write('"""\n')

        self.logger.info(f"Trading rules saved to {rules_path}")

    def generate_comprehensive_report(self, comparison_results: List[Dict], timestamp: str, win_count: int, loss_count: int):
        """종합 보고서 생성"""
        report_path = self.output_dir / f"comprehensive_report_{timestamp}.txt"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=== 종합 승패 분석 보고서 ===\n\n")
            f.write(f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"총 매매 건수: {win_count + loss_count}\n")
            f.write(f"승리: {win_count}건 ({win_count/(win_count+loss_count)*100:.1f}%)\n")
            f.write(f"패배: {loss_count}건 ({loss_count/(win_count+loss_count)*100:.1f}%)\n\n")

            # 통계적으로 유의미한 특성들
            significant_features = [r for r in comparison_results if r['significant']]

            f.write("=== 통계적으로 유의미한 차이점 ===\n")
            for i, result in enumerate(significant_features, 1):
                direction = "↑ 높음" if result['difference'] > 0 else "↓ 낮음"
                f.write(f"{i:2d}. {result['feature']:<30} | "
                       f"승리 시 {direction:6} | "
                       f"차이: {result['difference']:8.4f} | "
                       f"p={result['p_value']:.3f}\n")

            f.write(f"\n총 {len(significant_features)}개의 유의미한 특성 발견\n\n")

            # 카테고리별 분석
            f.write("=== 카테고리별 핵심 인사이트 ===\n\n")

            # 분봉 관련 특성
            minute_features = [r for r in significant_features if 'minute_' in r['feature']]
            if minute_features:
                f.write("📊 분봉 패턴:\n")
                for feature in minute_features[:3]:
                    direction = "높을 때" if feature['difference'] > 0 else "낮을 때"
                    f.write(f"  - {feature['feature']}: 승리 시 {direction} 유리 (p={feature['p_value']:.3f})\n")
                f.write("\n")

            # 일봉 추세 관련
            trend_features = [r for r in significant_features if any(keyword in r['feature'] for keyword in ['trend', 'ma_position', 'breakout'])]
            if trend_features:
                f.write("📈 일봉 추세:\n")
                for feature in trend_features[:3]:
                    direction = "높을 때" if feature['difference'] > 0 else "낮을 때"
                    f.write(f"  - {feature['feature']}: 승리 시 {direction} 유리 (p={feature['p_value']:.3f})\n")
                f.write("\n")

            # 거래량 관련
            volume_features = [r for r in significant_features if 'volume' in r['feature']]
            if volume_features:
                f.write("📊 거래량 패턴:\n")
                for feature in volume_features[:3]:
                    direction = "높을 때" if feature['difference'] > 0 else "낮을 때"
                    f.write(f"  - {feature['feature']}: 승리 시 {direction} 유리 (p={feature['p_value']:.3f})\n")
                f.write("\n")

            # 캔들 패턴 관련
            candle_features = [r for r in significant_features if any(keyword in r['feature'] for keyword in ['doji', 'hammer', 'shooting_star', 'engulfing'])]
            if candle_features:
                f.write("🕯️ 캔들 패턴:\n")
                for feature in candle_features:
                    direction = "True일 때" if feature['difference'] > 0 else "False일 때"
                    f.write(f"  - {feature['feature']}: 승리 시 {direction} 유리 (p={feature['p_value']:.3f})\n")
                f.write("\n")

            # 기술적 지표 관련
            technical_features = [r for r in significant_features if any(keyword in r['feature'] for keyword in ['rsi', 'bollinger', 'macd'])]
            if technical_features:
                f.write("📊 기술적 지표:\n")
                for feature in technical_features:
                    direction = "높을 때" if feature['difference'] > 0 else "낮을 때"
                    f.write(f"  - {feature['feature']}: 승리 시 {direction} 유리 (p={feature['p_value']:.3f})\n")
                f.write("\n")

            # 실전 활용 가이드
            f.write("=== 실전 활용 가이드 ===\n\n")
            f.write("💡 매수 신호 강화 조건:\n")

            top_positive = [r for r in significant_features if r['difference'] > 0][:5]
            for i, feature in enumerate(top_positive, 1):
                f.write(f"{i}. {feature['feature']} >= {feature['win_mean']:.3f}\n")

            f.write("\n⚠️ 매수 회피 조건:\n")

            top_negative = [r for r in significant_features if r['difference'] < 0][:5]
            for i, feature in enumerate(top_negative, 1):
                f.write(f"{i}. {feature['feature']} >= {feature['loss_mean']:.3f}\n")

            f.write(f"\n📁 상세 분석 파일:\n")
            f.write(f"  - 특성 비교: feature_comparison_{timestamp}.csv\n")
            f.write(f"  - 매매 규칙: trading_rules_{timestamp}.py\n")
            f.write(f"  - 시각화: comprehensive_features_{timestamp}.png\n")

        self.logger.info(f"Comprehensive report saved to {report_path}")

def main():
    """메인 실행 함수"""
    analyzer = ComprehensiveWinLossAnalyzer()

    print("Comprehensive win/loss analysis starting...")
    print("Analyzing with enhanced daily features for actionable trading rules.\n")

    try:
        result_df = analyzer.analyze_all_trades()

        if result_df is not None and not result_df.empty:
            wins = len(result_df[result_df['is_win']==True])
            losses = len(result_df[result_df['is_win']==False])

            print(f"Analysis completed!")
            print(f"Total trades: {len(result_df)}")
            print(f"Wins: {wins} ({wins/len(result_df)*100:.1f}%)")
            print(f"Losses: {losses} ({losses/len(result_df)*100:.1f}%)")
            print(f"Results saved to: {analyzer.output_dir}")
            print("\nGenerated files:")
            print("- Comprehensive analysis data (CSV)")
            print("- Feature comparison (CSV)")
            print("- Trading rules (Python code)")
            print("- Visualization (PNG)")
            print("- Comprehensive report (TXT)")
        else:
            print("No data available for analysis.")

    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()