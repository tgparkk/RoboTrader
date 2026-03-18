"""
5일 모멘텀 필터 멀티버스 시뮬레이션

가설: 5일간 강한 상승 모멘텀을 보인 종목이 익절 확률이 더 높다.
(금 03-13 익절 종목 5일 모멘텀 +10~29% vs 월 03-16 손절 종목 +7~14%)

접근: 기본 시뮬레이션을 돌린 뒤, 각 거래의 종목이 매수 전날까지
5일간 얼마나 올랐는지(모멘텀)로 후 필터링.

Usage:
  python simulate_momentum_filter.py --start 20250224 --end 20260313
  python simulate_momentum_filter.py --start 20250901 --end 20260313 --max-daily 5
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


def load_stock_momentum_data():
    """
    종목별 5일 모멘텀 데이터 로드.

    daily_candles + minute_candles에서 종목별 일별 종가를 구하고,
    5거래일 전 종가 대비 변화율을 계산.

    Returns:
        {(stock_code, trade_date): momentum_5d_pct}
    """
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    # 1) daily_candles에서 개별종목 종가 (지수 제외)
    cur.execute('''
        SELECT stock_code, stck_bsop_date, CAST(stck_clpr AS FLOAT) as close
        FROM daily_candles
        WHERE stock_code NOT IN ('KS11', 'KQ11')
        ORDER BY stock_code, stck_bsop_date
    ''')
    daily_rows = cur.fetchall()

    # stock_code -> [(date, close), ...]
    stock_daily = defaultdict(list)
    daily_codes = set()
    for code, dt, close in daily_rows:
        stock_daily[code].append((dt, close))
        daily_codes.add(code)

    print(f'  daily_candles 종목: {len(daily_codes)}개')

    # 2) minute_candles에서 daily_candles에 없는 종목 보완
    #    각 종목/거래일의 마지막 봉 종가를 일봉 종가로 사용
    cur.execute('''
        SELECT stock_code, trade_date, close
        FROM minute_candles mc
        WHERE NOT EXISTS (
            SELECT 1 FROM daily_candles dc
            WHERE dc.stock_code = mc.stock_code
              AND dc.stock_code NOT IN ('KS11', 'KQ11')
        )
        AND idx = (
            SELECT MAX(idx) FROM minute_candles mc2
            WHERE mc2.stock_code = mc.stock_code
              AND mc2.trade_date = mc.trade_date
        )
        ORDER BY stock_code, trade_date
    ''')
    minute_rows = cur.fetchall()
    minute_codes = set()
    for code, dt, close in minute_rows:
        stock_daily[code].append((dt, float(close)))
        minute_codes.add(code)

    print(f'  minute_candles 보완 종목: {len(minute_codes)}개')
    print(f'  총 종목: {len(stock_daily)}개')

    conn.close()

    # 3) 종목별 5일 모멘텀 계산
    momentum = {}  # (stock_code, date) -> pct
    for code, series in stock_daily.items():
        series.sort(key=lambda x: x[0])
        for i in range(5, len(series)):
            dt = series[i][0]
            close_now = series[i][1]
            close_5ago = series[i - 5][1]
            if close_5ago > 0:
                mom_pct = (close_now / close_5ago - 1) * 100
                momentum[(code, dt)] = mom_pct

    print(f'  모멘텀 데이터: {len(momentum):,}건')
    return momentum


def get_prev_date_map(trades_df):
    """
    각 거래일의 전 거래일 매핑.
    모멘텀은 '매수 전날'까지의 5일 수익률이어야 look-ahead bias 없음.
    """
    dates = sorted(trades_df['date'].unique())
    prev_map = {}
    for i in range(1, len(dates)):
        prev_map[dates[i]] = dates[i - 1]
    return prev_map


def calc_stats(df):
    """거래 DataFrame으로 통계 계산"""
    if df is None or len(df) == 0:
        return {'trades': 0, 'wins': 0, 'winrate': 0, 'avg_pnl': 0,
                'capital_return': 0, 'avg_win': 0, 'avg_loss': 0,
                'tp_rate': 0, 'sl_rate': 0}
    wins = (df['result'] == 'WIN').sum()
    cap = calc_capital_returns(df)
    avg_win = df[df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
    avg_loss = df[df['result'] != 'WIN']['pnl'].mean() if len(df) - wins > 0 else 0
    tp_count = (df['exit_reason'] == '익절').sum() if 'exit_reason' in df.columns else 0
    sl_count = (df['exit_reason'] == '손절').sum() if 'exit_reason' in df.columns else 0
    return {
        'trades': len(df),
        'wins': int(wins),
        'winrate': wins / len(df) * 100,
        'avg_pnl': df['pnl'].mean(),
        'capital_return': cap['total_return_pct'],
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'tp_rate': tp_count / len(df) * 100,
        'sl_rate': sl_count / len(df) * 100,
    }


def run_multiverse(trades_df, momentum_data, max_daily=5):
    """5일 모멘텀 임계값별 필터 시나리오 비교"""

    # 기준선
    limited_df = apply_daily_limit(trades_df, max_daily)

    # 모멘텀 매칭: 매수일의 전 거래일 모멘텀 사용 (look-ahead 방지)
    # 하지만 daily_candles의 날짜는 해당 종목의 거래일이고,
    # trades에서 date는 매수 당일 → 전일 종가 기준 모멘텀을 써야 함.
    # 실제로는 "매수 당일" 시가 시점에 전일까지의 5일 모멘텀을 알 수 있으므로
    # (code, prev_date) 기준으로 매칭.
    all_dates = sorted(trades_df['date'].unique())
    prev_date_map = {}
    for i in range(1, len(all_dates)):
        prev_date_map[all_dates[i]] = all_dates[i - 1]

    # 하지만 daily_candles의 날짜와 minute_candles의 거래일이 다를 수 있음.
    # 간단히: (code, date)로 직접 매칭하되, 없으면 (code, prev_date)도 시도
    def get_momentum(code, date):
        # 먼저 전일 기준
        prev = prev_date_map.get(date)
        if prev:
            m = momentum_data.get((code, prev))
            if m is not None:
                return m
        # 당일 기준 (daily_candles에서 매수 당일 데이터가 있으면 전일까지의 모멘텀)
        m = momentum_data.get((code, date))
        if m is not None:
            return m
        return None

    # 모멘텀 컬럼 추가
    limited_df = limited_df.copy()
    limited_df['mom_5d'] = limited_df.apply(
        lambda r: get_momentum(r['stock_code'], r['date']), axis=1
    )

    matched = limited_df['mom_5d'].notna().sum()
    total = len(limited_df)
    coverage = matched / total * 100 if total > 0 else 0
    print(f'\n  모멘텀 매칭: {matched}/{total}건 ({coverage:.1f}%)')
    if coverage < 50:
        print(f'  [경고] 커버리지 {coverage:.1f}% -- 결과 해석에 주의')

    base = calc_stats(limited_df)

    # ================================================================
    # 1. 모멘텀 버킷 분석 (핵심)
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  1. 모멘텀 버킷별 성과 분석 (5일 모멘텀 구간별)')
    print('=' * 120)

    has_mom = limited_df[limited_df['mom_5d'].notna()].copy()

    buckets = [
        ('< 0%', has_mom[has_mom['mom_5d'] < 0]),
        ('0~5%', has_mom[(has_mom['mom_5d'] >= 0) & (has_mom['mom_5d'] < 5)]),
        ('5~10%', has_mom[(has_mom['mom_5d'] >= 5) & (has_mom['mom_5d'] < 10)]),
        ('10~15%', has_mom[(has_mom['mom_5d'] >= 10) & (has_mom['mom_5d'] < 15)]),
        ('15~20%', has_mom[(has_mom['mom_5d'] >= 15) & (has_mom['mom_5d'] < 20)]),
        ('20~30%', has_mom[(has_mom['mom_5d'] >= 20) & (has_mom['mom_5d'] < 30)]),
        ('>= 30%', has_mom[has_mom['mom_5d'] >= 30]),
    ]

    print(f'\n  {"구간":<10} {"거래":>6} {"승률":>7} {"평균PnL":>9} '
          f'{"익절률":>7} {"손절률":>7} {"평균승":>8} {"평균패":>8} {"모멘텀평균":>10}')
    print('  ' + '-' * 100)

    for label, bdf in buckets:
        if len(bdf) == 0:
            print(f'  {label:<10} {"0건":>6}')
            continue
        s = calc_stats(bdf)
        avg_mom = bdf['mom_5d'].mean()
        print(f'  {label:<10} {s["trades"]:>5}건 {s["winrate"]:>6.1f}% {s["avg_pnl"]:>+8.2f}% '
              f'{s["tp_rate"]:>6.1f}% {s["sl_rate"]:>6.1f}% {s["avg_win"]:>+7.2f}% '
              f'{s["avg_loss"]:>+7.2f}% {avg_mom:>+9.1f}%')

    # 전체 (매칭된 것만)
    s_all = calc_stats(has_mom)
    print(f'  {"전체":<10} {s_all["trades"]:>5}건 {s_all["winrate"]:>6.1f}% {s_all["avg_pnl"]:>+8.2f}% '
          f'{s_all["tp_rate"]:>6.1f}% {s_all["sl_rate"]:>6.1f}% {s_all["avg_win"]:>+7.2f}% '
          f'{s_all["avg_loss"]:>+7.2f}% {has_mom["mom_5d"].mean():>+9.1f}%')

    # ================================================================
    # 2. 임계값별 필터 시나리오 (모멘텀 이상만 진입)
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  2. 모멘텀 하한 필터 시나리오 (N% 이상 종목만 진입)')
    print('=' * 120)

    print(f'\n  {"시나리오":<35} {"거래":>6} {"승률":>7} {"평균PnL":>9} '
          f'{"원금수익률":>10} {"개선":>9} {"익절률":>7} {"손절률":>7}')
    print('  ' + '-' * 110)
    print(f'  {"[기준선] 필터 없음 (max=" + str(max_daily) + ")":<35} '
          f'{base["trades"]:>5}건 {base["winrate"]:>6.1f}% {base["avg_pnl"]:>+8.2f}% '
          f'{base["capital_return"]:>+9.2f}% {"":>9} '
          f'{base["tp_rate"]:>6.1f}% {base["sl_rate"]:>6.1f}%')

    scenarios_lower = []
    for threshold in [0, 5, 10, 15, 20, 25]:
        # 모멘텀 데이터 없는 거래는 통과시킴 (보수적)
        mask = (limited_df['mom_5d'].isna()) | (limited_df['mom_5d'] >= threshold)
        filtered = limited_df[mask].reset_index(drop=True)
        # 필터 후 다시 daily limit 적용
        filtered_limited = apply_daily_limit(filtered, max_daily) if len(filtered) > 0 else pd.DataFrame()
        s = calc_stats(filtered_limited)
        improvement = s['capital_return'] - base['capital_return']
        marker = ' ★' if improvement > 0 else ''
        label = f'모멘텀 >= {threshold}%'
        print(f'  {label:<35} {s["trades"]:>5}건 {s["winrate"]:>6.1f}% {s["avg_pnl"]:>+8.2f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+8.2f}%p '
              f'{s["tp_rate"]:>6.1f}% {s["sl_rate"]:>6.1f}%{marker}')
        scenarios_lower.append((label, s, threshold))

    # ================================================================
    # 3. 모멘텀 상한 필터 (과열 종목 제외)
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  3. 모멘텀 상한 필터 시나리오 (N% 이하 종목만 진입, 과열 제외)')
    print('=' * 120)

    print(f'\n  {"시나리오":<35} {"거래":>6} {"승률":>7} {"평균PnL":>9} '
          f'{"원금수익률":>10} {"개선":>9} {"익절률":>7} {"손절률":>7}')
    print('  ' + '-' * 110)
    print(f'  {"[기준선] 필터 없음":<35} '
          f'{base["trades"]:>5}건 {base["winrate"]:>6.1f}% {base["avg_pnl"]:>+8.2f}% '
          f'{base["capital_return"]:>+9.2f}% {"":>9} '
          f'{base["tp_rate"]:>6.1f}% {base["sl_rate"]:>6.1f}%')

    for threshold in [30, 25, 20, 15, 10]:
        mask = (limited_df['mom_5d'].isna()) | (limited_df['mom_5d'] <= threshold)
        filtered = limited_df[mask].reset_index(drop=True)
        filtered_limited = apply_daily_limit(filtered, max_daily) if len(filtered) > 0 else pd.DataFrame()
        s = calc_stats(filtered_limited)
        improvement = s['capital_return'] - base['capital_return']
        marker = ' ★' if improvement > 0 else ''
        label = f'모멘텀 <= {threshold}%'
        print(f'  {label:<35} {s["trades"]:>5}건 {s["winrate"]:>6.1f}% {s["avg_pnl"]:>+8.2f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+8.2f}%p '
              f'{s["tp_rate"]:>6.1f}% {s["sl_rate"]:>6.1f}%{marker}')

    # ================================================================
    # 4. 밴드 필터 (특정 구간만)
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  4. 모멘텀 밴드 필터 (특정 구간만 진입)')
    print('=' * 120)

    print(f'\n  {"시나리오":<35} {"거래":>6} {"승률":>7} {"평균PnL":>9} '
          f'{"원금수익률":>10} {"개선":>9} {"익절률":>7} {"손절률":>7}')
    print('  ' + '-' * 110)
    print(f'  {"[기준선] 필터 없음":<35} '
          f'{base["trades"]:>5}건 {base["winrate"]:>6.1f}% {base["avg_pnl"]:>+8.2f}% '
          f'{base["capital_return"]:>+9.2f}% {"":>9} '
          f'{base["tp_rate"]:>6.1f}% {base["sl_rate"]:>6.1f}%')

    bands = [
        (0, 10), (0, 15), (5, 15), (5, 20), (10, 20), (10, 25), (10, 30), (15, 30),
    ]
    for lo, hi in bands:
        mask = (limited_df['mom_5d'].isna()) | (
            (limited_df['mom_5d'] >= lo) & (limited_df['mom_5d'] <= hi)
        )
        filtered = limited_df[mask].reset_index(drop=True)
        filtered_limited = apply_daily_limit(filtered, max_daily) if len(filtered) > 0 else pd.DataFrame()
        s = calc_stats(filtered_limited)
        improvement = s['capital_return'] - base['capital_return']
        marker = ' ★' if improvement > 0 else ''
        label = f'모멘텀 {lo}~{hi}%'
        print(f'  {label:<35} {s["trades"]:>5}건 {s["winrate"]:>6.1f}% {s["avg_pnl"]:>+8.2f}% '
              f'{s["capital_return"]:>+9.2f}% {improvement:>+8.2f}%p '
              f'{s["tp_rate"]:>6.1f}% {s["sl_rate"]:>6.1f}%{marker}')

    # ================================================================
    # 5. 청산사유별 모멘텀 분석
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  5. 청산사유별 모멘텀 분포')
    print('=' * 120)

    if 'exit_reason' in has_mom.columns:
        print(f'\n  {"청산사유":<10} {"건수":>6} {"모멘텀평균":>10} {"모멘텀중앙":>10} {"모멘텀표준편차":>12}')
        print('  ' + '-' * 60)
        for reason in sorted(has_mom['exit_reason'].unique()):
            rdf = has_mom[has_mom['exit_reason'] == reason]
            print(f'  {reason:<10} {len(rdf):>5}건 {rdf["mom_5d"].mean():>+9.1f}% '
                  f'{rdf["mom_5d"].median():>+9.1f}% {rdf["mom_5d"].std():>11.1f}%')

    # ================================================================
    # 6. 월별 모멘텀 효과 (안정성 확인)
    # ================================================================
    print('\n')
    print('=' * 120)
    print('  6. 월별: 고모멘텀(>=15%) vs 저모멘텀(<15%) 비교')
    print('=' * 120)

    has_mom_copy = has_mom.copy()
    has_mom_copy['month'] = has_mom_copy['date'].str[:6]
    high_mom = has_mom_copy[has_mom_copy['mom_5d'] >= 15]
    low_mom = has_mom_copy[has_mom_copy['mom_5d'] < 15]

    print(f'\n  {"월":<8} {"고모멘텀거래":>10} {"고승률":>7} {"고평균PnL":>10} '
          f'{"저모멘텀거래":>10} {"저승률":>7} {"저평균PnL":>10}')
    print('  ' + '-' * 80)

    for month in sorted(has_mom_copy['month'].unique()):
        hm = high_mom[high_mom['month'] == month]
        lm = low_mom[low_mom['month'] == month]
        h_wr = (hm['result'] == 'WIN').sum() / len(hm) * 100 if len(hm) > 0 else 0
        l_wr = (lm['result'] == 'WIN').sum() / len(lm) * 100 if len(lm) > 0 else 0
        h_avg = hm['pnl'].mean() if len(hm) > 0 else 0
        l_avg = lm['pnl'].mean() if len(lm) > 0 else 0
        print(f'  {month[:4]}-{month[4:]:<4} {len(hm):>9}건 {h_wr:>6.1f}% {h_avg:>+9.2f}% '
              f'{len(lm):>9}건 {l_wr:>6.1f}% {l_avg:>+9.2f}%')

    # 합계
    h_wr_t = (high_mom['result'] == 'WIN').sum() / len(high_mom) * 100 if len(high_mom) > 0 else 0
    l_wr_t = (low_mom['result'] == 'WIN').sum() / len(low_mom) * 100 if len(low_mom) > 0 else 0
    h_avg_t = high_mom['pnl'].mean() if len(high_mom) > 0 else 0
    l_avg_t = low_mom['pnl'].mean() if len(low_mom) > 0 else 0
    print('  ' + '-' * 80)
    print(f'  {"합계":<8} {len(high_mom):>9}건 {h_wr_t:>6.1f}% {h_avg_t:>+9.2f}% '
          f'{len(low_mom):>9}건 {l_wr_t:>6.1f}% {l_avg_t:>+9.2f}%')


def main():
    parser = argparse.ArgumentParser(description='5일 모멘텀 필터 멀티버스 시뮬레이션')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260313', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    args = parser.parse_args()

    print('=' * 120)
    print('5일 모멘텀 필터 멀티버스 시뮬레이션')
    print(f'  가설: 5일 상승 모멘텀이 강한 종목이 익절 확률이 높다')
    print('=' * 120)

    print('\n[1/3] 모멘텀 데이터 로드...')
    momentum_data = load_stock_momentum_data()

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
    run_multiverse(trades_df, momentum_data, args.max_daily)

    print('\nDone!')


if __name__ == '__main__':
    main()
