"""종가 드리프트 (Closing Drift) — 14:00~14:20 진입, 익일 청산.

라이브 core/strategies/closing_trade_strategy.py 의 backtest 포팅.
overnight hold (hold_days=1) — _last_df_minute + count_trading_days_between 패턴
(weighted_score_full 의 hold_limit 와 동일).
"""
from typing import Optional

import numpy as np
import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class ClosingDriftStrategy(StrategyBase):
    name = "closing_drift"
    hold_days = 1

    param_space = {
        "min_prev_body_pct": {"type": "float", "low": 0.5, "high": 3.0, "step": 0.25},
        "max_day_decline_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
        "entry_hhmm_start": {"type": "int", "low": 1300, "high": 1500, "step": 30},
        "entry_hhmm_end": {"type": "int", "low": 1330, "high": 1520, "step": 10},
        "gap_sl_limit_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
    }

    def __init__(
        self,
        min_prev_body_pct: float = 1.0,
        max_day_decline_pct: float = -3.0,
        entry_hhmm_start: int = 1400,
        entry_hhmm_end: int = 1420,
        gap_sl_limit_pct: float = -3.0,
        budget_ratio: float = 0.20,
    ):
        self.min_prev_body_pct = min_prev_body_pct
        self.max_day_decline_pct = max_day_decline_pct
        self.entry_hhmm_start = entry_hhmm_start
        self.entry_hhmm_end = entry_hhmm_end
        self.gap_sl_limit_pct = gap_sl_limit_pct
        self.budget_ratio = budget_ratio
        self._last_df_minute: Optional[pd.DataFrame] = None

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        self._last_df_minute = df_minute
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_body_pct": [], "day_open": [], "day_low_pct": [],
                 "vwap": [], "close": [], "hhmm": []},
                index=df_minute.index,
            )
        df = df_minute.copy()

        # 전일 body% (daily 에서 shift(1) 로 직전 거래일 close/open)
        prev_body_map = self._build_prev_body_map(df_daily)
        df["prev_body_pct"] = df["trade_date"].map(prev_body_map)

        # 당일 시가, 누적 최저가, 시가 대비 % 하락
        day_open_per_date = df.groupby("trade_date")["open"].first()
        df["day_open"] = df["trade_date"].map(day_open_per_date)
        df["day_low_so_far"] = df.groupby("trade_date")["low"].cummin()
        df["day_low_pct"] = (
            (df["day_low_so_far"] - df["day_open"]) / df["day_open"] * 100.0
        )

        # 누적 VWAP (각 거래일 내)
        typ = (df["high"] + df["low"] + df["close"]) / 3.0
        df["_pv"] = typ * df["volume"]
        df["_cum_pv"] = df.groupby("trade_date")["_pv"].cumsum()
        df["_cum_v"] = df.groupby("trade_date")["volume"].cumsum()
        df["vwap"] = df["_cum_pv"] / df["_cum_v"].replace(0, np.nan)

        # hhmm (정수, 1400 = 14:00)
        df["hhmm"] = df["trade_time"].astype(str).str[:4].astype(int)

        return df[
            ["prev_body_pct", "day_open", "day_low_pct", "vwap", "close", "hhmm"]
        ]

    @staticmethod
    def _build_prev_body_map(df_daily: pd.DataFrame) -> dict:
        if df_daily is None or df_daily.empty:
            return {}
        d = df_daily.sort_values("trade_date").copy()
        d["prev_open"] = d["open"].shift(1)
        d["prev_close"] = d["close"].shift(1)
        d["prev_body_pct"] = (
            (d["prev_close"] - d["prev_open"]) / d["prev_open"] * 100.0
        )
        return dict(zip(d["trade_date"], d["prev_body_pct"]))

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["close"]):
            return None
        prev_body_pct = arr["prev_body_pct"][bar_idx]
        day_open = arr["day_open"][bar_idx]
        if pd.isna(prev_body_pct) or pd.isna(day_open):
            return None
        hhmm = arr["hhmm"][bar_idx]
        if hhmm < self.entry_hhmm_start or hhmm >= self.entry_hhmm_end:
            return None
        if prev_body_pct < self.min_prev_body_pct:
            return None
        if arr["day_low_pct"][bar_idx] < self.max_day_decline_pct:
            return None
        close = arr["close"][bar_idx]
        if close <= day_open:
            return None
        vwap = arr["vwap"][bar_idx]
        if pd.isna(vwap) or close <= vwap:
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
        # 오버나이트 — 다음 거래일 진입 시점에서 청산
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
