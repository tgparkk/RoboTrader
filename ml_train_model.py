#!/usr/bin/env python3
"""
ML 모델 학습 및 검증

데이터: ml_dataset.csv
모델: LightGBM (XGBoost의 빠른 대안)
목표: 패턴 신호의 승/패 예측
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
matplotlib.use('Agg')  # GUI 없는 환경에서도 작동
import matplotlib.pyplot as plt
import pickle

sys.stdout.reconfigure(encoding='utf-8')


def load_and_prepare_data(csv_file: str = 'ml_dataset.csv'):
    """데이터 로드 및 전처리"""
    print("=" * 70)
    print("📂 데이터 로드 중...")
    print("=" * 70)

    df = pd.read_csv(csv_file, encoding='utf-8-sig')
    print(f"데이터 로드 완료: {len(df)}행")

    # 메타데이터 컬럼 제거
    meta_cols = ['stock_code', 'pattern_id', 'timestamp', 'sell_reason', 'profit_rate']
    feature_cols = [col for col in df.columns if col not in meta_cols + ['label']]

    X = df[feature_cols].copy()
    y = df['label'].copy()

    # 범주형 변수 인코딩 (signal_type)
    le = LabelEncoder()
    if 'signal_type' in X.columns:
        X['signal_type'] = le.fit_transform(X['signal_type'])

    print(f"\n특징(feature) 수: {len(feature_cols)}")
    print(f"라벨 분포: 승리={y.sum()} ({y.mean()*100:.1f}%), 패배={len(y)-y.sum()} ({(1-y.mean())*100:.1f}%)")

    return X, y, feature_cols, le


def train_lightgbm_model(X_train, y_train, X_val, y_val, feature_names):
    """LightGBM 모델 학습"""
    print("\n" + "=" * 70)
    print("🚀 LightGBM 모델 학습 시작")
    print("=" * 70)

    # LightGBM 하이퍼파라미터 (과적합 방지)
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,  # 트리 복잡도 (작을수록 단순)
        'learning_rate': 0.05,
        'feature_fraction': 0.8,  # 각 트리에서 사용할 특징 비율
        'bagging_fraction': 0.8,  # 각 트리에서 사용할 데이터 비율
        'bagging_freq': 5,
        'min_data_in_leaf': 20,  # 리프 노드의 최소 샘플 수 (과적합 방지)
        'max_depth': 6,  # 트리 최대 깊이 (과적합 방지)
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
        num_boost_round=500,  # 최대 반복 횟수
        valid_sets=[lgb_train, lgb_val],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),  # 50회 개선 없으면 조기 종료
            lgb.log_evaluation(period=50)
        ]
    )

    print(f"✅ 학습 완료: 최적 반복 횟수 = {model.best_iteration}")

    return model


def evaluate_model(model, X_test, y_test, feature_names):
    """모델 평가"""
    print("\n" + "=" * 70)
    print("📊 모델 평가")
    print("=" * 70)

    # 예측
    y_pred_proba = model.predict(X_test, num_iteration=model.best_iteration)
    y_pred = (y_pred_proba >= 0.5).astype(int)

    # AUC 스코어
    auc = roc_auc_score(y_test, y_pred_proba)
    print(f"\n🎯 AUC Score: {auc:.4f}")

    # 혼동 행렬
    cm = confusion_matrix(y_test, y_pred)
    print("\n혼동 행렬:")
    print("              예측 패배  예측 승리")
    print(f"실제 패배        {cm[0,0]:4d}      {cm[0,1]:4d}")
    print(f"실제 승리        {cm[1,0]:4d}      {cm[1,1]:4d}")

    # 분류 리포트
    print("\n분류 리포트:")
    print(classification_report(y_test, y_pred, target_names=['패배', '승리'], digits=4))

    # 다양한 임계값에서의 성능
    print("\n🎚️ 임계값별 성능:")
    print("-" * 60)
    print("임계값 | 정밀도 | 재현율 | 승률예측 | 실제승률 | 거래수")
    print("-" * 60)

    for threshold in [0.3, 0.4, 0.5, 0.6, 0.7]:
        y_pred_thresh = (y_pred_proba >= threshold).astype(int)

        # 승리로 예측한 샘플들
        predicted_wins = y_pred_thresh == 1

        if predicted_wins.sum() > 0:
            precision = y_test[predicted_wins].mean()  # 예측한 것 중 실제 승리 비율
            recall = y_test[predicted_wins].sum() / y_test.sum()  # 전체 승리 중 잡아낸 비율
            predicted_win_rate = predicted_wins.mean() * 100
            actual_win_rate = precision * 100
            n_trades = predicted_wins.sum()
        else:
            precision = 0
            recall = 0
            predicted_win_rate = 0
            actual_win_rate = 0
            n_trades = 0

        print(f" {threshold:.1f}    | {precision:6.1%} | {recall:6.1%} | "
              f"{predicted_win_rate:7.1f}% | {actual_win_rate:7.1f}% | {n_trades:5d}건")

    return y_pred_proba, auc


def plot_feature_importance(model, feature_names, top_n=20):
    """특징 중요도 시각화"""
    print("\n" + "=" * 70)
    print("🔍 특징 중요도 분석")
    print("=" * 70)

    importance = model.feature_importance(importance_type='gain')
    feature_importance_df = pd.DataFrame({
        'feature': feature_names,
        'importance': importance
    }).sort_values('importance', ascending=False)

    print(f"\n상위 {top_n}개 중요 특징:")
    for i, row in feature_importance_df.head(top_n).iterrows():
        print(f"  {row['feature']:35s}: {row['importance']:8.0f}")

    # 그래프 저장
    plt.figure(figsize=(10, 8))
    top_features = feature_importance_df.head(top_n)
    plt.barh(range(len(top_features)), top_features['importance'])
    plt.yticks(range(len(top_features)), top_features['feature'])
    plt.xlabel('Importance (Gain)')
    plt.title(f'Top {top_n} Feature Importance')
    plt.tight_layout()
    plt.savefig('ml_feature_importance.png', dpi=150)
    print("\n✅ 특징 중요도 그래프 저장: ml_feature_importance.png")

    return feature_importance_df


def plot_roc_curve(y_test, y_pred_proba):
    """ROC 곡선 시각화"""
    fpr, tpr, thresholds = roc_curve(y_test, y_pred_proba)
    auc = roc_auc_score(y_test, y_pred_proba)

    plt.figure(figsize=(8, 6))
    plt.plot(fpr, tpr, label=f'LightGBM (AUC = {auc:.4f})')
    plt.plot([0, 1], [0, 1], 'k--', label='Random')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('ROC Curve')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('ml_roc_curve.png', dpi=150)
    print("✅ ROC 곡선 저장: ml_roc_curve.png")


def save_model(model, feature_names, label_encoder, filename='ml_model.pkl'):
    """모델 저장"""
    model_data = {
        'model': model,
        'feature_names': feature_names,
        'label_encoder': label_encoder
    }

    with open(filename, 'wb') as f:
        pickle.dump(model_data, f)

    print(f"\n✅ 모델 저장 완료: {filename}")
    print(f"   파일 크기: {Path(filename).stat().st_size / 1024:.1f} KB")


def cross_validate_model(X, y, feature_names, n_splits=5):
    """교차 검증으로 모델 안정성 평가"""
    print("\n" + "=" * 70)
    print(f"🔄 {n_splits}-Fold 교차 검증")
    print("=" * 70)

    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 20,
        'max_depth': 6,
        'verbose': -1,
        'seed': 42
    }

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    cv_scores = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y), 1):
        X_train_cv, X_val_cv = X.iloc[train_idx], X.iloc[val_idx]
        y_train_cv, y_val_cv = y.iloc[train_idx], y.iloc[val_idx]

        lgb_train = lgb.Dataset(X_train_cv, y_train_cv, feature_name=feature_names)
        lgb_val = lgb.Dataset(X_val_cv, y_val_cv, reference=lgb_train, feature_name=feature_names)

        model_cv = lgb.train(
            params,
            lgb_train,
            num_boost_round=500,
            valid_sets=[lgb_val],
            valid_names=['valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=50, verbose=False),
                lgb.log_evaluation(period=0)  # 로그 비활성화
            ]
        )

        y_pred_proba = model_cv.predict(X_val_cv, num_iteration=model_cv.best_iteration)
        auc_score = roc_auc_score(y_val_cv, y_pred_proba)
        cv_scores.append(auc_score)

        print(f"Fold {fold}: AUC = {auc_score:.4f}")

    print(f"\n평균 AUC: {np.mean(cv_scores):.4f} (± {np.std(cv_scores):.4f})")
    print(f"최소 AUC: {np.min(cv_scores):.4f}")
    print(f"최대 AUC: {np.max(cv_scores):.4f}")

    return cv_scores


def main():
    print("\n" + "=" * 70)
    print("🤖 트레이딩 패턴 ML 모델 학습")
    print("=" * 70)

    # 1. 데이터 로드
    X, y, feature_names, label_encoder = load_and_prepare_data()

    # 2. 시간 기반 분할 (처음 60%로 학습, 나중 40%로 검증/테스트)
    # (랜덤 분할은 미래 데이터 누수 위험)
    train_split = int(len(X) * 0.6)
    val_split = int(len(X) * 0.8)

    X_train = X.iloc[:train_split]
    X_val = X.iloc[train_split:val_split]
    X_test = X.iloc[val_split:]

    y_train = y.iloc[:train_split]
    y_val = y.iloc[train_split:val_split]
    y_test = y.iloc[val_split:]

    print(f"\n데이터 분할:")
    print(f"  학습 세트: {len(X_train):4d}개 (승률 {y_train.mean()*100:.1f}%)")
    print(f"  검증 세트: {len(X_val):4d}개 (승률 {y_val.mean()*100:.1f}%)")
    print(f"  테스트 세트: {len(X_test):4d}개 (승률 {y_test.mean()*100:.1f}%)")

    # 3. 교차 검증 (학습 세트만 사용)
    cv_scores = cross_validate_model(X_train, y_train, feature_names, n_splits=5)

    # 4. 모델 학습
    model = train_lightgbm_model(X_train, y_train, X_val, y_val, feature_names)

    # 5. 평가
    y_pred_proba, auc = evaluate_model(model, X_test, y_test, feature_names)

    # 6. 특징 중요도 분석
    feature_importance_df = plot_feature_importance(model, feature_names, top_n=20)

    # 7. ROC 곡선
    plot_roc_curve(y_test, y_pred_proba)

    # 8. 모델 저장
    save_model(model, feature_names, label_encoder, filename='ml_model.pkl')

    print("\n" + "=" * 70)
    print("✅ 모델 학습 및 평가 완료!")
    print("=" * 70)
    print("\n생성된 파일:")
    print("  - ml_model.pkl (학습된 모델)")
    print("  - ml_feature_importance.png (특징 중요도)")
    print("  - ml_roc_curve.png (ROC 곡선)")

    # 최종 권장사항
    print("\n" + "=" * 70)
    print("💡 사용 권장사항")
    print("=" * 70)
    print(f"1. 모델 AUC: {auc:.4f}")

    if auc >= 0.60:
        print("   → 모델이 유의미한 예측력을 보입니다.")
        print("   → 임계값 0.6 이상 신호만 거래하면 승률 향상 가능")
    elif auc >= 0.55:
        print("   → 모델이 약간의 예측력을 보입니다.")
        print("   → 기존 필터와 병행 사용 권장")
    else:
        print("   → 모델 성능이 낮습니다. 추가 특징 필요")

    print("\n2. 다음 단계:")
    print("   - batch_signal_replay_ml.py 로 실제 백테스트 수행")
    print("   - 임계값 조정하여 최적 승률/거래수 밸런스 찾기")


if __name__ == '__main__':
    try:
        import lightgbm
    except ImportError:
        print("❌ lightgbm이 설치되지 않았습니다.")
        print("다음 명령어로 설치하세요:")
        print("  pip install lightgbm scikit-learn matplotlib")
        sys.exit(1)

    main()
