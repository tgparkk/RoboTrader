"""Quick Pattern Discovery Test"""

import duckdb
import pandas as pd
import numpy as np

print('=' * 80)
print('Quick Pattern Discovery Test')
print('Stop Loss: -2.5%, Take Profit: +3.5%')
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

print('\nLoading data and simulating...')

for t in tables[:200]:
    table_name = t[0]
    stock_code = table_name.replace('minute_', '')

    try:
        dates = conn.execute(f'''
            SELECT DISTINCT trade_date FROM {table_name}
            ORDER BY trade_date
        ''').fetchall()

        for d in dates:
            trade_date = d[0]

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

            traded = False
            for idx in range(10, len(df) - 10):
                if traded:
                    break

                row = df.iloc[idx]
                hour = int(str(row['time'])[:2])

                if hour >= 12:
                    continue

                current_price = row['close']
                pct_from_open = (current_price / day_open - 1) * 100

                prev_close = df.iloc[idx-1]['close']
                pct_change = (current_price / prev_close - 1) * 100 if prev_close > 0 else 0

                prev_volume = df.iloc[idx-1]['volume']
                current_volume = row['volume']
                volume_change = current_volume / prev_volume if prev_volume > 0 else 1

                is_bullish = 1 if row['close'] > row['open'] else 0

                day_high = df.iloc[:idx+1]['high'].max()
                day_low = df.iloc[:idx+1]['low'].min()
                day_position = (current_price - day_low) / (day_high - day_low) if day_high > day_low else 0.5

                ma5 = df.iloc[max(0,idx-5):idx]['close'].mean()
                above_ma5 = 1 if current_price > ma5 else 0

                bullish_streak = 0
                for i in range(idx, max(0, idx-5), -1):
                    if df.iloc[i]['close'] > df.iloc[i]['open']:
                        bullish_streak += 1
                    else:
                        break

                if hour >= 10:
                    result = simulate_entry(df, idx)
                    if result:
                        all_trades.append({
                            'hour': hour,
                            'pct_from_open': pct_from_open,
                            'pct_change': pct_change,
                            'volume_change': volume_change,
                            'is_bullish': is_bullish,
                            'day_position': day_position,
                            'above_ma5': above_ma5,
                            'bullish_streak': bullish_streak,
                            **result
                        })
                        traded = True

    except Exception as e:
        continue

print(f'\nTotal trades collected: {len(all_trades)}')

if len(all_trades) < 100:
    print('Not enough data')
    conn.close()
    exit()

trades_df = pd.DataFrame(all_trades)

print('\n' + '=' * 80)
print('SINGLE CONDITION ANALYSIS')
print('=' * 80)

conditions = {
    'All (baseline)': trades_df,
    'pct_from_open < 2%': trades_df[trades_df['pct_from_open'] < 2],
    'pct_from_open < 3%': trades_df[trades_df['pct_from_open'] < 3],
    'pct_from_open < 4%': trades_df[trades_df['pct_from_open'] < 4],
    'pct_from_open < 5%': trades_df[trades_df['pct_from_open'] < 5],
    'pct_from_open 2-5%': trades_df[(trades_df['pct_from_open'] >= 2) & (trades_df['pct_from_open'] < 5)],
    'pct_from_open > 5%': trades_df[trades_df['pct_from_open'] >= 5],
    'is_bullish=1': trades_df[trades_df['is_bullish'] == 1],
    'volume_change > 1.5': trades_df[trades_df['volume_change'] > 1.5],
    'volume_change > 2': trades_df[trades_df['volume_change'] > 2],
    'day_position > 0.8': trades_df[trades_df['day_position'] > 0.8],
    'day_position < 0.3': trades_df[trades_df['day_position'] < 0.3],
    'above_ma5=1': trades_df[trades_df['above_ma5'] == 1],
    'bullish_streak >= 2': trades_df[trades_df['bullish_streak'] >= 2],
    'pct_change > 0.3': trades_df[trades_df['pct_change'] > 0.3],
}

print(f"\n{'Condition':<30} {'Trades':>7} {'Wins':>6} {'Rate':>7} {'TotalPnL':>10} {'AvgPnL':>8}")
print('-' * 75)

for name, filtered in conditions.items():
    if len(filtered) < 20:
        continue

    wins = (filtered['result'] == 'WIN').sum()
    total = len(filtered)
    winrate = wins / total * 100
    total_pnl = filtered['pnl'].sum()
    avg_pnl = filtered['pnl'].mean()

    print(f"{name:<30} {total:>7} {wins:>6} {winrate:>6.1f}% {total_pnl:>+9.1f}% {avg_pnl:>+7.2f}%")

print('\n' + '=' * 80)
print('COMBINATION CONDITIONS')
print('=' * 80)

combo_conditions = {
    'pct<2% + bullish': trades_df[(trades_df['pct_from_open'] < 2) & (trades_df['is_bullish'] == 1)],
    'pct<3% + bullish': trades_df[(trades_df['pct_from_open'] < 3) & (trades_df['is_bullish'] == 1)],
    'pct<3% + vol_surge': trades_df[(trades_df['pct_from_open'] < 3) & (trades_df['volume_change'] > 1.5)],
    'pct<3% + day_pos>0.8': trades_df[(trades_df['pct_from_open'] < 3) & (trades_df['day_position'] > 0.8)],
    'pct<3% + above_ma5': trades_df[(trades_df['pct_from_open'] < 3) & (trades_df['above_ma5'] == 1)],
    'pct<2% + streak>=2': trades_df[(trades_df['pct_from_open'] < 2) & (trades_df['bullish_streak'] >= 2)],
    'vol_surge + bullish': trades_df[(trades_df['volume_change'] > 1.5) & (trades_df['is_bullish'] == 1)],
    'pct<3% + pct_chg>0.3': trades_df[(trades_df['pct_from_open'] < 3) & (trades_df['pct_change'] > 0.3)],
    'day_pos<0.3 + bullish': trades_df[(trades_df['day_position'] < 0.3) & (trades_df['is_bullish'] == 1)],
}

print(f"\n{'Condition':<30} {'Trades':>7} {'Wins':>6} {'Rate':>7} {'TotalPnL':>10} {'AvgPnL':>8}")
print('-' * 75)

for name, filtered in combo_conditions.items():
    if len(filtered) < 20:
        continue

    wins = (filtered['result'] == 'WIN').sum()
    total = len(filtered)
    winrate = wins / total * 100
    total_pnl = filtered['pnl'].sum()
    avg_pnl = filtered['pnl'].mean()

    print(f"{name:<30} {total:>7} {wins:>6} {winrate:>6.1f}% {total_pnl:>+9.1f}% {avg_pnl:>+7.2f}%")

conn.close()
print('\nDone!')
