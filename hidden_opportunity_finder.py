"""
숨겨진 기회 발견기

signal_replay_log에서 아무 신호도 발생하지 않은 케이스들을 분석하여
CLAUDE.md의 눌림목 캔들패턴 기준으로 놓친 기회를 찾습니다.

CLAUDE.md 핵심 패턴:
1. 주가 상승, 거래량 추세 하락
2. 이등분선 위에서 조정, 거래량 급감, 봉 캔들 축소
3. 급감된 거래량이 조금씩 증가하며 봉 크기 서서히 확대
4. 기준거래량(당일 최대) 대비 1/4 수준으로 거래
"""

import re
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import matplotlib.pyplot as plt

class HiddenOpportunityFinder:
    """숨겨진 기회 발견기"""

    def __init__(self):
        self.signal_log_dir = Path("signal_replay_log")
        self.cache_dir = Path("cache")
        self.minute_data_dir = self.cache_dir / "minute_data"
        self.output_dir = Path("hidden_opportunities")
        self.output_dir.mkdir(exist_ok=True)

    def find_no_signal_cases(self) -> List[Dict]:
        """신호가 없었던 케이스들 찾기"""
        no_signal_cases = []

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

                # 각 종목별 분석
                stock_sections = re.split(r'=== (\d{6}) - \d{8}', content)[1:]

                for i in range(0, len(stock_sections), 2):
                    if i + 1 >= len(stock_sections):
                        break

                    stock_code = stock_sections[i]
                    section_content = stock_sections[i + 1]

                    # 매매신호 섹션 확인
                    signal_section = re.search(r'매매신호:\s*\n(.*?)\n\s*체결', section_content, re.DOTALL)

                    has_signal = False
                    if signal_section:
                        signal_text = signal_section.group(1).strip()
                        if signal_text and "없음" not in signal_text:
                            # 실제 시간 형태의 신호가 있는지 확인
                            time_signals = re.findall(r'\d{2}:\d{2}', signal_text)
                            if time_signals:
                                has_signal = True

                    # 신호가 없는 경우
                    if not has_signal:
                        # selection_date 추출
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
            print(f"Error loading minute data {file_path}: {e}")
            return None

    def check_pullback_pattern(self, df: pd.DataFrame, selection_time: str = "12:00") -> Dict:
        """눌림목 패턴 체크 (CLAUDE.md 기준)"""
        if df is None or df.empty:
            return {}

        try:
            # selection_time 이후 데이터만 분석
            selection_hour, selection_min = map(int, selection_time.split(':'))
            selection_time_int = selection_hour * 100 + selection_min

            # time 컬럼을 정수로 변환하여 비교
            df['time_int'] = df['time'].astype(str).str.replace(':', '').astype(int)
            after_selection = df[df['time_int'] >= selection_time_int].copy()

            if len(after_selection) < 10:
                return {}

            # 기준 거래량 (당일 최대)
            base_volume = df['volume'].max()

            # 이등분선 계산 (당일 고점과 저점의 중간)
            day_high = df['high'].max()
            day_low = df['low'].min()
            bisector = (day_high + day_low) / 2

            # selection_time 이후 분석
            analysis_results = []

            for i in range(len(after_selection) - 5):
                current_idx = i + 5  # 최소 5개 데이터 후부터 분석

                # 현재 시점 데이터
                current = after_selection.iloc[current_idx]
                recent_5 = after_selection.iloc[current_idx-4:current_idx+1]  # 최근 5분봉
                recent_10 = after_selection.iloc[current_idx-9:current_idx+1] if current_idx >= 9 else recent_5  # 최근 10분봉

                # 1. 이등분선 위에서 조정 중인지
                is_above_bisector = current['close'] > bisector

                # 2. 거래량 급감 체크 (기준거래량 대비 1/4 수준)
                current_volume = current['volume']
                volume_ratio = current_volume / base_volume if base_volume > 0 else 0
                is_low_volume = volume_ratio <= 0.25

                # 3. 캔들 크기 축소 확인 (최근 5분봉 평균 대비)
                if len(recent_5) >= 3:
                    recent_candle_sizes = (recent_5['high'] - recent_5['low']) / recent_5['close']
                    current_candle_size = (current['high'] - current['low']) / current['close']
                    avg_recent_size = recent_candle_sizes[:-1].mean()  # 현재 제외한 평균
                    is_small_candle = current_candle_size < avg_recent_size * 0.8
                else:
                    is_small_candle = False

                # 4. 거래량 증가 전환점 체크
                if len(recent_5) >= 3:
                    prev_volumes = recent_5['volume'].iloc[:-1]
                    min_volume_idx = prev_volumes.idxmin()
                    volume_increasing = current_volume > recent_5.loc[min_volume_idx, 'volume'] * 1.2
                else:
                    volume_increasing = False

                # 5. 주가 상승 추세 확인 (selection 이후)
                if current_idx >= 5:
                    price_trend = np.polyfit(range(len(recent_10)), recent_10['close'], 1)[0]
                    is_uptrend = price_trend > 0
                else:
                    is_uptrend = False

                # 눌림목 패턴 점수 계산
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

                # 패턴이 강한 경우 기록
                if pattern_score >= 60:  # 60점 이상

                    # 이후 수익률 계산 (다음 30분 동안)
                    future_data = after_selection.iloc[current_idx+1:current_idx+11]  # 다음 10개 봉 (30분)
                    if len(future_data) > 0:
                        entry_price = current['close']
                        max_future_price = future_data['high'].max()
                        potential_return = (max_future_price - entry_price) / entry_price * 100
                    else:
                        potential_return = 0

                    analysis_results.append({
                        'time': current['time'],
                        'price': current['close'],
                        'volume': current_volume,
                        'volume_ratio': volume_ratio,
                        'pattern_score': pattern_score,
                        'potential_return': potential_return,
                        'is_above_bisector': is_above_bisector,
                        'is_low_volume': is_low_volume,
                        'is_small_candle': is_small_candle,
                        'volume_increasing': volume_increasing,
                        'is_uptrend': is_uptrend
                    })

            # 가장 좋은 패턴 선택
            if analysis_results:
                best_pattern = max(analysis_results, key=lambda x: x['pattern_score'])
                return {
                    'found_pattern': True,
                    'best_score': best_pattern['pattern_score'],
                    'best_time': best_pattern['time'],
                    'potential_return': best_pattern['potential_return'],
                    'pattern_details': best_pattern,
                    'all_patterns': analysis_results
                }
            else:
                return {'found_pattern': False}

        except Exception as e:
            print(f"Error in pullback pattern check: {e}")
            return {}

    def analyze_hidden_opportunities(self, no_signal_cases: List[Dict]) -> List[Dict]:
        """숨겨진 기회 분석"""
        hidden_opportunities = []

        for case in no_signal_cases[:50]:  # 처음 50개만 테스트
            stock_code = case['stock_code']
            date = case['date']

            print(f"Analyzing {stock_code} on {date}")

            # 분봉 데이터 로드
            minute_df = self.load_minute_data(stock_code, date)
            if minute_df is None:
                continue

            # selection_date를 시간으로 변환
            selection_time = "12:00"  # 기본값
            if case['selection_date']:
                try:
                    sel_dt = datetime.strptime(case['selection_date'], '%Y-%m-%d %H:%M:%S')
                    selection_time = sel_dt.strftime('%H:%M')
                except:
                    pass

            # 눌림목 패턴 체크
            pattern_result = self.check_pullback_pattern(minute_df, selection_time)

            if pattern_result.get('found_pattern', False):
                hidden_opportunity = {
                    'stock_code': stock_code,
                    'date': date,
                    'selection_time': selection_time,
                    'pattern_score': pattern_result['best_score'],
                    'signal_time': pattern_result['best_time'],
                    'potential_return': pattern_result['potential_return'],
                    'pattern_details': pattern_result['pattern_details']
                }

                hidden_opportunities.append(hidden_opportunity)
                print(f"  Found opportunity: {pattern_result['best_time']} (score: {pattern_result['best_score']}, return: {pattern_result['potential_return']:.2f}%)")

        return hidden_opportunities

    def generate_summary_report(self, hidden_opportunities: List[Dict], total_cases: int):
        """요약 보고서 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"hidden_opportunities_report_{timestamp}.txt"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=== 숨겨진 기회 발견 보고서 ===\n\n")
            f.write(f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"분석 대상: 신호가 없었던 {total_cases}개 케이스\n")
            f.write(f"발견된 기회: {len(hidden_opportunities)}개\n")

            if hidden_opportunities:
                potential_returns = [opp['potential_return'] for opp in hidden_opportunities]
                pattern_scores = [opp['pattern_score'] for opp in hidden_opportunities]

                f.write(f"발견율: {len(hidden_opportunities)/total_cases*100:.1f}%\n")
                f.write(f"평균 패턴 점수: {np.mean(pattern_scores):.1f}점\n")
                f.write(f"평균 잠재 수익률: {np.mean(potential_returns):.2f}%\n")
                f.write(f"최대 잠재 수익률: {max(potential_returns):.2f}%\n\n")

                # 상위 기회들
                top_opportunities = sorted(hidden_opportunities,
                                         key=lambda x: x['potential_return'], reverse=True)[:10]

                f.write("=== 상위 10개 기회 ===\n")
                for i, opp in enumerate(top_opportunities, 1):
                    f.write(f"{i:2d}. {opp['stock_code']} {opp['date']} {opp['signal_time']} | "
                           f"점수:{opp['pattern_score']:2.0f} | 수익률:{opp['potential_return']:6.2f}%\n")

                # 패턴 분석
                f.write(f"\n=== 패턴 특성 분석 ===\n")
                above_bisector_count = sum(1 for opp in hidden_opportunities
                                         if opp['pattern_details']['is_above_bisector'])
                low_volume_count = sum(1 for opp in hidden_opportunities
                                     if opp['pattern_details']['is_low_volume'])
                volume_increasing_count = sum(1 for opp in hidden_opportunities
                                            if opp['pattern_details']['volume_increasing'])

                f.write(f"이등분선 위 조정: {above_bisector_count}/{len(hidden_opportunities)} ({above_bisector_count/len(hidden_opportunities)*100:.1f}%)\n")
                f.write(f"저거래량 상태: {low_volume_count}/{len(hidden_opportunities)} ({low_volume_count/len(hidden_opportunities)*100:.1f}%)\n")
                f.write(f"거래량 증가 전환: {volume_increasing_count}/{len(hidden_opportunities)} ({volume_increasing_count/len(hidden_opportunities)*100:.1f}%)\n")

        print(f"보고서 저장: {report_path}")

    def run_analysis(self):
        """전체 분석 실행"""
        print("숨겨진 기회 분석을 시작합니다...")

        # 1. 신호가 없었던 케이스들 찾기
        no_signal_cases = self.find_no_signal_cases()

        if not no_signal_cases:
            print("분석할 케이스가 없습니다.")
            return

        # 2. 눌림목 패턴 기반 숨겨진 기회 찾기
        hidden_opportunities = self.analyze_hidden_opportunities(no_signal_cases)

        # 3. 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if hidden_opportunities:
            # CSV 저장
            df = pd.DataFrame(hidden_opportunities)
            csv_path = self.output_dir / f"hidden_opportunities_{timestamp}.csv"
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"상세 데이터 저장: {csv_path}")

            # 요약 보고서
            self.generate_summary_report(hidden_opportunities, len(no_signal_cases))

            print(f"\n=== 빠른 요약 ===")
            print(f"분석 대상: {len(no_signal_cases)}개 케이스")
            print(f"발견된 기회: {len(hidden_opportunities)}개")
            print(f"발견율: {len(hidden_opportunities)/len(no_signal_cases)*100:.1f}%")

            if hidden_opportunities:
                avg_return = np.mean([opp['potential_return'] for opp in hidden_opportunities])
                print(f"평균 잠재 수익률: {avg_return:.2f}%")

        else:
            print("숨겨진 기회를 찾지 못했습니다.")

        return hidden_opportunities

def main():
    finder = HiddenOpportunityFinder()
    results = finder.run_analysis()

if __name__ == "__main__":
    main()