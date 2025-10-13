#!/usr/bin/env python3
"""
자동 일치성 검증 스크립트

매일 15:40에 실행하여 실시간 데이터와 시뮬레이션 데이터의 일치성을 자동 검증
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


def verify_data_consistency(date_str: str):
    """
    데이터 일치성 검증
    
    Args:
        date_str: 검증할 날짜 (YYYYMMDD)
    """
    cache_dir = Path("cache/minute_data")
    
    if not cache_dir.exists():
        logger.error(f"캐시 디렉토리 없음: {cache_dir}")
        return {'success': False, 'message': '캐시 디렉토리 없음'}
    
    # 해당 날짜의 파일 찾기
    files = list(cache_dir.glob(f"*_{date_str}.pkl"))
    
    if not files:
        logger.warning(f"해당 날짜 파일 없음: {date_str}")
        return {'success': False, 'message': f'파일 없음: {date_str}'}
    
    logger.info(f"✅ 검증 대상: {len(files)}개 파일")
    
    # 각 파일 검증
    results = {
        'date': date_str,
        'total_files': len(files),
        'valid_files': 0,
        'invalid_files': 0,
        'issues': []
    }
    
    for file in files:
        stock_code = file.stem.split('_')[0]
        
        try:
            with open(file, 'rb') as f:
                data = pickle.load(f)
            
            if data is None or data.empty:
                results['invalid_files'] += 1
                results['issues'].append(f"{stock_code}: 빈 데이터")
                continue
            
            # 데이터 품질 검사
            issues = []
            
            # 1. 최소 데이터 개수 (09:00~15:30 = 390개)
            if len(data) < 300:
                issues.append(f"데이터 부족 ({len(data)}/390)")
            
            # 2. datetime 컬럼 존재
            if 'datetime' not in data.columns and 'time' not in data.columns:
                issues.append("시간 컬럼 없음")
            
            # 3. OHLCV 컬럼 존재
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            missing_cols = [col for col in required_cols if col not in data.columns]
            if missing_cols:
                issues.append(f"누락 컬럼: {missing_cols}")
            
            # 4. 09:00 시작 확인
            if 'datetime' in data.columns:
                data['datetime'] = pd.to_datetime(data['datetime'])
                first_time = data['datetime'].iloc[0]
                if first_time.hour != 9 or first_time.minute != 0:
                    issues.append(f"09:00 시작 아님 ({first_time.strftime('%H:%M')})")
            
            # 5. 15:00 이후 데이터 포함
            if 'datetime' in data.columns:
                has_afternoon = any(data['datetime'].dt.hour >= 15)
                if not has_afternoon:
                    issues.append("15:00 이후 데이터 없음")
            
            # 6. 중복 검사
            if 'datetime' in data.columns:
                duplicates = data['datetime'].duplicated().sum()
                if duplicates > 0:
                    issues.append(f"중복 데이터: {duplicates}개")
            
            # 7. 시간 연속성 검사 (샘플)
            if 'datetime' in data.columns and len(data) > 10:
                # 처음 10개 분봉 연속성 확인
                for i in range(1, min(10, len(data))):
                    time_diff = (data['datetime'].iloc[i] - data['datetime'].iloc[i-1]).total_seconds()
                    if time_diff != 60:  # 1분 간격 아님
                        issues.append(f"시간 불연속: {data['datetime'].iloc[i-1].strftime('%H:%M')} → {data['datetime'].iloc[i].strftime('%H:%M')}")
                        break
            
            if issues:
                results['invalid_files'] += 1
                results['issues'].append(f"{stock_code}: {', '.join(issues)}")
                logger.warning(f"⚠️ {stock_code}: {', '.join(issues)}")
            else:
                results['valid_files'] += 1
                logger.debug(f"✅ {stock_code}: 정상 ({len(data)}개)")
        
        except Exception as e:
            results['invalid_files'] += 1
            results['issues'].append(f"{stock_code}: 로드 실패 ({e})")
            logger.error(f"❌ {stock_code}: {e}")
    
    # 결과 요약
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 검증 결과")
    logger.info(f"{'='*80}")
    logger.info(f"날짜: {date_str}")
    logger.info(f"전체 파일: {results['total_files']}개")
    logger.info(f"✅ 정상: {results['valid_files']}개 ({results['valid_files']/results['total_files']*100:.1f}%)")
    logger.info(f"⚠️ 이상: {results['invalid_files']}개 ({results['invalid_files']/results['total_files']*100:.1f}%)")
    
    if results['issues']:
        logger.info(f"\n🔍 발견된 문제점:")
        for issue in results['issues'][:10]:  # 최대 10개만 표시
            logger.info(f"   - {issue}")
        if len(results['issues']) > 10:
            logger.info(f"   ... 외 {len(results['issues']) - 10}건")
    
    results['success'] = results['invalid_files'] == 0
    
    return results


def generate_report(date_str: str, output_file: str = None):
    """검증 리포트 생성"""
    
    if output_file is None:
        output_file = f"verification_report_{date_str}.txt"
    
    results = verify_data_consistency(date_str)
    
    if not results['success']:
        logger.warning(f"⚠️ 검증 실패: {results['message'] if 'message' in results else '데이터 품질 이슈'}")
    
    # 리포트 저장
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"{'='*100}\n")
            f.write(f"실시간 데이터 품질 검증 리포트\n")
            f.write(f"{'='*100}\n\n")
            f.write(f"날짜: {date_str}\n")
            f.write(f"검증 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"\n")
            f.write(f"{'='*100}\n")
            f.write(f"검증 결과\n")
            f.write(f"{'='*100}\n\n")
            f.write(f"전체 파일: {results['total_files']}개\n")
            f.write(f"정상: {results['valid_files']}개 ({results['valid_files']/results['total_files']*100:.1f}%)\n")
            f.write(f"이상: {results['invalid_files']}개 ({results['invalid_files']/results['total_files']*100:.1f}%)\n")
            f.write(f"\n")
            
            if results['issues']:
                f.write(f"{'='*100}\n")
                f.write(f"발견된 문제점\n")
                f.write(f"{'='*100}\n\n")
                for issue in results['issues']:
                    f.write(f"- {issue}\n")
            
            f.write(f"\n")
            f.write(f"{'='*100}\n")
            f.write(f"검증 완료\n")
            f.write(f"{'='*100}\n")
        
        logger.info(f"📄 리포트 저장: {output_file}")
        
    except Exception as e:
        logger.error(f"❌ 리포트 저장 실패: {e}")
    
    return results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="실시간 데이터 자동 검증")
    parser.add_argument('--date', type=str, help='날짜 (YYYYMMDD), 미지정 시 오늘')
    parser.add_argument('--report', action='store_true', help='리포트 파일 생성')
    
    args = parser.parse_args()
    
    # 날짜 설정
    if args.date:
        date_str = args.date
    else:
        from utils.korean_time import now_kst
        date_str = now_kst().strftime('%Y%m%d')
    
    logger.info(f"🔍 자동 검증 시작: {date_str}")
    
    if args.report:
        results = generate_report(date_str)
    else:
        results = verify_data_consistency(date_str)
    
    # 종료 코드
    if results['success']:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()

