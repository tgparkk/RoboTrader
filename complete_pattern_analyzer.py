"""
완전한 패턴 분석기

숨겨진 기회 뿐만 아니라 실패 케이스도 함께 분석하여
눌림목 패턴의 실제 성공률과 위험도를 정확히 파악합니다.
"""

import re
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import matplotlib.pyplot as plt

class CompletePatternAnalyzer:
    """완전한 패턴 분석기 (성공+실패)"""

    def __init__(self):
        self.signal_log_dir = Path("signal_replay_log")
        self.cache_dir = Path("cache")
        self.minute_data_dir = self.cache_dir / "minute_data"
        self.output_dir = Path("complete_pattern_analysis")
        self.output_dir.mkdir(exist_ok=True)

    def find_no_signal_cases(self) -> List[Dict]:
        """신호가 없었던 케이스들 찾기"""
        no_signal_cases = []

        for log_file in sorted(self.signal_log_dir.glob("signal_new2_replay_*.txt")):
            print(f"Processing {log_file.name}")

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                date_match = re.search(r'(\d{8})', log_file.name)
                if not date_match:
                    continue
                trade_date = date_match.group(1)

                stock_sections = re.split(r'=== (\d{6}) - \d{8}', content)[1:]

                for i in range(0, len(stock_sections), 2):
                    if i + 1 >= len(stock_sections):
                        break

                    stock_code = stock_sections[i]
                    section_content = stock_sections[i + 1]

                    signal_section = re.search(r'매매신호:\s*\n(.*?)\n\s*체결', section_content, re.DOTALL)

                    has_signal = False
                    if signal_section:
                        signal_text = signal_section.group(1).strip()
                        if signal_text and "없음" not in signal_text:
                            time_signals = re.findall(r'\d{2}:\d{2}', signal_text)
                            if time_signals:
                                has_signal = True

                    if not has_signal:
                        selection_date_match = re.search(r'selection_date: ([^\\n]+)', section_content)
                        selection_date = selection_date_match.group(1).strip() if selection_date_match else None

                        no_signal_case = {
                            'stock_code': stock_code,
                            'date': trade_date,
                            'selection_date': selection_date,
                            'log_file': log_file.name
                        }

                        no_signal_cases.append(no_signal_case)

            except Exception as e:
                print(f"Error processing {log_file.name}: {e}")
                continue

        print(f"신호가 없었던 케이스: {len(no_signal_cases)}개")
        return no_signal_cases

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
            return None

    def find_all_pullback_patterns(self, df: pd.DataFrame, selection_time: str = "12:00") -> List[Dict]:
        """모든 눌림목 패턴 찾기 (성공/실패 포함)"""
        if df is None or df.empty:
            return []

        try:
            selection_hour, selection_min = map(int, selection_time.split(':'))
            selection_time_int = selection_hour * 100 + selection_min

            df['time_int'] = df['time'].astype(str).str.replace(':', '').astype(int)
            after_selection = df[df['time_int'] >= selection_time_int].copy()

            if len(after_selection) < 15:  # 최소 45분치 데이터 필요
                return []

            base_volume = df['volume'].max()
            day_high = df['high'].max()
            day_low = df['low'].min()
            bisector = (day_high + day_low) / 2

            all_patterns = []

            for i in range(len(after_selection) - 10):  # 최소 30분 후 결과를 볼 수 있도록
                current_idx = i + 5

                current = after_selection.iloc[current_idx]
                recent_5 = after_selection.iloc[current_idx-4:current_idx+1]
                recent_10 = after_selection.iloc[current_idx-9:current_idx+1] if current_idx >= 9 else recent_5

                # 패턴 조건 체크
                is_above_bisector = current['close'] > bisector
                current_volume = current['volume']
                volume_ratio = current_volume / base_volume if base_volume > 0 else 0
                is_low_volume = volume_ratio <= 0.25

                if len(recent_5) >= 3:
                    recent_candle_sizes = (recent_5['high'] - recent_5['low']) / recent_5['close']
                    current_candle_size = (current['high'] - current['low']) / current['close']
                    avg_recent_size = recent_candle_sizes[:-1].mean()
                    is_small_candle = current_candle_size < avg_recent_size * 0.8
                else:
                    is_small_candle = False

                if len(recent_5) >= 3:
                    prev_volumes = recent_5['volume'].iloc[:-1]
                    min_volume_idx = prev_volumes.idxmin()
                    volume_increasing = current_volume > recent_5.loc[min_volume_idx, 'volume'] * 1.2
                else:
                    volume_increasing = False

                if current_idx >= 5:
                    price_trend = np.polyfit(range(len(recent_10)), recent_10['close'], 1)[0]
                    is_uptrend = price_trend > 0
                else:
                    is_uptrend = False

                # 패턴 점수 계산
                pattern_score = 0
                if is_above_bisector:
                    pattern_score += 25
                if is_low_volume:
                    pattern_score += 30
                if is_small_candle:
                    pattern_score += 20
                if volume_increasing:
                    pattern_score += 15
                if is_uptrend:
                    pattern_score += 10

                # 패턴 점수가 일정 이상인 모든 케이스 분석
                if pattern_score >= 50:  # 50점 이상 모든 패턴

                    # 여러 시간대별 수익률 계산
                    entry_price = current['close']

                    # 10분 후 (3개 봉)
                    future_3 = after_selection.iloc[current_idx+1:current_idx+4]
                    return_10min = 0
                    if len(future_3) > 0:
                        max_price_10min = future_3['high'].max()
                        min_price_10min = future_3['low'].min()
                        return_10min = (max_price_10min - entry_price) / entry_price * 100
                        loss_10min = (min_price_10min - entry_price) / entry_price * 100

                    # 30분 후 (10개 봉)
                    future_10 = after_selection.iloc[current_idx+1:current_idx+11]
                    return_30min = 0
                    loss_30min = 0
                    if len(future_10) > 0:
                        max_price_30min = future_10['high'].max()
                        min_price_30min = future_10['low'].min()
                        return_30min = (max_price_30min - entry_price) / entry_price * 100
                        loss_30min = (min_price_30min - entry_price) / entry_price * 100

                    # 60분 후 (20개 봉)
                    future_20 = after_selection.iloc[current_idx+1:current_idx+21]
                    return_60min = 0
                    loss_60min = 0
                    if len(future_20) > 0:
                        max_price_60min = future_20['high'].max()
                        min_price_60min = future_20['low'].min()
                        return_60min = (max_price_60min - entry_price) / entry_price * 100
                        loss_60min = (min_price_60min - entry_price) / entry_price * 100

                    # 손절 시뮬레이션 (2% 손절)
                    stop_loss_pct = -2.0
                    was_stopped = False
                    stop_time = None

                    for j in range(current_idx + 1, min(current_idx + 21, len(after_selection))):
                        future_candle = after_selection.iloc[j]
                        loss_pct = (future_candle['low'] - entry_price) / entry_price * 100
                        if loss_pct <= stop_loss_pct:
                            was_stopped = True
                            stop_time = future_candle['time']
                            break

                    # 수익률 분류
                    is_profitable_10min = return_10min > 0.5  # 0.5% 이상
                    is_profitable_30min = return_30min > 0.5
                    is_profitable_60min = return_60min > 0.5

                    all_patterns.append({
                        'time': current['time'],
                        'price': current['close'],
                        'volume': current_volume,
                        'volume_ratio': volume_ratio,
                        'pattern_score': pattern_score,
                        'is_above_bisector': is_above_bisector,
                        'is_low_volume': is_low_volume,
                        'is_small_candle': is_small_candle,
                        'volume_increasing': volume_increasing,
                        'is_uptrend': is_uptrend,
                        'return_10min': return_10min,
                        'return_30min': return_30min,
                        'return_60min': return_60min,
                        'loss_10min': loss_10min,
                        'loss_30min': loss_30min,
                        'loss_60min': loss_60min,
                        'is_profitable_10min': is_profitable_10min,
                        'is_profitable_30min': is_profitable_30min,
                        'is_profitable_60min': is_profitable_60min,
                        'was_stopped': was_stopped,
                        'stop_time': stop_time
                    })

            return all_patterns

        except Exception as e:
            print(f"Error in pattern analysis: {e}")
            return []

    def analyze_all_patterns(self, no_signal_cases: List[Dict]) -> List[Dict]:
        """모든 패턴 분석 (성공+실패)"""
        all_pattern_results = []

        for case in no_signal_cases[:100]:  # 처음 100개 분석
            stock_code = case['stock_code']
            date = case['date']

            print(f"Analyzing {stock_code} on {date}")

            minute_df = self.load_minute_data(stock_code, date)
            if minute_df is None:
                continue

            selection_time = "12:00"
            if case['selection_date']:
                try:
                    sel_dt = datetime.strptime(case['selection_date'], '%Y-%m-%d %H:%M:%S')
                    selection_time = sel_dt.strftime('%H:%M')
                except:
                    pass

            patterns = self.find_all_pullback_patterns(minute_df, selection_time)

            for pattern in patterns:
                pattern_result = {
                    'stock_code': stock_code,
                    'date': date,
                    'selection_time': selection_time,
                    **pattern
                }
                all_pattern_results.append(pattern_result)

            if patterns:
                print(f"  Found {len(patterns)} patterns")

        return all_pattern_results

    def analyze_success_failure_rates(self, pattern_results: List[Dict]):
        """성공/실패율 분석"""
        if not pattern_results:
            print("분석할 패턴이 없습니다.")
            return

        print(f"\n=== 전체 패턴 분석 결과 ===")
        print(f"총 발견된 패턴: {len(pattern_results)}개")

        # 점수별 분석
        score_ranges = {
            '90점 이상': [p for p in pattern_results if p['pattern_score'] >= 90],
            '80-89점': [p for p in pattern_results if 80 <= p['pattern_score'] < 90],
            '70-79점': [p for p in pattern_results if 70 <= p['pattern_score'] < 80],
            '60-69점': [p for p in pattern_results if 60 <= p['pattern_score'] < 70],
            '50-59점': [p for p in pattern_results if 50 <= p['pattern_score'] < 60]
        }

        print(f"\n=== 패턴 점수별 성공률 ===")
        for score_range, patterns in score_ranges.items():
            if patterns:
                success_10min = sum(1 for p in patterns if p['is_profitable_10min'])
                success_30min = sum(1 for p in patterns if p['is_profitable_30min'])
                success_60min = sum(1 for p in patterns if p['is_profitable_60min'])
                stopped_out = sum(1 for p in patterns if p['was_stopped'])

                print(f"{score_range:8} ({len(patterns):3}개):")
                print(f"  10분후 성공: {success_10min:3}/{len(patterns):3} ({success_10min/len(patterns)*100:5.1f}%)")
                print(f"  30분후 성공: {success_30min:3}/{len(patterns):3} ({success_30min/len(patterns)*100:5.1f}%)")
                print(f"  60분후 성공: {success_60min:3}/{len(patterns):3} ({success_60min/len(patterns)*100:5.1f}%)")
                print(f"  2% 손절당함: {stopped_out:3}/{len(patterns):3} ({stopped_out/len(patterns)*100:5.1f}%)")

                avg_return_30min = np.mean([p['return_30min'] for p in patterns])
                avg_loss_30min = np.mean([p['loss_30min'] for p in patterns])
                print(f"  평균 최대수익: {avg_return_30min:5.2f}% | 평균 최대손실: {avg_loss_30min:5.2f}%")
                print()

        # 조건별 분석
        print(f"=== 조건별 성공률 (30분 기준) ===")

        conditions = {
            '전체': pattern_results,
            '이등분선 위': [p for p in pattern_results if p['is_above_bisector']],
            '저거래량': [p for p in pattern_results if p['is_low_volume']],
            '거래량 증가': [p for p in pattern_results if p['volume_increasing']],
            '상승추세': [p for p in pattern_results if p['is_uptrend']],
            '모든 조건': [p for p in pattern_results if
                          p['is_above_bisector'] and p['is_low_volume'] and
                          p['volume_increasing'] and p['is_uptrend']]
        }

        for condition_name, patterns in conditions.items():
            if patterns:
                success_count = sum(1 for p in patterns if p['is_profitable_30min'])
                stopped_count = sum(1 for p in patterns if p['was_stopped'])
                success_rate = success_count / len(patterns) * 100
                stop_rate = stopped_count / len(patterns) * 100

                avg_return = np.mean([p['return_30min'] for p in patterns])
                avg_loss = np.mean([p['loss_30min'] for p in patterns])

                print(f"{condition_name:10} ({len(patterns):3}개): 성공률 {success_rate:5.1f}% | "
                      f"손절률 {stop_rate:5.1f}% | 평균수익 {avg_return:5.2f}% | 평균손실 {avg_loss:5.2f}%")

    def generate_complete_report(self, pattern_results: List[Dict]):
        """완전한 보고서 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV 저장
        if pattern_results:
            df = pd.DataFrame(pattern_results)
            csv_path = self.output_dir / f"complete_pattern_analysis_{timestamp}.csv"
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"\n상세 데이터 저장: {csv_path}")

        # 보고서 저장
        report_path = self.output_dir / f"complete_analysis_report_{timestamp}.txt"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=== 완전한 눌림목 패턴 분석 보고서 ===\n\n")
            f.write(f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"총 발견된 패턴: {len(pattern_results)}개\n\n")

            if pattern_results:
                # 전체 통계
                all_success_30min = sum(1 for p in pattern_results if p['is_profitable_30min'])
                all_stopped = sum(1 for p in pattern_results if p['was_stopped'])

                f.write(f"전체 성공률 (30분): {all_success_30min/len(pattern_results)*100:.1f}%\n")
                f.write(f"전체 손절률: {all_stopped/len(pattern_results)*100:.1f}%\n")
                f.write(f"평균 최대수익률: {np.mean([p['return_30min'] for p in pattern_results]):.2f}%\n")
                f.write(f"평균 최대손실률: {np.mean([p['loss_30min'] for p in pattern_results]):.2f}%\n\n")

                # 최고 성과 패턴들
                top_patterns = sorted(pattern_results, key=lambda x: x['return_30min'], reverse=True)[:10]
                f.write("=== 최고 성과 패턴 (상위 10개) ===\n")
                for i, pattern in enumerate(top_patterns, 1):
                    f.write(f"{i:2d}. {pattern['stock_code']} {pattern['date']} {pattern['time']} | "
                           f"점수:{pattern['pattern_score']:2.0f} | 수익률:{pattern['return_30min']:6.2f}%\n")

                # 최악 성과 패턴들
                worst_patterns = sorted(pattern_results, key=lambda x: x['loss_30min'])[:10]
                f.write(f"\n=== 최악 손실 패턴 (하위 10개) ===\n")
                for i, pattern in enumerate(worst_patterns, 1):
                    f.write(f"{i:2d}. {pattern['stock_code']} {pattern['date']} {pattern['time']} | "
                           f"점수:{pattern['pattern_score']:2.0f} | 손실률:{pattern['loss_30min']:6.2f}%\n")

        print(f"완전한 보고서 저장: {report_path}")

    def run_complete_analysis(self):
        """완전한 분석 실행"""
        print("완전한 눌림목 패턴 분석을 시작합니다...")

        # 1. 신호가 없었던 케이스들 찾기
        no_signal_cases = self.find_no_signal_cases()

        if not no_signal_cases:
            print("분석할 케이스가 없습니다.")
            return

        # 2. 모든 패턴 분석 (성공+실패)
        pattern_results = self.analyze_all_patterns(no_signal_cases)

        if not pattern_results:
            print("발견된 패턴이 없습니다.")
            return

        # 3. 성공/실패율 분석
        self.analyze_success_failure_rates(pattern_results)

        # 4. 완전한 보고서 생성
        self.generate_complete_report(pattern_results)

        return pattern_results

def main():
    analyzer = CompletePatternAnalyzer()
    results = analyzer.run_complete_analysis()
    print("\n완전한 분석 완료!")

if __name__ == "__main__":
    main()