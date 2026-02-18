"""구문 검증 스크립트"""
import py_compile
import sys

files = [
    'config/settings.py',
    'db/database_manager.py',
    'utils/data_cache.py',
    'core/post_market_data_saver.py',
    'main.py',
    'scripts/migrate_duckdb_to_pg.py',
    'scripts/create_pg_db.py',
]

all_ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"  OK: {f}")
    except py_compile.PyCompileError as e:
        print(f"  FAIL: {f} - {e}")
        all_ok = False

if all_ok:
    print("\nAll files passed syntax check!")
else:
    print("\nSome files failed!")
    sys.exit(1)
