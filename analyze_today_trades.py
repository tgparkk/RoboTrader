"""
시뮬 거래의 승/패 차이 분석 (기간 지정 가능)
"""

import duckdb
import pandas as pd
import numpy as np
from datetime import datetime
from core.strategies.price_position_strategy import PricePositionStrategy
import argparse


def collect_trades(start_date, end_date):
    """시뮬레이션 실행 + 분석 지표 수집"""
    strategy = PricePositionStrategy()
    conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)

    tables = conn.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name LIKE 'minute_%'
    """).fetchall()

    all_trades = []
    total_stocks = len(tables)

    for idx, t in enumerate(tables):
        if idx % 100 == 0:
            print(f'  {idx}/{total_stocks} 종목 처리 중...')

        table_name = t[0]
        stock_code = table_name.replace('minute_', '')

        try:
            date_cond = f"WHERE trade_date >= '{start_date}'"
            if end_date:
                date_cond += f" AND trade_date <= '{end_date}'"

            dates = conn.execute(f"""
                SELECT DISTINCT trade_date FROM {table_name}
                {date_cond}
                ORDER BY trade_date
            """).fetchall()

            for d in dates:
                trade_date = d[0]

                try:
                    dt = datetime.strptime(trade_date, '%Y%m%d')
                    weekday = dt.weekday()
                except:
                    continue

                df = conn.execute(f"""
                    SELECT * FROM {table_name}
                    WHERE trade_date = '{trade_date}'
                    ORDER BY idx
                """).fetchdf()

                if len(df) < 50:
                    continue

                day_open = df.iloc[0]['open']
                if day_open <= 0:
                    continue

                traded = False

                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    can_enter, reason = strategy.check_entry_conditions(
                        stock_code=stock_code,
                        current_price=current_price,
                        day_open=day_open,
                        current_time=current_time,
                        trade_date=trade_date,
                        weekday=weekday,
                    )

                    if not can_enter:
                        continue

                    result = strategy.simulate_trade(df, candle_idx)
                    if result:
                        pct_from_open = (current_price / day_open - 1) * 100

                        # === 분석 지표 ===
                        pre_start = max(0, candle_idx - 10)
                        pre_candles = df.iloc[pre_start:candle_idx]

                        # 진입 전 모멘텀
                        if len(pre_candles) >= 2:
                            pre_momentum = (pre_candles.iloc[-1]['close'] / pre_candles.iloc[0]['open'] - 1) * 100
                        else:
                            pre_momentum = 0

                        # 진입 전 변동성
                        if len(pre_candles) > 0:
                            pre_volatility = ((pre_candles['high'] - pre_candles['low']) / pre_candles['low'] * 100).mean()
                        else:
                            pre_volatility = 0

                        # 거래량 추세
                        if len(pre_candles) >= 10 and 'volume' in pre_candles.columns:
                            vol_first = pre_candles.iloc[:5]['volume'].mean()
                            vol_last = pre_candles.iloc[5:]['volume'].mean()
                            vol_trend = (vol_last / vol_first - 1) * 100 if vol_first > 0 else 0
                        else:
                            vol_trend = 0

                        # 진입 캔들 특성
                        entry_candle_body = (row['close'] - row['open']) / row['open'] * 100
                        entry_candle_range = (row['high'] - row['low']) / row['low'] * 100
                        candle_body_top = max(row['open'], row['close'])
                        upper_wick = (row['high'] - candle_body_top) / row['low'] * 100 if row['low'] > 0 else 0

                        # 가격대
                        price_level = current_price

                        # 장 시작 후 분
                        try:
                            entry_minutes = (int(str(current_time)[:2]) - 9) * 60 + int(str(current_time)[2:4])
                        except:
                            entry_minutes = 0

                        # 당일 고점 대비
                        candles_so_far = df.iloc[:candle_idx + 1]
                        day_high_so_far = candles_so_far['high'].max()
                        pct_from_day_high = (current_price / day_high_so_far - 1) * 100

                        # 거래량
                        entry_volume = row['volume'] if 'volume' in row.index else 0

                        # 직전 5봉 양봉 수
                        if len(pre_candles) >= 5:
                            last5 = pre_candles.iloc[-5:]
                            consecutive_green = sum(1 for _, c in last5.iterrows() if c['close'] > c['open'])
                        else:
                            consecutive_green = 0

                        # 당일 최대 하락폭
                        day_low_so_far = candles_so_far['low'].min()
                        max_drawdown_from_open = (day_low_so_far / day_open - 1) * 100

                        # 초반 30분 변동성
                        early_candles = df[df['time'].astype(str).str[:4].between('0900', '0929')]
                        if len(early_candles) > 0:
                            early_volatility = (early_candles['high'].max() - early_candles['low'].min()) / day_open * 100
                        else:
                            early_volatility = 0

                        # 진입 전 20봉 고점 대비 (더 넓은 범위)
                        pre20_start = max(0, candle_idx - 20)
                        pre20_candles = df.iloc[pre20_start:candle_idx]
                        if len(pre20_candles) > 0:
                            pre20_high = pre20_candles['high'].max()
                            pct_from_pre20_high = (current_price / pre20_high - 1) * 100
                        else:
                            pct_from_pre20_high = 0

                        # 진입 전 20봉 모멘텀
                        if len(pre20_candles) >= 2:
                            pre20_momentum = (pre20_candles.iloc[-1]['close'] / pre20_candles.iloc[0]['open'] - 1) * 100
                        else:
                            pre20_momentum = 0

                        trade = {
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'result': result['result'],
                            'pnl': result['pnl'],
                            'exit_reason': result['exit_reason'],
                            'entry_time': result['entry_time'],
                            'exit_time': result['exit_time'],
                            'entry_price': result['entry_price'],
                            'holding_candles': result['holding_candles'],
                            'pct_from_open': round(pct_from_open, 2),
                            'pre_momentum': round(pre_momentum, 2),
                            'pre20_momentum': round(pre20_momentum, 2),
                            'pre_volatility': round(pre_volatility, 3),
                            'vol_trend': round(vol_trend, 1),
                            'entry_candle_body': round(entry_candle_body, 3),
                            'entry_candle_range': round(entry_candle_range, 3),
                            'upper_wick': round(upper_wick, 3),
                            'price_level': price_level,
                            'entry_minutes': entry_minutes,
                            'pct_from_day_high': round(pct_from_day_high, 2),
                            'pct_from_pre20_high': round(pct_from_pre20_high, 2),
                            'entry_volume': entry_volume,
                            'consecutive_green': consecutive_green,
                            'max_drawdown_from_open': round(max_drawdown_from_open, 2),
                            'early_volatility': round(early_volatility, 2),
                        }
                        all_trades.append(trade)
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

        except Exception as e:
            continue

    conn.close()
    return all_trades


def analyze(start_date='20251209', end_date='20260209'):
    print(f'분석 기간: {start_date} ~ {end_date}')
    print('시뮬레이션 실행 중...')

    all_trades = collect_trades(start_date, end_date)

    if not all_trades:
        print("거래 없음")
        return

    df_trades = pd.DataFrame(all_trades)
    wins = df_trades[df_trades['result'] == 'WIN']
    losses = df_trades[df_trades['result'] == 'LOSS']

    print(f"\n{'='*80}")
    print(f"승/패 패턴 분석: {len(df_trades)}건 ({len(wins)}승 {len(losses)}패)")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"{'='*80}")

    # === 승 vs 패 비교 통계 ===
    metrics = [
        ('시가 대비 상승률 (%)', 'pct_from_open'),
        ('진입 전 10봉 모멘텀 (%)', 'pre_momentum'),
        ('진입 전 20봉 모멘텀 (%)', 'pre20_momentum'),
        ('진입 전 변동성 (%)', 'pre_volatility'),
        ('거래량 추세 (후반/전반 %)', 'vol_trend'),
        ('진입 캔들 몸통 (%)', 'entry_candle_body'),
        ('진입 캔들 범위 (%)', 'entry_candle_range'),
        ('윗꼬리 비율 (%)', 'upper_wick'),
        ('절대 가격 (원)', 'price_level'),
        ('장 시작 후 분', 'entry_minutes'),
        ('당일 고점 대비 (%)', 'pct_from_day_high'),
        ('진입 전 20봉 고점 대비 (%)', 'pct_from_pre20_high'),
        ('진입 캔들 거래량', 'entry_volume'),
        ('직전 5봉 양봉 수', 'consecutive_green'),
        ('당일 최대 하락폭 (%)', 'max_drawdown_from_open'),
        ('초반 30분 변동성 (%)', 'early_volatility'),
        ('보유 캔들 수', 'holding_candles'),
    ]

    print(f"\n{'지표':>30} {'승리 평균':>12} {'패배 평균':>12} {'차이':>10} {'유의':>4}")
    print(f"{'─'*75}")

    significant_features = []

    for label, col in metrics:
        w_mean = wins[col].mean()
        l_mean = losses[col].mean()
        diff = w_mean - l_mean

        total_std = df_trades[col].std()
        is_significant = abs(diff) > total_std * 0.3 if total_std > 0 else False
        sig_mark = "★" if is_significant else ""

        if is_significant:
            significant_features.append((label, col, w_mean, l_mean, diff))

        if col in ['price_level', 'entry_volume']:
            print(f"{label:>30} {w_mean:>12,.0f} {l_mean:>12,.0f} {diff:>+10,.0f} {sig_mark:>3}")
        else:
            print(f"{label:>30} {w_mean:>12.2f} {l_mean:>12.2f} {diff:>+10.2f} {sig_mark:>3}")

    # === 유의미한 차이점 요약 ===
    if significant_features:
        print(f"\n{'='*80}")
        print("★ 유의미한 차이점 요약")
        print(f"{'='*80}")
        for label, col, w_mean, l_mean, diff in significant_features:
            direction = "높을수록" if diff > 0 else "낮을수록"
            print(f"  - {label}: 승리={w_mean:.2f}, 패배={l_mean:.2f} → {direction} 유리")

    # === 청산 사유별 분석 ===
    print(f"\n{'='*80}")
    print("청산 사유별 분석")
    print(f"{'='*80}")
    for reason in df_trades['exit_reason'].unique():
        sub = df_trades[df_trades['exit_reason'] == reason]
        w = (sub['result'] == 'WIN').sum()
        l = (sub['result'] == 'LOSS').sum()
        avg_pnl = sub['pnl'].mean()
        print(f"\n  [{reason}] {len(sub)}건 ({w}승 {l}패, 평균 {avg_pnl:+.2f}%)")
        for label, col in metrics[:9]:
            m = sub[col].mean()
            if col in ['price_level', 'entry_volume']:
                print(f"    {label}: {m:,.0f}")
            else:
                print(f"    {label}: {m:.2f}")

    # === 시가 대비 구간별 승률 ===
    print(f"\n{'='*80}")
    print("시가 대비 상승률 구간별 승률")
    print(f"{'='*80}")
    bins = [2.0, 2.5, 3.0, 3.5, 4.0]
    for i in range(len(bins) - 1):
        low, high = bins[i], bins[i+1]
        sub = df_trades[(df_trades['pct_from_open'] >= low) & (df_trades['pct_from_open'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:.1f}% ~ {high:.1f}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 진입 전 모멘텀 구간별 ===
    print(f"\n{'='*80}")
    print("진입 전 10봉 모멘텀 구간별 승률")
    print(f"{'='*80}")
    momentum_bins = [-10, -1, -0.3, 0, 0.3, 1, 10]
    for i in range(len(momentum_bins) - 1):
        low, high = momentum_bins[i], momentum_bins[i+1]
        sub = df_trades[(df_trades['pre_momentum'] >= low) & (df_trades['pre_momentum'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:+.1f}% ~ {high:+.1f}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 진입 전 20봉 모멘텀 구간별 ===
    print(f"\n{'='*80}")
    print("진입 전 20봉 모멘텀 구간별 승률")
    print(f"{'='*80}")
    momentum_bins_20 = [-10, -2, -1, 0, 1, 2, 10]
    for i in range(len(momentum_bins_20) - 1):
        low, high = momentum_bins_20[i], momentum_bins_20[i+1]
        sub = df_trades[(df_trades['pre20_momentum'] >= low) & (df_trades['pre20_momentum'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:+.1f}% ~ {high:+.1f}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 거래량 추세 구간별 ===
    print(f"\n{'='*80}")
    print("거래량 추세 구간별 승률 (후반5봉/전반5봉)")
    print(f"{'='*80}")
    vol_bins = [-100, -50, -20, 0, 20, 50, 100, 500, 10000]
    for i in range(len(vol_bins) - 1):
        low, high = vol_bins[i], vol_bins[i+1]
        sub = df_trades[(df_trades['vol_trend'] >= low) & (df_trades['vol_trend'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:+d}% ~ {high:+d}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 진입 캔들 유형별 ===
    print(f"\n{'='*80}")
    print("진입 캔들 유형별 승률")
    print(f"{'='*80}")
    green = df_trades[df_trades['entry_candle_body'] > 0]
    red = df_trades[df_trades['entry_candle_body'] <= 0]
    if len(green) > 0:
        gw = (green['result'] == 'WIN').sum()
        print(f"  양봉 진입: {len(green)}건, {gw}승, 승률 {gw/len(green)*100:.0f}%, 평균 {green['pnl'].mean():+.2f}%")
    if len(red) > 0:
        rw = (red['result'] == 'WIN').sum()
        print(f"  음봉 진입: {len(red)}건, {rw}승, 승률 {rw/len(red)*100:.0f}%, 평균 {red['pnl'].mean():+.2f}%")

    # === 당일 고점 대비 ===
    print(f"\n{'='*80}")
    print("당일 고점 대비 위치별 승률")
    print(f"{'='*80}")
    high_bins = [-20, -2, -1, -0.5, -0.2, 0.01]
    for i in range(len(high_bins) - 1):
        low, high = high_bins[i], high_bins[i+1]
        sub = df_trades[(df_trades['pct_from_day_high'] >= low) & (df_trades['pct_from_day_high'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:+.1f}% ~ {high:+.1f}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 진입 전 20봉 고점 대비 ===
    print(f"\n{'='*80}")
    print("진입 전 20봉 고점 대비 위치별 승률")
    print(f"{'='*80}")
    pre20_bins = [-10, -2, -1, -0.5, -0.2, 0.01]
    for i in range(len(pre20_bins) - 1):
        low, high = pre20_bins[i], pre20_bins[i+1]
        sub = df_trades[(df_trades['pct_from_pre20_high'] >= low) & (df_trades['pct_from_pre20_high'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:+.1f}% ~ {high:+.1f}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 진입 전 변동성 구간별 ===
    print(f"\n{'='*80}")
    print("진입 전 변동성 구간별 승률")
    print(f"{'='*80}")
    vol_pct_bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0, 5.0]
    for i in range(len(vol_pct_bins) - 1):
        low, high = vol_pct_bins[i], vol_pct_bins[i+1]
        sub = df_trades[(df_trades['pre_volatility'] >= low) & (df_trades['pre_volatility'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:.1f}% ~ {high:.1f}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 초반 30분 변동성 구간별 ===
    print(f"\n{'='*80}")
    print("초반 30분 변동성 구간별 승률")
    print(f"{'='*80}")
    early_bins = [0, 2, 4, 6, 8, 10, 50]
    for i in range(len(early_bins) - 1):
        low, high = early_bins[i], early_bins[i+1]
        sub = df_trades[(df_trades['early_volatility'] >= low) & (df_trades['early_volatility'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:.0f}% ~ {high:.0f}%: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 가격대별 승률 ===
    print(f"\n{'='*80}")
    print("가격대별 승률")
    print(f"{'='*80}")
    price_bins = [0, 5000, 10000, 20000, 50000, 100000, 500000]
    for i in range(len(price_bins) - 1):
        low, high = price_bins[i], price_bins[i+1]
        sub = df_trades[(df_trades['price_level'] >= low) & (df_trades['price_level'] < high)]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {low:>6,}원 ~ {high:>6,}원: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 요일별 승률 ===
    print(f"\n{'='*80}")
    print("요일별 승률")
    print(f"{'='*80}")
    weekday_names = ['월', '화', '수', '목', '금']
    for wd in sorted(df_trades['weekday'].unique()):
        sub = df_trades[df_trades['weekday'] == wd]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {weekday_names[wd]}요일: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 시간대별 승률 ===
    print(f"\n{'='*80}")
    print("진입 시간대별 승률")
    print(f"{'='*80}")
    df_trades['hour'] = df_trades['entry_time'].apply(lambda x: int(str(x)[:2]))
    for h in sorted(df_trades['hour'].unique()):
        sub = df_trades[df_trades['hour'] == h]
        if len(sub) > 0:
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            print(f"  {h}시: {len(sub)}건, {w}승, 승률 {rate:.0f}%, 평균 {avg_pnl:+.2f}%")

    # === 복합 조건 탐색 ===
    print(f"\n{'='*80}")
    print("복합 조건별 승률 (유의미한 조합 탐색)")
    print(f"{'='*80}")

    # 각 조건 조합 테스트
    conditions = [
        ('모멘텀<-0.3% & 변동성>0.4%',
         (df_trades['pre_momentum'] < -0.3) & (df_trades['pre_volatility'] > 0.4)),
        ('모멘텀>0% & 거래량추세<20%',
         (df_trades['pre_momentum'] > 0) & (df_trades['vol_trend'] < 20)),
        ('고점이격>-0.5% & 양봉진입',
         (df_trades['pct_from_day_high'] >= -0.5) & (df_trades['entry_candle_body'] > 0)),
        ('고점이격<-1% & 모멘텀<0%',
         (df_trades['pct_from_day_high'] < -1) & (df_trades['pre_momentum'] < 0)),
        ('시가+2~3% & 모멘텀<0%',
         (df_trades['pct_from_open'] >= 2) & (df_trades['pct_from_open'] < 3) & (df_trades['pre_momentum'] < 0)),
        ('시가+3~4% & 모멘텀<0%',
         (df_trades['pct_from_open'] >= 3) & (df_trades['pct_from_open'] < 4) & (df_trades['pre_momentum'] < 0)),
        ('거래량추세>100% (급증)',
         df_trades['vol_trend'] > 100),
        ('거래량추세<0% (감소) & 양봉',
         (df_trades['vol_trend'] < 0) & (df_trades['entry_candle_body'] > 0)),
        ('초반변동>6% & 시가+3~4%',
         (df_trades['early_volatility'] > 6) & (df_trades['pct_from_open'] >= 3)),
        ('초반변동<4% & 시가+2~3%',
         (df_trades['early_volatility'] < 4) & (df_trades['pct_from_open'] >= 2) & (df_trades['pct_from_open'] < 3)),
        ('20봉고점<-1% (눌림)',
         df_trades['pct_from_pre20_high'] < -1),
        ('20봉고점>-0.5% (고점근처)',
         df_trades['pct_from_pre20_high'] >= -0.5),
    ]

    for name, mask in conditions:
        sub = df_trades[mask]
        if len(sub) >= 5:  # 최소 5건 이상
            w = (sub['result'] == 'WIN').sum()
            rate = w / len(sub) * 100
            avg_pnl = sub['pnl'].mean()
            total_pnl = sub['pnl'].sum()
            base_rate = len(wins) / len(df_trades) * 100
            improvement = rate - base_rate
            marker = "▲" if improvement > 5 else ("▼" if improvement < -5 else " ")
            print(f"  {marker} {name}: {len(sub)}건, {w}승, 승률 {rate:.0f}% ({improvement:+.0f}%), 평균 {avg_pnl:+.2f}%, 총 {total_pnl:+.1f}%")

    print(f"\n  (기준 승률: {len(wins)/len(df_trades)*100:.0f}%)")

    print('\nDone!')


def main():
    parser = argparse.ArgumentParser(description='승/패 패턴 분석')
    parser.add_argument('--start', default='20251209', help='시작일 (YYYYMMDD)')
    parser.add_argument('--end', default='20260209', help='종료일 (YYYYMMDD)')
    args = parser.parse_args()

    analyze(start_date=args.start, end_date=args.end)


if __name__ == '__main__':
    main()
