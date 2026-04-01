"""
전략 설정 파일

사용 가능한 전략:
1. 'pullback' - 기존 눌림목 캔들패턴 전략 (기본값)
2. 'price_position' - 가격 위치 기반 전략 (신규)

가격 위치 기반 전략 (price_position):
- 시가 대비 1~3% 상승 구간 진입
- 월~금 전체 거래
- 9시~12시 진입
- 손절 -5.0%, 익절 +6.0%
- 진입 전 변동성 > 1.2% 제외, 20봉 모멘텀 > +2.0% 제외
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
        MAX_PRE_VOLATILITY = 1.2     # 진입 전 10봉 변동성 상한 (%) — 0.8→1.2 (익절 특성 분석 최적화)
        MAX_PRE20_MOMENTUM = 2.0     # 진입 전 20봉 모멘텀 상한 (%) — 1.5→2.0 (시뮬 최적화)
        MIN_RISING_CANDLES = 3       # 직전 N봉 대비 상승 확인 (0이면 비활성)
        MIN_VOLUME_RATIO = 0         # 신호 캔들 거래량 > 직전 5봉 평균 × 이 값 (0이면 비활성)
                                         # 03-28 멀티버스: 5종목+vol1.2x는 최근1M 개선되나, 7종목에서는 역효과 (+15.6%→+7.6%)

        # 손익 설정 (trading_config.json의 설정을 따름)
        # stop_loss_ratio: 0.05 (-5.0%)
        # take_profit_ratio: 0.06 (+6.0%)

        # 거래 제한
        ONE_TRADE_PER_STOCK_PER_DAY = True  # 하루에 종목당 1회만 거래
        MAX_DAILY_POSITIONS = 7              # 최대 동시 보유 종목 수 (03-28 멀티버스: 7종목 +280% vs 5종목 +216%)

        # === ATR 동적 TP/SL ===
        ATR_DYNAMIC_TP_SL_ENABLED = False  # 멀티버스 검증: 고정 SL5/TP6 대비 효과 미미 (04-01)
        ATR_LOOKBACK_DAYS = 20
        ATR_TP_MULTIPLIER = 2.0
        ATR_SL_MULTIPLIER = 1.0
        ATR_TP_MIN = 2.0
        ATR_TP_MAX = 10.0
        ATR_SL_MIN = 2.0
        ATR_SL_MAX = 6.0

    # ========================================
    # 실시간 종목 스크리너 설정
    # ========================================
    class Screener:
        ENABLED = True                          # 스크리너 사용 여부
        SCAN_INTERVAL_SECONDS = 120             # 스캔 주기 (2분)
        SCAN_START_HOUR = 9                     # 스캔 시작 시 (9시)
        SCAN_START_MINUTE = 1                   # 스캔 시작 분 (9:01) — 09:05→09:01: 09:10 진입 가능하도록 앞당김
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
        MAX_GAP_PCT = 3.0                       # 시가 vs 전일종가 갭 최대 (%, 상방)
        MIN_GAP_DOWN_PCT = -2.0                 # 시가 vs 전일종가 갭다운 하한 (실거래: -2% 이하 승률 9%)
        MAX_PHASE3_CHECKS = 15                  # Phase3 최대 검증 종목 수

        # 제한
        MAX_CANDIDATES_PER_SCAN = 5             # 스캔당 최대 추가 종목 수
        MAX_TOTAL_CANDIDATES = 15               # 일일 최대 총 후보 종목 수

    # ========================================
    # NXT 프리마켓 인텔리전스 설정
    # ========================================
    class PreMarket:
        ENABLED = True                          # 프리마켓 분석 사용 여부
        SNAPSHOT_INTERVAL_SECONDS = 300          # 스냅샷 수집 주기 (5분)
        MAX_BELLWETHER_STOCKS = 30              # 모니터링 대표 종목 수
        NXT_DIV_CODE = "NX"                     # NXT 시장 코드
        API_CALL_INTERVAL_MS = 100              # API 호출 간격 (ms)

        # 분석 시간 (08:00 ~ 08:55)
        ANALYSIS_START_HOUR = 8
        ANALYSIS_START_MINUTE = 0
        ANALYSIS_END_HOUR = 8
        ANALYSIS_END_MINUTE = 55

        # 심리 판단 임계값 (-1.0 ~ +1.0)
        BEARISH_THRESHOLD = -0.3                # 이 이하면 약세
        VERY_BEARISH_THRESHOLD = -0.7           # 이 이하면 강약세 (손절축소, 매수 허용)
        EXTREME_BEARISH_THRESHOLD = -0.9        # 이 이하면 극약세 (매수 중단)
        BULLISH_THRESHOLD = 0.3                 # 이 이상이면 강세

        # 약세장 포지션 축소 (SL/TP는 항상 5%/6% — 03-24 멀티버스: 축소는 모든 시나리오에서 역효과)
        BEARISH_MAX_POSITIONS = 3               # 5 → 3

        # 강약세장 (sentiment -0.7~-0.9: 매수 허용, 포지션 축소)
        VERY_BEARISH_MAX_POSITIONS = 3          # 포지션 축소

        # 극약세장 (sentiment <= -0.9: 매수 완전 중단)
        EXTREME_BEARISH_MAX_POSITIONS = 0       # 매수 중단

        # 서킷브레이커: 전일 지수 기반 매수 완전 중단
        # 조건1: 전일 KOSPI 또는 KOSDAQ 등락률이 이 값 이하 → 매수 중단
        CIRCUIT_BREAKER_PREV_DAY_PCT = -3.0     # 전일 -3% 이상 하락 (4년 시뮬: -3% 이하만 마이너스)

        # 조건1b: 전일 -1% 이하 감지 (로깅 전용 — SL/TP는 항상 5%/6% 유지)
        PREV_DAY_DECLINE_THRESHOLD = -1.0       # 전일 -1% 이하 시 로깅
        # 조건2: 전일 -1% 이하 + 당일 NXT 갭 이 값 이하 → 매수 중단
        CIRCUIT_BREAKER_PREV_DAY_PCT_WITH_GAP = -1.0  # 전일 -1% 하락
        CIRCUIT_BREAKER_NXT_GAP_PCT = -0.5            # + NXT 갭 -0.5%
        # 해제 조건: 서킷브레이커 발동 상태에서 NXT 갭이 이 값 이상이면 해제
        CIRCUIT_BREAKER_RELEASE_GAP_PCT = 3.0         # NXT 갭 +3% 이상이면 강한 반등으로 해제

        # 장 시작 후 지수 갭 체크 (09:00~09:05 실제 KOSPI/KOSDAQ 시가 확인)
        MARKET_OPEN_GAP_CHECK_ENABLED = True          # 장 시작 갭 체크 사용 여부
        MARKET_OPEN_GAP_THRESHOLD_PCT = -1.5          # 지수 시가 갭 이 값 이하 → 매수 중단
        MARKET_OPEN_GAP_CHECK_MINUTE = 1              # 장 시작 후 N분에 체크 (09:01)

        # 장중 지수 모니터링 (09:30~ 장 마감까지 주기적 체크)
        INTRADAY_INDEX_CHECK_ENABLED = True           # 장중 지수 체크 사용 여부
        INTRADAY_INDEX_CHECK_INTERVAL_MINUTES = 10    # 체크 주기 (분) — 동적SL 반응속도 위해 30→10분
        INTRADAY_INDEX_DROP_THRESHOLD_PCT = -2.0      # 전일 대비 이 값 이하 → 매수 중단
        INTRADAY_INDEX_RECOVERY_PCT = -1.0            # 이 값 이상 회복 시 → 매수 재개

        # 장중 동적 손절 (시뮬 검증: 시장-0.7%→SL3%가 두 기간 모두 1위)
        INTRADAY_DYNAMIC_SL_ENABLED = True            # 장중 동적 SL 사용 여부
        INTRADAY_SL_TIGHTEN_THRESHOLD_PCT = -0.7      # 지수 -0.7% 이하 → SL 축소
        INTRADAY_TIGHTENED_STOP_LOSS_RATIO = 0.03     # 축소된 SL (3%)
        INTRADAY_SL_RECOVERY_PCT = -0.3               # 지수 -0.3% 이상 회복 → SL 원복

        # NXT 실패 시 기본값
        FALLBACK_SENTIMENT = 'neutral'
        FALLBACK_MAX_POSITIONS = 7               # 정상=7종목 (5→7: 03-28 멀티버스 최적화)

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
