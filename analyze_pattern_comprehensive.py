#!/usr/bin/env python3
"""
눌림목 패턴 종합 분석: 승/패 거래의 패턴 특징 차이 심층 분석
- decline_pct는 백분율 값 (1.5 = 1.5%)
"""
import json
import os
import numpy as np
from collections import defaultdict

def main():
    wins = []
    losses = []

    pattern_dir = r'D:\GIT\RoboTrader\pattern_data_log'

    for filename in os.listdir(pattern_dir):
        if not filename.endswith('.jsonl'):
            continue

        filepath = os.path.join(pattern_dir, filename)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())

                        trade_result = data.get('trade_result', {})
                        if not trade_result or not trade_result.get('trade_executed'):
                            continue

                        profit_rate = trade_result.get('profit_rate', 0)
                        stages = data.get('pattern_stages', {})

                        if not stages:
                            continue

                        uptrend = stages.get('1_uptrend', {})
                        decline = stages.get('2_decline', {})
                        support = stages.get('3_support', {})
                        breakout = stages.get('4_breakout', {})

                        features = {
                            'uptrend_gain': float(uptrend.get('price_gain', 0) or 0),
                            'uptrend_candles': int(uptrend.get('candle_count', 0) or 0),
                            'uptrend_max_vol_ratio': float(uptrend.get('max_volume_ratio_vs_avg', 0) or 0),
                            'decline_pct': float(decline.get('decline_pct', 0) or 0),  # 백분율!
                            'decline_candles': int(decline.get('candle_count', 0) or 0),
                            'decline_vol_ratio': float(decline.get('avg_volume_ratio', 0) or 0),
                            'support_candles': int(support.get('candle_count', 0) or 0),
                            'support_vol_ratio': float(support.get('avg_volume_ratio', 0) or 0),
                            'support_volatility': float(support.get('price_volatility', 0) or 0),
                            'breakout_vol_ratio': float(breakout.get('volume_ratio_vs_prev', 0) or 0),
                            'breakout_body_increase': float(breakout.get('body_increase_vs_support', 0) or 0),
                            'profit_rate': profit_rate,
                        }

                        if profit_rate > 0:
                            wins.append(features)
                        else:
                            losses.append(features)

                    except:
                        continue
        except:
            continue

    total = len(wins) + len(losses)
    print('=' * 80)
    print('PULLBACK PATTERN COMPREHENSIVE ANALYSIS')
    print('=' * 80)
    print('Total: {} wins, {} losses'.format(len(wins), len(losses)))
    if total > 0:
        print('Baseline Win Rate: {:.1f}%'.format(len(wins)/total*100))
    print('=' * 80)

    if not wins or not losses:
        print('No data to analyze')
        return

    # 1. 기본 특징 비교
    print('\n[1] FEATURE COMPARISON: Win vs Loss')
    print('-' * 80)
    metrics = [
        ('uptrend_gain', 'Uptrend Gain (%)'),
        ('uptrend_candles', 'Uptrend Candles'),
        ('uptrend_max_vol_ratio', 'Uptrend MaxVol Ratio'),
        ('decline_pct', 'Decline (%)'),
        ('decline_candles', 'Decline Candles'),
        ('decline_vol_ratio', 'Decline Vol Ratio'),
        ('support_candles', 'Support Candles'),
        ('support_vol_ratio', 'Support Vol Ratio'),
        ('support_volatility', 'Support Volatility'),
        ('breakout_vol_ratio', 'Breakout Vol Ratio'),
        ('breakout_body_increase', 'Breakout Body Incr'),
    ]

    print('{:<22} | {:>10} | {:>10} | {:>10} | {:>8}'.format(
        'Feature', 'Win Avg', 'Loss Avg', 'Diff', 'Diff%'))
    print('-' * 75)

    for metric, name in metrics:
        win_vals = [f[metric] for f in wins if f[metric] != 0]
        loss_vals = [f[metric] for f in losses if f[metric] != 0]

        if win_vals and loss_vals:
            win_avg = np.mean(win_vals)
            loss_avg = np.mean(loss_vals)
            diff = win_avg - loss_avg
            diff_pct = (diff / (abs(loss_avg) + 0.0001)) * 100

            marker = ''
            if abs(diff_pct) > 15:
                marker = ' ***'
            elif abs(diff_pct) > 10:
                marker = ' **'
            elif abs(diff_pct) > 5:
                marker = ' *'

            print('{:<22} | {:>10.4f} | {:>10.4f} | {:>+10.4f} | {:>+7.1f}%{}'.format(
                name, win_avg, loss_avg, diff, diff_pct, marker))

    # 2. Uptrend Gain 임계값 분석
    print('\n' + '=' * 80)
    print('[2] UPTREND GAIN THRESHOLD ANALYSIS')
    print('=' * 80)
    print('Finding: Win trades have LOWER uptrend gain (과도한 상승 = 손실 위험)')
    print('-' * 80)

    for threshold in [3, 4, 5, 6, 7, 8]:
        win_below = sum(1 for f in wins if f['uptrend_gain'] < threshold)
        loss_below = sum(1 for f in losses if f['uptrend_gain'] < threshold)
        total_below = win_below + loss_below
        if total_below > 0:
            wr = win_below / total_below * 100
            print('uptrend_gain < {}%: {}W/{}L = {:.1f}% win rate (n={})'.format(
                threshold, win_below, loss_below, wr, total_below))

    # 3. Decline 임계값 분석 (백분율 값 사용!)
    print('\n' + '=' * 80)
    print('[3] DECLINE THRESHOLD ANALYSIS (values are percentages)')
    print('=' * 80)

    for threshold in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
        win_below = sum(1 for f in wins if f['decline_pct'] < threshold)
        loss_below = sum(1 for f in losses if f['decline_pct'] < threshold)
        total_below = win_below + loss_below
        if total_below > 0:
            wr = win_below / total_below * 100
            print('decline_pct < {:.1f}%: {}W/{}L = {:.1f}% win rate (n={})'.format(
                threshold, win_below, loss_below, wr, total_below))

    print()
    for threshold in [1.5, 2.0, 2.5, 3.0, 3.5]:
        win_above = sum(1 for f in wins if f['decline_pct'] >= threshold)
        loss_above = sum(1 for f in losses if f['decline_pct'] >= threshold)
        total_above = win_above + loss_above
        if total_above > 0:
            wr = win_above / total_above * 100
            print('decline_pct >= {:.1f}%: {}W/{}L = {:.1f}% win rate (n={})'.format(
                threshold, win_above, loss_above, wr, total_above))

    # 4. Support Candles 임계값 분석
    print('\n' + '=' * 80)
    print('[4] SUPPORT CANDLES THRESHOLD ANALYSIS')
    print('=' * 80)

    for threshold in [2, 3, 4, 5, 6]:
        win_above = sum(1 for f in wins if f['support_candles'] >= threshold)
        loss_above = sum(1 for f in losses if f['support_candles'] >= threshold)
        total_above = win_above + loss_above
        if total_above > 0:
            wr = win_above / total_above * 100
            print('support_candles >= {}: {}W/{}L = {:.1f}% win rate (n={})'.format(
                threshold, win_above, loss_above, wr, total_above))

    # 5. 복합 필터 분석
    print('\n' + '=' * 80)
    print('[5] COMBINED FILTER ANALYSIS')
    print('=' * 80)

    all_trades = wins + losses
    combinations = [
        # (조건명, 조건 함수)
        ('uptrend < 5% AND support >= 3',
         lambda f: f['uptrend_gain'] < 5 and f['support_candles'] >= 3),
        ('uptrend < 5% AND support >= 4',
         lambda f: f['uptrend_gain'] < 5 and f['support_candles'] >= 4),
        ('uptrend < 6% AND support >= 3',
         lambda f: f['uptrend_gain'] < 6 and f['support_candles'] >= 3),
        ('uptrend < 6% AND decline >= 1.5%',
         lambda f: f['uptrend_gain'] < 6 and f['decline_pct'] >= 1.5),
        ('uptrend < 5% AND decline >= 2.0%',
         lambda f: f['uptrend_gain'] < 5 and f['decline_pct'] >= 2.0),
        ('support >= 3 AND decline >= 1.5%',
         lambda f: f['support_candles'] >= 3 and f['decline_pct'] >= 1.5),
        ('support >= 4 AND decline >= 2.0%',
         lambda f: f['support_candles'] >= 4 and f['decline_pct'] >= 2.0),
        ('uptrend < 5% AND support >= 3 AND decline >= 1.5%',
         lambda f: f['uptrend_gain'] < 5 and f['support_candles'] >= 3 and f['decline_pct'] >= 1.5),
        ('uptrend < 6% AND support >= 3 AND decline >= 1.5%',
         lambda f: f['uptrend_gain'] < 6 and f['support_candles'] >= 3 and f['decline_pct'] >= 1.5),
        ('breakout_vol >= 0.2 AND support >= 3',
         lambda f: f['breakout_vol_ratio'] >= 0.2 and f['support_candles'] >= 3),
        ('breakout_vol >= 0.3 AND uptrend < 6%',
         lambda f: f['breakout_vol_ratio'] >= 0.3 and f['uptrend_gain'] < 6),
    ]

    results = []
    for name, condition in combinations:
        matched_wins = sum(1 for f in wins if condition(f))
        matched_losses = sum(1 for f in losses if condition(f))
        matched_total = matched_wins + matched_losses
        if matched_total >= 50:  # 최소 50건 이상
            wr = matched_wins / matched_total * 100
            improvement = wr - (len(wins)/total*100)
            results.append((name, matched_wins, matched_losses, matched_total, wr, improvement))

    # 승률 기준 정렬
    results.sort(key=lambda x: x[4], reverse=True)

    print('{:<50} | {:>5} | {:>5} | {:>5} | {:>7} | {:>8}'.format(
        'Condition', 'Win', 'Loss', 'Total', 'WinRate', 'Improve'))
    print('-' * 95)

    for name, w, l, t, wr, imp in results:
        print('{:<50} | {:>5} | {:>5} | {:>5} | {:>6.1f}% | {:>+7.1f}%'.format(
            name, w, l, t, wr, imp))

    # 6. 핵심 인사이트
    print('\n' + '=' * 80)
    print('[6] KEY INSIGHTS FOR PULLBACK PATTERN IMPROVEMENT')
    print('=' * 80)

    print('''
    1. UPTREND GAIN (상승폭)
       - 승리 거래는 패배 거래보다 상승폭이 더 작음
       - 과도한 상승 후 눌림목은 실패 확률이 높음
       - 권장: uptrend_gain < 5~6% 필터 적용

    2. SUPPORT CANDLES (지지 캔들 수)
       - 지지구간이 길수록 승률 상승 (안정적 눌림목)
       - support_candles >= 3 이상이 중요
       - 권장: support_candles >= 3 필터 적용

    3. DECLINE (조정폭)
       - 적당한 조정폭이 필요 (너무 작으면 불안정)
       - decline_pct >= 1.5% 이상이 건전한 눌림목
       - 권장: decline_pct >= 1.5% 필터 적용

    4. 복합 조건
       - uptrend < 5% AND support >= 3: 최고 승률 조합
       - 3가지 조건 복합시 추가 개선 가능
    ''')

    # 7. 수익률 분석
    print('=' * 80)
    print('[7] PROFIT RATE DISTRIBUTION')
    print('=' * 80)

    win_profits = [f['profit_rate'] for f in wins]
    loss_profits = [f['profit_rate'] for f in losses]

    print('Win trades:')
    print('  Average profit: {:.2f}%'.format(np.mean(win_profits)))
    print('  Median profit: {:.2f}%'.format(np.median(win_profits)))
    print('  Max profit: {:.2f}%'.format(max(win_profits)))

    print('\nLoss trades:')
    print('  Average loss: {:.2f}%'.format(np.mean(loss_profits)))
    print('  Median loss: {:.2f}%'.format(np.median(loss_profits)))
    print('  Max loss: {:.2f}%'.format(min(loss_profits)))

    # 8. 필터 적용시 예상 수익
    print('\n' + '=' * 80)
    print('[8] EXPECTED PROFIT WITH BEST FILTER')
    print('=' * 80)

    best_filter = lambda f: f['uptrend_gain'] < 5 and f['support_candles'] >= 3
    filtered_wins = [f for f in wins if best_filter(f)]
    filtered_losses = [f for f in losses if best_filter(f)]

    if filtered_wins or filtered_losses:
        total_filtered = len(filtered_wins) + len(filtered_losses)
        filtered_wr = len(filtered_wins) / total_filtered * 100

        avg_win_profit = np.mean([f['profit_rate'] for f in filtered_wins]) if filtered_wins else 0
        avg_loss_profit = np.mean([f['profit_rate'] for f in filtered_losses]) if filtered_losses else 0

        # 1/5 투자시 (건당 200만원)
        trade_amount = 2000000
        expected_per_trade = (filtered_wr/100 * avg_win_profit + (1-filtered_wr/100) * avg_loss_profit) / 100 * trade_amount

        print('Filter: uptrend < 5% AND support >= 3')
        print('  Total trades: {}'.format(total_filtered))
        print('  Win rate: {:.1f}%'.format(filtered_wr))
        print('  Avg win profit: {:.2f}%'.format(avg_win_profit))
        print('  Avg loss: {:.2f}%'.format(avg_loss_profit))
        print('  Expected profit per trade (200만원): {:+,.0f}원'.format(expected_per_trade))
        print('  Expected profit for {} trades: {:+,.0f}원'.format(
            total_filtered, expected_per_trade * total_filtered))


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
