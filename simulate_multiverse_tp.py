"""
익절 특성 기반 멀티버스 시뮬레이션

1단계: 필터 최소화하여 전체 가능한 거래를 수집 (DB 1회 스캔)
2단계: 다양한 필터 조합을 후처리로 적용하여 비교

테스트 변수:
- max_pre_volatility: 0.8(현재), 1.0, 1.2, 1.5, 제거
- screener_max_price: 500000(현재), 100000, 50000
- entry_end_hour: 12(현재), 10, 11
- stop_loss / take_profit 비율
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
import argparse
import itertools

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


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
          AND idx = (
            SELECT MAX(idx) FROM minute_candles mc2
            WHERE mc2.stock_code = minute_candles.stock_code
              AND mc2.trade_date = %s
          )
    ''', [prev_date, prev_date])
    return {row[0]: row[1] for row in cur.fetchall()}


def get_daily_metrics(cur, trade_date):
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


def apply_screener_filter(daily_metrics, prev_close_map, top_n=60,
                          min_price=5000, max_price=500000,
                          min_amount=1_000_000_000, max_gap_pct=3.0):
    ranked = sorted(
        daily_metrics.items(),
        key=lambda x: x[1]['daily_amount'],
        reverse=True
    )[:top_n]

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
            gap_pct = abs(day_open / prev_close - 1) * 100
            if gap_pct > max_gap_pct:
                continue
        passed.add(stock_code)
    return passed


def simulate_trade_flexible(df, entry_idx, stop_loss_pct, take_profit_pct):
    """손익비를 파라미터로 받는 유연한 시뮬레이션"""
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']

    if entry_price <= 0:
        return None

    max_profit_pct = 0.0
    max_drawdown_pct = 0.0

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl = (row['low'] / entry_price - 1) * 100

        if high_pnl > max_profit_pct:
            max_profit_pct = high_pnl
        if low_pnl < max_drawdown_pct:
            max_drawdown_pct = low_pnl

        # 익절
        if high_pnl >= take_profit_pct:
            return {
                'result': 'WIN',
                'pnl': take_profit_pct,
                'exit_reason': '익절',
                'entry_time': entry_time,
                'exit_time': row['time'],
                'entry_price': entry_price,
                'holding_candles': i - entry_idx,
                'max_profit_pct': round(max_profit_pct, 2),
                'max_drawdown_pct': round(max_drawdown_pct, 2),
            }

        # 손절
        if low_pnl <= stop_loss_pct:
            return {
                'result': 'LOSS',
                'pnl': stop_loss_pct,
                'exit_reason': '손절',
                'entry_time': entry_time,
                'exit_time': row['time'],
                'entry_price': entry_price,
                'holding_candles': i - entry_idx,
                'max_profit_pct': round(max_profit_pct, 2),
                'max_drawdown_pct': round(max_drawdown_pct, 2),
            }

    # 장마감
    last_row = df.iloc[-1]
    last_pnl = (last_row['close'] / entry_price - 1) * 100

    return {
        'result': 'WIN' if last_pnl > 0 else 'LOSS',
        'pnl': last_pnl,
        'exit_reason': '장마감',
        'entry_time': entry_time,
        'exit_time': last_row['time'],
        'entry_price': entry_price,
        'holding_candles': len(df) - 1 - entry_idx,
        'max_profit_pct': round(max_profit_pct, 2),
        'max_drawdown_pct': round(max_drawdown_pct, 2),
    }


def collect_all_trades(start_date, end_date, verbose=True):
    """
    필터를 최소화하여 모든 가능한 진입 기회 수집.
    변동성/모멘텀 필터 제거, 시간 09~12, 시가대비 1~3%.
    각 거래에 피처 + 원시 캔들 데이터(재시뮬용) 포함.
    """
    # 변동성/모멘텀 필터 완전 해제
    strategy = PricePositionStrategy(config={
        'max_pre_volatility': None,
        'max_pre20_momentum': None,
        'min_rising_candles': 0,
        'entry_start_hour': 9,
        'entry_end_hour': 12,
        'min_pct_from_open': 1.0,
        'max_pct_from_open': 3.0,
    })

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'거래일: {len(trading_dates)}일 ({start_date} ~ {end_date})')

    all_entries = []

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 수집 {len(all_entries)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        # 스크리너: max_price를 500000으로 (가장 넓게)
        screened = apply_screener_filter(daily_metrics, prev_close_map, max_price=500000)
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

                prev_close = prev_close_map.get(stock_code)
                traded = False

                for candle_idx in range(10, len(df) - 10):
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

                    # --- 피처 추출 (필터 적용 전 원시값) ---
                    entry_time_str = str(current_time).zfill(6)
                    entry_hour = int(entry_time_str[:2])

                    pct_from_open = (current_price / day_open - 1) * 100
                    gap_pct = 0.0
                    if prev_close and prev_close > 0:
                        gap_pct = (day_open / prev_close - 1) * 100

                    # 변동성 계산 (10봉)
                    pre_start = max(0, candle_idx - 10)
                    pre_candles = df.iloc[pre_start:candle_idx]
                    pre_volatility_10 = 0.0
                    if len(pre_candles) > 0:
                        v = ((pre_candles['high'] - pre_candles['low']) / pre_candles['low'].replace(0, np.nan) * 100).mean()
                        if not np.isnan(v):
                            pre_volatility_10 = v

                    # 변동성 계산 (20봉)
                    pre20_start = max(0, candle_idx - 20)
                    pre20 = df.iloc[pre20_start:candle_idx]
                    pre_volatility_20 = 0.0
                    if len(pre20) > 0:
                        v20 = ((pre20['high'] - pre20['low']) / pre20['low'].replace(0, np.nan) * 100).mean()
                        if not np.isnan(v20):
                            pre_volatility_20 = v20

                    # 모멘텀 계산 (20봉)
                    pre_momentum_20 = 0.0
                    if len(pre20) >= 2:
                        pre_momentum_20 = (pre20.iloc[-1]['close'] / pre20.iloc[0]['open'] - 1) * 100

                    # 모멘텀 계산 (5봉)
                    pre5 = df.iloc[max(0, candle_idx - 5):candle_idx]
                    pre_momentum_5 = 0.0
                    if len(pre5) >= 2:
                        pre_momentum_5 = (pre5.iloc[-1]['close'] / pre5.iloc[0]['open'] - 1) * 100

                    # 거래량 비율
                    avg_vol_pre10 = pre_candles['volume'].mean() if len(pre_candles) > 0 else 1
                    volume_ratio = df.iloc[candle_idx]['volume'] / avg_vol_pre10 if avg_vol_pre10 > 0 else 1.0

                    # 양봉비율 (20봉)
                    bullish_ratio = 0.5
                    if len(pre20) >= 5:
                        bullish_ratio = (pre20['close'] > pre20['open']).sum() / len(pre20)

                    # 당일 변동폭
                    day_candles_so_far = df.iloc[:candle_idx + 1]
                    day_high = day_candles_so_far['high'].max()
                    day_low = day_candles_so_far['low'].min()
                    day_range_pct = (day_high / day_low - 1) * 100 if day_low > 0 else 0
                    pct_from_day_high = (current_price / day_high - 1) * 100 if day_high > 0 else 0

                    # 다양한 손익비로 시뮬 결과 미리 계산
                    sl_tp_results = {}
                    for sl, tp in [(-4.0, 5.0), (-3.0, 5.0), (-4.0, 4.0), (-3.0, 4.0),
                                   (-4.0, 6.0), (-3.0, 6.0), (-5.0, 5.0), (-5.0, 6.0),
                                   (-2.0, 3.0), (-3.0, 3.0), (-2.0, 4.0)]:
                        res = simulate_trade_flexible(df, candle_idx, sl, tp)
                        if res:
                            key = f'sl{sl}_tp{tp}'
                            sl_tp_results[key] = res

                    if not sl_tp_results:
                        continue

                    entry = {
                        'date': trade_date,
                        'weekday': weekday,
                        'stock_code': stock_code,
                        'entry_hour': entry_hour,
                        'entry_price': df.iloc[candle_idx + 1]['open'] if candle_idx + 1 < len(df) else current_price,
                        'day_open': day_open,
                        'pct_from_open': round(pct_from_open, 4),
                        'gap_pct': round(gap_pct, 4),
                        'pre_volatility_10': round(pre_volatility_10, 4),
                        'pre_volatility_20': round(pre_volatility_20, 4),
                        'pre_momentum_5': round(pre_momentum_5, 4),
                        'pre_momentum_20': round(pre_momentum_20, 4),
                        'volume_ratio': round(volume_ratio, 4),
                        'bullish_ratio': round(bullish_ratio, 4),
                        'day_range_pct': round(day_range_pct, 4),
                        'pct_from_day_high': round(pct_from_day_high, 4),
                        'daily_amount': daily_metrics[stock_code]['daily_amount'],
                    }

                    # 손익비별 결과 저장
                    for key, res in sl_tp_results.items():
                        entry[f'{key}_pnl'] = round(res['pnl'], 4)
                        entry[f'{key}_reason'] = res['exit_reason']
                        entry[f'{key}_result'] = res['result']
                        entry[f'{key}_holding'] = res['holding_candles']
                        entry[f'{key}_maxprofit'] = res['max_profit_pct']

                    all_entries.append(entry)
                    strategy.record_trade(stock_code, trade_date)
                    traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n수집 완료: {len(all_entries)}건')
    return pd.DataFrame(all_entries) if all_entries else pd.DataFrame()


def apply_daily_limit(trades_df, max_daily, sl_tp_key):
    """동시 보유 제한 적용 (특정 손익비 기준)"""
    pnl_col = f'{sl_tp_key}_pnl'
    reason_col = f'{sl_tp_key}_reason'
    result_col = f'{sl_tp_key}_result'

    if pnl_col not in trades_df.columns:
        return trades_df

    limited = []
    for date in trades_df['date'].unique():
        day_trades = trades_df[trades_df['date'] == date].copy()
        day_trades = day_trades.sort_values('entry_hour')

        accepted = []
        for _, trade in day_trades.iterrows():
            holding = len(accepted)  # 간소화: 동시보유 근사
            if holding < max_daily:
                accepted.append(trade)
                limited.append(trade)

    return pd.DataFrame(limited).reset_index(drop=True) if limited else pd.DataFrame()


def calc_capital_returns(trades_df, pnl_col, initial_capital=10_000_000, buy_ratio=0.20):
    if trades_df is None or len(trades_df) == 0:
        return {'final_capital': initial_capital, 'total_return_pct': 0.0}

    capital = initial_capital
    for date in sorted(trades_df['date'].unique()):
        day_trades = trades_df[trades_df['date'] == date]
        day_start_capital = capital
        for _, trade in day_trades.iterrows():
            invest = day_start_capital * buy_ratio
            profit = invest * (trade[pnl_col] / 100)
            capital += profit

    return {
        'final_capital': capital,
        'total_return_pct': (capital / initial_capital - 1) * 100,
    }


def run_multiverse(df, max_daily=5):
    """다양한 필터 조합 적용하여 성과 비교"""

    # === 파라미터 공간 정의 ===
    volatility_options = [
        (0.8, '변동성<=0.8%(현재)'),
        (1.0, '변동성<=1.0%'),
        (1.2, '변동성<=1.2%'),
        (1.5, '변동성<=1.5%'),
        (999, '변동성필터제거'),
    ]

    max_price_options = [
        (500000, '가격<=50만(현재)'),
        (100000, '가격<=10만'),
        (50000, '가격<=5만'),
    ]

    end_hour_options = [
        (12, '매수~12시(현재)'),
        (11, '매수~11시'),
        (10, '매수~10시'),
    ]

    momentum_options = [
        (2.0, '모멘텀<=2%(현재)'),
        (999, '모멘텀필터제거'),
    ]

    sl_tp_options = [
        ('sl-4.0_tp5.0', '손절4%/익절5%(현재)'),
        ('sl-3.0_tp5.0', '손절3%/익절5%'),
        ('sl-3.0_tp4.0', '손절3%/익절4%'),
        ('sl-4.0_tp6.0', '손절4%/익절6%'),
        ('sl-3.0_tp6.0', '손절3%/익절6%'),
        ('sl-5.0_tp5.0', '손절5%/익절5%'),
        ('sl-5.0_tp6.0', '손절5%/익절6%'),
        ('sl-4.0_tp4.0', '손절4%/익절4%'),
        ('sl-2.0_tp3.0', '손절2%/익절3%'),
        ('sl-3.0_tp3.0', '손절3%/익절3%'),
        ('sl-2.0_tp4.0', '손절2%/익절4%'),
    ]

    results = []
    total_combos = (len(volatility_options) * len(max_price_options) *
                    len(end_hour_options) * len(momentum_options) * len(sl_tp_options))
    print(f'\n총 조합 수: {total_combos}개')
    print('멀티버스 시뮬레이션 시작...\n')

    combo_idx = 0
    for vol_max, vol_label in volatility_options:
        for price_max, price_label in max_price_options:
            for end_hour, hour_label in end_hour_options:
                for mom_max, mom_label in momentum_options:
                    # 필터 적용
                    filtered = df.copy()

                    # 변동성 필터
                    if vol_max < 999:
                        filtered = filtered[filtered['pre_volatility_10'] <= vol_max]

                    # 가격 필터
                    filtered = filtered[filtered['entry_price'] <= price_max]

                    # 시간 필터
                    filtered = filtered[filtered['entry_hour'] < end_hour]

                    # 모멘텀 필터
                    if mom_max < 999:
                        filtered = filtered[filtered['pre_momentum_20'] <= mom_max]

                    if len(filtered) == 0:
                        continue

                    # 동시보유 제한 적용 (간소화)
                    limited = apply_daily_limit(filtered, max_daily, 'sl-4.0_tp5.0')

                    for sl_tp_key, sl_tp_label in sl_tp_options:
                        pnl_col = f'{sl_tp_key}_pnl'
                        reason_col = f'{sl_tp_key}_reason'
                        result_col = f'{sl_tp_key}_result'

                        if pnl_col not in limited.columns:
                            continue

                        valid = limited[limited[pnl_col].notna()]
                        if len(valid) < 10:
                            continue

                        n_trades = len(valid)
                        n_wins = (valid[result_col] == 'WIN').sum()
                        n_tp = (valid[reason_col] == '익절').sum()
                        n_sl = (valid[reason_col] == '손절').sum()
                        winrate = n_wins / n_trades * 100
                        tp_rate = n_tp / n_trades * 100
                        avg_pnl = valid[pnl_col].mean()

                        cap = calc_capital_returns(valid, pnl_col)

                        results.append({
                            'vol_filter': vol_label,
                            'price_filter': price_label,
                            'hour_filter': hour_label,
                            'momentum_filter': mom_label,
                            'sl_tp': sl_tp_label,
                            'trades': n_trades,
                            'wins': n_wins,
                            'winrate': round(winrate, 1),
                            'tp_rate': round(tp_rate, 1),
                            'sl_rate': round(n_sl / n_trades * 100, 1),
                            'avg_pnl': round(avg_pnl, 3),
                            'capital_return': round(cap['total_return_pct'], 2),
                            'final_capital': round(cap['final_capital']),
                        })

                        combo_idx += 1

    if combo_idx % 100 == 0:
        print(f'  {combo_idx}/{total_combos} 조합 처리...')

    print(f'\n총 {len(results)}개 유효 조합 처리 완료')
    return pd.DataFrame(results)


def print_results(results_df):
    """결과 출력"""
    if len(results_df) == 0:
        print('결과 없음')
        return

    # === 현재 설정 기준 ===
    current = results_df[
        (results_df['vol_filter'] == '변동성<=0.8%(현재)') &
        (results_df['price_filter'] == '가격<=50만(현재)') &
        (results_df['hour_filter'] == '매수~12시(현재)') &
        (results_df['momentum_filter'] == '모멘텀<=2%(현재)') &
        (results_df['sl_tp'] == '손절4%/익절5%(현재)')
    ]

    if len(current) > 0:
        c = current.iloc[0]
        print('\n' + '=' * 100)
        print('현재 설정 기준선')
        print('=' * 100)
        print(f'  거래: {c["trades"]}건, 승률: {c["winrate"]}%, '
              f'익절률: {c["tp_rate"]}%, 손절률: {c["sl_rate"]}%')
        print(f'  평균PnL: {c["avg_pnl"]:+.3f}%, '
              f'원금수익률: {c["capital_return"]:+.2f}% '
              f'(1000만 -> {c["final_capital"]/10000:,.0f}만원)')
        baseline_return = c['capital_return']
    else:
        baseline_return = 0
        print('\n(현재 설정 조합을 찾을 수 없음)')

    # === 원금수익률 TOP 30 ===
    print('\n' + '=' * 100)
    print('원금수익률 TOP 30')
    print('=' * 100)

    top = results_df.nlargest(30, 'capital_return')
    print(f'{"순위":>4} {"변동성":<18} {"가격":<16} {"시간":<14} {"모멘텀":<16} '
          f'{"손익비":<18} {"거래":>5} {"승률":>6} {"익절률":>6} {"PnL":>7} {"원금수익률":>10} {"vs현재":>8}')
    print('-' * 145)

    for rank, (_, row) in enumerate(top.iterrows(), 1):
        delta = row['capital_return'] - baseline_return
        print(f'{rank:>4} {row["vol_filter"]:<18} {row["price_filter"]:<16} '
              f'{row["hour_filter"]:<14} {row["momentum_filter"]:<16} '
              f'{row["sl_tp"]:<18} {row["trades"]:>5} {row["winrate"]:>5.1f}% '
              f'{row["tp_rate"]:>5.1f}% {row["avg_pnl"]:>+6.3f}% '
              f'{row["capital_return"]:>+9.2f}% {delta:>+7.2f}%p')

    # === 각 변수별 개별 영향도 분석 ===
    print('\n' + '=' * 100)
    print('개별 변수 영향도 (다른 변수는 현재 설정 고정)')
    print('=' * 100)

    # 변동성 영향
    print('\n[변동성 필터]')
    subset = results_df[
        (results_df['price_filter'] == '가격<=50만(현재)') &
        (results_df['hour_filter'] == '매수~12시(현재)') &
        (results_df['momentum_filter'] == '모멘텀<=2%(현재)') &
        (results_df['sl_tp'] == '손절4%/익절5%(현재)')
    ].sort_values('capital_return', ascending=False)
    for _, row in subset.iterrows():
        delta = row['capital_return'] - baseline_return
        print(f'  {row["vol_filter"]:<20} 거래 {row["trades"]:>4}건  승률 {row["winrate"]:>5.1f}%  '
              f'익절률 {row["tp_rate"]:>5.1f}%  PnL {row["avg_pnl"]:>+6.3f}%  '
              f'원금 {row["capital_return"]:>+8.2f}% ({delta:>+6.2f}%p)')

    # 가격 영향
    print('\n[가격 필터]')
    subset = results_df[
        (results_df['vol_filter'] == '변동성<=0.8%(현재)') &
        (results_df['hour_filter'] == '매수~12시(현재)') &
        (results_df['momentum_filter'] == '모멘텀<=2%(현재)') &
        (results_df['sl_tp'] == '손절4%/익절5%(현재)')
    ].sort_values('capital_return', ascending=False)
    for _, row in subset.iterrows():
        delta = row['capital_return'] - baseline_return
        print(f'  {row["price_filter"]:<20} 거래 {row["trades"]:>4}건  승률 {row["winrate"]:>5.1f}%  '
              f'익절률 {row["tp_rate"]:>5.1f}%  PnL {row["avg_pnl"]:>+6.3f}%  '
              f'원금 {row["capital_return"]:>+8.2f}% ({delta:>+6.2f}%p)')

    # 시간 영향
    print('\n[매수 종료 시간]')
    subset = results_df[
        (results_df['vol_filter'] == '변동성<=0.8%(현재)') &
        (results_df['price_filter'] == '가격<=50만(현재)') &
        (results_df['momentum_filter'] == '모멘텀<=2%(현재)') &
        (results_df['sl_tp'] == '손절4%/익절5%(현재)')
    ].sort_values('capital_return', ascending=False)
    for _, row in subset.iterrows():
        delta = row['capital_return'] - baseline_return
        print(f'  {row["hour_filter"]:<20} 거래 {row["trades"]:>4}건  승률 {row["winrate"]:>5.1f}%  '
              f'익절률 {row["tp_rate"]:>5.1f}%  PnL {row["avg_pnl"]:>+6.3f}%  '
              f'원금 {row["capital_return"]:>+8.2f}% ({delta:>+6.2f}%p)')

    # 모멘텀 영향
    print('\n[모멘텀 필터]')
    subset = results_df[
        (results_df['vol_filter'] == '변동성<=0.8%(현재)') &
        (results_df['price_filter'] == '가격<=50만(현재)') &
        (results_df['hour_filter'] == '매수~12시(현재)') &
        (results_df['sl_tp'] == '손절4%/익절5%(현재)')
    ].sort_values('capital_return', ascending=False)
    for _, row in subset.iterrows():
        delta = row['capital_return'] - baseline_return
        print(f'  {row["momentum_filter"]:<20} 거래 {row["trades"]:>4}건  승률 {row["winrate"]:>5.1f}%  '
              f'익절률 {row["tp_rate"]:>5.1f}%  PnL {row["avg_pnl"]:>+6.3f}%  '
              f'원금 {row["capital_return"]:>+8.2f}% ({delta:>+6.2f}%p)')

    # 손익비 영향
    print('\n[손절/익절 비율]')
    subset = results_df[
        (results_df['vol_filter'] == '변동성<=0.8%(현재)') &
        (results_df['price_filter'] == '가격<=50만(현재)') &
        (results_df['hour_filter'] == '매수~12시(현재)') &
        (results_df['momentum_filter'] == '모멘텀<=2%(현재)')
    ].sort_values('capital_return', ascending=False)
    for _, row in subset.iterrows():
        delta = row['capital_return'] - baseline_return
        print(f'  {row["sl_tp"]:<20} 거래 {row["trades"]:>4}건  승률 {row["winrate"]:>5.1f}%  '
              f'익절률 {row["tp_rate"]:>5.1f}%  PnL {row["avg_pnl"]:>+6.3f}%  '
              f'원금 {row["capital_return"]:>+8.2f}% ({delta:>+6.2f}%p)')

    # === 최적 조합 vs 현재 ===
    if len(results_df) > 0:
        best = results_df.iloc[results_df['capital_return'].idxmax()]
        print('\n' + '=' * 100)
        print('최적 조합 vs 현재 설정')
        print('=' * 100)
        print(f'  최적: {best["vol_filter"]} | {best["price_filter"]} | '
              f'{best["hour_filter"]} | {best["momentum_filter"]} | {best["sl_tp"]}')
        print(f'  거래: {best["trades"]}건, 승률: {best["winrate"]}%, '
              f'익절률: {best["tp_rate"]}%, 손절률: {best["sl_rate"]}%')
        print(f'  평균PnL: {best["avg_pnl"]:+.3f}%')
        print(f'  원금수익률: {best["capital_return"]:+.2f}% '
              f'(1000만 -> {best["final_capital"]/10000:,.0f}만원)')
        if baseline_return:
            print(f'  현재 대비: {best["capital_return"] - baseline_return:+.2f}%p 개선')


def main():
    parser = argparse.ArgumentParser(description='익절 특성 기반 멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260223', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    # 1단계: 전체 거래 수집
    print('=' * 100)
    print('1단계: 전체 가능한 거래 수집 (필터 최소화)')
    print('=' * 100)
    all_trades = collect_all_trades(args.start, args.end, verbose=not args.quiet)

    if len(all_trades) == 0:
        print('거래 없음')
        return

    # 2단계: 멀티버스 시뮬
    print('\n' + '=' * 100)
    print('2단계: 멀티버스 시뮬레이션')
    print('=' * 100)
    results_df = run_multiverse(all_trades, max_daily=args.max_daily)

    # 3단계: 결과 출력
    print_results(results_df)

    # CSV 저장
    csv_path = f'multiverse_tp_{args.start}_{args.end}.csv'
    results_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f'\n결과 저장: {csv_path}')


if __name__ == '__main__':
    main()
