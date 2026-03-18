"""
멀티버스 시뮬레이션: 일괄매도 시간 비교

현재 15:00 일괄매도 vs 더 이른 시간 일괄매도 비교.
13:00, 13:30, 14:00, 14:30, 15:00 각각에서 장마감 청산했을 때 수익 차이 분석.
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
    apply_screener_filter, apply_daily_limit, calc_capital_returns, print_stats,
)


def simulate_trade_with_cutoff(strategy, df, entry_idx, cutoff_time_str):
    """
    조기 청산 시간을 적용한 simulate_trade

    cutoff_time_str: "130000", "133000", "140000", "143000", "150000" 등
    해당 시간 이후의 캔들은 장마감으로 간주
    """
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']

    if entry_price <= 0:
        return None

    cutoff_int = int(cutoff_time_str)
    max_profit_pct = 0.0
    last_valid_row = None

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        row_time = int(str(row['time']).replace(':', '').ljust(6, '0')[:6])

        # cutoff 시간 초과 시 이 캔들에서 장마감 청산
        if row_time >= cutoff_int:
            # 이 캔들의 시가에서 청산 (cutoff 시점에 시장가 매도)
            exit_price = row['open']
            exit_pnl = (exit_price / entry_price - 1) * 100

            # 이 캔들의 고가/저가로 손절/익절 체크 (cutoff 전 도달 가능)
            high_pnl = (row['high'] / entry_price - 1) * 100
            if high_pnl > max_profit_pct:
                max_profit_pct = high_pnl

            should_exit, reason, pnl = strategy.check_exit_conditions(
                entry_price=entry_price,
                current_high=row['high'],
                current_low=row['low'],
                current_close=exit_price,
            )
            if should_exit:
                return {
                    'result': 'WIN' if pnl > 0 else 'LOSS',
                    'pnl': pnl,
                    'exit_reason': reason,
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                    'holding_candles': i - entry_idx,
                    'max_profit_pct': round(max_profit_pct, 2),
                }

            # 손절/익절 미해당 → 시가에서 장마감 청산
            return {
                'result': 'WIN' if exit_pnl > 0 else 'LOSS',
                'pnl': exit_pnl,
                'exit_reason': '장마감',
                'entry_time': entry_time,
                'exit_time': row['time'],
                'entry_price': entry_price,
                'holding_candles': i - entry_idx,
                'max_profit_pct': round(max_profit_pct, 2),
            }

        # cutoff 전: 정상 손절/익절 체크
        high_pnl = (row['high'] / entry_price - 1) * 100
        if high_pnl > max_profit_pct:
            max_profit_pct = high_pnl

        should_exit, reason, pnl = strategy.check_exit_conditions(
            entry_price=entry_price,
            current_high=row['high'],
            current_low=row['low'],
            current_close=row['close'],
        )
        if should_exit:
            return {
                'result': 'WIN' if pnl > 0 else 'LOSS',
                'pnl': pnl,
                'exit_reason': reason,
                'entry_time': entry_time,
                'exit_time': row['time'],
                'entry_price': entry_price,
                'holding_candles': i - entry_idx,
                'max_profit_pct': round(max_profit_pct, 2),
            }

        last_valid_row = row

    # 데이터 끝까지 왔으면 마지막 캔들에서 청산
    if last_valid_row is not None:
        last_pnl = (last_valid_row['close'] / entry_price - 1) * 100
        return {
            'result': 'WIN' if last_pnl > 0 else 'LOSS',
            'pnl': last_pnl,
            'exit_reason': '장마감',
            'entry_time': entry_time,
            'exit_time': last_valid_row['time'],
            'entry_price': entry_price,
            'holding_candles': len(df) - 1 - entry_idx,
            'max_profit_pct': round(max_profit_pct, 2),
        }

    return None


def run_multiverse(start_date='20250224', end_date=None, verbose=True):
    """여러 청산 시간으로 멀티버스 시뮬레이션"""

    cutoff_times = [
        ('12:00', '120000'),
        ('13:00', '130000'),
        ('13:30', '133000'),
        ('14:00', '140000'),
        ('14:30', '143000'),
        ('15:00', '150000'),  # 현재 설정 (baseline)
    ]

    # 전략 설정 로드
    strategy = PricePositionStrategy()
    info = strategy.get_strategy_info()

    print('=' * 80)
    print('멀티버스 시뮬레이션: 일괄매도 시간 비교')
    print('=' * 80)
    print(f"진입: 시가 대비 {info['entry_conditions']['pct_from_open']}, "
          f"{info['entry_conditions']['time_range']}")
    print(f"청산: 손절 {info['exit_conditions']['stop_loss']}, "
          f"익절 {info['exit_conditions']['take_profit']}")
    print(f"비교 시간: {', '.join(t[0] for t in cutoff_times)}")
    print(f"기간: {start_date} ~ {end_date or '전체'}")
    print('=' * 80)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    # 각 cutoff별 거래 결과
    all_results = {ct[0]: [] for ct in cutoff_times}

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

                # 진입 시점 찾기 (모든 cutoff에서 동일)
                entry_found = False
                for candle_idx in range(10, len(df) - 10):
                    if entry_found:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    can_enter, reason = strategy.check_entry_conditions(
                        stock_code=stock_code,
                        current_price=current_price,
                        day_open=day_open,
                        current_time=current_time,
                        trade_date=trade_date,
                        weekday=weekday,
                    )
                    if not can_enter:
                        continue

                    adv_ok, adv_reason = strategy.check_advanced_conditions(
                        df=df, candle_idx=candle_idx
                    )
                    if not adv_ok:
                        continue

                    # 진입 확인 → 각 cutoff 시간별로 시뮬레이션
                    pct_from_open = (current_price / day_open - 1) * 100

                    for label, cutoff_str in cutoff_times:
                        result = simulate_trade_with_cutoff(
                            strategy, df, candle_idx, cutoff_str
                        )
                        if result:
                            all_results[label].append({
                                'date': trade_date,
                                'stock_code': stock_code,
                                'weekday': weekday,
                                'pct_from_open': pct_from_open,
                                **result,
                            })

                    strategy.record_trade(stock_code, trade_date)
                    entry_found = True

            except Exception:
                continue

    cur.close()
    conn.close()

    # ====== 결과 출력 ======
    print('\n\n')
    print('#' * 80)
    print('#  멀티버스 결과 비교: 일괄매도 시간별')
    print('#' * 80)

    summary_rows = []
    for label, cutoff_str in cutoff_times:
        trades = all_results[label]
        if not trades:
            summary_rows.append((label, 0, 0, 0, 0, 0, 0))
            continue

        trades_df = pd.DataFrame(trades)
        limited_df = apply_daily_limit(trades_df, 5)

        if len(limited_df) == 0:
            summary_rows.append((label, 0, 0, 0, 0, 0, 0))
            continue

        total = len(limited_df)
        wins = (limited_df['result'] == 'WIN').sum()
        losses = (limited_df['result'] == 'LOSS').sum()
        winrate = wins / total * 100
        avg_pnl = limited_df['pnl'].mean()

        cap = calc_capital_returns(limited_df)
        cap_return = cap['total_return_pct']

        # 청산 사유별 카운트
        n_sl = len(limited_df[limited_df['exit_reason'] == '손절'])
        n_tp = len(limited_df[limited_df['exit_reason'] == '익절'])
        n_mc = len(limited_df[limited_df['exit_reason'] == '장마감'])

        summary_rows.append((label, total, wins, winrate, avg_pnl, cap_return, n_sl, n_tp, n_mc))

    # 요약 테이블
    print(f'\n{"청산시간":>8} {"거래수":>7} {"승수":>5} {"승률":>7} {"평균수익":>9} {"원금수익률":>10}  {"손절":>5} {"익절":>5} {"장마감":>5}')
    print('-' * 80)
    for row in summary_rows:
        if len(row) == 7:
            label, total, wins, winrate, avg_pnl, cap_return, _ = row
            print(f'{label:>8} {total:>7} {wins:>5} {winrate:>6.1f}% {avg_pnl:>+8.2f}% {cap_return:>+9.2f}%')
        else:
            label, total, wins, winrate, avg_pnl, cap_return, n_sl, n_tp, n_mc = row
            print(f'{label:>8} {total:>7} {wins:>5} {winrate:>6.1f}% {avg_pnl:>+8.2f}% {cap_return:>+9.2f}%  {n_sl:>5} {n_tp:>5} {n_mc:>5}')

    # 15:00 대비 차이
    baseline = summary_rows[-1]
    if baseline[1] > 0:
        print(f'\n{"":>8} {"":>7} {"":>5} {"":>7} {"vs 15시":>9} {"vs 15시":>10}')
        print('-' * 60)
        for row in summary_rows[:-1]:
            if len(row) >= 6 and row[1] > 0:
                diff_avg = row[4] - baseline[4]
                diff_cap = row[5] - baseline[5]
                print(f'{row[0]:>8} {"":>7} {"":>5} {"":>7} {diff_avg:>+8.2f}%p {diff_cap:>+9.2f}%p')

    # 각 시간대별 상세 출력
    for label, cutoff_str in cutoff_times:
        trades = all_results[label]
        if not trades:
            continue
        trades_df = pd.DataFrame(trades)
        limited_df = apply_daily_limit(trades_df, 5)
        if len(limited_df) > 0:
            limited_daily = defaultdict(list)
            for _, row in limited_df.iterrows():
                limited_daily[row['date']].append(row.to_dict())
            print(f'\n\n{"="*80}')
            print(f'상세: 청산시간 {label}')
            print(f'{"="*80}')
            print_stats(limited_df, limited_daily, f'청산 {label}')

    print('\nDone!')


def main():
    parser = argparse.ArgumentParser(description='멀티버스: 일괄매도 시간 비교')
    parser.add_argument('--start', default='20250224', help='시작일 (default: 20250224)')
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
