"""macd_cross 5~6월 실거래 22건 손절 반사실(counterfactual) 시뮬.

각 거래의 매수~실제청산 구간 분봉을 걸어가며, 장중 손절선 X%를 먼저
건드렸으면 거기서 청산했을 때의 순손익을 실제와 비교한다.
- 갭하락(시가 < 손절가)이면 시가 체결(보수적)
- 수수료: 매수/매도 편도 0.014%, 매도세 0.18% (config/trading_config.json)
"""
import psycopg2
from datetime import datetime

COMMISSION = 0.00014
TAX = 0.0018  # 매도시만

# (buy_id, code, qty, buy_px, buy_ts, sell_px, sell_ts, actual_net)
TRADES = [
    (3986, '006800', 12, 79000, '2026-05-07 14:31:17', 79700, '2026-05-11 15:00:09', 6412),
    (3987, '010170', 44, 22150, '2026-05-08 14:31:16', 28650, '2026-05-12 15:00:07', 283418),
    (3988, '028050', 15, 62200, '2026-05-08 14:31:17', 54500, '2026-05-12 15:00:10', -117217),
    (3989, '068270', 5, 199100, '2026-05-08 14:31:17', 194000, '2026-05-12 15:00:13', -27521),
    (3994, '483650', 4, 249500, '2026-05-13 14:31:17', 256500, '2026-05-15 09:01:06', 25870),
    (3996, '322000', 5, 199600, '2026-05-15 14:31:23', 208000, '2026-05-19 09:01:10', 39843),
    (3997, '034220', 73, 13980, '2026-05-15 14:31:24', 13370, '2026-05-19 09:01:10', -46566),
    (3998, '196170', 2, 370500, '2026-05-15 14:31:24', 374000, '2026-05-19 09:01:10', 5445),
    (3999, '088350', 191, 5390, '2026-05-15 14:31:25', 5670, '2026-05-19 09:01:13', 51235),
    (4004, '347700', 24, 43250, '2026-05-19 14:31:18', 42795, '2026-05-21 09:01:07', -13058),
    (4006, '034220', 68, 15230, '2026-05-22 14:31:15', 15590, '2026-05-26 15:00:08', 22278),
    (4007, '000270', 6, 165700, '2026-05-22 14:31:20', 166400, '2026-05-26 15:00:08', 2124),
    (4008, '222800', 7, 132700, '2026-05-22 14:31:20', 133700, '2026-05-26 15:00:08', 5054),
    (4009, '036540', 93, 11210, '2026-05-26 14:31:16', 9180, '2026-05-28 09:01:08', -190592),
    (4013, '010170', 37, 27350, '2026-05-27 14:31:28', 24450, '2026-05-29 09:01:06', -109197),
    (4014, '403870', 18, 55900, '2026-05-27 14:31:29', 50600, '2026-05-29 09:01:09', -97308),
    (4015, '000990', 4, 203500, '2026-05-27 14:31:30', 194800, '2026-05-29 09:01:09', -36426),
    (4020, '417010', 74, 12820, '2026-05-29 14:31:18', 10750, '2026-06-02 09:01:09', -154856),
    (4021, '035420', 3, 279500, '2026-06-01 14:31:18', 266000, '2026-06-04 09:01:20', -42166),
    (4022, '028260', 2, 465000, '2026-06-01 14:31:23', 505000, '2026-06-04 09:01:24', 77910),
    (4024, '108490', 2, 410500, '2026-06-02 14:31:16', 339000, '2026-06-04 15:00:12', -144430),
    (4025, '454910', 5, 163800, '2026-06-02 14:31:17', 157800, '2026-06-04 15:00:15', -31645),
]

conn = psycopg2.connect(host='127.0.0.1', port=5433, dbname='robotrader', user='postgres', password='')
cur = conn.cursor()


def net_pnl(buy_px, sell_px, qty):
    buy_val = buy_px * qty
    sell_val = sell_px * qty
    fees = buy_val * COMMISSION + sell_val * (COMMISSION + TAX)
    return (sell_val - buy_val) - fees


def candles(code, start, end):
    cur.execute(
        """SELECT datetime, open, high, low, close FROM minute_candles
           WHERE stock_code=%s AND datetime > %s AND datetime <= %s
           ORDER BY datetime""", (code, start, end))
    return cur.fetchall()


def simulate(stop_pct):
    total = 0
    rows = []
    for (bid, code, qty, bpx, bts, spx, sts, actual) in TRADES:
        stop_px = bpx * (1 - stop_pct)
        cs = candles(code, bts, sts)
        fill = None
        ftime = None
        for (dt, o, h, lo, c) in cs:
            if lo <= stop_px:
                fill = o if o < stop_px else stop_px  # 갭하락이면 시가 체결
                ftime = dt
                break
        if fill is None:
            # 손절 미발동 → 실제 청산가 사용
            cf = net_pnl(bpx, spx, qty)
            triggered = ''
        else:
            cf = net_pnl(bpx, fill, qty)
            triggered = f'STOP@{int(fill)} {ftime:%m-%d %H:%M}'
        total += cf
        rows.append((code, actual, int(cf), triggered))
    return total, rows


actual_total = sum(t[7] for t in TRADES)
print(f"실제 순손익 합계: {actual_total:,}원  (22건)\n")
print(f"{'손절선':>6} | {'순손익합계':>12} | {'vs실제':>10} | 발동건수")
print('-' * 50)
for pct in [0.03, 0.04, 0.05, 0.06, 0.07, 0.10, 0.12, 0.15]:
    total, rows = simulate(pct)
    n_trig = sum(1 for r in rows if r[3])
    print(f"{pct*100:>5.0f}% | {total:>12,} | {total-actual_total:>+10,} | {n_trig}건")

for lvl in (0.10, 0.15):
    print(f"\n=== 손절 {lvl:.0%} 상세 (실거래 22건, 갭 체결 메커니즘 확인) ===")
    total_d, rows_d = simulate(lvl)
    print(f"  [{lvl:.0%} 합계] 실제 {actual_total:,} -> 손절後 {int(total_d):,}  (차이 {int(total_d)-actual_total:+,})")
    for (code, actual, cf, trig) in rows_d:
        diff = cf - actual
        mark = 'WIN_KILLED' if (actual > 0 and cf < 0) else ('improved' if cf > actual else ('worse' if cf < actual else ''))
        print(f"  {code}: actual {actual:>+9,} -> stop {cf:>+9,} (Δ{diff:>+8,}) {trig} {mark}")

print("\n=== 손절 3% 상세 (승자 보존 점검) ===")
total, rows = simulate(0.03)
for (code, actual, cf, trig) in rows:
    mark = 'WIN_KILLED' if (actual > 0 and cf < 0) else ('improved' if cf > actual else ('worse' if cf < actual else ''))
    print(f"  {code}: actual {actual:>+9,} -> stop {cf:>+9,} {trig} {mark}")

print("\n=== 손절 5% 상세 ===")
total, rows = simulate(0.05)
for (code, actual, cf, trig) in rows:
    mark = '←개선' if cf > actual else ('←악화' if cf < actual else '')
    print(f"  {code}: 실제 {actual:>+9,} → 손절後 {cf:>+9,} {trig} {mark}")

cur.close()
conn.close()
