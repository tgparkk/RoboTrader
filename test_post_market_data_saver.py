"""
장 마감 후 데이터 저장 기능 테스트 스크립트
15:30 시점을 시뮬레이션하여 일봉/분봉 데이터 저장 테스트
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from core.post_market_data_saver import PostMarketDataSaver
from core.intraday_stock_manager import IntradayStockManager
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

def test_post_market_data_saving():
    """15:30 장 마감 후 데이터 저장 테스트"""
    try:
        logger.info("=" * 80)
        logger.info("🧪 장 마감 후 데이터 저장 테스트 시작")
        logger.info("=" * 80)

        # 1. API 매니저 초기화
        logger.info("📡 API 매니저 초기화...")
        api_manager = KISAPIManager()
        if not api_manager.initialize():
            logger.error("❌ API 초기화 실패")
            return False
        logger.info("✅ API 매니저 초기화 완료")

        # 2. IntradayStockManager 초기화
        logger.info("📊 IntradayStockManager 초기화...")
        intraday_manager = IntradayStockManager(api_manager)
        logger.info("✅ IntradayStockManager 초기화 완료")

        # 3. 현재 관리 중인 종목 확인
        with intraday_manager._lock:
            stock_codes = list(intraday_manager.selected_stocks.keys())

        if not stock_codes:
            logger.warning("⚠️ 관리 중인 종목이 없습니다.")
            logger.info("💡 테스트를 위해 샘플 종목을 추가하시겠습니까?")
            logger.info("   예: await intraday_manager.add_stock('005930', 'Samsung Electronics')")
            return False

        logger.info(f"📋 관리 중인 종목: {len(stock_codes)}개")
        logger.info(f"   종목 코드: {', '.join(stock_codes[:5])}{'...' if len(stock_codes) > 5 else ''}")

        # 4. PostMarketDataSaver 초기화 및 실행
        logger.info("\n" + "=" * 80)
        logger.info("💾 PostMarketDataSaver 테스트 시작")
        logger.info("=" * 80)

        data_saver = PostMarketDataSaver()

        # 5. 모든 데이터 저장 (분봉 + 일봉 + 텍스트)
        result = data_saver.save_all_data(intraday_manager)

        # 6. 결과 출력
        logger.info("\n" + "=" * 80)
        logger.info("📊 테스트 결과")
        logger.info("=" * 80)

        if result['success']:
            logger.info(f"✅ 전체 성공")
            logger.info(f"   - 분봉 데이터: {result['minute_data']['saved']}/{result['minute_data']['total']}개 저장")
            logger.info(f"   - 일봉 데이터: {result['daily_data']['saved']}/{result['daily_data']['total']}개 저장")
            logger.info(f"   - 텍스트 파일: {result['text_file'] if result['text_file'] else '저장 실패'}")

            # 저장된 파일 확인
            logger.info("\n📁 저장된 파일 확인:")

            # 분봉 pkl 파일
            minute_cache_dir = Path("cache/minute_data")
            if minute_cache_dir.exists():
                pkl_files = list(minute_cache_dir.glob("*.pkl"))
                logger.info(f"   분봉 pkl 파일: {len(pkl_files)}개")
                for f in sorted(pkl_files)[-5:]:  # 최근 5개만 표시
                    size_kb = f.stat().st_size / 1024
                    logger.info(f"     - {f.name} ({size_kb:.1f} KB)")

            # 일봉 pkl 파일
            daily_cache_dir = Path("cache/daily")
            if daily_cache_dir.exists():
                daily_files = list(daily_cache_dir.glob("*_daily.pkl"))
                logger.info(f"   일봉 pkl 파일: {len(daily_files)}개")
                for f in sorted(daily_files)[-5:]:  # 최근 5개만 표시
                    size_kb = f.stat().st_size / 1024
                    logger.info(f"     - {f.name} ({size_kb:.1f} KB)")

            return True
        else:
            logger.error(f"❌ 실패: {result.get('error', '알 수 없는 오류')}")
            return False

    except Exception as e:
        logger.error(f"❌ 테스트 중 오류 발생: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    finally:
        # API 매니저 종료
        if 'api_manager' in locals():
            api_manager.shutdown()
        logger.info("\n" + "=" * 80)
        logger.info("🧪 테스트 종료")
        logger.info("=" * 80)


if __name__ == "__main__":
    import io
    import sys

    # UTF-8 출력 설정
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    print("=" * 80)
    print("TEST: Post Market Data Saver")
    print("=" * 80)
    print()
    print("This script tests:")
    print("  1. Save minute data to cache/minute_data/ as pkl")
    print("  2. Save daily data to cache/daily/ as pkl")
    print("  3. Save minute data as text file (for debugging)")
    print()
    print("WARNING: This calls real API. Be aware of API rate limits.")
    print()

    input("Press Enter to continue...")
    print()

    success = test_post_market_data_saving()

    print()
    if success:
        print("SUCCESS: Test passed!")
        print()
        print("Check these folders:")
        print("  - cache/minute_data/  : minute pkl files")
        print("  - cache/daily/        : daily pkl files")
        print("  - root directory      : memory_minute_data_*.txt file")
    else:
        print("FAILED: Check the logs above.")
