"""
멀티버스 시뮬레이션: 청산 전략 비교

다양한 청산 방법을 비교:
1. 현행: 손절-5%/익절+6%, 15시 장마감
2. 트레일링 스탑: 고점 대비 N% 하락 시 매도
3. 시간+수익 조건: 특정 시간에 수익 중이면 매도
4. 오후 트레일링: 12시 이후부터 트레일링 적용
5. 수익 확보형: +N% 도달 후 M% 되돌림 시 매도
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict, OrderedDict
import argparse
import sys

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy
from simulate_with_screener import (
    get_trading_dates, get_prev_close_map, get_daily_metrics,
    apply_screener_filter, apply_daily_limit, calc_capital_returns,
)


def simulate_with_exit_strategy(df, entry_idx, strategy_type, params, base_sl=-5.0, base_tp=6.0):
    """
    다양한 청산 전략으로 거래 시뮬레이션

    strategy_type:
        'baseline'       - 현행 (SL/TP + 15시 장마감)
        'trailing'       - 트레일링 스탑 (고점 대비 N% 하락)
        'time_profit'    - 시간+수익 조건 (특정 시간에 수익이면 매도)
        'pm_trailing'    - 오후 트레일링 (특정 시간 이후 트레일링 적용)
        'profit_lock'    - 수익 확보형 (+N% 도달 후 SL을 올림)
    """
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']

    if entry_price <= 0:
        return None

    max_profit_pct = 0.0
    max_price = entry_price

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        high = float(row['high'])
        low = float(row['low'])
        close = float(row['close'])
        row_time = str(row['time']).replace(':', '').ljust(6, '0')[:6]
        row_time_int = int(row_time)

        # 고점 추적
        if high > max_price:
            max_price = high
        high_pnl = (high / entry_price - 1) * 100
        if high_pnl > max_profit_pct:
            max_profit_pct = high_pnl

        # 기본 익절 체크
        if high_pnl >= base_tp:
            return _result('WIN', base_tp, '익절', entry_time, row['time'], entry_price, i - entry_idx, max_profit_pct)

        # 기본 손절 체크
        low_pnl = (low / entry_price - 1) * 100
        if low_pnl <= base_sl:
            return _result('LOSS', base_sl, '손절', entry_time, row['time'], entry_price, i - entry_idx, max_profit_pct)

        close_pnl = (close / entry_price - 1) * 100

        # === 전략별 청산 로직 ===

        if strategy_type == 'trailing':
            trail_pct = params['trail_pct']  # e.g., -2.0
            if max_price > entry_price:
                drop_from_peak = (close / max_price - 1) * 100
                if drop_from_peak <= trail_pct:
                    return _result('WIN' if close_pnl > 0 else 'LOSS', close_pnl, '트레일링',
                                   entry_time, row['time'], entry_price, i - entry_idx, max_profit_pct)

        elif strategy_type == 'time_profit':
            cutoff_time = params['cutoff_time']  # e.g., 130000
            min_profit = params.get('min_profit', 0.0)  # e.g., 0.0 (수익이면 매도)
            if row_time_int >= cutoff_time and close_pnl >= min_profit:
                return _result('WIN' if close_pnl > 0 else 'LOSS', close_pnl, '조건청산',
                               entry_time, row['time'], entry_price, i - entry_idx, max_profit_pct)

        elif strategy_type == 'pm_trailing':
            trail_start = params['trail_start']  # e.g., 120000
            trail_pct = params['trail_pct']
            if row_time_int >= trail_start and max_price > entry_price:
                drop_from_peak = (close / max_price - 1) * 100
                if drop_from_peak <= trail_pct:
                    return _result('WIN' if close_pnl > 0 else 'LOSS', close_pnl, '오후트레일링',
                                   entry_time, row['time'], entry_price, i - entry_idx, max_profit_pct)

        elif strategy_type == 'profit_lock':
            threshold = params['threshold']  # e.g., +3.0 (3% 도달하면)
            lock_sl = params['lock_sl']      # e.g., +1.0 (손절을 +1%로 올림)
            if max_profit_pct >= threshold and close_pnl <= lock_sl:
                return _result('WIN' if close_pnl > 0 else 'LOSS', close_pnl, '수익확보',
                               entry_time, row['time'], entry_price, i - entry_idx, max_profit_pct)

    # 장마감
    last_row = df.iloc[-1]
    last_pnl = (float(last_row['close']) / entry_price - 1) * 100
    return _result('WIN' if last_pnl > 0 else 'LOSS', last_pnl, '장마감',
                   entry_time, last_row['time'], entry_price, len(df) - 1 - entry_idx, max_profit_pct)


def _result(result, pnl, reason, entry_time, exit_time, entry_price, holding, max_profit):
    return {
        'result': result,
        'pnl': pnl,
        'exit_reason': reason,
        'entry_time': entry_time,
        'exit_time': exit_time,
        'entry_price': entry_price,
        'holding_candles': holding,
        'max_profit_pct': round(max_profit, 2),
    }


def run_multiverse(start_date='20250224', end_date=None, verbose=True):
    """멀티버스 시뮬레이션: 다양한 청산 전략"""

    # 테스트할 전략들
    strategies = [
        # 현행
        ('현행(-5/+6,15시)', 'baseline', {}),

        # 트레일링 스탑
        ('트레일-1.0%', 'trailing', {'trail_pct': -1.0}),
        ('트레일-1.5%', 'trailing', {'trail_pct': -1.5}),
        ('트레일-2.0%', 'trailing', {'trail_pct': -2.0}),
        ('트레일-2.5%', 'trailing', {'trail_pct': -2.5}),
        ('트레일-3.0%', 'trailing', {'trail_pct': -3.0}),

        # 시간+수익 조건: N시에 수익이면 매도, 아니면 15시까지
        ('12시수익매도', 'time_profit', {'cutoff_time': 120000, 'min_profit': 0.0}),
        ('13시수익매도', 'time_profit', {'cutoff_time': 130000, 'min_profit': 0.0}),
        ('13시+1%매도', 'time_profit', {'cutoff_time': 130000, 'min_profit': 1.0}),
        ('14시수익매도', 'time_profit', {'cutoff_time': 140000, 'min_profit': 0.0}),

        # 오후 트레일링 (12시부터 트레일링)
        ('12시~트레일-1%', 'pm_trailing', {'trail_start': 120000, 'trail_pct': -1.0}),
        ('12시~트레일-1.5%', 'pm_trailing', {'trail_start': 120000, 'trail_pct': -1.5}),
        ('12시~트레일-2%', 'pm_trailing', {'trail_start': 120000, 'trail_pct': -2.0}),
        ('13시~트레일-1%', 'pm_trailing', {'trail_start': 130000, 'trail_pct': -1.0}),
        ('13시~트레일-1.5%', 'pm_trailing', {'trail_start': 130000, 'trail_pct': -1.5}),
        ('13시~트레일-2%', 'pm_trailing', {'trail_start': 130000, 'trail_pct': -2.0}),

        # 수익 확보형: +N% 달성 후 M%로 떨어지면 매도
        ('+2%후→+0.5%확보', 'profit_lock', {'threshold': 2.0, 'lock_sl': 0.5}),
        ('+2%후→+1%확보', 'profit_lock', {'threshold': 2.0, 'lock_sl': 1.0}),
        ('+3%후→+1%확보', 'profit_lock', {'threshold': 3.0, 'lock_sl': 1.0}),
        ('+3%후→+1.5%확보', 'profit_lock', {'threshold': 3.0, 'lock_sl': 1.5}),
        ('+4%후→+2%확보', 'profit_lock', {'threshold': 4.0, 'lock_sl': 2.0}),
    ]

    strategy_obj = PricePositionStrategy()
    info = strategy_obj.get_strategy_info()

    print('=' * 90)
    print('멀티버스 시뮬레이션: 청산 전략 비교')
    print('=' * 90)
    print(f"진입: 시가 대비 {info['entry_conditions']['pct_from_open']}, "
          f"{info['entry_conditions']['time_range']}")
    print(f"기본: 손절 -5.0%, 익절 +6.0%")
    print(f"비교 전략: {len(strategies)}개")
    print(f"기간: {start_date} ~ {end_date or '전체'}")
    print('=' * 90)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    # 각 전략별 결과
    all_results = {s[0]: [] for s in strategies}

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 처리 중...')

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

                entry_found = False
                for candle_idx in range(10, len(df) - 10):
                    if entry_found:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    can_enter, _ = strategy_obj.check_entry_conditions(
                        stock_code=stock_code,
                        current_price=current_price,
                        day_open=day_open,
                        current_time=current_time,
                        trade_date=trade_date,
                        weekday=weekday,
                    )
                    if not can_enter:
                        continue

                    adv_ok, _ = strategy_obj.check_advanced_conditions(df=df, candle_idx=candle_idx)
                    if not adv_ok:
                        continue

                    pct_from_open = (current_price / day_open - 1) * 100

                    for label, stype, params in strategies:
                        result = simulate_with_exit_strategy(
                            df, candle_idx, stype, params,
                            base_sl=-5.0, base_tp=6.0,
                        )
                        if result:
                            all_results[label].append({
                                'date': trade_date,
                                'stock_code': stock_code,
                                'weekday': weekday,
                                'pct_from_open': pct_from_open,
                                **result,
                            })

                    strategy_obj.record_trade(stock_code, trade_date)
                    entry_found = True

            except Exception:
                continue

    cur.close()
    conn.close()

    # ====== 결과 출력 ======
    print('\n\n')
    print('#' * 90)
    print('#  멀티버스 결과: 청산 전략별 비교 (동시보유 5종목)')
    print('#' * 90)

    summary = []
    for label, stype, params in strategies:
        trades = all_results[label]
        if not trades:
            continue

        trades_df = pd.DataFrame(trades)
        limited_df = apply_daily_limit(trades_df, 5)

        if len(limited_df) == 0:
            continue

        total = len(limited_df)
        wins = (limited_df['result'] == 'WIN').sum()
        winrate = wins / total * 100
        avg_pnl = limited_df['pnl'].mean()
        cap = calc_capital_returns(limited_df)
        cap_ret = cap['total_return_pct']

        # 청산 사유별
        reasons = limited_df['exit_reason'].value_counts().to_dict()

        # 평균 최고 수익률 (얼마나 놓쳤는지)
        avg_max_profit = limited_df['max_profit_pct'].mean()
        # 놓친 수익 = 최고 수익 - 실현 수익
        avg_missed = avg_max_profit - avg_pnl

        summary.append({
            'label': label,
            'total': total,
            'wins': wins,
            'winrate': winrate,
            'avg_pnl': avg_pnl,
            'cap_ret': cap_ret,
            'reasons': reasons,
            'avg_max': avg_max_profit,
            'avg_missed': avg_missed,
        })

    # 정렬: 평균 수익률 내림차순
    summary.sort(key=lambda x: x['avg_pnl'], reverse=True)

    baseline = next((s for s in summary if s['label'].startswith('현행')), summary[0])

    print(f'\n{"전략":>20} {"거래":>5} {"승률":>6} {"평균":>7} {"원금수익":>9} {"vs현행":>7} {"최고평균":>7} {"놓친%":>6}  청산사유분포')
    print('-' * 110)
    for s in summary:
        diff = s['avg_pnl'] - baseline['avg_pnl']
        # 사유 요약
        r = s['reasons']
        reason_str = ' '.join(f"{k}{v}" for k, v in sorted(r.items()))

        marker = ' <-- 현행' if s['label'].startswith('현행') else ''
        print(f"{s['label']:>20} {s['total']:>5} {s['winrate']:>5.1f}% {s['avg_pnl']:>+6.2f}% {s['cap_ret']:>+8.1f}% {diff:>+6.2f}%p {s['avg_max']:>+6.2f}% {s['avg_missed']:>5.2f}%  {reason_str}{marker}")

    # 카테고리별 최적
    print('\n\n')
    print('=' * 90)
    print('카테고리별 최적 전략')
    print('=' * 90)

    categories = {
        '트레일링': [s for s in summary if '트레일-' in s['label'] and '시~' not in s['label']],
        '시간+수익': [s for s in summary if '시수익' in s['label'] or '시+' in s['label']],
        '오후트레일링': [s for s in summary if '시~트레일' in s['label']],
        '수익확보': [s for s in summary if '확보' in s['label']],
    }

    for cat, items in categories.items():
        if not items:
            continue
        best = max(items, key=lambda x: x['avg_pnl'])
        diff = best['avg_pnl'] - baseline['avg_pnl']
        print(f'\n[{cat}] 최적: {best["label"]}')
        print(f'  평균 {best["avg_pnl"]:+.2f}% (현행 대비 {diff:+.2f}%p), 승률 {best["winrate"]:.1f}%, 원금수익률 {best["cap_ret"]:+.1f}%')

    print(f'\n[현행] {baseline["label"]}')
    print(f'  평균 {baseline["avg_pnl"]:+.2f}%, 승률 {baseline["winrate"]:.1f}%, 원금수익률 {baseline["cap_ret"]:+.1f}%')

    print('\nDone!')


def main():
    parser = argparse.ArgumentParser(description='멀티버스: 청산 전략 비교')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default=None, help='종료일')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
