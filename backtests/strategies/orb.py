"""ORB (Opening Range Breakout) — 장 시작 N분 고점 돌파 전략."""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class ORBStrategy(StrategyBase):
    name = "orb"
    hold_days = 0  # 당일 청산

    param_space = {
        "opening_window_min": {"type": "int", "low": 10, "high": 60, "step": 5},
        "breakout_buffer_pct": {"type": "float", "low": 0.0, "high": 0.5, "step": 0.05},
        "entry_end_bar": {"type": "int", "low": 60, "high": 240, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -4.0, "high": -1.0, "step": 0.5},
    }

    def __init__(
        self,
        opening_window_min: int = 30,
        breakout_buffer_pct: float = 0.2,
        entry_end_bar: int = 240,  # 13:00 (당일 시작 기준)
        take_profit_pct: float = 3.0,
        stop_loss_pct: float = -2.0,
        budget_ratio: float = 0.30,
    ):
        self.opening_window_min = opening_window_min
        self.breakout_buffer_pct = breakout_buffer_pct
        self.entry_end_bar = entry_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        """각 거래일에 대해 opening range (OR) high/low 계산 후 분봉에 broadcast."""
        if df_minute.empty:
            return pd.DataFrame(
                {"or_high": [], "or_low": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )

        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        # OR 구간 마스크 (bar 0 ~ opening_window_min-1)
        or_mask = df["bar_in_day"] < self.opening_window_min

        # OR 구간 집계 — 각 date 의 high max, low min
        or_high_per_date = df[or_mask].groupby("trade_date")["high"].max()
        or_low_per_date = df[or_mask].groupby("trade_date")["low"].min()

        df["or_high"] = df["trade_date"].map(or_high_per_date)
        df["or_low"] = df["trade_date"].map(or_low_per_date)

        # OR 구간 내 (bar < opening_window_min) 에서는 OR 값 NaN (아직 확정 안 됨)
        df.loc[or_mask, "or_high"] = float("nan")
        df.loc[or_mask, "or_low"] = float("nan")

        return df[["or_high", "or_low", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["close"]):
            return None
        or_high = arr["or_high"][bar_idx]
        if pd.isna(or_high):
            return None
        if arr["bar_in_day"][bar_idx] > self.entry_end_bar:
            return None
        threshold = or_high * (1 + self.breakout_buffer_pct / 100.0)
        if arr["close"][bar_idx] <= threshold:
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
        # TP/SL only — hold_days=0 이므로 EOD 청산은 엔진이 처리
        if current_price is None or position.entry_price <= 0:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.take_profit_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.stop_loss_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None
