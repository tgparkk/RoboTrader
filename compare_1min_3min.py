"""
1분봉 vs 3분봉 시뮬레이션 비교
"""
import duckdb
import pandas as pd
from datetime import datetime
from collections import defaultdict

print('=' * 60)
print('1분봉 vs 3분봉 시뮬레이션 비교 (자본금 제한 적용)')
print('=' * 60)

conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)
tables = conn.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_name LIKE 'minute_%'
""").fetchall()

def to_3min(df):
    """1분봉을 3분봉으로 변환"""
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    # time을 정수로 변환
    df['time_int'] = df['time'].apply(lambda x: int(float(x)) if isinstance(x, (int, float)) else int(x))
    df['h'] = df['time_int'] // 10000
    df['m'] = (df['time_int'] // 100) % 100
    df['g'] = df['h'] * 100 + (df['m'] // 3) * 3
    return df.groupby('g').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).reset_index().rename(columns={'g': 'time'}).sort_values('time')

daily_1 = defaultdict(list)
daily_3 = defaultdict(list)

processed = 0
for t in tables:
    tbl = t[0]
    code = tbl.replace('minute_', '')
    try:
        dates = conn.execute(f"""
            SELECT DISTINCT trade_date FROM {tbl}
            WHERE trade_date >= '20250901'
            ORDER BY trade_date
        """).fetchall()

        for d in dates:
            td = d[0]
            dt = datetime.strptime(td, '%Y%m%d')
            if dt.weekday() in [1, 3]:  # 화/목 회피
                continue

            df1 = conn.execute(f"""
                SELECT * FROM {tbl}
                WHERE trade_date = '{td}'
                ORDER BY idx
            """).fetchdf()

            if len(df1) < 50:
                continue
            day_open = df1.iloc[0]['open']
            if day_open <= 0:
                continue

            df3 = to_3min(df1)
            if len(df3) < 20:
                continue

            # 1분봉 시뮬레이션
            for idx in range(10, len(df1) - 10):
                r = df1.iloc[idx]
                time_val = r['time']
                time_int = int(float(time_val)) if isinstance(time_val, (int, float)) else int(time_val)
                h = time_int // 10000
                if h < 10 or h >= 12:
                    continue
                ep = r['close']
                pct = (ep / day_open - 1) * 100
                if 2 <= pct < 4:
                    res = None
                    for i in range(idx + 1, len(df1)):
                        rr = df1.iloc[i]
                        hp = (rr['high'] / ep - 1) * 100
                        lp = (rr['low'] / ep - 1) * 100
                        if hp >= 3.5:
                            res = {'pnl': 3.5, 'w': 1, 't': time_int}
                            break
                        if lp <= -2.5:
                            res = {'pnl': -2.5, 'w': 0, 't': time_int}
                            break
                    if res is None:
                        lp = (df1.iloc[-1]['close'] / ep - 1) * 100
                        res = {'pnl': lp, 'w': 1 if lp > 0 else 0, 't': time_int}
                    daily_1[td].append(res)
                    break

            # 3분봉 시뮬레이션
            for idx in range(5, len(df3) - 5):
                r = df3.iloc[idx]
                h = r['time'] // 100
                if h < 10 or h >= 12:
                    continue
                ep = r['close']
                pct = (ep / day_open - 1) * 100
                if 2 <= pct < 4:
                    res = None
                    for i in range(idx + 1, len(df3)):
                        rr = df3.iloc[i]
                        hp = (rr['high'] / ep - 1) * 100
                        lp = (rr['low'] / ep - 1) * 100
                        if hp >= 3.5:
                            res = {'pnl': 3.5, 'w': 1, 't': r['time']}
                            break
                        if lp <= -2.5:
                            res = {'pnl': -2.5, 'w': 0, 't': r['time']}
                            break
                    if res is None:
                        lp = (df3.iloc[-1]['close'] / ep - 1) * 100
                        res = {'pnl': lp, 'w': 1 if lp > 0 else 0, 't': r['time']}
                    daily_3[td].append(res)
                    break
        processed += 1
    except Exception as e:
        print(f'Error in {tbl}: {e}')

print(f'Processed {processed} stocks')
print(f'Daily signals 1min: {len(daily_1)} days')
print(f'Daily signals 3min: {len(daily_3)} days')

conn.close()

# 자본금 제한 적용 (하루 최대 5종목)
MAX_POSITIONS = 5
r1, r3 = [], []

for d in sorted(daily_1.keys()):
    s = sorted(daily_1[d], key=lambda x: x['t'])[:MAX_POSITIONS]
    r1.extend(s)

for d in sorted(daily_3.keys()):
    s = sorted(daily_3[d], key=lambda x: x['t'])[:MAX_POSITIONS]
    r3.extend(s)

# 통계 계산
n1, n3 = len(r1), len(r3)
print(f'After capital limit: 1min={n1}, 3min={n3}')

if n1 == 0 or n3 == 0:
    print('ERROR: No trades found!')
    exit(1)

w1 = sum(x['w'] for x in r1)
w3 = sum(x['w'] for x in r3)
wr1, wr3 = w1 / n1 * 100, w3 / n3 * 100
pnl1 = sum(x['pnl'] for x in r1)
pnl3 = sum(x['pnl'] for x in r3)

PER_TRADE = 2_000_000
FEE_RATE = 0.0025
MONTHS = 5

net1 = PER_TRADE * pnl1 / 100 - n1 * PER_TRADE * FEE_RATE
net3 = PER_TRADE * pnl3 / 100 - n3 * PER_TRADE * FEE_RATE
mon1, mon3 = net1 / MONTHS, net3 / MONTHS

print()
print(f"{'':20} {'1분봉':>12} {'3분봉':>12} {'차이':>10}")
print('-' * 55)
print(f"{'총 거래':20} {n1:>12} {n3:>12} {n3 - n1:>+10}")
print(f"{'승률':20} {wr1:>11.1f}% {wr3:>11.1f}% {wr3 - wr1:>+9.1f}%")
print(f"{'월 순수익':20} {mon1:>+11,.0f} {mon3:>+11,.0f} {mon3 - mon1:>+10,.0f}")
print()
print('=' * 55)
print('결론')
print('=' * 55)
print(f'1분봉: {n1}건, 승률 {wr1:.1f}%, 월 +{mon1:,.0f}원')
print(f'3분봉: {n3}건, 승률 {wr3:.1f}%, 월 +{mon3:,.0f}원')
print(f'차이: {(mon3 / mon1 - 1) * 100:+.1f}%')
print()
print(f'실거래는 3분봉 사용 -> 예상 월 수익: +{mon3:,.0f}원')
