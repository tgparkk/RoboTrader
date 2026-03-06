"""
전일 지수 하락일 전략 성과 멀티버스 시뮬레이션

전일 KOSPI/KOSDAQ 하락 정도별로 전략이 어떻게 작동하는지 분석.
핵심 질문: "전일 지수가 하락한 다음날, 이 전략이 안 먹히는가?"

분석 축:
1. 전일 지수 하락 강도별 성과 (0~-0.5%, -0.5~-1%, -1~-2%, -2%~)
2. 전일 KOSPI vs KOSDAQ 각각 / 둘 다 하락
3. 전일 하락 + 당일 갭 조합
4. 하락일 필터 시나리오 (스킵, 포지션축소, 손절축소)
5. 연속 하락일 분석

Usage:
  python simulate_prev_day_decline.py --start 20250224 --end 20260306
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
    """KOSPI/KOSDAQ 일봉 데이터 로드"""
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
    result = {}
    for dt in dates:
        d = data[dt]
        if 'KS11' in d and 'KQ11' in d:
            entry = {}
            if 'KS11' in prev and 'KQ11' in prev:
                entry['kospi_chg'] = (d['KS11']['close'] / prev['KS11']['close'] - 1) * 100
                entry['kosdaq_chg'] = (d['KQ11']['close'] / prev['KQ11']['close'] - 1) * 100
                entry['kospi_gap'] = (d['KS11']['open'] / prev['KS11']['close'] - 1) * 100
                entry['kosdaq_gap'] = (d['KQ11']['open'] / prev['KQ11']['close'] - 1) * 100
                entry['prev_kospi_chg'] = prev.get('_kospi_chg', 0)
                entry['prev_kosdaq_chg'] = prev.get('_kosdaq_chg', 0)
            else:
                entry['kospi_chg'] = 0
                entry['kosdaq_chg'] = 0
                entry['kospi_gap'] = 0
                entry['kosdaq_gap'] = 0
                entry['prev_kospi_chg'] = 0
                entry['prev_kosdaq_chg'] = 0

            # 당일 등락률을 다음날 prev_로 사용하기 위해 임시 저장
            prev_kospi_chg = entry['kospi_chg']
            prev_kosdaq_chg = entry['kosdaq_chg']

            result[dt] = entry
            prev = {k: v for k, v in d.items()}
            prev['_kospi_chg'] = prev_kospi_chg
            prev['_kosdaq_chg'] = prev_kosdaq_chg

    return result


def calc_stats(df):
    """거래 DataFrame으로 통계 계산"""
    if df is None or len(df) == 0:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'winrate': 0,
                'avg_pnl': 0, 'capital_return': 0, 'avg_win': 0, 'avg_loss': 0,
                'stop_loss_count': 0, 'take_profit_count': 0}
    wins = (df['result'] == 'WIN').sum()
    losses = (df['result'] == 'LOSS').sum()
    cap = calc_capital_returns(df)
    avg_win = df[df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
    avg_loss = df[df['result'] != 'WIN']['pnl'].mean() if len(df) - wins > 0 else 0
    stop_loss_count = (df['exit_reason'] == '손절').sum() if 'exit_reason' in df.columns else 0
    take_profit_count = (df['exit_reason'] == '익절').sum() if 'exit_reason' in df.columns else 0
    return {
        'trades': len(df),
        'wins': int(wins),
        'losses': int(losses),
        'winrate': wins / len(df) * 100,
        'avg_pnl': df['pnl'].mean(),
        'capital_return': cap['total_return_pct'],
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'stop_loss_count': int(stop_loss_count),
        'take_profit_count': int(take_profit_count),
    }


def get_prev_market_date(all_market_dates, date):
    """전일 시장 날짜 반환"""
    try:
        idx = all_market_dates.index(date)
        return all_market_dates[idx - 1] if idx > 0 else None
    except ValueError:
        return None


def classify_prev_day(market_data, all_market_dates, date):
    """전일 지수 하락 정도 분류"""
    prev_date = get_prev_market_date(all_market_dates, date)
    if not prev_date or prev_date not in market_data:
        return None

    prev = market_data[prev_date]
    kospi_chg = prev['kospi_chg']
    kosdaq_chg = prev['kosdaq_chg']
    worst = min(kospi_chg, kosdaq_chg)

    return {
        'prev_date': prev_date,
        'kospi_chg': kospi_chg,
        'kosdaq_chg': kosdaq_chg,
        'worst_chg': worst,
        'today_kospi_gap': market_data.get(date, {}).get('kospi_gap', 0),
        'today_kosdaq_gap': market_data.get(date, {}).get('kosdaq_gap', 0),
    }


def print_section(title):
    print('\n')
    print('=' * 120)
    print(f'  {title}')
    print('=' * 120)


def print_stats_row(label, s, base_s=None):
    """한 줄 통계 출력"""
    improvement = ''
    if base_s and base_s['capital_return'] != 0:
        diff = s['capital_return'] - base_s['capital_return']
        improvement = f' ({diff:>+7.2f}%p)'
    sl = f" 손절{s['stop_loss_count']}" if s['stop_loss_count'] > 0 else ""
    tp = f" 익절{s['take_profit_count']}" if s['take_profit_count'] > 0 else ""
    print(f'  {label:<50} {s["trades"]:>4}건 '
          f'{s["wins"]:>3}승{s["losses"]:>3}패 '
          f'승률{s["winrate"]:>5.1f}% '
          f'평균{s["avg_pnl"]:>+6.2f}% '
          f'원금{s["capital_return"]:>+8.2f}%{improvement}'
          f'{sl}{tp}')


def run_analysis(trades_df, market_data, max_daily=5):
    """전일 지수 하락 영향 분석"""

    limited_df = apply_daily_limit(trades_df, max_daily)
    all_trade_dates = sorted(limited_df['date'].unique())
    all_market_dates = sorted(market_data.keys())

    base_stats = calc_stats(limited_df)

    # ================================================================
    # 1. 전일 지수 하락 강도별 성과 분류
    # ================================================================
    print_section('1. 전일 지수 하락 강도별 당일 전략 성과')

    # 각 거래일을 전일 지수 변동으로 분류
    buckets = {
        '전일 +1% 이상': [],
        '전일 0~+1%': [],
        '전일 -0.5~0%': [],
        '전일 -1~-0.5%': [],
        '전일 -2~-1%': [],
        '전일 -2% 이하': [],
    }

    day_classification = {}  # date -> prev worst_chg
    for date in all_trade_dates:
        info = classify_prev_day(market_data, all_market_dates, date)
        if not info:
            continue
        worst = info['worst_chg']
        day_classification[date] = info

        if worst >= 1.0:
            buckets['전일 +1% 이상'].append(date)
        elif worst >= 0:
            buckets['전일 0~+1%'].append(date)
        elif worst >= -0.5:
            buckets['전일 -0.5~0%'].append(date)
        elif worst >= -1.0:
            buckets['전일 -1~-0.5%'].append(date)
        elif worst >= -2.0:
            buckets['전일 -2~-1%'].append(date)
        else:
            buckets['전일 -2% 이하'].append(date)

    print(f'\n  기준선: {base_stats["trades"]}건, 승률 {base_stats["winrate"]:.1f}%, '
          f'원금수익률 {base_stats["capital_return"]:+.2f}%')
    print()
    print(f'  {"구간":<25} {"거래일":>5} {"거래":>5} {"승":>4} {"패":>4} '
          f'{"승률":>6} {"평균PnL":>8} {"원금수익률":>10} {"손절":>5} {"익절":>5}')
    print('  ' + '-' * 110)

    for label, dates in buckets.items():
        if not dates:
            s = calc_stats(None)
            print(f'  {label:<25} {0:>4}일 {s["trades"]:>4}건 {s["wins"]:>3}승 {s["losses"]:>3}패 '
                  f'{s["winrate"]:>5.1f}% {s["avg_pnl"]:>+7.2f}% {s["capital_return"]:>+9.2f}% '
                  f'{s["stop_loss_count"]:>4}건 {s["take_profit_count"]:>4}건')
            continue
        day_trades = limited_df[limited_df['date'].isin(dates)]
        s = calc_stats(day_trades)
        print(f'  {label:<25} {len(dates):>4}일 {s["trades"]:>4}건 {s["wins"]:>3}승 {s["losses"]:>3}패 '
              f'{s["winrate"]:>5.1f}% {s["avg_pnl"]:>+7.2f}% {s["capital_return"]:>+9.2f}% '
              f'{s["stop_loss_count"]:>4}건 {s["take_profit_count"]:>4}건')

    # ================================================================
    # 2. KOSPI vs KOSDAQ 개별 하락 영향
    # ================================================================
    print_section('2. KOSPI vs KOSDAQ 개별 하락 영향')

    conditions = {
        '전일 KOSPI만 -1%↓ (KOSDAQ은 정상)': [],
        '전일 KOSDAQ만 -1%↓ (KOSPI는 정상)': [],
        '전일 KOSPI+KOSDAQ 둘다 -1%↓': [],
        '전일 KOSPI 또는 KOSDAQ -1%↓': [],
        '전일 둘 다 정상 (>-1%)': [],
    }

    for date in all_trade_dates:
        info = day_classification.get(date)
        if not info:
            continue
        ki = info['kospi_chg'] <= -1.0
        qi = info['kosdaq_chg'] <= -1.0

        if ki and qi:
            conditions['전일 KOSPI+KOSDAQ 둘다 -1%↓'].append(date)
        elif ki:
            conditions['전일 KOSPI만 -1%↓ (KOSDAQ은 정상)'].append(date)
        elif qi:
            conditions['전일 KOSDAQ만 -1%↓ (KOSPI는 정상)'].append(date)
        else:
            conditions['전일 둘 다 정상 (>-1%)'].append(date)

        if ki or qi:
            conditions['전일 KOSPI 또는 KOSDAQ -1%↓'].append(date)

    for label, dates in conditions.items():
        day_trades = limited_df[limited_df['date'].isin(dates)] if dates else pd.DataFrame()
        s = calc_stats(day_trades if len(day_trades) > 0 else None)
        print(f'  {label:<45} {len(dates):>3}일 ', end='')
        print(f'{s["trades"]:>4}건 승률{s["winrate"]:>5.1f}% '
              f'평균{s["avg_pnl"]:>+6.2f}% 원금{s["capital_return"]:>+8.2f}%')

    # ================================================================
    # 3. 전일 하락 + 당일 갭 조합
    # ================================================================
    print_section('3. 전일 하락 + 당일 시가 갭 조합')

    combos = [
        ('전일-1%↓ + 당일갭-0.5%↓', -1.0, -0.5),
        ('전일-1%↓ + 당일갭-1.0%↓', -1.0, -1.0),
        ('전일-1%↓ + 당일갭+0%↑', -1.0, 0.0),
        ('전일-0.5%↓ + 당일갭-0.5%↓', -0.5, -0.5),
        ('전일-2%↓ + 당일갭-0.5%↓', -2.0, -0.5),
        ('전일-2%↓ + 당일갭 무관', -2.0, None),
    ]

    for label, prev_th, gap_th in combos:
        matched = []
        for date in all_trade_dates:
            info = day_classification.get(date)
            if not info:
                continue
            if info['worst_chg'] > prev_th:
                continue
            if gap_th is not None:
                today_gap = min(info['today_kospi_gap'], info['today_kosdaq_gap'])
                if gap_th < 0 and today_gap > gap_th:
                    continue
                if gap_th >= 0 and today_gap < gap_th:
                    continue
            matched.append(date)

        day_trades = limited_df[limited_df['date'].isin(matched)] if matched else pd.DataFrame()
        s = calc_stats(day_trades if len(day_trades) > 0 else None)
        print(f'  {label:<45} {len(matched):>3}일 ', end='')
        print(f'{s["trades"]:>4}건 승률{s["winrate"]:>5.1f}% '
              f'평균{s["avg_pnl"]:>+6.2f}% 원금{s["capital_return"]:>+8.2f}%')

    # ================================================================
    # 4. 연속 하락일 분석
    # ================================================================
    print_section('4. 연속 하락일 분석')

    consec_buckets = {
        '전일 하락 (1일)': [],
        '2일 연속 하락': [],
        '3일+ 연속 하락': [],
        '하락 후 반등 (전일 양봉)': [],
    }

    for date in all_trade_dates:
        info = day_classification.get(date)
        if not info:
            continue

        # 전일 하락인지
        if info['worst_chg'] >= 0:
            continue

        # 전전일도 하락인지 (market_data에서 prev_kospi_chg, prev_kosdaq_chg)
        m = market_data.get(info['prev_date'])
        if not m:
            continue

        prev_prev_worst = min(
            m.get('prev_kospi_chg', 0),
            m.get('prev_kosdaq_chg', 0)
        )

        # 전전전일 체크 (3일 연속)
        prev_prev_date = get_prev_market_date(all_market_dates, info['prev_date'])
        three_day = False
        if prev_prev_date and prev_prev_date in market_data:
            ppm = market_data[prev_prev_date]
            ppw = min(ppm.get('prev_kospi_chg', 0), ppm.get('prev_kosdaq_chg', 0))
            if prev_prev_worst < 0 and ppw < 0:
                three_day = True

        if three_day:
            consec_buckets['3일+ 연속 하락'].append(date)
        elif prev_prev_worst < 0:
            consec_buckets['2일 연속 하락'].append(date)
        elif prev_prev_worst >= 0:
            consec_buckets['하락 후 반등 (전일 양봉)'].append(date)
        else:
            consec_buckets['전일 하락 (1일)'].append(date)

    for label, dates in consec_buckets.items():
        day_trades = limited_df[limited_df['date'].isin(dates)] if dates else pd.DataFrame()
        s = calc_stats(day_trades if len(day_trades) > 0 else None)
        print(f'  {label:<35} {len(dates):>3}일 ', end='')
        print(f'{s["trades"]:>4}건 승률{s["winrate"]:>5.1f}% '
              f'평균{s["avg_pnl"]:>+6.2f}% 원금{s["capital_return"]:>+8.2f}%')

    # ================================================================
    # 5. 멀티버스: 전일 하락일 필터 시나리오 비교
    # ================================================================
    print_section('5. 멀티버스: 전일 하락일 필터 시나리오 비교')
    print(f'\n  기준선: {base_stats["trades"]}건, 승률 {base_stats["winrate"]:.1f}%, '
          f'원금수익률 {base_stats["capital_return"]:+.2f}%')

    scenarios = []

    # --- 5A: 완전 스킵 시나리오 ---
    print(f'\n  --- 5A. 전일 하락일 완전 스킵 ---')
    for threshold in [-0.5, -1.0, -1.5, -2.0]:
        skip_dates = set()
        for date in all_trade_dates:
            info = day_classification.get(date)
            if info and info['worst_chg'] <= threshold:
                skip_dates.add(date)
        filtered = limited_df[~limited_df['date'].isin(skip_dates)].reset_index(drop=True)
        s = calc_stats(filtered)
        label = f'전일 {threshold}%↓ → 스킵'
        print_stats_row(f'{label} ({len(skip_dates)}일)', s, base_stats)
        scenarios.append((label, s, len(skip_dates)))

    # --- 5B: 포지션 축소 시나리오 ---
    print(f'\n  --- 5B. 전일 하락일 포지션 축소 ---')
    for threshold, new_limit in [(-0.5, 3), (-0.5, 2), (-1.0, 3), (-1.0, 2), (-1.5, 2)]:
        overrides = {}
        for date in all_trade_dates:
            info = day_classification.get(date)
            if info and info['worst_chg'] <= threshold:
                overrides[date] = new_limit

        from simulate_regime_filter import apply_daily_limit_variable
        result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
        s = calc_stats(result_df)
        label = f'전일 {threshold}%↓ → {new_limit}종목'
        print_stats_row(f'{label} ({len(overrides)}일)', s, base_stats)
        scenarios.append((label, s, len(overrides)))

    # --- 5C: 손절 축소 시나리오 ---
    print(f'\n  --- 5C. 전일 하락일 손절 축소 (5%→3%) ---')
    for threshold in [-0.5, -1.0, -1.5, -2.0]:
        target_dates = set()
        for date in all_trade_dates:
            info = day_classification.get(date)
            if info and info['worst_chg'] <= threshold:
                target_dates.add(date)

        from simulate_regime_filter import apply_tighter_stop_loss
        adjusted = apply_tighter_stop_loss(limited_df, target_dates, -3.0)
        s = calc_stats(adjusted)
        label = f'전일 {threshold}%↓ → 손절3%'
        print_stats_row(f'{label} ({len(target_dates)}일)', s, base_stats)
        scenarios.append((label, s, len(target_dates)))

    # --- 5D: 복합 시나리오 (포지션축소 + 손절축소) ---
    print(f'\n  --- 5D. 전일 하락일 복합 (포지션축소 + 손절축소) ---')
    for threshold, new_limit, new_stop in [
        (-0.5, 3, -3.0), (-1.0, 3, -3.0), (-1.0, 2, -3.0),
        (-1.5, 2, -3.0), (-2.0, 0, None),
    ]:
        overrides = {}
        stop_dates = set()
        for date in all_trade_dates:
            info = day_classification.get(date)
            if info and info['worst_chg'] <= threshold:
                overrides[date] = new_limit
                if new_stop is not None:
                    stop_dates.add(date)

        result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
        if new_stop is not None:
            result_df = apply_tighter_stop_loss(result_df, stop_dates, new_stop)
        s = calc_stats(result_df)
        stop_label = f'+손절{abs(new_stop):.0f}%' if new_stop else ''
        label = f'전일 {threshold}%↓ → {new_limit}종목{stop_label}'
        print_stats_row(f'{label} ({len(overrides)}일)', s, base_stats)
        scenarios.append((label, s, len(overrides)))

    # --- 5E: 전일 하락 + 당일 갭 복합 ---
    print(f'\n  --- 5E. 전일 하락 + 당일 갭 복합 필터 ---')
    for prev_th, gap_th, new_limit, new_stop in [
        (-1.0, -0.5, 0, None),      # 서킷브레이커 현재 조건
        (-1.0, -0.5, 2, -3.0),
        (-1.0, -0.5, 3, -3.0),
        (-0.5, -0.5, 3, -3.0),
        (-1.0, None, 3, -3.0),      # 갭 무관, 전일 -1%만
        (-2.0, None, 0, None),       # 전일 -2% → 무조건 스킵
    ]:
        overrides = {}
        stop_dates = set()
        for date in all_trade_dates:
            info = day_classification.get(date)
            if not info:
                continue
            if info['worst_chg'] > prev_th:
                continue
            if gap_th is not None:
                today_gap = min(info['today_kospi_gap'], info['today_kosdaq_gap'])
                if today_gap > gap_th:
                    continue
            overrides[date] = new_limit
            if new_stop is not None:
                stop_dates.add(date)

        result_df = apply_daily_limit_variable(trades_df, max_daily, overrides)
        if new_stop is not None:
            result_df = apply_tighter_stop_loss(result_df, stop_dates, new_stop)
        s = calc_stats(result_df)
        gap_label = f'+갭{gap_th}%↓' if gap_th is not None else ''
        stop_label = f'+손절{abs(new_stop):.0f}%' if new_stop else ''
        limit_label = '스킵' if new_limit == 0 else f'{new_limit}종목'
        label = f'전일{prev_th}%↓{gap_label} → {limit_label}{stop_label}'
        print_stats_row(f'{label} ({len(overrides)}일)', s, base_stats)
        scenarios.append((label, s, len(overrides)))

    # ================================================================
    # 6. 전체 비교 요약
    # ================================================================
    print_section('6. 전체 비교 요약 (원금수익률 기준 정렬)')

    print(f'  {"시나리오":<55} {"거래":>5} {"승률":>6} {"원금수익률":>10} {"개선":>8} {"적용일":>6}')
    print('  ' + '-' * 100)
    print(f'  {"[기준선] 필터 없음 (max=" + str(max_daily) + ")":<55} '
          f'{base_stats["trades"]:>4}건 {base_stats["winrate"]:>5.1f}% '
          f'{base_stats["capital_return"]:>+9.2f}% {"":>8} {"":>6}')

    sorted_scenarios = sorted(scenarios, key=lambda x: x[1]['capital_return'], reverse=True)
    for name, s, cnt in sorted_scenarios:
        improvement = s['capital_return'] - base_stats['capital_return']
        marker = ' *' if improvement > 0 else ''
        print(f'  {name:<55} {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+7.2f}%p {cnt:>5}일{marker}')

    # ================================================================
    # 7. 하락일 상세 목록
    # ================================================================
    print_section('7. 전일 -1% 이하 하락 후 당일 거래 상세')

    decline_dates = []
    for date in all_trade_dates:
        info = day_classification.get(date)
        if info and info['worst_chg'] <= -1.0:
            decline_dates.append((date, info))

    decline_dates.sort(key=lambda x: x[1]['worst_chg'])

    print(f'\n  {"날짜":>10} {"전일KOSPI":>10} {"전일KOSDAQ":>10} {"당일갭K":>8} {"당일갭Q":>8} '
          f'{"거래":>4} {"승":>3} {"패":>3} {"평균PnL":>8} {"손절":>4} {"익절":>4}')
    print('  ' + '-' * 100)

    for date, info in decline_dates:
        day_trades = limited_df[limited_df['date'] == date]
        if len(day_trades) == 0:
            wins, losses, avg_pnl, sl, tp = 0, 0, 0, 0, 0
            n_trades = 0
        else:
            n_trades = len(day_trades)
            wins = int((day_trades['result'] == 'WIN').sum())
            losses = int((day_trades['result'] == 'LOSS').sum())
            avg_pnl = day_trades['pnl'].mean()
            sl = int((day_trades['exit_reason'] == '손절').sum())
            tp = int((day_trades['exit_reason'] == '익절').sum())

        print(f'  {date:>10} {info["kospi_chg"]:>+9.2f}% {info["kosdaq_chg"]:>+9.2f}% '
              f'{info["today_kospi_gap"]:>+7.2f}% {info["today_kosdaq_gap"]:>+7.2f}% '
              f'{n_trades:>3}건 {wins:>2}승 {losses:>2}패 {avg_pnl:>+7.2f}% '
              f'{sl:>3}건 {tp:>3}건')

    # 요약
    if decline_dates:
        total_decline_trades = limited_df[limited_df['date'].isin([d for d, _ in decline_dates])]
        s = calc_stats(total_decline_trades if len(total_decline_trades) > 0 else None)
        print(f'\n  합계: {len(decline_dates)}일, {s["trades"]}건, '
              f'승률 {s["winrate"]:.1f}%, 평균 {s["avg_pnl"]:+.2f}%')


def main():
    parser = argparse.ArgumentParser(description='전일 지수 하락 영향 멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260306', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    args = parser.parse_args()

    print('=' * 120)
    print('전일 지수 하락 영향 멀티버스 시뮬레이션')
    print(f'  기간: {args.start} ~ {args.end}, 동시보유: {args.max_daily}종목')
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

    print(f'\n[3/3] 전일 하락 영향 분석 ({len(trades_df)}건 기반)...')
    run_analysis(trades_df, market_data, args.max_daily)

    print('\nDone!')


if __name__ == '__main__':
    main()
