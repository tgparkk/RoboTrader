"""Phase B 검증: 상위 K trial 을 test 구간에서 재시뮬.

실행:
    python -m analysis.research.weighted_score.phase_b.validate \\
        --study phaseb_20260421_001133 --top 20

절차:
1. Study 로드
2. train value (Calmar) 기준 상위 K trial 추출
3. 각 trial 의 params → test_ctx 에서 시뮬
4. (train_calmar + test_calmar) / 2 로 최종 순위
5. overfit 필터: train/test < 2.0
6. validation.csv + report.md 저장
"""
from __future__ import annotations

import argparse
import json
import time
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


OVERFIT_RATIO_LIMIT = 2.0


def _load_config(study_dir: Path) -> dict:
    p = study_dir / "config.json"
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))


def _load_study(study_dir: Path, study_name: str) -> optuna.Study:
    storage = f"sqlite:///{(study_dir / 'study.db').as_posix()}"
    return optuna.load_study(study_name=study_name, storage=storage)


def _trial_to_params(trial: optuna.trial.FrozenTrial, surviving: list[str]) -> dict:
    p = trial.params
    # time_exit_bars: 신 버전은 무조건 sample, 구 버전(use_time_exit 조건부) 도 호환
    if "time_exit_bars" in p:
        te = p["time_exit_bars"]
        if "use_time_exit" in p and not p["use_time_exit"]:
            te = None
    else:
        te = None
    return {
        "weights": {name: p[f"w_{name}"] for name in surviving if f"w_{name}" in p},
        "entry_pct": p["entry_pct"],
        "stop_loss_pct": p["stop_loss_pct"],
        "take_profit_pct": p["take_profit_pct"],
        "time_exit_bars": te,
        "max_positions": p["max_positions"],
        "max_holding_days": p["max_holding_days"],
    }


def validate(
    study_name: str,
    top_k: int = 20,
    universe_size: Optional[int] = None,
    overfit_limit: float = OVERFIT_RATIO_LIMIT,
) -> Path:
    study_dir = config.PHASE_B_DIR / study_name
    cfg = _load_config(study_dir)
    surviving: list[str] = cfg["surviving_features"]
    universe_used = cfg.get("universe_size_used")
    universe_size = universe_size or universe_used

    study = _load_study(study_dir, study_name)
    completed = [t for t in study.trials if t.value is not None and t.value > -1e8]
    completed.sort(key=lambda t: t.value, reverse=True)
    top = completed[:top_k]
    print(f"[validate] study has {len(completed)} completed trials; picking top {len(top)}")

    # 피처 로드 + test ctx 빌드
    from analysis.research.weighted_score.universe import universe_codes
    codes = universe_codes()[:universe_size] if universe_size else universe_codes()
    feat_by_code: dict[str, pd.DataFrame] = {}
    for c in codes:
        df = feature_store.load_features(c)
        if df is not None and not df.empty:
            feat_by_code[c] = df
    print(f"[validate] loaded features for {len(feat_by_code)} codes")

    train_dates, test_dates = pg_loader.train_test_split_dates()
    t0 = time.time()
    test_ctx = fast_engine.build_context(feat_by_code, test_dates, feature_names=surviving)
    print(f"[validate] test_ctx built {time.time() - t0:.1f}s  "
          f"N={len(test_ctx.timeline_dates):,}")

    cost = CostModel(one_way_pct=config.COST_ONE_WAY_PCT)

    rows: list[dict] = []
    for t in top:
        params = _trial_to_params(t, surviving)
        t1 = time.time()
        try:
            result = obj_mod.simulate_trial(
                params, test_ctx, cost,
                config.INITIAL_CAPITAL, config.POSITION_SIZE_KRW,
            )
        except Exception as e:
            print(f"  [warn] trial {t.number} test sim failed: {e}")
            continue
        m = result.metrics
        train_calmar = t.value
        test_calmar = float(m.calmar)
        overfit_ratio = abs(train_calmar) / max(abs(test_calmar), 1e-9)
        rows.append({
            "trial_number": t.number,
            "train_calmar": train_calmar,
            "test_calmar": test_calmar,
            "test_total_return": float(m.total_return),
            "test_mdd": float(m.mdd),
            "test_sharpe": float(m.sharpe),
            "test_win_rate": float(m.win_rate),
            "test_n_trades": int(m.n_trades),
            "overfit_ratio": overfit_ratio,
            "passes_filter": overfit_ratio < overfit_limit and test_calmar > 0,
            "combined_score": 0.5 * (train_calmar + test_calmar),
            "params": json.dumps(t.params, ensure_ascii=False),
            "elapsed_sec": time.time() - t1,
        })

    val_df = pd.DataFrame(rows)
    if val_df.empty:
        print("[validate] no valid results")
        return study_dir

    # 최종 랭킹
    val_df = val_df.sort_values("combined_score", ascending=False).reset_index(drop=True)
    val_df.to_csv(study_dir / "validation.csv", index=False)

    # 리포트
    lines: list[str] = []
    lines.append(f"# Phase B 검증 리포트\n")
    lines.append(f"- Study: `{study_name}`")
    lines.append(f"- Top-K: {len(val_df)}")
    lines.append(f"- Overfit filter: train/test < {overfit_limit}\n")

    pass_df = val_df[val_df["passes_filter"]].reset_index(drop=True)
    lines.append(f"\n## 필터 통과 ({len(pass_df)}개, combined_score 순)\n")
    if not pass_df.empty:
        cols = [
            "trial_number", "train_calmar", "test_calmar", "test_total_return",
            "test_mdd", "test_sharpe", "test_win_rate", "test_n_trades",
            "overfit_ratio", "combined_score",
        ]
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for _, row in pass_df.head(10).iterrows():
            vals = [f"{row[c]:.4f}" if isinstance(row[c], (int, float, np.floating)) else str(row[c]) for c in cols]
            lines.append("| " + " | ".join(vals) + " |")
    else:
        lines.append("(통과 trial 없음)")

    lines.append(f"\n## 전체 {len(val_df)}건 (combined_score 상위 10)\n")
    cols = [
        "trial_number", "train_calmar", "test_calmar",
        "test_mdd", "test_n_trades", "overfit_ratio", "combined_score", "passes_filter",
    ]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for _, row in val_df.head(10).iterrows():
        vals = [
            f"{row[c]:.4f}" if isinstance(row[c], (int, float, np.floating)) else str(row[c])
            for c in cols
        ]
        lines.append("| " + " | ".join(vals) + " |")

    (study_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[validate] saved: {study_dir / 'validation.csv'}, {study_dir / 'report.md'}")

    return study_dir


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--study", type=str, required=True)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--universe-size", type=int, default=None)
    p.add_argument("--overfit-limit", type=float, default=OVERFIT_RATIO_LIMIT)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    validate(
        study_name=args.study,
        top_k=args.top,
        universe_size=args.universe_size,
        overfit_limit=args.overfit_limit,
    )


if __name__ == "__main__":
    main()
