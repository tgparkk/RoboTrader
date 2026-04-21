"""Phase A 청산 파라미터 그리드 서치.

주어진 피처 가중치(logreg) 를 고정하고, 청산 규칙 및 동시보유 등
소규모 그리드를 돌려 train 구간 Calmar 상위 조합을 찾는다.

출력: GridResult 리스트 (train 지표 포함). Phase B 시드로 사용.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from analysis.research.weighted_score.sim import fast_engine, metrics as mtr
from analysis.research.weighted_score.sim.cost_model import CostModel
from analysis.research.weighted_score.strategy.exit_rules import ExitPolicy
from analysis.research.weighted_score.strategy.weighted_score import WeightedScoreStrategy


@dataclass
class ExitGridConfig:
    entry_thresholds: list[float]
    stop_loss_pcts: list[float]           # 음수
    take_profit_pcts: list[float]         # 양수
    max_positions_list: list[int]
    max_holding_days_list: list[int]
    trail_pcts: list[Optional[float]] = field(default_factory=lambda: [None])
    time_exit_bars_list: list[Optional[int]] = field(default_factory=lambda: [None])
    score_exit_thresholds: list[Optional[float]] = field(default_factory=lambda: [None])

    def iter_combos(self):
        for et, sl, tp, mp, mhd, tr, tbx, sex in itertools.product(
            self.entry_thresholds,
            self.stop_loss_pcts,
            self.take_profit_pcts,
            self.max_positions_list,
            self.max_holding_days_list,
            self.trail_pcts,
            self.time_exit_bars_list,
            self.score_exit_thresholds,
        ):
            yield dict(
                entry_threshold=et,
                stop_loss_pct=sl,
                take_profit_pct=tp,
                max_positions=mp,
                max_holding_days=mhd,
                trail_pct=tr,
                time_exit_bars=tbx,
                score_exit_threshold=sex,
            )

    def n_combos(self) -> int:
        return (
            len(self.entry_thresholds)
            * len(self.stop_loss_pcts)
            * len(self.take_profit_pcts)
            * len(self.max_positions_list)
            * len(self.max_holding_days_list)
            * len(self.trail_pcts)
            * len(self.time_exit_bars_list)
            * len(self.score_exit_thresholds)
        )


@dataclass
class GridResult:
    params: dict
    train_metrics: mtr.PerfMetrics
    test_metrics: Optional[mtr.PerfMetrics]
    elapsed_sec: float

    def to_row(self) -> dict:
        row = dict(self.params)
        for k, v in self.train_metrics.to_dict().items():
            row[f"train_{k}"] = v
        if self.test_metrics is not None:
            for k, v in self.test_metrics.to_dict().items():
                row[f"test_{k}"] = v
        row["elapsed_sec"] = self.elapsed_sec
        return row


def _simulate_combo(
    weights: dict[str, float],
    ctx: fast_engine.SimContext,
    params: dict,
    initial_capital: float,
    size_krw: float,
    cost_model: CostModel,
) -> mtr.PerfMetrics:
    policy = ExitPolicy(
        stop_loss_pct=params["stop_loss_pct"],
        take_profit_pct=params["take_profit_pct"],
        max_holding_days=params["max_holding_days"],
        trail_pct=params["trail_pct"],
        time_exit_bars=params["time_exit_bars"],
        score_exit_threshold=params["score_exit_threshold"],
    )
    strategy = WeightedScoreStrategy(
        weights=weights,
        entry_threshold=params["entry_threshold"],
        exit_policy=policy,
    )
    result = fast_engine.simulate_fast(
        ctx=ctx,
        strategy=strategy,
        initial_capital=initial_capital,
        size_krw=size_krw,
        max_positions=params["max_positions"],
        cost_model=cost_model,
    )
    return result.metrics


def run_exit_grid(
    weights: dict[str, float],
    feat_by_code: dict[str, pd.DataFrame],
    train_dates: list[str],
    grid: ExitGridConfig,
    initial_capital: float,
    size_krw: float,
    cost_model: CostModel,
    test_dates: Optional[list[str]] = None,
    top_k_for_test: int = 5,
    progress_every: int = 10,
) -> list[GridResult]:
    """Train 구간에서 모든 combo 시뮬 → Calmar 상위 top_k_for_test 만 test 재시뮬.

    Fast engine 사용: SimContext 를 train/test 각각 1회 빌드해 재사용.
    """
    combos = list(grid.iter_combos())
    n_combos = len(combos)
    print(f"[exit_grid] train combos: {n_combos}")

    # Context 1회 빌드
    feature_names = list(weights.keys())
    t_build = time.time()
    train_ctx = fast_engine.build_context(feat_by_code, train_dates, feature_names)
    print(f"[exit_grid] train ctx built {time.time() - t_build:.2f}s  "
          f"N={len(train_ctx.timeline_dates):,}  K={len(train_ctx.stock_codes)}")

    test_ctx: Optional[fast_engine.SimContext] = None
    if test_dates:
        t_build = time.time()
        test_ctx = fast_engine.build_context(feat_by_code, test_dates, feature_names)
        print(f"[exit_grid] test ctx built {time.time() - t_build:.2f}s  "
              f"N={len(test_ctx.timeline_dates):,}")

    results: list[GridResult] = []
    t_start = time.time()

    for i, params in enumerate(combos, 1):
        t0 = time.time()
        try:
            train_m = _simulate_combo(
                weights, train_ctx, params,
                initial_capital, size_krw, cost_model,
            )
        except Exception as e:
            print(f"[exit_grid] combo {i} failed: {e}")
            continue
        elapsed = time.time() - t0
        results.append(GridResult(params=params, train_metrics=train_m, test_metrics=None, elapsed_sec=elapsed))

        if progress_every and i % progress_every == 0:
            total_elapsed = time.time() - t_start
            rate = i / max(total_elapsed, 1e-9)
            eta = (n_combos - i) / rate if rate > 0 else 0.0
            best_so_far = max((r.train_metrics.calmar for r in results), default=0.0)
            print(
                f"[exit_grid] {i}/{n_combos}  elapsed {total_elapsed:.1f}s  "
                f"rate {rate:.2f}/s  ETA {eta:.0f}s  best_calmar={best_so_far:.3f}"
            )

    # 상위 K 에 대해 test 시뮬
    if test_ctx is not None and results:
        results.sort(key=lambda r: r.train_metrics.calmar, reverse=True)
        top = results[:top_k_for_test]
        for r in top:
            try:
                t0 = time.time()
                r.test_metrics = _simulate_combo(
                    weights, test_ctx, r.params,
                    initial_capital, size_krw, cost_model,
                )
                r.elapsed_sec += time.time() - t0
            except Exception as e:
                print(f"[exit_grid] test sim failed for params={r.params}: {e}")

    return results


def rank_results(results: list[GridResult]) -> pd.DataFrame:
    """GridResult 리스트 → 정렬된 DataFrame (train calmar 내림차순)."""
    rows = [r.to_row() for r in results]
    df = pd.DataFrame(rows)
    if "train_calmar" in df.columns:
        df = df.sort_values("train_calmar", ascending=False).reset_index(drop=True)
    return df
