"""Fast engine 검증: slow engine (sim/engine.py) 과 동일 결과 확인 + 속도 측정.

실행:
    python -m analysis.research.weighted_score.tests.test_fast_engine_parity

절차:
1. 3종목 × 전체 기간 로드 + 피처
2. 동일 전략으로 slow vs fast 시뮬
3. 체결 거래수 / 총수익률 / Calmar 일치 확인 (허용 오차 내)
4. 속도 비교 출력
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import feature_store, pg_loader
from analysis.research.weighted_score.features import pipeline as feat_pipeline
from analysis.research.weighted_score.sim import cost_model, engine, fast_engine
from analysis.research.weighted_score.strategy.exit_rules import ExitPolicy
from analysis.research.weighted_score.strategy.weighted_score import WeightedScoreStrategy
from analysis.research.weighted_score.universe import universe_codes


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[ok]   {msg}")


def main() -> None:
    codes = universe_codes()[:3]
    print(f"대상 종목: {codes}")

    feat_by_code: dict[str, pd.DataFrame] = {}
    for code in codes:
        cached = feature_store.load_features(code)
        if cached is None or "close" not in cached.columns:
            # 캐시 없으면 계산
            df = pg_loader.load_minute_range(code, config.DATA_START, config.DATA_END)
            cached = feat_pipeline.compute_and_normalize(df, rolling_window=500, min_periods=50)
            feature_store.save_features(code, cached)
        feat_by_code[code] = cached

    # 짧은 기간 (30일) 으로 제한 — slow engine 비교용
    all_dates = pg_loader.list_trading_dates(config.DATA_START, config.DATA_END)
    sim_dates = all_dates[-30:]
    print(f"시뮬 기간: {sim_dates[0]} ~ {sim_dates[-1]} ({len(sim_dates)}일)")

    # 전략 (간단 — 두 피처, threshold 고정)
    strategy = WeightedScoreStrategy(
        weights={
            "pct_from_open": 1.0,
            "rsi_14": 0.5,
        },
        entry_threshold=0.85,
        exit_policy=ExitPolicy(
            stop_loss_pct=-3.0,
            take_profit_pct=5.0,
            max_holding_days=3,
            trail_pct=None,
            time_exit_bars=None,
            score_exit_threshold=None,
        ),
    )
    cost = cost_model.CostModel(one_way_pct=config.COST_ONE_WAY_PCT)

    # ---- slow engine ----
    t0 = time.time()
    slow_result = engine.simulate(
        strategy=strategy,
        stock_data=feat_by_code,
        dates=sim_dates,
        initial_capital=config.INITIAL_CAPITAL,
        size_krw=config.POSITION_SIZE_KRW,
        max_positions=3,
        cost_model=cost,
    )
    slow_elapsed = time.time() - t0
    print(f"\n[slow] elapsed {slow_elapsed:.2f}s  trades={len(slow_result.trades)}  "
          f"total_return={slow_result.metrics.total_return:+.4f}  "
          f"calmar={slow_result.metrics.calmar:.3f}")

    # ---- fast engine ----
    t0 = time.time()
    ctx = fast_engine.build_context(
        stock_data=feat_by_code,
        dates=sim_dates,
        feature_names=list(strategy.weights.keys()),
    )
    build_elapsed = time.time() - t0
    print(f"[fast] build_context elapsed {build_elapsed:.2f}s  "
          f"N={len(ctx.timeline_dates):,}  K={len(ctx.stock_codes)}")

    t0 = time.time()
    fast_result = fast_engine.simulate_fast(
        ctx=ctx,
        strategy=strategy,
        initial_capital=config.INITIAL_CAPITAL,
        size_krw=config.POSITION_SIZE_KRW,
        max_positions=3,
        cost_model=cost,
    )
    fast_elapsed = time.time() - t0
    print(f"[fast] simulate_fast elapsed {fast_elapsed:.2f}s  trades={fast_result.n_trades}  "
          f"total_return={fast_result.metrics.total_return:+.4f}  "
          f"calmar={fast_result.metrics.calmar:.3f}")

    # ---- 비교 ----
    # 목표: 메트릭(Calmar, total_return, MDD) 불변. 거래수는 시뮬 경계에서 last-bar 진입
    # 타이밍 차이로 ±5건 수준의 미세 차이 허용. 이는 Phase A/B 의 목적함수인 Calmar 가
    # 동일하게 계산되면 연구 관점에서 동등하다는 판단에 따른 것.
    print("\n=== 검증 ===")
    slow_set = set(
        (t["stock_code"], t["entry_date"], t["entry_idx"])
        for _, t in slow_result.trades.iterrows()
    )
    fast_set = set(
        (t["stock_code"], t["entry_date"], t["entry_idx"])
        for _, t in fast_result.trades.iterrows()
    )
    common = slow_set & fast_set
    only_slow = slow_set - fast_set
    only_fast = fast_set - slow_set
    print(f"  공통 거래: {len(common)}")
    print(f"  slow only: {len(only_slow)}  fast only: {len(only_fast)}")

    _assert(
        len(common) >= 0.9 * min(len(slow_set), len(fast_set)),
        f"공통 거래 비율 >= 90%",
    )

    # 공통 거래에 대한 net_pct 일치
    if common:
        slow_trades = slow_result.trades.set_index(["stock_code", "entry_date", "entry_idx"])
        fast_trades = fast_result.trades.set_index(["stock_code", "entry_date", "entry_idx"])
        max_diff = 0.0
        mismatch_reason = 0
        for key in sorted(common):
            s = slow_trades.loc[key]
            f = fast_trades.loc[key]
            s_pct = float(s["net_pct"]) if not hasattr(s["net_pct"], "values") else float(s["net_pct"].iloc[0])
            f_pct = float(f["net_pct"]) if not hasattr(f["net_pct"], "values") else float(f["net_pct"].iloc[0])
            max_diff = max(max_diff, abs(s_pct - f_pct))
            s_reason = s["exit_reason"] if isinstance(s["exit_reason"], str) else s["exit_reason"].iloc[0]
            f_reason = f["exit_reason"] if isinstance(f["exit_reason"], str) else f["exit_reason"].iloc[0]
            # EOS vs MAX_HOLD 는 경계 케이스에서 동등하게 취급
            if s_reason != f_reason and {s_reason, f_reason} != {"EOS", "MAX_HOLD"}:
                mismatch_reason += 1
        _assert(max_diff < 1e-4, f"공통 거래 net_pct max diff < 1e-4 (actual={max_diff:.2e})")
        _assert(
            mismatch_reason == 0,
            f"공통 거래 exit_reason 불일치 {mismatch_reason}건 (EOS↔MAX_HOLD 제외)",
        )

    # 메트릭 비교 — 엄격
    _assert(
        abs(slow_result.metrics.total_return - fast_result.metrics.total_return) < 1e-4,
        f"total_return 일치 (slow {slow_result.metrics.total_return:+.6f}  "
        f"fast {fast_result.metrics.total_return:+.6f})",
    )
    _assert(
        abs(slow_result.metrics.mdd - fast_result.metrics.mdd) < 1e-4,
        f"MDD 일치 (slow {slow_result.metrics.mdd:.6f}  fast {fast_result.metrics.mdd:.6f})",
    )
    _assert(
        abs(slow_result.metrics.calmar - fast_result.metrics.calmar) < 0.1,
        f"Calmar 일치 (slow {slow_result.metrics.calmar:.4f}  fast {fast_result.metrics.calmar:.4f})",
    )

    # 속도
    speedup = slow_elapsed / max(fast_elapsed, 1e-9)
    print(f"\n=== 속도 ===")
    print(f"  slow: {slow_elapsed:.3f}s")
    print(f"  fast: {fast_elapsed:.3f}s  (build 별도 {build_elapsed:.3f}s, context 재사용 가능)")
    print(f"  speedup: {speedup:.1f}x")

    print("\n[SUCCESS] fast engine parity 통과")


if __name__ == "__main__":
    main()
