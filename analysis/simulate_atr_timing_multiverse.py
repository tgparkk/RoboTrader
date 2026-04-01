"""
ATR 동적 TP/SL + 매수 타이밍 멀티버스 시뮬레이션

목적:
1. 고정 TP/SL vs ATR 동적 TP/SL 비교
2. 매수 시간대별 성과 분석
3. TP/SL 조합 최적화

방법:
- simulate_with_screener의 인프라를 재사용
- 각 거래에 대해 분봉 데이터에서 다양한 TP/SL로 재시뮬레이션
- ATR은 daily_candles에서 계산
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from config.strategy_settings import StrategySettings


def get_stock_atr_from_db(cur, stock_code, trade_date, lookback=20):
    """DB에서 ATR 계산 (일봉 기반)"""
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
    # ATR을 % 단위로 변환 (현재가 대비)
    current_close = rows[0][2]
    if current_close <= 0:
        return None
    return (atr / current_close) * 100


def simulate_single_trade(df, entry_idx, entry_price, tp_pct, sl_pct):
    """단일 거래를 특정 TP/SL로 시뮬레이션"""
    entry_price_actual = df.iloc[entry_idx + 1]['open']
    if entry_price_actual <= 0:
        return None

    max_profit = 0.0
    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        high_pnl = (row['high'] / entry_price_actual - 1) * 100
        low_pnl = (row['low'] / entry_price_actual - 1) * 100
        if high_pnl > max_profit:
            max_profit = high_pnl

        # 익절
        if high_pnl >= tp_pct:
            return {'pnl': tp_pct, 'reason': '익절', 'max_profit': max_profit}
        # 손절
        if low_pnl <= sl_pct:
            return {'pnl': sl_pct, 'reason': '손절', 'max_profit': max_profit}

    # 장마감
    last_pnl = (df.iloc[-1]['close'] / entry_price_actual - 1) * 100
    return {'pnl': last_pnl, 'reason': '장마감', 'max_profit': max_profit}


def main():
    pp = StrategySettings.PricePosition

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    # 시뮬 기간
    start_date = '20250224'
    end_date = '20260401'

    # 거래일 목록
    cur.execute('''
        SELECT DISTINCT trade_date FROM minute_candles
        WHERE trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date
    ''', [start_date, end_date])
    trading_dates = [r[0] for r in cur.fetchall()]
    print(f'거래일: {len(trading_dates)}일 ({start_date}~{end_date})')

    # === Phase 1: 모든 진입 포인트 수집 ===
    print('\n=== Phase 1: 진입 포인트 수집 ===')

    from simulate_with_screener import (
        get_daily_metrics, get_prev_close_map, apply_screener_filter,
        check_circuit_breaker,
    )
    from core.strategies.price_position_strategy import PricePositionStrategy

    # 기본 설정 (현재 운영 설정)
    config = {
        'min_pct_from_open': pp.MIN_PCT_FROM_OPEN,
        'max_pct_from_open': pp.MAX_PCT_FROM_OPEN,
        'entry_start_hour': 9,
        'entry_end_hour': 12,
        'stop_loss_pct': -5.0,
        'take_profit_pct': 6.0,
    }
    strategy = PricePositionStrategy(config=config)

    entries = []  # (trade_date, stock_code, entry_idx, df, atr_pct, entry_hour)

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) ... 진입 {len(entries)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        # 서킷브레이커
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
                    current_time = str(row['time'])
                    current_price = row['close']

                    # 진입 시간 확장 (9~12시 전체 범위)
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

                    # ATR 계산
                    atr_pct = get_stock_atr_from_db(cur, stock_code, trade_date)

                    entry_hour = int(current_time[:2]) if len(current_time) >= 2 else 9

                    entries.append({
                        'trade_date': trade_date,
                        'stock_code': stock_code,
                        'entry_idx': candle_idx,
                        'df': df,
                        'atr_pct': atr_pct,
                        'entry_hour': entry_hour,
                        'weekday': weekday,
                        'pct_from_open': (current_price / day_open - 1) * 100,
                    })
                    traded = True

            except Exception:
                continue

    print(f'\n총 진입 포인트: {len(entries)}건')
    atr_available = sum(1 for e in entries if e['atr_pct'] is not None)
    print(f'ATR 데이터 있는 건: {atr_available}건 ({atr_available/len(entries)*100:.0f}%)')

    # ATR 분포
    atrs = [e['atr_pct'] for e in entries if e['atr_pct'] is not None]
    if atrs:
        print(f'ATR 분포: 평균 {sum(atrs)/len(atrs):.1f}%, '
              f'중위 {sorted(atrs)[len(atrs)//2]:.1f}%, '
              f'최소 {min(atrs):.1f}%, 최대 {max(atrs):.1f}%')

    # === Phase 2: 멀티버스 시뮬레이션 ===
    print('\n=== Phase 2: TP/SL 멀티버스 ===')

    # 테스트할 TP/SL 조합
    scenarios = {
        '고정 SL5/TP6 (현재)':   {'sl': -5.0, 'tp': 6.0, 'mode': 'fixed'},
        '고정 SL5/TP8':          {'sl': -5.0, 'tp': 8.0, 'mode': 'fixed'},
        '고정 SL5/TP10':         {'sl': -5.0, 'tp': 10.0, 'mode': 'fixed'},
        '고정 SL4/TP6':          {'sl': -4.0, 'tp': 6.0, 'mode': 'fixed'},
        '고정 SL3/TP6':          {'sl': -3.0, 'tp': 6.0, 'mode': 'fixed'},
        '고정 SL4/TP8':          {'sl': -4.0, 'tp': 8.0, 'mode': 'fixed'},
        'ATR(x2/x1, 2-10/2-6)': {'mode': 'atr', 'tp_mult': 2.0, 'sl_mult': 1.0,
                                   'tp_min': 2.0, 'tp_max': 10.0, 'sl_min': 2.0, 'sl_max': 6.0},
        'ATR(x1.5/x1, 2-8/2-5)': {'mode': 'atr', 'tp_mult': 1.5, 'sl_mult': 1.0,
                                    'tp_min': 2.0, 'tp_max': 8.0, 'sl_min': 2.0, 'sl_max': 5.0},
        'ATR(x2/x0.8, 3-10/3-5)': {'mode': 'atr', 'tp_mult': 2.0, 'sl_mult': 0.8,
                                     'tp_min': 3.0, 'tp_max': 10.0, 'sl_min': 3.0, 'sl_max': 5.0},
    }

    cost_pct = 0.33
    results = {}

    for name, params in scenarios.items():
        trades = []
        for entry in entries:
            df = entry['df']
            idx = entry['entry_idx']

            if params['mode'] == 'fixed':
                tp = params['tp']
                sl = params['sl']
            elif params['mode'] == 'atr':
                atr = entry['atr_pct']
                if atr is None:
                    # ATR 없으면 기본값 사용
                    tp = 6.0
                    sl = -5.0
                else:
                    tp = max(params['tp_min'], min(atr * params['tp_mult'], params['tp_max']))
                    sl_val = max(params['sl_min'], min(atr * params['sl_mult'], params['sl_max']))
                    sl = -sl_val

            result = simulate_single_trade(df, idx, None, tp, sl)
            if result:
                trades.append({
                    'pnl': result['pnl'],
                    'reason': result['reason'],
                    'max_profit': result['max_profit'],
                    'date': entry['trade_date'],
                    'hour': entry['entry_hour'],
                    'weekday': entry['weekday'],
                    'atr': entry['atr_pct'],
                    'tp_used': tp,
                    'sl_used': sl,
                })

        if not trades:
            continue

        df_trades = pd.DataFrame(trades)
        net_pnls = df_trades['pnl'] - cost_pct
        wins = (net_pnls > 0).sum()
        total = len(df_trades)
        avg_net = net_pnls.mean()

        # 고정자본 수익률
        invest = 10_000_000 * 0.20
        total_profit = sum(invest * (p / 100) for p in net_pnls)
        return_pct = total_profit / 10_000_000 * 100

        # 청산 사유별
        tp_cnt = (df_trades['reason'] == '익절').sum()
        sl_cnt = (df_trades['reason'] == '손절').sum()
        eod_cnt = (df_trades['reason'] == '장마감').sum()

        results[name] = {
            'total': total, 'wins': wins, 'winrate': wins/total*100,
            'avg_net': avg_net, 'return_pct': return_pct,
            'tp_cnt': tp_cnt, 'sl_cnt': sl_cnt, 'eod_cnt': eod_cnt,
            'trades_df': df_trades,
        }

    # 결과 출력
    print(f'\n{"시나리오":<30} {"거래":>5} {"승률":>7} {"순평균":>8} {"수익률":>9} {"익절":>5} {"손절":>5} {"장마감":>5}')
    print('-' * 85)
    for name in scenarios:
        if name not in results:
            continue
        r = results[name]
        print(f'{name:<30} {r["total"]:>5} {r["winrate"]:>6.1f}% {r["avg_net"]:>+7.2f}% '
              f'{r["return_pct"]:>+8.1f}% {r["tp_cnt"]:>5} {r["sl_cnt"]:>5} {r["eod_cnt"]:>5}')

    # === Phase 3: 매수 시간대별 분석 ===
    print('\n\n=== Phase 3: 매수 시간대별 분석 ===')
    print('(고정 SL5/TP6 기준)')

    base_trades = results.get('고정 SL5/TP6 (현재)', {}).get('trades_df')
    if base_trades is not None and len(base_trades) > 0:
        print(f'\n{"시간대":<15} {"거래":>5} {"승률":>7} {"순평균":>8} {"익절":>5} {"손절":>5} {"장마감":>5}')
        print('-' * 60)
        for hour in sorted(base_trades['hour'].unique()):
            ht = base_trades[base_trades['hour'] == hour]
            net = ht['pnl'] - cost_pct
            wins = (net > 0).sum()
            tp_cnt = (ht['reason'] == '익절').sum()
            sl_cnt = (ht['reason'] == '손절').sum()
            eod_cnt = (ht['reason'] == '장마감').sum()
            print(f'  {hour}시         {len(ht):>5} {wins/len(ht)*100:>6.1f}% {net.mean():>+7.2f}% '
                  f'{tp_cnt:>5} {sl_cnt:>5} {eod_cnt:>5}')

    # === Phase 4: ATR 구간별 분석 ===
    print('\n\n=== Phase 4: ATR 구간별 분석 (고정 SL5/TP6 기준) ===')

    if base_trades is not None:
        atr_trades = base_trades[base_trades['atr'].notna()].copy()
        if len(atr_trades) > 0:
            bins = [(0, 3, 'ATR 0-3% (저변동)'),
                    (3, 5, 'ATR 3-5% (보통)'),
                    (5, 8, 'ATR 5-8% (고변동)'),
                    (8, 100, 'ATR 8%+ (초고변동)')]

            print(f'\n{"ATR 구간":<25} {"거래":>5} {"승률":>7} {"순평균":>8} {"익절":>5} {"손절":>5}')
            print('-' * 60)
            for lo, hi, label in bins:
                bt = atr_trades[(atr_trades['atr'] >= lo) & (atr_trades['atr'] < hi)]
                if len(bt) == 0:
                    continue
                net = bt['pnl'] - cost_pct
                wins = (net > 0).sum()
                tp_cnt = (bt['reason'] == '익절').sum()
                sl_cnt = (bt['reason'] == '손절').sum()
                print(f'{label:<25} {len(bt):>5} {wins/len(bt)*100:>6.1f}% {net.mean():>+7.2f}% '
                      f'{tp_cnt:>5} {sl_cnt:>5}')

            # ATR 동적 vs 고정 비교 (ATR 구간별)
            print('\n\n=== Phase 5: ATR 구간별 - 고정 vs 동적 비교 ===')
            atr_scenario = results.get('ATR(x2/x1, 2-10/2-6)', {}).get('trades_df')
            if atr_scenario is not None:
                atr_dynamic = atr_scenario[atr_scenario['atr'].notna()].copy()

                print(f'\n{"ATR 구간":<20} {"고정(5/6) 순평균":>16} {"동적ATR 순평균":>16} {"차이":>8}')
                print('-' * 65)
                for lo, hi, label in bins:
                    bt_fixed = atr_trades[(atr_trades['atr'] >= lo) & (atr_trades['atr'] < hi)]
                    bt_dyn = atr_dynamic[(atr_dynamic['atr'] >= lo) & (atr_dynamic['atr'] < hi)]
                    if len(bt_fixed) == 0:
                        continue
                    avg_fixed = (bt_fixed['pnl'] - cost_pct).mean()
                    avg_dyn = (bt_dyn['pnl'] - cost_pct).mean() if len(bt_dyn) > 0 else 0
                    diff = avg_dyn - avg_fixed
                    print(f'{label:<20} {avg_fixed:>+15.2f}% {avg_dyn:>+15.2f}% {diff:>+7.2f}%')

    # === Phase 6: 최대 도달 수익률 분석 (TP 효율성) ===
    print('\n\n=== Phase 6: 최대 도달 수익률 분석 ===')
    print('(진입 후 장중 최고 수익률이 어디까지 갔는지)')

    if base_trades is not None:
        mp = base_trades['max_profit']
        print(f'  평균 최고 도달: +{mp.mean():.2f}%')
        print(f'  중위 최고 도달: +{mp.median():.2f}%')
        for threshold in [3, 4, 5, 6, 8, 10]:
            pct = (mp >= threshold).sum() / len(mp) * 100
            print(f'  +{threshold}% 이상 도달: {(mp >= threshold).sum()}건 ({pct:.1f}%)')

    conn.close()
    print('\n\nDone!')


if __name__ == '__main__':
    main()
