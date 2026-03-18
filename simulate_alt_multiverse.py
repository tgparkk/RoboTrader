"""
대안 전략 멀티버스 시뮬레이션 (최적화 버전)

프리로드 없이, 전략별로 날짜 루프를 한 번 돌면서 모든 파라미터 조합을 동시에 테스트.
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse
import itertools
import sys

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from simulate_with_screener import (
    get_trading_dates, get_prev_close_map, get_daily_metrics,
    apply_screener_filter, apply_daily_limit, calc_fixed_capital_returns,
)
from simulate_alternative_strategies import (
    simulate_existing_strategy, simulate_gapdown_reversion,
    simulate_volume_breakout, simulate_afternoon_pullback,
)


def run_multiverse_single_pass(start_date, end_date, strategy_name, strategy_func,
                                param_grid, max_daily=5, cost_pct=0.33,
                                screener_max_gap=5.0):
    """
    한 번의 날짜 루프로 모든 파라미터 조합을 동시 테스트.
    핵심: 분봉 데이터를 한 번만 읽고, 모든 config에 대해 전략 실행.
    """
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(itertools.product(*values))
    configs = [dict(zip(keys, c)) for c in combos]

    print(f'{"="*90}')
    print(f'{strategy_name} 멀티버스 ({len(configs)}개 조합)')
    print(f'{"="*90}')

    # 조합별 거래 저장소
    all_trades = {i: [] for i in range(len(configs))}
    traded_keys = {i: set() for i in range(len(configs))}

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    trading_dates = get_trading_dates(cur, start_date, end_date)

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 30 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date})')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=60, min_price=5000, max_price=500000,
            min_amount=1_000_000_000, max_gap_pct=screener_max_gap,
        )
        if not screened:
            continue

        for stock_code in screened:
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
                prev_close = prev_close_map.get(stock_code)

                # 모든 config에 대해 실행
                for ci, config in enumerate(configs):
                    key = (trade_date, stock_code)
                    if key in traded_keys[ci]:
                        continue

                    result = None
                    if strategy_func == 'existing':
                        result = simulate_existing_strategy(df, day_open, config)
                    elif strategy_func == 'gapdown':
                        result = simulate_gapdown_reversion(df, day_open, prev_close, config)
                    elif strategy_func == 'volume':
                        result = simulate_volume_breakout(df, day_open, config)
                    elif strategy_func == 'afternoon':
                        result = simulate_afternoon_pullback(df, day_open, config)

                    if result:
                        all_trades[ci].append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            **result,
                        })
                        traded_keys[ci].add(key)

            except Exception:
                continue

    cur.close()
    conn.close()

    # 결과 집계
    results = []
    for ci, config in enumerate(configs):
        trades = all_trades[ci]
        if not trades:
            continue

        df_t = pd.DataFrame(trades)
        limited = apply_daily_limit(df_t, max_daily) if max_daily > 0 else df_t
        if len(limited) == 0:
            continue

        total = len(limited)
        wins = (limited['result'] == 'WIN').sum()
        winrate = wins / total * 100
        avg_net = limited['pnl'].mean() - cost_pct
        stop_count = len(limited[limited['exit_reason'] == '손절'])
        tp_count = len(limited[limited['exit_reason'] == '익절'])
        cap = calc_fixed_capital_returns(limited, cost_pct=cost_pct)

        results.append({
            'config': config,
            'total': total, 'wins': wins, 'winrate': winrate,
            'avg_net': avg_net, 'stop_count': stop_count, 'tp_count': tp_count,
            'fixed_return': cap['total_return_pct'],
            'final_capital': cap['final_capital'],
        })

    results.sort(key=lambda x: x['fixed_return'], reverse=True)

    # 출력
    show_n = min(15, len(results))
    print(f'\nTOP {show_n} / {len(results)}개 조합')
    print(f'{"순위":>4} {"거래":>5} {"승률":>7} {"순평균":>8} {"손절":>4} {"익절":>4} '
          f'{"고정수익률":>10}  파라미터')
    print('-' * 105)

    for i, r in enumerate(results[:show_n]):
        params = ', '.join(f'{k}={v}' for k, v in r['config'].items()
                           if k not in ('max_volatility', 'max_momentum', 'start_hour', 'max_gap'))
        print(f'{i+1:>4} {r["total"]:>4}건 {r["winrate"]:>6.1f}% {r["avg_net"]:>+7.2f}% '
              f'{r["stop_count"]:>3}건 {r["tp_count"]:>3}건 '
              f'{r["fixed_return"]:>+9.2f}%  {params}')

    if len(results) > show_n:
        print(f'...')
        for r in results[-3:]:
            rank = results.index(r) + 1
            params = ', '.join(f'{k}={v}' for k, v in r['config'].items()
                               if k not in ('max_volatility', 'max_momentum', 'start_hour', 'max_gap'))
            print(f'{rank:>4} {r["total"]:>4}건 {r["winrate"]:>6.1f}% {r["avg_net"]:>+7.2f}% '
                  f'{r["stop_count"]:>3}건 {r["tp_count"]:>3}건 '
                  f'{r["fixed_return"]:>+9.2f}%  {params}')

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='20250224')
    parser.add_argument('--end', default=None)
    parser.add_argument('--cost', type=float, default=0.33)
    parser.add_argument('--max-daily', type=int, default=5)
    parser.add_argument('--strategy', default='all',
                        choices=['all', 'existing', 'gapdown', 'volume', 'afternoon'])
    args = parser.parse_args()

    strategies_to_run = {
        'existing': ('기존 전략 (시가 대비 상승)', 'existing', {
            'min_pct': [0.5, 1.0, 1.5, 2.0],
            'max_pct': [2.0, 3.0, 4.0, 5.0],
            'stop_loss': [-3.0, -4.0, -5.0],
            'take_profit': [4.0, 5.0, 6.0, 8.0],
            'start_hour': [9],
            'end_hour': [10, 12],
            'max_volatility': [1.2],
            'max_momentum': [2.0],
        }),
        'gapdown': ('갭다운 반등 전략', 'gapdown', {
            'min_gap': [-1.0, -1.5, -2.0, -3.0],
            'max_gap': [-10.0],
            'stop_loss': [-2.0, -3.0, -4.0, -5.0],
            'take_profit': [3.0, 4.0, 5.0, 6.0],
            'start_hour': [9],
            'end_hour': [10, 11, 12],
        }),
        'volume': ('거래량 급증 전략', 'volume', {
            'stop_loss': [-3.0, -4.0, -5.0],
            'take_profit': [4.0, 5.0, 6.0],
            'vol_multiplier': [2.0, 3.0, 4.0, 5.0],
            'start_hour': [9],
            'end_hour': [10, 11, 12],
        }),
        'afternoon': ('오후 풀백 전략', 'afternoon', {
            'stop_loss': [-2.0, -3.0, -4.0, -5.0],
            'take_profit': [2.0, 3.0, 4.0, 5.0, 6.0],
            'min_morning_high': [3.0, 4.0, 5.0],
            'pullback_min': [-4.0, -3.0, -2.0],
            'pullback_max': [-2.0, -1.0, -0.5],
        }),
    }

    if args.strategy == 'all':
        to_run = strategies_to_run
    else:
        to_run = {args.strategy: strategies_to_run[args.strategy]}

    all_best = {}
    for key, (name, func, grid) in to_run.items():
        total_combos = 1
        for v in grid.values():
            total_combos *= len(v)
        print(f'\n{name}: {total_combos}개 조합')

        results = run_multiverse_single_pass(
            args.start, args.end, name, func, grid,
            max_daily=args.max_daily, cost_pct=args.cost,
        )
        if results:
            all_best[name] = results[0]

    # 최종 비교
    if len(all_best) > 1:
        print(f'\n{"="*90}')
        print('전략별 최적 조합 비교')
        print(f'{"="*90}')
        print(f'{"전략":<20} {"거래":>5} {"승률":>7} {"순평균":>8} {"손절":>4} {"익절":>4} '
              f'{"고정수익률":>10}')
        print('-' * 70)
        for name, r in sorted(all_best.items(), key=lambda x: x[1]['fixed_return'], reverse=True):
            print(f'{name:<20} {r["total"]:>4}건 {r["winrate"]:>6.1f}% {r["avg_net"]:>+7.2f}% '
                  f'{r["stop_count"]:>3}건 {r["tp_count"]:>3}건 '
                  f'{r["fixed_return"]:>+9.2f}%')

    print('\nDone!')


if __name__ == '__main__':
    main()
