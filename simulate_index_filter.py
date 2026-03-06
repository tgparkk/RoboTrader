"""
장중 지수 필터 시뮬레이션

기존 simulate_with_screener.py의 결과에 지수 기반 서킷브레이커를 적용하여
수익률 변화를 비교합니다.

시나리오:
1. 기준선: 지수 필터 없음 (기존 시뮬 동일)
2. 09:01 시가 갭 체크: 지수 시가 갭 <= -1.5% → 매수 중단
3. 장중 저가 체크: 지수 저가 기준 전일 대비 <= -2.0% → 매수 중단 (근사)
4. 복합: 시가 갭 + 장중 저가 체크 모두 적용

한계:
- 장중 30분 체크는 일봉 저가로 근사 (정확한 시점 알 수 없음)
- 실제로는 저가 도달 전에 일부 매수가 발생할 수 있음 → 보수적 추정
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from simulate_with_screener import (
    get_trading_dates, get_daily_metrics, get_prev_close_map,
    apply_screener_filter, apply_daily_limit, calc_capital_returns,
)
from core.strategies.price_position_strategy import PricePositionStrategy


def load_index_data(cur, start_date, end_date=None):
    """
    KS11/KQ11 일봉 데이터 로드

    Returns:
        dict: {date: {kospi: {open, high, low, close}, kosdaq: {open, high, low, close}}}
    """
    sql = """
        SELECT stock_code, stck_bsop_date,
               CAST(stck_oprc AS FLOAT) as open,
               CAST(stck_hgpr AS FLOAT) as high,
               CAST(stck_lwpr AS FLOAT) as low,
               CAST(stck_clpr AS FLOAT) as close
        FROM daily_candles
        WHERE stock_code IN ('KS11', 'KQ11')
          AND stck_bsop_date >= %s
    """
    params = [start_date]
    if end_date:
        sql += " AND stck_bsop_date <= %s"
        params.append(end_date)
    sql += " ORDER BY stck_bsop_date"

    cur.execute(sql, params)
    rows = cur.fetchall()

    index_data = {}
    for code, date, opn, high, low, close in rows:
        if date not in index_data:
            index_data[date] = {}
        key = 'kospi' if code == 'KS11' else 'kosdaq'
        index_data[date][key] = {
            'open': opn, 'high': high, 'low': low, 'close': close
        }

    return index_data


def calc_index_signals(index_data, trading_dates, open_gap_threshold, intraday_drop_threshold):
    """
    각 거래일에 대해 지수 필터 신호 계산

    Returns:
        dict: {date: {
            kospi_prev_close, kosdaq_prev_close,
            kospi_open_gap, kosdaq_open_gap, worst_open_gap,
            kospi_intraday_drop, kosdaq_intraday_drop, worst_intraday_drop,
            block_by_open_gap, block_by_intraday,
        }}
    """
    signals = {}

    for i, date in enumerate(trading_dates):
        if i == 0:
            continue

        prev_date = trading_dates[i - 1]
        if date not in index_data or prev_date not in index_data:
            continue

        today = index_data[date]
        prev = index_data[prev_date]

        if 'kospi' not in today or 'kosdaq' not in today:
            continue
        if 'kospi' not in prev or 'kosdaq' not in prev:
            continue

        kospi_prev_close = prev['kospi']['close']
        kosdaq_prev_close = prev['kosdaq']['close']

        if kospi_prev_close <= 0 or kosdaq_prev_close <= 0:
            continue

        # 시가 갭 (09:01 체크 시뮬)
        kospi_open_gap = (today['kospi']['open'] / kospi_prev_close - 1) * 100
        kosdaq_open_gap = (today['kosdaq']['open'] / kosdaq_prev_close - 1) * 100
        worst_open_gap = min(kospi_open_gap, kosdaq_open_gap)

        # 장중 최대 하락 (저가 기준, 30분 체크 근사)
        kospi_intraday_drop = (today['kospi']['low'] / kospi_prev_close - 1) * 100
        kosdaq_intraday_drop = (today['kosdaq']['low'] / kosdaq_prev_close - 1) * 100
        worst_intraday_drop = min(kospi_intraday_drop, kosdaq_intraday_drop)

        signals[date] = {
            'kospi_prev_close': kospi_prev_close,
            'kosdaq_prev_close': kosdaq_prev_close,
            'kospi_open_gap': round(kospi_open_gap, 2),
            'kosdaq_open_gap': round(kosdaq_open_gap, 2),
            'worst_open_gap': round(worst_open_gap, 2),
            'kospi_intraday_drop': round(kospi_intraday_drop, 2),
            'kosdaq_intraday_drop': round(kosdaq_intraday_drop, 2),
            'worst_intraday_drop': round(worst_intraday_drop, 2),
            'block_by_open_gap': worst_open_gap <= open_gap_threshold,
            'block_by_intraday': worst_intraday_drop <= intraday_drop_threshold,
        }

    return signals


def run_simulation_with_index_filter(
    start_date='20250224',
    end_date=None,
    open_gap_threshold=-1.5,
    intraday_drop_threshold=-2.0,
    max_daily=5,
    verbose=True,
):
    """지수 필터 적용 시뮬레이션"""

    # 설정 로드
    import json, os
    from config.strategy_settings import StrategySettings
    pp = StrategySettings.PricePosition
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'trading_config.json')
    with open(config_path, 'r') as f:
        tc = json.load(f)
    rm = tc.get('risk_management', {})

    config = {
        'min_pct_from_open': pp.MIN_PCT_FROM_OPEN,
        'max_pct_from_open': pp.MAX_PCT_FROM_OPEN,
        'entry_start_hour': pp.ENTRY_START_HOUR,
        'entry_end_hour': pp.ENTRY_END_HOUR,
        'stop_loss_pct': -rm.get('stop_loss_ratio', 0.05) * 100,
        'take_profit_pct': rm.get('take_profit_ratio', 0.06) * 100,
        'max_pre_volatility': pp.MAX_PRE_VOLATILITY,
        'max_pre20_momentum': pp.MAX_PRE20_MOMENTUM,
    }

    strategy = PricePositionStrategy(config=config)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    # 거래일 + 지수 데이터
    trading_dates = get_trading_dates(cur, start_date, end_date)
    # 지수 데이터는 더 이전부터 필요 (전일 종가 참조)
    prev_start = str(int(start_date) - 100)  # 대략 1개월 전
    index_data = load_index_data(cur, prev_start, end_date)
    # 지수 날짜 목록 (거래일 범위보다 넓게)
    all_index_dates = sorted(index_data.keys())

    signals = calc_index_signals(index_data, all_index_dates, open_gap_threshold, intraday_drop_threshold)

    print('=' * 80)
    print('장중 지수 필터 시뮬레이션')
    print('=' * 80)
    print(f'기간: {start_date} ~ {end_date or "전체"}')
    print(f'거래일: {len(trading_dates)}일')
    print(f'지수 데이터: {len(index_data)}일')
    print(f'시가 갭 임계값: {open_gap_threshold}%')
    print(f'장중 하락 임계값: {intraday_drop_threshold}%')
    print(f'동시보유: {max_daily}종목')
    print('=' * 80)

    # 시나리오별 거래 수집
    # key: 'baseline', 'open_gap', 'intraday', 'combined'
    scenario_trades = {
        'baseline': [],
        'open_gap': [],
        'intraday': [],
        'combined': [],
    }

    blocked_days = {'open_gap': [], 'intraday': [], 'combined': []}

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date})...')

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

        # 지수 신호
        sig = signals.get(trade_date, {})
        is_open_gap_blocked = sig.get('block_by_open_gap', False)
        is_intraday_blocked = sig.get('block_by_intraday', False)

        if is_open_gap_blocked:
            blocked_days['open_gap'].append(trade_date)
        if is_intraday_blocked:
            blocked_days['intraday'].append(trade_date)
        if is_open_gap_blocked or is_intraday_blocked:
            blocked_days['combined'].append(trade_date)

        # 각 종목 시뮬
        day_trades = []
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
                    row_data = df.iloc[candle_idx]
                    current_time = str(row_data['time'])
                    current_price = row_data['close']

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

                    adv_ok, _ = strategy.check_advanced_conditions(df=df, candle_idx=candle_idx)
                    if not adv_ok:
                        continue

                    result = strategy.simulate_trade(df, candle_idx)
                    if result:
                        pct_from_open = (current_price / day_open - 1) * 100
                        trade_record = {
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            **result,
                        }
                        day_trades.append(trade_record)
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

            except Exception:
                continue

        # 시나리오별 거래 배분
        for trade in day_trades:
            scenario_trades['baseline'].append(trade)

            if not is_open_gap_blocked:
                scenario_trades['open_gap'].append(trade)

            if not is_intraday_blocked:
                scenario_trades['intraday'].append(trade)

            if not is_open_gap_blocked and not is_intraday_blocked:
                scenario_trades['combined'].append(trade)

    cur.close()
    conn.close()

    # === 결과 출력 ===
    print('\n')
    print('#' * 80)
    print('#  차단된 거래일')
    print('#' * 80)

    for name, days in blocked_days.items():
        if days:
            print(f'\n[{name}] {len(days)}일 차단:')
            for d in days:
                sig = signals.get(d, {})
                print(f'  {d}: 시가갭={sig.get("worst_open_gap", "?"):+.2f}%, '
                      f'장중저가={sig.get("worst_intraday_drop", "?"):+.2f}%')

    print('\n')
    print('#' * 80)
    print('#  시나리오별 비교')
    print('#' * 80)

    scenario_labels = {
        'baseline': '기준선 (필터 없음)',
        'open_gap': f'시가갭 체크 (<={open_gap_threshold}%)',
        'intraday': f'장중 하락 체크 (<={intraday_drop_threshold}%)',
        'combined': '복합 (시가갭 + 장중)',
    }

    results = {}
    for scenario, trades in scenario_trades.items():
        if not trades:
            results[scenario] = {
                'trades': 0, 'wins': 0, 'winrate': 0, 'avg_pnl': 0,
                'capital_return': 0, 'final_capital': 10_000_000,
            }
            continue

        df = pd.DataFrame(trades)
        limited = apply_daily_limit(df, max_daily)

        total = len(limited)
        wins = (limited['result'] == 'WIN').sum()
        winrate = wins / total * 100 if total > 0 else 0
        avg_pnl = limited['pnl'].mean() if total > 0 else 0
        cap = calc_capital_returns(limited)

        results[scenario] = {
            'trades': total,
            'wins': wins,
            'winrate': winrate,
            'avg_pnl': avg_pnl,
            'capital_return': cap['total_return_pct'],
            'final_capital': cap['final_capital'],
        }

    # 비교 테이블
    print(f'\n{"시나리오":>30} {"거래수":>8} {"승률":>8} {"평균수익":>10} {"원금수익률":>12} {"최종자본":>14}')
    print('-' * 90)
    for scenario in ['baseline', 'open_gap', 'intraday', 'combined']:
        r = results[scenario]
        label = scenario_labels[scenario]
        print(f'{label:>30} {r["trades"]:>7}건 {r["winrate"]:>7.1f}% '
              f'{r["avg_pnl"]:>+9.2f}% {r["capital_return"]:>+11.2f}% '
              f'{r["final_capital"]/10000:>12,.0f}만')

    # 차단일 상세: 해당 날 거래가 있었으면 그 거래 결과 표시
    combined_blocked = set(blocked_days['combined'])
    if combined_blocked:
        print('\n')
        print('#' * 80)
        print('#  차단일의 원래 거래 결과 (필터 없었을 때)')
        print('#' * 80)

        baseline_df = pd.DataFrame(scenario_trades['baseline'])
        if len(baseline_df) > 0:
            blocked_trades = baseline_df[baseline_df['date'].isin(combined_blocked)]
            if len(blocked_trades) > 0:
                limited_blocked = apply_daily_limit(blocked_trades, max_daily)
                for date in sorted(combined_blocked):
                    dt = limited_blocked[limited_blocked['date'] == date]
                    if len(dt) == 0:
                        sig = signals.get(date, {})
                        print(f'  {date}: 거래 없음 (갭={sig.get("worst_open_gap", "?"):+.2f}%)')
                        continue
                    wins = (dt['result'] == 'WIN').sum()
                    total_pnl = dt['pnl'].sum()
                    trades_str = ', '.join(
                        f'{r["stock_code"]}({r["pnl"]:+.1f}%)' for _, r in dt.iterrows()
                    )
                    sig = signals.get(date, {})
                    print(f'  {date}: {len(dt)}건 {wins}승 합계{total_pnl:+.1f}% '
                          f'(갭={sig.get("worst_open_gap", "?"):+.2f}%, '
                          f'저가={sig.get("worst_intraday_drop", "?"):+.2f}%) '
                          f'[{trades_str}]')

                total_blocked_pnl = limited_blocked['pnl'].sum()
                avg_blocked_pnl = limited_blocked['pnl'].mean()
                blocked_wins = (limited_blocked['result'] == 'WIN').sum()
                print(f'\n  차단 거래 요약: {len(limited_blocked)}건, {blocked_wins}승, '
                      f'평균{avg_blocked_pnl:+.2f}%, 합계{total_blocked_pnl:+.1f}%')

                if avg_blocked_pnl < 0:
                    print(f'  → 평균 마이너스: 필터가 효과적!')
                else:
                    print(f'  → 평균 플러스: 필터가 수익 기회를 제거함 (재검토 필요)')

    # 개선도 요약
    baseline_ret = results['baseline']['capital_return']
    print('\n')
    print('#' * 80)
    print('#  개선도 요약')
    print('#' * 80)
    for scenario in ['open_gap', 'intraday', 'combined']:
        r = results[scenario]
        diff = r['capital_return'] - baseline_ret
        label = scenario_labels[scenario]
        sign = '+' if diff >= 0 else ''
        removed = results['baseline']['trades'] - r['trades']
        print(f'  {label}: {sign}{diff:.2f}%p (거래 {removed}건 제거)')

    print('\nDone!')
    return results


def main():
    parser = argparse.ArgumentParser(description='장중 지수 필터 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default=None, help='종료일')
    parser.add_argument('--open-gap', type=float, default=-1.5,
                        help='시가 갭 임계값 (%%, default: -1.5)')
    parser.add_argument('--intraday-drop', type=float, default=-2.0,
                        help='장중 하락 임계값 (%%, default: -2.0)')
    parser.add_argument('--max-daily', type=int, default=5,
                        help='동시보유 최대 (default: 5)')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    run_simulation_with_index_filter(
        start_date=args.start,
        end_date=args.end,
        open_gap_threshold=args.open_gap,
        intraday_drop_threshold=args.intraday_drop,
        max_daily=args.max_daily,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
