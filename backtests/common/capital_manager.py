"""자금 제약·우선순위 관리 — 원칙 2 강제."""
from typing import Dict, List


class InsufficientCapital(Exception):
    """가용 자금 초과 주문."""


class CapitalManager:
    def __init__(self, initial_capital: float):
        self._cash = float(initial_capital)
        self._invested = 0.0

    @property
    def available_cash(self) -> float:
        return self._cash

    @property
    def total_invested(self) -> float:
        return self._invested

    def can_afford(self, cost: float) -> bool:
        return cost <= self._cash

    def process_buy(self, stock_code: str, cost: float) -> None:
        if cost > self._cash:
            raise InsufficientCapital(
                f"매수 {stock_code} 비용 {cost:,.0f} > 가용 {self._cash:,.0f}"
            )
        self._cash -= cost
        self._invested += cost

    def process_sell(self, stock_code: str, proceed: float, original_cost: float) -> None:
        self._cash += proceed
        self._invested = max(0.0, self._invested - original_cost)

    def step_orders(
        self, sell_orders: List[Dict], buy_orders: List[Dict]
    ) -> Dict[str, List[Dict]]:
        """한 시점의 주문들을 처리: 매도 먼저, 그 다음 매수 (우선순위 오름차순)."""
        executed_sells = []
        for order in sell_orders:
            self.process_sell(
                stock_code=order["stock_code"],
                proceed=order["proceed"],
                original_cost=order["original_cost"],
            )
            executed_sells.append(order)

        executed_buys = []
        rejected_buys = []
        sorted_buys = sorted(buy_orders, key=lambda o: o.get("priority", 0))
        for order in sorted_buys:
            if self.can_afford(order["cost"]):
                self.process_buy(stock_code=order["stock_code"], cost=order["cost"])
                executed_buys.append(order)
            else:
                rejected_buys.append(order)

        return {
            "sells": executed_sells,
            "buys": executed_buys,
            "rejected_buys": rejected_buys,
        }
