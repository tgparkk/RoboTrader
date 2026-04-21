"""Trial 1600 파라미터 + 정규화 기준 분포 스냅샷을 JSON 으로 추출.

실행:
    python -m analysis.research.weighted_score.export_params \\
        --study phaseb_20260421_005323 --trial 1600

출력:
    core/strategies/weighted_score_params.json

내용:
- weights (23개, Trial 1600)
- exit_policy (SL/TP/max_hold 등)
- max_positions, entry_pct
- threshold_abs: train score matrix 의 entry_pct 분위값 (절대 임계치)
- normalization:
  - rolling_percentile 피처(9개): 1001 분위수 테이블
  - zscore_clip 피처(8개): mean, std
  - scale_to_unit (3개): 상수 (코드에서 하드코딩, 참고용만 저장)
  - linear (3개): 상수 (참고용만)
- daily_reference_dates: train 기간
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import optuna
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import feature_store, pg_loader
from analysis.research.weighted_score.features import (
    normalize,
    pipeline as feat_pipeline,
    price_momentum,
    prior_day,
    relative_market,
    technical,
    temporal,
    volume_volatility,
)
from analysis.research.weighted_score.sim import fast_engine


# 정규화 카테고리 분류 (pipeline.normalize_features 기준)
ROLLING_PERCENTILE_FEATURES = (
    price_momentum.FEATURE_NAMES + volume_volatility.FEATURE_NAMES
)  # 9개
SCALE_TO_UNIT_FEATURES = {
    "rsi_14": (0.0, 100.0),
    "adx_14": (0.0, 100.0),
    "stoch_k_14": (0.0, 100.0),
    "minutes_since_open": (0.0, 390.0),
}
ZSCORE_CLIP_FEATURES = (
    ["macd_hist"]
    + list(relative_market.FEATURE_NAMES)  # 4개
    + list(prior_day.FEATURE_NAMES)  # 3개
)  # 8개
LINEAR_FEATURES = {
    "hour_sin": ("shift", -1.0, 1.0),     # (x + 1) / 2
    "hour_cos": ("shift", -1.0, 1.0),
    "bb_percent_b": ("clip_shift", -0.5, 1.5),  # clip → +0.5 → /2
}

QUANTILE_COUNT = 1001  # 0%, 0.1%, 0.2%, ..., 100%


# ---------- 유틸 ----------


def _load_trial(study_dir: Path, study_name: str, trial_number: int) -> optuna.trial.FrozenTrial:
    storage = f"sqlite:///{(study_dir / 'study.db').as_posix()}"
    study = optuna.load_study(study_name=study_name, storage=storage)
    for t in study.trials:
        if t.number == trial_number:
            return t
    raise ValueError(f"trial #{trial_number} not found in {study_name}")


def _extract_weights(trial: optuna.trial.FrozenTrial, all_features: list[str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for name in all_features:
        key = f"w_{name}"
        if key in trial.params:
            weights[name] = float(trial.params[key])
        else:
            weights[name] = 0.0  # 생존하지 못한 피처
    return weights


def _load_cached_features(codes: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for code in codes:
        df = feature_store.load_features(code)
        if df is not None and not df.empty:
            out[code] = df
    return out


def _compute_rolling_percentile_quantiles(
    feat_by_code: dict[str, pd.DataFrame],
    train_dates: list[str],
    feature_name: str,
) -> np.ndarray:
    """rolling_percentile 로 정규화되는 피처의 raw 분포에서 1001 분위수 추출.

    주의: normalize.rolling_percentile 은 훈련 시 rolling window=1000 으로 매 분봉마다
    과거 값 대비 랭크를 계산한다. 실거래 시 매 분봉 rolling 재계산을 피하려면
    고정 분포 스냅샷을 사용한다. 분포는 train 전체 기간의 **raw 피처 값** 을 쓴다.

    반환: shape (QUANTILE_COUNT,) float64 정렬된 분위수 배열.
    """
    date_set = set(train_dates)
    all_vals = []
    for code, df in feat_by_code.items():
        if feature_name not in df.columns:
            continue
        sub = df[df["trade_date"].isin(date_set)]
        if sub.empty:
            continue
        # 주의: feature_store 에 저장된 값은 "정규화된" rolling_percentile 이 아니라
        # pipeline.compute_and_normalize 의 출력. 즉 이미 0~1 정규화된 값이다.
        # 우리는 "raw" 분포가 필요하므로 raw 피처를 재계산해야 한다.
        # → 다른 함수에서 raw 재계산 후 전달받도록 설계 변경
        raise NotImplementedError("use _gather_raw_feature_values instead")


def _gather_raw_feature_values(
    feat_by_code_raw: dict[str, pd.DataFrame],
    train_dates: list[str],
    feature_name: str,
) -> np.ndarray:
    """Train 기간에서 raw 피처 값을 모아 1D numpy array 로 반환."""
    date_set = set(train_dates)
    arrs = []
    for code, df in feat_by_code_raw.items():
        if feature_name not in df.columns:
            continue
        sub = df[df["trade_date"].isin(date_set)]
        if sub.empty:
            continue
        vals = sub[feature_name].to_numpy(dtype=np.float64)
        vals = vals[~np.isnan(vals)]
        if len(vals) > 0:
            arrs.append(vals)
    if not arrs:
        return np.array([], dtype=np.float64)
    return np.concatenate(arrs)


def _compute_raw_feature_frames(
    minute_by_code: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """분봉 → raw 피처 DF. 정규화 **전** 값이 필요하므로 pipeline.compute_raw_features 사용."""
    out: dict[str, pd.DataFrame] = {}
    for code, minute_df in minute_by_code.items():
        raw = feat_pipeline.compute_raw_features(minute_df)
        merged = minute_df[["trade_date", "idx"]].reset_index(drop=True)
        merged = pd.concat([merged, raw.reset_index(drop=True)], axis=1)
        out[code] = merged
    return out


# ---------- 메인 ----------


def build_params(
    study_name: str,
    trial_number: int,
    universe_size: int,
    output_path: Path,
) -> dict:
    t0 = time.time()
    study_dir = config.PHASE_B_DIR / study_name
    if not study_dir.exists():
        raise FileNotFoundError(study_dir)

    # 1) Trial 로드
    trial = _load_trial(study_dir, study_name, trial_number)
    print(f"[export] trial #{trial.number} value={trial.value:.4f}")

    # Phase A 정보 로드
    study_cfg = json.loads((study_dir / "config.json").read_text(encoding="utf-8"))
    phase_a_id = study_cfg["phase_a_run_id"]
    surviving = study_cfg["surviving_features"]
    print(f"[export] phase_a={phase_a_id}  surviving={len(surviving)}")

    weights = _extract_weights(trial, surviving)
    entry_pct = float(trial.params["entry_pct"])
    print(f"[export] weights (non-zero): {sum(1 for w in weights.values() if abs(w) > 1e-9)}")

    # 2) Universe + 피처 캐시 로드 (정규화된 값 — score/threshold 계산용)
    from analysis.research.weighted_score.universe import universe_codes
    codes = universe_codes()[:universe_size]
    feat_by_code_norm = _load_cached_features(codes)
    print(f"[export] universe={len(codes)} requested, {len(feat_by_code_norm)} cached")

    # 3) Train/Test split
    train_dates, _ = pg_loader.train_test_split_dates()
    print(f"[export] train={len(train_dates)}d {train_dates[0]}~{train_dates[-1]}")

    # 4) Train context 빌드 → score matrix → threshold_abs
    print("[export] computing score matrix on train ctx...")
    train_ctx = fast_engine.build_context(feat_by_code_norm, train_dates, feature_names=surviving)
    score_mat = fast_engine.compute_score_matrix(train_ctx, weights)
    valid_scores = score_mat[~np.isnan(score_mat)]
    threshold_abs = float(np.percentile(valid_scores, entry_pct))
    print(f"[export] threshold_abs @ percentile {entry_pct} = {threshold_abs:.6f}")
    print(f"[export] score stats: min={valid_scores.min():.3f} max={valid_scores.max():.3f} "
          f"mean={valid_scores.mean():.3f}")

    # 5) Raw 피처 재계산 (정규화 전) - 분포 추출용
    # 주의: 시간 많이 걸림. 대안: 캐시된 정규화 값이 아닌 raw 분봉에서 재계산
    print("[export] loading raw minute data for distribution extraction...")
    minute_by_code: dict[str, pd.DataFrame] = {}
    load_codes = list(feat_by_code_norm.keys())
    for i, code in enumerate(load_codes, 1):
        df = pg_loader.load_minute_range(code, config.DATA_START, config.DATA_END)
        if not df.empty:
            minute_by_code[code] = df
        if i % 50 == 0:
            print(f"  [{i}/{len(load_codes)}] loaded")
    print(f"[export] raw minute data loaded: {len(minute_by_code)} codes")

    print("[export] computing raw feature frames...")
    raw_by_code = _compute_raw_feature_frames(minute_by_code)
    print(f"[export] raw feature frames: {len(raw_by_code)} codes")

    # 6) 정규화 스냅샷 추출
    normalization: dict = {
        "rolling_percentile": {},
        "zscore_clip": {},
        "scale_to_unit": dict(SCALE_TO_UNIT_FEATURES),
        "linear": {k: list(v) for k, v in LINEAR_FEATURES.items()},
        "quantile_count": QUANTILE_COUNT,
        "zscore_clip_value": 3.0,
    }

    # rolling_percentile (9 피처): 1001 분위수 저장
    for name in ROLLING_PERCENTILE_FEATURES:
        vals = _gather_raw_feature_values(raw_by_code, train_dates, name)
        if len(vals) == 0:
            print(f"  [warn] {name}: empty raw values, skip")
            continue
        qs = np.linspace(0.0, 100.0, QUANTILE_COUNT)
        quantiles = np.percentile(vals, qs)
        normalization["rolling_percentile"][name] = {
            "quantiles": quantiles.tolist(),
            "n_samples": int(len(vals)),
        }
        print(f"  rolling_pct: {name:<22}  n={len(vals):,}  "
              f"q[0/50/100]={quantiles[0]:.4f}/{quantiles[500]:.4f}/{quantiles[-1]:.4f}")

    # zscore_clip (8 피처): mean, std 저장
    for name in ZSCORE_CLIP_FEATURES:
        vals = _gather_raw_feature_values(raw_by_code, train_dates, name)
        if len(vals) == 0:
            print(f"  [warn] {name}: empty raw values, skip")
            continue
        mean = float(np.mean(vals))
        std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 1.0
        if std < 1e-12:
            std = 1.0
        normalization["zscore_clip"][name] = {
            "mean": mean,
            "std": std,
            "n_samples": int(len(vals)),
        }
        print(f"  zscore:      {name:<22}  n={len(vals):,}  mean={mean:+.4f}  std={std:.4f}")

    # 7) JSON payload 구성
    payload = {
        "meta": {
            "trial_number": trial_number,
            "study_name": study_name,
            "phase_a_run": phase_a_id,
            "universe_size": len(feat_by_code_norm),
            "train_dates_span": [train_dates[0], train_dates[-1]],
            "n_train_bars": int(len(train_ctx.timeline_dates)),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_trial_value": float(trial.value),
            "test_metrics_snapshot": {
                "note": "see artifacts/phase_b/<study>/validation.csv for test metrics",
            },
        },
        "entry": {
            "threshold_abs": threshold_abs,
            "entry_pct": entry_pct,
            "max_positions": int(trial.params["max_positions"]),
        },
        "exit": {
            "stop_loss_pct": float(trial.params["stop_loss_pct"]),
            "take_profit_pct": float(trial.params["take_profit_pct"]),
            "max_holding_days": int(trial.params["max_holding_days"]),
            "time_exit_bars": int(trial.params.get("time_exit_bars", 2000)),
        },
        "weights": weights,
        "feature_names": surviving,
        "normalization": normalization,
    }

    # 8) 저장
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[export] saved: {output_path}")
    print(f"[export] size: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"[export] elapsed: {time.time() - t0:.1f}s")
    return payload


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--study", type=str, required=True)
    p.add_argument("--trial", type=int, required=True)
    p.add_argument("--universe-size", type=int, default=200)
    p.add_argument(
        "--output",
        type=str,
        default=str(config.PROJECT_ROOT / "core" / "strategies" / "weighted_score_params.json"),
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    build_params(
        study_name=args.study,
        trial_number=args.trial,
        universe_size=args.universe_size,
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
