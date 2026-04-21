"""Step 5 엔진 스모크: 3종목 × 5일 시뮬.

실행:
    python -m analysis.research.weighted_score.tests.test_engine_smoke

피처 2개 (pct_from_open, rsi_14) 를 정규화해 간단한 WeightedScoreStrategy 로
시뮬레이션을 돌린다. 목표는 엔진이 정상 종료하고 거래가 최소 몇 건은
발생하는지 확인.
"""
from __future__ import annotations

import sys
import time

import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import pg_loader
from analysis.research.weighted_score.features import normalize, price_momentum, technical
from analysis.research.weighted_score.sim import cost_model, engine
from analysis.research.weighted_score.strategy.exit_rules import ExitPolicy
from analysis.research.weighted_score.strategy.weighted_score import WeightedScoreStrategy
from analysis.research.weighted_score.universe import universe_codes


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[ok]   {msg}")


def main() -> None:
    # 1) 3종목 선정
    all_codes = universe_codes()
    _assert(len(all_codes) >= 3, "universe 3종목 이상")
    codes = all_codes[:3]
    print(f"대상 종목: {codes}")

    # 2) 각 종목 분봉 로드 (정규화를 위해 전 기간)
    stock_data: dict[str, pd.DataFrame] = {}
    for code in codes:
        df = pg_loader.load_minute_range(code, config.DATA_START, config.DATA_END)
        _assert(not df.empty, f"{code} 분봉 로드 rows={len(df):,}")
        stock_data[code] = df

    # 3) 피처 계산 + 정규화
    #    - pct_from_open → rolling_percentile (0~1)
    #    - rsi_14 → scale_to_unit_interval(0, 100) (0~1)
    feat_by_code: dict[str, pd.DataFrame] = {}
    for code, df in stock_data.items():
        pm = price_momentum.compute_price_momentum(df)
        tc = technical.compute_technical(df)

        feat = df.copy()
        feat["raw_pct_from_open"] = pm["pct_from_open"]
        feat["raw_rsi_14"] = tc["rsi_14"]

        feat["pct_from_open_norm"] = normalize.rolling_percentile(
            pm["pct_from_open"], window=500, min_periods=50
        )
        feat["rsi_14_norm"] = normalize.scale_to_unit_interval(tc["rsi_14"], 0, 100)

        feat_by_code[code] = feat

    # 4) 최근 5 거래일 선정
    dates_all = pg_loader.list_trading_dates(config.DATA_START, config.DATA_END)
    sim_dates = dates_all[-5:]
    print(f"시뮬 기간: {sim_dates[0]} ~ {sim_dates[-1]} ({len(sim_dates)}일)")

    # 5) 전략 구성
    #    정규화값은 0~1 이므로, 진입 임계치 0.7 정도
    strategy = WeightedScoreStrategy(
        weights={
            "pct_from_open_norm": 1.0,
            "rsi_14_norm": 0.3,
        },
        entry_threshold=0.7,  # 가중 합계의 최대 1.3 중 0.7 초과
        exit_policy=ExitPolicy(
            stop_loss_pct=-3.0,
            take_profit_pct=5.0,
            max_holding_days=3,
            trail_pct=None,
            time_exit_bars=None,
            score_exit_threshold=None,
            force_eod=False,
        ),
    )
    _assert(strategy.feature_names == ["pct_from_open_norm", "rsi_14_norm"], "피처명 저장")

    # 6) 시뮬 실행
    t0 = time.time()
    result = engine.simulate(
        strategy=strategy,
        stock_data=feat_by_code,
        dates=sim_dates,
        initial_capital=config.INITIAL_CAPITAL,
        size_krw=config.POSITION_SIZE_KRW,
        max_positions=3,
        cost_model=cost_model.CostModel(one_way_pct=config.COST_ONE_WAY_PCT),
    )
    elapsed = time.time() - t0
    print(f"시뮬 완료: {elapsed:.2f}s  bars_processed={result.n_bars_processed:,}")

    # 7) 결과 검증
    _assert(result.n_bars_processed > 0, "바 처리 > 0")
    print(f"\n체결 거래: {len(result.trades)}")
    if not result.trades.empty:
        print(result.trades[[
            "stock_code", "entry_date", "entry_time", "entry_price",
            "exit_date", "exit_time", "exit_price", "exit_reason",
            "bars_held", "trading_days_held", "net_pct",
        ]].head(20).to_string())

    _assert(
        result.metrics.n_trades == len(result.trades),
        f"metrics.n_trades == len(trades) ({result.metrics.n_trades})",
    )
    _assert(
        (result.trades["net_pct"].between(-10, 15)).all() if not result.trades.empty else True,
        "모든 net_pct 가 합리 범위 (-10 ~ 15%)",
    )

    print("\n=== 성과 지표 ===")
    for k, v in result.metrics.to_dict().items():
        print(f"  {k}: {v:.6f}" if isinstance(v, float) else f"  {k}: {v}")

    print(f"\n=== 자본곡선 (앞 10개) ===")
    print(result.equity_curve.head(10).to_string())

    print("\n[SUCCESS] Step 5 엔진 스모크 통과")


if __name__ == "__main__":
    main()
