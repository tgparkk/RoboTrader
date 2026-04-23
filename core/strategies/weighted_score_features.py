"""Weighted Score 실시간 피처 계산.

23개 피처를 **daily (12)**, **intraday (8)**, **temporal (3)** 로 분리:

- Daily (장 시작 전 1회 계산 → 종일 broadcast):
    rsi_14, macd_hist, bb_percent_b, adx_14,
    atr_pct_14d, obv_slope_5d,
    rel_ret_20d_kospi, rel_ret_20d_kosdaq, kospi_trend_5d, kospi_vol_20d,
    gap_pct, prior_day_range, cum_ret_3d   (12)

- Intraday (매 분봉 완성 시 계산):
    pct_from_open, ret_1min, ret_5min, ret_15min, ret_30min,
    vol_ratio_5d, realized_vol_30min   (7)

    (obv_slope_5d 는 일간 값이므로 daily 로 이동)

- Temporal (매 분봉 계산, 초경량):
    hour_sin, hour_cos, minutes_since_open   (3)

참고: `analysis/research/weighted_score/features/` 과 **결정론적 동치** 보장.
shift(1) 규칙 동일 (daily 지표는 전일까지의 정보로 계산).

정규화는 `weighted_score_params.json` 에 저장된 train 분포 기준.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ============================================================================
#  파라미터 로드
# ============================================================================


@dataclass
class WeightedScoreParams:
    """`weighted_score_params.json` 역직렬화."""
    threshold_abs: float
    entry_pct: float
    max_positions: int
    stop_loss_pct: float
    take_profit_pct: float
    max_holding_days: int
    time_exit_bars: int
    weights: Dict[str, float]
    feature_names: List[str]
    rolling_percentile_quantiles: Dict[str, np.ndarray]  # feature → sorted quantiles
    zscore_params: Dict[str, Dict[str, float]]          # feature → {mean, std}
    zscore_clip: float
    scale_to_unit_ranges: Dict[str, tuple]              # feature → (lo, hi)
    meta: dict

    @classmethod
    def load(cls, path: str | Path) -> "WeightedScoreParams":
        p = Path(path)
        payload = json.loads(p.read_text(encoding="utf-8"))

        norm = payload["normalization"]

        rp_quants: Dict[str, np.ndarray] = {}
        for name, block in norm["rolling_percentile"].items():
            rp_quants[name] = np.asarray(block["quantiles"], dtype=np.float64)

        zs = {
            name: {"mean": float(b["mean"]), "std": float(b["std"])}
            for name, b in norm["zscore_clip"].items()
        }
        stu = {name: tuple(v) for name, v in norm["scale_to_unit"].items()}

        return cls(
            threshold_abs=float(payload["entry"]["threshold_abs"]),
            entry_pct=float(payload["entry"]["entry_pct"]),
            max_positions=int(payload["entry"]["max_positions"]),
            stop_loss_pct=float(payload["exit"]["stop_loss_pct"]),
            take_profit_pct=float(payload["exit"]["take_profit_pct"]),
            max_holding_days=int(payload["exit"]["max_holding_days"]),
            time_exit_bars=int(payload["exit"]["time_exit_bars"]),
            weights=dict(payload["weights"]),
            feature_names=list(payload["feature_names"]),
            rolling_percentile_quantiles=rp_quants,
            zscore_params=zs,
            zscore_clip=float(norm["zscore_clip_value"]),
            scale_to_unit_ranges=stu,
            meta=payload.get("meta", {}),
        )


# ============================================================================
#  정규화
# ============================================================================


def _rolling_percentile_lookup(value: float, quantiles: np.ndarray) -> float:
    """정렬된 분위수 배열에 대해 value 의 percentile (0~1) 을 찾음."""
    if np.isnan(value) or len(quantiles) == 0:
        return float("nan")
    # searchsorted: 삽입 위치 반환. left 인덱스 / N-1 = percentile.
    idx = int(np.searchsorted(quantiles, value, side="right"))
    n = len(quantiles)
    if idx <= 0:
        return 0.0
    if idx >= n:
        return 1.0
    return idx / (n - 1)


def _zscore_clip_normalize(value: float, mean: float, std: float, clip: float) -> float:
    if np.isnan(value) or std <= 0:
        return float("nan")
    z = (value - mean) / std
    z = max(-clip, min(clip, z))
    return (z + clip) / (2.0 * clip)


def _scale_to_unit(value: float, lo: float, hi: float) -> float:
    if np.isnan(value) or hi <= lo:
        return float("nan")
    v = max(lo, min(hi, value))
    return (v - lo) / (hi - lo)


def _linear_hour_trig(value: float) -> float:
    """sin/cos (-1~1) → 0~1."""
    if np.isnan(value):
        return float("nan")
    return (max(-1.0, min(1.0, value)) + 1.0) / 2.0


def _linear_bb_percent_b(value: float) -> float:
    """bb_percent_b: clip(-0.5, 1.5) → +0.5 → /2.0."""
    if np.isnan(value):
        return float("nan")
    v = max(-0.5, min(1.5, value))
    return (v + 0.5) / 2.0


# 피처별 정규화 방식 (pipeline.normalize_features 와 일치)
_ROLLING_PCT_FEATURES = {
    "pct_from_open", "ret_1min", "ret_5min", "ret_15min", "ret_30min",
    "vol_ratio_5d", "atr_pct_14d", "realized_vol_30min", "obv_slope_5d",
}
_SCALE_TO_UNIT_FEATURES = {"rsi_14", "adx_14", "stoch_k_14", "minutes_since_open"}
_ZSCORE_CLIP_FEATURES = {
    "macd_hist",
    "rel_ret_20d_kospi", "rel_ret_20d_kosdaq",
    "kospi_trend_5d", "kospi_vol_20d",
    "gap_pct", "prior_day_range", "cum_ret_3d",
}
_LINEAR_HOUR = {"hour_sin", "hour_cos"}
_LINEAR_BB = {"bb_percent_b"}


def normalize_feature(name: str, value: float, params: WeightedScoreParams) -> float:
    """raw 값 → 0~1 정규화 값. 학습 시 분포/상수 기준."""
    if np.isnan(value):
        return float("nan")
    if name in _ROLLING_PCT_FEATURES:
        q = params.rolling_percentile_quantiles.get(name)
        if q is None:
            return float("nan")
        return _rolling_percentile_lookup(value, q)
    if name in _SCALE_TO_UNIT_FEATURES:
        rng = params.scale_to_unit_ranges.get(name)
        if rng is None:
            return float("nan")
        return _scale_to_unit(value, rng[0], rng[1])
    if name in _ZSCORE_CLIP_FEATURES:
        p = params.zscore_params.get(name)
        if p is None:
            return float("nan")
        return _zscore_clip_normalize(value, p["mean"], p["std"], params.zscore_clip)
    if name in _LINEAR_HOUR:
        return _linear_hour_trig(value)
    if name in _LINEAR_BB:
        return _linear_bb_percent_b(value)
    return float("nan")  # 알 수 없는 피처


def normalize_feature_dict(
    raw: Dict[str, float], params: WeightedScoreParams
) -> Dict[str, float]:
    return {name: normalize_feature(name, val, params) for name, val in raw.items()}


# ============================================================================
#  Intraday (분봉 실시간 + 시간) raw 피처 계산
# ============================================================================


@dataclass
class IntradayBar:
    """피처 계산에 필요한 분봉 정보."""
    trade_date: str       # YYYYMMDD
    time_str: str         # HHMMSS
    open: float
    high: float
    low: float
    close: float
    volume: float


def compute_intraday_raw(
    bars: pd.DataFrame,
    day_open: float,
    past_volume_by_idx: Optional[Dict[int, float]] = None,
) -> Dict[str, float]:
    """분봉 DF 의 마지막 바 시점에 대한 intraday+temporal raw 피처.

    Args:
        bars: 당일 분봉 DF (컬럼: trade_date, idx, time, open, high, low, close, volume).
              정렬 (trade_date, idx 오름차순) 전제.
        day_open: 당일 첫 분봉의 open.
        past_volume_by_idx: {idx: 평균 volume} — 최근 5거래일 같은 idx 의 평균.
                             vol_ratio_5d 계산에 사용. None 이면 NaN.

    Returns:
        dict with keys:
            pct_from_open, ret_1min, ret_5min, ret_15min, ret_30min,
            vol_ratio_5d, realized_vol_30min,
            hour_sin, hour_cos, minutes_since_open
    """
    out: Dict[str, float] = {
        "pct_from_open": float("nan"),
        "ret_1min": float("nan"),
        "ret_5min": float("nan"),
        "ret_15min": float("nan"),
        "ret_30min": float("nan"),
        "vol_ratio_5d": float("nan"),
        "realized_vol_30min": float("nan"),
        "hour_sin": float("nan"),
        "hour_cos": float("nan"),
        "minutes_since_open": float("nan"),
    }

    if bars is None or len(bars) == 0 or day_open is None or day_open <= 0:
        return out

    closes = bars["close"].astype(float).to_numpy()
    last_close = float(closes[-1])
    last_row = bars.iloc[-1]
    n = len(closes)

    # --- 가격/모멘텀 ---
    out["pct_from_open"] = (last_close / day_open - 1.0) * 100.0
    if n >= 2 and closes[-2] > 0:
        out["ret_1min"] = (last_close / closes[-2] - 1.0) * 100.0
    for lag, key in ((5, "ret_5min"), (15, "ret_15min"), (30, "ret_30min")):
        if n >= lag + 1 and closes[-1 - lag] > 0:
            out[key] = (last_close / closes[-1 - lag] - 1.0) * 100.0

    # --- realized vol 30min (ret_1min 의 30분 std) ---
    if n >= 31:
        window_close = closes[-31:]
        rets = np.diff(window_close) / window_close[:-1]
        rets_pct = rets * 100.0
        if len(rets_pct) >= 2:
            out["realized_vol_30min"] = float(np.std(rets_pct, ddof=1))

    # --- volume ratio (현재 분봉 volume / 과거 5일 평균 같은 idx volume) ---
    if past_volume_by_idx is not None and "idx" in bars.columns:
        cur_idx = int(last_row["idx"])
        cur_vol = float(last_row["volume"])
        past_avg = past_volume_by_idx.get(cur_idx)
        if past_avg is not None and past_avg > 0:
            out["vol_ratio_5d"] = cur_vol / past_avg

    # --- temporal ---
    time_str = str(last_row["time"]).zfill(6)
    try:
        hh = int(time_str[0:2])
        mm = int(time_str[2:4])
    except ValueError:
        hh, mm = 0, 0
    angle = 2.0 * math.pi * (hh + mm / 60.0) / 24.0
    out["hour_sin"] = math.sin(angle)
    out["hour_cos"] = math.cos(angle)
    # minutes_since_open: 09:00 기준. 범위 [0, 390].
    mso = (hh - 9) * 60 + mm
    out["minutes_since_open"] = float(max(0, min(8 * 60, mso)))

    return out


# ============================================================================
#  Daily raw 피처 계산 (장 시작 전 1회)
# ============================================================================


def _atr(daily: pd.DataFrame, window: int = 14) -> pd.Series:
    high = daily["high"].astype(float)
    low = daily["low"].astype(float)
    close_prev = daily["close"].astype(float).shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - close_prev).abs(), (low - close_prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=window, min_periods=window).mean()


def _obv(daily: pd.DataFrame) -> pd.Series:
    close = daily["close"].astype(float)
    vol = daily["volume"].astype(float)
    diff = close.diff()
    signed = vol.where(diff > 0, -vol.where(diff < 0, 0))
    return signed.fillna(0).cumsum()


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    def _slope(y: np.ndarray) -> float:
        if np.isnan(y).any():
            return np.nan
        x = np.arange(len(y), dtype=float)
        x_mean = x.mean()
        y_mean = y.mean()
        denom = ((x - x_mean) ** 2).sum()
        if denom == 0:
            return 0.0
        return float(((x - x_mean) * (y - y_mean)).sum() / denom)

    return series.rolling(window=window, min_periods=window).apply(_slope, raw=True)


def compute_daily_raw(
    stock_daily: pd.DataFrame,
    kospi_daily: pd.DataFrame,
    kosdaq_daily: pd.DataFrame,
    target_trade_date: str,
) -> Dict[str, float]:
    """해당 종목의 `target_trade_date` 에 적용할 daily 피처 12개 계산.

    모든 피처는 `target_trade_date` **전일까지** 의 데이터로만 계산됨 (shift(1)).

    Args:
        stock_daily: 종목 일봉 DF. 컬럼: trade_date (YYYYMMDD), open, high, low, close, volume.
                     정렬 (trade_date 오름차순). **당일 포함 가능** (shift 로 제외).
        kospi_daily: KS11 일봉 DF. 컬럼: date (YYYYMMDD), open, close, high, low.
        kosdaq_daily: KQ11 일봉 DF. 같은 구조.
        target_trade_date: YYYYMMDD, 적용 대상 일자.

    Returns:
        dict with 12 keys. NaN 시 해당 피처 NaN.
    """
    out: Dict[str, float] = {
        "rsi_14": float("nan"),
        "macd_hist": float("nan"),
        "bb_percent_b": float("nan"),
        "adx_14": float("nan"),
        "atr_pct_14d": float("nan"),
        "obv_slope_5d": float("nan"),
        "rel_ret_20d_kospi": float("nan"),
        "rel_ret_20d_kosdaq": float("nan"),
        "kospi_trend_5d": float("nan"),
        "kospi_vol_20d": float("nan"),
        "gap_pct": float("nan"),
        "prior_day_range": float("nan"),
        "cum_ret_3d": float("nan"),
    }

    if stock_daily is None or stock_daily.empty:
        return out

    d = stock_daily.sort_values("trade_date").reset_index(drop=True).copy()
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = pd.to_numeric(d[c], errors="coerce")

    # 해당 일자 이전 데이터만 사용 (당일 포함하지만 계산 시 shift(1))
    d = d[d["trade_date"] <= target_trade_date].reset_index(drop=True)
    if len(d) < 5:
        return out

    # 실거래에서 prep 시점에 당일 분봉이 아직 없을 수 있음 (09:00 개장 직후).
    # shift(1) 기반 피처 11개는 어제까지 데이터로 계산 가능하므로, 당일 placeholder
    # 행을 삽입해 `mask.any()` 로 lookup 이 동작하도록 한다. gap_pct 는 NaN 으로 남음.
    if not (d["trade_date"] == target_trade_date).any():
        d = pd.concat(
            [
                d,
                pd.DataFrame(
                    [
                        {
                            "trade_date": target_trade_date,
                            "open": float("nan"),
                            "high": float("nan"),
                            "low": float("nan"),
                            "close": float("nan"),
                            "volume": float("nan"),
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    # --- 기술지표 (ta lib, shift(1)) ---
    try:
        from ta.momentum import RSIIndicator, StochasticOscillator
        from ta.trend import MACD, ADXIndicator
        from ta.volatility import BollingerBands
    except ImportError:
        # ta 없으면 모두 NaN
        pass
    else:
        close = d["close"]
        high = d["high"]
        low = d["low"]
        try:
            rsi = RSIIndicator(close=close, window=14, fillna=False).rsi().shift(1)
            macd = MACD(close=close, fillna=False).macd_diff().shift(1)
            bb = BollingerBands(close=close, window=20, window_dev=2, fillna=False).bollinger_pband().shift(1)
            adx = ADXIndicator(high=high, low=low, close=close, window=14, fillna=False).adx().shift(1)

            # target 날 row
            mask = d["trade_date"] == target_trade_date
            if mask.any():
                idx = d.index[mask][-1]
                out["rsi_14"] = float(rsi.iloc[idx]) if not pd.isna(rsi.iloc[idx]) else float("nan")
                out["macd_hist"] = float(macd.iloc[idx]) if not pd.isna(macd.iloc[idx]) else float("nan")
                out["bb_percent_b"] = float(bb.iloc[idx]) if not pd.isna(bb.iloc[idx]) else float("nan")
                out["adx_14"] = float(adx.iloc[idx]) if not pd.isna(adx.iloc[idx]) else float("nan")
        except Exception:
            pass

    # --- ATR% (14d, shift(1)) ---
    atr = _atr(d, 14)
    atr_pct = (atr / d["close"].astype(float)) * 100.0
    atr_pct = atr_pct.shift(1)

    # --- OBV slope (5d daily, shift(1)) ---
    obv = _obv(d)
    avg_dollar = (d["close"] * d["volume"]).rolling(window=20, min_periods=5).mean()
    obv_slope_raw = _rolling_slope(obv, window=5)
    obv_norm = (obv_slope_raw / avg_dollar.replace(0, np.nan)).shift(1)

    # --- 이전 데이터 (gap, range, cum_ret_3d) ---
    prev_close = d["close"].shift(1)
    prev_high = d["high"].shift(1)
    prev_low = d["low"].shift(1)
    gap_pct = (d["open"] - prev_close) / prev_close * 100.0
    prior_day_range = (prev_high - prev_low) / prev_close * 100.0
    cum_ret_3d = (d["close"].shift(1) / d["close"].shift(4) - 1.0) * 100.0

    mask = d["trade_date"] == target_trade_date
    if mask.any():
        idx = d.index[mask][-1]
        out["atr_pct_14d"] = float(atr_pct.iloc[idx]) if not pd.isna(atr_pct.iloc[idx]) else float("nan")
        out["obv_slope_5d"] = float(obv_norm.iloc[idx]) if not pd.isna(obv_norm.iloc[idx]) else float("nan")
        out["gap_pct"] = float(gap_pct.iloc[idx]) if not pd.isna(gap_pct.iloc[idx]) else float("nan")
        out["prior_day_range"] = float(prior_day_range.iloc[idx]) if not pd.isna(prior_day_range.iloc[idx]) else float("nan")
        out["cum_ret_3d"] = float(cum_ret_3d.iloc[idx]) if not pd.isna(cum_ret_3d.iloc[idx]) else float("nan")

    # --- 상대강도·시장 (vs KS11/KQ11, shift(1)) ---
    stock_ret_20d = (d["close"] / d["close"].shift(20) - 1.0).shift(1)

    def _map_to_date(idx_daily: pd.DataFrame, col: str) -> Optional[float]:
        if idx_daily is None or idx_daily.empty:
            return None
        id_ = idx_daily.copy().sort_values("date").reset_index(drop=True)
        id_["close"] = pd.to_numeric(id_["close"], errors="coerce")
        id_["ret"] = id_["close"].pct_change()
        id_["ret_20d"] = id_["close"].pct_change(20)
        id_["ret_5d"] = id_["close"].pct_change(5)
        id_["vol_20d"] = id_["ret"].rolling(window=20, min_periods=10).std() * 100.0
        # shift(1)
        id_[col] = id_[col].shift(1) if col in id_.columns else None
        row = id_[id_["date"] == target_trade_date]
        if row.empty:
            return None
        v = row.iloc[-1][col]
        return float(v) if not pd.isna(v) else None

    # KOSPI
    if kospi_daily is not None and not kospi_daily.empty:
        ks = kospi_daily.copy().sort_values("date").reset_index(drop=True)
        ks["close"] = pd.to_numeric(ks["close"], errors="coerce")
        ks["ret"] = ks["close"].pct_change()
        ks["ret_20d"] = ks["close"].pct_change(20).shift(1)
        ks["ret_5d"] = ks["close"].pct_change(5).shift(1)
        ks["vol_20d"] = (ks["ret"].rolling(window=20, min_periods=10).std() * 100.0).shift(1)
        row = ks[ks["date"] == target_trade_date]
        if not row.empty:
            r = row.iloc[-1]
            if not pd.isna(r["ret_5d"]):
                out["kospi_trend_5d"] = float(r["ret_5d"])
            if not pd.isna(r["vol_20d"]):
                out["kospi_vol_20d"] = float(r["vol_20d"])
            if not pd.isna(r["ret_20d"]) and mask.any():
                stock20 = stock_ret_20d.iloc[d.index[mask][-1]]
                if not pd.isna(stock20):
                    out["rel_ret_20d_kospi"] = float(stock20 - r["ret_20d"])

    # KOSDAQ
    if kosdaq_daily is not None and not kosdaq_daily.empty:
        kq = kosdaq_daily.copy().sort_values("date").reset_index(drop=True)
        kq["close"] = pd.to_numeric(kq["close"], errors="coerce")
        kq["ret_20d"] = kq["close"].pct_change(20).shift(1)
        row = kq[kq["date"] == target_trade_date]
        if not row.empty:
            r = row.iloc[-1]
            if not pd.isna(r["ret_20d"]) and mask.any():
                stock20 = stock_ret_20d.iloc[d.index[mask][-1]]
                if not pd.isna(stock20):
                    out["rel_ret_20d_kosdaq"] = float(stock20 - r["ret_20d"])

    return out


# ============================================================================
#  Score 계산
# ============================================================================


def compute_score(
    normalized: Dict[str, float],
    params: WeightedScoreParams,
) -> float:
    """정규화 피처 dict + 가중치 → 최종 score (가중합). NaN 피처 있으면 NaN."""
    total = 0.0
    for name in params.feature_names:
        w = params.weights.get(name, 0.0)
        if abs(w) < 1e-12:
            continue
        v = normalized.get(name)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return float("nan")
        total += w * v
    return total


def past_volume_by_idx_from_minutes(
    past_minute_df: pd.DataFrame,
    n_days: int = 5,
) -> Dict[int, float]:
    """최근 n_days 거래일 분봉에서 (idx → 평균 volume) 맵 생성.

    당일 제외. vol_ratio_5d 계산용.
    """
    if past_minute_df is None or past_minute_df.empty:
        return {}
    df = past_minute_df.copy()
    recent_dates = sorted(df["trade_date"].unique())[-n_days:]
    sub = df[df["trade_date"].isin(recent_dates)]
    if sub.empty:
        return {}
    grouped = sub.groupby("idx")["volume"].mean()
    return {int(k): float(v) for k, v in grouped.items()}
