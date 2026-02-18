"""
SQLite → DuckDB 마이그레이션 스크립트
DuckDB의 sqlite_scanner 확장을 사용하여 빠르게 마이그레이션
"""
import duckdb
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


def migrate():
    project_root = Path(__file__).parent.parent
    sqlite_path = project_root / "data" / "robotrader.db"
    duckdb_path = project_root / "db" / "robotrader_trades.duckdb"

    if not sqlite_path.exists():
        print(f"[SKIP] SQLite DB not found: {sqlite_path}")
        return

    if duckdb_path.exists():
        duckdb_path.unlink()
        print(f"[INFO] Removed existing DuckDB file")

    print(f"[INFO] Migrating {sqlite_path} -> {duckdb_path}")

    dst = duckdb.connect(str(duckdb_path))

    # Install and load sqlite scanner
    dst.execute("INSTALL sqlite_scanner")
    dst.execute("LOAD sqlite_scanner")

    # Attach SQLite DB
    dst.execute(f"ATTACH '{sqlite_path}' AS src (TYPE sqlite)")

    tables = [
        'candidate_stocks',
        'stock_prices',
        'trading_records',
        'virtual_trading_records',
        'real_trading_records',
    ]

    for table in tables:
        try:
            # Check if source table exists
            count = dst.execute(f"SELECT COUNT(*) FROM src.{table}").fetchone()[0]
            # CREATE TABLE AS SELECT (fast bulk copy)
            dst.execute(f"CREATE TABLE {table} AS SELECT * FROM src.{table}")
            print(f"  {table}: {count} rows migrated")
        except Exception as e:
            print(f"  [ERROR] {table}: {e}")
            # Create empty table if source doesn't exist
            try:
                dst.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER)")
            except:
                pass

    # Create sequences starting after max IDs
    seq_map = {
        'candidate_stocks': 'seq_candidate_stocks',
        'stock_prices': 'seq_stock_prices',
        'trading_records': 'seq_trading_records',
        'virtual_trading_records': 'seq_virtual_trading',
        'real_trading_records': 'seq_real_trading',
    }

    for table, seq_name in seq_map.items():
        try:
            max_id = dst.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
            dst.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START {max_id + 1}")
            print(f"  Sequence {seq_name}: start at {max_id + 1}")
        except Exception as e:
            print(f"  [WARN] Sequence {seq_name}: {e}")

    # Create indexes
    indexes = [
        'CREATE INDEX IF NOT EXISTS idx_candidate_date ON candidate_stocks(selection_date)',
        'CREATE INDEX IF NOT EXISTS idx_candidate_code ON candidate_stocks(stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_price_code_date ON stock_prices(stock_code, date_time)',
        'CREATE INDEX IF NOT EXISTS idx_trading_code_date ON trading_records(stock_code, timestamp)',
        'CREATE INDEX IF NOT EXISTS idx_virtual_trading_code_date ON virtual_trading_records(stock_code, timestamp)',
        'CREATE INDEX IF NOT EXISTS idx_virtual_trading_action ON virtual_trading_records(action)',
        'CREATE INDEX IF NOT EXISTS idx_real_trading_code_date ON real_trading_records(stock_code, timestamp)',
        'CREATE INDEX IF NOT EXISTS idx_real_trading_action ON real_trading_records(action)',
    ]
    for idx in indexes:
        try:
            dst.execute(idx)
        except Exception:
            pass

    dst.execute("DETACH src")
    dst.close()

    print(f"\n[DONE] Migration complete: {duckdb_path}")
    print(f"  Original SQLite kept at: {sqlite_path}")


if __name__ == '__main__':
    migrate()
