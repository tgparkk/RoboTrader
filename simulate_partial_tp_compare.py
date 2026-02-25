"""
분할 익절 vs 기존 전략 비교 시뮬레이션

동일한 진입 조건에서:
  - Original: +5% 익절 / -4% 손절 (전량)
  - Partial TP: +3% 시 30% 매도, 이후 +7% 익절 or 0% 손절 (잔여 70%)

동일 데이터, 동일 진입 시점에서 청산 방식만 다르게 적용하여 비교.
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


# ===== 기존 simulate_with_screener.py에서 재사용 =====

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
        SELECT stock_code,
               MIN(CASE WHEN idx = (
                   SELECT MIN(idx) FROM minute_candles mc2
                   WHERE mc2.stock_code = minute_candles.stock_code
                     AND mc2.trade_date = %s
               ) THEN open END) as day_open,
               SUM(amount) as daily_amount
        FROM minute_candles
        WHERE trade_date = %s
        GROUP BY stock_code
    ''', [trade_date, trade_date])
    return {
        row[0]: {'day_open': row[1] or 0, 'daily_amount': row[2] or 0}
        for row in cur.fetchall()
    }


def apply_screener_filter(daily_metrics, prev_close_map,
                          top_n=60, min_price=5000, max_price=500000,
                          min_amount=1_000_000_000, max_gap_pct=3.0):
    ranked = sorted(
        daily_metrics.items(),
        key=lambda x: x[1]['daily_amount'],
        reverse=True
    )[:top_n]

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
            gap_pct = abs(day_open / prev_close - 1) * 100
            if gap_pct > max_gap_pct:
                continue
        passed.add(stock_code)
    return passed


def apply_daily_limit(trades_df, max_daily):
    limited = []
    for date in trades_df['date'].unique():
        day_trades = trades_df[trades_df['date'] == date].copy()
        day_trades = day_trades.sort_values('entry_time')
        accepted = []
        for _, trade in day_trades.iterrows():
            entry_t = str(trade['entry_time']).zfill(6)
            exit_t = str(trade['exit_time']).zfill(6)
            holding = sum(1 for _, et in accepted if et > entry_t)
            if holding < max_daily:
                accepted.append((entry_t, exit_t))
                limited.append(trade)
    return pd.DataFrame(limited).reset_index(drop=True) if limited else pd.DataFrame()


# ===== 분할 익절 시뮬레이션 =====

def simulate_trade_partial_tp(
    df, entry_idx,
    stop_loss_pct=-4.0,    # 기본 손절 %
    tp1_pct=3.0,           # 1차 익절 %
    sell_ratio=0.3,        # 1차 매도 비율
    tp2_pct=7.0,           # 2차 익절 %
    remaining_sl_pct=0.0,  # 나머지 손절 % (0=본전)
):
    """
    분할 익절 시뮬레이션

    Returns:
        dict with: result, pnl (가중평균), exit_reason, entry_time, exit_time,
                   entry_price, holding_candles, detail
    """
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']

    if entry_price <= 0:
        return None

    stage = 0  # 0: 1차 미발동, 1: 1차 완료
    tp1_pnl = None  # 1차 매도 수익률 기록

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl = (row['low'] / entry_price - 1) * 100
        close_pnl = (row['close'] / entry_price - 1) * 100

        if stage == 0:
            # TP2 직행 체크 (고가가 TP2 이상이면 partial 건너뜀)
            if high_pnl >= tp2_pct:
                # 전량 TP2에서 매도
                total_pnl = tp2_pct
                return {
                    'result': 'WIN',
                    'pnl': total_pnl,
                    'exit_reason': 'TP2직행',
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                    'holding_candles': i - entry_idx,
                    'detail': f'전량 +{tp2_pct:.1f}%',
                }

            # 1차 익절 체크 (고가 기준)
            if high_pnl >= tp1_pct:
                tp1_pnl = tp1_pct
                stage = 1
                # 같은 캔들에서 나머지 손절도 체크
                if low_pnl <= remaining_sl_pct:
                    remaining_pnl = remaining_sl_pct
                    total_pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * remaining_pnl
                    return {
                        'result': 'WIN' if total_pnl > 0 else 'LOSS',
                        'pnl': total_pnl,
                        'exit_reason': '1차익절+잔여손절',
                        'entry_time': entry_time,
                        'exit_time': row['time'],
                        'entry_price': entry_price,
                        'holding_candles': i - entry_idx,
                        'detail': f'{sell_ratio:.0%}@+{tp1_pct:.1f}% + {1-sell_ratio:.0%}@{remaining_pnl:.1f}%',
                    }
                continue  # 다음 캔들에서 2차 체크

            # 기본 손절 (고가가 TP1 미달 && 저가가 SL 이하)
            if low_pnl <= stop_loss_pct:
                return {
                    'result': 'LOSS',
                    'pnl': stop_loss_pct,
                    'exit_reason': '손절',
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                    'holding_candles': i - entry_idx,
                    'detail': f'전량 {stop_loss_pct:.1f}%',
                }

        elif stage == 1:
            # 2차 익절 (고가 기준)
            if high_pnl >= tp2_pct:
                remaining_pnl = tp2_pct
                total_pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * remaining_pnl
                return {
                    'result': 'WIN',
                    'pnl': total_pnl,
                    'exit_reason': '2차익절',
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                    'holding_candles': i - entry_idx,
                    'detail': f'{sell_ratio:.0%}@+{tp1_pnl:.1f}% + {1-sell_ratio:.0%}@+{tp2_pct:.1f}%',
                }

            # 나머지 손절 (저가 기준)
            if low_pnl <= remaining_sl_pct:
                remaining_pnl = remaining_sl_pct
                total_pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * remaining_pnl
                return {
                    'result': 'WIN' if total_pnl > 0 else 'LOSS',
                    'pnl': total_pnl,
                    'exit_reason': '잔여손절',
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                    'holding_candles': i - entry_idx,
                    'detail': f'{sell_ratio:.0%}@+{tp1_pnl:.1f}% + {1-sell_ratio:.0%}@{remaining_pnl:.1f}%',
                }

    # 장 마감 시 청산
    last_row = df.iloc[-1]
    last_pnl = (last_row['close'] / entry_price - 1) * 100

    if stage == 0:
        total_pnl = last_pnl
        detail = f'전량 {last_pnl:.2f}%'
    else:
        total_pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * last_pnl
        detail = f'{sell_ratio:.0%}@+{tp1_pnl:.1f}% + {1-sell_ratio:.0%}@{last_pnl:.2f}%'

    return {
        'result': 'WIN' if total_pnl > 0 else 'LOSS',
        'pnl': total_pnl,
        'exit_reason': '장마감',
        'entry_time': entry_time,
        'exit_time': last_row['time'],
        'entry_price': entry_price,
        'holding_candles': len(df) - 1 - entry_idx,
        'detail': detail,
    }


# ===== 비교 실행 =====

def run_comparison(
    start_date='20250901',
    end_date=None,
    max_daily=5,
    screener_top_n=60,
    screener_min_amount=1_000_000_000,
    screener_max_gap=3.0,
    screener_min_price=5000,
    screener_max_price=500000,
    verbose=True,
):
    """동일 진입 시점에서 Original vs Partial TP 비교"""

    # 전략 설정 (진입 조건 동일)
    strategy = PricePositionStrategy(config={
        'stop_loss_pct': -4.0,
        'take_profit_pct': 5.0,
    })

    print('=' * 80)
    print('분할 익절 vs 기존 전략 비교 시뮬레이션')
    print('=' * 80)
    print(f'  Original : 익절 +5.0% / 손절 -4.0% (전량)')
    print(f'  Partial  : 1차 +3.0% (30% 매도) → 2차 +7.0% or 본전 0% (70% 매도)')
    print(f'  기간: {start_date} ~ {end_date or "전체"}')
    print(f'  동시보유: {max_daily}종목')
    print('=' * 80)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    original_trades = []
    partial_trades = []

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 처리 중... '
                  f'거래 {len(original_trades)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=screener_top_n, min_price=screener_min_price,
            max_price=screener_max_price, min_amount=screener_min_amount,
            max_gap_pct=screener_max_gap,
        )

        if not screened:
            continue

        strategy.reset_daily_trades(trade_date)

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

                traded = False
                for candle_idx in range(10, len(df) - 10):
                    if traded:
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

                    # 동일 진입 시점에서 양쪽 버전 시뮬
                    result_orig = strategy.simulate_trade(df, candle_idx)
                    result_partial = simulate_trade_partial_tp(
                        df, candle_idx,
                        stop_loss_pct=-4.0,
                        tp1_pct=3.0,
                        sell_ratio=0.3,
                        tp2_pct=7.0,
                        remaining_sl_pct=0.0,
                    )

                    if result_orig and result_partial:
                        pct_from_open = (current_price / day_open - 1) * 100
                        base = {
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                        }
                        original_trades.append({**base, **result_orig})
                        partial_trades.append({**base, **result_partial})
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    if not original_trades:
        print('\n거래 없음')
        return

    orig_df = pd.DataFrame(original_trades)
    part_df = pd.DataFrame(partial_trades)

    # 동시보유 제한 적용
    if max_daily > 0:
        orig_limited = apply_daily_limit(orig_df, max_daily)
        # 동일 인덱스 사용 (같은 거래만 비교)
        if len(orig_limited) > 0:
            limited_keys = set(zip(orig_limited['date'], orig_limited['stock_code']))
            part_limited = part_df[
                part_df.apply(lambda r: (r['date'], r['stock_code']) in limited_keys, axis=1)
            ].reset_index(drop=True)
        else:
            part_limited = pd.DataFrame()
    else:
        orig_limited = orig_df
        part_limited = part_df

    # ===== 결과 출력 =====
    print('\n')
    print('#' * 80)
    print(f'#  비교 결과 (동시보유 {max_daily}종목 제한)')
    print('#' * 80)

    def calc_stats(df_trades, label):
        total = len(df_trades)
        if total == 0:
            return {}
        wins = (df_trades['result'] == 'WIN').sum()
        losses = total - wins
        winrate = wins / total * 100
        total_pnl = df_trades['pnl'].sum()
        avg_pnl = df_trades['pnl'].mean()
        avg_win = df_trades[df_trades['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
        avg_loss = df_trades[df_trades['result'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        return {
            'label': label, 'total': total, 'wins': wins, 'losses': losses,
            'winrate': winrate, 'total_pnl': total_pnl, 'avg_pnl': avg_pnl,
            'avg_win': avg_win, 'avg_loss': avg_loss, 'pl_ratio': pl_ratio,
        }

    orig_s = calc_stats(orig_limited, 'Original (+5%/-4%)')
    part_s = calc_stats(part_limited, 'Partial TP (+3%→+7%/0%)')

    if not orig_s or not part_s:
        print('비교할 거래 없음')
        return

    print(f"\n{'':>25} {'Original':>18} {'Partial TP':>18} {'차이':>12}")
    print('-' * 75)
    print(f"{'총 거래':>25} {orig_s['total']:>17}건 {part_s['total']:>17}건")
    print(f"{'승/패':>25} {orig_s['wins']:>8}승 {orig_s['losses']:>5}패 "
          f"{part_s['wins']:>8}승 {part_s['losses']:>5}패")
    print(f"{'승률':>25} {orig_s['winrate']:>17.1f}% {part_s['winrate']:>17.1f}% "
          f"{part_s['winrate'] - orig_s['winrate']:>+11.1f}%p")
    print(f"{'총 수익률':>25} {orig_s['total_pnl']:>+17.1f}% {part_s['total_pnl']:>+17.1f}% "
          f"{part_s['total_pnl'] - orig_s['total_pnl']:>+11.1f}%")
    print(f"{'평균 수익률':>25} {orig_s['avg_pnl']:>+17.2f}% {part_s['avg_pnl']:>+17.2f}% "
          f"{part_s['avg_pnl'] - orig_s['avg_pnl']:>+11.2f}%")
    print(f"{'평균 승리':>25} {orig_s['avg_win']:>+17.2f}% {part_s['avg_win']:>+17.2f}%")
    print(f"{'평균 손실':>25} {orig_s['avg_loss']:>+17.2f}% {part_s['avg_loss']:>+17.2f}%")
    print(f"{'손익비':>25} {orig_s['pl_ratio']:>17.2f}:1 {part_s['pl_ratio']:>17.2f}:1")

    # 100만원/건 기준 월간 수익 추정
    dates = sorted(orig_limited['date'].unique())
    num_months = max(len(set(d[:6] for d in dates)), 1)
    orig_monthly = (orig_s['total_pnl'] / num_months) * 10000
    part_monthly = (part_s['total_pnl'] / num_months) * 10000
    print(f"\n{'월평균 수익(100만/건)':>25} {orig_monthly:>+15,.0f}원 {part_monthly:>+15,.0f}원 "
          f"{part_monthly - orig_monthly:>+11,.0f}원")

    # 청산 사유별 비교
    print('\n' + '=' * 80)
    print('청산 사유별 비교')
    print('=' * 80)

    print(f"\n--- Original ---")
    for reason in orig_limited['exit_reason'].unique():
        f = orig_limited[orig_limited['exit_reason'] == reason]
        w = (f['result'] == 'WIN').sum()
        print(f'  {reason:>8}: {len(f):>4}건, {w}승 {len(f)-w}패, '
              f'승률{w/len(f)*100:>5.1f}%, 총{f["pnl"].sum():>+7.1f}%')

    print(f"\n--- Partial TP ---")
    for reason in sorted(part_limited['exit_reason'].unique()):
        f = part_limited[part_limited['exit_reason'] == reason]
        w = (f['result'] == 'WIN').sum()
        print(f'  {reason:>10}: {len(f):>4}건, {w}승 {len(f)-w}패, '
              f'승률{w/len(f)*100:>5.1f}%, 총{f["pnl"].sum():>+7.1f}%')

    # 거래별 비교 (Original이 손실인데 Partial이 이익인 경우 등)
    print('\n' + '=' * 80)
    print('흐름 전환 분석 (동일 진입에서 결과가 달라진 거래)')
    print('=' * 80)

    merged = orig_limited[['date', 'stock_code', 'pnl', 'exit_reason']].copy()
    merged.columns = ['date', 'stock_code', 'orig_pnl', 'orig_reason']
    merged['part_pnl'] = part_limited['pnl'].values
    merged['part_reason'] = part_limited['exit_reason'].values
    merged['diff'] = merged['part_pnl'] - merged['orig_pnl']

    improved = merged[merged['diff'] > 0.1]
    worsened = merged[merged['diff'] < -0.1]
    similar = merged[abs(merged['diff']) <= 0.1]

    print(f"\n  개선된 거래: {len(improved)}건 (평균 +{improved['diff'].mean():.2f}%p)" if len(improved) > 0 else "  개선된 거래: 0건")
    print(f"  악화된 거래: {len(worsened)}건 (평균 {worsened['diff'].mean():.2f}%p)" if len(worsened) > 0 else "  악화된 거래: 0건")
    print(f"  동일한 거래: {len(similar)}건")

    # 흐름 전환 상세
    if len(improved) > 0:
        print(f"\n  [개선 TOP 5] (Original → Partial TP)")
        for _, r in improved.nlargest(5, 'diff').iterrows():
            print(f"    {r['date']} {r['stock_code']}: {r['orig_pnl']:+.2f}%({r['orig_reason']}) → "
                  f"{r['part_pnl']:+.2f}%({r['part_reason']}) = {r['diff']:+.2f}%p")

    if len(worsened) > 0:
        print(f"\n  [악화 TOP 5] (Original → Partial TP)")
        for _, r in worsened.nsmallest(5, 'diff').iterrows():
            print(f"    {r['date']} {r['stock_code']}: {r['orig_pnl']:+.2f}%({r['orig_reason']}) → "
                  f"{r['part_pnl']:+.2f}%({r['part_reason']}) = {r['diff']:+.2f}%p")

    # 월별 비교
    print('\n' + '=' * 80)
    print('월별 비교')
    print('=' * 80)
    orig_limited_c = orig_limited.copy()
    part_limited_c = part_limited.copy()
    orig_limited_c['month'] = orig_limited_c['date'].str[:6]
    part_limited_c['month'] = part_limited_c['date'].str[:6]

    print(f"\n{'월':>8} {'Original':>15} {'Partial TP':>15} {'차이':>10}")
    print('-' * 50)
    for month in sorted(orig_limited_c['month'].unique()):
        o = orig_limited_c[orig_limited_c['month'] == month]
        p = part_limited_c[part_limited_c['month'] == month]
        o_pnl = o['pnl'].sum()
        p_pnl = p['pnl'].sum()
        print(f"  {month:>6} {o_pnl:>+14.1f}% {p_pnl:>+14.1f}% {p_pnl - o_pnl:>+9.1f}%")

    totals_o = orig_limited_c['pnl'].sum()
    totals_p = part_limited_c['pnl'].sum()
    print('-' * 50)
    print(f"  {'합계':>6} {totals_o:>+14.1f}% {totals_p:>+14.1f}% {totals_p - totals_o:>+9.1f}%")

    # 최종 판정
    print('\n' + '=' * 80)
    diff_total = part_s['total_pnl'] - orig_s['total_pnl']
    if diff_total > 0:
        winner = 'Partial TP'
    elif diff_total < 0:
        winner = 'Original'
    else:
        winner = '무승부'
    print(f'  최종 승자: {winner} (총 수익률 차이: {diff_total:+.1f}%)')
    print('=' * 80)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='분할 익절 비교 시뮬레이션')
    parser.add_argument('--start', default='20250901', help='시작일 (YYYYMMDD)')
    parser.add_argument('--end', default=None, help='종료일 (YYYYMMDD)')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 최대')
    args = parser.parse_args()

    run_comparison(
        start_date=args.start,
        end_date=args.end,
        max_daily=args.max_daily,
    )
