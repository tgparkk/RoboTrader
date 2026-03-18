"""
스크리너 필터 통합 시뮬레이션

기존 simulate_price_position_strategy.py와 동일한 전략 로직에
실시간 스크리너의 후보 선정 필터를 추가하여 실거래와 동일한 조건으로 백테스트.

차이점:
- 기존: DB의 모든 종목을 스캔 (927개)
- 신규: 각 거래일마다 거래대금 상위 60개만 선별 → 스크리너 필터 적용 → 전략 실행
"""

import psycopg2
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
import argparse
import time as time_module

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


def get_trading_dates(cur, start_date, end_date=None):
    """거래일 목록 조회"""
    sql = "SELECT DISTINCT trade_date FROM minute_candles WHERE trade_date >= %s"
    params = [start_date]
    if end_date:
        sql += " AND trade_date <= %s"
        params.append(end_date)
    sql += " ORDER BY trade_date"
    cur.execute(sql, params)
    return [row[0] for row in cur.fetchall()]


def get_prev_close_map(cur, trade_date, prev_date):
    """전일 종가 맵 생성 {stock_code: prev_close}"""
    cur.execute('''
        SELECT stock_code, close
        FROM minute_candles
        WHERE trade_date = %s
          AND idx = (
            SELECT MAX(idx) FROM minute_candles mc2
            WHERE mc2.stock_code = minute_candles.stock_code
              AND mc2.trade_date = %s
          )
    ''', [prev_date, prev_date])
    return {row[0]: row[1] for row in cur.fetchall()}


def get_daily_metrics(cur, trade_date):
    """
    해당 거래일의 종목별 일간 지표 계산

    Returns:
        {stock_code: {day_open, daily_amount, first_close, last_close, max_price, min_price}}
    """
    cur.execute('''
        SELECT
            stock_code,
            MIN(CASE WHEN time >= '090000' AND time <= '090300' THEN open END) as day_open,
            SUM(amount) as daily_amount,
            MAX(close) as max_price,
            MIN(close) as min_price
        FROM minute_candles
        WHERE trade_date = %s
        GROUP BY stock_code
        HAVING COUNT(*) >= 50
    ''', [trade_date])

    metrics = {}
    for row in cur.fetchall():
        stock_code, day_open, daily_amount, max_price, min_price = row
        if day_open and day_open > 0 and daily_amount:
            metrics[stock_code] = {
                'day_open': float(day_open),
                'daily_amount': float(daily_amount),
                'max_price': float(max_price),
                'min_price': float(min_price),
            }
    return metrics


def apply_screener_filter(
    daily_metrics, prev_close_map,
    top_n=60,
    min_price=5000, max_price=500000,
    min_amount=1_000_000_000,
    max_gap_pct=3.0,
):
    """
    스크리너 필터 적용 (Phase 1 + Phase 2 시뮬레이션)

    Phase 1 시뮬: 거래대금 상위 top_n개 선별 (거래량순위 API 대용)
    Phase 2: 가격 범위, 거래대금, 갭 필터

    Args:
        daily_metrics: {stock_code: {day_open, daily_amount, max_price, min_price}}
        prev_close_map: {stock_code: prev_close}
        top_n: 거래대금 상위 N개 (volume rank API 시뮬)

    Returns:
        스크리너 통과 종목 set
    """
    # Phase 1: 거래대금 상위 N개
    ranked = sorted(
        daily_metrics.items(),
        key=lambda x: x[1]['daily_amount'],
        reverse=True
    )[:top_n]

    passed = set()
    for stock_code, metrics in ranked:
        day_open = metrics['day_open']

        # 우선주 제외
        if stock_code[-1] == '5':
            continue

        # 가격 필터
        if not (min_price <= day_open <= max_price):
            continue

        # 거래대금 필터
        if metrics['daily_amount'] < min_amount:
            continue

        # 갭 필터 (시가 vs 전일종가)
        prev_close = prev_close_map.get(stock_code)
        if prev_close and prev_close > 0:
            gap_pct = abs(day_open / prev_close - 1) * 100
            if gap_pct > max_gap_pct:
                continue

        passed.add(stock_code)

    return passed


def apply_daily_limit(trades_df, max_daily):
    """동시 보유 제한 적용"""
    limited = []
    for date in trades_df['date'].unique():
        day_trades = trades_df[trades_df['date'] == date].copy()
        day_trades = day_trades.sort_values('entry_time')

        accepted = []
        for _, trade in day_trades.iterrows():
            entry_t = str(trade['entry_time']).zfill(6)
            exit_t = str(trade['exit_time']).zfill(6)
            holding = sum(1 for _, et in accepted if et > entry_t)
            if holding < max_daily:
                accepted.append((entry_t, exit_t))
                limited.append(trade)

    return pd.DataFrame(limited).reset_index(drop=True) if limited else pd.DataFrame()


def calc_capital_returns(trades_df, initial_capital=10_000_000, buy_ratio=0.20,
                         cost_pct=0.0):
    """
    원금 기반 누적 수익률 계산

    날짜순으로 거래를 처리하며, 각 거래의 투자금 = 당시 자본 * buy_ratio.
    동일 날짜 내 거래는 해당 날짜 시작 자본 기준으로 계산 (장중 자본 변동 미반영).

    Args:
        cost_pct: 건당 왕복 비용 (수수료+세금+슬리피지). 예: 0.3 = 0.3%

    Returns:
        dict: {final_capital, total_return_pct, monthly_returns: {month: pct}}
    """
    if trades_df is None or len(trades_df) == 0:
        return {'final_capital': initial_capital, 'total_return_pct': 0.0, 'monthly_returns': {}}

    capital = initial_capital
    monthly_returns = {}  # month -> (start_capital, end_capital)
    current_month = None
    month_start_capital = capital

    for date in sorted(trades_df['date'].unique()):
        month = date[:6]
        if month != current_month:
            if current_month is not None:
                monthly_returns[current_month] = (month_start_capital, capital)
            current_month = month
            month_start_capital = capital

        day_trades = trades_df[trades_df['date'] == date]
        day_start_capital = capital

        for _, trade in day_trades.iterrows():
            invest_amount = day_start_capital * buy_ratio
            net_pnl = trade['pnl'] - cost_pct
            profit = invest_amount * (net_pnl / 100)
            capital += profit

    # 마지막 월 마무리
    if current_month is not None:
        monthly_returns[current_month] = (month_start_capital, capital)

    total_return_pct = (capital / initial_capital - 1) * 100
    monthly_pcts = {}
    for m, (s, e) in monthly_returns.items():
        monthly_pcts[m] = (e / s - 1) * 100 if s > 0 else 0.0

    return {
        'final_capital': capital,
        'total_return_pct': total_return_pct,
        'monthly_returns': monthly_pcts,
    }


def calc_fixed_capital_returns(trades_df, initial_capital=10_000_000, buy_ratio=0.20,
                                cost_pct=0.0):
    """
    고정자본 수익률 계산 (복리 없음)

    매 거래의 투자금 = 초기자본 * buy_ratio (고정).
    복리 효과를 제거하여 전략 자체의 순수 성과를 측정.
    """
    if trades_df is None or len(trades_df) == 0:
        return {'final_capital': initial_capital, 'total_return_pct': 0.0,
                'monthly_returns': {}, 'total_profit': 0}

    invest_amount = initial_capital * buy_ratio  # 고정
    total_profit = 0
    monthly_profits = {}  # month -> profit_won
    current_month = None

    for date in sorted(trades_df['date'].unique()):
        month = date[:6]
        if month != current_month:
            current_month = month
            if month not in monthly_profits:
                monthly_profits[month] = 0

        day_trades = trades_df[trades_df['date'] == date]
        for _, trade in day_trades.iterrows():
            net_pnl = trade['pnl'] - cost_pct
            profit = invest_amount * (net_pnl / 100)
            total_profit += profit
            monthly_profits[month] += profit

    total_return_pct = total_profit / initial_capital * 100
    monthly_pcts = {m: p / initial_capital * 100 for m, p in monthly_profits.items()}

    return {
        'final_capital': initial_capital + total_profit,
        'total_return_pct': total_return_pct,
        'monthly_returns': monthly_pcts,
        'total_profit': total_profit,
    }


def print_stats(trades_df, daily_results, label, initial_capital=10_000_000, buy_ratio=0.20,
                cost_pct=0.0):
    """거래 통계 출력"""
    if len(trades_df) == 0:
        print(f'\n[{label}] 거래 없음')
        return

    wins = (trades_df['result'] == 'WIN').sum()
    losses = (trades_df['result'] == 'LOSS').sum()
    total = len(trades_df)
    winrate = wins / total * 100
    avg_pnl = trades_df['pnl'].mean()
    avg_net = avg_pnl - cost_pct

    avg_win = trades_df[trades_df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
    avg_loss = trades_df[trades_df['result'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # 수익률 계산 (비용 적용)
    cap_compound = calc_capital_returns(trades_df, initial_capital, buy_ratio, cost_pct)
    cap_fixed = calc_fixed_capital_returns(trades_df, initial_capital, buy_ratio, cost_pct)

    print('\n' + '=' * 80)
    print(f'전체 통계 [{label}]')
    print(f'  (초기자본: {initial_capital/10000:,.0f}만원, 건당 투자비율: {buy_ratio:.0%},'
          f' 비용: {cost_pct:.2f}%/건)')
    print('=' * 80)
    print(f'총 거래: {total}건 ({wins}승 {losses}패)')
    print(f'승률: {winrate:.1f}%')
    print(f'평균 수익률: {avg_pnl:+.2f}% (건당, 비용 전)')
    print(f'평균 순수익률: {avg_net:+.2f}% (건당, 비용 {cost_pct:.2f}% 차감)')
    print(f'평균 승리: {avg_win:+.2f}% | 평균 손실: {avg_loss:.2f}%')
    print(f'손익비: {pl_ratio:.2f}:1')
    print()
    print(f'  [고정자본] 수익률: {cap_fixed["total_return_pct"]:+.2f}% '
          f'({initial_capital/10000:,.0f}만 → {cap_fixed["final_capital"]/10000:,.0f}만원)')
    print(f'  [복리자본] 수익률: {cap_compound["total_return_pct"]:+.2f}% '
          f'({initial_capital/10000:,.0f}만 → {cap_compound["final_capital"]/10000:,.0f}만원)')

    # 요일별
    print('\n' + '-' * 60)
    print(f'요일별 [{label}]')
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    for wd in sorted(trades_df['weekday'].unique()):
        f = trades_df[trades_df['weekday'] == wd]
        if len(f) == 0:
            continue
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        avg = f['pnl'].mean()
        print(f'  {weekday_names[wd]}: {len(f)}건, {w}승 {len(f)-w}패, {rate:.1f}%, 평균{avg:+.2f}%')

    # 시간대별
    print('\n' + '-' * 60)
    print(f'시간대별 [{label}]')
    trades_df = trades_df.copy()
    trades_df['hour'] = trades_df['entry_time'].apply(lambda x: int(str(x)[:2]) if len(str(x)) >= 2 else 0)
    for h in sorted(trades_df['hour'].unique()):
        f = trades_df[trades_df['hour'] == h]
        if len(f) == 0:
            continue
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        avg = f['pnl'].mean()
        print(f'  {h}시: {len(f)}건, {w}승 {len(f)-w}패, {rate:.1f}%, 평균{avg:+.2f}%')

    # 월별
    print('\n' + '-' * 60)
    print(f'월별 [{label}]')
    trades_df['month'] = trades_df['date'].str[:6]
    for month in sorted(trades_df['month'].unique()):
        f = trades_df[trades_df['month'] == month]
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        avg = f['pnl'].mean()
        avg_n = avg - cost_pct
        cap_m = cap_fixed['monthly_returns'].get(month, 0.0)
        print(f'  {month}: {len(f)}건, {w}승 {len(f)-w}패, {rate:.1f}%, '
              f'순평균{avg_n:+.2f}%, 고정수익률{cap_m:+.2f}%')

    # 청산 사유별
    print('\n' + '-' * 60)
    print(f'청산 사유별 [{label}]')
    for reason in trades_df['exit_reason'].unique():
        f = trades_df[trades_df['exit_reason'] == reason]
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        avg = f['pnl'].mean()
        print(f'  {reason}: {len(f)}건, {w}승 {len(f)-w}패, {rate:.1f}%, 평균{avg:+.2f}%')

    # 기간 정보
    dates = sorted(trades_df['date'].unique())
    num_months = max(len(set(d[:6] for d in dates)), 1)
    print(f'\n  기간: {dates[0]}~{dates[-1]} ({num_months}개월)')
    print(f'  월평균 거래: {total/num_months:.0f}건')


def run_simulation(
    start_date='20250901',
    end_date=None,
    config=None,
    max_daily=5,
    screener_top_n=60,
    screener_min_amount=1_000_000_000,
    screener_max_gap=3.0,
    screener_min_price=5000,
    screener_max_price=500000,
    verbose=True,
    cost_pct=0.33,
    max_holding_minutes=0,
):
    strategy = PricePositionStrategy(config=config)
    info = strategy.get_strategy_info()

    print('=' * 80)
    print(f"스크리너 통합 시뮬레이션: {info['name']}")
    print('=' * 80)
    print(f"진입: 시가 대비 {info['entry_conditions']['pct_from_open']}, "
          f"{info['entry_conditions']['time_range']}")
    print(f"청산: 손절 {info['exit_conditions']['stop_loss']}, "
          f"익절 {info['exit_conditions']['take_profit']}")
    print(f"스크리너: 거래대금 상위 {screener_top_n}개, "
          f"거래대금>{screener_min_amount/1e8:.0f}억, "
          f"갭<{screener_max_gap}%, "
          f"가격 {screener_min_price:,}~{screener_max_price:,}원")
    print(f"동시보유: {max_daily}종목")
    print(f"비용: {cost_pct:.2f}%/건 (수수료+세금+슬리피지)")
    hold_str = f"{max_holding_minutes}분" if max_holding_minutes > 0 else "제한없음"
    print(f"최대보유: {hold_str}")
    print(f"기간: {start_date} ~ {end_date or '전체'}")
    print('=' * 80)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    # 거래일 목록
    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    all_trades = []
    screener_stats = {'total_stocks': 0, 'screened_stocks': 0, 'days': 0}

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 10 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 처리 중... '
                  f'거래 {len(all_trades)}건')

        # 전일 날짜 (이전 거래일)
        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        # 일간 지표 계산 (전 종목)
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        # 전일 종가 맵
        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        # 스크리너 필터 적용
        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=screener_top_n,
            min_price=screener_min_price,
            max_price=screener_max_price,
            min_amount=screener_min_amount,
            max_gap_pct=screener_max_gap,
        )

        screener_stats['total_stocks'] += len(daily_metrics)
        screener_stats['screened_stocks'] += len(screened)
        screener_stats['days'] += 1

        if not screened:
            continue

        # 스크리너 통과 종목만 전략 실행
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
                            **result,
                        })
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    # 결과 출력
    avg_total = screener_stats['total_stocks'] / max(screener_stats['days'], 1)
    avg_screened = screener_stats['screened_stocks'] / max(screener_stats['days'], 1)
    print(f'\n스크리너 통계: 일평균 {avg_total:.0f}개 → {avg_screened:.0f}개 통과 '
          f'({avg_screened/max(avg_total,1)*100:.0f}%)')
    print(f'총 거래: {len(all_trades)}건')

    if not all_trades:
        print('거래 없음')
        return None

    trades_df = pd.DataFrame(all_trades)

    # 무제한 결과
    unlimited_daily = defaultdict(list)
    for t in all_trades:
        unlimited_daily[t['date']].append(t)
    print_stats(trades_df, unlimited_daily, '무제한', cost_pct=cost_pct)

    # 동시보유 제한 결과
    if max_daily > 0:
        limited_df = apply_daily_limit(trades_df, max_daily)
        limited_daily = defaultdict(list)
        for _, row in limited_df.iterrows():
            limited_daily[row['date']].append(row.to_dict())

        print('\n')
        print('#' * 80)
        print(f'#  동시보유 {max_daily}종목 제한')
        print('#' * 80)
        print_stats(limited_df, limited_daily, f'동시보유 {max_daily}종목', cost_pct=cost_pct)

        # 비교 요약
        u_total = len(trades_df)
        u_wins = (trades_df['result'] == 'WIN').sum()
        u_fixed = calc_fixed_capital_returns(trades_df, cost_pct=cost_pct)
        l_total = len(limited_df)
        l_wins = (limited_df['result'] == 'WIN').sum() if l_total > 0 else 0
        l_fixed = calc_fixed_capital_returns(limited_df, cost_pct=cost_pct) if l_total > 0 else {'total_return_pct': 0}

        print('\n' + '=' * 80)
        print(f'비교 요약 (비용 {cost_pct:.2f}%/건 차감, 고정자본 기준)')
        print('=' * 80)
        print(f"{'':>20} {'무제한':>15} {'최대 '+str(max_daily)+'종목':>15}")
        print('-' * 50)
        print(f"{'거래수':>20} {u_total:>14}건 {l_total:>14}건")
        print(f"{'승률':>20} {u_wins/u_total*100:>13.1f}% "
              f"{l_wins/l_total*100 if l_total else 0:>13.1f}%")
        print(f"{'고정자본수익률':>20} {u_fixed['total_return_pct']:>+13.2f}% "
              f"{l_fixed['total_return_pct']:>+13.2f}%")
        print(f"{'순평균수익률':>20} {trades_df['pnl'].mean()-cost_pct:>+13.2f}% "
              f"{limited_df['pnl'].mean()-cost_pct if l_total else 0:>+13.2f}%")

    print('\nDone!')
    return trades_df


def _load_defaults():
    """설정 파일에서 기본값 로드"""
    import json, os
    from config.strategy_settings import StrategySettings
    pp = StrategySettings.PricePosition

    config_path = os.path.join(os.path.dirname(__file__), 'config', 'trading_config.json')
    with open(config_path, 'r') as f:
        tc = json.load(f)
    rm = tc.get('risk_management', {})

    return {
        'stop_loss': -rm.get('stop_loss_ratio', 0.05) * 100,
        'take_profit': rm.get('take_profit_ratio', 0.06) * 100,
        'max_volatility': pp.MAX_PRE_VOLATILITY,
        'max_momentum': pp.MAX_PRE20_MOMENTUM,
        'min_pct': pp.MIN_PCT_FROM_OPEN,
        'max_pct': pp.MAX_PCT_FROM_OPEN,
        'start_hour': pp.ENTRY_START_HOUR,
        'end_hour': pp.ENTRY_END_HOUR,
        'max_daily': pp.MAX_DAILY_POSITIONS,
    }


def main():
    defaults = _load_defaults()
    parser = argparse.ArgumentParser(description='스크리너 통합 시뮬레이션')
    parser.add_argument('--start', default='20250901', help='시작일')
    parser.add_argument('--end', default=None, help='종료일')
    parser.add_argument('--min-pct', type=float, default=defaults['min_pct'])
    parser.add_argument('--max-pct', type=float, default=defaults['max_pct'])
    parser.add_argument('--start-hour', type=int, default=defaults['start_hour'])
    parser.add_argument('--end-hour', type=int, default=defaults['end_hour'])
    parser.add_argument('--stop-loss', type=float, default=defaults['stop_loss'])
    parser.add_argument('--take-profit', type=float, default=defaults['take_profit'])
    parser.add_argument('--max-daily', type=int, default=defaults['max_daily'])
    parser.add_argument('--max-volatility', type=float, default=defaults['max_volatility'])
    parser.add_argument('--max-momentum', type=float, default=defaults['max_momentum'])
    parser.add_argument('--weekdays', default=None)
    parser.add_argument('--screener-top', type=int, default=60,
                        help='거래대금 상위 N개 (volume rank 시뮬)')
    parser.add_argument('--screener-min-amount', type=float, default=1e9,
                        help='최소 거래대금 (원)')
    parser.add_argument('--screener-max-gap', type=float, default=3.0,
                        help='최대 갭 %%')
    parser.add_argument('--cost', type=float, default=0.33,
                        help='건당 왕복 비용 %% (수수료+세금+슬리피지, 기본 0.33%%)')
    parser.add_argument('--max-hold', type=int, default=0,
                        help='최대 보유 시간(분). 0이면 제한없음 (기본 0)')
    parser.add_argument('--quiet', action='store_true')

    args = parser.parse_args()

    config = {
        'min_pct_from_open': args.min_pct,
        'max_pct_from_open': args.max_pct,
        'entry_start_hour': args.start_hour,
        'entry_end_hour': args.end_hour,
        'stop_loss_pct': args.stop_loss,
        'take_profit_pct': args.take_profit,
    }
    if args.weekdays is not None:
        config['allowed_weekdays'] = [int(d) for d in args.weekdays.split(',')]
    if args.max_volatility > 0:
        config['max_pre_volatility'] = args.max_volatility
    if args.max_momentum > 0:
        config['max_pre20_momentum'] = args.max_momentum

    run_simulation(
        start_date=args.start,
        end_date=args.end,
        config=config,
        max_daily=args.max_daily,
        screener_top_n=args.screener_top,
        screener_min_amount=args.screener_min_amount,
        screener_max_gap=args.screener_max_gap,
        verbose=not args.quiet,
        cost_pct=args.cost,
        max_holding_minutes=args.max_hold,
    )


if __name__ == '__main__':
    main()
