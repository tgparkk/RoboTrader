"""macd_cross 라이브 어댑터.

페이퍼 단계 운영:
- 매일 pre_market 에서 종목별 daily history 주입 → MACD hist 계산 → prev/prev_prev 캐시
- 14:30~15:00 매 분봉 마감 시점에 캐시된 hist + 현재 hhmm 으로 골든크로스 판정
- 시그널 발생 시 main._analyze_buy_decision 이 가상매매 라우팅

Spec §4.2: 백테스트 macd_cross 의 시그널 식과 1:1 동등 보장.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from core.strategies.macd_cross_signal import (
    compute_macd_histogram_series,
    is_macd_golden_cross,
    is_in_entry_window,
)


class MacdCrossStrategy:
    """라이브 어댑터 (intraday_manager 와 결합)."""

    def __init__(
        self,
        fast: int = 14,
        slow: int = 34,
        signal: int = 12,
        entry_hhmm_min: int = 1430,
        entry_hhmm_max: int = 1500,
        logger=None,
    ):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.entry_hhmm_min = entry_hhmm_min
        self.entry_hhmm_max = entry_hhmm_max
        self.logger = logger
        # {stock_code: (prev_hist, prev_prev_hist)} — 매일 pre_market 에서 갱신
        self._cache: Dict[str, Tuple[float, float]] = {}
        # {stock_code: (prev_close, prev_trading_value)} — feasibility 체크용 (Fix C)
        self._meta: Dict[str, Tuple[float, float]] = {}
        self._cache_date: Optional[str] = None

    def set_daily_history(
        self,
        stock_code: str,
        df_daily: pd.DataFrame,
        today_yyyymmdd: str,
        prev_trading_value: Optional[float] = None,
    ) -> None:
        """종목별 daily 시퀀스 주입 → MACD hist 계산 → prev/prev_prev 캐시.

        Args:
            df_daily: 오늘 이전 거래일까지의 일봉 (trade_date asc, close 컬럼).
            today_yyyymmdd: 진입 대상 거래일 (YYYYMMDD). 캐시 invalidation 키.
            prev_trading_value: 전일 거래대금 (원). volume feasibility 체크용.
        """
        if self._cache_date != today_yyyymmdd:
            self._cache.clear()
            self._meta.clear()
            self._cache_date = today_yyyymmdd

        if df_daily is None or df_daily.empty or len(df_daily) < self.slow + self.signal:
            return

        hist = compute_macd_histogram_series(
            df_daily, fast=self.fast, slow=self.slow, signal=self.signal
        )
        if len(hist) < 2:
            return
        prev_hist = float(hist.iloc[-1])      # 가장 최근 거래일 hist (= 진입일 직전 거래일)
        prev_prev_hist = float(hist.iloc[-2]) # 그 직전 거래일
        self._cache[stock_code] = (prev_hist, prev_prev_hist)

        # 메타 캐시 (Fix C — feasibility check)
        try:
            d_sorted = df_daily.sort_values("trade_date")
            prev_close = float(d_sorted["close"].iloc[-1])
            tv = float(prev_trading_value) if prev_trading_value is not None else 0.0
            self._meta[stock_code] = (prev_close, tv)
        except Exception:
            pass

    def get_cached_hist(self, stock_code: str) -> Tuple[Optional[float], Optional[float]]:
        return self._cache.get(stock_code, (None, None))

    def get_daily_meta(self, stock_code: str) -> Tuple[Optional[float], Optional[float]]:
        """(prev_close, prev_trading_value) 반환. feasibility check 용."""
        return self._meta.get(stock_code, (None, None))

    def check_entry(self, stock_code: str, hhmm: int) -> bool:
        """진입 판정. 캐시된 hist + 시간대 + 골든크로스 충족 시 True."""
        if not is_in_entry_window(hhmm, self.entry_hhmm_min, self.entry_hhmm_max):
            return False
        prev_hist, prev_prev_hist = self.get_cached_hist(stock_code)
        return is_macd_golden_cross(prev_hist, prev_prev_hist)

    def cached_universe_size(self) -> int:
        return len(self._cache)
