"""
전략 설정 파일

사용 가능한 전략:
1. 'pullback' - 기존 눌림목 캔들패턴 전략 (롤백용)
2. 'closing_trade' - 종가매매(오버나이트) 전략
3. 'weighted_score' - 가중 점수 전략 (Trial #1600, test Calmar 162.75, 2026-04-21)

weighted_score 전략 (현 운영):
- 23개 피처 가중합 > 임계치(-0.127) 시 진입
- 분봉 단위 실시간 스코어링
- 고정 SL -5.04%, TP +7.07%, max_hold 3일
- 장중 청산 (closing_trade 와 달리 오버나이트 홀드 아님)
- 파라미터: core/strategies/weighted_score_params.json

**폐기됨 (2026-04-21)**: 'price_position' 전략은 weighted_score 로 대체되며 완전 삭제됨.
"""


class StrategySettings:
    """전략 설정"""

    # ========================================
    # 사용할 전략 선택
    # ========================================
    # 'pullback'       : 눌림목 캔들패턴 전략 (롤백용)
    # 'closing_trade'  : 종가매매 오버나이트 전략
    # 'weighted_score' : 가중 점수 전략 (2026-04-21, 통합 작업 중)
    ACTIVE_STRATEGY = 'weighted_score'  # <-- 여기서 전략 변경

    # ========================================
    # 종가매매 전략 설정 (closing_trade, 오버나이트 홀드)
    # ========================================
    class ClosingTrade:
        """
        종가매매(오버나이트) 전략 파라미터.
        멀티버스 시뮬 검증 (2025-04~2026-04, 보수화·자본제약):
          +53.7% / MDD 3.56% / 승률 60.6% / 404건 / gap_down_rate 4.93%
        """
        CANDLE_INTERVAL = 1

        # 진입 시간대 (HHMM int) — 시뮬 signal_prev_body_momentum 와 단발 평가 정합 (2026-04-18)
        # START=1420: 14:00~14:19 매 분 평가 경로를 차단. 14:20:05 트리거 시점 단발 진입.
        # END=1422: 14:20:05 놓칠 경우 14:21:05 에 14:20봉 close로 예비 진입 (시뮬 ≤1분 괴리)
        ENTRY_HHMM_START = 1420
        ENTRY_HHMM_END = 1422

        # 신호 조건 (prev_body_momentum)
        MIN_PREV_BODY_PCT = 1.0       # 전일 양봉 몸통 최소 (%)
        MAX_DAY_DECLINE_PCT = -3.0    # 당일 시가 대비 최저점 하한 (%)
        REQUIRE_VWAP_ABOVE = True     # 현재 봉 close > 당일 누적 VWAP

        # 후보 갭 필터 (시뮬 screen_for_day_strict 와 정합)
        MIN_GAP_PCT = 0.5             # 시가/전일종가 갭 하한 (%)
        MAX_GAP_PCT = 5.0             # 시가/전일종가 갭 상한 (%)
        MAX_ABS_GAP_PCT = 3.0         # 절대값 상한 — 실질적으로 상방 3% 컷
        MIN_GAP_DOWN_PCT = -2.0       # 갭다운 하한 (중복 의미이나 시뮬 구조 준수)

        # 후보 풀 (시뮬 screen_for_day_strict 와 정합)
        PRELOAD_TOP_N = 100           # 전일 거래대금 상위 N종목 (시뮬: 100)
        PRELOAD_ONLY_CANDIDATES = True  # 프리로드 외(실시간 스크리너) 종목 진입 차단

        # 청산 설정
        # EXIT_HHMM=850: 08:50 주문 접수로 09:00 동시호가 단일가매매에 편입 → 시뮬 next_O[i_open] 정합
        # (KIS API는 08:20부터 예약주문 수용)
        EXIT_HHMM = 850
        EXIT_DEADLINE_HHMM = 905      # 09:05까지 체결 확인
        GAP_SL_LIMIT_PCT = -5.0       # 시장가 매도라 기록용 (실제 주문 영향 없음)

        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]
        MAX_DAILY_POSITIONS = 5

        # Surge Avoidance 필터 (시뮬 filter_surge_avoidance, 2026-04-18 정합)
        # best 파라미터 불명 — 안전 측면에서 활성화 (급등/VI 종목 배제)
        SURGE_AVOIDANCE_ENABLED = True
        SURGE_MAX_PREV_TO_LAST_PCT = 15.0    # 전일종가 대비 > 15% 배제
        SURGE_MAX_INTRADAY_RANGE_PCT = 12.0  # (고-저)/저 > 12% 배제
        SURGE_MAX_PCT_FROM_OPEN = 10.0       # 시가 대비 > 10% 배제

        # 매수 주문 제어 (2026-04-18)
        BUY_TIMEOUT_SECONDS = 60             # 지정가 미체결 타임아웃 (시뮬 단발 체결 가정 정합)
        DISABLE_MARKET_ORDER_FALLBACK = True # 타임아웃 시 시장가 전환 금지 → 취소

    # ========================================
    # 가중 점수 전략 설정 (weighted_score) — **단일 관리 지점**
    # ========================================
    class WeightedScore:
        """
        가중 점수 전략 (Trial #1600, 2026-04-21 탐색).

        백테스트 성과 (200종목 × 88일 test):
            test Calmar 162.75, return +74.2%, MDD 2.84%, Sharpe 9.69,
            win 62.2%, 394건

        파라미터 소스:
          - 이 파일: 운영 설정 (진입/청산 임계값, 동시보유, 자금관리, 가상매매 스위치)
          - core/strategies/weighted_score_params.json: 피처 가중치·정규화 분포 (연구 추출)
          - trading_config.json: **사용 안 함** (risk_management 값 무시됨)

        연구 아카이브: analysis/research/weighted_score/
        통합 계획: analysis/research/weighted_score/INTEGRATION_PLAN.md

        **하나의 파일 정책 (2026-04-21)**: weighted_score 운영 관련 수치는 모두 이 클래스에
        서 관리한다. trading_decision_engine 의 get_effective_*() 가 이 클래스 값을 우선
        참조하도록 구현됨.
        """
        # ---- 캔들 / 진입 시간 ----
        CANDLE_INTERVAL = 1
        ENTRY_START_HOUR = 9
        ENTRY_END_HOUR = 14               # 14 시 이후 진입 금지
        WARMUP_MINUTES = 30               # 09:30 이후 진입 허용 (ret_30min 워밍업)
        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]

        # ---- 청산 임계값 (research Trial #1600) ----
        STOP_LOSS_PCT = -5.04             # 손절 (%, 음수)
        TAKE_PROFIT_PCT = 7.07            # 익절 (%, 양수)

        # ---- 홀딩 / 동시보유 ----
        MAX_HOLDING_DAYS = 3              # 거래일 기준 최대 보유 (research 값)
        MAX_DAILY_POSITIONS = 9           # 동시 보유 최대 (research Trial #1600 값, 2026-04-21 5 → 9)

        # ---- 오버나이트 홀드 ----
        # True : 3 거래일까지 보유 (연구 Calmar 162.75 재현 조건)
        #        → EOD 15:00 에서 days_held < MAX_HOLDING_DAYS 포지션은 스킵
        # False: EOD 15:00 강제 청산 (effective max_hold=1일, 보수적)
        ALLOW_OVERNIGHT_HOLD = True

        # ---- 자금 관리 ----
        # 각 매수 = 계좌 총잔고 × BUY_BUDGET_RATIO (고정, compounding 아님)
        # 연구 Trial #1600 재현: 9 × 10% = 90% 활용, 10% 현금 buffer
        # (5종목 운영 시에는 0.19 가 적절: 5×19%=95%)
        BUY_BUDGET_RATIO = 0.10           # 1/MAX_DAILY_POSITIONS ≈ 0.111 보다 살짝 보수적
        BUY_COOLDOWN_MINUTES = 25         # 동일 종목 재매수 쿨다운

        # ---- 거래 제한 ----
        ONE_TRADE_PER_STOCK_PER_DAY = True

        # ---- Universe 공급 ----
        UNIVERSE_TOP_N = 300              # 전일 거래대금 상위 N
        REQUIRE_RESEARCH_UNIVERSE = True  # research universe(517) 교집합만 사용

        # ---- Phase 5 가상 매매 모드 ----
        # True : main.py 분기에서 execute_virtual_buy 로 라우팅 (실 계좌 주문 X)
        # False: execute_real_buy (실 계좌 주문)
        VIRTUAL_ONLY = False  # 2026-04-21 실전 전환 (가상매매 단계 스킵)

    # ========================================
    # 실시간 종목 스크리너 설정
    # ========================================
    # ⚠️ closing_trade 전략은 프리로드 30종목(preload_previous_day_stocks)만 후보로 사용.
    #    실시간 스크리너 SCAN_END(11:50)는 price_position 기준이며 closing_trade 진입창
    #    (14:00~14:20) 전에 종료되지만, 이는 의도된 설계임. (2026-04-18 검증)
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
        MAX_GAP_PCT = 1.5                       # 시가 vs 전일종가 갭 최대 (%, 상방) - 멀티버스: 1.5%가 +32%p 개선
        MIN_GAP_DOWN_PCT = -2.0                 # 시가 vs 전일종가 갭다운 하한 (실거래: -2% 이하 승률 9%)
        MAX_PHASE3_CHECKS = 15                  # Phase3 최대 검증 종목 수

        # 제한
        MAX_CANDIDATES_PER_SCAN = 5             # 스캔당 최대 추가 종목 수
        MAX_TOTAL_CANDIDATES = 15               # 일일 최대 총 후보 종목 수

        # 점수 임계값 (04-13 멀티버스: T65가 5 fold 중 4 fold 우위, +5.2%p 개선, 승률 62.1→62.4%)
        MIN_SCORE = 65                          # 이 점수 미만 종목은 후보에서 제외 (0 = 비활성)

        # 프리로드 종목 전용 점수 임계값 (04-13 멀티버스: 프리로드 T70이 +3.9%p, 3/5 fold 우위)
        # 주의: 진입 시점 실시간 계산시 전일종가 기반 change_rate(10pt) 제외 → 실효 임계값 65 권장
        PRELOAD_MIN_SCORE = 65                  # 0 = 비활성

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

        # 심리 판단 임계값 — closing_trade 전략에서는 모든 약세 가드 비활성 (2026-04-18)
        BEARISH_THRESHOLD = -99.0               # 사실상 트리거 불가
        VERY_BEARISH_THRESHOLD = -99.0
        EXTREME_BEARISH_THRESHOLD = -99.0
        BULLISH_THRESHOLD = 99.0

        # 약세장 포지션 축소 — 비활성 (모두 FALLBACK과 동일)
        BEARISH_MAX_POSITIONS = 5
        VERY_BEARISH_MAX_POSITIONS = 5
        EXTREME_BEARISH_MAX_POSITIONS = 5

        # 서킷브레이커 — 시뮬 track_b_closing_sim:155-158 과 정합 (원복, 2026-04-18)
        # 시뮬 +53.7% 검증이 "전일 KOSPI/KOSDAQ -3% 이하인 날 건너뛰기"를 포함한 결과
        CIRCUIT_BREAKER_PREV_DAY_PCT = -3.0
        PREV_DAY_DECLINE_THRESHOLD = -99.0    # 로깅 전용 (실질 비활성)
        CIRCUIT_BREAKER_PREV_DAY_PCT_WITH_GAP = -99.0  # NXT 연계 가드 비활성
        CIRCUIT_BREAKER_NXT_GAP_PCT = -99.0
        CIRCUIT_BREAKER_RELEASE_GAP_PCT = 99.0

        # 장 시작 갭 / 갭업 / 장중 지수 / 동적 SL — 전부 비활성
        MARKET_OPEN_GAP_CHECK_ENABLED = False
        MARKET_OPEN_GAP_THRESHOLD_PCT = -99.0
        MARKET_OPEN_GAP_CHECK_MINUTE = 1

        MARKET_OPEN_GAP_UP_FILTER_ENABLED = False
        MARKET_OPEN_GAP_UP_THRESHOLD_PCT = 99.0

        INTRADAY_INDEX_CHECK_ENABLED = False
        INTRADAY_INDEX_CHECK_INTERVAL_MINUTES = 2
        INTRADAY_INDEX_DROP_THRESHOLD_PCT = -99.0
        INTRADAY_INDEX_RECOVERY_PCT = -99.0

        INTRADAY_DYNAMIC_SL_ENABLED = False
        INTRADAY_SL_TIGHTEN_THRESHOLD_PCT = -99.0
        INTRADAY_TIGHTENED_STOP_LOSS_RATIO = 0.05
        INTRADAY_SL_RECOVERY_PCT = -99.0

        # NXT 실패 시 기본값
        FALLBACK_SENTIMENT = 'neutral'
        FALLBACK_MAX_POSITIONS = 5               # closing_trade MAX_DAILY_POSITIONS 와 일치

    # ========================================
    # 성과 기반 매수 게이트 설정
    # ========================================
    class PerformanceGate:
        """성과 기반 매수 게이트 — closing_trade 에서 비활성 (2026-04-18)"""
        ENABLED = False
        ROLLING_N = 20
        ROLLING_THRESHOLD = 0.40
        CONSEC_LOSS_LIMIT = 3
        HARD_CAP_DAYS = 10

    # ========================================
    # closing_trade 시뮬 기준선 (daily_report.py 참조)
    # ========================================
    class SimBaseline:
        """
        closing_trade 시뮬 기준선 (월별 rolling walk-forward OOS 기반, 2026-04-18 갱신).
        데이터: 2025-10 ~ 2026-04 월별 독립 시뮬, 운영 파라미터 고정
                (analysis/results/walkforward_monthly.json)
        범위: 월평균 +3.20% ± 2.90, 연율 환산 +45.93%
              최악 월 gap_down_rate 43.48% (2026-03) 관측
        """
        UPDATED = '2026-04-18'
        PERIOD = '2025-10~2026-04 (월별 OOS)'
        NOTE = 'operational params, monthly rolling OOS'
        WIN_RATE = 63.2              # 월평균 승률 (%)
        AVG_PNL_PCT = 0.84           # 건당 평균 순수익률 (%) — OOS 2.5개월 기준
        GAP_DOWN_RATE = 10.25        # 월평균 gap_down (pnl ≤ -3%) 비율 (%)
        MONTHLY_STDEV_RETURN = 2.90  # 월 수익률 표준편차 (%)
        ANNUAL_COMPOUND_EST = 45.93  # 월평균 복리 기반 연율 추정 (%)
        WORST_MONTH_GDR = 43.48      # 최악 월 gap_down_rate 관측치 (%)
        STRATEGY_START_DATE = '20260420'  # closing_trade 첫 매수 예정일 (월요일)

    # ========================================
    # 눌림목 캔들패턴 전략 설정 (pullback)
    # ========================================
    class Pullback:
        # 캔들 간격 (분)
        CANDLE_INTERVAL = 3          # 3분봉 사용

        # 기존 설정은 advanced_filter_settings.py 참조


def get_candle_interval() -> int:
    """현재 활성 전략의 캔들 간격(분) 반환"""
    if StrategySettings.ACTIVE_STRATEGY == 'closing_trade':
        return StrategySettings.ClosingTrade.CANDLE_INTERVAL
    if StrategySettings.ACTIVE_STRATEGY == 'weighted_score':
        return StrategySettings.WeightedScore.CANDLE_INTERVAL
    return StrategySettings.Pullback.CANDLE_INTERVAL


def is_overnight_strategy() -> bool:
    """전체 EOD 청산 스킵 플래그.

    closing_trade 는 익일 09:00 시장가 청산 로직을 별도 보유 → 전체 스킵.
    weighted_score 는 포지션별 days_held 기반 선별적 스킵 (EOD 함수 내부 처리).
    """
    return StrategySettings.ACTIVE_STRATEGY == 'closing_trade'


def allow_weighted_score_overnight() -> bool:
    """weighted_score 전략이 활성이면서 overnight 홀드 허용 여부."""
    return (
        StrategySettings.ACTIVE_STRATEGY == 'weighted_score'
        and StrategySettings.WeightedScore.ALLOW_OVERNIGHT_HOLD
    )


# 설정 검증
def validate_settings():
    """설정 유효성 검증"""
    valid_strategies = ['pullback', 'closing_trade', 'weighted_score']

    if StrategySettings.ACTIVE_STRATEGY not in valid_strategies:
        raise ValueError(
            f"잘못된 전략: {StrategySettings.ACTIVE_STRATEGY}. "
            f"사용 가능: {valid_strategies}"
        )

    if StrategySettings.ACTIVE_STRATEGY == 'closing_trade':
        ct = StrategySettings.ClosingTrade
        if ct.ENTRY_HHMM_START >= ct.ENTRY_HHMM_END:
            raise ValueError("ENTRY_HHMM_START는 ENTRY_HHMM_END보다 작아야 합니다")
        if ct.MAX_DAILY_POSITIONS <= 0:
            raise ValueError("MAX_DAILY_POSITIONS는 1 이상이어야 합니다")
        if not ct.ALLOWED_WEEKDAYS:
            raise ValueError("ALLOWED_WEEKDAYS가 비어있습니다")

    if StrategySettings.ACTIVE_STRATEGY == 'weighted_score':
        ws = StrategySettings.WeightedScore
        if ws.ENTRY_START_HOUR >= ws.ENTRY_END_HOUR:
            raise ValueError("ENTRY_START_HOUR은 ENTRY_END_HOUR보다 작아야 합니다")
        if ws.MAX_DAILY_POSITIONS <= 0:
            raise ValueError("MAX_DAILY_POSITIONS는 1 이상이어야 합니다")
        if not ws.ALLOWED_WEEKDAYS:
            raise ValueError("ALLOWED_WEEKDAYS가 비어있습니다")
        # params.json 존재 여부는 trading_decision_engine 초기화 시 확인

    return True


# 모듈 로드 시 검증 실행
try:
    validate_settings()
except Exception as e:
    print(f"⚠️ 전략 설정 오류: {e}")
