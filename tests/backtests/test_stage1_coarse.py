"""Stage 1 coarse search 인프라 단위 테스트."""
import random

import pandas as pd
import pytest

from backtests.multiverse.fold import Fold, STAGE1_FOLD1, SMOKE_FOLD
from backtests.multiverse.stage1_coarse import (
    sample_params, evaluate_gates, run_one_trial, summarize_trials,
    GATE_OVERFIT_MIN, GATE_MDD_MAX, GATE_TRADES_MIN,
    GATE_WIN_RATE_MIN, GATE_MONTHLY_TRADES_MIN, STAGE1_CALMAR_FLOOR,
)
from backtests.strategies.volume_surge import VolumeSurgeStrategy


def test_fold_default_dates():
    assert STAGE1_FOLD1.train_start == "20250901"
    assert STAGE1_FOLD1.test_end == "20260424"
    assert STAGE1_FOLD1.daily_history_start == "20240901"


def test_sample_params_int_with_step():
    rng = random.Random(0)
    spec = {"a": {"type": "int", "low": 5, "high": 25, "step": 5}}
    for _ in range(20):
        s = sample_params(spec, rng)
        assert s["a"] in (5, 10, 15, 20, 25)


def test_sample_params_float_with_step():
    rng = random.Random(0)
    spec = {"b": {"type": "float", "low": -3.0, "high": -1.0, "step": 0.5}}
    for _ in range(20):
        s = sample_params(spec, rng)
        assert s["b"] in (-3.0, -2.5, -2.0, -1.5, -1.0)


def test_sample_volume_surge_param_space():
    rng = random.Random(42)
    s = VolumeSurgeStrategy()
    p = sample_params(s.param_space, rng)
    # 인스턴스화 가능
    inst = VolumeSurgeStrategy(**p)
    assert inst.vol_lookback_bars >= 5
    assert inst.volume_mult >= 2.0


def test_evaluate_gates_pass():
    train = {"calmar": 5.0, "mdd": -0.10, "total_trades": 50, "win_rate": 0.45}
    test = {"calmar": 4.0, "mdd": -0.10, "total_trades": 40, "win_rate": 0.45,
            "total_return": 0.05}
    out = evaluate_gates(train, test, test_period_days=42)
    assert out["overfit_ratio"] == pytest.approx(0.8)
    assert out["monthly_trades"] == pytest.approx(20.0, abs=0.1)
    assert out["gates_passed"] == 5
    assert out["gate_calmar_ok"] is True
    assert out["pass_stage1"] is True


def test_evaluate_gates_fail_calmar():
    train = {"calmar": 5.0, "mdd": -0.10, "total_trades": 50, "win_rate": 0.45}
    # test calmar 2.0 < 3.0 floor → 통과 못함
    test = {"calmar": 2.0, "mdd": -0.10, "total_trades": 40, "win_rate": 0.45}
    out = evaluate_gates(train, test, test_period_days=42)
    assert out["gate_calmar_ok"] is False
    assert out["pass_stage1"] is False


def test_evaluate_gates_fail_mdd():
    train = {"calmar": 5.0, "mdd": -0.10, "total_trades": 50, "win_rate": 0.45}
    # mdd 20% > 15%
    test = {"calmar": 4.0, "mdd": -0.20, "total_trades": 40, "win_rate": 0.45}
    out = evaluate_gates(train, test, test_period_days=42)
    assert out["gates"]["mdd"] is False
    # 4 게이트 통과 (3+ ok) 이지만 calmar floor 통과해도 mdd 실패는 별개로 카운트만 영향
    # 4/5 gates ≥ 3 + calmar OK → pass
    assert out["pass_stage1"] is True


def test_summarize_trials_empty():
    s = summarize_trials([])
    assert s == {"n_trials": 0, "n_pass": 0, "best": None}
