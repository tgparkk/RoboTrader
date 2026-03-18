"""
매수 시작 시간 멀티버스 시뮬레이션

전략의 매수 시작 시간을 변경했을 때 성과가 어떻게 달라지는지 비교.
기본 시뮬을 한 번 실행(start_hour=9)한 뒤, 진입 시간별로 필터링하여 다수의 시나리오를 빠르게 비교.

시나리오:
- 9:00~ (현재), 9:15~, 9:30~, 9:45~, 10:00~, 10:30~, 11:00~
- 종료 시간도 별도 테스트: ~11:00, ~12:00(현재), ~13:00, ~14:00
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
    apply_screener_filter, apply_daily_limit,
    calc_fixed_capital_returns, calc_capital_returns,
)


def collect_all_trades(start_date, end_date, config, screener_top_n=60,
                       screener_min_amount=1e9, screener_max_gap=3.0,
                       screener_min_price=5000, screener_max_price=500000,
                       max_holding_minutes=0, verbose=True):
    """
    매수 시간 제한 없이(9~15시) 모든 가능한 진입을 수집.
    이후 시간 필터링으로 멀티버스 비교.
    """
    # 9시~15시 전체를 스캔하는 config
    wide_config = {**config, 'entry_start_hour': 9, 'entry_end_hour': 15}
    strategy = PricePositionStrategy(config=wide_config)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'총 거래일: {len(trading_dates)}일')

    all_trades = []

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 처리 중... '
                  f'거래 {len(all_trades)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=screener_top_n,
            min_price=screener_min_price,
            max_price=screener_max_price,
            min_amount=screener_min_amount,
            max_gap_pct=screener_max_gap,
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

                    result = strategy.simulate_trade(df, candle_idx, max_holding_minutes)
                    if result:
                        pct_from_open = (current_price / day_open - 1) * 100
                        all_trades.append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            'entry_time_str': current_time,
                            **result,
                        })
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'전체 수집 완료: {len(all_trades)}건')
    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


def time_to_minutes(t):
    """시간 문자열(HHMMSS or HHMM)을 분 단위로 변환"""
    s = str(t).zfill(6)
    return int(s[:2]) * 60 + int(s[2:4])


def filter_by_time_window(trades_df, start_minutes, end_minutes, max_daily=5):
    """진입 시간 범위로 필터링 후 동시보유 제한 적용"""
    if trades_df is None or len(trades_df) == 0:
        return pd.DataFrame()

    filtered = trades_df[
        (trades_df['entry_minutes'] >= start_minutes) &
        (trades_df['entry_minutes'] < end_minutes)
    ].copy()

    if len(filtered) == 0:
        return pd.DataFrame()

    if max_daily > 0:
        filtered = apply_daily_limit(filtered, max_daily)

    return filtered


def calc_stats(df, cost_pct=0.33, initial_capital=10_000_000, buy_ratio=0.20):
    """통계 계산"""
    if df is None or len(df) == 0:
        return None

    total = len(df)
    wins = (df['result'] == 'WIN').sum()
    losses = (df['result'] == 'LOSS').sum()
    winrate = wins / total * 100
    avg_pnl = df['pnl'].mean()
    avg_net = avg_pnl - cost_pct

    avg_win = df[df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
    avg_loss = df[df['result'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    cap_fixed = calc_fixed_capital_returns(df, initial_capital, buy_ratio, cost_pct)

    # 손절 건수
    stop_loss_count = len(df[df['exit_reason'] == '손절']) if 'exit_reason' in df.columns else 0

    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'winrate': winrate,
        'avg_pnl': avg_pnl,
        'avg_net': avg_net,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'pl_ratio': pl_ratio,
        'fixed_return': cap_fixed['total_return_pct'],
        'final_capital': cap_fixed['final_capital'],
        'stop_loss_count': stop_loss_count,
        'monthly_returns': cap_fixed['monthly_returns'],
    }


def run_multiverse(start_date, end_date, cost_pct=0.33, max_daily=5, verbose=True):
    """매수 시작 시간 멀티버스 실행"""

    # 기본 설정 로드
    defaults = PricePositionStrategy._load_default_config()
    config = {
        'min_pct_from_open': defaults['min_pct_from_open'],
        'max_pct_from_open': defaults['max_pct_from_open'],
        'stop_loss_pct': defaults['stop_loss_pct'],
        'take_profit_pct': defaults['take_profit_pct'],
        'max_pre_volatility': defaults['max_pre_volatility'],
        'max_pre20_momentum': defaults['max_pre20_momentum'],
    }

    print('=' * 90)
    print('매수 시작 시간 멀티버스 시뮬레이션')
    print('=' * 90)
    print(f'기간: {start_date} ~ {end_date or "전체"}')
    print(f'비용: {cost_pct:.2f}%/건, 동시보유: {max_daily}종목')
    print(f'진입: 시가 대비 {config["min_pct_from_open"]}~{config["max_pct_from_open"]}%')
    print(f'손절: {config["stop_loss_pct"]}%, 익절: {config["take_profit_pct"]}%')
    print('=' * 90)

    # 1. 전체 거래 수집 (9:00~15:00)
    print('\n[Phase 1] 전체 가능 거래 수집 (9:00~15:00)...')
    all_trades = collect_all_trades(
        start_date=start_date,
        end_date=end_date,
        config=config,
        verbose=verbose,
    )

    if len(all_trades) == 0:
        print('거래 없음')
        return

    # entry_time을 분 단위로 변환
    all_trades['entry_minutes'] = all_trades['entry_time'].apply(time_to_minutes)

    # 2. 시간대별 분포 확인
    print('\n[Phase 2] 시간대별 진입 분포')
    print('-' * 50)
    all_trades['entry_hour'] = all_trades['entry_minutes'] // 60
    for h in sorted(all_trades['entry_hour'].unique()):
        f = all_trades[all_trades['entry_hour'] == h]
        w = (f['result'] == 'WIN').sum()
        avg = f['pnl'].mean()
        print(f'  {h}시대: {len(f):>5}건, 승률 {w/len(f)*100:>5.1f}%, '
              f'평균 {avg:+.2f}%')

    # 3. 멀티버스: 매수 시작 시간 변경
    print('\n' + '=' * 90)
    print('[Phase 3] 매수 시작 시간 멀티버스')
    print('=' * 90)

    # 시작 시간 시나리오 (분 단위)
    start_scenarios = [
        (9 * 60,      '09:00 (현재)'),
        (9 * 60 + 10, '09:10'),
        (9 * 60 + 15, '09:15'),
        (9 * 60 + 20, '09:20'),
        (9 * 60 + 30, '09:30'),
        (9 * 60 + 45, '09:45'),
        (10 * 60,     '10:00'),
        (10 * 60 + 30,'10:30'),
        (11 * 60,     '11:00'),
    ]

    # 종료 시간은 현재 설정(12시) 기준
    end_minutes = defaults['entry_end_hour'] * 60  # 12:00 = 720

    results = []
    for start_min, label in start_scenarios:
        filtered = filter_by_time_window(all_trades, start_min, end_minutes, max_daily)
        stats = calc_stats(filtered, cost_pct)
        if stats:
            results.append({'label': label, 'start_min': start_min, **stats})

    # 결과 테이블
    if not results:
        print('결과 없음')
        return

    # 기준 시나리오 (09:00)
    base = results[0]

    print(f'\n{"시작시간":<15} {"거래수":>6} {"승률":>7} {"순평균":>8} {"손절":>5} '
          f'{"고정수익률":>10} {"vs기준":>8}')
    print('-' * 70)
    for r in results:
        diff = r['fixed_return'] - base['fixed_return']
        marker = ' ◀ 현재' if r['start_min'] == 9 * 60 else ''
        best = ' ★' if r['fixed_return'] == max(x['fixed_return'] for x in results) else ''
        print(f'{r["label"]:<15} {r["total"]:>5}건 {r["winrate"]:>6.1f}% '
              f'{r["avg_net"]:>+7.2f}% {r["stop_loss_count"]:>4}건 '
              f'{r["fixed_return"]:>+9.2f}% {diff:>+7.2f}%p{marker}{best}')

    # 4. 멀티버스: 매수 종료 시간 변경
    print('\n' + '=' * 90)
    print('[Phase 4] 매수 종료 시간 멀티버스 (시작: 09:00 고정)')
    print('=' * 90)

    end_scenarios = [
        (10 * 60,     '~10:00'),
        (10 * 60 + 30,'~10:30'),
        (11 * 60,     '~11:00'),
        (11 * 60 + 30,'~11:30'),
        (12 * 60,     '~12:00 (현재)'),
        (13 * 60,     '~13:00'),
        (14 * 60,     '~14:00'),
        (15 * 60,     '~15:00'),
    ]

    start_minutes = 9 * 60
    end_results = []
    for end_min, label in end_scenarios:
        filtered = filter_by_time_window(all_trades, start_minutes, end_min, max_daily)
        stats = calc_stats(filtered, cost_pct)
        if stats:
            end_results.append({'label': label, 'end_min': end_min, **stats})

    if end_results:
        base_end = next((r for r in end_results if r['end_min'] == 12 * 60), end_results[0])
        print(f'\n{"종료시간":<15} {"거래수":>6} {"승률":>7} {"순평균":>8} {"손절":>5} '
              f'{"고정수익률":>10} {"vs기준":>8}')
        print('-' * 70)
        for r in end_results:
            diff = r['fixed_return'] - base_end['fixed_return']
            marker = ' ◀ 현재' if r['end_min'] == 12 * 60 else ''
            best = ' ★' if r['fixed_return'] == max(x['fixed_return'] for x in end_results) else ''
            print(f'{r["label"]:<15} {r["total"]:>5}건 {r["winrate"]:>6.1f}% '
                  f'{r["avg_net"]:>+7.2f}% {r["stop_loss_count"]:>4}건 '
                  f'{r["fixed_return"]:>+9.2f}% {diff:>+7.2f}%p{marker}{best}')

    # 5. 조합 멀티버스: 시작 × 종료
    print('\n' + '=' * 90)
    print('[Phase 5] 시작×종료 조합 TOP 10')
    print('=' * 90)

    combo_results = []
    combo_starts = [9*60, 9*60+15, 9*60+30, 9*60+45, 10*60]
    combo_ends = [10*60, 10*60+30, 11*60, 11*60+30, 12*60, 13*60, 14*60]

    for s in combo_starts:
        for e in combo_ends:
            if e <= s:
                continue
            filtered = filter_by_time_window(all_trades, s, e, max_daily)
            stats = calc_stats(filtered, cost_pct)
            if stats and stats['total'] >= 10:
                s_label = f'{s//60:02d}:{s%60:02d}'
                e_label = f'{e//60:02d}:{e%60:02d}'
                combo_results.append({
                    'label': f'{s_label}~{e_label}',
                    'start_min': s, 'end_min': e,
                    **stats
                })

    if combo_results:
        combo_results.sort(key=lambda x: x['fixed_return'], reverse=True)
        current = next((r for r in combo_results
                        if r['start_min'] == 9*60 and r['end_min'] == 12*60), None)
        current_ret = current['fixed_return'] if current else 0

        print(f'\n{"구간":<15} {"거래수":>6} {"승률":>7} {"순평균":>8} {"손절":>5} '
              f'{"고정수익률":>10} {"vs현재":>8}')
        print('-' * 70)
        shown = 0
        current_shown = False
        for r in combo_results:
            is_current = (r['start_min'] == 9*60 and r['end_min'] == 12*60)
            if shown >= 10 and not is_current:
                continue
            if is_current:
                current_shown = True
            diff = r['fixed_return'] - current_ret
            marker = ' ◀ 현재' if is_current else ''
            rank = combo_results.index(r) + 1
            print(f'{rank:>2}. {r["label"]:<12} {r["total"]:>5}건 {r["winrate"]:>6.1f}% '
                  f'{r["avg_net"]:>+7.2f}% {r["stop_loss_count"]:>4}건 '
                  f'{r["fixed_return"]:>+9.2f}% {diff:>+7.2f}%p{marker}')
            if not is_current:
                shown += 1

        if current and not current_shown:
            r = current
            rank = combo_results.index(r) + 1
            diff = 0
            print(f'...')
            print(f'{rank:>2}. {r["label"]:<12} {r["total"]:>5}건 {r["winrate"]:>6.1f}% '
                  f'{r["avg_net"]:>+7.2f}% {r["stop_loss_count"]:>4}건 '
                  f'{r["fixed_return"]:>+9.2f}% {diff:>+7.2f}%p ◀ 현재')

    # 6. 오늘 같은 날(전일 하락) 시작시간별 분석
    print('\n' + '=' * 90)
    print('[Phase 6] 전일 하락일(-1%↓) vs 정상일 - 시작시간별 비교')
    print('=' * 90)

    # 전일 지수 데이터 조회
    conn2 = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur2 = conn2.cursor()

    cur2.execute('''
        SELECT stck_bsop_date,
               ((CAST(stck_clpr AS FLOAT) / NULLIF(LAG(CAST(stck_clpr AS FLOAT)) OVER (ORDER BY stck_bsop_date), 0)) - 1) * 100 as pct_change
        FROM daily_candles
        WHERE stock_code = 'KS11'
        ORDER BY stck_bsop_date
    ''')
    kospi_daily = {row[0]: row[1] for row in cur2.fetchall() if row[1] is not None}
    cur2.close()
    conn2.close()

    # 각 거래일의 전일 KOSPI 등락률 매핑
    trading_dates_list = sorted(all_trades['date'].unique())
    date_to_prev_kospi = {}
    for i, td in enumerate(trading_dates_list):
        # 전일 거래일 찾기
        prev_dates = [d for d in kospi_daily.keys() if d < td]
        if prev_dates:
            prev_d = max(prev_dates)
            date_to_prev_kospi[td] = kospi_daily.get(prev_d, 0)

    all_trades['prev_kospi_pct'] = all_trades['date'].map(date_to_prev_kospi)
    decline_mask = all_trades['prev_kospi_pct'].fillna(0) <= -1.0
    normal_mask = all_trades['prev_kospi_pct'].fillna(0) > -1.0

    decline_trades = all_trades[decline_mask]
    normal_trades = all_trades[normal_mask]

    decline_days = decline_trades['date'].nunique()
    normal_days = normal_trades['date'].nunique()
    print(f'\n전일 하락일(-1%↓): {decline_days}일, 정상일: {normal_days}일')

    for subset_name, subset in [('전일하락(-1%↓)', decline_trades),
                                 ('정상일', normal_trades)]:
        print(f'\n--- {subset_name} ---')
        if len(subset) == 0:
            print('  거래 없음')
            continue

        sub_results = []
        for start_min, label in start_scenarios:
            filtered = filter_by_time_window(subset, start_min, end_minutes, max_daily)
            stats = calc_stats(filtered, cost_pct)
            if stats:
                sub_results.append({'label': label, 'start_min': start_min, **stats})

        if sub_results:
            sub_base = sub_results[0]
            print(f'{"시작시간":<15} {"거래수":>6} {"승률":>7} {"순평균":>8} {"손절":>5} '
                  f'{"고정수익률":>10} {"vs기준":>8}')
            print('-' * 70)
            for r in sub_results:
                diff = r['fixed_return'] - sub_base['fixed_return']
                marker = ' ◀' if r['start_min'] == 9 * 60 else ''
                best = ' ★' if r['fixed_return'] == max(x['fixed_return'] for x in sub_results) else ''
                print(f'{r["label"]:<15} {r["total"]:>5}건 {r["winrate"]:>6.1f}% '
                      f'{r["avg_net"]:>+7.2f}% {r["stop_loss_count"]:>4}건 '
                      f'{r["fixed_return"]:>+9.2f}% {diff:>+7.2f}%p{marker}{best}')

    print('\n' + '=' * 90)
    print('Done!')
    print('=' * 90)


def main():
    parser = argparse.ArgumentParser(description='매수 시작 시간 멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default=None, help='종료일')
    parser.add_argument('--cost', type=float, default=0.33, help='건당 비용 %%')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    run_multiverse(
        start_date=args.start,
        end_date=args.end,
        cost_pct=args.cost,
        max_daily=args.max_daily,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
