#!/usr/bin/env python3
"""
signal_replay_log의 매매 결과를 pattern_data_log에 병합

signal_replay_log/*.txt 파일에서 매매 결과를 읽어서
pattern_data_log/*.jsonl 파일의 trade_result 필드를 업데이트
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

def parse_trade_result_from_log(log_file: Path) -> Dict[str, dict]:
    """
    signal_replay_log 파일에서 매매 결과 파싱

    Returns:
        Dict[매칭키, trade_result]
        매칭키 형식: {stock_code}_{YYYYMMDD}_{HHMM} (분까지만)
    """
    trade_results = {}

    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 날짜 추출 (파일명에서)
    date_match = re.search(r'(\d{8})', log_file.stem)
    if not date_match:
        print(f"⚠️ 날짜 파싱 실패: {log_file.name}")
        return trade_results

    trade_date = date_match.group(1)  # YYYYMMDD

    # 매매 기록 파싱
    # 형식 예: "   🔴 174900 09:21 매수 → -2.50%"
    #          "   🟢 087010 09:27 매수 → +3.50%"
    pattern = r'[🔴🟢]\s+(\d{6})\s+(\d{2}):(\d{2})\s+매수\s+→\s+([-+]\d+\.\d+)%'

    for match in re.finditer(pattern, content):
        stock_code = match.group(1)
        hour = match.group(2)
        minute = match.group(3)
        profit_rate = float(match.group(4))

        # 매칭 키 생성 (분까지만 사용)
        match_key = f"{stock_code}_{trade_date}_{hour}{minute}"

        # 승/패 판단
        is_win = profit_rate > 0

        trade_results[match_key] = {
            'trade_executed': True,
            'profit_rate': profit_rate,
            'win': is_win,
            'loss': not is_win
        }

    return trade_results

def merge_trade_results_to_pattern_log(log_file: Path, trade_results: Dict[str, dict], dry_run: bool = False) -> Tuple[int, int]:
    """
    패턴 로그에 매매 결과 병합 (±3분 범위 매칭)

    Returns:
        Tuple[업데이트된 패턴 수, 총 패턴 수]
    """
    updated_count = 0
    total_count = 0

    # 로그 읽기
    records = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    record = json.loads(line)
                    records.append(record)
                    total_count += 1
                except Exception as e:
                    print(f"⚠️ JSON 파싱 실패: {e}")

    # 매매 결과 병합 (±3분 범위 매칭)
    for record in records:
        pattern_id = record.get('pattern_id', '')

        # pattern_id에서 시간 정보 추출
        # 예: 174900_20251120_092137 → 09:21
        try:
            parts = pattern_id.split('_')
            if len(parts) >= 3:
                stock_code = parts[0]
                date = parts[1]
                time_str = parts[2]  # HHMMSS

                # 시간을 분 단위로 변환
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                signal_minutes = hour * 60 + minute

                # ±3분 범위에서 매칭 시도
                matched = False
                for offset in range(-3, 4):  # -3, -2, -1, 0, +1, +2, +3
                    check_minutes = signal_minutes + offset
                    check_hour = check_minutes // 60
                    check_minute = check_minutes % 60

                    # 매칭 키 생성
                    match_key = f"{stock_code}_{date}_{check_hour:02d}{check_minute:02d}"

                    if match_key in trade_results:
                        # 매매 결과 업데이트
                        record['trade_result'] = trade_results[match_key]
                        updated_count += 1
                        matched = True
                        break
        except Exception:
            pass

    # 파일 쓰기
    if not dry_run and updated_count > 0:
        backup_file = log_file.with_suffix('.jsonl.merge_backup')

        # 백업 (이미 있으면 삭제)
        if backup_file.exists():
            backup_file.unlink()
        log_file.rename(backup_file)

        # 새 파일 쓰기
        with open(log_file, 'w', encoding='utf-8') as f:
            for record in records:
                json_str = json.dumps(record, ensure_ascii=False)
                f.write(json_str + '\n')

    return updated_count, total_count

def main():
    print("=" * 70)
    print("🔄 매매 결과 병합")
    print("=" * 70)

    # signal_replay_log 파일들 찾기
    signal_log_dir = Path('signal_replay_log')
    signal_log_files = sorted(signal_log_dir.glob('signal_new2_replay_2025*.txt'))

    print(f"\n📂 signal_replay_log: {len(signal_log_files)}개 파일")

    # 모든 매매 결과 파싱
    all_trade_results = {}

    for log_file in signal_log_files:
        trade_results = parse_trade_result_from_log(log_file)
        all_trade_results.update(trade_results)
        print(f"  {log_file.name}: {len(trade_results)}개 매매 결과")

    print(f"\n📊 총 {len(all_trade_results)}개 매매 결과 파싱됨")

    if len(all_trade_results) == 0:
        print("\n❌ 매매 결과가 없습니다!")
        return

    # pattern_data_log 파일들 찾기
    pattern_log_dir = Path('pattern_data_log')
    pattern_log_files = sorted(pattern_log_dir.glob('pattern_data_2025*.jsonl'))

    print(f"\n📂 pattern_data_log: {len(pattern_log_files)}개 파일")

    # Dry run으로 먼저 확인
    print("\n=== Dry Run (변경사항 확인) ===")
    total_updated = 0
    total_patterns = 0

    for log_file in pattern_log_files:
        updated, total = merge_trade_results_to_pattern_log(log_file, all_trade_results, dry_run=True)
        total_updated += updated
        total_patterns += total

        if updated > 0:
            print(f"  {log_file.name}: {updated}/{total}개 업데이트 예정")

    print(f"\n=== Dry Run 결과 ===")
    print(f"총 패턴: {total_patterns:,}개")
    print(f"업데이트 예정: {total_updated:,}개 ({total_updated/total_patterns*100 if total_patterns > 0 else 0:.1f}%)")

    if total_updated == 0:
        print("\n업데이트할 패턴이 없습니다.")
        return

    print("\n자동으로 병합을 진행합니다...")

    # 실제 병합
    print("\n=== 실제 병합 시작 ===")
    total_updated = 0
    total_patterns = 0

    for log_file in pattern_log_files:
        updated, total = merge_trade_results_to_pattern_log(log_file, all_trade_results, dry_run=False)
        total_updated += updated
        total_patterns += total

        if updated > 0:
            print(f"  ✅ {log_file.name}: {updated}/{total}개 업데이트")

    print("\n" + "=" * 70)
    print("✅ 병합 완료")
    print("=" * 70)
    print(f"총 패턴: {total_patterns:,}개")
    print(f"업데이트: {total_updated:,}개 ({total_updated/total_patterns*100 if total_patterns > 0 else 0:.1f}%)")
    print(f"미업데이트: {total_patterns - total_updated:,}개")

if __name__ == '__main__':
    main()
