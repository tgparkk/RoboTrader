#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
패배 감소 분석 스크립트

승리는 유지하면서 패배만 줄이기 위한 필터 조건 도출
"""

import pandas as pd
import numpy as np
from pathlib import Path


def analyze_loss_reduction(csv_file: str = "all_patterns_analysis.csv"):
    """패배 감소를 위한 분석"""

    print("=" * 80)
    print("패배 감소 분석 - 승리 유지, 패배 제거")
    print("=" * 80)

    # CSV 로드
    df = pd.read_csv(csv_file)

    # 거래 실행된 것만
    traded = df[df['trade_executed'] == True].copy()

    # 승/패 분류
    wins = traded[traded['profit_rate'] > 0].copy()
    losses = traded[traded['profit_rate'] <= 0].copy()

    print(f"\n총 거래: {len(traded)}건")
    print(f"승리: {len(wins)}건 ({len(wins)/len(traded)*100:.1f}%)")
    print(f"패배: {len(losses)}건 ({len(losses)/len(traded)*100:.1f}%)")

    # 각 지표별로 승/패 분포 분석
    indicators = {
        '1단계_캔들수': 'uptrend_candle_count',
        '1단계_가격상승률': 'uptrend_price_gain',
        '1단계_최대거래량비율': 'uptrend_max_volume_ratio',
        '2단계_캔들수': 'decline_candle_count',
        '2단계_하락률': 'decline_pct',
        '2단계_평균거래량비율': 'decline_avg_volume_ratio',
        '3단계_캔들수': 'support_candle_count',
        '3단계_가격변동성': 'support_price_volatility',
        '3단계_평균거래량비율': 'support_avg_volume_ratio',
        '4단계_몸통크기': 'breakout_body_size',
        '4단계_거래량비율': 'breakout_volume_ratio_vs_prev',
        '4단계_몸통증가율': 'breakout_body_increase_vs_support',
    }

    print("\n" + "=" * 80)
    print("1. 승/패 지표 비교")
    print("=" * 80)

    comparison = []

    for name, col in indicators.items():
        if col not in traded.columns:
            continue

        # None 값 제거
        win_data = wins[col].dropna()
        loss_data = losses[col].dropna()

        if len(win_data) == 0 or len(loss_data) == 0:
            continue

        win_mean = win_data.mean()
        loss_mean = loss_data.mean()
        diff_pct = ((win_mean - loss_mean) / abs(loss_mean) * 100) if loss_mean != 0 else 0

        win_median = win_data.median()
        loss_median = loss_data.median()

        comparison.append({
            '지표': name,
            '승리_평균': win_mean,
            '패배_평균': loss_mean,
            '차이_%': diff_pct,
            '승리_중앙값': win_median,
            '패배_중앙값': loss_median
        })

        print(f"\n{name}:")
        print(f"  승리 평균: {win_mean:.2f} | 패배 평균: {loss_mean:.2f} | 차이: {diff_pct:+.1f}%")
        print(f"  승리 중앙값: {win_median:.2f} | 패배 중앙값: {loss_median:.2f}")

    # 필터 조건 테스트
    print("\n" + "=" * 80)
    print("2. 패배 제거 필터 조건 테스트")
    print("=" * 80)

    filter_tests = []

    # 테스트할 필터 조건들
    test_conditions = [
        # 2단계 하락률 필터
        ('2단계_하락률 < 1.5%', lambda df: df['decline_pct'] < 1.5),
        ('2단계_하락률 < 2.0%', lambda df: df['decline_pct'] < 2.0),
        ('2단계_하락률 < 2.5%', lambda df: df['decline_pct'] < 2.5),

        # 3단계 캔들수 필터
        ('3단계_캔들수 <= 2개', lambda df: df['support_candle_count'] <= 2),
        ('3단계_캔들수 <= 3개', lambda df: df['support_candle_count'] <= 3),
        ('3단계_캔들수 <= 4개', lambda df: df['support_candle_count'] <= 4),

        # 3단계 가격변동성 필터
        ('3단계_변동성 < 10%', lambda df: df['support_price_volatility'] < 10),
        ('3단계_변동성 < 15%', lambda df: df['support_price_volatility'] < 15),
        ('3단계_변동성 < 20%', lambda df: df['support_price_volatility'] < 20),

        # 복합 조건
        ('하락률<2.0% AND 지지캔들<=3',
         lambda df: (df['decline_pct'] < 2.0) & (df['support_candle_count'] <= 3)),
        ('하락률<2.5% AND 변동성<15%',
         lambda df: (df['decline_pct'] < 2.5) & (df['support_price_volatility'] < 15)),
        ('지지캔들<=3 AND 변동성<15%',
         lambda df: (df['support_candle_count'] <= 3) & (df['support_price_volatility'] < 15)),
        ('하락률<2.0% AND 지지캔들<=3 AND 변동성<15%',
         lambda df: (df['decline_pct'] < 2.0) & (df['support_candle_count'] <= 3) & (df['support_price_volatility'] < 15)),
    ]

    for condition_name, condition_func in test_conditions:
        try:
            # 필터 적용
            filtered = traded[condition_func(traded)].copy()

            if len(filtered) == 0:
                continue

            filtered_wins = filtered[filtered['profit_rate'] > 0]
            filtered_losses = filtered[filtered['profit_rate'] <= 0]

            # 통과한 거래 중 승/패
            pass_rate = len(filtered) / len(traded) * 100
            new_win_rate = len(filtered_wins) / len(filtered) * 100 if len(filtered) > 0 else 0

            # 승리 유지율 (원래 승리 중 몇 % 유지되는지)
            win_retention = len(filtered_wins) / len(wins) * 100 if len(wins) > 0 else 0

            # 패배 제거율 (원래 패배 중 몇 % 제거되는지)
            loss_reduction = (len(losses) - len(filtered_losses)) / len(losses) * 100 if len(losses) > 0 else 0

            # 실제 수익금 계산
            # 필터 전
            total_profit_before = wins['profit_rate'].sum()
            total_loss_before = losses['profit_rate'].sum()
            net_profit_before = total_profit_before + total_loss_before

            # 필터 후
            total_profit_after = filtered_wins['profit_rate'].sum() if len(filtered_wins) > 0 else 0
            total_loss_after = filtered_losses['profit_rate'].sum() if len(filtered_losses) > 0 else 0
            net_profit_after = total_profit_after + total_loss_after

            # 수익 변화
            profit_change = net_profit_after - net_profit_before
            profit_change_pct = (profit_change / net_profit_before * 100) if net_profit_before != 0 else 0

            # 평균 수익률
            avg_profit_before = net_profit_before / len(traded) if len(traded) > 0 else 0
            avg_profit_after = net_profit_after / len(filtered) if len(filtered) > 0 else 0

            filter_tests.append({
                '조건': condition_name,
                '통과율': pass_rate,
                '새승률': new_win_rate,
                '승리유지율': win_retention,
                '패배제거율': loss_reduction,
                '통과_승': len(filtered_wins),
                '통과_패': len(filtered_losses),
                '필터_승': len(wins) - len(filtered_wins),
                '필터_패': len(losses) - len(filtered_losses),
                '순수익_변화': profit_change,
                '순수익_변화율': profit_change_pct,
                '평균수익_전': avg_profit_before,
                '평균수익_후': avg_profit_after
            })

            print(f"\n[{condition_name}]")
            print(f"  통과: {len(filtered)}/{len(traded)}건 ({pass_rate:.1f}%)")
            print(f"  통과한 거래의 승률: {new_win_rate:.1f}% (승 {len(filtered_wins)}, 패 {len(filtered_losses)})")
            print(f"  승리 유지: {len(filtered_wins)}/{len(wins)}건 ({win_retention:.1f}%)")
            print(f"  패배 제거: {len(losses) - len(filtered_losses)}/{len(losses)}건 ({loss_reduction:.1f}%)")
            print(f"  순수익 변화: {profit_change:+.2f}% ({profit_change_pct:+.1f}%)")
            print(f"  평균 수익률: {avg_profit_before:.3f}% → {avg_profit_after:.3f}%")
            print(f"  효과: 승리 {win_retention:.1f}% 유지, 패배 {loss_reduction:.1f}% 제거, 수익 {profit_change_pct:+.1f}%")

        except Exception as e:
            print(f"\n[{condition_name}] 오류: {e}")

    # 결과 DataFrame
    filter_df = pd.DataFrame(filter_tests)

    if len(filter_df) > 0:
        print("\n" + "=" * 80)
        print("3. 최적 필터 조건 (순수익 증가 기준)")
        print("=" * 80)

        # 순수익 변화율 기준 정렬
        top_filters_profit = filter_df.sort_values('순수익_변화율', ascending=False).head(10)

        print("\n[순수익 증가하는 필터]")
        profit_gainers = top_filters_profit[top_filters_profit['순수익_변화율'] > 0]

        if len(profit_gainers) > 0:
            for idx, row in profit_gainers.iterrows():
                print(f"\n{row['조건']}")
                print(f"  [OK] 순수익 증가: {row['순수익_변화']:+.2f}% ({row['순수익_변화율']:+.1f}%)")
                print(f"  평균 수익률: {row['평균수익_전']:.3f}% → {row['평균수익_후']:.3f}%")
                print(f"  거래 수: {len(traded)}건 → {int(row['통과_승'] + row['통과_패'])}건")
                print(f"  승률: 49.1% → {row['새승률']:.1f}%")
                print(f"  승리 유지: {row['승리유지율']:.1f}% / 패배 제거: {row['패배제거율']:.1f}%")
        else:
            print("  [WARNING] 순수익이 증가하는 필터가 없습니다!")

        print("\n" + "=" * 80)
        print("4. 참고: 효율성 점수 기준 (승리유지율 + 패배제거율)")
        print("=" * 80)

        # 효율성 점수: 승리 유지율 + 패배 제거율
        filter_df['효율성점수'] = filter_df['승리유지율'] + filter_df['패배제거율']

        # 정렬
        top_filters = filter_df.sort_values('효율성점수', ascending=False).head(5)

        for idx, row in top_filters.iterrows():
            print(f"\n{row['조건']}")
            print(f"  효율성 점수: {row['효율성점수']:.1f}")
            print(f"  순수익 변화: {row['순수익_변화']:+.2f}% ({row['순수익_변화율']:+.1f}%)")
            print(f"  승리 유지: {row['승리유지율']:.1f}% ({row['통과_승']}/{len(wins)})")
            print(f"  패배 제거: {row['패배제거율']:.1f}% ({row['필터_패']}/{len(losses)})")
            print(f"  새 승률: {row['새승률']:.1f}%")

        # CSV 저장
        filter_df.to_csv('loss_reduction_filters.csv', index=False, encoding='utf-8-sig')
        print(f"\n필터 테스트 결과 저장: loss_reduction_filters.csv")

    # 백분위수 분석
    print("\n" + "=" * 80)
    print("5. 주요 지표 백분위수 분석 (패배를 걸러낼 임계값 찾기)")
    print("=" * 80)

    key_indicators = [
        ('2단계_하락률', 'decline_pct'),
        ('3단계_캔들수', 'support_candle_count'),
        ('3단계_가격변동성', 'support_price_volatility'),
    ]

    for name, col in key_indicators:
        if col not in traded.columns:
            continue

        loss_data = losses[col].dropna()

        if len(loss_data) == 0:
            continue

        print(f"\n{name} (패배 패턴):")
        for p in [25, 50, 75, 90]:
            val = np.percentile(loss_data, p)
            print(f"  {p}% 백분위: {val:.2f}")

        # 이 값 이하로 필터링하면 패배의 몇 %를 제거하는지
        print(f"\n  임계값별 패배 제거율:")
        for threshold in [np.percentile(loss_data, p) for p in [25, 50, 75]]:
            removed = len(loss_data[loss_data > threshold])
            removal_rate = removed / len(loss_data) * 100

            # 승리 중 몇 개가 필터링되는지
            win_data = wins[col].dropna()
            win_filtered = len(win_data[win_data > threshold])
            win_loss_rate = win_filtered / len(win_data) * 100 if len(win_data) > 0 else 0

            print(f"    {col} > {threshold:.2f}: 패배 {removal_rate:.1f}% 제거, 승리 {win_loss_rate:.1f}% 손실")


if __name__ == '__main__':
    analyze_loss_reduction()
