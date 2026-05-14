"""macd_cross exit-side regime v2 wrapper — Trailing / Reversal / Tiered SL.

3 family 단독 (조합 없음). family='off' 면 base MACDCrossStrategy 와 동일.
라이브 코드 (macd_cross.py / macd_cross_signal.py) 미수정 보장.

Spec: docs/superpowers/specs/(TBD)-macd-cross-exit-regime-v2.
"""
from typing import Optional

import numpy as np
import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import ExitOrder, Position
from backtests.strategies.macd_cross import MACDCrossStrategy
from core.strategies.macd_cross_signal import compute_macd_histogram_series


VALID_FAMILIES = ("off", "trailing", "reversal", "tiered_sl")


class MACDCrossExitRegimeV2Strategy(MACDCrossStrategy):
    """Exit-side regime v2 — 3 family 단독 트리거 wrapper."""
    name = "macd_cross_exit_regime_v2"

    def __init__(
        self,
        family: str = "off",
        # Family A — Trailing stop (high-water)
        trailing_pct: Optional[float] = None,
        trailing_activate_after_pct: float = 0.0,
        # Family B — Intraday MACD reversal 확장
        reversal_eval_hhmm: Optional[int] = None,
        reversal_hist_threshold: Optional[float] = 0.0,
        reversal_min_hold_days: int = 1,
        # Family C — Hold-day 차등 stop
        sl_d1_pct: Optional[float] = None,
        sl_d2_pct: Optional[float] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if family not in VALID_FAMILIES:
            raise ValueError(
                f"family must be one of {VALID_FAMILIES}, got {family!r}"
            )
        if family == "trailing" and trailing_pct is None:
            raise ValueError("family='trailing' requires trailing_pct")
        if family == "reversal" and reversal_hist_threshold is None:
            raise ValueError("family='reversal' requires reversal_hist_threshold")
        if family == "tiered_sl" and sl_d1_pct is None and sl_d2_pct is None:
            raise ValueError(
                "family='tiered_sl' requires at least one of sl_d1_pct / sl_d2_pct"
            )
        self.family = family
        self.trailing_pct = trailing_pct
        self.trailing_activate_after_pct = trailing_activate_after_pct
        self.reversal_eval_hhmm = reversal_eval_hhmm
        self.reversal_hist_threshold = reversal_hist_threshold
        self.reversal_min_hold_days = reversal_min_hold_days
        self.sl_d1_pct = sl_d1_pct
        self.sl_d2_pct = sl_d2_pct

    # ---- features ----

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        feat = super().prepare_features(df_minute, df_daily).copy()
        if df_minute.empty or self.family == "off":
            return feat
        feat["high"] = df_minute["high"].astype(float).values
        feat["low"] = df_minute["low"].astype(float).values
        feat["close"] = df_minute["close"].astype(float).values
        feat["trade_date"] = df_minute["trade_date"].astype(str).values
        if self.family == "reversal":
            feat["eval_hist_bps"] = self._compute_eval_hist_bps(df_minute, df_daily)
        return feat

    def _compute_eval_hist_bps(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> np.ndarray:
        """eval_hhmm 시점 분봉의 partial-close 기반 MACD hist (bps = hist/prev_close × 10000)."""
        n = len(df_minute)
        result = np.full(n, np.nan, dtype=float)
        if df_daily is None or df_daily.empty:
            return result

        d_sorted = df_daily.sort_values("trade_date").reset_index(drop=True)
        d_sorted = d_sorted.assign(
            trade_date=d_sorted["trade_date"].astype(str),
            close=d_sorted["close"].astype(float),
        )
        dates_list = d_sorted["trade_date"].tolist()
        closes_list = d_sorted["close"].tolist()
        prev_close_map = {
            dates_list[i]: closes_list[i - 1] for i in range(1, len(dates_list))
        }

        minute_dates = df_minute["trade_date"].astype(str).values
        minute_closes = df_minute["close"].astype(float).values
        minute_hhmm = df_minute["trade_time"].astype(str).str[:4].astype(int).values

        if self.reversal_eval_hhmm is None:
            # last_bar 모드 — today's full daily close (MV-B 동등)
            hist_series = compute_macd_histogram_series(
                d_sorted,
                fast=self.fast_period,
                slow=self.slow_period,
                signal=self.signal_period,
            )
            today_hist_map = dict(zip(d_sorted["trade_date"], hist_series))
            for i in range(n):
                is_last = (i == n - 1) or (minute_dates[i + 1] != minute_dates[i])
                if is_last:
                    date = minute_dates[i]
                    hist = today_hist_map.get(date)
                    prev_c = prev_close_map.get(date)
                    if (
                        hist is not None
                        and not pd.isna(hist)
                        and prev_c
                        and prev_c > 0
                    ):
                        result[i] = float(hist) / prev_c * 10000.0
            return result

        # intraday eval_hhmm 모드 — bar close 를 today's pseudo-close 로 substitute
        target_hhmm = int(self.reversal_eval_hhmm)
        for i in range(n):
            if minute_hhmm[i] != target_hhmm:
                continue
            date = minute_dates[i]
            bar_close = float(minute_closes[i])
            yest = d_sorted[d_sorted["trade_date"] < date]
            if len(yest) == 0:
                continue
            modified = pd.concat(
                [
                    yest[["trade_date", "close"]],
                    pd.DataFrame({"trade_date": [date], "close": [bar_close]}),
                ],
                ignore_index=True,
            )
            hist_series = compute_macd_histogram_series(
                modified,
                fast=self.fast_period,
                slow=self.slow_period,
                signal=self.signal_period,
            )
            if len(hist_series) == 0:
                continue
            hist = float(hist_series.iloc[-1])
            prev_c = prev_close_map.get(date)
            if not pd.isna(hist) and prev_c and prev_c > 0:
                result[i] = hist / prev_c * 10000.0
        return result

    # ---- exit_signal ----

    def exit_signal(
        self,
        position: Position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        if self.family == "off":
            return super().exit_signal(position, features, bar_idx, current_price)

        if features.empty:
            return super().exit_signal(position, features, bar_idx, current_price)

        arr = get_arrays(features)
        if "high" not in arr or bar_idx >= len(arr["high"]):
            return super().exit_signal(position, features, bar_idx, current_price)

        if self.family == "trailing":
            order = self._check_trailing(position, arr, bar_idx)
        elif self.family == "reversal":
            order = self._check_reversal(position, arr, bar_idx)
        elif self.family == "tiered_sl":
            order = self._check_tiered_sl(position, arr, bar_idx)
        else:
            order = None

        if order is not None:
            return order
        return super().exit_signal(position, features, bar_idx, current_price)

    def _check_trailing(
        self, position: Position, arr, bar_idx: int
    ) -> Optional[ExitOrder]:
        # entry 봉 자체 미트리거 (peak window 비어있음)
        if bar_idx <= position.entry_bar_idx:
            return None
        high_arr = arr["high"]
        low_arr = arr["low"]
        window = high_arr[position.entry_bar_idx + 1 : bar_idx + 1]
        if len(window) == 0:
            return None
        peak = max(position.entry_price, float(np.max(window)))

        if self.trailing_activate_after_pct > 0:
            activate_threshold = (
                position.entry_price * (1.0 + self.trailing_activate_after_pct)
            )
            if peak < activate_threshold:
                return None  # activate_after 미충족

        low = float(low_arr[bar_idx])
        if low <= peak * (1.0 - self.trailing_pct):
            return ExitOrder(
                stock_code=position.stock_code, reason="trailing_stop"
            )
        return None

    def _check_reversal(
        self, position: Position, arr, bar_idx: int
    ) -> Optional[ExitOrder]:
        if "eval_hist_bps" not in arr or self._last_df_minute is None:
            return None
        bps = arr["eval_hist_bps"][bar_idx]
        if pd.isna(bps):
            return None
        days_held = count_trading_days_between(
            self._last_df_minute,
            from_idx=position.entry_bar_idx,
            to_idx=bar_idx,
        )
        if days_held < self.reversal_min_hold_days:
            return None
        if float(bps) <= float(self.reversal_hist_threshold):
            return ExitOrder(
                stock_code=position.stock_code, reason="macd_reversal"
            )
        return None

    def _check_tiered_sl(
        self, position: Position, arr, bar_idx: int
    ) -> Optional[ExitOrder]:
        if self._last_df_minute is None:
            return None
        days_held = count_trading_days_between(
            self._last_df_minute,
            from_idx=position.entry_bar_idx,
            to_idx=bar_idx,
        )
        if days_held == 0:
            return None  # entry day 무적용
        low = float(arr["low"][bar_idx])
        if days_held == 1 and self.sl_d1_pct is not None:
            if low <= position.entry_price * (1.0 - self.sl_d1_pct):
                return ExitOrder(stock_code=position.stock_code, reason="sl_d1")
        elif days_held >= 2 and self.sl_d2_pct is not None:
            if low <= position.entry_price * (1.0 - self.sl_d2_pct):
                return ExitOrder(stock_code=position.stock_code, reason="sl_d2")
        return None
