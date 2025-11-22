#!/usr/bin/env python3
"""업그레이드된 패턴 로그 검증"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
from pathlib import Path

# 업그레이드된 파일 샘플 확인
log_file = Path('pattern_data_log/pattern_data_20250902.jsonl')

with open(log_file, 'r', encoding='utf-8') as f:
    sample = json.loads(f.readline())

print("=" * 70)
print("📋 업그레이드된 로그 샘플 검증")
print("=" * 70)

print(f"\npattern_id: {sample['pattern_id']}")
print(f"\n✅ 새로운 필드 확인:")
print(f"  - signal_time: {'✓' if 'signal_time' in sample else '✗'}")
print(f"  - log_timestamp: {'✓' if 'log_timestamp' in sample else '✗'}")
print(f"  - signal_snapshot: {'✓' if 'signal_snapshot' in sample else '✗'}")

print(f"\n📅 시각 정보:")
print(f"  - signal_time: {sample.get('signal_time', 'N/A')}")
print(f"  - log_timestamp: {sample.get('log_timestamp', 'N/A')}")
print(f"  - old timestamp: {sample.get('timestamp', 'N/A')}")

# 기술 지표 확인
ti = sample.get('signal_snapshot', {}).get('technical_indicators_1min', {})
print(f"\n📊 기술 지표 (1분봉):")
print(f"  - 지표 수: {len(ti)}개")
if ti:
    print(f"  - 주요 지표:")
    for key, value in list(ti.items())[:10]:
        if isinstance(value, float):
            print(f"    • {key}: {value:.2f}")
        else:
            print(f"    • {key}: {value}")

# Lookback 시퀀스 확인
lb = sample.get('signal_snapshot', {}).get('lookback_sequence_1min', [])
print(f"\n📈 Lookback 시퀀스 (1분봉):")
print(f"  - 시퀀스 길이: {len(lb)}개")
if lb:
    first = lb[0]
    last = lb[-1]
    print(f"  - 첫 번째 캔들: {first.get('datetime', 'N/A')}")
    print(f"  - 마지막 캔들: {last.get('datetime', 'N/A')}")

print("\n" + "=" * 70)
print("✅ 업그레이드 검증 완료!")
print("=" * 70)
