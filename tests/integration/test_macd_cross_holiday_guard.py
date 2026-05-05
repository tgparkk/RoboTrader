"""macd_cross 휴일 가드 회귀 방지 (2026-05-05).

수정 대상:
- `_previous_trading_day` 헬퍼 (KOREAN_HOLIDAYS + 주말 모두 스킵)
- `_evaluate_macd_cross_window` / `_macd_cross_exit_dispatcher` 진입부 휴일 가드
- 분봉 백필 prev_date 계산 (line 2397) 헬퍼로 교체
"""
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from config.market_hours import MarketHours, KOREAN_HOLIDAYS

KST = pytz.timezone('Asia/Seoul')


class _FakeBot:
    def __init__(self):
        self.logger = MagicMock()
        self._holiday_logged_date = None


def _bind(bot, *method_names):
    from main import DayTradingBot
    for name in method_names:
        setattr(bot, name, DayTradingBot.__dict__[name].__get__(bot, _FakeBot))


# ---------------------------------------------------------------------------
# Task 1: _previous_trading_day 헬퍼
# ---------------------------------------------------------------------------

def test_previous_trading_day_skips_weekend():
    """월요일에서 호출하면 직전 금요일을 반환 (토/일 스킵)."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    # 2026-05-04 (월) → 2026-05-01 (금)
    monday = KST.localize(datetime(2026, 5, 4, 9, 0))
    result = bot._previous_trading_day(monday)

    assert result.date() == date(2026, 5, 1)


def test_previous_trading_day_skips_holiday():
    """5/6 수요일에서 호출하면 5/5 어린이날을 스킵하고 5/4 월요일 반환."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    wed = KST.localize(datetime(2026, 5, 6, 9, 0))
    result = bot._previous_trading_day(wed)

    assert result.date() == date(2026, 5, 4)
    # KOREAN_HOLIDAYS 등록 확인
    assert '20260505' in KOREAN_HOLIDAYS


def test_previous_trading_day_skips_long_holiday_chain():
    """9/28 월요일에서 호출하면 9/24~26 추석 + 9/27 일요일을 스킵하고 9/23 수요일 반환."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    mon = KST.localize(datetime(2026, 9, 28, 9, 0))
    result = bot._previous_trading_day(mon)

    assert result.date() == date(2026, 9, 23)
    # KOREAN_HOLIDAYS 등록 확인
    for holi in ('20260924', '20260925', '20260926'):
        assert holi in KOREAN_HOLIDAYS


def test_previous_trading_day_raises_on_runaway(monkeypatch):
    """KOREAN_HOLIDAYS 가 모든 평일을 휴일로 마킹하면 14일 cap 으로 ValueError."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    # 30일치 평일을 모두 휴일로 monkeypatch
    fake_holidays = set()
    base = date(2026, 5, 1)
    for i in range(30):
        d = base - timedelta(days=i)
        fake_holidays.add(d.strftime('%Y%m%d'))

    monkeypatch.setattr('config.market_hours.KOREAN_HOLIDAYS', fake_holidays)

    dt = KST.localize(datetime(2026, 5, 1, 9, 0))
    with pytest.raises(ValueError, match='14일 내 영업일 없음'):
        bot._previous_trading_day(dt)
