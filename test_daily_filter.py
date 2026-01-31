#!/usr/bin/env python3
"""
일봉 필터 테스트 스크립트

사용법:
    python test_daily_filter.py
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from core.indicators.advanced_filters import AdvancedFilterManager
from config.advanced_filter_settings import AdvancedFilterSettings


def test_daily_filter():
    """일봉 필터 테스트"""
    print("=" * 70)
    print("일봉 필터 테스트")
    print("=" * 70)

    # 현재 설정 출력
    print(f"\n현재 활성 프리셋: {AdvancedFilterSettings.ACTIVE_DAILY_PRESET}")
    print(f"마스터 스위치: {AdvancedFilterSettings.ENABLED}")

    # 필터 매니저 초기화
    print("\n필터 매니저 초기화 중...")
    filter_manager = AdvancedFilterManager()

    # 활성 필터 확인
    print(f"\n{filter_manager.get_summary()}")
    active_filters = filter_manager.get_active_filters()
    if active_filters:
        print(f"활성화된 필터: {', '.join(active_filters)}")
    else:
        print("활성화된 필터 없음")

    # 테스트 케이스
    print("\n" + "=" * 70)
    print("테스트 케이스")
    print("=" * 70)

    test_cases = [
        {
            'name': '테스트 1: 일봉 필터 없음 (stock_code/trade_date 미전달)',
            'stock_code': None,
            'trade_date': None,
            'signal_time': datetime(2026, 1, 31, 10, 30),
        },
        {
            'name': '테스트 2: 일봉 필터 적용 (종목: 005930, 날짜: 20260131)',
            'stock_code': '005930',
            'trade_date': '20260131',
            'signal_time': datetime(2026, 1, 31, 10, 30),
        },
        {
            'name': '테스트 3: 일봉 필터 적용 (종목: 000660, 날짜: 20260130)',
            'stock_code': '000660',
            'trade_date': '20260130',
            'signal_time': datetime(2026, 1, 30, 14, 20),
        },
    ]

    for test_case in test_cases:
        print(f"\n{test_case['name']}")
        print("-" * 70)

        result = filter_manager.check_signal(
            stock_code=test_case['stock_code'],
            trade_date=test_case['trade_date'],
            signal_time=test_case['signal_time'],
        )

        if result.passed:
            print("✅ 신호 통과")
        else:
            print(f"❌ 신호 차단: {result.blocked_by}")
            print(f"   사유: {result.blocked_reason}")

        if result.details:
            print(f"   상세: {result.details}")

    # 일봉 특징 직접 확인 (stock_code가 있는 경우)
    if filter_manager._daily_cache:
        print("\n" + "=" * 70)
        print("일봉 특징 확인 (005930, 20260131)")
        print("=" * 70)

        features = filter_manager._extract_daily_features('005930', '20260131')
        if features:
            print(f"연속 상승일: {features.get('consecutive_up_days', 0)}일")
            print(f"전일 등락률: {features.get('prev_day_change', 0):.2f}%")
            print(f"거래량 비율: {features.get('volume_ratio_20d', 0):.2f}x")
            print(f"가격 위치: {features.get('price_position_20d', 0)*100:.1f}%")
        else:
            print("일봉 데이터 없음 또는 부족")

    print("\n" + "=" * 70)
    print("테스트 완료")
    print("=" * 70)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    test_daily_filter()
