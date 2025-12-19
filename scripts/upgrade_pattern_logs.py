#!/usr/bin/env python3
"""
기존 패턴 로그를 신규 형식으로 업그레이드

추가할 정보:
1. signal_time (pattern_id에서 추출)
2. log_timestamp (기존 timestamp를 사용)
3. signal_snapshot (1분봉 데이터로부터 계산)
   - technical_indicators_3min/1min
   - lookback_sequence_1min
4. post_trade_analysis (매매 결과가 있는 경우만)
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from typing import Dict, Any, Optional

try:
    from tqdm import tqdm as tqdm_func
except ImportError:
    # tqdm이 없으면 기본 반복자 사용
    def tqdm_func(iterable, desc=""):
        return iterable

# 패턴 로거 임포트 (기술 지표 계산 로직 재사용)
from core.pattern_data_logger import PatternDataLogger


def extract_signal_time_from_pattern_id(pattern_id: str) -> Optional[datetime]:
    """
    pattern_id에서 signal_time 추출
    형식: {stock_code}_{YYYYMMDD}_{HHMMSS}
    예: 347850_20251105_191023
    """
    try:
        parts = pattern_id.split('_')
        if len(parts) >= 3:
            date_str = parts[1]  # 20251105
            time_str = parts[2]  # 191023

            datetime_str = f"{date_str}_{time_str}"
            return datetime.strptime(datetime_str, '%Y%m%d_%H%M%S')
    except Exception as e:
        print(f"⚠️ pattern_id 파싱 실패 ({pattern_id}): {e}")

    return None


def load_minute_data(stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
    """1분봉 데이터 로드"""
    try:
        cache_file = Path(f'cache/minute_data/{stock_code}_{date_str}.pkl')
        if cache_file.exists():
            df = pd.read_pickle(cache_file)
            # datetime 컬럼 확인
            if 'datetime' not in df.columns and 'time' in df.columns:
                df['datetime'] = pd.to_datetime(df['time'])
            return df
    except Exception as e:
        print(f"⚠️ {stock_code} 1분봉 로드 실패: {e}")

    return None


def upgrade_pattern_log(log_file: Path, dry_run: bool = False) -> Dict[str, int]:
    """
    패턴 로그 파일을 신규 형식으로 업그레이드

    Args:
        log_file: 업그레이드할 로그 파일
        dry_run: True이면 변경사항만 확인하고 실제 쓰기는 안함

    Returns:
        통계 딕셔너리
    """
    stats = {
        'total': 0,
        'upgraded': 0,
        'failed': 0,
        'skipped': 0
    }

    print(f"\n📂 처리 중: {log_file.name}")

    # 로그 읽기
    records = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    record = json.loads(line)
                    records.append(record)
                    stats['total'] += 1
                except Exception as e:
                    print(f"⚠️ JSON 파싱 실패: {e}")
                    stats['failed'] += 1

    print(f"  총 {stats['total']}개 패턴 로드됨")

    # 패턴 로거 인스턴스 (기술 지표 계산용)
    date_str = log_file.stem.replace('pattern_data_', '')
    pattern_logger = PatternDataLogger()

    # 각 레코드 업그레이드
    for i, record in enumerate(tqdm_func(records, desc="  업그레이드")):
        try:
            # 이미 업그레이드된 경우 스킵
            if 'signal_time' in record and 'signal_snapshot' in record:
                stats['skipped'] += 1
                continue

            # 1. signal_time 추출
            pattern_id = record.get('pattern_id', '')
            signal_time = extract_signal_time_from_pattern_id(pattern_id)

            if not signal_time:
                stats['failed'] += 1
                continue

            # 2. log_timestamp 설정 (기존 timestamp 사용)
            log_timestamp = record.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

            # 3. 1분봉 데이터 로드
            stock_code = record.get('stock_code', '')
            df_1min = load_minute_data(stock_code, signal_time.strftime('%Y%m%d'))

            # 4. signal_snapshot 계산
            signal_snapshot = {
                'technical_indicators_3min': {},
                'technical_indicators_1min': {},
                'lookback_sequence_1min': []
            }

            if df_1min is not None and not df_1min.empty:
                # 1분봉에서 신호 시점 찾기
                signal_1min_data = df_1min[df_1min['datetime'] <= signal_time]
                if not signal_1min_data.empty:
                    signal_1min_idx = len(signal_1min_data) - 1

                    # 기술적 지표 계산
                    signal_snapshot['technical_indicators_1min'] = pattern_logger._calculate_technical_indicators(
                        df_1min, signal_1min_idx
                    )

                    # Lookback 시퀀스
                    signal_snapshot['lookback_sequence_1min'] = pattern_logger._extract_lookback_sequence(
                        df_1min, signal_time, lookback_minutes=60
                    )

            # 5. post_trade_analysis 계산 (매매 결과가 있는 경우)
            trade_result = record.get('trade_result')
            if trade_result and trade_result.get('trade_executed') and df_1min is not None:
                # 매수 시각 = signal_time
                # 매도 시각은 추정 불가능 (기존 로그에 없음) - 패스
                pass

            # 6. 레코드 업데이트
            record['signal_time'] = signal_time.strftime('%Y-%m-%d %H:%M:%S')
            record['log_timestamp'] = log_timestamp
            record['signal_snapshot'] = signal_snapshot

            # timestamp 필드는 유지 (하위 호환성)

            stats['upgraded'] += 1

        except Exception as e:
            print(f"⚠️ 레코드 {i} 업그레이드 실패: {e}")
            stats['failed'] += 1

    # 7. 파일 쓰기 (dry_run이 아닌 경우)
    if not dry_run and stats['upgraded'] > 0:
        backup_file = log_file.with_suffix('.jsonl.backup')

        # 백업 (이미 있으면 삭제)
        if backup_file.exists():
            backup_file.unlink()
        log_file.rename(backup_file)
        print(f"  ✅ 백업 생성: {backup_file.name}")

        # 새 파일 쓰기
        with open(log_file, 'w', encoding='utf-8') as f:
            for record in records:
                json_str = json.dumps(record, ensure_ascii=False)
                f.write(json_str + '\n')

        print(f"  ✅ 업그레이드 완료: {stats['upgraded']}개")

    return stats


def main():
    print("=" * 70)
    print("🔄 패턴 로그 업그레이드")
    print("=" * 70)

    log_dir = Path('pattern_data_log')
    log_files = sorted(log_dir.glob('pattern_data_2025*.jsonl'))

    print(f"\n📊 총 {len(log_files)}개 파일 발견")

    # Dry run으로 먼저 확인
    print("\n=== Dry Run (변경사항 확인) ===")
    total_stats = {'total': 0, 'upgraded': 0, 'failed': 0, 'skipped': 0}

    for log_file in log_files[:3]:  # 처음 3개만 테스트
        stats = upgrade_pattern_log(log_file, dry_run=True)
        for key in total_stats:
            total_stats[key] += stats[key]

    print("\n=== Dry Run 결과 ===")
    print(f"총 패턴: {total_stats['total']}")
    print(f"업그레이드 필요: {total_stats['upgraded']}")
    print(f"이미 완료: {total_stats['skipped']}")
    print(f"실패: {total_stats['failed']}")

    if total_stats['upgraded'] == 0:
        print("\n업그레이드할 패턴이 없습니다.")
        return

    print("\n자동으로 업그레이드를 진행합니다...")

    print("\n=== 실제 업그레이드 시작 ===")
    total_stats = {'total': 0, 'upgraded': 0, 'failed': 0, 'skipped': 0}

    for log_file in log_files:
        stats = upgrade_pattern_log(log_file, dry_run=False)
        for key in total_stats:
            total_stats[key] += stats[key]

    print("\n" + "=" * 70)
    print("✅ 업그레이드 완료")
    print("=" * 70)
    print(f"총 패턴: {total_stats['total']}")
    print(f"업그레이드: {total_stats['upgraded']}")
    print(f"이미 완료: {total_stats['skipped']}")
    print(f"실패: {total_stats['failed']}")


if __name__ == '__main__':
    main()
