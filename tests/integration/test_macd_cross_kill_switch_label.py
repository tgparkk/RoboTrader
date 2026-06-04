"""킬스위치가 라벨이 덮인 macd_cross 매도를 집계하는지 검증 (회귀 테스트).

배경 (2026-06-04 진단):
  macd_cross 는 D+2 보유 중 봇 재시작 시 emergency_sync 가 포지션을 재등록하면서
  매도 레코드의 strategy 가 '보유종목 자동복구' 로 덮인다. 기존 킬스위치 SQL 은
  `WHERE strategy='macd_cross' AND action='SELL'` 로 매도 라벨만 필터하여
  실제 macd_cross 손실 23건을 0건으로 오판 → 안전망이 라이브 내내 무력화됐다.

수정: 매수 레코드(buy_record_id)의 strategy 로도 macd_cross 를 식별.

이 테스트는 실데이터를 건드리지 않도록 TEMP TABLE 이 public.real_trading_records 를
세션 내에서 shadow 하는 방식으로 main.py 의 실제 SQL 상수를 검증한다.
"""
import pytest

from main import _MACD_CROSS_KILL_SWITCH_SELL_SQL

try:
    import psycopg2
    from config import settings as _settings
    _conn = psycopg2.connect(
        host=_settings.PG_HOST, port=_settings.PG_PORT,
        dbname=_settings.PG_DATABASE, user=_settings.PG_USER,
        password=_settings.PG_PASSWORD, connect_timeout=3,
    )
    _conn.close()
    _DB_OK = True
except Exception:
    _DB_OK = False

pytestmark = pytest.mark.skipif(not _DB_OK, reason="PostgreSQL(robotrader) 미가용 — DB 통합 테스트 skip")

# 기존(버그) SQL: 매도 라벨만 필터 → 덮인 라벨을 놓침
_OLD_BUGGY_SQL = """
    SELECT timestamp, net_profit
    FROM real_trading_records
    WHERE strategy='macd_cross' AND action='SELL'
      AND net_profit IS NOT NULL
    ORDER BY timestamp ASC
"""


@pytest.fixture
def seeded_conn():
    """TEMP TABLE 로 public.real_trading_records 를 shadow 하고 대표 행을 적재."""
    conn = psycopg2.connect(
        host=_settings.PG_HOST, port=_settings.PG_PORT,
        dbname=_settings.PG_DATABASE, user=_settings.PG_USER,
        password=_settings.PG_PASSWORD,
    )
    cur = conn.cursor()
    # 세션 내에서만 존재하며 public 테이블을 가린다. 실데이터 미접촉.
    cur.execute("CREATE TEMP TABLE real_trading_records (LIKE public.real_trading_records)")
    # macd_cross 매수 (라벨 정확)
    cur.execute(
        """INSERT INTO real_trading_records
           (id, stock_code, stock_name, action, quantity, price, timestamp, strategy)
           VALUES (1,'028260','MC_028260','BUY',2,465000,'2026-06-01 14:31:23+09','macd_cross')"""
    )
    # 매도: 복구 경로로 라벨이 덮임 + 매수와 buy_record_id 로 연결, 손실
    cur.execute(
        """INSERT INTO real_trading_records
           (id, stock_code, stock_name, action, quantity, price, timestamp, strategy,
            buy_record_id, net_profit)
           VALUES (2,'028260','삼성물산','SELL',2,440000,'2026-06-04 09:01:24+09',
                   %s, 1, -100000)""",
        ("보유종목 자동복구 (2주 @465,000)",),
    )
    yield conn
    conn.close()  # TEMP TABLE 자동 소멸


def test_old_query_misses_relabeled_sell(seeded_conn):
    """회귀 문서화: 기존 SQL 은 라벨이 덮인 macd_cross 매도를 0건으로 놓친다."""
    cur = seeded_conn.cursor()
    cur.execute(_OLD_BUGGY_SQL)
    rows = cur.fetchall()
    assert rows == [], "기존 SQL 은 라벨 덮인 매도를 놓쳐야 한다(버그 재현)"


def test_fixed_query_counts_relabeled_sell(seeded_conn):
    """수정 SQL 은 매수 레코드로 식별해 라벨이 덮인 macd_cross 매도를 집계한다."""
    cur = seeded_conn.cursor()
    cur.execute(_MACD_CROSS_KILL_SWITCH_SELL_SQL)
    rows = cur.fetchall()
    assert len(rows) == 1, f"라벨이 덮여도 매수 기준으로 1건 집계되어야 함 (got {len(rows)})"
    assert float(rows[0][1]) == -100000.0


def test_fixed_query_counts_correctly_labeled_sell(seeded_conn):
    """매도 라벨이 정상 'macd_cross' 인 경우(buy_record_id 없어도)도 집계."""
    cur = seeded_conn.cursor()
    cur.execute(
        """INSERT INTO real_trading_records
           (id, stock_code, stock_name, action, quantity, price, timestamp, strategy, net_profit)
           VALUES (3,'005930','삼성전자','SELL',1,70000,'2026-06-04 15:00:00+09','macd_cross',5000)"""
    )
    cur.execute(_MACD_CROSS_KILL_SWITCH_SELL_SQL)
    rows = cur.fetchall()
    assert len(rows) == 2, f"덮인 매도 + 정상라벨 매도 = 2건 (got {len(rows)})"


def test_fixed_query_excludes_non_macd(seeded_conn):
    """다른 전략 매도는 집계에서 제외."""
    cur = seeded_conn.cursor()
    cur.execute(
        """INSERT INTO real_trading_records
           (id, stock_code, stock_name, action, quantity, price, timestamp, strategy, net_profit)
           VALUES (4,'000660','SK하이닉스','SELL',1,150000,'2026-06-04 15:00:00+09','price_position',-3000)"""
    )
    cur.execute(_MACD_CROSS_KILL_SWITCH_SELL_SQL)
    rows = cur.fetchall()
    assert len(rows) == 1, f"non-macd 매도는 제외되어야 함 (got {len(rows)})"
