"""
전략 탐색기: 분봉 데이터로 승리 전략 발굴

266거래일 × 1095종목 분봉 데이터에서 다양한 진입/청산 조합을 테스트.
"""
import psycopg2
import numpy as np
from collections import defaultdict
import sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD


def simulate_trade(prices, entry_idx, entry_price, strategy):
    """
    단일 거래 시뮬레이션.
    prices: [(time_str, open, high, low, close), ...]
    Returns: (pnl_pct, exit_reason, holding_minutes, max_profit_pct)
    """
    tp = strategy.get('tp', 6.0)
    sl = strategy.get('sl', -5.0)
    trailing = strategy.get('trailing', False)
    trail_activate = strategy.get('trail_activate', 1.5)  # 트레일링 활성화 수익%
    trail_offset = strategy.get('trail_offset', 1.0)      # 고점 대비 하락 허용%
    eod_close = strategy.get('eod_close', True)

    max_profit = 0.0
    trailing_sl = sl
    trailing_active = False

    for i in range(entry_idx + 1, len(prices)):
        t, o, h, l, c = prices[i]

        high_pnl = (h / entry_price - 1) * 100
        low_pnl = (l / entry_price - 1) * 100
        close_pnl = (c / entry_price - 1) * 100

        if high_pnl > max_profit:
            max_profit = high_pnl

        # 트레일링 스탑
        if trailing and max_profit >= trail_activate:
            trailing_active = True
            trailing_sl = max(trailing_sl, max_profit - trail_offset)

        # 익절
        if high_pnl >= tp:
            return tp, 'TP', i - entry_idx, max_profit

        # 손절 (트레일링 또는 고정)
        effective_sl = trailing_sl if trailing_active else sl
        if low_pnl <= effective_sl:
            exit_pnl = effective_sl
            reason = 'TRAIL_SL' if trailing_active else 'SL'
            return exit_pnl, reason, i - entry_idx, max_profit

    # 장마감
    if eod_close and len(prices) > entry_idx + 1:
        last_pnl = (prices[-1][4] / entry_price - 1) * 100  # close
        return last_pnl, 'EOD', len(prices) - 1 - entry_idx, max_profit

    return 0.0, 'NONE', 0, 0.0


def run_discovery():
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD
    )
    cur = conn.cursor()

    # 거래일 목록
    cur.execute("SELECT DISTINCT trade_date FROM minute_candles WHERE trade_date >= '20250224' ORDER BY trade_date")
    trading_dates = [r[0] for r in cur.fetchall()]
    print(f"거래일: {len(trading_dates)}일")

    # 전략 정의
    strategies = {
        # === 현행 기준선 ===
        'A_현행(시가+1~3%,TP6/SL5)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 6.0, 'sl': -5.0, 'trailing': False,
            'gap_min': None, 'gap_max': None,
        },
        # === TP/SL 변형 ===
        'B_TP3/SL2': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 3.0, 'sl': -2.0, 'trailing': False,
            'gap_min': None, 'gap_max': None,
        },
        'C_TP3/SL1.5': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 3.0, 'sl': -1.5, 'trailing': False,
            'gap_min': None, 'gap_max': None,
        },
        'D_TP2/SL1': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 2.0, 'sl': -1.0, 'trailing': False,
            'gap_min': None, 'gap_max': None,
        },
        # === 트레일링 스탑 ===
        'E_트레일링(1.5%활성,1%오프셋)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 6.0, 'sl': -2.0, 'trailing': True,
            'trail_activate': 1.5, 'trail_offset': 1.0,
            'gap_min': None, 'gap_max': None,
        },
        'F_트레일링(1.0%활성,0.7%오프셋)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 4.0, 'sl': -1.5, 'trailing': True,
            'trail_activate': 1.0, 'trail_offset': 0.7,
            'gap_min': None, 'gap_max': None,
        },
        # === 갭다운 반등 전략 ===
        'G_갭다운반등(갭-2~0%,TP3/SL1.5)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 3.0, 'sl': -1.5, 'trailing': False,
            'gap_min': -2.0, 'gap_max': 0.0,
        },
        'H_갭다운반등(갭-2~0%,트레일링)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 5.0, 'sl': -1.5, 'trailing': True,
            'trail_activate': 1.5, 'trail_offset': 1.0,
            'gap_min': -2.0, 'gap_max': 0.0,
        },
        # === 10시 이후 확인 진입 ===
        'I_10시이후(TP3/SL1.5)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '1000', 'entry_end': '1200',
            'tp': 3.0, 'sl': -1.5, 'trailing': False,
            'gap_min': None, 'gap_max': None,
        },
        'J_10시이후+갭다운(갭-2~0%)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '1000', 'entry_end': '1200',
            'tp': 3.0, 'sl': -1.5, 'trailing': False,
            'gap_min': -2.0, 'gap_max': 0.0,
        },
        # === 시가 근처 눌림 후 돌파 ===
        'K_시가근처눌림(시가-1~+0.5%→+1%돌파,TP3/SL1.5)': {
            'entry': 'open_pullback_breakout', 'min_pct': -1.0, 'max_pct': 0.5,
            'breakout_pct': 1.0,
            'entry_start': '0930', 'entry_end': '1130',
            'tp': 3.0, 'sl': -1.5, 'trailing': False,
            'gap_min': None, 'gap_max': None,
        },
        # === 현행+갭필터+TP축소 (종합 개선) ===
        'L_종합개선(갭-2~+2%,TP3/SL2,트레일링)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 4.0, 'sl': -2.0, 'trailing': True,
            'trail_activate': 1.5, 'trail_offset': 1.0,
            'gap_min': -2.0, 'gap_max': 2.0,
        },
        'M_종합개선v2(갭-2~+2%,TP3/SL1.5)': {
            'entry': 'pct_from_open', 'min_pct': 1.0, 'max_pct': 3.0,
            'entry_start': '0900', 'entry_end': '1200',
            'tp': 3.0, 'sl': -1.5, 'trailing': False,
            'gap_min': -2.0, 'gap_max': 2.0,
        },
        # === 종가 매매 (14시 이후 매수 → 익일 시가 매도) ===
        'N_종가매수(14시이후,시가-1~+1%)': {
            'entry': 'pct_from_open', 'min_pct': -1.0, 'max_pct': 1.0,
            'entry_start': '1400', 'entry_end': '1450',
            'tp': 99.0, 'sl': -99.0, 'trailing': False,  # 장마감 청산만
            'gap_min': None, 'gap_max': None,
            'next_day_exit': True,
        },
    }

    # 결과 저장
    results = {name: [] for name in strategies}

    # 전일 종가 캐시 (일봉에서)
    cur.execute("""
        SELECT stock_code, stck_bsop_date, stck_clpr
        FROM daily_candles
        WHERE stock_code NOT IN ('KS11','KQ11')
        ORDER BY stock_code, stck_bsop_date
    """)
    prev_close_db = {}
    last_code = None
    last_close = None
    for code, date, close in cur.fetchall():
        if code == last_code and last_close:
            prev_close_db[(code, date)] = float(last_close)
        last_code = code
        last_close = close
    print(f"전일종가 캐시: {len(prev_close_db)}건")

    # 분봉 전일종가 보완 (daily_candles에 없는 종목)
    print("분봉 기반 전일종가 보완 중...")
    cur.execute("""
        SELECT stock_code, trade_date,
               (SELECT mc2.close FROM minute_candles mc2
                WHERE mc2.stock_code = mc.stock_code
                AND mc2.trade_date < mc.trade_date
                ORDER BY mc2.trade_date DESC, mc2.idx DESC LIMIT 1) as prev_close
        FROM (SELECT DISTINCT stock_code, trade_date FROM minute_candles) mc
    """)
    # This query would be too slow, let's use a different approach
    # Build prev close from minute candles directly

    total_processed = 0

    for day_idx, trade_date in enumerate(trading_dates):
        if day_idx % 20 == 0:
            print(f"  {day_idx}/{len(trading_dates)} ({trade_date})...")

        # 이 날의 모든 종목 분봉 가져오기
        cur.execute("""
            SELECT stock_code, time, open, high, low, close, volume
            FROM minute_candles
            WHERE trade_date = %s
            ORDER BY stock_code, idx
        """, [trade_date])

        # 종목별 그룹핑
        stock_candles = defaultdict(list)
        for row in cur.fetchall():
            code = row[0]
            t = str(row[1]).replace(':', '')[:4]  # HHMM
            o, h, l, c, v = [float(x) if x else 0 for x in row[2:]]
            if o > 0 and c > 0:
                stock_candles[code].append((t, o, h, l, c, v))

        for stock_code, candles in stock_candles.items():
            if len(candles) < 30:
                continue

            # 시가 (첫 캔들 open)
            day_open = candles[0][1]
            if day_open <= 0:
                continue

            # 전일종가
            prev_close = prev_close_db.get((stock_code, trade_date))
            gap_pct = ((day_open / prev_close) - 1) * 100 if prev_close and prev_close > 0 else None

            # 각 전략 테스트
            for strat_name, strat in strategies.items():
                entry_start = strat['entry_start']
                entry_end = strat['entry_end']
                gap_min = strat.get('gap_min')
                gap_max = strat.get('gap_max')

                # 갭 필터
                if gap_min is not None and gap_pct is not None and gap_pct < gap_min:
                    continue
                if gap_max is not None and gap_pct is not None and gap_pct > gap_max:
                    continue

                # 진입 신호 탐색
                entry_found = False
                for ci in range(5, len(candles) - 5):
                    if entry_found:
                        break

                    t, o, h, l, c, v = candles[ci]

                    # 시간 필터
                    if t < entry_start or t >= entry_end:
                        continue

                    entry_type = strat['entry']

                    if entry_type == 'pct_from_open':
                        pct = (c / day_open - 1) * 100
                        if pct < strat['min_pct'] or pct >= strat['max_pct']:
                            continue
                        entry_price = c

                    elif entry_type == 'open_pullback_breakout':
                        pct = (c / day_open - 1) * 100
                        # 이전에 시가 근처 눌림이 있었는지 확인
                        had_pullback = False
                        for pi in range(max(0, ci-20), ci):
                            pp = (candles[pi][4] / day_open - 1) * 100  # close
                            if strat['min_pct'] <= pp <= strat['max_pct']:
                                had_pullback = True
                                break
                        if not had_pullback:
                            continue
                        # 현재 시가 대비 돌파
                        if pct < strat.get('breakout_pct', 1.0):
                            continue
                        entry_price = c

                    else:
                        continue

                    # 거래 시뮬
                    prices_for_sim = [(candles[j][0], candles[j][1], candles[j][2],
                                       candles[j][3], candles[j][4]) for j in range(len(candles))]

                    pnl, reason, holding, max_profit = simulate_trade(
                        prices_for_sim, ci, entry_price, strat
                    )

                    # 수수료/세금 차감
                    fee_pct = 0.015 * 2 + 0.18  # 매수0.015% + 매도0.015% + 세금0.18%
                    net_pnl = pnl - fee_pct / 100 * 100  # 대략 0.21% 차감
                    # 더 정확하게: 수수료는 금액 기반이므로 % 단순 차감
                    net_pnl = pnl - 0.21

                    results[strat_name].append({
                        'date': trade_date,
                        'code': stock_code,
                        'pnl': net_pnl,
                        'raw_pnl': pnl,
                        'reason': reason,
                        'max_profit': max_profit,
                        'gap': gap_pct,
                        'holding': holding,
                    })

                    entry_found = True
                    total_processed += 1

    cur.close()
    conn.close()

    # ====== 결과 출력 ======
    print(f"\n총 시뮬 거래: {total_processed:,}건\n")
    print('=' * 100)
    print(f'{"전략":>40} {"거래":>6} {"승률":>6} {"평균":>7} {"중앙":>7} {"누적":>10} {"TP":>5} {"SL":>5} {"TRAIL":>5} {"EOD":>5}')
    print('-' * 100)

    summary = []
    for name in sorted(strategies.keys()):
        trades = results[name]
        if not trades:
            continue

        pnls = [t['pnl'] for t in trades]
        total = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        avg = np.mean(pnls)
        med = np.median(pnls)
        cum = np.sum(pnls)

        reasons = defaultdict(int)
        for t in trades:
            reasons[t['reason']] += 1

        tp_cnt = reasons.get('TP', 0)
        sl_cnt = reasons.get('SL', 0)
        trail_cnt = reasons.get('TRAIL_SL', 0)
        eod_cnt = reasons.get('EOD', 0)

        summary.append({
            'name': name, 'total': total, 'wins': wins,
            'winrate': wins/total*100, 'avg': avg, 'med': med, 'cum': cum,
            'tp': tp_cnt, 'sl': sl_cnt, 'trail': trail_cnt, 'eod': eod_cnt,
        })

    summary.sort(key=lambda x: x['avg'], reverse=True)

    for s in summary:
        print(f"{s['name']:>40} {s['total']:>6} {s['winrate']:>5.1f}% {s['avg']:>+6.2f}% {s['med']:>+6.2f}% {s['cum']:>+9.1f}% {s['tp']:>5} {s['sl']:>5} {s['trail']:>5} {s['eod']:>5}")

    # 상위 3개 전략 상세
    print('\n')
    print('=' * 100)
    print('상위 3개 전략 상세')
    print('=' * 100)

    for rank, s in enumerate(summary[:3], 1):
        name = s['name']
        trades = results[name]
        pnls = [t['pnl'] for t in trades]

        # 월별 수익
        monthly = defaultdict(list)
        for t in trades:
            month = t['date'][:6]
            monthly[month].append(t['pnl'])

        print(f"\n#{rank} {name}")
        print(f"  거래: {s['total']}건, 승률: {s['winrate']:.1f}%, 평균: {s['avg']:+.2f}%")
        print(f"  월별:")
        for m in sorted(monthly.keys()):
            mp = monthly[m]
            mw = sum(1 for p in mp if p > 0)
            print(f"    {m}: {len(mp):>3}건, 승률 {mw/len(mp)*100:>5.1f}%, 평균 {np.mean(mp):+.2f}%")

        # 갭별 성과
        if any(t['gap'] is not None for t in trades):
            print(f"  갭별:")
            gap_bins = [(-100, -2), (-2, 0), (0, 2), (2, 4), (4, 100)]
            for lo, hi in gap_bins:
                gt = [t for t in trades if t['gap'] is not None and lo <= t['gap'] < hi]
                if gt:
                    gw = sum(1 for t in gt if t['pnl'] > 0)
                    print(f"    갭{lo:>+.0f}~{hi:>+.0f}%: {len(gt):>3}건, 승률 {gw/len(gt)*100:>5.1f}%, 평균 {np.mean([t['pnl'] for t in gt]):+.2f}%")

    print('\nDone!')


if __name__ == '__main__':
    run_discovery()
