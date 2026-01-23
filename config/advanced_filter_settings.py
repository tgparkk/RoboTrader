"""
고급 필터 설정 (3분봉 기준)
분석 결과 기반 승률 개선 필터 (489건 백테스트 기준)

3분봉 분석 결과 (2026-01-24):
- 기본 승률: 49.9%
- 연속양봉1+ & 가격위치80%+: 102건, 승률 75.5% (+25.6%p)

각 필터는 개별적으로 켜고 끌 수 있습니다.
enabled=False로 설정하면 해당 필터가 비활성화됩니다.
"""


class AdvancedFilterSettings:
    """고급 필터 설정 (3분봉 데이터 분석 기반)"""

    # ========================================
    # 마스터 스위치
    # ========================================
    ENABLED = True  # False면 모든 고급 필터 비활성화

    # ========================================
    # 1. 연속 양봉 필터 (3분봉 기준: 승률 66.7%, +16.8%p)
    # ========================================
    CONSECUTIVE_BULLISH = {
        'enabled': True,
        'min_count': 1,  # 최소 연속 양봉 수
        'description': '최근 3분봉에서 연속 양봉 1개 이상 필요 (승률 66.7%)',
    }

    # ========================================
    # 2. 가격 위치 필터 (3분봉 기준: 80%+ 승률 65.8%, +15.9%p)
    # ========================================
    PRICE_POSITION = {
        'enabled': True,
        'min_position': 0.80,  # 최근 5봉 범위 내 가격 위치 (0=저점, 1=고점)
        'description': '최근 5봉(3분봉) 중 가격이 80% 이상 위치에 있어야 함 (승률 65.8%)',
    }

    # ========================================
    # 3. 윗꼬리 비율 필터 (3분봉 기준: 효과 미미)
    # ========================================
    UPPER_WICK = {
        'enabled': False,  # 비활성화 (3분봉 분석 결과 효과 미미)
        'max_ratio': 0.10,  # 최대 윗꼬리 비율 (10%)
        'description': '돌파 봉의 윗꼬리가 10% 이하여야 함',
    }

    # ========================================
    # 4. 거래량 필터 (3분봉 기준: 1.5x 이상 승률 55.9%, +6.0%p)
    # ========================================
    VOLUME_RATIO = {
        'enabled': False,  # 비활성화 (연속양봉+가격위치 조합이 더 효과적)
        'avoid_range': (0, 1.0),  # 거래량 1.0x 미만 회피 (승률 45.5%)
        'description': '평균 대비 1.0x 미만 거래량 구간 회피',
    }

    # ========================================
    # 5. RSI 필터 (승률: <50 54.8%, 70+ 53.3%)
    # ========================================
    RSI_FILTER = {
        'enabled': False,  # 기본 비활성화 (단독 효과 보통)
        'favorable_ranges': [(0, 50), (70, 100)],  # 유리한 RSI 구간
        'avoid_range': (50, 70),  # 회피 구간 (44% 승률)
        'description': 'RSI 50-70 구간 회피 (중립~약과매수)',
    }

    # ========================================
    # 6. 화요일 필터 (승률 36.2% → 최악)
    # ========================================
    TUESDAY_FILTER = {
        'enabled': True,
        'action': 'avoid',  # 'avoid' = 화요일 거래 회피
        'description': '화요일 거래 회피 (승률 36.2%)',
    }

    # ========================================
    # 7. 시간대 필터 (09시 화요일 29.5% → 절대 회피)
    # ========================================
    TIME_DAY_FILTER = {
        'enabled': True,
        'avoid_combinations': [
            (9, 1),   # 9시 화요일 (승률 29.5%)
            (10, 1),  # 10시 화요일 (승률 40%)
            (11, 1),  # 11시 화요일 (승률 36%)
            (10, 2),  # 10시 수요일 (승률 38%)
        ],
        'description': '승률 40% 미만 시간대-요일 조합 회피',
    }

    # ========================================
    # 8. 저승률 종목 필터
    # ========================================
    LOW_WINRATE_STOCKS = {
        'enabled': True,
        'blacklist': ['101170', '394800'],  # 15.4%, 30% 승률
        'description': '백테스트 기준 저승률 종목 회피',
    }

    # ========================================
    # 9. 첫 거래 필터 (당일 1번째 거래 38.3% 승률)
    # ========================================
    FIRST_TRADE_FILTER = {
        'enabled': False,  # 기본 비활성화 (구현 복잡)
        'description': '당일 첫 번째 거래 회피 (38.3% 승률)',
    }

    # ========================================
    # 복합 필터 프리셋 (3분봉 기준)
    # ========================================
    PRESETS = {
        # 보수적: 높은 승률, 적은 거래 (75.5% 목표)
        'conservative': {
            'CONSECUTIVE_BULLISH': {'enabled': True, 'min_count': 1},
            'PRICE_POSITION': {'enabled': True, 'min_position': 0.80},
            'TUESDAY_FILTER': {'enabled': True},
            'expected_winrate': 75.5,
            'expected_trade_reduction': 79.1,  # 102/489
        },
        # 균형: 적절한 승률과 거래량 (69.3% 목표)
        'balanced': {
            'CONSECUTIVE_BULLISH': {'enabled': True, 'min_count': 1},
            'PRICE_POSITION': {'enabled': True, 'min_position': 0.70},
            'expected_winrate': 69.3,
            'expected_trade_reduction': 74.0,  # 127/489
        },
        # 공격적: 최소 필터, 많은 거래
        'aggressive': {
            'TUESDAY_FILTER': {'enabled': True},
            'TIME_DAY_FILTER': {'enabled': True},
            'expected_winrate': 50.0,
            'expected_trade_reduction': 19.0,
        },
        # 최고승률: 연속양봉3+ (71.6% 승률)
        'highest_winrate': {
            'CONSECUTIVE_BULLISH': {'enabled': True, 'min_count': 3},
            'PRICE_POSITION': {'enabled': True, 'min_position': 0.80},
            'TUESDAY_FILTER': {'enabled': True},
            'expected_winrate': 71.6,
            'expected_trade_reduction': 82.0,  # 88/489
        },
    }

    # ========================================
    # 현재 활성 프리셋 (None이면 개별 설정 사용)
    # ========================================
    ACTIVE_PRESET = None  # 'conservative', 'balanced', 'aggressive', 'highest_winrate'
