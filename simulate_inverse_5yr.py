"""
인버스 ETF 하락 예측 신호 5년 검증

개별주 시뮬 없이, 지수 일봉만으로 신호 정확도를 순수 검증.
- 신호 발동일에 인버스 매수 → 당일 시가→종가 수익률 계산
- 고정금액 투자 (복리 없음) → 정직한 수익률
- 5년 데이터로 과적합 여부 확인

Usage:
  python simulate_inverse_5yr.py
  python simulate_inverse_5yr.py --start 20210304 --end 20260304
"""

import psycopg2
import numpy as np
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD


def load_index_daily(start_date='20210304', end_date='20260304'):
    """KS11/KQ11 일봉 로드 + 기술지표 계산"""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute('''
        SELECT stock_code, stck_bsop_date,
               CAST(stck_oprc AS FLOAT), CAST(stck_clpr AS FLOAT),
               CAST(stck_hgpr AS FLOAT), CAST(stck_lwpr AS FLOAT)
        FROM daily_candles
        WHERE stock_code IN ('KS11', 'KQ11')
          AND stck_bsop_date >= %s AND stck_bsop_date <= %s
        ORDER BY stck_bsop_date
    ''', (start_date, end_date))
    rows = cur.fetchall()
    conn.close()

    # 코드별 분리
    raw = defaultdict(list)
    for code, dt, opn, cls, high, low in rows:
        raw[code].append((dt, float(opn), float(cls), float(high), float(low)))

    # 코드별 지표 계산
    data = {}  # {code: {date: {open, close, high, low, ret, intra, range, gap, ...}}}
    for code, entries in raw.items():
        data[code] = {}
        closes = [e[2] for e in entries]
        opens = [e[1] for e in entries]

        for i, (dt, opn, cls, high, low) in enumerate(entries):
            # 전일 종가 대비 등락률
            ret = (cls / closes[i-1] - 1) * 100 if i > 0 else 0
            # 장중 수익률 (시가->종가)
            intra = (cls / opn - 1) * 100 if opn > 0 else 0
            # 변동성
            rng = (high - low) / low * 100 if low > 0 else 0
            # 시가 갭
            gap = (opn / closes[i-1] - 1) * 100 if i > 0 else 0
            # 5일 수익률
            ret_5d = (cls / closes[i-5] - 1) * 100 if i >= 5 else 0
            # 연속 하락 일수
            consec = 0
            if i > 0:
                j = i
                while j > 0 and (closes[j] / closes[j-1] - 1) < 0:
                    consec += 1
                    j -= 1

            data[code][dt] = {
                'open': opn, 'close': cls, 'high': high, 'low': low,
                'ret': ret, 'intra': intra, 'range': rng, 'gap': gap,
                'ret_5d': ret_5d, 'consec_down': consec,
            }

    return data


def get_inverse_return(kospi_day, multiplier=1):
    """인버스 ETF 당일 수익률 (시가->종가 기준)"""
    if not kospi_day or kospi_day['open'] <= 0:
        return None
    return -multiplier * (kospi_day['close'] / kospi_day['open'] - 1) * 100


# ===================================================================
# 신호 함수들 (전일 데이터 기반)
# ===================================================================

def make_signals(kospi_data, kosdaq_data):
    """모든 신호를 미리 계산"""
    dates = sorted(kospi_data.keys())

    signals = {}
    for i, date in enumerate(dates):
        if i < 2:
            continue

        prev_date = dates[i-1]
        prev2_date = dates[i-2]
        kp = kospi_data.get(prev_date, {})
        kp2 = kospi_data.get(prev2_date, {})
        kd = kosdaq_data.get(prev_date, {})
        kp_today = kospi_data.get(date, {})
        kd_today = kosdaq_data.get(date, {})

        # 전일 등락률 (코스피/코스닥 중 더 나쁜 쪽)
        prev_ret = min(kp.get('ret', 0), kd.get('ret', 0))
        prev2_ret = min(kp2.get('ret', 0), kosdaq_data.get(prev2_date, {}).get('ret', 0))

        # 전일 변동성
        prev_range = max(kp.get('range', 0), kd.get('range', 0))

        # 당일 시가 갭
        today_gap = min(kp_today.get('gap', 0), kd_today.get('gap', 0))

        # 5일 수익률
        prev_5d = min(kp.get('ret_5d', 0), kd.get('ret_5d', 0))

        # 연속 하락
        prev_consec = max(kp.get('consec_down', 0), kd.get('consec_down', 0))

        signals[date] = {
            'prev_ret': prev_ret,
            'prev2_ret': prev2_ret,
            'prev_range': prev_range,
            'today_gap': today_gap,
            'prev_5d': prev_5d,
            'prev_consec': prev_consec,
        }

    return signals, dates


def run_5yr_analysis():
    parser = argparse.ArgumentParser(description='5yr inverse signal analysis')
    parser.add_argument('--start', default='20210304')
    parser.add_argument('--end', default='20260304')
    args = parser.parse_args()

    print('=' * 100)
    print('  인버스 ETF 하락 예측 신호 5년 검증')
    print('  고정금액 투자 (복리 없음) / 지수 일봉 기반')
    print('=' * 100)

    print('\n[1/2] 지수 데이터 로드...')
    data = load_index_daily(args.start, args.end)
    kospi = data.get('KS11', {})
    kosdaq = data.get('KQ11', {})
    print(f'  KS11: {len(kospi)}일, KQ11: {len(kosdaq)}일')

    print('[2/2] 신호 계산 + 검증...\n')
    signals, dates = make_signals(kospi, kosdaq)

    # ================================================================
    # 신호 정의
    # ================================================================
    signal_defs = [
        # (이름, 조건 함수)
        # A. 전일 하락 모멘텀
        ('A1. 전일하락 < -0.5%', lambda s: s['prev_ret'] < -0.5),
        ('A2. 전일하락 < -1.0%', lambda s: s['prev_ret'] < -1.0),
        ('A3. 전일하락 < -1.5%', lambda s: s['prev_ret'] < -1.5),
        ('A4. 전일하락 < -2.0%', lambda s: s['prev_ret'] < -2.0),
        ('A5. 전일하락 < -3.0%', lambda s: s['prev_ret'] < -3.0),

        # B. 2일 연속 하락
        ('B1. 2일연속 < -0.3%', lambda s: s['prev_ret'] < -0.3 and s['prev2_ret'] < -0.3),
        ('B2. 2일연속 < -0.5%', lambda s: s['prev_ret'] < -0.5 and s['prev2_ret'] < -0.5),
        ('B3. 2일연속 < -1.0%', lambda s: s['prev_ret'] < -1.0 and s['prev2_ret'] < -1.0),

        # C. 5일 누적 하락
        ('C1. 5일누적 < -3%', lambda s: s['prev_5d'] < -3.0),
        ('C2. 5일누적 < -5%', lambda s: s['prev_5d'] < -5.0),
        ('C3. 5일누적 < -7%', lambda s: s['prev_5d'] < -7.0),

        # D. 변동성 폭발
        ('D1. 전일변동성 > 2.0%', lambda s: s['prev_range'] > 2.0),
        ('D2. 전일변동성 > 2.5%', lambda s: s['prev_range'] > 2.5),
        ('D3. 전일변동성 > 3.0%', lambda s: s['prev_range'] > 3.0),

        # E. 시가 갭
        ('E1. 당일갭 < -0.3%', lambda s: s['today_gap'] < -0.3),
        ('E2. 당일갭 < -0.5%', lambda s: s['today_gap'] < -0.5),
        ('E3. 당일갭 < -1.0%', lambda s: s['today_gap'] < -1.0),

        # F. 연속하락 일수
        ('F1. 연속하락 >= 2일', lambda s: s['prev_consec'] >= 2),
        ('F2. 연속하락 >= 3일', lambda s: s['prev_consec'] >= 3),
        ('F3. 연속하락 >= 4일', lambda s: s['prev_consec'] >= 4),

        # G. 복합 신호
        ('G1. 전일-1%+갭-0.5%', lambda s: s['prev_ret'] < -1.0 and s['today_gap'] < -0.5),
        ('G2. 전일-1%+갭-1.0%', lambda s: s['prev_ret'] < -1.0 and s['today_gap'] < -1.0),
        ('G3. 전일-2%+갭-0.5%', lambda s: s['prev_ret'] < -2.0 and s['today_gap'] < -0.5),
        ('G4. 2일연속-0.5%+갭-0.3%', lambda s: s['prev_ret'] < -0.5 and s['prev2_ret'] < -0.5 and s['today_gap'] < -0.3),
        ('G5. 전일-1%+변동성>2.5%', lambda s: s['prev_ret'] < -1.0 and s['prev_range'] > 2.5),
        ('G6. 전일-1%+5일-3%', lambda s: s['prev_ret'] < -1.0 and s['prev_5d'] < -3.0),
        ('G7. 전일-1%+연속2일', lambda s: s['prev_ret'] < -1.0 and s['prev_consec'] >= 2),

        # H. 복합 점수 (2점 이상)
        ('H1. 복합점수>=2', lambda s: _crash_score(s) >= 2),
        ('H2. 복합점수>=3', lambda s: _crash_score(s) >= 3),
        ('H3. 복합점수>=4', lambda s: _crash_score(s) >= 4),
    ]

    # ================================================================
    # 전체 기간 분석
    # ================================================================
    print('=' * 100)
    print(f'  전체 기간: {dates[0]} ~ {dates[-1]} ({len(dates)}거래일)')
    print('=' * 100)
    _print_signal_table(signal_defs, signals, dates, kospi, '전체 5년')

    # ================================================================
    # 연도별 분석
    # ================================================================
    years = sorted(set(d[:4] for d in dates))
    for year in years:
        year_dates = [d for d in dates if d[:4] == year]
        if len(year_dates) < 20:
            continue
        year_signals = {d: signals[d] for d in year_dates if d in signals}
        print(f'\n{"=" * 100}')
        print(f'  {year}년 ({len(year_dates)}거래일)')
        print(f'{"=" * 100}')
        _print_signal_table(signal_defs, year_signals, year_dates, kospi, year)

    # ================================================================
    # 시장 구간별 분석 (상승장 vs 하락장)
    # ================================================================
    print(f'\n{"=" * 100}')
    print('  시장 구간별 분석')
    print(f'{"=" * 100}')

    # 코스피 주요 구간 식별
    sorted_dates = sorted(kospi.keys())
    print('\n  코스피 연도별 등락:')
    for year in years:
        yd = [d for d in sorted_dates if d[:4] == year]
        if len(yd) < 2:
            continue
        start_c = kospi[yd[0]]['close']
        end_c = kospi[yd[-1]]['close']
        chg = (end_c / start_c - 1) * 100
        label = 'UP' if chg > 5 else ('DOWN' if chg < -5 else 'FLAT')
        print(f'    {year}: {start_c:.0f} -> {end_c:.0f} ({chg:+.1f}%) [{label}]')

    # ================================================================
    # 고정금액 투자 시뮬레이션
    # ================================================================
    print(f'\n{"=" * 100}')
    print('  고정금액 인버스 투자 시뮬레이션 (건당 100만원 고정)')
    print('  개별주 없이, 신호 발동시 인버스만 매수')
    print(f'{"=" * 100}')

    INVEST_PER_TRADE = 1_000_000  # 건당 100만원

    best_scenarios = []
    for name, condition_fn in signal_defs:
        for mult in [1, 2]:
            total_profit = 0
            trades = 0
            wins = 0
            yearly_profit = defaultdict(float)
            yearly_trades = defaultdict(int)

            for date in dates:
                if date not in signals:
                    continue
                if not condition_fn(signals[date]):
                    continue
                if date not in kospi:
                    continue

                inv_ret = get_inverse_return(kospi[date], mult)
                if inv_ret is None:
                    continue

                profit = INVEST_PER_TRADE * (inv_ret / 100)
                total_profit += profit
                trades += 1
                if inv_ret > 0:
                    wins += 1
                yearly_profit[date[:4]] += profit
                yearly_trades[date[:4]] += 1

            if trades == 0:
                continue

            winrate = wins / trades * 100
            avg_ret = total_profit / trades / INVEST_PER_TRADE * 100
            total_invested = trades * INVEST_PER_TRADE

            best_scenarios.append({
                'name': f'{name} x{mult}',
                'trades': trades,
                'wins': wins,
                'winrate': winrate,
                'total_profit': total_profit,
                'avg_ret': avg_ret,
                'total_invested': total_invested,
                'roi': total_profit / INVEST_PER_TRADE * 100,  # 100만원 기준 총수익률
                'yearly_profit': dict(yearly_profit),
                'yearly_trades': dict(yearly_trades),
            })

    # 총수익 기준 정렬
    best_scenarios.sort(key=lambda x: x['total_profit'], reverse=True)

    print(f'\n  {"시나리오":<40} {"거래":>5} {"승률":>6} {"평균수익":>8} '
          f'{"총수익(만원)":>10} {"건당100만ROI":>10}')
    print('  ' + '-' * 95)
    for s in best_scenarios[:30]:
        print(f'  {s["name"]:<40} {s["trades"]:>4}건 {s["winrate"]:>5.1f}% '
              f'{s["avg_ret"]:>+7.2f}% '
              f'{s["total_profit"]/10000:>+9.0f}만 '
              f'{s["roi"]:>+9.1f}%')

    # 연도별 분해 (상위 5개)
    print(f'\n  --- 상위 5개 시나리오 연도별 분해 (수익 만원) ---')
    header = f'  {"시나리오":<35}'
    for y in years:
        header += f' {y:>12}'
    header += f' {"합계":>12}'
    print(header)
    print('  ' + '-' * (35 + 13 * (len(years) + 1)))

    for s in best_scenarios[:5]:
        row = f'  {s["name"]:<35}'
        for y in years:
            p = s['yearly_profit'].get(y, 0) / 10000
            t = s['yearly_trades'].get(y, 0)
            row += f' {p:>+7.0f}({t:>2})'
        row += f' {s["total_profit"]/10000:>+11.0f}'
        print(row)

    # ================================================================
    # 핵심 결론
    # ================================================================
    print(f'\n{"=" * 100}')
    print('  핵심 결론')
    print(f'{"=" * 100}')

    # 전체 기간 코스피 방향
    all_sorted = sorted(kospi.keys())
    total_chg = (kospi[all_sorted[-1]]['close'] / kospi[all_sorted[0]]['close'] - 1) * 100
    print(f'\n  코스피 전체: {kospi[all_sorted[0]]["close"]:.0f} -> {kospi[all_sorted[-1]]["close"]:.0f} ({total_chg:+.1f}%)')

    # 하락장 연도 vs 상승장 연도 비교
    for year in years:
        yd = [d for d in all_sorted if d[:4] == year]
        if len(yd) < 20:
            continue
        chg = (kospi[yd[-1]]['close'] / kospi[yd[0]]['close'] - 1) * 100
        if chg < -5:
            print(f'\n  ** {year}년 (하락장 {chg:+.1f}%) 상위 신호 성과:')
            for s in best_scenarios[:5]:
                yp = s['yearly_profit'].get(year, 0) / 10000
                yt = s['yearly_trades'].get(year, 0)
                print(f'     {s["name"]:<35}: {yp:>+7.0f}만원 ({yt}건)')

    print()


def _crash_score(s):
    """복합 하락 점수 (0~5)"""
    score = 0
    if s['prev_ret'] < -1.0:
        score += 1
    if s['prev2_ret'] < -0.5:
        score += 1
    if s['prev_5d'] < -3.0:
        score += 1
    if s['prev_range'] > 2.5:
        score += 1
    if s['today_gap'] < -0.5:
        score += 1
    return score


def _print_signal_table(signal_defs, signals, dates, kospi, label):
    """신호별 정확도 테이블"""
    print(f'\n  {"신호":<40} {"발동":>5} {"적중":>5} {"적중률":>6} '
          f'{"인버스1x평균":>10} {"인버스2x평균":>10} {"손익비":>6}')
    print('  ' + '-' * 95)

    for name, condition_fn in signal_defs:
        triggered = []
        inv_returns = []

        for date in dates:
            if date not in signals:
                continue
            if not condition_fn(signals[date]):
                continue
            if date not in kospi:
                continue

            inv_ret = get_inverse_return(kospi[date], 1)
            if inv_ret is not None:
                triggered.append(date)
                inv_returns.append(inv_ret)

        if not triggered:
            print(f'  {name:<40} {"0":>4}일')
            continue

        correct = sum(1 for r in inv_returns if r > 0)
        acc = correct / len(triggered) * 100
        avg1 = np.mean(inv_returns)
        avg2 = avg1 * 2
        # 손익비
        gains = [r for r in inv_returns if r > 0]
        losses = [r for r in inv_returns if r <= 0]
        avg_gain = np.mean(gains) if gains else 0
        avg_loss = abs(np.mean(losses)) if losses else 0.01
        plr = avg_gain / avg_loss if avg_loss > 0 else 99

        print(f'  {name:<40} {len(triggered):>4}일 {correct:>4}일 {acc:>5.1f}% '
              f'{avg1:>+9.3f}% {avg2:>+9.3f}% {plr:>5.2f}')


if __name__ == '__main__':
    run_5yr_analysis()
