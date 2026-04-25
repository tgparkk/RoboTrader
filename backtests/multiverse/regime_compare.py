"""Fold2 vs OOS vs (Fold1+Fold3) 시장 레짐 비교.

macd_cross 가 fold2 에서 Calmar -3.12, OOS 에서 +54.16 차이가
시장 레짐 변화에 의한 것인지 평가.

지표 (KOSPI/KOSDAQ 각각):
  - daily return: mean / std (annualized) / skew / kurtosis
  - 음수 일 비율
  - 누적 수익률 / MDD (period 내)
  - daily range (high-low) / open
  - gap pct (open vs prev close) 분포
  - 추세 slope (cumret linear fit)
"""
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd
import psycopg2

from config.settings import (
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD,
)


PERIODS = {
    "fold1_test (2025-09~10)": ("20250901", "20251031"),
    "fold2_test (2025-11~12)": ("20251101", "20251231"),
    "fold3_test (2026-01~02)": ("20260101", "20260228"),
    "OOS       (2026-03~04)": ("20260301", "20260424"),
}


def load_index_daily(code: str, start: str, end: str) -> pd.DataFrame:
    sql = """
        SELECT stck_bsop_date AS date,
               CAST(stck_oprc AS DOUBLE PRECISION) AS open,
               CAST(stck_hgpr AS DOUBLE PRECISION) AS high,
               CAST(stck_lwpr AS DOUBLE PRECISION) AS low,
               CAST(stck_clpr AS DOUBLE PRECISION) AS close
        FROM daily_candles
        WHERE stock_code = %s
          AND stck_bsop_date >= %s
          AND stck_bsop_date <= %s
        ORDER BY stck_bsop_date
    """
    with psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                          user=PG_USER, password=PG_PASSWORD) as c:
        df = pd.read_sql(sql, c, params=(code, start, end))
    df["date"] = pd.to_datetime(df["date"])
    return df


def compute_regime_stats(df: pd.DataFrame) -> Dict[str, float]:
    if len(df) < 2:
        return {}
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"].astype(float)
    ret = close.pct_change().dropna()  # daily simple return

    # gap = open vs prev close
    prev_close = close.shift(1)
    gap = (df["open"] - prev_close) / prev_close
    gap = gap.dropna()

    # daily range
    daily_range = (df["high"] - df["low"]) / df["open"]

    # cumulative return
    cumret = (1 + ret).cumprod()
    mdd = (cumret / cumret.cummax() - 1).min()

    # trend slope (linear fit on log cumret)
    x = np.arange(len(cumret))
    y = np.log(cumret.values)
    slope_per_day = np.polyfit(x, y, 1)[0] if len(y) >= 2 else 0.0

    return {
        "n_days": int(len(ret)),
        "mean_ret_pct": float(ret.mean() * 100),
        "std_ret_pct_ann": float(ret.std() * np.sqrt(252) * 100),
        "skew_ret": float(ret.skew()),
        "kurt_ret": float(ret.kurt()),
        "neg_day_pct": float((ret < 0).mean() * 100),
        "cumret_pct": float((cumret.iloc[-1] - 1) * 100),
        "mdd_pct": float(mdd * 100),
        "trend_slope_per_day_bps": float(slope_per_day * 10000),
        "gap_mean_pct": float(gap.mean() * 100),
        "gap_std_pct": float(gap.std() * 100),
        "gap_neg_pct": float((gap < 0).mean() * 100),
        "daily_range_mean_pct": float(daily_range.mean() * 100),
        "daily_range_std_pct": float(daily_range.std() * 100),
    }


def main():
    print("=== KOSPI/KOSDAQ 레짐 비교 (각 기간 daily 일봉) ===\n")

    for code, label in [("KS11", "KOSPI"), ("KQ11", "KOSDAQ")]:
        print(f"\n##### {label} ({code}) #####\n")
        rows = []
        for period_label, (start, end) in PERIODS.items():
            df = load_index_daily(code, start, end)
            stats = compute_regime_stats(df)
            stats["period"] = period_label
            rows.append(stats)
        out = pd.DataFrame(rows).set_index("period")
        # 출력 — 기간을 컬럼, 지표를 행으로 transpose
        print(out.T.to_string(float_format=lambda x: f"{x:8.2f}"))

    # macd_cross fold-별 결과를 reference 로 출력
    print("\n\n=== macd_cross Stage 2 best params per-fold + OOS Calmar ===")
    print("  fold1_test  (2025-09~10):  +39.48")
    print("  fold2_test  (2025-11~12):  -3.12   ← 약세")
    print("  fold3_test  (2026-01~02):  +227.17")
    print("  OOS         (2026-03~04):  +54.16  ← 통과")


if __name__ == "__main__":
    main()
