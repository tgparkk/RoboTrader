#!/usr/bin/env python3
"""패턴 로그 JSONL 파일 무결성 검증"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
from pathlib import Path

log_dir = Path('pattern_data_log')
log_files = sorted(log_dir.glob('pattern_data_2025*.jsonl'))

total_files = 0
total_lines = 0
parse_errors = 0
error_details = []

print("=" * 70)
print("🔍 패턴 로그 JSONL 무결성 검증")
print("=" * 70)

for log_file in log_files:
    total_files += 1
    file_errors = 0

    with open(log_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                total_lines += 1
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    parse_errors += 1
                    file_errors += 1
                    error_details.append({
                        'file': log_file.name,
                        'line': line_num,
                        'error': str(e)
                    })

                    # 처음 5개 오류만 상세 출력
                    if len(error_details) <= 5:
                        print(f"⚠️  {log_file.name}:{line_num} - {e}")

    if file_errors > 0:
        print(f"  ❌ {log_file.name}: {file_errors}개 오류")

print("\n" + "=" * 70)
print("📊 검증 결과")
print("=" * 70)
print(f"총 파일: {total_files}개")
print(f"총 라인: {total_lines:,}개")
print(f"파싱 오류: {parse_errors:,}개 ({parse_errors/total_lines*100 if total_lines > 0 else 0:.3f}%)")

if parse_errors == 0:
    print("\n✅ 모든 JSONL 파일이 정상입니다!")
    print("   병렬 쓰기로 인한 문제가 없습니다.")
else:
    print(f"\n⚠️  {parse_errors}개의 파싱 오류 발견!")
    print("   병렬 쓰기로 인한 데이터 손상 가능성 있음.")

    if len(error_details) > 5:
        print(f"\n   (상세 오류 {len(error_details)}개 중 처음 5개만 표시됨)")

print("=" * 70)
