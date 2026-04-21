"""Universe: 260일+ 풀커버 종목 리스트 확정 및 조회.

트레이드 기간 중 MIN_TRADING_DAYS 이상 데이터가 존재하는 종목만 포함한다.
첫 실행 시 DB에서 조회해 parquet/json 으로 스냅샷 저장, 이후 실행은 스냅샷 재사용.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg2

from analysis.research.weighted_score import config

UNIVERSE_SNAPSHOT = config.RESEARCH_ROOT / "universe_snapshot.json"


@dataclass(frozen=True)
class UniverseEntry:
    stock_code: str
    n_days: int
    first_date: str
    last_date: str


def _open_conn():
    from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD

    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD,
        connect_timeout=10,
    )


def query_universe_from_db(
    min_days: int = config.MIN_TRADING_DAYS,
    date_start: str = config.DATA_START,
    date_end: str = config.DATA_END,
) -> list[UniverseEntry]:
    """min_days 이상 거래일을 커버하는 종목 리스트를 DB에서 조회."""
    sql = """
        SELECT stock_code,
               COUNT(DISTINCT trade_date) AS n_days,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date
        FROM minute_candles
        WHERE trade_date BETWEEN %s AND %s
        GROUP BY stock_code
        HAVING COUNT(DISTINCT trade_date) >= %s
        ORDER BY n_days DESC, stock_code ASC
    """
    with _open_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (date_start, date_end, min_days))
        rows = cur.fetchall()
    return [UniverseEntry(code, n, first, last) for code, n, first, last in rows]


def save_snapshot(entries: Iterable[UniverseEntry], path: Path = UNIVERSE_SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "min_days": config.MIN_TRADING_DAYS,
        "date_start": config.DATA_START,
        "date_end": config.DATA_END,
        "count": sum(1 for _ in entries) if not isinstance(entries, list) else len(entries),
        "entries": [
            {
                "stock_code": e.stock_code,
                "n_days": e.n_days,
                "first_date": e.first_date,
                "last_date": e.last_date,
            }
            for e in entries
        ],
    }
    # count 재계산 (iterator 고갈 회피를 위해 entries를 list로 받음)
    payload["count"] = len(payload["entries"])
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_snapshot(path: Path = UNIVERSE_SNAPSHOT) -> list[UniverseEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [UniverseEntry(**e) for e in data["entries"]]


def get_universe(refresh: bool = False) -> list[UniverseEntry]:
    """snapshot 이 있으면 재사용, 없거나 refresh=True 면 DB 재조회."""
    if not refresh and UNIVERSE_SNAPSHOT.exists():
        return load_snapshot()
    entries = query_universe_from_db()
    save_snapshot(entries)
    return entries


def universe_codes(refresh: bool = False) -> list[str]:
    return [e.stock_code for e in get_universe(refresh=refresh)]


if __name__ == "__main__":
    # 수동 실행: python -m analysis.research.weighted_score.universe
    entries = query_universe_from_db()
    save_snapshot(entries)
    print(f"Universe 확정: {len(entries)}종목 (min_days={config.MIN_TRADING_DAYS}, {config.DATA_START}~{config.DATA_END})")
    if entries:
        head = entries[:3]
        tail = entries[-3:]
        print("상위 3종목:")
        for e in head:
            print(f"  {e.stock_code}  n_days={e.n_days}  {e.first_date}~{e.last_date}")
        print("하위 3종목:")
        for e in tail:
            print(f"  {e.stock_code}  n_days={e.n_days}  {e.first_date}~{e.last_date}")
    print(f"스냅샷 저장: {UNIVERSE_SNAPSHOT}")
