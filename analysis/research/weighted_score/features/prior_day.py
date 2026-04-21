"""이전 데이터 피처 (3개).

- `gap_pct`         : (당일 open - 전일 close) / 전일 close * 100 (broadcast)
- `prior_day_range` : (전일 high - 전일 low) / 전일 close * 100 (broadcast)
- `cum_ret_3d`      : 최근 3일 누적 수익률 (%) — 과거 3일 (shift(1))

NXT sentiment 는 별도 테이블·부분 커버리지 이슈로 Step 3에서 제외 (추후 확장).
"""
from __future__ import annotations

import pandas as pd

from analysis.research.weighted_score.data import daily_bars


FEATURE_NAMES: list[str] = [
    "gap_pct",
    "prior_day_range",
    "cum_ret_3d",
]


def compute_prior_day(minute_df: pd.DataFrame) -> pd.DataFrame:
    for col in ("trade_date", "open", "high", "low", "close"):
        if col not in minute_df.columns:
            raise ValueError(f"missing column: {col}")

    daily = daily_bars.aggregate_minutes_to_daily(minute_df)
    daily["close"] = daily["close"].astype(float)
    daily["open"] = daily["open"].astype(float)
    daily["high"] = daily["high"].astype(float)
    daily["low"] = daily["low"].astype(float)

    prev_close = daily["close"].shift(1)
    prev_high = daily["high"].shift(1)
    prev_low = daily["low"].shift(1)

    daily["gap_pct"] = (daily["open"] - prev_close) / prev_close * 100.0
    daily["prior_day_range"] = (prev_high - prev_low) / prev_close * 100.0
    # 3일 누적 수익률 = close(t-1) / close(t-4) - 1 (오늘 정보 미포함)
    daily["cum_ret_3d"] = (daily["close"].shift(1) / daily["close"].shift(4) - 1.0) * 100.0

    out = pd.DataFrame(index=minute_df.index)
    for name in FEATURE_NAMES:
        m = dict(zip(daily["trade_date"], daily[name]))
        out[name] = minute_df["trade_date"].map(m).astype(float)

    return out
