"""VWAP 반등 (VWAP Bounce) — 당일 누적 VWAP 대비 하회 후 반등 매수."""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class VWAPBounceStrategy(StrategyBase):
    name = "vwap_bounce"
    hold_days = 0

    param_space = {
        "vwap_deviation_pct": {"type": "float", "low": -3.0, "high": -0.3, "step": 0.3},
        "rebound_min_bars": {"type": "int", "low": 1, "high": 10, "step": 1},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.3},
    }

    def __init__(
        self,
        vwap_deviation_pct: float = -1.0,
        rebound_min_bars: int = 3,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.vwap_deviation_pct = vwap_deviation_pct
        self.rebound_min_bars = rebound_min_bars
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_vwap": [], "deviation_pct": [], "prev_close": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()
        typ = (df["high"] + df["low"] + df["close"]) / 3.0
        df["_pv"] = typ * df["volume"]
        df["_cum_pv"] = df.groupby("trade_date")["_pv"].cumsum()
        df["_cum_v"] = df.groupby("trade_date")["volume"].cumsum()
        df["vwap"] = df["_cum_pv"] / df["_cum_v"].replace(0, float("nan"))
        df["prev_vwap"] = df.groupby("trade_date")["vwap"].shift(1)
        df["prev_close"] = df.groupby("trade_date")["close"].shift(1)
        df["deviation_pct"] = (df["prev_close"] - df["prev_vwap"]) / df["prev_vwap"] * 100.0
        return df[["prev_vwap", "deviation_pct", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["close"]):
            return None
        deviation_pct = arr["deviation_pct"][bar_idx]
        prev_close = arr["prev_close"][bar_idx]
        if pd.isna(deviation_pct) or pd.isna(prev_close):
            return None
        bar_in_day = arr["bar_in_day"][bar_idx]
        if bar_in_day < self.rebound_min_bars:
            return None
        if bar_in_day > self.entry_window_end_bar:
            return None
        if deviation_pct > self.vwap_deviation_pct:
            return None
        if arr["close"][bar_idx] <= prev_close:
            return None
        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self, position, features, bar_idx, current_price: Optional[float] = None
    ) -> Optional[ExitOrder]:
        if current_price is None or position.entry_price <= 0:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.take_profit_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.stop_loss_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None
