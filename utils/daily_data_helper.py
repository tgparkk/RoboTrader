"""
일봉 데이터 자동 수집 헬퍼
실시간 거래 시 일봉 필터를 위한 데이터 확보
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def ensure_daily_data_for_stock(stock_code: str, api_manager=None) -> bool:
    """
    종목 선정 시 일봉 데이터 확보

    Args:
        stock_code: 종목 코드
        api_manager: API 관리자 (없으면 직접 import)

    Returns:
        bool: 데이터 확보 성공 여부
    """
    try:
        from utils.data_cache import DailyDataCache
        from api.kis_market_api import get_inquire_daily_itemchartprice

        daily_cache = DailyDataCache()

        # 기존 데이터 확인
        existing = daily_cache.load_data(stock_code)
        today = datetime.now().strftime('%Y%m%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

        # 최신 데이터가 있으면 스킵
        if existing is not None and not existing.empty:
            latest = existing['stck_bsop_date'].max()
            # 전일 또는 당일 데이터까지 있으면 충분
            # (주말/공휴일 고려하여 2일 전까지 허용)
            cutoff = (datetime.now() - timedelta(days=2)).strftime('%Y%m%d')
            if latest >= cutoff:
                logger.debug(f"일봉 데이터 최신: {stock_code} (최근: {latest})")
                return True

        # 없으면 수집 (최근 30일, 여유있게)
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')

        logger.info(f"일봉 데이터 수집 시작: {stock_code} ({start_date} ~ {today})")

        df = get_inquire_daily_itemchartprice(
            output_dv="2",  # output2 (상세)
            itm_no=stock_code,
            inqr_strt_dt=start_date,
            inqr_end_dt=today
        )

        if df is not None and not df.empty:
            # 장중에는 저장하지 않음 (동시 접근 충돌 방지)
            # 장 마감 후 post_market_data_saver에서 일괄 저장
            from datetime import time as dt_time
            now_time = datetime.now().time()
            market_open = dt_time(9, 0)
            market_close = dt_time(15, 30)

            if now_time < market_open or now_time > market_close:
                # 장 시간 외에만 저장
                daily_cache.save_data(stock_code, df)
                logger.info(f"✅ 일봉 데이터 수집 및 저장 완료: {stock_code} ({len(df)}일)")
            else:
                # 장중에는 메모리 캐시만 사용 (저장 생략)
                logger.info(f"✅ 일봉 데이터 수집 완료 (장중 저장 생략): {stock_code} ({len(df)}일)")
            return True
        else:
            logger.warning(f"⚠️ 일봉 데이터 없음: {stock_code}")
            return False

    except Exception as e:
        logger.error(f"❌ 일봉 데이터 수집 실패: {stock_code} - {e}")
        return False


async def ensure_daily_data_async(stock_code: str, api_manager=None, sleep_interval: float = 0.05) -> bool:
    """
    비동기 버전: 종목 선정 시 일봉 데이터 확보

    Args:
        stock_code: 종목 코드
        api_manager: API 관리자
        sleep_interval: API 호출 후 대기 시간 (초)

    Returns:
        bool: 데이터 확보 성공 여부
    """
    import asyncio

    # 동기 함수 실행
    result = ensure_daily_data_for_stock(stock_code, api_manager)

    # API 제한 준수
    if sleep_interval > 0:
        await asyncio.sleep(sleep_interval)

    return result


def ensure_daily_data_for_candidates(stock_codes: list, api_manager=None, max_parallel: int = 1) -> dict:
    """
    여러 종목에 대해 일봉 데이터 일괄 수집

    Args:
        stock_codes: 종목 코드 리스트
        api_manager: API 관리자
        max_parallel: 최대 병렬 처리 수 (현재 1만 지원)

    Returns:
        dict: {stock_code: success (bool)}
    """
    results = {}

    for stock_code in stock_codes:
        success = ensure_daily_data_for_stock(stock_code, api_manager)
        results[stock_code] = success

        # API 제한 준수 (초당 20회)
        import time
        time.sleep(0.05)

    # 요약
    success_count = sum(1 for v in results.values() if v)
    logger.info(f"일봉 데이터 일괄 수집 완료: {success_count}/{len(stock_codes)}건 성공")

    return results


async def ensure_daily_data_for_candidates_async(stock_codes: list, api_manager=None) -> dict:
    """
    비동기 버전: 여러 종목에 대해 일봉 데이터 일괄 수집

    Args:
        stock_codes: 종목 코드 리스트
        api_manager: API 관리자

    Returns:
        dict: {stock_code: success (bool)}
    """
    results = {}

    for stock_code in stock_codes:
        success = await ensure_daily_data_async(stock_code, api_manager, sleep_interval=0.05)
        results[stock_code] = success

    # 요약
    success_count = sum(1 for v in results.values() if v)
    logger.info(f"일봉 데이터 일괄 수집 완료: {success_count}/{len(stock_codes)}건 성공")

    return results


def check_daily_data_coverage(stock_codes: list) -> dict:
    """
    일봉 데이터 커버리지 확인 (진단용)

    Args:
        stock_codes: 종목 코드 리스트

    Returns:
        dict: {
            'total': 총 종목 수,
            'with_data': 데이터 있는 종목 수,
            'without_data': 데이터 없는 종목 수,
            'outdated': 데이터 오래된 종목 수,
            'missing_stocks': 데이터 없는 종목 리스트,
            'outdated_stocks': 데이터 오래된 종목 리스트
        }
    """
    from utils.data_cache import DailyDataCache

    daily_cache = DailyDataCache()
    cutoff = (datetime.now() - timedelta(days=2)).strftime('%Y%m%d')

    with_data = []
    without_data = []
    outdated = []

    for stock_code in stock_codes:
        df = daily_cache.load_data(stock_code)

        if df is None or df.empty:
            without_data.append(stock_code)
        else:
            latest = df['stck_bsop_date'].max()
            if latest < cutoff:
                outdated.append((stock_code, latest))
            else:
                with_data.append((stock_code, latest))

    logger.info(f"일봉 데이터 커버리지: {len(with_data)}/{len(stock_codes)} 최신")

    if without_data:
        logger.warning(f"데이터 없음: {len(without_data)}건 - {without_data[:5]}...")

    if outdated:
        logger.warning(f"데이터 오래됨: {len(outdated)}건")

    return {
        'total': len(stock_codes),
        'with_data': len(with_data),
        'without_data': len(without_data),
        'outdated': len(outdated),
        'missing_stocks': without_data,
        'outdated_stocks': [s[0] for s in outdated],
    }
