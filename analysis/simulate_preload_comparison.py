"""
프리로드 종목 포함 시뮬레이션 vs 기존 시뮬레이션 비교

시뮬에서 프리로드를 반영하지 않아 실거래와 종목 풀이 달랐던 문제를 검증.
기존 시뮬: 당일 09:30까지 거래대금 상위 60개에서 스크리너 필터
프리로드 추가: 전일 거래대금 상위 30개를 추가 후보로 포함
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from config.strategy_settings import StrategySettings
from simulate_with_screener import (
    get_trading_dates, get_daily_metrics, get_prev_close_map,
    apply_screener_filter, check_circuit_breaker, apply_daily_limit,
    calc_fixed_capital_returns,
)
from core.strategies.price_position_strategy import PricePositionStrategy


def get_preload_stocks(cur, prev_date, top_n=30):
    """전일 거래대금 상위 종목 (프리로드 시뮬)"""
    cur.execute('''
        SELECT stock_code, SUM(amount) as daily_amount,
               MAX(close) as last_close
        FROM minute_candles
        WHERE trade_date = %s
        GROUP BY stock_code
        HAVING MAX(close) BETWEEN 5000 AND 500000
        ORDER BY SUM(amount) DESC
        LIMIT %s
    ''', [prev_date, top_n])
    return set(r[0] for r in cur.fetchall() if not r[0].endswith('5'))


def run_comparison():
    pp = StrategySettings.PricePosition
    config = {
        'min_pct_from_open': pp.MIN_PCT_FROM_OPEN,
        'max_pct_from_open': pp.MAX_PCT_FROM_OPEN,
        'entry_start_hour': 9,
        'entry_end_hour': 12,
        'stop_loss_pct': -5.0,
        'take_profit_pct': 6.0,
    }
    strategy = PricePositionStrategy(config=config)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    start_date, end_date = '20250224', '20260401'
    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'거래일: {len(trading_dates)}일')

    results = {'기존 시뮬': [], '프리로드 추가': [], '프리로드만': []}

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date})')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        # 서킷브레이커
        if day_idx > 1:
            is_cb, _ = check_circuit_breaker(cur, prev_date, trading_dates[day_idx - 2], -3.0)
            if is_cb:
                continue

        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = get_prev_close_map(cur, trade_date, prev_date) if prev_date else {}

        # 기존 스크리너 후보
        screened_original = set(apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=60, min_amount=1e9, max_gap_pct=3.0,
            min_change_rate=0.5, max_change_rate=5.0,
            max_candidates=15,
        ))

        # 프리로드 후보
        preload_stocks = get_preload_stocks(cur, prev_date, 30) if prev_date else set()

        # 프리로드 중 daily_metrics에 있는 것만 (당일 데이터 필요)
        preload_valid = preload_stocks & set(daily_metrics.keys())

        # 합집합
        combined = screened_original | preload_valid
        preload_only = preload_valid - screened_original

        # 각 후보 셋에 대해 거래 시뮬
        for label, stock_set in [('기존 시뮬', screened_original),
                                   ('프리로드 추가', combined),
                                   ('프리로드만', preload_only)]:
            for stock_code in stock_set:
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
                            stock_code=stock_code,
                            current_price=current_price,
                            day_open=day_open,
                            current_time=current_time,
                            trade_date=trade_date,
                            weekday=weekday,
                        )
                        if not can_enter:
                            continue

                        adv_ok, _ = strategy.check_advanced_conditions(df=df, candle_idx=candle_idx)
                        if not adv_ok:
                            continue

                        result = strategy.simulate_trade(df, candle_idx)
                        if result:
                            entry_hour = int(current_time[:2]) if len(current_time) >= 2 else 9
                            results[label].append({
                                'date': trade_date,
                                'stock_code': stock_code,
                                'weekday': weekday,
                                'entry_time': result.get('entry_time', current_time),
                                'exit_time': result.get('exit_time', '150000'),
                                'entry_hour': entry_hour,
                                'pnl': result['pnl'],
                                'result': result['result'],
                                'exit_reason': result.get('exit_reason', ''),
                                'in_original': stock_code in screened_original,
                                'is_preload': stock_code in preload_only,
                            })
                            traded = True
                except Exception:
                    continue

    conn.close()

    # 결과 출력
    cost_pct = 0.33
    max_daily = 7

    print('\n' + '=' * 90)
    print('=== 프리로드 효과 비교 ===')
    print('=' * 90)

    print(f'\n{"시나리오":<20} {"거래":>6} {"승률":>7} {"순평균":>8} {"수익률(무제한)":>14} {"수익률(7종목)":>14}')
    print('-' * 75)

    for label in ['기존 시뮬', '프리로드 추가', '프리로드만']:
        trades = results[label]
        if not trades:
            print(f'{label:<20} {"없음":>6}')
            continue

        df_trades = pd.DataFrame(trades)
        net = df_trades['pnl'] - cost_pct
        wins = (net > 0).sum()
        total = len(df_trades)

        # 무제한
        cap_unlimited = calc_fixed_capital_returns(df_trades, cost_pct=cost_pct)

        # 7종목 제한
        limited = apply_daily_limit(df_trades, max_daily)
        cap_limited = calc_fixed_capital_returns(limited, cost_pct=cost_pct) if len(limited) > 0 else {'total_return_pct': 0}
        net_limited = limited['pnl'] - cost_pct if len(limited) > 0 else pd.Series([0])

        print(f'{label:<20} {total:>6} {wins/total*100:>6.1f}% {net.mean():>+7.2f}% '
              f'{cap_unlimited["total_return_pct"]:>+13.1f}% {cap_limited["total_return_pct"]:>+13.1f}%')

    # 프리로드 종목 시간대 분석
    print('\n\n=== 프리로드 종목의 시간대별 성과 ===')
    preload_trades = results.get('프리로드만', [])
    if preload_trades:
        df_pre = pd.DataFrame(preload_trades)
        print(f'\n{"시간대":<10} {"거래":>5} {"승률":>7} {"순평균":>8}')
        print('-' * 35)
        for hour in sorted(df_pre['entry_hour'].unique()):
            ht = df_pre[df_pre['entry_hour'] == hour]
            net = ht['pnl'] - cost_pct
            wins = (net > 0).sum()
            print(f'  {hour}시     {len(ht):>5} {wins/len(ht)*100:>6.1f}% {net.mean():>+7.2f}%')

    # 프리로드 추가의 시간대별 비교
    print('\n\n=== 기존 vs 프리로드추가: 시간대별 ===')
    for label in ['기존 시뮬', '프리로드 추가']:
        trades = results[label]
        if not trades:
            continue
        df_t = pd.DataFrame(trades)
        print(f'\n  [{label}]')
        for hour in sorted(df_t['entry_hour'].unique()):
            ht = df_t[df_t['entry_hour'] == hour]
            net = ht['pnl'] - cost_pct
            wins = (net > 0).sum()
            print(f'    {hour}시: {len(ht)}건, 승률 {wins/len(ht)*100:.1f}%, 순평균 {net.mean():+.2f}%')

    print('\n\nDone!')


if __name__ == '__main__':
    run_comparison()
