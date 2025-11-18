#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
신뢰도 점수별 승률 분석 & 4단계 패턴 조합 분석

1. 신뢰도 점수 구간별 실제 승률
2. 4단계 구간 조합별 승률 및 수익률
"""

import pandas as pd
import numpy as np


def analyze_confidence_winrate(csv_file: str = "all_patterns_analysis.csv"):
    """신뢰도 점수별 승률 분석"""

    print("=" * 80)
    print("신뢰도 점수 vs 실제 승률 분석")
    print("=" * 80)

    # CSV 로드
    df = pd.read_csv(csv_file)

    # 거래 실행된 것만
    traded = df[df['trade_executed'] == True].copy()

    print(f"\n총 거래: {len(traded)}건")

    # 신뢰도 구간별 분석
    confidence_ranges = [
        (80, 85, '80-85'),
        (85, 90, '85-90'),
        (90, 95, '90-95'),
        (95, 100, '95-100')
    ]

    print("\n" + "=" * 80)
    print("1. 신뢰도 구간별 승률 및 수익률")
    print("=" * 80)

    conf_results = []

    for min_conf, max_conf, label in confidence_ranges:
        mask = (traded['confidence'] >= min_conf) & (traded['confidence'] < max_conf)
        group = traded[mask]

        if len(group) == 0:
            continue

        wins = group[group['profit_rate'] > 0]
        losses = group[group['profit_rate'] <= 0]

        win_rate = len(wins) / len(group) * 100
        avg_profit = group['profit_rate'].mean()
        total_profit = group['profit_rate'].sum()

        conf_results.append({
            '신뢰도구간': label,
            '거래수': len(group),
            '승': len(wins),
            '패': len(losses),
            '승률': win_rate,
            '평균수익률': avg_profit,
            '총수익': total_profit
        })

        print(f"\n신뢰도 {label}%:")
        print(f"  거래 수: {len(group)}건")
        print(f"  승/패: {len(wins)}승 {len(losses)}패")
        print(f"  승률: {win_rate:.1f}%")
        print(f"  평균 수익률: {avg_profit:.3f}%")
        print(f"  총 수익: {total_profit:.2f}%")

    # 개별 신뢰도 점수별 분석
    print("\n" + "=" * 80)
    print("2. 개별 신뢰도 점수별 상세 분석")
    print("=" * 80)

    individual_scores = sorted(traded['confidence'].unique())

    score_results = []

    for score in individual_scores:
        group = traded[traded['confidence'] == score]

        if len(group) == 0:
            continue

        wins = group[group['profit_rate'] > 0]
        losses = group[group['profit_rate'] <= 0]

        win_rate = len(wins) / len(group) * 100
        avg_profit = group['profit_rate'].mean()

        score_results.append({
            '신뢰도': score,
            '거래수': len(group),
            '승': len(wins),
            '패': len(losses),
            '승률': win_rate,
            '평균수익률': avg_profit
        })

    # DataFrame으로 변환 및 정렬
    score_df = pd.DataFrame(score_results)

    # 승률 높은 순
    print("\n[승률 높은 순 TOP 10]")
    top_by_winrate = score_df.sort_values('승률', ascending=False).head(10)
    for idx, row in top_by_winrate.iterrows():
        print(f"신뢰도 {row['신뢰도']:.0f}%: 승률 {row['승률']:.1f}% ({row['승']}승/{row['패']}패, {row['거래수']}건)")

    # 평균 수익률 높은 순
    print("\n[평균 수익률 높은 순 TOP 10]")
    top_by_profit = score_df.sort_values('평균수익률', ascending=False).head(10)
    for idx, row in top_by_profit.iterrows():
        print(f"신뢰도 {row['신뢰도']:.0f}%: 평균 {row['평균수익률']:.3f}% (승률 {row['승률']:.1f}%, {row['거래수']}건)")

    # 거래 수 많은 순
    print("\n[거래 수 많은 순]")
    top_by_count = score_df.sort_values('거래수', ascending=False).head(10)
    for idx, row in top_by_count.iterrows():
        print(f"신뢰도 {row['신뢰도']:.0f}%: {row['거래수']}건 (승률 {row['승률']:.1f}%, 평균 {row['평균수익률']:.3f}%)")

    return score_df


def analyze_pattern_combinations(csv_file: str = "all_patterns_analysis.csv"):
    """4단계 패턴 조합별 승률 분석"""

    print("\n" + "=" * 80)
    print("4단계 패턴 조합별 승률 분석")
    print("=" * 80)

    # CSV 로드
    df = pd.read_csv(csv_file)

    # 거래 실행된 것만
    traded = df[df['trade_executed'] == True].copy()

    # 각 단계를 카테고리화
    # 1단계: 상승 강도 (가격 상승률)
    traded['상승강도'] = pd.cut(traded['uptrend_price_gain'],
                               bins=[0, 4, 6, 100],
                               labels=['약함(<4%)', '보통(4-6%)', '강함(>6%)'])

    # 2단계: 하락 정도
    traded['하락정도'] = pd.cut(traded['decline_pct'],
                               bins=[0, 1.5, 2.5, 100],
                               labels=['얕음(<1.5%)', '보통(1.5-2.5%)', '깊음(>2.5%)'])

    # 3단계: 지지 캔들 수
    traded['지지길이'] = pd.cut(traded['support_candle_count'],
                              bins=[0, 2, 4, 100],
                              labels=['짧음(≤2)', '보통(3-4)', '김(>4)'])

    # 4단계: 돌파 강도 (거래량 비율)
    traded['돌파강도'] = pd.cut(traded['breakout_volume_ratio_vs_prev'],
                               bins=[0, 1.5, 2.5, 100],
                               labels=['약함(<1.5배)', '보통(1.5-2.5배)', '강함(>2.5배)'])

    print("\n" + "=" * 80)
    print("1. 각 단계별 개별 영향")
    print("=" * 80)

    stages = [
        ('상승강도', '1단계: 상승 구간'),
        ('하락정도', '2단계: 하락 구간'),
        ('지지길이', '3단계: 지지 구간'),
        ('돌파강도', '4단계: 돌파 양봉')
    ]

    for col, stage_name in stages:
        print(f"\n{stage_name}:")

        for category in traded[col].dropna().unique():
            group = traded[traded[col] == category]

            if len(group) == 0:
                continue

            wins = group[group['profit_rate'] > 0]
            win_rate = len(wins) / len(group) * 100
            avg_profit = group['profit_rate'].mean()

            print(f"  {category}: {len(group)}건, 승률 {win_rate:.1f}%, 평균 {avg_profit:.3f}%")

    # 최고 성과 조합 찾기
    print("\n" + "=" * 80)
    print("2. 최고 성과 4단계 조합 (거래 5건 이상)")
    print("=" * 80)

    # 조합별 그룹화
    combinations = traded.groupby(['상승강도', '하락정도', '지지길이', '돌파강도'], dropna=False)

    combo_results = []

    for combo, group in combinations:
        if len(group) < 5:  # 최소 5건 이상만
            continue

        wins = group[group['profit_rate'] > 0]
        win_rate = len(wins) / len(group) * 100
        avg_profit = group['profit_rate'].mean()
        total_profit = group['profit_rate'].sum()

        combo_results.append({
            '조합': ' + '.join([str(c) for c in combo if pd.notna(c)]),
            '거래수': len(group),
            '승': len(wins),
            '패': len(group) - len(wins),
            '승률': win_rate,
            '평균수익률': avg_profit,
            '총수익': total_profit,
            '상승강도': combo[0],
            '하락정도': combo[1],
            '지지길이': combo[2],
            '돌파강도': combo[3]
        })

    combo_df = pd.DataFrame(combo_results)

    if len(combo_df) > 0:
        # 승률 높은 조합
        print("\n[승률 높은 조합 TOP 10]")
        top_winrate = combo_df.sort_values('승률', ascending=False).head(10)
        for idx, row in top_winrate.iterrows():
            print(f"\n조합: {row['조합']}")
            print(f"  거래: {row['거래수']}건 ({row['승']}승 {row['패']}패)")
            print(f"  승률: {row['승률']:.1f}%")
            print(f"  평균 수익률: {row['평균수익률']:.3f}%")
            print(f"  총 수익: {row['총수익']:.2f}%")

        # 총 수익 높은 조합
        print("\n" + "=" * 80)
        print("3. 총 수익 높은 조합 TOP 10")
        print("=" * 80)

        top_total = combo_df.sort_values('총수익', ascending=False).head(10)
        for idx, row in top_total.iterrows():
            print(f"\n조합: {row['조합']}")
            print(f"  거래: {row['거래수']}건 ({row['승']}승 {row['패']}패)")
            print(f"  승률: {row['승률']:.1f}%")
            print(f"  평균 수익률: {row['평균수익률']:.3f}%")
            print(f"  총 수익: {row['총수익']:.2f}%")

        # CSV 저장
        combo_df.to_csv('pattern_combinations_analysis.csv', index=False, encoding='utf-8-sig')
        print("\n\n조합 분석 결과 저장: pattern_combinations_analysis.csv")

    return combo_df


def main():
    print("\n")

    # 1. 신뢰도 분석
    score_df = analyze_confidence_winrate()

    # 2. 패턴 조합 분석
    combo_df = analyze_pattern_combinations()

    print("\n" + "=" * 80)
    print("분석 완료!")
    print("=" * 80)


if __name__ == '__main__':
    main()
