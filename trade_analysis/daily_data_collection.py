#!/usr/bin/env python3
"""
매일 장 마감 후 자동 데이터 수집 스크립트
"""
import os
import sys
import logging
from datetime import datetime, timedelta
from auto_daily_data_collector import AutoDailyDataCollector

def setup_logging():
    """로깅 설정"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler('logs/daily_collection.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def main():
    """메인 실행 함수"""
    logger = setup_logging()
    
    try:
        logger.info("🚀 매일 자동 데이터 수집 시작")
        
        # 오늘 날짜
        today = datetime.now().strftime('%Y%m%d')
        
        # 어제 날짜 (장 마감 후이므로 어제 데이터 수집)
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        
        logger.info(f"📅 수집 대상 날짜: {yesterday}")
        
        # 데이터 수집기 초기화
        collector = AutoDailyDataCollector()
        
        # 인증 확인
        if not collector._ensure_authenticated():
            logger.error("❌ KIS API 인증 실패")
            return False
        
        # 데이터 수집 실행
        success = collector.collect_missing_daily_data(
            start_date="20240601",
            end_date=yesterday
        )
        
        if success:
            logger.info("✅ 데이터 수집 완료")
            return True
        else:
            logger.error("❌ 데이터 수집 실패")
            return False
            
    except Exception as e:
        logger.error(f"❌ 오류 발생: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
