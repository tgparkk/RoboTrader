#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
승리 조합 분석

승률이 높고 수익성이 좋은 패턴 조합을 찾아냅니다.
"""

import pandas as pd
import numpy as np


def analyze_winning_combinations(csv_file: str = "all_patterns_analysis.csv"):
    """승리 조합 분석"""

    print("=" * 80)
    print("승리 조합 분석")
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

    # 전체 수익
    total_profit = traded['profit_rate'].sum()
    avg_profit = traded['profit_rate'].mean()

    print(f"\n[전체 성과]")
    print(f"  총 수익: {total_profit:.2f}%")
    print(f"  평균 수익률: {avg_profit:.3f}%")
    print(f"  승률: {len(wins)/len(traded)*100:.1f}%")

    # 각 단계를 카테고리화
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
    print("1. 전체 패턴 조합별 분석")
    print("=" * 80)

    # 조합별 그룹화
    combinations = traded.groupby(['상승강도', '하락정도', '지지길이', '돌파강도'], dropna=False, observed=True)

    combo_results = []

    for combo, group in combinations:
        wins_in_combo = group[group['profit_rate'] > 0]
        losses_in_combo = group[group['profit_rate'] <= 0]

        win_rate = len(wins_in_combo) / len(group) * 100 if len(group) > 0 else 0
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

    print("\n" + "=" * 80)
    print("2. 승리 조합 기준")
    print("=" * 80)

    print("\n기준 1: 승률 60% 이상")
    print("기준 2: 평균 수익률 +0.5% 이상")
    print("기준 3: 거래 횟수 10건 이상 (통계적 신뢰도)")

    # 승리 조합 찾기
    winning_combos = combo_df[
        (combo_df['승률'] >= 60) &
        (combo_df['평균수익률'] >= 0.5) &
        (combo_df['거래수'] >= 10)
    ].copy()

    print(f"\n승리 조합: {len(winning_combos)}개")

    if len(winning_combos) > 0:
        print("\n" + "=" * 80)
        print("3. 승리 조합 상세")
        print("=" * 80)

        # 총 수익 기준으로 정렬
        winning_combos = winning_combos.sort_values('총수익', ascending=False)

        for idx, row in winning_combos.iterrows():
            print(f"\n  조합: {row['조합']}")
            print(f"    거래: {row['거래수']}건 (승 {row['승']}, 패 {row['패']})")
            print(f"    승률: {row['승률']:.1f}%")
            print(f"    평균 수익률: {row['평균수익률']:.3f}%")
            print(f"    총 수익: {row['총수익']:.2f}%")

        # 승리 조합의 총 거래수 및 수익 합계
        winning_trade_count = winning_combos['거래수'].sum()
        winning_total_profit = winning_combos['총수익'].sum()

        print(f"\n[승리 조합 합계]")
        print(f"  총 거래 수: {winning_trade_count}건")
        print(f"  총 수익 합계: {winning_total_profit:.2f}%")

        # 승리 조합만 필터링 시뮬레이션
        print("\n" + "=" * 80)
        print("4. 승리 조합만 매매 시뮬레이션")
        print("=" * 80)

        # 승리 조합에 해당하는 거래 찾기
        include_mask = pd.Series([False] * len(traded), index=traded.index)

        for idx, row in winning_combos.iterrows():
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
            include_mask = include_mask | combo_mask

        # 필터링 (승리 조합만 포함)
        filtered = traded[include_mask].copy()
        excluded = traded[~include_mask].copy()

        print(f"\n승리 조합 거래: {len(filtered)}건 ({len(filtered)/len(traded)*100:.1f}%)")
        print(f"제외될 거래: {len(excluded)}건")

        # 승리 조합 거래 분석
        filtered_wins = filtered[filtered['profit_rate'] > 0]
        filtered_losses = filtered[filtered['profit_rate'] <= 0]

        total_profit_winning = filtered['profit_rate'].sum()
        avg_profit_winning = filtered['profit_rate'].mean()
        win_rate_winning = len(filtered_wins) / len(filtered) * 100 if len(filtered) > 0 else 0

        print(f"\n[승리 조합 거래 상세]")
        print(f"  승: {len(filtered_wins)}건")
        print(f"  패: {len(filtered_losses)}건")
        print(f"  승률: {win_rate_winning:.1f}%")
        print(f"  총 수익: {total_profit_winning:.2f}%")
        print(f"  평균 수익률: {avg_profit_winning:.3f}%")

        # 제외된 거래 분석
        excluded_wins = excluded[excluded['profit_rate'] > 0]

        print(f"\n[제외된 거래 상세]")
        print(f"  거래 수: {len(excluded)}건")
        print(f"  승: {len(excluded_wins)}건")
        print(f"  패: {len(excluded) - len(excluded_wins)}건")
        if len(excluded) > 0:
            print(f"  승률: {len(excluded_wins)/len(excluded)*100:.1f}%")
            print(f"  총 수익: {excluded['profit_rate'].sum():.2f}%")

        print("\n" + "=" * 80)
        print("5. 성과 비교")
        print("=" * 80)

        # 수익 변화
        profit_change = total_profit_winning - total_profit
        profit_change_pct = (profit_change / total_profit * 100) if total_profit != 0 else 0

        # 평균 수익률 변화
        avg_change = avg_profit_winning - avg_profit
        avg_change_pct = (avg_change / avg_profit * 100) if avg_profit != 0 else 0

        # 승률 변화
        win_rate_before = len(wins) / len(traded) * 100
        win_rate_change = win_rate_winning - win_rate_before

        print(f"\n[총 수익]")
        print(f"  전체 거래: {total_profit:.2f}%")
        print(f"  승리 조합만: {total_profit_winning:.2f}%")
        print(f"  변화: {profit_change:+.2f}% ({profit_change_pct:+.1f}%)")

        print(f"\n[평균 수익률]")
        print(f"  전체 거래: {avg_profit:.3f}%")
        print(f"  승리 조합만: {avg_profit_winning:.3f}%")
        print(f"  변화: {avg_change:+.3f}% ({avg_change_pct:+.1f}%)")

        print(f"\n[승률]")
        print(f"  전체 거래: {win_rate_before:.1f}%")
        print(f"  승리 조합만: {win_rate_winning:.1f}%")
        print(f"  변화: {win_rate_change:+.1f}%p")

        print(f"\n[거래 수]")
        print(f"  전체 거래: {len(traded)}건")
        print(f"  승리 조합만: {len(filtered)}건")
        print(f"  감소: {len(excluded)}건 ({len(excluded)/len(traded)*100:.1f}%)")

        # 거래당 투자금 증액 시뮬레이션
        print("\n" + "=" * 80)
        print("6. 거래당 투자금 최적화")
        print("=" * 80)

        total_capital = 1100  # 1100만원
        current_per_trade = 100  # 현재 100만원

        print(f"\n총 투자 가능 금액: {total_capital}만원")
        print(f"\n시나리오 비교:")

        # 시나리오 1: 현재 (전체 거래, 100만원)
        scenario1_trades = len(traded)
        scenario1_per_trade = current_per_trade
        scenario1_profit = total_profit
        scenario1_profit_won = scenario1_profit / 100 * scenario1_per_trade * 10000
        print(f"\n[현재] 전체 거래 + 100만원/건")
        print(f"  거래 수: {scenario1_trades}건")
        print(f"  총 수익률: {scenario1_profit:.2f}%")
        print(f"  총 수익금: {scenario1_profit_won:,.0f}원")

        # 시나리오 2: 승리 조합만, 투자금 증액
        scenario2_trades = len(filtered)
        # 거래 수 감소율에 따른 투자금 증액
        trade_reduction = len(excluded) / len(traded)
        scenario2_per_trade = min(current_per_trade * (1 + trade_reduction * 0.5), total_capital / 10)  # 보수적 증액
        scenario2_profit = total_profit_winning
        scenario2_profit_won = scenario2_profit / 100 * scenario2_per_trade * 10000

        print(f"\n[개선안] 승리 조합만 + {scenario2_per_trade:.0f}만원/건")
        print(f"  거래 수: {scenario2_trades}건 (-{len(excluded)/len(traded)*100:.1f}%)")
        print(f"  거래당 투자금: {scenario2_per_trade:.0f}만원 (+{(scenario2_per_trade/current_per_trade-1)*100:.1f}%)")
        print(f"  총 수익률: {scenario2_profit:.2f}% ({profit_change:+.2f}%)")
        print(f"  총 수익금: {scenario2_profit_won:,.0f}원")
        print(f"  수익금 변화: {scenario2_profit_won - scenario1_profit_won:+,.0f}원 ({(scenario2_profit_won/scenario1_profit_won-1)*100:+.1f}%)")

        print("\n" + "=" * 80)
        print("7. 결론")
        print("=" * 80)

        if win_rate_winning > win_rate_before and avg_profit_winning > avg_profit:
            print(f"\n[OK] 승리 조합 필터 효과 확인!")
            print(f"  승률: {win_rate_before:.1f}% -> {win_rate_winning:.1f}% ({win_rate_change:+.1f}%p)")
            print(f"  평균 수익률: {avg_profit:.3f}% -> {avg_profit_winning:.3f}% ({avg_change_pct:+.1f}%)")
            print(f"  거래당 수익금: {scenario1_profit_won/scenario1_trades:,.0f}원 -> {scenario2_profit_won/scenario2_trades:,.0f}원")
            print(f"\n  [추천] 승리 조합만 매매하고 거래당 투자금을 증액하세요!")
        else:
            print(f"\n[INFO] 승리 조합 필터 적용 시 주의 필요")

        # CSV 저장
        winning_combos.to_csv('winning_combinations.csv', index=False, encoding='utf-8-sig')
        print(f"\n승리 조합 저장: winning_combinations.csv")

    else:
        print("\n[INFO] 기준을 만족하는 승리 조합이 없습니다.")
        print("기준을 완화하여 다시 분석하시겠습니까?")

        # 기준 완화 분석
        print("\n" + "=" * 80)
        print("기준 완화 분석")
        print("=" * 80)

        for min_winrate in [55, 50]:
            for min_avg_profit in [0.4, 0.3]:
                relaxed_combos = combo_df[
                    (combo_df['승률'] >= min_winrate) &
                    (combo_df['평균수익률'] >= min_avg_profit) &
                    (combo_df['거래수'] >= 10)
                ]
                print(f"\n승률 {min_winrate}%+, 평균수익 {min_avg_profit}%+, 거래 10건+: {len(relaxed_combos)}개")

    return combo_df


if __name__ == '__main__':
    combo_df = analyze_winning_combinations()
