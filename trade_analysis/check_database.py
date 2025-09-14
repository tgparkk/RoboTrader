#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
데이터베이스 테이블 확인 스크립트
"""

import sqlite3
import os

def check_database_tables():
    """데이터베이스 테이블 확인"""
    db_path = "robottrader.db"
    
    if not os.path.exists(db_path):
        print(f"❌ 데이터베이스 파일이 없습니다: {db_path}")
        return
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 모든 테이블 조회
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            print(f"📊 데이터베이스 테이블 목록 ({db_path}):")
            for table in tables:
                table_name = table[0]
                print(f"   - {table_name}")
                
                # 테이블 구조 확인
                cursor.execute(f"PRAGMA table_info({table_name});")
                columns = cursor.fetchall()
                print(f"     컬럼: {[col[1] for col in columns]}")
                
                # 데이터 개수 확인
                cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
                count = cursor.fetchone()[0]
                print(f"     데이터 개수: {count}")
                print()
    
    except Exception as e:
        print(f"❌ 데이터베이스 확인 실패: {e}")

if __name__ == "__main__":
    check_database_tables()
