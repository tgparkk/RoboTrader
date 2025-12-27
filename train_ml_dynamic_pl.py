#!/usr/bin/env python3
"""
동적 손익비 데이터로 ML 모델 학습

입력: ml_dataset_dynamic_pl.csv (test_results 기반)
출력: ml_model_dynamic_pl.pkl (기존 ml_model.pkl과 별도)
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


# 설정
INPUT_FILE = 'ml_dataset_dynamic_pl.csv'
OUTPUT_MODEL = 'ml_model_dynamic_pl.pkl'
OUTPUT_REPORT = 'ml_training_report_dynamic_pl.txt'


def load_and_prepare_data():
    """데이터 로드 및 전처리 (기존 ml_model.pkl과 동일한 방식)"""
    print("=" * 70)
    print("데이터 로드 중...")
    print("=" * 70)

    df = pd.read_csv(INPUT_FILE, encoding='utf-8-sig')
    print(f"데이터 로드 완료: {len(df)}행")

    # 메타데이터 컬럼 제거 (기존 모델과 동일)
    meta_cols = ['stock_code', 'stock_name', 'date', 'buy_time', 'profit_rate']
    # ⭐ target_stop_loss, target_take_profit는 학습에 사용 (메타데이터 아님)
    feature_cols = [col for col in df.columns if col not in meta_cols + ['label']]

    X = df[feature_cols].copy()
    y = df['label'].copy()

    # 범주형 변수 인코딩 (signal_type만)
    le = LabelEncoder()
    if 'signal_type' in X.columns:
        X['signal_type'] = le.fit_transform(X['signal_type'])

    print(f"\n특징(feature) 수: {len(feature_cols)}")
    print(f"라벨 분포: 승리={y.sum()} ({y.mean()*100:.1f}%), 패배={len(y)-y.sum()} ({(1-y.mean())*100:.1f}%)")

    return X, y, feature_cols, le


def train_lightgbm_model(X_train, y_train, X_val, y_val, feature_names):
    """LightGBM 모델 학습"""
    print("\n" + "=" * 70)
    print("LightGBM 모델 학습 시작")
    print("=" * 70)

    # LightGBM 하이퍼파라미터 (동적 손익비 데이터에 최적화)
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
        'seed': 42,
        'is_unbalance': True  # 불균형 데이터 처리
    }

    # 데이터셋 생성
    lgb_train = lgb.Dataset(X_train, y_train, feature_name=feature_names)
    lgb_val = lgb.Dataset(X_val, y_val, reference=lgb_train, feature_name=feature_names)

    # 학습
    print("학습 중...")
    model = lgb.train(
        params,
        lgb_train,
        num_boost_round=500,
        valid_sets=[lgb_train, lgb_val],
        valid_names=['train', 'valid'],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=50)
        ]
    )

    print(f"학습 완료: 최적 반복 횟수 = {model.best_iteration}")

    return model


def evaluate_model(model, X_test, y_test, feature_names):
    """모델 평가"""
    print("\n" + "=" * 70)
    print("모델 평가")
    print("=" * 70)

    # 예측
    y_pred_proba = model.predict(X_test, num_iteration=model.best_iteration)
    y_pred = (y_pred_proba >= 0.5).astype(int)

    # AUC 스코어
    auc = roc_auc_score(y_test, y_pred_proba)
    print(f"\nAUC Score: {auc:.4f}")

    # 혼동 행렬
    cm = confusion_matrix(y_test, y_pred)
    print("\n혼동 행렬:")
    print("              예측 패배  예측 승리")
    print(f"실제 패배        {cm[0,0]:4d}      {cm[0,1]:4d}")
    print(f"실제 승리        {cm[1,0]:4d}      {cm[1,1]:4d}")

    # 분류 리포트
    print("\n분류 리포트:")
    print(classification_report(y_test, y_pred, target_names=['패배', '승리'], digits=4))

    # 임계값별 성능
    print("\n임계값별 성능:")
    print("-" * 70)
    print("임계값 | 정밀도 | 재현율 | 예측승률 | 실제승률 | 거래수")
    print("-" * 70)

    results = []
    for threshold in [0.3, 0.4, 0.5, 0.6, 0.7]:
        y_pred_thresh = (y_pred_proba >= threshold).astype(int)
        predicted_wins = y_pred_thresh == 1

        if predicted_wins.sum() > 0:
            precision = y_test[predicted_wins].mean()
            recall = y_test[predicted_wins].sum() / y_test.sum()
            predicted_win_rate = predicted_wins.mean() * 100
            actual_win_rate = precision * 100
            n_trades = predicted_wins.sum()
        else:
            precision = recall = predicted_win_rate = actual_win_rate = 0
            n_trades = 0

        print(f"  {threshold:.1f}  |  {precision:5.1%} | {recall:5.1%} |   {predicted_win_rate:5.1f}% |   {actual_win_rate:5.1f}% | {n_trades:4d}건")

        results.append({
            'threshold': threshold,
            'precision': precision,
            'recall': recall,
            'n_trades': n_trades,
            'actual_win_rate': actual_win_rate
        })

    # 최적 임계값 추천
    print("\n" + "=" * 70)
    print("임계값 추천")
    print("=" * 70)

    # 승률 60% 이상 달성하는 임계값
    high_precision = [r for r in results if r['actual_win_rate'] >= 60]
    if high_precision:
        best = max(high_precision, key=lambda x: x['n_trades'])
        print(f"\n[추천] 임계값 {best['threshold']:.1f}")
        print(f"  - 예측 승률: {best['actual_win_rate']:.1f}%")
        print(f"  - 거래 건수: {best['n_trades']}건")
        print(f"  - 정밀도: {best['precision']:.1%}")
        print(f"  - 재현율: {best['recall']:.1%}")
    else:
        print("\n승률 60% 이상 달성하는 임계값이 없습니다.")
        print("기본 임계값 0.5 사용 권장")

    # Feature Importance
    print("\n" + "=" * 70)
    print("Feature Importance (상위 15개)")
    print("=" * 70)

    importance = model.feature_importance(importance_type='gain')
    feature_importance = pd.DataFrame({
        'feature': feature_names,
        'importance': importance
    }).sort_values('importance', ascending=False)

    print(feature_importance.head(15).to_string(index=False))

    return auc, results, feature_importance


def save_model(model, feature_names, label_encoder, auc_score):
    """모델 저장 (기존 모델 형식과 동일)"""
    model_data = {
        'model': model,
        'feature_names': feature_names,
        'label_encoder': label_encoder,
        'auc_score': auc_score,
        'threshold_recommended': 0.5,
        'version': f'dynamic_pl_{pd.Timestamp.now().strftime("%Y%m%d")}',
        'trained_at': pd.Timestamp.now().isoformat(),
        'data_source': INPUT_FILE,
        'n_features': len(feature_names)
    }

    with open(OUTPUT_MODEL, 'wb') as f:
        pickle.dump(model_data, f)

    print(f"\n모델 저장 완료: {OUTPUT_MODEL}")


def main():
    print("=" * 70)
    print("동적 손익비 ML 모델 학습")
    print("=" * 70)
    print(f"입력: {INPUT_FILE}")
    print(f"출력: {OUTPUT_MODEL}")
    print("=" * 70)

    # 1. 데이터 로드
    X, y, feature_names, label_encoder = load_and_prepare_data()

    # 2. 데이터 분할 (70% train, 15% val, 15% test)
    print("\n데이터 분할 중...")
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, random_state=42, stratify=y_temp
    )

    print(f"  - 학습 세트: {len(X_train)}건")
    print(f"  - 검증 세트: {len(X_val)}건")
    print(f"  - 테스트 세트: {len(X_test)}건")

    # 3. 모델 학습
    model = train_lightgbm_model(X_train, y_train, X_val, y_val, feature_names)

    # 4. 모델 평가
    auc_score, threshold_results, feature_importance = evaluate_model(
        model, X_test, y_test, feature_names
    )

    # 5. 모델 저장
    save_model(model, feature_names, label_encoder, auc_score)

    # 6. 리포트 저장
    with open(OUTPUT_REPORT, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("동적 손익비 ML 모델 학습 리포트\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"학습 일시: {pd.Timestamp.now()}\n")
        f.write(f"데이터: {INPUT_FILE}\n")
        f.write(f"모델: {OUTPUT_MODEL}\n\n")
        f.write(f"총 데이터: {len(X)}건\n")
        f.write(f"AUC Score: {auc_score:.4f}\n\n")
        f.write("Feature Importance (Top 15):\n")
        f.write(feature_importance.head(15).to_string(index=False))

    print(f"\n리포트 저장 완료: {OUTPUT_REPORT}")

    print("\n" + "=" * 70)
    print("학습 완료!")
    print("=" * 70)
    print(f"\n다음 단계:")
    print(f"1. 모델 파일 확인: {OUTPUT_MODEL}")
    print(f"2. apply_ml_filter.py 수정하여 새 모델 사용")
    print(f"3. 백테스트로 성능 검증")


if __name__ == "__main__":
    main()
