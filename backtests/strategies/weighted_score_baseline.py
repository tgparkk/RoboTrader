"""weighted_score Trial 837 baseline 어댑터.

새 엔진(backtests/common/engine.py) 인터페이스에 맞춰 포장한 간소화 버전.
Trial 837 전체 11개 피처 중 핵심 4개만 구현 — 엔진 신뢰성 스모크 테스트용.

look-ahead 없음: daily 피처 모두 .shift(1) 적용 후 minute 에 trade_date 기준 broadcast.
"""
from typing import Optional
import json
from pathlib import Path

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


PARAMS_FILE = Path(__file__).parent.parent.parent / "core" / "strategies" / "weighted_score_params.json"

BARS_PER_TRADING_DAY = 390  # 09:00~15:30 근사치


class WeightedScoreBaseline(StrategyBase):
    name = "weighted_score_baseline"
    hold_days = 5  # Trial 837 max_holding_days
    param_space = {}

    def __init__(self):
        with open(PARAMS_FILE, "r", encoding="utf-8") as f:
            self.params = json.load(f)
        self.threshold = self.params["entry"]["threshold_abs"]
        self.max_holding_days = self.params["exit"]["max_holding_days"]

    def prepare_features(self, df_minute: pd.DataFrame, df_daily: pd.DataFrame) -> pd.DataFrame:
        """4개 간소화 피처 (모두 shift(1) 적용)."""
        if df_daily.empty or df_minute.empty:
            return pd.DataFrame({"score": [float("nan")] * len(df_minute)}, index=df_minute.index)

        daily = df_daily.sort_values("trade_date").copy()
        daily["ret_1d"] = daily["close"].pct_change().shift(1)
        daily["atr_pct_14d"] = (
            (daily["high"] - daily["low"]).rolling(14).mean() / daily["close"]
        ).shift(1)
        daily["vol_ratio_20d"] = (
            daily["volume"] / daily["volume"].rolling(20).mean()
        ).shift(1)
        # 간소화 score: 음수일수록 매수 선호
        daily["score"] = (
            -daily["ret_1d"]
            + 0.5 * daily["atr_pct_14d"]
            - 0.3 * (daily["vol_ratio_20d"] - 1)
        )

        merged = df_minute[["trade_date"]].merge(
            daily[["trade_date", "score"]], on="trade_date", how="left"
        )
        return pd.DataFrame({"score": merged["score"].values}, index=df_minute.index)

    def entry_signal(self, features, bar_idx, stock_code) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        # 장 시작 첫 5 bar 에서만 진입 시도
        if bar_idx % BARS_PER_TRADING_DAY > 5:
            return None
        score = features["score"].iloc[bar_idx]
        if pd.isna(score) or score >= self.threshold:
            return None
        return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.30)

    def exit_signal(self, position, features, bar_idx) -> Optional[ExitOrder]:
        held_bars = bar_idx - position.entry_bar_idx
        if held_bars <= 0:
            return None
        days_held = held_bars // BARS_PER_TRADING_DAY
        if days_held >= self.max_holding_days:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
