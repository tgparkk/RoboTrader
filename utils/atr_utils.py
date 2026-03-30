"""
ATR(Average True Range) 유틸리티

종목별 ATR 기반 동적 TP/SL을 위한 일봉 수집 및 신선도 관리.
- 프리로드 시: 전일 거래대금 상위 종목 일봉 사전 수집
- 스크리너 발견 시: 신규 후보 종목 일봉 수집
- 매수 체결 시: get_stock_atr()로 ATR 계산 (data_cache.py)
"""

import logging
from datetime import datetime
from typing import List

from utils.data_cache import _get_pg_pool

logger = logging.getLogger(__name__)

STALE_DAYS_THRESHOLD = 7  # 달력일 기준 (영업일 ~5일)


def collect_daily_candles_for_atr(stock_codes: List[str], api_manager=None):
    """
    ATR 계산용 일봉 데이터 사전 수집 (동기 함수).

    신선도 체크 후 오래된 종목만 API로 수집.
    run_in_executor()로 비동기 호출 가능.

    Args:
        stock_codes: 수집 대상 종목 코드 리스트
        api_manager: (미사용, 호환성 유지)
    """
    from core.post_market_data_saver import PostMarketDataSaver
    from utils.korean_time import now_kst

    if not stock_codes:
        return

    today = now_kst().strftime('%Y%m%d')

    # 신선도 체크: 최근 데이터가 오래된 종목만 필터
    stale_codes = _find_stale_stocks(stock_codes, today)

    if not stale_codes:
        logger.info(f"[ATR 일봉] {len(stock_codes)}개 종목 모두 최신 — 수집 불필요")
        return

    logger.info(f"[ATR 일봉] {len(stale_codes)}개 종목 일봉 수집 시작 (총 {len(stock_codes)}개 중)")

    saver = PostMarketDataSaver()
    result = saver.save_daily_data(stale_codes, target_date=today, days_back=30, force=True)
    logger.info(f"[ATR 일봉] 수집 완료: {result}")


def _find_stale_stocks(stock_codes: List[str], today: str) -> List[str]:
    """daily_candles에서 데이터가 오래되었거나 없는 종목 필터링"""
    pool = _get_pg_pool()
    conn = pool.getconn()
    today_dt = datetime.strptime(today, '%Y%m%d')
    try:
        cur = conn.cursor()
        stale_codes = []
        for code in stock_codes:
            cur.execute('''
                SELECT MAX(stck_bsop_date) FROM daily_candles
                WHERE stock_code = %s
            ''', [code])
            row = cur.fetchone()
            if row and row[0]:
                last_dt = datetime.strptime(row[0], '%Y%m%d')
                days_gap = (today_dt - last_dt).days
                if days_gap > STALE_DAYS_THRESHOLD:
                    stale_codes.append(code)
            else:
                stale_codes.append(code)
        cur.close()
        return stale_codes
    except Exception as e:
        logger.warning(f"[ATR 일봉] 신선도 체크 실패: {e}")
        return stock_codes  # 실패 시 전체 수집 시도
    finally:
        pool.putconn(conn)
