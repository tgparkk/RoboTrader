"""
4단계 조합 필터 작동 진단
실제 pattern_data_log 데이터로 필터가 제대로 작동하는지 확인
"""

import os
import json
import logging
from core.indicators.four_stage_combination_filter import FourStageCombinationFilter

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# 필터 초기화
combo_filter = FourStageCombinationFilter(logger=logger)

# pattern_data_log 디렉토리 읽기
log_dir = 'pattern_data_log'
activation_count = 0
total_count = 0
bonus_count = 0
penalty_count = 0
blocked_count = 0

print("="*80)
print("[4단계 조합 필터 작동 진단]")
print("="*80)

for filename in os.listdir(log_dir):
    if not filename.endswith('.jsonl'):
        continue

    filepath = os.path.join(log_dir, filename)

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line.strip())

                # pattern_stages가 있는 경우만 처리
                if 'pattern_stages' not in data:
                    continue

                total_count += 1

                # pattern_stages를 debug_info 형식으로 변환
                debug_info = data['pattern_stages']

                # 필터 적용
                bonus_penalty, reason = combo_filter.calculate_bonus_penalty(debug_info)

                if bonus_penalty != 0:
                    activation_count += 1

                    if bonus_penalty > 0:
                        bonus_count += 1
                        print(f"\n[가점 +{bonus_penalty}]")
                    else:
                        penalty_count += 1
                        print(f"\n[감점 {bonus_penalty}]")

                        # 차단 여부 확인 (임의 신뢰도 50 기준)
                        if 50 + bonus_penalty <= 0:
                            blocked_count += 1
                            print(f"  -> 차단됨 (신뢰도 50 + {bonus_penalty} = {50 + bonus_penalty})")

                    print(f"  이유: {reason}")
                    print(f"  파일: {filename}")

                    # 패턴 정보 출력
                    pattern = combo_filter.classify_pattern_from_debug_info(debug_info)
                    print(f"  패턴: {combo_filter._format_pattern(pattern)}")

                    # 실제 결과 출력
                    if 'actual_result' in data:
                        result = data['actual_result']
                        print(f"  실제 결과: {result.get('result', 'N/A')} (수익: {result.get('profit', 'N/A')})")

            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"오류 발생: {e}")
                continue

print("\n" + "="*80)
print("[진단 결과 요약]")
print("="*80)
print(f"총 패턴 수: {total_count}")
print(f"필터 활성화: {activation_count}회 ({activation_count/total_count*100:.1f}%)")
print(f"  - 가점 부여: {bonus_count}회")
print(f"  - 감점 부여: {penalty_count}회")
print(f"  - 차단: {blocked_count}회")
print(f"필터 미활성화: {total_count - activation_count}회 ({(total_count-activation_count)/total_count*100:.1f}%)")
print("="*80)

if activation_count == 0:
    print("\n⚠️ 경고: 필터가 한 번도 활성화되지 않았습니다!")
    print("가능한 원인:")
    print("1. debug_info 구조가 필터와 맞지 않음")
    print("2. 패턴 분류 로직에 문제가 있음")
    print("3. 고승률/저승률 조합이 실제 데이터에 없음")
