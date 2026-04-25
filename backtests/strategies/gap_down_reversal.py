"""갭다운 역행 (Gap-Down Reversal) — 시가 갭다운 후 반등 매수."""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class GapDownReversalStrategy(StrategyBase):
    name = "gap_down_reversal"
    hold_days = 0

    param_space = {
        "gap_threshold_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
        "reversal_threshold_pct": {"type": "float", "low": 0.3, "high": 3.0, "step": 0.3},
        "entry_window_end_bar": {"type": "int", "low": 30, "high": 120, "step": 15},
        "take_profit_pct": {"type": "float", "low": 1.5, "high": 6.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -5.0, "high": -1.5, "step": 0.5},
    }

    def __init__(
        self,
        gap_threshold_pct: float = -2.0,
        reversal_threshold_pct: float = 1.0,
        entry_window_end_bar: int = 60,
        take_profit_pct: float = 3.0,
        stop_loss_pct: float = -2.0,
        budget_ratio: float = 0.30,
    ):
        self.gap_threshold_pct = gap_threshold_pct
        self.reversal_threshold_pct = reversal_threshold_pct
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"gap_pct": [], "day_low_so_far": [], "rebound_pct": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )

        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        # 각 minute trade_date 에 대해 "그 이전 거래일의 daily close" 맵 (look-ahead 없음)
        prev_close_by_date = self._build_prev_close_map(df, df_daily)
        df["prev_close"] = df["trade_date"].map(prev_close_by_date)

        # 시가갭 (각 날의 첫 bar open 기준)
        day_open_per_date = df.groupby("trade_date")["open"].first()
        df["day_open"] = df["trade_date"].map(day_open_per_date)
        df["gap_pct"] = (df["day_open"] - df["prev_close"]) / df["prev_close"] * 100.0

        # 당일 누적 최저가 (bar 진행에 따라 갱신)
        df["day_low_so_far"] = df.groupby("trade_date")["low"].cummin()

        # 반등률: (현재 close - day_low_so_far) / day_low_so_far * 100
        df["rebound_pct"] = (
            (df["close"] - df["day_low_so_far"]) / df["day_low_so_far"] * 100.0
        )

        return df[["gap_pct", "day_low_so_far", "rebound_pct", "close", "bar_in_day"]]

    @staticmethod
    def _build_prev_close_map(df_minute, df_daily):
        """각 minute trade_date 에 대해 그 전 거래일 (< 해당 날짜) 의 daily close 반환.

        daily 에 같은 날짜 데이터가 있어도 '해당일 이전' 만 참조 → look-ahead 없음.
        """
        if df_daily is None or df_daily.empty:
            return {}
        daily = df_daily.sort_values("trade_date").copy()
        daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
        result = {}
        for md in df_minute["trade_date"].unique():
            prior = daily[daily["trade_date"] < md]
            if not prior.empty:
                result[md] = float(prior["close"].iloc[-1])
        return result

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["close"]):
            return None
        if arr["bar_in_day"][bar_idx] > self.entry_window_end_bar:
            return None
        gap_pct = arr["gap_pct"][bar_idx]
        if pd.isna(gap_pct) or gap_pct > self.gap_threshold_pct:
            return None
        rebound_pct = arr["rebound_pct"][bar_idx]
        if pd.isna(rebound_pct) or rebound_pct < self.reversal_threshold_pct:
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
