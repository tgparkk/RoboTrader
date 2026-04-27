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

## ⚠️ 현재 상태 (2026-04-27): macd_cross 실거래 (단일 운영)

```python
# config/strategy_settings.py
ACTIVE_STRATEGY = 'macd_cross'                  # 실거래 primary
PAPER_STRATEGY  = None                          # 페이퍼 종료

# macd_cross 실거래 (Phase 1~4 완료, 2026-04-27)
MacdCross.FAST_PERIOD = 14
MacdCross.SLOW_PERIOD = 34
MacdCross.SIGNAL_PERIOD = 12
MacdCross.ENTRY_HHMM_MIN = 1431                 # 백테스트 next_bar_open 정렬
MacdCross.ENTRY_HHMM_MAX = 1500
MacdCross.HOLD_DAYS = 2                         # KRX 영업일 기준
MacdCross.BUY_BUDGET_RATIO = 0.20               # 자본 1/N (실 잔고 × 20%)
MacdCross.MAX_DAILY_POSITIONS = 5
MacdCross.UNIVERSE_TOP_N = 30
MacdCross.VIRTUAL_ONLY = False                  # 실 주문 활성
MacdCross.APPLY_LIVE_OVERLAY = False            # G1 원칙 (라이브 필터 미적용)
```

설계서: `docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md`

### 운영 정책 (2026-04-27 결정)

| 항목 | 결정 |
|------|------|
| 자금 사이즈 | (가용잔고) / (남은 슬롯) 동적 분할, 최대 5종목 |
| 주문 유형 | 시장가 (14:31:00 분봉 시작) |
| 진입 가드 | 백테스트 가드만 (1일 1회·5포지션·거래량). SL/TP·25분 쿨다운 미적용 |
| 위험 오버레이 | 전일 -3% 서킷브레이커 만 inherit (자본 보호 absolute) |
| 청산 | D+2 영업일 09:01~05 시장가 + EOD(15:00) 안전망 |
| 폴백 | 없음. 킬 스위치 발동 시 ACTIVE_STRATEGY 동작 정지 |
| 킬 스위치 | 누적 -5% 또는 5연속 손실 → `config/macd_cross_kill_switch.json` 디스크 저장 → 매수 영구 정지. 복구 = 파일 삭제 후 봇 재시작 |

### 백테스트 OOS 성과 (Phase 3 Stage 2)
- Calmar 54.16, Return +11.66%, MDD 1.99%, Win% 61.1%, 36 trades, 열화 ratio 0.62
- 4-pillar audit: 데이터 무결성·일반화·universe 안정성 통과. fragility (top1=56.8%) ⚠️ 잔존.

### 구조

- **시그널 모듈**: `core/strategies/macd_cross_signal.py` (백테스트 공유)
- **라이브 어댑터**: `core/strategies/macd_cross_strategy.py`
- **KPI 모듈**: `core/strategies/macd_cross_kpi.py`
- **매수 경로**: `main.py::_evaluate_macd_cross_window` (virtual/real dispatcher)
- **매도 경로**: `main.py::_macd_cross_exit_dispatcher` → `_macd_cross_paper_exit_task` 또는 `_macd_cross_live_exit_task`
- **킬 스위치**: `main.py::_check_macd_cross_kill_switch_thresholds` (EOD 호출)
- **포지션 동기화**: `main.py::emergency_sync_positions` 가 strategy_tag 복원

### 운영 가이드

- **실거래 전환 명령**: `MacdCross.VIRTUAL_ONLY = False` + 봇 재시작
- **가상 회귀**: `MacdCross.VIRTUAL_ONLY = True` + 봇 재시작
- **킬 스위치 복구**: `D:/GIT/RoboTrader/config/macd_cross_kill_switch.json` 삭제 후 봇 재시작
- **자동 실행**: `D:/GIT/run_all_robotraders.bat` 의 RoboTrader 라인 활성화

---

## 폐기된 전략

- **weighted_score** (2026-04-27 폐기): macd_cross 로 대체. 실거래 전환 1주차 안정 후 코드 완전 삭제 예정 (`WeightedScore` 클래스, `weighted_score_*.py`, `weighted_score_params.json`, 분기 로직).
- **price_position** (2026-04-21 삭제): `core/strategies/price_position_strategy.py` + `class PricePosition` + ATR 동적 TP/SL dead code 모두 제거.

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
