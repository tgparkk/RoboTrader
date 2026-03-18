"""
현실적 스크리너 vs 기존 스크리너 비교 시뮬레이션

핵심 차이:
- 기존: 하루 전체 거래대금으로 상위 60개 선별 (미래참조 편향)
- 현실적: 해당 시점까지 누적 거래대금으로 선별 (실시간 스크리너와 동일)

실거래 스크리너 동작:
- 9:05부터 11:50까지 2분 간격으로 거래량순위 API 호출
- 후보 풀은 누적됨 (한번 발견된 종목은 계속 후보)
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy
from simulate_with_screener import (
    get_trading_dates, get_prev_close_map,
    apply_daily_limit, calc_fixed_capital_returns, print_stats,
)


# 스크리너 체크포인트 (실거래: 9:05~11:50, 2분 간격 → 시뮬: 10분 간격으로 근사)
SCREENER_CHECKPOINTS = [
    '091000', '092000', '093000', '094000', '095000',
    '100000', '101000', '102000', '103000', '104000', '105000',
    '110000', '111000', '112000', '113000', '114000', '115000',
]


def get_cumulative_metrics(cur, trade_date):
    """
    시간대별 누적 거래대금 + 시가 계산.
    각 체크포인트까지의 누적 거래대금을 한 쿼리로 조회.
    """
    # 동적 SUM CASE WHEN 생성
    sum_clauses = []
    for cp in SCREENER_CHECKPOINTS:
        sum_clauses.append(
            f"SUM(CASE WHEN time <= '{cp}' THEN amount ELSE 0 END) as amt_{cp}"
        )

    sql = f'''
        SELECT
            stock_code,
            MIN(CASE WHEN time >= '090000' AND time <= '090300' THEN open END) as day_open,
            {', '.join(sum_clauses)}
        FROM minute_candles
        WHERE trade_date = %s
        GROUP BY stock_code
        HAVING COUNT(*) >= 50
    '''
    cur.execute(sql, [trade_date])

    results = {}
    for row in cur.fetchall():
        stock_code = row[0]
        day_open = row[1]
        if not day_open or float(day_open) <= 0:
            continue

        cumulative = {}
        for i, cp in enumerate(SCREENER_CHECKPOINTS):
            cumulative[cp] = float(row[2 + i] or 0)

        results[stock_code] = {
            'day_open': float(day_open),
            'cumulative': cumulative,
        }

    return results


def build_realistic_candidate_pool(
    cumulative_metrics, prev_close_map,
    top_n=60,
    min_price=5000, max_price=500000,
    max_gap_pct=3.0,
):
    """
    시간대별 누적 거래대금으로 후보 풀 구축 (미래참조 제거).

    각 체크포인트에서:
    1. 누적 거래대금 상위 top_n개 선별
    2. 기본 필터 적용
    3. 새로 통과한 종목을 후보 풀에 추가 (발견 시점 기록)

    Returns:
        {stock_code: discovery_time} - 종목별 최초 발견 시점
    """
    candidate_pool = {}  # {stock_code: first_discovered_checkpoint}

    for cp in SCREENER_CHECKPOINTS:
        # 이 체크포인트 기준 누적 거래대금으로 랭킹
        ranked = sorted(
            cumulative_metrics.items(),
            key=lambda x: x[1]['cumulative'].get(cp, 0),
            reverse=True
        )[:top_n]

        for stock_code, metrics in ranked:
            if stock_code in candidate_pool:
                continue  # 이미 발견됨

            day_open = metrics['day_open']

            # 우선주 제외
            if stock_code[-1] == '5':
                continue

            # 가격 필터
            if not (min_price <= day_open <= max_price):
                continue

            # 누적 거래대금이 0이면 스킵
            if metrics['cumulative'].get(cp, 0) <= 0:
                continue

            # 갭 필터
            prev_close = prev_close_map.get(stock_code)
            if prev_close and prev_close > 0:
                gap_pct = abs(day_open / prev_close - 1) * 100
                if gap_pct > max_gap_pct:
                    continue

            candidate_pool[stock_code] = cp

    return candidate_pool


def run_comparison(
    start_date='20250224',
    end_date=None,
    max_daily=5,
    screener_top_n=60,
    screener_max_gap=3.0,
    screener_min_price=5000,
    screener_max_price=500000,
    screener_min_amount=1_000_000_000,
    cost_pct=0.33,
    max_holding_minutes=0,
    verbose=True,
):
    """기존 vs 현실적 스크리너 비교 시뮬레이션"""

    # 전략 설정 로드
    defaults = PricePositionStrategy._load_default_config()
    config = {
        'min_pct_from_open': defaults['min_pct_from_open'],
        'max_pct_from_open': defaults['max_pct_from_open'],
        'entry_start_hour': defaults['entry_start_hour'],
        'entry_end_hour': defaults['entry_end_hour'],
        'stop_loss_pct': defaults['stop_loss_pct'],
        'take_profit_pct': defaults['take_profit_pct'],
        'max_pre_volatility': defaults['max_pre_volatility'],
        'max_pre20_momentum': defaults['max_pre20_momentum'],
    }

    strategy_old = PricePositionStrategy(config=config)
    strategy_new = PricePositionStrategy(config=config)
    info = strategy_old.get_strategy_info()

    print('=' * 80)
    print('현실적 스크리너 vs 기존 스크리너 비교 시뮬레이션')
    print('=' * 80)
    print(f"진입: 시가 대비 {info['entry_conditions']['pct_from_open']}, "
          f"{info['entry_conditions']['time_range']}")
    print(f"청산: 손절 {info['exit_conditions']['stop_loss']}, "
          f"익절 {info['exit_conditions']['take_profit']}")
    print(f"비용: {cost_pct:.2f}%/건, 동시보유: {max_daily}종목")
    print(f"기간: {start_date} ~ {end_date or '전체'}")
    print(f"체크포인트: {len(SCREENER_CHECKPOINTS)}개 "
          f"({SCREENER_CHECKPOINTS[0][:4]}~{SCREENER_CHECKPOINTS[-1][:4]})")
    print('=' * 80)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    old_trades = []  # 기존 (미래참조)
    new_trades = []  # 현실적 (시점 누적)
    pool_stats = {'old_total': 0, 'new_total': 0, 'overlap': 0, 'days': 0}

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 10 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 처리 중... '
                  f'기존 {len(old_trades)}건, 현실적 {len(new_trades)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        # 전일 종가
        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        # === 누적 지표 조회 (현실적 스크리너용) ===
        cumulative_metrics = get_cumulative_metrics(cur, trade_date)
        if not cumulative_metrics:
            continue

        # === 기존 스크리너: 하루 전체 거래대금 ===
        # cumulative_metrics에서 daily_amount는 마지막 체크포인트 값으로 근사
        # (실제로는 전체 합이지만, 11:50까지의 누적으로 충분히 유사)
        from simulate_with_screener import get_daily_metrics, apply_screener_filter
        daily_metrics = get_daily_metrics(cur, trade_date)
        old_screened = set()
        if daily_metrics:
            old_screened = apply_screener_filter(
                daily_metrics, prev_close_map,
                top_n=screener_top_n,
                min_price=screener_min_price,
                max_price=screener_max_price,
                min_amount=screener_min_amount,
                max_gap_pct=screener_max_gap,
            )

        # === 현실적 스크리너: 시점별 누적 거래대금 ===
        new_candidate_pool = build_realistic_candidate_pool(
            cumulative_metrics, prev_close_map,
            top_n=screener_top_n,
            min_price=screener_min_price,
            max_price=screener_max_price,
            max_gap_pct=screener_max_gap,
        )
        new_screened = set(new_candidate_pool.keys())

        # 후보 풀 통계
        pool_stats['old_total'] += len(old_screened)
        pool_stats['new_total'] += len(new_screened)
        pool_stats['overlap'] += len(old_screened & new_screened)
        pool_stats['days'] += 1

        # === 양쪽 모두에 대해 전략 실행 ===
        all_candidates = old_screened | new_screened

        for stock_code in all_candidates:
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

                # 시가
                day_open = None
                if stock_code in daily_metrics:
                    day_open = daily_metrics[stock_code]['day_open']
                elif stock_code in cumulative_metrics:
                    day_open = cumulative_metrics[stock_code]['day_open']
                if not day_open or day_open <= 0:
                    continue

                # 기존 스크리너용 (미래참조)
                in_old = stock_code in old_screened
                # 현실적 스크리너용
                in_new = stock_code in new_candidate_pool
                new_discovery_time = new_candidate_pool.get(stock_code, '999999')

                traded_old = False
                traded_new = False

                for candle_idx in range(10, len(df) - 10):
                    if traded_old and traded_new:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time']).zfill(6)
                    current_price = row['close']

                    # 기존: check_entry_conditions
                    if in_old and not traded_old:
                        can_enter, reason = strategy_old.check_entry_conditions(
                            stock_code=stock_code,
                            current_price=current_price,
                            day_open=day_open,
                            current_time=current_time,
                            trade_date=trade_date,
                            weekday=weekday,
                        )
                        if can_enter:
                            adv_ok, _ = strategy_old.check_advanced_conditions(
                                df=df, candle_idx=candle_idx
                            )
                            if adv_ok:
                                result = strategy_old.simulate_trade(
                                    df, candle_idx, max_holding_minutes
                                )
                                if result:
                                    pct_from_open = (current_price / day_open - 1) * 100
                                    old_trades.append({
                                        'date': trade_date,
                                        'stock_code': stock_code,
                                        'weekday': weekday,
                                        'pct_from_open': pct_from_open,
                                        **result,
                                    })
                                    strategy_old.record_trade(stock_code, trade_date)
                                    traded_old = True

                    # 현실적: 발견 시점 이후에만 진입 가능
                    if in_new and not traded_new:
                        # 발견 시점 이전이면 아직 후보 아님
                        if current_time < new_discovery_time:
                            continue

                        can_enter, reason = strategy_new.check_entry_conditions(
                            stock_code=stock_code,
                            current_price=current_price,
                            day_open=day_open,
                            current_time=current_time,
                            trade_date=trade_date,
                            weekday=weekday,
                        )
                        if can_enter:
                            adv_ok, _ = strategy_new.check_advanced_conditions(
                                df=df, candle_idx=candle_idx
                            )
                            if adv_ok:
                                result = strategy_new.simulate_trade(
                                    df, candle_idx, max_holding_minutes
                                )
                                if result:
                                    pct_from_open = (current_price / day_open - 1) * 100
                                    new_trades.append({
                                        'date': trade_date,
                                        'stock_code': stock_code,
                                        'weekday': weekday,
                                        'pct_from_open': pct_from_open,
                                        **result,
                                    })
                                    strategy_new.record_trade(stock_code, trade_date)
                                    traded_new = True

            except Exception:
                continue

    cur.close()
    conn.close()

    # === 결과 출력 ===
    days = max(pool_stats['days'], 1)
    print(f'\n후보 풀 통계 (일평균):')
    print(f'  기존 (미래참조): {pool_stats["old_total"]/days:.1f}개')
    print(f'  현실적 (시점누적): {pool_stats["new_total"]/days:.1f}개')
    print(f'  겹치는 종목: {pool_stats["overlap"]/days:.1f}개 '
          f'({pool_stats["overlap"]/max(pool_stats["old_total"],1)*100:.0f}%)')

    print(f'\n총 거래: 기존 {len(old_trades)}건, 현실적 {len(new_trades)}건')

    # 기존 결과
    if old_trades:
        old_df = pd.DataFrame(old_trades)
        old_limited = apply_daily_limit(old_df, max_daily) if max_daily > 0 else old_df
        old_daily = defaultdict(list)
        for _, row in old_limited.iterrows():
            old_daily[row['date']].append(row.to_dict())
        print_stats(old_limited, old_daily, f'기존 스크리너 (미래참조, {max_daily}종목)',
                    cost_pct=cost_pct)
    else:
        old_limited = pd.DataFrame()

    # 현실적 결과
    if new_trades:
        new_df = pd.DataFrame(new_trades)
        new_limited = apply_daily_limit(new_df, max_daily) if max_daily > 0 else new_df
        new_daily = defaultdict(list)
        for _, row in new_limited.iterrows():
            new_daily[row['date']].append(row.to_dict())
        print_stats(new_limited, new_daily, f'현실적 스크리너 (시점누적, {max_daily}종목)',
                    cost_pct=cost_pct)
    else:
        new_limited = pd.DataFrame()

    # === 비교 요약 ===
    print('\n' + '=' * 80)
    print('비교 요약 (고정자본 기준)')
    print('=' * 80)

    def summarize(df, label):
        if df is None or len(df) == 0:
            return None
        total = len(df)
        wins = (df['result'] == 'WIN').sum()
        winrate = wins / total * 100
        avg_net = df['pnl'].mean() - cost_pct
        stop_count = len(df[df['exit_reason'] == '손절'])
        cap = calc_fixed_capital_returns(df, cost_pct=cost_pct)
        return {
            'label': label, 'total': total, 'wins': wins, 'winrate': winrate,
            'avg_net': avg_net, 'stop_count': stop_count,
            'fixed_return': cap['total_return_pct'],
        }

    old_s = summarize(old_limited, '기존 (미래참조)')
    new_s = summarize(new_limited, '현실적 (시점누적)')

    if old_s and new_s:
        print(f'\n{"":>20} {"기존(미래참조)":>15} {"현실적(시점누적)":>15} {"차이":>10}')
        print('-' * 65)
        print(f'{"거래수":>20} {old_s["total"]:>14}건 {new_s["total"]:>14}건 '
              f'{new_s["total"]-old_s["total"]:>+9}건')
        print(f'{"승률":>20} {old_s["winrate"]:>13.1f}% {new_s["winrate"]:>13.1f}% '
              f'{new_s["winrate"]-old_s["winrate"]:>+8.1f}%p')
        print(f'{"순평균수익률":>20} {old_s["avg_net"]:>+13.2f}% {new_s["avg_net"]:>+13.2f}% '
              f'{new_s["avg_net"]-old_s["avg_net"]:>+8.2f}%p')
        print(f'{"손절건수":>20} {old_s["stop_count"]:>13}건 {new_s["stop_count"]:>13}건 '
              f'{new_s["stop_count"]-old_s["stop_count"]:>+9}건')
        print(f'{"고정자본수익률":>20} {old_s["fixed_return"]:>+13.2f}% '
              f'{new_s["fixed_return"]:>+13.2f}% '
              f'{new_s["fixed_return"]-old_s["fixed_return"]:>+8.2f}%p')

        # 겹치는 거래 분석
        if len(old_limited) > 0 and len(new_limited) > 0:
            old_keys = set(zip(old_limited['date'], old_limited['stock_code']))
            new_keys = set(zip(new_limited['date'], new_limited['stock_code']))
            common = old_keys & new_keys
            old_only = old_keys - new_keys
            new_only = new_keys - old_keys

            print(f'\n거래 겹침 분석:')
            print(f'  동일 거래: {len(common)}건')
            print(f'  기존에만 있는 거래: {len(old_only)}건 (미래참조로 선별된 종목)')
            print(f'  현실적에만 있는 거래: {len(new_only)}건')

            # 기존에만 있는 거래의 성과
            if old_only:
                old_only_df = old_limited[
                    old_limited.apply(lambda r: (r['date'], r['stock_code']) in old_only, axis=1)
                ]
                avg = old_only_df['pnl'].mean()
                wr = (old_only_df['result'] == 'WIN').sum() / len(old_only_df) * 100
                print(f'    -> 미래참조 전용 거래 성과: {len(old_only_df)}건, '
                      f'승률 {wr:.1f}%, 평균 {avg:+.2f}%')

    print('\nDone!')


def main():
    parser = argparse.ArgumentParser(description='현실적 스크리너 비교 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default=None, help='종료일')
    parser.add_argument('--cost', type=float, default=0.33, help='건당 비용 %%')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    parser.add_argument('--screener-top', type=int, default=60, help='거래대금 상위 N개')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    run_comparison(
        start_date=args.start,
        end_date=args.end,
        cost_pct=args.cost,
        max_daily=args.max_daily,
        screener_top_n=args.screener_top,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
