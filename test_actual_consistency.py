#!/usr/bin/env python3
"""
실제 실행 테스트: 동일한 데이터로 실시간 vs 시뮬 비교

동일한 1분봉 데이터를 사용하여 실제로 신호를 생성하고 비교
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


def test_realtime_logic(df_1min: pd.DataFrame, stock_code: str, test_time: str = "10:30"):
    """실시간 로직 시뮬레이션"""
    
    logger.info(f"\n{'='*100}")
    logger.info(f"[실시간 로직] 테스트")
    logger.info(f"{'='*100}")
    
    # 테스트 시점까지의 데이터만 사용
    test_datetime = pd.to_datetime(f"2025-01-01 {test_time}:00")
    df_until_test = df_1min[df_1min['datetime'].dt.time <= test_datetime.time()].copy()
    
    logger.info(f"테스트 시점: {test_time}")
    logger.info(f"1분봉 데이터: {len(df_until_test)}개")
    
    # 1. 3분봉 변환 (실시간과 동일)
    df_3min = TimeFrameConverter.convert_to_3min_data(df_until_test)
    
    if df_3min is None or len(df_3min) < 5:
        logger.error("3분봉 데이터 부족")
        return None
    
    logger.info(f"3분봉 변환: {len(df_3min)}개")
    logger.info(f"마지막 3분봉: {df_3min['datetime'].iloc[-1].strftime('%H:%M')}")
    
    # 2. 신호 생성 (실시간과 동일 - trading_decision_engine.py 방식)
    signal_strength = PullbackCandlePattern.generate_improved_signals(
        df_3min,
        stock_code=stock_code,
        debug=True
    )
    
    if signal_strength is None:
        logger.error("신호 생성 실패")
        return None
    
    logger.info(f"\n[신호 생성 결과]")
    logger.info(f"신호 유형: {signal_strength.signal_type.value}")
    logger.info(f"신뢰도: {signal_strength.confidence:.2f}%")
    logger.info(f"매수가 (4/5가): {signal_strength.buy_price:,.0f}원")
    logger.info(f"진입 저가: {signal_strength.entry_low:,.0f}원")
    logger.info(f"목표 수익률: {signal_strength.target_profit*100:.2f}%")
    logger.info(f"신호 이유: {', '.join(signal_strength.reasons)}")
    
    # 3. 간단한 패턴 필터 (실시간과 동일)
    if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
        try:
            from core.indicators.simple_pattern_filter import SimplePatternFilter
            
            pattern_filter = SimplePatternFilter()
            should_filter, filter_reason = pattern_filter.should_filter_out(
                stock_code, signal_strength, df_3min
            )
            
            logger.info(f"\n[간단한 패턴 필터]")
            logger.info(f"필터 결과: {'❌ 차단' if should_filter else '✅ 통과'}")
            logger.info(f"사유: {filter_reason}")
            
            return {
                'signal_strength': signal_strength,
                'filtered': should_filter,
                'filter_reason': filter_reason
            }
            
        except Exception as e:
            logger.error(f"패턴 필터 오류: {e}")
            return None
    else:
        logger.info(f"\n매수 신호 아님 ({signal_strength.signal_type.value})")
        return None


def test_simulation_logic(df_1min: pd.DataFrame, stock_code: str, test_time: str = "10:30"):
    """시뮬레이션 로직 (signal_replay.py 방식)"""
    
    logger.info(f"\n{'='*100}")
    logger.info(f"[시뮬레이션 로직] 테스트")
    logger.info(f"{'='*100}")
    
    # 테스트 시점까지의 데이터만 사용
    test_datetime = pd.to_datetime(f"2025-01-01 {test_time}:00")
    df_until_test = df_1min[df_1min['datetime'].dt.time <= test_datetime.time()].copy()
    
    logger.info(f"테스트 시점: {test_time}")
    logger.info(f"1분봉 데이터: {len(df_until_test)}개")
    
    # 1. 3분봉 변환 (시뮬과 동일)
    df_3min = TimeFrameConverter.convert_to_3min_data(df_until_test)
    
    if df_3min is None or len(df_3min) < 5:
        logger.error("3분봉 데이터 부족")
        return None
    
    logger.info(f"3분봉 변환: {len(df_3min)}개")
    logger.info(f"마지막 3분봉: {df_3min['datetime'].iloc[-1].strftime('%H:%M')}")
    
    # 2. 신호 생성 (시뮬과 동일 - signal_replay.py 방식)
    signal_strength = PullbackCandlePattern.generate_improved_signals(
        df_3min,
        stock_code=stock_code,
        debug=True
    )
    
    if signal_strength is None:
        logger.error("신호 생성 실패")
        return None
    
    logger.info(f"\n[신호 생성 결과]")
    logger.info(f"신호 유형: {signal_strength.signal_type.value}")
    logger.info(f"신뢰도: {signal_strength.confidence:.2f}%")
    logger.info(f"매수가 (4/5가): {signal_strength.buy_price:,.0f}원")
    logger.info(f"진입 저가: {signal_strength.entry_low:,.0f}원")
    logger.info(f"목표 수익률: {signal_strength.target_profit*100:.2f}%")
    logger.info(f"신호 이유: {', '.join(signal_strength.reasons)}")
    
    # 3. 간단한 패턴 필터 (시뮬과 동일)
    if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
        try:
            from core.indicators.simple_pattern_filter import SimplePatternFilter
            
            pattern_filter = SimplePatternFilter()
            should_filter, filter_reason = pattern_filter.should_filter_out(
                stock_code, signal_strength, df_3min
            )
            
            logger.info(f"\n[간단한 패턴 필터]")
            logger.info(f"필터 결과: {'❌ 차단' if should_filter else '✅ 통과'}")
            logger.info(f"사유: {filter_reason}")
            
            return {
                'signal_strength': signal_strength,
                'filtered': should_filter,
                'filter_reason': filter_reason
            }
            
        except Exception as e:
            logger.error(f"패턴 필터 오류: {e}")
            return None
    else:
        logger.info(f"\n매수 신호 아님 ({signal_strength.signal_type.value})")
        return None


def compare_results(realtime_result, simulation_result):
    """두 결과 비교"""
    
    logger.info(f"\n{'='*100}")
    logger.info(f"[비교 결과]")
    logger.info(f"{'='*100}")
    
    if realtime_result is None or simulation_result is None:
        logger.error("❌ 한쪽 또는 양쪽 결과 없음")
        return False
    
    rt = realtime_result['signal_strength']
    sim = simulation_result['signal_strength']
    
    # 상세 비교
    differences = []
    
    # 1. 신호 유형
    if rt.signal_type != sim.signal_type:
        differences.append(f"신호 유형: {rt.signal_type.value} vs {sim.signal_type.value}")
    
    # 2. 신뢰도
    confidence_diff = abs(rt.confidence - sim.confidence)
    if confidence_diff > 0.01:
        differences.append(f"신뢰도: {rt.confidence:.2f}% vs {sim.confidence:.2f}% (차이: {confidence_diff:.2f}%)")
    
    # 3. 매수가
    price_diff = abs(rt.buy_price - sim.buy_price)
    if price_diff > 1.0:
        differences.append(f"매수가: {rt.buy_price:,.0f}원 vs {sim.buy_price:,.0f}원 (차이: {price_diff:,.0f}원)")
    
    # 4. 진입 저가
    entry_diff = abs(rt.entry_low - sim.entry_low)
    if entry_diff > 1.0:
        differences.append(f"진입저가: {rt.entry_low:,.0f}원 vs {sim.entry_low:,.0f}원 (차이: {entry_diff:,.0f}원)")
    
    # 5. 목표 수익률
    target_diff = abs(rt.target_profit - sim.target_profit)
    if target_diff > 0.001:
        differences.append(f"목표수익률: {rt.target_profit*100:.2f}% vs {sim.target_profit*100:.2f}% (차이: {target_diff*100:.2f}%)")
    
    # 6. 필터 결과
    if realtime_result['filtered'] != simulation_result['filtered']:
        differences.append(f"필터 결과: {realtime_result['filtered']} vs {simulation_result['filtered']}")
    
    # 7. 신호 이유
    rt_reasons = set(rt.reasons)
    sim_reasons = set(sim.reasons)
    if rt_reasons != sim_reasons:
        differences.append(f"신호 이유 차이: {rt_reasons.symmetric_difference(sim_reasons)}")
    
    # 결과 출력
    if differences:
        logger.error(f"\n❌ 차이점 발견: {len(differences)}개")
        for i, diff in enumerate(differences, 1):
            logger.error(f"   {i}. {diff}")
        return False
    else:
        logger.info(f"\n✅ 완전 일치!")
        logger.info(f"   신호: {rt.signal_type.value}")
        logger.info(f"   신뢰도: {rt.confidence:.2f}%")
        logger.info(f"   매수가: {rt.buy_price:,.0f}원")
        logger.info(f"   필터: {'차단' if realtime_result['filtered'] else '통과'}")
        return True


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="실제 실행 테스트: 실시간 vs 시뮬")
    parser.add_argument('--stock', type=str, required=True, help='종목코드')
    parser.add_argument('--date', type=str, help='날짜 (YYYYMMDD), 미지정 시 오늘')
    parser.add_argument('--time', type=str, default="10:30", help='테스트 시점 (HH:MM)')
    
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
        
        # datetime 변환
        if 'datetime' in df_1min.columns:
            df_1min['datetime'] = pd.to_datetime(df_1min['datetime'])
        
        logger.info(f"✅ 데이터 로드: {len(df_1min)}개 1분봉")
        logger.info(f"   시간 범위: {df_1min['datetime'].iloc[0].strftime('%H:%M')} ~ {df_1min['datetime'].iloc[-1].strftime('%H:%M')}")
    
    except Exception as e:
        logger.error(f"데이터 로드 실패: {e}")
        sys.exit(1)
    
    # 실시간 로직 테스트
    realtime_result = test_realtime_logic(df_1min, args.stock, args.time)
    
    # 시뮬레이션 로직 테스트
    simulation_result = test_simulation_logic(df_1min, args.stock, args.time)
    
    # 결과 비교
    is_match = compare_results(realtime_result, simulation_result)
    
    # 최종 결과
    logger.info(f"\n{'='*100}")
    if is_match:
        logger.info(f"🎯 최종 결과: ✅ 실시간과 시뮬레이션 로직 완전 일치!")
    else:
        logger.error(f"🚨 최종 결과: ❌ 차이점 발견! 위 내용 확인 필요")
    logger.info(f"{'='*100}")
    
    sys.exit(0 if is_match else 1)


if __name__ == '__main__':
    main()

