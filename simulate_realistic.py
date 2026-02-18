"""
현실적 시뮬레이션 - 미체결/슬리피지 반영

기존 시뮬과 차이점:
1. 진입가: 신호 봉의 종가가 아닌 다음 봉의 시가 사용
2. 체결 조건: 다음 봉에서 진입가 이하 터치 시에만 체결
3. 슬리피지: 진입가에 0.1% 추가
"""
import duckdb
import pandas as pd
from datetime import datetime
from collections import defaultdict

print('=' * 60)
print('현실적 시뮬레이션 (미체결/슬리피지 반영)')
print('=' * 60)

# 설정
SLIPPAGE_PCT = 0.1  # 슬리피지 0.1%
FILL_CHECK_CANDLES = 3  # 체결 확인할 캔들 수 (3분 = 3개 1분봉)

conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)
tables = conn.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_name LIKE 'minute_%'
""").fetchall()

# 결과 저장
results_ideal = []      # 기존 방식 (즉시 체결)
results_realistic = []  # 현실적 (미체결 고려)
unfilled_count = 0

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
            # 화요일만 회피 (현재 설정과 동일)
            if dt.weekday() == 1:
                continue

            df = conn.execute(f"""
                SELECT * FROM {tbl}
                WHERE trade_date = '{td}'
                ORDER BY idx
            """).fetchdf()

            if len(df) < 50:
                continue

            day_open = df.iloc[0]['open']
            if day_open <= 0:
                continue

            # 1분봉 시뮬레이션
            for idx in range(10, len(df) - 10):
                r = df.iloc[idx]
                time_val = r['time']
                time_int = int(float(time_val)) if isinstance(time_val, (int, float)) else int(time_val)
                h = time_int // 10000
                if h < 10 or h >= 12:
                    continue

                signal_price = r['close']  # 신호 시점 가격
                pct = (signal_price / day_open - 1) * 100

                if 2 <= pct < 4:
                    # === 기존 방식 (즉시 체결) ===
                    entry_price_ideal = signal_price
                    res_ideal = None
                    for i in range(idx + 1, len(df)):
                        rr = df.iloc[i]
                        hp = (rr['high'] / entry_price_ideal - 1) * 100
                        lp = (rr['low'] / entry_price_ideal - 1) * 100
                        if hp >= 3.5:
                            res_ideal = {'pnl': 3.5, 'w': 1, 't': time_int, 'code': code, 'date': td}
                            break
                        if lp <= -2.5:
                            res_ideal = {'pnl': -2.5, 'w': 0, 't': time_int, 'code': code, 'date': td}
                            break
                    if res_ideal is None:
                        lp = (df.iloc[-1]['close'] / entry_price_ideal - 1) * 100
                        res_ideal = {'pnl': lp, 'w': 1 if lp > 0 else 0, 't': time_int, 'code': code, 'date': td}
                    results_ideal.append(res_ideal)

                    # === 현실적 방식 (미체결 고려) ===
                    # 다음 봉 시가 + 슬리피지 = 실제 진입가
                    if idx + 1 >= len(df):
                        unfilled_count += 1
                        break

                    next_candle = df.iloc[idx + 1]
                    entry_price_realistic = next_candle['open'] * (1 + SLIPPAGE_PCT / 100)

                    # 체결 확인: 다음 N개 봉 내에서 진입가 이하 터치 확인
                    filled = False
                    fill_idx = idx + 1

                    for check_i in range(idx + 1, min(idx + 1 + FILL_CHECK_CANDLES, len(df))):
                        check_candle = df.iloc[check_i]
                        # 시가가 진입가 이하이거나, 봉 중에 진입가 이하 터치
                        if check_candle['open'] <= entry_price_realistic or check_candle['low'] <= entry_price_realistic:
                            filled = True
                            fill_idx = check_i
                            # 실제 진입가는 시가와 진입가 중 높은 것 (불리하게)
                            entry_price_realistic = max(check_candle['open'], entry_price_realistic)
                            break

                    if not filled:
                        # 미체결
                        unfilled_count += 1
                        break

                    # 체결된 경우 손익 계산
                    res_realistic = None
                    for i in range(fill_idx + 1, len(df)):
                        rr = df.iloc[i]
                        hp = (rr['high'] / entry_price_realistic - 1) * 100
                        lp = (rr['low'] / entry_price_realistic - 1) * 100
                        if hp >= 3.5:
                            res_realistic = {'pnl': 3.5, 'w': 1, 't': time_int, 'code': code, 'date': td, 'entry': entry_price_realistic}
                            break
                        if lp <= -2.5:
                            res_realistic = {'pnl': -2.5, 'w': 0, 't': time_int, 'code': code, 'date': td, 'entry': entry_price_realistic}
                            break
                    if res_realistic is None:
                        lp = (df.iloc[-1]['close'] / entry_price_realistic - 1) * 100
                        res_realistic = {'pnl': lp, 'w': 1 if lp > 0 else 0, 't': time_int, 'code': code, 'date': td, 'entry': entry_price_realistic}
                    results_realistic.append(res_realistic)

                    break  # 종목당 하루 1회

        processed += 1
    except Exception as e:
        print(f'Error in {tbl}: {e}')

conn.close()

print(f'Processed {processed} stocks')
print(f'Unfilled orders: {unfilled_count}')

# 일별 자본금 제한 적용 (하루 최대 5종목)
MAX_POSITIONS = 5

def apply_capital_limit(results):
    daily = defaultdict(list)
    for r in results:
        daily[r['date']].append(r)

    limited = []
    for d in sorted(daily.keys()):
        s = sorted(daily[d], key=lambda x: x['t'])[:MAX_POSITIONS]
        limited.extend(s)
    return limited

r_ideal = apply_capital_limit(results_ideal)
r_realistic = apply_capital_limit(results_realistic)

# 통계 계산
def calc_stats(results, label):
    n = len(results)
    if n == 0:
        print(f'{label}: 거래 없음')
        return

    wins = sum(x['w'] for x in results)
    wr = wins / n * 100
    total_pnl = sum(x['pnl'] for x in results)

    PER_TRADE = 2_000_000
    FEE_RATE = 0.0025
    MONTHS = 5

    net = PER_TRADE * total_pnl / 100 - n * PER_TRADE * FEE_RATE
    monthly = net / MONTHS

    print(f'\n{label}')
    print('-' * 40)
    print(f'  총 거래: {n}건')
    print(f'  승률: {wr:.1f}%')
    print(f'  총 수익률: {total_pnl:.1f}%')
    print(f'  월 순수익: {monthly:+,.0f}원')

    return {'n': n, 'wr': wr, 'monthly': monthly}

print('\n' + '=' * 60)
print('비교 결과')
print('=' * 60)

stats_ideal = calc_stats(r_ideal, '기존 방식 (즉시 체결 가정)')
stats_realistic = calc_stats(r_realistic, f'현실적 방식 (슬리피지 {SLIPPAGE_PCT}%, 체결확인 {FILL_CHECK_CANDLES}봉)')

if stats_ideal and stats_realistic:
    print('\n' + '=' * 60)
    print('차이 분석')
    print('=' * 60)
    fill_rate = len(r_realistic) / len(r_ideal) * 100 if len(r_ideal) > 0 else 0
    print(f'  체결률: {fill_rate:.1f}% ({len(r_realistic)}/{len(r_ideal)})')
    print(f'  미체결: {unfilled_count}건')
    print(f'  승률 차이: {stats_realistic["wr"] - stats_ideal["wr"]:+.1f}%p')
    print(f'  월수익 차이: {stats_realistic["monthly"] - stats_ideal["monthly"]:+,.0f}원')
    print(f'  월수익 감소율: {(1 - stats_realistic["monthly"] / stats_ideal["monthly"]) * 100:.1f}%')
