#!/usr/bin/env python3
"""
눌림목 패턴 종합 분석 v2
- uptrend_gain: 소수 (0.05 = 5%)
- decline_pct: 백분율 (1.5 = 1.5%)
"""
import json
import os
import numpy as np

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

                        # uptrend_gain은 소수 (0.05 = 5%)
                        uptrend_gain_pct = float(uptrend.get('price_gain', 0) or 0) * 100

                        features = {
                            'uptrend_gain_pct': uptrend_gain_pct,  # 백분율로 변환
                            'uptrend_candles': int(uptrend.get('candle_count', 0) or 0),
                            'uptrend_max_vol_ratio': float(uptrend.get('max_volume_ratio_vs_avg', 0) or 0),
                            'decline_pct': float(decline.get('decline_pct', 0) or 0),
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
    baseline_wr = len(wins)/total*100 if total > 0 else 0

    print('=' * 80)
    print('PULLBACK PATTERN COMPREHENSIVE ANALYSIS v2')
    print('=' * 80)
    print('Total: {} wins, {} losses'.format(len(wins), len(losses)))
    print('Baseline Win Rate: {:.1f}%'.format(baseline_wr))
    print('=' * 80)

    if not wins or not losses:
        print('No data to analyze')
        return

    # 1. 기본 특징 비교 (수정된 단위)
    print('\n[1] FEATURE COMPARISON: Win vs Loss')
    print('-' * 80)

    metrics = [
        ('uptrend_gain_pct', 'Uptrend Gain (%)'),
        ('uptrend_candles', 'Uptrend Candles'),
        ('decline_pct', 'Decline (%)'),
        ('decline_candles', 'Decline Candles'),
        ('support_candles', 'Support Candles'),
        ('support_vol_ratio', 'Support Vol Ratio'),
        ('breakout_vol_ratio', 'Breakout Vol Ratio'),
    ]

    print('{:<22} | {:>10} | {:>10} | {:>10} | {:>8}'.format(
        'Feature', 'Win Avg', 'Loss Avg', 'Diff', 'Diff%'))
    print('-' * 75)

    for metric, name in metrics:
        win_vals = [f[metric] for f in wins]
        loss_vals = [f[metric] for f in losses]

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

        print('{:<22} | {:>10.2f} | {:>10.2f} | {:>+10.2f} | {:>+7.1f}%{}'.format(
            name, win_avg, loss_avg, diff, diff_pct, marker))

    # 2. Uptrend Gain 분석 (올바른 백분율 임계값)
    print('\n' + '=' * 80)
    print('[2] UPTREND GAIN THRESHOLD ANALYSIS')
    print('=' * 80)
    print('>> Win trades have LOWER uptrend gain')
    print('-' * 80)

    for threshold in [3, 4, 5, 6, 7, 8, 10]:
        win_below = sum(1 for f in wins if f['uptrend_gain_pct'] < threshold)
        loss_below = sum(1 for f in losses if f['uptrend_gain_pct'] < threshold)
        total_below = win_below + loss_below
        if total_below >= 30:
            wr = win_below / total_below * 100
            improvement = wr - baseline_wr
            print('uptrend_gain < {}%: {}W/{}L = {:.1f}% ({:+.1f}%)'.format(
                threshold, win_below, loss_below, wr, improvement))

    print()
    for threshold in [5, 6, 7, 8, 10]:
        win_above = sum(1 for f in wins if f['uptrend_gain_pct'] >= threshold)
        loss_above = sum(1 for f in losses if f['uptrend_gain_pct'] >= threshold)
        total_above = win_above + loss_above
        if total_above >= 30:
            wr = win_above / total_above * 100
            improvement = wr - baseline_wr
            print('uptrend_gain >= {}%: {}W/{}L = {:.1f}% ({:+.1f}%)'.format(
                threshold, win_above, loss_above, wr, improvement))

    # 3. Decline 분석
    print('\n' + '=' * 80)
    print('[3] DECLINE THRESHOLD ANALYSIS')
    print('=' * 80)
    print('>> Lower decline shows higher win rate!')
    print('-' * 80)

    for threshold in [1.0, 1.5, 2.0, 2.5, 3.0]:
        win_below = sum(1 for f in wins if f['decline_pct'] < threshold)
        loss_below = sum(1 for f in losses if f['decline_pct'] < threshold)
        total_below = win_below + loss_below
        if total_below >= 30:
            wr = win_below / total_below * 100
            improvement = wr - baseline_wr
            print('decline_pct < {:.1f}%: {}W/{}L = {:.1f}% ({:+.1f}%)'.format(
                threshold, win_below, loss_below, wr, improvement))

    # 4. Support Candles 분석
    print('\n' + '=' * 80)
    print('[4] SUPPORT CANDLES THRESHOLD ANALYSIS')
    print('=' * 80)

    for threshold in [2, 3, 4, 5]:
        win_match = sum(1 for f in wins if f['support_candles'] >= threshold)
        loss_match = sum(1 for f in losses if f['support_candles'] >= threshold)
        total_match = win_match + loss_match
        if total_match >= 30:
            wr = win_match / total_match * 100
            improvement = wr - baseline_wr
            print('support_candles >= {}: {}W/{}L = {:.1f}% ({:+.1f}%)'.format(
                threshold, win_match, loss_match, wr, improvement))

    # 5. 복합 필터 분석 (수정된 임계값)
    print('\n' + '=' * 80)
    print('[5] COMBINED FILTER ANALYSIS')
    print('=' * 80)

    combinations = [
        # 단일 필터
        ('uptrend < 5%', lambda f: f['uptrend_gain_pct'] < 5),
        ('uptrend < 6%', lambda f: f['uptrend_gain_pct'] < 6),
        ('decline < 1.5%', lambda f: f['decline_pct'] < 1.5),
        ('decline < 2.0%', lambda f: f['decline_pct'] < 2.0),
        ('support >= 4', lambda f: f['support_candles'] >= 4),

        # 복합 필터 - 상승폭 제한 + 지지
        ('uptrend < 5% AND support >= 3',
         lambda f: f['uptrend_gain_pct'] < 5 and f['support_candles'] >= 3),
        ('uptrend < 5% AND support >= 4',
         lambda f: f['uptrend_gain_pct'] < 5 and f['support_candles'] >= 4),
        ('uptrend < 6% AND support >= 4',
         lambda f: f['uptrend_gain_pct'] < 6 and f['support_candles'] >= 4),

        # 복합 필터 - 상승폭 제한 + 조정폭 제한
        ('uptrend < 5% AND decline < 1.5%',
         lambda f: f['uptrend_gain_pct'] < 5 and f['decline_pct'] < 1.5),
        ('uptrend < 6% AND decline < 2.0%',
         lambda f: f['uptrend_gain_pct'] < 6 and f['decline_pct'] < 2.0),

        # 복합 필터 - 지지 + 조정폭
        ('support >= 4 AND decline < 1.5%',
         lambda f: f['support_candles'] >= 4 and f['decline_pct'] < 1.5),
        ('support >= 4 AND decline < 2.0%',
         lambda f: f['support_candles'] >= 4 and f['decline_pct'] < 2.0),

        # 3가지 조합
        ('uptrend < 5% AND support >= 4 AND decline < 1.5%',
         lambda f: f['uptrend_gain_pct'] < 5 and f['support_candles'] >= 4 and f['decline_pct'] < 1.5),
        ('uptrend < 6% AND support >= 4 AND decline < 2.0%',
         lambda f: f['uptrend_gain_pct'] < 6 and f['support_candles'] >= 4 and f['decline_pct'] < 2.0),
    ]

    results = []
    for name, condition in combinations:
        matched_wins = sum(1 for f in wins if condition(f))
        matched_losses = sum(1 for f in losses if condition(f))
        matched_total = matched_wins + matched_losses
        if matched_total >= 30:
            wr = matched_wins / matched_total * 100
            improvement = wr - baseline_wr
            results.append((name, matched_wins, matched_losses, matched_total, wr, improvement))

    # 승률 기준 정렬
    results.sort(key=lambda x: x[4], reverse=True)

    print('{:<50} | {:>5} | {:>5} | {:>5} | {:>7} | {:>8}'.format(
        'Condition', 'Win', 'Loss', 'Total', 'WinRate', 'Improve'))
    print('-' * 95)

    for name, w, l, t, wr, imp in results:
        marker = ' <<' if imp > 3 else ''
        print('{:<50} | {:>5} | {:>5} | {:>5} | {:>6.1f}% | {:>+7.1f}%{}'.format(
            name, w, l, t, wr, imp, marker))

    # 6. 핵심 발견
    print('\n' + '=' * 80)
    print('[6] KEY FINDINGS')
    print('=' * 80)

    print('''
    ** 핵심 발견 **

    1. UPTREND GAIN (상승폭)
       - 승리: 평균 5.71%, 패배: 평균 6.54%
       - 과도한 상승(>=6%) 후 눌림목 = 손실 위험 증가
       - 해석: 너무 많이 오른 종목은 차익실현 압력 존재

    2. DECLINE (조정폭) - 예상과 반대!
       - 낮은 조정(< 1.5%)이 오히려 승률 높음
       - 해석: 강한 종목은 적게 조정받고 바로 상승

    3. SUPPORT CANDLES (지지 캔들)
       - support >= 4 일 때 50.5% 승률 (+4.5%)
       - 해석: 충분한 지지 형성이 안정적

    4. 최적 필터 조합
       - uptrend < 5% + support >= 4 + decline < 1.5%
       - 작은 상승 + 충분한 지지 + 적은 조정 = 최적 눌림목
    ''')

    # 7. 최적 필터 수익 예상
    print('=' * 80)
    print('[7] BEST FILTER PROFIT ESTIMATION')
    print('=' * 80)

    best_conditions = [
        ('support >= 4', lambda f: f['support_candles'] >= 4),
        ('decline < 1.5%', lambda f: f['decline_pct'] < 1.5),
        ('uptrend < 5% + support >= 4',
         lambda f: f['uptrend_gain_pct'] < 5 and f['support_candles'] >= 4),
    ]

    trade_amount = 2000000  # 1/5 투자

    for name, condition in best_conditions:
        filtered_wins = [f for f in wins if condition(f)]
        filtered_losses = [f for f in losses if condition(f)]

        if len(filtered_wins) + len(filtered_losses) >= 30:
            total_f = len(filtered_wins) + len(filtered_losses)
            wr = len(filtered_wins) / total_f * 100

            avg_win = np.mean([f['profit_rate'] for f in filtered_wins]) if filtered_wins else 0
            avg_loss = np.mean([f['profit_rate'] for f in filtered_losses]) if filtered_losses else 0

            expected = (wr/100 * avg_win + (1-wr/100) * avg_loss) / 100 * trade_amount

            print('\nFilter: {}'.format(name))
            print('  Trades: {} ({}W/{}L)'.format(total_f, len(filtered_wins), len(filtered_losses)))
            print('  Win Rate: {:.1f}% (baseline: {:.1f}%)'.format(wr, baseline_wr))
            print('  Avg Win: {:.2f}%, Avg Loss: {:.2f}%'.format(avg_win, avg_loss))
            print('  Expected per trade: {:+,.0f}won'.format(expected))
            print('  Total for {} trades: {:+,.0f}won'.format(total_f, expected * total_f))


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
