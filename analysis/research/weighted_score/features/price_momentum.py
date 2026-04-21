"""가격·모멘텀 피처 (5개, Step 2).

입력: 한 종목의 연속된 분봉 DataFrame. 최소 컬럼: [trade_date, idx, open, close].
- 일자 경계를 넘으며 이어 붙인다고 가정 (load_minute_range 결과 그대로).

출력: 원본 index 보존, 피처 컬럼만 (raw values, 정규화 전).

피처 정의:
- `pct_from_open`      : (close / 당일시가 - 1) * 100
- `ret_1min`           : (close / close.shift(1) - 1) * 100
- `ret_5min`           : (close / close.shift(5) - 1) * 100
- `ret_15min`          : (close / close.shift(15) - 1) * 100
- `ret_30min`          : (close / close.shift(30) - 1) * 100

주의:
- shift 는 분봉 단위. 일자 경계에서는 전날 마지막 분봉에서 당일 첫 분봉으로의
  "overnight return" 이 섞여 들어온다. 이는 `ret_Nmin` 피처의 의도된 특성이다
  (연속적인 시계열 신호). 별도 갭 피처는 prior_day.py 에서 다룬다.
- `pct_from_open` 은 당일시가를 동일 날짜의 첫 분봉 open 으로 정의한다.
"""
from __future__ import annotations

import pandas as pd


FEATURE_NAMES: list[str] = [
    "pct_from_open",
    "ret_1min",
    "ret_5min",
    "ret_15min",
    "ret_30min",
]


def compute_price_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """분봉 DF → 5개 피처 DF (원시값, %).

    입력 DF 는 `trade_date`, `idx`, `open`, `close` 컬럼을 포함해야 한다.
    정렬은 (trade_date, idx) 오름차순이어야 한다.
    """
    for col in ("trade_date", "idx", "open", "close"):
        if col not in df.columns:
            raise ValueError(f"missing column: {col}")

    close = df["close"].astype(float)

    # 당일시가 = groupby(trade_date).open.first() 를 broadcast
    day_open = df.groupby("trade_date")["open"].transform("first").astype(float)

    out = pd.DataFrame(index=df.index)
    out["pct_from_open"] = (close / day_open - 1.0) * 100.0
    out["ret_1min"] = (close / close.shift(1) - 1.0) * 100.0
    out["ret_5min"] = (close / close.shift(5) - 1.0) * 100.0
    out["ret_15min"] = (close / close.shift(15) - 1.0) * 100.0
    out["ret_30min"] = (close / close.shift(30) - 1.0) * 100.0
    return out
