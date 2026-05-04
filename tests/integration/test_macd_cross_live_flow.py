"""macd_cross 실거래 e2e 시나리오 검증 (mock DB / mock fund_manager).

Phase 1~3 통합 검증:
1. _macd_cross_mode 분기 (paper/virtual/real/off + kill switch)
2. 킬 스위치 발동 (누적 -5% / 5연속 손실)
3. 디스크 기반 kill switch state 파일 round-trip
4. 서킷브레이커 inherit (전일 -3%)
5. 영업일 기반 hold_days D+2 카운팅
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.strategy_settings import StrategySettings


class _FakeBot:
    """DayTradingBot 의 메서드를 instance 메서드처럼 호출하기 위한 최소 컨테이너."""
    def __init__(self):
        self.logger = MagicMock()
        self.fund_manager = MagicMock()
        self.fund_manager.get_status.return_value = {
            'total_funds': 10_000_000, 'available_funds': 6_433_589
        }
        self.db_manager = MagicMock()
        self.telegram = MagicMock()
        self.pre_market_analyzer = MagicMock()


def _bind(bot, *method_names):
    """main.DayTradingBot 의 instance 메서드를 _FakeBot 에 바인딩."""
    from main import DayTradingBot
    for name in method_names:
        setattr(bot, name, DayTradingBot.__dict__[name].__get__(bot, _FakeBot))


def test_macd_cross_mode_off_when_kill_switch_active(tmp_path, monkeypatch):
    """킬 스위치 발동 시 ACTIVE='macd_cross' + VIRTUAL_ONLY=False 라도 'off' 반환."""
    bot = _FakeBot()
    _bind(bot, '_macd_cross_mode', '_is_macd_cross_kill_switch_active')

    # 킬 스위치 파일을 tmp_path 로 redirect
    ks_file = tmp_path / 'config' / 'macd_cross_kill_switch.json'
    ks_file.parent.mkdir()
    ks_file.write_text(json.dumps({'disabled': True, 'reason': 'test'}), encoding='utf-8')

    # __file__ 경로 redirect: _is_macd_cross_kill_switch_active 가 main.py 위치 기준
    with patch('main.__file__', str(tmp_path / 'main.py')):
        with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
            with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
                assert bot._macd_cross_mode() == 'off'


def test_macd_cross_mode_real_without_kill_switch(tmp_path):
    """킬 스위치 없을 때 ACTIVE='macd_cross' + VIRTUAL_ONLY=False → 'real'."""
    bot = _FakeBot()
    _bind(bot, '_macd_cross_mode', '_is_macd_cross_kill_switch_active')

    # 킬 스위치 파일 없음 (tmp_path/config 디렉터리 비어있음)
    with patch('main.__file__', str(tmp_path / 'main.py')):
        with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
            with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
                assert bot._macd_cross_mode() == 'real'


def test_macd_cross_mode_virtual_when_paper_strategy(tmp_path):
    """PAPER_STRATEGY='macd_cross' → 'virtual' (현재 운영 상태)."""
    bot = _FakeBot()
    _bind(bot, '_macd_cross_mode', '_is_macd_cross_kill_switch_active')

    with patch('main.__file__', str(tmp_path / 'main.py')):
        with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'weighted_score'):
            with patch.object(StrategySettings, 'PAPER_STRATEGY', 'macd_cross'):
                assert bot._macd_cross_mode() == 'virtual'


def test_kill_switch_trigger_writes_disk(tmp_path):
    """_trigger_macd_cross_kill_switch 가 JSON 파일을 정확히 write."""
    bot = _FakeBot()
    _bind(bot, '_trigger_macd_cross_kill_switch')

    with patch('main.__file__', str(tmp_path / 'main.py')):
        bot._trigger_macd_cross_kill_switch("테스트 사유")

    ks_file = tmp_path / 'config' / 'macd_cross_kill_switch.json'
    assert ks_file.exists()
    state = json.loads(ks_file.read_text(encoding='utf-8'))
    assert state['disabled'] is True
    assert state['reason'] == "테스트 사유"
    assert 'triggered_at' in state


def test_kill_switch_threshold_cumulative_loss(tmp_path):
    """누적 -5% 시 킬 스위치 발동."""
    bot = _FakeBot()
    _bind(bot, '_check_macd_cross_kill_switch_thresholds',
          '_macd_cross_mode', '_is_macd_cross_kill_switch_active',
          '_trigger_macd_cross_kill_switch')

    # SELL records: 누적 -600,000 (10M 의 -6%)
    sell_rows = [
        (datetime(2026, 4, 27, 14, 31), -200_000),
        (datetime(2026, 4, 28, 14, 31), -100_000),
        (datetime(2026, 4, 29, 14, 31), -300_000),  # 마지막 1건만 음수
    ]
    cur_mock = MagicMock()
    cur_mock.fetchall.return_value = sell_rows
    conn_mock = MagicMock()
    conn_mock.cursor.return_value = cur_mock
    bot.db_manager._pool_obj.connection.return_value.__enter__.return_value = conn_mock

    with patch('main.__file__', str(tmp_path / 'main.py')):
        with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
            with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
                bot._check_macd_cross_kill_switch_thresholds()

    ks_file = tmp_path / 'config' / 'macd_cross_kill_switch.json'
    assert ks_file.exists()
    state = json.loads(ks_file.read_text(encoding='utf-8'))
    assert state['disabled'] is True
    assert '-6.00%' in state['reason'] or '누적 손실' in state['reason']


def test_kill_switch_threshold_consecutive_losses(tmp_path):
    """5연속 손실 시 킬 스위치 발동 (누적은 양수여도)."""
    bot = _FakeBot()
    _bind(bot, '_check_macd_cross_kill_switch_thresholds',
          '_macd_cross_mode', '_is_macd_cross_kill_switch_active',
          '_trigger_macd_cross_kill_switch')

    # SELL: 처음 1건 +1M (이익), 이후 5연속 -100K = +500K 누적 (5%) but 5연속 손실
    sell_rows = [
        (datetime(2026, 4, 20, 14, 31), 1_000_000),
        (datetime(2026, 4, 21, 14, 31), -100_000),
        (datetime(2026, 4, 22, 14, 31), -100_000),
        (datetime(2026, 4, 23, 14, 31), -100_000),
        (datetime(2026, 4, 24, 14, 31), -100_000),
        (datetime(2026, 4, 27, 14, 31), -100_000),
    ]
    cur_mock = MagicMock()
    cur_mock.fetchall.return_value = sell_rows
    conn_mock = MagicMock()
    conn_mock.cursor.return_value = cur_mock
    bot.db_manager._pool_obj.connection.return_value.__enter__.return_value = conn_mock

    with patch('main.__file__', str(tmp_path / 'main.py')):
        with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
            with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
                bot._check_macd_cross_kill_switch_thresholds()

    ks_file = tmp_path / 'config' / 'macd_cross_kill_switch.json'
    assert ks_file.exists()
    state = json.loads(ks_file.read_text(encoding='utf-8'))
    assert state['disabled'] is True
    assert '연속' in state['reason'] or '5건' in state['reason']


def test_kill_switch_no_trigger_when_under_threshold(tmp_path):
    """누적 -3% + 4연속 손실: 둘 다 미달 → 미발동."""
    bot = _FakeBot()
    _bind(bot, '_check_macd_cross_kill_switch_thresholds',
          '_macd_cross_mode', '_is_macd_cross_kill_switch_active',
          '_trigger_macd_cross_kill_switch')

    sell_rows = [
        (datetime(2026, 4, 21, 14, 31), -100_000),
        (datetime(2026, 4, 22, 14, 31), -100_000),
        (datetime(2026, 4, 23, 14, 31), -50_000),
        (datetime(2026, 4, 24, 14, 31), -50_000),  # 4연속 손실, 누적 -300K (=-3%)
    ]
    cur_mock = MagicMock()
    cur_mock.fetchall.return_value = sell_rows
    conn_mock = MagicMock()
    conn_mock.cursor.return_value = cur_mock
    bot.db_manager._pool_obj.connection.return_value.__enter__.return_value = conn_mock

    with patch('main.__file__', str(tmp_path / 'main.py')):
        with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
            with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
                bot._check_macd_cross_kill_switch_thresholds()

    ks_file = tmp_path / 'config' / 'macd_cross_kill_switch.json'
    assert not ks_file.exists()


def test_circuit_breaker_inherit_3pct_blocks(tmp_path):
    """전일 KOSPI -3.5% 시 _macd_cross_circuit_breaker_blocks=True."""
    bot = _FakeBot()
    _bind(bot, '_macd_cross_circuit_breaker_blocks')

    bot.pre_market_analyzer._get_prev_day_index_returns.return_value = {
        'kospi_ret': -3.5, 'kosdaq_ret': -2.0
    }
    current_time = datetime(2026, 4, 27, 14, 31)
    assert bot._macd_cross_circuit_breaker_blocks(current_time) is True


def test_circuit_breaker_inherit_no_block_when_above_threshold(tmp_path):
    """전일 -2.5% 시 차단 안 함 (임계값 -3.0% 미달)."""
    bot = _FakeBot()
    _bind(bot, '_macd_cross_circuit_breaker_blocks')

    bot.pre_market_analyzer._get_prev_day_index_returns.return_value = {
        'kospi_ret': -2.5, 'kosdaq_ret': -2.0
    }
    current_time = datetime(2026, 4, 27, 14, 31)
    assert bot._macd_cross_circuit_breaker_blocks(current_time) is False


def test_circuit_breaker_inherit_caches_within_day(tmp_path):
    """동일 날짜 두 번째 호출 시 DB 재조회 없음 (캐시)."""
    bot = _FakeBot()
    _bind(bot, '_macd_cross_circuit_breaker_blocks')

    bot.pre_market_analyzer._get_prev_day_index_returns.return_value = {
        'kospi_ret': -3.5, 'kosdaq_ret': -2.0
    }
    current_time = datetime(2026, 4, 27, 14, 31)
    bot._macd_cross_circuit_breaker_blocks(current_time)
    bot._macd_cross_circuit_breaker_blocks(current_time)
    # _get_prev_day_index_returns 는 1회만 호출되어야 함 (캐시)
    assert bot.pre_market_analyzer._get_prev_day_index_returns.call_count == 1


# ---------------------------------------------------------------------------
# EOD 격리 회귀 테스트 (incident 2026-04-29 D+0 당일청산 방지)
# ---------------------------------------------------------------------------

def test_get_buy_time_position_entry_time_priority():
    """Position.entry_time 우선 사용 (정상 매수 케이스)."""
    from core.models import TradingStock, StockState
    ts = TradingStock(
        stock_code='005010', stock_name='휴스틸',
        state=StockState.POSITIONED, selected_time=datetime(2026, 4, 29, 8, 55),
    )
    expected = datetime(2026, 4, 29, 14, 31)
    ts.set_position(quantity=10, avg_price=6970, entry_time=expected)
    ts.last_buy_time = datetime(2026, 4, 30, 10, 0)  # 다른 값이라도 entry_time 우선
    assert ts.get_buy_time() == expected


def test_get_buy_time_falls_back_to_last_buy_time():
    """Position 없을 때 last_buy_time 사용."""
    from core.models import TradingStock, StockState
    ts = TradingStock(
        stock_code='005010', stock_name='휴스틸',
        state=StockState.SELECTED, selected_time=datetime(2026, 4, 29, 8, 55),
    )
    expected = datetime(2026, 4, 29, 14, 31)
    ts.last_buy_time = expected
    assert ts.get_buy_time() == expected


def test_get_buy_time_none_when_no_data():
    """Position·last_buy_time 둘 다 None → None (보수 분기 트리거)."""
    from core.models import TradingStock, StockState
    ts = TradingStock(
        stock_code='005010', stock_name='휴스틸',
        state=StockState.SELECTED, selected_time=datetime(2026, 4, 29, 8, 55),
    )
    assert ts.get_buy_time() is None


def _make_ts(stock_code, state, *, entry_time=None, last_buy_time=None,
             strategy_tag=None):
    """테스트용 TradingStock factory."""
    from core.models import TradingStock
    ts = TradingStock(
        stock_code=stock_code, stock_name=f'TS_{stock_code}',
        state=state, selected_time=datetime(2026, 4, 29, 8, 55),
    )
    if entry_time is not None:
        ts.set_position(quantity=10, avg_price=10000, entry_time=entry_time)
    if last_buy_time is not None:
        ts.last_buy_time = last_buy_time
    if strategy_tag is not None:
        setattr(ts, 'strategy_tag', strategy_tag)
    return ts


def test_eod_filter_protects_macd_cross_d0(tmp_path):
    """매수 당일(D+0) macd_cross 포지션 EOD 청산 차단 — incident 2026-04-29 회귀 방지."""
    from core.models import StockState
    bot = _FakeBot()
    _bind(bot, '_filter_macd_cross_live_eod_targets')

    ts = _make_ts('005010', StockState.POSITIONED,
                  entry_time=datetime(2026, 4, 29, 14, 31),
                  strategy_tag='macd_cross')

    with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
        with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
            with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
                held_over, to_close = bot._filter_macd_cross_live_eod_targets(
                    [ts], datetime(2026, 4, 29).date()
                )

    assert len(held_over) == 1
    assert held_over[0][0] is ts
    assert held_over[0][1] == 0  # D+0
    assert to_close == []


def test_eod_filter_closes_macd_cross_at_d2(tmp_path):
    """D+2 영업일 도달 macd_cross 포지션은 청산 대상."""
    from core.models import StockState
    bot = _FakeBot()
    _bind(bot, '_filter_macd_cross_live_eod_targets')

    # 04-27(월) 매수 → 04-29(수) 가 D+2
    ts = _make_ts('005010', StockState.POSITIONED,
                  entry_time=datetime(2026, 4, 27, 14, 31),
                  strategy_tag='macd_cross')

    with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
        with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
            with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
                held_over, to_close = bot._filter_macd_cross_live_eod_targets(
                    [ts], datetime(2026, 4, 29).date()
                )

    assert held_over == []
    assert to_close == [ts]


def test_eod_filter_passes_through_other_strategy(tmp_path):
    """다른 전략 종목은 격리 안 함 → 청산 통과."""
    from core.models import StockState
    bot = _FakeBot()
    _bind(bot, '_filter_macd_cross_live_eod_targets')

    ts = _make_ts('000660', StockState.POSITIONED,
                  entry_time=datetime(2026, 4, 29, 14, 31),
                  strategy_tag='weighted_score')

    with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
        with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
            with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
                held_over, to_close = bot._filter_macd_cross_live_eod_targets(
                    [ts], datetime(2026, 4, 29).date()
                )

    assert held_over == []
    assert to_close == [ts]


def test_eod_filter_conservative_close_when_buy_time_unknown(tmp_path):
    """buy_time 미상 (position·last_buy_time 둘 다 None) → 보수적 청산."""
    from core.models import StockState
    bot = _FakeBot()
    _bind(bot, '_filter_macd_cross_live_eod_targets')

    ts = _make_ts('005010', StockState.POSITIONED, strategy_tag='macd_cross')
    # entry_time, last_buy_time 둘 다 None

    with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
        with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
            with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
                held_over, to_close = bot._filter_macd_cross_live_eod_targets(
                    [ts], datetime(2026, 4, 29).date()
                )

    assert held_over == []
    assert to_close == [ts]


def test_eod_filter_inactive_when_paper_only(tmp_path):
    """VIRTUAL_ONLY=True (페이퍼) 시 격리 미작동 → 전체 통과 (held_over 없음)."""
    from core.models import StockState
    bot = _FakeBot()
    _bind(bot, '_filter_macd_cross_live_eod_targets')

    ts = _make_ts('005010', StockState.POSITIONED,
                  entry_time=datetime(2026, 4, 29, 14, 31),
                  strategy_tag='macd_cross')

    with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
        with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', True):
            with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
                held_over, to_close = bot._filter_macd_cross_live_eod_targets(
                    [ts], datetime(2026, 4, 29).date()
                )

    assert held_over == []
    assert to_close == [ts]


def test_eod_filter_inactive_when_other_active_strategy(tmp_path):
    """ACTIVE_STRATEGY != 'macd_cross' 시 격리 미작동."""
    from core.models import StockState
    bot = _FakeBot()
    _bind(bot, '_filter_macd_cross_live_eod_targets')

    ts = _make_ts('005010', StockState.POSITIONED,
                  entry_time=datetime(2026, 4, 29, 14, 31),
                  strategy_tag='macd_cross')

    with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'weighted_score'):
        with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
            with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
                held_over, to_close = bot._filter_macd_cross_live_eod_targets(
                    [ts], datetime(2026, 4, 29).date()
                )

    assert held_over == []
    assert to_close == [ts]


def test_eod_filter_mixed_targets(tmp_path):
    """다양한 케이스 혼합 — 격리/청산이 올바르게 분리되는지 검증."""
    from core.models import StockState
    bot = _FakeBot()
    _bind(bot, '_filter_macd_cross_live_eod_targets')

    ts_d0 = _make_ts('005010', StockState.POSITIONED,
                     entry_time=datetime(2026, 4, 29, 14, 31),
                     strategy_tag='macd_cross')  # 보호
    ts_d2 = _make_ts('425040', StockState.POSITIONED,
                     entry_time=datetime(2026, 4, 27, 14, 31),
                     strategy_tag='macd_cross')  # 청산
    ts_other = _make_ts('000660', StockState.POSITIONED,
                        entry_time=datetime(2026, 4, 29, 14, 31),
                        strategy_tag='weighted_score')  # 다른 전략 → 청산
    ts_unknown = _make_ts('006400', StockState.POSITIONED,
                          strategy_tag='macd_cross')  # buy_time 미상 → 청산

    with patch.object(StrategySettings, 'ACTIVE_STRATEGY', 'macd_cross'):
        with patch.object(StrategySettings.MacdCross, 'VIRTUAL_ONLY', False):
            with patch.object(StrategySettings.MacdCross, 'HOLD_DAYS', 2):
                held_over, to_close = bot._filter_macd_cross_live_eod_targets(
                    [ts_d0, ts_d2, ts_other, ts_unknown],
                    datetime(2026, 4, 29).date()
                )

    held_codes = [pair[0].stock_code for pair in held_over]
    closed_codes = [t.stock_code for t in to_close]
    assert held_codes == ['005010']
    assert sorted(closed_codes) == ['000660', '006400', '425040']
