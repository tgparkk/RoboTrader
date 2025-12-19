#!/usr/bin/env python3
"""
실시간 수집 데이터 vs 시뮬레이션 데이터 비교
cache/minute_data에 저장된 두 데이터를 비교하여 일치 여부 확인
"""
import sys
import os
from pathlib import Path

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pickle
import pandas as pd
from datetime import datetime
from utils.logger import setup_logger

logger = setup_logger(__name__)


def load_pickle_data(file_path: Path) -> pd.DataFrame:
    """pickle 파일 로드"""
    try:
        with open(file_path, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.error(f"파일 로드 실패 {file_path}: {e}")
        return None


def compare_dataframes(df1: pd.DataFrame, df2: pd.DataFrame, label1: str, label2: str) -> dict:
    """두 DataFrame 비교"""
    result = {
        'identical': False,
        'row_count_match': False,
        'column_match': False,
        'data_match': False,
        'differences': []
    }
    
    if df1 is None or df2 is None:
        result['differences'].append("한쪽 또는 양쪽 데이터 없음")
        return result
    
    # 1. 행 개수 비교
    if len(df1) == len(df2):
        result['row_count_match'] = True
    else:
        result['differences'].append(f"행 개수 불일치: {label1}={len(df1)}, {label2}={len(df2)}")
    
    # 2. 컬럼 비교
    cols1 = set(df1.columns)
    cols2 = set(df2.columns)
    
    if cols1 == cols2:
        result['column_match'] = True
    else:
        only_in_1 = cols1 - cols2
        only_in_2 = cols2 - cols1
        if only_in_1:
            result['differences'].append(f"{label1}에만 있는 컬럼: {only_in_1}")
        if only_in_2:
            result['differences'].append(f"{label2}에만 있는 컬럼: {only_in_2}")
    
    # 3. 공통 컬럼으로 데이터 비교
    common_cols = list(cols1 & cols2)
    if common_cols and len(df1) == len(df2):
        try:
            # 시간순 정렬
            if 'time' in common_cols:
                df1_sorted = df1.sort_values('time').reset_index(drop=True)
                df2_sorted = df2.sort_values('time').reset_index(drop=True)
            elif 'datetime' in common_cols:
                df1_sorted = df1.sort_values('datetime').reset_index(drop=True)
                df2_sorted = df2.sort_values('datetime').reset_index(drop=True)
            else:
                df1_sorted = df1.reset_index(drop=True)
                df2_sorted = df2.reset_index(drop=True)
            
            # 주요 컬럼 비교
            key_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
            compare_cols = [col for col in key_cols if col in common_cols]
            
            if compare_cols:
                mismatch_count = 0
                for col in compare_cols:
                    if not df1_sorted[col].equals(df2_sorted[col]):
                        # 숫자형 컬럼은 근사 비교
                        if col in ['open', 'high', 'low', 'close', 'volume']:
                            if not pd.api.types.is_numeric_dtype(df1_sorted[col]):
                                df1_sorted[col] = pd.to_numeric(df1_sorted[col], errors='coerce')
                            if not pd.api.types.is_numeric_dtype(df2_sorted[col]):
                                df2_sorted[col] = pd.to_numeric(df2_sorted[col], errors='coerce')
                            
                            # 차이 계산
                            diff = (df1_sorted[col] - df2_sorted[col]).abs()
                            max_diff = diff.max()
                            if max_diff > 0:
                                mismatch_count += 1
                                result['differences'].append(f"{col} 컬럼 불일치 (최대 차이: {max_diff})")
                        else:
                            mismatch_count += 1
                            result['differences'].append(f"{col} 컬럼 불일치")
                
                if mismatch_count == 0:
                    result['data_match'] = True
        
        except Exception as e:
            result['differences'].append(f"데이터 비교 중 오류: {e}")
    
    # 완전 일치 판정
    result['identical'] = (result['row_count_match'] and 
                          result['column_match'] and 
                          result['data_match'])
    
    return result


def compare_stock_data(stock_code: str, date_str: str, realtime_dir: Path, simulation_dir: Path = None):
    """특정 종목의 실시간 데이터와 시뮬레이션 데이터 비교"""
    
    if simulation_dir is None:
        simulation_dir = realtime_dir  # 같은 디렉토리에서 비교
    
    # 파일 경로
    realtime_file = realtime_dir / f"{stock_code}_{date_str}.pkl"
    simulation_file = simulation_dir / f"{stock_code}_{date_str}.pkl"
    
    # 파일 존재 확인
    if not realtime_file.exists():
        logger.warning(f"실시간 파일 없음: {realtime_file}")
        return None
    
    if not simulation_file.exists():
        logger.warning(f"시뮬 파일 없음: {simulation_file}")
        return None
    
    # 데이터 로드
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 종목: {stock_code} ({date_str})")
    logger.info(f"{'='*80}")
    
    df_realtime = load_pickle_data(realtime_file)
    df_simulation = load_pickle_data(simulation_file)
    
    if df_realtime is None or df_simulation is None:
        logger.error(f"❌ 데이터 로드 실패")
        return None
    
    logger.info(f"실시간 데이터: {len(df_realtime)}행, 컬럼: {list(df_realtime.columns)}")
    logger.info(f"시뮬 데이터: {len(df_simulation)}행, 컬럼: {list(df_simulation.columns)}")
    
    # 비교
    result = compare_dataframes(df_realtime, df_simulation, "실시간", "시뮬")
    
    if result['identical']:
        logger.info(f"✅ 완전 일치!")
    else:
        logger.warning(f"⚠️ 불일치 발견:")
        for diff in result['differences']:
            logger.warning(f"   - {diff}")
    
    return result


def compare_all_stocks(date_str: str = None):
    """모든 종목 비교"""
    try:
        if date_str is None:
            from utils.korean_time import now_kst
            date_str = now_kst().strftime('%Y%m%d')
        
        cache_dir = Path("cache/minute_data")
        
        if not cache_dir.exists():
            logger.error(f"캐시 디렉토리 없음: {cache_dir}")
            return
        
        # 해당 날짜의 모든 파일 찾기
        pattern = f"*_{date_str}.pkl"
        files = list(cache_dir.glob(pattern))
        
        if not files:
            logger.warning(f"해당 날짜({date_str}) 파일 없음")
            return
        
        logger.info(f"🔍 총 {len(files)}개 종목 데이터 발견")
        logger.info(f"📅 날짜: {date_str}")
        
        # 종목 코드 추출
        stock_codes = set()
        for file in files:
            stock_code = file.stem.split('_')[0]
            stock_codes.add(stock_code)
        
        logger.info(f"📊 종목 코드: {sorted(stock_codes)}")
        
        # 각 종목별 비교 (동일 파일 2번 로드하여 일치 확인)
        identical_count = 0
        mismatch_count = 0
        
        for stock_code in sorted(stock_codes):
            result = compare_stock_data(stock_code, date_str, cache_dir, cache_dir)
            if result and result['identical']:
                identical_count += 1
            elif result:
                mismatch_count += 1
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 비교 결과 요약")
        logger.info(f"{'='*80}")
        logger.info(f"✅ 일치: {identical_count}개")
        logger.info(f"⚠️ 불일치: {mismatch_count}개")
        logger.info(f"📁 전체: {len(stock_codes)}개")
        
    except Exception as e:
        logger.error(f"❌ 비교 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="실시간 vs 시뮬레이션 데이터 비교")
    parser.add_argument('--date', type=str, help='날짜 (YYYYMMDD), 미지정 시 오늘')
    parser.add_argument('--stock', type=str, help='특정 종목만 비교 (종목코드)')
    
    args = parser.parse_args()
    
    if args.stock:
        # 특정 종목만 비교
        cache_dir = Path("cache/minute_data")
        date_str = args.date
        if date_str is None:
            from utils.korean_time import now_kst
            date_str = now_kst().strftime('%Y%m%d')
        
        compare_stock_data(args.stock, date_str, cache_dir, cache_dir)
    else:
        # 모든 종목 비교
        compare_all_stocks(args.date)


if __name__ == '__main__':
    main()

