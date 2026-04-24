"""Look-ahead 자동 감사 — 원칙 1 강제.

방법(perturbation): 시점 t 이후의 모든 데이터를 랜덤 값으로 교란한 뒤 피처를
재계산. feature[t] 가 변하면 feature[t] 가 data[t:] 에 의존한다 → look-ahead.

이 방식은 다음 look-ahead 패턴을 모두 감지한다:
- 당일 데이터 직접 사용 (df["close"][t])
- 미래 데이터 참조 (df["close"].shift(-1))
- 전체 집계 broadcast (df["close"].mean())
- shift 없는 rolling window (df["close"].rolling(5).mean())

안전한 패턴:
- shift(1) / prev_*
- rolling(N).shift(1)
"""
from typing import Callable

import numpy as np
import pandas as pd


class LookAheadDetected(Exception):
    """피처 계산에서 미래 또는 현재 바 데이터 참조 감지."""


def audit_no_lookahead(
    prepare_features: Callable[[pd.DataFrame], pd.DataFrame],
    df: pd.DataFrame,
    test_indices: list = None,
    atol: float = 1e-9,
    seed: int = 42,
) -> None:
    """
    prepare_features 가 look-ahead 없이 작성됐는지 검증.

    각 test_index t 에 대해:
      1. full 결과: features = prepare_features(df)
      2. perturbed 결과: df 의 숫자 컬럼에서 t 이상 인덱스의 값을 랜덤 교체, 재계산
      3. features[t] 와 perturbed_features[t] 가 atol 이내 일치하면 OK
         그렇지 않으면 LookAheadDetected.
    """
    n = len(df)
    if n < 4:
        raise ValueError(f"감사에는 최소 4행 필요 (현재 {n})")

    if test_indices is None:
        # 기본: 중간, 3/4 지점
        test_indices = [n // 2, 3 * n // 4]

    full = prepare_features(df.copy())
    if full is None or len(full) == 0:
        raise LookAheadDetected("prepare_features 가 빈 결과를 반환")

    rng = np.random.default_rng(seed)
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    for t in test_indices:
        if t >= n or t < 1:
            continue
        perturbed = df.copy()
        for col in numeric_cols:
            size = n - t
            # 원본 값과 명확히 구분되는 양수 랜덤값 (원 스케일 무관)
            random_vals = rng.uniform(low=1e6, high=1e7, size=size)
            perturbed[col] = perturbed[col].astype(float)
            perturbed.loc[perturbed.index[t]:, col] = random_vals

        perturbed_features = prepare_features(perturbed)

        common_cols = [c for c in full.columns if c in perturbed_features.columns]
        for col in common_cols:
            a = full[col].iloc[t]
            b = perturbed_features[col].iloc[t]
            a_nan, b_nan = pd.isna(a), pd.isna(b)
            if a_nan and b_nan:
                continue
            if a_nan != b_nan:
                raise LookAheadDetected(
                    f"컬럼 '{col}' 시점 t={t}: 교란 후 NaN 상태 변화 "
                    f"(full={a}, perturbed={b}) → data[t:] 의존"
                )
            if abs(float(a) - float(b)) > atol:
                raise LookAheadDetected(
                    f"컬럼 '{col}' 시점 t={t}: 교란 후 값 변화 "
                    f"(full={a}, perturbed={b}) → data[t:] 의존"
                )
