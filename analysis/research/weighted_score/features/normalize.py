"""피처 값 정규화 유틸.

세 가지 정규화 방식을 지원:
1. `rolling_percentile` — 직전 window 개 값 중 현재 값이 몇 번째 백분위인지. 0~1.
2. `sigmoid` — (x - center) / scale 에 로지스틱 sigmoid 적용. 0~1.
3. `zscore_clip` — 직전 window 값으로 z-score, [-clip, clip] 클리핑 후 0~1 매핑.

세 방식 모두 **shift(1) 강제**: 현재 값은 정규화 분포에 포함되지 않는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_percentile(
    series: pd.Series,
    window: int = 1000,
    min_periods: int = 50,
) -> pd.Series:
    """직전 `window` 개 (shift(1) 후) 값 중 현재 값의 percentile rank.

    반환값: 0~1 float Series. min_periods 미만이면 NaN.

    구현: pandas.rolling.rank(pct=True, method='max') + shift(-1) 트릭 대신
    명시적으로 shift(1) 후 rolling 한 다음 현재 값과 비교한다.
    """
    if series.empty:
        return series.astype(float)

    s = series.astype(float)
    past = s.shift(1)

    # rolling window 내에서 과거 값들의 분포와 현재 값의 비교
    # (과거 값이 N개, 현재 값이 과거 값 중 몇 %를 초과하는지)
    # 벡터화된 구현: rolling.apply 를 사용하면 느리므로 근사.
    #
    # 정확 구현: 각 t 에 대해 (현재값 > past[t-W:t]).mean().
    # 속도를 위해 pandas rolling.rank 활용 — 단, shift(1) 된 past 로부터 확장 후
    # 맨 끝에 현재값을 append 하는 개념. 아래 방식은 Series 전체에 대해
    # `s.rolling(window+1).apply(rank_last, raw=True)` 로 대체.

    def _rank_last(arr: np.ndarray) -> float:
        # arr[-1] = 현재값, arr[:-1] = 과거 window 개
        if len(arr) < 2:
            return np.nan

        past_arr = arr[:-1]
        current = arr[-1]
        valid = past_arr[~np.isnan(past_arr)]
        if len(valid) < min_periods:
            return np.nan
        # (과거값 < 현재값) 비율 — tie 는 0.5 로 카운트
        lt = (valid < current).sum()
        eq = (valid == current).sum()
        return (lt + 0.5 * eq) / len(valid)

    result = s.rolling(window=window + 1, min_periods=min_periods + 1).apply(
        _rank_last, raw=True
    )
    return result


def sigmoid_normalize(
    series: pd.Series,
    center: float = 0.0,
    scale: float = 1.0,
) -> pd.Series:
    """(x - center) / scale 에 표준 sigmoid 적용 → 0~1.

    shift 불필요: 값 자체의 변환이라 look-ahead 위험 없음.
    단, center/scale 가 고정 상수여야 안전. 데이터 기반 center/scale 은 금지.
    """
    z = (series.astype(float) - center) / scale
    # overflow 방지
    z = z.clip(lower=-50, upper=50)
    return 1.0 / (1.0 + np.exp(-z))


def zscore_clip_normalize(
    series: pd.Series,
    window: int = 1000,
    min_periods: int = 50,
    clip: float = 3.0,
) -> pd.Series:
    """직전 window 개 값 (shift(1)) 의 평균/표준편차로 z-score → 클립 → 0~1.

    0~1 매핑: (z + clip) / (2 * clip).
    """
    s = series.astype(float)
    past = s.shift(1)
    mean = past.rolling(window=window, min_periods=min_periods).mean()
    std = past.rolling(window=window, min_periods=min_periods).std()
    # 분모 0 방지
    std = std.where(std > 1e-12, np.nan)
    z = (s - mean) / std
    z_clipped = z.clip(lower=-clip, upper=clip)
    return (z_clipped + clip) / (2 * clip)


def scale_to_unit_interval(
    series: pd.Series,
    lo: float,
    hi: float,
) -> pd.Series:
    """고정 상수 lo~hi 를 0~1 로 선형 매핑 (look-ahead 무관).

    예: RSI(0~100) → scale_to_unit_interval(rsi, 0, 100).
    """
    if hi <= lo:
        raise ValueError(f"hi must be > lo, got lo={lo} hi={hi}")
    s = series.astype(float).clip(lower=lo, upper=hi)
    return (s - lo) / (hi - lo)
