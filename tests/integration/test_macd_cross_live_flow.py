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
