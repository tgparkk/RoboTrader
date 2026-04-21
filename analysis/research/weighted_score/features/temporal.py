"""시간 피처 (3개).

minute_df 의 `time` 컬럼은 "HHMMSS" 문자열. 한국 장 시간 9:00~15:30 을 가정.

- `hour_sin`          : sin(2π * hour / 24)
- `hour_cos`          : cos(2π * hour / 24)
- `minutes_since_open`: 장 시작(09:00) 이후 경과 분

모두 look-ahead 위험 없는 결정적 값 (정규화 불필요 또는 sigmoid/스케일만).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


FEATURE_NAMES: list[str] = [
    "hour_sin",
    "hour_cos",
    "minutes_since_open",
]

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 0
# 장 연장·동시호가 포함 안전 상한 (분봉 idx 개수 한계치)
MAX_MINUTES = 8 * 60


def _parse_hm(time_col: pd.Series) -> tuple[pd.Series, pd.Series]:
    """time 문자열 "HHMMSS" → (hour, minute) int Series.

    None/NaN 는 NaN 으로 유지.
    """
    s = time_col.astype(str).str.zfill(6)
    hour = pd.to_numeric(s.str[0:2], errors="coerce")
    minute = pd.to_numeric(s.str[2:4], errors="coerce")
    return hour, minute


def compute_temporal(minute_df: pd.DataFrame) -> pd.DataFrame:
    if "time" not in minute_df.columns:
        raise ValueError("missing column: time")

    hour, minute = _parse_hm(minute_df["time"])

    out = pd.DataFrame(index=minute_df.index)
    # day-of-hour cyclical encoding
    angle = 2.0 * np.pi * (hour + minute / 60.0) / 24.0
    out["hour_sin"] = np.sin(angle)
    out["hour_cos"] = np.cos(angle)

    # minutes since market open (음수면 pre-open, 0 이상만 의미)
    mso = (hour - MARKET_OPEN_HOUR) * 60 + (minute - MARKET_OPEN_MIN)
    out["minutes_since_open"] = mso.clip(lower=0, upper=MAX_MINUTES).astype(float)

    return out
