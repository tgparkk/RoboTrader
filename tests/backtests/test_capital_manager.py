"""backtests.common.capital_manager 단위 테스트."""
import pytest

from backtests.common.capital_manager import CapitalManager, InsufficientCapital


def test_initial_capital():
    cm = CapitalManager(initial_capital=10_000_000)
    assert cm.available_cash == 10_000_000
    assert cm.total_invested == 0


def test_buy_deducts_cash():
    cm = CapitalManager(initial_capital=10_000_000)
    cm.process_buy(stock_code="005930", cost=3_000_000)
    assert cm.available_cash == 7_000_000
    assert cm.total_invested == 3_000_000


def test_buy_raises_when_insufficient():
    cm = CapitalManager(initial_capital=10_000_000)
    with pytest.raises(InsufficientCapital):
        cm.process_buy(stock_code="005930", cost=11_000_000)


def test_sell_returns_proceed():
    cm = CapitalManager(initial_capital=10_000_000)
    cm.process_buy(stock_code="005930", cost=3_000_000)
    cm.process_sell(stock_code="005930", proceed=3_500_000, original_cost=3_000_000)
    assert cm.available_cash == 10_500_000
    assert cm.total_invested == 0


def test_sell_first_then_buy_sequence():
    """매도로 확보한 현금을 같은 시점에 매수에 사용 가능."""
    cm = CapitalManager(initial_capital=10_000_000)
    cm.process_buy(stock_code="A", cost=9_000_000)
    # 현금 1,000,000 남음. 바로는 500만원 매수 불가
    with pytest.raises(InsufficientCapital):
        cm.process_buy(stock_code="B", cost=5_000_000)
    # 매도 후에는 가능
    cm.process_sell(stock_code="A", proceed=9_500_000, original_cost=9_000_000)
    cm.process_buy(stock_code="B", cost=5_000_000)
    assert cm.available_cash == 5_500_000


def test_can_afford_helper():
    cm = CapitalManager(initial_capital=10_000_000)
    cm.process_buy(stock_code="A", cost=3_000_000)
    assert cm.can_afford(7_000_000)
    assert not cm.can_afford(7_000_001)


def test_step_orders_applies_sells_before_buys():
    """step_orders 는 매도 주문을 먼저 처리한 뒤 매수 주문을 처리."""
    cm = CapitalManager(initial_capital=10_000_000)
    cm.process_buy(stock_code="A", cost=9_000_000)
    sell_orders = [
        {"stock_code": "A", "proceed": 9_500_000, "original_cost": 9_000_000},
    ]
    buy_orders = [
        {"stock_code": "B", "cost": 4_000_000, "priority": 1},
        {"stock_code": "C", "cost": 4_000_000, "priority": 2},
        {"stock_code": "D", "cost": 4_000_000, "priority": 3},  # 자금 부족
    ]
    executed = cm.step_orders(sell_orders=sell_orders, buy_orders=buy_orders)
    assert len(executed["sells"]) == 1
    assert len(executed["buys"]) == 2  # B, C 체결 / D 탈락
    assert {o["stock_code"] for o in executed["buys"]} == {"B", "C"}
    assert len(executed["rejected_buys"]) == 1
    assert executed["rejected_buys"][0]["stock_code"] == "D"


def test_step_orders_respects_priority():
    """priority 값이 낮을수록 먼저 체결 시도."""
    cm = CapitalManager(initial_capital=5_000_000)
    buy_orders = [
        {"stock_code": "HIGH_PRIO", "cost": 4_000_000, "priority": 1},
        {"stock_code": "LOW_PRIO", "cost": 4_000_000, "priority": 2},  # 자금 부족
    ]
    executed = cm.step_orders(sell_orders=[], buy_orders=buy_orders)
    assert executed["buys"][0]["stock_code"] == "HIGH_PRIO"
    assert executed["rejected_buys"][0]["stock_code"] == "LOW_PRIO"


def test_step_orders_empty_inputs():
    cm = CapitalManager(initial_capital=10_000_000)
    executed = cm.step_orders(sell_orders=[], buy_orders=[])
    assert executed == {"sells": [], "buys": [], "rejected_buys": []}
    assert cm.available_cash == 10_000_000
