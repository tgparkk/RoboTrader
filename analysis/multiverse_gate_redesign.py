"""
성과 게이트 재설계 멀티버스

비교 시나리오:
1. BASELINE: 게이트 없음
2. CURRENT: N=20, 45%, 가상추적 무제한 → 같은 deque
3. FIX_THR40: N=20, 40%, 가상추적 무제한 → 같은 deque
4. FIX_CAP7: N=20, 40%, 가상추적 7건/일 제한 → 같은 deque
5. FIX_SEP: N=20, 40%, 가상추적 7건/일 제한 → 별도 deque (해제 전용)
6. FIX_SEP45: N=20, 45%, 가상추적 7건/일 제한 → 별도 deque (해제 전용)

기존 multiverse_defense_grid.py의 데이터 수집 로직 재사용.
"""

import sys
sys.path.insert(0, 'D:/GIT/RoboTrader')

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from collections import deque
import warnings
warnings.filterwarnings('ignore')

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy
from simulate_with_screener import (
    get_trading_dates, get_prev_close_map, get_daily_metrics,
    apply_screener_filter, get_preload_stocks, check_circuit_breaker,
)

INITIAL_CAPITAL = 10_000_000
BUY_RATIO = 0.20
COST_PCT = 0.33
MAX_DAILY = 7


def collect_data():
    """기존 그리드 서치와 동일한 데이터 수집"""
    conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                            user=PG_USER, password=PG_PASSWORD)
    cur = conn.cursor()
    trading_dates = get_trading_dates(cur, '20250224', '20260403')
    strategy = PricePositionStrategy()

    print('데이터 수집 중...')
    daily_trades = {}
    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except:
            continue
        if day_idx % 50 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date})')
        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        if day_idx > 1:
            is_cb, _ = check_circuit_breaker(cur, prev_date, trading_dates[day_idx - 2], -3.0)
            if is_cb:
                continue
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue
        prev_close_map = get_prev_close_map(cur, trade_date, prev_date) if prev_date else {}
        screened = apply_screener_filter(
            daily_metrics, prev_close_map, top_n=60, min_price=5000, max_price=500000,
            min_amount=1_000_000_000, max_gap_pct=1.5,
            min_change_rate=0.5, max_change_rate=5.0, max_candidates=15)
        if prev_date:
            preload = get_preload_stocks(cur, prev_date, 30, 5000, 500000)
            screened = set(screened) | ((preload & set(daily_metrics.keys())) - set(screened))
        screened = list(screened)
        if not screened:
            continue
        day_results = []
        for stock_code in screened:
            try:
                cur.execute(
                    'SELECT idx,date,time,close,open,high,low,volume,amount '
                    'FROM minute_candles WHERE stock_code=%s AND trade_date=%s ORDER BY idx',
                    [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue
                df = pd.DataFrame(rows, columns=[
                    'idx', 'date', 'time', 'close', 'open', 'high', 'low', 'volume', 'amount'])
                day_open = daily_metrics[stock_code]['day_open']
                if day_open <= 0:
                    continue
                entry_idx = None
                for ci in range(10, len(df) - 10):
                    r = df.iloc[ci]
                    can, _ = strategy.check_entry_conditions(
                        stock_code, r['close'], day_open, str(r['time']), trade_date, weekday)
                    if not can:
                        continue
                    adv, _ = strategy.check_advanced_conditions(df, ci)
                    if not adv:
                        continue
                    entry_idx = ci
                    break
                if entry_idx is None:
                    continue
                result = strategy.simulate_trade(df, entry_idx)
                if result:
                    day_results.append(result)
            except:
                continue
        if day_results:
            day_results.sort(key=lambda x: str(x['entry_time']))
            daily_trades[trade_date] = day_results

    cur.close()
    conn.close()
    total = sum(len(v) for v in daily_trades.values())
    print(f'수집 완료: {len(daily_trades)}일, {total}건')
    return daily_trades


def run_baseline(daily_trades):
    """게이트 없음 (BASELINE)"""
    capital = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    min_cap = INITIAL_CAPITAL
    total_trades = 0
    total_wins = 0

    mar_start = None
    mar_end = None

    for td in sorted(daily_trades.keys()):
        if td >= '20260301' and mar_start is None:
            mar_start = capital

        day_list = daily_trades[td]
        day_start = capital
        holding = 0

        for t in day_list:
            if holding >= MAX_DAILY:
                continue
            holding += 1
            total_trades += 1
            inv = day_start * BUY_RATIO
            profit = inv * (t['pnl'] - COST_PCT) / 100
            capital += profit
            if t['result'] == 'WIN':
                total_wins += 1
            if capital > peak:
                peak = capital
            if capital < min_cap:
                min_cap = capital

        if td >= '20260301':
            mar_end = capital

    mdd = (peak - min_cap) / peak * 100 if peak > 0 else 0
    total_ret = (capital / INITIAL_CAPITAL - 1) * 100
    winrate = total_wins / total_trades * 100 if total_trades > 0 else 0
    mar_ret = ((mar_end / mar_start - 1) * 100) if mar_start and mar_end else 0

    return {
        'name': 'BASELINE (게이트 없음)',
        'capital': capital, 'total_ret': total_ret,
        'trades': total_trades, 'blocked': 0,
        'winrate': winrate, 'mdd': mdd,
        'mar_ret': mar_ret,
    }


def run_current(daily_trades, rolling_n, rolling_thr, shadow_cap=None, separate_deque=False):
    """
    게이트 시나리오 실행

    Args:
        shadow_cap: 일일 가상추적 최대 건수 (None=무제한)
        separate_deque: True이면 가상결과를 별도 deque로 관리 (실거래 deque 안 건드림)
    """
    capital = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    min_cap = INITIAL_CAPITAL

    # 실거래 deque
    real_deque = deque(maxlen=rolling_n)
    # 가상추적 deque (separate_deque=True일 때 사용)
    shadow_deque = deque(maxlen=rolling_n) if separate_deque else None

    total_trades = 0
    total_blocked = 0
    total_wins = 0
    blocked_pnls = []
    blocked_wins = 0

    # 게이트 차단일 수 추적
    block_days = 0
    was_blocked_yesterday = False

    mar_start = None
    mar_end = None

    for td in sorted(daily_trades.keys()):
        if td >= '20260301' and mar_start is None:
            mar_start = capital

        day_list = daily_trades[td]
        day_start = capital
        holding = 0
        day_shadow_count = 0
        day_blocked = False

        for t in day_list:
            is_win = t['result'] == 'WIN'

            # 동시 보유 한도 체크 (게이트 통과 후에도)
            if holding >= MAX_DAILY:
                # 한도 초과 시에도 실거래 deque에는 추가하지 않음 (실제로 안 샀으니)
                continue

            # 롤링 승률 체크
            blocked = False
            if separate_deque:
                # 별도 deque: 실거래 deque로 차단 여부 판단
                # 해제: 가상 deque 승률이 임계값 이상이면 해제
                if len(real_deque) >= rolling_n:
                    real_wr = sum(real_deque) / len(real_deque)
                    if real_wr < rolling_thr:
                        # 차단 상태 → 가상 deque로 해제 조건 확인
                        if len(shadow_deque) >= rolling_n:
                            shadow_wr = sum(shadow_deque) / len(shadow_deque)
                            if shadow_wr >= rolling_thr:
                                blocked = False  # 가상이 회복 → 해제
                            else:
                                blocked = True
                        else:
                            blocked = True  # 가상 데이터 부족 → 계속 차단
            else:
                # 같은 deque: 기존 방식
                if len(real_deque) >= rolling_n:
                    wr = sum(real_deque) / len(real_deque)
                    if wr < rolling_thr:
                        blocked = True

            if blocked:
                day_blocked = True
                total_blocked += 1
                blocked_pnls.append(t['pnl'])
                if is_win:
                    blocked_wins += 1

                if separate_deque:
                    # 별도 deque: 가상 결과는 shadow_deque에만
                    if shadow_cap is None or day_shadow_count < shadow_cap:
                        shadow_deque.append(1 if is_win else 0)
                        day_shadow_count += 1
                else:
                    # 같은 deque: 가상 결과도 real_deque에
                    if shadow_cap is None or day_shadow_count < shadow_cap:
                        real_deque.append(1 if is_win else 0)
                        day_shadow_count += 1

                continue

            # 실제 매수 실행
            holding += 1
            total_trades += 1
            inv = day_start * BUY_RATIO
            profit = inv * (t['pnl'] - COST_PCT) / 100
            capital += profit

            if is_win:
                total_wins += 1

            real_deque.append(1 if is_win else 0)

            if capital > peak:
                peak = capital
            if capital < min_cap:
                min_cap = capital

        # 차단일 수 추적
        if day_blocked:
            if was_blocked_yesterday:
                block_days += 1
            else:
                block_days = 1
            was_blocked_yesterday = True
        else:
            was_blocked_yesterday = False
            block_days = 0

        if td >= '20260301':
            mar_end = capital

    mdd = (peak - min_cap) / peak * 100 if peak > 0 else 0
    total_ret = (capital / INITIAL_CAPITAL - 1) * 100
    winrate = total_wins / total_trades * 100 if total_trades > 0 else 0
    mar_ret = ((mar_end / mar_start - 1) * 100) if mar_start and mar_end else 0
    blocked_wr = blocked_wins / len(blocked_pnls) * 100 if blocked_pnls else 0
    blocked_avg = np.mean(blocked_pnls) if blocked_pnls else 0

    return {
        'capital': capital, 'total_ret': total_ret,
        'trades': total_trades, 'blocked': total_blocked,
        'winrate': winrate, 'mdd': mdd,
        'mar_ret': mar_ret,
        'blocked_wr': blocked_wr, 'blocked_avg': blocked_avg,
    }


def main():
    daily_trades = collect_data()

    scenarios = []

    # 1. BASELINE
    r = run_baseline(daily_trades)
    scenarios.append(r)
    baseline_ret = r['total_ret']

    # 2. CURRENT: N=20, 45%, 무제한, 같은 deque
    r = run_current(daily_trades, 20, 0.45, shadow_cap=None, separate_deque=False)
    r['name'] = 'CURRENT (N20/45%/무제한/같은deque)'
    scenarios.append(r)

    # 3. FIX_THR40: N=20, 40%, 무제한, 같은 deque
    r = run_current(daily_trades, 20, 0.40, shadow_cap=None, separate_deque=False)
    r['name'] = 'FIX_THR40 (N20/40%/무제한/같은deque)'
    scenarios.append(r)

    # 4. FIX_CAP7: N=20, 40%, 7건제한, 같은 deque
    r = run_current(daily_trades, 20, 0.40, shadow_cap=7, separate_deque=False)
    r['name'] = 'FIX_CAP7 (N20/40%/7건/같은deque)'
    scenarios.append(r)

    # 5. FIX_SEP: N=20, 40%, 7건제한, 별도 deque
    r = run_current(daily_trades, 20, 0.40, shadow_cap=7, separate_deque=True)
    r['name'] = 'FIX_SEP (N20/40%/7건/별도deque)'
    scenarios.append(r)

    # 6. FIX_SEP45: N=20, 45%, 7건제한, 별도 deque
    r = run_current(daily_trades, 20, 0.45, shadow_cap=7, separate_deque=True)
    r['name'] = 'FIX_SEP45 (N20/45%/7건/별도deque)'
    scenarios.append(r)

    # 7. 추가: N=25, 40%, 7건제한, 별도 deque
    r = run_current(daily_trades, 25, 0.40, shadow_cap=7, separate_deque=True)
    r['name'] = 'N25_SEP (N25/40%/7건/별도deque)'
    scenarios.append(r)

    # 8. 추가: N=20, 40%, 3건제한, 별도 deque
    r = run_current(daily_trades, 20, 0.40, shadow_cap=3, separate_deque=True)
    r['name'] = 'CAP3_SEP (N20/40%/3건/별도deque)'
    scenarios.append(r)

    # 9. 추가: N=20, 45%, 무제한, 별도 deque
    r = run_current(daily_trades, 20, 0.45, shadow_cap=None, separate_deque=True)
    r['name'] = 'SEP_UNLIM (N20/45%/무제한/별도deque)'
    scenarios.append(r)

    # 결과 출력
    print('\n' + '=' * 140)
    print('성과 게이트 재설계 멀티버스 결과')
    print('=' * 140)
    print(f'{"#":>2} {"시나리오":<40} {"자본(만)":>10} {"총수익":>10} {"MDD":>6} '
          f'{"거래":>6} {"차단":>6} {"승률":>6} {"3월~":>8} '
          f'{"차단WR":>7} {"차단Avg":>8} {"vs BL":>8}')
    print('-' * 140)

    for i, r in enumerate(scenarios):
        diff = r['total_ret'] - baseline_ret
        blocked_wr = r.get('blocked_wr', 0)
        blocked_avg = r.get('blocked_avg', 0)
        print(f'{i+1:>2} {r["name"]:<40} {r["capital"]/10000:>9,.0f} '
              f'{r["total_ret"]:>+9.1f}% {r["mdd"]:>5.1f}% '
              f'{r["trades"]:>6} {r["blocked"]:>6} '
              f'{r["winrate"]:>5.1f}% {r["mar_ret"]:>+7.1f}% '
              f'{blocked_wr:>6.1f}% {blocked_avg:>+7.2f}% ({diff:>+.0f}pp)')

    # MDD 기준 정렬
    print('\n' + '=' * 140)
    print('MDD 낮은 순')
    print('=' * 140)
    sorted_by_mdd = sorted(scenarios, key=lambda x: x['mdd'])
    for i, r in enumerate(sorted_by_mdd):
        diff = r['total_ret'] - baseline_ret
        print(f'{i+1:>2} {r["name"]:<40} '
              f'총수익:{r["total_ret"]:>+8.1f}% MDD:{r["mdd"]:>5.1f}% '
              f'거래:{r["trades"]:>5} 차단:{r["blocked"]:>5} '
              f'3월~:{r["mar_ret"]:>+7.1f}% ({diff:>+.0f}pp)')

    # 수익/MDD 효율
    print('\n' + '=' * 140)
    print('수익/MDD 효율')
    print('=' * 140)
    for r in scenarios:
        r['efficiency'] = r['total_ret'] / r['mdd'] if r['mdd'] > 0 else 0
    sorted_by_eff = sorted(scenarios, key=lambda x: x['efficiency'], reverse=True)
    for i, r in enumerate(sorted_by_eff):
        print(f'{i+1:>2} {r["name"]:<40} '
              f'효율:{r["efficiency"]:>6.1f}x 총수익:{r["total_ret"]:>+8.1f}% '
              f'MDD:{r["mdd"]:>5.1f}%')

    print('\n완료!')


if __name__ == '__main__':
    main()
