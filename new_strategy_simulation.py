"""
새로운 매매 전략 시뮬레이션
기존 눌림목과 무관, 순수 데이터 기반

전략:
- 시가 대비 2~4% 상승 구간 진입
- 월/수/금요일만 거래 (화/목 회피)
- 10시 이후 진입
- 손절 -2.5%, 익절 +3.5%
"""

import duckdb
import pandas as pd
from datetime import datetime
from collections import defaultdict

print('=' * 80)
print('새로운 전략 시뮬레이션')
print('조건: 시가 2~4% + 월/수/금 + 10시+')
print('손절 -2.5%, 익절 +3.5%')
print('=' * 80)

conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)

# 모든 분봉 테이블
tables = conn.execute('''
    SELECT table_name FROM information_schema.tables
    WHERE table_name LIKE 'minute_%'
''').fetchall()

print(f'\n총 종목 수: {len(tables)}')

def simulate_entry(df, entry_idx, stop_loss=-2.5, take_profit=3.5):
    """진입 후 손익 시뮬레이션"""
    if entry_idx >= len(df) - 5:
        return None

    entry_price = df.iloc[entry_idx]['close']
    entry_time = df.iloc[entry_idx]['time']

    if entry_price <= 0:
        return None

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]

        # 익절 체크
        high_pnl = (row['high'] / entry_price - 1) * 100
        if high_pnl >= take_profit:
            return {
                'result': 'WIN',
                'pnl': take_profit,
                'entry_time': entry_time,
                'exit_time': row['time'],
                'entry_price': entry_price
            }

        # 손절 체크
        low_pnl = (row['low'] / entry_price - 1) * 100
        if low_pnl <= stop_loss:
            return {
                'result': 'LOSS',
                'pnl': stop_loss,
                'entry_time': entry_time,
                'exit_time': row['time'],
                'entry_price': entry_price
            }

    # 장 마감
    last_pnl = (df.iloc[-1]['close'] / entry_price - 1) * 100
    return {
        'result': 'WIN' if last_pnl > 0 else 'LOSS',
        'pnl': last_pnl,
        'entry_time': entry_time,
        'exit_time': df.iloc[-1]['time'],
        'entry_price': entry_price
    }

# 날짜별 결과 수집
daily_results = defaultdict(list)
all_trades = []

print('\n시뮬레이션 실행 중...')

for idx, t in enumerate(tables):
    if idx % 100 == 0:
        print(f'  {idx}/{len(tables)} 종목 처리 중...')

    table_name = t[0]
    stock_code = table_name.replace('minute_', '')

    try:
        # 해당 종목의 모든 거래일
        dates = conn.execute(f'''
            SELECT DISTINCT trade_date FROM {table_name}
            WHERE trade_date >= '20250901'
            ORDER BY trade_date
        ''').fetchall()

        for d in dates:
            trade_date = d[0]

            # 요일 확인 (0=월, 1=화, 2=수, 3=목, 4=금)
            try:
                dt = datetime.strptime(trade_date, '%Y%m%d')
                weekday = dt.weekday()
            except:
                continue

            # 화요일(1), 목요일(3) 회피
            if weekday in [1, 3]:
                continue

            # 분봉 데이터 로드
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

            # 해당 날짜에 이 종목에서 이미 거래했는지 체크
            traded = False

            for candle_idx in range(10, len(df) - 10):
                if traded:
                    break

                row = df.iloc[candle_idx]
                hour = int(str(row['time'])[:2])

                # 10시 이후, 12시 이전만
                if hour < 10 or hour >= 12:
                    continue

                current_price = row['close']
                pct_from_open = (current_price / day_open - 1) * 100

                # 시가 대비 2~4% 상승 조건
                if pct_from_open < 2 or pct_from_open >= 4:
                    continue

                # 진입 시뮬레이션
                result = simulate_entry(df, candle_idx)
                if result:
                    trade = {
                        'date': trade_date,
                        'stock_code': stock_code,
                        'weekday': weekday,
                        'pct_from_open': pct_from_open,
                        **result
                    }
                    all_trades.append(trade)
                    daily_results[trade_date].append(trade)
                    traded = True

    except Exception as e:
        continue

conn.close()

# 결과 분석
print(f'\n총 거래 수: {len(all_trades)}')

if len(all_trades) == 0:
    print('거래 없음')
    exit()

trades_df = pd.DataFrame(all_trades)

# 전체 통계
wins = (trades_df['result'] == 'WIN').sum()
losses = (trades_df['result'] == 'LOSS').sum()
total = len(trades_df)
winrate = wins / total * 100
total_pnl = trades_df['pnl'].sum()
avg_pnl = trades_df['pnl'].mean()

avg_win = trades_df[trades_df['result'] == 'WIN']['pnl'].mean()
avg_loss = trades_df[trades_df['result'] == 'LOSS']['pnl'].mean()
pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

print('\n' + '=' * 80)
print('전체 통계')
print('=' * 80)
print(f'총 거래: {total}건 ({wins}승 {losses}패)')
print(f'승률: {winrate:.1f}%')
print(f'총 수익률: {total_pnl:+.1f}%')
print(f'평균 수익률: {avg_pnl:+.2f}%')
print(f'평균 승리: {avg_win:+.2f}% | 평균 손실: {avg_loss:.2f}%')
print(f'손익비: {pl_ratio:.2f}:1')

# 요일별 통계
print('\n' + '=' * 80)
print('요일별 통계')
print('=' * 80)
weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
for wd in [0, 2, 4]:  # 월, 수, 금
    filtered = trades_df[trades_df['weekday'] == wd]
    if len(filtered) == 0:
        continue
    w = (filtered['result'] == 'WIN').sum()
    l = (filtered['result'] == 'LOSS').sum()
    rate = w / len(filtered) * 100
    pnl = filtered['pnl'].sum()
    print(f'{weekday_names[wd]}: {len(filtered)}거래, {w}승 {l}패, {rate:.1f}%, {pnl:+.1f}%')

# 시간대별 통계
print('\n' + '=' * 80)
print('시간대별 통계')
print('=' * 80)
trades_df['hour'] = trades_df['entry_time'].apply(lambda x: int(str(x)[:2]))
for h in [10, 11]:
    filtered = trades_df[trades_df['hour'] == h]
    if len(filtered) == 0:
        continue
    w = (filtered['result'] == 'WIN').sum()
    l = (filtered['result'] == 'LOSS').sum()
    rate = w / len(filtered) * 100
    pnl = filtered['pnl'].sum()
    print(f'{h}시: {len(filtered)}거래, {w}승 {l}패, {rate:.1f}%, {pnl:+.1f}%')

# 월별 통계
print('\n' + '=' * 80)
print('월별 통계')
print('=' * 80)
trades_df['month'] = trades_df['date'].str[:6]
for month in sorted(trades_df['month'].unique()):
    filtered = trades_df[trades_df['month'] == month]
    w = (filtered['result'] == 'WIN').sum()
    l = (filtered['result'] == 'LOSS').sum()
    rate = w / len(filtered) * 100
    pnl = filtered['pnl'].sum()
    avg = filtered['pnl'].mean()
    print(f'{month}: {len(filtered)}거래, {w}승 {l}패, {rate:.1f}%, 총 {pnl:+.1f}%, 평균 {avg:+.2f}%')

# 일별 상세
print('\n' + '=' * 80)
print('일별 상세 (최근 20일)')
print('=' * 80)
print(f"{'날짜':<12} {'거래':>4} {'승':>3} {'패':>3} {'승률':>7} {'수익':>10}")
print('-' * 50)

for date in sorted(daily_results.keys())[-20:]:
    trades = daily_results[date]
    w = sum(1 for t in trades if t['result'] == 'WIN')
    l = sum(1 for t in trades if t['result'] == 'LOSS')
    total_day = len(trades)
    rate = w / total_day * 100 if total_day > 0 else 0
    pnl = sum(t['pnl'] for t in trades)
    print(f'{date:<12} {total_day:>4} {w:>3} {l:>3} {rate:>6.1f}% {pnl:>+9.1f}%')

# 수익 예상 (100만원/건 기준)
print('\n' + '=' * 80)
print('수익 예상 (건당 100만원 기준)')
print('=' * 80)
# 데이터 기간 계산
dates = sorted(trades_df['date'].unique())
num_months = len(set(d[:6] for d in dates))
monthly_trades = total / max(num_months, 1)
monthly_profit = (total_pnl / max(num_months, 1)) * 10000

print(f'분석 기간: {dates[0]} ~ {dates[-1]} ({num_months}개월)')
print(f'월평균 거래: {monthly_trades:.0f}건')
print(f'월평균 수익: {monthly_profit:+,.0f}원')

print('\nDone!')
