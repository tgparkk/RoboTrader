"""
개선된 매매 신호 분석기

매매 로그의 실제 구조에 맞춰 정확한 데이터 추출 및 분석
승률 개선을 위한 구체적인 제안 생성
"""

import re
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

class ImprovedSignalAnalyzer:
    """개선된 신호 분석기"""

    def __init__(self):
        self.signal_log_dir = Path("signal_replay_log")
        self.cache_dir = Path("cache")
        self.daily_dir = self.cache_dir / "daily"
        self.minute_data_dir = self.cache_dir / "minute_data"
        self.output_dir = Path("improved_signal_analysis")
        self.output_dir.mkdir(exist_ok=True)

        # 결과 저장
        self.all_trades = []
        self.winning_trades = []
        self.losing_trades = []
        self.no_signal_cases = []
        self.hidden_opportunities = []

    def extract_trades_from_log(self) -> None:
        """로그에서 실제 매매 데이터 추출"""
        print("매매 로그에서 실제 거래 데이터 추출 중...")

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

                # 종목별 섹션 분할
                sections = re.split(r'=== (\d{6}) - \d{8}', content)

                for i in range(1, len(sections), 2):
                    if i + 1 >= len(sections):
                        break

                    stock_code = sections[i]
                    section_content = sections[i + 1]

                    # selection_date 추출
                    selection_match = re.search(r'selection_date: ([^\\n]+)', section_content)
                    selection_date = selection_match.group(1).strip() if selection_match else None

                    # 실제 매매 데이터 추출 (새로운 패턴)
                    trade_matches = re.findall(
                        r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([^)]+)\)',
                        section_content
                    )

                    if trade_matches:
                        for match in trade_matches:
                            buy_time, buy_signal, buy_price_str, sell_time, sell_signal, sell_price_str, pnl_str = match

                            buy_price = int(buy_price_str.replace(',', ''))
                            sell_price = int(sell_price_str.replace(',', ''))

                            # 수익률 계산
                            pnl_pct = (sell_price - buy_price) / buy_price * 100

                            trade_data = {
                                'stock_code': stock_code,
                                'date': trade_date,
                                'selection_date': selection_date,
                                'buy_time': buy_time,
                                'buy_signal': buy_signal,
                                'buy_price': buy_price,
                                'sell_time': sell_time,
                                'sell_signal': sell_signal,
                                'sell_price': sell_price,
                                'pnl_pct': pnl_pct,
                                'pnl_str': pnl_str,
                                'is_winning': pnl_pct > 0,
                                'log_file': log_file.name
                            }

                            self.all_trades.append(trade_data)

                            if pnl_pct > 0:
                                self.winning_trades.append(trade_data)
                            else:
                                self.losing_trades.append(trade_data)

                    else:
                        # 신호가 없는 케이스
                        no_signal_case = {
                            'stock_code': stock_code,
                            'date': trade_date,
                            'selection_date': selection_date,
                            'log_file': log_file.name
                        }
                        self.no_signal_cases.append(no_signal_case)

            except Exception as e:
                print(f"Error processing {log_file.name}: {e}")
                continue

        print(f"총 거래: {len(self.all_trades)}개")
        print(f"승리 거래: {len(self.winning_trades)}개")
        print(f"패배 거래: {len(self.losing_trades)}개")
        print(f"신호 없음: {len(self.no_signal_cases)}개")

    def load_minute_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """분봉 데이터 로드"""
        file_path = self.minute_data_dir / f"{stock_code}_{date}.pkl"
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'rb') as f:
                df = pickle.load(f)
            return df
        except:
            return None

    def load_daily_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드"""
        try:
            date_obj = datetime.strptime(date, '%Y%m%d')
            year_month = date_obj.strftime('%Y%m')

            file_path = self.daily_dir / f"{stock_code}_{year_month}_daily.pkl"
            if not file_path.exists():
                return None

            with open(file_path, 'rb') as f:
                df = pickle.load(f)

            # 해당 날짜까지만
            df['date'] = pd.to_datetime(df['date'])
            target_date = pd.to_datetime(date)
            return df[df['date'] <= target_date].copy()
        except:
            return None

    def analyze_winning_patterns(self):
        """승리 패턴 상세 분석"""
        print("승리 패턴 분석 중...")

        winning_pattern_features = []

        for trade in self.winning_trades:
            features = self.extract_trade_features(trade)
            if features:
                winning_pattern_features.append(features)

        if winning_pattern_features:
            win_df = pd.DataFrame(winning_pattern_features)

            print(f"\n=== 승리 패턴 특성 ({len(winning_pattern_features)}개) ===")

            # 시간대별 분석
            time_analysis = win_df.groupby('time_category').agg({
                'pnl_pct': ['count', 'mean'],
                'pattern_score': 'mean'
            }).round(2)
            print("\n시간대별 승률:")
            print(time_analysis)

            # 패턴 점수별 분석
            win_df['score_range'] = pd.cut(win_df['pattern_score'],
                                         bins=[0, 60, 70, 80, 90, 100],
                                         labels=['50-60', '60-70', '70-80', '80-90', '90-100'])

            score_analysis = win_df.groupby('score_range').agg({
                'pnl_pct': ['count', 'mean'],
                'volume_ratio': 'mean'
            }).round(2)
            print("\n패턴 점수별 성과:")
            print(score_analysis)

            return win_df
        return pd.DataFrame()

    def analyze_losing_patterns(self):
        """패배 패턴 상세 분석"""
        print("패배 패턴 분석 중...")

        losing_pattern_features = []

        for trade in self.losing_trades:
            features = self.extract_trade_features(trade)
            if features:
                losing_pattern_features.append(features)

        if losing_pattern_features:
            loss_df = pd.DataFrame(losing_pattern_features)

            print(f"\n=== 패배 패턴 특성 ({len(losing_pattern_features)}개) ===")

            # 시간대별 분석
            time_analysis = loss_df.groupby('time_category').agg({
                'pnl_pct': ['count', 'mean'],
                'pattern_score': 'mean'
            }).round(2)
            print("\n시간대별 손실:")
            print(time_analysis)

            # 주요 실패 원인 분석
            print("\n주요 실패 특성:")
            print(f"평균 패턴 점수: {loss_df['pattern_score'].mean():.1f}")
            print(f"이등분선 위 비율: {loss_df['is_above_bisector'].mean():.1%}")
            print(f"저거래량 비율: {loss_df['is_low_volume'].mean():.1%}")
            print(f"상승추세 비율: {loss_df['is_uptrend'].mean():.1%}")

            return loss_df
        return pd.DataFrame()

    def extract_trade_features(self, trade: Dict) -> Optional[Dict]:
        """거래별 특성 추출"""
        try:
            stock_code = trade['stock_code']
            date = trade['date']
            buy_time = trade['buy_time']

            # 분봉 데이터 로드
            minute_df = self.load_minute_data(stock_code, date)
            if minute_df is None:
                return None

            # 일봉 데이터 로드
            daily_df = self.load_daily_data(stock_code, date)

            # 거래 시점 찾기
            minute_df['time_str'] = minute_df['time'].astype(str)
            trade_rows = minute_df[minute_df['time_str'] == buy_time]

            if trade_rows.empty:
                return None

            trade_idx = trade_rows.index[0]

            # 기본 지표 계산
            day_high = minute_df['high'].max()
            day_low = minute_df['low'].min()
            bisector = (day_high + day_low) / 2
            base_volume = minute_df['volume'].max()

            current = minute_df.iloc[trade_idx]

            # 눌림목 패턴 특성
            is_above_bisector = current['close'] > bisector
            volume_ratio = current['volume'] / base_volume if base_volume > 0 else 0
            is_low_volume = volume_ratio <= 0.25

            # 시간대 분류
            hour = int(buy_time.split(':')[0])
            if 9 <= hour < 10:
                time_category = "opening"
            elif 10 <= hour < 12:
                time_category = "morning"
            elif 12 <= hour < 14:
                time_category = "afternoon"
            elif 14 <= hour < 15:
                time_category = "late"
            else:
                time_category = "other"

            # 패턴 점수 계산
            pattern_score = 0
            if is_above_bisector:
                pattern_score += 30
            if is_low_volume:
                pattern_score += 25
            if hour >= 13:
                pattern_score += 15

            # 추세 분석
            is_uptrend = False
            if trade_idx >= 5:
                recent_prices = minute_df.iloc[trade_idx-5:trade_idx]['close']
                if len(recent_prices) >= 3:
                    trend = np.polyfit(range(len(recent_prices)), recent_prices, 1)[0]
                    is_uptrend = trend > 0

            # 일봉 패턴
            daily_pattern = {}
            if daily_df is not None and len(daily_df) >= 3:
                recent_daily = daily_df.tail(3)
                price_trend = np.polyfit(range(len(recent_daily)), recent_daily['close'], 1)[0]
                volume_trend = np.polyfit(range(len(recent_daily)), recent_daily['volume'], 1)[0]

                daily_pattern = {
                    'price_rising': price_trend > 0,
                    'volume_declining': volume_trend < 0,
                    'ideal_pattern': price_trend > 0 and volume_trend < 0
                }

            return {
                'stock_code': stock_code,
                'date': date,
                'buy_time': buy_time,
                'pnl_pct': trade['pnl_pct'],
                'is_above_bisector': is_above_bisector,
                'volume_ratio': volume_ratio,
                'is_low_volume': is_low_volume,
                'time_category': time_category,
                'pattern_score': pattern_score,
                'is_uptrend': is_uptrend,
                'hour': hour,
                **daily_pattern
            }

        except Exception as e:
            return None

    def find_hidden_opportunities_simple(self):
        """간단한 숨겨진 기회 탐지"""
        print("숨겨진 기회 탐지 중...")

        opportunities = []

        for case in self.no_signal_cases[:50]:  # 샘플 50개
            stock_code = case['stock_code']
            date = case['date']

            minute_df = self.load_minute_data(stock_code, date)
            if minute_df is None:
                continue

            # selection_time 추출
            selection_time = "12:00"
            if case['selection_date']:
                try:
                    sel_dt = datetime.strptime(case['selection_date'], '%Y-%m-%d %H:%M:%S')
                    selection_time = sel_dt.strftime('%H:%M')
                except:
                    pass

            # 간단한 패턴 체크
            found_patterns = self.simple_pattern_check(minute_df, selection_time, case)
            opportunities.extend(found_patterns)

        self.hidden_opportunities = opportunities
        print(f"발견된 숨겨진 기회: {len(opportunities)}개")

    def simple_pattern_check(self, df: pd.DataFrame, selection_time: str, case: Dict) -> List[Dict]:
        """간단한 패턴 체크"""
        patterns = []

        try:
            # selection_time 이후 데이터
            selection_hour, selection_min = map(int, selection_time.split(':'))
            selection_time_int = selection_hour * 100 + selection_min

            df['time_int'] = df['time'].astype(str).str.replace(':', '').astype(int)
            after_selection = df[df['time_int'] >= selection_time_int].copy()

            if len(after_selection) < 10:
                return patterns

            # 기본 지표
            day_high = df['high'].max()
            day_low = df['low'].min()
            bisector = (day_high + day_low) / 2
            base_volume = df['volume'].max()

            # 각 시점 체크
            for i in range(5, min(30, len(after_selection))):  # 최대 30개 시점만
                current = after_selection.iloc[i]

                # 간단한 조건 체크
                is_above_bisector = current['close'] > bisector
                volume_ratio = current['volume'] / base_volume if base_volume > 0 else 0
                is_low_volume = volume_ratio <= 0.3

                if is_above_bisector and is_low_volume:
                    # 미래 수익률 체크
                    future_data = after_selection.iloc[i+1:i+11]  # 다음 30분
                    if len(future_data) > 0:
                        entry_price = current['close']
                        max_price = future_data['high'].max()
                        potential_return = (max_price - entry_price) / entry_price * 100

                        if potential_return > 0.5:  # 0.5% 이상 수익 가능
                            patterns.append({
                                'stock_code': case['stock_code'],
                                'date': case['date'],
                                'time': current['time'],
                                'potential_return': potential_return,
                                'volume_ratio': volume_ratio,
                                'pattern_score': 70 if is_above_bisector and is_low_volume else 50
                            })

        except Exception as e:
            pass

        return patterns

    def generate_optimization_recommendations(self):
        """최적화 권장사항 생성"""
        print("\n=== 매매 신호 최적화 권장사항 ===")

        if not self.all_trades:
            print("분석할 거래 데이터가 없습니다.")
            return

        # 현재 성과
        total_trades = len(self.all_trades)
        winning_trades = len(self.winning_trades)
        current_win_rate = winning_trades / total_trades * 100

        print(f"현재 성과: {winning_trades}승 {total_trades - winning_trades}패 (승률: {current_win_rate:.1f}%)")

        # 시간대별 분석
        time_performance = defaultdict(lambda: {'wins': 0, 'total': 0})

        for trade in self.all_trades:
            hour = int(trade['buy_time'].split(':')[0])
            if 9 <= hour < 10:
                time_cat = "opening"
            elif 10 <= hour < 12:
                time_cat = "morning"
            elif 12 <= hour < 14:
                time_cat = "afternoon"
            elif 14 <= hour < 15:
                time_cat = "late"
            else:
                time_cat = "other"

            time_performance[time_cat]['total'] += 1
            if trade['is_winning']:
                time_performance[time_cat]['wins'] += 1

        print("\n시간대별 성과:")
        best_time_slots = []
        for time_cat, perf in time_performance.items():
            if perf['total'] > 0:
                win_rate = perf['wins'] / perf['total'] * 100
                print(f"{time_cat:10}: {perf['wins']:2}/{perf['total']:2} ({win_rate:5.1f}%)")
                if win_rate > current_win_rate:
                    best_time_slots.append(time_cat)

        # 권장사항
        print(f"\n=== 구체적 개선 방안 ===")

        print("1. 시간대 필터링:")
        if best_time_slots:
            print(f"   - 우수 시간대 집중: {', '.join(best_time_slots)}")
        else:
            print("   - 모든 시간대 성과 검토 필요")

        print("2. 패턴 조건 강화:")
        print("   - 이등분선 위치: 1-3% 범위로 제한")
        print("   - 거래량 조건: 기준 거래량 20% 이하")
        print("   - 일봉 추가 필터: 주가상승+거래량하락 패턴")

        print("3. 손절 최적화:")
        print("   - 현재 2% 손절을 1.5%로 조정 검토")
        print("   - 시간 기반 손절 추가 (30분 무수익시)")

        if self.hidden_opportunities:
            avg_hidden_return = np.mean([op['potential_return'] for op in self.hidden_opportunities])
            print(f"4. 놓친 기회 활용:")
            print(f"   - {len(self.hidden_opportunities)}개 기회 발견 (평균 {avg_hidden_return:.2f}% 수익)")
            print("   - 패턴 감지 감도 조정 고려")

    def run_comprehensive_analysis(self):
        """종합 분석 실행"""
        print("개선된 매매 신호 분석을 시작합니다...")

        # 1. 거래 데이터 추출
        self.extract_trades_from_log()

        if not self.all_trades:
            print("분석할 거래 데이터가 없습니다.")
            return

        # 2. 승리/패배 패턴 분석
        win_df = self.analyze_winning_patterns()
        loss_df = self.analyze_losing_patterns()

        # 3. 숨겨진 기회 탐지
        self.find_hidden_opportunities_simple()

        # 4. 최적화 권장사항
        self.generate_optimization_recommendations()

        # 5. 결과 저장
        self.save_results(win_df, loss_df)

        return {
            'total_trades': len(self.all_trades),
            'winning_trades': len(self.winning_trades),
            'losing_trades': len(self.losing_trades),
            'hidden_opportunities': len(self.hidden_opportunities)
        }

    def save_results(self, win_df: pd.DataFrame, loss_df: pd.DataFrame):
        """결과 저장"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV 저장
        if not win_df.empty:
            win_df.to_csv(self.output_dir / f"winning_patterns_{timestamp}.csv",
                         index=False, encoding='utf-8-sig')

        if not loss_df.empty:
            loss_df.to_csv(self.output_dir / f"losing_patterns_{timestamp}.csv",
                          index=False, encoding='utf-8-sig')

        if self.hidden_opportunities:
            hidden_df = pd.DataFrame(self.hidden_opportunities)
            hidden_df.to_csv(self.output_dir / f"hidden_opportunities_{timestamp}.csv",
                            index=False, encoding='utf-8-sig')

        # 종합 보고서
        report_path = self.output_dir / f"analysis_report_{timestamp}.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=== 개선된 매매 신호 분석 보고서 ===\n\n")
            f.write(f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            if self.all_trades:
                total = len(self.all_trades)
                wins = len(self.winning_trades)
                win_rate = wins / total * 100

                f.write(f"총 거래: {total}개\n")
                f.write(f"승리: {wins}개, 패배: {total - wins}개\n")
                f.write(f"현재 승률: {win_rate:.1f}%\n\n")

                if self.hidden_opportunities:
                    f.write(f"숨겨진 기회: {len(self.hidden_opportunities)}개\n")
                    avg_return = np.mean([op['potential_return'] for op in self.hidden_opportunities])
                    f.write(f"평균 잠재 수익률: {avg_return:.2f}%\n\n")

                f.write("=== 개선 방안 ===\n")
                f.write("1. 시간대별 선별적 매매\n")
                f.write("2. 패턴 조건 강화 (이등분선, 거래량)\n")
                f.write("3. 일봉 패턴 추가 필터링\n")
                f.write("4. 손절 규칙 최적화\n")

        print(f"분석 보고서 저장: {report_path}")

def main():
    analyzer = ImprovedSignalAnalyzer()
    results = analyzer.run_comprehensive_analysis()
    print(f"\n분석 완료: {results}")

if __name__ == "__main__":
    main()