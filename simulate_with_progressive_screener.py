"""
점진적 스크리너 시뮬레이션 — 미래참조 제거

기존 simulate_with_screener.py와의 차이:
  1. 스크리너가 09:01부터 2분마다 점진적으로 종목 발견 (실전 동일)
  2. 각 시점의 실제 누적 거래대금으로 순위 결정 (09:30 미래참조 제거)
  3. 종목별 발견 시각 + 20봉 워밍업 후 진입 (실전 동일)
  4. get_daily_metrics의 SUM→MAX 버그 수정

비교 모드(--compare): 기존 방식과 나란히 비교
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
import argparse
import time as time_module

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy
from simulate_with_screener import (
    get_trading_dates, get_prev_close_map, check_circuit_breaker,
    apply_daily_limit, calc_fixed_capital_returns, print_stats,
)

WARMUP_CANDLES = 10   # 변동성 필터 10봉 (실전 동일: 모멘텀은 max(0,idx-20)으로 부족해도 동작)
SCAN_INTERVAL = 2     # 스캔 주기 (분)
SCAN_START = 901      # 09:01 (HHMM)
SCAN_END = 1150       # 11:50
MAX_PER_SCAN = 5      # 스캔당 최대 발견
MAX_TOTAL = 15        # 일일 최대 후보


# ============================================================
# Step 1: 데이터 로딩
# ============================================================

def load_day_snapshots(cur, trade_date):
    """
    거래일 전 종목의 분별 누적 거래대금 + 시가 로드 (1회 쿼리).

    Returns:
        snapshots: {stock_code: [(hhmm_int, amount, close, open, day_open), ...]}
        day_open_map: {stock_code: day_open}
    """
    cur.execute('''
        SELECT stock_code, time,
               amount,
               close, open, high, low, volume,
               MIN(CASE WHEN time >= '090000' AND time <= '090300' THEN open END)
                   OVER (PARTITION BY stock_code) as day_open
        FROM minute_candles
        WHERE trade_date = %s
        ORDER BY stock_code, idx
    ''', [trade_date])

    snapshots = defaultdict(list)
    day_open_map = {}

    for row in cur.fetchall():
        code, time_str, amount, close, open_p, high, low, volume, day_open = row
        hhmm = int(str(time_str).zfill(6)[:4])
        snapshots[code].append((hhmm, amount, close, open_p, high, low, volume))
        if day_open and day_open > 0 and code not in day_open_map:
            day_open_map[code] = float(day_open)

    return dict(snapshots), day_open_map


def get_amount_at_time(snapshots, scan_hhmm):
    """
    특정 시점의 종목별 누적 거래대금 조회.
    amount가 누적이므로 해당 시점의 마지막 값 = 누적 거래대금.

    Returns: {stock_code: cumulative_amount}
    """
    result = {}
    for code, candles in snapshots.items():
        # scan_hhmm 이하인 마지막 캔들의 amount
        best_amt = 0
        for hhmm, amount, *_ in candles:
            if hhmm <= scan_hhmm:
                best_amt = amount if amount else 0
            else:
                break
        if best_amt > 0:
            result[code] = best_amt
    return result


# ============================================================
# Step 2: 점진적 스크리너 스캔
# ============================================================

def progressive_scan(snapshots, day_open_map, prev_close_map,
                     min_price=5000, max_price=500000,
                     min_gap_down_pct=-2.0, max_gap_pct=3.0,
                     min_change_rate=0.5, max_change_rate=5.0):
    """
    실전 스크리너와 동일한 점진적 종목 발견 시뮬레이션.

    2분마다 (09:01, 09:03, ...) 해당 시점의 누적 거래대금 순위로
    top-60에서 Phase 2 필터 적용 후 최대 5종목 발견.

    Returns:
        {stock_code: discovery_hhmm}  (발견 시각)
    """
    discovered = {}
    total = 0

    # 스캔 시각 생성: 0901, 0903, 0905, ...
    scan_times = []
    h, m = 9, 1
    while h * 100 + m <= SCAN_END:
        scan_times.append(h * 100 + m)
        m += SCAN_INTERVAL
        if m >= 60:
            h += 1
            m -= 60

    for scan_hhmm in scan_times:
        if total >= MAX_TOTAL:
            break

        # 해당 시점의 누적 거래대금
        amounts = get_amount_at_time(snapshots, scan_hhmm)
        if not amounts:
            continue

        # top-60 (기존 스크리너 Phase 1과 동일)
        ranked = sorted(amounts.items(), key=lambda x: x[1], reverse=True)[:60]

        added_this_scan = 0
        for code, amt in ranked:
            if added_this_scan >= MAX_PER_SCAN or total >= MAX_TOTAL:
                break
            if code in discovered:
                continue

            # 우선주 제외
            if code[-1] == '5':
                continue

            day_open = day_open_map.get(code, 0)
            if day_open <= 0:
                continue

            # 가격 필터
            if not (min_price <= day_open <= max_price):
                continue

            # 등락률 + 갭 필터
            prev_close = prev_close_map.get(code)
            if prev_close and prev_close > 0:
                gap_pct = (day_open / prev_close - 1) * 100
                if gap_pct < min_change_rate or gap_pct > max_change_rate:
                    continue
                if abs(gap_pct) > max_gap_pct:
                    continue
                if gap_pct < min_gap_down_pct:
                    continue

            discovered[code] = scan_hhmm
            total += 1
            added_this_scan += 1

    return discovered


# ============================================================
# Step 3: 메인 시뮬레이션
# ============================================================

def run_simulation(start_date='20250224', end_date=None, config=None,
                   max_daily=7, cost_pct=0.33, verbose=True,
                   compare_mode=False):
    """점진적 스크리너 시뮬레이션 실행"""
    t0 = time_module.time()

    strategy = PricePositionStrategy(config=config)
    all_trades = []
    # 비교용: 기존 방식 거래도 수집
    legacy_trades = [] if compare_mode else None

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    trading_dates = get_trading_dates(cur, start_date, end_date)

    print(f"점진적 스크리너 시뮬레이션: {len(trading_dates)}거래일")
    print(f"  스캔: {SCAN_START//100}:{SCAN_START%100:02d}~{SCAN_END//100}:{SCAN_END%100:02d}, "
          f"{SCAN_INTERVAL}분 간격, 스캔당 {MAX_PER_SCAN}종목, 일일 {MAX_TOTAL}종목")
    print(f"  워밍업: {WARMUP_CANDLES}봉, 비용: {cost_pct:.2f}%, 동시보유: {max_daily}종목")
    if compare_mode:
        print(f"  비교 모드: 기존 방식(09:30 일괄)과 나란히 비교")
    print("=" * 90)

    stats = {'days': 0, 'cb_days': 0, 'avg_discovered': []}

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            elapsed = time_module.time() - t0
            print(f"  [{day_idx}/{len(trading_dates)}] {trade_date}  "
                  f"({elapsed:.0f}s, 거래 {len(all_trades)}건)")

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        # 서킷브레이커
        if day_idx > 1:
            is_cb, cb_reason = check_circuit_breaker(
                cur, prev_date, trading_dates[day_idx - 2], -3.0)
            if is_cb:
                stats['cb_days'] += 1
                continue

        # 1) 전 종목 분봉 데이터 1회 로드
        snapshots, day_open_map = load_day_snapshots(cur, trade_date)
        if not snapshots:
            continue

        prev_close_map = get_prev_close_map(cur, trade_date, prev_date) if prev_date else {}

        # 2) 점진적 스크리너 → 종목별 발견 시각
        discovery_map = progressive_scan(snapshots, day_open_map, prev_close_map)
        stats['avg_discovered'].append(len(discovery_map))
        stats['days'] += 1

        if not discovery_map:
            continue

        # 3) 각 종목: 발견 시각 + 워밍업 이후부터 진입 스캔
        day_trade_list = []

        for stock_code, disc_hhmm in discovery_map.items():
            candles = snapshots.get(stock_code, [])
            if len(candles) < 50:
                continue

            day_open = day_open_map.get(stock_code, 0)
            if day_open <= 0:
                continue

            # numpy 변환 없이 DataFrame 사용 (기존 strategy 호환)
            df = pd.DataFrame(candles,
                              columns=['hhmm', 'amount', 'close', 'open', 'high', 'low', 'volume'])
            # time 컬럼 추가 (strategy가 사용)
            df['time'] = df['hhmm'].apply(lambda x: f'{x:04d}00')
            df['idx'] = range(len(df))
            df['date'] = trade_date

            # 발견 시각의 idx 찾기
            disc_idx = 0
            for i, (hhmm, *_) in enumerate(candles):
                if hhmm >= disc_hhmm:
                    disc_idx = i
                    break

            # 진입 가능 시작: 발견 idx + 워밍업
            earliest = disc_idx + WARMUP_CANDLES
            if earliest >= len(candles) - 10:
                continue

            traded = False
            for candle_idx in range(earliest, len(df) - 10):
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

                adv_ok, _ = strategy.check_advanced_conditions(
                    df=df, candle_idx=candle_idx
                )
                if not adv_ok:
                    continue

                result = strategy.simulate_trade(df, candle_idx)
                if result:
                    pct_from_open = (current_price / day_open - 1) * 100
                    trade = {
                        'date': trade_date,
                        'stock_code': stock_code,
                        'weekday': weekday,
                        'pct_from_open': pct_from_open,
                        'disc_time': disc_hhmm,
                        **result,
                    }
                    day_trade_list.append(trade)
                    strategy.record_trade(stock_code, trade_date)
                    traded = True

        all_trades.extend(day_trade_list)

        # 비교 모드: 기존 방식도 실행 (09:30 일괄, idx=10부터)
        if compare_mode:
            legacy_day = []
            for stock_code in discovery_map.keys():
                candles = snapshots.get(stock_code, [])
                if len(candles) < 50:
                    continue
                day_open = day_open_map.get(stock_code, 0)
                if day_open <= 0:
                    continue

                df = pd.DataFrame(candles,
                                  columns=['hhmm', 'amount', 'close', 'open', 'high', 'low', 'volume'])
                df['time'] = df['hhmm'].apply(lambda x: f'{x:04d}00')
                df['idx'] = range(len(df))
                df['date'] = trade_date

                traded_l = False
                for candle_idx in range(10, len(df) - 10):
                    if traded_l:
                        break
                    row = df.iloc[candle_idx]
                    can_enter, _ = strategy.check_entry_conditions(
                        stock_code=stock_code,
                        current_price=row['close'],
                        day_open=day_open,
                        current_time=str(row['time']),
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
                        legacy_day.append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': (row['close'] / day_open - 1) * 100,
                            **result,
                        })
                        traded_l = True
            legacy_trades.extend(legacy_day)

    cur.close()
    conn.close()

    elapsed = time_module.time() - t0
    avg_disc = np.mean(stats['avg_discovered']) if stats['avg_discovered'] else 0
    print(f"\n완료 ({elapsed:.0f}s)")
    print(f"거래일: {stats['days']}일, 서킷브레이커: {stats['cb_days']}일")
    print(f"일평균 발견 종목: {avg_disc:.1f}개")
    print(f"총 거래: {len(all_trades)}건")

    if not all_trades:
        print("거래 없음")
        return

    trades_df = pd.DataFrame(all_trades)

    # 동시보유 제한 적용
    limited_df = apply_daily_limit(trades_df, max_daily)
    l_total = len(limited_df)

    # ============================================================
    # 결과 출력
    # ============================================================

    print("\n" + "=" * 90)
    print("  점진적 스크리너 결과 (미래참조 제거)")
    print("=" * 90)

    if l_total > 0:
        wins = (limited_df['result'] == 'WIN').sum()
        avg_pnl = limited_df['pnl'].mean() - cost_pct
        fixed = calc_fixed_capital_returns(limited_df, cost_pct=cost_pct)
        fret = fixed['total_return_pct']

        print(f"  거래: {l_total}건, 승률: {wins/l_total*100:.1f}%, "
              f"평균순익: {avg_pnl:+.2f}%, 고정수익률: {fret:+.1f}%")

        # 진입 시각 분포
        print(f"\n  진입 시각 분포:")
        entry_times = limited_df['entry_time'].apply(
            lambda x: int(str(x).zfill(6)[:4]) if pd.notna(x) else 0)
        bins = [(900, 910), (910, 920), (920, 930), (930, 1000),
                (1000, 1030), (1030, 1100), (1100, 1200)]
        for lo, hi in bins:
            count = ((entry_times >= lo) & (entry_times < hi)).sum()
            pct = count / l_total * 100
            bar = '#' * int(pct)
            print(f"    {lo//100}:{lo%100:02d}-{hi//100}:{hi%100:02d}  {count:>5}건 ({pct:4.1f}%)  {bar}")

        # 월별
        print(f"\n  월별 수익 (만원):")
        monthly = defaultdict(float)
        invest = 10_000_000 * 0.20
        for _, row in limited_df.iterrows():
            m = row['date'][:6]
            monthly[m] += invest * ((row['pnl'] - cost_pct) / 100)
        for m in sorted(monthly.keys()):
            v = monthly[m] / 10000
            print(f"    {m}: {v:>+8.0f}만")

    # ============================================================
    # 비교 모드
    # ============================================================

    if compare_mode and legacy_trades:
        legacy_df = pd.DataFrame(legacy_trades)
        legacy_limited = apply_daily_limit(legacy_df, max_daily)
        ll = len(legacy_limited)

        print("\n" + "=" * 90)
        print("  기존 방식 vs 점진적 스크리너 비교")
        print("=" * 90)

        if ll > 0:
            l_wins = (legacy_limited['result'] == 'WIN').sum()
            l_fixed = calc_fixed_capital_returns(legacy_limited, cost_pct=cost_pct)

            print(f"\n  {'':>25} {'기존(09:30일괄)':>18} {'점진적(실전)':>18} {'차이':>10}")
            print(f"  {'-'*75}")
            print(f"  {'거래수':>25} {ll:>17}건 {l_total:>17}건 {l_total-ll:>+9}건")
            print(f"  {'승률':>25} {l_wins/ll*100:>16.1f}% {wins/l_total*100:>16.1f}% "
                  f"{wins/l_total*100 - l_wins/ll*100:>+8.1f}%p")
            print(f"  {'평균순익':>25} {legacy_limited['pnl'].mean()-cost_pct:>+16.2f}% "
                  f"{avg_pnl:>+16.2f}% {avg_pnl-(legacy_limited['pnl'].mean()-cost_pct):>+8.2f}%p")
            print(f"  {'고정수익률':>25} {l_fixed['total_return_pct']:>+16.1f}% "
                  f"{fret:>+16.1f}% {fret-l_fixed['total_return_pct']:>+8.1f}%p")

            # 기존 방식 진입 시각 분포
            leg_times = legacy_limited['entry_time'].apply(
                lambda x: int(str(x).zfill(6)[:4]) if pd.notna(x) else 0)
            print(f"\n  진입 시각 분포 비교:")
            print(f"  {'시간대':>15} {'기존':>10} {'점진적':>10}")
            for lo, hi in bins:
                c_leg = ((leg_times >= lo) & (leg_times < hi)).sum()
                c_new = ((entry_times >= lo) & (entry_times < hi)).sum()
                print(f"  {lo//100}:{lo%100:02d}-{hi//100}:{hi%100:02d}"
                      f"  {c_leg:>8}건  {c_new:>8}건")

    print(f"\n총 실행 시간: {time_module.time()-t0:.0f}초")


if __name__ == '__main__':
    from simulate_with_screener import _load_defaults
    defaults = _load_defaults()

    parser = argparse.ArgumentParser(description='점진적 스크리너 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default=None, help='종료일')
    parser.add_argument('--max-daily', type=int, default=defaults['max_daily'])
    parser.add_argument('--cost', type=float, default=0.33)
    parser.add_argument('--compare', action='store_true', help='기존 방식과 비교')
    parser.add_argument('--quiet', action='store_true')

    args = parser.parse_args()
    run_simulation(
        start_date=args.start, end_date=args.end,
        max_daily=args.max_daily, cost_pct=args.cost,
        verbose=not args.quiet, compare_mode=args.compare,
    )
