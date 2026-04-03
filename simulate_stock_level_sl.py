"""
종목 레벨 급락 감지 동적 SL 시뮬레이션

아이디어: 지수 하락을 기다리지 않고, 개별 종목의 단기 급락을 감지하여 SL을 축소.
- 보유 중 직전 N분간 X% 이상 하락 -> SL을 tightened_sl로 즉시 축소
- 멀티버스: 감지 기간(3/5/7분) x 급락 임계값(-1.0/-1.5/-2.0%) x 축소 SL(2/3/4%)

최적화: 진입 포인트당 분봉 데이터 1회 조회, 28개 config 동시 시뮬.
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
from typing import Optional
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy

from simulate_with_screener import (
    get_trading_dates,
    get_prev_close_map,
    get_daily_metrics,
    apply_screener_filter,
    get_preload_stocks,
    check_circuit_breaker,
    apply_daily_limit,
    print_stats,
    calc_fixed_capital_returns,
)


def simulate_trade_with_stock_level_sl(
    df: pd.DataFrame,
    entry_idx: int,
    strategy,
    lookback_minutes: int = 5,
    drop_threshold_pct: float = -1.5,
    tightened_sl_pct: float = -3.0,
    max_holding_minutes: int = 0,
) -> Optional[dict]:
    """
    종목 레벨 급락 감지가 적용된 simulate_trade.
    """
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']

    if entry_price <= 0:
        return None

    normal_sl = strategy.config['stop_loss_pct']
    normal_tp = strategy.config['take_profit_pct']

    max_profit_pct = 0.0
    min_profit_pct = 0.0
    sl_tightened = False

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        holding_candles = i - entry_idx

        if max_holding_minutes > 0 and holding_candles > max_holding_minutes:
            time_pnl = (row['close'] / entry_price - 1) * 100
            return {
                'result': 'WIN' if time_pnl > 0 else 'LOSS',
                'pnl': time_pnl,
                'exit_reason': '시간청산',
                'entry_time': entry_time, 'exit_time': row['time'],
                'entry_price': entry_price, 'holding_candles': holding_candles,
                'max_profit_pct': round(max_profit_pct, 2),
                'min_profit_pct': round(min_profit_pct, 2),
                'sl_tightened': sl_tightened,
            }

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl = (row['low'] / entry_price - 1) * 100
        if high_pnl > max_profit_pct:
            max_profit_pct = high_pnl
        if low_pnl < min_profit_pct:
            min_profit_pct = low_pnl

        # 종목 레벨 급락 감지
        current_sl = normal_sl
        if not sl_tightened and i >= lookback_minutes:
            past_close = df.iloc[i - lookback_minutes]['close']
            if past_close > 0:
                recent_change = (row['close'] / past_close - 1) * 100
                if recent_change <= drop_threshold_pct:
                    sl_tightened = True

        if sl_tightened:
            current_sl = tightened_sl_pct

        # 익절
        if high_pnl >= normal_tp:
            return {
                'result': 'WIN', 'pnl': normal_tp,
                'exit_reason': '익절',
                'entry_time': entry_time, 'exit_time': row['time'],
                'entry_price': entry_price, 'holding_candles': holding_candles,
                'max_profit_pct': round(max_profit_pct, 2),
                'min_profit_pct': round(min_profit_pct, 2),
                'sl_tightened': sl_tightened,
            }

        # 손절 (동적 SL 적용)
        if low_pnl <= current_sl:
            return {
                'result': 'LOSS', 'pnl': current_sl,
                'exit_reason': '손절(급락SL)' if sl_tightened else '손절',
                'entry_time': entry_time, 'exit_time': row['time'],
                'entry_price': entry_price, 'holding_candles': holding_candles,
                'max_profit_pct': round(max_profit_pct, 2),
                'min_profit_pct': round(min_profit_pct, 2),
                'sl_tightened': sl_tightened,
            }

    last_row = df.iloc[-1]
    last_pnl = (last_row['close'] / entry_price - 1) * 100
    return {
        'result': 'WIN' if last_pnl > 0 else 'LOSS',
        'pnl': last_pnl,
        'exit_reason': '장마감',
        'entry_time': entry_time, 'exit_time': last_row['time'],
        'entry_price': entry_price,
        'holding_candles': len(df) - 1 - entry_idx,
        'max_profit_pct': round(max_profit_pct, 2),
        'min_profit_pct': round(min_profit_pct, 2),
        'sl_tightened': sl_tightened,
    }


def run_multiverse(
    start_date='20250224',
    end_date='20260223',
    cost_pct=0.33,
    max_daily=7,
    preload_top_n=30,
    circuit_breaker_pct=-3.0,
):
    """종목 레벨 급락 감지 멀티버스 시뮬레이션"""

    lookback_options = [3, 5, 7]
    drop_threshold_options = [-1.0, -1.5, -2.0]
    tightened_sl_options = [-2.0, -3.0, -4.0]

    configs = [
        {'name': '기준선(SL5%)', 'lookback': 0, 'drop_threshold': 0, 'tightened_sl': -5.0},
    ]
    for lb in lookback_options:
        for dt in drop_threshold_options:
            for ts in tightened_sl_options:
                configs.append({
                    'name': f'{lb}분/{dt}%->SL{ts}%',
                    'lookback': lb, 'drop_threshold': dt, 'tightened_sl': ts,
                })

    print('=' * 100)
    print('종목 레벨 급락 감지 동적 SL - 멀티버스 시뮬레이션')
    print('=' * 100)
    print(f'기간: {start_date} ~ {end_date}')
    print(f'동시보유: {max_daily}종목, 비용: {cost_pct:.2f}%/건')
    print(f'멀티버스: {len(configs)}개 조합')
    print(f'  감지기간: {lookback_options}분')
    print(f'  급락임계: {drop_threshold_options}%')
    print(f'  축소SL:   {tightened_sl_options}%')
    print('=' * 100)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    strategy = PricePositionStrategy()

    # config별 거래 리스트
    all_trades_by_cfg = {i: [] for i in range(len(configs))}

    # 날짜별로 진입 포인트 수집 + 모든 config 동시 시뮬
    total_entries = 0

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
            is_cb, _ = check_circuit_breaker(
                cur, prev_date, prev_prev_date, circuit_breaker_pct
            )
            if is_cb:
                continue

        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

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

                # 진입 포인트 찾기
                entry_candle_idx = None
                for candle_idx in range(10, len(df) - 10):
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

                    adv_ok, _ = strategy.check_advanced_conditions(
                        df=df, candle_idx=candle_idx
                    )
                    if not adv_ok:
                        continue

                    entry_candle_idx = candle_idx
                    break

                if entry_candle_idx is None:
                    continue

                total_entries += 1
                pct_from_open = (df.iloc[entry_candle_idx]['close'] / day_open - 1) * 100

                # 모든 config에 대해 시뮬 실행 (df를 메모리에 1번만 로드)
                for cfg_idx, cfg in enumerate(configs):
                    is_baseline = cfg['lookback'] == 0

                    if is_baseline:
                        result = strategy.simulate_trade(df, entry_candle_idx)
                    else:
                        result = simulate_trade_with_stock_level_sl(
                            df=df,
                            entry_idx=entry_candle_idx,
                            strategy=strategy,
                            lookback_minutes=cfg['lookback'],
                            drop_threshold_pct=cfg['drop_threshold'],
                            tightened_sl_pct=cfg['tightened_sl'],
                        )

                    if result:
                        all_trades_by_cfg[cfg_idx].append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            **result,
                        })

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n진입 포인트: {total_entries}건')

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

        sl_tightened_count = 0
        if 'sl_tightened' in trades_df.columns:
            sl_tightened_count = int(trades_df['sl_tightened'].sum())

        stop_trades = trades_df[trades_df['exit_reason'].str.contains('손절')]
        stop_count = len(stop_trades)
        stop_avg = stop_trades['pnl'].mean() if stop_count > 0 else 0

        results.append({
            'name': cfg['name'],
            'lookback': cfg['lookback'],
            'drop_threshold': cfg['drop_threshold'],
            'tightened_sl': cfg['tightened_sl'],
            'total': total, 'wins': wins, 'win_rate': win_rate,
            'avg_pnl': avg_pnl, 'total_return': total_return,
            'sl_tightened_count': sl_tightened_count,
            'stop_count': stop_count, 'stop_avg_pnl': stop_avg,
        })

    # 결과 출력
    print('\n')
    print('=' * 130)
    print('멀티버스 결과 (고정자본 수익률 순)')
    print('=' * 130)
    print(f'{"순위":>3} {"설정":<22} {"거래":>5} {"승률":>7} {"평균PnL":>8} '
          f'{"고정자본":>10} {"급락SL발동":>10} {"손절건":>6} {"손절평균":>8} {"기준대비":>10}')
    print('-' * 130)

    results.sort(key=lambda x: x['total_return'], reverse=True)
    baseline_return = next((r['total_return'] for r in results if '기준선' in r['name']), 0)

    for rank, r in enumerate(results, 1):
        diff = r['total_return'] - baseline_return
        diff_str = f"{diff:+.1f}%p" if '기준선' not in r['name'] else '-'
        marker = ' *' if rank <= 3 and '기준선' not in r['name'] else ''
        print(f"{rank:>3} {r['name']:<22} {r['total']:>5} {r['win_rate']:>6.1f}% "
              f"{r['avg_pnl']:>+7.2f}% {r['total_return']:>+9.1f}% "
              f"{r['sl_tightened_count']:>10} {r['stop_count']:>6} "
              f"{r['stop_avg_pnl']:>+7.2f}% {diff_str:>10}{marker}")

    # 상위 5개 상세
    print('\n' + '=' * 80)
    print('상위 5개 상세')
    print('=' * 80)
    for rank, r in enumerate(results[:5], 1):
        diff = r['total_return'] - baseline_return
        print(f"\n#{rank} {r['name']}")
        print(f"  거래 {r['total']}건, 승률 {r['win_rate']:.1f}%, "
              f"평균 {r['avg_pnl']:+.2f}%")
        print(f"  고정자본 수익률: {r['total_return']:+.1f}% "
              f"(기준 대비 {diff:+.1f}%p)")
        print(f"  급락SL 발동: {r['sl_tightened_count']}건, "
              f"손절 {r['stop_count']}건 (평균 {r['stop_avg_pnl']:+.2f}%)")

    # 결론
    if results and '기준선' not in results[0]['name']:
        best = results[0]
        print(f"\n{'='*80}")
        print(f"결론: {best['name']}이 기준선 대비 "
              f"{best['total_return'] - baseline_return:+.1f}%p 개선")
        print(f"  급락SL 발동 {best['sl_tightened_count']}건으로 "
              f"손절 평균 {best['stop_avg_pnl']:+.2f}%")
    else:
        print(f"\n{'='*80}")
        print("결론: 기준선(SL5%)이 최고 - 종목 레벨 급락 감지는 효과 없음")

    print('\nDone!')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='종목 레벨 급락 감지 동적 SL 멀티버스')
    parser.add_argument('--start', default='20250224')
    parser.add_argument('--end', default='20260223')
    parser.add_argument('--cost', type=float, default=0.33)
    parser.add_argument('--max-daily', type=int, default=7)
    parser.add_argument('--preload-top', type=int, default=30)
    parser.add_argument('--circuit-breaker', type=float, default=-3.0)
    args = parser.parse_args()

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        cost_pct=args.cost,
        max_daily=args.max_daily,
        preload_top_n=args.preload_top,
        circuit_breaker_pct=args.circuit_breaker,
    )
