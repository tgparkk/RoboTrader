"""Phase A 스모크: 라벨링 + L1 로지스틱 회귀.

실행:
    python -m analysis.research.weighted_score.tests.test_phase_a_smoke

절차:
1. 5종목 분봉 로드
2. 24개 피처 계산 + 정규화 (0~1)
3. triple-barrier 라벨 (horizon=60, tp=1.5%, sl=-1.5%)
4. 종목별 라벨/피처 병합 → 시간순 pool
5. L1 로지스틱 회귀 (C 그리드 + TimeSeriesSplit CV)
6. 살아남은 피처 + CV AUC 출력
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import pg_loader
from analysis.research.weighted_score.features import (
    normalize,
    price_momentum,
    prior_day,
    relative_market,
    technical,
    temporal,
    volume_volatility,
)
from analysis.research.weighted_score.phase_a import labeling, train_logreg
from analysis.research.weighted_score.universe import universe_codes


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[ok]   {msg}")


def _normalize_all(
    minute_df: pd.DataFrame,
    raw_feat: pd.DataFrame,
    rolling_window: int = 500,
    min_periods: int = 50,
) -> pd.DataFrame:
    """24개 원시 피처를 적절한 방식으로 0~1 정규화.

    - rolling_percentile: price_momentum, volume_volatility (분봉 변동값)
    - scale_to_unit_interval: rsi, stoch, adx (0~100 bounded), minutes_since_open
    - sigmoid 매핑: macd_hist, bb_percent_b 는 zscore_clip
    - 상대강도/prior_day: zscore_clip
    - temporal sin/cos: (x+1)/2 선형
    """
    out = pd.DataFrame(index=raw_feat.index)

    # price_momentum 5개 → rolling_percentile
    for name in price_momentum.FEATURE_NAMES:
        out[name] = normalize.rolling_percentile(raw_feat[name], rolling_window, min_periods)

    # volume_volatility 4개 → rolling_percentile
    for name in volume_volatility.FEATURE_NAMES:
        out[name] = normalize.rolling_percentile(raw_feat[name], rolling_window, min_periods)

    # technical
    out["rsi_14"] = normalize.scale_to_unit_interval(raw_feat["rsi_14"], 0, 100)
    out["macd_hist"] = normalize.zscore_clip_normalize(raw_feat["macd_hist"], rolling_window, min_periods)
    out["bb_percent_b"] = raw_feat["bb_percent_b"].clip(lower=-0.5, upper=1.5).add(0.5).div(2.0)
    out["stoch_k_14"] = normalize.scale_to_unit_interval(raw_feat["stoch_k_14"], 0, 100)
    out["adx_14"] = normalize.scale_to_unit_interval(raw_feat["adx_14"], 0, 100)

    # relative_market 4개 → zscore_clip
    for name in relative_market.FEATURE_NAMES:
        out[name] = normalize.zscore_clip_normalize(raw_feat[name], rolling_window, min_periods)

    # temporal
    out["hour_sin"] = (raw_feat["hour_sin"] + 1.0) / 2.0
    out["hour_cos"] = (raw_feat["hour_cos"] + 1.0) / 2.0
    out["minutes_since_open"] = normalize.scale_to_unit_interval(
        raw_feat["minutes_since_open"], 0, 390
    )

    # prior_day 3개 → zscore_clip
    for name in prior_day.FEATURE_NAMES:
        out[name] = normalize.zscore_clip_normalize(raw_feat[name], rolling_window, min_periods)

    return out


def _compute_raw_features(minute_df: pd.DataFrame) -> pd.DataFrame:
    pm = price_momentum.compute_price_momentum(minute_df)
    vv = volume_volatility.compute_volume_volatility(minute_df, ret_1min=pm["ret_1min"])
    tc = technical.compute_technical(minute_df)
    rm = relative_market.compute_relative_market(minute_df)
    tm = temporal.compute_temporal(minute_df)
    pd_ = prior_day.compute_prior_day(minute_df)
    return pd.concat([pm, vv, tc, rm, tm, pd_], axis=1)


def main() -> None:
    codes = universe_codes()[:5]
    print(f"대상 종목: {codes}")

    combined_parts: list[pd.DataFrame] = []
    t0 = time.time()

    for code in codes:
        df = pg_loader.load_minute_range(code, config.DATA_START, config.DATA_END)
        _assert(not df.empty, f"{code} 분봉 로드 rows={len(df):,}")

        raw = _compute_raw_features(df)
        norm = _normalize_all(df, raw)

        # 라벨
        labels = labeling.triple_barrier_labels(
            df, labeling.LabelingConfig(horizon_bars=60, tp_pct=1.5, sl_pct=-1.5)
        )

        # 학습 프레임 구성
        train_df = train_logreg.prepare_training_frame(
            feat_df=df[["trade_date", "idx"]].join(norm),
            label_series=labels,
            stock_code=code,
        )
        combined_parts.append(train_df)
        pos_rate = (train_df["label"] == 1).mean() if not train_df.empty else float("nan")
        print(
            f"  {code}: raw rows={len(df):,}  labeled={len(train_df):,}  "
            f"pos_rate={pos_rate:.4f}"
        )

    combined = pd.concat(combined_parts, axis=0).reset_index(drop=True)
    _assert(not combined.empty, f"pooled training frame rows={len(combined):,}")

    print(f"\n로드·라벨 elapsed: {time.time() - t0:.1f}s")
    print(f"풀 pos_rate: {(combined['label'] == 1).mean():.4f}")
    print(f"풀 샘플수: {len(combined):,}")

    # 피처명 추출 (trade_date, idx, stock_code, label 제외)
    feature_names = [
        c for c in combined.columns
        if c not in ("trade_date", "idx", "stock_code", "label")
    ]
    _assert(len(feature_names) == 24, f"피처 24개 (actual={len(feature_names)})")

    # 학습 (종목당 최대 5k 샘플)
    t1 = time.time()
    result = train_logreg.fit_l1_logreg(
        combined,
        feature_names=feature_names,
        C_grid=(0.01, 0.1, 1.0, 10.0),
        cv_splits=5,
        max_samples_per_stock=5_000,
        max_total_samples=25_000,
    )
    print(f"\n학습 elapsed: {time.time() - t1:.1f}s")

    # 결과 출력
    print(f"\n=== LogReg 결과 ===")
    print(f"  best_C: {result.best_C}")
    print(f"  n_samples: {result.n_train_samples:,}")
    print(f"  train_auc: {result.train_auc:.4f}")
    print(f"  cv_auc: {result.cv_auc_mean:.4f} ± {result.cv_auc_std:.4f}")
    print(f"  intercept: {result.intercept:+.4f}")
    print(f"  surviving features: {len(result.surviving_features)} / {len(feature_names)}")

    print(f"\n=== 모든 피처 coef (크기순) ===")
    ranked = sorted(result.weights.items(), key=lambda x: -abs(x[1]))
    for name, w in ranked:
        marker = "*" if name in result.surviving_features else " "
        print(f"  {marker} {name:<22}  {w:+.5f}")

    print(f"\n=== C-grid CV 점수 ===")
    for C, (mean, std) in sorted(result.all_cv_scores.items()):
        print(f"  C={C:>8.4f}: AUC {mean:.4f} ± {std:.4f}")

    _assert(result.cv_auc_mean > 0.45, f"CV AUC > 0.45 (baseline 0.5 근처 OK, actual={result.cv_auc_mean:.4f})")
    _assert(len(result.surviving_features) > 0, "살아남은 피처 > 0")

    print(f"\n[SUCCESS] Phase A 스모크 통과")


if __name__ == "__main__":
    main()
