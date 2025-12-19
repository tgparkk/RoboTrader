import sqlite3

conn = sqlite3.connect(r'C:\GIT\RoboTrader\data\robotrader.db')
cursor = conn.cursor()

# 총 후보 종목 수
cursor.execute("SELECT COUNT(*) FROM candidate_stocks")
print('Total candidate stocks:', cursor.fetchone()[0])

# 날짜 범위
cursor.execute("SELECT MIN(selection_date), MAX(selection_date) FROM candidate_stocks")
print('Date range:', cursor.fetchone())

# 최근 10일 데이터
cursor.execute("SELECT selection_date, COUNT(*) FROM candidate_stocks GROUP BY selection_date ORDER BY selection_date DESC LIMIT 10")
print('Recent dates:')
for row in cursor.fetchall():
    print(row)

# 샘플 데이터
cursor.execute("SELECT * FROM candidate_stocks ORDER BY selection_date DESC LIMIT 5")
print('\nSample data:')
for row in cursor.fetchall():
    print(row)

conn.close()