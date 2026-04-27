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
    # 활성 전략 (2026-04-27 부터 macd_cross 단일 운영)
    # ========================================
    # 다른 전략 (pullback / closing_trade / weighted_score) 은 모두 폐기됨.
    # 신규 전략 도입 시 valid_strategies 에 추가하고 dispatch 분기를 별도 작성한다.
    ACTIVE_STRATEGY = 'macd_cross'
    PAPER_STRATEGY = None

    # ========================================
    # macd_cross 전략 설정 (페이퍼 단계, 2026-04-26)
    # ========================================
    class MacdCross:
        """
        macd_cross 페이퍼 트레이딩 파라미터.

        Stage 2 best params (backtests/reports/stage2/macd_cross_best.json):
          fast=14, slow=34, signal=12, entry_hhmm_min=1430
        OOS 성과 (backtests/reports/stage2/oos_summary.csv):
          Calmar 54.16, return +11.66%, MDD 1.99%, win 61.1%, 36 trades

        설계서: docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md
        """
        # ---- 분봉 간격 ----
        CANDLE_INTERVAL = 1                    # 1분봉 시그널

        # ---- 시그널 (백테스트와 동일) ----
        FAST_PERIOD = 14
        SLOW_PERIOD = 34
        SIGNAL_PERIOD = 12

        # ---- 진입 시간대 (HHMM int) ----
        # 1431: 백테스트 next_bar_open(14:31) 정렬. 14:30 close 시그널 → 14:31:00 시장가 진입.
        # (이전 1430 은 paper 운영 중 14:30 mid-candle 가격으로 진입해 백테스트와 1분 lookahead 발생)
        ENTRY_HHMM_MIN = 1431
        ENTRY_HHMM_MAX = 1500

        # ---- 청산 ----
        HOLD_DAYS = 2  # 거래일 기준. SL/TP 없음 (G1: 백테스트 100% 재현)

        # ---- 페이퍼 자금 (F1) ----
        VIRTUAL_CAPITAL = 10_000_000           # 가상 자본 1천만원
        BUY_BUDGET_RATIO = 0.20                # 종목당 200만원
        MAX_DAILY_POSITIONS = 5                # 동시 보유 최대

        # ---- Universe ----
        UNIVERSE_TOP_N = 30                    # 거래대금 상위 30 (백테스트 동일)

        # ---- 운영 가드 (G1: 라이브 필터 미적용) ----
        APPLY_LIVE_OVERLAY = False             # 승격 시 True 검토
        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]

        # ---- 실거래 / 가상 라우팅 (Phase 1~4 완료, 2026-04-27 실거래 전환) ----
        # True : 시그널 발생 시 execute_virtual_buy 라우팅 (페이퍼)
        # False: KIS 실 계좌 시장가 주문 (실거래) ← 현재
        VIRTUAL_ONLY = False

    # ========================================
    # 실시간 종목 스크리너 설정
    # ========================================
    # macd_cross 는 자체 universe (preload_macd_cross_universe, top_n=30) 만 사용.
    # 아래 Screener 설정은 일반 후보 스크리닝용 (현재 macd_cross 단일 운영에서는 미사용).
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

def get_candle_interval() -> int:
    """현재 활성 전략의 캔들 간격(분) 반환"""
    return StrategySettings.MacdCross.CANDLE_INTERVAL


def is_overnight_strategy() -> bool:
    """전체 EOD 청산 스킵 플래그 (현재 macd_cross 는 EOD 함수 내부에서 별도 분기)."""
    return False


def allow_weighted_score_overnight() -> bool:
    """[deprecated] weighted_score 폐기로 항상 False."""
    return False


# 설정 검증
def validate_settings():
    """설정 유효성 검증"""
    valid_strategies = ['macd_cross']  # 2026-04-27: 다른 전략 잠금 (코드 삭제는 1주 안정 후)

    if StrategySettings.ACTIVE_STRATEGY not in valid_strategies:
        raise ValueError(
            f"잘못된 전략: {StrategySettings.ACTIVE_STRATEGY}. "
            f"사용 가능: {valid_strategies}"
        )

    valid_paper_strategies = [None, 'macd_cross']
    if StrategySettings.PAPER_STRATEGY not in valid_paper_strategies:
        raise ValueError(
            f"잘못된 페이퍼 전략: {StrategySettings.PAPER_STRATEGY}. "
            f"사용 가능: {valid_paper_strategies}"
        )

    if StrategySettings.ACTIVE_STRATEGY == 'macd_cross':
        mc = StrategySettings.MacdCross
        if mc.ENTRY_HHMM_MIN >= mc.ENTRY_HHMM_MAX:
            raise ValueError("MacdCross.ENTRY_HHMM_MIN은 ENTRY_HHMM_MAX보다 작아야 합니다")
        if mc.MAX_DAILY_POSITIONS <= 0:
            raise ValueError("MacdCross.MAX_DAILY_POSITIONS는 1 이상이어야 합니다")
        if not mc.ALLOWED_WEEKDAYS:
            raise ValueError("MacdCross.ALLOWED_WEEKDAYS가 비어있습니다")

    return True


# 모듈 로드 시 검증 실행
try:
    validate_settings()
except Exception as e:
    print(f"⚠️ 전략 설정 오류: {e}")
