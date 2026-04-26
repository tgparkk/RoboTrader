"""상한가 따라잡기 (Limit-Up Chase) — 전일 close 대비 큰 상승 + 거래량 폭증 추격.

한국 일일 한도 +30% 직전(`limit_proximity_pct`) 까지만 추격.
엔진의 VOLUME_LIMIT_RATIO + LIMIT_PRICE_BUFFER 가 호가·유동성 마찰 강제.
"""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class LimitUpChaseStrategy(StrategyBase):
    name = "limit_up_chase"
    hold_days = 0

    param_space = {
        "chase_threshold_pct": {"type": "float", "low": 8.0, "high": 22.0, "step": 1.0},
        "limit_proximity_pct": {"type": "float", "low": 24.0, "high": 29.0, "step": 0.5},
        "vol_lookback_bars": {"type": "int", "low": 10, "high": 30, "step": 5},
        "volume_mult": {"type": "float", "low": 3.0, "high": 10.0, "step": 0.5},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 300, "step": 30},
        "take_profit_pct": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -5.0, "high": -1.5, "step": 0.5},
    }

    def __init__(
        self,
        chase_threshold_pct: float = 15.0,
        limit_proximity_pct: float = 27.0,
        vol_lookback_bars: int = 15,
        volume_mult: float = 5.0,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 4.0,
        stop_loss_pct: float = -2.5,
        budget_ratio: float = 0.20,
    ):
        self.chase_threshold_pct = chase_threshold_pct
        self.limit_proximity_pct = limit_proximity_pct
        self.vol_lookback_bars = vol_lookback_bars
        self.volume_mult = volume_mult
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_close": [], "price_change_pct": [], "vol_ratio": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        # 전일 close (daily, shift(1))
        prev_close_map = self._build_prev_close_map(df_daily)
        df["prev_close"] = df["trade_date"].map(prev_close_map)
        df["price_change_pct"] = (df["close"] - df["prev_close"]) / df["prev_close"] * 100.0

        # 분봉 거래량 비율 (당일 내 rolling)
        def _vol_per_day(g: pd.DataFrame) -> pd.DataFrame:
            vol = g["volume"].astype(float)
            roll = vol.rolling(
                self.vol_lookback_bars, min_periods=self.vol_lookback_bars
            ).mean().shift(1)
            return pd.DataFrame({
                "vol_ratio": vol / roll.replace(0, float("nan")),
            }, index=g.index)

        per_day = df.groupby("trade_date", group_keys=False).apply(_vol_per_day)
        df = df.join(per_day)

        return df[
            ["prev_close", "price_change_pct", "vol_ratio", "close", "bar_in_day"]
        ]

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
        prev_close = arr["prev_close"][bar_idx]
        price_change_pct = arr["price_change_pct"][bar_idx]
        vol_ratio = arr["vol_ratio"][bar_idx]
        if pd.isna(prev_close) or pd.isna(price_change_pct) or pd.isna(vol_ratio):
            return None
        if arr["bar_in_day"][bar_idx] > self.entry_window_end_bar:
            return None
        if price_change_pct < self.chase_threshold_pct:
            return None
        if price_change_pct >= self.limit_proximity_pct:
            return None
        if vol_ratio < self.volume_mult:
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
