"""
대안 전략 멀티버스 시뮬레이션

기존 price_position 전략과 3가지 대안 전략을 동일 기간/조건으로 비교.

전략:
1. 기존: 시가 대비 +1~3% 구간 진입 (9~12시)
2. 갭다운 반등: 전일 대비 -2% 이상 갭다운 종목, 반등 시 진입
3. 거래량 급증: 직전 10분 대비 거래량 3배 이상 급증 시 진입
4. 오후 풀백: 오전 고점 대비 -2~-3.5% 조정 시 오후 진입
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse
import sys

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from simulate_with_screener import (
    get_trading_dates, get_prev_close_map, get_daily_metrics,
    apply_screener_filter, apply_daily_limit,
    calc_fixed_capital_returns, calc_capital_returns,
)


def simulate_existing_strategy(df, day_open, config):
    """기존 price_position 전략 시뮬레이션 (종목 1개, 1일)"""
    min_pct = config.get('min_pct', 1.0)
    max_pct = config.get('max_pct', 3.0)
    stop_loss = config.get('stop_loss', -5.0)
    take_profit = config.get('take_profit', 6.0)
    start_hour = config.get('start_hour', 9)
    end_hour = config.get('end_hour', 12)
    max_vol = config.get('max_volatility', 1.2)
    max_mom = config.get('max_momentum', 2.0)

    for i in range(10, len(df) - 10):
        row = df.iloc[i]
        t = str(row['time']).zfill(6)
        hour = int(t[:2])
        price = row['close']

        if hour < start_hour or hour >= end_hour:
            continue

        pct = (price / day_open - 1) * 100
        if pct < min_pct or pct >= max_pct:
            continue

        # 변동성 필터
        pre = df.iloc[max(0, i-10):i]
        if len(pre) > 0:
            vol = ((pre['high'] - pre['low']) / pre['low'] * 100).mean()
            if vol > max_vol:
                continue

        # 모멘텀 필터
        pre20 = df.iloc[max(0, i-20):i]
        if len(pre20) >= 2:
            mom = (pre20.iloc[-1]['close'] / pre20.iloc[0]['open'] - 1) * 100
            if mom > max_mom:
                continue

        # 진입 (다음 캔들 시가)
        return _simulate_trade(df, i, stop_loss, take_profit)

    return None


def simulate_gapdown_reversion(df, day_open, prev_close, config):
    """전략2: 갭다운 반등 전략"""
    if prev_close is None or prev_close <= 0:
        return None

    gap_pct = (day_open / prev_close - 1) * 100
    min_gap = config.get('min_gap', -2.0)  # 갭다운 최소 -2%
    max_gap = config.get('max_gap', -8.0)  # 너무 큰 갭은 제외

    if gap_pct > min_gap or gap_pct < max_gap:
        return None

    stop_loss = config.get('stop_loss', -3.0)
    take_profit = config.get('take_profit', 4.0)
    start_hour = config.get('start_hour', 9)
    end_hour = config.get('end_hour', 11)

    for i in range(10, len(df) - 10):
        row = df.iloc[i]
        t = str(row['time']).zfill(6)
        hour = int(t[:2])
        minute = int(t[2:4])

        # 9:10 ~ end_hour
        if hour < start_hour:
            continue
        if hour == start_hour and minute < 10:
            continue
        if hour >= end_hour:
            break

        price = row['close']
        pct_from_open = (price / day_open - 1) * 100

        # 반등 신호: 시가 대비 +0.5% 이상 올라왔을 때
        if pct_from_open < 0.5:
            continue

        # 추가: 직전 3봉 상승 추세
        if i >= 3:
            if df.iloc[i]['close'] <= df.iloc[i-3]['close']:
                continue

        return _simulate_trade(df, i, stop_loss, take_profit)

    return None


def simulate_volume_breakout(df, day_open, config):
    """전략3: 거래량 급증 전략"""
    stop_loss = config.get('stop_loss', -4.5)
    take_profit = config.get('take_profit', 5.5)
    vol_multiplier = config.get('vol_multiplier', 3.0)
    start_hour = config.get('start_hour', 9)
    end_hour = config.get('end_hour', 12)

    for i in range(15, len(df) - 10):
        row = df.iloc[i]
        t = str(row['time']).zfill(6)
        hour = int(t[:2])
        minute = int(t[2:4])

        if hour < start_hour:
            continue
        if hour == start_hour and minute < 30:
            continue
        if hour >= end_hour:
            break

        price = row['close']
        pct_from_open = (price / day_open - 1) * 100

        # 시가 대비 +0.5~5% 구간
        if pct_from_open < 0.5 or pct_from_open > 5.0:
            continue

        # 거래량 급증 체크
        current_vol = row['volume']
        if current_vol <= 0:
            continue

        pre_vols = df.iloc[max(0, i-10):i]['volume']
        avg_vol = pre_vols.mean()
        if avg_vol <= 0:
            continue

        if current_vol < avg_vol * vol_multiplier:
            continue

        # 상방 돌파 확인 (현재 종가 > 시가)
        if row['close'] <= row['open']:
            continue

        return _simulate_trade(df, i, stop_loss, take_profit)

    return None


def simulate_afternoon_pullback(df, day_open, config):
    """전략4: 오후 풀백 전략"""
    stop_loss = config.get('stop_loss', -2.5)
    take_profit = config.get('take_profit', 3.0)
    min_morning_high_pct = config.get('min_morning_high', 5.0)
    pullback_min = config.get('pullback_min', -3.5)
    pullback_max = config.get('pullback_max', -2.0)

    # 1단계: 오전 고점 확인 (9:00~11:00)
    morning_high = 0
    for i in range(len(df)):
        t = str(df.iloc[i]['time']).zfill(6)
        hour = int(t[:2])
        if hour >= 11:
            break
        if df.iloc[i]['high'] > morning_high:
            morning_high = df.iloc[i]['high']

    if morning_high <= 0:
        return None

    morning_high_pct = (morning_high / day_open - 1) * 100
    if morning_high_pct < min_morning_high_pct:
        return None

    # 2단계: 오후 풀백 진입 (12:30~14:00)
    for i in range(10, len(df) - 10):
        row = df.iloc[i]
        t = str(row['time']).zfill(6)
        hour = int(t[:2])
        minute = int(t[2:4])

        if hour < 12 or (hour == 12 and minute < 30):
            continue
        if hour >= 14:
            break

        price = row['close']
        pullback_pct = (price / morning_high - 1) * 100

        # 고점 대비 -2~-3.5% 구간
        if pullback_pct < pullback_min or pullback_pct > pullback_max:
            continue

        # 시가 대비 아직 플러스인지 (모멘텀 유지)
        if (price / day_open - 1) * 100 < 1.5:
            continue

        # 직전 3봉 반등 시작 (저점 찍고 올라오는 중)
        if i >= 3:
            if df.iloc[i]['close'] <= df.iloc[i-2]['close']:
                continue

        return _simulate_trade(df, i, stop_loss, take_profit)

    return None


def _simulate_trade(df, signal_idx, stop_loss_pct, take_profit_pct):
    """공통 거래 시뮬레이션 (신호 후 다음봉 시가 진입)"""
    if signal_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[signal_idx + 1]['open']
    entry_time = df.iloc[signal_idx + 1]['time']

    if entry_price <= 0:
        return None

    max_profit = 0.0
    min_profit = 0.0

    for i in range(signal_idx + 1, len(df)):
        row = df.iloc[i]

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl = (row['low'] / entry_price - 1) * 100

        if high_pnl > max_profit:
            max_profit = high_pnl
        if low_pnl < min_profit:
            min_profit = low_pnl

        # 익절
        if high_pnl >= take_profit_pct:
            return {
                'result': 'WIN', 'pnl': take_profit_pct,
                'exit_reason': '익절',
                'entry_time': entry_time, 'exit_time': row['time'],
                'entry_price': entry_price,
            }

        # 손절
        if low_pnl <= stop_loss_pct:
            return {
                'result': 'LOSS', 'pnl': stop_loss_pct,
                'exit_reason': '손절',
                'entry_time': entry_time, 'exit_time': row['time'],
                'entry_price': entry_price,
            }

    # 장마감
    last = df.iloc[-1]
    pnl = (last['close'] / entry_price - 1) * 100
    return {
        'result': 'WIN' if pnl > 0 else 'LOSS', 'pnl': pnl,
        'exit_reason': '장마감',
        'entry_time': entry_time, 'exit_time': last['time'],
        'entry_price': entry_price,
    }


def run_all_strategies(start_date, end_date, max_daily=5, cost_pct=0.33, verbose=True):
    """4가지 전략 동시 시뮬레이션"""

    strategies = {
        '기존(시가+1~3%)': {
            'func': 'existing', 'trades': [],
            'config': {
                'min_pct': 1.0, 'max_pct': 3.0,
                'stop_loss': -5.0, 'take_profit': 6.0,
                'start_hour': 9, 'end_hour': 12,
                'max_volatility': 1.2, 'max_momentum': 2.0,
            },
        },
        '갭다운반등(-2%gap)': {
            'func': 'gapdown', 'trades': [],
            'config': {
                'min_gap': -2.0, 'max_gap': -8.0,
                'stop_loss': -3.0, 'take_profit': 4.0,
                'start_hour': 9, 'end_hour': 11,
            },
        },
        '거래량급증(3x)': {
            'func': 'volume', 'trades': [],
            'config': {
                'stop_loss': -4.5, 'take_profit': 5.5,
                'vol_multiplier': 3.0,
                'start_hour': 9, 'end_hour': 12,
            },
        },
        '오후풀백(고점-2~3.5%)': {
            'func': 'afternoon', 'trades': [],
            'config': {
                'stop_loss': -2.5, 'take_profit': 3.0,
                'min_morning_high': 5.0,
                'pullback_min': -3.5, 'pullback_max': -2.0,
            },
        },
    }

    print('=' * 90)
    print('대안 전략 비교 시뮬레이션')
    print('=' * 90)
    print(f'기간: {start_date} ~ {end_date or "전체"}')
    print(f'비용: {cost_pct:.2f}%/건, 동시보유: {max_daily}종목')
    print()
    for name, s in strategies.items():
        c = s['config']
        sl = c.get('stop_loss', 0)
        tp = c.get('take_profit', 0)
        print(f'  {name}: 손절 {sl}%, 익절 +{tp}%')
    print('=' * 90)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n총 거래일: {len(trading_dates)}일')

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            counts = ', '.join(f'{len(s["trades"])}' for s in strategies.values())
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) [{counts}]')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        # 스크리너 (기존과 동일)
        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=60, min_price=5000, max_price=500000,
            min_amount=1_000_000_000, max_gap_pct=5.0,  # 갭다운 전략 위해 5%로 확대
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

                prev_close = prev_close_map.get(stock_code)

                # 각 전략 실행
                for name, s in strategies.items():
                    func_name = s['func']
                    config = s['config']

                    # 종목당 1회 거래
                    already = any(t['stock_code'] == stock_code and t['date'] == trade_date
                                  for t in s['trades'])
                    if already:
                        continue

                    result = None
                    if func_name == 'existing':
                        result = simulate_existing_strategy(df, day_open, config)
                    elif func_name == 'gapdown':
                        result = simulate_gapdown_reversion(df, day_open, prev_close, config)
                    elif func_name == 'volume':
                        result = simulate_volume_breakout(df, day_open, config)
                    elif func_name == 'afternoon':
                        result = simulate_afternoon_pullback(df, day_open, config)

                    if result:
                        s['trades'].append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            **result,
                        })

            except Exception:
                continue

    cur.close()
    conn.close()

    # === 결과 출력 ===
    print('\n' + '=' * 90)
    print('전략별 비교 결과 (동시보유 %d종목, 비용 %.2f%%/건, 고정자본 기준)' % (max_daily, cost_pct))
    print('=' * 90)

    header = (f'{"전략":<22} {"거래수":>6} {"승률":>7} {"순평균":>8} '
              f'{"손절":>5} {"익절":>5} {"장마감":>5} '
              f'{"고정수익률":>10} {"최종자본":>12}')
    print(f'\n{header}')
    print('-' * 95)

    all_results = {}
    for name, s in strategies.items():
        trades = s['trades']
        if not trades:
            print(f'{name:<22} {"거래없음":>6}')
            continue

        df = pd.DataFrame(trades)

        # 동시보유 제한
        limited = apply_daily_limit(df, max_daily) if max_daily > 0 else df

        if len(limited) == 0:
            print(f'{name:<22} {"제한후 0건":>6}')
            continue

        total = len(limited)
        wins = (limited['result'] == 'WIN').sum()
        winrate = wins / total * 100
        avg_net = limited['pnl'].mean() - cost_pct

        stop_count = len(limited[limited['exit_reason'] == '손절'])
        tp_count = len(limited[limited['exit_reason'] == '익절'])
        close_count = len(limited[limited['exit_reason'] == '장마감'])

        cap = calc_fixed_capital_returns(limited, cost_pct=cost_pct)

        all_results[name] = {
            'df': limited, 'total': total, 'wins': wins, 'winrate': winrate,
            'avg_net': avg_net, 'stop_count': stop_count, 'tp_count': tp_count,
            'close_count': close_count, 'fixed_return': cap['total_return_pct'],
            'final_capital': cap['final_capital'],
            'monthly': cap['monthly_returns'],
        }

        print(f'{name:<22} {total:>5}건 {winrate:>6.1f}% {avg_net:>+7.2f}% '
              f'{stop_count:>4}건 {tp_count:>4}건 {close_count:>4}건 '
              f'{cap["total_return_pct"]:>+9.2f}% '
              f'{cap["final_capital"]/10000:>10,.0f}만')

    # === 월별 비교 ===
    if len(all_results) > 1:
        print('\n' + '=' * 90)
        print('월별 고정자본 수익률 비교')
        print('=' * 90)

        # 모든 월 수집
        all_months = set()
        for r in all_results.values():
            all_months.update(r['monthly'].keys())

        header_names = list(all_results.keys())
        short_names = [n[:10] for n in header_names]
        print(f'{"월":>8}', end='')
        for sn in short_names:
            print(f' {sn:>12}', end='')
        print()
        print('-' * (8 + 13 * len(short_names)))

        for month in sorted(all_months):
            print(f'{month:>8}', end='')
            for name in header_names:
                val = all_results[name]['monthly'].get(month, 0)
                print(f' {val:>+11.2f}%', end='')
            print()

        # 합계
        print('-' * (8 + 13 * len(short_names)))
        print(f'{"합계":>8}', end='')
        for name in header_names:
            print(f' {all_results[name]["fixed_return"]:>+11.2f}%', end='')
        print()

    # === 청산 사유별 상세 ===
    print('\n' + '=' * 90)
    print('청산 사유별 상세')
    print('=' * 90)
    for name, r in all_results.items():
        df = r['df']
        print(f'\n--- {name} ---')
        for reason in ['익절', '손절', '장마감']:
            f = df[df['exit_reason'] == reason]
            if len(f) == 0:
                continue
            w = (f['result'] == 'WIN').sum()
            avg = f['pnl'].mean()
            print(f'  {reason}: {len(f)}건, {w}승 {len(f)-w}패, 평균 {avg:+.2f}%')

    # === 포트폴리오 결합 ===
    if '기존(시가+1~3%)' in all_results and len(all_results) > 1:
        print('\n' + '=' * 90)
        print('포트폴리오 결합 (기존 + 대안 전략 동시 운영)')
        print('=' * 90)

        base_name = '기존(시가+1~3%)'
        base = all_results[base_name]

        for alt_name, alt in all_results.items():
            if alt_name == base_name:
                continue

            # 두 전략 거래를 합쳐서 날짜별 수익 계산
            combined_trades = pd.concat([base['df'], alt['df']], ignore_index=True)

            # 각 전략에 자본 50%씩 배분
            cap_base = calc_fixed_capital_returns(
                base['df'], initial_capital=5_000_000, buy_ratio=0.20, cost_pct=cost_pct)
            cap_alt = calc_fixed_capital_returns(
                alt['df'], initial_capital=5_000_000, buy_ratio=0.20, cost_pct=cost_pct)

            combined_return = (cap_base['final_capital'] + cap_alt['final_capital']) / 10_000_000
            combined_pct = (combined_return - 1) * 100

            print(f'\n  기존 + {alt_name}:')
            print(f'    기존 50% 배분: {cap_base["total_return_pct"]:+.2f}%')
            print(f'    대안 50% 배분: {cap_alt["total_return_pct"]:+.2f}%')
            print(f'    결합 수익률: {combined_pct:+.2f}% '
                  f'(1000만 -> {(cap_base["final_capital"]+cap_alt["final_capital"])/10000:,.0f}만)')
            print(f'    기존 100% 대비: {combined_pct - base["fixed_return"]:+.2f}%p')

    print('\n' + '=' * 90)
    print('Done!')
    print('=' * 90)


def main():
    parser = argparse.ArgumentParser(description='대안 전략 비교 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default=None, help='종료일')
    parser.add_argument('--cost', type=float, default=0.33, help='건당 비용')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    run_all_strategies(
        start_date=args.start,
        end_date=args.end,
        cost_pct=args.cost,
        max_daily=args.max_daily,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
