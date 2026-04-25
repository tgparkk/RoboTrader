"""Stage 2 Optuna 멀티프로세싱 — sqlite 기반 공유 study + N workers.

Pattern:
  - 메인: 공유 sqlite study 생성 + 데이터를 임시 pickle 로 dump
  - 각 worker: pickle 에서 데이터 로드 + sqlite study 에 join + study.optimize(local_n_trials)
  - SQLite 가 concurrent trial 추가 처리 (WAL 모드)
  - 시계열 순서 / look-ahead 무관: 각 worker 의 백테스트는 자기 trial 안에서 시간 순서대로 진행

TPE 의 sequential learning 효율은 약간 둔화 (동시 실행 trial 들은 같은 prior 사용)
하지만 결과 정확성은 영향 없음.
"""
import os
import pickle
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Type

import optuna
import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import Fold, STAGE2_FOLDS, stage2_data_range
from backtests.multiverse.stage2_fine import (
    make_objective, save_study_results,
)
from backtests.multiverse.universe import select_top_universe
from backtests.strategies.base import StrategyBase


optuna.logging.set_verbosity(optuna.logging.WARNING)


def _worker_run_optuna(args) -> int:
    """Worker process: pickle 로드 → study 로드 → optimize.

    Returns: 처리한 trial 수.
    """
    (
        pickle_path, storage_url, study_name, strategy_class, folds,
        n_trials_local, initial_capital, seed_offset,
    ) = args
    # 데이터 로드
    with open(pickle_path, "rb") as f:
        data = pickle.load(f)
    minute_by_code = data["minute"]
    daily_by_code = data["daily"]

    # Study 로드 (이미 메인이 만들어둠)
    study = optuna.load_study(study_name=study_name, storage=storage_url)

    # Objective 빌드 (worker 마다 매번 — closure 방식)
    objective = make_objective(
        strategy_class=strategy_class,
        folds=folds,
        minute_by_code=minute_by_code,
        daily_by_code=daily_by_code,
        initial_capital=initial_capital,
    )

    study.optimize(objective, n_trials=n_trials_local, show_progress_bar=False)
    return n_trials_local


def run_stage2_parallel(
    strategy_class: Type[StrategyBase],
    n_trials: int = 1000,
    n_workers: int = 4,
    seed: int = 42,
    initial_capital: float = 100_000_000,
    folds: List[Fold] = STAGE2_FOLDS,
    minute_by_code: Optional[Dict] = None,
    daily_by_code: Optional[Dict] = None,
    universe: Optional[List[str]] = None,
    storage_dir: Path = Path("backtests/reports/stage2"),
    progress_every: int = 50,
):
    """전략 1개에 대해 N workers 가 sqlite study 공유로 Optuna TPE 분산 실행."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    name = strategy_class.name

    # 데이터 로드
    if minute_by_code is None or daily_by_code is None:
        if universe is None:
            raise ValueError("universe 또는 minute_by_code 필요")
        d_start, d_end = stage2_data_range()
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

    # 데이터 → 임시 pickle (Windows pipe 우회, Stage 1 패턴 동일)
    pickle_fd, pickle_path = tempfile.mkstemp(suffix=".pkl", prefix=f"stage2_{name}_")
    os.close(pickle_fd)
    with open(pickle_path, "wb") as f:
        pickle.dump({"minute": minute_by_code, "daily": daily_by_code}, f,
                    protocol=pickle.HIGHEST_PROTOCOL)

    storage_url = f"sqlite:///{storage_dir}/{name}.db"
    study_name = f"stage2_{name}"

    try:
        # 메인이 study 생성 (worker 들이 join)
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=seed),
            storage=storage_url,
            load_if_exists=True,
            study_name=study_name,
        )

        n_done = len(study.trials)
        if n_done >= n_trials:
            print(f"[{name}] {n_done}/{n_trials} 이미 완료")
            save_study_results(study, storage_dir, name)
            return study

        remaining = n_trials - n_done
        per_worker = remaining // n_workers
        extra = remaining % n_workers
        worker_loads = [per_worker + (1 if i < extra else 0)
                        for i in range(n_workers)]

        print(f"[{name}] {remaining} trials 남음 → "
              f"{n_workers} workers × {worker_loads}")

        tasks = [
            (pickle_path, storage_url, study_name, strategy_class, folds,
             load, initial_capital, i)
            for i, load in enumerate(worker_loads)
        ]

        t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            for i, n_done_local in enumerate(ex.map(_worker_run_optuna, tasks)):
                el = time.perf_counter() - t0
                print(f"  [{name}] worker {i+1}/{n_workers} 완료 "
                      f"({n_done_local} trials, total elapsed {el:.0f}s)")

        # 결과 fetch
        study = optuna.load_study(study_name=study_name, storage=storage_url)
        save_study_results(study, storage_dir, name)
        return study
    finally:
        try:
            os.remove(pickle_path)
        except OSError:
            pass
