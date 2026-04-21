# RoboTrader - Claude 컨텍스트

## Claude 작업 지침

**상세 정보가 필요할 때 참조할 문서**:
- 데이터 흐름, 디버깅, 실시간 vs 시뮬 차이 → `DEVELOPMENT.md` 읽기
- 설정값 변경, 필터 설정, 투자비율 조정 → `CONFIGURATION.md` 읽기

---

## 프로젝트 개요

한국투자증권 KIS API 기반 자동매매 시스템

**데이터 저장**: PostgreSQL (port 5433, DB: `robotrader`)
- 캐시: `minute_candles`, `daily_candles` (utils/data_cache.py)
- 거래: `candidate_stocks`, `real_trading_records`, `virtual_trading_records`, `trading_records` (db/database_manager.py)
- 시장: `nxt_snapshots` (NXT 센티먼트)

**종목 발굴**: 코드 기반 실시간 스크리너 (KOSPI + KOSDAQ 2472종목)

---

## ⚠️ 현재 상태 (2026-04-21): weighted_score 통합 중

```python
# config/strategy_settings.py — weighted_score 운영 수치는 전부 이 클래스에서 관리
ACTIVE_STRATEGY = 'weighted_score'              # 2026-04-21 전환
WeightedScore.STOP_LOSS_PCT = -5.04             # 손절
WeightedScore.TAKE_PROFIT_PCT = 7.07            # 익절
WeightedScore.MAX_HOLDING_DAYS = 3              # 최대 보유 거래일 (research Trial #1600)
WeightedScore.ALLOW_OVERNIGHT_HOLD = True       # EOD 15:00 선별 스킵 (days < max_hold 인 포지션만)
WeightedScore.MAX_DAILY_POSITIONS = 9           # 동시 보유 (research Trial #1600 동일)
WeightedScore.BUY_BUDGET_RATIO = 0.10           # 건당 = 총자본 × 10% (고정, 9종목 × 10% = 90%)
WeightedScore.VIRTUAL_ONLY = True               # main.py 분기에서 가상매매로 라우팅 (실 주문 X)
```

**설정 단일 관리 지점**: weighted_score 운영 수치는 모두 `StrategySettings.WeightedScore` 클래스에서
관리. `trading_config.json` 의 `risk_management.stop_loss_ratio/take_profit_ratio` 와 `order_management.buy_budget_ratio` 는 weighted_score 시 **무시**됨. `trading_decision_engine.get_effective_stop_loss/take_profit` 과 `main.FundManager` 초기화가 WeightedScore 값을 우선 참조한다.

- **실거래 파일**: `core/strategies/weighted_score_strategy.py`, `weighted_score_features.py`,
  `weighted_score_daily_prep.py`, `weighted_score_params.json`
- **통합 계획/진행 상태**: [analysis/research/weighted_score/INTEGRATION_PLAN.md](analysis/research/weighted_score/INTEGRATION_PLAN.md)
- **자동 실행 차단**: `D:\GIT\run_all_robotraders.bat` 의 RoboTrader 라인 주석 처리됨
- **핵심 파라미터**: Trial #1600 (test Calmar 162.75, return +74.2%, MDD 2.84%)
- **Phase 5 연결 완료 (2026-04-21)**:
  - `main._pre_market_task()` 내 `_prepare_weighted_score_for_today()` — universe 300 × research universe 교집합
  - `stock_screener.preload_weighted_score_universe()` — 전일 거래대금 + research universe 교집합
  - `main.py` 매수 경로에서 `VIRTUAL_ONLY=True` 시 `execute_virtual_buy` 라우팅
  - `analyze_sell_decision` — weighted_score 시 max_holding_days 도달 체크 (busday_count)
  - `_execute_end_of_day_liquidation` — overnight 허용 시 days_held < max_hold 포지션 선별 스킵
  - 실 주문 열기: `VIRTUAL_ONLY = False` 한 줄 변경 (가상매매 1~2주 관찰 후)
- **롤백**: `ACTIVE_STRATEGY = 'closing_trade'` 또는 `'pullback'` + .bat 라인 주석 해제
  - price_position 전략은 2026-04-21 완전 삭제되어 롤백 옵션에서 제외됨

> 현재 `VIRTUAL_ONLY=True` 이므로 신호는 발생하되 `virtual_trading_records` 테이블에만 기록 — 실 계좌 주문 없음.

---

## 폐기된 전략

- **price_position** (2026-04-21 삭제): weighted_score 로 대체. `core/strategies/price_position_strategy.py` 파일과 `class PricePosition` 설정, `_check_price_position_buy_signal` 메서드, ATR 동적 TP/SL 관련 dead code 모두 제거.

---

## 현재 시스템 설정

### 투자 비율 (config/trading_config.json)
- **buy_budget_ratio**: 0.19 (건당 가용잔고의 19%, closing_trade 최적값: 5종목 × 0.19 = 95%)

### 손익비
- **고정값**: SL -5.0% / TP +6.0% (동적 손익비 코드 존재하나 전부 비활성, 04-01 멀티버스 검증: 고정 대비 효과 미미)
- 장중 동적 SL: 지수 -0.7% 이하 → SL 3%로 축소, -0.3% 이상 회복 시 원복 (10분 주기 체크)

### 서킷브레이커 (config/strategy_settings.py > PreMarket)
- 전일 KOSPI/KOSDAQ -3% → 매수 완전 중단 (4년 시뮬: -3% 이하만 마이너스)
- 전일 -1% 이하 → SL/TP 정상 유지 (03-24 멀티버스: 축소는 역효과)
- 전일 -1% + NXT 갭 -0.5% → 매수 완전 중단
- NXT sentiment -0.7~-0.9 → very_bearish (3종목 축소, SL/TP는 5%/6% 고정)
- NXT sentiment <= -0.9 → extreme_bearish (매수 완전 중단)
- 장 시작 갭 -1.5% 이하 → 매수 중단 (09:01 체크)
- **장 시작 KOSPI 갭업 +1.0% 이상 → 매수 중단** (09:01 체크, 04-11 멀티버스: 강건성 검증 완료)
- 장중 지수 -0.7% 이하 → SL 3%로 동적 축소 (2분 주기, -0.3% 회복 시 원복)
- 장중 지수 -2% 이하 → 매수 중단 (-1% 이상 회복 시 재개)
- 상세: [docs/pre_market_circuit_breaker.md](docs/pre_market_circuit_breaker.md)

---

## 주요 파일 구조

```
config/
├── trading_config.json          # 거래 설정 (투자비율, 손익비, 수수료)
├── strategy_settings.py         # 전략/스크리너/프리마켓 설정
├── market_hours.py              # 장 시간 설정 (EOD 청산 15:00, 특별일 시프트)
├── settings.py                  # DB 접속 정보 (PG_HOST/PORT/DATABASE/USER/PASSWORD)
├── dynamic_profit_loss_config.py # 동적 손익비 설정 (비활성 dead code)
├── strategy_settings.py > ATR_*  # ATR 동적 TP/SL 설정 (비활성, ATR_DYNAMIC_TP_SL_ENABLED=False)

api/
├── kis_auth.py                  # KIS API 인증 & Rate Limiting
├── kis_order_api.py             # 주문 API
├── kis_chart_api.py             # 차트 데이터 API
├── kis_market_api.py            # 시장 데이터 API
├── kis_account_api.py           # 계좌 조회 API
├── kis_api_manager.py           # API 매니저

core/
├── models.py                    # 핵심 데이터 모델 (StockState, TradingStock, TradingConfig)
├── trading_decision_engine.py   # 매매 판단 엔진 (매수/매도 신호 평가)
├── trade_executor.py            # 매수/매도 실행 로직
├── order_manager.py             # 주문 관리 (미체결, 타임아웃, 정정)
├── stock_screener.py            # 실시간 종목 스크리너
├── trading_stock_manager.py     # 종목 상태 관리 (상태 머신)
├── intraday_stock_manager.py    # 장중 분봉 데이터 관리
├── pre_market_analyzer.py       # 프리마켓 분석 & 서킷브레이커
├── post_market_data_saver.py    # 장 마감 데이터 저장
├── fund_manager.py              # 자금 관리
├── virtual_trading_manager.py   # 가상 매매 관리
├── telegram_integration.py      # 텔레그램 알림
├── candidate_selector.py        # 후보 종목 선정
├── strategies/
│   └── price_position_strategy.py  # 가격 위치 전략

utils/
├── data_cache.py               # PostgreSQL 데이터 캐시
├── korean_time.py              # 한국 시간 유틸리티

db/
└── database_manager.py         # PostgreSQL 데이터 관리

analysis/                        # 분석/시뮬레이션 스크립트
```

---

## 안전장치

- **서킷브레이커**: 전일 -3% → 매수 중단, NXT ≤ -0.9 → 매수 중단, KOSPI갭업 +1.0% → 매수 중단 (상세: docs/pre_market_circuit_breaker.md)
- **장중 동적 SL**: 지수 -0.7% 이하 시 SL 3%로 축소 (03-26 멀티버스: 두 기간 모두 1위)
- **매수 쿨다운**: 동일 종목 25분 내 재매수 차단
- **자금 관리**: 건당 가용잔고 19%, 총 투자 95% 상한 (closing_trade 5종목 기준, core/fund_manager.py)
- **포지션 제한**: 정상 7종목, 약세 3종목, 극약세 0종목 (03-28 멀티버스: 7종목 +280% vs 5종목 +216%)
- **장마감 청산**: 15:00 보유 전 종목 시장가 매도 (15:30은 장 마감, 청산은 30분 전)
- **API Rate Limiting**: 60ms 간격, 서킷 브레이커 연속 실패 시 차단 (api/kis_auth.py)
- **상태 머신**: asyncio.Lock 기반 종목 상태 전이 보호 (core/trading_stock_manager.py)
- **중복 매수 방지**: is_buying 플래그 + 쿨다운 이중 차단
- **성과 게이트**: 최근 20건 승률 < 40% → 매수 차단 (가상 추적으로 자동 해제), 당일 3연패 → 당일 매수 중단
- **분봉 확대 수집 (04-12 추가)**: 15:45 자동 실행, 거래대금 상위 300종목/일 분봉을 minute_candles에 저장 → 시뮬-실거래 후보 풀 격차 해소. 매매 로직 무영향 (상세: [.omc/plans/minute-collection-expansion.md](.omc/plans/minute-collection-expansion.md))

---

## 런타임 아키텍처 (main.py)

### 7개 비동기 태스크
| 태스크 | 함수 | 역할 |
|--------|------|------|
| pre_market | `_pre_market_task()` | NXT 스냅샷 수집 + 리포트 생성 (08:00~09:00) |
| data_collection | `_data_collection_task()` | 실시간 데이터 수집 |
| order_monitoring | `_order_monitoring_task()` | 미체결 주문 모니터링 |
| stock_monitoring | `_stock_monitoring_task()` | 종목 상태 모니터링 |
| trading_decision | `_trading_decision_task()` | **매도** 판단 + 포지션 동기화 (매수 아님!) |
| system_monitoring | `_system_monitoring_task()` | 장중 데이터 업데이트 + **매수** 판단 트리거 |
| telegram | 텔레그램 봇 | 알림 및 명령 수신 |

- 워치독이 크래시된 태스크를 자동 재시작
- 매수/매도 판단이 별도 태스크에서 실행됨에 주의

### 매수 판단 트리거 경로
```
_system_monitoring_task() (매 13~45초)
  → _update_intraday_data()
    → intraday_manager.batch_update_realtime_data()
    → 캔들 완성 시점 (minute % interval == 0, second >= 10)
      → _analyze_buy_decision()
        → trading_decision_engine.analyze_buy_decision()
```

> **주의**: `_trading_decision_task()`는 매도 판단만 담당. 매수는 `_system_monitoring_task()`에서 트리거됨.

---

## 분석 방법

### 봇 실행
```bash
python main.py                    # 자동매매 봇 시작
```

### 실시간 거래 분석
```bash
# 매수 신호
grep "가격위치전략.*매수 신호" logs/trading_YYYYMMDD.log

# 매수 주문 실행
grep "실제 매수 주문 완료" logs/trading_YYYYMMDD.log

# 매도 체결 / 손절 / 익절
grep "매도 완료\|손절\|익절" logs/trading_YYYYMMDD.log

# 스크리너 결과
grep "\[스크리너\]" logs/trading_YYYYMMDD.log

# 서킷브레이커 발동
grep "서킷브레이커" logs/trading_YYYYMMDD.log
```

### 시뮬레이션
```bash
# 스크리너 통합 시뮬레이션 (추천)
python simulate_with_screener.py --start 20250224 --end 20260223

# 데이터 수집 + 시뮬레이션 파이프라인
python collect_and_simulate.py --phase ABCD --start 20250224 --end 20260223
```

---

## 상세 문서 참조

- [DEVELOPMENT.md](DEVELOPMENT.md) - 개발자용 상세 가이드
- [CONFIGURATION.md](CONFIGURATION.md) - 설정 파일 상세 설명
- [README.md](README.md) - 프로젝트 소개 및 설치 방법
- [docs/pre_market_circuit_breaker.md](docs/pre_market_circuit_breaker.md) - 서킷브레이커 상세
- [docs/stock_state_management.md](docs/stock_state_management.md) - 종목 상태 관리
- [docs/telegram_setup.md](docs/telegram_setup.md) - 텔레그램 설정
- [장중_테스트_가이드.md](장중_테스트_가이드.md) - 장중 테스트
