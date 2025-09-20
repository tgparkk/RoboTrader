"""
개선된 신호 생성 테스트

실제 pullback_candle_pattern.py 모듈을 import해서 신호 생성을 테스트
"""

import sys
import os
sys.path.append(os.getcwd())

from core.indicators.pullback_candle_pattern import PullbackCandlePattern, analyze_daily_pattern_strength
import pandas as pd
import numpy as np
from datetime import datetime

def test_signal_generation():
    """실제 신호 생성 테스트"""
    print("개선된 신호 생성 테스트")
    print("="*50)

    # PullbackCandlePattern 인스턴스 생성
    pattern = PullbackCandlePattern()

    # 샘플 3분봉 데이터 생성 (테스트용)
    sample_data = pd.DataFrame({
        'open': [10000, 10050, 10100, 10080, 10120],
        'high': [10080, 10120, 10150, 10100, 10180],
        'low': [9980, 10030, 10080, 10050, 10100],
        'close': [10050, 10100, 10080, 10120, 10150],
        'volume': [50000, 80000, 30000, 25000, 45000],
        'datetime': pd.date_range('2025-09-19 09:00:00', periods=5, freq='3min')
    })

    print(f"샘플 데이터:")
    print(sample_data[['close', 'volume', 'datetime']])

    # 일봉 패턴 분석 테스트
    print(f"\n일봉 패턴 분석 테스트:")
    daily_pattern = analyze_daily_pattern_strength("036570", "20250919")
    print(f"  패턴 강도: {daily_pattern['strength']}")
    print(f"  이상적 패턴: {daily_pattern['ideal_pattern']}")

    # 다양한 시간대에서 신호 생성 테스트
    test_times = [
        (9, 30, "개장시간"),
        (11, 0, "오전시간"),
        (13, 0, "오후시간"),
        (14, 30, "늦은시간")
    ]

    print(f"\n시간대별 신호 생성 테스트:")

    for hour, minute, time_name in test_times:
        test_time = datetime(2025, 9, 19, hour, minute)
        sample_data['datetime'] = pd.date_range(test_time, periods=5, freq='3min')

        try:
            # 신호 생성 시도
            signals = pattern.generate_improved_signals(
                data=sample_data,
                stock_code="036570",
                current_date=test_time.date()
            )

            print(f"  {time_name} ({hour:02d}:{minute:02d}): {len(signals)}개 신호")
            for signal in signals:
                print(f"    - {signal}")

        except Exception as e:
            print(f"  {time_name} ({hour:02d}:{minute:02d}): 오류 - {e}")

if __name__ == "__main__":
    test_signal_generation()