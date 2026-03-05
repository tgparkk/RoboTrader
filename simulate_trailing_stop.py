"""
트레일링 스탑 멀티버스 시뮬레이션 (최적화 버전)

기본 설정: 변동성 <= 1.2%, 손절 -5%, 익절 +6%
각 진입에 대해 캔들을 한 번만 스캔하면서 모든 트레일링 조합의 결과를 동시에 기록.
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


def get_trading_dates(cur, start_date, end_date=None):
    sql = "SELECT DISTINCT trade_date FROM minute_candles WHERE trade_date >= %s"
    params = [start_date]
    if end_date:
        sql += " AND trade_date <= %s"
        params.append(end_date)
    sql += " ORDER BY trade_date"
    cur.execute(sql, params)
    return [row[0] for row in cur.fetchall()]


def get_prev_close_map(cur, trade_date, prev_date):
    cur.execute('''
        SELECT stock_code, close
        FROM minute_candles
        WHERE trade_date = %s
          AND idx = (
            SELECT MAX(idx) FROM minute_candles mc2
            WHERE mc2.stock_code = minute_candles.stock_code
              AND mc2.trade_date = %s
          )
    ''', [prev_date, prev_date])
    return {row[0]: row[1] for row in cur.fetchall()}


def get_daily_metrics(cur, trade_date):
    cur.execute('''
        SELECT
            stock_code,
            MIN(CASE WHEN time >= '090000' AND time <= '090300' THEN open END) as day_open,
            SUM(amount) as daily_amount
        FROM minute_candles
        WHERE trade_date = %s
        GROUP BY stock_code
        HAVING COUNT(*) >= 50
    ''', [trade_date])
    metrics = {}
    for row in cur.fetchall():
        stock_code, day_open, daily_amount = row
        if day_open and day_open > 0 and daily_amount:
            metrics[stock_code] = {'day_open': float(day_open), 'daily_amount': float(daily_amount)}
    return metrics


def apply_screener_filter(daily_metrics, prev_close_map, top_n=60,
                          min_price=5000, max_price=500000,
                          min_amount=1_000_000_000, max_gap_pct=3.0):
    ranked = sorted(daily_metrics.items(), key=lambda x: x[1]['daily_amount'], reverse=True)[:top_n]
    passed = set()
    for stock_code, metrics in ranked:
        day_open = metrics['day_open']
        if stock_code[-1] == '5':
            continue
        if not (min_price <= day_open <= max_price):
            continue
        if metrics['daily_amount'] < min_amount:
            continue
        prev_close = prev_close_map.get(stock_code)
        if prev_close and prev_close > 0:
            if abs(day_open / prev_close - 1) * 100 > max_gap_pct:
                continue
        passed.add(stock_code)
    return passed


def build_configs():
    """트레일링 조합 생성"""
    configs = []

    # 기준선들
    configs.append(('기준_SL5_TP6_없음', -5.0, 6.0, None, None))
    configs.append(('이전_SL4_TP5_없음', -4.0, 5.0, None, None))

    # 트레일링 조합: 손절5%/익절6% 고정
    for act in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
        for trail in [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]:
            if act <= trail:
                continue
            configs.append((f'SL5_TP6_act{act}_tr{trail}', -5.0, 6.0, act, trail))

    # 익절 높이거나 제거 + 트레일링
    for tp, tp_label in [(8.0, 'TP8'), (10.0, 'TP10'), (999.0, 'TPoff')]:
        for act in [2.0, 2.5, 3.0, 3.5, 4.0]:
            for trail in [0.8, 1.0, 1.5, 2.0]:
                if act <= trail:
                    continue
                configs.append((f'SL5_{tp_label}_act{act}_tr{trail}', -5.0, tp, act, trail))

    return configs


def simulate_all_configs_single_pass(df, entry_idx, configs):
    """
    캔들을 한 번만 스캔하면서 모든 config의 결과를 동시에 기록.
    각 config별 상태를 유지하며 순회.
    """
    if entry_idx + 1 >= len(df) - 5:
        return {}

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']
    if entry_price <= 0:
        return {}

    n_configs = len(configs)

    # 각 config별 상태
    done = [False] * n_configs
    results = {}
    max_profit = [0.0] * n_configs
    trail_active = [False] * n_configs

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl = (row['low'] / entry_price - 1) * 100
        close_pnl = (row['close'] / entry_price - 1) * 100
        offset = i - entry_idx

        all_done = True

        for c in range(n_configs):
            if done[c]:
                continue
            all_done = False

            name, sl, tp, act, tr = configs[c]

            # 최고점 갱신
            if high_pnl > max_profit[c]:
                max_profit[c] = high_pnl

            # 익절
            if high_pnl >= tp:
                results[name] = {
                    'pnl': tp, 'exit_reason': '익절', 'result': 'WIN',
                    'holding': offset, 'max_profit': round(max_profit[c], 3),
                }
                done[c] = True
                continue

            # 트레일링
            if act is not None and tr is not None:
                if max_profit[c] >= act:
                    trail_active[c] = True
                if trail_active[c]:
                    trail_level = max_profit[c] - tr
                    if low_pnl <= trail_level:
                        exit_pnl = round(trail_level, 3)
                        results[name] = {
                            'pnl': exit_pnl,
                            'exit_reason': '트레일링',
                            'result': 'WIN' if exit_pnl > 0 else 'LOSS',
                            'holding': offset,
                            'max_profit': round(max_profit[c], 3),
                        }
                        done[c] = True
                        continue

            # 손절
            if low_pnl <= sl:
                results[name] = {
                    'pnl': sl, 'exit_reason': '손절', 'result': 'LOSS',
                    'holding': offset, 'max_profit': round(max_profit[c], 3),
                }
                done[c] = True
                continue

        if all_done:
            break

    # 미완료 -> 장마감
    last = df.iloc[-1]
    last_pnl = round((last['close'] / entry_price - 1) * 100, 3)
    for c in range(n_configs):
        if not done[c]:
            name = configs[c][0]
            results[name] = {
                'pnl': last_pnl,
                'exit_reason': '장마감',
                'result': 'WIN' if last_pnl > 0 else 'LOSS',
                'holding': len(df) - 1 - entry_idx,
                'max_profit': round(max_profit[c], 3),
            }

    return results


def run_simulation(start_date, end_date, max_daily=5, verbose=True):
    """메인 시뮬레이션"""
    strategy = PricePositionStrategy(config={
        'max_pre_volatility': 1.2,
        'max_pre20_momentum': 2.0,
        'entry_start_hour': 9,
        'entry_end_hour': 12,
    })

    configs = build_configs()
    print(f'트레일링 조합: {len(configs)}개')

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'거래일: {len(trading_dates)}일 ({start_date} ~ {end_date})')
    print(f'설정: 변동성 <= 1.2%, 모멘텀 <= 2.0%')

    # config별 거래 결과 수집
    all_results = defaultdict(list)  # {config_name: [{date, pnl, ...}, ...]}
    entry_count = 0

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 진입 {entry_count}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        screened = apply_screener_filter(daily_metrics, prev_close_map)
        if not screened:
            continue

        day_entries = 0  # 동시보유 제한

        for stock_code in screened:
            if day_entries >= max_daily:
                break

            try:
                cur.execute('''
                    SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s
                    ORDER BY idx
                ''', [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue

                columns = ['idx', 'date', 'time', 'close', 'open', 'high',
                           'low', 'volume', 'amount', 'datetime']
                df = pd.DataFrame(rows, columns=columns)

                day_open = daily_metrics[stock_code]['day_open']
                if day_open <= 0:
                    continue

                traded = False
                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    can_enter, _ = strategy.check_entry_conditions(
                        stock_code=stock_code, current_price=current_price,
                        day_open=day_open, current_time=current_time,
                        trade_date=trade_date, weekday=weekday,
                    )
                    if not can_enter:
                        continue

                    adv_ok, _ = strategy.check_advanced_conditions(df=df, candle_idx=candle_idx)
                    if not adv_ok:
                        continue

                    # 한 번의 캔들 스캔으로 모든 config 결과
                    res_map = simulate_all_configs_single_pass(df, candle_idx, configs)

                    for cfg_name, res in res_map.items():
                        res['date'] = trade_date
                        res['weekday'] = weekday
                        res['stock_code'] = stock_code
                        all_results[cfg_name].append(res)

                    strategy.record_trade(stock_code, trade_date)
                    traded = True
                    day_entries += 1
                    entry_count += 1

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n총 진입: {entry_count}건')
    return all_results, configs


def calc_capital_returns(trades, initial_capital=10_000_000, buy_ratio=0.20):
    if not trades:
        return {'final_capital': initial_capital, 'total_return_pct': 0.0, 'monthly': {}}

    capital = initial_capital
    current_month = None
    month_start = capital
    monthly = {}

    for date in sorted(set(t['date'] for t in trades)):
        month = date[:6]
        if month != current_month:
            if current_month:
                monthly[current_month] = (capital / month_start - 1) * 100
            current_month = month
            month_start = capital

        day_trades = [t for t in trades if t['date'] == date]
        day_start = capital
        for t in day_trades:
            invest = day_start * buy_ratio
            capital += invest * (t['pnl'] / 100)

    if current_month:
        monthly[current_month] = (capital / month_start - 1) * 100

    return {
        'final_capital': capital,
        'total_return_pct': (capital / initial_capital - 1) * 100,
        'monthly': monthly,
    }


def print_results(all_results, configs):
    # 각 config별 통계
    stats = []
    for name, sl, tp, act, tr in configs:
        trades = all_results.get(name, [])
        if not trades:
            continue

        n = len(trades)
        n_wins = sum(1 for t in trades if t['result'] == 'WIN')
        n_tp = sum(1 for t in trades if t['exit_reason'] == '익절')
        n_sl = sum(1 for t in trades if t['exit_reason'] == '손절')
        n_trail = sum(1 for t in trades if t['exit_reason'] == '트레일링')
        n_mc = sum(1 for t in trades if t['exit_reason'] == '장마감')
        avg_pnl = np.mean([t['pnl'] for t in trades])

        trail_avg = np.mean([t['pnl'] for t in trades if t['exit_reason'] == '트레일링']) if n_trail > 0 else 0

        cap = calc_capital_returns(trades)

        # 읽기 좋은 라벨
        if act is not None:
            tp_str = '익절없음' if tp > 100 else f'익절{tp:.0f}%'
            label = f'손절{abs(sl):.0f}%/{tp_str}, 활성+{act:.1f}%/되돌림{tr:.1f}%p'
        elif '이전' in name:
            label = '손절4%/익절5% (이전 설정)'
        else:
            label = '손절5%/익절6% (트레일링 없음)'

        stats.append({
            'name': name, 'label': label,
            'sl': sl, 'tp': tp, 'act': act, 'tr': tr,
            'trades': n, 'wins': n_wins, 'winrate': round(n_wins / n * 100, 1),
            'tp_cnt': n_tp, 'sl_cnt': n_sl, 'trail_cnt': n_trail, 'mc_cnt': n_mc,
            'trail_avg': round(trail_avg, 3),
            'avg_pnl': round(avg_pnl, 3),
            'capital_return': round(cap['total_return_pct'], 2),
            'final_capital': round(cap['final_capital']),
            'monthly': cap['monthly'],
        })

    # 기준선
    baseline = next((s for s in stats if '기준' in s['name']), None)
    prev = next((s for s in stats if '이전' in s['name']), None)
    baseline_return = baseline['capital_return'] if baseline else 0

    print('\n' + '=' * 130)
    print('트레일링 스탑 멀티버스 시뮬레이션 결과')
    print('  기본: 변동성 <= 1.2%, 손절 -5%, 익절 +6%')
    print('=' * 130)

    if prev:
        print(f'\n  [이전 설정] {prev["label"]}')
        print(f'    거래 {prev["trades"]}건, 승률 {prev["winrate"]}%, '
              f'익절 {prev["tp_cnt"]}건, 손절 {prev["sl_cnt"]}건')
        print(f'    평균PnL {prev["avg_pnl"]:+.3f}%, '
              f'원금수익률 {prev["capital_return"]:+.2f}%')

    if baseline:
        print(f'\n  [신규 기준] {baseline["label"]}')
        print(f'    거래 {baseline["trades"]}건, 승률 {baseline["winrate"]}%, '
              f'익절 {baseline["tp_cnt"]}건, 손절 {baseline["sl_cnt"]}건, 장마감 {baseline["mc_cnt"]}건')
        print(f'    평균PnL {baseline["avg_pnl"]:+.3f}%, '
              f'원금수익률 {baseline["capital_return"]:+.2f}% '
              f'(1000만 -> {baseline["final_capital"]/10000:,.0f}만원)')

    # TOP 30
    sorted_stats = sorted(stats, key=lambda x: x['capital_return'], reverse=True)

    print('\n' + '=' * 130)
    print('원금수익률 TOP 30')
    print('=' * 130)
    print(f'{"순위":>3} {"설정":<50} {"거래":>4} {"승률":>5} '
          f'{"익절":>4} {"손절":>4} {"트레일":>5} {"장마감":>4} '
          f'{"트레일PnL":>9} {"PnL":>7} {"원금수익률":>10} {"vs기준":>8}')
    print('-' * 130)

    for rank, s in enumerate(sorted_stats[:30], 1):
        delta = s['capital_return'] - baseline_return
        print(f'{rank:>3} {s["label"]:<50} {s["trades"]:>4} {s["winrate"]:>4.1f}% '
              f'{s["tp_cnt"]:>4} {s["sl_cnt"]:>4} {s["trail_cnt"]:>5} {s["mc_cnt"]:>4} '
              f'{s["trail_avg"]:>+8.3f}% {s["avg_pnl"]:>+6.3f}% '
              f'{s["capital_return"]:>+9.2f}% {delta:>+7.2f}%p')

    # 활성화별 최적
    print('\n' + '=' * 130)
    print('활성화 기준별 최적 (손절5%/익절6% 고정)')
    print('=' * 130)

    trail_stats = [s for s in stats if s['act'] is not None and s['tp'] == 6.0]
    for act in sorted(set(s['act'] for s in trail_stats)):
        group = [s for s in trail_stats if s['act'] == act]
        group.sort(key=lambda x: x['capital_return'], reverse=True)
        b = group[0]
        delta = b['capital_return'] - baseline_return
        print(f'  활성 +{act:.1f}%: 최적 되돌림 {b["tr"]:.1f}%p  '
              f'트레일 {b["trail_cnt"]:>4}건(PnL {b["trail_avg"]:>+5.2f}%)  '
              f'전체PnL {b["avg_pnl"]:>+6.3f}%  '
              f'원금 {b["capital_return"]:>+9.2f}% ({delta:>+7.2f}%p)')

    # TOP 1 월별
    best = sorted_stats[0]
    print('\n' + '=' * 130)
    print(f'TOP 1: {best["label"]}')
    print('=' * 130)
    print(f'  거래: {best["trades"]}건, 승률: {best["winrate"]}%')
    print(f'  익절: {best["tp_cnt"]}건, 손절: {best["sl_cnt"]}건, '
          f'트레일링: {best["trail_cnt"]}건, 장마감: {best["mc_cnt"]}건')
    print(f'  트레일링 평균PnL: {best["trail_avg"]:+.3f}%')
    print(f'  전체 평균PnL: {best["avg_pnl"]:+.3f}%')
    print(f'  원금수익률: {best["capital_return"]:+.2f}% '
          f'(1000만 -> {best["final_capital"]/10000:,.0f}만원)')

    if best.get('monthly') and baseline and baseline.get('monthly'):
        print(f'\n  {"월":>8} {"기준":>8} {"TOP1":>8} {"차이":>8}')
        for month in sorted(best['monthly'].keys()):
            base_m = baseline['monthly'].get(month, 0)
            best_m = best['monthly'].get(month, 0)
            diff = best_m - base_m
            print(f'  {month:>8} {base_m:>+7.2f}% {best_m:>+7.2f}% {diff:>+7.2f}%p')


def main():
    parser = argparse.ArgumentParser(description='트레일링 스탑 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260223', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    all_results, configs = run_simulation(
        args.start, args.end, max_daily=args.max_daily,
        verbose=not args.quiet,
    )
    print_results(all_results, configs)


if __name__ == '__main__':
    main()
