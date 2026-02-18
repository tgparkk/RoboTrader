"""Deep Pattern Analysis - More Conditions"""

import duckdb
import pandas as pd
import numpy as np
from datetime import datetime

print('=' * 80)
print('Deep Pattern Analysis')
print('=' * 80)

conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)

tables = conn.execute('''
    SELECT table_name FROM information_schema.tables
    WHERE table_name LIKE 'minute_%'
''').fetchall()

def simulate_entry(df, entry_idx, stop_loss=-2.5, take_profit=3.5):
    if entry_idx >= len(df) - 5:
        return None
    entry_price = df.iloc[entry_idx]['close']
    if entry_price <= 0:
        return None

    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        high_pnl = (row['high'] / entry_price - 1) * 100
        if high_pnl >= take_profit:
            return {'result': 'WIN', 'pnl': take_profit}
        low_pnl = (row['low'] / entry_price - 1) * 100
        if low_pnl <= stop_loss:
            return {'result': 'LOSS', 'pnl': stop_loss}

    last_pnl = (df.iloc[-1]['close'] / entry_price - 1) * 100
    return {'result': 'WIN' if last_pnl > 0 else 'LOSS', 'pnl': last_pnl}

all_trades = []
print(f'Processing {len(tables)} tables...')

for idx, t in enumerate(tables):
    if idx % 100 == 0:
        print(f'  {idx}/{len(tables)}...')

    table_name = t[0]
    stock_code = table_name.replace('minute_', '')

    try:
        dates = conn.execute(f'''
            SELECT DISTINCT trade_date FROM {table_name}
        ''').fetchall()

        for d in dates:
            trade_date = d[0]

            # 요일 계산
            try:
                dt = datetime.strptime(trade_date, '%Y%m%d')
                weekday = dt.weekday()  # 0=Mon, 1=Tue, ...
            except:
                weekday = -1

            df = conn.execute(f'''
                SELECT * FROM {table_name}
                WHERE trade_date = '{trade_date}'
                ORDER BY idx
            ''').fetchdf()

            if len(df) < 60:
                continue

            day_open = df.iloc[0]['open']
            if day_open <= 0:
                continue

            traded = False
            for idx2 in range(15, len(df) - 15):
                if traded:
                    break

                row = df.iloc[idx2]
                hour = int(str(row['time'])[:2])
                minute = int(str(row['time'])[2:4])

                if hour >= 12:
                    continue

                current_price = row['close']
                pct_from_open = (current_price / day_open - 1) * 100

                # 당일 고/저
                day_high = df.iloc[:idx2+1]['high'].max()
                day_low = df.iloc[:idx2+1]['low'].min()
                day_position = (current_price - day_low) / (day_high - day_low) if day_high > day_low else 0.5

                # 캔들 특성
                is_bullish = 1 if row['close'] > row['open'] else 0

                # 거래량
                current_volume = row['volume']
                day_max_volume = df.iloc[:idx2+1]['volume'].max()
                volume_ratio = current_volume / day_max_volume if day_max_volume > 0 else 0

                prev_volume = df.iloc[idx2-1]['volume']
                volume_change = current_volume / prev_volume if prev_volume > 0 else 1

                # 이동평균
                ma5 = df.iloc[max(0,idx2-5):idx2]['close'].mean()
                ma10 = df.iloc[max(0,idx2-10):idx2]['close'].mean()
                ma20 = df.iloc[max(0,idx2-20):idx2]['close'].mean() if idx2 >= 20 else ma10

                above_ma5 = 1 if current_price > ma5 else 0
                above_ma10 = 1 if current_price > ma10 else 0
                above_ma20 = 1 if current_price > ma20 else 0

                # MA 배열 (상승 정배열)
                ma_aligned = 1 if ma5 > ma10 > ma20 else 0

                # 연속 양봉
                bullish_streak = 0
                for i in range(idx2, max(0, idx2-5), -1):
                    if df.iloc[i]['close'] > df.iloc[i]['open']:
                        bullish_streak += 1
                    else:
                        break

                # 가격 모멘텀
                prev_close = df.iloc[idx2-1]['close']
                pct_change = (current_price / prev_close - 1) * 100 if prev_close > 0 else 0

                # 3봉 모멘텀
                close_3ago = df.iloc[idx2-3]['close'] if idx2 >= 3 else current_price
                pct_change_3 = (current_price / close_3ago - 1) * 100 if close_3ago > 0 else 0

                if hour >= 10:
                    result = simulate_entry(df, idx2)
                    if result:
                        all_trades.append({
                            'hour': hour,
                            'minute': minute,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            'day_position': day_position,
                            'is_bullish': is_bullish,
                            'volume_ratio': volume_ratio,
                            'volume_change': volume_change,
                            'above_ma5': above_ma5,
                            'above_ma10': above_ma10,
                            'above_ma20': above_ma20,
                            'ma_aligned': ma_aligned,
                            'bullish_streak': bullish_streak,
                            'pct_change': pct_change,
                            'pct_change_3': pct_change_3,
                            **result
                        })
                        traded = True
    except:
        continue

print(f'\nTotal trades: {len(all_trades)}')
trades_df = pd.DataFrame(all_trades)

# 분석 함수
def analyze(name, filtered):
    if len(filtered) < 30:
        return None
    wins = (filtered['result'] == 'WIN').sum()
    total = len(filtered)
    winrate = wins / total * 100
    total_pnl = filtered['pnl'].sum()
    avg_pnl = filtered['pnl'].mean()
    return {'name': name, 'trades': total, 'wins': wins, 'winrate': winrate, 'total_pnl': total_pnl, 'avg_pnl': avg_pnl}

results = []

# 1. 시간대별
print('\n' + '=' * 80)
print('1. TIME ANALYSIS')
print('=' * 80)

for h in [9, 10, 11]:
    r = analyze(f'Hour {h}', trades_df[trades_df['hour'] == h])
    if r: results.append(r)

for m_start in [0, 15, 30, 45]:
    for h in [10, 11]:
        r = analyze(f'{h}:{m_start:02d}-{m_start+14:02d}',
                   trades_df[(trades_df['hour'] == h) & (trades_df['minute'] >= m_start) & (trades_df['minute'] < m_start+15)])
        if r: results.append(r)

# 2. 요일별
print('\n' + '=' * 80)
print('2. WEEKDAY ANALYSIS')
print('=' * 80)

weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
for wd in range(5):
    r = analyze(f'Weekday {weekday_names[wd]}', trades_df[trades_df['weekday'] == wd])
    if r: results.append(r)

# 3. 시가 대비 상승률
print('\n' + '=' * 80)
print('3. PCT FROM OPEN ANALYSIS')
print('=' * 80)

for low, high in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 7), (7, 10), (10, 15), (15, 100)]:
    r = analyze(f'pct {low}-{high}%', trades_df[(trades_df['pct_from_open'] >= low) & (trades_df['pct_from_open'] < high)])
    if r: results.append(r)

# 4. 당일 위치
print('\n' + '=' * 80)
print('4. DAY POSITION ANALYSIS')
print('=' * 80)

for low, high in [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]:
    r = analyze(f'day_pos {low}-{high}', trades_df[(trades_df['day_position'] >= low) & (trades_df['day_position'] < high)])
    if r: results.append(r)

# 5. 거래량
print('\n' + '=' * 80)
print('5. VOLUME ANALYSIS')
print('=' * 80)

for thresh in [0.3, 0.5, 0.7, 0.9]:
    r = analyze(f'vol_ratio > {thresh}', trades_df[trades_df['volume_ratio'] > thresh])
    if r: results.append(r)

for thresh in [1.5, 2.0, 3.0]:
    r = analyze(f'vol_change > {thresh}', trades_df[trades_df['volume_change'] > thresh])
    if r: results.append(r)

# 6. 이동평균
print('\n' + '=' * 80)
print('6. MOVING AVERAGE ANALYSIS')
print('=' * 80)

r = analyze('above_ma5', trades_df[trades_df['above_ma5'] == 1])
if r: results.append(r)
r = analyze('below_ma5', trades_df[trades_df['above_ma5'] == 0])
if r: results.append(r)
r = analyze('above_ma10', trades_df[trades_df['above_ma10'] == 1])
if r: results.append(r)
r = analyze('above_ma20', trades_df[trades_df['above_ma20'] == 1])
if r: results.append(r)
r = analyze('ma_aligned (5>10>20)', trades_df[trades_df['ma_aligned'] == 1])
if r: results.append(r)

# 7. 캔들 패턴
print('\n' + '=' * 80)
print('7. CANDLE PATTERN ANALYSIS')
print('=' * 80)

r = analyze('bullish_candle', trades_df[trades_df['is_bullish'] == 1])
if r: results.append(r)
r = analyze('bearish_candle', trades_df[trades_df['is_bullish'] == 0])
if r: results.append(r)

for streak in [1, 2, 3, 4]:
    r = analyze(f'bullish_streak >= {streak}', trades_df[trades_df['bullish_streak'] >= streak])
    if r: results.append(r)

# 8. 모멘텀
print('\n' + '=' * 80)
print('8. MOMENTUM ANALYSIS')
print('=' * 80)

for thresh in [0.2, 0.3, 0.5, 1.0]:
    r = analyze(f'pct_change > {thresh}', trades_df[trades_df['pct_change'] > thresh])
    if r: results.append(r)

for thresh in [0.5, 1.0, 2.0]:
    r = analyze(f'pct_change_3 > {thresh}', trades_df[trades_df['pct_change_3'] > thresh])
    if r: results.append(r)

# 결과 정렬 및 출력
results_df = pd.DataFrame(results)

print('\n' + '=' * 80)
print('TOP CONDITIONS BY WIN RATE (min 50 trades)')
print('=' * 80)

top_winrate = results_df[results_df['trades'] >= 50].nlargest(20, 'winrate')
print(f"\n{'Condition':<25} {'Trades':>7} {'Wins':>6} {'Rate':>7} {'TotalPnL':>10} {'AvgPnL':>8}")
print('-' * 70)
for _, r in top_winrate.iterrows():
    print(f"{r['name']:<25} {r['trades']:>7} {r['wins']:>6} {r['winrate']:>6.1f}% {r['total_pnl']:>+9.1f}% {r['avg_pnl']:>+7.2f}%")

print('\n' + '=' * 80)
print('TOP CONDITIONS BY TOTAL PROFIT (min 50 trades)')
print('=' * 80)

top_profit = results_df[results_df['trades'] >= 50].nlargest(15, 'total_pnl')
print(f"\n{'Condition':<25} {'Trades':>7} {'Wins':>6} {'Rate':>7} {'TotalPnL':>10} {'AvgPnL':>8}")
print('-' * 70)
for _, r in top_profit.iterrows():
    print(f"{r['name']:<25} {r['trades']:>7} {r['wins']:>6} {r['winrate']:>6.1f}% {r['total_pnl']:>+9.1f}% {r['avg_pnl']:>+7.2f}%")

# 조합 분석
print('\n' + '=' * 80)
print('BEST COMBINATIONS')
print('=' * 80)

combo_results = []

combos = [
    ('pct2-4% + hour10', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['hour'] == 10)),
    ('pct2-4% + hour11', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['hour'] == 11)),
    ('pct2-4% + Wed', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['weekday'] == 2)),
    ('pct2-4% + Fri', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['weekday'] == 4)),
    ('pct2-4% + day_pos>0.7', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['day_position'] > 0.7)),
    ('pct2-4% + vol_surge', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['volume_change'] > 1.5)),
    ('pct2-4% + above_ma5', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['above_ma5'] == 1)),
    ('pct2-4% + bullish', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['is_bullish'] == 1)),
    ('pct1-3% + day_pos>0.8', (trades_df['pct_from_open'] >= 1) & (trades_df['pct_from_open'] < 3) & (trades_df['day_position'] > 0.8)),
    ('pct1-3% + vol_surge', (trades_df['pct_from_open'] >= 1) & (trades_df['pct_from_open'] < 3) & (trades_df['volume_change'] > 1.5)),
    ('hour10 + Wed', (trades_df['hour'] == 10) & (trades_df['weekday'] == 2)),
    ('hour11 + Fri', (trades_df['hour'] == 11) & (trades_df['weekday'] == 4)),
    ('vol_surge + bullish + ma5', (trades_df['volume_change'] > 1.5) & (trades_df['is_bullish'] == 1) & (trades_df['above_ma5'] == 1)),
    ('day_pos>0.8 + bullish', (trades_df['day_position'] > 0.8) & (trades_df['is_bullish'] == 1)),
    ('pct2-5% + NotTue + hour10+', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 5) & (trades_df['weekday'] != 1) & (trades_df['hour'] >= 10)),
    ('pct2-4% + NotTue + day_pos>0.7', (trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 4) & (trades_df['weekday'] != 1) & (trades_df['day_position'] > 0.7)),
]

print(f"\n{'Condition':<35} {'Trades':>7} {'Wins':>6} {'Rate':>7} {'TotalPnL':>10} {'AvgPnL':>8}")
print('-' * 80)

for name, cond in combos:
    filtered = trades_df[cond]
    if len(filtered) < 30:
        continue
    wins = (filtered['result'] == 'WIN').sum()
    total = len(filtered)
    winrate = wins / total * 100
    total_pnl = filtered['pnl'].sum()
    avg_pnl = filtered['pnl'].mean()
    print(f"{name:<35} {total:>7} {wins:>6} {winrate:>6.1f}% {total_pnl:>+9.1f}% {avg_pnl:>+7.2f}%")

conn.close()
print('\nDone!')
