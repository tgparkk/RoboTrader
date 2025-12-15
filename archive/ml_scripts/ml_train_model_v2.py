#!/usr/bin/env python3
"""
ML 모델 학습 및 검증 (V2 - 일봉 데이터 포함)

데이터: ml_dataset_v2.csv
모델: LightGBM
목표: 패턴 신호의 승/패 예측 (일봉 데이터 및 기술적 지표 포함)
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    roc_curve,
    precision_recall_curve
)
import lightgbm as lgb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pickle

sys.stdout.reconfigure(encoding='utf-8')


def load_and_prepare_data(csv_file: str = 'ml_dataset_v2.csv'):
    """데이터 로드 및 전처리"""
    print("=" * 70)
    print("📂 데이터 로드 중... (V2 - 일봉 데이터 포함)")
    print("=" * 70)

    df = pd.read_csv(csv_file, encoding='utf-8-sig', low_memory=False)
    print(f"데이터 로드 완료: {len(df)}행")

    # 메타데이터 컬럼 제거
    meta_cols = ['stock_code', 'pattern_id', 'timestamp', 'sell_reason', 'profit_rate']
    feature_cols = [col for col in df.columns if col not in meta_cols + ['label']]

    X = df[feature_cols].copy()
    y = df['label'].copy()

    # 범주형 변수 인코딩 (signal_type)
    le = LabelEncoder()
    if 'signal_type' in X.columns:
        X['signal_type'] = le.fit_transform(X['signal_type'].astype(str))

    # 결측치 처리
    X = X.fillna(0)

    print(f"\n특징(feature) 수: {len(feature_cols)}")
    print(f"라벨 분포: 승리={y.sum()} ({y.mean()*100:.1f}%), 패배={len(y)-y.sum()} ({(1-y.mean())*100:.1f}%)")

    # 특성 그룹별 개수
    pattern_features = [col for col in feature_cols if not col.startswith(('daily_', 'price_change_', 'volume_change_', 'rsi_', 'macd_', 'bb_', 'ma', 'volatility_', 'high_low_'))]
    daily_features = [col for col in feature_cols if col not in pattern_features]

    print(f"\n특성 구성:")
    print(f"  - 패턴 특성: {len(pattern_features)}개")
    print(f"  - 일봉/기술지표 특성: {len(daily_features)}개")

    return X, y, feature_cols, le


def train_lightgbm_model(X_train, y_train, X_val, y_val, feature_names):
    """LightGBM 모델 학습"""
    print("\n" + "=" * 70)
    print("🚀 LightGBM 모델 학습 시작 (V2)")
    print("=" * 70)

    # LightGBM 하이퍼파라미터 (과적합 방지 강화)
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.03,  # 학습률 낮춤 (더 안정적)
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 20,
        'max_depth': 6,
        'lambda_l1': 0.5,  # L1 정규화
        'lambda_l2': 0.5,  # L2 정규화
        'verbose': -1,
        'seed': 42
    }

    # 데이터셋 생성
    lgb_train = lgb.Dataset(X_train, y_train, feature_name=feature_names)
    lgb_val = lgb.Dataset(X_val, y_val, reference=lgb_train, feature_name=feature_names)

    # 학습
    print("학습 중...")
    model = lgb.train(
        params,
        lgb_train,
        num_boost_round=1000,
        valid_sets=[lgb_train, lgb_val],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=50)
        ]
    )

    print(f"✅ 학습 완료: 최적 반복 횟수 = {model.best_iteration}")
    return model


def evaluate_model(model, X_test, y_test, feature_names, output_dir='ml_results_v2'):
    """모델 평가 및 결과 저장"""
    print("\n" + "=" * 70)
    print("📊 모델 평가")
    print("=" * 70)

    Path(output_dir).mkdir(exist_ok=True)

    # 예측
    y_pred_proba = model.predict(X_test, num_iteration=model.best_iteration)
    y_pred = (y_pred_proba > 0.5).astype(int)

    # 성능 지표
    print("\n분류 리포트:")
    print(classification_report(y_test, y_pred, target_names=['패배', '승리']))

    # 혼동 행렬
    cm = confusion_matrix(y_test, y_pred)
    print("\n혼동 행렬:")
    print(f"             예측: 패배  예측: 승리")
    print(f"실제 패배:   {cm[0][0]:>6}    {cm[0][1]:>6}")
    print(f"실제 승리:   {cm[1][0]:>6}    {cm[1][1]:>6}")

    # AUC
    auc_score = roc_auc_score(y_test, y_pred_proba)
    print(f"\n🎯 Test AUC: {auc_score:.4f}")

    # ROC Curve 저장
    fpr, tpr, thresholds = roc_curve(y_test, y_pred_proba)
    plt.figure(figsize=(10, 6))
    plt.plot(fpr, tpr, label=f'ROC Curve (AUC = {auc_score:.4f})')
    plt.plot([0, 1], [0, 1], 'k--', label='Random')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('ROC Curve - V2 Model')
    plt.legend()
    plt.grid(True)
    plt.savefig(f'{output_dir}/roc_curve_v2.png', dpi=150)
    print(f"✅ ROC Curve 저장: {output_dir}/roc_curve_v2.png")

    # Feature Importance
    importance_df = pd.DataFrame({
        'feature': feature_names,
        'importance': model.feature_importance(importance_type='gain')
    }).sort_values('importance', ascending=False)

    print("\n🔝 Top 20 중요 특성:")
    for i, row in importance_df.head(20).iterrows():
        print(f"  {row['feature']:30s}: {row['importance']:>10.0f}")

    # Feature Importance 저장
    plt.figure(figsize=(12, 10))
    top_features = importance_df.head(30)
    plt.barh(range(len(top_features)), top_features['importance'])
    plt.yticks(range(len(top_features)), top_features['feature'])
    plt.xlabel('Importance (Gain)')
    plt.title('Top 30 Feature Importance - V2 Model')
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(f'{output_dir}/feature_importance_v2.png', dpi=150)
    print(f"✅ Feature Importance 저장: {output_dir}/feature_importance_v2.png")

    # 일봉 특성 vs 패턴 특성 중요도 비교
    pattern_features = [f for f in feature_names if not f.startswith(('daily_', 'price_change_', 'volume_change_', 'rsi_', 'macd_', 'bb_', 'ma', 'volatility_', 'high_low_'))]
    daily_features = [f for f in feature_names if f not in pattern_features]

    pattern_importance = importance_df[importance_df['feature'].isin(pattern_features)]['importance'].sum()
    daily_importance = importance_df[importance_df['feature'].isin(daily_features)]['importance'].sum()
    total_importance = pattern_importance + daily_importance

    print(f"\n📊 특성 그룹별 중요도:")
    print(f"  패턴 특성: {pattern_importance:>10.0f} ({pattern_importance/total_importance*100:.1f}%)")
    print(f"  일봉/기술지표: {daily_importance:>10.0f} ({daily_importance/total_importance*100:.1f}%)")

    # CSV 저장
    importance_df.to_csv(f'{output_dir}/feature_importance_v2.csv', index=False, encoding='utf-8-sig')

    return auc_score, importance_df


def cross_validate_model(X, y, feature_names):
    """교차 검증"""
    print("\n" + "=" * 70)
    print("🔄 5-Fold 교차 검증")
    print("=" * 70)

    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.03,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 20,
        'max_depth': 6,
        'lambda_l1': 0.5,
        'lambda_l2': 0.5,
        'verbose': -1,
        'seed': 42
    }

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = []

    for fold, (train_idx, val_idx) in enumerate(cv.split(X, y), 1):
        X_train_fold, X_val_fold = X.iloc[train_idx], X.iloc[val_idx]
        y_train_fold, y_val_fold = y.iloc[train_idx], y.iloc[val_idx]

        lgb_train = lgb.Dataset(X_train_fold, y_train_fold, feature_name=feature_names)
        lgb_val = lgb.Dataset(X_val_fold, y_val_fold, reference=lgb_train, feature_name=feature_names)

        model_cv = lgb.train(
            params,
            lgb_train,
            num_boost_round=1000,
            valid_sets=[lgb_val],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50),
                lgb.log_evaluation(period=0)  # 출력 억제
            ]
        )

        y_pred_proba = model_cv.predict(X_val_fold, num_iteration=model_cv.best_iteration)
        auc = roc_auc_score(y_val_fold, y_pred_proba)
        cv_scores.append(auc)
        print(f"Fold {fold}: AUC = {auc:.4f}")

    print(f"\n평균 CV AUC: {np.mean(cv_scores):.4f} ± {np.std(cv_scores):.4f}")
    return cv_scores


def save_model(model, label_encoder, feature_names, output_file='ml_model_v2.pkl'):
    """모델 저장"""
    model_data = {
        'model': model,
        'label_encoder': label_encoder,
        'feature_names': feature_names,
        'version': 'v2',
        'description': 'LightGBM model with daily data and technical indicators'
    }

    with open(output_file, 'wb') as f:
        pickle.dump(model_data, f)

    print(f"\n✅ 모델 저장 완료: {output_file}")
    print(f"   모델 크기: {Path(output_file).stat().st_size / 1024:.1f} KB")


def main():
    print("=" * 70)
    print("🤖 ML 모델 학습 시스템 V2 (일봉 데이터 포함)")
    print("=" * 70)

    # 1. 데이터 로드
    X, y, feature_names, label_encoder = load_and_prepare_data('ml_dataset_v2.csv')

    # 2. 데이터 분할 (시간 기반: 60% 학습, 20% 검증, 20% 테스트)
    print("\n" + "=" * 70)
    print("✂️ 데이터 분할 (시간 기반)")
    print("=" * 70)

    train_split = int(len(X) * 0.6)
    val_split = int(len(X) * 0.8)

    X_train = X.iloc[:train_split]
    y_train = y.iloc[:train_split]

    X_val = X.iloc[train_split:val_split]
    y_val = y.iloc[train_split:val_split]

    X_test = X.iloc[val_split:]
    y_test = y.iloc[val_split:]

    print(f"학습 세트: {len(X_train)}개 (승률 {y_train.mean()*100:.1f}%)")
    print(f"검증 세트: {len(X_val)}개 (승률 {y_val.mean()*100:.1f}%)")
    print(f"테스트 세트: {len(X_test)}개 (승률 {y_test.mean()*100:.1f}%)")

    # 3. 교차 검증
    cv_scores = cross_validate_model(X, y, feature_names)

    # 4. 모델 학습
    model = train_lightgbm_model(X_train, y_train, X_val, y_val, feature_names)

    # 5. 모델 평가
    test_auc, importance_df = evaluate_model(model, X_test, y_test, feature_names)

    # 6. 모델 저장
    save_model(model, label_encoder, feature_names, 'ml_model_v2.pkl')

    # 7. 요약
    print("\n" + "=" * 70)
    print("📈 최종 성과 요약")
    print("=" * 70)
    print(f"교차 검증 AUC: {np.mean(cv_scores):.4f} ± {np.std(cv_scores):.4f}")
    print(f"테스트 AUC:     {test_auc:.4f}")
    print(f"\n특성 수: {len(feature_names)}개")
    print(f"샘플 수: {len(X)}개 (학습 {len(X_train)}, 검증 {len(X_val)}, 테스트 {len(X_test)})")

    # V1 모델과 비교 (있는 경우)
    if Path('ml_model.pkl').exists():
        print("\n" + "=" * 70)
        print("🔄 V1 모델과 비교")
        print("=" * 70)
        print("V1 모델 (패턴만): 특성 26개")
        print("V2 모델 (패턴+일봉): 특성 68개")
        print(f"특성 증가: +{len(feature_names) - 26}개 (+{(len(feature_names) - 26) / 26 * 100:.0f}%)")


if __name__ == '__main__':
    main()
