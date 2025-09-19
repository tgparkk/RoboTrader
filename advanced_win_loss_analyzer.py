"""
고급 승패 분석기 - 분봉+일봉 조합 분석

실제 매매 로그에서 승리/패배 매매를 추출하고,
해당 종목의 분봉 데이터와 일봉 데이터를 조합하여
승리한 매매와 패배한 매매의 차이점을 분석합니다.

CLAUDE.md의 눌림목 캔들패턴 로직을 기반으로:
1. 거래량 패턴 (기준거래량 대비 1/4 수준)
2. 이등분선 관련 패턴
3. 캔들 크기 변화 패턴
4. 일봉 추세와 분봉 패턴의 조합
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
# import seaborn as sns  # Optional, not critical for analysis
from dataclasses import dataclass
import json

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

@dataclass
class CombinedFeatures:
    """분봉+일봉 조합 특성"""
    # 분봉 특성
    minute_volume_ratio: float  # 현재 거래량 / 기준거래량
    minute_candle_size_trend: float  # 최근 캔들 크기 변화 추세
    minute_bisector_position: float  # 이등분선 대비 위치
    minute_volume_decrease_ratio: float  # 거래량 급감 비율

    # 일봉 특성
    daily_trend_strength: float  # 일봉 추세 강도
    daily_volume_trend: float  # 일봉 거래량 추세
    daily_ma_position: float  # 이동평균선 대비 위치
    daily_volatility: float  # 일봉 변동성

    # 조합 특성
    volume_divergence: float  # 일봉 상승 vs 분봉 거래량 감소 괴리도
    trend_confirmation: float  # 일봉 추세와 분봉 패턴 일치도

class AdvancedWinLossAnalyzer:
    """고급 승패 분석기"""

    def __init__(self):
        self.logger = self._setup_logger()
        self.signal_log_dir = Path("signal_replay_log")
        self.cache_dir = Path("cache")
        self.minute_data_dir = self.cache_dir / "minute_data"
        self.daily_data_dir = self.cache_dir / "daily"
        self.output_dir = Path("win_loss_analysis_results")
        self.output_dir.mkdir(exist_ok=True)

        # 매매 결과 저장
        self.trade_results: List[TradeResult] = []
        self.combined_features: List[CombinedFeatures] = []

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

    def load_daily_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드"""
        file_path = self.daily_data_dir / f"{stock_code}_{date}_daily.pkl"
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'rb') as f:
                df = pickle.load(f)
            return df
        except Exception as e:
            self.logger.error(f"Error loading daily data {file_path}: {e}")
            return None

    def calculate_minute_features(self, minute_df: pd.DataFrame, signal_time: str) -> Dict[str, float]:
        """분봉 특성 계산"""
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

    def calculate_daily_features(self, daily_df: pd.DataFrame) -> Dict[str, float]:
        """일봉 특성 계산"""
        if daily_df is None or daily_df.empty:
            return {}

        try:
            # 최근 데이터 순서 정렬 (날짜 순)
            daily_df = daily_df.sort_values('stck_bsop_date').reset_index(drop=True)

            # 가격 데이터 변환
            prices = daily_df['stck_clpr'].astype(float)
            volumes = daily_df['acml_vol'].astype(float)

            # 추세 강도 (최근 20일 선형회귀 기울기)
            if len(prices) >= 20:
                recent_prices = prices[-20:]
                trend_strength = np.polyfit(range(len(recent_prices)), recent_prices, 1)[0] / recent_prices.mean()
            else:
                trend_strength = 0

            # 거래량 추세 (최근 10일 거래량 추세)
            if len(volumes) >= 10:
                recent_volumes = volumes[-10:]
                volume_trend = np.polyfit(range(len(recent_volumes)), recent_volumes, 1)[0] / recent_volumes.mean()
            else:
                volume_trend = 0

            # 이동평균 대비 위치 (20일 이동평균)
            if len(prices) >= 20:
                ma20 = prices[-20:].mean()
                current_price = prices.iloc[-1]
                ma_position = (current_price - ma20) / ma20
            else:
                ma_position = 0

            # 변동성 (최근 20일 표준편차)
            if len(prices) >= 20:
                volatility = prices[-20:].std() / prices[-20:].mean()
            else:
                volatility = 0

            return {
                'daily_trend_strength': trend_strength,
                'daily_volume_trend': volume_trend,
                'daily_ma_position': ma_position,
                'daily_volatility': volatility
            }

        except Exception as e:
            self.logger.error(f"Error calculating daily features: {e}")
            return {}

    def calculate_combined_features(self, minute_features: Dict, daily_features: Dict) -> Dict[str, float]:
        """조합 특성 계산"""
        try:
            # 볼륨 다이버전스 (일봉 상승 vs 분봉 거래량 감소)
            daily_trend = daily_features.get('daily_trend_strength', 0)
            minute_volume_ratio = minute_features.get('minute_volume_ratio', 0)
            volume_divergence = daily_trend / (minute_volume_ratio + 0.01)  # 0으로 나누기 방지

            # 추세 확인 (일봉 추세와 분봉 이등분선 위치 일치도)
            daily_ma_pos = daily_features.get('daily_ma_position', 0)
            minute_bisector_pos = minute_features.get('minute_bisector_position', 0)
            trend_confirmation = 1 - abs(daily_ma_pos - minute_bisector_pos)

            return {
                'volume_divergence': volume_divergence,
                'trend_confirmation': trend_confirmation
            }

        except Exception as e:
            self.logger.error(f"Error calculating combined features: {e}")
            return {}

    def analyze_all_trades(self):
        """모든 매매 분석"""
        self.logger.info("Starting comprehensive trade analysis")

        # 매매 결과 추출
        self.trade_results = self.extract_trade_results_from_logs()

        analysis_data = []

        for trade in self.trade_results:
            # 분봉 데이터 로드
            minute_df = self.load_minute_data(trade.stock_code, trade.date)
            daily_df = self.load_daily_data(trade.stock_code, trade.date)

            if minute_df is None:
                self.logger.warning(f"No minute data for {trade.stock_code}_{trade.date}")
                continue

            # 특성 계산
            minute_features = self.calculate_minute_features(minute_df, trade.signal_time)
            daily_features = self.calculate_daily_features(daily_df) if daily_df is not None else {}
            combined_features = self.calculate_combined_features(minute_features, daily_features)

            # 모든 특성 통합
            all_features = {
                'stock_code': trade.stock_code,
                'date': trade.date,
                'signal_time': trade.signal_time,
                'return_pct': trade.return_pct,
                'is_win': trade.is_win,
                **minute_features,
                **daily_features,
                **combined_features
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
        csv_path = self.output_dir / f"trade_analysis_{timestamp}.csv"
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
                win_mean = wins[col].mean()
                loss_mean = losses[col].mean()
                difference = win_mean - loss_mean

                # t-test (간단한 유의성 검정)
                from scipy import stats
                try:
                    t_stat, p_value = stats.ttest_ind(wins[col].dropna(), losses[col].dropna())
                except:
                    t_stat, p_value = 0, 1

                comparison_results.append({
                    'feature': col,
                    'win_mean': win_mean,
                    'loss_mean': loss_mean,
                    'difference': difference,
                    'p_value': p_value,
                    'significant': p_value < 0.05
                })

        # 결과 정렬 (차이가 큰 순)
        comparison_results.sort(key=lambda x: abs(x['difference']), reverse=True)

        # 결과 저장
        comparison_df = pd.DataFrame(comparison_results)
        comparison_path = self.output_dir / f"win_loss_comparison_{timestamp}.csv"
        comparison_df.to_csv(comparison_path, index=False, encoding='utf-8-sig')

        # 시각화
        self.create_visualization(df, comparison_results, timestamp)

        # 요약 보고서
        self.generate_summary_report(comparison_results, timestamp, len(wins), len(losses))

    def create_visualization(self, df: pd.DataFrame, comparison_results: List[Dict], timestamp: str):
        """시각화 생성"""
        plt.rcParams['font.family'] = 'DejaVu Sans'

        # Top 8 차이나는 특성들 시각화
        top_features = [r['feature'] for r in comparison_results[:8] if r['significant']]

        if len(top_features) < 2:
            self.logger.warning("Not enough significant features for visualization")
            return

        fig, axes = plt.subplots(2, 4, figsize=(20, 10))
        axes = axes.flatten()

        for i, feature in enumerate(top_features):
            if i >= 8:
                break

            wins = df[df['is_win'] == True][feature].dropna()
            losses = df[df['is_win'] == False][feature].dropna()

            axes[i].hist(wins, alpha=0.7, label='Wins', bins=20, color='green')
            axes[i].hist(losses, alpha=0.7, label='Losses', bins=20, color='red')
            axes[i].set_title(f'{feature}')
            axes[i].legend()
            axes[i].grid(True, alpha=0.3)

        # 빈 subplot 숨기기
        for i in range(len(top_features), 8):
            axes[i].set_visible(False)

        plt.tight_layout()
        viz_path = self.output_dir / f"feature_comparison_{timestamp}.png"
        plt.savefig(viz_path, dpi=300, bbox_inches='tight')
        plt.close()

        self.logger.info(f"Visualization saved to {viz_path}")

    def generate_summary_report(self, comparison_results: List[Dict], timestamp: str, win_count: int, loss_count: int):
        """요약 보고서 생성"""
        report_path = self.output_dir / f"analysis_summary_{timestamp}.txt"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=== 고급 승패 분석 결과 ===\n\n")
            f.write(f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"총 매매 건수: {win_count + loss_count}\n")
            f.write(f"승리: {win_count}건 ({win_count/(win_count+loss_count)*100:.1f}%)\n")
            f.write(f"패배: {loss_count}건 ({loss_count/(win_count+loss_count)*100:.1f}%)\n\n")

            f.write("=== 주요 차이점 (상위 10개) ===\n")
            for i, result in enumerate(comparison_results[:10], 1):
                significance = "***" if result['significant'] else ""
                f.write(f"{i:2d}. {result['feature']:<25} | "
                       f"승리평균: {result['win_mean']:8.4f} | "
                       f"패배평균: {result['loss_mean']:8.4f} | "
                       f"차이: {result['difference']:8.4f} {significance}\n")

            f.write("\n=== 핵심 인사이트 ===\n")

            # 유의미한 차이가 있는 특성들
            significant_features = [r for r in comparison_results if r['significant']]

            if significant_features:
                f.write("통계적으로 유의미한 차이가 있는 특성들:\n")
                for feature in significant_features[:5]:
                    direction = "높음" if feature['difference'] > 0 else "낮음"
                    f.write(f"- {feature['feature']}: 승리 시 {direction} (p={feature['p_value']:.3f})\n")
            else:
                f.write("통계적으로 유의미한 차이를 보이는 특성이 없습니다.\n")

        self.logger.info(f"Summary report saved to {report_path}")

def main():
    """메인 실행 함수"""
    analyzer = AdvancedWinLossAnalyzer()

    print("Advanced win/loss analysis starting...")
    print("Extracting trade results from signal logs and analyzing minute+daily features.\n")

    try:
        result_df = analyzer.analyze_all_trades()

        if result_df is not None and not result_df.empty:
            print(f"Analysis completed!")
            print(f"Total trades analyzed: {len(result_df)}")
            print(f"Wins: {len(result_df[result_df['is_win']==True])}")
            print(f"Losses: {len(result_df[result_df['is_win']==False])}")
            print(f"Results saved to: {analyzer.output_dir}")
        else:
            print("No data available for analysis.")

    except Exception as e:
        print(f"Error during analysis: {e}")

if __name__ == "__main__":
    main()