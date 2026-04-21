"""Triple-barrier 라벨링.

각 분봉 t 에 대해 향후 `horizon_bars` 내에
- +`tp_pct` 먼저 도달 → 라벨 1 (win)
- -|sl_pct| 먼저 도달 → 라벨 0 (loss)
- 둘 다 미도달 → NaN (drop)
- 동일 바에서 둘 다 터치 → 0 (보수적: SL 우선)

옵션:
- respect_day_boundary=True: 날짜 경계를 넘지 않음 (기본값, 장 마감 시 윈도우 종료)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LabelingConfig:
    horizon_bars: int = 60
    tp_pct: float = 1.5
    sl_pct: float = -1.5
    respect_day_boundary: bool = True


def triple_barrier_labels(
    df: pd.DataFrame,
    config: LabelingConfig = LabelingConfig(),
) -> pd.Series:
    """한 종목의 연속 분봉 DF → 라벨 Series (0/1/NaN).

    입력 컬럼: trade_date, close, high, low (정렬되어 있어야 함).
    인덱스는 df 의 인덱스를 보존.
    """
    for col in ("trade_date", "close", "high", "low"):
        if col not in df.columns:
            raise ValueError(f"missing column: {col}")
    if config.tp_pct <= 0 or config.sl_pct >= 0:
        raise ValueError("tp_pct must be > 0 and sl_pct must be < 0")

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    trade_dates = df["trade_date"].to_numpy()
    n = len(df)

    # 각 위치에서 "같은 날짜 마지막 인덱스" 를 미리 계산 (day boundary 처리)
    if config.respect_day_boundary:
        # 각 인덱스가 속한 day 의 마지막 row index
        day_change = np.r_[False, trade_dates[1:] != trade_dates[:-1]]
        day_group = day_change.cumsum()
        # groupby → last index
        day_last = pd.Series(np.arange(n)).groupby(day_group).transform("max").to_numpy()
    else:
        day_last = np.full(n, n - 1, dtype=int)

    labels = np.full(n, np.nan, dtype=float)
    tp_mult = 1.0 + config.tp_pct / 100.0
    sl_mult = 1.0 + config.sl_pct / 100.0

    for t in range(n - 1):
        entry = close[t]
        tp_trigger = entry * tp_mult
        sl_trigger = entry * sl_mult

        end_bar_limit = min(t + config.horizon_bars, day_last[t])
        if end_bar_limit <= t:
            continue

        # window: t+1 ~ end_bar_limit (inclusive)
        h_window = high[t + 1 : end_bar_limit + 1]
        l_window = low[t + 1 : end_bar_limit + 1]

        tp_mask = h_window >= tp_trigger
        sl_mask = l_window <= sl_trigger

        tp_first = np.argmax(tp_mask) if tp_mask.any() else -1
        sl_first = np.argmax(sl_mask) if sl_mask.any() else -1

        if tp_first == -1 and sl_first == -1:
            continue  # NaN (drop)
        if tp_first == -1:
            labels[t] = 0.0
        elif sl_first == -1:
            labels[t] = 1.0
        else:
            if sl_first <= tp_first:
                # 동률일 때도 보수적으로 SL 먼저
                labels[t] = 0.0
            else:
                labels[t] = 1.0

    return pd.Series(labels, index=df.index, name="label")
