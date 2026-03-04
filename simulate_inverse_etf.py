"""
인버스 ETF 멀티버스 시뮬레이션

하락장 감지 시 인버스 ETF 매수 전략의 다양한 시나리오를 비교.

인버스 ETF 수익은 KS11/KQ11 일봉 데이터로 합성:
- 인버스 1x ≈ -1 × 지수 장중 수익률 (시가→종가)
- 인버스 2x ≈ -2 × 지수 장중 수익률 (시가→종가)
- 손절/익절은 지수 고가/저가 기반으로 체크

Usage:
  python simulate_inverse_etf.py --start 20250224 --end 20260223
  python simulate_inverse_etf.py --start 20250224 --end 20260223 --max-daily 5
"""
import psycopg2
import pandas as pd
import numpy as np
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from simulate_with_screener import (
    run_simulation, apply_daily_limit, calc_capital_returns
)


# ===================================================================
# 데이터 로드
# ===================================================================

def load_index_daily():
    """
    KS11/KQ11 일봉 데이터 로드 → 인버스 ETF 수익 합성용

    Returns:
        {date: {
            'kospi': {open, close, high, low},
            'kosdaq': {open, close, high, low},
        }}
    """
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute('''
        SELECT stock_code, stck_bsop_date,
               CAST(stck_oprc AS FLOAT) as open,
               CAST(stck_clpr AS FLOAT) as close,
               CAST(stck_hgpr AS FLOAT) as high,
               CAST(stck_lwpr AS FLOAT) as low
        FROM daily_candles
        WHERE stock_code IN ('KS11', 'KQ11')
        ORDER BY stck_bsop_date
    ''')
    rows = cur.fetchall()
    conn.close()

    data = defaultdict(dict)
    for code, dt, opn, cls, high, low in rows:
        key = 'kospi' if code == 'KS11' else 'kosdaq'
        data[dt][key] = {
            'open': opn, 'close': cls, 'high': high, 'low': low,
        }

    # 전일 종가 대비 갭 계산 (regime detection용)
    dates = sorted(data.keys())
    prev_close = {}
    for dt in dates:
        d = data[dt]
        for key in ['kospi', 'kosdaq']:
            if key in d and key in prev_close:
                d[key]['prev_close'] = prev_close[key]
                d[key]['gap_pct'] = (d[key]['open'] / prev_close[key] - 1) * 100
            else:
                d[key]['prev_close'] = d[key].get('open', 0)
                d[key]['gap_pct'] = 0.0
        prev_close = {k: v['close'] for k, v in d.items() if 'close' in v}

    return dict(data)


def calc_inverse_return(index_data, multiplier=1, stop_loss=None, take_profit=None):
    """
    인버스 ETF 장중 수익률 계산 (시가 매수 → 종가 매도)

    Args:
        index_data: {open, close, high, low}
        multiplier: 배수 (1 or 2)
        stop_loss: 손절 비율 (예: -4.0), None이면 미적용
        take_profit: 익절 비율 (예: 5.0), None이면 미적용

    Returns:
        (pnl_pct, exit_reason)
    """
    opn = index_data['open']
    cls = index_data['close']
    high = index_data['high']
    low = index_data['low']

    if opn <= 0:
        return 0.0, '무효'

    # 인버스: 지수가 내리면 수익, 올리면 손실
    # 최악(지수 최고점): inverse_worst = -multiplier * (high / open - 1)
    # 최선(지수 최저점): inverse_best = -multiplier * (low / open - 1)
    inverse_worst = -multiplier * (high / opn - 1) * 100
    inverse_best = -multiplier * (low / opn - 1) * 100
    inverse_close = -multiplier * (cls / opn - 1) * 100

    # 손절 체크 (최악 시나리오)
    if stop_loss is not None and inverse_worst <= stop_loss:
        return stop_loss, '손절'

    # 익절 체크 (최선 시나리오)
    if take_profit is not None and inverse_best >= take_profit:
        return take_profit, '익절'

    # 장마감 청산
    return inverse_close, '장마감'


# ===================================================================
# 통계 계산
# ===================================================================

def calc_combined_capital(stock_trades_df, inverse_trades, initial_capital=10_000_000, buy_ratio=0.20):
    """
    개별주 + 인버스 ETF 혼합 원금 수익률 계산

    Args:
        stock_trades_df: 개별주 거래 DataFrame (date, pnl, ...)
        inverse_trades: [{date, pnl, positions, ...}, ...]
        initial_capital: 초기 자본
        buy_ratio: 건당 투자 비율

    Returns:
        dict: {final_capital, total_return_pct, monthly_returns}
    """
    # 날짜별 PnL 합산
    daily_pnl = defaultdict(list)

    if stock_trades_df is not None and len(stock_trades_df) > 0:
        for _, row in stock_trades_df.iterrows():
            daily_pnl[row['date']].append(row['pnl'])

    for inv in inverse_trades:
        for _ in range(inv.get('positions', 1)):
            daily_pnl[inv['date']].append(inv['pnl'])

    capital = initial_capital
    monthly_returns = {}
    current_month = None
    month_start_capital = capital

    for date in sorted(daily_pnl.keys()):
        month = date[:6]
        if month != current_month:
            if current_month is not None:
                monthly_returns[current_month] = (month_start_capital, capital)
            current_month = month
            month_start_capital = capital

        day_start_capital = capital
        for pnl in daily_pnl[date]:
            invest_amount = day_start_capital * buy_ratio
            profit = invest_amount * (pnl / 100)
            capital += profit

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


def calc_stats(stock_trades_df, inverse_trades=None):
    """통합 통계 계산"""
    # 개별주 통계
    stock_count = len(stock_trades_df) if stock_trades_df is not None and len(stock_trades_df) > 0 else 0
    inv_count = len(inverse_trades) if inverse_trades else 0

    all_pnl = []
    if stock_count > 0:
        all_pnl.extend(stock_trades_df['pnl'].tolist())
    if inverse_trades:
        for inv in inverse_trades:
            for _ in range(inv.get('positions', 1)):
                all_pnl.append(inv['pnl'])

    total = len(all_pnl)
    if total == 0:
        return {
            'total': 0, 'stock_trades': 0, 'inv_trades': 0,
            'wins': 0, 'winrate': 0, 'avg_pnl': 0, 'capital_return': 0,
            'inv_avg_pnl': 0, 'inv_wins': 0, 'inv_winrate': 0,
        }

    wins = sum(1 for p in all_pnl if p > 0)
    cap = calc_combined_capital(stock_trades_df, inverse_trades or [])

    # 인버스 전용 통계
    inv_pnls = []
    if inverse_trades:
        for inv in inverse_trades:
            for _ in range(inv.get('positions', 1)):
                inv_pnls.append(inv['pnl'])
    inv_wins = sum(1 for p in inv_pnls if p > 0)

    return {
        'total': total,
        'stock_trades': stock_count,
        'inv_trades': len(inv_pnls),
        'wins': wins,
        'winrate': wins / total * 100 if total > 0 else 0,
        'avg_pnl': np.mean(all_pnl),
        'capital_return': cap['total_return_pct'],
        'monthly_returns': cap.get('monthly_returns', {}),
        'inv_avg_pnl': np.mean(inv_pnls) if inv_pnls else 0,
        'inv_wins': inv_wins,
        'inv_winrate': inv_wins / len(inv_pnls) * 100 if inv_pnls else 0,
    }


# ===================================================================
# 레짐 감지 함수
# ===================================================================

def detect_regime_nxt_gap(date, index_data, threshold=-0.5):
    """NXT 프록시: 당일 시가 갭 기반 하락 감지"""
    d = index_data.get(date)
    if not d:
        return False
    kospi_gap = d.get('kospi', {}).get('gap_pct', 0)
    kosdaq_gap = d.get('kosdaq', {}).get('gap_pct', 0)
    return kospi_gap <= threshold or kosdaq_gap <= threshold


def detect_regime_prev_trade(date, all_dates, daily_results, condition='alllose'):
    """전일 매매결과 기반 하락 감지"""
    try:
        idx = all_dates.index(date)
    except ValueError:
        return False
    if idx == 0:
        return False

    prev = all_dates[idx - 1]
    r = daily_results.get(prev)
    if not r or r['trades'] < 1:
        return False

    if condition == 'alllose':
        return r['trades'] >= 2 and r['winrate'] == 0
    elif condition == 'minus':
        return r['avg_pnl'] < 0
    elif condition == 'bad':
        return r['avg_pnl'] < -2.0
    return False


def detect_regime_prev_index(date, index_data, threshold=-1.0):
    """전일 지수 등락 기반 하락 감지"""
    dates = sorted(index_data.keys())
    try:
        idx = dates.index(date)
    except ValueError:
        return False
    if idx == 0:
        return False

    prev = dates[idx - 1]
    d = index_data.get(prev)
    if not d:
        return False

    for key in ['kospi', 'kosdaq']:
        info = d.get(key, {})
        if 'prev_close' in info and info['prev_close'] > 0:
            chg = (info['close'] / info['prev_close'] - 1) * 100
            if chg <= threshold:
                return True
    return False


# ===================================================================
# 멀티버스 엔진
# ===================================================================

def run_multiverse(trades_df, index_data, max_daily=5):
    """인버스 ETF 멀티버스 시뮬레이션"""

    limited_df = apply_daily_limit(trades_df, max_daily)
    all_dates = sorted(limited_df['date'].unique())

    # 일별 매매결과
    daily_results = {}
    for date in all_dates:
        day = limited_df[limited_df['date'] == date]
        wins = (day['result'] == 'WIN').sum()
        daily_results[date] = {
            'trades': len(day),
            'wins': int(wins),
            'winrate': wins / len(day) * 100 if len(day) > 0 else 0,
            'avg_pnl': day['pnl'].mean(),
        }

    # 인버스 데이터 가용 날짜 (지수 데이터가 있는 날만)
    avail_dates = set(all_dates) & set(index_data.keys())
    unavail = set(all_dates) - avail_dates

    print('\n')
    print('=' * 120)
    print('  인버스 ETF 멀티버스 시뮬레이션')
    print('=' * 120)
    print(f'  거래일: {len(all_dates)}일, 지수데이터 가용: {len(avail_dates)}일, '
          f'미가용: {len(unavail)}일')
    if unavail:
        print(f'  ※ 지수 데이터 없는 날짜: {sorted(unavail)[:5]}...')

    # 기준선 (개별주만)
    base = calc_stats(limited_df)
    print(f'\n  기준선 (개별주만, max={max_daily}): {base["total"]}건, '
          f'승률 {base["winrate"]:.1f}%, 원금수익률 {base["capital_return"]:+.2f}%')

    # 인버스 수익률 미리 계산
    inv_returns = {}  # {date: {(index, mult): (pnl, reason)}}
    for date in avail_dates:
        d = index_data[date]
        inv_returns[date] = {}
        for idx_key in ['kospi', 'kosdaq']:
            if idx_key not in d:
                continue
            for mult in [1, 2]:
                # 손절/익절 없이
                pnl, reason = calc_inverse_return(d[idx_key], mult)
                inv_returns[date][(idx_key, mult, 'none')] = (pnl, reason)
                # 손절 -4%, 익절 +5%
                pnl2, reason2 = calc_inverse_return(d[idx_key], mult, stop_loss=-4.0, take_profit=5.0)
                inv_returns[date][(idx_key, mult, 'sl4tp5')] = (pnl2, reason2)
                # 손절 -3%, 익절 +5%
                pnl3, reason3 = calc_inverse_return(d[idx_key], mult, stop_loss=-3.0, take_profit=5.0)
                inv_returns[date][(idx_key, mult, 'sl3tp5')] = (pnl3, reason3)

    all_scenarios = []  # (name, stats, trigger_count, category)

    # ================================================================
    # 카테고리 1: 매일 인버스 헤지 (개별주 + 인버스 포지션)
    # ================================================================
    cat1 = []
    for idx_key in ['kospi', 'kosdaq']:
        for mult in [1, 2]:
            for num_pos in [1, 2]:
                label = f'{idx_key.upper()} 인버스{mult}x × {num_pos}포지션'
                inv_trades = []
                for date in all_dates:
                    if date not in avail_dates:
                        continue
                    ret = inv_returns[date].get((idx_key, mult, 'none'))
                    if ret:
                        inv_trades.append({
                            'date': date, 'pnl': ret[0], 'reason': ret[1],
                            'positions': num_pos,
                        })
                s = calc_stats(limited_df, inv_trades)
                cat1.append((f'1. 매일 {label}', s, len(inv_trades)))

    _print_category('카테고리 1: 매일 인버스 헤지 (개별주 유지 + 인버스 추가)', cat1, base)
    for name, s, cnt in cat1:
        all_scenarios.append((name, s, cnt, '매일헤지'))

    # ================================================================
    # 카테고리 2: NXT 갭 하락 시 → 인버스 전환 (개별주 스킵)
    # ================================================================
    cat2 = []
    for gap_th in [-0.3, -0.5, -1.0, -1.5]:
        trigger_dates = set()
        for date in all_dates:
            if detect_regime_nxt_gap(date, index_data, gap_th):
                trigger_dates.add(date)

        for idx_key in ['kospi']:
            for mult in [1, 2]:
                for num_pos in [2, 3, 5]:
                    label = f'NXT갭{gap_th}%→{idx_key.upper()}인버스{mult}x×{num_pos}'
                    # 트리거 날: 개별주 스킵, 인버스 매수
                    stock_filtered = limited_df[~limited_df['date'].isin(trigger_dates)]
                    inv_trades = []
                    for date in trigger_dates & avail_dates:
                        ret = inv_returns[date].get((idx_key, mult, 'none'))
                        if ret:
                            inv_trades.append({
                                'date': date, 'pnl': ret[0], 'reason': ret[1],
                                'positions': num_pos,
                            })
                    s = calc_stats(stock_filtered, inv_trades)
                    cat2.append((f'2. {label}', s, len(trigger_dates)))

    _print_category('카테고리 2: NXT 갭 하락 → 인버스 전환 (개별주 스킵)', cat2, base)
    for name, s, cnt in cat2:
        all_scenarios.append((name, s, cnt, 'NXT전환'))

    # ================================================================
    # 카테고리 3: NXT 갭 하락 시 → 개별주 축소 + 인버스 추가
    # ================================================================
    cat3 = []
    for gap_th in [-0.3, -0.5, -1.0]:
        trigger_dates = set()
        for date in all_dates:
            if detect_regime_nxt_gap(date, index_data, gap_th):
                trigger_dates.add(date)

        for idx_key in ['kospi']:
            for mult in [1, 2]:
                for stock_limit, inv_pos in [(3, 2), (2, 3), (3, 1), (2, 2)]:
                    label = f'NXT갭{gap_th}%→개별{stock_limit}+인버스{mult}x×{inv_pos}'
                    # 트리거 날: 개별주 제한 + 인버스 추가
                    from simulate_regime_filter import apply_daily_limit_variable
                    overrides = {d: stock_limit for d in trigger_dates}
                    stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
                    inv_trades = []
                    for date in trigger_dates & avail_dates:
                        ret = inv_returns[date].get((idx_key, mult, 'none'))
                        if ret:
                            inv_trades.append({
                                'date': date, 'pnl': ret[0], 'reason': ret[1],
                                'positions': inv_pos,
                            })
                    s = calc_stats(stock_df, inv_trades)
                    cat3.append((f'3. {label}', s, len(trigger_dates)))

    _print_category('카테고리 3: NXT 갭 하락 → 개별주 축소 + 인버스 추가', cat3, base)
    for name, s, cnt in cat3:
        all_scenarios.append((name, s, cnt, 'NXT혼합'))

    # ================================================================
    # 카테고리 4: 전일 매매결과 기반 → 인버스 전환/추가
    # ================================================================
    cat4 = []
    for cond_label, cond_key in [('전패', 'alllose'), ('마이너스', 'minus'), ('평균<-2%', 'bad')]:
        trigger_dates = set()
        for date in all_dates:
            if detect_regime_prev_trade(date, all_dates, daily_results, cond_key):
                trigger_dates.add(date)

        for mult in [1, 2]:
            # 전환 (개별주 스킵)
            stock_filtered = limited_df[~limited_df['date'].isin(trigger_dates)]
            inv_trades = []
            for date in trigger_dates & avail_dates:
                ret = inv_returns[date].get(('kospi', mult, 'none'))
                if ret:
                    inv_trades.append({
                        'date': date, 'pnl': ret[0], 'reason': ret[1],
                        'positions': 3,
                    })
            s = calc_stats(stock_filtered, inv_trades)
            cat4.append((f'4. T-1 {cond_label}→KOSPI인버스{mult}x×3(전환)', s, len(trigger_dates)))

            # 혼합 (개별주 3 + 인버스 2)
            from simulate_regime_filter import apply_daily_limit_variable
            overrides = {d: 3 for d in trigger_dates}
            stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
            inv_trades2 = []
            for date in trigger_dates & avail_dates:
                ret = inv_returns[date].get(('kospi', mult, 'none'))
                if ret:
                    inv_trades2.append({
                        'date': date, 'pnl': ret[0], 'reason': ret[1],
                        'positions': 2,
                    })
            s2 = calc_stats(stock_df, inv_trades2)
            cat4.append((f'4. T-1 {cond_label}→개별3+인버스{mult}x×2', s2, len(trigger_dates)))

    _print_category('카테고리 4: 전일 매매결과 → 인버스 전환/혼합', cat4, base)
    for name, s, cnt in cat4:
        all_scenarios.append((name, s, cnt, 'T-1'))

    # ================================================================
    # 카테고리 5: 복합 조건 (NXT + T-1)
    # ================================================================
    cat5 = []

    # 5A: NXT 갭 -0.5% AND T-1 마이너스 → 인버스 전환
    for mult in [1, 2]:
        trigger_dates = set()
        for date in all_dates:
            nxt = detect_regime_nxt_gap(date, index_data, -0.5)
            t1 = detect_regime_prev_trade(date, all_dates, daily_results, 'minus')
            if nxt and t1:
                trigger_dates.add(date)

        stock_filtered = limited_df[~limited_df['date'].isin(trigger_dates)]
        inv_trades = []
        for date in trigger_dates & avail_dates:
            ret = inv_returns[date].get(('kospi', mult, 'none'))
            if ret:
                inv_trades.append({
                    'date': date, 'pnl': ret[0], 'reason': ret[1],
                    'positions': 5,
                })
        s = calc_stats(stock_filtered, inv_trades)
        cat5.append((f'5A. NXT갭-0.5%+T-1마이너스→인버스{mult}x×5(전환)', s, len(trigger_dates)))

    # 5B: NXT 갭 -0.5% OR T-1 전패 → 개별3 + 인버스2
    for mult in [1, 2]:
        trigger_dates = set()
        for date in all_dates:
            nxt = detect_regime_nxt_gap(date, index_data, -0.5)
            t1 = detect_regime_prev_trade(date, all_dates, daily_results, 'alllose')
            if nxt or t1:
                trigger_dates.add(date)

        from simulate_regime_filter import apply_daily_limit_variable
        overrides = {d: 3 for d in trigger_dates}
        stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
        inv_trades = []
        for date in trigger_dates & avail_dates:
            ret = inv_returns[date].get(('kospi', mult, 'none'))
            if ret:
                inv_trades.append({
                    'date': date, 'pnl': ret[0], 'reason': ret[1],
                    'positions': 2,
                })
        s = calc_stats(stock_df, inv_trades)
        cat5.append((f'5B. NXT-0.5%ORT-1전패→개별3+인버스{mult}x×2', s, len(trigger_dates)))

    # 5C: 전일 지수 -1% → 인버스 전환
    for mult in [1, 2]:
        trigger_dates = set()
        for date in all_dates:
            if detect_regime_prev_index(date, index_data, -1.0):
                trigger_dates.add(date)

        stock_filtered = limited_df[~limited_df['date'].isin(trigger_dates)]
        inv_trades = []
        for date in trigger_dates & avail_dates:
            ret = inv_returns[date].get(('kospi', mult, 'none'))
            if ret:
                inv_trades.append({
                    'date': date, 'pnl': ret[0], 'reason': ret[1],
                    'positions': 5,
                })
        s = calc_stats(stock_filtered, inv_trades)
        cat5.append((f'5C. 전일지수-1%→인버스{mult}x×5(전환)', s, len(trigger_dates)))

    # 5D: NXT 갭 + 전일 지수 하락 → 개별2 + 인버스3
    for mult in [1, 2]:
        trigger_dates = set()
        for date in all_dates:
            nxt = detect_regime_nxt_gap(date, index_data, -0.5)
            prev_idx = detect_regime_prev_index(date, index_data, -1.0)
            if nxt and prev_idx:
                trigger_dates.add(date)

        from simulate_regime_filter import apply_daily_limit_variable
        overrides = {d: 2 for d in trigger_dates}
        stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
        inv_trades = []
        for date in trigger_dates & avail_dates:
            ret = inv_returns[date].get(('kospi', mult, 'none'))
            if ret:
                inv_trades.append({
                    'date': date, 'pnl': ret[0], 'reason': ret[1],
                    'positions': 3,
                })
        s = calc_stats(stock_df, inv_trades)
        cat5.append((f'5D. NXT-0.5%+전일지수-1%→개별2+인버스{mult}x×3', s, len(trigger_dates)))

    # 5E: 단계적 대응
    for mult in [1, 2]:
        trigger_dates = set()
        strong_dates = set()  # 강한 신호 → 인버스 전환
        mild_dates = set()    # 약한 신호 → 혼합

        for date in all_dates:
            nxt = detect_regime_nxt_gap(date, index_data, -0.5)
            nxt_strong = detect_regime_nxt_gap(date, index_data, -1.0)
            t1_bad = detect_regime_prev_trade(date, all_dates, daily_results, 'minus')
            t1_alllose = detect_regime_prev_trade(date, all_dates, daily_results, 'alllose')
            prev_idx = detect_regime_prev_index(date, index_data, -1.0)

            # 강한 신호: NXT -1% + (T-1 전패 OR 전일 지수 -1%)
            if nxt_strong and (t1_alllose or prev_idx):
                strong_dates.add(date)
                trigger_dates.add(date)
            # 약한 신호: NXT -0.5% + T-1 마이너스
            elif nxt and t1_bad:
                mild_dates.add(date)
                trigger_dates.add(date)

        overrides = {}
        for d in strong_dates:
            overrides[d] = 0  # 개별주 완전 스킵
        for d in mild_dates:
            overrides[d] = 3  # 개별주 3종목

        stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
        inv_trades = []
        for date in trigger_dates & avail_dates:
            n_pos = 5 if date in strong_dates else 2
            ret = inv_returns[date].get(('kospi', mult, 'none'))
            if ret:
                inv_trades.append({
                    'date': date, 'pnl': ret[0], 'reason': ret[1],
                    'positions': n_pos,
                })
        s = calc_stats(stock_df, inv_trades)
        cat5.append((
            f'5E. 단계적(강{len(strong_dates)}일→인버스{mult}x×5, '
            f'약{len(mild_dates)}일→개별3+인버스{mult}x×2)',
            s, len(trigger_dates)))

    _print_category('카테고리 5: 복합 조건 (NXT + T-1 + 지수)', cat5, base)
    for name, s, cnt in cat5:
        all_scenarios.append((name, s, cnt, '복합'))

    # ================================================================
    # 카테고리 6: 인버스 ETF 손절/익절 적용
    # ================================================================
    cat6 = []
    best_scenarios = sorted(all_scenarios, key=lambda x: x[1]['capital_return'], reverse=True)[:3]

    # 상위 시나리오에 손절/익절 적용 재테스트
    for gap_th in [-0.5, -1.0]:
        trigger_dates = set()
        for date in all_dates:
            if detect_regime_nxt_gap(date, index_data, gap_th):
                trigger_dates.add(date)

        for mult in [2]:
            for sl_key, sl_label in [('sl4tp5', '손절4%익절5%'), ('sl3tp5', '손절3%익절5%')]:
                stock_filtered = limited_df[~limited_df['date'].isin(trigger_dates)]
                inv_trades = []
                for date in trigger_dates & avail_dates:
                    ret = inv_returns[date].get(('kospi', mult, sl_key))
                    if ret:
                        inv_trades.append({
                            'date': date, 'pnl': ret[0], 'reason': ret[1],
                            'positions': 5,
                        })
                s = calc_stats(stock_filtered, inv_trades)
                cat6.append((f'6. NXT갭{gap_th}%→인버스{mult}x×5({sl_label})',
                             s, len(trigger_dates)))

    _print_category('카테고리 6: 인버스 ETF + 손절/익절', cat6, base)
    for name, s, cnt in cat6:
        all_scenarios.append((name, s, cnt, '손절익절'))

    # ================================================================
    # 전체 비교 요약
    # ================================================================
    print('\n')
    print('=' * 130)
    print('  전체 비교 요약 (원금수익률 기준 정렬)')
    print('=' * 130)
    print(f'  {"시나리오":<65} {"총거래":>5} {"개별주":>5} {"인버스":>5} '
          f'{"승률":>6} {"원금수익률":>10} {"개선":>8} {"인버스승률":>8}')
    print('  ' + '-' * 125)
    print(f'  {"[기준선] 개별주만 (max=" + str(max_daily) + ")":<65} '
          f'{base["total"]:>4}건 {base["stock_trades"]:>4}건 {"0":>4}건 '
          f'{base["winrate"]:>5.1f}% {base["capital_return"]:>+9.2f}% '
          f'{"":>8} {"":>8}')

    sorted_all = sorted(all_scenarios, key=lambda x: x[1]['capital_return'], reverse=True)
    for name, s, cnt, cat in sorted_all:
        improvement = s['capital_return'] - base['capital_return']
        marker = ' ★' if improvement > 0 else ''
        inv_wr = f'{s["inv_winrate"]:.0f}%' if s['inv_trades'] > 0 else ''
        print(f'  {name:<65} {s["total"]:>4}건 {s["stock_trades"]:>4}건 '
              f'{s["inv_trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+7.2f}%p '
              f'{inv_wr:>7}{marker}')

    # ================================================================
    # 인버스 수익률 일별 분석
    # ================================================================
    print('\n')
    print('=' * 130)
    print('  인버스 ETF 일별 수익률 분석 (KOSPI 기준)')
    print('=' * 130)

    down_days = 0
    up_days = 0
    inv1_down_pnl = []
    inv1_up_pnl = []

    for date in sorted(avail_dates):
        ret1 = inv_returns[date].get(('kospi', 1, 'none'))
        if ret1:
            if ret1[0] > 0:
                down_days += 1
                inv1_down_pnl.append(ret1[0])
            else:
                up_days += 1
                inv1_up_pnl.append(ret1[0])

    print(f'  인버스 1x 양수일 (=지수하락): {down_days}일, 평균 +{np.mean(inv1_down_pnl):.2f}%')
    print(f'  인버스 1x 음수일 (=지수상승): {up_days}일, 평균 {np.mean(inv1_up_pnl):.2f}%')
    print(f'  인버스 1x 전체: 평균 {np.mean(inv1_down_pnl + inv1_up_pnl):.3f}%')

    # 월별 인버스 성과
    print(f'\n  월별 KOSPI 인버스 1x / 2x 수익률:')
    monthly_inv = defaultdict(lambda: {'inv1': [], 'inv2': []})
    for date in sorted(avail_dates):
        month = date[:6]
        ret1 = inv_returns[date].get(('kospi', 1, 'none'))
        ret2 = inv_returns[date].get(('kospi', 2, 'none'))
        if ret1:
            monthly_inv[month]['inv1'].append(ret1[0])
        if ret2:
            monthly_inv[month]['inv2'].append(ret2[0])

    print(f'  {"월":>8} {"인버스1x합":>10} {"인버스2x합":>10} {"거래일":>5} {"인버스1x양수일":>12}')
    for month in sorted(monthly_inv.keys()):
        d = monthly_inv[month]
        sum1 = sum(d['inv1'])
        sum2 = sum(d['inv2'])
        pos1 = sum(1 for x in d['inv1'] if x > 0)
        print(f'  {month[:4]}-{month[4:]:>4} {sum1:>+9.2f}% {sum2:>+9.2f}% '
              f'{len(d["inv1"]):>4}일 {pos1:>5}/{len(d["inv1"])}일')


def _print_category(title, scenarios, base_stats):
    """카테고리별 테이블 출력"""
    print('\n')
    print('#' * 130)
    print(f'#  {title}')
    print('#' * 130)
    print(f'  {"시나리오":<65} {"총거래":>5} {"승률":>6} {"원금수익률":>10} '
          f'{"개선":>8} {"적용일":>6} {"인버스평균":>10}')
    print('  ' + '-' * 125)
    print(f'  {"[기준선] 개별주만":<65} {base_stats["total"]:>4}건 '
          f'{base_stats["winrate"]:>5.1f}% {base_stats["capital_return"]:>+9.2f}% '
          f'{"":>8} {"":>6} {"":>10}')

    for name, s, cnt in scenarios:
        improvement = s['capital_return'] - base_stats['capital_return']
        inv_avg = f'{s["inv_avg_pnl"]:>+.2f}%' if s['inv_trades'] > 0 else ''
        marker = ' ★' if improvement > 0 else ''
        print(f'  {name:<65} {s["total"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+7.2f}%p '
              f'{cnt:>5}일 {inv_avg:>9}{marker}')


def main():
    parser = argparse.ArgumentParser(description='인버스 ETF 멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260223', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    args = parser.parse_args()

    print('=' * 130)
    print('인버스 ETF 멀티버스 시뮬레이션')
    print('  지수 일봉 기반 인버스 수익 합성 (KS11/KQ11)')
    print('=' * 130)

    print('\n[1/3] 지수 데이터 로드...')
    index_data = load_index_daily()
    print(f'  KS11/KQ11 데이터: {len(index_data)}일')

    print('\n[2/3] 개별주 시뮬레이션 실행...')
    trades_df = run_simulation(
        start_date=args.start,
        end_date=args.end,
        max_daily=0,
        verbose=True,
    )

    if trades_df is None or len(trades_df) == 0:
        print('거래 없음. 종료.')
        return

    print(f'\n[3/3] 인버스 ETF 멀티버스 시뮬레이션 ({len(trades_df)}건 기반)...')
    run_multiverse(trades_df, index_data, args.max_daily)

    print('\nDone!')


if __name__ == '__main__':
    main()
