"""Universe selection bias 검증.

원래 universe: 거래대금 상위 30 (2025-03 ~ 2026-02 = 12 개월).
OOS (2026-03 ~ 04) 는 그 이후라 기술적으로 look-ahead 없지만,
"trading 시점 (2026-03-01) 에 알 수 있던" universe 로 재선정 후 OOS 재실행.

다음 universe 정의로 macd_cross OOS 재현 여부 확인:
  A. 원래: 2025-03 ~ 2026-02 거래대금 (12 개월) → 기존 결과
  B. 6개월: 2025-09 ~ 2026-02 거래대금 (직전 6 개월)
  C. 3개월: 2025-12 ~ 2026-02 거래대금 (직전 3 개월)
  D. 1개월: 2026-02 만 (직전 1 개월)
"""
import json
from pathlib import Path

import pandas as pd
import psycopg2

from config.settings import (
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD,
)
try:
    from config.settings import PG_DATABASE_QUANT
except ImportError:
    PG_DATABASE_QUANT = "robotrader_quant"

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.common.engine import BacktestEngine
from backtests.strategies.macd_cross import MACDCrossStrategy


def select_universe_pre_oos(start: str, end: str, n_stocks: int = 30,
                             min_days_present: int = 20):
    """주어진 기간 거래대금 + daily 데이터 보유 종목 top N."""
    sql = """
        SELECT stock_code,
               COUNT(DISTINCT trade_date) AS days,
               SUM(amount) AS total_amount
        FROM minute_candles
        WHERE trade_date >= %s AND trade_date <= %s
        GROUP BY stock_code
        HAVING COUNT(DISTINCT trade_date) >= %s
        ORDER BY total_amount DESC NULLS LAST
        LIMIT %s
    """
    with psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                          user=PG_USER, password=PG_PASSWORD) as c:
        cur = c.cursor()
        cur.execute(sql, (start, end, min_days_present, n_stocks * 3))
        cands = [r[0] for r in cur.fetchall()]

    # daily_prices 보유 필터
    sql2 = """
        SELECT stock_code FROM daily_prices
        WHERE stock_code = ANY(%s)
        GROUP BY stock_code HAVING COUNT(*) >= 60
    """
    with psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE_QUANT,
                          user=PG_USER, password=PG_PASSWORD) as c:
        cur = c.cursor()
        cur.execute(sql2, (cands,))
        valid = {r[0] for r in cur.fetchall()}

    return [c for c in cands if c in valid][:n_stocks]


def run_oos_with_universe(strategy_class, params, universe,
                           oos_start="20260301", oos_end="20260424"):
    minute_df = load_minute_df(universe, oos_start, oos_end)
    daily_df = load_daily_df(universe, "20250101", oos_end)
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    nonempty = [c for c in universe if len(minute_by_code[c]) > 0]
    eng = BacktestEngine(
        strategy=strategy_class(**params),
        initial_capital=100_000_000,
        universe=nonempty,
        minute_df_by_code={c: minute_by_code[c] for c in nonempty},
        daily_df_by_code={c: daily_by_code[c] for c in nonempty},
    )
    return eng.run().metrics, len(nonempty)


def main():
    # macd_cross best params 로딩
    best_path = Path("backtests/reports/stage2/macd_cross_best.json")
    d = json.loads(best_path.read_text(encoding="utf-8"))
    params = d["best_params"]
    print(f"macd_cross best params: {params}")
    print(f"Stage 2 avg Calmar: {d['best_value']:.2f}\n")

    universe_defs = {
        "A_12mo (orig 2025-03~2026-02)": ("20250301", "20260228"),
        "B_6mo  (2025-09~2026-02)": ("20250901", "20260228"),
        "C_3mo  (2025-12~2026-02)": ("20251201", "20260228"),
        "D_1mo  (2026-02 only)": ("20260201", "20260228"),
    }

    print(f"{'universe':<30} {'overlap%':>9} {'OOS_calmar':>11} "
          f"{'OOS_ret':>8} {'OOS_mdd':>8} {'trades':>7} {'status':>8}")
    print("-" * 84)

    # A 의 universe 를 기준으로 overlap 계산
    base_universe = None
    for label, (s, e) in universe_defs.items():
        universe = select_universe_pre_oos(s, e, n_stocks=30, min_days_present=20)
        if base_universe is None:
            base_universe = set(universe)
        overlap = len(set(universe) & base_universe) / 30 * 100

        try:
            metrics, n_used = run_oos_with_universe(MACDCrossStrategy, params, universe)
        except Exception as ex:
            print(f"{label:<30} ERROR: {ex}")
            continue

        calmar = metrics.get("calmar", float("nan"))
        ret = metrics.get("total_return", 0)
        mdd = metrics.get("mdd", 0)
        trades = metrics.get("total_trades", 0)
        status = "PASS" if (pd.notna(calmar) and calmar >= 5) else "FAIL"
        print(
            f"{label:<30} {overlap:>8.0f}% {calmar:>10.2f} "
            f"{ret:>7.2%} {mdd:>7.2%} {trades:>7d}  {status:>7}"
        )


if __name__ == "__main__":
    main()
