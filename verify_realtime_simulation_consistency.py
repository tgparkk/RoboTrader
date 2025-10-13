#!/usr/bin/env python3
"""
실시간 거래 vs 시뮬레이션 일치성 검증 스크립트

동일한 분봉 데이터를 사용했을 때 신호 생성 및 매매 판단이 동일한지 검증
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
from core.timeframe_converter import TimeFrameConverter
from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType

logger = setup_logger(__name__)


def test_signal_generation_consistency(stock_code: str, df_1min: pd.DataFrame):
    """
    동일한 1분봉 데이터로 신호 생성 테스트
    
    Args:
        stock_code: 종목코드
        df_1min: 1분봉 데이터
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 신호 생성 일치성 테스트: {stock_code}")
    logger.info(f"{'='*80}")
    
    if df_1min is None or df_1min.empty:
        logger.error("데이터 없음")
        return
    
    logger.info(f"1분봉 데이터: {len(df_1min)}개")
    
    # 3분봉 변환
    df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)
    
    if df_3min is None or df_3min.empty:
        logger.error("3분봉 변환 실패")
        return
    
    logger.info(f"3분봉 데이터: {len(df_3min)}개")
    
    # 여러 시점에서 신호 생성 비교
    test_indices = [
        len(df_3min) // 4,  # 25% 지점
        len(df_3min) // 2,  # 50% 지점
        len(df_3min) * 3 // 4,  # 75% 지점
        len(df_3min) - 1  # 마지막
    ]
    
    results = []
    
    for idx in test_indices:
        if idx < 5:  # 최소 5개 필요
            continue
        
        # 해당 시점까지의 데이터
        data_subset = df_3min.iloc[:idx+1].copy()
        candle_time = data_subset['datetime'].iloc[-1]
        
        logger.info(f"\n--- 테스트 시점: {candle_time.strftime('%H:%M')} (인덱스: {idx}) ---")
        
        # 방법 1: 실시간 방식 (generate_improved_signals)
        signal_realtime = PullbackCandlePattern.generate_improved_signals(
            data_subset,
            stock_code=stock_code,
            debug=False
        )
        
        # 방법 2: 시뮬레이션 방식 (동일한 함수 사용)
        signal_simulation = PullbackCandlePattern.generate_improved_signals(
            data_subset,
            stock_code=stock_code,
            debug=False
        )
        
        # 비교
        if signal_realtime and signal_simulation:
            match = (
                signal_realtime.signal_type == signal_simulation.signal_type and
                abs(signal_realtime.confidence - signal_simulation.confidence) < 0.01 and
                abs(signal_realtime.buy_price - signal_simulation.buy_price) < 1.0
            )
            
            logger.info(f"실시간: {signal_realtime.signal_type.value}, 신뢰도: {signal_realtime.confidence:.1f}%, 가격: {signal_realtime.buy_price:,.0f}")
            logger.info(f"시뮬: {signal_simulation.signal_type.value}, 신뢰도: {signal_simulation.confidence:.1f}%, 가격: {signal_simulation.buy_price:,.0f}")
            logger.info(f"일치 여부: {'✅ 일치' if match else '❌ 불일치'}")
            
            results.append({
                'time': candle_time.strftime('%H:%M'),
                'index': idx,
                'match': match,
                'realtime_signal': signal_realtime.signal_type.value,
                'simulation_signal': signal_simulation.signal_type.value
            })
        else:
            logger.warning(f"신호 생성 실패")
            results.append({
                'time': candle_time.strftime('%H:%M'),
                'index': idx,
                'match': False,
                'realtime_signal': str(signal_realtime.signal_type.value if signal_realtime else None),
                'simulation_signal': str(signal_simulation.signal_type.value if signal_simulation else None)
            })
    
    # 결과 요약
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 테스트 결과 요약")
    logger.info(f"{'='*80}")
    
    match_count = sum(1 for r in results if r['match'])
    logger.info(f"✅ 일치: {match_count}/{len(results)}개")
    logger.info(f"❌ 불일치: {len(results) - match_count}/{len(results)}개")
    
    return results


def test_3min_conversion_consistency(stock_code: str, df_1min: pd.DataFrame):
    """
    3분봉 변환 일치성 테스트
    
    여러 번 변환해도 동일한 결과가 나오는지 확인
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 3분봉 변환 일치성 테스트: {stock_code}")
    logger.info(f"{'='*80}")
    
    if df_1min is None or df_1min.empty:
        logger.error("데이터 없음")
        return False
    
    # 5회 변환 시도
    results = []
    for i in range(5):
        df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)
        if df_3min is not None:
            results.append({
                'count': len(df_3min),
                'first_time': df_3min['datetime'].iloc[0],
                'last_time': df_3min['datetime'].iloc[-1],
                'total_volume': df_3min['volume'].sum()
            })
    
    # 일치성 확인
    if len(results) < 2:
        logger.error("변환 실패")
        return False
    
    all_match = all(
        r['count'] == results[0]['count'] and
        r['first_time'] == results[0]['first_time'] and
        r['last_time'] == results[0]['last_time'] and
        r['total_volume'] == results[0]['total_volume']
        for r in results
    )
    
    if all_match:
        logger.info(f"✅ 5회 변환 모두 일치")
        logger.info(f"   3분봉 개수: {results[0]['count']}개")
        logger.info(f"   시간 범위: {results[0]['first_time']} ~ {results[0]['last_time']}")
    else:
        logger.error(f"❌ 변환 결과 불일치 발견")
        for i, r in enumerate(results):
            logger.error(f"   #{i+1}: {r['count']}개, {r['first_time']} ~ {r['last_time']}")
    
    return all_match


def compare_buy_logic(stock_code: str, df_1min: pd.DataFrame, test_time: str = "10:30"):
    """
    실시간 매수 판단 로직 vs 시뮬레이션 매수 로직 비교
    
    Args:
        stock_code: 종목코드
        df_1min: 1분봉 데이터
        test_time: 테스트할 시간 (HH:MM)
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 매수 로직 비교: {stock_code} @ {test_time}")
    logger.info(f"{'='*80}")
    
    try:
        # 테스트 시점까지의 데이터만 사용
        test_datetime = pd.to_datetime(f"2025-01-01 {test_time}:00")
        df_until_test = df_1min[df_1min['datetime'].dt.time <= test_datetime.time()].copy()
        
        if df_until_test.empty:
            logger.error("테스트 시점 데이터 없음")
            return
        
        logger.info(f"테스트 데이터: {len(df_until_test)}개 1분봉")
        
        # 3분봉 변환
        df_3min = TimeFrameConverter.convert_to_3min_data(df_until_test)
        
        if df_3min is None or len(df_3min) < 5:
            logger.error("3분봉 데이터 부족")
            return
        
        logger.info(f"3분봉: {len(df_3min)}개")
        
        # 신호 생성
        signal_strength = PullbackCandlePattern.generate_improved_signals(
            df_3min,
            stock_code=stock_code,
            debug=True
        )
        
        if signal_strength is None:
            logger.error("신호 생성 실패")
            return
        
        logger.info(f"신호 유형: {signal_strength.signal_type.value}")
        logger.info(f"신뢰도: {signal_strength.confidence:.1f}%")
        logger.info(f"매수가 (4/5가): {signal_strength.buy_price:,.0f}원")
        logger.info(f"진입 저가: {signal_strength.entry_low:,.0f}원")
        logger.info(f"목표 수익률: {signal_strength.target_profit*100:.1f}%")
        logger.info(f"신호 이유: {', '.join(signal_strength.reasons)}")
        
        # 간단한 패턴 필터 테스트
        try:
            from core.indicators.simple_pattern_filter import SimplePatternFilter
            pattern_filter = SimplePatternFilter()
            
            should_filter, filter_reason = pattern_filter.should_filter_out(
                stock_code, signal_strength, df_3min
            )
            
            logger.info(f"간단한 패턴 필터: {'❌ 차단' if should_filter else '✅ 통과'} - {filter_reason}")
            
        except Exception as e:
            logger.warning(f"패턴 필터 테스트 실패: {e}")
        
    except Exception as e:
        logger.error(f"매수 로직 비교 실패: {e}")
        import traceback
        logger.error(traceback.format_exc())


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="실시간 vs 시뮬레이션 일치성 검증")
    parser.add_argument('--stock', type=str, required=True, help='종목코드')
    parser.add_argument('--date', type=str, help='날짜 (YYYYMMDD), 미지정 시 오늘')
    parser.add_argument('--test-time', type=str, default="10:30", help='매수 로직 테스트 시간 (HH:MM)')
    
    args = parser.parse_args()
    
    # 날짜 설정
    if args.date:
        date_str = args.date
    else:
        from utils.korean_time import now_kst
        date_str = now_kst().strftime('%Y%m%d')
    
    # 데이터 로드
    cache_file = Path(f"cache/minute_data/{args.stock}_{date_str}.pkl")
    
    if not cache_file.exists():
        logger.error(f"캐시 파일 없음: {cache_file}")
        logger.info("먼저 실시간 거래를 실행하거나 save_candidate_data.py로 데이터를 수집하세요.")
        sys.exit(1)
    
    try:
        with open(cache_file, 'rb') as f:
            df_1min = pickle.load(f)
        
        logger.info(f"✅ 데이터 로드 성공: {cache_file}")
        logger.info(f"   1분봉 개수: {len(df_1min)}개")
        
        # 시간 범위 확인
        if 'datetime' in df_1min.columns:
            df_1min['datetime'] = pd.to_datetime(df_1min['datetime'])
            logger.info(f"   시간 범위: {df_1min['datetime'].iloc[0]} ~ {df_1min['datetime'].iloc[-1]}")
        
    except Exception as e:
        logger.error(f"데이터 로드 실패: {e}")
        sys.exit(1)
    
    # 테스트 실행
    logger.info(f"\n{'='*80}")
    logger.info(f"🔍 일치성 검증 시작")
    logger.info(f"{'='*80}")
    
    # 1. 3분봉 변환 일치성 테스트
    logger.info(f"\n[1/3] 3분봉 변환 일치성 테스트")
    conversion_ok = test_3min_conversion_consistency(args.stock, df_1min)
    
    # 2. 신호 생성 일치성 테스트
    logger.info(f"\n[2/3] 신호 생성 일치성 테스트")
    signal_results = test_signal_generation_consistency(args.stock, df_1min)
    
    # 3. 매수 로직 비교
    logger.info(f"\n[3/3] 매수 로직 비교")
    compare_buy_logic(args.stock, df_1min, args.test_time)
    
    # 최종 결과
    logger.info(f"\n{'='*80}")
    logger.info(f"🎯 검증 완료")
    logger.info(f"{'='*80}")
    
    if conversion_ok:
        logger.info(f"✅ 3분봉 변환: 일치")
    else:
        logger.error(f"❌ 3분봉 변환: 불일치")
    
    if signal_results:
        signal_match_count = sum(1 for r in signal_results if r['match'])
        logger.info(f"{'✅' if signal_match_count == len(signal_results) else '⚠️'} 신호 생성: {signal_match_count}/{len(signal_results)} 일치")


if __name__ == '__main__':
    main()

