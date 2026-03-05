"""
익절 미도달 거래의 장중 궤적 분석

질문: 익절(+5%)까지 못 간 거래들은 어떤 패턴으로 움직이다 끝나는가?
- 최대 수익에 도달하는 시점은 언제인가?
- 최대 수익 후 얼마나 되돌리는가?
- 시간/거래량/가격 패턴으로 "더 이상 안 오른다"를 감지할 수 있는가?
- 트레일링 스탑 or 시간 기반 청산이 유효한가?
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


def get_trading_dates(cur, start_date, end_date=None):
    sql = "SELECT DISTINCT trade_date FROM minute_candles WHERE trade_date >= %s"
    params = [start_date]
    if end_date:
        sql += " AND trade_date <= %s"
        params.append(end_date)
    sql += " ORDER BY trade_date"
    cur.execute(sql, params)
    return [row[0] for row in cur.fetchall()]


def get_prev_close_map(cur, trade_date, prev_date):
    cur.execute('''
        SELECT stock_code, close
        FROM minute_candles
        WHERE trade_date = %s
          AND idx = (
            SELECT MAX(idx) FROM minute_candles mc2
            WHERE mc2.stock_code = minute_candles.stock_code
              AND mc2.trade_date = %s
          )
    ''', [prev_date, prev_date])
    return {row[0]: row[1] for row in cur.fetchall()}


def get_daily_metrics(cur, trade_date):
    cur.execute('''
        SELECT
            stock_code,
            MIN(CASE WHEN time >= '090000' AND time <= '090300' THEN open END) as day_open,
            SUM(amount) as daily_amount,
            MAX(close) as max_price,
            MIN(close) as min_price
        FROM minute_candles
        WHERE trade_date = %s
        GROUP BY stock_code
        HAVING COUNT(*) >= 50
    ''', [trade_date])
    metrics = {}
    for row in cur.fetchall():
        stock_code, day_open, daily_amount, max_price, min_price = row
        if day_open and day_open > 0 and daily_amount:
            metrics[stock_code] = {
                'day_open': float(day_open),
                'daily_amount': float(daily_amount),
            }
    return metrics


def apply_screener_filter(daily_metrics, prev_close_map, top_n=60,
                          min_price=5000, max_price=500000,
                          min_amount=1_000_000_000, max_gap_pct=3.0):
    ranked = sorted(daily_metrics.items(), key=lambda x: x[1]['daily_amount'], reverse=True)[:top_n]
    passed = set()
    for stock_code, metrics in ranked:
        day_open = metrics['day_open']
        if stock_code[-1] == '5':
            continue
        if not (min_price <= day_open <= max_price):
            continue
        if metrics['daily_amount'] < min_amount:
            continue
        prev_close = prev_close_map.get(stock_code)
        if prev_close and prev_close > 0:
            gap_pct = abs(day_open / prev_close - 1) * 100
            if gap_pct > max_gap_pct:
                continue
        passed.add(stock_code)
    return passed


def collect_trajectories(start_date, end_date, verbose=True):
    """각 거래의 분봉별 수익률 궤적을 수집"""
    strategy = PricePositionStrategy()  # 현재 설정 (변동성 0.8%, 모멘텀 2.0%)

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'거래일: {len(trading_dates)}일')

    all_trades = []

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 수집 {len(all_trades)}건')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None
        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        screened = apply_screener_filter(daily_metrics, prev_close_map)
        if not screened:
            continue

        for stock_code in screened:
            try:
                cur.execute('''
                    SELECT idx, date, time, close, open, high, low, volume, amount
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s
                    ORDER BY idx
                ''', [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue

                columns = ['idx', 'date', 'time', 'close', 'open', 'high', 'low', 'volume', 'amount']
                df = pd.DataFrame(rows, columns=columns)

                day_open = daily_metrics[stock_code]['day_open']
                if day_open <= 0:
                    continue

                traded = False
                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    can_enter, _ = strategy.check_entry_conditions(
                        stock_code=stock_code, current_price=current_price,
                        day_open=day_open, current_time=current_time,
                        trade_date=trade_date, weekday=weekday,
                    )
                    if not can_enter:
                        continue

                    adv_ok, _ = strategy.check_advanced_conditions(df=df, candle_idx=candle_idx)
                    if not adv_ok:
                        continue

                    # 진입 확정
                    if candle_idx + 1 >= len(df) - 5:
                        continue

                    entry_price = df.iloc[candle_idx + 1]['open']
                    entry_time_str = str(df.iloc[candle_idx + 1]['time']).zfill(6)

                    if entry_price <= 0:
                        continue

                    # === 분봉별 궤적 추적 ===
                    max_profit = 0.0
                    max_profit_candle = 0
                    max_profit_time = entry_time_str
                    min_profit = 0.0  # 최대 드로다운
                    exit_reason = '장마감'
                    final_pnl = 0.0
                    exit_candle = 0

                    # 진입 전 거래량 (기준)
                    pre10 = df.iloc[max(0, candle_idx - 10):candle_idx]
                    avg_vol_pre = pre10['volume'].mean() if len(pre10) > 0 else 1

                    # 체크포인트별 수익률 (진입 후 N분)
                    checkpoints = {}  # {candle_offset: pnl}
                    # 거래량 체크포인트
                    vol_checkpoints = {}  # {candle_offset: volume_ratio}

                    # 최고점 이후 되돌림 추적
                    profit_after_peak = []  # (candle_offset, pnl, peak까지의 pnl)

                    holding_volumes = []

                    for i in range(candle_idx + 1, len(df)):
                        r = df.iloc[i]
                        offset = i - candle_idx  # 진입 후 캔들 수

                        high_pnl = (r['high'] / entry_price - 1) * 100
                        low_pnl = (r['low'] / entry_price - 1) * 100
                        close_pnl = (r['close'] / entry_price - 1) * 100

                        holding_volumes.append(r['volume'])

                        if high_pnl > max_profit:
                            max_profit = high_pnl
                            max_profit_candle = offset
                            max_profit_time = str(r['time']).zfill(6)

                        if low_pnl < min_profit:
                            min_profit = low_pnl

                        # 체크포인트 저장 (10, 20, 30, 60, 90, 120, 180분)
                        for cp in [10, 20, 30, 60, 90, 120, 180, 240]:
                            if offset == cp:
                                checkpoints[cp] = close_pnl
                                vol_ratio = r['volume'] / avg_vol_pre if avg_vol_pre > 0 else 1
                                vol_checkpoints[cp] = vol_ratio

                        # 익절 도달
                        if high_pnl >= 5.0:
                            exit_reason = '익절'
                            final_pnl = 5.0
                            exit_candle = offset
                            break

                        # 손절 도달
                        if low_pnl <= -4.0:
                            exit_reason = '손절'
                            final_pnl = -4.0
                            exit_candle = offset
                            break

                    else:
                        # 장마감
                        last = df.iloc[-1]
                        final_pnl = (last['close'] / entry_price - 1) * 100
                        exit_candle = len(df) - 1 - candle_idx

                    # 진입 전 변동성
                    pre_vol = 0
                    pre20 = df.iloc[max(0, candle_idx - 20):candle_idx]
                    if len(pre20) > 0:
                        pre_vol = ((pre20['high'] - pre20['low']) / pre20['low'].replace(0, np.nan) * 100).mean()
                        if np.isnan(pre_vol):
                            pre_vol = 0

                    # 보유 중 거래량 패턴
                    vol_first_half = 0
                    vol_second_half = 0
                    if len(holding_volumes) >= 4:
                        mid = len(holding_volumes) // 2
                        vol_first_half = np.mean(holding_volumes[:mid])
                        vol_second_half = np.mean(holding_volumes[mid:])

                    vol_decay = vol_second_half / vol_first_half if vol_first_half > 0 else 1.0

                    # 최고점 후 되돌림 비율
                    retracement_from_peak = max_profit - final_pnl if exit_reason != '익절' else 0

                    entry_hour = int(entry_time_str[:2])
                    pct_from_open = (current_price / day_open - 1) * 100

                    trade = {
                        'date': trade_date,
                        'stock_code': stock_code,
                        'weekday': weekday,
                        'entry_hour': entry_hour,
                        'entry_price': entry_price,
                        'pct_from_open': round(pct_from_open, 3),
                        'pre_volatility_20': round(pre_vol, 4),
                        'exit_reason': exit_reason,
                        'final_pnl': round(final_pnl, 3),
                        'max_profit': round(max_profit, 3),
                        'max_profit_candle': max_profit_candle,
                        'max_profit_time': max_profit_time,
                        'max_drawdown': round(min_profit, 3),
                        'holding_candles': exit_candle,
                        'retracement': round(retracement_from_peak, 3),
                        'vol_decay': round(vol_decay, 3),
                        'avg_vol_pre': round(avg_vol_pre, 1),
                    }

                    # 체크포인트 추가
                    for cp in [10, 20, 30, 60, 90, 120, 180, 240]:
                        trade[f'pnl_{cp}m'] = round(checkpoints.get(cp, np.nan), 3)
                        trade[f'vol_{cp}m'] = round(vol_checkpoints.get(cp, np.nan), 3)

                    all_trades.append(trade)
                    strategy.record_trade(stock_code, trade_date)
                    traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n수집 완료: {len(all_trades)}건')
    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


def analyze_trajectories(df):
    """궤적 패턴 분석"""
    tp = df[df['exit_reason'] == '익절']
    sl = df[df['exit_reason'] == '손절']
    mc = df[df['exit_reason'] == '장마감']

    print('\n' + '=' * 100)
    print(f'거래 궤적 분석 (총 {len(df)}건)')
    print(f'  익절: {len(tp)}건 ({len(tp)/len(df)*100:.1f}%)')
    print(f'  손절: {len(sl)}건 ({len(sl)/len(df)*100:.1f}%)')
    print(f'  장마감: {len(mc)}건 ({len(mc)/len(df)*100:.1f}%)')
    print('=' * 100)

    # === 1. 최대 수익률 분포 (익절 미도달 거래) ===
    non_tp = df[df['exit_reason'] != '익절']
    print('\n' + '-' * 80)
    print('[1] 익절 미도달 거래의 최대 수익률 분포')
    print('    -> "5%까지 못 갔지만, 최대 몇 %까지는 갔는가?"')
    print('-' * 80)

    bins = [(-999, 0), (0, 1), (1, 2), (2, 3), (3, 4), (4, 4.99)]
    for lo, hi in bins:
        mask = (non_tp['max_profit'] > lo) & (non_tp['max_profit'] <= hi)
        group = non_tp[mask]
        pct = len(group) / len(non_tp) * 100
        avg_final = group['final_pnl'].mean() if len(group) > 0 else 0
        avg_retrace = group['retracement'].mean() if len(group) > 0 else 0
        label = f'{lo:+.0f}~{hi:+.0f}%' if lo >= 0 else f'마이너스'
        print(f'  최대 {label:>12}: {len(group):>4}건 ({pct:>5.1f}%)  '
              f'최종PnL {avg_final:>+6.2f}%  되돌림 {avg_retrace:>5.2f}%p')

    # === 2. 최고점 도달 시간 ===
    print('\n' + '-' * 80)
    print('[2] 최고점 도달 시점 (진입 후 몇 캔들만에?)')
    print('-' * 80)

    for group_name, group_df in [('익절', tp), ('손절', sl), ('장마감', mc)]:
        if len(group_df) == 0:
            continue
        peak_candles = group_df['max_profit_candle']
        print(f'\n  [{group_name}] n={len(group_df)}')
        print(f'    평균 {peak_candles.mean():.0f}캔들, '
              f'중앙값 {peak_candles.median():.0f}캔들, '
              f'75% {peak_candles.quantile(0.75):.0f}캔들')

        # 시간대별
        for t, label in [(10, '~10분'), (30, '~30분'), (60, '~1시간'),
                         (120, '~2시간'), (999, '2시간+')]:
            prev_t = {10: 0, 30: 10, 60: 30, 120: 60, 999: 120}[t]
            mask = (peak_candles > prev_t) & (peak_candles <= t)
            cnt = mask.sum()
            pct = cnt / len(group_df) * 100
            print(f'    {label:>10}: {cnt:>4}건 ({pct:>5.1f}%)')

    # === 3. 되돌림(retracement) 분석 - 장마감 거래 ===
    print('\n' + '-' * 80)
    print('[3] 장마감 거래: 최고점 -> 최종가 되돌림')
    print('    -> "수익이 있었는데 놓친 금액"')
    print('-' * 80)

    if len(mc) > 0:
        mc_positive = mc[mc['max_profit'] > 0]
        print(f'  장마감 중 한 번이라도 양수: {len(mc_positive)}건 ({len(mc_positive)/len(mc)*100:.1f}%)')
        print(f'  평균 최대수익: {mc_positive["max_profit"].mean():+.2f}%')
        print(f'  평균 최종PnL: {mc_positive["final_pnl"].mean():+.2f}%')
        print(f'  평균 되돌림: {mc_positive["retracement"].mean():.2f}%p')

        # 최대수익 구간별 되돌림
        print(f'\n  최대수익 구간별:')
        for lo, hi in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]:
            mask = (mc['max_profit'] > lo) & (mc['max_profit'] <= hi)
            g = mc[mask]
            if len(g) == 0:
                continue
            print(f'    최대 +{lo}~+{hi}%: {len(g):>4}건  '
                  f'최종PnL {g["final_pnl"].mean():>+6.2f}%  '
                  f'되돌림 {g["retracement"].mean():>5.2f}%p  '
                  f'최종 양수 {(g["final_pnl"]>0).sum()/len(g)*100:>5.1f}%')

    # === 4. 시간 경과별 평균 수익률 (체크포인트) ===
    print('\n' + '-' * 80)
    print('[4] 진입 후 시간 경과별 평균 수익률')
    print('-' * 80)

    checkpoints = [10, 20, 30, 60, 90, 120, 180, 240]
    print(f'\n  {"시간":>8} {"익절(평균)":>10} {"손절(평균)":>10} {"장마감(평균)":>10} {"전체(평균)":>10}')
    for cp in checkpoints:
        col = f'pnl_{cp}m'
        if col not in df.columns:
            continue
        tp_val = tp[col].dropna().mean() if len(tp) > 0 else 0
        sl_val = sl[col].dropna().mean() if len(sl) > 0 else 0
        mc_val = mc[col].dropna().mean() if len(mc) > 0 else 0
        all_val = df[col].dropna().mean()
        print(f'  {cp:>5}분 {tp_val:>+10.3f}% {sl_val:>+10.3f}% {mc_val:>+10.3f}% {all_val:>+10.3f}%')

    # === 5. 거래량 감소 패턴 ===
    print('\n' + '-' * 80)
    print('[5] 보유 중 거래량 감소(vol_decay) vs 결과')
    print('    vol_decay = 보유 후반 거래량 / 보유 전반 거래량')
    print('-' * 80)

    for group_name, group_df in [('익절', tp), ('손절', sl), ('장마감', mc)]:
        if len(group_df) == 0:
            continue
        print(f'  [{group_name}] 평균 vol_decay: {group_df["vol_decay"].mean():.3f}  '
              f'중앙값: {group_df["vol_decay"].median():.3f}')

    # 장마감 거래를 vol_decay로 구간 분리
    if len(mc) > 0:
        print(f'\n  장마감 거래의 vol_decay 구간별 성과:')
        try:
            bins = pd.qcut(mc['vol_decay'], q=4, duplicates='drop')
            for label, group in mc.groupby(bins, observed=True):
                avg_pnl = group['final_pnl'].mean()
                avg_max = group['max_profit'].mean()
                print(f'    {str(label):<25} n={len(group):>4}  PnL {avg_pnl:>+6.2f}%  '
                      f'최대수익 {avg_max:>+5.2f}%')
        except Exception:
            pass

    # === 6. 시간별 체크포인트에서 수익률로 최종 결과 예측 ===
    print('\n' + '-' * 80)
    print('[6] "N분 후 수익률"로 최종 결과 예측')
    print('    -> 특정 시점의 수익률이 낮으면 조기 청산하는 게 유리한가?')
    print('-' * 80)

    for cp in [10, 20, 30, 60]:
        col = f'pnl_{cp}m'
        if col not in df.columns:
            continue

        valid = df[df[col].notna()].copy()
        if len(valid) < 50:
            continue

        print(f'\n  [{cp}분 후 수익률 기준]')
        try:
            bins_q = pd.qcut(valid[col], q=5, duplicates='drop')
            for label, group in valid.groupby(bins_q, observed=True):
                avg_final = group['final_pnl'].mean()
                tp_rate = (group['exit_reason'] == '익절').sum() / len(group) * 100
                sl_rate = (group['exit_reason'] == '손절').sum() / len(group) * 100
                print(f'    {str(label):<28} n={len(group):>4}  최종PnL {avg_final:>+6.2f}%  '
                      f'익절률 {tp_rate:>5.1f}%  손절률 {sl_rate:>5.1f}%')
        except Exception:
            pass

    # === 7. 트레일링 스탑 시뮬레이션 ===
    print('\n' + '-' * 80)
    print('[7] 트레일링 스탑 시뮬레이션')
    print('    -> 최대수익의 X%를 되돌리면 청산하는 전략 비교')
    print('-' * 80)

    # 장마감 거래에서 트레일링 적용 시 효과
    # 이건 체크포인트 데이터만으로는 부족하므로, max_profit과 final_pnl로 근사
    if len(mc) > 0:
        current_avg = mc['final_pnl'].mean()
        print(f'  현재(장마감 청산) 평균PnL: {current_avg:+.3f}%')
        print()

        # 트레일링 스탑 = "최대수익 - trail_pct 이하로 떨어지면 청산"
        # 여기서는 max_profit 기준으로 근사 (실제로는 분봉별 추적 필요)
        # max_profit >= threshold면 그 수익을 확보할 수 있었다고 가정
        for take_at in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
            # "최대수익이 take_at% 이상이면 그 시점에서 take_at%로 청산"
            improved = mc.copy()
            mask = improved['max_profit'] >= take_at
            improved.loc[mask, 'simulated_pnl'] = take_at
            improved.loc[~mask, 'simulated_pnl'] = improved.loc[~mask, 'final_pnl']
            new_avg = improved['simulated_pnl'].mean()
            delta = new_avg - current_avg
            caught = mask.sum()
            print(f'    +{take_at:.1f}% 도달 시 청산: '
                  f'적용 {caught:>4}건({caught/len(mc)*100:.1f}%)  '
                  f'평균PnL {new_avg:>+6.3f}% ({delta:>+6.3f}%p)')

    # === 8. 시간 기반 청산 시뮬레이션 ===
    print('\n' + '-' * 80)
    print('[8] 시간 기반 청산 시뮬레이션')
    print('    -> "N분 후 무조건 청산"하면 어떨까?')
    print('-' * 80)

    for cp in [30, 60, 90, 120, 180]:
        col = f'pnl_{cp}m'
        if col not in df.columns:
            continue

        # 이미 익절/손절된 건은 원래 pnl, 아직 보유중인 건은 체크포인트 pnl로 청산
        simulated = df.copy()
        # 아직 보유 중인 거래 (홀딩 캔들 > cp)
        still_holding = simulated['holding_candles'] > cp
        has_data = simulated[col].notna()
        force_exit = still_holding & has_data

        simulated.loc[force_exit, 'sim_pnl'] = simulated.loc[force_exit, col]
        simulated.loc[~force_exit, 'sim_pnl'] = simulated.loc[~force_exit, 'final_pnl']

        valid = simulated[simulated['sim_pnl'].notna()]
        if len(valid) == 0:
            continue

        avg_pnl = valid['sim_pnl'].mean()
        n_forced = force_exit.sum()
        current_avg = df['final_pnl'].mean()
        delta = avg_pnl - current_avg
        print(f'  {cp:>3}분 후 청산: 강제청산 {n_forced:>4}건  '
              f'평균PnL {avg_pnl:>+6.3f}% ({delta:>+6.3f}%p)')

    # === 9. 복합 전략: 체크포인트 수익률 기반 조기 청산 ===
    print('\n' + '-' * 80)
    print('[9] 조건부 조기 청산 시뮬레이션')
    print('    -> "N분 후 수익률이 X% 미만이면 청산"')
    print('-' * 80)

    current_avg = df['final_pnl'].mean()
    print(f'  기준선: 평균PnL {current_avg:+.3f}% (거래 {len(df)}건)')

    best_rules = []

    for cp in [20, 30, 60, 90, 120]:
        col = f'pnl_{cp}m'
        if col not in df.columns:
            continue

        for threshold in [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5]:
            simulated = df.copy()
            # 아직 보유 중 + 체크포인트 데이터 있음 + 수익률이 threshold 미만
            still_holding = simulated['holding_candles'] > cp
            has_data = simulated[col].notna()
            below_threshold = simulated[col] < threshold
            force_exit = still_holding & has_data & below_threshold

            simulated.loc[force_exit, 'sim_pnl'] = simulated.loc[force_exit, col]
            simulated.loc[~force_exit, 'sim_pnl'] = simulated.loc[~force_exit, 'final_pnl']

            valid = simulated[simulated['sim_pnl'].notna()]
            if len(valid) == 0:
                continue

            avg_pnl = valid['sim_pnl'].mean()
            n_forced = force_exit.sum()
            delta = avg_pnl - current_avg

            if delta > 0.01:  # 개선된 것만
                best_rules.append((cp, threshold, n_forced, avg_pnl, delta))

    best_rules.sort(key=lambda x: x[4], reverse=True)
    print(f'\n  개선되는 규칙 (상위 15개):')
    for cp, th, n_forced, avg_pnl, delta in best_rules[:15]:
        print(f'    {cp:>3}분 후 < {th:>+5.1f}% 이면 청산: '
              f'강제 {n_forced:>4}건  PnL {avg_pnl:>+6.3f}% ({delta:>+6.3f}%p)')

    # === 10. 거래량 급감 기반 청산 ===
    print('\n' + '-' * 80)
    print('[10] 거래량 패턴과 수익률 관계')
    print('-' * 80)

    for cp in [30, 60]:
        vol_col = f'vol_{cp}m'
        pnl_col = f'pnl_{cp}m'
        if vol_col not in df.columns or pnl_col not in df.columns:
            continue

        valid = df[df[vol_col].notna() & df[pnl_col].notna()].copy()
        if len(valid) < 50:
            continue

        print(f'\n  [{cp}분 후 거래량비율 구간별]')
        try:
            bins_q = pd.qcut(valid[vol_col], q=4, duplicates='drop')
            for label, group in valid.groupby(bins_q, observed=True):
                avg_final = group['final_pnl'].mean()
                avg_cp_pnl = group[pnl_col].mean()
                tp_rate = (group['exit_reason'] == '익절').sum() / len(group) * 100
                print(f'    거래량비 {str(label):<22} n={len(group):>4}  '
                      f'{cp}분PnL {avg_cp_pnl:>+5.2f}%  최종PnL {avg_final:>+5.2f}%  '
                      f'익절률 {tp_rate:>5.1f}%')
        except Exception:
            pass

    return df


def main():
    parser = argparse.ArgumentParser(description='익절 미도달 궤적 분석')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260223', help='종료일')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    trades_df = collect_trajectories(args.start, args.end, verbose=not args.quiet)

    if len(trades_df) == 0:
        print('거래 없음')
        return

    analyze_trajectories(trades_df)

    csv_path = f'trajectory_analysis_{args.start}_{args.end}.csv'
    trades_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f'\n데이터 저장: {csv_path}')


if __name__ == '__main__':
    main()
