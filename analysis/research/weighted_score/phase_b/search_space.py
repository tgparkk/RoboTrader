"""Optuna 탐색 공간 정의.

Phase A 의 로지스틱 회귀 결과(weights.json) 를 seed 로 활용:
- 피처별로 coef 부호를 보존 (+ 면 [0, MAX_ABS_WEIGHT], - 면 [-MAX_ABS_WEIGHT, 0])
- 살아남은 피처만 탐색 대상 (|coef| > 1e-9)
- 부호 정보 없는 피처는 [-MAX_ABS_WEIGHT, MAX_ABS_WEIGHT]

탐색 파라미터:
- weights (per feature)          — float
- entry_pct (score percentile)   — float [70, 98]
- stop_loss_pct                  — float [-6, -1]
- take_profit_pct                — float [1.5, 10]
- time_exit_bars                 — int, step 30 [30, 2000]  (>=1800 은 사실상 비활성)
- max_positions                  — int [3, 10]
- max_holding_days               — categorical [3, 5]

**조건부 파라미터 회피**: time_exit_bars 를 "비활성화" 하고 싶으면 큰 값(>= 1800 = 약 5일)
으로 샘플링 → max_holding_days 상한에 걸리므로 실질적으로 트리거되지 않음. TPE 의
`multivariate=True` 가 독립 샘플링으로 폴백하지 않게 하는 trick.

**주의**: v1 은 trailing stop / score_exit_threshold 미지원 (fast_engine v1 한계).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


MAX_ABS_WEIGHT = 3.0


@dataclass
class SearchSpaceConfig:
    surviving_features: list[str]
    feature_signs: dict[str, str]  # '+' or '-' or 'any'
    entry_pct_range: tuple[float, float] = (70.0, 98.0)
    stop_loss_range: tuple[float, float] = (-6.0, -1.0)
    take_profit_range: tuple[float, float] = (1.5, 10.0)
    time_exit_bars_range: tuple[int, int] = (30, 2000)
    time_exit_bars_step: int = 30
    max_positions_range: tuple[int, int] = (3, 10)
    max_holding_days_choices: tuple[int, ...] = (3, 5)
    max_abs_weight: float = MAX_ABS_WEIGHT


def sample_params(trial, space: SearchSpaceConfig) -> dict:
    """한 trial 의 파라미터 샘플링 — 모든 파라미터 무조건 샘플링."""
    weights: dict[str, float] = {}
    for name in space.surviving_features:
        sign = space.feature_signs.get(name, "any")
        if sign == "+":
            weights[name] = trial.suggest_float(f"w_{name}", 0.0, space.max_abs_weight)
        elif sign == "-":
            weights[name] = trial.suggest_float(f"w_{name}", -space.max_abs_weight, 0.0)
        else:
            weights[name] = trial.suggest_float(
                f"w_{name}", -space.max_abs_weight, space.max_abs_weight
            )

    entry_pct = trial.suggest_float("entry_pct", *space.entry_pct_range)
    sl = trial.suggest_float("stop_loss_pct", *space.stop_loss_range)
    tp = trial.suggest_float("take_profit_pct", *space.take_profit_range)
    te = trial.suggest_int(
        "time_exit_bars",
        space.time_exit_bars_range[0],
        space.time_exit_bars_range[1],
        step=space.time_exit_bars_step,
    )
    mp = trial.suggest_int(
        "max_positions", space.max_positions_range[0], space.max_positions_range[1]
    )
    mhd = trial.suggest_categorical("max_holding_days", list(space.max_holding_days_choices))

    return {
        "weights": weights,
        "entry_pct": entry_pct,
        "stop_loss_pct": sl,
        "take_profit_pct": tp,
        "time_exit_bars": te,
        "max_positions": mp,
        "max_holding_days": mhd,
    }


def extract_signs_from_weights(weights: dict[str, float]) -> dict[str, str]:
    """Phase A weights → 피처별 부호 dict. coef==0 인 피처는 'any'."""
    out: dict[str, str] = {}
    for name, w in weights.items():
        if abs(w) <= 1e-9:
            out[name] = "any"
        elif w > 0:
            out[name] = "+"
        else:
            out[name] = "-"
    return out


def surviving_from_weights(weights: dict[str, float]) -> list[str]:
    return [name for name, w in weights.items() if abs(w) > 1e-9]
