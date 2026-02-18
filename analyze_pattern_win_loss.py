#!/usr/bin/env python3
"""
승/패 거래의 패턴 특징 차이 분석
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

                        features = {
                            'uptrend_gain': float(uptrend.get('price_gain', 0) or 0),
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
                        }

                        if profit_rate > 0:
                            wins.append(features)
                        else:
                            losses.append(features)

                    except:
                        continue
        except:
            continue

    print('=' * 80)
    print('PULLBACK PATTERN ANALYSIS: Win vs Loss')
    print('=' * 80)
    print(f'Total: {len(wins)} wins, {len(losses)} losses')
    if wins or losses:
        print(f'Win Rate: {len(wins)/(len(wins)+len(losses))*100:.1f}%')
    print('=' * 80)

    if wins and losses:
        metrics = [
            ('uptrend_gain', 'Uptrend Gain'),
            ('uptrend_candles', 'Uptrend Candles'),
            ('uptrend_max_vol_ratio', 'Uptrend MaxVol Ratio'),
            ('decline_pct', 'Decline %'),
            ('decline_candles', 'Decline Candles'),
            ('decline_vol_ratio', 'Decline Vol Ratio'),
            ('support_candles', 'Support Candles'),
            ('support_vol_ratio', 'Support Vol Ratio'),
            ('support_volatility', 'Support Volatility'),
            ('breakout_vol_ratio', 'Breakout Vol Incr'),
            ('breakout_body_increase', 'Breakout Body Incr'),
        ]

        print()
        print(f'{"Feature":<22} | {"Win Avg":>10} | {"Loss Avg":>10} | {"Diff":>10} | {"Diff%":>8}')
        print('-' * 75)

        significant = []

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
                    significant.append((name, win_avg, loss_avg, diff, diff_pct))
                elif abs(diff_pct) > 10:
                    marker = ' **'
                    significant.append((name, win_avg, loss_avg, diff, diff_pct))
                elif abs(diff_pct) > 5:
                    marker = ' *'

                print(f'{name:<22} | {win_avg:>10.4f} | {loss_avg:>10.4f} | {diff:>+10.4f} | {diff_pct:>+7.1f}%{marker}')

        print()
        print('=' * 80)
        print('SIGNIFICANT DIFFERENCES (>10%):')
        print('=' * 80)

        for name, win_avg, loss_avg, diff, diff_pct in sorted(significant, key=lambda x: abs(x[4]), reverse=True):
            direction = 'HIGHER' if diff > 0 else 'LOWER'
            print(f'* {name} - Win is {direction}: {win_avg:.4f} vs {loss_avg:.4f} ({diff_pct:+.1f}%)')

        # 추가 분석: 임계값 기반 승률
        print()
        print('=' * 80)
        print('THRESHOLD ANALYSIS (potential new filters):')
        print('=' * 80)

        # 하락률 임계값 분석
        for threshold in [0.015, 0.02, 0.025, 0.03]:
            win_below = sum(1 for f in wins if f['decline_pct'] < threshold)
            loss_below = sum(1 for f in losses if f['decline_pct'] < threshold)
            total_below = win_below + loss_below
            if total_below > 0:
                wr = win_below / total_below * 100
                print(f'decline_pct < {threshold:.1%}: {win_below}W/{loss_below}L = {wr:.1f}% win rate (n={total_below})')

        print()

        # 지지구간 캔들 수 임계값 분석
        for threshold in [2, 3, 4, 5]:
            win_above = sum(1 for f in wins if f['support_candles'] >= threshold)
            loss_above = sum(1 for f in losses if f['support_candles'] >= threshold)
            total_above = win_above + loss_above
            if total_above > 0:
                wr = win_above / total_above * 100
                print(f'support_candles >= {threshold}: {win_above}W/{loss_above}L = {wr:.1f}% win rate (n={total_above})')

        print()

        # 돌파봉 거래량 증가율 임계값 분석
        for threshold in [0.1, 0.2, 0.3, 0.5]:
            win_above = sum(1 for f in wins if f['breakout_vol_ratio'] >= threshold)
            loss_above = sum(1 for f in losses if f['breakout_vol_ratio'] >= threshold)
            total_above = win_above + loss_above
            if total_above > 0:
                wr = win_above / total_above * 100
                print(f'breakout_vol_ratio >= {threshold:.0%}: {win_above}W/{loss_above}L = {wr:.1f}% win rate (n={total_above})')

if __name__ == '__main__':
    main()
