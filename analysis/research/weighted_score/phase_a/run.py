"""Phase A 엔드투엔드 CLI.

실행:
    python -m analysis.research.weighted_score.phase_a.run --smoke
    python -m analysis.research.weighted_score.phase_a.run --universe-size 50

단계:
1. Universe 선정 (옵션 제한)
2. 종목별 분봉 로드 → 피처 계산·정규화 → parquet 캐시
3. Triple-barrier 라벨 생성
4. Train 구간 pooled 데이터로 L1 로지스틱 회귀 학습
5. Train score 분포에서 entry_threshold 후보 선정 (75/85/90/95 분위)
6. 청산 그리드 서치 (train Calmar)
7. 상위 K 조합을 test 구간에서 재시뮬
8. artifacts/phase_a/<run_id>/ 에 결과 저장
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import feature_store, pg_loader
from analysis.research.weighted_score.features import pipeline as feat_pipeline
from analysis.research.weighted_score.phase_a import exit_grid, labeling, train_logreg
from analysis.research.weighted_score.sim.cost_model import CostModel
from analysis.research.weighted_score.strategy.weighted_score import WeightedScoreStrategy
from analysis.research.weighted_score.universe import universe_codes


# ---------- 피처 캐시 ----------


REQUIRED_CACHE_COLS = ("trade_date", "idx", "open", "high", "low", "close", "time")


def _cache_valid(code: str) -> bool:
    """캐시 parquet 이 필수 컬럼을 포함하는지 확인. 구 버전 캐시 걸러냄."""
    if not feature_store.has_features(code):
        return False
    df = feature_store.load_features(code)
    if df is None or df.empty:
        return False
    return all(c in df.columns for c in REQUIRED_CACHE_COLS)


def _ensure_cached_features(
    codes: list[str],
    rolling_window: int,
    min_periods: int,
    force: bool = False,
) -> None:
    """종목별로 (raw+normalized) 피처 parquet 캐시 생성. 유효 캐시면 skip."""
    for i, code in enumerate(codes, 1):
        if not force and _cache_valid(code):
            print(f"  [{i}/{len(codes)}] {code}: cache hit, skip")
            continue
        t0 = time.time()
        df = pg_loader.load_minute_range(code, config.DATA_START, config.DATA_END)
        if df.empty:
            print(f"  [{i}/{len(codes)}] {code}: empty minute data, skip")
            continue
        feat = feat_pipeline.compute_and_normalize(
            df, rolling_window=rolling_window, min_periods=min_periods
        )
        feature_store.save_features(code, feat)
        print(f"  [{i}/{len(codes)}] {code}: computed {len(feat):,} rows in {time.time() - t0:.1f}s")


def _load_cached_features(codes: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for code in codes:
        df = feature_store.load_features(code)
        if df is not None and not df.empty:
            out[code] = df
    return out


# ---------- 라벨링 ----------


def _build_labeled_pool(
    feat_by_code: dict[str, pd.DataFrame],
    train_dates: list[str],
    label_cfg: labeling.LabelingConfig,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """모든 종목의 train 구간 피처+라벨 → pooled DF.

    반환: (pooled_df, stock_label_stats).
    """
    train_date_set = set(train_dates)
    parts: list[pd.DataFrame] = []
    stats: dict[str, float] = {}
    for code, df in feat_by_code.items():
        sub = df[df["trade_date"].isin(train_date_set)].copy()
        if sub.empty:
            continue
        labels = labeling.triple_barrier_labels(sub, label_cfg)
        lf = train_logreg.prepare_training_frame(
            feat_df=sub[["trade_date", "idx"] + feat_pipeline.ALL_FEATURE_NAMES],
            label_series=labels,
            stock_code=code,
        )
        if not lf.empty:
            parts.append(lf)
            stats[code] = float((lf["label"] == 1).mean())
    if not parts:
        raise RuntimeError("pooled training frame is empty")
    pooled = pd.concat(parts, axis=0).sort_values(["trade_date", "idx"]).reset_index(drop=True)
    return pooled, stats


# ---------- 아티팩트 ----------


def _new_run_dir() -> Path:
    config.ensure_artifact_dirs()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = config.PHASE_A_DIR / run_id
    p.mkdir(parents=True, exist_ok=False)
    return p


def _save_weights(dir_: Path, result: train_logreg.LogRegResult) -> None:
    payload = {
        "best_C": result.best_C,
        "intercept": result.intercept,
        "cv_auc_mean": result.cv_auc_mean,
        "cv_auc_std": result.cv_auc_std,
        "train_auc": result.train_auc,
        "n_train_samples": result.n_train_samples,
        "weights": result.weights,
        "surviving_features": result.surviving_features,
        "all_cv_scores": {str(k): list(v) for k, v in result.all_cv_scores.items()},
    }
    (dir_ / "weights.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _save_grid_csv(dir_: Path, df: pd.DataFrame) -> None:
    df.to_csv(dir_ / "exit_grid.csv", index=False)


def _write_report(
    dir_: Path,
    cfg: dict,
    logreg: train_logreg.LogRegResult,
    grid_df: pd.DataFrame,
) -> None:
    lines: list[str] = []
    lines.append(f"# Phase A 리포트 ({dir_.name})\n")
    lines.append(f"**생성 시각**: {datetime.now().isoformat(timespec='seconds')}\n")

    lines.append("\n## 실행 설정\n")
    lines.append("```json")
    lines.append(json.dumps(cfg, indent=2, ensure_ascii=False))
    lines.append("```\n")

    lines.append("\n## 로지스틱 회귀 결과\n")
    lines.append(f"- best_C: **{logreg.best_C}**")
    lines.append(f"- CV AUC: **{logreg.cv_auc_mean:.4f} ± {logreg.cv_auc_std:.4f}**")
    lines.append(f"- Train AUC: **{logreg.train_auc:.4f}**")
    lines.append(f"- 샘플 수: {logreg.n_train_samples:,}")
    lines.append(f"- 살아남은 피처: **{len(logreg.surviving_features)} / {len(logreg.weights)}**")

    lines.append("\n### 피처 가중치 (|coef| 내림차순)\n")
    lines.append("| 피처 | coef | 생존 |")
    lines.append("|---|---:|:---:|")
    for name, w in sorted(logreg.weights.items(), key=lambda x: -abs(x[1])):
        mark = "✓" if abs(w) > 1e-9 else "-"
        lines.append(f"| {name} | {w:+.5f} | {mark} |")

    lines.append("\n## 청산 그리드 TOP 10 (train_calmar 순)\n")
    if not grid_df.empty:
        top = grid_df.head(10)
        cols_to_show = [c for c in [
            "entry_threshold", "stop_loss_pct", "take_profit_pct",
            "max_positions", "max_holding_days",
            "train_calmar", "train_mdd", "train_total_return",
            "train_sharpe", "train_win_rate", "train_n_trades",
            "test_calmar", "test_mdd", "test_total_return", "test_n_trades",
        ] if c in top.columns]
        header = " | ".join(cols_to_show)
        sep = " | ".join(["---"] * len(cols_to_show))
        lines.append("| " + header + " |")
        lines.append("| " + sep + " |")
        for _, row in top[cols_to_show].iterrows():
            vals = [f"{row[c]:.4f}" if isinstance(row[c], (int, float, np.floating)) else str(row[c]) for c in cols_to_show]
            lines.append("| " + " | ".join(vals) + " |")
    else:
        lines.append("(empty)")

    (dir_ / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- 메인 ----------


def _pick_entry_thresholds(
    weights: dict[str, float],
    feat_by_code: dict[str, pd.DataFrame],
    train_dates: list[str],
    percentiles: tuple[float, ...] = (75, 85, 90, 95),
) -> list[float]:
    """Train 구간에서 weighted score 분포의 주어진 percentile 값을 entry_threshold 후보로."""
    strategy = WeightedScoreStrategy(
        weights=weights,
        entry_threshold=-1e18,  # 임시
        exit_policy=_dummy_policy(),
    )
    scores_all = []
    date_set = set(train_dates)
    for df in feat_by_code.values():
        sub = df[df["trade_date"].isin(date_set)]
        if sub.empty:
            continue
        s = strategy.score_frame(sub).dropna()
        scores_all.append(s.to_numpy())
    if not scores_all:
        raise RuntimeError("no scores computable for entry threshold selection")
    arr = np.concatenate(scores_all)
    thresholds = [float(np.percentile(arr, p)) for p in percentiles]
    return thresholds


def _dummy_policy():
    from analysis.research.weighted_score.strategy.exit_rules import ExitPolicy
    return ExitPolicy(stop_loss_pct=-3.0, take_profit_pct=5.0, max_holding_days=3)


def run_phase_a(
    universe_size: Optional[int],
    train_ratio: float,
    rolling_window: int,
    min_periods: int,
    label_horizon_bars: int,
    label_tp_pct: float,
    label_sl_pct: float,
    logreg_max_per_stock: int,
    logreg_max_total: int,
    stop_loss_pcts: list[float],
    take_profit_pcts: list[float],
    max_positions_list: list[int],
    max_holding_days_list: list[int],
    entry_percentiles: tuple[float, ...],
    top_k_for_test: int,
    output_dir: Optional[Path] = None,
) -> Path:
    t_total = time.time()
    run_dir = output_dir or _new_run_dir()
    print(f"[phase_a] run_dir = {run_dir}")

    # 1) universe
    all_codes = universe_codes()
    codes = all_codes if universe_size is None else all_codes[:universe_size]
    print(f"[phase_a] universe = {len(codes)} codes (of {len(all_codes)})")

    # 2) 피처 캐시
    print(f"[phase_a] precomputing features (window={rolling_window}, min_periods={min_periods})...")
    _ensure_cached_features(codes, rolling_window, min_periods, force=False)
    feat_by_code = _load_cached_features(codes)
    if not feat_by_code:
        raise RuntimeError("no cached features loaded")
    print(f"[phase_a] loaded features for {len(feat_by_code)} codes")

    # 3) train/test split
    train_dates, test_dates = pg_loader.train_test_split_dates(train_ratio=train_ratio)
    print(f"[phase_a] train={len(train_dates)}d {train_dates[0]}~{train_dates[-1]}  "
          f"test={len(test_dates)}d {test_dates[0]}~{test_dates[-1]}")

    # 4) 라벨링 + pooled DF
    label_cfg = labeling.LabelingConfig(
        horizon_bars=label_horizon_bars, tp_pct=label_tp_pct, sl_pct=label_sl_pct,
    )
    pooled, lbl_stats = _build_labeled_pool(feat_by_code, train_dates, label_cfg)
    print(f"[phase_a] pooled samples: {len(pooled):,}  "
          f"pos_rate={(pooled['label'] == 1).mean():.4f}")

    # 5) L1 로지스틱 회귀
    t0 = time.time()
    logreg_result = train_logreg.fit_l1_logreg(
        pooled,
        feature_names=feat_pipeline.ALL_FEATURE_NAMES,
        max_samples_per_stock=logreg_max_per_stock,
        max_total_samples=logreg_max_total,
    )
    print(f"[phase_a] logreg elapsed {time.time() - t0:.1f}s  "
          f"cv_auc={logreg_result.cv_auc_mean:.4f}  "
          f"surviving={len(logreg_result.surviving_features)}")

    # 전체 피처가 아닌 surviving 만 쓰는게 효율적이지만, 단순화 위해 전부 사용
    # (coef=0 인 피처는 시뮬에 영향 없음)

    # 6) entry_threshold 후보
    thresholds = _pick_entry_thresholds(
        logreg_result.weights, feat_by_code, train_dates, percentiles=entry_percentiles,
    )
    print(f"[phase_a] entry thresholds: {[f'{t:.3f}' for t in thresholds]} "
          f"(percentiles={entry_percentiles})")

    # 7) 청산 그리드
    grid_cfg = exit_grid.ExitGridConfig(
        entry_thresholds=thresholds,
        stop_loss_pcts=stop_loss_pcts,
        take_profit_pcts=take_profit_pcts,
        max_positions_list=max_positions_list,
        max_holding_days_list=max_holding_days_list,
    )
    print(f"[phase_a] grid combos: {grid_cfg.n_combos()}")

    cost_model = CostModel(one_way_pct=config.COST_ONE_WAY_PCT)
    results = exit_grid.run_exit_grid(
        weights=logreg_result.weights,
        feat_by_code=feat_by_code,
        train_dates=train_dates,
        test_dates=test_dates,
        grid=grid_cfg,
        initial_capital=config.INITIAL_CAPITAL,
        size_krw=config.POSITION_SIZE_KRW,
        cost_model=cost_model,
        top_k_for_test=top_k_for_test,
    )
    grid_df = exit_grid.rank_results(results)

    # 8) 저장
    cfg_dump = {
        "universe_size": len(codes),
        "train_dates_span": [train_dates[0], train_dates[-1]],
        "test_dates_span": [test_dates[0], test_dates[-1]],
        "rolling_window": rolling_window,
        "min_periods": min_periods,
        "label_cfg": asdict(label_cfg),
        "logreg_max_per_stock": logreg_max_per_stock,
        "logreg_max_total": logreg_max_total,
        "grid_combos": grid_cfg.n_combos(),
        "top_k_for_test": top_k_for_test,
        "entry_percentiles": list(entry_percentiles),
        "cost_one_way_pct": config.COST_ONE_WAY_PCT,
        "initial_capital": config.INITIAL_CAPITAL,
        "position_size_krw": config.POSITION_SIZE_KRW,
    }
    (run_dir / "config.json").write_text(
        json.dumps(cfg_dump, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _save_weights(run_dir, logreg_result)
    _save_grid_csv(run_dir, grid_df)
    _write_report(run_dir, cfg_dump, logreg_result, grid_df)

    print(f"\n[phase_a] total elapsed {time.time() - t_total:.1f}s → {run_dir}")
    return run_dir


def _parse_args():
    p = argparse.ArgumentParser(description="Phase A end-to-end runner")
    p.add_argument("--smoke", action="store_true", help="소규모 스모크 모드 (3종목, 작은 그리드)")
    p.add_argument("--universe-size", type=int, default=None, help="사용할 종목 수 상한")
    p.add_argument("--train-ratio", type=float, default=8.0 / 12.0)
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.smoke:
        run_phase_a(
            universe_size=3,
            train_ratio=args.train_ratio,
            rolling_window=500,
            min_periods=50,
            label_horizon_bars=60,
            label_tp_pct=1.5,
            label_sl_pct=-1.5,
            logreg_max_per_stock=3_000,
            logreg_max_total=10_000,
            stop_loss_pcts=[-2.0, -3.0, -5.0],
            take_profit_pcts=[3.0, 5.0],
            max_positions_list=[3, 7],
            max_holding_days_list=[3],
            entry_percentiles=(85, 95),
            top_k_for_test=3,
        )
    else:
        run_phase_a(
            universe_size=args.universe_size,
            train_ratio=args.train_ratio,
            rolling_window=1000,
            min_periods=50,
            label_horizon_bars=60,
            label_tp_pct=1.5,
            label_sl_pct=-1.5,
            logreg_max_per_stock=10_000,
            logreg_max_total=200_000,
            stop_loss_pcts=[-1.5, -2.0, -3.0, -4.0, -5.0],
            take_profit_pcts=[2.0, 3.0, 5.0, 8.0],
            max_positions_list=[3, 5, 7, 10],
            max_holding_days_list=[3, 5],
            entry_percentiles=(75, 85, 90, 95),
            top_k_for_test=5,
        )


if __name__ == "__main__":
    main()
