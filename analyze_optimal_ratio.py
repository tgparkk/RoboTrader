"""
signal_replay_log 파일들을 분석하여 최적의 투자 비율을 찾는 스크립트
- 일별 동시 보유 종목 수 분석
- 보유 종목 수에 따른 수익률 분석
- 최적 비율 추천
"""

import os
import re
import sys
from collections import defaultdict
from datetime import datetime

# Windows 콘솔 인코딩 설정
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
        'trades': []  # (time, stock, result_pct) 리스트
    }

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        return None

    # 파일명에서 날짜 추출
    m = re.search(r'(\d{8})', os.path.basename(filepath))
    if m:
        result['date'] = m.group(1)

    # 총 거래 정보
    m = re.search(r'총 거래: (\d+)건 \((\d+)승 (\d+)패\)', content)
    if m:
        result['total_trades'] = int(m.group(1))
        result['wins'] = int(m.group(2))
        result['losses'] = int(m.group(3))

    # 총 수익금
    m = re.search(r'총 수익금: ([+-]?[\d,]+)원', content)
    if m:
        result['total_profit'] = int(m.group(1).replace(',', ''))

    # 최대 동시 보유 종목 수
    m = re.search(r'최대 동시 보유 종목 수: (\d+)개', content)
    if m:
        result['max_simultaneous'] = int(m.group(1))

    # 개별 거래 정보 (🔴/🟢 라인)
    trade_pattern = r'(🔴|🟢)\s+(\d{6})\([^)]+\)\s+(\d{2}:\d{2})\s+매수\s+→\s+([+-]?[\d.]+)%'
    for m in re.finditer(trade_pattern, content):
        is_win = m.group(1) == '🟢'
        stock = m.group(2)
        time = m.group(3)
        pct = float(m.group(4))
        result['trades'].append({
            'time': time,
            'stock': stock,
            'pct': pct,
            'is_win': is_win
        })

    return result


def calculate_simultaneous_positions(trades):
    """매매 시간 기반으로 동시 보유 종목 수 계산"""
    if not trades:
        return 0, []

    # 시간순 정렬
    sorted_trades = sorted(trades, key=lambda x: x['time'])

    # 각 매매에서 동시에 몇 개가 진행중이었는지 계산
    # 익절/손절 3.5%/-2.5% 기준, 평균 보유시간 약 30분으로 가정
    positions = []
    for i, trade in enumerate(sorted_trades):
        # 현재 시간 기준 이전 30분 내 거래 수 카운트
        current_time = int(trade['time'].replace(':', ''))
        count = 0
        for j, prev_trade in enumerate(sorted_trades[:i+1]):
            prev_time = int(prev_trade['time'].replace(':', ''))
            # 30분 이내 거래 (동시 보유 가능성)
            if current_time - prev_time <= 30:  # 0930 - 0900 = 30
                count += 1
        positions.append(count)

    return max(positions) if positions else 0, positions


def simulate_with_limit(trades, max_positions, investment_per_trade):
    """최대 동시 보유 제한을 적용한 시뮬레이션"""
    if not trades:
        return 0, 0, 0

    sorted_trades = sorted(trades, key=lambda x: x['time'])

    total_profit = 0
    executed_trades = 0
    wins = 0

    # 간단한 시뮬: 동시 보유 제한을 30분 윈도우로 적용
    active_positions = []  # (end_time_estimate, is_completed)

    for trade in sorted_trades:
        current_time = int(trade['time'].replace(':', ''))

        # 종료된 포지션 제거 (30분 지난 것)
        active_positions = [pos for pos in active_positions if pos > current_time - 30]

        # 동시 보유 한도 체크
        if len(active_positions) < max_positions:
            # 매매 실행
            executed_trades += 1
            profit = investment_per_trade * trade['pct'] / 100
            total_profit += profit
            if trade['is_win']:
                wins += 1
            active_positions.append(current_time)

    win_rate = (wins / executed_trades * 100) if executed_trades > 0 else 0
    return executed_trades, total_profit, win_rate


def main():
    log_dir = 'signal_replay_log'

    # ml_filtered 아닌 파일만 선택
    files = [f for f in os.listdir(log_dir)
             if f.startswith('signal_new2_replay_')
             and f.endswith('.txt')
             and 'ml_filtered' not in f]

    print("=" * 80)
    print("signal_replay_log 기반 최적 투자 비율 분석")
    print("=" * 80)
    print(f"분석 파일 수: {len(files)}")
    print()

    all_data = []
    for f in files:
        filepath = os.path.join(log_dir, f)
        data = parse_signal_replay_file(filepath)
        if data and data['total_trades'] > 0:
            all_data.append(data)

    print(f"유효 거래일: {len(all_data)}")

    # 1. 일별 통계
    print("\n" + "=" * 80)
    print("1. 일별 최대 동시 보유 종목 수 분포")
    print("=" * 80)

    max_sim_dist = defaultdict(int)
    for data in all_data:
        max_sim_dist[data['max_simultaneous']] += 1

    for cnt in sorted(max_sim_dist.keys()):
        days = max_sim_dist[cnt]
        print(f"  {cnt}개: {days}일 ({days/len(all_data)*100:.1f}%)")

    # 2. 최대 동시 보유 별 수익 분석
    print("\n" + "=" * 80)
    print("2. 최대 동시 보유 종목 수 vs 수익 분석")
    print("=" * 80)

    profit_by_max = defaultdict(list)
    for data in all_data:
        profit_by_max[data['max_simultaneous']].append(data['total_profit'])

    for cnt in sorted(profit_by_max.keys()):
        profits = profit_by_max[cnt]
        avg = sum(profits) / len(profits)
        total = sum(profits)
        positive_days = sum(1 for p in profits if p > 0)
        print(f"  {cnt}개: {len(profits)}일, 평균 {avg:+,.0f}원, 합계 {total:+,.0f}원, 수익일 {positive_days}일 ({positive_days/len(profits)*100:.1f}%)")

    # 3. 시간대별 거래 분포 및 동시 보유 패턴
    print("\n" + "=" * 80)
    print("3. 시간대별 거래 빈도")
    print("=" * 80)

    time_dist = defaultdict(int)
    for data in all_data:
        for trade in data['trades']:
            hour = trade['time'][:2]
            time_dist[hour] += 1

    for hour in sorted(time_dist.keys()):
        cnt = time_dist[hour]
        bar = '#' * (cnt // 10)
        print(f"  {hour}시: {cnt}건 {bar}")

    # 4. 투자 비율별 시뮬레이션
    print("\n" + "=" * 80)
    print("4. 동시 보유 제한별 수익 시뮬레이션 (투자금 기준)")
    print("=" * 80)

    total_capital = 11_000_000  # 총 자본금 (현재 1/11 = 100만원씩)

    print(f"총 자본금: {total_capital:,}원")
    print()

    simulation_results = []

    for max_pos in range(3, 16):  # 3개 ~ 15개 동시 보유
        investment_per = total_capital / max_pos

        total_trades = 0
        total_profit = 0
        total_wins = 0

        for data in all_data:
            executed, profit, win_rate = simulate_with_limit(
                data['trades'], max_pos, investment_per
            )
            total_trades += executed
            # 수익금 계산 (건당 투자금 기준)
            for trade in data['trades'][:executed]:  # 간단 시뮬
                total_profit += investment_per * trade['pct'] / 100
                if trade['is_win']:
                    total_wins += 1

        # 간단 시뮬레이션: 전체 거래 대상으로
        all_trades = []
        for data in all_data:
            for trade in data['trades']:
                all_trades.append(trade)

        # 날짜+시간 순으로 정렬 후 제한 적용
        daily_results = []
        for data in all_data:
            executed, profit, wr = simulate_with_limit(data['trades'], max_pos, investment_per)
            daily_results.append({'trades': executed, 'profit': profit, 'win_rate': wr})

        sim_total_trades = sum(r['trades'] for r in daily_results)
        sim_total_profit = sum(r['profit'] for r in daily_results)
        avg_wr = sum(r['win_rate'] for r in daily_results) / len(daily_results) if daily_results else 0

        simulation_results.append({
            'max_pos': max_pos,
            'investment_per': investment_per,
            'total_trades': sim_total_trades,
            'total_profit': sim_total_profit,
            'avg_win_rate': avg_wr
        })

        print(f"  1/{max_pos} (건당 {investment_per:,.0f}원): "
              f"거래 {sim_total_trades}건, 수익 {sim_total_profit:+,.0f}원")

    # 5. 최적 비율 추천
    print("\n" + "=" * 80)
    print("5. 최적 투자 비율 추천")
    print("=" * 80)

    # 수익금 기준 최적
    best_profit = max(simulation_results, key=lambda x: x['total_profit'])
    print(f"\n수익금 최적: 1/{best_profit['max_pos']} "
          f"(건당 {best_profit['investment_per']:,.0f}원)")
    print(f"  → 예상 거래: {best_profit['total_trades']}건, "
          f"예상 수익: {best_profit['total_profit']:+,.0f}원")

    # 리스크 조정 수익 (샤프비율 유사)
    for res in simulation_results:
        res['profit_per_trade'] = res['total_profit'] / res['total_trades'] if res['total_trades'] > 0 else 0

    best_efficiency = max(simulation_results, key=lambda x: x['profit_per_trade'])
    print(f"\n거래당 수익 최적: 1/{best_efficiency['max_pos']} "
          f"(건당 {best_efficiency['investment_per']:,.0f}원)")
    print(f"  → 거래당 평균: {best_efficiency['profit_per_trade']:+,.0f}원")

    # 6. 현재 설정 대비 비교
    print("\n" + "=" * 80)
    print("6. 현재 설정 (1/11) 대비 비교")
    print("=" * 80)

    current = next((r for r in simulation_results if r['max_pos'] == 11), None)
    if current:
        print(f"\n현재 (1/11): 거래 {current['total_trades']}건, 수익 {current['total_profit']:+,.0f}원")
        print(f"추천 (1/{best_profit['max_pos']}): 거래 {best_profit['total_trades']}건, "
              f"수익 {best_profit['total_profit']:+,.0f}원")
        diff = best_profit['total_profit'] - current['total_profit']
        print(f"차이: {diff:+,.0f}원 ({diff/abs(current['total_profit'])*100 if current['total_profit'] != 0 else 0:+.1f}%)")

    # 7. 실제 일별 데이터로 추가 분석
    print("\n" + "=" * 80)
    print("7. 일별 거래 패턴 분석")
    print("=" * 80)

    trade_counts = [data['total_trades'] for data in all_data]
    avg_trades = sum(trade_counts) / len(trade_counts)
    max_trades = max(trade_counts)
    min_trades = min(trade_counts)

    print(f"일 평균 거래: {avg_trades:.1f}건")
    print(f"일 최대 거래: {max_trades}건")
    print(f"일 최소 거래: {min_trades}건")

    # 거래 건수 분포
    print("\n거래 건수별 일수:")
    trade_cnt_dist = defaultdict(int)
    for cnt in trade_counts:
        bucket = (cnt // 5) * 5  # 5건 단위
        trade_cnt_dist[bucket] += 1

    for bucket in sorted(trade_cnt_dist.keys()):
        days = trade_cnt_dist[bucket]
        print(f"  {bucket}~{bucket+4}건: {days}일")

    print("\n" + "=" * 80)
    print("결론 및 권장사항")
    print("=" * 80)
    print(f"""
1. 일 평균 거래: {avg_trades:.1f}건, 일 최대 동시 보유: {max(max_sim_dist.keys())}개

2. 현재 1/11 (건당 100만원) 설정 분석:
   - 대부분의 날짜에서 동시 보유 {sum(max_sim_dist[k] for k in max_sim_dist if k <= 11)}일/{len(all_data)}일 커버

3. 추천 비율:
   - 수익 극대화: 1/{best_profit['max_pos']} (건당 {best_profit['investment_per']:,.0f}원)
   - 효율성 최적: 1/{best_efficiency['max_pos']} (건당 {best_efficiency['investment_per']:,.0f}원)

4. 주의사항:
   - 너무 적은 분할(1/5 등)은 동시 신호 누락 위험
   - 너무 많은 분할(1/15 등)은 개별 수익 미미
   - 실제 최대 동시 보유 발생 빈도 고려 필요
""")


if __name__ == '__main__':
    main()
