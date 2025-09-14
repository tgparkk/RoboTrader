#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
머신러닝 학습 실행 스크립트
사용법:
    python run_ml_training.py --start-date 20250901 --end-date 20250915
    python run_ml_training.py --days 14  # 최근 N일
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml_training_script import MLTrainingPipeline
from utils.logger import setup_logger

logger = setup_logger(__name__)

def main():
    parser = argparse.ArgumentParser(description='머신러닝 학습 실행')
    parser.add_argument('--start-date', type=str, help='시작 날짜 (YYYYMMDD)')
    parser.add_argument('--end-date', type=str, help='종료 날짜 (YYYYMMDD)')
    parser.add_argument('--days', type=int, help='최근 N일간 데이터 사용')
    parser.add_argument('--model-name', type=str, default='default', help='모델 이름')
    
    args = parser.parse_args()
    
    # 날짜 설정
    if args.days:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y%m%d")
    elif args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        # 기본값: 최근 14일
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
    
    logger.info(f"ML 학습 시작")
    logger.info(f"   기간: {start_date} ~ {end_date}")
    logger.info(f"   모델명: {args.model_name}")
    
    try:
        # 학습 파이프라인 실행
        pipeline = MLTrainingPipeline()
        pipeline.run_full_pipeline(start_date, end_date)
        
        logger.info("ML 학습 완료!")
        
    except Exception as e:
        logger.error(f"ML 학습 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
