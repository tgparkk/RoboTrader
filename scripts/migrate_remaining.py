"""Migrate remaining tables that failed due to NAType"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb
import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
from pathlib import Path
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD

TRADES_DB = Path(__file__).parent.parent / "db" / "robotrader_trades.duckdb"

duck = duckdb.connect(str(TRADES_DB), read_only=True)
pg = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD)
cur = pg.cursor()

for table in ['virtual_trading_records', 'real_trading_records']:
    df = duck.execute(f"SELECT * FROM {table}").fetchdf()
    if df.empty:
        print(f"  [{table}] empty")
        continue
    
    cols = [c for c in df.columns if c != 'id']
    placeholders = ', '.join(['%s'] * len(cols))
    col_names = ', '.join(cols)
    
    rows = []
    for _, row in df.iterrows():
        row_data = []
        for c in cols:
            val = row[c]
            if hasattr(val, 'isoformat'):
                val = val.isoformat()
            else:
                try:
                    if pd.isna(val):
                        val = None
                except (TypeError, ValueError):
                    pass
            # bool conversion for is_test
            if c == 'is_test' and val is not None:
                val = bool(val)
            row_data.append(val)
        rows.append(tuple(row_data))
    
    psycopg2.extras.execute_batch(cur, f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", rows, page_size=500)
    pg.commit()
    print(f"  [{table}] {len(rows)} rows migrated")

duck.close()
pg.close()
print("Done!")
