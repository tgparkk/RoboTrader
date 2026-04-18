"""오버나이트 청산 교차 검증 스크립트 (closing_trade 전용).

매일 09:10 이후 실행하여 전일 미매칭 BUY 집합 (A)과
금일 09:00~09:10 SELL 집합 (B)이 1:1 매칭되는지 확인한다.

사용법:
    python scripts/verify_overnight_exit.py [--date YYYYMMDD]

기본 검사:
    (A) 전일 이전의 미매칭 BUY 종목
    (B) 검사 대상 날짜 09:00~09:10 SELL 종목
    결과:
        매칭됨  - (A) stock_code set == (B) stock_code set
        누락    - (A) - (B) : 청산 실패한 포지션 (수동 조치 필요)
        초과    - (B) - (A) : 당일 09:00 이후 매수됐던 종목 (비정상)
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database_manager import DatabaseManager


def fetch_unmatched_buys_before(db: DatabaseManager, date_str: str) -> List[Tuple]:
    """date_str(YYYYMMDD) 이전의 미매칭 BUY 전체"""
    return db._fetchall('''
        SELECT b.id, b.stock_code, b.stock_name, b.timestamp, b.price, b.quantity, b.strategy
        FROM real_trading_records b
        WHERE b.action = 'BUY'
          AND b.timestamp < TO_DATE(%s, 'YYYYMMDD')
          AND NOT EXISTS (
              SELECT 1 FROM real_trading_records s
              WHERE s.buy_record_id = b.id AND s.action = 'SELL'
          )
        ORDER BY b.timestamp DESC
    ''', (date_str,))


def fetch_overnight_sells(db: DatabaseManager, date_str: str) -> List[Tuple]:
    """date_str 09:00~09:10 SELL 전체"""
    return db._fetchall('''
        SELECT id, stock_code, price, quantity, timestamp, reason,
               net_profit, net_profit_rate, buy_record_id
        FROM real_trading_records
        WHERE action = 'SELL'
          AND timestamp >= TO_DATE(%s, 'YYYYMMDD')
          AND timestamp <  TO_DATE(%s, 'YYYYMMDD') + INTERVAL '1 day'
          AND timestamp::time BETWEEN '09:00:00' AND '09:10:00'
        ORDER BY timestamp
    ''', (date_str, date_str))


def main():
    parser = argparse.ArgumentParser(description='오버나이트 청산 교차 검증')
    parser.add_argument('--date', help='검사 대상 YYYYMMDD (기본=오늘)', default=None)
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime('%Y%m%d')
    print(f'[verify_overnight_exit] 검사 대상 날짜: {date_str}')
    print()

    db = DatabaseManager()

    # (A) 전일 이전의 미매칭 BUY
    buys = fetch_unmatched_buys_before(db, date_str)
    buy_codes = {row[1] for row in buys}
    print(f'(A) {date_str} 이전 미매칭 BUY : {len(buys)}건')
    for r in buys:
        print(f'    id={r[0]} {r[1]}({r[2]}) ts={r[3]} '
              f'price={r[4]} qty={r[5]} strategy={r[6]!r}')
    print()

    # (B) 당일 09:00~09:10 SELL
    sells = fetch_overnight_sells(db, date_str)
    sell_codes = {row[1] for row in sells}
    print(f'(B) {date_str} 09:00~09:10 SELL : {len(sells)}건')
    for r in sells:
        print(f'    id={r[0]} {r[1]} price={r[2]} qty={r[3]} ts={r[4]} reason={r[5]!r} '
              f'buy_id={r[8]} pnl={r[6]} ({r[7]}%)')
    print()

    # 교차 검증
    missing = buy_codes - sell_codes  # 청산 실패
    extra = sell_codes - buy_codes    # 비정상
    matched = buy_codes & sell_codes

    print('=== 교차 검증 결과 ===')
    print(f'매칭됨  : {len(matched)}건 {sorted(matched)}')
    print(f'누락    : {len(missing)}건 {sorted(missing)}  [!] 청산 실패, 수동 조치 필요')
    print(f'초과    : {len(extra)}건 {sorted(extra)}  [!] 당일 매수 직후 매도? 점검 필요')

    # buy_record_id 연결 매칭 (ID 기반 정확 일치 확인)
    linked_buy_ids = {r[8] for r in sells if r[8] is not None}
    all_buy_ids = {r[0] for r in buys}
    id_matched = linked_buy_ids & all_buy_ids
    id_extra = linked_buy_ids - all_buy_ids
    print()
    print(f'buy_record_id 연결: 매칭 {len(id_matched)}건, 오매칭 {len(id_extra)}건')
    if id_extra:
        print(f'  오매칭 buy_id: {sorted(id_extra)} (이미 매칭된 BUY가 재매도됨)')

    # Exit code
    if missing or extra:
        print()
        print('[FAIL] 교차 검증 불일치 - 즉시 조치 필요')
        raise SystemExit(1)
    print()
    print('[PASS] 교차 검증 일치')


if __name__ == '__main__':
    main()
