"""breakout_52w — 52주 (또는 N일) 신고가 돌파, 2일 홀드."""
from typing import Optional

import pandas as pd

from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class Breakout52wStrategy(StrategyBase):
    name = "breakout_52w"
    hold_days = 2

    param_space = {
        "lookback_days": {"type": "int", "low": 60, "high": 252, "step": 30},
        "buffer_pct": {"type": "float", "low": 0.0, "high": 1.0, "step": 0.1},
        "entry_hhmm_min": {"type": "int", "low": 1430, "high": 1500, "step": 10},
    }

    def __init__(
        self,
        lookback_days: int = 252,
        buffer_pct: float = 0.0,
        entry_hhmm_min: int = 1450,
        entry_hhmm_max: int = 1500,
        budget_ratio: float = 0.20,
    ):
        self.lookback_days = lookback_days
        self.buffer_pct = buffer_pct
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
                {"prev_high": [], "close": [], "hhmm": []},
                index=df_minute.index,
            )
        df = df_minute.copy()

        prev_high_map = self._build_prev_high_map(df_daily)
        df["prev_high"] = df["trade_date"].map(prev_high_map)
        df["hhmm"] = df["trade_time"].astype(str).str[:4].astype(int)
        return df[["prev_high", "close", "hhmm"]]

    def _build_prev_high_map(self, df_daily: pd.DataFrame) -> dict:
        if df_daily is None or df_daily.empty:
            return {}
        d = df_daily.sort_values("trade_date").copy()
        # min_periods 는 lookback 의 1/4 (충분한 표본 확보)
        min_p = max(1, self.lookback_days // 4)
        d["prev_high"] = (
            d["high"].rolling(self.lookback_days, min_periods=min_p).max().shift(1)
        )
        return dict(zip(d["trade_date"], d["prev_high"]))

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_high"]):
            return None
        if not (self.entry_hhmm_min <= row["hhmm"] <= self.entry_hhmm_max):
            return None
        threshold = row["prev_high"] * (1.0 + self.buffer_pct / 100.0)
        if row["close"] <= threshold:
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
