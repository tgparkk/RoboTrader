#!/usr/bin/env python3
"""패턴 로그의 매매 결과 업데이트 상태 확인"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
from pathlib import Path

log_dir = Path('pattern_data_log')
log_files = sorted(log_dir.glob('pattern_data_2025*.jsonl'))

total_patterns = 0
patterns_with_trade = 0
patterns_without_trade = 0

print("=" * 70)
print("📊 패턴 로그 매매 결과 상태 확인")
print("=" * 70)

for log_file in log_files:  # 전체 파일 확인
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    record = json.loads(line)
                    total_patterns += 1

                    trade_result = record.get('trade_result')
                    if trade_result and trade_result.get('trade_executed') == True:
                        patterns_with_trade += 1
                    else:
                        patterns_without_trade += 1

                except Exception:
                    pass

print(f"\n전체 파일 확인:")
print(f"  총 패턴: {total_patterns:,}개")
print(f"  매매 결과 있음: {patterns_with_trade:,}개 ({patterns_with_trade/total_patterns*100 if total_patterns > 0 else 0:.1f}%)")
print(f"  매매 결과 없음: {patterns_without_trade:,}개 ({patterns_without_trade/total_patterns*100 if total_patterns > 0 else 0:.1f}%)")

print("\n" + "=" * 70)
if patterns_with_trade == 0:
    print("❌ 매매 결과가 없습니다!")
    print("\n다음 중 하나를 실행해야 합니다:")
    print("  1. python batch_signal_replay.py -s 20250901 -e 20251120")
    print("     (전체 백테스트 재실행 - 시간 소요)")
    print("\n  2. 병합 스크립트로 기존 signal_replay_log 결과 활용")
    print("     (빠름, 추천)")
elif patterns_with_trade < total_patterns * 0.5:
    print("⚠️  매매 결과가 부분적으로만 있습니다.")
    print(f"  {patterns_without_trade:,}개 패턴의 매매 결과를 추가해야 합니다.")
else:
    print("✅ 대부분의 패턴에 매매 결과가 있습니다!")
    print("  ML 학습 데이터셋 생성 가능합니다.")
print("=" * 70)
