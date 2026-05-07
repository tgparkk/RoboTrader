"""macd_cross 에 SL/TP/intraday MACD reversal exit overlay 를 얹은 백테스트 wrapper.

본체 backtests/strategies/macd_cross.py 는 라이브 동등성 보호 위해 미수정.
실제 fill 가격은 engine 의 next_fill_index(t) next-bar open 모델을 따른다
(spec § 4.3, 기존 hold_limit 와 동일).
"""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import ExitOrder, Position
from backtests.strategies.macd_cross import MACDCrossStrategy
from core.strategies.macd_cross_signal import compute_macd_histogram_series


class MACDCrossExitOverlayStrategy(MACDCrossStrategy):
    """SL / TP / intraday MACD reversal exit overlay.

    Args:
        sl_pct: 0~1 fractional. None 이면 SL 비활성.
        tp_pct: 0~1 fractional. None 이면 TP 비활성.
        intraday_reversal: True 면 D+1 부터 매일 last bar 에서 today_hist<0 시 청산.
    """
    name = "macd_cross_exit_overlay"

    def __init__(
        self,
        sl_pct: Optional[float] = None,
        tp_pct: Optional[float] = None,
        intraday_reversal: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.intraday_reversal = intraday_reversal

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        feat = super().prepare_features(df_minute, df_daily).copy()
        if df_minute.empty:
            return feat
        # SL/TP 용 OHLC 캐시
        feat["high"] = df_minute["high"].astype(float).values
        feat["low"] = df_minute["low"].astype(float).values
        feat["trade_date"] = df_minute["trade_date"].astype(str).values
        # intraday reversal 용 today_hist (no shift)
        if self.intraday_reversal:
            today_hist_map = self._build_today_hist_map(df_daily)
            feat["today_hist"] = (
                df_minute["trade_date"].astype(str).map(today_hist_map).values
            )
        return feat

    def _build_today_hist_map(self, df_daily: pd.DataFrame):
        if df_daily is None or df_daily.empty:
            return {}
        d = df_daily.sort_values("trade_date").copy()
        hist = compute_macd_histogram_series(
            d, fast=self.fast_period, slow=self.slow_period, signal=self.signal_period
        )
        # NO shift — 오늘 hist 값
        return dict(zip(d["trade_date"].astype(str), hist))

    def exit_signal(
        self,
        position: Position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        # 모든 overlay off 시 base 동일
        if (self.sl_pct is None and self.tp_pct is None
                and not self.intraday_reversal):
            return super().exit_signal(position, features, bar_idx, current_price)

        # features 가 비어있으면 (테스트의 dummy DF) base 만 호출
        if features.empty:
            return super().exit_signal(position, features, bar_idx, current_price)

        arr = get_arrays(features)
        if bar_idx >= len(arr.get("high", [])):
            return super().exit_signal(position, features, bar_idx, current_price)

        # === Task 6 에서 SL 추가 ===
        # === Task 7 에서 TP 추가 ===
        # === Task 8 에서 reversal 추가 ===

        return super().exit_signal(position, features, bar_idx, current_price)
