"""Step 3 통합 스모크 테스트: 6개 카테고리 전체 피처 계산 + parquet 왕복.

실행:
    python -m analysis.research.weighted_score.tests.test_features_all
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import feature_store, pg_loader
from analysis.research.weighted_score.features import (
    price_momentum,
    prior_day,
    relative_market,
    technical,
    temporal,
    volume_volatility,
)
from analysis.research.weighted_score.universe import universe_codes


ALL_FEATURE_NAMES = (
    price_momentum.FEATURE_NAMES
    + volume_volatility.FEATURE_NAMES
    + technical.FEATURE_NAMES
    + relative_market.FEATURE_NAMES
    + temporal.FEATURE_NAMES
    + prior_day.FEATURE_NAMES
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[ok]   {msg}")


def _summarize(df: pd.DataFrame, title: str) -> None:
    print(f"\n[{title}] describe:")
    stats = df.describe().T[["mean", "std", "min", "max"]]
    stats["nan_ratio"] = df.isna().mean()
    print(stats.to_string(float_format="%.4f"))


def main() -> None:
    codes = universe_codes()
    _assert(len(codes) > 0, f"universe 로드 ({len(codes)}종목)")

    code = codes[0]
    print(f"\n대상 종목: {code}")

    df = pg_loader.load_minute_range(code, config.DATA_START, config.DATA_END)
    _assert(not df.empty, f"분봉 로드 rows={len(df):,}")

    # 1) price/momentum (5)
    pm = price_momentum.compute_price_momentum(df)
    _assert(list(pm.columns) == price_momentum.FEATURE_NAMES, "price_momentum 컬럼")
    _summarize(pm, "price_momentum")

    # 2) volume/volatility (4) - ret_1min 입력 필요
    vv = volume_volatility.compute_volume_volatility(df, ret_1min=pm["ret_1min"])
    _assert(list(vv.columns) == volume_volatility.FEATURE_NAMES, "volume_volatility 컬럼")
    _summarize(vv, "volume_volatility")

    # 3) technical (5)
    tc = technical.compute_technical(df)
    _assert(list(tc.columns) == technical.FEATURE_NAMES, "technical 컬럼")
    _summarize(tc, "technical")

    # 4) relative_market (4)
    rm = relative_market.compute_relative_market(df)
    _assert(list(rm.columns) == relative_market.FEATURE_NAMES, "relative_market 컬럼")
    _summarize(rm, "relative_market")

    # 5) temporal (3)
    tm = temporal.compute_temporal(df)
    _assert(list(tm.columns) == temporal.FEATURE_NAMES, "temporal 컬럼")
    _assert(tm["hour_sin"].abs().max() <= 1.0, "hour_sin |x| <= 1")
    _assert(tm["hour_cos"].abs().max() <= 1.0, "hour_cos |x| <= 1")
    _assert(
        (tm["minutes_since_open"] >= 0).all(),
        "minutes_since_open >= 0",
    )
    _summarize(tm, "temporal")

    # 6) prior_day (3)
    pd_ = prior_day.compute_prior_day(df)
    _assert(list(pd_.columns) == prior_day.FEATURE_NAMES, "prior_day 컬럼")
    _summarize(pd_, "prior_day")

    # === 통합 ===
    combined = pd.concat([pm, vv, tc, rm, tm, pd_], axis=1)
    _assert(
        list(combined.columns) == ALL_FEATURE_NAMES,
        f"combined 총 {len(ALL_FEATURE_NAMES)}개 컬럼",
    )
    _assert(len(combined) == len(df), "combined rows == minute rows")

    # NaN 비율이 비상식적으로 크지 않은지 (기술지표는 초기 ~30일 NaN)
    for col in combined.columns:
        nan_rat = combined[col].isna().mean()
        # technical 지표는 첫 수십 일 NaN 이므로 더 후하게
        cap = 0.25 if col in technical.FEATURE_NAMES or col in relative_market.FEATURE_NAMES else 0.10
        if col in ("cum_ret_3d", "gap_pct", "prior_day_range"):
            cap = 0.02  # 전일값은 첫날만 NaN
        if col in volume_volatility.FEATURE_NAMES:
            cap = 0.15
        _assert(nan_rat < cap, f"{col} NaN 비율 {nan_rat:.4f} < {cap}")

    # === parquet 왕복 ===
    feat_df = df[["trade_date", "idx", "datetime"]].copy().reset_index(drop=True)
    combined_reset = combined.reset_index(drop=True)
    for col in combined_reset.columns:
        feat_df[col] = combined_reset[col]
    path = feature_store.save_features(code, feat_df)
    _assert(path.exists(), f"parquet 저장 {path.stat().st_size/1024/1024:.2f} MB")

    loaded = feature_store.load_features(code)
    _assert(loaded is not None and len(loaded) == len(feat_df), "parquet 로드 길이")

    # 값 일치 (모든 피처 컬럼)
    for col in ALL_FEATURE_NAMES:
        a = feat_df[col].astype(float)
        b = loaded[col].astype(float)
        eq = np.allclose(a.fillna(-1e18), b.fillna(-1e18), equal_nan=True)
        _assert(eq, f"값 일치: {col}")

    print(f"\n[SUCCESS] Step 3 통합 피처 ({len(ALL_FEATURE_NAMES)}개) 스모크 통과")


if __name__ == "__main__":
    main()
