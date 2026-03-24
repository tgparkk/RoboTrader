"""
손절축소 멀티버스 시뮬레이션

핵심 질문: 전일 하락일에 손절/익절을 축소하는 현재 설정이 최적인가?

방법:
1. DB를 1회만 읽고, 각 진입 시점에서 여러 SL/TP 조합의 청산을 동시에 시뮬레이션
2. 전일 지수 데이터로 하락일 분류
3. "하락일에 다른 SL/TP 적용" 시나리오를 조합하여 비교

현재 설정:
- 정상: SL -5%, TP +6%
- 전일 -1% 하락: SL -3%, TP +4%
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
    get_trading_dates, get_prev_close_map, get_daily_metrics,
    apply_screener_filter, apply_daily_limit,
    calc_capital_returns, calc_fixed_capital_returns,
)


# ============================================================
# SL/TP 조합 정의
# ============================================================
SL_TP_CONFIGS = [
    (-5.0, 6.0),   # 기준선 (정상)
    (-4.5, 5.5),
    (-4.0, 5.0),
    (-4.0, 6.0),   # SL만 축소, TP 유지
    (-3.5, 4.5),
    (-3.5, 6.0),   # SL만 축소, TP 유지
    (-3.0, 4.0),   # 현재 하락일 설정
    (-3.0, 6.0),   # SL만 축소, TP 유지
]


def simulate_trade_multi(df, entry_idx, configs):
    """
    하나의 진입 시점에서 여러 SL/TP 조합의 청산을 동시에 시뮬레이션.
    진입: 신호 캔들 다음 캔들 시가 (simulate_trade와 동일)
    """
    if entry_idx + 1 >= len(df) - 5:
        return {}

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']

    if entry_price <= 0:
        return {}

    results = {}
    active = {cfg: True for cfg in configs}

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl = (row['low'] / entry_price - 1) * 100

        for cfg in list(active.keys()):
            if not active[cfg]:
                continue
            sl_pct, tp_pct = cfg

            # 익절 (고가 기준) — check_exit_conditions과 동일 순서
            if high_pnl >= tp_pct:
                results[cfg] = {
                    'pnl': tp_pct,
                    'result': 'WIN',
                    'exit_reason': '익절',
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                }
                active[cfg] = False
                continue

            # 손절 (저가 기준)
            if low_pnl <= sl_pct:
                results[cfg] = {
                    'pnl': sl_pct,
                    'result': 'LOSS',
                    'exit_reason': '손절',
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                }
                active[cfg] = False
                continue

        if not any(active.values()):
            break

    # 장 마감 처리
    last_row = df.iloc[-1]
    last_pnl = (last_row['close'] / entry_price - 1) * 100

    for cfg in active:
        if active[cfg]:
            results[cfg] = {
                'pnl': last_pnl,
                'result': 'WIN' if last_pnl > 0 else 'LOSS',
                'exit_reason': '장마감',
                'entry_time': entry_time,
                'exit_time': last_row['time'],
                'entry_price': entry_price,
            }

    return results


def load_market_data():
    """KOSPI/KOSDAQ 일봉 데이터 로드"""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute('''
        SELECT stock_code, stck_bsop_date,
               CAST(stck_oprc AS FLOAT) as open,
               CAST(stck_clpr AS FLOAT) as close
        FROM daily_candles
        WHERE stock_code IN ('KS11', 'KQ11')
        ORDER BY stck_bsop_date
    ''')
    rows = cur.fetchall()
    conn.close()

    data = defaultdict(dict)
    for code, dt, opn, cls in rows:
        data[dt][code] = {'open': opn, 'close': cls}

    dates = sorted(data.keys())
    prev = {}
    result = {}
    for dt in dates:
        d = data[dt]
        if 'KS11' in d and 'KQ11' in d:
            entry = {}
            if 'KS11' in prev and 'KQ11' in prev:
                entry['kospi_chg'] = (d['KS11']['close'] / prev['KS11']['close'] - 1) * 100
                entry['kosdaq_chg'] = (d['KQ11']['close'] / prev['KQ11']['close'] - 1) * 100
            else:
                entry['kospi_chg'] = 0
                entry['kosdaq_chg'] = 0
            result[dt] = entry
            prev = {k: v for k, v in d.items()}
    return result


def get_prev_day_worst(market_data, all_market_dates, date):
    """전일 지수 worst 등락률"""
    try:
        idx = all_market_dates.index(date)
        prev_date = all_market_dates[idx - 1] if idx > 0 else None
    except ValueError:
        prev_date = None

    if not prev_date or prev_date not in market_data:
        return 0.0
    m = market_data[prev_date]
    return min(m['kospi_chg'], m['kosdaq_chg'])


def run_multiverse(start_date='20250224', end_date='20260324', max_daily=5,
                   cost_pct=0.33):
    """메인 시뮬레이션"""
    t0 = time_module.time()

    print('=' * 100)
    print('손절축소 멀티버스 시뮬레이션')
    print(f'  기간: {start_date} ~ {end_date}')
    print(f'  동시보유: {max_daily}종목, 비용: {cost_pct:.2f}%/건')
    print(f'  SL/TP 조합: {len(SL_TP_CONFIGS)}개')
    print('=' * 100)

    # 1. 시장 데이터 로드
    print('\n[1/3] 시장 데이터 로드...')
    market_data = load_market_data()
    all_market_dates = sorted(market_data.keys())
    print(f'  KOSPI/KOSDAQ 데이터: {len(market_data)}일')

    # 2. 멀티 SL/TP 시뮬레이션
    print('\n[2/3] 멀티 SL/TP 시뮬레이션...')

    base_config = {
        'min_pct_from_open': 1.0,
        'max_pct_from_open': 3.0,
        'entry_start_hour': 9,
        'entry_end_hour': 12,
        'stop_loss_pct': -5.0,
        'take_profit_pct': 6.0,
    }
    strategy = PricePositionStrategy(config=base_config)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'  총 거래일: {len(trading_dates)}일')

    # {config: [trades]}
    all_trades = {cfg: [] for cfg in SL_TP_CONFIGS}
    entry_count = 0

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 20 == 0:
            elapsed = time_module.time() - t0
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) '
                  f'진입 {entry_count}건 | {elapsed:.0f}초')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=60, min_price=5000, max_price=500000,
            min_amount=1_000_000_000, max_gap_pct=3.0,
        )
        if not screened:
            continue

        strategy._daily_trades = {}  # reset daily trade tracker

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

                    # 여러 SL/TP로 동시 시뮬레이션
                    multi_results = simulate_trade_multi(df, candle_idx, SL_TP_CONFIGS)

                    if multi_results:
                        pct_from_open = (current_price / day_open - 1) * 100
                        for cfg, result in multi_results.items():
                            all_trades[cfg].append({
                                'date': trade_date,
                                'stock_code': stock_code,
                                'weekday': weekday,
                                'pct_from_open': pct_from_open,
                                **result,
                            })
                        strategy.record_trade(stock_code, trade_date)
                        traded = True
                        entry_count += 1

            except Exception:
                continue

    cur.close()
    conn.close()

    elapsed = time_module.time() - t0
    print(f'\n  시뮬레이션 완료: {entry_count}건 진입, {elapsed:.0f}초')

    # 3. 멀티버스 분석
    print('\n[3/3] 멀티버스 분석...')

    # 각 config별 DataFrame 생성 + daily limit 적용
    config_dfs = {}
    for cfg in SL_TP_CONFIGS:
        if all_trades[cfg]:
            df = pd.DataFrame(all_trades[cfg])
            config_dfs[cfg] = apply_daily_limit(df, max_daily)
        else:
            config_dfs[cfg] = pd.DataFrame()

    # 전일 하락 분류
    def classify_dates(config_df, threshold):
        """전일 하락 threshold 이하인 날짜 set"""
        bearish = set()
        for date in config_df['date'].unique():
            worst = get_prev_day_worst(market_data, all_market_dates, date)
            if worst <= threshold:
                bearish.add(date)
        return bearish

    # ============================================================
    # A. 기준선: 각 SL/TP를 항상 적용한 결과
    # ============================================================
    print('\n')
    print('=' * 100)
    print('A. 기준선: 각 SL/TP를 항상(모든 날) 적용한 결과')
    print('=' * 100)

    base_df = config_dfs[(-5.0, 6.0)]
    base_cap = calc_fixed_capital_returns(base_df, cost_pct=cost_pct)

    print(f'\n  {"SL/TP":<15} {"거래":>5} {"승":>4} {"패":>4} {"승률":>6} '
          f'{"평균PnL":>8} {"고정수익률":>10} {"개선":>10}  {"손절":>5} {"익절":>5} {"장마감":>5}')
    print('  ' + '-' * 95)

    for cfg in SL_TP_CONFIGS:
        df = config_dfs[cfg]
        if len(df) == 0:
            continue
        sl, tp = cfg
        wins = (df['result'] == 'WIN').sum()
        losses = len(df) - wins
        winrate = wins / len(df) * 100
        avg_pnl = df['pnl'].mean()
        cap = calc_fixed_capital_returns(df, cost_pct=cost_pct)
        diff = cap['total_return_pct'] - base_cap['total_return_pct']
        sl_cnt = (df['exit_reason'] == '손절').sum()
        tp_cnt = (df['exit_reason'] == '익절').sum()
        eod_cnt = (df['exit_reason'] == '장마감').sum()
        marker = ' <-- 현재' if cfg == (-5.0, 6.0) else ''
        print(f'  SL{sl:>+5.1f}/TP{tp:>+4.1f}  {len(df):>4}건 {wins:>3}승 {losses:>3}패 '
              f'{winrate:>5.1f}% {avg_pnl:>+7.2f}% {cap["total_return_pct"]:>+9.2f}% '
              f'{diff:>+9.2f}%p  {sl_cnt:>4}건 {tp_cnt:>4}건 {eod_cnt:>4}건{marker}')

    # ============================================================
    # B. 조건부 적용: 전일 하락일에만 다른 SL/TP
    # ============================================================
    print('\n')
    print('=' * 100)
    print('B. 조건부 적용: 정상일=SL-5%/TP+6%, 전일 하락일에만 다른 SL/TP 적용')
    print('=' * 100)

    base_normal = (-5.0, 6.0)
    thresholds = [-0.5, -1.0, -1.5, -2.0, -3.0]

    # 하락일에 적용할 SL/TP 후보
    bearish_configs = [
        (-5.0, 6.0),   # 조정 없음
        (-4.0, 6.0),   # SL만 4%
        (-4.0, 5.0),   # SL 4%, TP 5%
        (-3.5, 6.0),   # SL만 3.5%
        (-3.5, 4.5),   # SL 3.5%, TP 4.5%
        (-3.0, 6.0),   # SL만 3%
        (-3.0, 4.0),   # 현재 설정
    ]

    results = []

    for threshold in thresholds:
        bearish_dates = classify_dates(config_dfs[base_normal], threshold)
        n_bearish = len(bearish_dates)

        if n_bearish == 0:
            continue

        print(f'\n  --- 전일 {threshold}% 이하 → {n_bearish}일 ---')
        print(f'  {"하락일 SL/TP":<22} {"거래":>5} {"승률":>6} {"평균PnL":>8} '
              f'{"고정수익률":>10} {"개선":>10}  {"하락일거래":>8} {"하락일PnL":>10}')
        print('  ' + '-' * 95)

        for bear_cfg in bearish_configs:
            if bear_cfg not in config_dfs:
                continue

            # 정상일: base_normal 결과, 하락일: bear_cfg 결과
            normal_df = config_dfs[base_normal]
            bear_df = config_dfs[bear_cfg]

            normal_trades = normal_df[~normal_df['date'].isin(bearish_dates)]
            bear_trades = bear_df[bear_df['date'].isin(bearish_dates)]

            combined = pd.concat([normal_trades, bear_trades], ignore_index=True)
            combined = combined.sort_values(['date', 'entry_time']).reset_index(drop=True)

            if len(combined) == 0:
                continue

            wins = (combined['result'] == 'WIN').sum()
            winrate = wins / len(combined) * 100
            avg_pnl = combined['pnl'].mean()
            cap = calc_fixed_capital_returns(combined, cost_pct=cost_pct)
            diff = cap['total_return_pct'] - base_cap['total_return_pct']

            # 하락일만 통계
            bear_n = len(bear_trades)
            bear_avg = bear_trades['pnl'].mean() if bear_n > 0 else 0

            sl, tp = bear_cfg
            label = f'SL{sl:>+5.1f}/TP{tp:>+4.1f}'
            is_current = (threshold == -1.0 and bear_cfg == (-3.0, 4.0))
            is_none = (bear_cfg == base_normal)
            marker = ' <-- 현재' if is_current else (' (조정없음)' if is_none else '')

            print(f'  {label:<22} {len(combined):>4}건 {winrate:>5.1f}% '
                  f'{avg_pnl:>+7.2f}% {cap["total_return_pct"]:>+9.2f}% '
                  f'{diff:>+9.2f}%p  {bear_n:>7}건 {bear_avg:>+9.2f}%{marker}')

            results.append({
                'threshold': threshold,
                'bear_sl': sl,
                'bear_tp': tp,
                'trades': len(combined),
                'winrate': winrate,
                'avg_pnl': avg_pnl,
                'capital_return': cap['total_return_pct'],
                'improvement': diff,
                'bear_trades': bear_n,
                'bear_avg_pnl': bear_avg,
                'is_current': is_current,
            })

    # ============================================================
    # C. 전체 비교 요약 (수익률 순 정렬)
    # ============================================================
    print('\n')
    print('=' * 100)
    print('C. 전체 비교 요약 (고정자본수익률 순 정렬, 상위 20개)')
    print('=' * 100)

    print(f'\n  기준선 (항상 SL-5%/TP+6%): {base_cap["total_return_pct"]:+.2f}%')
    print()

    print(f'  {"#":>3} {"조건":<45} {"거래":>5} {"승률":>6} '
          f'{"고정수익률":>10} {"개선":>10} {"하락일PnL":>10}')
    print('  ' + '-' * 95)

    sorted_results = sorted(results, key=lambda x: x['capital_return'], reverse=True)

    for i, r in enumerate(sorted_results[:20]):
        label = (f'전일{r["threshold"]:>+5.1f}%↓ → '
                 f'SL{r["bear_sl"]:>+5.1f}/TP{r["bear_tp"]:>+4.1f} '
                 f'({r["bear_trades"]}일)')
        marker = ' ★현재' if r['is_current'] else ''
        print(f'  {i+1:>3} {label:<45} {r["trades"]:>4}건 {r["winrate"]:>5.1f}% '
              f'{r["capital_return"]:>+9.2f}% {r["improvement"]:>+9.2f}%p '
              f'{r["bear_avg_pnl"]:>+9.2f}%{marker}')

    # 현재 설정 위치 표시
    for i, r in enumerate(sorted_results):
        if r['is_current']:
            print(f'\n  ★ 현재 설정(전일-1%→SL-3%/TP+4%)은 {len(sorted_results)}개 중 {i+1}위')
            break

    # ============================================================
    # D. 하락일 깊이별 상세
    # ============================================================
    print('\n')
    print('=' * 100)
    print('D. 전일 하락 강도별 당일 전략 성과 (기준선 SL-5%/TP+6%)')
    print('=' * 100)

    base_df = config_dfs[(-5.0, 6.0)]
    buckets = [
        ('전일 +1% 이상', 1.0, 999),
        ('전일 0~+1%', 0.0, 1.0),
        ('전일 -0.5~0%', -0.5, 0.0),
        ('전일 -1~-0.5%', -1.0, -0.5),
        ('전일 -2~-1%', -2.0, -1.0),
        ('전일 -3~-2%', -3.0, -2.0),
        ('전일 -3% 이하', -999, -3.0),
    ]

    print(f'\n  {"구간":<20} {"일수":>5} {"거래":>5} {"승":>4} {"패":>4} '
          f'{"승률":>6} {"평균PnL":>8} {"손절":>5} {"익절":>5}')
    print('  ' + '-' * 80)

    for label, low, high in buckets:
        matched_dates = []
        for date in base_df['date'].unique():
            worst = get_prev_day_worst(market_data, all_market_dates, date)
            if low <= worst < high:
                matched_dates.append(date)
            elif low == -999 and worst < high:
                matched_dates.append(date)

        day_trades = base_df[base_df['date'].isin(matched_dates)]
        n = len(day_trades)
        if n == 0:
            print(f'  {label:<20} {len(matched_dates):>4}일 {0:>4}건 {0:>3}승 {0:>3}패 '
                  f'{"N/A":>6} {"N/A":>8} {0:>4}건 {0:>4}건')
            continue

        wins = (day_trades['result'] == 'WIN').sum()
        losses = n - wins
        winrate = wins / n * 100
        avg_pnl = day_trades['pnl'].mean()
        sl_cnt = (day_trades['exit_reason'] == '손절').sum()
        tp_cnt = (day_trades['exit_reason'] == '익절').sum()

        print(f'  {label:<20} {len(matched_dates):>4}일 {n:>4}건 {wins:>3}승 {losses:>3}패 '
              f'{winrate:>5.1f}% {avg_pnl:>+7.2f}% {sl_cnt:>4}건 {tp_cnt:>4}건')

    elapsed = time_module.time() - t0
    print(f'\n총 소요시간: {elapsed:.0f}초')
    print('Done!')


def main():
    parser = argparse.ArgumentParser(description='손절축소 멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260324', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    parser.add_argument('--cost', type=float, default=0.33,
                        help='건당 왕복 비용 %% (기본 0.33%%)')
    args = parser.parse_args()

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        max_daily=args.max_daily,
        cost_pct=args.cost,
    )


if __name__ == '__main__':
    main()
