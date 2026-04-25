"""Stage 1 멀티프로세싱 래퍼 — N workers × trial 분산.

Pattern:
  - Initializer 가 minute/daily 데이터를 worker process global 로 로드 (1회)
  - 각 task = (strategy_class, params, trial_id) — 가벼운 인자
  - ProcessPoolExecutor.map 으로 분산

Windows 호환: initializer 함수 + 작업 함수가 모두 모듈 top-level 에 정의 (picklable).
"""
import random
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import Fold
from backtests.multiverse.stage1_coarse import (
    TrialResult, run_one_trial, sample_params,
)
from backtests.strategies.base import StrategyBase


# Worker process global state — initializer 가 채움
_WORKER_MINUTE: Optional[Dict[str, pd.DataFrame]] = None
_WORKER_DAILY: Optional[Dict[str, pd.DataFrame]] = None
_WORKER_FOLD: Optional[Fold] = None
_WORKER_INITIAL_CAPITAL: float = 100_000_000


def _worker_init(
    minute_by_code: Dict[str, pd.DataFrame],
    daily_by_code: Dict[str, pd.DataFrame],
    fold: Fold,
    initial_capital: float,
) -> None:
    """ProcessPoolExecutor initializer — 데이터를 worker global 에 캐시."""
    global _WORKER_MINUTE, _WORKER_DAILY, _WORKER_FOLD, _WORKER_INITIAL_CAPITAL
    _WORKER_MINUTE = minute_by_code
    _WORKER_DAILY = daily_by_code
    _WORKER_FOLD = fold
    _WORKER_INITIAL_CAPITAL = initial_capital


def _worker_run(args) -> TrialResult:
    """Worker task: run_one_trial 호출."""
    strategy_class, params, trial_id = args
    return run_one_trial(
        strategy_class=strategy_class,
        params=params,
        fold=_WORKER_FOLD,
        minute_by_code=_WORKER_MINUTE,
        daily_by_code=_WORKER_DAILY,
        initial_capital=_WORKER_INITIAL_CAPITAL,
        trial_id=trial_id,
    )


def run_stage1_parallel(
    strategy_class: Type[StrategyBase],
    fold: Fold,
    n_trials: int,
    n_workers: int = 4,
    seed: int = 42,
    initial_capital: float = 100_000_000,
    minute_by_code: Optional[Dict[str, pd.DataFrame]] = None,
    daily_by_code: Optional[Dict[str, pd.DataFrame]] = None,
    progress_every: int = 50,
) -> List[TrialResult]:
    """전략 1개에 대해 n_trials trials 를 N workers 로 병렬 실행.

    Args:
        n_workers: ProcessPool worker 수. 1 이면 sequential (디버깅용).
    """
    # 데이터 로드 (필요 시)
    if minute_by_code is None or daily_by_code is None:
        all_codes = list(fold.universe)
        if not all_codes:
            raise ValueError("fold.universe 비어있음 — universe 선정 필요")
        minute_df = load_minute_df(all_codes, fold.train_start, fold.test_end)
        daily_df = load_daily_df(
            all_codes, fold.daily_history_start, fold.test_end
        )
        minute_by_code = {
            c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
            for c in all_codes
        }
        daily_by_code = {
            c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
            for c in all_codes
        }

    # 모든 trial 의 params 를 미리 샘플 (재현 가능성)
    rng = random.Random(seed)
    inst = strategy_class()
    if not inst.param_space:
        raise ValueError(f"{strategy_class.__name__} 의 param_space 비어있음")
    tasks = [
        (strategy_class, sample_params(inst.param_space, rng), i)
        for i in range(n_trials)
    ]

    if n_workers <= 1:
        # Sequential fallback
        _worker_init(minute_by_code, daily_by_code, fold, initial_capital)
        results: List[TrialResult] = []
        t0 = time.perf_counter()
        for i, task in enumerate(tasks):
            results.append(_worker_run(task))
            if (i + 1) % progress_every == 0:
                el = time.perf_counter() - t0
                print(f"  [{strategy_class.name}] {i+1}/{n_trials} trials ({el:.0f}s)")
        return results

    # Parallel
    results = []
    t0 = time.perf_counter()
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_worker_init,
        initargs=(minute_by_code, daily_by_code, fold, initial_capital),
    ) as ex:
        for i, r in enumerate(ex.map(_worker_run, tasks, chunksize=1)):
            results.append(r)
            if (i + 1) % progress_every == 0:
                el = time.perf_counter() - t0
                print(f"  [{strategy_class.name}] {i+1}/{n_trials} trials ({el:.0f}s)")
    return results
