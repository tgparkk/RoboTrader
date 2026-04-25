"""post_drop_rebound — 전일 -X% 이상 낙폭 + 당일 거래량 급증 → 1~2일 홀드."""
from typing import Optional

import pandas as pd

from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class PostDropReboundStrategy(StrategyBase):
    name = "post_drop_rebound"
    hold_days = 2

    param_space = {
        "max_prev_return_pct": {"type": "float", "low": -8.0, "high": -3.0, "step": 0.5},
        "vol_mult": {"type": "float", "low": 1.5, "high": 4.0, "step": 0.25},
        "vol_lookback_days": {"type": "int", "low": 3, "high": 10, "step": 1},
        "entry_hhmm_min": {"type": "int", "low": 1430, "high": 1500, "step": 10},
    }

    def __init__(
        self,
        max_prev_return_pct: float = -5.0,
        vol_mult: float = 2.0,
        vol_lookback_days: int = 5,
        entry_hhmm_min: int = 1450,
        entry_hhmm_max: int = 1500,
        budget_ratio: float = 0.20,
    ):
        self.max_prev_return_pct = max_prev_return_pct
        self.vol_mult = vol_mult
        self.vol_lookback_days = vol_lookback_days
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
                {"prev_return_pct": [], "vol_ratio": [], "hhmm": []},
                index=df_minute.index,
            )
        df = df_minute.copy()

        prev_return_map, avg_vol_map = self._build_daily_maps(df_daily)
        df["prev_return_pct"] = df["trade_date"].map(prev_return_map)
        df["avg_vol_nd"] = df["trade_date"].map(avg_vol_map)

        # 당일 누적 거래량 / N일 평균 (분봉 cumsum, look-ahead 없음 — 현재 시점까지만 누적)
        df["cum_vol_today"] = df.groupby("trade_date")["volume"].cumsum()
        df["vol_ratio"] = df["cum_vol_today"] / df["avg_vol_nd"].replace(0, float("nan"))

        df["hhmm"] = df["trade_time"].astype(str).str[:4].astype(int)
        return df[["prev_return_pct", "vol_ratio", "hhmm"]]

    def _build_daily_maps(self, df_daily: pd.DataFrame):
        if df_daily is None or df_daily.empty:
            return {}, {}
        d = df_daily.sort_values("trade_date").copy()
        d["prev_close"] = d["close"].shift(1)
        d["prev_prev_close"] = d["close"].shift(2)
        d["prev_return_pct"] = (
            (d["prev_close"] - d["prev_prev_close"]) / d["prev_prev_close"] * 100.0
        )
        d["avg_vol_nd"] = (
            d["volume"].rolling(self.vol_lookback_days, min_periods=1).mean().shift(1)
        )
        return (
            dict(zip(d["trade_date"], d["prev_return_pct"])),
            dict(zip(d["trade_date"], d["avg_vol_nd"])),
        )

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_return_pct"]) or pd.isna(row["vol_ratio"]):
            return None
        if not (self.entry_hhmm_min <= row["hhmm"] <= self.entry_hhmm_max):
            return None
        if row["prev_return_pct"] > self.max_prev_return_pct:
            return None
        if row["vol_ratio"] < self.vol_mult:
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
