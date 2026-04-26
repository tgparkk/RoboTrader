"""장중 눌림목 (Intraday Pullback to 20EMA) — 상승추세 중 EMA 근접 눌림 후 반등."""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class IntradayPullbackStrategy(StrategyBase):
    name = "intraday_pullback"
    hold_days = 0

    param_space = {
        "ema_period": {"type": "int", "low": 10, "high": 40, "step": 5},
        "pullback_lookback_bars": {"type": "int", "low": 3, "high": 15, "step": 1},
        "proximity_pct": {"type": "float", "low": 0.0, "high": 1.5, "step": 0.1},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 4.0, "step": 0.25},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        ema_period: int = 20,
        pullback_lookback_bars: int = 5,
        proximity_pct: float = 0.5,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.ema_period = ema_period
        self.pullback_lookback_bars = pullback_lookback_bars
        self.proximity_pct = proximity_pct
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_ema": [], "recent_high": [], "recent_low": [],
                 "prev_close": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        def _per_day(g: pd.DataFrame) -> pd.DataFrame:
            close = g["close"].astype(float)
            high = g["high"].astype(float)
            low = g["low"].astype(float)
            ema = close.ewm(span=self.ema_period, adjust=False).mean()
            recent_high = high.rolling(
                self.pullback_lookback_bars, min_periods=self.pullback_lookback_bars
            ).max().shift(1)
            recent_low = low.rolling(
                self.pullback_lookback_bars, min_periods=self.pullback_lookback_bars
            ).min().shift(1)
            return pd.DataFrame({
                "prev_ema": ema.shift(1),
                "recent_high": recent_high,
                "recent_low": recent_low,
                "prev_close": close.shift(1),
            }, index=g.index)

        per_day = df.groupby("trade_date", group_keys=False).apply(_per_day)
        df = df.join(per_day)
        return df[
            ["prev_ema", "recent_high", "recent_low", "prev_close", "close", "bar_in_day"]
        ]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["close"]):
            return None
        prev_ema = arr["prev_ema"][bar_idx]
        recent_high = arr["recent_high"][bar_idx]
        recent_low = arr["recent_low"][bar_idx]
        prev_close = arr["prev_close"][bar_idx]
        if (
            pd.isna(prev_ema)
            or pd.isna(recent_high)
            or pd.isna(recent_low)
            or pd.isna(prev_close)
        ):
            return None
        if arr["bar_in_day"][bar_idx] > self.entry_window_end_bar:
            return None
        if recent_high <= prev_ema:
            return None
        proximity_threshold = prev_ema * (1.0 + self.proximity_pct / 100.0)
        if recent_low > proximity_threshold:
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
