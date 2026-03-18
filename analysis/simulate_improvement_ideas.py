"""
"초반에 못 오르면 손절로 끝나는" 문제 개선 아이디어 시뮬레이션

3가지 아이디어를 baseline과 비교:
  아이디어 1: 시간 기반 조기청산 — 진입 후 N분 내에 수익 < 0%이면 즉시 청산
  아이디어 2: 트레일링 스탑    — 장중 최고점 대비 N% 하락 시 청산
  아이디어 3: 초반 타이트 손절 — 진입 후 30분 내 손절 -3%, 이후 -5% 유지

simulate_with_screener.py의 run_simulation 로직을 그대로 재사용.
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy

# simulate_with_screener.py 의 공용 함수 재사용
from simulate_with_screener import (
    get_trading_dates,
    get_prev_close_map,
    get_daily_metrics,
    apply_screener_filter,
    apply_daily_limit,
    calc_fixed_capital_returns,
)

# ===========================================================================
# 아이디어별 simulate_trade 변형
# ===========================================================================

def simulate_trade_baseline(df, entry_idx, stop_loss_pct=-5.0, take_profit_pct=6.0):
    """기본 전략: 고정 손절 -5%, 익절 +6%"""
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']
    if entry_price <= 0:
        return None

    max_profit_pct = 0.0
    min_profit_pct = 0.0

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        holding = i - entry_idx

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl  = (row['low']  / entry_price - 1) * 100
        max_profit_pct = max(max_profit_pct, high_pnl)
        min_profit_pct = min(min_profit_pct, low_pnl)

        # 익절
        if high_pnl >= take_profit_pct:
            return _make_result('WIN', take_profit_pct, '익절', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)
        # 손절
        if low_pnl <= stop_loss_pct:
            return _make_result('LOSS', stop_loss_pct, '손절', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)

    last = df.iloc[-1]
    pnl = (last['close'] / entry_price - 1) * 100
    return _make_result('WIN' if pnl > 0 else 'LOSS', pnl, '장마감', entry_time, last['time'],
                        entry_price, len(df) - 1 - entry_idx, max_profit_pct, min_profit_pct)


def simulate_trade_idea1(df, entry_idx, early_exit_minutes,
                         stop_loss_pct=-5.0, take_profit_pct=6.0):
    """
    아이디어 1: 시간 기반 조기청산
    진입 후 early_exit_minutes 분 경과 시점에 수익률 < 0% 이면 즉시 청산.
    """
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']
    if entry_price <= 0:
        return None

    max_profit_pct = 0.0
    min_profit_pct = 0.0

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        holding = i - entry_idx

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl  = (row['low']  / entry_price - 1) * 100
        close_pnl = (row['close'] / entry_price - 1) * 100
        max_profit_pct = max(max_profit_pct, high_pnl)
        min_profit_pct = min(min_profit_pct, low_pnl)

        # 익절
        if high_pnl >= take_profit_pct:
            return _make_result('WIN', take_profit_pct, '익절', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)
        # 손절
        if low_pnl <= stop_loss_pct:
            return _make_result('LOSS', stop_loss_pct, '손절', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)

        # 조기청산: N분 경과 후 수익률 < 0%
        if holding == early_exit_minutes and close_pnl < 0:
            return _make_result('LOSS', close_pnl, f'조기청산{early_exit_minutes}분',
                                entry_time, row['time'], entry_price, holding,
                                max_profit_pct, min_profit_pct)

    last = df.iloc[-1]
    pnl = (last['close'] / entry_price - 1) * 100
    return _make_result('WIN' if pnl > 0 else 'LOSS', pnl, '장마감', entry_time, last['time'],
                        entry_price, len(df) - 1 - entry_idx, max_profit_pct, min_profit_pct)


def simulate_trade_idea2(df, entry_idx, trailing_pct,
                         stop_loss_pct=-5.0, take_profit_pct=6.0):
    """
    아이디어 2: 트레일링 스탑
    장중 최고 수익률 대비 trailing_pct% 하락 시 청산.
    단, 고정 손절(-5%)도 병행 유지 (더 빠른 쪽이 발동).
    """
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']
    if entry_price <= 0:
        return None

    peak_price = entry_price  # 진입가가 초기 최고점
    max_profit_pct = 0.0
    min_profit_pct = 0.0

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        holding = i - entry_idx

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl  = (row['low']  / entry_price - 1) * 100
        max_profit_pct = max(max_profit_pct, high_pnl)
        min_profit_pct = min(min_profit_pct, low_pnl)

        # 최고가 갱신
        if row['high'] > peak_price:
            peak_price = row['high']

        # 익절 (고정 상한)
        if high_pnl >= take_profit_pct:
            return _make_result('WIN', take_profit_pct, '익절', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)

        # 고정 손절 (-5%)
        if low_pnl <= stop_loss_pct:
            return _make_result('LOSS', stop_loss_pct, '손절', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)

        # 트레일링 스탑: 최고점 대비 trailing_pct% 이상 하락
        trailing_stop_price = peak_price * (1 - trailing_pct / 100)
        if row['low'] <= trailing_stop_price:
            trail_pnl = (trailing_stop_price / entry_price - 1) * 100
            return _make_result('WIN' if trail_pnl > 0 else 'LOSS', trail_pnl,
                                f'트레일링{trailing_pct}%', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)

    last = df.iloc[-1]
    pnl = (last['close'] / entry_price - 1) * 100
    return _make_result('WIN' if pnl > 0 else 'LOSS', pnl, '장마감', entry_time, last['time'],
                        entry_price, len(df) - 1 - entry_idx, max_profit_pct, min_profit_pct)


def simulate_trade_idea3(df, entry_idx, tight_minutes=30, tight_stop=-3.0,
                         stop_loss_pct=-5.0, take_profit_pct=6.0):
    """
    아이디어 3: 초반 타이트 손절
    진입 후 tight_minutes 분 내에는 손절 tight_stop%, 이후에는 stop_loss_pct%.
    """
    if entry_idx + 1 >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx + 1]['open']
    entry_time = df.iloc[entry_idx + 1]['time']
    if entry_price <= 0:
        return None

    max_profit_pct = 0.0
    min_profit_pct = 0.0

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        holding = i - entry_idx

        high_pnl = (row['high'] / entry_price - 1) * 100
        low_pnl  = (row['low']  / entry_price - 1) * 100
        max_profit_pct = max(max_profit_pct, high_pnl)
        min_profit_pct = min(min_profit_pct, low_pnl)

        # 현재 적용할 손절선
        current_stop = tight_stop if holding <= tight_minutes else stop_loss_pct

        # 익절
        if high_pnl >= take_profit_pct:
            return _make_result('WIN', take_profit_pct, '익절', entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)

        # 손절 (타이트 or 일반)
        if low_pnl <= current_stop:
            reason = f'초반손절{tight_stop}%' if holding <= tight_minutes else '손절'
            return _make_result('LOSS', current_stop, reason, entry_time, row['time'],
                                entry_price, holding, max_profit_pct, min_profit_pct)

    last = df.iloc[-1]
    pnl = (last['close'] / entry_price - 1) * 100
    return _make_result('WIN' if pnl > 0 else 'LOSS', pnl, '장마감', entry_time, last['time'],
                        entry_price, len(df) - 1 - entry_idx, max_profit_pct, min_profit_pct)


def _make_result(result, pnl, exit_reason, entry_time, exit_time,
                 entry_price, holding_candles, max_profit_pct, min_profit_pct):
    return {
        'result': result,
        'pnl': round(pnl, 4),
        'exit_reason': exit_reason,
        'entry_time': entry_time,
        'exit_time': exit_time,
        'entry_price': entry_price,
        'holding_candles': holding_candles,
        'max_profit_pct': round(max_profit_pct, 2),
        'min_profit_pct': round(min_profit_pct, 2),
    }


# ===========================================================================
# 멀티버스 시뮬레이션 실행
# ===========================================================================

def run_multiverse(
    start_date='20250224',
    end_date='20260313',
    screener_top_n=60,
    screener_min_amount=1_000_000_000,
    screener_max_gap=3.0,
    screener_min_price=5000,
    screener_max_price=500000,
    max_daily=5,
    cost_pct=0.33,
    stop_loss_pct=-5.0,
    take_profit_pct=6.0,
):
    """
    여러 아이디어를 단일 DB 스캔으로 동시에 시뮬레이션.
    각 종목/날짜에 대해 진입 조건 확인 후 아이디어별로 simulate_trade 변형을 각각 호출.
    """
    strategy = PricePositionStrategy()
    # 손익 설정을 config 값으로 통일
    strategy.config['stop_loss_pct'] = stop_loss_pct
    strategy.config['take_profit_pct'] = take_profit_pct

    print('=' * 80)
    print(f'개선 아이디어 멀티버스 시뮬레이션')
    print(f'기간: {start_date} ~ {end_date}')
    print(f'손절: {stop_loss_pct}%  익절: +{take_profit_pct}%  비용: {cost_pct:.2f}%/건')
    print('=' * 80)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'총 거래일: {len(trading_dates)}일\n')

    # 아이디어 목록: (label, simulate_fn)
    variants = {
        'baseline':          lambda df, ei: simulate_trade_baseline(df, ei, stop_loss_pct, take_profit_pct),
        'idea1_30m':         lambda df, ei: simulate_trade_idea1(df, ei, 30,  stop_loss_pct, take_profit_pct),
        'idea1_60m':         lambda df, ei: simulate_trade_idea1(df, ei, 60,  stop_loss_pct, take_profit_pct),
        'idea1_90m':         lambda df, ei: simulate_trade_idea1(df, ei, 90,  stop_loss_pct, take_profit_pct),
        'idea2_trail2%':     lambda df, ei: simulate_trade_idea2(df, ei, 2.0, stop_loss_pct, take_profit_pct),
        'idea2_trail3%':     lambda df, ei: simulate_trade_idea2(df, ei, 3.0, stop_loss_pct, take_profit_pct),
        'idea3_tight30m':    lambda df, ei: simulate_trade_idea3(df, ei, 30, -3.0, stop_loss_pct, take_profit_pct),
    }

    # 결과 저장소: {label: [trade_dict, ...]}
    all_results = {k: [] for k in variants}

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 20 == 0:
            base_cnt = len(all_results['baseline'])
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date})  baseline 거래: {base_cnt}건')

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

                # 진입 캔들 탐색 (baseline과 동일한 진입 조건)
                entry_idx = None
                for candle_idx in range(10, len(df) - 10):
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
                    entry_idx = candle_idx
                    break

                if entry_idx is None:
                    continue

                # 각 아이디어별로 동일 진입점에서 시뮬
                pct_from_open = (df.iloc[entry_idx]['close'] / day_open - 1) * 100
                base_record = {
                    'date': trade_date,
                    'stock_code': stock_code,
                    'weekday': weekday,
                    'pct_from_open': pct_from_open,
                }

                for label, sim_fn in variants.items():
                    result = sim_fn(df, entry_idx)
                    if result:
                        all_results[label].append({**base_record, **result})

                # baseline 기준으로 record_trade (동시 진입 중복 방지)
                strategy.record_trade(stock_code, trade_date)

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n수집 완료.')
    for k, v in all_results.items():
        print(f'  {k}: {len(v)}건 진입')

    # 동시보유 제한 적용
    print(f'\n동시보유 {max_daily}종목 제한 적용 중...')
    limited_results = {}
    for label, trades in all_results.items():
        if not trades:
            limited_results[label] = pd.DataFrame()
            continue
        df_trades = pd.DataFrame(trades)
        limited = apply_daily_limit(df_trades, max_daily)
        limited_results[label] = limited

    return limited_results


# ===========================================================================
# 결과 출력
# ===========================================================================

def summarize(label, trades_df, cost_pct, baseline_stats=None):
    """단일 variant 통계 계산 및 반환 (dict)"""
    if trades_df is None or len(trades_df) == 0:
        return {
            'label': label, 'total': 0, 'wins': 0, 'winrate': 0.0,
            'avg_pnl': 0.0, 'avg_net': 0.0, 'fixed_return': 0.0,
        }

    total = len(trades_df)
    wins = (trades_df['result'] == 'WIN').sum()
    winrate = wins / total * 100
    avg_pnl = trades_df['pnl'].mean()
    avg_net = avg_pnl - cost_pct

    cap = calc_fixed_capital_returns(trades_df, cost_pct=cost_pct)
    fixed_return = cap['total_return_pct']

    return {
        'label': label,
        'total': total,
        'wins': wins,
        'winrate': winrate,
        'avg_pnl': avg_pnl,
        'avg_net': avg_net,
        'fixed_return': fixed_return,
    }


def print_exit_breakdown(label, trades_df):
    """청산 사유별 분해"""
    if trades_df is None or len(trades_df) == 0:
        return
    print(f'\n  [{label}] 청산 사유별:')
    for reason in sorted(trades_df['exit_reason'].unique()):
        f = trades_df[trades_df['exit_reason'] == reason]
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        avg = f['pnl'].mean()
        print(f'    {reason:20s}: {len(f):4d}건  {w:4d}승 {len(f)-w:4d}패  '
              f'승률{rate:5.1f}%  평균{avg:+.2f}%')


def print_comparison_table(stats_list, cost_pct):
    """비교 테이블 출력"""
    base = stats_list[0]

    print('\n')
    print('=' * 100)
    print('  개선 아이디어 비교 결과 (동시보유 5종목 제한, 고정자본 1000만, 건당투자 20%)')
    print(f'  비용: {cost_pct:.2f}%/건 (수수료+세금+슬리피지)')
    print('=' * 100)
    header = (f"{'전략':>22} | {'거래':>5} | {'승률':>6} | {'평균수익(순)':>10} | "
              f"{'고정수익률':>10} | {'vs baseline':>11}")
    print(header)
    print('-' * 100)

    for s in stats_list:
        delta = s['fixed_return'] - base['fixed_return']
        delta_str = f'{delta:+.2f}%p' if s['label'] != 'baseline' else '  (기준)'
        print(
            f"  {s['label']:>20} | {s['total']:>5} | {s['winrate']:>5.1f}% | "
            f"{s['avg_net']:>+9.2f}% | {s['fixed_return']:>+9.2f}% | {delta_str:>11}"
        )

    print('=' * 100)


def print_monthly_comparison(limited_results, cost_pct):
    """월별 baseline vs 최고 아이디어 비교"""
    base_df = limited_results.get('baseline')
    if base_df is None or len(base_df) == 0:
        return

    from simulate_with_screener import calc_fixed_capital_returns as cfcr

    # 최고 성과 아이디어 찾기
    best_label = 'baseline'
    best_return = cfcr(base_df, cost_pct=cost_pct)['total_return_pct']
    for label, df in limited_results.items():
        if label == 'baseline' or df is None or len(df) == 0:
            continue
        r = cfcr(df, cost_pct=cost_pct)['total_return_pct']
        if r > best_return:
            best_return = r
            best_label = label

    if best_label == 'baseline':
        # 2위도 출력
        print('\n  [월별 비교] baseline이 최고 성과 — 모든 아이디어가 baseline 미달')
        best_label = sorted(
            [(l, cfcr(d, cost_pct=cost_pct)['total_return_pct'])
             for l, d in limited_results.items() if l != 'baseline' and d is not None and len(d) > 0],
            key=lambda x: -x[1]
        )[0][0] if any(
            len(d) > 0 for l, d in limited_results.items() if l != 'baseline' and d is not None
        ) else 'baseline'

    best_df = limited_results[best_label]

    base_cap = cfcr(base_df, cost_pct=cost_pct)
    best_cap = cfcr(best_df, cost_pct=cost_pct)

    months = sorted(set(list(base_cap['monthly_returns'].keys()) +
                        list(best_cap['monthly_returns'].keys())))

    print(f'\n월별 비교: baseline  vs  {best_label}')
    print(f"{'월':>8} | {'baseline':>10} | {best_label:>14} | {'차이':>8}")
    print('-' * 50)
    for m in months:
        b = base_cap['monthly_returns'].get(m, 0.0)
        x = best_cap['monthly_returns'].get(m, 0.0)
        diff = x - b
        print(f"  {m}  | {b:>+9.2f}% | {x:>+13.2f}% | {diff:>+7.2f}%p")
    print(f"  {'합계':>6}  | {base_cap['total_return_pct']:>+9.2f}% | "
          f"{best_cap['total_return_pct']:>+13.2f}% | "
          f"{best_cap['total_return_pct'] - base_cap['total_return_pct']:>+7.2f}%p")


# ===========================================================================
# main
# ===========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description='개선 아이디어 멀티버스 시뮬레이션')
    parser.add_argument('--start',  default='20250224', help='시작일 (기본 20250224)')
    parser.add_argument('--end',    default='20260313', help='종료일 (기본 20260313)')
    parser.add_argument('--cost',   type=float, default=0.33, help='건당 왕복 비용 %% (기본 0.33)')
    parser.add_argument('--max-daily', type=int, default=5,   help='동시보유 최대 종목 (기본 5)')
    args = parser.parse_args()

    cost_pct = args.cost
    max_daily = args.max_daily

    limited_results = run_multiverse(
        start_date=args.start,
        end_date=args.end,
        max_daily=max_daily,
        cost_pct=cost_pct,
        stop_loss_pct=-5.0,
        take_profit_pct=6.0,
    )

    # 통계 수집
    stats_list = []
    for label in [
        'baseline',
        'idea1_30m',
        'idea1_60m',
        'idea1_90m',
        'idea2_trail2%',
        'idea2_trail3%',
        'idea3_tight30m',
    ]:
        df = limited_results.get(label)
        s = summarize(label, df, cost_pct)
        stats_list.append(s)

    # 메인 비교 테이블
    print_comparison_table(stats_list, cost_pct)

    # 아이디어별 설명
    print('\n아이디어 설명:')
    print('  baseline      : 고정 손절 -5%, 익절 +6% (현재 전략)')
    print('  idea1_30m     : 아이디어1 - 진입 후 30분 경과 시 수익 < 0% 이면 즉시 청산')
    print('  idea1_60m     : 아이디어1 - 진입 후 60분 경과 시 수익 < 0% 이면 즉시 청산')
    print('  idea1_90m     : 아이디어1 - 진입 후 90분 경과 시 수익 < 0% 이면 즉시 청산')
    print('  idea2_trail2% : 아이디어2 - 장중 최고점 대비 -2% 하락 시 트레일링 스탑')
    print('  idea2_trail3% : 아이디어2 - 장중 최고점 대비 -3% 하락 시 트레일링 스탑')
    print('  idea3_tight30m: 아이디어3 - 진입 후 30분 내 손절 -3%, 이후 -5%')

    # 청산 사유별 상세
    print('\n\n=== 청산 사유별 상세 ===')
    for label in [
        'baseline', 'idea1_30m', 'idea1_60m', 'idea1_90m',
        'idea2_trail2%', 'idea2_trail3%', 'idea3_tight30m',
    ]:
        df = limited_results.get(label)
        print_exit_breakdown(label, df)

    # 월별 비교
    print('\n\n=== 월별 비교 ===')
    print_monthly_comparison(limited_results, cost_pct)

    print('\nDone.')


if __name__ == '__main__':
    main()
