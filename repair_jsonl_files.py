#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
손상된 JSONL 파일 복구 스크립트

JSON 파싱 오류가 있는 라인을 제거하고 유효한 데이터만 남깁니다.
"""

import json
from pathlib import Path
import shutil


def repair_jsonl_file(file_path: Path):
    """JSONL 파일 복구"""
    if not file_path.exists():
        print(f"파일 없음: {file_path}")
        return

    print(f"\n처리 중: {file_path.name}")

    # 백업 생성
    backup_path = file_path.with_suffix('.jsonl.backup')
    shutil.copy2(file_path, backup_path)
    print(f"  백업 생성: {backup_path.name}")

    # 유효한 레코드만 읽기
    valid_records = []
    invalid_count = 0

    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                try:
                    record = json.loads(line)
                    # 한번 더 직렬화해서 검증
                    json_str = json.dumps(record, ensure_ascii=False)
                    json.loads(json_str)
                    valid_records.append(record)
                except json.JSONDecodeError as e:
                    print(f"  [라인 {line_num}] 파싱 실패: {e}")
                    invalid_count += 1

    # 유효한 레코드로 파일 다시 쓰기
    with open(file_path, 'w', encoding='utf-8') as f:
        for record in valid_records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

    print(f"  결과: {len(valid_records)}개 유효, {invalid_count}개 제거")


def main():
    """전체 pattern_data_log 디렉토리 복구"""
    log_dir = Path('pattern_data_log')

    if not log_dir.exists():
        print(f"디렉토리 없음: {log_dir}")
        return

    jsonl_files = sorted(log_dir.glob('pattern_data_*.jsonl'))

    print(f"================================================================================")
    print(f"JSONL 파일 복구")
    print(f"================================================================================")
    print(f"대상 파일: {len(jsonl_files)}개")

    for jsonl_file in jsonl_files:
        repair_jsonl_file(jsonl_file)

    print(f"\n================================================================================")
    print(f"복구 완료!")
    print(f"================================================================================")
    print(f"백업 파일: pattern_data_log/*.jsonl.backup")


if __name__ == '__main__':
    main()
