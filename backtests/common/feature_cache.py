"""Feature DataFrame → numpy array 캐시 헬퍼.

엔진 메인 루프에서 `features.iloc[bar_idx]` 가 핫패스 (cProfile 측정 60%+).
한 번 변환 후 numpy array 인덱싱으로 ~5x 속도.

Usage:
    arr = get_arrays(features)
    val = arr["col"][bar_idx]      # O(1) numpy 접근

캐시는 features.attrs["_arrays"] 에 저장 — pandas 가 객체 lifetime 동안 보존.
WeakRef/id() 기반 전역 dict 와 달리 GC 후 id 재사용으로 인한 stale cache 문제 없음.
"""
from typing import Dict

import numpy as np
import pandas as pd


_ATTR_KEY = "_feature_cache_arrays"


def get_arrays(features: pd.DataFrame) -> Dict[str, np.ndarray]:
    """features DataFrame 에서 numpy array dict 반환. attrs 캐시 재사용."""
    cache = features.attrs.get(_ATTR_KEY)
    if cache is None or not _matches(cache, features):
        cache = {col: features[col].to_numpy() for col in features.columns}
        features.attrs[_ATTR_KEY] = cache
    return cache


def _matches(cache: Dict[str, np.ndarray], features: pd.DataFrame) -> bool:
    """캐시가 현재 features 와 일치하는지 (컬럼·길이 동일) 확인."""
    if set(cache.keys()) != set(features.columns):
        return False
    if not cache:
        return len(features) == 0
    sample = next(iter(cache.values()))
    return len(sample) == len(features)


def clear_cache(features: pd.DataFrame) -> None:
    """단일 features 캐시 무효화."""
    features.attrs.pop(_ATTR_KEY, None)
