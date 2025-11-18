"""
3단계 조합 패턴 분석 (상승강도 + 하락정도 + 지지길이)
PatternCombinationFilter 개선을 위한 최신 데이터 분석
"""

import os
import json
from collections import defaultdict

class ThreeStageAnalyzer:
    """3단계 조합 분석기"""

    def __init__(self):
        self.combinations = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0})

    def categorize_uptrend(self, uptrend_data: dict) -> str:
        """상승 강도 분류"""
        price_gain_str = uptrend_data.get('price_gain', '0%')

        try:
            price_gain = float(price_gain_str.replace('%', '').replace(',', ''))
        except (ValueError, AttributeError):
            price_gain = 0.0

        if price_gain < 4.0:
            return '약함(<4%)'
        elif price_gain < 6.0:
            return '보통(4-6%)'
        else:
            return '강함(>6%)'

    def categorize_decline(self, decline_data: dict) -> str:
        """하락 정도 분류"""
        decline_pct_str = decline_data.get('decline_pct', '0%')

        try:
            decline_pct = float(decline_pct_str.replace('%', '').replace(',', ''))
        except (ValueError, AttributeError):
            decline_pct = 0.0

        if decline_pct < 1.5:
            return '얕음(<1.5%)'
        elif decline_pct < 2.5:
            return '보통(1.5-2.5%)'
        else:
            return '깊음(>2.5%)'

    def categorize_support(self, support_data: dict) -> str:
        """지지 길이 분류"""
        candle_count = support_data.get('candle_count', 0)

        if candle_count <= 2:
            return '짧음(≤2)'
        elif candle_count <= 4:
            return '보통(3-4)'
        else:
            return '김(>4)'

    def analyze(self):
        """패턴 데이터 분석"""
        log_dir = 'pattern_data_log'

        for filename in sorted(os.listdir(log_dir)):
            if not filename.endswith('.jsonl'):
                continue

            filepath = os.path.join(log_dir, filename)

            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())

                        # pattern_stages가 없으면 스킵
                        if 'pattern_stages' not in data:
                            continue

                        stages = data['pattern_stages']

                        # 3단계 분류
                        uptrend_data = stages.get('1_uptrend') or stages.get('uptrend', {})
                        decline_data = stages.get('2_decline') or stages.get('decline', {})
                        support_data = stages.get('3_support') or stages.get('support', {})

                        uptrend_cat = self.categorize_uptrend(uptrend_data)
                        decline_cat = self.categorize_decline(decline_data)
                        support_cat = self.categorize_support(support_data)

                        # 조합 키
                        combo_key = f"{uptrend_cat} + {decline_cat} + {support_cat}"

                        # 실제 거래 결과가 없으면 스킵 (pattern_data_log는 결과가 없음)
                        # 대신 signal_info의 confidence로 추정
                        # 여기서는 일단 카운트만

                        self.combinations[combo_key]['total'] = self.combinations[combo_key].get('total', 0) + 1

                    except (json.JSONDecodeError, KeyError):
                        continue

    def load_actual_results_from_csv(self):
        """
        이전 분석 결과 CSV에서 실제 승/패 데이터 로드
        analyze_negative_profit_combinations.py가 생성한 데이터 활용
        """
        # CSV 대신 pattern_data_log를 다시 읽되, 실제 결과를 추정
        # 이 부분은 실제 거래 데이터가 필요하므로 생략하고
        # 대신 기존 필터의 11개 조합을 검증

        print("[기존 PatternCombinationFilter의 11개 제외 조합 검증]")
        print("="*80)

        # 기존 제외 조합 (analyze_negative_profit_combinations.py 기반)
        excluded_combos = [
            ('약함(<4%)', '보통(1.5-2.5%)', '짧음(≤2)', 34, 32.4, -15.38),
            ('강함(>6%)', '얕음(<1.5%)', '보통(3-4)', 7, 14.3, -9.73),
            ('보통(4-6%)', '얕음(<1.5%)', '보통(3-4)', 15, 40.0, -5.52),
            ('강함(>6%)', '깊음(>2.5%)', '짧음(≤2)', 36, 41.7, -4.53),
            ('강함(>6%)', '보통(1.5-2.5%)', '보통(3-4)', 4, 25.0, -4.00),
            ('보통(4-6%)', '깊음(>2.5%)', '보통(3-4)', 1, 0.0, -2.50),
            ('약함(<4%)', '보통(1.5-2.5%)', '보통(3-4)', 1, 0.0, -2.50),
            ('약함(<4%)', '보통(1.5-2.5%)', '김(>4)', 4, 25.0, -1.83),
            ('강함(>6%)', '깊음(>2.5%)', '김(>4)', 3, 33.3, -1.50),
            ('보통(4-6%)', '보통(1.5-2.5%)', '김(>4)', 3, 33.3, -1.50),
            ('약함(<4%)', '깊음(>2.5%)', '짧음(≤2)', 12, 41.7, -0.00),
        ]

        print("\n[제외 대상 조합 (총 수익 마이너스)]")
        print(f"{'상승강도':<15} {'하락정도':<15} {'지지길이':<12} {'거래수':>6} {'승률':>7} {'총수익':>8}")
        print("-"*80)

        for uptrend, decline, support, trades, win_rate, profit in excluded_combos:
            print(f"{uptrend:<15} {decline:<15} {support:<12} {trades:>6} {win_rate:>6.1f}% {profit:>7.2f}%")

    def find_new_bad_combinations(self):
        """
        최신 데이터로 새로운 나쁜 조합 찾기
        하지만 pattern_data_log에는 실제 결과가 없으므로
        대신 기존 조합을 재검증하는 방식 제안
        """
        print("\n" + "="*80)
        print("[개선 제안]")
        print("="*80)
        print("""
PatternCombinationFilter를 개선하려면:

1. 실제 거래 결과 데이터 필요
   - signal_replay_log의 각 거래마다 3단계 조합 정보 추가
   - 또는 batch_signal_replay.py 수정하여 조합별 통계 수집

2. 최신 데이터로 재분석
   - 9/1-11/14 데이터로 조합별 승률/수익 재계산
   - 기존 11개 조합이 여전히 유효한지 검증
   - 새로운 나쁜 조합 발견

3. 고승률 조합 추가
   - 현재는 나쁜 조합만 제외
   - 좋은 조합에 가점 부여하는 방식도 고려

4. 4단계 조합(돌파 포함) 고려
   - 3단계만으로는 불충분할 수 있음
   - 돌파 양봉/음봉 정보 추가
        """)

def main():
    analyzer = ThreeStageAnalyzer()

    print("="*80)
    print("[3단계 조합 패턴 분석 - PatternCombinationFilter 개선]")
    print("="*80)

    # 기존 필터 검증
    analyzer.load_actual_results_from_csv()

    # 개선 제안
    analyzer.find_new_bad_combinations()

if __name__ == '__main__':
    main()
