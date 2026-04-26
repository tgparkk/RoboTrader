"""macd_cross 시그널 식 (백테스트·라이브 공유, 2026-04-26).

backtests/strategies/macd_cross.py 와 core/strategies/macd_cross_strategy.py 가
이 모듈만을 호출해야 한다. 한 픽셀이라도 다르면 페이퍼 단계 OOS 재현
검증이 의미를 잃는다.

Spec: docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md §4.4
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def compute_macd_histogram_series(
    df_daily: pd.DataFrame,
    fast: int,
    slow: int,
    signal: int,
) -> pd.Series:
    """일봉 close 시퀀스로부터 MACD histogram 시계열을 계산한다.

    Args:
        df_daily: `trade_date` 오름차순 + `close` 컬럼 보유. 최소 slow+signal 일 필요.
        fast: 빠른 EMA span
        slow: 느린 EMA span
        signal: signal EMA span

    Returns:
        histogram 시계열 (df_daily.index 와 1:1).
        EMA span 적응 기간 동안은 finite 이지만 의미 부족 (호출 측이 NaN 처리는 안 함).
    """
    if df_daily is None or df_daily.empty:
        return pd.Series([], dtype=float)
    d = df_daily.sort_values("trade_date")
    close = d["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd - sig


def is_macd_golden_cross(
    prev_hist: Optional[float],
    prev_prev_hist: Optional[float],
) -> bool:
    """직전 거래일 MACD histogram 음→양 골든크로스 판정.

    백테스트 entry_signal 의 핵심 식 (prev_prev_hist < 0 AND prev_hist >= 0).
    한 픽셀이라도 다르면 OOS 재현 검증 의미를 잃는다.
    """
    if pd.isna(prev_hist) or pd.isna(prev_prev_hist):
        return False
    return prev_prev_hist < 0 and prev_hist >= 0


def is_in_entry_window(hhmm: int, hhmm_min: int, hhmm_max: int) -> bool:
    """진입 시간대 검사 (HHMM int 비교)."""
    return hhmm_min <= hhmm <= hhmm_max
