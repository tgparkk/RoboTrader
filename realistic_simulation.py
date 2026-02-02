"""
현실적 시뮬레이션 - 가격 위치 기반 전략
자본금, 수수료, 동시보유 제한 반영
"""

import duckdb
import pandas as pd
from datetime import datetime
from collections import defaultdict

print('=' * 75)
print('현실적 시뮬레이션 - 가격 위치 기반 전략')
print('=' * 75)
print('설정:')
print('  - 자본금: 1,000만원')
print('  - 건당 투자: 200만원 (20%)')
print('  - 최대 동시보유: 5종목')
print('  - 손절: -2.5%, 익절: +3.5%')
print('  - 수수료: 0.25% (매수+매도 합산)')
print('=' * 75)

conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)

tables = conn.execute('''
    SELECT table_name FROM information_schema.tables
    WHERE table_name LIKE 'minute_%'
''').fetchall()

# 일별로 모든 신호 수집
daily_signals = defaultdict(list)

for t in tables:
    table_name = t[0]
    stock_code = table_name.replace('minute_', '')

    try:
        dates = conn.execute(f'''
            SELECT DISTINCT trade_date FROM {table_name}
            WHERE trade_date >= '20250901'
            ORDER BY trade_date
        ''').fetchall()

        for d in dates:
            trade_date = d[0]

            try:
                dt = datetime.strptime(trade_date, '%Y%m%d')
                weekday = dt.weekday()
            except:
                continue

            # 화/목 회피
            if weekday in [1, 3]:
                continue

            df = conn.execute(f'''
                SELECT * FROM {table_name}
                WHERE trade_date = '{trade_date}'
                ORDER BY idx
            ''').fetchdf()

            if len(df) < 50:
                continue

            day_open = df.iloc[0]['open']
            if day_open <= 0:
                continue

            for idx in range(10, len(df) - 10):
                row = df.iloc[idx]
                hour = int(str(row['time'])[:2])

                if hour < 10 or hour >= 12:
                    continue

                entry_price = row['close']
                pct = (entry_price / day_open - 1) * 100

                if 2 <= pct < 4:
                    # 거래 시뮬레이션
                    result = None
                    for i in range(idx + 1, len(df)):
                        r = df.iloc[i]
                        high_pnl = (r['high'] / entry_price - 1) * 100
                        low_pnl = (r['low'] / entry_price - 1) * 100

                        if high_pnl >= 3.5:
                            result = {'pnl': 3.5, 'result': 'WIN', 'reason': '익절'}
                            break
                        if low_pnl <= -2.5:
                            result = {'pnl': -2.5, 'result': 'LOSS', 'reason': '손절'}
                            break

                    if result is None:
                        last_pnl = (df.iloc[-1]['close'] / entry_price - 1) * 100
                        result = {'pnl': last_pnl, 'result': 'WIN' if last_pnl > 0 else 'LOSS', 'reason': '장마감'}

                    daily_signals[trade_date].append({
                        'stock_code': stock_code,
                        'entry_time': row['time'],
                        'pct_from_open': pct,
                        **result
                    })
                    break

    except:
        continue

conn.close()

# 현실적 시뮬레이션
CAPITAL = 10_000_000
PER_TRADE = 2_000_000
MAX_POSITIONS = 5
FEE_RATE = 0.0025  # 0.25% (매수+매도)

results = []
monthly_stats = defaultdict(lambda: {
    'trades': 0, 'wins': 0, 'losses': 0,
    'gross_pnl': 0, 'fees': 0, 'net_pnl': 0
})

for date in sorted(daily_signals.keys()):
    signals = daily_signals[date]
    signals.sort(key=lambda x: x['entry_time'])  # 시간순

    month = date[:6]

    # 최대 5종목만 진입
    for s in signals[:MAX_POSITIONS]:
        gross_profit = PER_TRADE * (s['pnl'] / 100)
        fee = PER_TRADE * FEE_RATE
        net_profit = gross_profit - fee

        results.append({
            'date': date,
            'month': month,
            **s,
            'gross_profit': gross_profit,
            'fee': fee,
            'net_profit': net_profit
        })

        monthly_stats[month]['trades'] += 1
        monthly_stats[month]['gross_pnl'] += gross_profit
        monthly_stats[month]['fees'] += fee
        monthly_stats[month]['net_pnl'] += net_profit
        if s['result'] == 'WIN':
            monthly_stats[month]['wins'] += 1
        else:
            monthly_stats[month]['losses'] += 1

df = pd.DataFrame(results)

# 전체 통계
total_trades = len(df)
total_wins = (df['result'] == 'WIN').sum()
total_losses = (df['result'] == 'LOSS').sum()
winrate = total_wins / total_trades * 100
total_gross = df['gross_profit'].sum()
total_fees = df['fee'].sum()
total_net = df['net_profit'].sum()

print(f'\n분석 기간: {df["date"].min()} ~ {df["date"].max()}')
print(f'총 거래일: {len(daily_signals)}일')

print('\n' + '=' * 75)
print('전체 성과')
print('=' * 75)
print(f'총 거래: {total_trades}건 ({total_wins}승 {total_losses}패)')
print(f'승률: {winrate:.1f}%')
print(f'')
print(f'총 수익(세전): {total_gross:+,.0f}원')
print(f'총 수수료: {total_fees:,.0f}원')
print(f'순 수익: {total_net:+,.0f}원')

# 월별 상세
print('\n' + '=' * 75)
print('월별 상세')
print('=' * 75)
header = f"{'월':<8} {'거래':>5} {'승':>4} {'패':>4} {'승률':>7} {'세전수익':>12} {'수수료':>10} {'순수익':>12}"
print(header)
print('-' * 75)

months = sorted(monthly_stats.keys())
for m in months:
    s = monthly_stats[m]
    wr = s['wins'] / s['trades'] * 100 if s['trades'] > 0 else 0
    print(f"{m:<8} {s['trades']:>5} {s['wins']:>4} {s['losses']:>4} {wr:>6.1f}% {s['gross_pnl']:>+11,.0f}원 {s['fees']:>9,.0f}원 {s['net_pnl']:>+11,.0f}원")

print('-' * 75)
avg_trades = total_trades / len(months)
avg_gross = total_gross / len(months)
avg_fees = total_fees / len(months)
avg_net = total_net / len(months)
print(f"{'월평균':<8} {avg_trades:>5.0f} {'-':>4} {'-':>4} {winrate:>6.1f}% {avg_gross:>+11,.0f}원 {avg_fees:>9,.0f}원 {avg_net:>+11,.0f}원")

# 일별 상세 (최근 20일)
print('\n' + '=' * 75)
print('일별 상세 (최근 20일)')
print('=' * 75)
print(f"{'날짜':<12} {'거래':>4} {'승':>3} {'패':>3} {'승률':>7} {'순수익':>12}")
print('-' * 50)

daily_summary = df.groupby('date').agg({
    'result': lambda x: (x == 'WIN').sum(),
    'net_profit': 'sum'
}).reset_index()
daily_summary['total'] = df.groupby('date').size().values
daily_summary.columns = ['date', 'wins', 'net_profit', 'total']
daily_summary['losses'] = daily_summary['total'] - daily_summary['wins']

for _, row in daily_summary.tail(20).iterrows():
    wr = row['wins'] / row['total'] * 100
    print(f"{row['date']:<12} {row['total']:>4} {row['wins']:>3} {row['losses']:>3} {wr:>6.1f}% {row['net_profit']:>+11,.0f}원")

# 최종 요약
print('\n' + '=' * 75)
print('최종 요약')
print('=' * 75)
print('')
print(f'  자본금 1,000만원 기준')
print(f'  ' + '-' * 40)
print(f'  월평균 거래: {avg_trades:.0f}건')
print(f'  월평균 승률: {winrate:.1f}%')
print(f'  월평균 순수익: {avg_net:+,.0f}원')
print(f'  월 수익률: {avg_net/CAPITAL*100:+.1f}%')
print(f'  ' + '-' * 40)
print(f'  5개월 누적 순수익: {total_net:+,.0f}원')
print(f'  누적 수익률: {total_net/CAPITAL*100:+.1f}%')
print('')

# 승/패 분석
print('\n' + '=' * 75)
print('승패 분석')
print('=' * 75)
win_df = df[df['result'] == 'WIN']
loss_df = df[df['result'] == 'LOSS']
print(f'평균 수익 (WIN): {win_df["gross_profit"].mean():+,.0f}원')
print(f'평균 손실 (LOSS): {loss_df["gross_profit"].mean():+,.0f}원')
print(f'손익비: {abs(win_df["gross_profit"].mean() / loss_df["gross_profit"].mean()):.2f}:1')

# 청산 사유별
print('\n청산 사유별:')
for reason in df['reason'].unique():
    r_df = df[df['reason'] == reason]
    r_wins = (r_df['result'] == 'WIN').sum()
    r_total = len(r_df)
    r_net = r_df['net_profit'].sum()
    print(f'  {reason}: {r_total}건 ({r_wins}승), 순수익 {r_net:+,.0f}원')

print('\n' + '=' * 75)
print('기존 눌림목 전략 대비')
print('=' * 75)
print('기존: 승률 40%, 4개월 -25만원 손실')
print(f'신규: 승률 {winrate:.1f}%, 5개월 {total_net:+,.0f}원 수익')
print('')
print('Done!')
