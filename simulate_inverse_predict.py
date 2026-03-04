"""
인버스 ETF 하락 예측 전략 멀티버스 시뮬레이션

핵심 발견: "폭락은 연속된다" — 평균회귀(RSI, MA 괴리)는 상승장에서 실패,
하락 모멘텀(전일 하락 → 다음날도 하락) 신호만 유효.

예측 신호:
  A. 하락 모멘텀: 전일 큰 하락 → 다음날 인버스
  B. 누적 하락: 5일 누적 수익률 마이너스 → 인버스
  C. 변동성 폭발: 전일 고가-저가 범위 확대 → 인버스
  D. NXT 갭 + 모멘텀 복합
  E. 복합 점수 기반 단계적 대응

Usage:
  python simulate_inverse_predict.py --start 20250224 --end 20260304
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
from simulate_regime_filter import apply_daily_limit_variable


# ===================================================================
# 지수 데이터 로드 및 기술 지표 계산
# ===================================================================

def load_index_with_indicators():
    """
    KS11/KQ11 일봉 데이터 + 기술 지표 계산

    Returns:
        {date: {
            kospi_open, kospi_close, kospi_high, kospi_low,
            kospi_ret, kospi_intra, kospi_range,
            kospi_ret_5d, kospi_rsi, kospi_ma20_gap,
            kospi_gap, kosdaq_gap,
            (kosdaq 동일 필드들...)
        }}
    """
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute('''
        SELECT stock_code, stck_bsop_date,
               CAST(stck_oprc AS FLOAT), CAST(stck_clpr AS FLOAT),
               CAST(stck_hgpr AS FLOAT), CAST(stck_lwpr AS FLOAT)
        FROM daily_candles
        WHERE stock_code IN ('KS11', 'KQ11')
        ORDER BY stck_bsop_date
    ''')
    rows = cur.fetchall()
    conn.close()

    # 코드별 분리
    raw = defaultdict(list)
    for code, dt, opn, cls, high, low in rows:
        raw[code].append((dt, float(opn), float(cls), float(high), float(low)))

    # 지표 계산 함수
    def calc_rsi(closes, period=14):
        rsi = np.full(len(closes), np.nan)
        if len(closes) < period + 1:
            return rsi
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period]) + 1e-10
        rsi[period] = 100 - 100 / (1 + avg_gain / avg_loss)
        for i in range(period + 1, len(closes)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period + 1e-10
            rsi[i] = 100 - 100 / (1 + avg_gain / avg_loss)
        return rsi

    # 코드별 지표 계산
    indicators = {}  # {code: {date: {...}}}
    for code, data in raw.items():
        prefix = 'kospi' if code == 'KS11' else 'kosdaq'
        dates = [d[0] for d in data]
        opens = np.array([d[1] for d in data])
        closes = np.array([d[2] for d in data])
        highs = np.array([d[3] for d in data])
        lows = np.array([d[4] for d in data])

        # 전일 대비 등락률
        daily_ret = np.zeros(len(closes))
        daily_ret[1:] = np.diff(closes) / closes[:-1] * 100

        # 장중 수익률 (시가→종가)
        intra_ret = (closes / opens - 1) * 100

        # 고가-저가 변동성
        daily_range = (highs - lows) / lows * 100

        # 5일 누적 수익률
        ret_5d = np.zeros(len(closes))
        for i in range(5, len(closes)):
            ret_5d[i] = (closes[i] / closes[i - 5] - 1) * 100

        # RSI(14)
        rsi = calc_rsi(closes, 14)

        # MA20 괴리율
        ma20_gap = np.zeros(len(closes))
        for i in range(19, len(closes)):
            ma20 = np.mean(closes[i - 19:i + 1])
            ma20_gap[i] = (closes[i] / ma20 - 1) * 100

        # 시가 갭 (전일종가 대비)
        gap = np.zeros(len(opens))
        for i in range(1, len(opens)):
            gap[i] = (opens[i] / closes[i - 1] - 1) * 100

        # 연속 하락 일수
        consec_down = np.zeros(len(daily_ret), dtype=int)
        for i in range(1, len(daily_ret)):
            if daily_ret[i] < 0:
                consec_down[i] = consec_down[i - 1] + 1
            else:
                consec_down[i] = 0

        indicators[code] = {}
        for i, dt in enumerate(dates):
            indicators[code][dt] = {
                f'{prefix}_open': opens[i],
                f'{prefix}_close': closes[i],
                f'{prefix}_high': highs[i],
                f'{prefix}_low': lows[i],
                f'{prefix}_ret': daily_ret[i],
                f'{prefix}_intra': intra_ret[i],
                f'{prefix}_range': daily_range[i],
                f'{prefix}_ret_5d': ret_5d[i],
                f'{prefix}_rsi': rsi[i],
                f'{prefix}_ma20_gap': ma20_gap[i],
                f'{prefix}_gap': gap[i],
                f'{prefix}_consec_down': consec_down[i],
            }

    # 병합
    all_dates = sorted(set(list(indicators.get('KS11', {}).keys())) &
                        set(list(indicators.get('KQ11', {}).keys())))
    result = {}
    for dt in all_dates:
        entry = {}
        for code in ['KS11', 'KQ11']:
            if dt in indicators.get(code, {}):
                entry.update(indicators[code][dt])
        result[dt] = entry

    return result


def calc_inverse_return(index_data_entry, prefix, multiplier=1):
    """인버스 ETF 장중 수익률 (시가→종가 기준)"""
    opn = index_data_entry.get(f'{prefix}_open', 0)
    cls = index_data_entry.get(f'{prefix}_close', 0)
    high = index_data_entry.get(f'{prefix}_high', 0)
    low = index_data_entry.get(f'{prefix}_low', 0)
    if opn <= 0:
        return 0.0, '무효'

    inverse_close = -multiplier * (cls / opn - 1) * 100
    return inverse_close, '장마감'


# ===================================================================
# 예측 신호 함수들 (전일 데이터 기반 → 당일 매매)
# ===================================================================

def signal_decline_momentum(date, index_data, all_index_dates, threshold=-1.0):
    """전일 하락 모멘텀: 전일 등락률이 threshold 이하면 발동"""
    try:
        idx = all_index_dates.index(date)
    except ValueError:
        return False
    if idx < 1:
        return False
    prev = all_index_dates[idx - 1]
    d = index_data.get(prev, {})
    return d.get('kospi_ret', 0) <= threshold or d.get('kosdaq_ret', 0) <= threshold


def signal_two_day_decline(date, index_data, all_index_dates, threshold=-0.5):
    """2일 연속 하락: 전일+전전일 모두 threshold 이하"""
    try:
        idx = all_index_dates.index(date)
    except ValueError:
        return False
    if idx < 2:
        return False
    d1 = index_data.get(all_index_dates[idx - 1], {})
    d2 = index_data.get(all_index_dates[idx - 2], {})
    k1 = d1.get('kospi_ret', 0) <= threshold
    k2 = d2.get('kospi_ret', 0) <= threshold
    return k1 and k2


def signal_5d_decline(date, index_data, all_index_dates, threshold=-3.0):
    """5일 누적 하락: 전일 기준 5일 수익률이 threshold 이하"""
    try:
        idx = all_index_dates.index(date)
    except ValueError:
        return False
    if idx < 1:
        return False
    prev = all_index_dates[idx - 1]
    d = index_data.get(prev, {})
    return d.get('kospi_ret_5d', 0) <= threshold


def signal_volatility_spike(date, index_data, all_index_dates, threshold=2.5):
    """변동성 폭발: 전일 고가-저가 범위가 threshold 이상"""
    try:
        idx = all_index_dates.index(date)
    except ValueError:
        return False
    if idx < 1:
        return False
    prev = all_index_dates[idx - 1]
    d = index_data.get(prev, {})
    return d.get('kospi_range', 0) >= threshold or d.get('kosdaq_range', 0) >= threshold


def signal_nxt_gap(date, index_data, threshold=-0.5):
    """NXT 갭: 당일 시가 갭이 threshold 이하"""
    d = index_data.get(date, {})
    return d.get('kospi_gap', 0) <= threshold or d.get('kosdaq_gap', 0) <= threshold


def signal_consec_down(date, index_data, all_index_dates, n=2):
    """N일 연속 하락 중"""
    try:
        idx = all_index_dates.index(date)
    except ValueError:
        return False
    if idx < 1:
        return False
    prev = all_index_dates[idx - 1]
    d = index_data.get(prev, {})
    return d.get('kospi_consec_down', 0) >= n


def signal_crash_score(date, index_data, all_index_dates):
    """
    복합 하락 점수 (0~5): 여러 신호의 합산

    1점: 전일 하락 > -1%
    1점: 전전일도 하락
    1점: 5일 수익률 < -3%
    1점: 전일 변동성 > 2.5%
    1점: 당일 시가 갭 < -0.5%
    """
    score = 0
    if signal_decline_momentum(date, index_data, all_index_dates, -1.0):
        score += 1
    if signal_two_day_decline(date, index_data, all_index_dates, -0.5):
        score += 1
    if signal_5d_decline(date, index_data, all_index_dates, -3.0):
        score += 1
    if signal_volatility_spike(date, index_data, all_index_dates, 2.5):
        score += 1
    if signal_nxt_gap(date, index_data, -0.5):
        score += 1
    return score


# ===================================================================
# 통계 계산
# ===================================================================

def calc_combined_capital(stock_df, inv_trades, initial_capital=10_000_000, buy_ratio=0.20):
    """개별주 + 인버스 혼합 원금 수익률"""
    daily_pnl = defaultdict(list)
    if stock_df is not None and len(stock_df) > 0:
        for _, row in stock_df.iterrows():
            daily_pnl[row['date']].append(row['pnl'])
    for inv in inv_trades:
        for _ in range(inv.get('positions', 1)):
            daily_pnl[inv['date']].append(inv['pnl'])

    capital = initial_capital
    monthly = {}
    cur_month = None
    month_start = capital

    for date in sorted(daily_pnl.keys()):
        m = date[:6]
        if m != cur_month:
            if cur_month is not None:
                monthly[cur_month] = (month_start, capital)
            cur_month = m
            month_start = capital
        day_cap = capital
        for pnl in daily_pnl[date]:
            capital += day_cap * buy_ratio * (pnl / 100)
    if cur_month is not None:
        monthly[cur_month] = (month_start, capital)

    total_ret = (capital / initial_capital - 1) * 100
    monthly_pcts = {m: (e / s - 1) * 100 if s > 0 else 0 for m, (s, e) in monthly.items()}
    return {'total_return_pct': total_ret, 'monthly_returns': monthly_pcts, 'final_capital': capital}


def calc_stats(stock_df, inv_trades=None):
    """통합 통계"""
    s_cnt = len(stock_df) if stock_df is not None and len(stock_df) > 0 else 0
    all_pnl = list(stock_df['pnl']) if s_cnt > 0 else []
    inv_pnls = []
    if inv_trades:
        for inv in inv_trades:
            for _ in range(inv.get('positions', 1)):
                inv_pnls.append(inv['pnl'])
                all_pnl.append(inv['pnl'])

    total = len(all_pnl)
    if total == 0:
        return {'total': 0, 'stock_trades': 0, 'inv_trades': 0,
                'wins': 0, 'winrate': 0, 'avg_pnl': 0, 'capital_return': 0,
                'inv_avg': 0, 'inv_wins': 0, 'inv_wr': 0}

    wins = sum(1 for p in all_pnl if p > 0)
    cap = calc_combined_capital(stock_df, inv_trades or [])
    inv_wins = sum(1 for p in inv_pnls if p > 0)

    return {
        'total': total,
        'stock_trades': s_cnt,
        'inv_trades': len(inv_pnls),
        'wins': wins,
        'winrate': wins / total * 100,
        'avg_pnl': np.mean(all_pnl),
        'capital_return': cap['total_return_pct'],
        'monthly': cap.get('monthly_returns', {}),
        'inv_avg': np.mean(inv_pnls) if inv_pnls else 0,
        'inv_wins': inv_wins,
        'inv_wr': inv_wins / len(inv_pnls) * 100 if inv_pnls else 0,
    }


# ===================================================================
# 시나리오 헬퍼
# ===================================================================

def make_inverse_trades(trigger_dates, avail_dates, index_data, prefix='kospi',
                        mult=1, positions=1):
    """트리거 날짜에 인버스 거래 생성"""
    trades = []
    for date in trigger_dates:
        if date not in avail_dates:
            continue
        d = index_data.get(date, {})
        pnl, reason = calc_inverse_return(d, prefix, mult)
        trades.append({'date': date, 'pnl': pnl, 'reason': reason, 'positions': positions})
    return trades


def run_scenario(name, trigger_dates, limited_df, trades_df, index_data,
                 avail_dates, max_daily, mode='switch',
                 stock_limit=0, inv_mult=2, inv_pos=5, inv_prefix='kospi'):
    """
    단일 시나리오 실행

    mode:
      'switch': 트리거 날 개별주 완전 스킵 → 인버스만
      'hybrid': 트리거 날 개별주 축소 + 인버스 추가
      'hedge': 개별주 유지 + 인버스 추가
    """
    if mode == 'switch':
        stock_df = limited_df[~limited_df['date'].isin(trigger_dates)].reset_index(drop=True)
    elif mode == 'hybrid':
        overrides = {d: stock_limit for d in trigger_dates}
        stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    else:  # hedge
        stock_df = limited_df

    inv_trades = make_inverse_trades(
        trigger_dates, avail_dates, index_data,
        prefix=inv_prefix, mult=inv_mult, positions=inv_pos,
    )
    s = calc_stats(stock_df, inv_trades)
    return (name, s, len(trigger_dates))


# ===================================================================
# 멀티버스 엔진
# ===================================================================

def run_multiverse(trades_df, index_data, max_daily=5):
    """하락 예측 기반 인버스 ETF 멀티버스 시뮬레이션"""

    limited_df = apply_daily_limit(trades_df, max_daily)
    all_dates = sorted(limited_df['date'].unique())
    all_index_dates = sorted(index_data.keys())
    avail_dates = set(all_dates) & set(all_index_dates)

    # 일별 매매결과 (T-1 참조용)
    daily_results = {}
    for date in all_dates:
        day = limited_df[limited_df['date'] == date]
        daily_results[date] = {
            'trades': len(day),
            'wins': int((day['result'] == 'WIN').sum()),
            'winrate': (day['result'] == 'WIN').sum() / len(day) * 100 if len(day) > 0 else 0,
            'avg_pnl': day['pnl'].mean(),
        }

    print('\n')
    print('=' * 130)
    print('  하락 예측 기반 인버스 ETF 멀티버스 시뮬레이션')
    print('=' * 130)
    print(f'  거래일: {len(all_dates)}일, 지수데이터: {len(avail_dates)}일')

    base = calc_stats(limited_df)
    print(f'\n  기준선 (개별주만, max={max_daily}): {base["total"]}건, '
          f'승률 {base["winrate"]:.1f}%, 원금수익률 {base["capital_return"]:+.2f}%')

    all_scenarios = []

    # ================================================================
    # 카테고리 A: 하락 모멘텀 (전일 큰 하락 → 다음날 인버스)
    # ================================================================
    cat = []
    for th in [-1.0, -1.5, -2.0, -3.0]:
        triggers = {d for d in all_dates
                    if signal_decline_momentum(d, index_data, all_index_dates, th)}
        for mult in [1, 2]:
            # 전환
            cat.append(run_scenario(
                f'A. 전일하락{th}%→인버스{mult}x×5(전환)',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='switch', inv_mult=mult, inv_pos=5))
            # 혼합
            cat.append(run_scenario(
                f'A. 전일하락{th}%→개별2+인버스{mult}x×3',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='hybrid', stock_limit=2, inv_mult=mult, inv_pos=3))

    _print_category('카테고리 A: 전일 하락 모멘텀', cat, base)
    all_scenarios.extend(cat)

    # ================================================================
    # 카테고리 B: 2일 연속 하락
    # ================================================================
    cat = []
    for th in [-0.3, -0.5, -1.0]:
        triggers = {d for d in all_dates
                    if signal_two_day_decline(d, index_data, all_index_dates, th)}
        for mult in [1, 2]:
            cat.append(run_scenario(
                f'B. 2일연속하락{th}%→인버스{mult}x×5(전환)',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='switch', inv_mult=mult, inv_pos=5))
            cat.append(run_scenario(
                f'B. 2일연속하락{th}%→개별2+인버스{mult}x×3',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='hybrid', stock_limit=2, inv_mult=mult, inv_pos=3))

    _print_category('카테고리 B: 2일 연속 하락', cat, base)
    all_scenarios.extend(cat)

    # ================================================================
    # 카테고리 C: 5일 누적 하락
    # ================================================================
    cat = []
    for th in [-2.0, -3.0, -5.0, -7.0]:
        triggers = {d for d in all_dates
                    if signal_5d_decline(d, index_data, all_index_dates, th)}
        for mult in [1, 2]:
            cat.append(run_scenario(
                f'C. 5일하락{th}%→인버스{mult}x×5(전환)',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='switch', inv_mult=mult, inv_pos=5))
            cat.append(run_scenario(
                f'C. 5일하락{th}%→개별2+인버스{mult}x×3',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='hybrid', stock_limit=2, inv_mult=mult, inv_pos=3))

    _print_category('카테고리 C: 5일 누적 하락', cat, base)
    all_scenarios.extend(cat)

    # ================================================================
    # 카테고리 D: 변동성 폭발
    # ================================================================
    cat = []
    for th in [2.0, 2.5, 3.0]:
        triggers = {d for d in all_dates
                    if signal_volatility_spike(d, index_data, all_index_dates, th)}
        for mult in [1, 2]:
            cat.append(run_scenario(
                f'D. 변동성>{th}%→인버스{mult}x×5(전환)',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='switch', inv_mult=mult, inv_pos=5))
            cat.append(run_scenario(
                f'D. 변동성>{th}%→개별3+인버스{mult}x×2',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='hybrid', stock_limit=3, inv_mult=mult, inv_pos=2))

    _print_category('카테고리 D: 전일 변동성 폭발', cat, base)
    all_scenarios.extend(cat)

    # ================================================================
    # 카테고리 E: NXT 갭 + 하락 모멘텀 복합
    # ================================================================
    cat = []

    # E1: NXT 갭 + 전일 하락
    for gap_th, ret_th in [(-0.3, -0.5), (-0.5, -1.0), (-0.5, -0.5), (-1.0, -1.0)]:
        triggers = {d for d in all_dates
                    if signal_nxt_gap(d, index_data, gap_th) and
                    signal_decline_momentum(d, index_data, all_index_dates, ret_th)}
        for mult in [1, 2]:
            cat.append(run_scenario(
                f'E1. NXT{gap_th}%+전일{ret_th}%→인버스{mult}x×5(전환)',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='switch', inv_mult=mult, inv_pos=5))
            cat.append(run_scenario(
                f'E1. NXT{gap_th}%+전일{ret_th}%→개별2+인버스{mult}x×3',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='hybrid', stock_limit=2, inv_mult=mult, inv_pos=3))

    # E2: NXT 갭 + 5일 하락
    for gap_th, d5_th in [(-0.3, -3.0), (-0.5, -3.0), (-0.5, -5.0)]:
        triggers = {d for d in all_dates
                    if signal_nxt_gap(d, index_data, gap_th) and
                    signal_5d_decline(d, index_data, all_index_dates, d5_th)}
        for mult in [2]:
            cat.append(run_scenario(
                f'E2. NXT{gap_th}%+5일{d5_th}%→인버스{mult}x×5(전환)',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='switch', inv_mult=mult, inv_pos=5))

    # E3: 전일 하락 + 변동성
    for ret_th, vol_th in [(-1.0, 2.0), (-1.0, 2.5), (-0.5, 2.5)]:
        triggers = {d for d in all_dates
                    if signal_decline_momentum(d, index_data, all_index_dates, ret_th) and
                    signal_volatility_spike(d, index_data, all_index_dates, vol_th)}
        for mult in [2]:
            cat.append(run_scenario(
                f'E3. 전일{ret_th}%+변동성>{vol_th}%→인버스{mult}x×5(전환)',
                triggers, limited_df, trades_df, index_data, avail_dates,
                max_daily, mode='switch', inv_mult=mult, inv_pos=5))

    _print_category('카테고리 E: 복합 신호 (NXT + 모멘텀 + 변동성)', cat, base)
    all_scenarios.extend(cat)

    # ================================================================
    # 카테고리 F: 복합 점수 기반 단계적 대응
    # ================================================================
    cat = []

    for min_score in [2, 3, 4]:
        triggers_switch = set()
        triggers_hybrid = set()
        for d in all_dates:
            score = signal_crash_score(d, index_data, all_index_dates)
            if score >= min_score + 1:
                triggers_switch.add(d)
            elif score >= min_score:
                triggers_hybrid.add(d)

        for mult in [1, 2]:
            # 단계적: 높은 점수→전환, 낮은 점수→혼합
            overrides = {}
            for d in triggers_switch:
                overrides[d] = 0
            for d in triggers_hybrid:
                overrides[d] = 2
            stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)

            inv_trades = []
            for d in (triggers_switch | triggers_hybrid) & avail_dates:
                dd = index_data.get(d, {})
                pnl, reason = calc_inverse_return(dd, 'kospi', mult)
                n_pos = 5 if d in triggers_switch else 2
                inv_trades.append({'date': d, 'pnl': pnl, 'reason': reason, 'positions': n_pos})

            s = calc_stats(stock_df, inv_trades)
            n_sw = len(triggers_switch)
            n_hy = len(triggers_hybrid)
            cat.append((
                f'F. 점수>={min_score}(전환{n_sw}일+혼합{n_hy}일)인버스{mult}x',
                s, n_sw + n_hy))

    # T-1 매매결과도 점수에 추가하는 확장 버전
    for min_score in [2, 3]:
        triggers_switch = set()
        triggers_hybrid = set()
        for d in all_dates:
            score = signal_crash_score(d, index_data, all_index_dates)
            # T-1 매매결과 추가 점수
            try:
                d_idx = all_dates.index(d)
                if d_idx > 0:
                    prev_r = daily_results.get(all_dates[d_idx - 1])
                    if prev_r and prev_r['trades'] >= 2 and prev_r['winrate'] == 0:
                        score += 1
                    if prev_r and prev_r['avg_pnl'] < -2.0:
                        score += 1
            except ValueError:
                pass

            if score >= min_score + 2:
                triggers_switch.add(d)
            elif score >= min_score:
                triggers_hybrid.add(d)

        for mult in [2]:
            overrides = {}
            for d in triggers_switch:
                overrides[d] = 0
            for d in triggers_hybrid:
                overrides[d] = 2

            stock_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
            inv_trades = []
            for d in (triggers_switch | triggers_hybrid) & avail_dates:
                dd = index_data.get(d, {})
                pnl, reason = calc_inverse_return(dd, 'kospi', mult)
                n_pos = 5 if d in triggers_switch else 2
                inv_trades.append({'date': d, 'pnl': pnl, 'reason': reason, 'positions': n_pos})

            s = calc_stats(stock_df, inv_trades)
            n_sw = len(triggers_switch)
            n_hy = len(triggers_hybrid)
            cat.append((
                f'F+. 확장점수>={min_score}(전환{n_sw}+혼합{n_hy})인버스{mult}x',
                s, n_sw + n_hy))

    _print_category('카테고리 F: 복합 점수 (단계적 대응)', cat, base)
    all_scenarios.extend(cat)

    # ================================================================
    # 전체 비교 요약
    # ================================================================
    print('\n')
    print('=' * 130)
    print('  전체 비교 요약 (원금수익률 기준 TOP 30)')
    print('=' * 130)
    print(f'  {"시나리오":<70} {"총거래":>5} {"승률":>6} {"원금수익률":>10} '
          f'{"개선":>9} {"적용일":>5} {"인버스평균":>8} {"인버스승률":>6}')
    print('  ' + '-' * 125)
    print(f'  {"[기준선] 개별주만 (max=" + str(max_daily) + ")":<70} '
          f'{base["total"]:>4}건 {base["winrate"]:>5.1f}% '
          f'{base["capital_return"]:>+9.2f}%')

    sorted_all = sorted(all_scenarios, key=lambda x: x[1]['capital_return'], reverse=True)
    for name, s, cnt in sorted_all[:30]:
        imp = s['capital_return'] - base['capital_return']
        marker = ' ★' if imp > 0 else ''
        inv_avg = f'{s["inv_avg"]:+.2f}%' if s['inv_trades'] > 0 else ''
        inv_wr = f'{s["inv_wr"]:.0f}%' if s['inv_trades'] > 0 else ''
        print(f'  {name:<70} {s["total"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["capital_return"]:>+9.2f}% {imp:>+8.2f}%p {cnt:>4}일 '
              f'{inv_avg:>7} {inv_wr:>5}{marker}')

    # ================================================================
    # 신호 정확도 분석
    # ================================================================
    print('\n')
    print('=' * 130)
    print('  신호별 하락 예측 정확도 (당일 인버스 1x 수익률 기준)')
    print('=' * 130)
    print(f'  {"신호":<50} {"발동":>5} {"정확":>5} {"정확도":>6} {"인버스1x평균":>10} {"인버스2x평균":>10}')
    print('  ' + '-' * 100)

    signal_tests = [
        ('전일 하락 < -1%', lambda d: signal_decline_momentum(d, index_data, all_index_dates, -1.0)),
        ('전일 하락 < -2%', lambda d: signal_decline_momentum(d, index_data, all_index_dates, -2.0)),
        ('전일 하락 < -3%', lambda d: signal_decline_momentum(d, index_data, all_index_dates, -3.0)),
        ('2일 연속 하락 < -0.5%', lambda d: signal_two_day_decline(d, index_data, all_index_dates, -0.5)),
        ('2일 연속 하락 < -1.0%', lambda d: signal_two_day_decline(d, index_data, all_index_dates, -1.0)),
        ('5일 하락 < -3%', lambda d: signal_5d_decline(d, index_data, all_index_dates, -3.0)),
        ('5일 하락 < -5%', lambda d: signal_5d_decline(d, index_data, all_index_dates, -5.0)),
        ('변동성 > 2.5%', lambda d: signal_volatility_spike(d, index_data, all_index_dates, 2.5)),
        ('변동성 > 3.0%', lambda d: signal_volatility_spike(d, index_data, all_index_dates, 3.0)),
        ('NXT 갭 < -0.5%', lambda d: signal_nxt_gap(d, index_data, -0.5)),
        ('NXT 갭 < -1.0%', lambda d: signal_nxt_gap(d, index_data, -1.0)),
        ('N일 연속하락 >= 2일', lambda d: signal_consec_down(d, index_data, all_index_dates, 2)),
        ('N일 연속하락 >= 3일', lambda d: signal_consec_down(d, index_data, all_index_dates, 3)),
        ('복합점수 >= 2', lambda d: signal_crash_score(d, index_data, all_index_dates) >= 2),
        ('복합점수 >= 3', lambda d: signal_crash_score(d, index_data, all_index_dates) >= 3),
        ('복합점수 >= 4', lambda d: signal_crash_score(d, index_data, all_index_dates) >= 4),
    ]

    for label, fn in signal_tests:
        triggered = [d for d in all_dates if fn(d) and d in avail_dates]
        if not triggered:
            print(f'  {label:<50} {"0":>4}일')
            continue
        inv1 = []
        for d in triggered:
            pnl, _ = calc_inverse_return(index_data.get(d, {}), 'kospi', 1)
            inv1.append(pnl)
        correct = sum(1 for p in inv1 if p > 0)
        acc = correct / len(triggered) * 100
        avg1 = np.mean(inv1)
        avg2 = avg1 * 2
        print(f'  {label:<50} {len(triggered):>4}일 {correct:>4}일 {acc:>5.1f}% '
              f'{avg1:>+9.3f}% {avg2:>+9.3f}%')

    # ================================================================
    # 월별 분해 (상위 3개)
    # ================================================================
    print('\n')
    print('=' * 130)
    print('  월별 성과 분해 (상위 3개 시나리오 vs 기준선)')
    print('=' * 130)

    base_monthly = calc_capital_returns(limited_df).get('monthly_returns', {})
    months = sorted(base_monthly.keys())

    top3 = sorted_all[:3]
    header = f'  {"월":>8} {"기준선":>10}'
    for name, _, _ in top3:
        short = name[:20]
        header += f' {short:>22}'
    print(header)
    print('  ' + '-' * (12 + 24 * (len(top3) + 1)))

    for m in months:
        row = f'  {m[:4]}-{m[4:]:>4} {base_monthly.get(m, 0):>+9.2f}%'
        for _, s, _ in top3:
            mv = s.get('monthly', {}).get(m, 0)
            row += f' {mv:>+21.2f}%'
        print(row)


def _print_category(title, scenarios, base_stats):
    """카테고리별 테이블 출력"""
    print('\n')
    print('#' * 130)
    print(f'#  {title}')
    print('#' * 130)
    print(f'  {"시나리오":<70} {"총거래":>5} {"승률":>6} {"원금수익률":>10} '
          f'{"개선":>9} {"적용일":>5} {"인버스평균":>8}')
    print('  ' + '-' * 125)
    print(f'  {"[기준선]":<70} {base_stats["total"]:>4}건 '
          f'{base_stats["winrate"]:>5.1f}% {base_stats["capital_return"]:>+9.2f}%')

    for name, s, cnt in scenarios:
        imp = s['capital_return'] - base_stats['capital_return']
        inv_avg = f'{s["inv_avg"]:+.2f}%' if s['inv_trades'] > 0 else ''
        marker = ' ★' if imp > 0 else ''
        print(f'  {name:<70} {s["total"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["capital_return"]:>+9.2f}% {imp:>+8.2f}%p {cnt:>4}일 '
              f'{inv_avg:>7}{marker}')


def main():
    parser = argparse.ArgumentParser(description='인버스 ETF 하락 예측 멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260304', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    args = parser.parse_args()

    print('=' * 130)
    print('인버스 ETF 하락 예측 멀티버스 시뮬레이션')
    print('  하락 모멘텀 + 변동성 + NXT 갭 복합 신호')
    print('=' * 130)

    print('\n[1/3] 지수 데이터 + 기술 지표 계산...')
    index_data = load_index_with_indicators()
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

    print(f'\n[3/3] 하락 예측 멀티버스 시뮬레이션 ({len(trades_df)}건 기반)...')
    run_multiverse(trades_df, index_data, args.max_daily)

    print('\nDone!')


if __name__ == '__main__':
    main()
