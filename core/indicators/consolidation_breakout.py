"""
정체(횡보) 이후 돌파 상승 캔들을 탐지하는 인디케이터.

기본 개념
- 변동성 축소(ATR, 밴드폭, 구간폭), 추세 평탄화(MA 기울기), 거래량 수축을 통해
  직전 구간을 "정체 구간"으로 정의
- 다음 봉에서 상단 돌파하는 상승 캔들을 매수 트리거로 생성
- 엔트리 가격은 돌파 캔들의 절반(1/2) 구간 가격으로 계산

반환
- 입력 df와 동일한 길이의 DataFrame
  - columns:
    - consolidation_low, consolidation_high: 직전 정체 구간의 하단/상단(없으면 NaN)
    - buy_consolidation_breakout: bool, 해당 봉에서 돌파 매수 트리거 발생 여부
    - entry_price_half: float, 해당 봉의 1/2 구간 엔트리 가격(없으면 NaN)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ConsolidationParams:
    # 정체 탐지 파라미터
    lookback_bars: int = 10          # 정체 탐지 윈도우 L
    min_persist_bars: int = 4        # 정체 최소 지속 봉수(간소화: 조건을 강하게 하여 별도 체크 생략 가능)
    atr_window: int = 14
    bb_window: int = 20
    bb_bandwidth_threshold: float = 0.02   # 2%
    range_pct_threshold: float = 0.006     # 0.6%
    atr_percentile: float = 0.25           # ATR 25% 분위수 이하
    ma_window: int = 20
    ma_slope_threshold: float = 0.0005     # 0.05%/bar
    vol_short: int = 5
    vol_long: int = 20
    vol_contract_ratio_threshold: float = 0.7

    # 돌파 트리거 파라미터
    breakout_buffer: float = 0.0005        # 0.05%
    body_ratio_threshold: float = 0.5      # 몸통/전체 ≥ 0.5
    atr_range_multiple: float = 0.8        # 캔들 범위 ≥ 0.8 * ATR


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr


def _atr(df: pd.DataFrame, window: int) -> pd.Series:
    tr = _true_range(df['high'], df['low'], df['close'])
    return tr.rolling(window, min_periods=1).mean()


def _bollinger(close: pd.Series, window: int, num_std: float = 2.0):
    mid = close.rolling(window, min_periods=1).mean()
    sd = close.rolling(window, min_periods=1).std(ddof=0)
    up = mid + num_std * sd
    dn = mid - num_std * sd
    return mid, up, dn


def generate_consolidation_breakout_signals(
    df: pd.DataFrame,
    params: Optional[ConsolidationParams] = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    p = params or ConsolidationParams()

    # 입력 복사 및 안전 캐스팅
    data = df.copy()
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors='coerce')
        else:
            data[col] = np.nan

    # 지표 계산
    atr = _atr(data, p.atr_window)
    bb_mid, bb_up, bb_dn = _bollinger(data['close'], p.bb_window, 2.0)
    bb_bw = (bb_up - bb_dn) / bb_mid.replace(0, np.nan)
    ma = data['close'].rolling(p.ma_window, min_periods=1).mean()
    ma_slope = (ma - ma.shift(1)) / ma.shift(1).replace(0, np.nan)

    # 전역 ATR 분위수 기준
    atr_quantile_value = atr.quantile(p.atr_percentile)

    n = len(data)
    zone_low = np.full(n, np.nan)
    zone_high = np.full(n, np.nan)
    consolidated = np.zeros(n, dtype=bool)
    consolidated_streak = np.zeros(n, dtype=int)
    buy_breakout = np.zeros(n, dtype=bool)
    entry_price_half = np.full(n, np.nan)

    # 1) 각 시점 i에 대해 "정체 여부"와 해당 시점의 박스 상하단 계산(윈도우: i-L+1 ~ i)
    for i in range(n):
        if i < p.lookback_bars - 1:
            continue
        win = data.iloc[i - p.lookback_bars + 1:i + 1]
        z_low = float(win['low'].min()) if not win['low'].isna().all() else np.nan
        z_high = float(win['high'].max()) if not win['high'].isna().all() else np.nan
        zone_low[i] = z_low
        zone_high[i] = z_high

        mean_close = float(win['close'].mean()) if not win['close'].isna().all() else np.nan
        range_pct = (z_high - z_low) / mean_close if mean_close and mean_close > 0 else np.inf
        atr_ok = bool(atr.iloc[i] <= atr_quantile_value) if pd.notna(atr.iloc[i]) else False
        bb_ok = bool(bb_bw.iloc[i] <= p.bb_bandwidth_threshold) if pd.notna(bb_bw.iloc[i]) else False
        range_ok = bool(range_pct <= p.range_pct_threshold)
        slope_ok = bool(abs(ma_slope.iloc[i]) <= p.ma_slope_threshold) if pd.notna(ma_slope.iloc[i]) else False
        v_short = float(data['volume'].rolling(p.vol_short, min_periods=1).mean().iloc[i])
        v_long = float(data['volume'].rolling(p.vol_long, min_periods=1).mean().iloc[i])
        vol_ok = (v_short / v_long) <= p.vol_contract_ratio_threshold if v_long > 0 else False
        consolidated[i] = bool(atr_ok and bb_ok and range_ok and slope_ok and vol_ok)
        consolidated_streak[i] = (consolidated_streak[i-1] + 1) if (i > 0 and consolidated[i]) else (1 if consolidated[i] else 0)

    # 2) 돌파 트리거: 직전 구간이 정체이며(연속 p.min_persist_bars 이상), 현재 봉이 직전 상단 돌파하는 상승 캔들
    for i in range(1, n):
        prev_i = i - 1
        # 정체 최소 지속 확인
        if not consolidated[prev_i]:
            continue
        if consolidated_streak[prev_i] < p.min_persist_bars:
            continue
        # 직전 정체 상단/하단(현재 기준으로는 i-1에서 계산된 박스)을 참조
        z_high_prev = zone_high[prev_i]
        z_low_prev = zone_low[prev_i]
        if not (np.isfinite(z_high_prev) and np.isfinite(z_low_prev)):
            continue

        o = float(data['open'].iloc[i]) if pd.notna(data['open'].iloc[i]) else np.nan
        h = float(data['high'].iloc[i]) if pd.notna(data['high'].iloc[i]) else np.nan
        l = float(data['low'].iloc[i]) if pd.notna(data['low'].iloc[i]) else np.nan
        c = float(data['close'].iloc[i]) if pd.notna(data['close'].iloc[i]) else np.nan
        if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l) and np.isfinite(c)):
            continue

        bullish = c > o
        breakout = c > z_high_prev * (1.0 + p.breakout_buffer)
        total_range = max(h - l, 1e-9)
        body_ratio = abs(c - o) / total_range
        vol_spike = data['volume'].iloc[i] >= 1.2 * data['volume'].rolling(p.vol_long, min_periods=1).mean().iloc[i]
        range_big = (h - l) >= p.atr_range_multiple * (atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.0)

        if bullish and breakout and body_ratio >= p.body_ratio_threshold and (vol_spike or range_big):
            buy_breakout[i] = True
            entry_price_half[i] = l + (h - l) * 0.5

    # 박스 상하단은 "현재 봉에서 참조할 직전 구간"을 정렬해서 보여주기 위해 1칸 시프트한 값도 제공
    zlow_prev_align = np.concatenate([[np.nan], zone_low[:-1]])
    zhigh_prev_align = np.concatenate([[np.nan], zone_high[:-1]])

    out = pd.DataFrame({
        'consolidation_low': zlow_prev_align,   # 현재 봉에서 참조 가능한 직전 박스 하단
        'consolidation_high': zhigh_prev_align, # 현재 봉에서 참조 가능한 직전 박스 상단
        'buy_consolidation_breakout': buy_breakout,
        'entry_price_half': entry_price_half,
    })
    # datetime 인덱스가 있다면 맞춰 부착
    if 'datetime' in df.columns:
        out['datetime'] = df['datetime'].values
    return out


