"""
익절(+5%) 도달 종목 vs 미도달 종목 특성 비교 분석

시뮬레이션을 실행하면서 거래별 다양한 피처를 수집하고,
익절 도달 그룹과 미도달 그룹의 통계적 차이를 분석합니다.
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
                'max_price': float(max_price),
                'min_price': float(min_price),
            }
    return metrics


def apply_screener_filter(daily_metrics, prev_close_map, top_n=60,
                          min_price=5000, max_price=500000,
                          min_amount=1_000_000_000, max_gap_pct=3.0):
    ranked = sorted(
        daily_metrics.items(),
        key=lambda x: x[1]['daily_amount'],
        reverse=True
    )[:top_n]

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


def extract_features(df, entry_idx, entry_price, day_open, prev_close, daily_metrics_item):
    """거래 진입 시점의 다양한 피처를 추출"""
    features = {}

    # === 1. 시간 관련 ===
    entry_candle = df.iloc[entry_idx + 1]  # 실제 체결 캔들
    entry_time_str = str(entry_candle['time']).zfill(6)
    entry_hour = int(entry_time_str[:2])
    entry_minute = int(entry_time_str[2:4])
    features['entry_hour'] = entry_hour
    features['entry_minute_of_day'] = entry_hour * 60 + entry_minute

    # === 2. 시가 대비 위치 ===
    signal_price = df.iloc[entry_idx]['close']
    features['pct_from_open'] = (signal_price / day_open - 1) * 100

    # === 3. 전일 종가 대비 (갭) ===
    if prev_close and prev_close > 0:
        features['gap_pct'] = (day_open / prev_close - 1) * 100
        features['pct_from_prev_close'] = (signal_price / prev_close - 1) * 100
    else:
        features['gap_pct'] = 0.0
        features['pct_from_prev_close'] = 0.0

    # === 4. 진입 전 변동성 (여러 윈도우) ===
    for window in [5, 10, 20]:
        start = max(0, entry_idx - window)
        pre = df.iloc[start:entry_idx]
        if len(pre) > 0:
            vol = ((pre['high'] - pre['low']) / pre['low'].replace(0, np.nan) * 100).mean()
            features[f'pre_volatility_{window}'] = round(vol, 4) if not np.isnan(vol) else 0.0
        else:
            features[f'pre_volatility_{window}'] = 0.0

    # === 5. 진입 전 모멘텀 (여러 윈도우) ===
    for window in [5, 10, 20]:
        start = max(0, entry_idx - window)
        pre = df.iloc[start:entry_idx]
        if len(pre) >= 2:
            mom = (pre.iloc[-1]['close'] / pre.iloc[0]['open'] - 1) * 100
            features[f'pre_momentum_{window}'] = round(mom, 4)
        else:
            features[f'pre_momentum_{window}'] = 0.0

    # === 6. 거래량 관련 ===
    # 진입 전 10봉 평균 거래량
    pre10 = df.iloc[max(0, entry_idx - 10):entry_idx]
    if len(pre10) > 0:
        avg_vol_pre10 = pre10['volume'].mean()
        features['avg_volume_pre10'] = avg_vol_pre10

        # 진입 캔들 거래량 vs 평균 (거래량 급증 비율)
        entry_volume = df.iloc[entry_idx]['volume']
        features['volume_ratio'] = entry_volume / avg_vol_pre10 if avg_vol_pre10 > 0 else 1.0

        # 진입 전 거래량 추세 (후반5봉 / 전반5봉)
        if len(pre10) >= 10:
            first_half = pre10.iloc[:5]['volume'].mean()
            second_half = pre10.iloc[5:]['volume'].mean()
            features['volume_trend'] = second_half / first_half if first_half > 0 else 1.0
        else:
            features['volume_trend'] = 1.0
    else:
        features['avg_volume_pre10'] = 0
        features['volume_ratio'] = 1.0
        features['volume_trend'] = 1.0

    # === 7. 진입 전 가격 패턴 ===
    pre20 = df.iloc[max(0, entry_idx - 20):entry_idx]
    if len(pre20) >= 5:
        # 양봉 비율 (close > open)
        bullish = (pre20['close'] > pre20['open']).sum()
        features['bullish_candle_ratio'] = bullish / len(pre20)

        # 진입 전 고가 대비 현재가 위치 (0~1, 1이면 최고점 부근)
        pre_high = pre20['high'].max()
        pre_low = pre20['low'].min()
        if pre_high > pre_low:
            features['price_position_in_range'] = (signal_price - pre_low) / (pre_high - pre_low)
        else:
            features['price_position_in_range'] = 0.5
    else:
        features['bullish_candle_ratio'] = 0.5
        features['price_position_in_range'] = 0.5

    # === 8. 거래대금 (일간) ===
    features['daily_amount'] = daily_metrics_item.get('daily_amount', 0)

    # === 9. 당일 가격 레인지 (시가 대비) ===
    # 진입 시점까지의 당일 고가/저가
    day_candles = df.iloc[:entry_idx + 1]
    if len(day_candles) > 0:
        day_high_so_far = day_candles['high'].max()
        day_low_so_far = day_candles['low'].min()
        features['day_range_pct'] = (day_high_so_far / day_low_so_far - 1) * 100 if day_low_so_far > 0 else 0
        features['pct_from_day_high'] = (signal_price / day_high_so_far - 1) * 100 if day_high_so_far > 0 else 0
    else:
        features['day_range_pct'] = 0
        features['pct_from_day_high'] = 0

    # === 10. 진입가 수준 (절대 가격대) ===
    features['entry_price'] = entry_price
    features['price_bucket'] = (
        '5k-10k' if entry_price < 10000 else
        '10k-30k' if entry_price < 30000 else
        '30k-50k' if entry_price < 50000 else
        '50k-100k' if entry_price < 100000 else
        '100k+'
    )

    return features


def simulate_with_features(start_date, end_date, verbose=True):
    """피처를 포함한 시뮬레이션 실행"""
    strategy = PricePositionStrategy()
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'총 거래일: {len(trading_dates)}일 ({start_date} ~ {end_date})')

    all_trades = []

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) 처리 중... 거래 {len(all_trades)}건')

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
                    SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s
                    ORDER BY idx
                ''', [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue

                columns = ['idx', 'date', 'time', 'close', 'open', 'high',
                           'low', 'volume', 'amount', 'datetime']
                df = pd.DataFrame(rows, columns=columns)

                day_open = daily_metrics[stock_code]['day_open']
                if day_open <= 0:
                    continue

                prev_close = prev_close_map.get(stock_code)
                traded = False

                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    can_enter, _ = strategy.check_entry_conditions(
                        stock_code=stock_code,
                        current_price=current_price,
                        day_open=day_open,
                        current_time=current_time,
                        trade_date=trade_date,
                        weekday=weekday,
                    )
                    if not can_enter:
                        continue

                    adv_ok, _ = strategy.check_advanced_conditions(df=df, candle_idx=candle_idx)
                    if not adv_ok:
                        continue

                    result = strategy.simulate_trade(df, candle_idx)
                    if result:
                        entry_price = result['entry_price']
                        features = extract_features(
                            df, candle_idx, entry_price, day_open,
                            prev_close, daily_metrics[stock_code]
                        )

                        trade_record = {
                            'date': trade_date,
                            'weekday': weekday,
                            'stock_code': stock_code,
                            **result,
                            **features,
                        }
                        all_trades.append(trade_record)
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    print(f'\n총 거래: {len(all_trades)}건')
    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


def analyze_features(trades_df):
    """익절 도달 vs 미도달 그룹 비교 분석"""
    tp = trades_df[trades_df['exit_reason'] == '익절'].copy()
    non_tp = trades_df[trades_df['exit_reason'] != '익절'].copy()

    # 손절과 장마감 분리
    sl = trades_df[trades_df['exit_reason'] == '손절'].copy()
    mc = trades_df[trades_df['exit_reason'] == '장마감'].copy()

    print('\n' + '=' * 90)
    print(f'익절 도달 특성 분석')
    print(f'  총 거래: {len(trades_df)}건')
    print(f'  익절: {len(tp)}건 ({len(tp)/len(trades_df)*100:.1f}%)')
    print(f'  손절: {len(sl)}건 ({len(sl)/len(trades_df)*100:.1f}%)')
    print(f'  장마감: {len(mc)}건 ({len(mc)/len(trades_df)*100:.1f}%)')
    print('=' * 90)

    # 비교할 수치형 피처 목록
    numeric_features = [
        ('entry_hour', '진입 시간(시)'),
        ('entry_minute_of_day', '진입 시간(분)'),
        ('pct_from_open', '시가 대비 상승률(%)'),
        ('gap_pct', '갭(%)'),
        ('pct_from_prev_close', '전일종가 대비(%)'),
        ('pre_volatility_5', '5봉 변동성(%)'),
        ('pre_volatility_10', '10봉 변동성(%)'),
        ('pre_volatility_20', '20봉 변동성(%)'),
        ('pre_momentum_5', '5봉 모멘텀(%)'),
        ('pre_momentum_10', '10봉 모멘텀(%)'),
        ('pre_momentum_20', '20봉 모멘텀(%)'),
        ('volume_ratio', '거래량 급증비율'),
        ('volume_trend', '거래량 추세(후/전)'),
        ('bullish_candle_ratio', '양봉 비율'),
        ('price_position_in_range', '레인지 내 위치(0~1)'),
        ('day_range_pct', '당일 변동폭(%)'),
        ('pct_from_day_high', '당일고가 대비(%)'),
        ('holding_candles', '보유 캔들 수'),
        ('max_profit_pct', '최대 수익률(%)'),
        ('entry_price', '진입가(원)'),
    ]

    print(f'\n{"피처":<25} {"익절(평균)":>12} {"손절(평균)":>12} {"장마감(평균)":>12} {"차이(익-손)":>12} {"판별력":>8}')
    print('-' * 90)

    feature_importance = []

    for feat_col, feat_name in numeric_features:
        if feat_col not in trades_df.columns:
            continue

        tp_mean = tp[feat_col].mean() if len(tp) > 0 else 0
        sl_mean = sl[feat_col].mean() if len(sl) > 0 else 0
        mc_mean = mc[feat_col].mean() if len(mc) > 0 else 0
        diff = tp_mean - sl_mean

        # 판별력 = |익절 평균 - 전체 평균| / 전체 표준편차
        overall_std = trades_df[feat_col].std()
        overall_mean = trades_df[feat_col].mean()
        discriminability = abs(tp_mean - overall_mean) / overall_std if overall_std > 0 else 0

        feature_importance.append((feat_name, feat_col, discriminability))

        print(f'{feat_name:<25} {tp_mean:>12.3f} {sl_mean:>12.3f} {mc_mean:>12.3f} {diff:>+12.3f} {discriminability:>8.3f}')

    # === 판별력 순위 ===
    print('\n' + '=' * 90)
    print('판별력 순위 (높을수록 익절 그룹을 잘 구분)')
    print('=' * 90)
    feature_importance.sort(key=lambda x: x[2], reverse=True)
    for rank, (name, col, disc) in enumerate(feature_importance, 1):
        bar = '#' * int(disc * 30)
        print(f'  {rank:2d}. {name:<25} {disc:.3f} {bar}')

    # === 분위수 분석 (상위 피처들) ===
    print('\n' + '=' * 90)
    print('상위 피처 분위수 비교 (익절 vs 손절)')
    print('=' * 90)

    top_features = feature_importance[:8]  # 상위 8개
    for name, col, _ in top_features:
        if col not in trades_df.columns or col in ('holding_candles', 'max_profit_pct'):
            continue

        print(f'\n  [{name}]')
        print(f'  {"분위":>8} {"익절":>10} {"손절":>10} {"장마감":>10}')

        for q, label in [(0.25, '25%'), (0.50, '50%'), (0.75, '75%')]:
            tp_q = tp[col].quantile(q) if len(tp) > 0 else 0
            sl_q = sl[col].quantile(q) if len(sl) > 0 else 0
            mc_q = mc[col].quantile(q) if len(mc) > 0 else 0
            print(f'  {label:>8} {tp_q:>10.3f} {sl_q:>10.3f} {mc_q:>10.3f}')

    # === 구간별 익절 확률 (상위 피처) ===
    print('\n' + '=' * 90)
    print('피처 구간별 익절 확률')
    print('=' * 90)

    is_tp = (trades_df['exit_reason'] == '익절').astype(int)

    for name, col, _ in top_features:
        if col not in trades_df.columns or col in ('holding_candles', 'max_profit_pct'):
            continue

        print(f'\n  [{name}]')
        try:
            bins = pd.qcut(trades_df[col], q=5, duplicates='drop')
            grouped = trades_df.groupby(bins, observed=True)
            for bin_label, group in grouped:
                tp_count = (group['exit_reason'] == '익절').sum()
                sl_count = (group['exit_reason'] == '손절').sum()
                total = len(group)
                tp_rate = tp_count / total * 100
                avg_pnl = group['pnl'].mean()
                print(f'    {str(bin_label):<30} n={total:>4}  익절 {tp_rate:>5.1f}%  '
                      f'손절 {sl_count/total*100:>5.1f}%  평균PnL {avg_pnl:>+6.2f}%')
        except Exception as e:
            print(f'    (분석 불가: {e})')

    # === 시간대별 분석 ===
    print('\n' + '=' * 90)
    print('진입 시간대별 익절 확률')
    print('=' * 90)
    for hour in sorted(trades_df['entry_hour'].unique()):
        h_trades = trades_df[trades_df['entry_hour'] == hour]
        tp_rate = (h_trades['exit_reason'] == '익절').sum() / len(h_trades) * 100
        sl_rate = (h_trades['exit_reason'] == '손절').sum() / len(h_trades) * 100
        avg_pnl = h_trades['pnl'].mean()
        print(f'  {hour}시: {len(h_trades):>4}건  익절 {tp_rate:>5.1f}%  손절 {sl_rate:>5.1f}%  '
              f'평균PnL {avg_pnl:>+6.2f}%')

    # === 가격대별 분석 ===
    print('\n' + '=' * 90)
    print('가격대별 익절 확률')
    print('=' * 90)
    for bucket in ['5k-10k', '10k-30k', '30k-50k', '50k-100k', '100k+']:
        b_trades = trades_df[trades_df['price_bucket'] == bucket]
        if len(b_trades) == 0:
            continue
        tp_rate = (b_trades['exit_reason'] == '익절').sum() / len(b_trades) * 100
        sl_rate = (b_trades['exit_reason'] == '손절').sum() / len(b_trades) * 100
        avg_pnl = b_trades['pnl'].mean()
        print(f'  {bucket:<12}: {len(b_trades):>4}건  익절 {tp_rate:>5.1f}%  손절 {sl_rate:>5.1f}%  '
              f'평균PnL {avg_pnl:>+6.2f}%')

    # === 요일별 분석 ===
    print('\n' + '=' * 90)
    print('요일별 익절 확률')
    print('=' * 90)
    weekday_names = ['월', '화', '수', '목', '금']
    for wd in sorted(trades_df['weekday'].unique()):
        w_trades = trades_df[trades_df['weekday'] == wd]
        tp_rate = (w_trades['exit_reason'] == '익절').sum() / len(w_trades) * 100
        sl_rate = (w_trades['exit_reason'] == '손절').sum() / len(w_trades) * 100
        avg_pnl = w_trades['pnl'].mean()
        print(f'  {weekday_names[wd]}: {len(w_trades):>4}건  익절 {tp_rate:>5.1f}%  손절 {sl_rate:>5.1f}%  '
              f'평균PnL {avg_pnl:>+6.2f}%')

    # === 복합 조건 탐색 ===
    print('\n' + '=' * 90)
    print('복합 조건 탐색 (상위 피처 조합)')
    print('=' * 90)

    base_tp_rate = len(tp) / len(trades_df) * 100
    base_avg_pnl = trades_df['pnl'].mean()
    print(f'  기준선: 익절률 {base_tp_rate:.1f}%, 평균PnL {base_avg_pnl:+.2f}%\n')

    # 각 피처의 유리한 방향을 자동으로 판단하여 필터 조합 탐색
    conditions = []

    # 상위 피처 기준 유리한 구간 찾기
    for name, col, disc in feature_importance[:6]:
        if col in ('holding_candles', 'max_profit_pct') or col not in trades_df.columns:
            continue
        if disc < 0.05:
            continue

        tp_median = tp[col].median()
        sl_median = sl[col].median()

        # 익절 중앙값이 높으면 >= 조건, 낮으면 <= 조건
        if tp_median > sl_median:
            threshold = trades_df[col].quantile(0.6)  # 상위 40%
            mask = trades_df[col] >= threshold
            label = f'{name} >= {threshold:.3f}'
        else:
            threshold = trades_df[col].quantile(0.4)  # 하위 40%
            mask = trades_df[col] <= threshold
            label = f'{name} <= {threshold:.3f}'

        filtered = trades_df[mask]
        if len(filtered) >= 20:
            f_tp_rate = (filtered['exit_reason'] == '익절').sum() / len(filtered) * 100
            f_avg_pnl = filtered['pnl'].mean()
            conditions.append((label, mask, f_tp_rate, f_avg_pnl, len(filtered)))

    # 단일 조건 결과
    print('  [단일 조건]')
    conditions.sort(key=lambda x: x[3], reverse=True)
    for label, mask, tp_rate, avg_pnl, n in conditions:
        delta_tp = tp_rate - base_tp_rate
        delta_pnl = avg_pnl - base_avg_pnl
        print(f'    {label:<40} n={n:>4}  익절 {tp_rate:>5.1f}% ({delta_tp:>+5.1f})  '
              f'PnL {avg_pnl:>+6.2f}% ({delta_pnl:>+5.2f})')

    # 2개 조합
    print(f'\n  [2개 조합] (최소 20건)')
    combos = []
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            combined_mask = conditions[i][1] & conditions[j][1]
            filtered = trades_df[combined_mask]
            if len(filtered) >= 20:
                f_tp_rate = (filtered['exit_reason'] == '익절').sum() / len(filtered) * 100
                f_avg_pnl = filtered['pnl'].mean()
                combo_label = f'{conditions[i][0]} + {conditions[j][0]}'
                combos.append((combo_label, f_tp_rate, f_avg_pnl, len(filtered)))

    combos.sort(key=lambda x: x[2], reverse=True)
    for label, tp_rate, avg_pnl, n in combos[:10]:
        delta_tp = tp_rate - base_tp_rate
        delta_pnl = avg_pnl - base_avg_pnl
        print(f'    {label}')
        print(f'      n={n:>4}  익절 {tp_rate:>5.1f}% ({delta_tp:>+5.1f})  '
              f'PnL {avg_pnl:>+6.2f}% ({delta_pnl:>+5.2f})')

    return trades_df


def main():
    parser = argparse.ArgumentParser(description='익절 도달 특성 분석')
    parser.add_argument('--start', default='20250224', help='시작일')
    parser.add_argument('--end', default='20260223', help='종료일')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    trades_df = simulate_with_features(args.start, args.end, verbose=not args.quiet)

    if len(trades_df) == 0:
        print('거래 없음')
        return

    analyze_features(trades_df)

    # CSV 저장
    output_path = f'take_profit_analysis_{args.start}_{args.end}.csv'
    trades_df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f'\n거래 데이터 저장: {output_path}')


if __name__ == '__main__':
    main()
