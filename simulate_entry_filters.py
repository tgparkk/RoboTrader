"""
진입 필터 멀티버스 시뮬레이션

04-03 WIN/LOSS 분석에서 도출된 3가지 필터 검증:
1. 거래량 스파이크 필터: 진입 캔들 거래량 > 직전 5분 평균 x N배 -> 진입 제외
2. 시가대비 하한 상향: +1.0% -> +1.3% / +1.5%
3. 전일 급락 필터: 전일 등락률 < -X% 종목 제외

기존 simulate_with_screener.py 구조 기반.
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
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
    calc_fixed_capital_returns,
)


def run_multiverse(
    start_date='20250224',
    end_date='20260223',
    cost_pct=0.33,
    max_daily=7,
    preload_top_n=30,
    circuit_breaker_pct=-3.0,
):
    # 멀티버스 파라미터
    vol_spike_max_options = [0, 1.5, 2.0, 2.5, 3.0]  # 0 = 필터 없음(기준선)
    min_pct_options = [1.0, 1.3, 1.5]                  # 시가대비 하한
    prev_drop_options = [0, -8.0, -6.0, -4.0]          # 0 = 필터 없음

    configs = []
    for vsp in vol_spike_max_options:
        for mpct in min_pct_options:
            for pdrop in prev_drop_options:
                name_parts = []
                if vsp > 0:
                    name_parts.append(f'VSpike<{vsp}x')
                if mpct != 1.0:
                    name_parts.append(f'Min{mpct}%')
                if pdrop < 0:
                    name_parts.append(f'PD>{pdrop}%')
                name = '+'.join(name_parts) if name_parts else '기준선'
                configs.append({
                    'name': name,
                    'vol_spike_max': vsp,
                    'min_pct': mpct,
                    'prev_drop_min': pdrop,
                })

    print('=' * 110)
    print('진입 필터 멀티버스 시뮬레이션')
    print('=' * 110)
    print(f'기간: {start_date} ~ {end_date}')
    print(f'동시보유: {max_daily}종목, 비용: {cost_pct:.2f}%/건')
    print(f'멀티버스: {len(configs)}개 조합')
    print(f'  거래량스파이크상한: {vol_spike_max_options} (0=없음)')
    print(f'  시가대비하한: {min_pct_options}%')
    print(f'  전일급락필터: {prev_drop_options}% (0=없음)')
    print('=' * 110)

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

    total_entries = 0
    total_filtered = defaultdict(int)  # 필터별 차단 횟수

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

        # 전일 등락률 맵 (전일급락 필터용)
        prev_change_map = {}
        if prev_date:
            for sc, prev_c in prev_close_map.items():
                if sc in daily_metrics:
                    day_open = daily_metrics[sc]['day_open']
                    if prev_c > 0:
                        # 전일 등락률 = (전일종가 - 전전일종가) / 전전일종가
                        # 여기서는 간단히 시가갭으로 대체: (당일시가 / 전일종가 - 1)은 갭
                        # 전일 등락률을 정확히 구하려면 전전일 종가 필요
                        pass

        # 전일 등락률 직접 계산 (daily_candles에서)
        prev_day_change = {}
        if prev_date and day_idx > 1:
            prev_prev_date = trading_dates[day_idx - 2]
            cur.execute('''
                SELECT a.stock_code,
                       (a.stck_clpr::float / NULLIF(b.stck_clpr::float, 0) - 1) * 100 as change_pct
                FROM daily_candles a
                JOIN daily_candles b ON a.stock_code = b.stock_code
                WHERE a.stck_bsop_date = %s AND b.stck_bsop_date = %s
            ''', [prev_date, prev_prev_date])
            for row in cur.fetchall():
                if row[1] is not None:
                    prev_day_change[row[0]] = row[1]

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

                # 진입 포인트 찾기 (기본 조건: 시가대비 1% 이상)
                # 각 config마다 다른 min_pct를 적용하므로, 가장 느슨한 조건으로 후보 수집
                entry_candidates = []
                for candle_idx in range(10, len(df) - 10):
                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    # 기본 진입 조건 (시가대비 하한은 1.0% 고정으로 체크)
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

                    pct_from_open = (current_price / day_open - 1) * 100

                    # 거래량 스파이크 계산
                    pre5_start = max(0, candle_idx - 5)
                    pre5_vol = df.iloc[pre5_start:candle_idx]['volume']
                    avg_vol = pre5_vol.mean() if len(pre5_vol) >= 3 else 0
                    cur_vol = row['volume']
                    vol_spike = cur_vol / avg_vol if avg_vol > 0 else 1.0

                    entry_candidates.append({
                        'candle_idx': candle_idx,
                        'pct_from_open': pct_from_open,
                        'vol_spike': vol_spike,
                    })
                    break  # 종목당 첫 진입만

                if not entry_candidates:
                    continue

                ec = entry_candidates[0]
                total_entries += 1

                # 전일 등락률
                stock_prev_change = prev_day_change.get(stock_code, 0)

                # 기준선 시뮬 결과 (한 번만 계산)
                base_result = strategy.simulate_trade(df, ec['candle_idx'])

                for cfg_idx, cfg in enumerate(configs):
                    # 필터 1: 거래량 스파이크 상한
                    if cfg['vol_spike_max'] > 0 and ec['vol_spike'] > cfg['vol_spike_max']:
                        continue

                    # 필터 2: 시가대비 하한
                    if ec['pct_from_open'] < cfg['min_pct']:
                        continue

                    # 필터 3: 전일 급락 필터
                    if cfg['prev_drop_min'] < 0 and stock_prev_change < cfg['prev_drop_min']:
                        continue

                    if base_result:
                        all_trades_by_cfg[cfg_idx].append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': ec['pct_from_open'],
                            'vol_spike': ec['vol_spike'],
                            'prev_change': stock_prev_change,
                            **base_result,
                        })

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n총 진입 포인트: {total_entries}건')

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

        stop_trades = trades_df[trades_df['exit_reason'].str.contains('손절')]
        stop_count = len(stop_trades)
        stop_avg = stop_trades['pnl'].mean() if stop_count > 0 else 0

        results.append({
            'name': cfg['name'],
            'vol_spike_max': cfg['vol_spike_max'],
            'min_pct': cfg['min_pct'],
            'prev_drop_min': cfg['prev_drop_min'],
            'total': total,
            'wins': wins,
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'total_return': total_return,
            'stop_count': stop_count,
            'stop_avg_pnl': stop_avg,
        })

    # 결과 출력
    print('\n')
    print('=' * 130)
    print('멀티버스 결과 (고정자본 수익률 순)')
    print('=' * 130)
    print(f'{"순위":>3} {"설정":<35} {"거래":>5} {"승률":>7} {"평균PnL":>8} '
          f'{"고정자본":>10} {"손절건":>6} {"손절평균":>8} {"기준대비":>10}')
    print('-' * 130)

    results.sort(key=lambda x: x['total_return'], reverse=True)
    baseline_return = next((r['total_return'] for r in results if r['name'] == '기준선'), 0)

    for rank, r in enumerate(results, 1):
        diff = r['total_return'] - baseline_return
        diff_str = f"{diff:+.1f}%p" if r['name'] != '기준선' else '-'
        marker = ' *' if rank <= 5 and r['name'] != '기준선' else ''
        baseline_mark = ' <<' if r['name'] == '기준선' else ''
        print(f"{rank:>3} {r['name']:<35} {r['total']:>5} {r['win_rate']:>6.1f}% "
              f"{r['avg_pnl']:>+7.2f}% {r['total_return']:>+9.1f}% "
              f"{r['stop_count']:>6} {r['stop_avg_pnl']:>+7.2f}% "
              f"{diff_str:>10}{marker}{baseline_mark}")

    # 필터별 효과 분석
    print('\n' + '=' * 80)
    print('개별 필터 효과 분석 (다른 필터 없을 때)')
    print('=' * 80)

    # 거래량 스파이크만 적용
    print('\n[거래량 스파이크 상한]')
    for r in results:
        if r['min_pct'] == 1.0 and r['prev_drop_min'] == 0:
            diff = r['total_return'] - baseline_return
            vsp_str = f"<{r['vol_spike_max']}x" if r['vol_spike_max'] > 0 else '없음'
            print(f"  {vsp_str:>8}: {r['total']}건, 승률 {r['win_rate']:.1f}%, "
                  f"수익률 {r['total_return']:+.1f}% ({diff:+.1f}%p)")

    # 시가대비 하한만 적용
    print('\n[시가대비 하한]')
    for r in results:
        if r['vol_spike_max'] == 0 and r['prev_drop_min'] == 0:
            diff = r['total_return'] - baseline_return
            print(f"  >={r['min_pct']:.1f}%: {r['total']}건, 승률 {r['win_rate']:.1f}%, "
                  f"수익률 {r['total_return']:+.1f}% ({diff:+.1f}%p)")

    # 전일급락 필터만 적용
    print('\n[전일 급락 필터]')
    for r in results:
        if r['vol_spike_max'] == 0 and r['min_pct'] == 1.0:
            diff = r['total_return'] - baseline_return
            pd_str = f">{r['prev_drop_min']}%" if r['prev_drop_min'] < 0 else '없음'
            print(f"  {pd_str:>8}: {r['total']}건, 승률 {r['win_rate']:.1f}%, "
                  f"수익률 {r['total_return']:+.1f}% ({diff:+.1f}%p)")

    # 상위 10개 상세
    print('\n' + '=' * 80)
    print('상위 10개 상세')
    print('=' * 80)
    for rank, r in enumerate(results[:10], 1):
        diff = r['total_return'] - baseline_return
        print(f"\n#{rank} {r['name']}")
        print(f"  거래 {r['total']}건, 승률 {r['win_rate']:.1f}%, 평균 {r['avg_pnl']:+.2f}%")
        print(f"  고정자본 수익률: {r['total_return']:+.1f}% (기준 대비 {diff:+.1f}%p)")
        print(f"  손절 {r['stop_count']}건 (평균 {r['stop_avg_pnl']:+.2f}%)")

    print('\nDone!')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='진입 필터 멀티버스')
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
