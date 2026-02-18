"""PostgreSQL robotrader DB 생성 스크립트"""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

conn = psycopg2.connect(host='127.0.0.1', port=5433, user='postgres', password='', dbname='postgres')
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname='robotrader'")
if not cur.fetchone():
    cur.execute('CREATE DATABASE robotrader')
    print('Created database robotrader')
else:
    print('Database robotrader already exists')
conn.close()
print('done')
