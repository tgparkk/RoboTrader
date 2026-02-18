import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
pg = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD)
cur = pg.cursor()
# Check constraints
cur.execute("""SELECT conname, conrelid::regclass, pg_get_constraintdef(oid) 
FROM pg_constraint WHERE conrelid = 'real_trading_records'::regclass""")
for row in cur.fetchall():
    print(row)
# Drop FK if exists
try:
    cur.execute("ALTER TABLE real_trading_records DROP CONSTRAINT IF EXISTS real_trading_records_buy_record_id_fkey")
    pg.commit()
    print("FK dropped")
except Exception as e:
    pg.rollback()
    print(f"No FK to drop: {e}")
pg.close()
