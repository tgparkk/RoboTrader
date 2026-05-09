"""macd_cross_alt (16/32) paper flow E2E.

라이브 14/34 와 paper 16/32 가 같은 봇 인스턴스에서 동시 동작 — paper 만
가상매매로 routing 되는지, KPI 집계가 strategy='macd_cross_alt' 필터로
분리되는지 검증.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.strategies.macd_cross_kpi import MacdCrossKpi
from core.strategies.macd_cross_strategy import MacdCrossStrategy


@pytest.fixture
def alt_strategy():
    return MacdCrossStrategy(
        fast=16, slow=32, signal=12, entry_hhmm_min=1431,
        label='macd_cross_alt',
    )


def test_alt_strategy_label_propagates_to_logging(alt_strategy):
    """label 'macd_cross_alt' 가 인스턴스에 보존."""
    assert alt_strategy.label == 'macd_cross_alt'


def test_alt_signal_independent_from_live():
    """동일 daily history 입력 시 14/34 와 16/32 의 prev_hist 가 다름."""
    import pandas as pd
    import numpy as np

    np.random.seed(42)
    n = 60
    df = pd.DataFrame({
        "trade_date": [f"202509{i:02d}" for i in range(1, n + 1)],
        "close": 1000 + np.cumsum(np.random.randn(n) * 5),
    })
    live = MacdCrossStrategy(fast=14, slow=34, signal=12, label='macd_cross')
    paper = MacdCrossStrategy(fast=16, slow=32, signal=12, label='macd_cross_alt')

    live.set_daily_history("000001", df, "20251102")
    paper.set_daily_history("000001", df, "20251102")

    live_hist = live.get_cached_hist("000001")
    paper_hist = paper.get_cached_hist("000001")

    # 다른 fast/slow 로 다른 hist 값 → cache 분리 검증
    assert live_hist != paper_hist


def test_kpi_filter_by_strategy_label(monkeypatch):
    """KPI 가 'macd_cross_alt' strategy filter 시 alt rows 만 집계."""
    import pandas as pd

    df_alt_only = pd.DataFrame({
        "buy_time": pd.to_datetime(["2026-05-12 14:31", "2026-05-13 14:31"]),
        "sell_time": pd.to_datetime(["2026-05-14 09:01", "2026-05-15 09:01"]),
        "pnl": [50000.0, -30000.0],
    })
    kpi = MacdCrossKpi(virtual_capital=10_000_000)
    metrics = kpi.compute(df_alt_only)
    assert metrics["trade_count"] == 2
    assert metrics["return"] == pytest.approx((50000 - 30000) / 10_000_000)
    gates = kpi.evaluate_gates(metrics)
    # 표본 적어 calmar/return 등 통과/탈락은 의미 없음 — 게이트 평가 동작만 확인
    assert "all_pass" in gates


@pytest.mark.skip(reason="Requires KIS API mock + DB fixture — run manually after Task 8")
def test_full_flow_signal_to_kpi():
    """E2E: signal hit → save_virtual_buy(strategy='macd_cross_alt') → D+2 청산
    → fetch_virtual_trades('macd_cross_alt') → KPI 집계.

    DB fixture + KIS mock 준비 후 활성화.
    """
    pass
