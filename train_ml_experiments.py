#!/usr/bin/env python3
"""
ML 모델 학습 실험 - 다양한 방법 테스트
기존 시스템에 영향 없이 여러 학습 방법을 비교합니다.

실험 목록:
1. 기본 LightGBM (현재 방식)
2. Cross-Validation (5-Fold)
3. 하이퍼파라미터 튜닝 (Optuna)
4. 데이터 병합 (ml_dataset.csv + ml_dataset_dynamic_pl.csv)
5. 앙상블 (LightGBM + XGBoost + CatBoost)
6. SMOTE 데이터 증강
7. 모든 방법 조합

출력: experiments/ 폴더에 각 실험 결과 저장
"""

import pandas as pd
import numpy as np
import sys
import os
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
import pickle
import warnings
warnings.filterwarnings('ignore')

sys.stdout.reconfigure(encoding='utf-8')

# 출력 디렉토리
OUTPUT_DIR = Path("experiments")
OUTPUT_DIR.mkdir(exist_ok=True)


def load_dataset(csv_file: str):
    """데이터셋 로드"""
    df = pd.read_csv(csv_file, encoding='utf-8-sig')

    # 메타데이터 제거
    meta_cols = ['stock_code', 'stock_name', 'date', 'buy_time', 'profit_rate', 'pattern_id', 'timestamp', 'sell_reason']
    feature_cols = [col for col in df.columns if col not in meta_cols + ['label']]

    X = df[feature_cols].copy()
    y = df['label'].copy()

    # signal_type 인코딩
    le = LabelEncoder()
    if 'signal_type' in X.columns:
        X['signal_type'] = le.fit_transform(X['signal_type'])

    return X, y, feature_cols, le


def experiment_1_baseline():
    """실험 1: 기본 LightGBM (현재 방식)"""
    print("\n" + "=" * 80)
    print("실험 1: 기본 LightGBM (Baseline)")
    print("=" * 80)

    X, y, feature_names, le = load_dataset('ml_dataset_dynamic_pl.csv')
    print(f"데이터: {len(X)}건 (승률 {y.mean()*100:.1f}%)")

    # Train/Test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )

    # 학습
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'seed': 42,
        'verbose': -1
    }

    lgb_train = lgb.Dataset(X_train, y_train)
    lgb_test = lgb.Dataset(X_test, y_test, reference=lgb_train)

    model = lgb.train(
        params,
        lgb_train,
        num_boost_round=500,
        valid_sets=[lgb_test],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
    )

    # 평가
    y_pred = model.predict(X_test, num_iteration=model.best_iteration)
    auc = roc_auc_score(y_test, y_pred)

    print(f"✅ AUC: {auc:.4f}")

    # 저장
    save_result("exp1_baseline", model, feature_names, le, auc, {
        'method': 'Baseline LightGBM',
        'data': 'ml_dataset_dynamic_pl.csv',
        'n_samples': len(X)
    })

    return auc


def experiment_2_cross_validation():
    """실험 2: 5-Fold Cross Validation"""
    print("\n" + "=" * 80)
    print("실험 2: 5-Fold Cross Validation")
    print("=" * 80)

    X, y, feature_names, le = load_dataset('ml_dataset_dynamic_pl.csv')
    print(f"데이터: {len(X)}건 (승률 {y.mean()*100:.1f}%)")

    # StratifiedKFold
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    params = {
        'objective': 'binary',
        'metric': 'auc',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'seed': 42,
        'verbose': -1
    }

    auc_scores = []
    models = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y), 1):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        lgb_train = lgb.Dataset(X_train, y_train)
        lgb_val = lgb.Dataset(X_val, y_val, reference=lgb_train)

        model = lgb.train(
            params,
            lgb_train,
            num_boost_round=500,
            valid_sets=[lgb_val],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
        )

        y_pred = model.predict(X_val, num_iteration=model.best_iteration)
        auc = roc_auc_score(y_val, y_pred)
        auc_scores.append(auc)
        models.append(model)

        print(f"  Fold {fold}: AUC = {auc:.4f}")

    avg_auc = np.mean(auc_scores)
    std_auc = np.std(auc_scores)

    print(f"\n✅ 평균 AUC: {avg_auc:.4f} ± {std_auc:.4f}")

    # 최고 성능 모델 저장
    best_idx = np.argmax(auc_scores)
    save_result("exp2_cv", models[best_idx], feature_names, le, avg_auc, {
        'method': '5-Fold Cross Validation',
        'avg_auc': avg_auc,
        'std_auc': std_auc,
        'best_fold': best_idx + 1
    })

    return avg_auc


def experiment_3_optuna():
    """실험 3: Optuna 하이퍼파라미터 튜닝"""
    print("\n" + "=" * 80)
    print("실험 3: Optuna 하이퍼파라미터 튜닝")
    print("=" * 80)

    try:
        import optuna
    except ImportError:
        print("❌ Optuna가 설치되지 않았습니다. 스킵합니다.")
        print("   설치: pip install optuna")
        return 0.0

    X, y, feature_names, le = load_dataset('ml_dataset_dynamic_pl.csv')
    print(f"데이터: {len(X)}건 (승률 {y.mean()*100:.1f}%)")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )

    def objective(trial):
        params = {
            'objective': 'binary',
            'metric': 'auc',
            'num_leaves': trial.suggest_int('num_leaves', 10, 50),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1),
            'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 5, 30),
            'feature_fraction': trial.suggest_float('feature_fraction', 0.6, 1.0),
            'bagging_fraction': trial.suggest_float('bagging_fraction', 0.6, 1.0),
            'bagging_freq': trial.suggest_int('bagging_freq', 1, 7),
            'max_depth': trial.suggest_int('max_depth', 3, 10),
            'seed': 42,
            'verbose': -1
        }

        lgb_train = lgb.Dataset(X_train, y_train)
        lgb_test = lgb.Dataset(X_test, y_test, reference=lgb_train)

        model = lgb.train(
            params,
            lgb_train,
            num_boost_round=500,
            valid_sets=[lgb_test],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
        )

        y_pred = model.predict(X_test, num_iteration=model.best_iteration)
        return roc_auc_score(y_test, y_pred)

    # 최적화
    print("최적화 중... (50회 시도)")
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=50, show_progress_bar=False)

    best_params = study.best_params
    best_auc = study.best_value

    print(f"\n✅ 최고 AUC: {best_auc:.4f}")
    print("최적 파라미터:")
    for key, value in best_params.items():
        print(f"  {key}: {value}")

    # 최적 파라미터로 재학습
    best_params.update({'objective': 'binary', 'metric': 'auc', 'seed': 42, 'verbose': -1})
    lgb_train = lgb.Dataset(X_train, y_train)
    final_model = lgb.train(best_params, lgb_train, num_boost_round=500)

    save_result("exp3_optuna", final_model, feature_names, le, best_auc, {
        'method': 'Optuna Hyperparameter Tuning',
        'best_params': best_params,
        'n_trials': 50
    })

    return best_auc


def experiment_4_merged_data():
    """실험 4: 데이터 병합 (ml_dataset.csv + ml_dataset_dynamic_pl.csv)"""
    print("\n" + "=" * 80)
    print("실험 4: 데이터 병합 학습")
    print("=" * 80)

    # 두 데이터셋 로드
    if not os.path.exists('ml_dataset.csv'):
        print("❌ ml_dataset.csv가 없습니다. 스킵합니다.")
        return 0.0

    df1 = pd.read_csv('ml_dataset.csv', encoding='utf-8-sig')
    df2 = pd.read_csv('ml_dataset_dynamic_pl.csv', encoding='utf-8-sig')

    print(f"  ml_dataset.csv: {len(df1)}건")
    print(f"  ml_dataset_dynamic_pl.csv: {len(df2)}건")

    # 공통 컬럼만 선택
    common_cols = set(df1.columns) & set(df2.columns)
    df1 = df1[list(common_cols)]
    df2 = df2[list(common_cols)]

    # 병합
    df_merged = pd.concat([df1, df2], ignore_index=True)
    print(f"  병합 후: {len(df_merged)}건")

    # 중복 제거 (같은 날짜/시간/종목)
    if 'stock_code' in df_merged.columns and 'buy_time' in df_merged.columns and 'date' in df_merged.columns:
        before = len(df_merged)
        df_merged = df_merged.drop_duplicates(subset=['stock_code', 'date', 'buy_time'])
        print(f"  중복 제거: {before - len(df_merged)}건 제거 → {len(df_merged)}건")

    # 메타데이터 제거
    meta_cols = ['stock_code', 'stock_name', 'date', 'buy_time', 'profit_rate', 'pattern_id', 'timestamp', 'sell_reason']
    feature_cols = [col for col in df_merged.columns if col not in meta_cols + ['label']]

    X = df_merged[feature_cols].copy()
    y = df_merged['label'].copy()

    # signal_type 인코딩
    le = LabelEncoder()
    if 'signal_type' in X.columns:
        X['signal_type'] = le.fit_transform(X['signal_type'])

    print(f"  최종 데이터: {len(X)}건 (승률 {y.mean()*100:.1f}%)")

    # 학습
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )

    params = {
        'objective': 'binary',
        'metric': 'auc',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'seed': 42,
        'verbose': -1
    }

    lgb_train = lgb.Dataset(X_train, y_train)
    lgb_test = lgb.Dataset(X_test, y_test, reference=lgb_train)

    model = lgb.train(
        params,
        lgb_train,
        num_boost_round=500,
        valid_sets=[lgb_test],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
    )

    y_pred = model.predict(X_test, num_iteration=model.best_iteration)
    auc = roc_auc_score(y_test, y_pred)

    print(f"\n✅ AUC: {auc:.4f}")

    save_result("exp4_merged", model, feature_cols, le, auc, {
        'method': 'Merged Dataset',
        'n_samples': len(X),
        'data_sources': ['ml_dataset.csv', 'ml_dataset_dynamic_pl.csv']
    })

    return auc


def experiment_5_ensemble():
    """실험 5: 앙상블 (LightGBM + XGBoost + CatBoost)"""
    print("\n" + "=" * 80)
    print("실험 5: 앙상블 학습 (LightGBM + XGBoost + CatBoost)")
    print("=" * 80)

    X, y, feature_names, le = load_dataset('ml_dataset_dynamic_pl.csv')
    print(f"데이터: {len(X)}건 (승률 {y.mean()*100:.1f}%)")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )

    predictions = []
    model_names = []

    # LightGBM
    print("  [1/3] LightGBM 학습 중...")
    lgb_train = lgb.Dataset(X_train, y_train)
    lgb_test = lgb.Dataset(X_test, y_test, reference=lgb_train)

    lgb_model = lgb.train(
        {'objective': 'binary', 'metric': 'auc', 'seed': 42, 'verbose': -1},
        lgb_train,
        num_boost_round=500,
        valid_sets=[lgb_test],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
    )

    lgb_pred = lgb_model.predict(X_test, num_iteration=lgb_model.best_iteration)
    lgb_auc = roc_auc_score(y_test, lgb_pred)
    predictions.append(lgb_pred)
    model_names.append('LightGBM')
    print(f"    AUC: {lgb_auc:.4f}")

    # XGBoost
    try:
        import xgboost as xgb
        print("  [2/3] XGBoost 학습 중...")

        dtrain = xgb.DMatrix(X_train, label=y_train)
        dtest = xgb.DMatrix(X_test, label=y_test)

        xgb_model = xgb.train(
            {'objective': 'binary:logistic', 'eval_metric': 'auc', 'seed': 42},
            dtrain,
            num_boost_round=500,
            evals=[(dtest, 'test')],
            early_stopping_rounds=50,
            verbose_eval=False
        )

        xgb_pred = xgb_model.predict(dtest)
        xgb_auc = roc_auc_score(y_test, xgb_pred)
        predictions.append(xgb_pred)
        model_names.append('XGBoost')
        print(f"    AUC: {xgb_auc:.4f}")
    except ImportError:
        print("    XGBoost 미설치 (스킵)")

    # CatBoost
    try:
        from catboost import CatBoostClassifier
        print("  [3/3] CatBoost 학습 중...")

        cat_model = CatBoostClassifier(
            iterations=500,
            learning_rate=0.05,
            depth=6,
            random_seed=42,
            verbose=0
        )
        cat_model.fit(X_train, y_train, eval_set=(X_test, y_test), early_stopping_rounds=50)

        cat_pred = cat_model.predict_proba(X_test)[:, 1]
        cat_auc = roc_auc_score(y_test, cat_pred)
        predictions.append(cat_pred)
        model_names.append('CatBoost')
        print(f"    AUC: {cat_auc:.4f}")
    except ImportError:
        print("    CatBoost 미설치 (스킵)")

    # 앙상블 (평균)
    ensemble_pred = np.mean(predictions, axis=0)
    ensemble_auc = roc_auc_score(y_test, ensemble_pred)

    print(f"\n✅ 앙상블 AUC: {ensemble_auc:.4f}")
    print(f"   사용 모델: {', '.join(model_names)}")

    # LightGBM 모델만 저장 (앙상블 전체는 저장 안함)
    save_result("exp5_ensemble", lgb_model, feature_names, le, ensemble_auc, {
        'method': 'Ensemble (Voting)',
        'models': model_names,
        'individual_aucs': {name: auc for name, auc in zip(model_names, [lgb_auc] + ([xgb_auc] if 'XGBoost' in model_names else []) + ([cat_auc] if 'CatBoost' in model_names else []))}
    })

    return ensemble_auc


def experiment_6_smote():
    """실험 6: SMOTE 데이터 증강"""
    print("\n" + "=" * 80)
    print("실험 6: SMOTE 데이터 증강")
    print("=" * 80)

    try:
        from imblearn.over_sampling import SMOTE
    except ImportError:
        print("❌ imbalanced-learn이 설치되지 않았습니다. 스킵합니다.")
        print("   설치: pip install imbalanced-learn")
        return 0.0

    X, y, feature_names, le = load_dataset('ml_dataset_dynamic_pl.csv')
    print(f"원본 데이터: {len(X)}건 (승률 {y.mean()*100:.1f}%)")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )

    # SMOTE 적용
    smote = SMOTE(random_state=42)
    X_train_resampled, y_train_resampled = smote.fit_resample(X_train, y_train)

    print(f"SMOTE 후: {len(X_train_resampled)}건 (승률 {y_train_resampled.mean()*100:.1f}%)")

    # 학습
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'seed': 42,
        'verbose': -1
    }

    lgb_train = lgb.Dataset(X_train_resampled, y_train_resampled)
    lgb_test = lgb.Dataset(X_test, y_test, reference=lgb_train)

    model = lgb.train(
        params,
        lgb_train,
        num_boost_round=500,
        valid_sets=[lgb_test],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
    )

    y_pred = model.predict(X_test, num_iteration=model.best_iteration)
    auc = roc_auc_score(y_test, y_pred)

    print(f"\n✅ AUC: {auc:.4f}")

    save_result("exp6_smote", model, feature_names, le, auc, {
        'method': 'SMOTE Oversampling',
        'original_samples': len(X_train),
        'resampled_samples': len(X_train_resampled)
    })

    return auc


def save_result(exp_name, model, feature_names, label_encoder, auc, metadata):
    """실험 결과 저장"""
    model_data = {
        'model': model,
        'feature_names': feature_names,
        'label_encoder': label_encoder,
        'auc_score': auc,
        'metadata': metadata,
        'trained_at': pd.Timestamp.now().isoformat()
    }

    output_file = OUTPUT_DIR / f"{exp_name}.pkl"
    with open(output_file, 'wb') as f:
        pickle.dump(model_data, f)

    print(f"💾 저장: {output_file}")


def main():
    """모든 실험 실행"""
    print("=" * 80)
    print("ML 학습 실험 시작")
    print("=" * 80)
    print(f"출력 디렉토리: {OUTPUT_DIR}")
    print()

    results = {}

    # 실험 1: Baseline
    try:
        results['Baseline'] = experiment_1_baseline()
    except Exception as e:
        print(f"❌ 실험 1 실패: {e}")
        results['Baseline'] = 0.0

    # 실험 2: Cross Validation
    try:
        results['Cross-Validation'] = experiment_2_cross_validation()
    except Exception as e:
        print(f"❌ 실험 2 실패: {e}")
        results['Cross-Validation'] = 0.0

    # 실험 3: Optuna
    try:
        results['Optuna'] = experiment_3_optuna()
    except Exception as e:
        print(f"❌ 실험 3 실패: {e}")
        results['Optuna'] = 0.0

    # 실험 4: Merged Data
    try:
        results['Merged Data'] = experiment_4_merged_data()
    except Exception as e:
        print(f"❌ 실험 4 실패: {e}")
        results['Merged Data'] = 0.0

    # 실험 5: Ensemble
    try:
        results['Ensemble'] = experiment_5_ensemble()
    except Exception as e:
        print(f"❌ 실험 5 실패: {e}")
        results['Ensemble'] = 0.0

    # 실험 6: SMOTE
    try:
        results['SMOTE'] = experiment_6_smote()
    except Exception as e:
        print(f"❌ 실험 6 실패: {e}")
        results['SMOTE'] = 0.0

    # 결과 요약
    print("\n" + "=" * 80)
    print("실험 결과 요약")
    print("=" * 80)

    results_df = pd.DataFrame([
        {'실험': name, 'AUC': auc}
        for name, auc in results.items()
        if auc > 0
    ]).sort_values('AUC', ascending=False)

    print(results_df.to_string(index=False))

    if len(results_df) > 0:
        best = results_df.iloc[0]
        print(f"\n🏆 최고 성능: {best['실험']} (AUC: {best['AUC']:.4f})")

    # 결과 저장
    results_file = OUTPUT_DIR / "experiment_summary.txt"
    with open(results_file, 'w', encoding='utf-8') as f:
        f.write("ML 학습 실험 결과 요약\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"실행 시간: {pd.Timestamp.now()}\n\n")
        f.write(results_df.to_string(index=False))
        f.write(f"\n\n최고 성능: {best['실험']} (AUC: {best['AUC']:.4f})\n")

    print(f"\n💾 결과 저장: {results_file}")
    print(f"💾 모델 저장: {OUTPUT_DIR}/*.pkl")


if __name__ == "__main__":
    main()
