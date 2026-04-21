"""기술지표 피처 (5개, daily 계산 후 분봉에 broadcast).

- `rsi_14`       : RSI(14) on daily close
- `macd_hist`    : MACD(12,26,9) histogram on daily close
- `bb_percent_b` : Bollinger %B(20,2) on daily close
- `stoch_k_14`   : Stochastic %K(14) on daily HLC
- `adx_14`       : ADX(14) on daily HLC

모두 일간 값이라 당일 모든 분봉에 동일 값이 broadcast 된다.
look-ahead 방지: 분봉 t 가 속한 날짜의 값은 **전일 종가까지의 정보**로 계산된다
(즉, 당일 daily close 는 아직 모르므로 shift(1) 적용).
"""
from __future__ import annotations

import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, ADXIndicator
from ta.volatility import BollingerBands

from analysis.research.weighted_score.data import daily_bars


FEATURE_NAMES: list[str] = [
    "rsi_14",
    "macd_hist",
    "bb_percent_b",
    "stoch_k_14",
    "adx_14",
]


def _compute_daily_indicators(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 DF → 기술지표 DF (shift(1) 미적용, 원값)."""
    d = daily.copy()
    d["close"] = d["close"].astype(float)
    d["high"] = d["high"].astype(float)
    d["low"] = d["low"].astype(float)

    rsi = RSIIndicator(close=d["close"], window=14, fillna=False)
    d["rsi_14"] = rsi.rsi()

    macd = MACD(close=d["close"], window_slow=26, window_fast=12, window_sign=9, fillna=False)
    d["macd_hist"] = macd.macd_diff()

    bb = BollingerBands(close=d["close"], window=20, window_dev=2, fillna=False)
    d["bb_percent_b"] = bb.bollinger_pband()  # 0~1 일반적 (밴드 바깥은 벗어남)

    stoch = StochasticOscillator(
        high=d["high"], low=d["low"], close=d["close"], window=14, smooth_window=3, fillna=False
    )
    d["stoch_k_14"] = stoch.stoch()

    adx = ADXIndicator(high=d["high"], low=d["low"], close=d["close"], window=14, fillna=False)
    d["adx_14"] = adx.adx()

    return d[["trade_date"] + FEATURE_NAMES]


def compute_technical(minute_df: pd.DataFrame) -> pd.DataFrame:
    """입력 분봉 → 5개 기술지표 DF (분봉 단위로 broadcast, shift(1) 적용)."""
    for col in ("trade_date", "idx", "open", "high", "low", "close", "volume"):
        if col not in minute_df.columns:
            raise ValueError(f"missing column: {col}")

    daily = daily_bars.aggregate_minutes_to_daily(minute_df)
    ind = _compute_daily_indicators(daily)

    # shift(1): 오늘의 분봉에는 어제까지 관측한 일봉 기반 지표를 쓴다 (look-ahead 방지)
    for name in FEATURE_NAMES:
        ind[name] = ind[name].shift(1)

    out = pd.DataFrame(index=minute_df.index)
    for name in FEATURE_NAMES:
        m = dict(zip(ind["trade_date"], ind[name]))
        out[name] = minute_df["trade_date"].map(m)

    return out
