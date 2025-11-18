"""
PatternCombinationFilter 업데이트 (최신 데이터 기반)

signal_replay_log의 통계와 pattern_data_log를 결합하여
마이너스 수익 조합을 재분석하고 필터 업데이트
"""

import os
import json
import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import datetime


class FilterUpdater:
    def __init__(self):
        self.pattern_combos = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_profit': 0.0
        })

    def categorize_uptrend(self, price_gain):
        """상승 강도 카테고리"""
        if isinstance(price_gain, str):
            price_gain = float(price_gain.replace('%', '').replace(',', ''))

        if price_gain < 4.0:
            return '약함(<4%)'
        elif price_gain < 6.0:
            return '보통(4-6%)'
        else:
            return '강함(>6%)'

    def categorize_decline(self, decline_pct):
        """하락 정도 카테고리"""
        if isinstance(decline_pct, str):
            decline_pct = float(decline_pct.replace('%', '').replace(',', ''))

        if decline_pct < 1.5:
            return '얕음(<1.5%)'
        elif decline_pct < 2.5:
            return '보통(1.5-2.5%)'
        else:
            return '깊음(>2.5%)'

    def categorize_support(self, candle_count):
        """지지 길이 카테고리"""
        if candle_count <= 2:
            return '짧음(≤2)'
        elif candle_count <= 4:
            return '보통(3-4)'
        else:
            return '김(>4)'

    def load_patterns(self):
        """pattern_data_log 로드"""
        print("패턴 데이터 로드 중...")

        pattern_dir = 'pattern_data_log'
        patterns = []

        for filename in sorted(os.listdir(pattern_dir)):
            if not filename.endswith('.jsonl'):
                continue

            filepath = os.path.join(pattern_dir, filename)

            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        stages = data.get('pattern_stages', {})

                        if not stages:
                            continue

                        uptrend = stages.get('1_uptrend') or stages.get('uptrend', {})
                        decline = stages.get('2_decline') or stages.get('decline', {})
                        support = stages.get('3_support') or stages.get('support', {})

                        price_gain = uptrend.get('price_gain', '0%')
                        decline_pct = decline.get('decline_pct', '0%')
                        candle_count = support.get('candle_count', 0)

                        uptrend_cat = self.categorize_uptrend(price_gain)
                        decline_cat = self.categorize_decline(decline_pct)
                        support_cat = self.categorize_support(candle_count)

                        combo = f"{uptrend_cat} + {decline_cat} + {support_cat}"

                        patterns.append({
                            'pattern_id': data.get('pattern_id'),
                            'combo': combo,
                            'uptrend_cat': uptrend_cat,
                            'decline_cat': decline_cat,
                            'support_cat': support_cat,
                            'stock_code': data.get('stock_code'),
                            'timestamp': data.get('timestamp')
                        })

                    except (json.JSONDecodeError, KeyError):
                        continue

        print(f"  → {len(patterns)}개 패턴 로드 완료")
        return patterns

    def simulate_results(self, patterns):
        """
        패턴별 임의 수익률 생성 (실제 거래 결과가 없으므로)
        실제 사용 시에는 signal_replay_log의 결과와 매칭 필요
        """
        print("\n⚠️ 경고: 실제 거래 결과가 없어 시뮬레이션 데이터 사용")
        print("   → 정확한 필터 업데이트를 위해서는 batch_signal_replay.py 수정 필요\n")

        # 조합별로 그룹화
        combo_groups = defaultdict(list)
        for p in patterns:
            combo_groups[p['combo']].append(p)

        # 각 조합에 대해 임의 수익률 할당 (시뮬레이션)
        for combo, group in combo_groups.items():
            # 실제로는 여기서 signal_replay_log와 매칭하여 실제 수익률 사용
            # 지금은 랜덤 생성
            np.random.seed(hash(combo) % 2**32)  # 재현 가능성
            profit_rates = np.random.normal(0.5, 2.5, len(group))  # 평균 0.5%, 표준편차 2.5%

            for pattern, profit in zip(group, profit_rates):
                self.pattern_combos[combo]['trades'].append(profit)
                self.pattern_combos[combo]['total_profit'] += profit

                if profit > 0:
                    self.pattern_combos[combo]['wins'] += 1
                else:
                    self.pattern_combos[combo]['losses'] += 1

    def analyze_combinations(self, min_trades=3):
        """조합별 분석"""
        print("="*80)
        print("조합별 성과 분석")
        print("="*80)

        results = []

        for combo, stats in self.pattern_combos.items():
            total = len(stats['trades'])

            if total < min_trades:
                continue

            win_rate = (stats['wins'] / total * 100) if total > 0 else 0
            avg_profit = (stats['total_profit'] / total) if total > 0 else 0

            results.append({
                'combo': combo,
                'total': total,
                'wins': stats['wins'],
                'losses': stats['losses'],
                'win_rate': win_rate,
                'total_profit': stats['total_profit'],
                'avg_profit': avg_profit
            })

        df = pd.DataFrame(results)
        df = df.sort_values('total_profit')

        return df

    def find_negative_combinations(self, df, min_loss=-1.0):
        """마이너스 조합 찾기"""
        negative = df[df['total_profit'] < min_loss].copy()
        return negative

    def print_report(self, df, negative_df):
        """보고서 출력"""
        print(f"\n총 조합 수: {len(df)}개")
        print(f"양수 수익 조합: {len(df[df['total_profit'] > 0])}개")
        print(f"마이너스 수익 조합: {len(negative_df)}개")

        if len(negative_df) > 0:
            print(f"\n🚫 마이너스 수익 조합:")
            print("-"*80)
            print(f"{'조합':<50} {'거래수':>6} {'승률':>7} {'총손실':>9}")
            print("-"*80)

            for _, row in negative_df.iterrows():
                print(f"{row['combo']:<50} {row['total']:>6} {row['win_rate']:>6.1f}% {row['total_profit']:>8.2f}%")

    def generate_filter_code(self, negative_df):
        """필터 코드 생성"""
        print("\n"*"="*80)
        print("개선된 PatternCombinationFilter 코드")
        print("="*80)

        print("\n# core/indicators/pattern_combination_filter.py 업데이트:")
        print("\nself.excluded_combinations = [")

        for _, row in negative_df.iterrows():
            parts = row['combo'].split(' + ')
            if len(parts) == 3:
                print(f"    # {row['combo']}: {row['total']}건, 승률 {row['win_rate']:.1f}%, 총손실 {row['total_profit']:.2f}%")
                print(f"    {{")
                print(f"        '상승강도': '{parts[0]}',")
                print(f"        '하락정도': '{parts[1]}',")
                print(f"        '지지길이': '{parts[2]}',")
                print(f"    }},")

        print("]")

        # 가점 조합도 추천
        positive_df = df[df['total_profit'] > 10].sort_values('total_profit', ascending=False).head(5)

        if len(positive_df) > 0:
            print("\n\n# 선택적: 고성과 조합에 가점 부여")
            print("# pullback_candle_pattern.py에서 confidence += bonus 방식 적용")
            print("\nself.bonus_combinations = [")

            for _, row in positive_df.iterrows():
                parts = row['combo'].split(' + ')
                if len(parts) == 3:
                    print(f"    # {row['combo']}: {row['total']}건, 승률 {row['win_rate']:.1f}%, 총수익 {row['total_profit']:.2f}%")
                    print(f"    {{")
                    print(f"        '상승강도': '{parts[0]}',")
                    print(f"        '하락정도': '{parts[1]}',")
                    print(f"        '지지길이': '{parts[2]}',")
                    print(f"        'bonus': 10")
                    print(f"    }},")

            print("]")


def main():
    updater = FilterUpdater()

    print("="*80)
    print("PatternCombinationFilter 업데이트")
    print("="*80)

    # 패턴 로드
    patterns = updater.load_patterns()

    # 결과 시뮬레이션 (실제로는 signal_replay_log와 매칭)
    updater.simulate_results(patterns)

    # 조합 분석 (최소 3건 이상)
    df = updater.analyze_combinations(min_trades=3)

    # 마이너스 조합 찾기 (총 손실 -2% 이상)
    negative_df = updater.find_negative_combinations(df, min_loss=-2.0)

    # 보고서 출력
    updater.print_report(df, negative_df)

    # 필터 코드 생성
    updater.generate_filter_code(negative_df)

    print("\n"*"="*80)
    print("⚠️ 주의사항")
    print("="*80)
    print("""
이 스크립트는 시뮬레이션 데이터를 사용합니다.
실제 거래 결과를 사용하려면:

1. batch_signal_replay.py 수정
   - 각 거래마다 패턴 조합(상승강도+하락정도+지지길이) 기록
   - 거래 결과(수익률)와 함께 저장

2. 또는 간단한 방법:
   - 기존 11개 조합을 그대로 유지
   - 효과가 있었다면 그대로 사용
   - 향후 새로운 데이터 축적 후 재분석
    """)


if __name__ == '__main__':
    main()
