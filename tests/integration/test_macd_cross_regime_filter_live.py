"""macd_cross KOSDAQ 레짐필터 라이브 배선 검증 (2026-06-04).

1. _macd_cross_kosdaq_regime_blocks 임계 분기 (mock 기반)
2. _get_kosdaq_trailing_return 신호식이 백테스트 정의와 일치 (실 DB 기반)
   — 백테스트: ret5 = close[D-1]/close[D-6] - 1 (shift1, lookahead 0)
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from config.strategy_settings import StrategySettings


class _FakeBot:
    def __init__(self):
        self.logger = MagicMock()
        self.pre_market_analyzer = MagicMock()


def _bind(bot, *names):
    from main import DayTradingBot
    for n in names:
        setattr(bot, n, DayTradingBot.__dict__[n].__get__(bot, _FakeBot))


def _make_bot(trailing_ret):
    bot = _FakeBot()
    _bind(bot, '_macd_cross_kosdaq_regime_blocks')
    bot.pre_market_analyzer._get_kosdaq_trailing_return.return_value = trailing_ret
    return bot


NOW = datetime(2026, 6, 4, 14, 31)


def test_regime_blocks_when_below_threshold():
    """KOSDAQ 5일 -2.5% (<= -2.0%) → 차단."""
    bot = _make_bot(-2.5)
    assert bot._macd_cross_kosdaq_regime_blocks(NOW) is True


def test_regime_at_exact_threshold_blocks():
    """정확히 -2.0% → 차단 (<= 경계 포함, 백테스트 cond 와 동일)."""
    bot = _make_bot(-2.0)
    assert bot._macd_cross_kosdaq_regime_blocks(NOW) is True


def test_regime_no_block_above_threshold():
    """KOSDAQ 5일 -1.5% (> -2.0%) → 차단 안 함."""
    bot = _make_bot(-1.5)
    assert bot._macd_cross_kosdaq_regime_blocks(NOW) is False


def test_regime_no_block_when_data_missing():
    """데이터 없음(None) → 보수적으로 차단 안 함."""
    bot = _make_bot(None)
    assert bot._macd_cross_kosdaq_regime_blocks(NOW) is False


def test_regime_disabled_flag(monkeypatch):
    """KOSDAQ_REGIME_FILTER_ENABLED=False → 항상 차단 안 함 (DB 조회도 안 함)."""
    monkeypatch.setattr(StrategySettings.MacdCross, 'KOSDAQ_REGIME_FILTER_ENABLED', False)
    bot = _make_bot(-9.0)  # 임계 한참 아래여도
    assert bot._macd_cross_kosdaq_regime_blocks(NOW) is False
    bot.pre_market_analyzer._get_kosdaq_trailing_return.assert_not_called()


def test_regime_caches_within_day():
    """같은 날 두 번째 호출은 캐시 사용 (DB 1회만)."""
    bot = _make_bot(-3.0)
    assert bot._macd_cross_kosdaq_regime_blocks(NOW) is True
    assert bot._macd_cross_kosdaq_regime_blocks(datetime(2026, 6, 4, 14, 45)) is True
    assert bot.pre_market_analyzer._get_kosdaq_trailing_return.call_count == 1


# ---------- 실 DB 신호식 일치 검증 ----------
try:
    import psycopg2
    from config import settings as _s
    _c = psycopg2.connect(host=_s.PG_HOST, port=_s.PG_PORT, dbname=_s.PG_DATABASE,
                          user=_s.PG_USER, password=_s.PG_PASSWORD, connect_timeout=3)
    _c.close()
    _DB_OK = True
except Exception:
    _DB_OK = False


@pytest.mark.skipif(not _DB_OK, reason="PostgreSQL 미가용")
def test_trailing_return_matches_backtest_formula():
    """_get_kosdaq_trailing_return 가 close[D-1]/close[D-6]-1 (lookahead 0) 와 일치."""
    from core.pre_market_analyzer import PreMarketAnalyzer

    class _FA: pass
    fa = _FA()
    fa._get_kosdaq_trailing_return = (
        PreMarketAnalyzer.__dict__['_get_kosdaq_trailing_return'].__get__(fa, _FA)
    )

    as_of = "20260604"
    got = fa._get_kosdaq_trailing_return(lookback_days=5, as_of_yyyymmdd=as_of)

    # 독립 계산: as_of 제외 직전 6개 종가
    import psycopg2
    conn = psycopg2.connect(host=_s.PG_HOST, port=_s.PG_PORT, dbname=_s.PG_DATABASE,
                            user=_s.PG_USER, password=_s.PG_PASSWORD)
    cur = conn.cursor()
    cur.execute('''SELECT CAST(stck_clpr AS FLOAT) FROM daily_candles
                   WHERE stock_code='KQ11' AND stck_bsop_date < %s
                   ORDER BY stck_bsop_date DESC LIMIT 6''', (as_of,))
    rows = cur.fetchall()
    conn.close()

    if len(rows) < 6:
        pytest.skip("KQ11 일봉 6개 미만")
    expected = (rows[0][0] / rows[5][0] - 1) * 100
    assert got is not None
    assert abs(got - expected) < 1e-6, f"got {got}, expected {expected}"
