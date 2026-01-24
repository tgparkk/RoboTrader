"""
signal_replay_log 기반 최적 투자 비율 분석 v2
- 리스크 분석 추가
- 최대 낙폭(MDD) 분석
- 날짜별 상세 시뮬레이션
"""

import os
import re
import sys
from collections import defaultdict

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def parse_signal_replay_file(filepath):
    """signal_replay_log 파일에서 주요 정보 추출"""
    result = {
        'date': None,
        'total_trades': 0,
        'wins': 0,
        'losses': 0,
        'total_profit': 0,
        'max_simultaneous': 0,
        'trades': []
    }

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        return None

    m = re.search(r'(\d{8})', os.path.basename(filepath))
    if m:
        result['date'] = m.group(1)

    m = re.search(r'총 거래: (\d+)건 \((\d+)승 (\d+)패\)', content)
    if m:
        result['total_trades'] = int(m.group(1))
        result['wins'] = int(m.group(2))
        result['losses'] = int(m.group(3))

    m = re.search(r'총 수익금: ([+-]?[\d,]+)원', content)
    if m:
        result['total_profit'] = int(m.group(1).replace(',', ''))

    m = re.search(r'최대 동시 보유 종목 수: (\d+)개', content)
    if m:
        result['max_simultaneous'] = int(m.group(1))

    trade_pattern = r'(🔴|🟢)\s+(\d{6})\([^)]+\)\s+(\d{2}:\d{2})\s+매수\s+→\s+([+-]?[\d.]+)%'
    for m in re.finditer(trade_pattern, content):
        is_win = m.group(1) == '🟢'
        result['trades'].append({
            'time': m.group(3),
            'stock': m.group(2),
            'pct': float(m.group(4)),
            'is_win': is_win
        })

    return result


def simulate_day(trades, max_positions, investment_per_trade):
    """하루 동안의 시뮬레이션"""
    if not trades:
        return 0, 0, 0, 0, 0

    sorted_trades = sorted(trades, key=lambda x: x['time'])
    active_positions = []

    total_profit = 0
    executed_trades = 0
    wins = 0
    max_loss = 0  # 최대 단일 손실

    for trade in sorted_trades:
        current_time = int(trade['time'].replace(':', ''))
        active_positions = [pos for pos in active_positions if pos > current_time - 30]

        if len(active_positions) < max_positions:
            executed_trades += 1
            profit = investment_per_trade * trade['pct'] / 100
            total_profit += profit
            if trade['is_win']:
                wins += 1
            else:
                max_loss = min(max_loss, profit)
            active_positions.append(current_time)

    skipped = len(trades) - executed_trades
    return executed_trades, total_profit, wins, max_loss, skipped


def main():
    log_dir = 'signal_replay_log'
    files = [f for f in os.listdir(log_dir)
             if f.startswith('signal_new2_replay_')
             and f.endswith('.txt')
             and 'ml_filtered' not in f]

    all_data = []
    for f in files:
        filepath = os.path.join(log_dir, f)
        data = parse_signal_replay_file(filepath)
        if data and data['total_trades'] > 0:
            all_data.append(data)

    # 날짜순 정렬
    all_data.sort(key=lambda x: x['date'])

    print("=" * 80)
    print("최적 투자 비율 분석 v2 (리스크 분석 포함)")
    print("=" * 80)
    print(f"분석 기간: {all_data[0]['date']} ~ {all_data[-1]['date']}")
    print(f"거래일: {len(all_data)}일")

    total_capital = 11_000_000

    print("\n" + "=" * 80)
    print("비율별 상세 시뮬레이션")
    print("=" * 80)

    ratios = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    results = {}

    for max_pos in ratios:
        investment_per = total_capital / max_pos

        daily_profits = []
        total_trades = 0
        total_wins = 0
        total_skipped = 0
        worst_day_loss = 0
        best_day_profit = 0

        # 누적 수익 추적 (MDD 계산용)
        cumulative = 0
        peak = 0
        max_drawdown = 0

        for data in all_data:
            executed, profit, wins, max_loss, skipped = simulate_day(
                data['trades'], max_pos, investment_per
            )
            daily_profits.append(profit)
            total_trades += executed
            total_wins += wins
            total_skipped += skipped

            worst_day_loss = min(worst_day_loss, profit)
            best_day_profit = max(best_day_profit, profit)

            cumulative += profit
            peak = max(peak, cumulative)
            drawdown = peak - cumulative
            max_drawdown = max(max_drawdown, drawdown)

        total_profit = sum(daily_profits)
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        avg_daily = total_profit / len(all_data)
        positive_days = sum(1 for p in daily_profits if p > 0)

        results[max_pos] = {
            'total_profit': total_profit,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_daily': avg_daily,
            'positive_days': positive_days,
            'worst_day': worst_day_loss,
            'best_day': best_day_profit,
            'max_drawdown': max_drawdown,
            'skipped': total_skipped,
            'investment_per': investment_per
        }

    # 결과 출력
    print(f"\n{'비율':^6} | {'건당투자':^12} | {'거래수':^6} | {'승률':^6} | "
          f"{'총수익':^12} | {'일평균':^10} | {'MDD':^10} | {'최악일':^10}")
    print("-" * 100)

    for max_pos in ratios:
        r = results[max_pos]
        print(f"1/{max_pos:<4} | {r['investment_per']:>10,.0f}원 | "
              f"{r['total_trades']:>5}건 | {r['win_rate']:>5.1f}% | "
              f"{r['total_profit']:>+11,.0f}원 | {r['avg_daily']:>+9,.0f}원 | "
              f"{r['max_drawdown']:>9,.0f}원 | {r['worst_day']:>+9,.0f}원")

    # 리스크 조정 수익률 계산
    print("\n" + "=" * 80)
    print("리스크 조정 분석")
    print("=" * 80)

    print(f"\n{'비율':^6} | {'총수익':^12} | {'MDD':^10} | {'수익/MDD':^8} | {'누락거래':^6} | {'평가'}")
    print("-" * 80)

    for max_pos in ratios:
        r = results[max_pos]
        reward_risk = r['total_profit'] / r['max_drawdown'] if r['max_drawdown'] > 0 else 999

        if reward_risk > 5:
            rating = "★★★★★ 최고"
        elif reward_risk > 4:
            rating = "★★★★☆ 우수"
        elif reward_risk > 3:
            rating = "★★★☆☆ 양호"
        elif reward_risk > 2:
            rating = "★★☆☆☆ 보통"
        else:
            rating = "★☆☆☆☆ 주의"

        print(f"1/{max_pos:<4} | {r['total_profit']:>+11,.0f}원 | "
              f"{r['max_drawdown']:>9,.0f}원 | {reward_risk:>7.2f} | "
              f"{r['skipped']:>5}건 | {rating}")

    # 최종 추천
    print("\n" + "=" * 80)
    print("최종 권장사항")
    print("=" * 80)

    # 수익/MDD 비율 기준 최적
    best_risk_adjusted = max(ratios, key=lambda x: results[x]['total_profit'] / results[x]['max_drawdown'] if results[x]['max_drawdown'] > 0 else 0)
    # 총 수익 기준 최적
    best_profit = min(ratios, key=lambda x: -results[x]['total_profit'])
    # 누락 거래 최소
    min_skipped = min(ratios, key=lambda x: results[x]['skipped'])

    print(f"""
1. 수익/리스크 최적 비율: 1/{best_risk_adjusted}
   - 총 수익: {results[best_risk_adjusted]['total_profit']:+,.0f}원
   - 최대 낙폭(MDD): {results[best_risk_adjusted]['max_drawdown']:,.0f}원
   - 수익/MDD: {results[best_risk_adjusted]['total_profit']/results[best_risk_adjusted]['max_drawdown']:.2f}

2. 총 수익 최적 비율: 1/{best_profit}
   - 총 수익: {results[best_profit]['total_profit']:+,.0f}원
   - 최대 낙폭(MDD): {results[best_profit]['max_drawdown']:,.0f}원
   - 누락 거래: {results[best_profit]['skipped']}건

3. 현재 설정 (1/11) 분석:
   - 총 수익: {results[11]['total_profit']:+,.0f}원
   - 최대 낙폭(MDD): {results[11]['max_drawdown']:,.0f}원
   - 수익/MDD: {results[11]['total_profit']/results[11]['max_drawdown']:.2f}
   - 누락 거래: {results[11]['skipped']}건

4. 권장 변경:
   - 공격적: 1/{best_profit} (수익 극대화, 리스크 증가)
   - 균형적: 1/{best_risk_adjusted} (리스크 대비 수익 최적)
   - 보수적: 1/11 유지 (현재 설정)
""")

    # 동시 보유 패턴 분석
    print("=" * 80)
    print("동시 보유 패턴 vs 누락 위험")
    print("=" * 80)

    max_sim_counts = [data['max_simultaneous'] for data in all_data]
    print(f"\n동시 보유 5개 이상 발생일: {sum(1 for x in max_sim_counts if x >= 5)}일 ({sum(1 for x in max_sim_counts if x >= 5)/len(all_data)*100:.1f}%)")
    print(f"동시 보유 8개 이상 발생일: {sum(1 for x in max_sim_counts if x >= 8)}일 ({sum(1 for x in max_sim_counts if x >= 8)/len(all_data)*100:.1f}%)")
    print(f"동시 보유 10개 이상 발생일: {sum(1 for x in max_sim_counts if x >= 10)}일 ({sum(1 for x in max_sim_counts if x >= 10)/len(all_data)*100:.1f}%)")

    # 실제 데이터 기반 권장
    percentile_80 = sorted(max_sim_counts)[int(len(max_sim_counts) * 0.8)]
    percentile_90 = sorted(max_sim_counts)[int(len(max_sim_counts) * 0.9)]
    percentile_95 = sorted(max_sim_counts)[int(len(max_sim_counts) * 0.95)]

    print(f"\n80% 커버: 동시 {percentile_80}개 이하 → 1/{percentile_80} 추천")
    print(f"90% 커버: 동시 {percentile_90}개 이하 → 1/{percentile_90} 추천")
    print(f"95% 커버: 동시 {percentile_95}개 이하 → 1/{percentile_95} 추천")


if __name__ == '__main__':
    main()
