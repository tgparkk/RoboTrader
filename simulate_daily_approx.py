"""
일봉 근사 시뮬레이션 (2022~2026)

분봉 없이 일봉(OHLC)만으로 price_position 전략을 근사 시뮬레이션.
pykrx로 과거 일봉을 수집하여 2022년 하락장부터 분석 가능.

근사 로직:
1. 스크리너: 거래대금(volume*avg_price) 상위 60개 → 가격/갭 필터
2. 진입 판단: 시가 대비 고가가 1~3% 이상이면 진입 기회가 있었다고 가정
   진입가 = 시가 * 1.02 (2% 지점, 1~3% 중간값)
3. 청산 판단:
   - 진입가 대비 저가 <= -5% → 손절 (-5%)
   - 진입가 대비 고가 >= +6% → 익절 (+6%)
   - 손절과 익절 둘 다 걸리면 → 보수적으로 손절 처리
   - 둘 다 안 걸리면 → 종가 청산 (종가 기준 PnL)

한계:
- 장중 시간순서를 알 수 없어 손절/익절 동시 발생 시 보수적 처리
- 변동성/모멘텀 고급 필터 미적용 (일봉으로는 불가)
- 실제보다 낙관적일 수 있음 (모든 종목이 시뮬 대상)

Usage:
  python simulate_daily_approx.py --start 20220101 --end 20260306
  python simulate_daily_approx.py --start 20220101 --end 20260306 --collect-only
"""
import psycopg2
import pandas as pd
import numpy as np
from pykrx import stock
from collections import defaultdict
from datetime import datetime, timedelta
import argparse
import time
import os
import pickle

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD


CACHE_DIR = os.path.join(os.path.dirname(__file__), '.cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def collect_stock_data(stock_codes, start_date, end_date):
    """pykrx로 종목별 일봉 수집 (캐시 활용)"""
    cache_file = os.path.join(CACHE_DIR, f'daily_ohlcv_{start_date}_{end_date}_{len(stock_codes)}.pkl')

    if os.path.exists(cache_file):
        print(f'  캐시 로드: {cache_file}')
        with open(cache_file, 'rb') as f:
            return pickle.load(f)

    all_data = {}
    failed = []
    t0 = time.time()

    for i, code in enumerate(stock_codes):
        if i % 100 == 0:
            elapsed = time.time() - t0
            print(f'  {i}/{len(stock_codes)} ({elapsed:.0f}s) 수집 중...')

        try:
            df = stock.get_market_ohlcv(start_date, end_date, code)
            if len(df) > 0:
                df.columns = ['open', 'high', 'low', 'close', 'volume', 'change_pct']
                df['amount'] = df['volume'] * (df['open'] + df['high'] + df['low'] + df['close']) / 4
                df.index = df.index.strftime('%Y%m%d')
                all_data[code] = df
        except Exception as e:
            failed.append(code)

    elapsed = time.time() - t0
    print(f'  수집 완료: {len(all_data)}/{len(stock_codes)}개 종목, {elapsed:.0f}초')
    if failed:
        print(f'  실패: {len(failed)}개')

    with open(cache_file, 'wb') as f:
        pickle.dump(all_data, f)
    print(f'  캐시 저장: {cache_file}')

    return all_data


def get_stock_codes_from_db():
    """DB에서 종목 코드 목록 가져오기"""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT stock_code FROM minute_candles WHERE stock_code NOT LIKE 'K%' ORDER BY stock_code")
    codes = [r[0] for r in cur.fetchall()]
    conn.close()
    return codes


def load_index_data():
    """DB에서 KOSPI/KOSDAQ 지수 일봉 로드"""
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
            else:
                entry['kospi_chg'] = 0
                entry['kosdaq_chg'] = 0
                entry['kospi_gap'] = 0
                entry['kosdaq_gap'] = 0
            result[dt] = entry
            prev = {k: v for k, v in d.items()}

    return result


def run_daily_simulation(all_data, start_date, end_date,
                         min_pct=1.0, max_pct=3.0,
                         stop_loss_pct=-5.0, take_profit_pct=6.0,
                         entry_price_pct=2.0,
                         screener_top_n=60,
                         screener_min_price=5000, screener_max_price=500000,
                         screener_max_gap=3.0,
                         max_daily=5):
    """
    일봉 근사 시뮬레이션

    Args:
        all_data: {stock_code: DataFrame(date index, OHLCV)}
        entry_price_pct: 진입 추정 지점 (시가 대비 %)
    """
    # 모든 거래일 파악
    all_dates = set()
    for code, df in all_data.items():
        all_dates.update(df.index)
    all_dates = sorted(d for d in all_dates if start_date <= d <= end_date)

    print(f'  거래일: {len(all_dates)}일')

    all_trades = []

    for day_idx, date in enumerate(all_dates):
        try:
            dt = datetime.strptime(date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if day_idx % 50 == 0:
            print(f'  {day_idx}/{len(all_dates)} ({date}) 거래 {len(all_trades)}건')

        # 전일 날짜
        prev_date = all_dates[day_idx - 1] if day_idx > 0 else None

        # 이 날 데이터가 있는 종목들
        day_stocks = {}
        for code, df in all_data.items():
            if date in df.index:
                row = df.loc[date]
                if row['open'] > 0 and row['volume'] > 0:
                    day_stocks[code] = row

        if not day_stocks:
            continue

        # 스크리너 시뮬: 거래대금 상위 N개
        ranked = sorted(day_stocks.items(), key=lambda x: x[1]['amount'], reverse=True)[:screener_top_n]

        candidates = []
        for code, row in ranked:
            # 우선주 제외
            if code[-1] == '5':
                continue
            # 가격 필터
            if not (screener_min_price <= row['open'] <= screener_max_price):
                continue
            # 갭 필터
            if prev_date and code in all_data:
                prev_df = all_data[code]
                if prev_date in prev_df.index:
                    prev_close = prev_df.loc[prev_date, 'close']
                    if prev_close > 0:
                        gap_pct = abs(row['open'] / prev_close - 1) * 100
                        if gap_pct > screener_max_gap:
                            continue

            candidates.append((code, row))

        # 전략 시뮬: 각 후보 종목에 대해 진입/청산 판단
        day_trades = []
        for code, row in candidates:
            opn = row['open']
            high = row['high']
            low = row['low']
            close = row['close']

            # 고가가 시가 대비 min_pct% 이상인가? (진입 기회 존재)
            high_pct = (high / opn - 1) * 100
            if high_pct < min_pct:
                continue

            # 고가가 max_pct 이내인지 확인 (너무 급등하면 진입 시점 자체가 없을 수도)
            # → 고가가 max_pct 넘어도 진입 시점(1~3%)은 있었을 것이므로 진입 가능

            # 진입가 추정
            entry_price = opn * (1 + entry_price_pct / 100)

            # 진입가가 저가보다 낮으면 실제로 해당 가격대를 지났다는 뜻
            # 진입가가 고가보다 높으면 도달 못한 것
            if entry_price > high:
                continue

            # 청산 판단
            stop_price = entry_price * (1 + stop_loss_pct / 100)
            tp_price = entry_price * (1 + take_profit_pct / 100)

            hit_stop = low <= stop_price
            hit_tp = high >= tp_price

            if hit_stop and hit_tp:
                # 둘 다 걸림 → 보수적으로 손절 처리
                pnl = stop_loss_pct
                exit_reason = '손절'
                result = 'LOSS'
            elif hit_stop:
                pnl = stop_loss_pct
                exit_reason = '손절'
                result = 'LOSS'
            elif hit_tp:
                pnl = take_profit_pct
                exit_reason = '익절'
                result = 'WIN'
            else:
                # 종가 청산
                pnl = (close / entry_price - 1) * 100
                exit_reason = '장마감'
                result = 'WIN' if pnl > 0 else 'LOSS'

            day_trades.append({
                'date': date,
                'stock_code': code,
                'weekday': weekday,
                'entry_price': entry_price,
                'pnl': pnl,
                'exit_reason': exit_reason,
                'result': result,
            })

        # 동시보유 제한 (날짜별 상위 N개만)
        if max_daily > 0 and len(day_trades) > max_daily:
            # 거래대금 상위 순서 유지 (candidates 순서)
            day_trades = day_trades[:max_daily]

        all_trades.extend(day_trades)

    print(f'  총 거래: {len(all_trades)}건')
    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


def calc_capital_returns(trades_df, initial_capital=10_000_000, buy_ratio=0.20):
    """원금 기반 누적 수익률 계산"""
    if trades_df is None or len(trades_df) == 0:
        return {'final_capital': initial_capital, 'total_return_pct': 0.0, 'monthly_returns': {}}

    capital = initial_capital
    monthly_returns = {}
    current_month = None
    month_start_capital = capital

    for date in sorted(trades_df['date'].unique()):
        month = date[:6]
        if month != current_month:
            if current_month is not None:
                monthly_returns[current_month] = (month_start_capital, capital)
            current_month = month
            month_start_capital = capital

        day_trades = trades_df[trades_df['date'] == date]
        day_start_capital = capital
        for _, trade in day_trades.iterrows():
            invest_amount = day_start_capital * buy_ratio
            profit = invest_amount * (trade['pnl'] / 100)
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


def calc_stats(df):
    if df is None or len(df) == 0:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'winrate': 0,
                'avg_pnl': 0, 'capital_return': 0, 'stop_loss_count': 0, 'take_profit_count': 0}
    wins = (df['result'] == 'WIN').sum()
    losses = (df['result'] == 'LOSS').sum()
    cap = calc_capital_returns(df)
    sl = (df['exit_reason'] == '손절').sum()
    tp = (df['exit_reason'] == '익절').sum()
    return {
        'trades': len(df),
        'wins': int(wins), 'losses': int(losses),
        'winrate': wins / len(df) * 100,
        'avg_pnl': df['pnl'].mean(),
        'capital_return': cap['total_return_pct'],
        'stop_loss_count': int(sl), 'take_profit_count': int(tp),
        'monthly_returns': cap['monthly_returns'],
    }


def analyze_prev_day_decline(trades_df, index_data):
    """전일 지수 하락 영향 분석"""
    all_trade_dates = sorted(trades_df['date'].unique())
    all_index_dates = sorted(index_data.keys())
    base_stats = calc_stats(trades_df)

    def get_prev_date(date):
        try:
            idx = all_index_dates.index(date)
            return all_index_dates[idx - 1] if idx > 0 else None
        except ValueError:
            return None

    def classify(date):
        prev = get_prev_date(date)
        if not prev or prev not in index_data:
            return None
        m = index_data[prev]
        return {
            'kospi_chg': m['kospi_chg'], 'kosdaq_chg': m['kosdaq_chg'],
            'worst_chg': min(m['kospi_chg'], m['kosdaq_chg']),
            'today_kospi_gap': index_data.get(date, {}).get('kospi_gap', 0),
            'today_kosdaq_gap': index_data.get(date, {}).get('kosdaq_gap', 0),
        }

    # 연속 하락 streak
    def get_streak(date, threshold=-1.0):
        streak = 0
        d = date
        while True:
            prev = get_prev_date(d)
            if not prev or prev not in index_data:
                break
            m = index_data[prev]
            if min(m['kospi_chg'], m['kosdaq_chg']) <= threshold:
                streak += 1
                d = prev
            else:
                break
        return streak

    # ================================================================
    # 1. 전일 하락 강도별 성과
    # ================================================================
    print('\n' + '=' * 120)
    print('  1. 전일 지수 하락 강도별 당일 전략 성과')
    print('=' * 120)

    buckets = {
        '전일 +1% 이상': [], '전일 0~+1%': [], '전일 -0.5~0%': [],
        '전일 -1~-0.5%': [], '전일 -2~-1%': [], '전일 -3~-2%': [],
        '전일 -3% 이하': [],
    }

    for date in all_trade_dates:
        info = classify(date)
        if not info:
            continue
        w = info['worst_chg']
        if w >= 1.0: buckets['전일 +1% 이상'].append(date)
        elif w >= 0: buckets['전일 0~+1%'].append(date)
        elif w >= -0.5: buckets['전일 -0.5~0%'].append(date)
        elif w >= -1.0: buckets['전일 -1~-0.5%'].append(date)
        elif w >= -2.0: buckets['전일 -2~-1%'].append(date)
        elif w >= -3.0: buckets['전일 -3~-2%'].append(date)
        else: buckets['전일 -3% 이하'].append(date)

    print(f'\n  기준선: {base_stats["trades"]}건, 승률 {base_stats["winrate"]:.1f}%, '
          f'평균 {base_stats["avg_pnl"]:+.2f}%, 원금수익률 {base_stats["capital_return"]:+.2f}%')
    print()
    print(f'  {"구간":<20} {"거래일":>5} {"거래":>5} {"승률":>6} {"평균PnL":>8} {"손절":>5} {"익절":>5}')
    print('  ' + '-' * 70)

    for label, dates in buckets.items():
        day_trades = trades_df[trades_df['date'].isin(dates)] if dates else pd.DataFrame()
        s = calc_stats(day_trades if len(day_trades) > 0 else None)
        print(f'  {label:<20} {len(dates):>4}일 {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["avg_pnl"]:>+7.2f}% {s["stop_loss_count"]:>4}건 {s["take_profit_count"]:>4}건')

    # ================================================================
    # 2. 연속 하락 분석
    # ================================================================
    print('\n' + '=' * 120)
    print('  2. 연속 하락 분석 (하락 기준: worst <= -1.0%)')
    print('=' * 120)

    streak_buckets = defaultdict(list)
    for date in all_trade_dates:
        s = get_streak(date, -1.0)
        if s == 0: streak_buckets['하락 없음'].append(date)
        elif s == 1: streak_buckets['1일 하락'].append(date)
        elif s == 2: streak_buckets['2일 연속'].append(date)
        elif s == 3: streak_buckets['3일 연속'].append(date)
        else: streak_buckets['4일+ 연속'].append(date)

    print(f'  {"구간":<20} {"거래일":>5} {"거래":>5} {"승률":>6} {"평균PnL":>8} {"손절":>5} {"익절":>5}')
    print('  ' + '-' * 70)
    for label in ['하락 없음', '1일 하락', '2일 연속', '3일 연속', '4일+ 연속']:
        dates = streak_buckets.get(label, [])
        day_trades = trades_df[trades_df['date'].isin(dates)] if dates else pd.DataFrame()
        s = calc_stats(day_trades if len(day_trades) > 0 else None)
        print(f'  {label:<20} {len(dates):>4}일 {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["avg_pnl"]:>+7.2f}% {s["stop_loss_count"]:>4}건 {s["take_profit_count"]:>4}건')

    # ================================================================
    # 3. 3일 누적 등락률별 성과
    # ================================================================
    print('\n' + '=' * 120)
    print('  3. 최근 3거래일 누적 등락률별 성과')
    print('=' * 120)

    cumul_buckets = defaultdict(list)
    for date in all_trade_dates:
        cumul = 0
        d = date
        for i in range(3):
            prev = get_prev_date(d)
            if not prev or prev not in index_data:
                break
            m = index_data[prev]
            cumul += min(m['kospi_chg'], m['kosdaq_chg'])
            d = prev

        if cumul >= 0: cumul_buckets['3일 누적 0%+'].append(date)
        elif cumul >= -2: cumul_buckets['3일 누적 -2~0%'].append(date)
        elif cumul >= -5: cumul_buckets['3일 누적 -5~-2%'].append(date)
        elif cumul >= -10: cumul_buckets['3일 누적 -10~-5%'].append(date)
        else: cumul_buckets['3일 누적 -10%↓'].append(date)

    print(f'  {"구간":<25} {"거래일":>5} {"거래":>5} {"승률":>6} {"평균PnL":>8}')
    print('  ' + '-' * 55)
    for label in ['3일 누적 0%+', '3일 누적 -2~0%', '3일 누적 -5~-2%', '3일 누적 -10~-5%', '3일 누적 -10%↓']:
        dates = cumul_buckets.get(label, [])
        day_trades = trades_df[trades_df['date'].isin(dates)] if dates else pd.DataFrame()
        s = calc_stats(day_trades if len(day_trades) > 0 else None)
        print(f'  {label:<25} {len(dates):>4}일 {s["trades"]:>4}건 {s["winrate"]:>5.1f}% {s["avg_pnl"]:>+7.2f}%')

    # ================================================================
    # 4. 월별 성과 + 시장 상황
    # ================================================================
    print('\n' + '=' * 120)
    print('  4. 월별 성과')
    print('=' * 120)

    trades_df_copy = trades_df.copy()
    trades_df_copy['month'] = trades_df_copy['date'].str[:6]
    months = sorted(trades_df_copy['month'].unique())

    print(f'  {"월":>8} {"거래":>5} {"승률":>6} {"평균PnL":>8} {"원금수익률":>10} {"손절":>5} {"익절":>5}')
    print('  ' + '-' * 65)

    for month in months:
        mf = trades_df_copy[trades_df_copy['month'] == month]
        s = calc_stats(mf)
        mr = s.get('monthly_returns', {})
        cap_m = list(mr.values())[0] if mr else 0
        print(f'  {month[:4]}-{month[4:]:>2} {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["avg_pnl"]:>+7.2f}% {cap_m:>+9.2f}% '
              f'{s["stop_loss_count"]:>4}건 {s["take_profit_count"]:>4}건')

    # 연도별 요약
    print('\n  --- 연도별 요약 ---')
    trades_df_copy['year'] = trades_df_copy['date'].str[:4]
    for year in sorted(trades_df_copy['year'].unique()):
        yf = trades_df_copy[trades_df_copy['year'] == year]
        s = calc_stats(yf)
        print(f'  {year}: {s["trades"]}건, 승률 {s["winrate"]:.1f}%, 평균 {s["avg_pnl"]:+.2f}%, '
              f'원금수익률 {s["capital_return"]:+.2f}%')

    # ================================================================
    # 5. 하락장 구간 집중 (2022년)
    # ================================================================
    print('\n' + '=' * 120)
    print('  5. 2022년 하락장 집중 분석')
    print('=' * 120)

    trades_2022 = trades_df[trades_df['date'].str.startswith('2022')]
    if len(trades_2022) > 0:
        # 2022년 내 전일 하락 강도별
        buckets_2022 = {'정상 (>-1%)': [], '전일 -1%↓': [], '전일 -2%↓': [], '전일 -3%↓': []}
        for date in sorted(trades_2022['date'].unique()):
            info = classify(date)
            if not info:
                continue
            w = info['worst_chg']
            if w <= -3: buckets_2022['전일 -3%↓'].append(date)
            elif w <= -2: buckets_2022['전일 -2%↓'].append(date)
            elif w <= -1: buckets_2022['전일 -1%↓'].append(date)
            else: buckets_2022['정상 (>-1%)'].append(date)

        for label, dates in buckets_2022.items():
            day_trades = trades_2022[trades_2022['date'].isin(dates)] if dates else pd.DataFrame()
            s = calc_stats(day_trades if len(day_trades) > 0 else None)
            print(f'  [2022] {label:<20} {len(dates):>3}일 {s["trades"]:>4}건 '
                  f'승률{s["winrate"]:>5.1f}% 평균{s["avg_pnl"]:>+6.2f}%')

        # 연속 하락 분석 (2022년)
        print()
        streak_2022 = defaultdict(list)
        for date in sorted(trades_2022['date'].unique()):
            s = get_streak(date, -1.0)
            if s == 0: streak_2022['하락 없음'].append(date)
            elif s == 1: streak_2022['1일'].append(date)
            elif s == 2: streak_2022['2일 연속'].append(date)
            else: streak_2022['3일+ 연속'].append(date)

        for label in ['하락 없음', '1일', '2일 연속', '3일+ 연속']:
            dates = streak_2022.get(label, [])
            day_trades = trades_2022[trades_2022['date'].isin(dates)] if dates else pd.DataFrame()
            s = calc_stats(day_trades if len(day_trades) > 0 else None)
            print(f'  [2022 연속] {label:<15} {len(dates):>3}일 {s["trades"]:>4}건 '
                  f'승률{s["winrate"]:>5.1f}% 평균{s["avg_pnl"]:>+6.2f}%')


def main():
    parser = argparse.ArgumentParser(description='일봉 근사 시뮬레이션 (2022~2026)')
    parser.add_argument('--start', default='20220101', help='시작일')
    parser.add_argument('--end', default='20260306', help='종료일')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 제한')
    parser.add_argument('--collect-only', action='store_true', help='데이터 수집만')
    args = parser.parse_args()

    print('=' * 120)
    print('일봉 근사 시뮬레이션')
    print(f'  기간: {args.start} ~ {args.end}, 동시보유: {args.max_daily}종목')
    print('  주의: 일봉 OHLC 기반 근사 (분봉 시뮬 대비 정확도 낮음)')
    print('=' * 120)

    # 1. 종목 코드 가져오기
    print('\n[1/4] 종목 코드 로드...')
    stock_codes = get_stock_codes_from_db()
    print(f'  DB 종목: {len(stock_codes)}개')

    # 2. 일봉 수집
    print('\n[2/4] 일봉 데이터 수집 (pykrx)...')
    all_data = collect_stock_data(stock_codes, args.start, args.end)

    if args.collect_only:
        print('\n수집 완료. --collect-only 모드.')
        return

    # 3. 시뮬레이션
    print('\n[3/4] 일봉 근사 시뮬레이션...')
    trades_df = run_daily_simulation(all_data, args.start, args.end, max_daily=args.max_daily)

    if trades_df is None or len(trades_df) == 0:
        print('거래 없음. 종료.')
        return

    # 전체 통계
    s = calc_stats(trades_df)
    print(f'\n  전체: {s["trades"]}건, 승률 {s["winrate"]:.1f}%, '
          f'평균 {s["avg_pnl"]:+.2f}%, 원금수익률 {s["capital_return"]:+.2f}%')
    print(f'  손절 {s["stop_loss_count"]}건, 익절 {s["take_profit_count"]}건, '
          f'장마감 {s["trades"] - s["stop_loss_count"] - s["take_profit_count"]}건')

    # 4. 전일 하락 영향 분석
    print('\n[4/4] 전일 하락 영향 분석...')
    index_data = load_index_data()
    analyze_prev_day_decline(trades_df, index_data)

    print('\nDone!')


if __name__ == '__main__':
    main()
