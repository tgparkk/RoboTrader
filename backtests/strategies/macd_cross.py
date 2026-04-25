"""macd_cross — Daily MACD 히스토그램 음→양 골든크로스, 2일 홀드."""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class MACDCrossStrategy(StrategyBase):
    name = "macd_cross"
    hold_days = 2

    param_space = {
        "fast_period": {"type": "int", "low": 8, "high": 16, "step": 2},
        "slow_period": {"type": "int", "low": 20, "high": 40, "step": 2},
        "signal_period": {"type": "int", "low": 7, "high": 12, "step": 1},
        "entry_hhmm_min": {"type": "int", "low": 1430, "high": 1500, "step": 10},
    }

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        entry_hhmm_min: int = 1450,
        entry_hhmm_max: int = 1500,
        budget_ratio: float = 0.20,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.entry_hhmm_min = entry_hhmm_min
        self.entry_hhmm_max = entry_hhmm_max
        self.budget_ratio = budget_ratio
        self._last_df_minute: Optional[pd.DataFrame] = None

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        self._last_df_minute = df_minute
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_hist": [], "prev_prev_hist": [], "hhmm": []},
                index=df_minute.index,
            )
        df = df_minute.copy()

        prev_hist_map, prev_prev_hist_map = self._build_macd_maps(df_daily)
        df["prev_hist"] = df["trade_date"].map(prev_hist_map)
        df["prev_prev_hist"] = df["trade_date"].map(prev_prev_hist_map)
        df["hhmm"] = df["trade_time"].astype(str).str[:4].astype(int)
        return df[["prev_hist", "prev_prev_hist", "hhmm"]]

    def _build_macd_maps(self, df_daily: pd.DataFrame):
        if df_daily is None or df_daily.empty:
            return {}, {}
        d = df_daily.sort_values("trade_date").copy()
        close = d["close"].astype(float)
        ema_fast = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_period, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=self.signal_period, adjust=False).mean()
        hist = macd - signal
        prev_hist = hist.shift(1)
        prev_prev_hist = hist.shift(2)
        return (
            dict(zip(d["trade_date"], prev_hist)),
            dict(zip(d["trade_date"], prev_prev_hist)),
        )

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["hhmm"]):
            return None
        prev_hist = arr["prev_hist"][bar_idx]
        prev_prev_hist = arr["prev_prev_hist"][bar_idx]
        if pd.isna(prev_hist) or pd.isna(prev_prev_hist):
            return None
        hhmm = arr["hhmm"][bar_idx]
        if not (self.entry_hhmm_min <= hhmm <= self.entry_hhmm_max):
            return None
        if not (prev_prev_hist < 0 and prev_hist >= 0):
            return None
        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self,
        position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        if self._last_df_minute is None:
            return None
        days_held = count_trading_days_between(
            self._last_df_minute,
            from_idx=position.entry_bar_idx,
            to_idx=bar_idx,
        )
        if days_held >= self.hold_days:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
