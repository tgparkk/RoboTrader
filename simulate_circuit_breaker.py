"""
서킷브레이커 파라미터 멀티버스 시뮬레이션

현재 서킷브레이커 설정:
- 조건1: 전일 KOSPI/KOSDAQ -3% 이하 -> 매수 완전 중단
- 조건1b: 전일 -1% 이하 -> 손절 3%/익절 4%로 축소 (매수 허용)
- 조건2: 전일 -1% + NXT갭 -0.5% -> 매수 완전 중단

이 시뮬에서 테스트하는 파라미터:
1. 매수중단 임계값: -2%, -2.5%, -3%, -3.5%, -4%
2. 손절축소 임계값: -0.5%, -1%, -1.5%, -2%
3. 축소 손절폭: 2%, 2.5%, 3%, 3.5%, 4%
4. NXT갭+전일하락 복합 조건

Usage:
  python simulate_circuit_breaker.py --start 20250224 --end 20260313
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
    """KOSPI/KOSDAQ 일봉 -> 전일대비 등락률 + 시가갭"""
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


def get_prev_market(market_data, trade_dates, date):
    """해당 거래일의 전일 지수 데이터 반환"""
    all_market_dates = sorted(market_data.keys())
    # date 이전의 가장 가까운 market date
    prev_dates = [d for d in all_market_dates if d < date]
    if not prev_dates:
        return None
    return market_data.get(prev_dates[-1])


def apply_modified_sl_tp(trades_df, target_dates, new_stop_pct=None, new_tp_pct=None):
    """
    특정 날짜들에서 손절/익절 변경을 정확하게 시뮬레이션.

    min_profit_pct(장중 최대 낙폭)과 max_profit_pct(장중 최고 수익)를 활용하여
    거래 결과를 올바르게 재분류:

    1. 원래 손절 -> 새 손절폭으로 PnL 조정 (손실 감소)
    2. 원래 익절/장마감 중 min_profit_pct <= new_stop_pct -> 새 손절로 전환 (false stop)
    3. 원래 익절 -> 새 익절폭으로 PnL 조정 (수익 감소)
    4. 원래 장마감 중 max_profit_pct >= new_tp_pct -> 새 익절로 전환
    5. 원래 손절 중 max_profit_pct >= new_tp_pct -> 새 익절로 전환
       (check_exit_conditions에서 high를 먼저 체크하므로 TP가 SL보다 선행)
    """
    if not target_dates:
        return trades_df

    df = trades_df.copy()
    has_min = 'min_profit_pct' in df.columns
    has_max = 'max_profit_pct' in df.columns
    in_target = df['date'].isin(target_dates)

    for idx in df[in_target].index:
        row = df.loc[idx]
        orig_reason = row['exit_reason']
        orig_pnl = row['pnl']
        min_pnl = row['min_profit_pct'] if has_min else None
        max_pnl = row['max_profit_pct'] if has_max else None

        # 새 TP가 있고, 장중 최고가 새 TP에 도달한 경우
        # (check_exit_conditions에서 high를 low보다 먼저 체크하므로
        #  TP 도달이 SL보다 선행한다고 간주)
        if new_tp_pct is not None and has_max and max_pnl is not None:
            if max_pnl >= new_tp_pct and orig_reason != '익절':
                # 원래 손절/장마감이었지만 새 TP에 먼저 도달
                df.loc[idx, 'pnl'] = new_tp_pct
                df.loc[idx, 'exit_reason'] = '익절'
                df.loc[idx, 'result'] = 'WIN'
                continue

        # 새 SL이 있고, 장중 최저가 새 SL에 도달한 경우 (false stop)
        if new_stop_pct is not None and has_min and min_pnl is not None:
            if min_pnl <= new_stop_pct and orig_reason != '손절':
                # 원래 익절/장마감이었지만 새 SL에 먼저 걸림
                # 단, 새 TP에도 도달했으면 위에서 이미 처리됨
                df.loc[idx, 'pnl'] = new_stop_pct
                df.loc[idx, 'exit_reason'] = '손절'
                df.loc[idx, 'result'] = 'LOSS'
                continue

        # 원래 손절 -> 새 손절폭으로 조정
        if new_stop_pct is not None and orig_reason == '손절':
            df.loc[idx, 'pnl'] = new_stop_pct

        # 원래 익절 -> 새 익절폭으로 조정
        if new_tp_pct is not None and orig_reason == '익절':
            df.loc[idx, 'pnl'] = new_tp_pct

        # 장마감: max_profit_pct >= new_tp_pct 이면 새 익절로 전환
        if new_tp_pct is not None and has_max and max_pnl is not None:
            if orig_reason == '장마감' and max_pnl >= new_tp_pct:
                df.loc[idx, 'pnl'] = new_tp_pct
                df.loc[idx, 'exit_reason'] = '익절'
                df.loc[idx, 'result'] = 'WIN'

    return df


def _print_category(title, scenarios, base_stats):
    """카테고리별 테이블 출력"""
    print('\n')
    print('#' * 120)
    print(f'#  {title}')
    print('#' * 120)
    print(f'  {"시나리오":<50} {"거래":>5} {"승률":>6} {"평균PnL":>8} '
          f'{"원금수익률":>10} {"개선":>9} {"적용일":>6}')
    print('  ' + '-' * 110)
    print(f'  {"[기준선] 필터 없음":<50} {base_stats["trades"]:>4}건 '
          f'{base_stats["winrate"]:>5.1f}% {base_stats["avg_pnl"]:>+7.2f}% '
          f'{base_stats["capital_return"]:>+9.2f}% {"":>9} {"":>6}')

    for name, s, cnt in scenarios:
        improvement = s['capital_return'] - base_stats['capital_return']
        marker = ' *' if improvement > 0 else ''
        print(f'  {name:<50} {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["avg_pnl"]:>+7.2f}% {s["capital_return"]:>+9.2f}% '
              f'{improvement:>+8.2f}%p {cnt:>5}일{marker}')


def run_multiverse(trades_df, market_data, max_daily=5):
    """서킷브레이커 파라미터 멀티버스"""

    limited_df = apply_daily_limit(trades_df, max_daily)
    all_dates = sorted(limited_df['date'].unique())
    all_market_dates = sorted(market_data.keys())

    base = calc_stats(limited_df)

    print('\n')
    print('=' * 120)
    print('  서킷브레이커 파라미터 멀티버스 시뮬레이션')
    print('=' * 120)
    print(f'\n  기준선 (서킷브레이커 없음, max={max_daily}): {base["trades"]}건, '
          f'승률 {base["winrate"]:.1f}%, 원금수익률 {base["capital_return"]:+.2f}%, '
          f'평균 {base["avg_pnl"]:+.2f}%')

    # 전일 지수 등락률 매핑
    def get_prev_chg(date):
        prev_dates = [d for d in all_market_dates if d < date]
        if not prev_dates:
            return None
        return market_data.get(prev_dates[-1])

    # ================================================================
    # 카테고리 1: 매수 완전 중단 임계값
    # ================================================================
    cat1 = []
    for threshold in [-1.5, -2.0, -2.5, -3.0, -3.5, -4.0]:
        skip_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            if prev and (prev['kospi_chg'] <= threshold or prev['kosdaq_chg'] <= threshold):
                skip_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        s = calc_stats(filtered)
        cat1.append((f'전일 {threshold}% 이하 -> 매수중단', s, len(skip_dates)))

    _print_category('카테고리 1: 매수 완전 중단 임계값', cat1, base)

    # ================================================================
    # 카테고리 2: 손절 축소 임계값 (전일 N% 이하 -> 손절 3%)
    # ================================================================
    cat2 = []
    for threshold in [-0.5, -0.7, -1.0, -1.5, -2.0]:
        target_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            if prev and (prev['kospi_chg'] <= threshold or prev['kosdaq_chg'] <= threshold):
                target_dates.add(date)
        adjusted = apply_modified_sl_tp(limited_df, target_dates, new_stop_pct=-3.0, new_tp_pct=4.0)
        s = calc_stats(adjusted)
        cat2.append((f'전일 {threshold}% 이하 -> 손절3%/익절4%', s, len(target_dates)))

    _print_category('카테고리 2: 손절/익절 축소 임계값 (손절3%/익절4%)', cat2, base)

    # ================================================================
    # 카테고리 3: 축소 손절폭 비교 (전일 -1% 고정, 손절폭 변경)
    # ================================================================
    cat3 = []
    threshold_1pct = set()
    for date in all_dates:
        prev = get_prev_chg(date)
        if prev and (prev['kospi_chg'] <= -1.0 or prev['kosdaq_chg'] <= -1.0):
            threshold_1pct.add(date)

    for sl, tp in [(-2.0, 3.0), (-2.5, 3.5), (-3.0, 4.0), (-3.5, 4.5), (-4.0, 5.0)]:
        adjusted = apply_modified_sl_tp(limited_df, threshold_1pct, new_stop_pct=sl, new_tp_pct=tp)
        s = calc_stats(adjusted)
        cat3.append((f'전일-1% -> 손절{abs(sl):.1f}%/익절{tp:.1f}%', s, len(threshold_1pct)))

    # 손절만 축소, 익절 유지
    for sl in [-2.0, -2.5, -3.0, -3.5]:
        adjusted = apply_modified_sl_tp(limited_df, threshold_1pct, new_stop_pct=sl)
        s = calc_stats(adjusted)
        cat3.append((f'전일-1% -> 손절{abs(sl):.1f}% (익절 유지)', s, len(threshold_1pct)))

    _print_category('카테고리 3: 축소 폭 비교 (전일 -1% 이하일 때)', cat3, base)

    # ================================================================
    # 카테고리 4: NXT갭 + 전일하락 복합
    # ================================================================
    cat4 = []

    for prev_th, gap_th in [
        (-0.5, -0.3), (-0.5, -0.5), (-0.5, -0.7),
        (-1.0, -0.3), (-1.0, -0.5), (-1.0, -0.7), (-1.0, -1.0),
        (-1.5, -0.5), (-1.5, -1.0),
    ]:
        # 매수 중단
        skip_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            m = market_data.get(date)
            if prev and m:
                prev_bad = prev['kospi_chg'] <= prev_th or prev['kosdaq_chg'] <= prev_th
                gap_bad = m.get('kospi_gap', 0) <= gap_th or m.get('kosdaq_gap', 0) <= gap_th
                if prev_bad and gap_bad:
                    skip_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        s = calc_stats(filtered)
        cat4.append((f'전일{prev_th}%+갭{gap_th}% -> 매수중단', s, len(skip_dates)))

    for prev_th, gap_th in [
        (-0.5, -0.5), (-1.0, -0.3), (-1.0, -0.5), (-1.0, -0.7),
    ]:
        # 손절 축소
        target_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            m = market_data.get(date)
            if prev and m:
                prev_bad = prev['kospi_chg'] <= prev_th or prev['kosdaq_chg'] <= prev_th
                gap_bad = m.get('kospi_gap', 0) <= gap_th or m.get('kosdaq_gap', 0) <= gap_th
                if prev_bad and gap_bad:
                    target_dates.add(date)
        adjusted = apply_modified_sl_tp(limited_df, target_dates, new_stop_pct=-3.0, new_tp_pct=4.0)
        s = calc_stats(adjusted)
        cat4.append((f'전일{prev_th}%+갭{gap_th}% -> 손절3%/익절4%', s, len(target_dates)))

    _print_category('카테고리 4: NXT갭 + 전일하락 복합', cat4, base)

    # ================================================================
    # 카테고리 5: 현재 설정 조합 vs 대안
    # ================================================================
    cat5 = []

    # 현재 설정: 전일-3% -> 매수중단, 전일-1% -> 손절3%/익절4%, 전일-1%+갭-0.5% -> 매수중단
    def apply_current_cb(limited_df, all_dates, get_prev_chg, market_data):
        skip_dates = set()
        sl_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            m = market_data.get(date)
            if not prev:
                continue
            worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
            # 조건1: 전일 -3%
            if worst <= -3.0:
                skip_dates.add(date)
                continue
            # 조건2: 전일 -1% + 갭 -0.5%
            if worst <= -1.0 and m:
                gap = min(m.get('kospi_gap', 0), m.get('kosdaq_gap', 0))
                if gap <= -0.5:
                    skip_dates.add(date)
                    continue
            # 조건1b: 전일 -1% -> 손절축소
            if worst <= -1.0:
                sl_dates.add(date)

        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        adjusted = apply_modified_sl_tp(filtered, sl_dates, new_stop_pct=-3.0, new_tp_pct=4.0)
        return adjusted, len(skip_dates), len(sl_dates)

    current_df, skip_n, sl_n = apply_current_cb(limited_df, all_dates, get_prev_chg, market_data)
    s_current = calc_stats(current_df)
    cat5.append((f'[현재] -3%중단/-1%손절축소/-1%+갭-0.5%중단', s_current,
                 skip_n + sl_n))

    # 대안 A: -2.5% 중단, -1% 손절축소
    def apply_alt_a(limited_df, all_dates, get_prev_chg, market_data):
        skip_dates = set()
        sl_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            if not prev:
                continue
            worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
            if worst <= -2.5:
                skip_dates.add(date)
                continue
            if worst <= -1.0:
                sl_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        adjusted = apply_modified_sl_tp(filtered, sl_dates, new_stop_pct=-3.0, new_tp_pct=4.0)
        return adjusted, len(skip_dates), len(sl_dates)

    alt_a_df, skip_n, sl_n = apply_alt_a(limited_df, all_dates, get_prev_chg, market_data)
    s_alt_a = calc_stats(alt_a_df)
    cat5.append((f'[대안A] -2.5%중단/-1%손절축소', s_alt_a, skip_n + sl_n))

    # 대안 B: -3% 중단, -0.5% 손절축소, 갭조건 없음
    def apply_alt_b(limited_df, all_dates, get_prev_chg, market_data):
        skip_dates = set()
        sl_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            if not prev:
                continue
            worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
            if worst <= -3.0:
                skip_dates.add(date)
                continue
            if worst <= -0.5:
                sl_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        adjusted = apply_modified_sl_tp(filtered, sl_dates, new_stop_pct=-3.0, new_tp_pct=4.0)
        return adjusted, len(skip_dates), len(sl_dates)

    alt_b_df, skip_n, sl_n = apply_alt_b(limited_df, all_dates, get_prev_chg, market_data)
    s_alt_b = calc_stats(alt_b_df)
    cat5.append((f'[대안B] -3%중단/-0.5%손절축소/갭없음', s_alt_b, skip_n + sl_n))

    # 대안 C: -3% 중단, -1% 손절 2.5%/익절 3.5%
    def apply_alt_c(limited_df, all_dates, get_prev_chg, market_data):
        skip_dates = set()
        sl_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            m = market_data.get(date)
            if not prev:
                continue
            worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
            if worst <= -3.0:
                skip_dates.add(date)
                continue
            if worst <= -1.0 and m:
                gap = min(m.get('kospi_gap', 0), m.get('kosdaq_gap', 0))
                if gap <= -0.5:
                    skip_dates.add(date)
                    continue
            if worst <= -1.0:
                sl_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        adjusted = apply_modified_sl_tp(filtered, sl_dates, new_stop_pct=-2.5, new_tp_pct=3.5)
        return adjusted, len(skip_dates), len(sl_dates)

    alt_c_df, skip_n, sl_n = apply_alt_c(limited_df, all_dates, get_prev_chg, market_data)
    s_alt_c = calc_stats(alt_c_df)
    cat5.append((f'[대안C] 현재+손절2.5%/익절3.5%', s_alt_c, skip_n + sl_n))

    # 대안 D: -3% 중단, -1.5% 손절축소 (더 보수적 진입)
    def apply_alt_d(limited_df, all_dates, get_prev_chg, market_data):
        skip_dates = set()
        sl_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            m = market_data.get(date)
            if not prev:
                continue
            worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
            if worst <= -3.0:
                skip_dates.add(date)
                continue
            if worst <= -1.0 and m:
                gap = min(m.get('kospi_gap', 0), m.get('kosdaq_gap', 0))
                if gap <= -0.5:
                    skip_dates.add(date)
                    continue
            if worst <= -1.5:
                sl_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        adjusted = apply_modified_sl_tp(filtered, sl_dates, new_stop_pct=-3.0, new_tp_pct=4.0)
        return adjusted, len(skip_dates), len(sl_dates)

    alt_d_df, skip_n, sl_n = apply_alt_d(limited_df, all_dates, get_prev_chg, market_data)
    s_alt_d = calc_stats(alt_d_df)
    cat5.append((f'[대안D] 현재+손절축소 -1.5%부터', s_alt_d, skip_n + sl_n))

    # 대안 E: 현재 + 손절만 축소 (익절은 6% 유지)
    def apply_alt_e(limited_df, all_dates, get_prev_chg, market_data):
        skip_dates = set()
        sl_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            m = market_data.get(date)
            if not prev:
                continue
            worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
            if worst <= -3.0:
                skip_dates.add(date)
                continue
            if worst <= -1.0 and m:
                gap = min(m.get('kospi_gap', 0), m.get('kosdaq_gap', 0))
                if gap <= -0.5:
                    skip_dates.add(date)
                    continue
            if worst <= -1.0:
                sl_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        adjusted = apply_modified_sl_tp(filtered, sl_dates, new_stop_pct=-3.0)
        return adjusted, len(skip_dates), len(sl_dates)

    alt_e_df, skip_n, sl_n = apply_alt_e(limited_df, all_dates, get_prev_chg, market_data)
    s_alt_e = calc_stats(alt_e_df)
    cat5.append((f'[대안E] 현재+손절3%만 (익절6% 유지)', s_alt_e, skip_n + sl_n))

    # 대안 F: -2% 중단, -1% 손절축소, 갭조건 유지
    def apply_alt_f(limited_df, all_dates, get_prev_chg, market_data):
        skip_dates = set()
        sl_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            m = market_data.get(date)
            if not prev:
                continue
            worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
            if worst <= -2.0:
                skip_dates.add(date)
                continue
            if worst <= -1.0 and m:
                gap = min(m.get('kospi_gap', 0), m.get('kosdaq_gap', 0))
                if gap <= -0.5:
                    skip_dates.add(date)
                    continue
            if worst <= -1.0:
                sl_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        adjusted = apply_modified_sl_tp(filtered, sl_dates, new_stop_pct=-3.0, new_tp_pct=4.0)
        return adjusted, len(skip_dates), len(sl_dates)

    alt_f_df, skip_n, sl_n = apply_alt_f(limited_df, all_dates, get_prev_chg, market_data)
    s_alt_f = calc_stats(alt_f_df)
    cat5.append((f'[대안F] -2%중단/-1%손절축소/갭-0.5%중단', s_alt_f, skip_n + sl_n))

    _print_category('카테고리 5: 현재 설정 vs 대안 조합', cat5, base)

    # ================================================================
    # 하락일 상세 분석
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  하락일 상세: 전일 하락 구간별 거래 성과')
    print('=' * 120)

    print(f'\n  {"전일 구간":<20} {"거래일":>6} {"거래":>6} {"승률":>7} '
          f'{"평균PnL":>9} {"평균승":>8} {"평균패":>8}')
    print('  ' + '-' * 80)

    ranges = [
        ('전일 -3% 이하', lambda w: w <= -3.0),
        ('전일 -2~-3%', lambda w: -3.0 < w <= -2.0),
        ('전일 -1~-2%', lambda w: -2.0 < w <= -1.0),
        ('전일 -0.5~-1%', lambda w: -1.0 < w <= -0.5),
        ('전일 0~-0.5%', lambda w: -0.5 < w <= 0),
        ('전일 양봉', lambda w: w > 0),
    ]

    for label, cond_fn in ranges:
        matched_dates = set()
        for date in all_dates:
            prev = get_prev_chg(date)
            if prev:
                worst = min(prev['kospi_chg'], prev['kosdaq_chg'])
                if cond_fn(worst):
                    matched_dates.add(date)
        subset = limited_df[limited_df['date'].isin(matched_dates)]
        if len(subset) == 0:
            print(f'  {label:<20} {len(matched_dates):>5}일 {"0건":>6}')
            continue
        s = calc_stats(subset)
        print(f'  {label:<20} {len(matched_dates):>5}일 {s["trades"]:>5}건 '
              f'{s["winrate"]:>6.1f}% {s["avg_pnl"]:>+8.2f}% '
              f'{s["avg_win"]:>+7.2f}% {s["avg_loss"]:>+7.2f}%')

    # ================================================================
    # 갭별 분석
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  당일 시가갭 구간별 거래 성과')
    print('=' * 120)

    print(f'\n  {"갭 구간":<20} {"거래일":>6} {"거래":>6} {"승률":>7} '
          f'{"평균PnL":>9} {"평균승":>8} {"평균패":>8}')
    print('  ' + '-' * 80)

    gap_ranges = [
        ('갭 -2% 이하', lambda g: g <= -2.0),
        ('갭 -1~-2%', lambda g: -2.0 < g <= -1.0),
        ('갭 -0.5~-1%', lambda g: -1.0 < g <= -0.5),
        ('갭 0~-0.5%', lambda g: -0.5 < g <= 0),
        ('갭 0~+0.5%', lambda g: 0 < g <= 0.5),
        ('갭 +0.5% 이상', lambda g: g > 0.5),
    ]

    for label, cond_fn in gap_ranges:
        matched_dates = set()
        for date in all_dates:
            m = market_data.get(date)
            if m:
                worst_gap = min(m.get('kospi_gap', 0), m.get('kosdaq_gap', 0))
                if cond_fn(worst_gap):
                    matched_dates.add(date)
        subset = limited_df[limited_df['date'].isin(matched_dates)]
        if len(subset) == 0:
            print(f'  {label:<20} {len(matched_dates):>5}일 {"0건":>6}')
            continue
        s = calc_stats(subset)
        print(f'  {label:<20} {len(matched_dates):>5}일 {s["trades"]:>5}건 '
              f'{s["winrate"]:>6.1f}% {s["avg_pnl"]:>+8.2f}% '
              f'{s["avg_win"]:>+7.2f}% {s["avg_loss"]:>+7.2f}%')


def main():
    parser = argparse.ArgumentParser(description='서킷브레이커 파라미터 멀티버스')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260313', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    args = parser.parse_args()

    print('=' * 120)
    print('서킷브레이커 파라미터 멀티버스 시뮬레이션')
    print('=' * 120)

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
