"""WeightedScoreStrategy: 정규화된 피처의 가중합 점수를 계산하고 진입 판단.

- 피처는 0~1 로 정규화된 값이어야 한다 (features/normalize.py 결과).
- score = Σ weights[f_i] * feat[f_i]
- 진입: score > entry_threshold
- 청산: ExitPolicy 에 위임
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from analysis.research.weighted_score.strategy.exit_rules import ExitPolicy


@dataclass
class WeightedScoreStrategy:
    weights: dict[str, float]           # feature_name → weight
    entry_threshold: float              # score 가 이보다 크면 진입 후보
    exit_policy: ExitPolicy

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("weights must be non-empty")
        # 결정론적 순서 확보
        self._feature_names: list[str] = list(self.weights.keys())
        self._weight_array: np.ndarray = np.array(
            [self.weights[n] for n in self._feature_names], dtype=float
        )

    @property
    def feature_names(self) -> list[str]:
        return list(self._feature_names)

    # ----- 점수 계산 -----

    def score_row(self, feat_row: pd.Series) -> float:
        """한 분봉의 피처 한 행 → score. NaN 가 있으면 NaN 반환."""
        vals = feat_row.reindex(self._feature_names).to_numpy(dtype=float)
        if np.isnan(vals).any():
            return float("nan")
        return float(np.dot(vals, self._weight_array))

    def score_frame(self, feat_df: pd.DataFrame) -> pd.Series:
        """DF 의 각 행에 대해 score 계산 (벡터화).

        feat_df 는 self.feature_names 를 포함해야 함. 결측행은 NaN.
        """
        missing = [n for n in self._feature_names if n not in feat_df.columns]
        if missing:
            raise ValueError(f"missing features in frame: {missing}")
        sub = feat_df[self._feature_names].to_numpy(dtype=float)
        scores = sub @ self._weight_array  # (N,) vector
        # NaN propagate
        nan_mask = np.isnan(sub).any(axis=1)
        scores[nan_mask] = np.nan
        return pd.Series(scores, index=feat_df.index, name="score")

    # ----- 진입 조건 -----

    def is_entry_signal(self, score: float) -> bool:
        return (score == score) and score > self.entry_threshold  # NaN → False
