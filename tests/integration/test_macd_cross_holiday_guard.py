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
    """월요일에서 호출하면 토/일 + 근로자의날(5/1 금) 스킵하고 4/30(목) 반환.

    2026-05-04(월) → 5/3(일) → 5/2(토) → 5/1(금, 근로자의날) → 4/30(목) 영업일.
    근로자의 날은 KRX 휴장 (mom 캘린더 대조 후 2025/2026/2027 모두 등록).
    """
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    monday = KST.localize(datetime(2026, 5, 4, 9, 0))
    result = bot._previous_trading_day(monday)

    assert result.date() == date(2026, 4, 30)
    assert '20260501' in KOREAN_HOLIDAYS, '근로자의 날 등록 누락'


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
    """9/28(월)에서 호출하면 9/27(일) + 9/26(토) + 9/25/24(추석)을 스킵하고 9/23(수) 반환.

    2026 추석은 9/24(목)/25(금)/26(토). 일요일이 없어 9/28은 대체공휴일 없음 → 영업일.
    """
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    mon = KST.localize(datetime(2026, 9, 28, 9, 0))
    result = bot._previous_trading_day(mon)

    assert result.date() == date(2026, 9, 23)
    # 추석 KOREAN_HOLIDAYS 등록 확인 (9/26 토 자연차단, 9/28 영업일이라 미등록)
    for holi in ('20260924', '20260925'):
        assert holi in KOREAN_HOLIDAYS
    assert '20260928' not in KOREAN_HOLIDAYS, '오등록 회귀'


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


# ---------------------------------------------------------------------------
# Task 3: _evaluate_macd_cross_window 휴일 가드
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_macd_cross_window_skips_holiday():
    """5/5 어린이날 14:31 호출 시 매수 트리거 미실행 + 1회만 로그."""
    bot = _FakeBot()
    bot.decision_engine = MagicMock()
    bot.decision_engine.macd_cross_strategy = MagicMock()
    bot.decision_engine.macd_cross_strategy._cache = {'005930': MagicMock()}
    bot.decision_engine.execute_real_buy = AsyncMock()
    bot.db_manager = MagicMock()
    bot._macd_cross_mode = MagicMock(return_value='real')
    _bind(bot, '_evaluate_macd_cross_window', '_evaluate_macd_cross_instance',
          '_apply_holiday_guard')

    holiday_dt = KST.localize(datetime(2026, 5, 5, 14, 31))

    # 첫 호출: return + 로그 1회
    await bot._evaluate_macd_cross_window(holiday_dt)
    bot.decision_engine.execute_real_buy.assert_not_awaited()
    info_calls = [c for c in bot.logger.info.call_args_list
                  if '[휴일가드]' in str(c)]
    assert len(info_calls) == 1
    assert bot._holiday_logged_date == date(2026, 5, 5)

    # 두 번째 호출: 동일 날짜 → 로그 추가 안 됨
    bot.logger.reset_mock()
    await bot._evaluate_macd_cross_window(holiday_dt)
    bot.decision_engine.execute_real_buy.assert_not_awaited()
    info_calls = [c for c in bot.logger.info.call_args_list
                  if '[휴일가드]' in str(c)]
    assert len(info_calls) == 0
    # 두 번째 호출이 _holiday_logged_date 를 reset 하지 않는지 확인
    assert bot._holiday_logged_date == date(2026, 5, 5)


# ---------------------------------------------------------------------------
# Task 4: _macd_cross_exit_dispatcher 휴일 가드
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_macd_cross_exit_dispatcher_skips_holiday():
    """5/5 어린이날 09:01 호출 시 dispatcher 즉시 return + paper/live 미호출."""
    bot = _FakeBot()
    bot._macd_cross_paper_exit_task = AsyncMock()
    bot._macd_cross_live_exit_task = AsyncMock()
    bot._macd_cross_mode = MagicMock(return_value='real')
    _bind(bot, '_macd_cross_exit_dispatcher', '_apply_holiday_guard')

    holiday_dt = KST.localize(datetime(2026, 5, 5, 9, 1))
    with patch('main.now_kst', return_value=holiday_dt):
        result = await bot._macd_cross_exit_dispatcher()

    # 휴일이라 즉시 return True (가드 set 가능 — off 모드와 동일 의미)
    assert result is True
    bot._macd_cross_paper_exit_task.assert_not_awaited()
    bot._macd_cross_live_exit_task.assert_not_awaited()
    # 첫 호출이라 로그 1회 + 상태 set 확인 (test 5 와 symmetry)
    info_calls = [c for c in bot.logger.info.call_args_list
                  if '[휴일가드]' in str(c)]
    assert len(info_calls) == 1
    assert bot._holiday_logged_date == date(2026, 5, 5)


# ---------------------------------------------------------------------------
# 2026-05-12 fix: _count_krx_trading_days_between — today 거래일 판정을
#   minute_candles row 존재 여부 → MarketHours.is_trading_day 로 교체.
#   (분봉은 장중 DB 미저장이라 09:01 morning exit 시점엔 항상 0 → hold_days 가
#    1일 적게 계산 → D+2 청산이 morning(09:01) 대신 EOD(15:00) 로 밀리는 버그.
#    2026-05-11 006800, 2026-05-12 010170/028050/068270 에서 재현됨.)
# ---------------------------------------------------------------------------

def _make_bot_with_db(past_trading_days: int):
    """db_manager._fetchone 이 (past_trading_days,) 를 돌려주는 _FakeBot."""
    bot = _FakeBot()
    bot.db_manager = MagicMock()
    bot.db_manager._fetchone = MagicMock(return_value=(past_trading_days,))
    _bind(bot, '_count_krx_trading_days_between')
    return bot


def test_count_krx_days_d2_morning_counts_today():
    """D+2 아침(09:01) 시점 — 분봉 DB 가 비어도 today 거래일이 카운트돼야 만료된다.

    회귀: 2026-05-08(금) 매수 → 2026-05-12(화) 가 D+2.
    과거 거래일 = 05-11(월) 1개, today(05-12) = 거래일 → 합계 2 == HOLD_DAYS.
    """
    bot = _make_bot_with_db(past_trading_days=1)
    n = bot._count_krx_trading_days_between(date(2026, 5, 8), date(2026, 5, 12))
    assert n == 2
    # minute_candles 조회를 더 이상 하지 않음 — daily_candles 1회만 호출
    assert bot.db_manager._fetchone.call_count == 1


def test_count_krx_days_d1_not_yet_expired():
    """D+1(매수 다음 거래일) 은 아직 만료 전 (합계 1 < HOLD_DAYS=2)."""
    bot = _make_bot_with_db(past_trading_days=0)
    # 2026-05-08(금) 매수, today=2026-05-11(월) → 과거 0, today 거래일 → 1
    n = bot._count_krx_trading_days_between(date(2026, 5, 8), date(2026, 5, 11))
    assert n == 1


def test_count_krx_days_today_holiday_not_counted():
    """today 가 공휴일이면 +1 안 함 (어린이날 5/5)."""
    bot = _make_bot_with_db(past_trading_days=2)
    n = bot._count_krx_trading_days_between(date(2026, 4, 30), date(2026, 5, 5))
    assert n == 2  # 과거 2개만, 휴일 today 미카운트
    assert '20260505' in KOREAN_HOLIDAYS


def test_count_krx_days_today_weekend_not_counted():
    """today 가 주말이면 +1 안 함."""
    bot = _make_bot_with_db(past_trading_days=1)
    n = bot._count_krx_trading_days_between(date(2026, 5, 7), date(2026, 5, 9))  # 5/9 토
    assert n == 1


def test_count_krx_days_db_error_returns_zero():
    """daily_candles 조회 실패 시 보수적으로 0 (만료 안 함)."""
    bot = _FakeBot()
    bot.db_manager = MagicMock()
    bot.db_manager._fetchone = MagicMock(side_effect=RuntimeError('boom'))
    _bind(bot, '_count_krx_trading_days_between')
    n = bot._count_krx_trading_days_between(date(2026, 5, 8), date(2026, 5, 12))
    assert n == 0
