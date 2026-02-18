#!/usr/bin/env python3
"""
두 데이터셋 병합 스크립트 (기존 파일 보존)

입력:
- ml_dataset.csv (기존 모델 데이터)
- ml_dataset_dynamic_pl.csv (동적 손익비 데이터)

출력:
- ml_dataset_merged.csv (새 파일, 기존 파일 보존)
"""

import pandas as pd
import os

def merge_datasets():
    """두 데이터셋을 병합하여 새 파일로 저장"""

    print("=" * 80)
    print("데이터셋 병합 스크립트")
    print("=" * 80)

    # 파일 존재 확인
    if not os.path.exists('ml_dataset.csv'):
        print("❌ ml_dataset.csv가 없습니다.")
        return

    if not os.path.exists('ml_dataset_dynamic_pl.csv'):
        print("❌ ml_dataset_dynamic_pl.csv가 없습니다.")
        return

    # 데이터 로드
    print("\n[1/4] 데이터 로드 중...")
    df1 = pd.read_csv('ml_dataset.csv', encoding='utf-8-sig')
    df2 = pd.read_csv('ml_dataset_dynamic_pl.csv', encoding='utf-8-sig')

    print(f"  ml_dataset.csv: {len(df1)}건")
    print(f"  ml_dataset_dynamic_pl.csv: {len(df2)}건")

    # 공통 컬럼만 선택
    print("\n[2/4] 컬럼 정렬 중...")
    common_cols = list(set(df1.columns) & set(df2.columns))

    print(f"  공통 컬럼: {len(common_cols)}개")

    # df1 전용 컬럼
    df1_only = set(df1.columns) - set(df2.columns)
    if df1_only:
        print(f"  ml_dataset.csv 전용: {df1_only}")

    # df2 전용 컬럼
    df2_only = set(df2.columns) - set(df1.columns)
    if df2_only:
        print(f"  ml_dataset_dynamic_pl.csv 전용: {df2_only}")

    # 공통 컬럼으로 정렬
    df1 = df1[common_cols]
    df2 = df2[common_cols]

    # 병합
    print("\n[3/4] 병합 중...")
    df_merged = pd.concat([df1, df2], ignore_index=True)
    print(f"  병합 후: {len(df_merged)}건")

    # 중복 제거 (같은 날짜/시간/종목 조합)
    print("\n[4/4] 중복 제거 중...")

    if 'stock_code' in df_merged.columns:
        # 날짜 컬럼 확인
        date_col = None
        time_col = None

        if 'date' in df_merged.columns:
            date_col = 'date'
        elif 'timestamp' in df_merged.columns:
            date_col = 'timestamp'

        if 'buy_time' in df_merged.columns:
            time_col = 'buy_time'

        # 중복 제거 키 설정
        dedup_cols = ['stock_code']
        if date_col:
            dedup_cols.append(date_col)
        if time_col:
            dedup_cols.append(time_col)

        before = len(df_merged)
        df_merged = df_merged.drop_duplicates(subset=dedup_cols, keep='first')
        removed = before - len(df_merged)

        print(f"  중복 제거: {removed}건 제거")
        print(f"  최종: {len(df_merged)}건")
    else:
        print("  stock_code 컬럼이 없어 중복 제거를 스킵합니다.")

    # 저장
    output_file = 'ml_dataset_merged.csv'
    df_merged.to_csv(output_file, index=False, encoding='utf-8-sig')

    print(f"\n[OK] 저장 완료: {output_file}")
    print(f"   총 {len(df_merged)}건")
    print(f"   승률: {df_merged['label'].mean()*100:.1f}%")

    # 통계
    print("\n" + "=" * 80)
    print("데이터셋 통계")
    print("=" * 80)

    print(f"\n라벨 분포:")
    print(f"  - 승리: {df_merged['label'].sum()}건 ({df_merged['label'].mean()*100:.1f}%)")
    print(f"  - 패배: {len(df_merged) - df_merged['label'].sum()}건 ({(1-df_merged['label'].mean())*100:.1f}%)")

    if 'profit_rate' in df_merged.columns:
        print(f"\n수익률:")
        print(f"  - 평균: {df_merged['profit_rate'].mean():.2f}%")
        print(f"  - 승리 시: {df_merged[df_merged['label']==1]['profit_rate'].mean():.2f}%")
        print(f"  - 패배 시: {df_merged[df_merged['label']==0]['profit_rate'].mean():.2f}%")

    # 컬럼 정보
    print(f"\n컬럼 정보:")
    meta_cols = ['stock_code', 'stock_name', 'date', 'buy_time', 'profit_rate', 'pattern_id', 'timestamp', 'sell_reason']
    feature_cols = [col for col in df_merged.columns if col not in meta_cols + ['label']]
    print(f"  - 전체 컬럼: {len(df_merged.columns)}개")
    print(f"  - 특성 컬럼: {len(feature_cols)}개")
    print(f"  - 메타 컬럼: {len([c for c in df_merged.columns if c in meta_cols])}개")

    print("\n" + "=" * 80)
    print("다음 단계:")
    print("  python train_ml_merged.py  # 병합 데이터로 학습")
    print("=" * 80)


if __name__ == "__main__":
    merge_datasets()
