"""
전략 설정 파일

사용 가능한 전략:
1. 'pullback' - 기존 눌림목 캔들패턴 전략 (기본값)
2. 'price_position' - 가격 위치 기반 전략 (신규)

가격 위치 기반 전략 (price_position):
- 시가 대비 1~3% 상승 구간 진입
- 월~금 전체 거래
- 9시~12시 진입
- 손절 -4.0%, 익절 +5.0%
- 진입 전 변동성 > 0.8% 제외, 20봉 모멘텀 > +2.0% 제외
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
        MIN_PCT_FROM_OPEN = 1.0      # 시가 대비 최소 상승률 (%)
        MAX_PCT_FROM_OPEN = 3.0      # 시가 대비 최대 상승률 (%) — 4.0→3.0 (시뮬 최적화)
        ENTRY_START_HOUR = 9         # 진입 시작 시간 (9시)
        ENTRY_END_HOUR = 12          # 진입 종료 시간 (12시)

        # 허용 요일 (0=월, 1=화, 2=수, 3=목, 4=금)
        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]  # 월~금 전체 (시뮬 검증: 화/목 포함이 +44% 수익)

        # 고급 진입 필터
        MAX_PRE_VOLATILITY = 0.8     # 진입 전 10봉 변동성 상한 (%) — 1.0→0.8 (시뮬 최적화)
        MAX_PRE20_MOMENTUM = 2.0     # 진입 전 20봉 모멘텀 상한 (%) — 1.5→2.0 (시뮬 최적화)
        MIN_RISING_CANDLES = 3       # 직전 N봉 대비 상승 확인 (0이면 비활성)

        # 손익 설정 (trading_config.json의 설정을 따름)
        # stop_loss_ratio: 0.04 (-4.0%)
        # take_profit_ratio: 0.05 (+5.0%)

        # 거래 제한
        ONE_TRADE_PER_STOCK_PER_DAY = True  # 하루에 종목당 1회만 거래
        MAX_DAILY_POSITIONS = 5              # 최대 동시 보유 종목 수 (청산 시 새 매수 가능)

    # ========================================
    # 실시간 종목 스크리너 설정
    # ========================================
    class Screener:
        ENABLED = True                          # 스크리너 사용 여부
        SCAN_INTERVAL_SECONDS = 120             # 스캔 주기 (2분)
        SCAN_START_HOUR = 9                     # 스캔 시작 시 (9시)
        SCAN_START_MINUTE = 5                   # 스캔 시작 분 (9:05)
        SCAN_END_HOUR = 11                      # 스캔 종료 시 (11시)
        SCAN_END_MINUTE = 50                    # 스캔 종료 분 (11:50)

        # Phase 2 기본 필터 (거래량순위 데이터 기반)
        MIN_CHANGE_RATE = 0.5                   # 최소 등락률 (%)
        MAX_CHANGE_RATE = 5.0                   # 최대 등락률 (%)
        MIN_PRICE = 5000                        # 최소 가격 (원)
        MAX_PRICE = 500000                      # 최대 가격 (원)
        MIN_TRADING_AMOUNT = 1_000_000_000      # 최소 거래대금 (10억)

        # Phase 3 정밀 필터 (현재가 API 기반)
        MIN_PCT_FROM_OPEN = 0.8                 # 시가 대비 최소 상승률 (%)
        MAX_PCT_FROM_OPEN = 4.0                 # 시가 대비 최대 상승률 (%)
        MAX_GAP_PCT = 3.0                       # 시가 vs 전일종가 갭 최대 (%)
        MAX_PHASE3_CHECKS = 15                  # Phase3 최대 검증 종목 수

        # 제한
        MAX_CANDIDATES_PER_SCAN = 5             # 스캔당 최대 추가 종목 수
        MAX_TOTAL_CANDIDATES = 15               # 일일 최대 총 후보 종목 수

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
