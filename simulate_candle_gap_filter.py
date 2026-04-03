"""
전일캔들+갭업 필터 멀티버스 시뮬레이션

핵심 발견: 전일 양봉 + 갭업 +1% 이상 = 승률 49~51% (동전 던지기)
이 조합을 차단하면 수익률이 개선되는지 13개월 시뮬로 검증.

멀티버스 변수:
1. 전일 양봉 시 갭업 상한 (1%, 1.5%, 2%, 3%, 없음)
2. 시가대비 진입 상한 (2.5%, 2.0%, 3.0%=기준선)
3. 갭업 단독 상한 (1%, 2%, 3%=기준선)
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy

from simulate_with_screener import (
    get_trading_dates, get_prev_close_map, get_daily_metrics,
    apply_screener_filter, get_preload_stocks, check_circuit_breaker,
    apply_daily_limit, calc_fixed_capital_returns,
)


def run_multiverse(
    start_date='20250224', end_date='20260223',
    cost_pct=0.33, max_daily=7, preload_top_n=30, circuit_breaker_pct=-3.0,
):
    # 멀티버스 파라미터
    # (전일양봉시 갭상한, 시가대비 상한, 갭 단독 상한)
    configs = [
        {'name': '기준선', 'prev_bull_gap_max': None, 'max_pct': 3.0, 'gap_max': None},
    ]

    # 1. 전일양봉+갭업 필터 단독
    for g in [0.5, 1.0, 1.5, 2.0]:
        configs.append({
            'name': f'전일양봉+갭>{g}%제외',
            'prev_bull_gap_max': g, 'max_pct': 3.0, 'gap_max': None,
        })

    # 2. 시가대비 상한 단독
    for p in [2.0, 2.5]:
        configs.append({
            'name': f'시가대비<{p}%',
            'prev_bull_gap_max': None, 'max_pct': p, 'gap_max': None,
        })

    # 3. 갭업 단독 상한
    for g in [1.0, 1.5, 2.0]:
        configs.append({
            'name': f'갭<{g}%',
            'prev_bull_gap_max': None, 'max_pct': 3.0, 'gap_max': g,
        })

    # 4. 복합: 전일양봉+갭 + 시가대비 상한
    for g in [1.0, 1.5]:
        for p in [2.5, 3.0]:
            configs.append({
                'name': f'전일양봉갭>{g}%+시가<{p}%',
                'prev_bull_gap_max': g, 'max_pct': p, 'gap_max': None,
            })

    # 5. 복합: 전일양봉+갭 + 갭 단독
    for pg in [1.0, 1.5]:
        for g in [2.0, 3.0]:
            configs.append({
                'name': f'전일양봉갭>{pg}%+갭<{g}%',
                'prev_bull_gap_max': pg, 'max_pct': 3.0, 'gap_max': g,
            })

    print('=' * 110)
    print('전일캔들+갭업 필터 멀티버스 시뮬레이션')
    print('=' * 110)
    print(f'기간: {start_date} ~ {end_date}')
    print(f'동시보유: {max_daily}종목, 비용: {cost_pct:.2f}%/건')
    print(f'멀티버스: {len(configs)}개 조합')
    print('=' * 110)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    strategy = PricePositionStrategy()
    all_trades_by_cfg = {i: [] for i in range(len(configs))}
    total_entries = 0
    filter_stats = defaultdict(int)

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 진입={total_entries}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        if circuit_breaker_pct and day_idx > 1:
            prev_prev_date = trading_dates[day_idx - 2]
            is_cb, _ = check_circuit_breaker(cur, prev_date, prev_prev_date, circuit_breaker_pct)
            if is_cb:
                continue

        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        # 전일 캔들 정보 (시가/종가로 양봉/음봉 판단)
        prev_candle = {}
        if prev_date:
            cur.execute('''
                SELECT stock_code, stck_oprc, stck_clpr
                FROM daily_candles
                WHERE stck_bsop_date = %s
            ''', [prev_date])
            for row in cur.fetchall():
                code, prev_open, prev_close = row[0], float(row[1] or 0), float(row[2] or 0)
                if prev_open > 0:
                    prev_candle[code] = {
                        'is_bull': prev_close >= prev_open,
                        'change_pct': (prev_close / prev_open - 1) * 100,
                    }

        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=60, min_price=5000, max_price=500000,
            min_amount=1_000_000_000, max_gap_pct=3.0,
            min_change_rate=0.5, max_change_rate=5.0,
            max_candidates=15,
        )

        if preload_top_n > 0 and prev_date:
            preload_set = get_preload_stocks(cur, prev_date, preload_top_n, 5000, 500000)
            preload_valid = preload_set & set(daily_metrics.keys())
            screened = list(set(screened) | (preload_valid - set(screened)))

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

                # 갭업 계산
                prev_c = prev_close_map.get(stock_code, 0)
                gap_pct = ((day_open / prev_c) - 1) * 100 if prev_c > 0 else 0

                # 전일 캔들
                pc = prev_candle.get(stock_code, {})
                is_prev_bull = pc.get('is_bull', False)

                # 진입 포인트 찾기
                entry_candle_idx = None
                for candle_idx in range(10, len(df) - 10):
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
                    entry_candle_idx = candle_idx
                    break

                if entry_candle_idx is None:
                    continue

                total_entries += 1
                pct_from_open = (df.iloc[entry_candle_idx]['close'] / day_open - 1) * 100
                base_result = strategy.simulate_trade(df, entry_candle_idx)

                for cfg_idx, cfg in enumerate(configs):
                    # 필터 1: 전일 양봉 + 갭업 상한
                    if cfg['prev_bull_gap_max'] is not None:
                        if is_prev_bull and gap_pct > cfg['prev_bull_gap_max']:
                            continue

                    # 필터 2: 시가대비 상한
                    if pct_from_open > cfg['max_pct']:
                        continue

                    # 필터 3: 갭업 단독 상한
                    if cfg['gap_max'] is not None:
                        if gap_pct > cfg['gap_max']:
                            continue

                    if base_result:
                        all_trades_by_cfg[cfg_idx].append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            'gap_pct': gap_pct,
                            'is_prev_bull': is_prev_bull,
                            **base_result,
                        })

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n총 진입 포인트: {total_entries}건')

    # 결과 집계
    results = []
    for cfg_idx, cfg in enumerate(configs):
        trades = all_trades_by_cfg[cfg_idx]
        if not trades:
            continue
        trades_df = pd.DataFrame(trades)
        if max_daily > 0:
            trades_df = apply_daily_limit(trades_df, max_daily)
        if len(trades_df) == 0:
            continue

        total = len(trades_df)
        wins = (trades_df['result'] == 'WIN').sum()
        win_rate = wins / total * 100
        avg_pnl = trades_df['pnl'].mean() - cost_pct
        fixed_ret = calc_fixed_capital_returns(trades_df, cost_pct=cost_pct)
        total_return = fixed_ret['total_return_pct']

        stop_trades = trades_df[trades_df['exit_reason'].str.contains('손절')]
        stop_count = len(stop_trades)
        stop_avg = stop_trades['pnl'].mean() if stop_count > 0 else 0

        results.append({
            'name': cfg['name'], 'total': total, 'wins': wins,
            'win_rate': win_rate, 'avg_pnl': avg_pnl,
            'total_return': total_return,
            'stop_count': stop_count, 'stop_avg_pnl': stop_avg,
        })

    # 결과 출력
    print('\n')
    print('=' * 130)
    print('멀티버스 결과 (고정자본 수익률 순)')
    print('=' * 130)
    print(f'{"순위":>3} {"설정":<35} {"거래":>5} {"승률":>7} {"평균PnL":>8} '
          f'{"고정자본":>10} {"손절건":>6} {"손절평균":>8} {"기준대비":>10}')
    print('-' * 130)

    results.sort(key=lambda x: x['total_return'], reverse=True)
    baseline_return = next((r['total_return'] for r in results if r['name'] == '기준선'), 0)

    for rank, r in enumerate(results, 1):
        diff = r['total_return'] - baseline_return
        diff_str = f"{diff:+.1f}%p" if r['name'] != '기준선' else '-'
        marker = ' *' if rank <= 3 and r['name'] != '기준선' else ''
        bl = ' <<' if r['name'] == '기준선' else ''
        print(f"{rank:>3} {r['name']:<35} {r['total']:>5} {r['win_rate']:>6.1f}% "
              f"{r['avg_pnl']:>+7.2f}% {r['total_return']:>+9.1f}% "
              f"{r['stop_count']:>6} {r['stop_avg_pnl']:>+7.2f}% "
              f"{diff_str:>10}{marker}{bl}")

    # 카테고리별 요약
    print('\n' + '=' * 80)
    print('카테고리별 효과')
    print('=' * 80)

    print('\n[전일양봉+갭업 필터 (단독)]')
    for r in results:
        if r['name'].startswith('전일양봉+갭>') and '시가' not in r['name'] and '갭<' not in r['name']:
            diff = r['total_return'] - baseline_return
            print(f"  {r['name']:<30} {r['total']}건 승률{r['win_rate']:.1f}% 수익률{r['total_return']:+.1f}% ({diff:+.1f}%p)")
    for r in results:
        if r['name'] == '기준선':
            print(f"  {'기준선':<30} {r['total']}건 승률{r['win_rate']:.1f}% 수익률{r['total_return']:+.1f}%")

    print('\n[시가대비 상한 (단독)]')
    for r in results:
        if r['name'].startswith('시가대비') or r['name'] == '기준선':
            diff = r['total_return'] - baseline_return
            ds = f"({diff:+.1f}%p)" if r['name'] != '기준선' else ''
            print(f"  {r['name']:<30} {r['total']}건 승률{r['win_rate']:.1f}% 수익률{r['total_return']:+.1f}% {ds}")

    print('\n[갭 단독 상한]')
    for r in results:
        if r['name'].startswith('갭<') or r['name'] == '기준선':
            diff = r['total_return'] - baseline_return
            ds = f"({diff:+.1f}%p)" if r['name'] != '기준선' else ''
            print(f"  {r['name']:<30} {r['total']}건 승률{r['win_rate']:.1f}% 수익률{r['total_return']:+.1f}% {ds}")

    # 상위 5개
    print('\n' + '=' * 80)
    print('상위 5개 상세')
    print('=' * 80)
    for rank, r in enumerate(results[:5], 1):
        diff = r['total_return'] - baseline_return
        print(f"\n#{rank} {r['name']}")
        print(f"  거래 {r['total']}건, 승률 {r['win_rate']:.1f}%, 평균 {r['avg_pnl']:+.2f}%")
        print(f"  고정자본 수익률: {r['total_return']:+.1f}% (기준 대비 {diff:+.1f}%p)")
        print(f"  손절 {r['stop_count']}건 (평균 {r['stop_avg_pnl']:+.2f}%)")

    print('\nDone!')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='전일캔들+갭업 필터 멀티버스')
    parser.add_argument('--start', default='20250224')
    parser.add_argument('--end', default='20260223')
    parser.add_argument('--cost', type=float, default=0.33)
    parser.add_argument('--max-daily', type=int, default=7)
    args = parser.parse_args()
    run_multiverse(start_date=args.start, end_date=args.end, cost_pct=args.cost, max_daily=args.max_daily)
