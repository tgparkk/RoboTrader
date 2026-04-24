"""RSI 과매도 반등 전략 — 분봉 RSI oversold 후 반전 매수."""
from typing import Optional

import numpy as np
import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class RSIOversoldStrategy(StrategyBase):
    name = "rsi_oversold"
    hold_days = 0

    param_space = {
        "rsi_period": {"type": "int", "low": 7, "high": 21, "step": 2},
        "oversold_threshold": {"type": "float", "low": 15.0, "high": 35.0, "step": 2.5},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 4.0, "step": 0.25},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_threshold: float = 30.0,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_rsi": [], "prev_prev_rsi": [], "prev_close": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        def _rsi_per_day(g: pd.DataFrame) -> pd.DataFrame:
            close = g["close"].astype(float)
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(self.rsi_period, min_periods=self.rsi_period).mean()
            avg_loss = loss.rolling(self.rsi_period, min_periods=self.rsi_period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100.0 - 100.0 / (1.0 + rs)
            return pd.DataFrame({
                "prev_rsi": rsi.shift(1),
                "prev_prev_rsi": rsi.shift(2),
                "prev_close": close.shift(1),
            }, index=g.index)

        rsi_df = df.groupby("trade_date", group_keys=False).apply(_rsi_per_day)
        df = df.join(rsi_df)
        return df[["prev_rsi", "prev_prev_rsi", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_rsi"]) or pd.isna(row["prev_prev_rsi"]) or pd.isna(row["prev_close"]):
            return None
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        # 전 또는 전전 bar 가 oversold 였어야 함
        if row["prev_rsi"] >= self.oversold_threshold and row["prev_prev_rsi"] >= self.oversold_threshold:
            return None
        # RSI 반전 (상승 전환)
        if row["prev_rsi"] <= row["prev_prev_rsi"]:
            return None
        # 가격 반등 확인
        if row["close"] <= row["prev_close"]:
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
