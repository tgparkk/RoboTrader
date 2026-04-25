"""Stage 1/2 백테스트 universe 선정.

기준:
  - Fold 기간 동안 minute_candles 에 충분한 데이터 (>= min_days_present)
  - SUM(amount) 거래대금 기준 상위 N
  - daily_prices (robotrader_quant) 에도 history 가 있어야 overnight 전략 적용 가능

선정 결과를 JSON 으로 캐시 (재실행 시 DB 쿼리 회피).
"""
import json
from pathlib import Path
from typing import List, Optional

import pandas as pd
import psycopg2

from config.settings import (
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD,
)
try:
    from config.settings import PG_DATABASE_QUANT
except ImportError:
    PG_DATABASE_QUANT = "robotrader_quant"


CACHE_DIR = Path(__file__).parent.parent / "reports" / "universe_cache"


def select_top_universe(
    fold_train_start: str,
    fold_test_end: str,
    n_stocks: int = 30,
    min_days_present: int = 100,
    cache: bool = True,
) -> List[str]:
    """Fold 기간 거래대금 기준 상위 N 종목 선정.

    Args:
        fold_train_start: Fold train 시작일 (YYYYMMDD)
        fold_test_end: Fold test 종료일
        n_stocks: 상위 N
        min_days_present: 최소 거래일 (이보다 적으면 제외)
        cache: True 면 결과를 reports/universe_cache/ 에 JSON 캐싱

    Returns:
        종목코드 리스트.
    """
    cache_path = (
        CACHE_DIR
        / f"top{n_stocks}_{fold_train_start}_{fold_test_end}_min{min_days_present}.json"
    )
    if cache and cache_path.exists():
        with cache_path.open(encoding="utf-8") as f:
            return json.load(f)["universe"]

    # 1. minute_candles 에서 기간 거래대금 + 거래일수 집계
    minute_sql = """
        SELECT stock_code,
               COUNT(DISTINCT trade_date) AS days_present,
               SUM(amount) AS total_amount
        FROM minute_candles
        WHERE trade_date >= %s AND trade_date <= %s
        GROUP BY stock_code
        HAVING COUNT(DISTINCT trade_date) >= %s
        ORDER BY total_amount DESC NULLS LAST
        LIMIT %s
    """
    cands: List[str] = []
    with psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    ) as c:
        cur = c.cursor()
        cur.execute(
            minute_sql,
            (fold_train_start, fold_test_end, min_days_present, n_stocks * 3),
        )
        cands = [r[0] for r in cur.fetchall()]

    # 2. quant.daily_prices 에 데이터가 있는지 필터
    daily_sql = """
        SELECT stock_code, COUNT(*) AS daily_rows
        FROM daily_prices
        WHERE stock_code = ANY(%s)
        GROUP BY stock_code
        HAVING COUNT(*) >= 60
    """
    with psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE_QUANT,
        user=PG_USER, password=PG_PASSWORD,
    ) as c:
        cur = c.cursor()
        cur.execute(daily_sql, (cands,))
        valid = {r[0] for r in cur.fetchall()}

    selected = [code for code in cands if code in valid][:n_stocks]

    if cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "fold_train_start": fold_train_start,
            "fold_test_end": fold_test_end,
            "n_stocks": n_stocks,
            "min_days_present": min_days_present,
            "universe": selected,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    return selected


def main():
    """CLI: 인자 없이 실행하면 STAGE1_FOLD1 universe 30 종목 선정."""
    from backtests.multiverse.fold import STAGE1_FOLD1
    universe = select_top_universe(
        fold_train_start=STAGE1_FOLD1.train_start,
        fold_test_end=STAGE1_FOLD1.test_end,
        n_stocks=30,
        min_days_present=120,  # 6개월 train + 2개월 test 의 70%+
    )
    print(f"Selected {len(universe)} stocks:")
    for i, c in enumerate(universe, 1):
        print(f"  {i:2d}. {c}")


if __name__ == "__main__":
    main()
