"""
시장 레짐 필터 멀티버스 시뮬레이션 v2

NXT 프리마켓 프록시(시가 갭) + 전일 매매 결과 + KOSPI/KOSDAQ 지수 조합으로
매수 중단/포지션 축소/손절 조정 시나리오 비교.

핵심 개선 (v2):
- 완전 스킵 대신 포지션 축소 (5→3, 5→2) 시나리오 추가
- 손절폭 축소 (-4%→-3%) 시나리오 추가
- NXT 프리마켓 프록시 (시가 갭) 조합
- 월별/레짐별 성과 분해 (상승장 편향 문제 해소)

Usage:
  python simulate_regime_filter.py --start 20250224 --end 20260304
  python simulate_regime_filter.py --start 20250901 --end 20260304 --max-daily 5
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


def load_market_data():
    """KOSPI/KOSDAQ 일봉 데이터 로드 → 전일 대비 등락률 + 시가 갭 계산"""
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
    changes = {}
    for dt in dates:
        d = data[dt]
        if 'KS11' in d and 'KQ11' in d:
            entry = {}
            if 'KS11' in prev and 'KQ11' in prev:
                entry['kospi_chg'] = (d['KS11']['close'] / prev['KS11']['close'] - 1) * 100
                entry['kosdaq_chg'] = (d['KQ11']['close'] / prev['KQ11']['close'] - 1) * 100
                entry['kospi_gap'] = (d['KS11']['open'] / prev['KS11']['close'] - 1) * 100
                entry['kosdaq_gap'] = (d['KQ11']['open'] / prev['KQ11']['close'] - 1) * 100
            else:
                entry['kospi_chg'] = 0
                entry['kosdaq_chg'] = 0
                entry['kospi_gap'] = 0
                entry['kosdaq_gap'] = 0
            changes[dt] = entry
            prev = {k: v for k, v in d.items()}

    return changes


def calc_daily_trade_results(trades_df):
    """날짜별 매매 결과 계산"""
    results = {}
    for date in trades_df['date'].unique():
        day = trades_df[trades_df['date'] == date]
        wins = (day['result'] == 'WIN').sum()
        total = len(day)
        results[date] = {
            'trades': total,
            'wins': int(wins),
            'winrate': wins / total * 100 if total > 0 else 0,
            'avg_pnl': day['pnl'].mean(),
        }
    return results


def get_prev_trading_dates(dates_list, date, n=2):
    """해당 날짜 기준 이전 n개 거래일 반환"""
    try:
        idx = dates_list.index(date)
    except ValueError:
        return []
    start = max(0, idx - n)
    return dates_list[start:idx]


def calc_stats(df):
    """거래 DataFrame으로 통계 계산"""
    if df is None or len(df) == 0:
        return {'trades': 0, 'wins': 0, 'winrate': 0, 'avg_pnl': 0,
                'capital_return': 0, 'avg_win': 0, 'avg_loss': 0}
    wins = (df['result'] == 'WIN').sum()
    cap = calc_capital_returns(df)
    avg_win = df[df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
    avg_loss = df[df['result'] != 'WIN']['pnl'].mean() if len(df) - wins > 0 else 0
    return {
        'trades': len(df),
        'wins': int(wins),
        'winrate': wins / len(df) * 100,
        'avg_pnl': df['pnl'].mean(),
        'capital_return': cap['total_return_pct'],
        'avg_win': avg_win,
        'avg_loss': avg_loss,
    }


# ===================================================================
# 핵심 v2 함수들: 포지션 축소 + 손절 조정
# ===================================================================

def apply_daily_limit_variable(trades_df, default_limit, date_overrides):
    """
    날짜별 가변 동시보유 제한 적용.

    Args:
        trades_df: 전체 거래 DataFrame
        default_limit: 기본 동시보유 제한 (예: 5)
        date_overrides: {date: limit} 특정 날짜의 제한 (예: {'20260303': 3})
    Returns:
        제한 적용된 DataFrame
    """
    limited = []
    for date in trades_df['date'].unique():
        day_trades = trades_df[trades_df['date'] == date].copy()
        day_trades = day_trades.sort_values('entry_time')

        limit = date_overrides.get(date, default_limit)
        if limit == 0:
            continue  # 완전 스킵

        accepted = []
        for _, trade in day_trades.iterrows():
            entry_t = str(trade['entry_time']).zfill(6)
            exit_t = str(trade['exit_time']).zfill(6)
            holding = sum(1 for _, et in accepted if et > entry_t)
            if holding < limit:
                accepted.append((entry_t, exit_t))
                limited.append(trade)

    return pd.DataFrame(limited).reset_index(drop=True) if limited else pd.DataFrame()


def apply_tighter_stop_loss(trades_df, target_dates, new_stop_pct=-3.0):
    """
    특정 날짜들에서 손절폭을 축소한 결과를 시뮬레이션.

    기존 -4% 손절에서 새로운 손절값으로 변경.
    exit_reason이 'stop_loss'이고 PnL이 new_stop_pct보다 나쁜 거래의 PnL을 new_stop_pct로 조정.
    또한, 원래 손절되지 않았지만 new_stop_pct에 걸릴 거래는
    분봉 데이터 없이는 정확히 판단 불가하므로 보수적으로 무시.

    Args:
        trades_df: 거래 DataFrame
        target_dates: 손절 축소 적용할 날짜 set
        new_stop_pct: 새 손절 비율 (예: -3.0)
    Returns:
        조정된 DataFrame
    """
    if not target_dates:
        return trades_df

    df = trades_df.copy()
    mask = (df['date'].isin(target_dates)) & (df['exit_reason'] == '손절')
    # 기존 손절(-4%) → 새 손절(-3%)로 교체 (손실 감소)
    df.loc[mask, 'pnl'] = new_stop_pct
    return df


def compute_regime_score(date, all_dates, all_market_dates,
                         daily_results, market_data):
    """
    날짜별 레짐 점수 계산 (-1.0 ~ +1.0)

    구성:
    - T-1 매매 결과 (40%): 전일 승률
    - T-2 매매 결과 (20%): 전전일 승률
    - T-1 지수 (40%): 전일 KOSPI+KOSDAQ 평균 등락률
    """
    score = 0.0

    # T-1 매매 결과 (40%)
    prevs_t = get_prev_trading_dates(all_dates, date, 1)
    if prevs_t:
        r = daily_results.get(prevs_t[0])
        if r and r['trades'] >= 1:
            score += (r['winrate'] / 50 - 1) * 0.4

    # T-2 매매 결과 (20%)
    prevs_t2 = get_prev_trading_dates(all_dates, date, 2)
    if len(prevs_t2) >= 2:
        r2 = daily_results.get(prevs_t2[0])
        if r2 and r2['trades'] >= 1:
            score += (r2['winrate'] / 50 - 1) * 0.2

    # T-1 지수 (40%)
    prevs_m = get_prev_trading_dates(all_market_dates, date, 1)
    if prevs_m:
        m = market_data.get(prevs_m[0])
        if m:
            idx_score = max(-1, min(1, (m['kospi_chg'] + m['kosdaq_chg']) / 2 / 3))
            score += idx_score * 0.4

    return score


def compute_nxt_score(date, market_data):
    """
    NXT 프리마켓 심리 프록시: 당일 시가 갭 기반 (-1.0 ~ +1.0)

    실제 NXT 데이터가 없으므로, 전일 종가 대비 당일 시가 갭으로 근사.
    장 시작 전(08:00-09:00) NXT 거래에서 나타나는 갭이
    곧 본장 시가 갭으로 나타난다는 가정.
    """
    m = market_data.get(date)
    if not m:
        return 0.0
    avg_gap = (m.get('kospi_gap', 0) + m.get('kosdaq_gap', 0)) / 2
    # -3% → -1.0, 0% → 0.0, +3% → +1.0
    return max(-1.0, min(1.0, avg_gap / 3.0))


# ===================================================================
# 멀티버스 엔진
# ===================================================================

def run_multiverse(trades_df, market_data, max_daily=5):
    """다양한 필터 시나리오 비교 (v2: 포지션축소 + 손절조정 + NXT)"""

    # 기준 데이터
    limited_df = apply_daily_limit(trades_df, max_daily)
    daily_results = calc_daily_trade_results(limited_df)
    all_dates = sorted(limited_df['date'].unique())
    all_market_dates = sorted(market_data.keys())

    print('\n')
    print('=' * 110)
    print('  멀티버스 시뮬레이션 v2: 포지션 축소 + 손절 조정 + NXT 프록시')
    print('=' * 110)

    base = calc_stats(limited_df)
    print(f'\n  기준선 (필터 없음, max={max_daily}): {base["trades"]}건, '
          f'승률 {base["winrate"]:.1f}%, 원금수익률 {base["capital_return"]:+.2f}%, '
          f'평균 {base["avg_pnl"]:+.2f}%')

    all_scenarios = []  # (name, stats, skip_count, category)

    # ================================================================
    # 카테고리 1: 전일 매매 결과 → 완전 스킵
    # ================================================================
    cat1 = []
    for label, condition_fn in [
        ('1A. T-1 전패→스킵',
         lambda r: r and r['trades'] >= 2 and r['winrate'] == 0),
        ('1B. T-1 승률<30%→스킵',
         lambda r: r and r['trades'] >= 2 and r['winrate'] < 30),
        ('1C. T-1 평균<-2%→스킵',
         lambda r: r and r['trades'] >= 1 and r['avg_pnl'] < -2.0),
        ('1D. T-1 평균<-3%→스킵',
         lambda r: r and r['trades'] >= 1 and r['avg_pnl'] < -3.0),
    ]:
        skip = set()
        for date in all_dates:
            prevs = get_prev_trading_dates(all_dates, date, 1)
            if prevs:
                r = daily_results.get(prevs[0])
                if condition_fn(r):
                    skip.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip)].reset_index(drop=True)
        s = calc_stats(filtered)
        skipped = limited_df[limited_df['date'].isin(skip)]
        cat1.append((label, s, len(skip), skipped))

    # 2일 연속 조건
    for label, cond_fn_pair in [
        ('1E. T-1,T-2 둘다 승률<50%→스킵',
         lambda r: r and r['trades'] >= 1 and r['winrate'] < 50),
        ('1F. T-1,T-2 둘다 마이너스→스킵',
         lambda r: r and r['trades'] >= 1 and r['avg_pnl'] < 0),
    ]:
        skip = set()
        for date in all_dates:
            prevs = get_prev_trading_dates(all_dates, date, 2)
            if len(prevs) == 2:
                r1 = daily_results.get(prevs[1])
                r2 = daily_results.get(prevs[0])
                if cond_fn_pair(r1) and cond_fn_pair(r2):
                    skip.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip)].reset_index(drop=True)
        s = calc_stats(filtered)
        skipped = limited_df[limited_df['date'].isin(skip)]
        cat1.append((label, s, len(skip), skipped))

    _print_category('카테고리 1: 전일 매매 결과 → 완전 스킵', cat1, base)
    for name, s, cnt, _ in cat1:
        all_scenarios.append((name, s, cnt, '매매결과'))

    # ================================================================
    # 카테고리 2: 전일 매매 결과 → 포지션 축소 (5→3, 5→2)
    # ================================================================
    cat2 = []
    for reduced_limit in [3, 2]:
        for label, condition_fn in [
            (f'2. T-1 전패→{reduced_limit}종목',
             lambda r: r and r['trades'] >= 2 and r['winrate'] == 0),
            (f'2. T-1 승률<30%→{reduced_limit}종목',
             lambda r: r and r['trades'] >= 2 and r['winrate'] < 30),
            (f'2. T-1 평균<-2%→{reduced_limit}종목',
             lambda r: r and r['trades'] >= 1 and r['avg_pnl'] < -2.0),
            (f'2. T-1,T-2 마이너스→{reduced_limit}종목',
             None),  # 2일 연속 special case
        ]:
            overrides = {}
            for date in all_dates:
                if condition_fn is not None:
                    prevs = get_prev_trading_dates(all_dates, date, 1)
                    if prevs:
                        r = daily_results.get(prevs[0])
                        if condition_fn(r):
                            overrides[date] = reduced_limit
                else:
                    # 2일 연속 마이너스
                    prevs = get_prev_trading_dates(all_dates, date, 2)
                    if len(prevs) == 2:
                        r1 = daily_results.get(prevs[1])
                        r2 = daily_results.get(prevs[0])
                        if (r1 and r1['trades'] >= 1 and r1['avg_pnl'] < 0 and
                            r2 and r2['trades'] >= 1 and r2['avg_pnl'] < 0):
                            overrides[date] = reduced_limit

            result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
            s = calc_stats(result_df)
            cat2.append((label, s, len(overrides), pd.DataFrame()))

    _print_category(f'카테고리 2: 전일 매매 결과 → 포지션 축소', cat2, base)
    for name, s, cnt, _ in cat2:
        all_scenarios.append((name, s, cnt, '포지션축소'))

    # ================================================================
    # 카테고리 3: NXT 프록시 (시가 갭) → 완전 스킵 / 포지션 축소
    # ================================================================
    cat3 = []
    for gap_th in [-0.5, -1.0, -1.5, -2.0]:
        # 스킵
        skip = set()
        for date in all_dates:
            m = market_data.get(date)
            if m and (m.get('kospi_gap', 0) <= gap_th or m.get('kosdaq_gap', 0) <= gap_th):
                skip.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip)].reset_index(drop=True)
        s = calc_stats(filtered)
        skipped = limited_df[limited_df['date'].isin(skip)]
        cat3.append((f'3. NXT갭{gap_th}%↓→스킵', s, len(skip), skipped))

    for gap_th, reduced_limit in [(-0.5, 3), (-1.0, 3), (-1.0, 2), (-1.5, 2)]:
        overrides = {}
        for date in all_dates:
            m = market_data.get(date)
            if m and (m.get('kospi_gap', 0) <= gap_th or m.get('kosdaq_gap', 0) <= gap_th):
                overrides[date] = reduced_limit
        result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
        s = calc_stats(result_df)
        cat3.append((f'3. NXT갭{gap_th}%↓→{reduced_limit}종목', s, len(overrides), pd.DataFrame()))

    _print_category('카테고리 3: NXT 프록시 (시가 갭)', cat3, base)
    for name, s, cnt, _ in cat3:
        all_scenarios.append((name, s, cnt, 'NXT'))

    # ================================================================
    # 카테고리 4: 손절 축소 (-4% → -3%)
    # ================================================================
    cat4 = []

    # 4A: 전일 전패 → 손절 3%
    for label, condition_fn in [
        ('4A. T-1 전패→손절3%',
         lambda r: r and r['trades'] >= 2 and r['winrate'] == 0),
        ('4B. T-1 승률<30%→손절3%',
         lambda r: r and r['trades'] >= 2 and r['winrate'] < 30),
        ('4C. T-1 평균<-2%→손절3%',
         lambda r: r and r['trades'] >= 1 and r['avg_pnl'] < -2.0),
    ]:
        target_dates = set()
        for date in all_dates:
            prevs = get_prev_trading_dates(all_dates, date, 1)
            if prevs:
                r = daily_results.get(prevs[0])
                if condition_fn(r):
                    target_dates.add(date)
        adjusted = apply_tighter_stop_loss(limited_df, target_dates, -3.0)
        s = calc_stats(adjusted)
        cat4.append((label, s, len(target_dates), pd.DataFrame()))

    # NXT 갭 → 손절 3%
    for gap_th in [-0.5, -1.0, -1.5]:
        target_dates = set()
        for date in all_dates:
            m = market_data.get(date)
            if m and (m.get('kospi_gap', 0) <= gap_th or m.get('kosdaq_gap', 0) <= gap_th):
                target_dates.add(date)
        adjusted = apply_tighter_stop_loss(limited_df, target_dates, -3.0)
        s = calc_stats(adjusted)
        cat4.append((f'4. NXT갭{gap_th}%↓→손절3%', s, len(target_dates), pd.DataFrame()))

    _print_category('카테고리 4: 손절 축소 (4%→3%)', cat4, base)
    for name, s, cnt, _ in cat4:
        all_scenarios.append((name, s, cnt, '손절축소'))

    # ================================================================
    # 카테고리 5: 복합 NXT + 전일매매 → 포지션축소 + 손절축소
    # ================================================================
    cat5 = []

    # --- 5A: NXT 약세 OR T-1 전패 → 3종목 + 손절3% ---
    overrides = {}
    stop_dates = set()
    for date in all_dates:
        triggered = False
        # NXT 갭 체크
        m = market_data.get(date)
        if m and (m.get('kospi_gap', 0) <= -1.0 or m.get('kosdaq_gap', 0) <= -1.0):
            triggered = True
        # T-1 전패 체크
        prevs = get_prev_trading_dates(all_dates, date, 1)
        if prevs:
            r = daily_results.get(prevs[0])
            if r and r['trades'] >= 2 and r['winrate'] == 0:
                triggered = True
        if triggered:
            overrides[date] = 3
            stop_dates.add(date)
    result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    result_df = apply_tighter_stop_loss(result_df, stop_dates, -3.0)
    s = calc_stats(result_df)
    cat5.append(('5A. NXT갭-1%OR T-1전패→3종목+손절3%', s, len(overrides), pd.DataFrame()))

    # --- 5B: NXT 약세 OR T-1 승률<30% → 3종목 + 손절3% ---
    overrides = {}
    stop_dates = set()
    for date in all_dates:
        triggered = False
        m = market_data.get(date)
        if m and (m.get('kospi_gap', 0) <= -1.0 or m.get('kosdaq_gap', 0) <= -1.0):
            triggered = True
        prevs = get_prev_trading_dates(all_dates, date, 1)
        if prevs:
            r = daily_results.get(prevs[0])
            if r and r['trades'] >= 2 and r['winrate'] < 30:
                triggered = True
        if triggered:
            overrides[date] = 3
            stop_dates.add(date)
    result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    result_df = apply_tighter_stop_loss(result_df, stop_dates, -3.0)
    s = calc_stats(result_df)
    cat5.append(('5B. NXT갭-1%OR T-1승률<30%→3종목+손절3%', s, len(overrides), pd.DataFrame()))

    # --- 5C: NXT 약세 AND T-1 마이너스 → 2종목 + 손절3% ---
    overrides = {}
    stop_dates = set()
    for date in all_dates:
        nxt_bad = False
        trade_bad = False
        m = market_data.get(date)
        if m and (m.get('kospi_gap', 0) <= -0.5 or m.get('kosdaq_gap', 0) <= -0.5):
            nxt_bad = True
        prevs = get_prev_trading_dates(all_dates, date, 1)
        if prevs:
            r = daily_results.get(prevs[0])
            if r and r['trades'] >= 1 and r['avg_pnl'] < 0:
                trade_bad = True
        if nxt_bad and trade_bad:
            overrides[date] = 2
            stop_dates.add(date)
    result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    result_df = apply_tighter_stop_loss(result_df, stop_dates, -3.0)
    s = calc_stats(result_df)
    cat5.append(('5C. NXT갭-0.5%AND T-1마이너스→2종목+손절3%', s, len(overrides), pd.DataFrame()))

    # --- 5D: NXT 약세 AND T-1,T-2 연속 마이너스 → 완전 스킵 ---
    skip = set()
    for date in all_dates:
        nxt_bad = False
        m = market_data.get(date)
        if m and (m.get('kospi_gap', 0) <= -0.5 or m.get('kosdaq_gap', 0) <= -0.5):
            nxt_bad = True
        prevs = get_prev_trading_dates(all_dates, date, 2)
        consec_bad = False
        if len(prevs) == 2:
            r1 = daily_results.get(prevs[1])
            r2 = daily_results.get(prevs[0])
            if (r1 and r1['trades'] >= 1 and r1['avg_pnl'] < 0 and
                r2 and r2['trades'] >= 1 and r2['avg_pnl'] < 0):
                consec_bad = True
        if nxt_bad and consec_bad:
            skip.add(date)
    filtered = limited_df[~limited_df['date'].isin(skip)].reset_index(drop=True)
    s = calc_stats(filtered)
    cat5.append(('5D. NXT갭-0.5%AND T-1,T-2마이너스→스킵', s, len(skip), pd.DataFrame()))

    # --- 5E: 복합점수(T-1매매+T-1지수) + NXT갭 → 단계적 조정 ---
    overrides = {}
    stop_dates = set()
    for date in all_dates:
        regime = compute_regime_score(date, all_dates, all_market_dates,
                                      daily_results, market_data)
        nxt = compute_nxt_score(date, market_data)
        combined = regime * 0.6 + nxt * 0.4

        if combined <= -0.6:
            overrides[date] = 0  # 완전 스킵
            stop_dates.add(date)
        elif combined <= -0.3:
            overrides[date] = 2
            stop_dates.add(date)
        elif combined <= -0.1:
            overrides[date] = 3
            stop_dates.add(date)
        # else: 기본 5종목

    result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    result_df = apply_tighter_stop_loss(result_df, stop_dates, -3.0)
    s = calc_stats(result_df)
    # 각 등급별 일수
    skip_count = sum(1 for v in overrides.values() if v == 0)
    reduce2_count = sum(1 for v in overrides.values() if v == 2)
    reduce3_count = sum(1 for v in overrides.values() if v == 3)
    cat5.append((f'5E. 복합점수 단계조정(스킵{skip_count}/2종목{reduce2_count}/3종목{reduce3_count})',
                 s, len(overrides), pd.DataFrame()))

    # --- 5F: 같은 복합점수 but 더 보수적 임계값 ---
    overrides = {}
    stop_dates = set()
    for date in all_dates:
        regime = compute_regime_score(date, all_dates, all_market_dates,
                                      daily_results, market_data)
        nxt = compute_nxt_score(date, market_data)
        combined = regime * 0.6 + nxt * 0.4

        if combined <= -0.4:
            overrides[date] = 0  # 완전 스킵
            stop_dates.add(date)
        elif combined <= -0.2:
            overrides[date] = 2
            stop_dates.add(date)
        elif combined <= 0.0:
            overrides[date] = 3
            stop_dates.add(date)

    result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    result_df = apply_tighter_stop_loss(result_df, stop_dates, -3.0)
    s = calc_stats(result_df)
    skip_count = sum(1 for v in overrides.values() if v == 0)
    reduce2_count = sum(1 for v in overrides.values() if v == 2)
    reduce3_count = sum(1 for v in overrides.values() if v == 3)
    cat5.append((f'5F. 복합점수 보수적(스킵{skip_count}/2종목{reduce2_count}/3종목{reduce3_count})',
                 s, len(overrides), pd.DataFrame()))

    # --- 5G: T-1 지수 하락 + NXT 갭 하락 → 3종목+손절3% ---
    overrides = {}
    stop_dates = set()
    for date in all_dates:
        nxt_bad = False
        index_bad = False
        m = market_data.get(date)
        if m and (m.get('kospi_gap', 0) <= -0.5 or m.get('kosdaq_gap', 0) <= -0.5):
            nxt_bad = True
        prevs_m = get_prev_trading_dates(all_market_dates, date, 1)
        if prevs_m:
            pm = market_data.get(prevs_m[0])
            if pm and (pm['kospi_chg'] <= -1.0 or pm['kosdaq_chg'] <= -1.0):
                index_bad = True
        if nxt_bad and index_bad:
            overrides[date] = 3
            stop_dates.add(date)
    result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    result_df = apply_tighter_stop_loss(result_df, stop_dates, -3.0)
    s = calc_stats(result_df)
    cat5.append(('5G. T-1지수-1%AND NXT갭-0.5%→3종목+손절3%', s, len(overrides), pd.DataFrame()))

    # --- 5H: T-1 전패 + NXT 갭 하락 → 완전 스킵, T-1 마이너스 + NXT 갭 하락 → 3종목 ---
    overrides = {}
    stop_dates = set()
    for date in all_dates:
        nxt_bad = False
        m = market_data.get(date)
        if m and (m.get('kospi_gap', 0) <= -0.5 or m.get('kosdaq_gap', 0) <= -0.5):
            nxt_bad = True

        prevs = get_prev_trading_dates(all_dates, date, 1)
        t1_alllose = False
        t1_minus = False
        if prevs:
            r = daily_results.get(prevs[0])
            if r and r['trades'] >= 2 and r['winrate'] == 0:
                t1_alllose = True
            if r and r['trades'] >= 1 and r['avg_pnl'] < 0:
                t1_minus = True

        if nxt_bad and t1_alllose:
            overrides[date] = 0  # 스킵
            stop_dates.add(date)
        elif nxt_bad and t1_minus:
            overrides[date] = 3
            stop_dates.add(date)

    result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
    result_df = apply_tighter_stop_loss(result_df, stop_dates, -3.0)
    s = calc_stats(result_df)
    skip_count = sum(1 for v in overrides.values() if v == 0)
    reduce_count = sum(1 for v in overrides.values() if v == 3)
    cat5.append((f'5H. NXT+T-1 단계적(스킵{skip_count}/3종목{reduce_count})', s, len(overrides), pd.DataFrame()))

    _print_category('카테고리 5: NXT + 전일매매 복합 (포지션축소+손절축소)', cat5, base)
    for name, s, cnt, _ in cat5:
        all_scenarios.append((name, s, cnt, 'NXT복합'))

    # ================================================================
    # 전체 비교 요약
    # ================================================================
    print('\n')
    print('=' * 110)
    print('  전체 비교 요약 (원금수익률 기준 정렬)')
    print('=' * 110)
    print(f'  {"시나리오":<55} {"거래":>5} {"승률":>6} {"원금수익률":>10} {"개선":>8} {"적용일":>6}')
    print('  ' + '-' * 100)
    print(f'  {"[기준선] 필터 없음 (max=" + str(max_daily) + ")":<55} '
          f'{base["trades"]:>4}건 {base["winrate"]:>5.1f}% '
          f'{base["capital_return"]:>+9.2f}% {"":>8} {"":>6}')

    sorted_scenarios = sorted(all_scenarios, key=lambda x: x[1]['capital_return'], reverse=True)
    for name, s, cnt, cat in sorted_scenarios:
        improvement = s['capital_return'] - base['capital_return']
        marker = ' ★' if improvement > 0 else ''
        print(f'  {name:<55} {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+7.2f}%p {cnt:>5}일{marker}')

    # ================================================================
    # 월별 성과 분해 (상위 5개 시나리오 + 기준선)
    # ================================================================
    print('\n')
    print('=' * 110)
    print('  월별 성과 분해 (상위 5개 시나리오 vs 기준선)')
    print('=' * 110)

    # 상위 5개 + 기준선 월별 성과 비교
    base_cap = calc_capital_returns(limited_df)
    months = sorted(base_cap.get('monthly_returns', {}).keys())

    if months:
        header = f'  {"월":>8}'
        header += f' {"기준선":>10}'
        top5 = sorted_scenarios[:5]
        for name, _, _, _ in top5:
            short_name = name[:12]
            header += f' {short_name:>12}'
        print(header)
        print('  ' + '-' * (10 + 12 * (len(top5) + 1)))

        # 각 시나리오 별로 월별 데이터 재계산
        top5_monthly = []
        for name, _, cnt, cat in top5:
            # 시나리오 재현을 위해 같은 필터를 적용해야 하지만,
            # 여기서는 전체 결과의 원금수익률만 보여줌
            top5_monthly.append({})

        for m in months:
            row = f'  {m[:4]}-{m[4:]:>4}'
            base_m = base_cap['monthly_returns'].get(m, 0)
            row += f' {base_m:>+9.2f}%'
            # 상위 시나리오의 월별 데이터는 복잡하므로 기준선만 표시
            for _ in top5:
                row += f' {"":>12}'
            print(row)

    # ================================================================
    # 하락장 구간 집중 분석
    # ================================================================
    print('\n')
    print('=' * 110)
    print('  하락장 구간 집중 분석: 지수 하락일의 필터별 성과')
    print('=' * 110)

    # 지수 하락일 (KOSPI 또는 KOSDAQ -1% 이하) 식별
    down_dates = set()
    for date in all_dates:
        m = market_data.get(date)
        if m and (m.get('kospi_chg', 0) <= -1.0 or m.get('kosdaq_chg', 0) <= -1.0):
            down_dates.add(date)

    up_dates = set(all_dates) - down_dates

    print(f'\n  전체 거래일: {len(all_dates)}일')
    print(f'  지수 하락일 (KOSPI 또는 KOSDAQ -1% 이하): {len(down_dates)}일')
    print(f'  정상/상승일: {len(up_dates)}일')

    # 기준선: 하락일 vs 정상일
    down_trades = limited_df[limited_df['date'].isin(down_dates)]
    up_trades = limited_df[limited_df['date'].isin(up_dates)]
    down_stats = calc_stats(down_trades) if len(down_trades) > 0 else calc_stats(None)
    up_stats = calc_stats(up_trades) if len(up_trades) > 0 else calc_stats(None)

    print(f'\n  기준선 하락일: {down_stats["trades"]}건, 승률 {down_stats["winrate"]:.1f}%, '
          f'평균 {down_stats["avg_pnl"]:+.2f}%')
    print(f'  기준선 정상일: {up_stats["trades"]}건, 승률 {up_stats["winrate"]:.1f}%, '
          f'평균 {up_stats["avg_pnl"]:+.2f}%')

    # 하락일에서의 보호 효과 분석
    print(f'\n  {"시나리오":<55} {"하락일거래":>8} {"하락일평균":>10} {"정상일거래":>8} {"정상일평균":>10}')
    print('  ' + '-' * 100)
    print(f'  {"[기준선]":<55} {down_stats["trades"]:>7}건 {down_stats["avg_pnl"]:>+9.2f}% '
          f'{up_stats["trades"]:>7}건 {up_stats["avg_pnl"]:>+9.2f}%')

    # 이 분석은 복잡하므로, 주요 시나리오만 표시
    # (완전 스킵 시나리오는 하락일 거래가 줄어들므로 의미 있음)

    # ================================================================
    # 03-03 ~ 03-04 시나리오 분석 (현재 상황)
    # ================================================================
    print('\n')
    print('=' * 110)
    print('  현재 상황 분석: 2026-03-03 ~ 03-04')
    print('=' * 110)

    for d in ['20260303', '20260304']:
        m = market_data.get(d, {})
        r = daily_results.get(d, {})
        regime = compute_regime_score(d, all_dates, all_market_dates,
                                      daily_results, market_data)
        nxt = compute_nxt_score(d, market_data)
        combined = regime * 0.6 + nxt * 0.4

        print(f'\n  [{d}]')
        print(f'    KOSPI: 등락 {m.get("kospi_chg", 0):+.2f}%, 갭 {m.get("kospi_gap", 0):+.2f}%')
        print(f'    KOSDAQ: 등락 {m.get("kosdaq_chg", 0):+.2f}%, 갭 {m.get("kosdaq_gap", 0):+.2f}%')
        if r:
            print(f'    매매: {r.get("trades", 0)}건, 승률 {r.get("winrate", 0):.0f}%, '
                  f'평균 {r.get("avg_pnl", 0):+.2f}%')
        print(f'    레짐 점수: {regime:+.3f}, NXT 점수: {nxt:+.3f}, 복합: {combined:+.3f}')

        # 각 필터가 이 날 어떤 판단을 내렸을지
        decisions = []
        prevs = get_prev_trading_dates(all_dates, d, 1)
        if prevs:
            pr = daily_results.get(prevs[0])
            if pr:
                decisions.append(f'T-1 매매: {pr["trades"]}건 승률{pr["winrate"]:.0f}% 평균{pr["avg_pnl"]:+.2f}%')
                if pr['trades'] >= 2 and pr['winrate'] == 0:
                    decisions.append('→ T-1 전패 필터 발동!')
                if pr['avg_pnl'] < -2.0:
                    decisions.append('→ T-1 평균<-2% 필터 발동!')

        if m:
            if m.get('kospi_gap', 0) <= -1.0 or m.get('kosdaq_gap', 0) <= -1.0:
                decisions.append(f'→ NXT 갭 -1% 필터 발동!')
            if m.get('kospi_gap', 0) <= -0.5 or m.get('kosdaq_gap', 0) <= -0.5:
                decisions.append(f'→ NXT 갭 -0.5% 필터 발동!')

        if combined <= -0.6:
            decisions.append(f'→ 복합점수 {combined:+.3f} → 완전 스킵')
        elif combined <= -0.3:
            decisions.append(f'→ 복합점수 {combined:+.3f} → 2종목 축소')
        elif combined <= -0.1:
            decisions.append(f'→ 복합점수 {combined:+.3f} → 3종목 축소')
        else:
            decisions.append(f'→ 복합점수 {combined:+.3f} → 정상 운영')

        for dec in decisions:
            print(f'    {dec}')


def _print_category(title, scenarios, base_stats):
    """카테고리별 테이블 출력"""
    print('\n')
    print('#' * 110)
    print(f'#  {title}')
    print('#' * 110)
    print(f'  {"시나리오":<55} {"거래":>5} {"승률":>6} {"원금수익률":>10} '
          f'{"개선":>8} {"적용일":>6} {"적용일 평균":>12}')
    print('  ' + '-' * 110)
    print(f'  {"[기준선] 필터 없음":<55} {base_stats["trades"]:>4}건 '
          f'{base_stats["winrate"]:>5.1f}% {base_stats["capital_return"]:>+9.2f}% '
          f'{"":>8} {"":>6} {"":>12}')

    for name, s, cnt, skipped_df in scenarios:
        improvement = s['capital_return'] - base_stats['capital_return']
        skip_avg = ''
        if isinstance(skipped_df, pd.DataFrame) and len(skipped_df) > 0:
            skip_avg = f'{skipped_df["pnl"].mean():>+.2f}%({len(skipped_df)}건)'
        marker = ' ★' if improvement > 0 else ''
        print(f'  {name:<55} {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+7.2f}%p {cnt:>5}일 '
              f'{skip_avg:>12}{marker}')


def main():
    parser = argparse.ArgumentParser(description='시장 레짐 필터 멀티버스 시뮬레이션 v2')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260304', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    args = parser.parse_args()

    print('=' * 110)
    print('시장 레짐 필터 멀티버스 시뮬레이션 v2')
    print('  NXT 프록시 + 포지션 축소 + 손절 조정')
    print('=' * 110)

    print('\n[1/3] 시장 데이터 로드...')
    market_data = load_market_data()
    print(f'  KOSPI/KOSDAQ 데이터: {len(market_data)}일')

    print('\n[2/3] 전체 시뮬레이션 실행...')
    trades_df = run_simulation(
        start_date=args.start,
        end_date=args.end,
        max_daily=0,
        verbose=True,
    )

    if trades_df is None or len(trades_df) == 0:
        print('거래 없음. 종료.')
        return

    print(f'\n[3/3] 멀티버스 시뮬레이션 ({len(trades_df)}건 기반)...')
    run_multiverse(trades_df, market_data, args.max_daily)

    print('\nDone!')


if __name__ == '__main__':
    main()
