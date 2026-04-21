"""Phase B runner: Optuna study 생성·저장·실행.

실행:
    python -m analysis.research.weighted_score.phase_b.runner --smoke
    python -m analysis.research.weighted_score.phase_b.runner \\
        --phase-a-run 20260421_001133 --trials 2000 --universe-size 200

전제조건:
- Phase A 결과 (`artifacts/phase_a/<run_id>/weights.json`) 존재
- 피처 캐시 (`artifacts/features/*.parquet`) 존재

출력:
- `artifacts/phase_b/<study_name>/study.db` (sqlite)
- `artifacts/phase_b/<study_name>/best_params.json`
- `artifacts/phase_b/<study_name>/trials.csv`
- `artifacts/phase_b/<study_name>/config.json`
"""
from __future__ import annotations

import argparse
import json
import time
import warnings
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import optuna
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import feature_store, pg_loader
from analysis.research.weighted_score.phase_b import objective as obj_mod
from analysis.research.weighted_score.phase_b import search_space as ss
from analysis.research.weighted_score.sim import fast_engine
from analysis.research.weighted_score.sim.cost_model import CostModel
from analysis.research.weighted_score.universe import universe_codes


warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)


# ---------- 로드 유틸 ----------


def _load_phase_a(run_id: str) -> dict:
    run_dir = config.PHASE_A_DIR / run_id
    wpath = run_dir / "weights.json"
    cpath = run_dir / "config.json"
    if not wpath.exists():
        raise FileNotFoundError(f"weights.json not found: {wpath}")
    weights = json.loads(wpath.read_text(encoding="utf-8"))
    cfg = json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {}
    return {"weights_payload": weights, "phase_a_config": cfg}


def _load_cached_features(codes: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for code in codes:
        df = feature_store.load_features(code)
        if df is not None and not df.empty:
            out[code] = df
    return out


def _pick_codes(universe_size: Optional[int]) -> list[str]:
    all_codes = universe_codes()
    if universe_size is None:
        return all_codes
    return all_codes[:universe_size]


# ---------- 저장 유틸 ----------


def _new_study_dir(name_prefix: str = "phaseb") -> tuple[str, Path]:
    config.ensure_artifact_dirs()
    study_name = f"{name_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    p = config.PHASE_B_DIR / study_name
    p.mkdir(parents=True, exist_ok=False)
    return study_name, p


def _save_config(dir_: Path, cfg: dict) -> None:
    (dir_ / "config.json").write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _save_trials_csv(dir_: Path, study: optuna.Study) -> None:
    rows = []
    for t in study.trials:
        row = {
            "number": t.number,
            "state": t.state.name,
            "value": t.value if t.value is not None else float("nan"),
            "datetime_start": t.datetime_start.isoformat() if t.datetime_start else None,
            "datetime_complete": t.datetime_complete.isoformat() if t.datetime_complete else None,
        }
        row.update({f"param_{k}": v for k, v in t.params.items()})
        row.update({f"attr_{k}": v for k, v in t.user_attrs.items()})
        rows.append(row)
    pd.DataFrame(rows).to_csv(dir_ / "trials.csv", index=False)


def _save_best_params(dir_: Path, study: optuna.Study, space: ss.SearchSpaceConfig) -> None:
    if not study.best_trial:
        return
    best = study.best_trial
    weights = {
        name: best.params[f"w_{name}"]
        for name in space.surviving_features
        if f"w_{name}" in best.params
    }
    payload = {
        "number": best.number,
        "value": best.value,
        "params": best.params,
        "weights": weights,
        "user_attrs": dict(best.user_attrs),
    }
    (dir_ / "best_params.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------- 메인 ----------


def run(
    phase_a_run_id: str,
    n_trials: int,
    universe_size: Optional[int],
    train_ratio: float = 8.0 / 12.0,
    n_jobs: int = config.N_JOBS,
    seed: int = config.SEED,
    min_trades: int = obj_mod.MIN_TRADES_FOR_VALID_CALMAR,
    resume_study_name: Optional[str] = None,
) -> Path:
    t_total = time.time()

    # 1) Phase A 결과 로드
    pa = _load_phase_a(phase_a_run_id)
    weights_a = pa["weights_payload"]["weights"]
    surviving = ss.surviving_from_weights(weights_a)
    signs = ss.extract_signs_from_weights(weights_a)
    print(f"[phase_b] Phase A run: {phase_a_run_id}")
    print(f"[phase_b] surviving features: {len(surviving)} / {len(weights_a)}")

    # 2) Universe + 피처 캐시 로드
    codes = _pick_codes(universe_size)
    feat_by_code = _load_cached_features(codes)
    if not feat_by_code:
        raise RuntimeError(
            f"no cached features — run phase_a first with matching universe_size"
        )
    print(f"[phase_b] universe = {len(codes)} requested, {len(feat_by_code)} cached")

    # 3) Train/Test split
    train_dates, test_dates = pg_loader.train_test_split_dates(train_ratio=train_ratio)
    print(f"[phase_b] train={len(train_dates)}d  test={len(test_dates)}d")

    # 4) Train context 빌드
    t0 = time.time()
    train_ctx = fast_engine.build_context(
        feat_by_code, train_dates, feature_names=surviving
    )
    print(f"[phase_b] train ctx built {time.time() - t0:.1f}s  "
          f"N={len(train_ctx.timeline_dates):,}  K={len(train_ctx.stock_codes)}")

    # 5) Study 생성
    if resume_study_name:
        study_name = resume_study_name
        study_dir = config.PHASE_B_DIR / study_name
        if not study_dir.exists():
            raise FileNotFoundError(f"study dir not found: {study_dir}")
    else:
        study_name, study_dir = _new_study_dir()
    storage_url = f"sqlite:///{(study_dir / 'study.db').as_posix()}"
    print(f"[phase_b] study_name: {study_name}")
    print(f"[phase_b] storage: {storage_url}")

    sampler = optuna.samplers.TPESampler(multivariate=True, seed=seed)
    pruner = optuna.pruners.MedianPruner(n_startup_trials=20, n_warmup_steps=0)
    study = optuna.create_study(
        study_name=study_name,
        storage=storage_url,
        sampler=sampler,
        pruner=pruner,
        direction="maximize",
        load_if_exists=True,
    )

    # 6) Objective
    space = ss.SearchSpaceConfig(surviving_features=surviving, feature_signs=signs)
    objective = obj_mod.make_objective(
        space=space,
        train_ctx=train_ctx,
        cost_model=CostModel(one_way_pct=config.COST_ONE_WAY_PCT),
        initial_capital=config.INITIAL_CAPITAL,
        size_krw=config.POSITION_SIZE_KRW,
        min_trades=min_trades,
    )

    # 7) 탐색
    print(f"[phase_b] optimizing {n_trials} trials, n_jobs={n_jobs}...")
    t0 = time.time()
    try:
        study.optimize(
            objective,
            n_trials=n_trials,
            n_jobs=n_jobs,
            show_progress_bar=False,
            catch=(RuntimeError, ValueError),
        )
    except KeyboardInterrupt:
        print("[phase_b] interrupted, saving partial results")
    elapsed = time.time() - t0
    print(f"[phase_b] optimize elapsed {elapsed:.1f}s  "
          f"({elapsed / max(n_trials, 1):.2f}s/trial)")

    # 8) 결과 저장
    cfg_dump = {
        "phase_a_run_id": phase_a_run_id,
        "universe_size_requested": universe_size,
        "universe_size_used": len(feat_by_code),
        "train_dates_span": [train_dates[0], train_dates[-1]],
        "test_dates_span": [test_dates[0], test_dates[-1]],
        "surviving_features": surviving,
        "feature_signs": signs,
        "n_trials_requested": n_trials,
        "n_trials_completed": len(study.trials),
        "n_jobs": n_jobs,
        "seed": seed,
        "min_trades": min_trades,
        "initial_capital": config.INITIAL_CAPITAL,
        "position_size_krw": config.POSITION_SIZE_KRW,
        "cost_one_way_pct": config.COST_ONE_WAY_PCT,
    }
    _save_config(study_dir, cfg_dump)
    _save_trials_csv(study_dir, study)
    _save_best_params(study_dir, study, space)

    if study.best_trial:
        bt = study.best_trial
        print(f"\n[phase_b] BEST trial #{bt.number}: value={bt.value:.4f}")
        print(f"  params: n_trades={bt.user_attrs.get('n_trades', '?')}  "
              f"mdd={bt.user_attrs.get('mdd', 0):.4f}  "
              f"sharpe={bt.user_attrs.get('sharpe', 0):.3f}  "
              f"total_ret={bt.user_attrs.get('total_return', 0):+.4f}")

    print(f"\n[phase_b] total elapsed {time.time() - t_total:.1f}s → {study_dir}")
    return study_dir


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--phase-a-run", type=str, required=False, default=None,
                   help="Phase A 결과 run_id (예: 20260421_001133). 미지정시 최신 사용")
    p.add_argument("--trials", type=int, default=2000)
    p.add_argument("--universe-size", type=int, default=None)
    p.add_argument("--n-jobs", type=int, default=config.N_JOBS)
    p.add_argument("--resume", type=str, default=None, help="기존 study_name 로 이어서")
    p.add_argument("--smoke", action="store_true", help="50 trials, universe=3")
    return p.parse_args()


def _latest_phase_a() -> str:
    """weights.json 이 있는 최신 Phase A run 반환 (진행 중 런 제외)."""
    dirs = sorted(config.PHASE_A_DIR.glob("*"), reverse=True)
    for d in dirs:
        if (d / "weights.json").exists():
            return d.name
    raise FileNotFoundError("no completed Phase A run found")


def main() -> None:
    args = _parse_args()
    phase_a_id = args.phase_a_run or _latest_phase_a()

    if args.smoke:
        run(
            phase_a_run_id=phase_a_id,
            n_trials=50,
            universe_size=3,
            n_jobs=1,
        )
    else:
        run(
            phase_a_run_id=phase_a_id,
            n_trials=args.trials,
            universe_size=args.universe_size,
            n_jobs=args.n_jobs,
            resume_study_name=args.resume,
        )


if __name__ == "__main__":
    main()
