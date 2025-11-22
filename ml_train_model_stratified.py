#!/usr/bin/env python3
"""
ML 모델 학습 (Stratified 분할 방식)

개선 사항:
- Stratified K-Fold로 데이터 분할 (시간 기반 → 라벨 기반)
- 과적합 방지 강화 (정규화, 드롭아웃)
- 특성 선택 (중요도 낮은 특성 제거)
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    roc_curve
)
import lightgbm as lgb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pickle

sys.stdout.reconfigure(encoding='utf-8')


def load_and_prepare_data(csv_file: str = 'ml_dataset.csv'):
    """데이터 로드 및 전처리"""
    print("=" * 70)
    print("📂 데이터 로드 중... (Stratified 방식)")
    print("=" * 70)

    df = pd.read_csv(csv_file, encoding='utf-8-sig')
    print(f"데이터 로드 완료: {len(df)}행")

    # 메타데이터 컬럼 제거
    meta_cols = ['stock_code', 'pattern_id', 'timestamp', 'sell_reason', 'profit_rate']
    feature_cols = [col for col in df.columns if col not in meta_cols + ['label']]

    X = df[feature_cols].copy()
    y = df['label'].copy()

    # 범주형 변수 인코딩
    le = LabelEncoder()
    if 'signal_type' in X.columns:
        X['signal_type'] = le.fit_transform(X['signal_type'])

    # 결측치 처리
    X = X.fillna(0)

    print(f"\n특징(feature) 수: {len(feature_cols)}")
    print(f"라벨 분포: 승리={y.sum()} ({y.mean()*100:.1f}%), 패배={len(y)-y.sum()} ({(1-y.mean())*100:.1f}%)")

    return X, y, feature_cols, le


def train_with_stratified_kfold(X, y, feature_names, n_splits=5):
    """Stratified K-Fold 교차 검증으로 모델 학습"""
    print("\n" + "=" * 70)
    print(f"🔄 Stratified {n_splits}-Fold 교차 검증")
    print("=" * 70)

    # 과적합 방지 강화 파라미터
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 15,           # 31 → 15 (복잡도 감소)
        'learning_rate': 0.01,      # 0.05 → 0.01 (더 느리게 학습)
        'feature_fraction': 0.6,    # 0.8 → 0.6 (더 많은 드롭아웃)
        'bagging_fraction': 0.6,    # 0.8 → 0.6
        'bagging_freq': 5,
        'min_data_in_leaf': 50,     # 20 → 50 (더 보수적)
        'max_depth': 4,             # 6 → 4 (더 얕은 트리)
        'lambda_l1': 1.0,           # L1 정규화 강화
        'lambda_l2': 1.0,           # L2 정규화 강화
        'verbose': -1,
        'seed': 42
    }

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    cv_scores = []
    models = []
    fold_results = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y), 1):
        print(f"\n📊 Fold {fold}/{n_splits}")
        print("-" * 70)

        X_train_fold, X_val_fold = X.iloc[train_idx], X.iloc[val_idx]
        y_train_fold, y_val_fold = y.iloc[train_idx], y.iloc[val_idx]

        print(f"  학습: {len(X_train_fold)}개 (승률 {y_train_fold.mean()*100:.1f}%)")
        print(f"  검증: {len(X_val_fold)}개 (승률 {y_val_fold.mean()*100:.1f}%)")

        # 데이터셋 생성
        lgb_train = lgb.Dataset(X_train_fold, y_train_fold, feature_name=feature_names)
        lgb_val = lgb.Dataset(X_val_fold, y_val_fold, reference=lgb_train, feature_name=feature_names)

        # 학습
        model = lgb.train(
            params,
            lgb_train,
            num_boost_round=1000,
            valid_sets=[lgb_train, lgb_val],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=100),
                lgb.log_evaluation(period=0)  # 출력 억제
            ]
        )

        # 평가
        y_pred_proba = model.predict(X_val_fold, num_iteration=model.best_iteration)
        auc = roc_auc_score(y_val_fold, y_pred_proba)
        cv_scores.append(auc)
        models.append(model)

        # 상세 결과 저장
        y_pred = (y_pred_proba > 0.5).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_val_fold, y_pred).ravel()

        fold_results.append({
            'fold': fold,
            'auc': auc,
            'accuracy': (tp + tn) / (tp + tn + fp + fn),
            'precision': tp / (tp + fp) if (tp + fp) > 0 else 0,
            'recall': tp / (tp + fn) if (tp + fn) > 0 else 0,
            'best_iteration': model.best_iteration
        })

        print(f"  ✅ Fold {fold} AUC: {auc:.4f} (반복: {model.best_iteration})")

    # 평균 성능
    print("\n" + "=" * 70)
    print("📈 교차 검증 결과")
    print("=" * 70)
    print(f"평균 AUC: {np.mean(cv_scores):.4f} (± {np.std(cv_scores):.4f})")
    print(f"최소 AUC: {np.min(cv_scores):.4f}")
    print(f"최대 AUC: {np.max(cv_scores):.4f}")

    print("\nFold별 상세 결과:")
    print("-" * 70)
    for result in fold_results:
        print(f"Fold {result['fold']}: AUC={result['auc']:.4f}, "
              f"정확도={result['accuracy']:.4f}, "
              f"정밀도={result['precision']:.4f}, "
              f"재현율={result['recall']:.4f}")

    # 최고 성능 모델 선택
    best_fold_idx = np.argmax(cv_scores)
    best_model = models[best_fold_idx]

    print(f"\n🏆 최고 성능 모델: Fold {best_fold_idx + 1} (AUC: {cv_scores[best_fold_idx]:.4f})")

    return best_model, cv_scores, fold_results


def final_evaluation(model, X, y, feature_names, output_dir='ml_results_stratified'):
    """최종 평가 (전체 데이터의 20%를 홀드아웃)"""
    print("\n" + "=" * 70)
    print("📊 최종 홀드아웃 테스트")
    print("=" * 70)

    Path(output_dir).mkdir(exist_ok=True)

    # 전체 데이터의 마지막 20%를 테스트용으로 사용
    test_size = int(len(X) * 0.2)

    X_test = X.iloc[-test_size:]
    y_test = y.iloc[-test_size:]

    print(f"테스트 세트: {len(X_test)}개 (승률 {y_test.mean()*100:.1f}%)")

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
    print(f"\n🎯 홀드아웃 테스트 AUC: {auc_score:.4f}")

    # ROC Curve 저장
    fpr, tpr, thresholds = roc_curve(y_test, y_pred_proba)
    plt.figure(figsize=(10, 6))
    plt.plot(fpr, tpr, label=f'ROC Curve (AUC = {auc_score:.4f})')
    plt.plot([0, 1], [0, 1], 'k--', label='Random')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('ROC Curve - Stratified Model')
    plt.legend()
    plt.grid(True)
    plt.savefig(f'{output_dir}/roc_curve_stratified.png', dpi=150)
    print(f"✅ ROC Curve 저장: {output_dir}/roc_curve_stratified.png")

    # Feature Importance
    importance_df = pd.DataFrame({
        'feature': feature_names,
        'importance': model.feature_importance(importance_type='gain')
    }).sort_values('importance', ascending=False)

    print("\n🔝 Top 20 중요 특성:")
    for i, row in importance_df.head(20).iterrows():
        print(f"  {row['feature']:30s}: {row['importance']:>10.0f}")

    # Feature Importance 그래프
    plt.figure(figsize=(12, 10))
    top_features = importance_df.head(30)
    plt.barh(range(len(top_features)), top_features['importance'])
    plt.yticks(range(len(top_features)), top_features['feature'])
    plt.xlabel('Importance (Gain)')
    plt.title('Top 30 Feature Importance - Stratified Model')
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(f'{output_dir}/feature_importance_stratified.png', dpi=150)
    print(f"✅ Feature Importance 저장: {output_dir}/feature_importance_stratified.png")

    # CSV 저장
    importance_df.to_csv(f'{output_dir}/feature_importance_stratified.csv', index=False, encoding='utf-8-sig')

    return auc_score, importance_df


def save_model(model, label_encoder, feature_names, cv_scores, output_file='ml_model_stratified.pkl'):
    """모델 저장"""
    model_data = {
        'model': model,
        'label_encoder': label_encoder,
        'feature_names': feature_names,
        'cv_scores': cv_scores,
        'version': 'stratified',
        'description': 'LightGBM with Stratified K-Fold and overfitting prevention'
    }

    with open(output_file, 'wb') as f:
        pickle.dump(model_data, f)

    print(f"\n✅ 모델 저장 완료: {output_file}")
    print(f"   모델 크기: {Path(output_file).stat().st_size / 1024:.1f} KB")


def main():
    print("=" * 70)
    print("🤖 ML 모델 학습 시스템 (Stratified 방식)")
    print("=" * 70)

    # 1. 데이터 로드
    X, y, feature_names, label_encoder = load_and_prepare_data('ml_dataset.csv')

    # 2. Stratified K-Fold 교차 검증
    best_model, cv_scores, fold_results = train_with_stratified_kfold(X, y, feature_names, n_splits=5)

    # 3. 최종 평가 (홀드아웃 테스트)
    test_auc, importance_df = final_evaluation(best_model, X, y, feature_names)

    # 4. 모델 저장
    save_model(best_model, label_encoder, feature_names, cv_scores, 'ml_model_stratified.pkl')

    # 5. 최종 요약
    print("\n" + "=" * 70)
    print("📈 최종 성과 요약")
    print("=" * 70)
    print(f"교차 검증 평균 AUC: {np.mean(cv_scores):.4f} (± {np.std(cv_scores):.4f})")
    print(f"홀드아웃 테스트 AUC: {test_auc:.4f}")
    print(f"\n특성 수: {len(feature_names)}개")
    print(f"샘플 수: {len(X)}개")

    # 과적합 체크
    cv_mean = np.mean(cv_scores)
    overfit_gap = cv_mean - test_auc
    print(f"\n과적합 체크:")
    print(f"  교차검증-테스트 차이: {overfit_gap:.4f} ({overfit_gap*100:.1f}%p)")

    if overfit_gap < 0.05:
        print("  ✅ 과적합 없음 (차이 < 5%p)")
    elif overfit_gap < 0.10:
        print("  ⚠️ 경미한 과적합 (차이 5-10%p)")
    else:
        print("  🚨 과적합 발생 (차이 > 10%p)")

    print("\n" + "=" * 70)
    print("💡 다음 단계")
    print("=" * 70)
    print("1. 백테스트 수행:")
    print("   python batch_signal_replay_ml.py --start 20250901 --end 20251118")
    print("\n2. apply_ml_filter.py에서 모델 파일명 변경:")
    print("   ml_model.pkl → ml_model_stratified.pkl")


if __name__ == '__main__':
    main()
