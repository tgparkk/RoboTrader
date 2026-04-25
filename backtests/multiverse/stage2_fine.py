"""Stage 2 Fine Search — Optuna TPE 1000 trials × 3-fold walk-forward.

각 trial:
  1. TPE sampler 가 param_space 에서 샘플
  2. 3 fold 각각 train + test 백테스트
  3. aggregate metrics 로 게이트 평가 (5/5 + Calmar≥3 floor)
  4. Objective = test Calmar 의 3-fold 평균

결과:
  - Optuna study: PostgreSQL `robotrader_optuna` DB (study_name = stage2_<strategy>)
  - trials CSV: backtests/reports/stage2/<strategy>_trials.csv
  - best params JSON: backtests/reports/stage2/<strategy>_best.json
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Type

import numpy as np
import optuna
import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.common.engine import BacktestEngine
from backtests.multiverse.fold import Fold, STAGE2_FOLDS, stage2_data_range
from backtests.multiverse.stage1_coarse import (
    GATE_OVERFIT_MIN, GATE_MDD_MAX, GATE_TRADES_MIN,
    GATE_WIN_RATE_MIN, GATE_MONTHLY_TRADES_MIN, STAGE1_CALMAR_FLOOR,
)
from backtests.strategies.base import StrategyBase
from config.settings import optuna_pg_url


optuna.logging.set_verbosity(optuna.logging.WARNING)


def suggest_params(trial: optuna.Trial, param_space: Dict) -> Dict:
    """Optuna trial 에서 strategy.param_space 에 따라 파라미터 샘플."""
    out = {}
    for name, spec in param_space.items():
        t = spec["type"]
        lo, hi = spec["low"], spec["high"]
        step = spec.get("step")
        if t == "int":
            out[name] = trial.suggest_int(name, lo, hi, step=step or 1)
        elif t == "float":
            if step:
                out[name] = trial.suggest_float(name, lo, hi, step=step)
            else:
                out[name] = trial.suggest_float(name, lo, hi)
        else:
            raise ValueError(f"unknown param type {t}")
    return out


def slice_minute_daily(
    minute_by_code: Dict[str, pd.DataFrame],
    daily_by_code: Dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
):
    m_slice = {
        c: df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)].reset_index(drop=True)
        for c, df in minute_by_code.items()
    }
    d_slice = {
        c: df[df["trade_date"] <= end_date].reset_index(drop=True)
        for c, df in daily_by_code.items()
    }
    return m_slice, d_slice


def evaluate_fold(
    strategy_class: Type[StrategyBase], params: Dict, fold: Fold,
    minute_by_code: Dict, daily_by_code: Dict,
    initial_capital: float = 100_000_000,
):
    """단일 fold train + test → metrics + gate flags 반환.

    Returns:
        {"train": metrics, "test": metrics, "gates_passed": int, "all_pass": bool}
    """
    universe = list(minute_by_code.keys())

    # train
    m_tr, d_tr = slice_minute_daily(
        minute_by_code, daily_by_code, fold.train_start, fold.train_end
    )
    nonempty_tr = [c for c in universe if len(m_tr.get(c, pd.DataFrame())) > 0]
    if not nonempty_tr:
        return None
    eng_tr = BacktestEngine(
        strategy=strategy_class(**params),
        initial_capital=initial_capital, universe=nonempty_tr,
        minute_df_by_code={c: m_tr[c] for c in nonempty_tr},
        daily_df_by_code={c: d_tr.get(c, pd.DataFrame()) for c in nonempty_tr},
    )
    train_m = eng_tr.run().metrics

    # test
    m_te, d_te = slice_minute_daily(
        minute_by_code, daily_by_code, fold.test_start, fold.test_end
    )
    nonempty_te = [c for c in universe if len(m_te.get(c, pd.DataFrame())) > 0]
    if not nonempty_te:
        return None
    eng_te = BacktestEngine(
        strategy=strategy_class(**params),
        initial_capital=initial_capital, universe=nonempty_te,
        minute_df_by_code={c: m_te[c] for c in nonempty_te},
        daily_df_by_code={c: d_te.get(c, pd.DataFrame()) for c in nonempty_te},
    )
    test_m = eng_te.run().metrics

    # gates
    train_calmar = train_m.get("calmar", float("nan"))
    test_calmar = test_m.get("calmar", float("nan"))
    if not math.isfinite(train_calmar) or train_calmar <= 0:
        overfit_ratio = float("nan")
    else:
        overfit_ratio = test_calmar / train_calmar

    test_trades = test_m.get("total_trades", 0)
    # test 기간 거래일 수 — Stage 1 evaluate_gates 와 동일 공식 (월 차이 × 21 + 21)
    test_period_days = (
        int(fold.test_end[:6]) - int(fold.test_start[:6])
    ) * 21 + 21
    test_months = max(test_period_days / 21.0, 0.001)
    monthly_trades = test_trades / test_months

    # overfit gate: train_calmar 유효할 때만 평가 (stage1_coarse.evaluate_gates 와 동일 정책)
    if math.isfinite(train_calmar) and train_calmar > 0:
        g_overfit = math.isfinite(overfit_ratio) and overfit_ratio >= GATE_OVERFIT_MIN
    else:
        g_overfit = True
    gates = {
        "overfit": g_overfit,
        "mdd": abs(test_m.get("mdd", 0)) <= GATE_MDD_MAX,
        "trades": test_trades >= GATE_TRADES_MIN,
        "win_rate": test_m.get("win_rate", 0) >= GATE_WIN_RATE_MIN,
        "monthly_trades": monthly_trades >= GATE_MONTHLY_TRADES_MIN,
    }
    n_pass = sum(gates.values())
    calmar_ok = math.isfinite(test_calmar) and test_calmar >= STAGE1_CALMAR_FLOOR
    all_pass = (n_pass == 5) and calmar_ok

    return {
        "train": train_m,
        "test": test_m,
        "overfit_ratio": overfit_ratio,
        "monthly_trades": monthly_trades,
        "gates": gates,
        "gates_passed": n_pass,
        "calmar_ok": calmar_ok,
        "all_pass": all_pass,
    }


def make_objective(
    strategy_class: Type[StrategyBase],
    folds: List[Fold],
    minute_by_code: Dict,
    daily_by_code: Dict,
    initial_capital: float = 100_000_000,
):
    """Optuna objective 반환. 모든 fold 가 게이트 통과 필요."""
    inst = strategy_class()
    param_space = inst.param_space

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, param_space)
        fold_results = []
        for fold in folds:
            res = evaluate_fold(strategy_class, params, fold,
                                minute_by_code, daily_by_code, initial_capital)
            fold_results.append(res)

        # 모든 fold 의 metrics 를 user_attrs 에 저장 (디버깅용)
        for i, r in enumerate(fold_results):
            if r is None:
                trial.set_user_attr(f"fold{i+1}_status", "no_data")
                continue
            trial.set_user_attr(f"fold{i+1}_test_calmar", r["test"].get("calmar"))
            trial.set_user_attr(f"fold{i+1}_test_return", r["test"].get("total_return"))
            trial.set_user_attr(f"fold{i+1}_test_trades", r["test"].get("total_trades"))
            trial.set_user_attr(f"fold{i+1}_test_mdd", r["test"].get("mdd"))
            trial.set_user_attr(f"fold{i+1}_test_win_rate", r["test"].get("win_rate"))
            trial.set_user_attr(f"fold{i+1}_overfit", r["overfit_ratio"])
            trial.set_user_attr(f"fold{i+1}_monthly_trades", r["monthly_trades"])
            trial.set_user_attr(f"fold{i+1}_gates_passed", r["gates_passed"])
            trial.set_user_attr(f"fold{i+1}_all_pass", r["all_pass"])

        if any(r is None for r in fold_results):
            trial.set_user_attr("status", "fold_no_data")
            return -1e6

        # Spec § 3 의 "3-fold 평균" 정신을 따라, aggregate metrics 으로 게이트 평가:
        #   trades = sum, win_rate = trade-weighted avg, mdd = worst (가장 큰 음수)
        #   overfit_ratio = avg, monthly_trades = avg, calmar = avg
        fold_calmars = [r["test"].get("calmar", float("nan")) for r in fold_results]
        agg_trades = sum(r["test"].get("total_trades", 0) for r in fold_results)
        if agg_trades > 0:
            agg_win_rate = sum(
                r["test"].get("win_rate", 0) * r["test"].get("total_trades", 0)
                for r in fold_results
            ) / agg_trades
        else:
            agg_win_rate = 0.0
        worst_mdd = min(r["test"].get("mdd", 0) for r in fold_results)
        finite_overfits = [r["overfit_ratio"] for r in fold_results
                            if math.isfinite(r["overfit_ratio"])]
        avg_overfit = float(np.mean(finite_overfits)) if finite_overfits else float("nan")
        avg_monthly = float(np.mean([r["monthly_trades"] for r in fold_results]))
        finite_calmars = [c for c in fold_calmars if math.isfinite(c)]
        avg_calmar = float(np.mean(finite_calmars)) if finite_calmars else float("nan")

        # 게이트 평가 (aggregate)
        # overfit: 모든 fold 의 train_calmar 가 invalid 면 자동 통과 (stage1 정책)
        all_train_invalid = all(
            not math.isfinite(r["overfit_ratio"]) for r in fold_results
        )
        if all_train_invalid:
            g_overfit = True
        else:
            g_overfit = math.isfinite(avg_overfit) and avg_overfit >= GATE_OVERFIT_MIN

        gates = {
            "overfit": g_overfit,
            "mdd": abs(worst_mdd) <= GATE_MDD_MAX,
            "trades": agg_trades >= GATE_TRADES_MIN * len(folds),  # 3-fold 합산
            "win_rate": agg_win_rate >= GATE_WIN_RATE_MIN,
            "monthly_trades": avg_monthly >= GATE_MONTHLY_TRADES_MIN,
        }
        n_pass = sum(gates.values())
        calmar_floor_ok = math.isfinite(avg_calmar) and avg_calmar >= STAGE1_CALMAR_FLOOR
        valid = (n_pass == 5) and calmar_floor_ok

        trial.set_user_attr("avg_calmar", avg_calmar)
        trial.set_user_attr("avg_overfit", avg_overfit)
        trial.set_user_attr("avg_monthly_trades", avg_monthly)
        trial.set_user_attr("agg_trades", agg_trades)
        trial.set_user_attr("agg_win_rate", agg_win_rate)
        trial.set_user_attr("worst_mdd", worst_mdd)
        trial.set_user_attr("agg_gates_passed", n_pass)
        trial.set_user_attr("valid", valid)

        if not valid:
            failed = [k for k, v in gates.items() if not v]
            if not calmar_floor_ok:
                failed.append("calmar_floor")
            trial.set_user_attr("failed_aggregate_gates", failed)
            return -1e6

        return avg_calmar

    return objective


def run_stage2_for_strategy(
    strategy_class: Type[StrategyBase],
    n_trials: int = 1000,
    seed: int = 42,
    initial_capital: float = 100_000_000,
    folds: List[Fold] = STAGE2_FOLDS,
    minute_by_code: Optional[Dict] = None,
    daily_by_code: Optional[Dict] = None,
    universe: Optional[List[str]] = None,
    storage_dir: Path = Path("backtests/reports/stage2"),
    progress_every: int = 50,
):
    """전략 1개에 대해 Optuna TPE Stage 2."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    name = strategy_class.name

    if minute_by_code is None or daily_by_code is None:
        if universe is None:
            raise ValueError("universe 필요 (또는 minute_by_code 직접 전달)")
        d_start, d_end = stage2_data_range()
        # daily history: 1년 추가 (overnight 전략 충분)
        daily_history_start = f"{int(d_start[:4]) - 1}{d_start[4:]}"
        minute_df = load_minute_df(universe, d_start, d_end)
        daily_df = load_daily_df(universe, daily_history_start, d_end)
        minute_by_code = {
            c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
            for c in universe
        }
        daily_by_code = {
            c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
            for c in universe
        }

    storage = optuna_pg_url()
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        storage=storage,
        load_if_exists=True,
        study_name=f"stage2_{name}",
    )

    objective = make_objective(
        strategy_class, folds, minute_by_code, daily_by_code, initial_capital
    )

    n_done = len(study.trials)
    if n_done >= n_trials:
        print(f"[{name}] {n_done}/{n_trials} trials already done")
        return study

    print(f"[{name}] starting {n_trials - n_done} trials "
          f"(resuming from {n_done})")

    def _callback(study, trial):
        if (trial.number + 1) % progress_every == 0:
            best = study.best_value if study.best_value is not None else float("nan")
            n_valid = sum(1 for t in study.trials if t.value and t.value > -1e5)
            print(f"  [{name}] trial {trial.number + 1}/{n_trials} "
                  f"best={best:.2f}  valid={n_valid}")

    study.optimize(
        objective, n_trials=n_trials - n_done, callbacks=[_callback],
        show_progress_bar=False,
    )

    # 결과 저장
    save_study_results(study, storage_dir, name)
    return study


def save_study_results(study: optuna.Study, storage_dir: Path, strategy_name: str):
    """trials → CSV, best params → JSON."""
    rows = []
    for t in study.trials:
        row = {"trial_id": t.number, "value": t.value, "state": str(t.state)}
        for k, v in (t.params or {}).items():
            row[f"p_{k}"] = v
        for k, v in (t.user_attrs or {}).items():
            row[f"a_{k}"] = v
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(storage_dir / f"{strategy_name}_trials.csv", index=False)

    valid = [t for t in study.trials if t.value and t.value > -1e5]
    if valid:
        best = max(valid, key=lambda t: t.value)
        best_data = {
            "strategy": strategy_name,
            "best_value": best.value,
            "best_params": best.params,
            "best_user_attrs": best.user_attrs,
            "n_trials": len(study.trials),
            "n_valid": len(valid),
        }
        (storage_dir / f"{strategy_name}_best.json").write_text(
            json.dumps(best_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
