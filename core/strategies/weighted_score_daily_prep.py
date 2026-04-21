"""Weighted Score 전략의 pre_market daily 피처 준비 모듈.

책임:
- universe 후보 종목에 대해 daily 피처 12개 계산 → strategy.update_daily_features()
- past_volume_by_idx 맵 계산 (최근 5거래일 분봉) → strategy.update_past_volume_map()

**사용 위치 (예정)**: `main.py._pre_market_task()` 내 08:50 전후. ACTIVE_STRATEGY=='weighted_score' 일 때만.

**파일 구조**:
    prepare_for_trade_date(strategy, codes, target_date, logger) → summary

데이터 소스:
- 종목 일봉: `minute_candles` 에서 집계 (utils/data_cache.load_minute_candles 사용)
  - 연구 단계와 동일한 방식 (`daily_bars.aggregate_minutes_to_daily`)
- KS11/KQ11 일봉: `daily_candles` 테이블 (PostgreSQL)
- 분봉 5일: `minute_candles` 최근 5 거래일

성능: 300종목 × 40일 분봉 로드 → 약 3~5분. pre_market 08:00~09:00 구간에서 실행.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

import pandas as pd

from core.strategies.weighted_score_features import (
    compute_daily_raw,
    past_volume_by_idx_from_minutes,
)
from core.strategies.weighted_score_strategy import WeightedScoreStrategy


def _prior_trading_dates(target: str, n_days: int = 45) -> List[str]:
    """target 이전의 거래일 후보 (calendar 기준 -2*n 일). 실제 거래일은 DB 조회 후 필터."""
    dt = datetime.strptime(target, "%Y%m%d")
    out = []
    for i in range(1, n_days * 2):
        prev = dt - timedelta(days=i)
        out.append(prev.strftime("%Y%m%d"))
    return out


def _load_stock_daily_from_minutes(
    stock_code: str,
    dates: List[str],
    loader,
) -> pd.DataFrame:
    """분봉 → 일봉 집계 (연구 단계 daily_bars.aggregate_minutes_to_daily 와 동치).

    Args:
        stock_code: 종목코드
        dates: YYYYMMDD 리스트
        loader: callable(stock_code, date) → pd.DataFrame (분봉) 또는 None.
                실거래 환경에서는 `utils.data_cache.MinuteDataCache().load_data` 사용.

    Returns:
        일봉 DF. 컬럼: trade_date, open, high, low, close, volume.
    """
    rows = []
    for d in dates:
        mdf = loader(stock_code, d)
        if mdf is None or len(mdf) == 0:
            continue
        mdf_sorted = mdf.sort_values("idx") if "idx" in mdf.columns else mdf
        rows.append({
            "trade_date": d,
            "open": float(mdf_sorted.iloc[0]["open"]),
            "high": float(mdf_sorted["high"].max()),
            "low": float(mdf_sorted["low"].min()),
            "close": float(mdf_sorted.iloc[-1]["close"]),
            "volume": float(mdf_sorted["volume"].sum()),
        })
    if not rows:
        return pd.DataFrame(columns=["trade_date", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)


def _load_past_5d_minutes(
    stock_code: str,
    target_date: str,
    loader,
    n: int = 5,
) -> pd.DataFrame:
    """target 이전 n 거래일 분봉을 concat. vol_ratio_5d 계산용."""
    candidates = _prior_trading_dates(target_date, n_days=20)
    collected = []
    n_found = 0
    for d in candidates:
        mdf = loader(stock_code, d)
        if mdf is None or len(mdf) == 0:
            continue
        mdf = mdf.copy()
        mdf["trade_date"] = d
        collected.append(mdf)
        n_found += 1
        if n_found >= n:
            break
    if not collected:
        return pd.DataFrame(columns=["trade_date", "idx", "volume"])
    return pd.concat(collected, ignore_index=True)


def _load_index_daily(symbol: str, conn) -> pd.DataFrame:
    """daily_candles 에서 KS11/KQ11 일봉 로드.

    conn: psycopg2 connection 또는 유사.
    """
    import psycopg2.extras
    sql = """
        SELECT stck_bsop_date AS date,
               stck_clpr AS close, stck_oprc AS open,
               stck_hgpr AS high, stck_lwpr AS low
        FROM daily_candles
        WHERE stock_code = %s
        ORDER BY stck_bsop_date
    """
    df = pd.read_sql_query(sql, conn, params=(symbol,))
    if df.empty:
        return df
    for c in ("close", "open", "high", "low"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def prepare_for_trade_date(
    strategy: WeightedScoreStrategy,
    stock_codes: Iterable[str],
    target_date: str,
    minute_loader,
    pg_conn,
    logger=None,
) -> Dict:
    """pre_market 에서 호출. strategy 에 daily 피처 / past_volume 주입.

    Args:
        strategy: 초기화된 WeightedScoreStrategy
        stock_codes: universe 종목 리스트
        target_date: YYYYMMDD (오늘)
        minute_loader: callable(stock_code, date) → 분봉 DF
        pg_conn: psycopg2 connection (KS11/KQ11 일봉용). None 이면 해당 피처 NaN.

    Returns:
        summary dict: {loaded: int, skipped_no_daily: int, skipped_no_prior: int, elapsed_sec: float}
    """
    t0 = time.time()

    # 지수 일봉 로드 (모든 종목 공통)
    kospi_df = pd.DataFrame()
    kosdaq_df = pd.DataFrame()
    if pg_conn is not None:
        try:
            kospi_df = _load_index_daily("KS11", pg_conn)
        except Exception as e:
            if logger:
                logger.warning(f"KS11 로드 실패: {e}")
        try:
            kosdaq_df = _load_index_daily("KQ11", pg_conn)
        except Exception as e:
            if logger:
                logger.warning(f"KQ11 로드 실패: {e}")

    dates_to_try = _prior_trading_dates(target_date, n_days=45)[::-1] + [target_date]

    loaded = 0
    skipped_no_daily = 0
    skipped_no_prior = 0

    codes = list(stock_codes)
    for i, code in enumerate(codes, 1):
        try:
            stock_daily = _load_stock_daily_from_minutes(code, dates_to_try, minute_loader)
            if len(stock_daily) < 21:  # 20d rolling 피처를 위해 최소 21거래일 필요
                skipped_no_daily += 1
                continue

            raw = compute_daily_raw(
                stock_daily=stock_daily,
                kospi_daily=kospi_df,
                kosdaq_daily=kosdaq_df,
                target_trade_date=target_date,
            )
            strategy.update_daily_features(code, raw)

            past_min = _load_past_5d_minutes(code, target_date, minute_loader, n=5)
            if past_min.empty:
                skipped_no_prior += 1
                continue
            vol_map = past_volume_by_idx_from_minutes(past_min, n_days=5)
            strategy.update_past_volume_map(code, vol_map)
            loaded += 1

            if logger and i % 50 == 0:
                logger.info(f"[weighted_score.prep] {i}/{len(codes)} loaded={loaded}")

        except Exception as e:
            if logger:
                logger.warning(f"[weighted_score.prep] {code}: {e}")

    elapsed = time.time() - t0
    summary = {
        "target_date": target_date,
        "n_requested": len(codes),
        "loaded": loaded,
        "skipped_no_daily": skipped_no_daily,
        "skipped_no_prior": skipped_no_prior,
        "elapsed_sec": elapsed,
    }
    if logger:
        logger.info(
            f"[weighted_score.prep] done {target_date}: "
            f"loaded={loaded}/{len(codes)}  elapsed={elapsed:.1f}s"
        )
    return summary
