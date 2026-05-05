"""macd_cross D+2 morning exit 누락 회귀 방지 (incident 2026-05-04).

수정 대상:
- Step 1: 봇 가동 후 1회 pre-market `emergency_sync_positions` 호출
  → `_ensure_pre_market_sync_once` 헬퍼
- Step 2: morning exit dispatcher 가 미등록 종목 시 False 반환 → 가드 미설정
  → `_macd_cross_exit_dispatcher` / `_macd_cross_live_exit_task` /
    `_macd_cross_paper_exit_task` bool 반환

원인: 봇 시작(07:40)이 장 시작 전이라 `_trading_decision_task` 가
`is_market_open()` 게이팅에 막혀 emergency_sync 미실행. 09:00 후 preload(4분)
가 끝난 09:04:30 에야 첫 sync → morning window(09:01~05) 마감 직전.
미관리 010950 보유로 dispatcher 가 trading_stock None 만나 skip.
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from config.strategy_settings import StrategySettings

_KST = pytz.timezone('Asia/Seoul')
_WEEKDAY_DT = _KST.localize(datetime(2026, 5, 4, 9, 1))  # 월요일 (평일)


class _FakeBot:
    def __init__(self):
        self.logger = MagicMock()
        self.fund_manager = MagicMock()
        self.db_manager = MagicMock()
        self.telegram = MagicMock()
        self.pre_market_analyzer = MagicMock()
        self.trading_manager = MagicMock()
        self.intraday_manager = MagicMock()
        self.decision_engine = MagicMock()
        self._pre_market_sync_done = False
        self._holiday_logged_date = None


def _bind(bot, *method_names):
    from main import DayTradingBot
    for name in method_names:
        setattr(bot, name, DayTradingBot.__dict__[name].__get__(bot, _FakeBot))


# ---------------------------------------------------------------------------
# Step 1: pre-market sync helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pre_market_sync_invokes_emergency_sync_on_first_call():
    """첫 호출: `emergency_sync_positions` 호출 + 플래그 set."""
    bot = _FakeBot()
    bot.emergency_sync_positions = AsyncMock()
    _bind(bot, '_ensure_pre_market_sync_once')

    await bot._ensure_pre_market_sync_once()

    bot.emergency_sync_positions.assert_awaited_once()
    assert bot._pre_market_sync_done is True


@pytest.mark.asyncio
async def test_pre_market_sync_skipped_on_second_call():
    """두 번째 호출: 이미 완료 → emergency_sync 호출 안 함."""
    bot = _FakeBot()
    bot.emergency_sync_positions = AsyncMock()
    _bind(bot, '_ensure_pre_market_sync_once')

    await bot._ensure_pre_market_sync_once()
    await bot._ensure_pre_market_sync_once()

    bot.emergency_sync_positions.assert_awaited_once()  # 1회만


@pytest.mark.asyncio
async def test_pre_market_sync_swallows_exception_and_sets_flag():
    """sync 예외 발생해도 플래그는 set (무한 재시도 방지)."""
    bot = _FakeBot()
    bot.emergency_sync_positions = AsyncMock(side_effect=RuntimeError("boom"))
    _bind(bot, '_ensure_pre_market_sync_once')

    await bot._ensure_pre_market_sync_once()  # 예외 swallow

    assert bot._pre_market_sync_done is True
    bot.logger.warning.assert_called()


# ---------------------------------------------------------------------------
# Step 2: dispatcher bool 반환 — live exit
# ---------------------------------------------------------------------------

def _expired_buy_row(stock_code: str = '010950', quantity: int = 7,
                    days_ago: int = 4) -> dict:
    """hold_days >= 2 만족하는 BUY 레코드 (영업일 기준)."""
    from utils.korean_time import now_kst
    buy_dt = now_kst() - timedelta(days=days_ago)
    return {
        'stock_code': stock_code,
        'quantity': quantity,
        'timestamp': buy_dt.replace(hour=14, minute=31),
    }


@pytest.mark.asyncio
async def test_live_exit_returns_true_when_no_open_buys():
    """미매칭 BUY 0건 → True (no-op, 가드 set 가능)."""
    bot = _FakeBot()
    bot.db_manager.get_open_real_buys_by_strategy.return_value = []
    _bind(bot, '_macd_cross_live_exit_task')

    result = await bot._macd_cross_live_exit_task()

    assert result is True


@pytest.mark.asyncio
async def test_live_exit_returns_false_when_trading_stock_unregistered():
    """만료 BUY 존재하지만 trading_stock 미등록 → False (재시도 필요)."""
    bot = _FakeBot()
    bot.db_manager.get_open_real_buys_by_strategy.return_value = [_expired_buy_row()]
    bot.trading_manager.get_trading_stock.return_value = None  # 미관리
    _bind(bot, '_macd_cross_live_exit_task', '_count_krx_trading_days_between')

    with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
        result = await bot._macd_cross_live_exit_task()

    assert result is False
    bot.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_live_exit_returns_true_when_all_expired_handled():
    """만료 BUY 가 sell 큐로 정상 진입 → True."""
    from core.models import StockState

    bot = _FakeBot()
    bot.db_manager.get_open_real_buys_by_strategy.return_value = [_expired_buy_row()]
    ts = MagicMock()
    ts.state = StockState.POSITIONED
    bot.trading_manager.get_trading_stock.return_value = ts
    bot.trading_manager.move_to_sell_candidate = AsyncMock(return_value=True)
    bot.trading_manager.execute_sell_order = AsyncMock(return_value=True)
    _bind(bot, '_macd_cross_live_exit_task', '_count_krx_trading_days_between')

    with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
        result = await bot._macd_cross_live_exit_task()

    assert result is True
    bot.trading_manager.execute_sell_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_exit_returns_false_when_exception():
    """내부 예외 발생 → False (다음 사이클 재시도 안전)."""
    bot = _FakeBot()
    bot.db_manager.get_open_real_buys_by_strategy.side_effect = RuntimeError("db down")
    _bind(bot, '_macd_cross_live_exit_task')

    result = await bot._macd_cross_live_exit_task()

    assert result is False


# ---------------------------------------------------------------------------
# Step 2: dispatcher bool 반환 — paper exit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paper_exit_returns_true_when_no_open_buys():
    """가상 미매칭 BUY 0건 → True."""
    import pandas as pd
    bot = _FakeBot()
    bot.db_manager.get_virtual_open_positions.return_value = pd.DataFrame()
    _bind(bot, '_macd_cross_paper_exit_task')

    result = await bot._macd_cross_paper_exit_task()

    assert result is True


@pytest.mark.asyncio
async def test_paper_exit_returns_false_when_price_unavailable():
    """만료 BUY 있지만 intraday 가격 캐시 없음 → False (다음 사이클 재시도)."""
    import pandas as pd
    from utils.korean_time import now_kst

    bot = _FakeBot()
    buy_dt = (now_kst() - timedelta(days=4)).replace(hour=14, minute=31)
    df = pd.DataFrame([{
        'id': 1,
        'stock_code': '010950',
        'stock_name': 'S-Oil',
        'quantity': 7,
        'buy_time': buy_dt,
        'strategy': 'macd_cross',
    }])
    bot.db_manager.get_virtual_open_positions.return_value = df
    bot.intraday_manager.get_cached_current_price.return_value = None  # 가격 없음
    bot.decision_engine.macd_cross_strategy = None
    _bind(bot, '_macd_cross_paper_exit_task', '_count_krx_trading_days_between')

    with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
        result = await bot._macd_cross_paper_exit_task()

    assert result is False


# ---------------------------------------------------------------------------
# Step 2: dispatcher bool 반환 — exit_dispatcher
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatcher_returns_true_when_mode_off():
    """mode=off → True (no-op, 가드 set OK)."""
    bot = _FakeBot()
    bot._macd_cross_mode = MagicMock(return_value='off')
    _bind(bot, '_macd_cross_exit_dispatcher', '_apply_holiday_guard')

    with patch('main.now_kst', return_value=_WEEKDAY_DT):
        result = await bot._macd_cross_exit_dispatcher()

    assert result is True


@pytest.mark.asyncio
async def test_dispatcher_passes_through_live_bool():
    """mode=real → live_exit_task 의 bool 반환값 그대로 전달."""
    bot = _FakeBot()
    bot._macd_cross_mode = MagicMock(return_value='real')
    bot._macd_cross_live_exit_task = AsyncMock(return_value=False)
    bot._macd_cross_paper_exit_task = AsyncMock(return_value=True)
    _bind(bot, '_macd_cross_exit_dispatcher', '_apply_holiday_guard')

    with patch('main.now_kst', return_value=_WEEKDAY_DT):
        result = await bot._macd_cross_exit_dispatcher()

    assert result is False
    bot._macd_cross_live_exit_task.assert_awaited_once()
    bot._macd_cross_paper_exit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_passes_through_paper_bool():
    """mode=virtual → paper_exit_task 의 bool 반환값 그대로 전달."""
    bot = _FakeBot()
    bot._macd_cross_mode = MagicMock(return_value='virtual')
    bot._macd_cross_live_exit_task = AsyncMock(return_value=True)
    bot._macd_cross_paper_exit_task = AsyncMock(return_value=False)
    _bind(bot, '_macd_cross_exit_dispatcher', '_apply_holiday_guard')

    with patch('main.now_kst', return_value=_WEEKDAY_DT):
        result = await bot._macd_cross_exit_dispatcher()

    assert result is False
    bot._macd_cross_paper_exit_task.assert_awaited_once()
    bot._macd_cross_live_exit_task.assert_not_awaited()
