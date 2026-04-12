"""최근 N거래일 분봉 확대 수집 (배치 실행)"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
import time
from datetime import datetime

import psycopg2

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from api.kis_auth import auth as kis_auth
from core.expanded_minute_collector import ExpandedMinuteCollector


def get_recent_trading_dates(days: int) -> list:
    """DB에서 최근 N 거래일 조회"""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute('''
        SELECT DISTINCT trade_date FROM minute_candles
        ORDER BY trade_date DESC LIMIT %s
    ''', [days])
    dates = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return sorted(dates)


def main():
    parser = argparse.ArgumentParser(description='최근 N 거래일 배치 수집')
    parser.add_argument('--days', type=int, default=10, help='최근 N 거래일 (기본 10)')
    parser.add_argument('--top', type=int, default=300, help='일별 상위 종목 수')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
    )
    logger = logging.getLogger('batch_collect')

    logger.info('KIS API 인증 중...')
    kis_auth()
    time.sleep(1)

    dates = get_recent_trading_dates(args.days)
    logger.info(f'대상 거래일: {len(dates)}일 ({dates[0]} ~ {dates[-1]})')

    total_collected = 0
    total_failed = 0
    start_ts = time.time()

    for i, td in enumerate(dates):
        logger.info(f'\n[{i+1}/{len(dates)}] === {td} ===')
        collector = ExpandedMinuteCollector(logger=logger)
        stats = collector.run(target_date=td, top_n=args.top, skip_existing=True)
        total_collected += stats['collected']
        total_failed += stats['failed']

        elapsed = time.time() - start_ts
        if i + 1 < len(dates):
            avg = elapsed / (i + 1)
            remaining = (len(dates) - i - 1) * avg
            logger.info(f'전체 진행 {i+1}/{len(dates)}, 경과 {elapsed/60:.1f}분, '
                        f'ETA {remaining/60:.0f}분')

    total_elapsed = time.time() - start_ts
    logger.info(f'\n=== 배치 완료 ===')
    logger.info(f'거래일: {len(dates)}일')
    logger.info(f'수집: 성공 {total_collected}, 실패 {total_failed}')
    logger.info(f'소요: {total_elapsed/60:.0f}분')


if __name__ == '__main__':
    main()
