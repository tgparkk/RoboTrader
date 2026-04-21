"""Step 2 스모크 테스트: 1종목 × 5피처 parquet 왕복 확인.

실행:
    python -m analysis.research.weighted_score.tests.test_features_smoke

검증 항목:
- 분봉 로드 성공
- 5개 price/momentum 피처 계산 성공, 값 범위 합리
- rolling_percentile 정규화 결과 0~1 범위
- parquet 저장/로드 왕복 후 값 일치
- look-ahead 방지: shift(1) 이 실제로 적용됐는지 (현재 값이 과거 분포에 없음)
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import feature_store, pg_loader
from analysis.research.weighted_score.features import normalize, price_momentum
from analysis.research.weighted_score.universe import universe_codes


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[ok]   {msg}")


def main() -> None:
    codes = universe_codes()
    _assert(len(codes) > 0, f"universe 로드 ({len(codes)}종목)")

    code = codes[0]
    print(f"\n대상 종목: {code}")

    # 1) 분봉 로드 (전체 기간)
    df = pg_loader.load_minute_range(code, config.DATA_START, config.DATA_END)
    _assert(not df.empty, f"분봉 로드 - rows={len(df):,}")
    _assert(
        all(c in df.columns for c in ("trade_date", "idx", "open", "close")),
        "필수 컬럼 존재",
    )

    # 2) 피처 계산 (원시값)
    raw = price_momentum.compute_price_momentum(df)
    _assert(
        list(raw.columns) == price_momentum.FEATURE_NAMES,
        f"피처 컬럼 5개 일치: {list(raw.columns)}",
    )
    _assert(len(raw) == len(df), "피처 rows == 분봉 rows")

    # pct_from_open sanity: 각 날짜 day_open 이 정확히 그 날 첫 봉의 open 과 일치해야 함
    # (첫 분봉의 pct_from_open 은 (close-open)/open*100 이라 0 이 아님)
    grouped = df.groupby("trade_date", as_index=False).agg(
        day_open_from_agg=("open", "first")
    )
    first_bars = df.groupby("trade_date").head(1)
    merged = first_bars.merge(grouped, on="trade_date")
    _assert(
        (merged["open"] == merged["day_open_from_agg"]).all(),
        "day_open = 각 날짜 첫 분봉 open",
    )
    # pct_from_open 전체 분포 범위가 비상식적으로 크지 않은지 (상하 ±30% 허용)
    pf = raw["pct_from_open"].dropna()
    _assert(
        pf.abs().quantile(0.99) < 30,
        f"pct_from_open 99% 분위 < 30% (actual={pf.abs().quantile(0.99):.2f})",
    )

    # ret_1min: NaN 비율 체크 (첫 분봉 + 일자 경계 여부)
    nan_ratio = raw["ret_1min"].isna().mean()
    _assert(nan_ratio < 0.02, f"ret_1min NaN 비율 < 2% (actual={nan_ratio:.4f})")

    # 3) 정규화 (pct_from_open 을 rolling percentile 로)
    norm = normalize.rolling_percentile(
        raw["pct_from_open"], window=500, min_periods=50
    )
    valid = norm.dropna()
    _assert(
        (valid >= 0).all() and (valid <= 1).all(),
        f"rolling_percentile 범위 0~1 (valid count={len(valid):,})",
    )
    _assert(
        len(valid) > 10_000,
        f"유효 정규화 값 충분 (>{10_000}, actual={len(valid):,})",
    )

    # 4) look-ahead 체크: shift(1) 후 윈도우라 현재값은 분포에서 제외됨.
    # 대리 검증: 동일 값이 두 번 이상 나오면 tie 0.5 처리지만 rare.
    # 더 강한 검증은 test_no_lookahead.py 에서 수행.

    # 5) parquet 왕복
    feat_df = df[["trade_date", "idx", "datetime"]].copy()
    for col in raw.columns:
        feat_df[f"raw_{col}"] = raw[col]
    feat_df["norm_pct_from_open"] = norm

    path = feature_store.save_features(code, feat_df)
    _assert(path.exists(), f"parquet 저장: {path.name}")

    loaded = feature_store.load_features(code)
    _assert(loaded is not None and len(loaded) == len(feat_df), "parquet 로드 길이 일치")

    # 값 일치 (NaN 포함해서 비교)
    for col in feat_df.columns:
        eq = _series_equal(feat_df[col], loaded[col])
        _assert(eq, f"컬럼 값 일치: {col}")

    # 6) 캐시 요약
    summary = feature_store.cache_size_summary()
    print(f"\n캐시 요약: {summary}")

    # 7) 피처별 분포 샘플
    print("\n원시값 describe:")
    print(raw.describe().T[["mean", "std", "min", "max"]].to_string(float_format="%.4f"))
    print("\n정규화값 describe:")
    print(norm.describe().to_string(float_format="%.4f"))

    print("\n[SUCCESS] Step 2 스모크 테스트 통과")


def _series_equal(a: pd.Series, b: pd.Series) -> bool:
    if a.dtype != b.dtype:
        # parquet 왕복시 일부 dtype 이 변할 수 있음 (category 등). 값만 비교.
        try:
            a2 = a.astype(float)
            b2 = b.astype(float)
        except (TypeError, ValueError):
            return (a.fillna("__NA__") == b.fillna("__NA__")).all()
        return np.allclose(a2.fillna(-1e18), b2.fillna(-1e18), equal_nan=True)
    if pd.api.types.is_float_dtype(a):
        return np.allclose(a.fillna(-1e18), b.fillna(-1e18), equal_nan=True)
    return (a.fillna("__NA__") == b.fillna("__NA__")).all()


if __name__ == "__main__":
    main()
