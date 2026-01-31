"""
고급 필터 설정 (3분봉 기준)
분석 결과 기반 승률 개선 필터

통합 분석 결과 (2026-01-24, v3):
- 기본 승률: 46.8% (714건)
- 연속양봉1+ & 가격위치80%+: 157건, 승률 74.5% (+27.7%p)
- 연속양봉1+ & 가격위치90%+: 115건, 승률 80.9% (+34.1%p)

회피 조건 (pattern_stages 기반):
- 상승폭 >= 15%: 승률 28.0% (-18.8%p)
- 하락폭 >= 5%: 승률 21.1% (-25.7%p)
- 지지캔들 = 3개: 승률 34.1% (-12.7%p)

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
    # 10. 상승폭 필터 (pattern_stages 기반)
    # 상승폭 >= 15%일 때 승률 28.0% (-18.8%p)
    # ========================================
    UPTREND_GAIN_FILTER = {
        'enabled': True,
        'max_gain': 15.0,  # 상승폭 15% 이상이면 회피
        'description': '상승폭 15% 이상 회피 (과열 진입 방지, 승률 28%)',
    }

    # ========================================
    # 11. 하락폭 필터 (pattern_stages 기반)
    # 하락폭 >= 5%일 때 승률 21.1% (-25.7%p)
    # ========================================
    DECLINE_PCT_FILTER = {
        'enabled': True,
        'max_decline': 5.0,  # 하락폭 5% 이상이면 회피
        'description': '하락폭 5% 이상 회피 (추세 반전 위험, 승률 21%)',
    }

    # ========================================
    # 12. 지지구간 캔들 수 필터 (pattern_stages 기반)
    # 지지캔들 = 3개일 때 승률 34.1% (-12.7%p)
    # ========================================
    SUPPORT_CANDLE_FILTER = {
        'enabled': True,
        'avoid_counts': [3],  # 지지캔들 3개일 때 회피
        'description': '지지구간 캔들 3개 회피 (지지 실패 위험, 승률 34%)',
    }

    # ========================================
    # 13. 일봉 기반 필터 (2026-01-31 분석)
    # 기준 승률: 49.6% (516건)
    # ========================================

    # 13-1. 연속 상승일 필터 (일봉 기준)
    DAILY_CONSECUTIVE_UP = {
        'enabled': False,  # 기본 비활성화 (테스트용)
        'min_days': 1,  # 최소 연속 상승일 (1: 52.8%, 2: 53.3%)
        'description': '일봉 기준 최소 1일 연속 상승 필요 (승률 52.8%, +3.1%p, 381건)',
    }

    # 13-2. 전일 등락률 필터 (일봉 기준)
    DAILY_PREV_CHANGE = {
        'enabled': False,  # 기본 비활성화 (테스트용)
        'min_change': 0.0,  # 최소 전일 등락률 (0%: 52.7%, 1%: 52.8%)
        'description': '전일 종가 상승 필요 (승률 52.7%, +3.1%p, 391건)',
    }

    # 13-3. 거래량 비율 필터 (일봉 기준: 전일 거래량 / 20일 평균)
    DAILY_VOLUME_RATIO = {
        'enabled': False,  # 기본 비활성화 (테스트용)
        'min_ratio': 1.5,  # 최소 거래량 비율 (1.5: 52.7%, 2.0: 52.8%)
        'description': '전일 거래량이 20일 평균의 1.5배 이상 (승률 52.7%, +3.1%p, 262건)',
    }

    # 13-4. 가격 위치 필터 (일봉 기준: 20일 고저점 범위 내 위치)
    DAILY_PRICE_POSITION = {
        'enabled': False,  # 기본 비활성화 (테스트용)
        'min_position': 0.5,  # 최소 가격 위치 (50%: 49.9%, 60%: 50.1%)
        'description': '20일 범위 내 가격 위치 50% 이상 (승률 49.9%)',
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
    # 일봉 필터 프리셋 (2026-01-31 분석)
    # ========================================
    DAILY_PRESETS = {
        # 옵션 0: 필터 없음 (베이스라인)
        'none': {
            'description': '일봉 필터 없음 (베이스라인)',
            'expected_winrate': 49.6,
            'expected_trades': 516,
        },
        # 옵션 1: 전일 상승
        'prev_day_up': {
            'DAILY_PREV_CHANGE': {'enabled': True, 'min_change': 0.0},
            'description': '전일 종가 상승 (보합 포함)',
            'expected_winrate': 52.7,
            'expected_trades': 391,  # 76% 유지
        },
        # 옵션 2: 연속 상승 1일
        'consecutive_1day': {
            'DAILY_CONSECUTIVE_UP': {'enabled': True, 'min_days': 1},
            'description': '최소 1일 연속 상승',
            'expected_winrate': 52.8,
            'expected_trades': 381,  # 74% 유지
        },
        # 옵션 3: 연속 상승 + 가격위치 (복합)
        'balanced': {
            'DAILY_CONSECUTIVE_UP': {'enabled': True, 'min_days': 1},
            'DAILY_PRICE_POSITION': {'enabled': True, 'min_position': 0.5},
            'description': '연속 상승 1일 + 가격위치 50% 이상',
            'expected_winrate': 52.5,
            'expected_trades': 373,  # 72% 유지
        },
        # 옵션 4: 연속 상승 2일 (승률 우선)
        'consecutive_2days': {
            'DAILY_CONSECUTIVE_UP': {'enabled': True, 'min_days': 2},
            'description': '최소 2일 연속 상승',
            'expected_winrate': 53.3,
            'expected_trades': 246,  # 48% 유지
        },
        # 옵션 5: 거래량 급증
        'volume_surge': {
            'DAILY_VOLUME_RATIO': {'enabled': True, 'min_ratio': 1.5},
            'description': '전일 거래량 20일 평균의 1.5배 이상',
            'expected_winrate': 52.7,
            'expected_trades': 262,  # 51% 유지
        },
    }

    # ========================================
    # 현재 활성 프리셋 (None이면 개별 설정 사용)
    # ========================================
    ACTIVE_PRESET = None  # 'conservative', 'balanced', 'aggressive', 'highest_winrate'

    # ========================================
    # 일봉 필터 프리셋 선택 (2026-01-31 분석 결과)
    # ========================================
    # None: 일봉 필터 사용 안 함
    # 'volume_surge': 최고 수익 200만원 (승률 52.7%, 거래 262건) - 거래량 급증 전략 ⭐ 추천
    # 'consecutive_2days': 최고 승률 53.3% (수익 185만원, 거래 246건) - 안정성 우선
    # 'prev_day_up': 승률 52.7% (수익 184만원, 거래 391건) - 거래 빈도 유지
    # 'consecutive_1day': 승률 52.8% (수익 182만원, 거래 381건)
    # 'balanced': 승률 52.5% (수익 173만원, 거래 373건)
    #
    # ⚠️ 'none' 사용 시: 승률 49.6%, 수익 144만원으로 가장 낮음
    #
    ACTIVE_DAILY_PRESET = None  # None 또는 'volume_surge', 'consecutive_2days', 'prev_day_up', 'consecutive_1day', 'balanced'
