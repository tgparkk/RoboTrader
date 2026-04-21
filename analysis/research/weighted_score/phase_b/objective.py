"""Optuna objective: trial → simulate → Calmar.

과적합 방지 가드:
- 최소 거래수 미달 시 -inf
- 극단값(MDD 0 근처) 시 Calmar 대신 total_return 으로 대체
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from analysis.research.weighted_score import config
from analysis.research.weighted_score.phase_b import search_space
from analysis.research.weighted_score.sim import fast_engine
from analysis.research.weighted_score.sim.cost_model import CostModel
from analysis.research.weighted_score.strategy.exit_rules import ExitPolicy
from analysis.research.weighted_score.strategy.weighted_score import WeightedScoreStrategy


MIN_TRADES_FOR_VALID_CALMAR = 50


def _compute_threshold_from_percentile(score_mat: np.ndarray, percentile: float) -> float:
    """score matrix 의 유효값 중 지정 percentile 을 threshold 로 반환."""
    valid = score_mat[~np.isnan(score_mat)]
    if valid.size == 0:
        return float("inf")
    return float(np.percentile(valid, percentile))


def build_strategy_from_params(params: dict, score_threshold: float) -> WeightedScoreStrategy:
    policy = ExitPolicy(
        stop_loss_pct=params["stop_loss_pct"],
        take_profit_pct=params["take_profit_pct"],
        max_holding_days=params["max_holding_days"],
        trail_pct=None,            # v1: 미지원
        time_exit_bars=params["time_exit_bars"],
        score_exit_threshold=None, # v1: 미지원
    )
    return WeightedScoreStrategy(
        weights=params["weights"],
        entry_threshold=score_threshold,
        exit_policy=policy,
    )


def simulate_trial(
    params: dict,
    ctx: fast_engine.SimContext,
    cost_model: CostModel,
    initial_capital: float,
    size_krw: float,
) -> fast_engine.FastSimResult:
    """한 trial 의 파라미터로 시뮬 실행."""
    score_mat = fast_engine.compute_score_matrix(ctx, params["weights"])
    threshold = _compute_threshold_from_percentile(score_mat, params["entry_pct"])
    strategy = build_strategy_from_params(params, threshold)
    return fast_engine.simulate_fast(
        ctx=ctx,
        strategy=strategy,
        initial_capital=initial_capital,
        size_krw=size_krw,
        max_positions=params["max_positions"],
        cost_model=cost_model,
    )


def make_objective(
    space: search_space.SearchSpaceConfig,
    train_ctx: fast_engine.SimContext,
    cost_model: CostModel,
    initial_capital: float = config.INITIAL_CAPITAL,
    size_krw: float = config.POSITION_SIZE_KRW,
    min_trades: int = MIN_TRADES_FOR_VALID_CALMAR,
):
    """Optuna study.optimize 에 전달할 objective 함수 반환."""

    def _objective(trial) -> float:
        params = search_space.sample_params(trial, space)
        try:
            result = simulate_trial(
                params=params,
                ctx=train_ctx,
                cost_model=cost_model,
                initial_capital=initial_capital,
                size_krw=size_krw,
            )
        except Exception as e:
            # 수치 문제로 실패 시 최악 점수
            return -1e9

        m = result.metrics
        trial.set_user_attr("n_trades", int(m.n_trades))
        trial.set_user_attr("total_return", float(m.total_return))
        trial.set_user_attr("mdd", float(m.mdd))
        trial.set_user_attr("sharpe", float(m.sharpe))
        trial.set_user_attr("win_rate", float(m.win_rate))
        trial.set_user_attr("annualized_return", float(m.annualized_return))

        if m.n_trades < min_trades:
            return -1e9

        if m.mdd < 1e-6:
            # MDD ~0 → Calmar 불안정. 대체로 짧은 기간 매우 드문 승리만 있는 경우.
            return float(m.total_return)

        return float(m.calmar)

    return _objective
