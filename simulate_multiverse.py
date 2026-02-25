"""
분할 익절 멀티버스 시뮬레이션 -최적 파라미터 탐색

1단계: 동일 진입 시점 + 캔들 데이터를 1회만 DB에서 로드 (캐싱)
2단계: 모든 파라미터 조합에 대해 메모리 내 exit 시뮬만 반복 (초고속)

탐색 대상:
  - TP1: 1차 익절 기준 (%)
  - sell_ratio: 1차 매도 비율
  - TP2: 2차 익절 기준 (%)
  - remaining_sl: 잔여 손절 기준 (%)
  + Original (분할 없음) 포함
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
import argparse
import time as time_module
import itertools

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


# ===== DB 헬퍼 (simulate_with_screener.py 재사용) =====

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
          AND idx = (SELECT MAX(idx) FROM minute_candles mc2
                     WHERE mc2.stock_code = minute_candles.stock_code AND mc2.trade_date = %s)
    ''', [prev_date, prev_date])
    return {row[0]: row[1] for row in cur.fetchall()}


def get_daily_metrics(cur, trade_date):
    cur.execute('''
        SELECT stock_code,
               MIN(CASE WHEN idx = (
                   SELECT MIN(idx) FROM minute_candles mc2
                   WHERE mc2.stock_code = minute_candles.stock_code AND mc2.trade_date = %s
               ) THEN open END) as day_open,
               SUM(amount) as daily_amount
        FROM minute_candles WHERE trade_date = %s GROUP BY stock_code
    ''', [trade_date, trade_date])
    return {row[0]: {'day_open': row[1] or 0, 'daily_amount': row[2] or 0}
            for row in cur.fetchall()}


def apply_screener_filter(daily_metrics, prev_close_map,
                          top_n=60, min_price=5000, max_price=500000,
                          min_amount=1_000_000_000, max_gap_pct=3.0):
    ranked = sorted(daily_metrics.items(), key=lambda x: x[1]['daily_amount'], reverse=True)[:top_n]
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
            if abs(day_open / prev_close - 1) * 100 > max_gap_pct:
                continue
        passed.add(stock_code)
    return passed


def apply_daily_limit(entries, max_daily):
    """동시보유 제한 적용 -entry 리스트 기반"""
    from collections import defaultdict
    by_date = defaultdict(list)
    for e in entries:
        by_date[e['date']].append(e)

    accepted_indices = []
    for date in sorted(by_date.keys()):
        day_entries = sorted(by_date[date], key=lambda x: x['entry_time'])
        holding = []
        for entry in day_entries:
            et = str(entry['entry_time']).zfill(6)
            active = sum(1 for _, xt in holding if xt > et)
            if active < max_daily:
                holding.append((et, str(entry['exit_time_orig']).zfill(6)))
                accepted_indices.append(entry['idx'])
    return set(accepted_indices)


# ===== 1단계: 진입 시점 + 캔들 데이터 캐싱 =====

def collect_entries(start_date, end_date, max_daily=5, verbose=True):
    """모든 진입 시점과 이후 캔들을 수집"""
    strategy = PricePositionStrategy(config={'stop_loss_pct': -4.0, 'take_profit_pct': 5.0})

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'총 거래일: {len(trading_dates)}일')

    entries = []  # [{date, stock_code, weekday, entry_price, entry_time, candles: [...], exit_time_orig}]

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 수집 중... 진입 {len(entries)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = get_prev_close_map(cur, trade_date, prev_date) if prev_date else {}

        screened = apply_screener_filter(daily_metrics, prev_close_map)
        if not screened:
            continue

        strategy.reset_daily_trades(trade_date)

        for stock_code in screened:
            try:
                cur.execute('''
                    SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s ORDER BY idx
                ''', [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue

                columns = ['idx', 'date', 'time', 'close', 'open', 'high', 'low',
                           'volume', 'amount', 'datetime']
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
                        stock_code=stock_code, current_price=current_price,
                        day_open=day_open, current_time=current_time,
                        trade_date=trade_date, weekday=weekday,
                    )
                    if not can_enter:
                        continue

                    adv_ok, _ = strategy.check_advanced_conditions(df=df, candle_idx=candle_idx)
                    if not adv_ok:
                        continue

                    # 진입 확정 -이후 캔들 데이터를 numpy 배열로 캐싱
                    if candle_idx + 1 >= len(df) - 5:
                        continue

                    entry_price = df.iloc[candle_idx + 1]['open']
                    entry_time = df.iloc[candle_idx + 1]['time']
                    if entry_price <= 0:
                        continue

                    # 진입 이후 모든 캔들 (high, low, close, time)
                    remaining = df.iloc[candle_idx + 1:]
                    candles = remaining[['high', 'low', 'close', 'time']].values  # numpy array

                    # Original 기준 exit_time (동시보유 제한용)
                    orig_result = strategy.simulate_trade(df, candle_idx)
                    exit_time_orig = orig_result['exit_time'] if orig_result else remaining.iloc[-1]['time']

                    pct_from_open = (current_price / day_open - 1) * 100

                    entries.append({
                        'idx': len(entries),
                        'date': trade_date,
                        'stock_code': stock_code,
                        'weekday': weekday,
                        'pct_from_open': pct_from_open,
                        'entry_price': entry_price,
                        'entry_time': entry_time,
                        'exit_time_orig': exit_time_orig,
                        'candles': candles,  # numpy: [[high, low, close, time], ...]
                    })

                    strategy.record_trade(stock_code, trade_date)
                    traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'진입 수집 완료: {len(entries)}건')
    return entries


# ===== 2단계: 파라미터별 exit 시뮬 (초고속) =====

def simulate_exits_original(entries, stop_loss=-4.0, take_profit=5.0):
    """Original 전략 시뮬"""
    results = []
    for e in entries:
        entry_price = e['entry_price']
        candles = e['candles']
        pnl = None

        for c in candles:
            high, low, close, ctime = c[0], c[1], c[2], c[3]
            high_pnl = (high / entry_price - 1) * 100
            low_pnl = (low / entry_price - 1) * 100

            if high_pnl >= take_profit:
                pnl = take_profit
                reason = '익절'
                break
            if low_pnl <= stop_loss:
                pnl = stop_loss
                reason = '손절'
                break

        if pnl is None:
            last_close = candles[-1][2]
            pnl = (last_close / entry_price - 1) * 100
            reason = '장마감'

        results.append({
            'idx': e['idx'],
            'pnl': pnl,
            'result': 'WIN' if pnl > 0 else 'LOSS',
            'exit_reason': reason,
        })
    return results


def simulate_exits_partial(entries, stop_loss=-4.0, tp1=3.0, sell_ratio=0.3,
                           tp2=7.0, remaining_sl=0.0):
    """분할 익절 시뮬"""
    results = []
    for e in entries:
        entry_price = e['entry_price']
        candles = e['candles']
        stage = 0
        tp1_pnl = None
        pnl = None
        reason = None

        for c in candles:
            high, low, close, ctime = c[0], c[1], c[2], c[3]
            high_pnl = (high / entry_price - 1) * 100
            low_pnl = (low / entry_price - 1) * 100

            if stage == 0:
                # TP2 직행
                if high_pnl >= tp2:
                    pnl = tp2
                    reason = 'TP2직행'
                    break
                # TP1
                if high_pnl >= tp1:
                    tp1_pnl = tp1
                    stage = 1
                    # 같은 캔들에서 잔여 손절
                    if low_pnl <= remaining_sl:
                        pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * remaining_sl
                        reason = '1차+잔여손절'
                        break
                    continue
                # 기본 손절
                if low_pnl <= stop_loss:
                    pnl = stop_loss
                    reason = '손절'
                    break
            elif stage == 1:
                # TP2
                if high_pnl >= tp2:
                    pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * tp2
                    reason = '2차익절'
                    break
                # 잔여 손절
                if low_pnl <= remaining_sl:
                    pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * remaining_sl
                    reason = '잔여손절'
                    break

        if pnl is None:
            last_close = candles[-1][2]
            close_pnl = (last_close / entry_price - 1) * 100
            if stage == 0:
                pnl = close_pnl
            else:
                pnl = sell_ratio * tp1_pnl + (1 - sell_ratio) * close_pnl
            reason = '장마감'

        results.append({
            'idx': e['idx'],
            'pnl': pnl,
            'result': 'WIN' if pnl > 0 else 'LOSS',
            'exit_reason': reason,
        })
    return results


def calc_stats(results, accepted_set=None):
    """통계 계산"""
    if accepted_set is not None:
        results = [r for r in results if r['idx'] in accepted_set]
    if not results:
        return None

    pnls = [r['pnl'] for r in results]
    wins = sum(1 for r in results if r['result'] == 'WIN')
    total = len(results)
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / total
    win_pnls = [r['pnl'] for r in results if r['result'] == 'WIN']
    loss_pnls = [r['pnl'] for r in results if r['result'] == 'LOSS']
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 99

    return {
        'total': total, 'wins': wins, 'losses': total - wins,
        'winrate': wins / total * 100,
        'total_pnl': total_pnl, 'avg_pnl': avg_pnl,
        'avg_win': avg_win, 'avg_loss': avg_loss, 'pl_ratio': pl_ratio,
    }


# ===== 메인 =====

def run_multiverse(start_date, end_date, max_daily=5):
    print('=' * 80)
    print('멀티버스 시뮬레이션 -분할 익절 최적 파라미터 탐색')
    print('=' * 80)

    t0 = time_module.time()

    # 1단계: 진입 시점 수집
    print('\n[1단계] 진입 시점 + 캔들 데이터 수집 (DB 1회 조회)')
    entries = collect_entries(start_date, end_date, max_daily=max_daily)

    if not entries:
        print('진입 없음')
        return

    # 동시보유 제한 적용 (Original 기준 exit_time으로)
    accepted = apply_daily_limit(entries, max_daily)
    print(f'동시보유 {max_daily}종목 제한 후: {len(accepted)}건')

    t1 = time_module.time()
    print(f'수집 소요: {t1 - t0:.1f}초')

    # 2단계: 파라미터 그리드 탐색
    print(f'\n[2단계] 파라미터 그리드 탐색')

    # 파라미터 범위
    tp1_values = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    sell_ratio_values = [0.2, 0.3, 0.4, 0.5, 0.6]
    tp2_values = [4.0, 5.0, 6.0, 7.0, 8.0, 10.0]
    remaining_sl_values = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]

    # 유효한 조합만 필터 (TP1 < TP2, remaining_sl < TP2)
    combos = []
    for tp1, sr, tp2, rsl in itertools.product(
        tp1_values, sell_ratio_values, tp2_values, remaining_sl_values
    ):
        if tp1 >= tp2:  # TP1은 TP2보다 낮아야
            continue
        if rsl >= tp2:  # 잔여 손절은 TP2보다 낮아야
            continue
        if rsl >= tp1:  # 잔여 손절은 TP1보다 낮아야 의미있음
            continue
        combos.append((tp1, sr, tp2, rsl))

    print(f'유효 조합: {len(combos)}개')

    # Original 기준
    orig_results = simulate_exits_original(entries)
    orig_stats = calc_stats(orig_results, accepted)

    # 그리드 탐색
    all_results = []
    for i, (tp1, sr, tp2, rsl) in enumerate(combos):
        if i % 200 == 0:
            print(f'  {i}/{len(combos)} 조합 처리 중...')

        part_results = simulate_exits_partial(
            entries, stop_loss=-4.0, tp1=tp1, sell_ratio=sr,
            tp2=tp2, remaining_sl=rsl,
        )
        stats = calc_stats(part_results, accepted)
        if stats:
            all_results.append({
                'tp1': tp1, 'sell_ratio': sr, 'tp2': tp2, 'remaining_sl': rsl,
                **stats,
            })

    t2 = time_module.time()
    print(f'탐색 소요: {t2 - t1:.1f}초 (총 {t2 - t0:.1f}초)')

    if not all_results:
        print('결과 없음')
        return

    results_df = pd.DataFrame(all_results)

    # ===== 결과 출력 =====

    print('\n' + '=' * 80)
    print('Original 기준선')
    print('=' * 80)
    print(f"  거래: {orig_stats['total']}건, 승률: {orig_stats['winrate']:.1f}%, "
          f"총 수익률: {orig_stats['total_pnl']:+.1f}%, "
          f"평균: {orig_stats['avg_pnl']:+.2f}%, 손익비: {orig_stats['pl_ratio']:.2f}:1")

    # 총 수익률 기준 TOP 20
    print('\n' + '=' * 80)
    print('총 수익률 TOP 20')
    print('=' * 80)
    top_pnl = results_df.nlargest(20, 'total_pnl')
    print(f"\n{'#':>3} {'TP1':>5} {'매도%':>5} {'TP2':>5} {'잔SL':>5} "
          f"{'거래':>5} {'승률':>6} {'총수익':>9} {'평균':>7} {'손익비':>6} {'vs Orig':>9}")
    print('-' * 80)
    for rank, (_, r) in enumerate(top_pnl.iterrows(), 1):
        diff = r['total_pnl'] - orig_stats['total_pnl']
        print(f"{rank:>3} {r['tp1']:>5.1f} {r['sell_ratio']:>5.0%} {r['tp2']:>5.1f} {r['remaining_sl']:>+5.1f} "
              f"{r['total']:>5.0f} {r['winrate']:>5.1f}% {r['total_pnl']:>+8.1f}% "
              f"{r['avg_pnl']:>+6.2f}% {r['pl_ratio']:>5.2f}:1 {diff:>+8.1f}%")

    # 평균 수익률 기준 TOP 20
    print('\n' + '=' * 80)
    print('평균 수익률 TOP 20')
    print('=' * 80)
    top_avg = results_df.nlargest(20, 'avg_pnl')
    print(f"\n{'#':>3} {'TP1':>5} {'매도%':>5} {'TP2':>5} {'잔SL':>5} "
          f"{'거래':>5} {'승률':>6} {'총수익':>9} {'평균':>7} {'손익비':>6} {'vs Orig':>9}")
    print('-' * 80)
    for rank, (_, r) in enumerate(top_avg.iterrows(), 1):
        diff = r['total_pnl'] - orig_stats['total_pnl']
        print(f"{rank:>3} {r['tp1']:>5.1f} {r['sell_ratio']:>5.0%} {r['tp2']:>5.1f} {r['remaining_sl']:>+5.1f} "
              f"{r['total']:>5.0f} {r['winrate']:>5.1f}% {r['total_pnl']:>+8.1f}% "
              f"{r['avg_pnl']:>+6.2f}% {r['pl_ratio']:>5.2f}:1 {diff:>+8.1f}%")

    # 승률 기준 TOP 20
    print('\n' + '=' * 80)
    print('승률 TOP 20 (총 수익률 > Original의 90%)')
    print('=' * 80)
    viable = results_df[results_df['total_pnl'] >= orig_stats['total_pnl'] * 0.9]
    if len(viable) > 0:
        top_wr = viable.nlargest(20, 'winrate')
        print(f"\n{'#':>3} {'TP1':>5} {'매도%':>5} {'TP2':>5} {'잔SL':>5} "
              f"{'거래':>5} {'승률':>6} {'총수익':>9} {'평균':>7} {'손익비':>6} {'vs Orig':>9}")
        print('-' * 80)
        for rank, (_, r) in enumerate(top_wr.iterrows(), 1):
            diff = r['total_pnl'] - orig_stats['total_pnl']
            print(f"{rank:>3} {r['tp1']:>5.1f} {r['sell_ratio']:>5.0%} {r['tp2']:>5.1f} {r['remaining_sl']:>+5.1f} "
                  f"{r['total']:>5.0f} {r['winrate']:>5.1f}% {r['total_pnl']:>+8.1f}% "
                  f"{r['avg_pnl']:>+6.2f}% {r['pl_ratio']:>5.2f}:1 {diff:>+8.1f}%")
    else:
        print('  조건 충족 조합 없음')

    # Original 능가 조합 수
    better = results_df[results_df['total_pnl'] > orig_stats['total_pnl']]
    print(f"\n{'=' * 80}")
    print(f"Original 능가 조합: {len(better)}/{len(results_df)} ({len(better)/len(results_df)*100:.1f}%)")

    if len(better) > 0:
        best = better.loc[better['total_pnl'].idxmax()]
        print(f"\n  BEST: TP1={best['tp1']:.1f}%, 매도={best['sell_ratio']:.0%}, "
              f"TP2={best['tp2']:.1f}%, 잔SL={best['remaining_sl']:+.1f}%")
        print(f"  → 총 수익률: {best['total_pnl']:+.1f}% (Original 대비 {best['total_pnl'] - orig_stats['total_pnl']:+.1f}%)")
        print(f"  → 승률: {best['winrate']:.1f}%, 손익비: {best['pl_ratio']:.2f}:1")
    else:
        print("  Original이 모든 분할 익절 조합보다 우세")

    # 패턴 분석: TP1별 평균 성과
    print(f"\n{'=' * 80}")
    print("파라미터별 평균 성과 (민감도 분석)")
    print('=' * 80)

    print(f"\n--- TP1별 ---")
    for tp1 in tp1_values:
        f = results_df[results_df['tp1'] == tp1]
        if len(f) == 0:
            continue
        print(f"  TP1={tp1:.1f}%: 평균총수익 {f['total_pnl'].mean():+.1f}%, "
              f"최고 {f['total_pnl'].max():+.1f}%, 평균승률 {f['winrate'].mean():.1f}%")

    print(f"\n--- 매도비율별 ---")
    for sr in sell_ratio_values:
        f = results_df[results_df['sell_ratio'] == sr]
        if len(f) == 0:
            continue
        print(f"  매도={sr:.0%}: 평균총수익 {f['total_pnl'].mean():+.1f}%, "
              f"최고 {f['total_pnl'].max():+.1f}%, 평균승률 {f['winrate'].mean():.1f}%")

    print(f"\n--- TP2별 ---")
    for tp2 in tp2_values:
        f = results_df[results_df['tp2'] == tp2]
        if len(f) == 0:
            continue
        print(f"  TP2={tp2:.1f}%: 평균총수익 {f['total_pnl'].mean():+.1f}%, "
              f"최고 {f['total_pnl'].max():+.1f}%, 평균승률 {f['winrate'].mean():.1f}%")

    print(f"\n--- 잔여손절별 ---")
    for rsl in remaining_sl_values:
        f = results_df[results_df['remaining_sl'] == rsl]
        if len(f) == 0:
            continue
        print(f"  잔SL={rsl:+.1f}%: 평균총수익 {f['total_pnl'].mean():+.1f}%, "
              f"최고 {f['total_pnl'].max():+.1f}%, 평균승률 {f['winrate'].mean():.1f}%")

    print(f"\n{'=' * 80}")
    print(f"탐색 완료! 총 {len(combos)}개 조합, 소요: {t2 - t0:.1f}초")
    print('=' * 80)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260224', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5)
    args = parser.parse_args()

    run_multiverse(args.start, args.end, args.max_daily)
