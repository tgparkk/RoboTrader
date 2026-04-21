"""피처 파이프라인: 분봉 DF → 0~1 정규화된 24개 피처 DF.

책임:
- 6개 카테고리 피처 모듈 호출 (raw 계산)
- 적절한 정규화 방식 선택 (rolling_percentile / scale / zscore_clip / sin·cos shift)
- 결과 DF 반환 (trade_date, idx, datetime + 24 피처)
"""
from __future__ import annotations

import pandas as pd

from analysis.research.weighted_score.features import (
    normalize,
    price_momentum,
    prior_day,
    relative_market,
    technical,
    temporal,
    volume_volatility,
)


ALL_FEATURE_NAMES: list[str] = (
    price_momentum.FEATURE_NAMES
    + volume_volatility.FEATURE_NAMES
    + technical.FEATURE_NAMES
    + relative_market.FEATURE_NAMES
    + temporal.FEATURE_NAMES
    + prior_day.FEATURE_NAMES
)


def compute_raw_features(minute_df: pd.DataFrame) -> pd.DataFrame:
    """한 종목 분봉 → 24개 원시 피처 DF (정규화 전)."""
    pm = price_momentum.compute_price_momentum(minute_df)
    vv = volume_volatility.compute_volume_volatility(minute_df, ret_1min=pm["ret_1min"])
    tc = technical.compute_technical(minute_df)
    rm = relative_market.compute_relative_market(minute_df)
    tm = temporal.compute_temporal(minute_df)
    pd_ = prior_day.compute_prior_day(minute_df)
    return pd.concat([pm, vv, tc, rm, tm, pd_], axis=1)


def normalize_features(
    raw_feat: pd.DataFrame,
    rolling_window: int = 1000,
    min_periods: int = 50,
) -> pd.DataFrame:
    """원시 피처 → 0~1 정규화."""
    out = pd.DataFrame(index=raw_feat.index)

    # price_momentum 5 — 분봉 단위 변동값 → rolling percentile
    for name in price_momentum.FEATURE_NAMES:
        out[name] = normalize.rolling_percentile(raw_feat[name], rolling_window, min_periods)

    # volume_volatility 4 — 대부분 분봉 단위 변동값 → rolling percentile
    for name in volume_volatility.FEATURE_NAMES:
        out[name] = normalize.rolling_percentile(raw_feat[name], rolling_window, min_periods)

    # technical 5 — 경계 알려진 지표는 선형, 아닌 것은 zscore
    out["rsi_14"] = normalize.scale_to_unit_interval(raw_feat["rsi_14"], 0, 100)
    out["macd_hist"] = normalize.zscore_clip_normalize(raw_feat["macd_hist"], rolling_window, min_periods)
    out["bb_percent_b"] = raw_feat["bb_percent_b"].clip(lower=-0.5, upper=1.5).add(0.5).div(2.0)
    out["stoch_k_14"] = normalize.scale_to_unit_interval(raw_feat["stoch_k_14"], 0, 100)
    out["adx_14"] = normalize.scale_to_unit_interval(raw_feat["adx_14"], 0, 100)

    # relative_market 4 — zscore_clip
    for name in relative_market.FEATURE_NAMES:
        out[name] = normalize.zscore_clip_normalize(raw_feat[name], rolling_window, min_periods)

    # temporal 3 — sin/cos 는 선형 shift, minutes_since_open 은 알려진 경계
    out["hour_sin"] = (raw_feat["hour_sin"] + 1.0) / 2.0
    out["hour_cos"] = (raw_feat["hour_cos"] + 1.0) / 2.0
    out["minutes_since_open"] = normalize.scale_to_unit_interval(raw_feat["minutes_since_open"], 0, 390)

    # prior_day 3 — zscore_clip
    for name in prior_day.FEATURE_NAMES:
        out[name] = normalize.zscore_clip_normalize(raw_feat[name], rolling_window, min_periods)

    # 순서 보존
    return out[ALL_FEATURE_NAMES]


def compute_and_normalize(
    minute_df: pd.DataFrame,
    rolling_window: int = 1000,
    min_periods: int = 50,
) -> pd.DataFrame:
    """분봉 → 정규화된 피처 DF (24개).

    반환: trade_date, idx, datetime + 24 normalized features.
    """
    raw = compute_raw_features(minute_df)
    norm = normalize_features(raw, rolling_window=rolling_window, min_periods=min_periods)
    meta = minute_df[["trade_date", "idx", "datetime", "open", "high", "low", "close", "time"]].copy()
    return pd.concat([meta.reset_index(drop=True), norm.reset_index(drop=True)], axis=1)
