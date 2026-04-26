"""Trial 837 재현 스모크 검증.

DB 접속 필요. 3종목 × 60일 단축 스모크 (full 재현이 아닌 engine 동작 확인 용도).
Trial 837 original: universe_size=200, test Calmar ≈ 25.10 — 우리 3종목은 정확 매칭
불가. 본 테스트의 목적은 adapter 가 engine 에서 end-to-end 실행되는지 확인.
"""
import pandas as pd
import psycopg2
import pytest

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from backtests.common.engine import BacktestEngine
from backtests.common.data_loader import load_minute_df, load_daily_df, load_index_df
from backtests.strategies.weighted_score_full import WeightedScoreFull


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
def test_trial837_smoke_3stocks_60days():
    """3종목 × 60일 단축 스모크. engine end-to-end 에러 없이 완주."""
    universe = ["005930", "000660", "035720"]  # 삼성전자, SK하이닉스, 카카오
    start = "20251001"  # 3개월 구간 (Trial 837 train 후반부)
    end = "20251215"

    minute_df = load_minute_df(codes=universe, start_date=start, end_date=end)
    if minute_df.empty:
        pytest.skip(f"분봉 데이터 없음: {start}~{end}")

    daily_df = load_daily_df(
        codes=universe, start_date="20250101", end_date=end
    )
    kospi_df = load_index_df(index_code="KS11", start_date="20250101", end_date=end)
    kosdaq_df = load_index_df(index_code="KQ11", start_date="20250101", end_date=end)

    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    nonempty = [c for c in universe if len(minute_by_code[c]) > 0]
    if not nonempty:
        pytest.skip("모든 종목에 분봉 없음")

    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }

    # 어댑터에 지수 DF 를 주입 (엔진은 prepare_features(df_minute, df_daily) 만 호출)
    strategy = WeightedScoreFull()
    original = strategy.prepare_features

    def prepare_with_indexes(df_minute, df_daily):
        return original(df_minute, df_daily, df_kospi=kospi_df, df_kosdaq=kosdaq_df)

    strategy.prepare_features = prepare_with_indexes

    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=10_000_000,
        universe=nonempty,
        minute_df_by_code={c: minute_by_code[c] for c in nonempty},
        daily_df_by_code={c: daily_by_code[c] for c in nonempty},
    )
    result = engine.run()

    # 스모크: engine 이 에러 없이 완주
    assert result.final_equity > 0, "final_equity 가 0 이하"
    assert "calmar" in result.metrics
    assert "mdd" in result.metrics
    assert "sharpe" in result.metrics

    # 결과 기록 (pytest -s 로 stdout 확인)
    print(
        f"\n[Trial 837 스모크] universe={nonempty} "
        f"period={start}~{end} "
        f"trades={result.metrics['total_trades']} "
        f"return={result.metrics['total_return']:.2%} "
        f"mdd={result.metrics['mdd']:.2%} "
        f"calmar={result.metrics.get('calmar', float('nan')):.2f} "
        f"sharpe={result.metrics.get('sharpe', float('nan')):.2f}"
    )
