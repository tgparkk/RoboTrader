"""
PatternCombinationFilter 개선
- 최신 데이터(9/1-11/14)로 3단계 조합 재분석
- pattern_data_log + signal_replay_log 결합
"""

import os
import json
import sqlite3
from collections import defaultdict
from datetime import datetime

class PatternCombinationImprover:
    """패턴 조합 필터 개선 분석기"""

    def __init__(self):
        self.combinations = defaultdict(lambda: {
            'wins': 0,
            'losses': 0,
            'total_profit': 0.0,
            'trades': []
        })

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

    def analyze_from_database(self):
        """
        데이터베이스에서 실제 거래 결과 분석
        """
        db_path = 'data/robotrader.db'

        if not os.path.exists(db_path):
            print(f"⚠️ 데이터베이스를 찾을 수 없습니다: {db_path}")
            return

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # trades 테이블에서 9/1-11/14 거래 조회
        query = """
        SELECT
            stock_code,
            buy_time,
            sell_time,
            buy_price,
            sell_price,
            profit_rate
        FROM trades
        WHERE buy_time >= '2025-09-01' AND buy_time <= '2025-11-14'
        ORDER BY buy_time
        """

        cursor.execute(query)
        trades = cursor.fetchall()

        print(f"\n데이터베이스에서 {len(trades)}건의 거래 발견")

        # 각 거래에 대해 pattern_data_log 찾기
        for stock_code, buy_time, sell_time, buy_price, sell_price, profit_rate in trades:
            # buy_time에서 날짜 추출 (2025-09-01 09:15:00 -> 20250901)
            try:
                date_obj = datetime.strptime(buy_time[:10], '%Y-%m-%d')
                date_str = date_obj.strftime('%Y%m%d')

                # pattern_data_log 파일 찾기
                log_file = f'pattern_data_log/pattern_data_{date_str}.jsonl'

                if not os.path.exists(log_file):
                    continue

                # 해당 시간대의 패턴 찾기
                pattern_found = False

                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())

                            # 종목코드와 시간 매칭
                            if data.get('stock_code') != stock_code:
                                continue

                            pattern_time = data.get('timestamp', '')
                            if not pattern_time.startswith(buy_time[:16]):  # 분까지 매칭
                                continue

                            # 패턴 발견!
                            pattern_found = True

                            stages = data.get('pattern_stages', {})
                            uptrend_data = stages.get('1_uptrend') or stages.get('uptrend', {})
                            decline_data = stages.get('2_decline') or stages.get('decline', {})
                            support_data = stages.get('3_support') or stages.get('support', {})

                            uptrend_cat = self.categorize_uptrend(uptrend_data)
                            decline_cat = self.categorize_decline(decline_data)
                            support_cat = self.categorize_support(support_data)

                            combo_key = f"{uptrend_cat} + {decline_cat} + {support_cat}"

                            # 거래 결과 기록
                            is_win = profit_rate > 0
                            if is_win:
                                self.combinations[combo_key]['wins'] += 1
                            else:
                                self.combinations[combo_key]['losses'] += 1

                            self.combinations[combo_key]['total_profit'] += profit_rate
                            self.combinations[combo_key]['trades'].append({
                                'stock_code': stock_code,
                                'buy_time': buy_time,
                                'profit_rate': profit_rate
                            })

                            break

                        except json.JSONDecodeError:
                            continue

                if not pattern_found:
                    # pattern_data_log에서 못 찾은 경우
                    pass

            except Exception as e:
                print(f"오류: {e}")
                continue

        conn.close()

    def print_results(self):
        """결과 출력"""
        print("\n" + "="*100)
        print("[3단계 조합별 성과 분석 (9/1-11/14)]")
        print("="*100)

        # 조합을 총 수익 기준으로 정렬
        sorted_combos = sorted(
            self.combinations.items(),
            key=lambda x: x[1]['total_profit']
        )

        print(f"\n{'조합':<50} {'거래수':>6} {'승리':>6} {'패배':>6} {'승률':>7} {'총수익':>9} {'평균수익':>9}")
        print("-"*100)

        for combo, stats in sorted_combos:
            total = stats['wins'] + stats['losses']
            win_rate = (stats['wins'] / total * 100) if total > 0 else 0
            avg_profit = (stats['total_profit'] / total) if total > 0 else 0

            status = "🚫" if stats['total_profit'] < 0 else "✓" if stats['total_profit'] > 10 else " "

            print(f"{status} {combo:<48} {total:>6} {stats['wins']:>6} {stats['losses']:>6} "
                  f"{win_rate:>6.1f}% {stats['total_profit']:>8.2f}% {avg_profit:>8.2f}%")

    def generate_improved_filter(self):
        """개선된 필터 코드 생성"""
        print("\n" + "="*100)
        print("[개선된 필터 제안]")
        print("="*100)

        # 마이너스 수익 조합 찾기 (거래수 3건 이상)
        bad_combos = []
        good_combos = []

        for combo, stats in self.combinations.items():
            total = stats['wins'] + stats['losses']

            if total < 3:  # 거래수 너무 적으면 제외
                continue

            win_rate = (stats['wins'] / total * 100) if total > 0 else 0
            avg_profit = (stats['total_profit'] / total) if total > 0 else 0

            if stats['total_profit'] < -2.0:  # 총 손실 -2% 이상
                bad_combos.append({
                    'combo': combo,
                    'total': total,
                    'win_rate': win_rate,
                    'total_profit': stats['total_profit'],
                    'avg_profit': avg_profit
                })
            elif stats['total_profit'] > 10.0 and win_rate > 60:  # 총 수익 +10% 이상, 승률 60% 이상
                good_combos.append({
                    'combo': combo,
                    'total': total,
                    'win_rate': win_rate,
                    'total_profit': stats['total_profit'],
                    'avg_profit': avg_profit
                })

        print(f"\n[제외 대상 조합: {len(bad_combos)}개]")
        for item in sorted(bad_combos, key=lambda x: x['total_profit']):
            print(f"  {item['combo']:<50} | {item['total']:>3}건, 승률 {item['win_rate']:>5.1f}%, "
                  f"총수익 {item['total_profit']:>7.2f}%, 평균 {item['avg_profit']:>6.2f}%")

        print(f"\n[고성과 조합: {len(good_combos)}개] (가점 부여 고려)")
        for item in sorted(good_combos, key=lambda x: -x['total_profit']):
            print(f"  {item['combo']:<50} | {item['total']:>3}건, 승률 {item['win_rate']:>5.1f}%, "
                  f"총수익 {item['total_profit']:>7.2f}%, 평균 {item['avg_profit']:>6.2f}%")

        # 코드 생성
        print("\n" + "="*100)
        print("[개선된 PatternCombinationFilter 코드]")
        print("="*100)
        print("""
self.excluded_combinations = [""")

        for item in sorted(bad_combos, key=lambda x: x['total_profit']):
            parts = item['combo'].split(' + ')
            if len(parts) == 3:
                print(f"""    # {item['combo']}: {item['total']}건, 승률 {item['win_rate']:.1f}%, 총수익 {item['total_profit']:.2f}%
    {{
        '상승강도': '{parts[0]}',
        '하락정도': '{parts[1]}',
        '지지길이': '{parts[2]}',
    }},""")

        print("""]

# 선택적: 고성과 조합에 가점 부여
self.bonus_combinations = [""")

        for item in sorted(good_combos, key=lambda x: -x['total_profit'])[:5]:  # 상위 5개만
            parts = item['combo'].split(' + ')
            if len(parts) == 3:
                print(f"""    # {item['combo']}: {item['total']}건, 승률 {item['win_rate']:.1f}%, 총수익 {item['total_profit']:.2f}%
    {{
        '상승강도': '{parts[0]}',
        '하락정도': '{parts[1]}',
        '지지길이': '{parts[2]}',
        'bonus': 10  # 가점
    }},""")

        print("""]
""")


def main():
    improver = PatternCombinationImprover()

    print("="*100)
    print("[PatternCombinationFilter 개선 분석]")
    print("="*100)

    # 데이터베이스에서 분석
    improver.analyze_from_database()

    # 결과 출력
    improver.print_results()

    # 개선된 필터 생성
    improver.generate_improved_filter()


if __name__ == '__main__':
    main()
