#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
마이너스 수익 조합 제외 분석

총 수익이 마이너스인 패턴 조합만 제외하고 순수익 변화 확인
"""

import pandas as pd
import numpy as np


def analyze_negative_profit_exclusion(csv_file: str = "all_patterns_analysis.csv"):
    """총 수익 마이너스 조합만 제외하는 분석"""

    print("=" * 80)
    print("마이너스 수익 조합 제외 분석")
    print("=" * 80)

    # CSV 로드
    df = pd.read_csv(csv_file)

    # 거래 실행된 것만
    traded = df[df['trade_executed'] == True].copy()

    print(f"\n총 거래: {len(traded)}건")

    # 승/패 분류
    wins = traded[traded['profit_rate'] > 0]
    losses = traded[traded['profit_rate'] <= 0]

    print(f"승리: {len(wins)}건 ({len(wins)/len(traded)*100:.1f}%)")
    print(f"패배: {len(losses)}건 ({len(losses)/len(traded)*100:.1f}%)")

    # 원래 수익
    total_profit_before = traded['profit_rate'].sum()
    avg_profit_before = traded['profit_rate'].mean()

    print(f"\n[필터 전]")
    print(f"  총 수익: {total_profit_before:.2f}%")
    print(f"  평균 수익률: {avg_profit_before:.3f}%")
    print(f"  승률: {len(wins)/len(traded)*100:.1f}%")

    # 각 단계를 카테고리화 (이전과 동일)
    traded['상승강도'] = pd.cut(traded['uptrend_price_gain'],
                               bins=[0, 4, 6, 100],
                               labels=['약함(<4%)', '보통(4-6%)', '강함(>6%)'])

    traded['하락정도'] = pd.cut(traded['decline_pct'],
                               bins=[0, 1.5, 2.5, 100],
                               labels=['얕음(<1.5%)', '보통(1.5-2.5%)', '깊음(>2.5%)'])

    traded['지지길이'] = pd.cut(traded['support_candle_count'],
                              bins=[0, 2, 4, 100],
                              labels=['짧음(≤2)', '보통(3-4)', '김(>4)'])

    traded['돌파강도'] = pd.cut(traded['breakout_volume_ratio_vs_prev'],
                               bins=[0, 1.5, 2.5, 100],
                               labels=['약함(<1.5배)', '보통(1.5-2.5배)', '강함(>2.5배)'])

    print("\n" + "=" * 80)
    print("1. 전체 패턴 조합별 총 수익 분석")
    print("=" * 80)

    # 조합별 그룹화
    combinations = traded.groupby(['상승강도', '하락정도', '지지길이', '돌파강도'], dropna=False)

    combo_results = []

    for combo, group in combinations:
        wins_in_combo = group[group['profit_rate'] > 0]
        losses_in_combo = group[group['profit_rate'] <= 0]

        win_rate = len(wins_in_combo) / len(group) * 100
        avg_profit = group['profit_rate'].mean()
        total_profit = group['profit_rate'].sum()

        combo_results.append({
            '조합': ' + '.join([str(c) for c in combo if pd.notna(c)]),
            '거래수': len(group),
            '승': len(wins_in_combo),
            '패': len(losses_in_combo),
            '승률': win_rate,
            '평균수익률': avg_profit,
            '총수익': total_profit,
            '상승강도': combo[0],
            '하락정도': combo[1],
            '지지길이': combo[2],
            '돌파강도': combo[3]
        })

    combo_df = pd.DataFrame(combo_results)

    # 총 수익 기준 정렬
    combo_df = combo_df.sort_values('총수익', ascending=False)

    print(f"\n전체 패턴 조합: {len(combo_df)}개")
    print(f"거래 수 범위: {combo_df['거래수'].min()}건 ~ {combo_df['거래수'].max()}건")

    # 마이너스 수익 조합 찾기
    negative_combos = combo_df[combo_df['총수익'] < 0].copy()
    positive_combos = combo_df[combo_df['총수익'] >= 0].copy()

    print("\n" + "=" * 80)
    print("2. 총 수익 마이너스 조합")
    print("=" * 80)

    print(f"\n마이너스 수익 조합: {len(negative_combos)}개")
    print(f"플러스/제로 수익 조합: {len(positive_combos)}개")

    if len(negative_combos) > 0:
        print(f"\n[마이너스 수익 조합 상세]")
        for idx, row in negative_combos.iterrows():
            print(f"\n  조합: {row['조합']}")
            print(f"    거래: {row['거래수']}건 (승 {row['승']}, 패 {row['패']})")
            print(f"    승률: {row['승률']:.1f}%")
            print(f"    평균 수익률: {row['평균수익률']:.3f}%")
            print(f"    총 수익: {row['총수익']:.2f}%")

        # 마이너스 조합의 총 거래수 및 수익 합계
        negative_trade_count = negative_combos['거래수'].sum()
        negative_total_profit = negative_combos['총수익'].sum()

        print(f"\n[마이너스 조합 합계]")
        print(f"  총 거래 수: {negative_trade_count}건")
        print(f"  총 수익 합계: {negative_total_profit:.2f}%")

    print("\n" + "=" * 80)
    print("3. 마이너스 조합 제외 시뮬레이션")
    print("=" * 80)

    # 마이너스 조합에 해당하는 거래 찾기
    if len(negative_combos) > 0:
        # 제외할 조합의 조건 생성
        exclude_mask = pd.Series([False] * len(traded), index=traded.index)

        for idx, row in negative_combos.iterrows():
            # NaN 처리를 위한 비교
            if pd.isna(row['상승강도']):
                cond1 = traded['상승강도'].isna()
            else:
                cond1 = (traded['상승강도'] == row['상승강도'])

            if pd.isna(row['하락정도']):
                cond2 = traded['하락정도'].isna()
            else:
                cond2 = (traded['하락정도'] == row['하락정도'])

            if pd.isna(row['지지길이']):
                cond3 = traded['지지길이'].isna()
            else:
                cond3 = (traded['지지길이'] == row['지지길이'])

            if pd.isna(row['돌파강도']):
                cond4 = traded['돌파강도'].isna()
            else:
                cond4 = (traded['돌파강도'] == row['돌파강도'])

            combo_mask = cond1 & cond2 & cond3 & cond4
            exclude_mask = exclude_mask | combo_mask

        # 필터링 (마이너스 조합 제외)
        filtered = traded[~exclude_mask].copy()
        excluded = traded[exclude_mask].copy()

        print(f"\n제외될 거래: {len(excluded)}건")
        print(f"남은 거래: {len(filtered)}건 ({len(filtered)/len(traded)*100:.1f}%)")

        # 제외된 거래 분석
        excluded_wins = excluded[excluded['profit_rate'] > 0]
        excluded_losses = excluded[excluded['profit_rate'] <= 0]

        print(f"\n[제외된 거래 상세]")
        print(f"  승: {len(excluded_wins)}건")
        print(f"  패: {len(excluded_losses)}건")
        if len(excluded) > 0:
            print(f"  승률: {len(excluded_wins)/len(excluded)*100:.1f}%")
            print(f"  총 수익: {excluded['profit_rate'].sum():.2f}%")
        else:
            print(f"  승률: N/A (제외된 거래 없음)")
            print(f"  총 수익: 0.00%")

        # 남은 거래 분석
        filtered_wins = filtered[filtered['profit_rate'] > 0]
        filtered_losses = filtered[filtered['profit_rate'] <= 0]

        total_profit_after = filtered['profit_rate'].sum()
        avg_profit_after = filtered['profit_rate'].mean()
        win_rate_after = len(filtered_wins) / len(filtered) * 100 if len(filtered) > 0 else 0

        print(f"\n[남은 거래 상세]")
        print(f"  승: {len(filtered_wins)}건")
        print(f"  패: {len(filtered_losses)}건")
        print(f"  승률: {win_rate_after:.1f}%")
        print(f"  총 수익: {total_profit_after:.2f}%")
        print(f"  평균 수익률: {avg_profit_after:.3f}%")

        print("\n" + "=" * 80)
        print("4. 필터 효과 분석")
        print("=" * 80)

        # 수익 변화
        profit_change = total_profit_after - total_profit_before
        profit_change_pct = (profit_change / total_profit_before * 100) if total_profit_before != 0 else 0

        # 평균 수익률 변화
        avg_change = avg_profit_after - avg_profit_before
        avg_change_pct = (avg_change / avg_profit_before * 100) if avg_profit_before != 0 else 0

        # 승률 변화
        win_rate_before = len(wins) / len(traded) * 100
        win_rate_change = win_rate_after - win_rate_before

        print(f"\n[총 수익]")
        print(f"  필터 전: {total_profit_before:.2f}%")
        print(f"  필터 후: {total_profit_after:.2f}%")
        print(f"  변화: {profit_change:+.2f}% ({profit_change_pct:+.1f}%)")

        print(f"\n[평균 수익률]")
        print(f"  필터 전: {avg_profit_before:.3f}%")
        print(f"  필터 후: {avg_profit_after:.3f}%")
        print(f"  변화: {avg_change:+.3f}% ({avg_change_pct:+.1f}%)")

        print(f"\n[승률]")
        print(f"  필터 전: {win_rate_before:.1f}%")
        print(f"  필터 후: {win_rate_after:.1f}%")
        print(f"  변화: {win_rate_change:+.1f}%p")

        print(f"\n[거래 수]")
        print(f"  필터 전: {len(traded)}건")
        print(f"  필터 후: {len(filtered)}건")
        print(f"  감소: {len(excluded)}건 ({len(excluded)/len(traded)*100:.1f}%)")

        print("\n" + "=" * 80)
        print("5. 결론")
        print("=" * 80)

        if profit_change > 0:
            print(f"\n[OK] 순수익 증가!")
            print(f"  마이너스 조합 {len(negative_combos)}개를 제외하면 순수익이 {profit_change:+.2f}% 증가합니다.")
            print(f"  총 수익: {total_profit_before:.2f}% -> {total_profit_after:.2f}%")
            print(f"  평균 수익률: {avg_profit_before:.3f}% -> {avg_profit_after:.3f}%")
            print(f"  승률: {win_rate_before:.1f}% -> {win_rate_after:.1f}%")
            print(f"\n  [추천] 이 필터를 적용하면 수익성이 개선됩니다.")
        else:
            print(f"\n[WARNING] 순수익 감소")
            print(f"  마이너스 조합을 제외해도 순수익이 {profit_change:.2f}% 감소합니다.")
            print(f"  이유: 마이너스 조합 내에도 수익 거래가 포함되어 있기 때문입니다.")

        # CSV 저장
        combo_df.to_csv('pattern_combinations_by_profit.csv', index=False, encoding='utf-8-sig')
        print(f"\n조합별 수익 분석 저장: pattern_combinations_by_profit.csv")

        # 제외할 조합 리스트 저장
        if len(negative_combos) > 0:
            negative_combos.to_csv('negative_profit_combinations.csv', index=False, encoding='utf-8-sig')
            print(f"마이너스 수익 조합 저장: negative_profit_combinations.csv")

    else:
        print("\n[INFO] 총 수익이 마이너스인 조합이 없습니다!")
        print("모든 패턴 조합이 플러스 또는 제로 수익을 기록했습니다.")

    return combo_df


def analyze_by_trade_count(csv_file: str = "all_patterns_analysis.csv"):
    """거래 수를 고려한 추가 분석"""

    print("\n" + "=" * 80)
    print("6. 거래 수 임계값별 분석 (최소 거래 수 필터)")
    print("=" * 80)

    df = pd.read_csv(csv_file)
    traded = df[df['trade_executed'] == True].copy()

    # 카테고리화
    traded['상승강도'] = pd.cut(traded['uptrend_price_gain'],
                               bins=[0, 4, 6, 100],
                               labels=['약함(<4%)', '보통(4-6%)', '강함(>6%)'])
    traded['하락정도'] = pd.cut(traded['decline_pct'],
                               bins=[0, 1.5, 2.5, 100],
                               labels=['얕음(<1.5%)', '보통(1.5-2.5%)', '깊음(>2.5%)'])
    traded['지지길이'] = pd.cut(traded['support_candle_count'],
                              bins=[0, 2, 4, 100],
                              labels=['짧음(≤2)', '보통(3-4)', '김(>4)'])
    traded['돌파강도'] = pd.cut(traded['breakout_volume_ratio_vs_prev'],
                               bins=[0, 1.5, 2.5, 100],
                               labels=['약함(<1.5배)', '보통(1.5-2.5배)', '강함(>2.5배)'])

    # 조합별 그룹화
    combinations = traded.groupby(['상승강도', '하락정도', '지지길이', '돌파강도'], dropna=False)

    # 원래 수익
    total_profit_before = traded['profit_rate'].sum()

    print(f"\n최소 거래 수 임계값을 변경하면서 마이너스 조합 제외:")

    for min_trades in [1, 3, 5, 10]:
        combo_results = []

        for combo, group in combinations:
            if len(group) < min_trades:
                continue

            total_profit = group['profit_rate'].sum()

            combo_results.append({
                'combo': combo,
                'count': len(group),
                'total_profit': total_profit
            })

        # 마이너스 조합 찾기
        negative_combos = [c for c in combo_results if c['total_profit'] < 0]

        if len(negative_combos) == 0:
            print(f"\n최소 거래 {min_trades}건: 마이너스 조합 없음")
            continue

        # 제외할 조합 마스크
        exclude_mask = pd.Series([False] * len(traded), index=traded.index)

        for neg_combo in negative_combos:
            combo = neg_combo['combo']

            # NaN 처리
            if pd.isna(combo[0]):
                cond1 = traded['상승강도'].isna()
            else:
                cond1 = (traded['상승강도'] == combo[0])

            if pd.isna(combo[1]):
                cond2 = traded['하락정도'].isna()
            else:
                cond2 = (traded['하락정도'] == combo[1])

            if pd.isna(combo[2]):
                cond3 = traded['지지길이'].isna()
            else:
                cond3 = (traded['지지길이'] == combo[2])

            if pd.isna(combo[3]):
                cond4 = traded['돌파강도'].isna()
            else:
                cond4 = (traded['돌파강도'] == combo[3])

            combo_mask = cond1 & cond2 & cond3 & cond4
            exclude_mask = exclude_mask | combo_mask

        filtered = traded[~exclude_mask]
        total_profit_after = filtered['profit_rate'].sum()
        profit_change = total_profit_after - total_profit_before

        print(f"\n최소 거래 {min_trades}건:")
        print(f"  마이너스 조합: {len(negative_combos)}개")
        print(f"  제외될 거래: {len(traded) - len(filtered)}건")
        print(f"  순수익 변화: {profit_change:+.2f}%")


def main():
    print("\n")

    # 1. 마이너스 수익 조합 제외 분석
    combo_df = analyze_negative_profit_exclusion()

    # 2. 거래 수 임계값별 분석
    analyze_by_trade_count()

    print("\n" + "=" * 80)
    print("분석 완료!")
    print("=" * 80)


if __name__ == '__main__':
    main()
