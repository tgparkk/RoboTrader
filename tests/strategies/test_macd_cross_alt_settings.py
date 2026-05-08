"""MacdCrossAlt 설정 + validate_settings 가드 검증."""
import pytest

from config.strategy_settings import StrategySettings, validate_settings


def test_macd_cross_alt_class_has_required_attrs():
    """16/32 paper 파라미터 존재 + 값 정확."""
    cfg = StrategySettings.MacdCrossAlt
    assert cfg.FAST_PERIOD == 16
    assert cfg.SLOW_PERIOD == 32
    assert cfg.SIGNAL_PERIOD == 12
    assert cfg.ENTRY_HHMM_MIN == 1431
    assert cfg.ENTRY_HHMM_MAX == 1500
    assert cfg.HOLD_DAYS == 2
    assert cfg.VIRTUAL_CAPITAL == 10_000_000
    assert cfg.BUY_BUDGET_RATIO == 0.20
    assert cfg.MAX_DAILY_POSITIONS == 5
    assert cfg.UNIVERSE_TOP_N == 30
    assert cfg.VIRTUAL_ONLY is True


def test_valid_paper_strategies_includes_macd_cross_alt():
    """'macd_cross_alt' 가 valid list 에 있어야 validate_settings 통과."""
    original = StrategySettings.PAPER_STRATEGY
    try:
        StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'
        assert validate_settings() is True
    finally:
        StrategySettings.PAPER_STRATEGY = original


def test_universe_top_n_must_match_macd_cross():
    """MacdCrossAlt.UNIVERSE_TOP_N != MacdCross.UNIVERSE_TOP_N 시 ValueError."""
    original_alt = StrategySettings.MacdCrossAlt.UNIVERSE_TOP_N
    original_paper = StrategySettings.PAPER_STRATEGY
    try:
        StrategySettings.MacdCrossAlt.UNIVERSE_TOP_N = 50
        StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'
        with pytest.raises(ValueError, match="UNIVERSE_TOP_N"):
            validate_settings()
    finally:
        StrategySettings.MacdCrossAlt.UNIVERSE_TOP_N = original_alt
        StrategySettings.PAPER_STRATEGY = original_paper


def test_entry_hhmm_min_lt_max():
    """ENTRY_HHMM_MIN >= MAX 시 validate_settings 가 ValueError."""
    original_min = StrategySettings.MacdCrossAlt.ENTRY_HHMM_MIN
    original_paper = StrategySettings.PAPER_STRATEGY
    try:
        StrategySettings.MacdCrossAlt.ENTRY_HHMM_MIN = 1500
        StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'
        with pytest.raises(ValueError, match="ENTRY_HHMM_MIN"):
            validate_settings()
    finally:
        StrategySettings.MacdCrossAlt.ENTRY_HHMM_MIN = original_min
        StrategySettings.PAPER_STRATEGY = original_paper
