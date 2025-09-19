"""
연속 신호 패턴 분석기

매매 신호가 연속으로 발생하는 패턴을 분석하여
신호의 품질과 승률 간의 관계를 파악합니다.

분석 항목:
1. 같은 종목 연속 신호 (당일/며칠간)
2. 전체 시장 신호 밀도 (시간대별)
3. 신호 간격에 따른 승률 차이
4. 연속 승리/패배 후 다음 신호 승률
5. 첫 신호 vs 추가 신호 승률 비교
"""

import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import matplotlib.pyplot as plt
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class SignalEvent:
    """신호 이벤트"""
    stock_code: str
    date: str
    signal_time: str
    signal_type: str
    buy_price: float
    sell_price: float
    return_pct: float
    is_win: bool
    sell_reason: str
    signal_order: int  # 해당 종목의 몇 번째 신호인지
    time_since_prev: float  # 이전 신호와의 시간 간격 (분)
    market_signal_count: int  # 같은 시간대 전체 시장 신호 수

@dataclass
class ConsecutivePattern:
    """연속 패턴"""
    pattern_type: str  # 'consecutive_wins', 'consecutive_losses', 'alternating' 등
    sequence_length: int
    overall_return: float
    individual_returns: List[float]
    stock_codes: List[str]
    dates: List[str]

class ConsecutiveSignalAnalyzer:
    """연속 신호 패턴 분석기"""

    def __init__(self):
        self.signal_log_dir = Path("signal_replay_log")
        self.output_dir = Path("consecutive_analysis_results")
        self.output_dir.mkdir(exist_ok=True)

        self.signal_events: List[SignalEvent] = []
        self.daily_signals: Dict[str, List[SignalEvent]] = defaultdict(list)
        self.stock_signals: Dict[str, List[SignalEvent]] = defaultdict(list)

    def extract_all_signals(self) -> List[SignalEvent]:
        """모든 신호를 시간순으로 추출"""
        all_signals = []

        for log_file in sorted(self.signal_log_dir.glob("signal_new2_replay_*.txt")):
            print(f"Processing {log_file.name}")

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 날짜 추출
                date_match = re.search(r'(\d{8})', log_file.name)
                if not date_match:
                    continue
                trade_date = date_match.group(1)

                # 각 종목별 신호 추출
                stock_sections = re.split(r'=== (\d{6}) - \d{8}', content)[1:]

                for i in range(0, len(stock_sections), 2):
                    if i + 1 >= len(stock_sections):
                        break

                    stock_code = stock_sections[i]
                    section_content = stock_sections[i + 1]

                    # 매매 신호 시간 추출
                    signal_times = re.findall(r'(\d{2}:\d{2}) \[pullback_pattern\]', section_content)

                    # 체결 결과 추출
                    simulation_matches = re.findall(
                        r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([0-9,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([0-9,]+) \(([+-]\d+\.\d+)%\)',
                        section_content
                    )

                    for match in simulation_matches:
                        buy_time, signal_type, buy_price_str, sell_time, sell_reason, sell_price_str, return_pct_str = match

                        signal_event = SignalEvent(
                            stock_code=stock_code,
                            date=trade_date,
                            signal_time=buy_time,
                            signal_type=signal_type,
                            buy_price=float(buy_price_str.replace(',', '')),
                            sell_price=float(sell_price_str.replace(',', '')),
                            return_pct=float(return_pct_str),
                            is_win=float(return_pct_str) > 0,
                            sell_reason=sell_reason,
                            signal_order=0,  # 나중에 계산
                            time_since_prev=0,  # 나중에 계산
                            market_signal_count=0  # 나중에 계산
                        )

                        all_signals.append(signal_event)

            except Exception as e:
                print(f"Error processing {log_file.name}: {e}")
                continue

        # 시간순 정렬
        all_signals.sort(key=lambda x: (x.date, x.signal_time))

        # 추가 정보 계산
        self._calculate_signal_metadata(all_signals)

        return all_signals

    def _calculate_signal_metadata(self, signals: List[SignalEvent]):
        """신호 메타데이터 계산"""
        # 종목별 신호 순서 계산
        stock_counters = defaultdict(int)

        # 시간별 신호 그룹화 (5분 단위)
        time_groups = defaultdict(list)

        for signal in signals:
            # 종목별 신호 순서
            stock_counters[signal.stock_code] += 1
            signal.signal_order = stock_counters[signal.stock_code]

            # 시간 그룹 키 생성 (5분 단위로 그룹화)
            time_key = f"{signal.date}_{signal.signal_time[:3]}x"  # 시간의 십의 자리까지
            time_groups[time_key].append(signal)

        # 이전 신호와의 시간 간격 계산
        prev_signals = {}  # stock_code -> 이전 신호

        for signal in signals:
            if signal.stock_code in prev_signals:
                prev_signal = prev_signals[signal.stock_code]

                # 시간 차이 계산 (분 단위)
                curr_datetime = datetime.strptime(f"{signal.date} {signal.signal_time}", "%Y%m%d %H:%M")
                prev_datetime = datetime.strptime(f"{prev_signal.date} {prev_signal.signal_time}", "%Y%m%d %H:%M")

                time_diff = (curr_datetime - prev_datetime).total_seconds() / 60
                signal.time_since_prev = time_diff

            prev_signals[signal.stock_code] = signal

        # 시장 전체 신호 밀도 계산
        for signal in signals:
            time_key = f"{signal.date}_{signal.signal_time[:3]}x"
            signal.market_signal_count = len(time_groups[time_key])

    def analyze_signal_order_effects(self, signals: List[SignalEvent]) -> Dict:
        """신호 순서별 승률 분석"""
        order_stats = defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []})

        for signal in signals:
            order = min(signal.signal_order, 5)  # 5번째 이후는 5+로 그룹화
            order_key = f"{order}번째" if order <= 5 else "6번째+"

            order_stats[order_key]['total'] += 1
            if signal.is_win:
                order_stats[order_key]['wins'] += 1
            order_stats[order_key]['returns'].append(signal.return_pct)

        # 승률 계산
        results = {}
        for order, stats in order_stats.items():
            win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
            avg_return = np.mean(stats['returns']) if stats['returns'] else 0

            results[order] = {
                'total_signals': stats['total'],
                'wins': stats['wins'],
                'win_rate': win_rate,
                'avg_return': avg_return,
                'median_return': np.median(stats['returns']) if stats['returns'] else 0
            }

        return results

    def analyze_time_interval_effects(self, signals: List[SignalEvent]) -> Dict:
        """신호 간격별 승률 분석"""
        interval_stats = defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []})

        for signal in signals:
            if signal.time_since_prev > 0:  # 첫 신호가 아닌 경우만
                # 시간 간격을 구간별로 분류
                if signal.time_since_prev <= 30:
                    interval_key = "30분 이내"
                elif signal.time_since_prev <= 60:
                    interval_key = "30분-1시간"
                elif signal.time_since_prev <= 180:
                    interval_key = "1-3시간"
                elif signal.time_since_prev <= 1440:  # 1일
                    interval_key = "3시간-1일"
                else:
                    interval_key = "1일 이상"

                interval_stats[interval_key]['total'] += 1
                if signal.is_win:
                    interval_stats[interval_key]['wins'] += 1
                interval_stats[interval_key]['returns'].append(signal.return_pct)

        # 결과 계산
        results = {}
        for interval, stats in interval_stats.items():
            win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
            avg_return = np.mean(stats['returns']) if stats['returns'] else 0

            results[interval] = {
                'total_signals': stats['total'],
                'wins': stats['wins'],
                'win_rate': win_rate,
                'avg_return': avg_return
            }

        return results

    def analyze_market_density_effects(self, signals: List[SignalEvent]) -> Dict:
        """시장 신호 밀도별 승률 분석"""
        density_stats = defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []})

        for signal in signals:
            # 신호 밀도 구간 분류
            if signal.market_signal_count == 1:
                density_key = "단독 신호"
            elif signal.market_signal_count <= 3:
                density_key = "2-3개 신호"
            elif signal.market_signal_count <= 5:
                density_key = "4-5개 신호"
            elif signal.market_signal_count <= 10:
                density_key = "6-10개 신호"
            else:
                density_key = "11개+ 신호"

            density_stats[density_key]['total'] += 1
            if signal.is_win:
                density_stats[density_key]['wins'] += 1
            density_stats[density_key]['returns'].append(signal.return_pct)

        # 결과 계산
        results = {}
        for density, stats in density_stats.items():
            win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
            avg_return = np.mean(stats['returns']) if stats['returns'] else 0

            results[density] = {
                'total_signals': stats['total'],
                'wins': stats['wins'],
                'win_rate': win_rate,
                'avg_return': avg_return
            }

        return results

    def analyze_consecutive_patterns(self, signals: List[SignalEvent]) -> Dict:
        """연속 승패 패턴 분석"""
        # 종목별로 연속 패턴 분석
        stock_patterns = defaultdict(list)

        for stock_code in set(s.stock_code for s in signals):
            stock_signals = [s for s in signals if s.stock_code == stock_code]
            stock_signals.sort(key=lambda x: (x.date, x.signal_time))

            # 연속 승리/패배 카운트
            consecutive_wins = 0
            consecutive_losses = 0

            for i, signal in enumerate(stock_signals):
                if signal.is_win:
                    consecutive_wins += 1
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
                    consecutive_wins = 0

                # 다음 신호가 있다면 그 결과를 기록
                if i + 1 < len(stock_signals):
                    next_signal = stock_signals[i + 1]

                    pattern_info = {
                        'prev_consecutive_wins': consecutive_wins,
                        'prev_consecutive_losses': consecutive_losses,
                        'next_signal_win': next_signal.is_win,
                        'next_signal_return': next_signal.return_pct
                    }

                    stock_patterns[stock_code].append(pattern_info)

        # 전체 패턴 분석
        pattern_analysis = {
            'after_wins': defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []}),
            'after_losses': defaultdict(lambda: {'wins': 0, 'total': 0, 'returns': []})
        }

        for patterns in stock_patterns.values():
            for pattern in patterns:
                # 연속 승리 후 분석
                if pattern['prev_consecutive_wins'] > 0:
                    win_key = f"{min(pattern['prev_consecutive_wins'], 5)}연승 후"
                    pattern_analysis['after_wins'][win_key]['total'] += 1
                    if pattern['next_signal_win']:
                        pattern_analysis['after_wins'][win_key]['wins'] += 1
                    pattern_analysis['after_wins'][win_key]['returns'].append(pattern['next_signal_return'])

                # 연속 패배 후 분석
                if pattern['prev_consecutive_losses'] > 0:
                    loss_key = f"{min(pattern['prev_consecutive_losses'], 5)}연패 후"
                    pattern_analysis['after_losses'][loss_key]['total'] += 1
                    if pattern['next_signal_win']:
                        pattern_analysis['after_losses'][loss_key]['wins'] += 1
                    pattern_analysis['after_losses'][loss_key]['returns'].append(pattern['next_signal_return'])

        # 결과 정리
        results = {'after_consecutive_wins': {}, 'after_consecutive_losses': {}}

        for category in ['after_wins', 'after_losses']:
            result_key = 'after_consecutive_wins' if category == 'after_wins' else 'after_consecutive_losses'

            for pattern_key, stats in pattern_analysis[category].items():
                win_rate = stats['wins'] / stats['total'] * 100 if stats['total'] > 0 else 0
                avg_return = np.mean(stats['returns']) if stats['returns'] else 0

                results[result_key][pattern_key] = {
                    'total_signals': stats['total'],
                    'wins': stats['wins'],
                    'win_rate': win_rate,
                    'avg_return': avg_return
                }

        return results

    def create_visualization(self, order_results, interval_results, density_results, consecutive_results, timestamp):
        """시각화 생성"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        # 1. 신호 순서별 승률
        ax1 = axes[0, 0]
        orders = list(order_results.keys())
        win_rates = [order_results[order]['win_rate'] for order in orders]
        ax1.bar(orders, win_rates, color='skyblue')
        ax1.set_title('Signal Order vs Win Rate')
        ax1.set_ylabel('Win Rate (%)')
        ax1.tick_params(axis='x', rotation=45)

        # 2. 시간 간격별 승률
        ax2 = axes[0, 1]
        intervals = list(interval_results.keys())
        interval_win_rates = [interval_results[interval]['win_rate'] for interval in intervals]
        ax2.bar(intervals, interval_win_rates, color='lightgreen')
        ax2.set_title('Time Interval vs Win Rate')
        ax2.set_ylabel('Win Rate (%)')
        ax2.tick_params(axis='x', rotation=45)

        # 3. 시장 밀도별 승률
        ax3 = axes[1, 0]
        densities = list(density_results.keys())
        density_win_rates = [density_results[density]['win_rate'] for density in densities]
        ax3.bar(densities, density_win_rates, color='orange')
        ax3.set_title('Market Density vs Win Rate')
        ax3.set_ylabel('Win Rate (%)')
        ax3.tick_params(axis='x', rotation=45)

        # 4. 연속 패턴별 승률
        ax4 = axes[1, 1]
        all_consecutive = {**consecutive_results['after_consecutive_wins'],
                          **consecutive_results['after_consecutive_losses']}
        consecutive_labels = list(all_consecutive.keys())
        consecutive_win_rates = [all_consecutive[label]['win_rate'] for label in consecutive_labels]

        colors = ['green' if '승' in label else 'red' for label in consecutive_labels]
        ax4.bar(consecutive_labels, consecutive_win_rates, color=colors, alpha=0.7)
        ax4.set_title('Consecutive Pattern vs Next Win Rate')
        ax4.set_ylabel('Win Rate (%)')
        ax4.tick_params(axis='x', rotation=45)

        plt.tight_layout()

        viz_path = self.output_dir / f"consecutive_analysis_{timestamp}.png"
        plt.savefig(viz_path, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"Visualization saved to {viz_path}")

    def generate_report(self, order_results, interval_results, density_results, consecutive_results, timestamp):
        """분석 보고서 생성"""
        report_path = self.output_dir / f"consecutive_report_{timestamp}.txt"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=== 연속 신호 패턴 분석 보고서 ===\n\n")
            f.write(f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # 1. 신호 순서별 분석
            f.write("=== 1. 신호 순서별 승률 ===\n")
            for order, stats in order_results.items():
                f.write(f"{order:10}: 승률 {stats['win_rate']:5.1f}% "
                       f"({stats['wins']:3}/{stats['total']:3}) "
                       f"평균수익률 {stats['avg_return']:6.2f}%\n")
            f.write("\n")

            # 2. 시간 간격별 분석
            f.write("=== 2. 이전 신호와의 시간 간격별 승률 ===\n")
            for interval, stats in interval_results.items():
                f.write(f"{interval:12}: 승률 {stats['win_rate']:5.1f}% "
                       f"({stats['wins']:3}/{stats['total']:3}) "
                       f"평균수익률 {stats['avg_return']:6.2f}%\n")
            f.write("\n")

            # 3. 시장 밀도별 분석
            f.write("=== 3. 동시간대 시장 신호 밀도별 승률 ===\n")
            for density, stats in density_results.items():
                f.write(f"{density:12}: 승률 {stats['win_rate']:5.1f}% "
                       f"({stats['wins']:3}/{stats['total']:3}) "
                       f"평균수익률 {stats['avg_return']:6.2f}%\n")
            f.write("\n")

            # 4. 연속 패턴별 분석
            f.write("=== 4. 연속 승패 후 다음 신호 승률 ===\n")
            f.write("연속 승리 후:\n")
            for pattern, stats in consecutive_results['after_consecutive_wins'].items():
                f.write(f"  {pattern:10}: 승률 {stats['win_rate']:5.1f}% "
                       f"({stats['wins']:3}/{stats['total']:3}) "
                       f"평균수익률 {stats['avg_return']:6.2f}%\n")

            f.write("\n연속 패배 후:\n")
            for pattern, stats in consecutive_results['after_consecutive_losses'].items():
                f.write(f"  {pattern:10}: 승률 {stats['win_rate']:5.1f}% "
                       f"({stats['wins']:3}/{stats['total']:3}) "
                       f"평균수익률 {stats['avg_return']:6.2f}%\n")

            # 5. 핵심 인사이트
            f.write("\n=== 5. 핵심 인사이트 ===\n\n")

            # 가장 좋은 조건 찾기
            best_order = max(order_results.items(), key=lambda x: x[1]['win_rate'])
            best_interval = max(interval_results.items(), key=lambda x: x[1]['win_rate'])
            best_density = max(density_results.items(), key=lambda x: x[1]['win_rate'])

            f.write(f"🏆 최고 승률 조건:\n")
            f.write(f"  - 신호 순서: {best_order[0]} (승률 {best_order[1]['win_rate']:.1f}%)\n")
            f.write(f"  - 시간 간격: {best_interval[0]} (승률 {best_interval[1]['win_rate']:.1f}%)\n")
            f.write(f"  - 시장 밀도: {best_density[0]} (승률 {best_density[1]['win_rate']:.1f}%)\n")

            # 가장 나쁜 조건
            worst_order = min(order_results.items(), key=lambda x: x[1]['win_rate'])
            worst_interval = min(interval_results.items(), key=lambda x: x[1]['win_rate'])
            worst_density = min(density_results.items(), key=lambda x: x[1]['win_rate'])

            f.write(f"\n⚠️ 최저 승률 조건:\n")
            f.write(f"  - 신호 순서: {worst_order[0]} (승률 {worst_order[1]['win_rate']:.1f}%)\n")
            f.write(f"  - 시간 간격: {worst_interval[0]} (승률 {worst_interval[1]['win_rate']:.1f}%)\n")
            f.write(f"  - 시장 밀도: {worst_density[0]} (승률 {worst_density[1]['win_rate']:.1f}%)\n")

        print(f"Report saved to {report_path}")

    def run_analysis(self):
        """전체 분석 실행"""
        print("연속 신호 패턴 분석을 시작합니다...")

        # 1. 모든 신호 추출
        signals = self.extract_all_signals()
        print(f"총 {len(signals)}개의 신호 추출됨")

        # 2. 각종 분석 수행
        order_results = self.analyze_signal_order_effects(signals)
        interval_results = self.analyze_time_interval_effects(signals)
        density_results = self.analyze_market_density_effects(signals)
        consecutive_results = self.analyze_consecutive_patterns(signals)

        # 3. 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV 저장
        signals_df = pd.DataFrame([
            {
                'stock_code': s.stock_code,
                'date': s.date,
                'signal_time': s.signal_time,
                'return_pct': s.return_pct,
                'is_win': s.is_win,
                'signal_order': s.signal_order,
                'time_since_prev': s.time_since_prev,
                'market_signal_count': s.market_signal_count
            }
            for s in signals
        ])

        csv_path = self.output_dir / f"signal_sequences_{timestamp}.csv"
        signals_df.to_csv(csv_path, index=False, encoding='utf-8-sig')

        # 4. 시각화 및 보고서
        self.create_visualization(order_results, interval_results, density_results, consecutive_results, timestamp)
        self.generate_report(order_results, interval_results, density_results, consecutive_results, timestamp)

        print(f"분석 완료! 결과 저장 위치: {self.output_dir}")

        return {
            'order_results': order_results,
            'interval_results': interval_results,
            'density_results': density_results,
            'consecutive_results': consecutive_results
        }

def main():
    analyzer = ConsecutiveSignalAnalyzer()
    results = analyzer.run_analysis()

    # 간단한 요약 출력
    print("\n=== 빠른 요약 ===")

    order_results = results['order_results']
    print("신호 순서별 승률:")
    for order, stats in order_results.items():
        print(f"  {order}: {stats['win_rate']:.1f}% ({stats['total']}건)")

if __name__ == "__main__":
    main()