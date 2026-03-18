"""
급락일 매수 중단 필터 백테스트

KOSPI/KOSDAQ 전일 대비 등락률 기준으로
특정 임계값 이하 날에 매수를 중단했을 때 성과 변화를 분석
"""
import sys
import psycopg2
import pandas as pd
from collections import defaultdict
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from simulate_with_screener import run_simulation, apply_daily_limit, calc_capital_returns


def load_market_changes():
    """KOSPI/KOSDAQ 전일 대비 등락률 계산"""
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
    changes = {}  # date -> {kospi_chg, kosdaq_chg, kospi_gap, kosdaq_gap}
    for dt in dates:
        d = data[dt]
        if 'KS11' in d and 'KQ11' in d and 'KS11' in prev and 'KQ11' in prev:
            changes[dt] = {
                'kospi_chg': (d['KS11']['close'] / prev['KS11']['close'] - 1) * 100,
                'kosdaq_chg': (d['KQ11']['close'] / prev['KQ11']['close'] - 1) * 100,
                'kospi_gap': (d['KS11']['open'] / prev['KS11']['close'] - 1) * 100,
                'kosdaq_gap': (d['KQ11']['open'] / prev['KQ11']['close'] - 1) * 100,
            }
        prev = {k: v for k, v in d.items()}
    return changes


def calc_stats(df):
    """trades DataFrame으로 통계 계산"""
    if df is None or len(df) == 0:
        return {'trades': 0, 'wins': 0, 'winrate': 0, 'avg_pnl': 0, 'capital_return': 0}
    wins = (df['result'] == 'WIN').sum()
    cap = calc_capital_returns(df)
    return {
        'trades': len(df),
        'wins': int(wins),
        'winrate': wins / len(df) * 100,
        'avg_pnl': df['pnl'].mean(),
        'capital_return': cap['total_return_pct'],
    }


def print_filter_table(label, thresholds, limited_df, market, date_filter_fn):
    """필터 분석 테이블 출력"""
    base = calc_stats(limited_df)
    print(f'\n{"기준":>12} | {"거래":>5} | {"승률":>6} | {"원금수익률":>9} | {"평균":>7} | {"제외일":>5} | {"제외거래":>8}')
    print('-' * 80)
    print(f'{"필터 없음":>12} | {base["trades"]:>4}건 | {base["winrate"]:>5.1f}% | '
          f'{base["capital_return"]:>+8.1f}% | {base["avg_pnl"]:>+6.2f}% | {"":>5} | {"":>8}')

    for th in thresholds:
        crash_dates = set(d for d, v in market.items() if date_filter_fn(v, th))
        filtered = limited_df[~limited_df['date'].isin(crash_dates)]
        removed = limited_df[limited_df['date'].isin(crash_dates)]
        s = calc_stats(filtered)
        r = calc_stats(removed)
        print(f'{label+str(th)+"%":>12} | {s["trades"]:>4}건 | {s["winrate"]:>5.1f}% | '
              f'{s["capital_return"]:>+8.1f}% | {s["avg_pnl"]:>+6.2f}% | '
              f'{len(crash_dates):>4}일 | {r["trades"]:>4}건(평균{r["avg_pnl"]:>+.2f}%)')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='급락일 매수 중단 필터 백테스트')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260303', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    args = parser.parse_args()

    # 1. 시장 데이터 로드
    print('=' * 80)
    print('급락일 매수 중단 필터 백테스트')
    print('=' * 80)
    market = load_market_changes()
    print(f'시장 데이터: {len(market)}일')

    # 2. 전체 시뮬레이션 1회 실행
    print('\n[1/2] 전체 시뮬레이션 실행...')
    trades_df = run_simulation(
        start_date=args.start,
        end_date=args.end,
        max_daily=0,  # 무제한으로 전체 거래 수집
        verbose=False,
    )

    if trades_df is None or len(trades_df) == 0:
        print('거래 없음. 종료.')
        return

    # 동시보유 제한 적용
    limited_df = apply_daily_limit(trades_df, args.max_daily)
    print(f'\n전체 거래: {len(trades_df)}건 → 동시보유 {args.max_daily}종목 제한: {len(limited_df)}건')

    # ================================================================
    # 방법 1: 전일 종가 대비 당일 종가 기준 (사후 분석, 참고용)
    # ================================================================
    print('\n')
    print('#' * 80)
    print('#  분석 1: 전일 종가 대비 당일 종가 기준 (사후 분석)')
    print('#  → 당일 끝나봐야 아는 값. 실시간 적용 불가. 참고용.')
    print('#' * 80)
    print_filter_table(
        '종가 >', [-1.0, -1.5, -2.0, -2.5, -3.0, -4.0, -5.0],
        limited_df, market,
        lambda v, th: v['kospi_chg'] <= th or v['kosdaq_chg'] <= th,
    )

    # ================================================================
    # 방법 2: 시가 갭 기준 (실시간 적용 가능!)
    # ================================================================
    print('\n')
    print('#' * 80)
    print('#  분석 2: 시가 갭 기준 (전일 종가 대비 당일 시가)')
    print('#  → 09:00 장 시작 직후 알 수 있는 값. 실시간 적용 가능!')
    print('#' * 80)
    print_filter_table(
        '갭 >', [-0.5, -1.0, -1.5, -2.0, -2.5, -3.0],
        limited_df, market,
        lambda v, th: v['kospi_gap'] <= th or v['kosdaq_gap'] <= th,
    )

    # ================================================================
    # 방법 3: 장중 실시간 지수 하락 기준 (가장 현실적)
    # ================================================================
    print('\n')
    print('#' * 80)
    print('#  분석 3: 당일 시가 대비 종가 하락 기준')
    print('#  → 장중에 지수가 시가 대비 N% 하락하면 매수 중단하는 시나리오')
    print('#  → 실제로는 장중 실시간 감지이나, 여기서는 종가 기준으로 근사')
    print('#' * 80)

    # 시가 대비 종가 등락 계산
    conn2 = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur2 = conn2.cursor()
    cur2.execute('''
        SELECT stock_code, stck_bsop_date,
               CAST(stck_oprc AS FLOAT) as open,
               CAST(stck_clpr AS FLOAT) as close
        FROM daily_candles
        WHERE stock_code IN ('KS11', 'KQ11')
        ORDER BY stck_bsop_date
    ''')
    intra_changes = {}
    for code, dt, opn, cls in cur2.fetchall():
        if dt not in intra_changes:
            intra_changes[dt] = {}
        intra_changes[dt][code] = (cls / opn - 1) * 100 if opn > 0 else 0
    conn2.close()

    print_filter_table(
        '장중 >', [-1.0, -1.5, -2.0, -2.5, -3.0, -4.0],
        limited_df, intra_changes,
        lambda v, th: v.get('KS11', 0) <= th or v.get('KQ11', 0) <= th,
    )

    # ================================================================
    # 제외된 날짜 상세
    # ================================================================
    print('\n')
    print('#' * 80)
    print('#  급락일 상세: 갭 -1.5% 이하 날짜의 거래 내역')
    print('#' * 80)
    crash_dates_detail = sorted(d for d, v in market.items()
                                if v['kospi_gap'] <= -1.5 or v['kosdaq_gap'] <= -1.5)
    for dt in crash_dates_detail:
        v = market[dt]
        day_trades = limited_df[limited_df['date'] == dt]
        if len(day_trades) > 0:
            wins = (day_trades['result'] == 'WIN').sum()
            losses = len(day_trades) - wins
            avg = day_trades['pnl'].mean()
            print(f'  {dt} | KOSPI갭{v["kospi_gap"]:>+5.1f}% 종가{v["kospi_chg"]:>+5.1f}% | '
                  f'KOSDAQ갭{v["kosdaq_gap"]:>+5.1f}% 종가{v["kosdaq_chg"]:>+5.1f}% | '
                  f'{wins}승{losses}패 | 평균{avg:>+5.2f}%')
        else:
            print(f'  {dt} | KOSPI갭{v["kospi_gap"]:>+5.1f}% 종가{v["kospi_chg"]:>+5.1f}% | '
                  f'KOSDAQ갭{v["kosdaq_gap"]:>+5.1f}% 종가{v["kosdaq_chg"]:>+5.1f}% | '
                  f'거래 없음')


if __name__ == '__main__':
    main()
