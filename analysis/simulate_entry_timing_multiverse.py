"""
매수 시간대 멀티버스 시뮬레이션

목적: 매수 시간 범위를 변경했을 때 수익률 변화 정밀 검증
- 현재: 9~12시
- 후보: 9~10시, 9~10:30, 9~11시, 9:05~10시, 9:15~10시 등
- 추가: ATR 8%+ 차단 효과
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from config.strategy_settings import StrategySettings


def get_stock_atr_from_db(cur, stock_code, trade_date, lookback=20):
    """DB에서 ATR 계산"""
    cur.execute('''
        SELECT stck_hgpr::float, stck_lwpr::float, stck_clpr::float
        FROM daily_candles
        WHERE stock_code = %s AND stck_bsop_date < %s
        ORDER BY stck_bsop_date DESC
        LIMIT %s
    ''', [stock_code, trade_date, lookback + 1])
    rows = cur.fetchall()
    if len(rows) < 5:
        return None
    trs = []
    for i in range(len(rows) - 1):
        high, low, close = rows[i]
        prev_close = rows[i + 1][2]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if not trs:
        return None
    atr = sum(trs) / len(trs)
    current_close = rows[0][2]
    if current_close <= 0:
        return None
    return (atr / current_close) * 100


def simulate_single_trade(df, entry_idx, tp_pct, sl_pct):
    """단일 거래 시뮬레이션"""
    entry_price = df.iloc[entry_idx + 1]['open']
    if entry_price <= 0:
        return None

    max_profit = 0.0
    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl = (row['low'] / entry_price - 1) * 100
        if high_pnl > max_profit:
            max_profit = high_pnl
        if high_pnl >= tp_pct:
            return {'pnl': tp_pct, 'reason': 'TP', 'max_profit': max_profit}
        if low_pnl <= sl_pct:
            return {'pnl': sl_pct, 'reason': 'SL', 'max_profit': max_profit}

    last_pnl = (df.iloc[-1]['close'] / entry_price - 1) * 100
    return {'pnl': last_pnl, 'reason': 'EOD', 'max_profit': max_profit}


def main():
    pp = StrategySettings.PricePosition

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    start_date, end_date = '20250224', '20260401'

    cur.execute('''
        SELECT DISTINCT trade_date FROM minute_candles
        WHERE trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date
    ''', [start_date, end_date])
    trading_dates = [r[0] for r in cur.fetchall()]
    print(f'거래일: {len(trading_dates)}일 ({start_date}~{end_date})')

    # === 진입 포인트 수집 (9~12시 전체, 분 단위 기록) ===
    print('\n=== 진입 포인트 수집 ===')

    from simulate_with_screener import (
        get_daily_metrics, get_prev_close_map, apply_screener_filter,
        check_circuit_breaker,
    )
    from core.strategies.price_position_strategy import PricePositionStrategy

    config = {
        'min_pct_from_open': pp.MIN_PCT_FROM_OPEN,
        'max_pct_from_open': pp.MAX_PCT_FROM_OPEN,
        'entry_start_hour': 9,
        'entry_end_hour': 12,
        'stop_loss_pct': -5.0,
        'take_profit_pct': 6.0,
    }
    strategy = PricePositionStrategy(config=config)

    entries = []

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) ... {len(entries)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        if day_idx > 1:
            prev_prev = trading_dates[day_idx - 2]
            is_cb, _ = check_circuit_breaker(cur, prev_date, prev_prev, -3.0)
            if is_cb:
                continue

        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = get_prev_close_map(cur, trade_date, prev_date) if prev_date else {}

        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=60, min_amount=1e9, max_gap_pct=3.0,
            min_change_rate=0.5, max_change_rate=5.0,
            max_candidates=15,
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

                traded = False
                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time']).zfill(6)
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

                    atr_pct = get_stock_atr_from_db(cur, stock_code, trade_date)

                    # 시간을 분 단위로 기록
                    entry_hour = int(current_time[:2])
                    entry_min = int(current_time[2:4])
                    entry_time_min = entry_hour * 60 + entry_min  # 분 단위

                    # 거래 시뮬레이션 (고정 SL5/TP6)
                    result = simulate_single_trade(df, candle_idx, 6.0, -5.0)
                    if result:
                        entries.append({
                            'trade_date': trade_date,
                            'stock_code': stock_code,
                            'entry_time': current_time,
                            'entry_hour': entry_hour,
                            'entry_min': entry_min,
                            'entry_time_min': entry_time_min,
                            'weekday': weekday,
                            'atr_pct': atr_pct,
                            'pnl': result['pnl'],
                            'reason': result['reason'],
                            'max_profit': result['max_profit'],
                        })
                        traded = True

            except Exception:
                continue

    print(f'\n총 거래: {len(entries)}건')

    df_all = pd.DataFrame(entries)
    cost_pct = 0.33

    # === 시간대별 멀티버스 ===
    print('\n' + '=' * 90)
    print('=== 매수 시간 범위 멀티버스 ===')
    print('=' * 90)

    # 시간 범위 시나리오 (분 단위)
    time_scenarios = [
        ('9:00~9:30',  540, 570),
        ('9:00~9:45',  540, 585),
        ('9:00~10:00', 540, 600),
        ('9:00~10:30', 540, 630),
        ('9:00~11:00', 540, 660),
        ('9:00~12:00 (현재)', 540, 720),
        ('9:05~9:30',  545, 570),
        ('9:05~10:00', 545, 600),
        ('9:10~10:00', 550, 600),
        ('9:15~10:00', 555, 600),
        ('9:15~10:30', 555, 630),
        ('9:15~11:00', 555, 660),
    ]

    print(f'\n{"시간 범위":<22} {"거래":>5} {"승률":>7} {"순평균":>8} {"수익률":>9} '
          f'{"월평균":>7} {"익절":>5} {"손절":>5} {"EOD":>5}')
    print('-' * 85)

    num_months = 13.0

    for label, start_min, end_min in time_scenarios:
        ft = df_all[(df_all['entry_time_min'] >= start_min) &
                     (df_all['entry_time_min'] < end_min)]
        if len(ft) == 0:
            continue

        # 동시보유 7종목 제한 적용
        limited = []
        for date in sorted(ft['trade_date'].unique()):
            day = ft[ft['trade_date'] == date].sort_values('entry_time_min')
            count = 0
            for _, t in day.iterrows():
                if count < 7:
                    limited.append(t)
                    count += 1
        ft_limited = pd.DataFrame(limited)

        net = ft_limited['pnl'] - cost_pct
        wins = (net > 0).sum()
        total = len(ft_limited)
        avg_net = net.mean()

        invest = 10_000_000 * 0.20
        total_profit = sum(invest * (p / 100) for p in net)
        return_pct = total_profit / 10_000_000 * 100
        monthly = return_pct / num_months

        tp_cnt = (ft_limited['reason'] == 'TP').sum()
        sl_cnt = (ft_limited['reason'] == 'SL').sum()
        eod_cnt = (ft_limited['reason'] == 'EOD').sum()

        marker = ' <--' if label == '9:00~12:00 (현재)' else ''
        print(f'{label:<22} {total:>5} {wins/total*100:>6.1f}% {avg_net:>+7.2f}% '
              f'{return_pct:>+8.1f}% {monthly:>+6.1f}% {tp_cnt:>5} {sl_cnt:>5} {eod_cnt:>5}{marker}')

    # === ATR 필터 조합 ===
    print('\n\n' + '=' * 90)
    print('=== ATR 필터 + 시간 범위 조합 ===')
    print('=' * 90)

    atr_filters = [
        ('ATR 제한 없음', 0, 100),
        ('ATR < 10%', 0, 10),
        ('ATR < 8%', 0, 8),
        ('ATR < 6%', 0, 6),
        ('ATR 3~8%', 3, 8),
    ]

    best_combos = [
        ('9:00~10:00', 540, 600),
        ('9:00~10:30', 540, 630),
        ('9:00~12:00 (현재)', 540, 720),
    ]

    print(f'\n{"조합":<40} {"거래":>5} {"승률":>7} {"순평균":>8} {"수익률":>9}')
    print('-' * 75)

    for time_label, t_start, t_end in best_combos:
        for atr_label, atr_lo, atr_hi in atr_filters:
            ft = df_all[(df_all['entry_time_min'] >= t_start) &
                         (df_all['entry_time_min'] < t_end)]

            # ATR 필터 (ATR 없는 건은 통과시킴 - 데이터 30%만 ATR 있음)
            if atr_lo > 0 or atr_hi < 100:
                ft = ft[(ft['atr_pct'].isna()) |
                         ((ft['atr_pct'] >= atr_lo) & (ft['atr_pct'] < atr_hi))]

            if len(ft) == 0:
                continue

            # 동시보유 7종목 제한
            limited = []
            for date in sorted(ft['trade_date'].unique()):
                day = ft[ft['trade_date'] == date].sort_values('entry_time_min')
                count = 0
                for _, t in day.iterrows():
                    if count < 7:
                        limited.append(t)
                        count += 1
            ft_limited = pd.DataFrame(limited)

            net = ft_limited['pnl'] - cost_pct
            wins = (net > 0).sum()
            total = len(ft_limited)
            avg_net = net.mean()
            invest = 10_000_000 * 0.20
            total_profit = sum(invest * (p / 100) for p in net)
            return_pct = total_profit / 10_000_000 * 100

            combo_label = f'{time_label} + {atr_label}'
            print(f'{combo_label:<40} {total:>5} {wins/total*100:>6.1f}% {avg_net:>+7.2f}% '
                  f'{return_pct:>+8.1f}%')
        print()

    # === 30분 단위 상세 분석 ===
    print('\n' + '=' * 90)
    print('=== 30분 단위 상세 성과 ===')
    print('=' * 90)

    print(f'\n{"시간 슬롯":<15} {"거래":>5} {"승률":>7} {"순평균":>8} {"익절%":>6} {"손절%":>6}')
    print('-' * 55)

    slots = [
        ('09:00~09:15', 540, 555),
        ('09:15~09:30', 555, 570),
        ('09:30~09:45', 570, 585),
        ('09:45~10:00', 585, 600),
        ('10:00~10:30', 600, 630),
        ('10:30~11:00', 630, 660),
        ('11:00~12:00', 660, 720),
    ]

    for label, s, e in slots:
        ft = df_all[(df_all['entry_time_min'] >= s) & (df_all['entry_time_min'] < e)]
        if len(ft) == 0:
            print(f'{label:<15} {"없음":>5}')
            continue
        net = ft['pnl'] - cost_pct
        wins = (net > 0).sum()
        tp_pct = (ft['reason'] == 'TP').sum() / len(ft) * 100
        sl_pct_val = (ft['reason'] == 'SL').sum() / len(ft) * 100
        print(f'{label:<15} {len(ft):>5} {wins/len(ft)*100:>6.1f}% {net.mean():>+7.2f}% '
              f'{tp_pct:>5.1f}% {sl_pct_val:>5.1f}%')

    # === 요일 x 시간대 교차분석 ===
    print('\n\n' + '=' * 90)
    print('=== 요일 x 시간대 교차분석 (순평균 수익률) ===')
    print('=' * 90)

    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    time_buckets = [('9시', 540, 600), ('10시', 600, 660), ('11시', 660, 720)]

    header = f'{"":>5}'
    for tl, _, _ in time_buckets:
        header += f'{tl:>12}'
    header += f'{"전체":>12}'
    print(header)
    print('-' * 55)

    for wd in range(5):
        wd_data = df_all[df_all['weekday'] == wd]
        row_str = f'{weekday_names[wd]:>5}'
        for _, ts, te in time_buckets:
            ft = wd_data[(wd_data['entry_time_min'] >= ts) & (wd_data['entry_time_min'] < te)]
            if len(ft) >= 5:
                net = (ft['pnl'] - cost_pct).mean()
                row_str += f'{net:>+11.2f}%'
            else:
                row_str += f'{"N/A":>12}'
        # 전체
        if len(wd_data) > 0:
            net_all = (wd_data['pnl'] - cost_pct).mean()
            row_str += f'{net_all:>+11.2f}%'
        print(row_str)

    conn.close()
    print('\n\nDone!')


if __name__ == '__main__':
    main()
