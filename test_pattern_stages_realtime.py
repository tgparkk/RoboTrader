"""
실시간 환경과 동일한 pattern_stages 생성 검증 스크립트

실시간 흐름:
1. pullback_candle_pattern.check_pullback_candle_pattern() 호출
2. signal_strength.pattern_data에 pattern_stages 포함
3. trading_decision_engine에서 pattern_stages 추출
4. advanced_filters.check_signal()에서 필터 적용

이 스크립트는 캐시된 분봉 데이터를 사용하여 위 흐름을 그대로 재현합니다.
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트 추가
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
from utils.data_cache import DataCache
from core.timeframe_converter import TimeFrameConverter
from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
from core.indicators.advanced_filters import AdvancedFilterManager
from utils.signal_replay import list_all_buy_signals


def load_minute_data(stock_code: str, date_str: str) -> pd.DataFrame:
    """캐시에서 분봉 데이터 로드"""
    cache = DataCache()
    data = cache.load_data(stock_code, date_str)
    return data


def test_pattern_stages_generation(stock_code: str, date_str: str):
    """실시간과 동일한 흐름으로 pattern_stages 생성 테스트"""

    print(f"\n{'='*60}")
    print(f"[TEST] pattern_stages 실시간 흐름 검증")
    print(f"   종목: {stock_code}, 날짜: {date_str}")
    print(f"{'='*60}")

    # 1. 분봉 데이터 로드
    df_1min = load_minute_data(stock_code, date_str)
    if df_1min is None or len(df_1min) == 0:
        print(f"[X] 분봉 데이터 없음: {stock_code}")
        return

    print(f"[OK] 1분봉 데이터 로드: {len(df_1min)}개")

    # 2. 3분봉 변환
    df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)
    print(f"[OK] 3분봉 변환: {len(df_3min)}개")

    # 3. 고급 필터 매니저 초기화
    advanced_filter = AdvancedFilterManager()
    active_filters = advanced_filter.get_active_filters()
    print(f"[OK] 고급 필터 활성화: {', '.join(active_filters)}")

    # 4. 시뮬레이션과 완전히 동일한 방식으로 신호 찾기
    # list_all_buy_signals 함수 사용 (signal_replay.py)
    print(f"\n[INFO] 시뮬레이션 방식으로 신호 탐색 중...")

    raw_signals = list_all_buy_signals(
        df_3min=df_3min,
        df_1min=df_1min,
        stock_code=stock_code,
        simulation_date=date_str
    )

    print(f"[OK] 원시 신호 {len(raw_signals)}개 발견")

    signals_found = []

    # 5. 각 신호에 대해 pattern_stages 생성 확인
    for raw_signal in raw_signals:
        signal_idx = raw_signal['index']
        signal_time = raw_signal.get('signal_time') or raw_signal.get('datetime')

        # 해당 시점까지의 데이터
        data_slice = df_3min.iloc[:signal_idx+1].copy()

        # generate_improved_signals로 다시 호출하여 pattern_data 확인
        try:
            result = PullbackCandlePattern.generate_improved_signals(
                data_slice,
                stock_code=stock_code,
                debug=True
            )

            if result and result.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                pattern_data = getattr(result, 'pattern_data', {})
                pattern_stages = pattern_data.get('pattern_stages')

                signal_info = {
                    'time': signal_time,
                    'signal_type': result.signal_type.value,
                    'confidence': result.confidence,
                    'pattern_stages': pattern_stages,
                    'has_pattern_stages': pattern_stages is not None
                }
                signals_found.append(signal_info)

                # 상세 출력
                time_str = signal_time.strftime('%H:%M') if hasattr(signal_time, 'strftime') else str(signal_time)
                print(f"\n[BUY] 매수 신호: {time_str}")
                print(f"   신호 유형: {result.signal_type.value}")
                print(f"   신뢰도: {result.confidence:.1f}%")

                if pattern_stages:
                    print(f"   [OK] pattern_stages 생성됨:")

                    # 1_uptrend
                    uptrend = pattern_stages.get('1_uptrend', {})
                    price_gain = uptrend.get('price_gain', 0)
                    print(f"      - 상승폭: {price_gain*100:.2f}%")

                    # 2_decline
                    decline = pattern_stages.get('2_decline', {})
                    decline_pct = decline.get('decline_pct', 0)
                    print(f"      - 하락폭: {decline_pct:.2f}%")

                    # 3_support
                    support = pattern_stages.get('3_support', {})
                    candle_count = support.get('candle_count', 0)
                    print(f"      - 지지캔들: {candle_count}개")

                    # 고급 필터 적용 테스트
                    ohlcv_sequence = []
                    if len(data_slice) >= 5:
                        recent = data_slice.tail(5)
                        for _, row in recent.iterrows():
                            ohlcv_sequence.append({
                                'open': float(row['open']),
                                'high': float(row['high']),
                                'low': float(row['low']),
                                'close': float(row['close']),
                                'volume': float(row['volume'])
                            })

                    filter_result = advanced_filter.check_signal(
                        ohlcv_sequence=ohlcv_sequence,
                        stock_code=stock_code,
                        signal_time=signal_time,
                        pattern_stages=pattern_stages
                    )

                    if filter_result.passed:
                        print(f"   [OK] 고급 필터 통과")
                    else:
                        print(f"   [BLOCK] 고급 필터 차단: {filter_result.blocked_by}")
                        print(f"      사유: {filter_result.blocked_reason}")
                else:
                    print(f"   [X] pattern_stages 없음!")

        except Exception as e:
            print(f"   [ERROR] {e}")

    # 결과 요약
    print(f"\n{'='*60}")
    print(f"[SUMMARY] 결과 요약")
    print(f"{'='*60}")
    print(f"총 신호 수: {len(signals_found)}")

    with_stages = sum(1 for s in signals_found if s['has_pattern_stages'])
    without_stages = len(signals_found) - with_stages

    print(f"pattern_stages 있음: {with_stages}")
    print(f"pattern_stages 없음: {without_stages}")

    if without_stages > 0:
        print(f"\n[WARN] 경고: pattern_stages가 없는 신호가 있습니다!")
    else:
        print(f"\n[OK] 모든 신호에 pattern_stages가 정상 생성됨")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='pattern_stages 실시간 흐름 검증')
    parser.add_argument('--code', type=str, default='005930', help='종목코드')
    parser.add_argument('--date', type=str, default=None, help='날짜 (YYYYMMDD)')

    args = parser.parse_args()

    # 날짜 기본값: 어제
    if args.date is None:
        yesterday = datetime.now() - timedelta(days=1)
        args.date = yesterday.strftime('%Y%m%d')

    test_pattern_stages_generation(args.code, args.date)


if __name__ == '__main__':
    main()
