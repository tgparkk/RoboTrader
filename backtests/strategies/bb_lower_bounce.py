"""볼린저 하단 반등 (BB Lower Bounce) — 하단밴드 이탈 후 반등 매수."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class BBLowerBounceStrategy(StrategyBase):
    name = "bb_lower_bounce"
    hold_days = 0

    param_space = {
        "bb_period": {"type": "int", "low": 10, "high": 40, "step": 5},
        "bb_num_std": {"type": "float", "low": 1.5, "high": 3.0, "step": 0.25},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 4.0, "step": 0.25},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        bb_period: int = 20,
        bb_num_std: float = 2.0,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.bb_period = bb_period
        self.bb_num_std = bb_num_std
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_lower": [], "prev_close": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        def _per_day(g):
            m = g["close"].rolling(self.bb_period, min_periods=self.bb_period).mean()
            s = g["close"].rolling(self.bb_period, min_periods=self.bb_period).std()
            lower = (m - self.bb_num_std * s).shift(1)
            prev_close = g["close"].shift(1)
            return pd.DataFrame({"prev_lower": lower, "prev_close": prev_close}, index=g.index)

        bb = df.groupby("trade_date", group_keys=False).apply(_per_day)
        df = df.join(bb)
        return df[["prev_lower", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_lower"]) or pd.isna(row["prev_close"]):
            return None
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        # 현재 close 가 하단밴드 위로 복귀(반등) + 전봉 대비 상승
        if row["close"] <= row["prev_lower"]:
            return None
        if row["close"] <= row["prev_close"]:
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
