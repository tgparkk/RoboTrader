"""weighted_score Trial 837 엔진 통합 스모크 테스트.

DB 접속 필요. 목적: 엔진이 실제 데이터로 end-to-end 실행 (거래 생성 or
스킵) 되면서 에러 없이 완주하는지.
"""
import pandas as pd
import psycopg2
import pytest

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from backtests.common.engine import BacktestEngine
from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.strategies.weighted_score_baseline import WeightedScoreBaseline


def _db_available() -> bool:
    try:
        c = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD, connect_timeout=2,
        )
        c.close()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="DB 접속 불가")


@requires_db
def test_baseline_smoke_runs_end_to_end():
    """2개월 샘플 구간에서 엔진 end-to-end 실행."""
    universe = ["005930", "000660", "035720"]  # 삼성전자, SK하이닉스, 카카오
    start = "20260101"
    end = "20260228"

    minute_df = load_minute_df(codes=universe, start_date=start, end_date=end)
    daily_df = load_daily_df(
        codes=universe, start_date="20250101", end_date=end
    )

    if minute_df.empty:
        pytest.skip(f"분봉 데이터 없음: {start}~{end}")

    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    # 각 종목에 분봉이 있는지 확인
    nonempty_universe = [c for c in universe if len(minute_by_code[c]) > 0]
    if not nonempty_universe:
        pytest.skip("모든 종목에 분봉 없음")

    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }

    engine = BacktestEngine(
        strategy=WeightedScoreBaseline(),
        initial_capital=10_000_000,
        universe=nonempty_universe,
        minute_df_by_code={c: minute_by_code[c] for c in nonempty_universe},
        daily_df_by_code={c: daily_by_code[c] for c in nonempty_universe},
    )
    result = engine.run()

    # 엔진 정상동작 최소 조건
    assert result.final_equity > 0
    assert "calmar" in result.metrics
    assert "mdd" in result.metrics
    assert "total_trades" in result.metrics

    # 관찰값 출력 (pytest -s 로 봄)
    print(
        f"\n[baseline smoke] universe={nonempty_universe} "
        f"trades={result.metrics['total_trades']} "
        f"return={result.metrics['total_return']:.2%} "
        f"mdd={result.metrics['mdd']:.2%} "
        f"final={result.final_equity:,.0f}"
    )
