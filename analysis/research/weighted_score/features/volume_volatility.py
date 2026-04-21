"""거래량·변동성 피처 (4개).

- `vol_ratio_5d`        : 분봉 volume / 최근 5거래일 같은 분봉 위치 평균 volume
- `atr_pct_14d`         : 일간 ATR(14) / 당일 close * 100 (daily 값을 분봉에 broadcast)
- `realized_vol_30min`  : 직전 30분 ret_1min 의 표준편차 (%)
- `obv_slope_5d`        : 최근 5일 OBV 회귀 slope (normalized by close*volume)

입력: 한 종목 분봉 DF (연속된 trade_date, idx 정렬). 일간 집계는 내부에서 수행.
출력: 같은 index, 4개 피처 컬럼 (raw values).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.research.weighted_score.data import daily_bars


FEATURE_NAMES: list[str] = [
    "vol_ratio_5d",
    "atr_pct_14d",
    "realized_vol_30min",
    "obv_slope_5d",
]


def _atr(daily: pd.DataFrame, window: int = 14) -> pd.Series:
    """일간 ATR. TR = max(H-L, |H-Cprev|, |L-Cprev|)."""
    high = daily["high"].astype(float)
    low = daily["low"].astype(float)
    close_prev = daily["close"].astype(float).shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # 단순 이동평균 ATR (Wilder 아님 - 의도적으로 안정적인 변동성 지표로 사용)
    return tr.rolling(window=window, min_periods=window).mean()


def _obv(daily: pd.DataFrame) -> pd.Series:
    """OBV = cumulative sum of signed volume."""
    close = daily["close"].astype(float)
    vol = daily["volume"].astype(float)
    diff = close.diff()
    signed = vol.where(diff > 0, -vol.where(diff < 0, 0))
    return signed.fillna(0).cumsum()


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    """직전 window 개 값의 선형회귀 slope (시간 단위 1)."""
    def _slope(y: np.ndarray) -> float:
        if np.isnan(y).any():
            return np.nan
        x = np.arange(len(y), dtype=float)
        x_mean = x.mean()
        y_mean = y.mean()
        denom = ((x - x_mean) ** 2).sum()
        if denom == 0:
            return 0.0
        return float(((x - x_mean) * (y - y_mean)).sum() / denom)

    return series.rolling(window=window, min_periods=window).apply(_slope, raw=True)


def compute_volume_volatility(
    minute_df: pd.DataFrame,
    ret_1min: pd.Series,
) -> pd.DataFrame:
    """입력:
    - minute_df: trade_date, idx, time, open, high, low, close, volume 컬럼
    - ret_1min:  minute_df 와 같은 index 의 1분 수익률 (%) — price_momentum 에서 계산됨

    출력: 4피처 raw DF.
    """
    for col in ("trade_date", "idx", "high", "low", "close", "volume"):
        if col not in minute_df.columns:
            raise ValueError(f"missing column: {col}")

    out = pd.DataFrame(index=minute_df.index)

    # --- 1) vol_ratio_5d ---
    # 최근 5거래일 같은 (idx=분봉 위치) 평균 volume 대비 오늘 그 위치의 volume 비율
    # 계산: pivot 을 쓰면 복잡하므로, (trade_date, idx) → volume 매핑 후 shift 기반으로
    # 직전 5일 값의 평균을 구한다.
    vol_series = minute_df["volume"].astype(float)
    # 같은 idx 끼리 묶어 5일 rolling 평균 (자신 제외 = shift(1))
    grouped = vol_series.groupby(minute_df["idx"])
    past5_mean = grouped.transform(lambda s: s.shift(1).rolling(window=5, min_periods=3).mean())
    out["vol_ratio_5d"] = vol_series / past5_mean.replace(0, np.nan)

    # --- 2) atr_pct_14d (daily ATR(14)/close * 100, broadcast) ---
    daily = daily_bars.aggregate_minutes_to_daily(minute_df)
    daily["atr"] = _atr(daily, window=14)
    daily["atr_pct"] = (daily["atr"] / daily["close"].astype(float)) * 100.0
    atr_map = dict(zip(daily["trade_date"], daily["atr_pct"]))
    out["atr_pct_14d"] = minute_df["trade_date"].map(atr_map)

    # --- 3) realized_vol_30min (rolling 30분 std of ret_1min, %) ---
    out["realized_vol_30min"] = ret_1min.rolling(window=30, min_periods=15).std()

    # --- 4) obv_slope_5d (daily OBV 의 최근 5일 기울기, normalized) ---
    daily["obv"] = _obv(daily)
    # 정규화: 최근 N일 평균 (close*volume) 으로 나눔 — 기울기 단위 약분
    avg_dollar = (daily["close"].astype(float) * daily["volume"].astype(float)).rolling(
        window=20, min_periods=5
    ).mean()
    obv_slope_raw = _rolling_slope(daily["obv"], window=5)
    daily["obv_slope_norm"] = obv_slope_raw / avg_dollar.replace(0, np.nan)
    slope_map = dict(zip(daily["trade_date"], daily["obv_slope_norm"]))
    out["obv_slope_5d"] = minute_df["trade_date"].map(slope_map)

    return out
