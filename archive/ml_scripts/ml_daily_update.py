"""
ML 모델 일일 자동 업데이트 스크립트

사용법:
    # 어제 데이터로 업데이트
    python ml_daily_update.py

    # 특정 날짜 데이터로 업데이트
    python ml_daily_update.py --date 20251118

    # 최근 N일 데이터 전체 재학습
    python ml_daily_update.py --days 90
"""

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import json


def get_yesterday_date():
    """어제 날짜 반환 (YYYYMMDD)"""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime('%Y%m%d')


def check_pattern_data_exists(date_str):
    """해당 날짜의 패턴 데이터가 있는지 확인"""
    log_file = Path(f"pattern_data_log/pattern_data_{date_str}.jsonl")
    if not log_file.exists():
        print(f"⚠️  {date_str} 패턴 데이터 없음: {log_file}")
        return False

    # 파일 크기 확인
    file_size = log_file.stat().st_size
    if file_size == 0:
        print(f"⚠️  {date_str} 패턴 데이터 비어있음")
        return False

    # 패턴 개수 확인
    with open(log_file, 'r', encoding='utf-8') as f:
        pattern_count = sum(1 for _ in f)

    print(f"✅ {date_str} 패턴 데이터: {pattern_count}개 패턴, {file_size:,} bytes")
    return True


def run_command(cmd, description):
    """명령어 실행"""
    print(f"\n{'='*60}")
    print(f"📌 {description}")
    print(f"{'='*60}")
    print(f"실행: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ 오류 발생:")
        print(result.stderr)
        return False

    print(result.stdout)
    return True


def incremental_update(date_str):
    """증분 업데이트: 특정 날짜 데이터만 추가하여 재학습"""
    print(f"\n🔄 증분 업데이트 시작: {date_str}")

    # 1. 해당 날짜 데이터 확인
    if not check_pattern_data_exists(date_str):
        return False

    # 2. ML 데이터셋 준비 (기존 데이터 + 새 데이터)
    success = run_command(
        ["python", "ml_prepare_dataset.py"],
        f"ML 데이터셋 생성 (pattern_data_log의 모든 데이터 사용)"
    )
    if not success:
        return False

    # 3. 모델 재학습
    success = run_command(
        ["python", "ml_train_model_stratified.py"],
        "Stratified ML 모델 재학습"
    )
    if not success:
        return False

    # 4. 백업 생성
    backup_model()

    print(f"\n✅ 증분 업데이트 완료!")
    return True


def full_retrain(days):
    """전체 재학습: 최근 N일 데이터로 완전히 재학습"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')

    print(f"\n🔄 전체 재학습 시작: {start_str} ~ {end_str} ({days}일)")

    # 1. 데이터 수집 (시뮬레이션 결과 활용)
    # 주의: save_daily_data_for_ml.py는 시뮬레이션 백테스트를 실행하므로 시간이 오래 걸림
    print(f"\n⚠️  전체 재학습은 시뮬레이션 백테스트를 다시 실행합니다.")
    print(f"   이 작업은 수 시간이 걸릴 수 있습니다.")

    response = input(f"   {days}일 백테스트를 실행하시겠습니까? (y/N): ")
    if response.lower() != 'y':
        print("❌ 사용자가 취소했습니다.")
        return False

    success = run_command(
        ["python", "save_daily_data_for_ml.py", "--start", start_str, "--end", end_str],
        f"시뮬레이션 백테스트 ({days}일)"
    )
    if not success:
        return False

    # 2. ML 데이터셋 생성
    success = run_command(
        ["python", "ml_prepare_dataset.py"],
        "ML 데이터셋 생성"
    )
    if not success:
        return False

    # 3. 모델 학습
    success = run_command(
        ["python", "ml_train_model_stratified.py"],
        "Stratified ML 모델 학습"
    )
    if not success:
        return False

    # 4. 백업 생성
    backup_model()

    print(f"\n✅ 전체 재학습 완료!")
    return True


def backup_model():
    """현재 모델 백업"""
    model_file = Path("ml_model_stratified.pkl")
    if not model_file.exists():
        print("⚠️  백업할 모델이 없습니다.")
        return

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = Path("model_backups")
    backup_dir.mkdir(exist_ok=True)

    backup_file = backup_dir / f"ml_model_stratified_{timestamp}.pkl"

    import shutil
    shutil.copy(model_file, backup_file)

    print(f"💾 모델 백업: {backup_file}")


def show_model_info():
    """현재 모델 정보 출력"""
    model_file = Path("ml_model_stratified.pkl")
    if not model_file.exists():
        print("❌ ML 모델 파일이 없습니다.")
        return

    # 모델 파일 정보
    file_stat = model_file.stat()
    modified_time = datetime.fromtimestamp(file_stat.st_mtime)

    print(f"\n📊 현재 ML 모델 정보")
    print(f"{'='*60}")
    print(f"파일: {model_file}")
    print(f"크기: {file_stat.st_size:,} bytes")
    print(f"최종 업데이트: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 데이터셋 정보
    dataset_file = Path("ml_dataset.csv")
    if dataset_file.exists():
        df = pd.read_csv(dataset_file)
        print(f"\n학습 데이터:")
        print(f"  총 패턴 수: {len(df):,}개")
        print(f"  승리: {len(df[df['label']==1]):,}개")
        print(f"  패배: {len(df[df['label']==0]):,}개")
        print(f"  승률: {len(df[df['label']==1])/len(df)*100:.1f}%")

        # 날짜 범위
        if 'timestamp' in df.columns:
            df['date'] = pd.to_datetime(df['timestamp']).dt.date
            print(f"  기간: {df['date'].min()} ~ {df['date'].max()}")

    # 최근 패턴 데이터
    log_dir = Path("pattern_data_log")
    if log_dir.exists():
        log_files = sorted(log_dir.glob("pattern_data_*.jsonl"), reverse=True)
        if log_files:
            print(f"\n최근 패턴 데이터:")
            for log_file in log_files[:5]:
                date_str = log_file.stem.replace('pattern_data_', '')
                with open(log_file, 'r', encoding='utf-8') as f:
                    count = sum(1 for _ in f)
                print(f"  {date_str}: {count}개 패턴")


def main():
    parser = argparse.ArgumentParser(description='ML 모델 일일 자동 업데이트')
    parser.add_argument('--date', type=str, help='업데이트할 날짜 (YYYYMMDD, 기본값: 어제)')
    parser.add_argument('--days', type=int, help='전체 재학습 기간 (일 수)')
    parser.add_argument('--info', action='store_true', help='현재 모델 정보만 출력')

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"🤖 ML 모델 자동 업데이트")
    print(f"{'='*60}")

    # 정보 출력 모드
    if args.info:
        show_model_info()
        return

    # 전체 재학습 모드
    if args.days:
        success = full_retrain(args.days)
        if success:
            show_model_info()
        sys.exit(0 if success else 1)

    # 증분 업데이트 모드 (기본)
    date_str = args.date if args.date else get_yesterday_date()
    success = incremental_update(date_str)

    if success:
        show_model_info()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
