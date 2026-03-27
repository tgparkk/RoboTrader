"""
멀티버스 시뮬레이션: 장중 시장 방향 연동 동적 손절

장중 시장 방향(스크리너 종목 평균 등락)에 따라 SL을 동적 조절.
KOSPI 분봉 없으므로 스크리너 전체 종목의 평균 시가대비 변동을 시장 프록시로 사용.

테스트 파라미터:
- 시장 하락 임계값: -0.3%, -0.5%, -0.7%, -1.0%
- SL 축소 수준: -2%, -3%
- 강제 청산 임계값: -1.0%, -1.5%, -2.0%
- 회복 시 SL 원복 조건
- max_positions 조합 (3, 5)
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
import argparse
import sys

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy
from simulate_with_screener import (
    get_trading_dates, get_prev_close_map, get_daily_metrics,
    apply_screener_filter, apply_daily_limit, calc_capital_returns,
)


def compute_market_proxy(cur, trade_date, screened_stocks, daily_metrics):
    """
    스크리너 종목들의 분봉 데이터로 장중 시장 방향 프록시 계산.
    각 분봉 시점에서 전 종목의 평균 시가대비 등락률 반환.

    Returns: dict[time_str] -> market_pct (평균 시가대비 %)
    """
    all_pcts = defaultdict(list)

    for stock_code in screened_stocks:
        day_open = daily_metrics.get(stock_code, {}).get('day_open', 0)
        if day_open <= 0:
            continue

        cur.execute('''
            SELECT time, close FROM minute_candles
            WHERE stock_code = %s AND trade_date = %s
            ORDER BY idx
        ''', [stock_code, trade_date])

        for time_str, close in cur.fetchall():
            if close and close > 0:
                pct = (float(close) / day_open - 1) * 100
                t = str(time_str).replace(':', '').ljust(6, '0')[:6]
                all_pcts[t].append(pct)

    # 각 시점의 중앙값 (평균보다 이상치에 강건)
    market_proxy = {}
    for t, pcts in all_pcts.items():
        if len(pcts) >= 3:
            market_proxy[t] = np.median(pcts)

    return market_proxy


def simulate_dynamic_sl_trade(df, entry_idx, market_proxy, strategy_params,
                               base_sl=-5.0, base_tp=6.0):
    """동적 SL로 거래 시뮬레이션"""
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']
    if entry_price <= 0:
        return None

    # 전략 파라미터
    tighten_threshold = strategy_params.get('tighten_threshold', -0.5)
    tighten_sl = strategy_params.get('tighten_sl', -3.0)
    force_close_threshold = strategy_params.get('force_close_threshold', None)
    recovery_pct = strategy_params.get('recovery_pct', None)

    max_profit_pct = 0.0
    current_sl = base_sl
    sl_tightened = False

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        high = float(row['high'])
        low = float(row['low'])
        close = float(row['close'])
        row_time = str(row['time']).replace(':', '').ljust(6, '0')[:6]

        # 고점 추적
        high_pnl = (high / entry_price - 1) * 100
        if high_pnl > max_profit_pct:
            max_profit_pct = high_pnl

        # 시장 프록시 확인
        mkt = market_proxy.get(row_time, 0.0)

        # 동적 SL 조절
        if force_close_threshold and mkt <= force_close_threshold:
            # 강제 청산
            close_pnl = (close / entry_price - 1) * 100
            return _result(close_pnl, '강제청산', entry_time, row['time'],
                           entry_price, i - entry_idx, max_profit_pct, mkt)

        if mkt <= tighten_threshold:
            current_sl = tighten_sl
            sl_tightened = True
        elif recovery_pct and sl_tightened and mkt >= recovery_pct:
            current_sl = base_sl
            sl_tightened = False

        # 익절 체크
        if high_pnl >= base_tp:
            return _result(base_tp, '익절', entry_time, row['time'],
                           entry_price, i - entry_idx, max_profit_pct, mkt)

        # 손절 체크 (동적 SL 적용)
        low_pnl = (low / entry_price - 1) * 100
        if low_pnl <= current_sl:
            exit_reason = '동적손절' if sl_tightened else '손절'
            return _result(current_sl, exit_reason, entry_time, row['time'],
                           entry_price, i - entry_idx, max_profit_pct, mkt)

    # 장마감
    last = df.iloc[-1]
    last_pnl = (float(last['close']) / entry_price - 1) * 100
    return _result(last_pnl, '장마감', entry_time, last['time'],
                   entry_price, len(df) - 1 - entry_idx, max_profit_pct, 0.0)


def _result(pnl, reason, entry_time, exit_time, entry_price, holding, max_profit, mkt_at_exit):
    return {
        'result': 'WIN' if pnl > 0 else 'LOSS',
        'pnl': pnl,
        'exit_reason': reason,
        'entry_time': entry_time,
        'exit_time': exit_time,
        'entry_price': entry_price,
        'holding_candles': holding,
        'max_profit_pct': round(max_profit, 2),
        'mkt_at_exit': round(mkt_at_exit, 2),
    }


def run_multiverse(start_date='20250224', end_date=None, verbose=True, cost_pct=0.33):
    """장중 지수 연동 동적 손절 멀티버스"""

    strategies = [
        # 현행 (기준선)
        ('현행(SL5/TP6)', {}),

        # === 시장 하락 시 SL 축소만 ===
        ('시장-0.3%→SL3%', {'tighten_threshold': -0.3, 'tighten_sl': -3.0}),
        ('시장-0.5%→SL3%', {'tighten_threshold': -0.5, 'tighten_sl': -3.0}),
        ('시장-0.7%→SL3%', {'tighten_threshold': -0.7, 'tighten_sl': -3.0}),
        ('시장-1.0%→SL3%', {'tighten_threshold': -1.0, 'tighten_sl': -3.0}),
        ('시장-0.3%→SL2%', {'tighten_threshold': -0.3, 'tighten_sl': -2.0}),
        ('시장-0.5%→SL2%', {'tighten_threshold': -0.5, 'tighten_sl': -2.0}),
        ('시장-0.7%→SL2%', {'tighten_threshold': -0.7, 'tighten_sl': -2.0}),
        ('시장-1.0%→SL2%', {'tighten_threshold': -1.0, 'tighten_sl': -2.0}),

        # === SL 축소 + 회복 시 원복 ===
        ('시장-0.5%→SL3%,+0.5복', {'tighten_threshold': -0.5, 'tighten_sl': -3.0, 'recovery_pct': 0.5}),
        ('시장-0.5%→SL3%,+1.0복', {'tighten_threshold': -0.5, 'tighten_sl': -3.0, 'recovery_pct': 1.0}),
        ('시장-0.5%→SL2%,+0.5복', {'tighten_threshold': -0.5, 'tighten_sl': -2.0, 'recovery_pct': 0.5}),

        # === 강제 청산 포함 ===
        ('시장-0.5%→SL3%,-1.5%청산', {'tighten_threshold': -0.5, 'tighten_sl': -3.0, 'force_close_threshold': -1.5}),
        ('시장-0.5%→SL3%,-2.0%청산', {'tighten_threshold': -0.5, 'tighten_sl': -3.0, 'force_close_threshold': -2.0}),
        ('시장-0.5%→SL2%,-1.0%청산', {'tighten_threshold': -0.5, 'tighten_sl': -2.0, 'force_close_threshold': -1.0}),
        ('시장-0.5%→SL2%,-1.5%청산', {'tighten_threshold': -0.5, 'tighten_sl': -2.0, 'force_close_threshold': -1.5}),
        ('시장-1.0%→SL3%,-1.5%청산', {'tighten_threshold': -1.0, 'tighten_sl': -3.0, 'force_close_threshold': -1.5}),
        ('시장-1.0%→SL2%,-1.5%청산', {'tighten_threshold': -1.0, 'tighten_sl': -2.0, 'force_close_threshold': -1.5}),

        # === 단계적 (2단계) ===
        # -0.5%에서 SL3%, -1.0%에서 강제청산
        ('2단계:-0.5%SL3%,-1.0%청산', {'tighten_threshold': -0.5, 'tighten_sl': -3.0, 'force_close_threshold': -1.0}),
        # -0.5%에서 SL3%, -1.5%에서 강제청산
        ('2단계:-0.5%SL3%,-1.5%청산', {'tighten_threshold': -0.5, 'tighten_sl': -3.0, 'force_close_threshold': -1.5}),
        # -0.3%에서 SL3%, -1.0%에서 강제청산
        ('2단계:-0.3%SL3%,-1.0%청산', {'tighten_threshold': -0.3, 'tighten_sl': -3.0, 'force_close_threshold': -1.0}),
    ]

    # max_positions 변형 추가 (3종목 제한)
    strategies_with_pos = []
    for label, params in strategies:
        strategies_with_pos.append((label + '/5종목', params, 5))
    # 상위 유력 전략만 3종목으로도 테스트
    for label, params in strategies[:9]:  # 현행 + SL축소 8개
        strategies_with_pos.append((label + '/3종목', params, 3))

    strategy_obj = PricePositionStrategy()
    info = strategy_obj.get_strategy_info()

    print('=' * 100)
    print('멀티버스 시뮬레이션: 장중 시장 방향 연동 동적 손절')
    print('=' * 100)
    print(f"진입: 시가 대비 {info['entry_conditions']['pct_from_open']}, "
          f"{info['entry_conditions']['time_range']}")
    print(f"기본: 손절 -5.0%, 익절 +6.0%")
    print(f"시장 프록시: 스크리너 종목 중앙값 (KOSPI 분봉 대체)")
    print(f"비교 전략: {len(strategies_with_pos)}개")
    print(f"기간: {start_date} ~ {end_date or '전체'}")
    print('=' * 100)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    all_results = {s[0]: [] for s in strategies_with_pos}

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

        # 시장 프록시 계산 (당일 전 종목)
        market_proxy = compute_market_proxy(cur, trade_date, screened, daily_metrics)

        # 각 종목 처리
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

                    for label, params, max_pos in strategies_with_pos:
                        result = simulate_dynamic_sl_trade(
                            df, candle_idx, market_proxy, params,
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
    print('#' * 100)
    print('#  멀티버스 결과: 장중 시장 연동 동적 손절 (동시보유 제한 적용)')
    print('#' * 100)

    summary = []
    for label, params, max_pos in strategies_with_pos:
        trades = all_results[label]
        if not trades:
            continue

        trades_df = pd.DataFrame(trades)
        limited_df = apply_daily_limit(trades_df, max_pos)

        if len(limited_df) == 0:
            continue

        total = len(limited_df)
        wins = (limited_df['result'] == 'WIN').sum()
        winrate = wins / total * 100
        avg_pnl = limited_df['pnl'].mean()
        cap = calc_capital_returns(limited_df, cost_pct=cost_pct)
        cap_ret = cap['total_return_pct']

        reasons = limited_df['exit_reason'].value_counts().to_dict()
        avg_max_profit = limited_df['max_profit_pct'].mean()

        summary.append({
            'label': label,
            'total': total,
            'wins': wins,
            'winrate': winrate,
            'avg_pnl': avg_pnl,
            'cap_ret': cap_ret,
            'reasons': reasons,
            'avg_max': avg_max_profit,
        })

    summary.sort(key=lambda x: x['avg_pnl'], reverse=True)
    baseline = next((s for s in summary if '현행' in s['label'] and '5종목' in s['label']), summary[0])

    print(f'\n{"전략":>28} {"거래":>5} {"승률":>6} {"평균":>7} {"원금수익":>9} {"vs현행":>8}  청산사유')
    print('-' * 120)
    for s in summary:
        diff = s['avg_pnl'] - baseline['avg_pnl']
        r = s['reasons']
        reason_str = ' '.join(f"{k}{v}" for k, v in sorted(r.items()))
        marker = ' <-- 현행' if s['label'] == baseline['label'] else ''
        print(f"{s['label']:>28} {s['total']:>5} {s['winrate']:>5.1f}% {s['avg_pnl']:>+6.2f}% "
              f"{s['cap_ret']:>+8.1f}% {diff:>+7.2f}%p  {reason_str}{marker}")

    # 카테고리별 최적
    print('\n')
    print('=' * 100)
    print('카테고리별 최적')
    print('=' * 100)

    categories = {
        'SL축소만(5종목)': [s for s in summary if '→SL' in s['label'] and '청산' not in s['label'] and '복' not in s['label'] and '5종목' in s['label']],
        'SL축소+회복(5종목)': [s for s in summary if '복' in s['label'] and '5종목' in s['label']],
        '강제청산포함(5종목)': [s for s in summary if '청산' in s['label'] and '5종목' in s['label']],
        '3종목제한': [s for s in summary if '3종목' in s['label']],
    }

    for cat, items in categories.items():
        if not items:
            continue
        best = max(items, key=lambda x: x['avg_pnl'])
        diff = best['avg_pnl'] - baseline['avg_pnl']
        print(f'\n[{cat}] 최적: {best["label"]}')
        print(f'  평균 {best["avg_pnl"]:+.2f}% (현행 대비 {diff:+.2f}%p), '
              f'승률 {best["winrate"]:.1f}%, 원금수익률 {best["cap_ret"]:+.1f}%')

    print(f'\n[현행] {baseline["label"]}')
    print(f'  평균 {baseline["avg_pnl"]:+.2f}%, 승률 {baseline["winrate"]:.1f}%, '
          f'원금수익률 {baseline["cap_ret"]:+.1f}%')

    print('\nDone!')


def main():
    parser = argparse.ArgumentParser(description='멀티버스: 장중 지수 연동 동적 손절')
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
