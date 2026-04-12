"""
분봉 확대 수집 CLI (수동 실행용)

사용:
    python scripts/collect_expanded_minutes.py
    python scripts/collect_expanded_minutes.py --date 20260412 --top 300
    python scripts/collect_expanded_minutes.py --no-skip-existing  # 기존 데이터 덮어쓰기
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
from datetime import datetime

from api.kis_auth import auth as kis_auth
from core.expanded_minute_collector import ExpandedMinuteCollector


def main():
    parser = argparse.ArgumentParser(description='분봉 확대 수집 CLI')
    parser.add_argument('--date', default=None,
                        help='대상 거래일 (YYYYMMDD, 기본: 오늘)')
    parser.add_argument('--top', type=int, default=300,
                        help='수집 상위 종목 수 (기본 300)')
    parser.add_argument('--no-skip-existing', action='store_true',
                        help='이미 저장된 종목도 재수집')
    args = parser.parse_args()

    # 로거 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    )
    logger = logging.getLogger('expanded_minute_cli')

    target_date = args.date or datetime.now().strftime('%Y%m%d')

    logger.info(f'KIS API 인증 중...')
    kis_auth()

    collector = ExpandedMinuteCollector(logger=logger)
    stats = collector.run(
        target_date=target_date,
        top_n=args.top,
        skip_existing=not args.no_skip_existing,
    )

    logger.info(f'\n=== 최종 결과 ===')
    logger.info(f'대상: {stats["target_count"]}종목')
    logger.info(f'성공: {stats["collected"]}')
    logger.info(f'실패: {stats["failed"]}')
    logger.info(f'스킵: {stats["skipped"]}')
    logger.info(f'소요: {stats["elapsed_sec"]:.0f}초')
    if stats['failed_codes']:
        logger.info(f'실패 종목(상위 20): {stats["failed_codes"][:20]}')


if __name__ == '__main__':
    main()
