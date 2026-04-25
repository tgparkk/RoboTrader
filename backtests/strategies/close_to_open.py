"""close_to_open — 강한 종가(전일대비 ≥ +X%) 매수, 익일 시가 매도. hold_days=1."""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class CloseToOpenStrategy(StrategyBase):
    name = "close_to_open"
    hold_days = 1

    param_space = {
        "min_change_pct": {"type": "float", "low": 1.5, "high": 6.0, "step": 0.5},
        "entry_hhmm_min": {"type": "int", "low": 1430, "high": 1500, "step": 10},
        "entry_hhmm_max": {"type": "int", "low": 1500, "high": 1520, "step": 5},
    }

    def __init__(
        self,
        min_change_pct: float = 3.0,
        entry_hhmm_min: int = 1450,
        entry_hhmm_max: int = 1500,
        budget_ratio: float = 0.20,
    ):
        self.min_change_pct = min_change_pct
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
                {"today_change_pct": [], "close": [], "hhmm": []},
                index=df_minute.index,
            )
        df = df_minute.copy()

        # 전일 daily close (shift(1))
        prev_close_map = self._build_prev_close_map(df_daily)
        df["prev_daily_close"] = df["trade_date"].map(prev_close_map)

        # 분봉 close 가 전일 daily close 대비 변화율 (현재 분봉 기준)
        df["today_change_pct"] = (
            (df["close"] - df["prev_daily_close"]) / df["prev_daily_close"] * 100.0
        )

        df["hhmm"] = df["trade_time"].astype(str).str[:4].astype(int)
        return df[["today_change_pct", "close", "hhmm"]]

    @staticmethod
    def _build_prev_close_map(df_daily: pd.DataFrame) -> dict:
        if df_daily is None or df_daily.empty:
            return {}
        d = df_daily.sort_values("trade_date").copy()
        d["prev_close"] = d["close"].shift(1)
        return dict(zip(d["trade_date"], d["prev_close"]))

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["close"]):
            return None
        today_change_pct = arr["today_change_pct"][bar_idx]
        if pd.isna(today_change_pct):
            return None
        hhmm = arr["hhmm"][bar_idx]
        if not (self.entry_hhmm_min <= hhmm <= self.entry_hhmm_max):
            return None
        if today_change_pct < self.min_change_pct:
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
