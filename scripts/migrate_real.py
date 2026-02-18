import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import duckdb, psycopg2, psycopg2.extras, pandas as pd
from pathlib import Path
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD

TRADES_DB = Path(__file__).parent.parent / "db" / "robotrader_trades.duckdb"
duck = duckdb.connect(str(TRADES_DB), read_only=True)
pg = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD)
cur = pg.cursor()

# Get old id -> new id mapping for buy records
df = duck.execute("SELECT * FROM real_trading_records ORDER BY id").fetchdf()
if df.empty:
    print("No data"); sys.exit(0)

# Insert all BUY records first, track id mapping
id_map = {}
for _, row in df.iterrows():
    cols = [c for c in df.columns if c != 'id']
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
        if c == 'buy_record_id' and val is not None:
            val = int(val) if val else None
        row_data.append(val)
    
    placeholders = ', '.join(['%s'] * len(cols))
    col_names = ', '.join(cols)
    cur.execute(f"INSERT INTO real_trading_records ({col_names}) VALUES ({placeholders}) RETURNING id", row_data)
    new_id = cur.fetchone()[0]
    id_map[int(row['id'])] = new_id

pg.commit()

# Now update buy_record_id references
for old_id, new_id in id_map.items():
    old_buy_ref = duck.execute(f"SELECT buy_record_id FROM real_trading_records WHERE id = {old_id}").fetchone()
    if old_buy_ref and old_buy_ref[0] is not None:
        old_buy_id = int(old_buy_ref[0])
        if old_buy_id in id_map:
            cur.execute("UPDATE real_trading_records SET buy_record_id = %s WHERE id = %s", 
                       (id_map[old_buy_id], new_id))

pg.commit()
print(f"real_trading_records: {len(df)} rows migrated with id remapping")
duck.close()
pg.close()
