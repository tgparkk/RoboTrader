"""거래량 급증 추격 (Volume Surge Chase) — 분봉 거래량 폭증 + 가격 추종 매수."""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class VolumeSurgeStrategy(StrategyBase):
    name = "volume_surge"
    hold_days = 0

    param_space = {
        "vol_lookback_bars": {"type": "int", "low": 5, "high": 30, "step": 5},
        "volume_mult": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
        "entry_window_start_bar": {"type": "int", "low": 5, "high": 60, "step": 5},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        vol_lookback_bars: int = 10,
        volume_mult: float = 3.0,
        entry_window_start_bar: int = 10,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.5,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.vol_lookback_bars = vol_lookback_bars
        self.volume_mult = volume_mult
        self.entry_window_start_bar = entry_window_start_bar
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"vol_ratio": [], "prev_close": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        def _per_day(g: pd.DataFrame) -> pd.DataFrame:
            vol = g["volume"].astype(float)
            roll_mean = vol.rolling(
                self.vol_lookback_bars, min_periods=self.vol_lookback_bars
            ).mean().shift(1)
            ratio = vol / roll_mean.replace(0, float("nan"))
            return pd.DataFrame({
                "vol_ratio": ratio,
                "prev_close": g["close"].shift(1),
            }, index=g.index)

        per_day = df.groupby("trade_date", group_keys=False).apply(_per_day)
        df = df.join(per_day)
        return df[["vol_ratio", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["close"]):
            return None
        vol_ratio = arr["vol_ratio"][bar_idx]
        prev_close = arr["prev_close"][bar_idx]
        if pd.isna(vol_ratio) or pd.isna(prev_close):
            return None
        bar_in_day = arr["bar_in_day"][bar_idx]
        if bar_in_day < self.entry_window_start_bar:
            return None
        if bar_in_day > self.entry_window_end_bar:
            return None
        if vol_ratio < self.volume_mult:
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
