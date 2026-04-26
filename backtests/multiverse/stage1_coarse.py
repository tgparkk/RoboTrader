"""Stage 1 Coarse Filter — 200 trials × 전략당 random search.

각 trial:
  1. param_space 에서 랜덤 샘플
  2. train 구간 백테스트
  3. test 구간 백테스트
  4. 게이트 평가 (5개 중 3+ 통과 + Calmar ≥ 3)

결과: trials DataFrame (params, metrics, gate flags) → CSV 저장.
가망 전략 = 하나라도 게이트 통과 trial 이 있는 전략.
"""
import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.common.engine import BacktestEngine
from backtests.multiverse.fold import Fold
from backtests.strategies.base import StrategyBase


# Stage 1 게이트 (Spec § 3)
GATE_OVERFIT_MIN = 0.5
GATE_MDD_MAX = 0.15
GATE_TRADES_MIN = 30
GATE_WIN_RATE_MIN = 0.35
GATE_MONTHLY_TRADES_MIN = 3
STAGE1_CALMAR_FLOOR = 3.0


@dataclass
class TrialResult:
    strategy_name: str
    trial_id: int
    params: Dict[str, Any]
    train_metrics: Dict[str, float] = field(default_factory=dict)
    test_metrics: Dict[str, float] = field(default_factory=dict)
    overfit_ratio: float = float("nan")
    monthly_trades: float = float("nan")
    gates_passed: int = 0
    gate_calmar_ok: bool = False
    pass_stage1: bool = False
    error: str = ""

    def to_row(self) -> Dict[str, Any]:
        row = {
            "strategy": self.strategy_name,
            "trial_id": self.trial_id,
            **{f"p_{k}": v for k, v in self.params.items()},
            **{f"train_{k}": v for k, v in self.train_metrics.items()},
            **{f"test_{k}": v for k, v in self.test_metrics.items()},
            "overfit_ratio": self.overfit_ratio,
            "monthly_trades": self.monthly_trades,
            "gates_passed": self.gates_passed,
            "gate_calmar_ok": self.gate_calmar_ok,
            "pass_stage1": self.pass_stage1,
            "error": self.error,
        }
        return row


def sample_params(param_space: Dict[str, Dict[str, Any]], rng: random.Random) -> Dict[str, Any]:
    """param_space 에서 랜덤 1 샘플 추출."""
    out = {}
    for name, spec in param_space.items():
        t = spec["type"]
        lo, hi = spec["low"], spec["high"]
        step = spec.get("step")
        if t == "int":
            if step:
                n_steps = int((hi - lo) / step) + 1
                out[name] = int(lo + rng.randrange(n_steps) * step)
            else:
                out[name] = rng.randint(lo, hi)
        elif t == "float":
            if step:
                n_steps = int((hi - lo) / step) + 1
                out[name] = float(lo + rng.randrange(n_steps) * step)
            else:
                out[name] = lo + rng.random() * (hi - lo)
        else:
            raise ValueError(f"unknown param type {t!r} for {name}")
    return out


def evaluate_gates(
    train_metrics: Dict[str, float],
    test_metrics: Dict[str, float],
    test_period_days: int,
) -> Dict[str, Any]:
    """5 게이트 + Calmar floor 검사. Spec § 3 기준."""
    train_calmar = train_metrics.get("calmar", float("nan"))
    test_calmar = test_metrics.get("calmar", float("nan"))

    # overfit_ratio = test / train (calmar 기준)
    if not math.isfinite(train_calmar) or train_calmar <= 0:
        overfit_ratio = float("nan")
    else:
        overfit_ratio = test_calmar / train_calmar

    test_trades = test_metrics.get("total_trades", 0)
    test_months = max(test_period_days / 21.0, 0.001)  # ~21 trading days/month
    monthly_trades = test_trades / test_months

    # overfit gate: train_calmar 유효할 때만 평가. train 무효 (NaN/non-positive) 면 auto-pass
    # (test 가 자체 Calmar floor 통과해야 해서 free pass 는 아님).
    if math.isfinite(train_calmar) and train_calmar > 0:
        g_overfit = math.isfinite(overfit_ratio) and overfit_ratio >= GATE_OVERFIT_MIN
    else:
        g_overfit = True
    gates = {
        "overfit": g_overfit,
        "mdd": abs(test_metrics.get("mdd", 0)) <= GATE_MDD_MAX,
        "trades": test_trades >= GATE_TRADES_MIN,
        "win_rate": test_metrics.get("win_rate", 0) >= GATE_WIN_RATE_MIN,
        "monthly_trades": monthly_trades >= GATE_MONTHLY_TRADES_MIN,
    }
    n_pass = sum(gates.values())
    gate_calmar_ok = math.isfinite(test_calmar) and test_calmar >= STAGE1_CALMAR_FLOOR
    # 강화 (2026-04-25): 5 게이트 모두 통과 + Calmar floor.
    # 기존 "3 of 5" 는 trades=2~3 outlier 가 통과하는 문제 발생 (post_drop_rebound,
    # limit_up_chase 의 inflated Calmar). 모든 게이트 mandatory 로 변경.
    pass_stage1 = (n_pass == 5) and gate_calmar_ok

    return {
        "overfit_ratio": overfit_ratio,
        "monthly_trades": monthly_trades,
        "gates": gates,
        "gates_passed": n_pass,
        "gate_calmar_ok": gate_calmar_ok,
        "pass_stage1": pass_stage1,
    }


def _slice_data_by_period(
    minute_by_code: Dict[str, pd.DataFrame],
    daily_by_code: Dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
):
    """기간으로 minute / daily 슬라이스. daily 는 history 보존 위해 end_date 까지만 자름."""
    minute_slice = {}
    for c, df in minute_by_code.items():
        m = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]
        minute_slice[c] = m.reset_index(drop=True)
    # daily 는 시작점 자르지 않음 (rolling/shift 위해 history 필요)
    daily_slice = {}
    for c, df in daily_by_code.items():
        d = df[df["trade_date"] <= end_date]
        daily_slice[c] = d.reset_index(drop=True)
    return minute_slice, daily_slice


def run_one_trial(
    strategy_class: Type[StrategyBase],
    params: Dict[str, Any],
    fold: Fold,
    minute_by_code: Dict[str, pd.DataFrame],
    daily_by_code: Dict[str, pd.DataFrame],
    initial_capital: float,
    trial_id: int,
) -> TrialResult:
    """단일 trial 실행: train + test 백테스트 + 게이트 평가."""
    universe = list(minute_by_code.keys())
    res = TrialResult(
        strategy_name=strategy_class.name if hasattr(strategy_class, "name") else strategy_class.__name__,
        trial_id=trial_id,
        params=params,
    )

    try:
        # train
        m_tr, d_tr = _slice_data_by_period(
            minute_by_code, daily_by_code, fold.train_start, fold.train_end
        )
        nonempty_tr = [c for c in universe if len(m_tr.get(c, pd.DataFrame())) > 0]
        if not nonempty_tr:
            res.error = "no train minute data"
            return res
        eng_tr = BacktestEngine(
            strategy=strategy_class(**params),
            initial_capital=initial_capital,
            universe=nonempty_tr,
            minute_df_by_code={c: m_tr[c] for c in nonempty_tr},
            daily_df_by_code={c: d_tr.get(c, pd.DataFrame()) for c in nonempty_tr},
        )
        res.train_metrics = eng_tr.run().metrics

        # test
        m_te, d_te = _slice_data_by_period(
            minute_by_code, daily_by_code, fold.test_start, fold.test_end
        )
        nonempty_te = [c for c in universe if len(m_te.get(c, pd.DataFrame())) > 0]
        if not nonempty_te:
            res.error = "no test minute data"
            return res
        eng_te = BacktestEngine(
            strategy=strategy_class(**params),
            initial_capital=initial_capital,
            universe=nonempty_te,
            minute_df_by_code={c: m_te[c] for c in nonempty_te},
            daily_df_by_code={c: d_te.get(c, pd.DataFrame()) for c in nonempty_te},
        )
        res.test_metrics = eng_te.run().metrics

        # 게이트
        # test_period 거래일 수 (대략) — fold dates 가 YYYYMMDD 라 차이로 추정 (월말 효과 무시)
        test_days = (
            int(fold.test_end[:6]) - int(fold.test_start[:6])
        ) * 21 + 21  # rough
        gate_eval = evaluate_gates(res.train_metrics, res.test_metrics, test_days)
        res.overfit_ratio = gate_eval["overfit_ratio"]
        res.monthly_trades = gate_eval["monthly_trades"]
        res.gates_passed = gate_eval["gates_passed"]
        res.gate_calmar_ok = gate_eval["gate_calmar_ok"]
        res.pass_stage1 = gate_eval["pass_stage1"]
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"

    return res


def run_stage1_for_strategy(
    strategy_class: Type[StrategyBase],
    fold: Fold,
    n_trials: int = 200,
    seed: int = 42,
    initial_capital: float = 100_000_000,
    minute_by_code: Optional[Dict[str, pd.DataFrame]] = None,
    daily_by_code: Optional[Dict[str, pd.DataFrame]] = None,
) -> List[TrialResult]:
    """전략 1개에 대해 n_trials 회 random search."""
    rng = random.Random(seed)
    results: List[TrialResult] = []

    if minute_by_code is None or daily_by_code is None:
        # 데이터를 한 번만 로드
        history_start = fold.daily_history_start
        all_codes = list(fold.universe)
        minute_df = load_minute_df(all_codes, fold.train_start, fold.test_end)
        daily_df = load_daily_df(all_codes, history_start, fold.test_end)
        minute_by_code = {
            c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
            for c in all_codes
        }
        daily_by_code = {
            c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
            for c in all_codes
        }

    inst = strategy_class()
    param_space = inst.param_space
    if not param_space:
        raise ValueError(f"{strategy_class.__name__} has empty param_space")

    for i in range(n_trials):
        params = sample_params(param_space, rng)
        res = run_one_trial(
            strategy_class, params, fold,
            minute_by_code, daily_by_code,
            initial_capital, trial_id=i,
        )
        results.append(res)
    return results


def save_trials(results: List[TrialResult], out_path: Path) -> None:
    """trials 결과를 CSV 로 저장."""
    if not results:
        return
    rows = [r.to_row() for r in results]
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)


def summarize_trials(results: List[TrialResult]) -> Dict[str, Any]:
    """전략 trials 요약 — 통과 trial 수, 최고 Calmar params."""
    if not results:
        return {"n_trials": 0, "n_pass": 0, "best": None}
    passing = [r for r in results if r.pass_stage1]
    valid = [r for r in results if not r.error and math.isfinite(r.test_metrics.get("calmar", float("nan")))]
    best = max(valid, key=lambda r: r.test_metrics.get("calmar", float("nan"))) if valid else None
    return {
        "n_trials": len(results),
        "n_pass": len(passing),
        "best_calmar": best.test_metrics.get("calmar", float("nan")) if best else float("nan"),
        "best_params": best.params if best else None,
        "best_test_return": best.test_metrics.get("total_return", float("nan")) if best else float("nan"),
        "best_test_trades": best.test_metrics.get("total_trades", 0) if best else 0,
    }
