"""
전략 설정 파일

사용 가능한 전략:
1. 'pullback' - 기존 눌림목 캔들패턴 전략 (기본값)
2. 'price_position' - 가격 위치 기반 전략 (신규)

가격 위치 기반 전략 (price_position):
- 시가 대비 2~4% 상승 구간 진입
- 월/수/목/금요일 거래 (화요일만 회피)
- 10시~12시 진입
- 손절 -2.5%, 익절 +3.5%
- 시뮬레이션 결과: 승률 59.7%, 월 +87만원 (1000만원 기준)
"""


class StrategySettings:
    """전략 설정"""

    # ========================================
    # 사용할 전략 선택
    # ========================================
    # 'pullback' : 기존 눌림목 캔들패턴 전략
    # 'price_position' : 가격 위치 기반 전략 (신규)
    ACTIVE_STRATEGY = 'price_position'  # <-- 여기서 전략 변경

    # ========================================
    # 가격 위치 기반 전략 설정 (price_position)
    # ========================================
    class PricePosition:
        # 캔들 간격 (분)
        CANDLE_INTERVAL = 1          # 1분봉 사용

        # 진입 조건
        MIN_PCT_FROM_OPEN = 2.0      # 시가 대비 최소 상승률 (%)
        MAX_PCT_FROM_OPEN = 4.0      # 시가 대비 최대 상승률 (%)
        ENTRY_START_HOUR = 10        # 진입 시작 시간 (10시)
        ENTRY_END_HOUR = 12          # 진입 종료 시간 (12시)

        # 허용 요일 (0=월, 1=화, 2=수, 3=목, 4=금)
        # 화요일(1)만 회피
        ALLOWED_WEEKDAYS = [0, 2, 3, 4]  # 월, 수, 목, 금

        # 손익 설정 (trading_config.json의 설정을 따름)
        # stop_loss_ratio: 0.025 (-2.5%)
        # take_profit_ratio: 0.035 (+3.5%)

        # 거래 제한
        ONE_TRADE_PER_STOCK_PER_DAY = True  # 하루에 종목당 1회만 거래
        MAX_DAILY_POSITIONS = 5              # 하루 최대 동시 보유 종목 수

    # ========================================
    # 눌림목 캔들패턴 전략 설정 (pullback)
    # ========================================
    class Pullback:
        # 캔들 간격 (분)
        CANDLE_INTERVAL = 3          # 3분봉 사용

        # 기존 설정은 advanced_filter_settings.py 참조


def get_candle_interval() -> int:
    """현재 활성 전략의 캔들 간격(분) 반환"""
    if StrategySettings.ACTIVE_STRATEGY == 'price_position':
        return StrategySettings.PricePosition.CANDLE_INTERVAL
    else:
        return StrategySettings.Pullback.CANDLE_INTERVAL


# 설정 검증
def validate_settings():
    """설정 유효성 검증"""
    valid_strategies = ['pullback', 'price_position']

    if StrategySettings.ACTIVE_STRATEGY not in valid_strategies:
        raise ValueError(
            f"잘못된 전략: {StrategySettings.ACTIVE_STRATEGY}. "
            f"사용 가능: {valid_strategies}"
        )

    if StrategySettings.ACTIVE_STRATEGY == 'price_position':
        pp = StrategySettings.PricePosition
        if pp.MIN_PCT_FROM_OPEN >= pp.MAX_PCT_FROM_OPEN:
            raise ValueError("MIN_PCT_FROM_OPEN은 MAX_PCT_FROM_OPEN보다 작아야 합니다")
        if pp.ENTRY_START_HOUR >= pp.ENTRY_END_HOUR:
            raise ValueError("ENTRY_START_HOUR은 ENTRY_END_HOUR보다 작아야 합니다")
        if not pp.ALLOWED_WEEKDAYS:
            raise ValueError("ALLOWED_WEEKDAYS가 비어있습니다")

    return True


# 모듈 로드 시 검증 실행
try:
    validate_settings()
except Exception as e:
    print(f"⚠️ 전략 설정 오류: {e}")
