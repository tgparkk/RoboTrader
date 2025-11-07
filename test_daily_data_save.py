"""
일봉 데이터 저장 기능만 단독 테스트
현재 cache/minute_data에 있는 종목들의 일봉 데이터를 저장
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from core.post_market_data_saver import PostMarketDataSaver
from utils.logger import setup_logger

logger = setup_logger(__name__)

def test_daily_data_save():
    """일봉 데이터 저장만 테스트"""
    try:
        print("=" * 80)
        print("TEST: Daily Data Save")
        print("=" * 80)

        # 1. 분봉 캐시 파일에서 종목 코드 추출
        minute_cache_dir = Path("cache/minute_data")
        if not minute_cache_dir.exists():
            print("ERROR: cache/minute_data directory not found")
            return False

        pkl_files = list(minute_cache_dir.glob("*.pkl"))
        if not pkl_files:
            print("ERROR: No minute data pkl files found")
            return False

        # 파일명에서 종목코드 추출 (예: 000230_20251107.pkl -> 000230)
        stock_codes = []
        for f in pkl_files:
            parts = f.stem.split('_')
            if len(parts) >= 2:
                stock_code = parts[0]
                if len(stock_code) == 6 and stock_code.isdigit():
                    stock_codes.append(stock_code)

        stock_codes = list(set(stock_codes))  # 중복 제거

        print(f"\nFound {len(stock_codes)} stocks from minute data cache:")
        print(f"  Stock codes: {', '.join(stock_codes[:10])}{'...' if len(stock_codes) > 10 else ''}")
        print()

        # 2. PostMarketDataSaver 생성
        data_saver = PostMarketDataSaver()

        # 3. 일봉 데이터 저장 실행
        print("Saving daily data...")
        print("-" * 80)

        result = data_saver.save_daily_data(stock_codes)

        # 4. 결과 출력
        print("-" * 80)
        print("\nRESULTS:")
        print(f"  Total stocks: {result['total']}")
        print(f"  Saved: {result['saved']}")
        print(f"  Failed: {result['failed']}")

        # 5. 저장된 파일 확인
        daily_cache_dir = Path("cache/daily")
        if daily_cache_dir.exists():
            daily_files = list(daily_cache_dir.glob("*_daily.pkl"))
            print(f"\nDaily pkl files in cache/daily: {len(daily_files)}")

            # 오늘 날짜 파일만 표시
            from utils.korean_time import now_kst
            today = now_kst().strftime('%Y%m%d')

            today_files = [f for f in daily_files if today in f.name]
            if today_files:
                print(f"\nToday's files ({today}):")
                for f in sorted(today_files)[:10]:  # 최대 10개
                    size_kb = f.stat().st_size / 1024
                    print(f"  - {f.name} ({size_kb:.1f} KB)")
                if len(today_files) > 10:
                    print(f"  ... and {len(today_files) - 10} more files")

        success = result['saved'] > 0
        print()
        if success:
            print("SUCCESS: Daily data saved!")
        else:
            print("FAILED: No daily data was saved")

        return success

    except Exception as e:
        logger.error(f"Test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import io
    import sys

    # UTF-8 출력 설정
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    success = test_daily_data_save()

    print()
    print("=" * 80)
    if success:
        print("Check cache/daily/ folder for *_daily.pkl files")
    print("=" * 80)
