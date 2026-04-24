"""갭업 추격 (Gap-Up Continuation) — 시가 갭업 + 거래량 급증 추격."""
from typing import Dict, Optional, Tuple

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


BARS_PER_TRADING_DAY = 390


class GapUpChaseStrategy(StrategyBase):
    name = "gap_up_chase"
    hold_days = 0

    param_space = {
        "gap_threshold_pct": {"type": "float", "low": 1.5, "high": 7.0, "step": 0.5},
        "volume_mult": {"type": "float", "low": 1.5, "high": 5.0, "step": 0.5},
        "entry_window_end_bar": {"type": "int", "low": 15, "high": 90, "step": 15},
        "take_profit_pct": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -4.0, "high": -1.0, "step": 0.5},
    }

    def __init__(
        self,
        gap_threshold_pct: float = 3.0,
        volume_mult: float = 2.0,
        entry_window_end_bar: int = 30,
        take_profit_pct: float = 4.0,
        stop_loss_pct: float = -2.0,
        budget_ratio: float = 0.30,
    ):
        self.gap_threshold_pct = gap_threshold_pct
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
                {"gap_pct": [], "vol_ratio": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )

        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        # 각 minute trade_date 에 대해 prev_close + avg_vol_5d (prior-date lookup).
        prev_close_map, avg_vol_map = self._build_daily_context_maps(df, df_daily)
        df["prev_close"] = df["trade_date"].map(prev_close_map)
        df["avg_vol_5d"] = df["trade_date"].map(avg_vol_map)

        # gap%
        day_open_per_date = df.groupby("trade_date")["open"].first()
        df["day_open"] = df["trade_date"].map(day_open_per_date)
        df["gap_pct"] = (df["day_open"] - df["prev_close"]) / df["prev_close"] * 100.0

        # 분봉 거래량 비율 = bar_vol / 과거 5일 daily-average / 390 (per-bar avg)
        # 실데이터: daily.volume = 당일 분봉 volume 합계. bar_vol / (daily_avg_vol / 390)
        df["vol_ratio"] = df["volume"] / (df["avg_vol_5d"] / BARS_PER_TRADING_DAY)

        return df[["gap_pct", "vol_ratio", "close", "bar_in_day"]]

    @staticmethod
    def _build_daily_context_maps(
        df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """각 minute trade_date 에 대해 (prev_close, avg_vol_5d) — prior-date lookup.

        < 해당 date 의 daily 행만 참조 → look-ahead 없음.
        """
        if df_daily is None or df_daily.empty:
            return {}, {}
        d = df_daily.sort_values("trade_date").copy()
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
        d["avg_vol_5d"] = d["volume"].rolling(5, min_periods=1).mean()

        prev_close_map: Dict[str, float] = {}
        avg_vol_map: Dict[str, float] = {}
        for md in df_minute["trade_date"].unique():
            prior = d[d["trade_date"] < md]
            if not prior.empty:
                prev_close_map[md] = float(prior["close"].iloc[-1])
                avg_vol_map[md] = float(prior["avg_vol_5d"].iloc[-1])
        return prev_close_map, avg_vol_map

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]

        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        if pd.isna(row["gap_pct"]) or row["gap_pct"] < self.gap_threshold_pct:
            return None
        if pd.isna(row["vol_ratio"]) or row["vol_ratio"] < self.volume_mult:
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
        if current_price is None or position.entry_price <= 0:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.take_profit_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.stop_loss_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None
