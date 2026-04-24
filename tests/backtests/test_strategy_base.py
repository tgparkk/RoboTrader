"""backtests.strategies.base 단위 테스트."""
from typing import Optional

import pandas as pd
import pytest

from backtests.strategies.base import StrategyBase, Position, EntryOrder, ExitOrder


class DummyStrategy(StrategyBase):
    name = "dummy"
    hold_days = 0
    param_space = {}

    def prepare_features(self, df_minute, df_daily):
        return pd.DataFrame(
            {"prev_close": df_minute["close"].shift(1)}, index=df_minute.index
        )

    def entry_signal(self, features, bar_idx, stock_code):
        if bar_idx == 10:
            return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.2)
        return None

    def exit_signal(self, position, features, bar_idx):
        if bar_idx - position.entry_bar_idx >= 5:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        StrategyBase()


def test_dummy_strategy_instantiates():
    s = DummyStrategy()
    assert s.name == "dummy"
    assert s.hold_days == 0


def test_prepare_features_returns_dataframe():
    s = DummyStrategy()
    df_minute = pd.DataFrame({"close": [100.0, 101, 102, 103, 104]})
    df_daily = pd.DataFrame()
    out = s.prepare_features(df_minute, df_daily)
    assert isinstance(out, pd.DataFrame)
    assert "prev_close" in out.columns


def test_entry_signal_fires_at_idx_10():
    s = DummyStrategy()
    features = pd.DataFrame({"prev_close": range(20)})
    order = s.entry_signal(features, bar_idx=10, stock_code="005930")
    assert order is not None
    assert order.stock_code == "005930"
    assert order.budget_ratio == 0.2
    assert order.priority == 1


def test_entry_signal_returns_none_otherwise():
    s = DummyStrategy()
    features = pd.DataFrame({"prev_close": range(20)})
    assert s.entry_signal(features, bar_idx=5, stock_code="005930") is None


def test_exit_signal_fires_after_5_bars():
    s = DummyStrategy()
    pos = Position(
        stock_code="005930", entry_bar_idx=10, entry_price=70000.0,
        quantity=100, entry_date="20260401",
    )
    features = pd.DataFrame()
    assert s.exit_signal(pos, features, bar_idx=14) is None
    order = s.exit_signal(pos, features, bar_idx=15)
    assert order is not None
    assert order.reason == "hold_limit"


def test_position_dataclass_fields():
    pos = Position(
        stock_code="005930",
        entry_bar_idx=10,
        entry_price=70000.0,
        quantity=100,
        entry_date="20260401",
    )
    assert pos.stock_code == "005930"
    assert pos.entry_bar_idx == 10
    assert pos.entry_price == 70000.0
    assert pos.quantity == 100
    assert pos.entry_date == "20260401"


def test_entry_order_dataclass_fields():
    o = EntryOrder(stock_code="005930", priority=1, budget_ratio=0.25)
    assert o.stock_code == "005930"
    assert o.priority == 1
    assert o.budget_ratio == 0.25


def test_exit_order_dataclass_fields():
    o = ExitOrder(stock_code="005930", reason="tp")
    assert o.stock_code == "005930"
    assert o.reason == "tp"
