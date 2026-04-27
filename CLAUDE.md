# RoboTrader - Claude 컨텍스트

한국투자증권 KIS API 기반 자동매매 시스템.

---

## 현재 상태 (2026-04-27): macd_cross 단일 실거래 운영

- ACTIVE_STRATEGY = 'macd_cross', PAPER_STRATEGY = None
- 5종목 동시 보유, 자본 1/N 동적 분할, 시장가 14:31 진입, D+2 영업일 청산
- 안전망: 전일 -3% 서킷브레이커 + 킬 스위치 (누적 -5% / 5연패)
- 폐기 전략: weighted_score / closing_trade / pullback / price_position

→ 상세 운영 정책·구조·명령: [docs/macd_cross_operation.md](docs/macd_cross_operation.md)

---

## 데이터 / 종목

**PostgreSQL** (port 5433, DB: `robotrader`)
- 캐시: `minute_candles`, `daily_candles` (utils/data_cache.py)
- 거래: `candidate_stocks`, `real_trading_records`, `virtual_trading_records` (db/database_manager.py)
- 시장: `nxt_snapshots` (NXT 센티먼트)
- DB 접속 정보: `config/settings.py`

**종목 발굴**: 코드 기반 실시간 스크리너 (KOSPI + KOSDAQ 2472종목). macd_cross 는 자체 universe (top 30 거래대금) 만 사용.

---

## 주요 파일 구조

```
config/
  trading_config.json          # 거래 설정 (수수료 등)
  strategy_settings.py         # 전략/스크리너/프리마켓 설정 (MacdCross 클래스 단일)
  market_hours.py              # 장 시간 (EOD 15:00, 특별일 시프트)
  settings.py                  # DB 접속 정보
  macd_cross_kill_switch.json  # 킬스위치 상태 (존재=정지)

api/
  kis_*.py                     # KIS API 인증/주문/차트/시장/계좌

core/
  models.py                    # StockState, TradingStock, TradingConfig
  trading_decision_engine.py   # 매매 판단 엔진
  trade_executor.py            # 주문 실행
  order_manager.py             # 주문 관리 (미체결, 시장가)
  stock_screener.py            # 실시간 스크리너 + macd_cross universe
  trading_stock_manager.py     # 종목 상태 머신 (asyncio.Lock)
  intraday_stock_manager.py    # 장중 분봉 관리
  pre_market_analyzer.py       # 프리마켓 + 서킷브레이커
  fund_manager.py              # 자금 관리
  virtual_trading_manager.py   # 가상매매
  telegram_integration.py      # 텔레그램 알림
  strategies/
    macd_cross_signal.py       # 시그널 (백테스트 공유)
    macd_cross_strategy.py     # 라이브 어댑터
    macd_cross_kpi.py          # KPI 집계

db/database_manager.py         # PG 데이터 관리
utils/                         # data_cache, korean_time
```

---

## 안전장치

| 항목 | 동작 |
|------|------|
| 서킷브레이커 | 전일 KOSPI/KOSDAQ -3% → macd_cross 매수 차단 |
| 킬 스위치 | 누적 -5% 또는 5연속 손실 → ACTIVE_STRATEGY 정지 (디스크 저장) |
| 장마감 청산 | 15:00 보유 종목 시장가 매도 (단, macd_cross D+2 미도달은 보호) |
| 매수 쿨다운 | 동일 종목 25분 내 재매수 차단 (macd_cross 는 미적용 — 1일 1회 가드) |
| API Rate Limiting | 60ms 간격, 연속 실패 시 차단 |
| 상태 머신 | asyncio.Lock 기반 종목 상태 전이 보호 |
| 중복 매수 방지 | is_buying 플래그 + 쿨다운 이중 차단 |

→ 서킷브레이커 상세: [docs/pre_market_circuit_breaker.md](docs/pre_market_circuit_breaker.md)

---

## 런타임 아키텍처 (main.py)

### 6개 비동기 태스크
| 태스크 | 함수 | 역할 |
|--------|------|------|
| pre_market | `_pre_market_task()` | NXT 스냅샷 + 리포트 (08:00~09:00) |
| data_collection | `_data_collection_task()` | 실시간 데이터 수집 |
| order_monitoring | `_order_monitoring_task()` | 미체결 모니터링 |
| stock_monitoring | `trading_manager.start_monitoring` | 종목 상태 모니터링 |
| trading_decision | `_trading_decision_task()` | **매도** 판단 + 포지션 동기화 |
| system_monitoring | `_system_monitoring_task()` | 장중 데이터 + **매수** 트리거 (`_evaluate_macd_cross_window`) |
| telegram | 텔레그램 봇 | 알림 / 명령 |

워치독이 크래시 태스크 자동 재시작.

### 매수 트리거 경로 (macd_cross)
`_system_monitoring_task` (13~45초) → `_update_intraday_data` → 캔들 완성 시점 (분봉마감 + 5초) → `_evaluate_macd_cross_window` (시그널 hit 시 시장가 매수)

### 매도 트리거 경로 (macd_cross)
- D+2 morning (09:01~05): `_macd_cross_exit_dispatcher` → `_macd_cross_live_exit_task`
- EOD (15:00): 같은 dispatcher 호출 (안전망)

> **주의**: `_trading_decision_task` 는 매도 판단만 담당. macd_cross 는 시간기반 청산이라 dispatcher 가 별도 처리.

---

## 봇 운영 명령어

```bash
# 봇 시작
python main.py

# 봇 정지
taskkill //PID $(cat bot.pid) //F

# 일일 거래 분석
grep -E "매수 주문|시장가 청산|서킷브레이커|killswitch" logs/trading_YYYYMMDD.log
grep "macd_cross" logs/trading_YYYYMMDD.log | grep -v DEBUG

# 테스트
python -m pytest tests/integration/test_macd_cross_*.py    # macd_cross 전용 (13건)
python -m pytest tests/                                     # 전체 (217건)
```

---

## 상세 문서 참조

**필독** (작업 시작 전):
- [docs/macd_cross_operation.md](docs/macd_cross_operation.md) — 현재 운영 정책·구조·명령어
- [docs/development_notes.md](docs/development_notes.md) — DB·봇 lifecycle·dispatcher gotcha

**도메인 상세**:
- [DEVELOPMENT.md](DEVELOPMENT.md) — 데이터 흐름·디버깅 가이드
- [CONFIGURATION.md](CONFIGURATION.md) — 설정 파일 상세
- [README.md](README.md) — 설치 / 프로젝트 소개
- [docs/pre_market_circuit_breaker.md](docs/pre_market_circuit_breaker.md) — 서킷브레이커
- [docs/stock_state_management.md](docs/stock_state_management.md) — 종목 상태 머신
- [docs/telegram_setup.md](docs/telegram_setup.md) — 텔레그램 설정
- [docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md](docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md) — 설계서
