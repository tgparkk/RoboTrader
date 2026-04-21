"""통합 Phase 3 스모크: daily_prep → strategy score 계산 검증.

실행:
    python -m analysis.research.weighted_score.tests.test_integration_smoke

절차:
1. WeightedScoreStrategy 초기화
2. minute_loader wrapper (analysis.research.pg_loader 사용 — 실거래 utils.data_cache 대체)
3. 1~2 종목에 대해 prepare_for_trade_date 호출
4. 특정 분봉 시점에 check_advanced_conditions 호출 → score 반환 확인
5. 연구 단계와 동일 로직인지 sanity 체크
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import psycopg2

from analysis.research.weighted_score.data import pg_loader
from analysis.research.weighted_score.universe import universe_codes
from config.settings import PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER
from core.strategies.weighted_score_daily_prep import prepare_for_trade_date
from core.strategies.weighted_score_strategy import WeightedScoreStrategy


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[ok]   {msg}")


def _make_minute_loader():
    """minute_loader: (stock_code, date_YYYYMMDD) → 분봉 DF or None."""
    def _loader(code: str, date: str):
        df = pg_loader.load_minute_day(code, date)
        return df
    return _loader


def main() -> None:
    t0 = time.time()

    strategy = WeightedScoreStrategy()
    print(f"strategy init OK: threshold={strategy.params.threshold_abs:+.4f}")

    codes = universe_codes()[:2]
    print(f"대상: {codes}")

    loader = _make_minute_loader()

    target_date = "20260416"  # test 기간 내 임의 거래일

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    try:
        summary = prepare_for_trade_date(
            strategy=strategy,
            stock_codes=codes,
            target_date=target_date,
            minute_loader=loader,
            pg_conn=conn,
            logger=None,
        )
    finally:
        conn.close()

    print(f"\nprep summary: {summary}")
    _assert(summary["loaded"] >= 1, f"prep loaded >= 1 (actual={summary['loaded']})")
    _assert(strategy.has_daily_features(codes[0]), f"{codes[0]} daily 피처 주입됨")

    # daily raw 확인
    daily = strategy.daily_raw_by_code[codes[0]]
    print(f"\ndaily raw features for {codes[0]}:")
    for k, v in daily.items():
        print(f"  {k}: {v}")

    # past volume map
    pv = strategy.past_volume_by_code.get(codes[0], {})
    print(f"past_volume_by_idx entries: {len(pv)}")

    # 분봉 하나 로드해서 score 확인
    bars = pg_loader.load_minute_day(codes[0], target_date)
    if bars is not None and len(bars) >= 50:
        bars["trade_date"] = target_date
        # 분봉 시점별 score 테스트 (09:30, 10:00, 12:00, 13:00)
        test_idxes = [30, 60, 180, 240]
        for ti in test_idxes:
            if ti >= len(bars):
                continue
            score = strategy.get_score(codes[0], bars, ti)
            t_s = str(bars.iloc[ti]["time"])
            print(f"  {codes[0]} {target_date} idx={ti} time={t_s} score={score}")

    # check_advanced_conditions (entry 판단)
    if bars is not None and len(bars) >= 50:
        bars["trade_date"] = target_date
        ok, reason = strategy.check_advanced_conditions(
            df=bars, candle_idx=min(60, len(bars) - 1), stock_code=codes[0]
        )
        print(f"\ncheck_advanced_conditions: ok={ok}  reason={reason}")

    print(f"\n[SUCCESS] Phase 3 통합 스모크 완료 (elapsed {time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
