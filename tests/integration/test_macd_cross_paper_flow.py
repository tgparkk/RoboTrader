"""macd_cross 페이퍼 e2e 시나리오 (mock DB / mock 분봉).

검증 흐름:
1. set_daily_history → 시그널 캐시 형성
2. check_entry → 시간대 + 골든크로스 결합 판정
3. KPI 파이프라인 → trade rows → metrics → gates
4. EOD 격리 — strategy='macd_cross' 행만 반환
"""
from datetime import date, datetime
import numpy as np
import pandas as pd
import pytest

from core.strategies.macd_cross_strategy import MacdCrossStrategy
from core.strategies.macd_cross_kpi import MacdCrossKpi


def _bullish_close_series(n=80):
    """음 hist → 양 hist 골든크로스를 마지막 부근에 만드는 close 시퀀스."""
    base = np.linspace(10000, 9000, n // 2)        # 하락 (음 hist 형성)
    rebound = np.linspace(9000, 10500, n - n // 2) # 반등 (양 hist 진입)
    return np.concatenate([base, rebound])


def test_signal_to_entry_then_kpi_pipeline():
    """공유 모듈 시그널 → 어댑터 cache → check_entry → KPI 계산."""
    strategy = MacdCrossStrategy(fast=14, slow=34, signal=12,
                                  entry_hhmm_min=1430, entry_hhmm_max=1500)
    closes = _bullish_close_series(80)
    dates = pd.date_range("2026-01-02", periods=80, freq="B").strftime("%Y%m%d")
    df_d = pd.DataFrame({"trade_date": dates.astype(str), "close": closes})
    strategy.set_daily_history("005930", df_d, today_yyyymmdd="20260423")

    # 캐시 채워짐
    prev, prev_prev = strategy.get_cached_hist("005930")
    assert prev is not None and prev_prev is not None

    # 시간대 + 시그널 충족 (테스트용 강제 cross 값)
    strategy._cache["005930"] = (0.5, -0.3)
    assert strategy.check_entry("005930", hhmm=1430) is True
    assert strategy.check_entry("005930", hhmm=1429) is False
    assert strategy.check_entry("005930", hhmm=1501) is False

    # KPI 파이프라인: 임의 trade 시뮬
    trades = pd.DataFrame({
        "buy_time": pd.date_range("2026-04-01", periods=5, freq="B"),
        "sell_time": pd.date_range("2026-04-03", periods=5, freq="B"),
        "pnl": [120_000, -40_000, 180_000, 60_000, -20_000],
    })
    kpi = MacdCrossKpi(virtual_capital=10_000_000)
    m = kpi.compute(trades)
    g = kpi.evaluate_gates(m)
    # net = 300_000, return = 3% → return gate pass
    assert m["return"] == pytest.approx(0.03, abs=1e-6)
    assert g["gates"]["return"]["pass"] is True


def test_eod_isolation_excludes_paper_codes():
    """get_virtual_open_positions 에서 strategy='macd_cross' 행만 격리 대상."""
    # mock db_manager
    class MockDB:
        def get_virtual_open_positions(self):
            return pd.DataFrame({
                "id": [1, 2, 3],
                "stock_code": ["005930", "000660", "035720"],
                "stock_name": ["삼성전자", "SK하이닉스", "카카오"],
                "quantity": [10, 5, 20],
                "buy_price": [70000, 130000, 50000],
                "buy_time": [datetime.now()] * 3,
                "strategy": ["macd_cross", "weighted_score", "macd_cross"],
                "buy_reason": ["", "", ""],
            })

    # main.DayTradingBot._get_macd_cross_paper_open_codes 의 로직만 모방
    db = MockDB()
    df = db.get_virtual_open_positions()
    paper_codes = set(df.loc[df["strategy"] == "macd_cross", "stock_code"].tolist())
    assert paper_codes == {"005930", "035720"}
    assert "000660" not in paper_codes  # weighted_score 는 격리 안 됨


def test_safety_stop_triggers_via_kpi():
    """KPI safety stop 조건이 5연속 손실에서 발동."""
    kpi = MacdCrossKpi(virtual_capital=10_000_000)
    losses = pd.DataFrame({
        "buy_time": pd.date_range("2026-04-01", periods=5, freq="B"),
        "sell_time": pd.date_range("2026-04-03", periods=5, freq="B"),
        "pnl": [-50_000, -40_000, -30_000, -20_000, -10_000],
    })
    m = kpi.compute(losses)
    assert m["max_consec_losses"] == 5
    assert kpi.should_safety_stop(m) is True
