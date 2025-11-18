"""
필터 로직 vs 분석 결과 비교

analyze_4stage_combination_patterns.py의 분석 결과와
four_stage_combination_filter.py의 필터 로직을 비교하여
필터가 올바르게 설계되었는지 검증
"""

import csv
from core.indicators.four_stage_combination_filter import FourStageCombinationFilter

# 분석 결과 읽기
combinations = []
with open('4stage_combinations.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        combinations.append(row)

print("="*80)
print("[필터 vs 분석 결과 비교]")
print("="*80)

filter = FourStageCombinationFilter()

# 필터에서 가점 부여하는 조합
print("\n[필터가 가점 부여하는 조합]")
for combo in filter.high_win_rate_combinations:
    pattern_str = f"{combo['상승']} + {combo['하락']} + {combo['지지']} + {combo['돌파']}"
    print(f"\n{pattern_str} (가점: +{combo['bonus']})")

    # 분석 결과에서 찾기
    for row in combinations:
        if (row['상승'] == combo['상승'] and
            row['하락'] == combo['하락'] and
            row['지지'] == combo['지지'] and
            row['돌파'] == combo['돌파']):

            trades = int(row['거래수'])
            wins = int(row['승리'])
            win_rate = float(row['승률'].replace('%', ''))
            total_profit = float(row['총수익'].replace('%', ''))

            print(f"  분석 결과: {trades}건, 승률 {win_rate:.1f}%, 총수익 {total_profit:+.2f}%")
            break
    else:
        print(f"  ⚠️ 분석 결과에서 찾을 수 없음 (실제 데이터에 없는 조합)")

# 필터에서 감점/차단하는 조합
print("\n" + "="*80)
print("[필터가 감점/차단하는 조합]")
for combo in filter.low_win_rate_combinations:
    # 조합 문자열 생성
    parts = []
    for key in ['상승', '하락', '지지', '돌파']:
        if key in combo:
            parts.append(f"{key}={combo[key]}")

    pattern_str = " + ".join(parts)
    penalty = combo['penalty']

    print(f"\n{pattern_str} (감점: {penalty})")

    # 부분 매칭 (모든 조건을 만족하는 패턴 찾기)
    matching_combos = []
    for row in combinations:
        match = True
        for key in ['상승', '하락', '지지', '돌파']:
            if key in combo:
                if row[key] != combo[key]:
                    match = False
                    break
        if match:
            matching_combos.append(row)

    if matching_combos:
        print(f"  매칭된 조합: {len(matching_combos)}개")
        for row in matching_combos:
            trades = int(row['거래수'])
            wins = int(row['승리'])
            win_rate = float(row['승률'].replace('%', ''))
            total_profit = float(row['총수익'].replace('%', ''))

            pattern_str2 = f"{row['상승']} + {row['하락']} + {row['지지']} + {row['돌파']}"
            status = "🚫" if total_profit < 0 else "✓" if total_profit > 0 else "="

            print(f"  {status} {pattern_str2}")
            print(f"     {trades}건, 승률 {win_rate:.1f}%, 총수익 {total_profit:+.2f}%")
    else:
        print(f"  ⚠️ 분석 결과에서 찾을 수 없음 (실제 데이터에 없는 조합)")

# 가장 중요한 문제: 고수익 조합을 차단하는 경우
print("\n" + "="*80)
print("[필터 문제점 분석]")
print("="*80)

print("\n[필터가 차단하는 조합 중 수익이 플러스인 경우]")
bad_blocks = []

for combo in filter.low_win_rate_combinations:
    if combo['penalty'] <= -100:  # 차단 수준
        # 매칭되는 조합 찾기
        for row in combinations:
            match = True
            for key in ['상승', '하락', '지지', '돌파']:
                if key in combo:
                    if row[key] != combo[key]:
                        match = False
                        break
            if match:
                total_profit = float(row['총수익'].replace('%', ''))
                if total_profit > 0:  # 수익이 플러스인데 차단
                    bad_blocks.append({
                        'pattern': f"{row['상승']} + {row['하락']} + {row['지지']} + {row['돌파']}",
                        'trades': int(row['거래수']),
                        'win_rate': float(row['승률'].replace('%', '')),
                        'profit': total_profit
                    })

if bad_blocks:
    print(f"⚠️ 총 {len(bad_blocks)}개의 수익 조합을 차단하고 있습니다!")
    for item in bad_blocks:
        print(f"\n  {item['pattern']}")
        print(f"  {item['trades']}건, 승률 {item['win_rate']:.1f}%, 총수익 {item['profit']:+.2f}%")
else:
    print("문제 없음 - 차단하는 조합은 모두 손실 조합입니다.")

print("\n" + "="*80)
