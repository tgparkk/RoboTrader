"""
4단계 조합 필터 정확도 분석
필터가 차단/감점한 패턴이 실제로 손실 패턴이었는지 검증
"""

import os
import json
import logging
from core.indicators.four_stage_combination_filter import FourStageCombinationFilter

logging.basicConfig(level=logging.WARNING)  # 로그 최소화
logger = logging.getLogger(__name__)

# 필터 초기화
combo_filter = FourStageCombinationFilter(logger=logger)

# pattern_data_log 디렉토리 읽기
log_dir = 'pattern_data_log'

# 통계
bonus_correct = 0  # 가점 → 승리
bonus_wrong = 0    # 가점 → 패배
penalty_correct = 0  # 감점 → 패배
penalty_wrong = 0    # 감점 → 승리
blocked_correct = 0  # 차단 → 패배 (정답)
blocked_wrong = 0    # 차단 → 승리 (오류!)

for filename in os.listdir(log_dir):
    if not filename.endswith('.jsonl'):
        continue

    filepath = os.path.join(log_dir, filename)

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line.strip())

                # pattern_stages와 actual_result가 있는 경우만 처리
                if 'pattern_stages' not in data or 'actual_result' not in data:
                    continue

                debug_info = data['pattern_stages']
                result = data['actual_result']

                # 실제 결과 (승리/패배)
                actual_win = result.get('result') == 'WIN'

                # 필터 적용
                bonus_penalty, reason = combo_filter.calculate_bonus_penalty(debug_info)

                if bonus_penalty == 0:
                    continue

                # 차단 여부 (임의 신뢰도 50 기준)
                would_be_blocked = (50 + bonus_penalty <= 0)

                if would_be_blocked:
                    # 차단된 경우
                    if actual_win:
                        blocked_wrong += 1  # 승리를 차단 → 오류!
                    else:
                        blocked_correct += 1  # 패배를 차단 → 정답!
                elif bonus_penalty > 0:
                    # 가점
                    if actual_win:
                        bonus_correct += 1
                    else:
                        bonus_wrong += 1
                else:
                    # 감점 (차단은 아님)
                    if actual_win:
                        penalty_wrong += 1
                    else:
                        penalty_correct += 1

            except (json.JSONDecodeError, KeyError):
                continue

print("="*80)
print("[필터 정확도 분석]")
print("="*80)

print("\n[가점 부여한 경우]")
print(f"  가점 → 승리: {bonus_correct}회 (정답)")
print(f"  가점 → 패배: {bonus_wrong}회 (오류)")
if bonus_correct + bonus_wrong > 0:
    bonus_accuracy = bonus_correct / (bonus_correct + bonus_wrong) * 100
    print(f"  가점 정확도: {bonus_accuracy:.1f}%")

print("\n[감점 부여한 경우 (차단 제외)]")
print(f"  감점 → 패배: {penalty_correct}회 (정답)")
print(f"  감점 → 승리: {penalty_wrong}회 (오류)")
if penalty_correct + penalty_wrong > 0:
    penalty_accuracy = penalty_correct / (penalty_correct + penalty_wrong) * 100
    print(f"  감점 정확도: {penalty_accuracy:.1f}%")

print("\n[차단한 경우]")
print(f"  차단 → 패배: {blocked_correct}회 (정답)")
print(f"  차단 → 승리: {blocked_wrong}회 (오류!)")
if blocked_correct + blocked_wrong > 0:
    blocked_accuracy = blocked_correct / (blocked_correct + blocked_wrong) * 100
    print(f"  차단 정확도: {blocked_accuracy:.1f}%")
    print(f"  🚨 잘못 차단된 승리: {blocked_wrong}회")

print("\n[전체 필터 성능]")
total_correct = bonus_correct + penalty_correct + blocked_correct
total_wrong = bonus_wrong + penalty_wrong + blocked_wrong
total = total_correct + total_wrong

if total > 0:
    overall_accuracy = total_correct / total * 100
    print(f"  전체 정확도: {overall_accuracy:.1f}%")
    print(f"  총 정답: {total_correct}회")
    print(f"  총 오류: {total_wrong}회")

# 가장 큰 문제: 승리 패턴을 차단한 경우
print("\n" + "="*80)
print("[필터 문제점 요약]")
print("="*80)

if blocked_wrong > 0:
    print(f"⚠️ 필터가 {blocked_wrong}개의 승리 패턴을 차단했습니다!")
    print(f"   이는 수익 기회를 놓친 것입니다.")

if blocked_wrong > blocked_correct:
    print(f"🚨 차단한 패턴 중 오히려 승리가 더 많습니다! ({blocked_wrong} vs {blocked_correct})")
    print(f"   필터 로직을 재검토해야 합니다.")

if penalty_wrong > penalty_correct:
    print(f"⚠️ 감점한 패턴 중 오히려 승리가 더 많습니다! ({penalty_wrong} vs {penalty_correct})")

if bonus_wrong > bonus_correct:
    print(f"⚠️ 가점한 패턴 중 오히려 패배가 더 많습니다! ({bonus_wrong} vs {bonus_correct})")

print("="*80)
