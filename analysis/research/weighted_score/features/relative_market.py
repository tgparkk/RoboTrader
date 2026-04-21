"""상대강도·시장 상태 피처 (4개).

minute_candles 에 개별 종목만 있고 지수는 daily_candles 에만 있으므로,
per-minute 상대강도는 근사로 처리한다.

- `rel_ret_20d_kospi`  : 종목 20일 수익률 - KOSPI 20일 수익률 (daily, broadcast)
- `rel_ret_20d_kosdaq` : 종목 - KOSDAQ, same
- `kospi_trend_5d`     : KOSPI 5일 수익률 (daily, broadcast)
- `kospi_vol_20d`      : KOSPI 일간 수익률의 20일 표준편차 (%) — 시장 변동성 레짐

구현 주의:
- 모두 daily-level 이므로 계산 후 shift(1) 필수 (오늘자 daily close 는 미공개).
- KOSPI/KOSDAQ 데이터는 각 연구 세션에서 1회 로드 후 캐시.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from analysis.research.weighted_score import config
from analysis.research.weighted_score.data import daily_bars, pg_loader


FEATURE_NAMES: list[str] = [
    "rel_ret_20d_kospi",
    "rel_ret_20d_kosdaq",
    "kospi_trend_5d",
    "kospi_vol_20d",
]


@lru_cache(maxsize=4)
def _load_index_daily(symbol: str) -> pd.DataFrame:
    df = pg_loader.load_daily_index(symbol, config.DATA_START, config.DATA_END)
    if df.empty:
        raise RuntimeError(f"no daily data for index {symbol}")
    df = df.sort_values("date").reset_index(drop=True)
    df["ret"] = df["close"].pct_change()
    df["ret_20d"] = df["close"].pct_change(20)
    df["ret_5d"] = df["close"].pct_change(5)
    df["vol_20d"] = df["ret"].rolling(window=20, min_periods=10).std() * 100.0
    return df


def compute_relative_market(minute_df: pd.DataFrame) -> pd.DataFrame:
    for col in ("trade_date", "open", "close", "volume"):
        if col not in minute_df.columns:
            raise ValueError(f"missing column: {col}")

    stock_daily = daily_bars.aggregate_minutes_to_daily(minute_df)
    stock_daily["ret_20d"] = stock_daily["close"].astype(float).pct_change(20)

    ks = _load_index_daily("KS11").set_index("date")
    kq = _load_index_daily("KQ11").set_index("date")

    # 일자별 병합 (stock_daily.trade_date 는 "YYYYMMDD", 지수 date 도 같은 포맷이어야 함)
    d = stock_daily.copy()
    d["ks_ret_20d"] = d["trade_date"].map(ks["ret_20d"])
    d["kq_ret_20d"] = d["trade_date"].map(kq["ret_20d"])
    d["ks_ret_5d"] = d["trade_date"].map(ks["ret_5d"])
    d["ks_vol_20d"] = d["trade_date"].map(ks["vol_20d"])

    d["rel_ret_20d_kospi"] = d["ret_20d"] - d["ks_ret_20d"]
    d["rel_ret_20d_kosdaq"] = d["ret_20d"] - d["kq_ret_20d"]
    d["kospi_trend_5d"] = d["ks_ret_5d"]
    d["kospi_vol_20d"] = d["ks_vol_20d"]

    # shift(1): 오늘 당일 daily close 는 미공개
    for name in FEATURE_NAMES:
        d[name] = d[name].shift(1)

    out = pd.DataFrame(index=minute_df.index)
    for name in FEATURE_NAMES:
        m = dict(zip(d["trade_date"], d[name]))
        out[name] = minute_df["trade_date"].map(m).astype(float)

    return out
