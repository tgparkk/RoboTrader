"""시간순 백테스트 엔진 — 3원칙 강제 실행."""
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from backtests.common.capital_manager import CapitalManager
from backtests.common.execution_model import (
    ExecutionModel, BUY_COMMISSION, SELL_COMMISSION,
)
from backtests.common.metrics import compute_all_metrics
from backtests.strategies.base import StrategyBase, Position


@dataclass
class BacktestResult:
    trades: List[Dict] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    metrics: Dict[str, float] = field(default_factory=dict)
    final_equity: float = 0.0


class BacktestEngine:
    def __init__(
        self,
        strategy: StrategyBase,
        initial_capital: float,
        universe: List[str],
        minute_df_by_code: Dict[str, pd.DataFrame],
        daily_df_by_code: Dict[str, pd.DataFrame],
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.universe = universe
        self.minute_df_by_code = minute_df_by_code
        self.daily_df_by_code = daily_df_by_code

    def run(self) -> BacktestResult:
        cm = CapitalManager(initial_capital=self.initial_capital)
        positions: Dict[str, Position] = {}
        trades: List[Dict] = []
        equity_points: List[float] = []

        # 종목별 피처 사전 계산
        features_by_code = {
            code: self.strategy.prepare_features(
                self.minute_df_by_code[code],
                self.daily_df_by_code.get(code, pd.DataFrame()),
            )
            for code in self.universe
        }

        n_bars = max(len(df) for df in self.minute_df_by_code.values())

        for t in range(n_bars):
            sell_orders: List[Dict] = []
            buy_orders: List[Dict] = []

            # 1. 보유 포지션 exit 체크
            for code, pos in list(positions.items()):
                features = features_by_code[code]
                if t >= len(features):
                    continue
                exit_order = self.strategy.exit_signal(pos, features, bar_idx=t)
                if exit_order is None:
                    continue
                fill_idx = ExecutionModel.next_fill_index(t)
                df_min = self.minute_df_by_code[code]
                if fill_idx >= len(df_min):
                    continue
                next_open = float(df_min["open"].iloc[fill_idx])
                sell_fill = ExecutionModel.compute_sell_fill_price(next_open)
                proceed = sell_fill * pos.quantity * (1 - SELL_COMMISSION)
                original_cost = pos.entry_price * pos.quantity
                sell_orders.append({
                    "stock_code": code,
                    "proceed": proceed,
                    "original_cost": original_cost,
                    "exit_bar_idx": fill_idx,
                    "exit_price": sell_fill,
                    "reason": exit_order.reason,
                    "position": pos,
                })

            # 2. 매수 신호 수집
            for code in self.universe:
                if code in positions:
                    continue
                features = features_by_code[code]
                if t >= len(features):
                    continue
                entry_order = self.strategy.entry_signal(
                    features, bar_idx=t, stock_code=code
                )
                if entry_order is None:
                    continue
                fill_idx = ExecutionModel.next_fill_index(t)
                df_min = self.minute_df_by_code[code]
                if fill_idx >= len(df_min):
                    continue
                next_open = float(df_min["open"].iloc[fill_idx])
                buy_fill = ExecutionModel.compute_buy_fill_price(next_open)
                budget = cm.available_cash * entry_order.budget_ratio
                quantity = int(budget / (buy_fill * (1 + BUY_COMMISSION)))
                if quantity <= 0:
                    continue
                cost = buy_fill * quantity * (1 + BUY_COMMISSION)
                buy_orders.append({
                    "stock_code": code,
                    "cost": cost,
                    "priority": entry_order.priority,
                    "entry_bar_idx": fill_idx,
                    "entry_price": buy_fill,
                    "quantity": quantity,
                })

            # 3. step_orders — 매도 선처리, 그다음 매수
            executed = cm.step_orders(sell_orders=sell_orders, buy_orders=buy_orders)

            # 4. 체결된 매도: 포지션 제거 + trade 기록
            for s in executed["sells"]:
                pos: Position = s["position"]
                trades.append({
                    "stock_code": pos.stock_code,
                    "entry_bar_idx": pos.entry_bar_idx,
                    "entry_price": pos.entry_price,
                    "exit_bar_idx": s["exit_bar_idx"],
                    "exit_price": s["exit_price"],
                    "quantity": pos.quantity,
                    "pnl": s["proceed"] - s["original_cost"],
                    "reason": s["reason"],
                })
                del positions[pos.stock_code]

            # 5. 체결된 매수: 포지션 추가
            for b in executed["buys"]:
                code = b["stock_code"]
                df_min = self.minute_df_by_code[code]
                positions[code] = Position(
                    stock_code=code,
                    entry_bar_idx=b["entry_bar_idx"],
                    entry_price=b["entry_price"],
                    quantity=b["quantity"],
                    entry_date=str(df_min["trade_date"].iloc[b["entry_bar_idx"]]),
                )

            # 6. equity 스냅샷 (매 bar)
            equity = cm.available_cash + sum(
                p.entry_price * p.quantity for p in positions.values()
            )
            equity_points.append(equity)

        # 포지션 정리: 마지막 bar 종가로 강제 청산
        for code, pos in list(positions.items()):
            df_min = self.minute_df_by_code[code]
            final_close = float(df_min["close"].iloc[-1])
            sell_fill = ExecutionModel.compute_sell_fill_price(final_close)
            proceed = sell_fill * pos.quantity * (1 - SELL_COMMISSION)
            original_cost = pos.entry_price * pos.quantity
            cm.process_sell(stock_code=code, proceed=proceed, original_cost=original_cost)
            trades.append({
                "stock_code": code,
                "entry_bar_idx": pos.entry_bar_idx,
                "entry_price": pos.entry_price,
                "exit_bar_idx": len(df_min) - 1,
                "exit_price": sell_fill,
                "quantity": pos.quantity,
                "pnl": proceed - original_cost,
                "reason": "eod_forced",
            })

        # 마지막 강제청산 반영된 최종 equity 업데이트
        if equity_points:
            equity_points[-1] = cm.available_cash

        equity_series = pd.Series(equity_points)
        pnl_series = pd.Series([t["pnl"] for t in trades]) if trades else pd.Series(dtype=float)
        metrics = compute_all_metrics(
            equity=equity_series,
            trade_pnls=pnl_series,
            trading_days=max(1, n_bars // 390),
        )
        return BacktestResult(
            trades=trades,
            equity_curve=equity_series,
            metrics=metrics,
            final_equity=float(equity_series.iloc[-1]) if len(equity_series) else 0.0,
        )
