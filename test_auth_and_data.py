"""
API 인증 테스트 및 실제 데이터 수집 테스트
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_api_manager import KISAPIManager
from api.kis_chart_api import get_full_trading_day_data_async
from utils.logger import setup_logger

logger = setup_logger(__name__)


async def test_auth_and_data():
    """API 인증 및 데이터 수집 테스트"""
    try:
        logger.info("=== API 인증 및 데이터 수집 테스트 시작 ===")
        
        # 1. API 매니저 초기화 및 인증
        logger.info("1. API 매니저 초기화 시작...")
        api_manager = KISAPIManager()
        
        if not api_manager.initialize():
            logger.error("API 초기화 실패")
            return False
        
        logger.info("API 초기화 성공")
        
        # 2. 실제 데이터 수집 테스트
        logger.info("2. 실제 데이터 수집 테스트 시작...")
        
        stock_code = "103840"  # 우양
        target_date = "20250801"  # 2025년 8월 1일 (금요일)
        
        logger.info(f"종목: {stock_code}, 날짜: {target_date}")
        
        # 전체 거래시간 데이터 수집
        data = await get_full_trading_day_data_async(
            stock_code=stock_code,
            target_date=target_date,
            selected_time="153000"  # 15:30까지
        )
        
        if data is None:
            logger.error("데이터 수집 실패 - None 반환")
            return False
        
        if data.empty:
            logger.error("데이터 수집 실패 - 빈 DataFrame")
            return False
        
        # 3. 데이터 확인
        logger.info("3. 수집된 데이터 확인...")
        logger.info(f"총 데이터 수: {len(data)}건")
        logger.info(f"컬럼: {list(data.columns)}")
        
        if len(data) > 0:
            logger.info(f"첫 번째 데이터: {data.iloc[0].to_dict()}")
            logger.info(f"마지막 데이터: {data.iloc[-1].to_dict()}")
            
            # 시간 범위 확인
            if 'time' in data.columns:
                start_time = data['time'].iloc[0]
                end_time = data['time'].iloc[-1]
                logger.info(f"시간 범위: {start_time} ~ {end_time}")
        
        # 4. 09:00~15:30 범위 필터링
        if 'time' in data.columns:
            data['time_str'] = data['time'].astype(str).str.zfill(6)
            filtered_data = data[
                (data['time_str'] >= "090000") & 
                (data['time_str'] <= "153000")
            ].copy()
            
            logger.info(f"필터링 후 데이터 수: {len(filtered_data)}건")
            
            if len(filtered_data) > 0:
                start_time = filtered_data['time'].iloc[0]
                end_time = filtered_data['time'].iloc[-1]
                logger.info(f"필터링 후 시간 범위: {start_time} ~ {end_time}")
                
                # 가격 정보 확인
                if 'close' in filtered_data.columns:
                    start_price = filtered_data['close'].iloc[0]
                    end_price = filtered_data['close'].iloc[-1]
                    high_price = filtered_data['high'].max()
                    low_price = filtered_data['low'].min()
                    
                    logger.info(f"가격 정보:")
                    logger.info(f"  시작가: {start_price:,.0f}원")
                    logger.info(f"  종료가: {end_price:,.0f}원")
                    logger.info(f"  최고가: {high_price:,.0f}원")
                    logger.info(f"  최저가: {low_price:,.0f}원")
                    logger.info(f"  변동률: {((end_price - start_price) / start_price * 100):+.2f}%")
        
        logger.info("=== 테스트 완료 ===")
        return True
        
    except Exception as e:
        logger.error(f"테스트 중 오류 발생: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(test_auth_and_data())