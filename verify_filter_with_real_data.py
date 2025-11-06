#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
실제 패턴 데이터로 필터 검증

pattern_data_*.jsonl 파일을 읽어서 필터가 실제로 작동하는지 확인
"""

import json
from pathlib import Path
from core.indicators.pattern_combination_filter import PatternCombinationFilter


def verify_filter_with_real_data():
    """실제 패턴 데이터로 필터 검증"""

    print("=" * 80)
    print("실제 패턴 데이터로 필터 검증")
    print("=" * 80)

    # 필터 초기화
    filter = PatternCombinationFilter()

    # pattern_data 디렉토리 찾기
    pattern_data_dir = Path('pattern_data_log')
    if not pattern_data_dir.exists():
        print(f"\n[오류] {pattern_data_dir} 디렉토리가 없습니다.")
        return

    # 모든 JSONL 파일 찾기
    jsonl_files = list(pattern_data_dir.glob('pattern_data_*.jsonl'))

    if not jsonl_files:
        print(f"\n[오류] {pattern_data_dir}에 JSONL 파일이 없습니다.")
        return

    print(f"\n발견된 파일: {len(jsonl_files)}개")

    total_patterns = 0
    patterns_with_debug_info = 0
    excluded_patterns = 0
    passed_patterns = 0

    excluded_details = []

    # 모든 파일 읽기
    for jsonl_file in sorted(jsonl_files):
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                    total_patterns += 1

                    # debug_info 확인
                    debug_info = record.get('pattern_stages', {})

                    if not debug_info:
                        continue

                    patterns_with_debug_info += 1

                    # 필터 적용
                    should_exclude, reason = filter.should_exclude(debug_info)

                    if should_exclude:
                        excluded_patterns += 1
                        excluded_details.append({
                            'file': jsonl_file.name,
                            'line': line_num,
                            'stock_code': record.get('stock_code', 'N/A'),
                            'date': record.get('date', 'N/A'),
                            'time': record.get('time', 'N/A'),
                            'reason': reason,
                            'debug_info': debug_info
                        })
                    else:
                        passed_patterns += 1

                except json.JSONDecodeError as e:
                    print(f"[경고] {jsonl_file.name} 라인 {line_num}: JSON 파싱 실패")
                    continue

    # 결과 출력
    print("\n" + "=" * 80)
    print("분석 결과")
    print("=" * 80)

    print(f"\n총 패턴: {total_patterns}개")
    print(f"debug_info 있는 패턴: {patterns_with_debug_info}개")
    print(f"필터로 제외된 패턴: {excluded_patterns}개 ({excluded_patterns/patterns_with_debug_info*100:.1f}%)" if patterns_with_debug_info > 0 else "")
    print(f"통과한 패턴: {passed_patterns}개 ({passed_patterns/patterns_with_debug_info*100:.1f}%)" if patterns_with_debug_info > 0 else "")

    # 제외된 패턴 상세
    if excluded_patterns > 0:
        print("\n" + "=" * 80)
        print(f"제외된 패턴 상세 (최대 20개)")
        print("=" * 80)

        for i, detail in enumerate(excluded_details[:20], 1):
            print(f"\n{i}. 종목: {detail['stock_code']}, 날짜: {detail['date']} {detail['time']}")
            print(f"   파일: {detail['file']} (라인 {detail['line']})")
            print(f"   제외 이유: {detail['reason']}")

            # 패턴 상세
            uptrend = detail['debug_info'].get('uptrend', {})
            decline = detail['debug_info'].get('decline', {})
            support = detail['debug_info'].get('support', {})

            print(f"   상승: {uptrend.get('price_gain', 'N/A')}")
            print(f"   하락: {decline.get('decline_pct', 'N/A')}")
            print(f"   지지: {support.get('candle_count', 'N/A')}개")
    else:
        print("\n[정보] 제외된 패턴이 없습니다!")
        print("가능한 이유:")
        print("  1. 실제로 마이너스 조합이 발생하지 않음")
        print("  2. debug_info의 구조가 다름")
        print("  3. 필터 로직에 문제가 있음")

    # 샘플 패턴 구조 출력 (첫 번째 패턴)
    if patterns_with_debug_info > 0:
        print("\n" + "=" * 80)
        print("샘플 패턴 구조 (첫 번째 패턴)")
        print("=" * 80)

        for jsonl_file in sorted(jsonl_files):
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        debug_info = record.get('pattern_stages', {})
                        if debug_info:
                            print(json.dumps(debug_info, indent=2, ensure_ascii=False))
                            return
                    except:
                        continue


if __name__ == '__main__':
    verify_filter_with_real_data()
