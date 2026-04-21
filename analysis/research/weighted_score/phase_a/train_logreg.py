"""L1 로지스틱 회귀로 피처 가중치 학습.

입력: 정규화된 피처(0~1) + 라벨(0/1/NaN).
출력: 피처별 coef, intercept, 교차검증 AUC, 살아남은 피처(= coef != 0).

구현:
- NaN 라벨 행 드롭
- 옵션 undersampling (per-stock 또는 전체 샘플 수 캡)
- 시간 인식 CV: TimeSeriesSplit (샘플이 trade_date 로 정렬되어야 함)
- C 그리드 탐색 → 평균 CV AUC 최고값 선정
- 해당 C 로 전체 train 재적합 → 최종 weights
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from analysis.research.weighted_score import config


@dataclass
class LogRegResult:
    best_C: float
    weights: dict[str, float]      # 전체 피처의 coef (0 포함)
    intercept: float
    cv_auc_mean: float
    cv_auc_std: float
    train_auc: float
    n_train_samples: int
    surviving_features: list[str]  # coef != 0 피처
    all_cv_scores: dict[float, tuple[float, float]]  # C → (mean, std)


def _undersample_per_stock(
    df: pd.DataFrame,
    stock_col: str,
    max_per_stock: int,
    seed: int,
) -> pd.DataFrame:
    """종목별 샘플 수를 max_per_stock 로 제한. 시간 순 유지 위해 정렬 후 stratify."""
    rng = np.random.default_rng(seed)
    parts = []
    for code, grp in df.groupby(stock_col, sort=False):
        if len(grp) <= max_per_stock:
            parts.append(grp)
        else:
            idx = np.sort(rng.choice(len(grp), size=max_per_stock, replace=False))
            parts.append(grp.iloc[idx])
    return pd.concat(parts, axis=0).sort_index()


def prepare_training_frame(
    feat_df: pd.DataFrame,
    label_series: pd.Series,
    stock_code: Optional[str] = None,
    trade_date_col: str = "trade_date",
) -> pd.DataFrame:
    """한 종목의 피처+라벨 → 학습용 flat DF.

    반환 컬럼: trade_date, idx, stock_code, <feature...>, label.
    NaN 라벨 행은 제거.
    """
    out = feat_df.copy()
    out["label"] = label_series.values
    if stock_code is not None:
        out["stock_code"] = stock_code
    out = out.dropna(subset=["label"])
    return out


def fit_l1_logreg(
    df: pd.DataFrame,
    feature_names: list[str],
    label_col: str = "label",
    date_col: str = "trade_date",
    stock_col: str = "stock_code",
    C_grid: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0),
    cv_splits: int = 5,
    max_samples_per_stock: Optional[int] = None,
    max_total_samples: Optional[int] = None,
    seed: int = config.SEED,
) -> LogRegResult:
    """데이터프레임에 L1 로지스틱 회귀를 학습.

    df 는 trade_date 오름차순으로 정렬되어야 함 (시간 인식 CV 의미).
    feature_names 이외 피처가 있어도 무시.
    """
    if df.empty:
        raise ValueError("empty training frame")
    for col in [label_col, date_col] + feature_names:
        if col not in df.columns:
            raise ValueError(f"missing column: {col}")

    # 정렬 보장
    df = df.sort_values([date_col, "idx"] if "idx" in df.columns else [date_col]).reset_index(drop=True)

    # Undersampling
    if max_samples_per_stock and stock_col in df.columns:
        df = _undersample_per_stock(df, stock_col, max_samples_per_stock, seed).reset_index(drop=True)
    if max_total_samples and len(df) > max_total_samples:
        rng = np.random.default_rng(seed)
        sampled_idx = np.sort(rng.choice(len(df), size=max_total_samples, replace=False))
        df = df.iloc[sampled_idx].reset_index(drop=True)

    # 학습 행렬
    X_full = df[feature_names].to_numpy(dtype=float)
    y_full = df[label_col].to_numpy(dtype=int)
    # NaN feature 행은 제거 (라벨은 이미 non-NaN)
    valid_mask = ~np.isnan(X_full).any(axis=1)
    X_full = X_full[valid_mask]
    y_full = y_full[valid_mask]
    n = len(X_full)
    if n < 200:
        raise ValueError(f"too few samples: {n}")

    # CV (time series split)
    tscv = TimeSeriesSplit(n_splits=cv_splits)
    all_cv_scores: dict[float, tuple[float, float]] = {}
    best_C = None
    best_mean = -np.inf

    for C in C_grid:
        fold_aucs = []
        for train_idx, val_idx in tscv.split(X_full):
            X_tr = X_full[train_idx]
            y_tr = y_full[train_idx]
            X_va = X_full[val_idx]
            y_va = y_full[val_idx]
            if len(np.unique(y_tr)) < 2 or len(np.unique(y_va)) < 2:
                continue
            clf = LogisticRegression(
                penalty="l1",
                solver="saga",
                C=C,
                class_weight="balanced",
                max_iter=2000,
                random_state=seed,
                n_jobs=config.N_JOBS,
            )
            clf.fit(X_tr, y_tr)
            preds = clf.predict_proba(X_va)[:, 1]
            fold_aucs.append(roc_auc_score(y_va, preds))
        if fold_aucs:
            mean = float(np.mean(fold_aucs))
            std = float(np.std(fold_aucs, ddof=1)) if len(fold_aucs) > 1 else 0.0
            all_cv_scores[C] = (mean, std)
            if mean > best_mean:
                best_mean = mean
                best_C = C

    if best_C is None:
        raise RuntimeError("no valid CV fold — check data diversity")

    # 전체 train 으로 재적합
    final = LogisticRegression(
        penalty="l1",
        solver="saga",
        C=best_C,
        class_weight="balanced",
        max_iter=5000,
        random_state=seed,
        n_jobs=config.N_JOBS,
    )
    final.fit(X_full, y_full)
    coefs = final.coef_[0]
    intercept = float(final.intercept_[0])
    weights_dict = {name: float(c) for name, c in zip(feature_names, coefs)}
    surviving = [name for name, c in weights_dict.items() if abs(c) > 1e-9]
    train_preds = final.predict_proba(X_full)[:, 1]
    train_auc = float(roc_auc_score(y_full, train_preds))

    return LogRegResult(
        best_C=best_C,
        weights=weights_dict,
        intercept=intercept,
        cv_auc_mean=best_mean,
        cv_auc_std=all_cv_scores[best_C][1],
        train_auc=train_auc,
        n_train_samples=n,
        surviving_features=surviving,
        all_cv_scores=all_cv_scores,
    )
