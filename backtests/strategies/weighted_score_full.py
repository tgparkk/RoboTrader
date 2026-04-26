"""weighted_score Trial 837 full adapter.

기존 core/strategies/weighted_score_features.py 의 피처 계산을 그대로 재사용.
엔진 인터페이스 (StrategyBase) 에 맞춰 포장.

Responsibilities:
- prepare_features: 종목별 daily_raw 계산 후 분봉별 intraday_raw + 정규화 + score
- entry_signal: score ≤ threshold 일 때 EntryOrder emit
- exit_signal: TP/SL (current_price 기준) + hold_limit (trade_date 기준 max_holding_days)
"""
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from core.strategies.weighted_score_features import (
    WeightedScoreParams,
    compute_daily_raw,
    compute_intraday_raw,
    compute_score,
    normalize_feature_dict,
    past_volume_by_idx_from_minutes,
)
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


PARAMS_FILE = (
    Path(__file__).parent.parent.parent
    / "core" / "strategies" / "weighted_score_params.json"
)


class WeightedScoreFull(StrategyBase):
    name = "weighted_score_full"
    hold_days = 5
    param_space = {}

    def __init__(self):
        self.params = WeightedScoreParams.load(PARAMS_FILE)
        self._last_df_minute: Optional[pd.DataFrame] = None  # trading_day 계산용

    def prepare_features(
        self,
        df_minute: pd.DataFrame,
        df_daily: pd.DataFrame,
        df_kospi: pd.DataFrame = None,
        df_kosdaq: pd.DataFrame = None,
    ) -> pd.DataFrame:
        """score 컬럼을 포함한 피처 DF 반환. look-ahead 없음 (daily 는 shift(1)).

        Note: df_kospi/df_kosdaq 는 지수 일봉 (KS11/KQ11). None 이면 rel_ret/kospi_*
              피처가 NaN 이 되어 score 가 NaN 이 됨 (가중치 큰 피처 누락 시 전체 NaN).
        """
        self._last_df_minute = df_minute  # exit_signal 에서 참조

        n = len(df_minute)
        scores = [float("nan")] * n

        if df_minute.empty or df_daily is None or df_daily.empty:
            return pd.DataFrame({"score": scores}, index=df_minute.index)

        kospi = self._prepare_index_df(df_kospi)
        kosdaq = self._prepare_index_df(df_kosdaq)

        # 분봉에 idx (1-based) 및 'time' 컬럼 (features.py 규약)
        bars = df_minute.copy()
        bars["time"] = bars["trade_time"]
        bars["idx"] = bars.groupby("trade_date").cumcount() + 1

        unique_dates = bars["trade_date"].unique()
        daily_raw_by_date: Dict[str, Dict[str, float]] = {}
        for target_date in unique_dates:
            daily_raw_by_date[target_date] = compute_daily_raw(
                stock_daily=df_daily,
                kospi_daily=kospi,
                kosdaq_daily=kosdaq,
                target_trade_date=str(target_date),
            )

        past_vol_map = past_volume_by_idx_from_minutes(bars, n_days=5)
        day_open_by_date = bars.groupby("trade_date")["open"].first().to_dict()

        for i in range(n):
            td = bars.iloc[i]["trade_date"]
            day_bars = bars[bars["trade_date"] == td]
            day_bars = day_bars[day_bars["idx"] <= bars.iloc[i]["idx"]]
            intraday = compute_intraday_raw(
                bars=day_bars,
                day_open=float(day_open_by_date[td]),
                past_volume_by_idx=past_vol_map,
            )
            merged = {**daily_raw_by_date[td], **intraday}
            normalized = normalize_feature_dict(merged, self.params)
            scores[i] = compute_score(normalized, self.params)

        return pd.DataFrame({"score": scores}, index=df_minute.index)

    @staticmethod
    def _prepare_index_df(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """data_loader 는 'trade_date' 반환. features.py 는 'date' 요구 → 리네임."""
        if df is None or df.empty:
            return None
        out = df.copy()
        if "date" not in out.columns and "trade_date" in out.columns:
            out = out.rename(columns={"trade_date": "date"})
        return out

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        score = features["score"].iloc[bar_idx]
        if pd.isna(score):
            return None
        if score >= self.params.threshold_abs:
            return None
        return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.30)

    def exit_signal(
        self,
        position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        # TP/SL: current_price 기준
        if current_price is not None and position.entry_price > 0:
            pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
            if pnl_pct >= self.params.take_profit_pct:
                return ExitOrder(stock_code=position.stock_code, reason="tp")
            if pnl_pct <= self.params.stop_loss_pct:
                return ExitOrder(stock_code=position.stock_code, reason="sl")

        # hold_limit: trade_date 기반 경과 거래일
        if self._last_df_minute is not None:
            days_held = count_trading_days_between(
                self._last_df_minute,
                from_idx=position.entry_bar_idx,
                to_idx=bar_idx,
            )
            if days_held >= self.params.max_holding_days:
                return ExitOrder(stock_code=position.stock_code, reason="hold_limit")

        return None
