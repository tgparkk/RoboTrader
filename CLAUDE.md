# RoboTrader - Claude 컨텍스트

## Claude 작업 지침

**상세 정보가 필요할 때 참조할 문서**:
- 데이터 흐름, 디버깅, 실시간 vs 시뮬 차이 → `DEVELOPMENT.md` 읽기
- 설정값 변경, 필터 설정, 투자비율 조정 → `CONFIGURATION.md` 읽기

---

## 프로젝트 개요

한국투자증권 KIS API 기반 자동매매 시스템

**데이터 저장**: PostgreSQL (분봉: `minute_candles`, 일봉: `daily_candles`)
**종목 발굴**: 코드 기반 실시간 스크리너 (KOSPI + KOSDAQ 2472종목)

---

## 현재 활성 전략: 가격 위치 기반 전략 (price_position)

### 전략 설정 (config/strategy_settings.py)
```python
ACTIVE_STRATEGY = 'price_position'
```

### 진입 조건
| 항목 | 설정값 |
|------|--------|
| 시가 대비 | 1% ~ 3% 상승 |
| 거래 시간 | 9:00 ~ 12:00 |
| 거래 요일 | 월~금 전체 |
| 동시 보유 최대 | 5종목 (청산 시 새 매수 가능) |
| 고급 필터 | 변동성 < 1.2%, 모멘텀 < +2.0% |

### 청산 조건
- **손절**: -5.0%
- **익절**: +6.0%

### 종목 발굴: 실시간 스크리너 (core/stock_screener.py)
- 2분 주기로 KOSPI+KOSDAQ 거래량순위 API 스캔 (4회 호출)
- 3단계 필터: 기본필터 → 정밀필터(시가대비, 갭) → 점수순 최대 5개 추가
- 설정: `config/strategy_settings.py` > `Screener` 클래스

### 관련 파일
- `config/strategy_settings.py` - 전략/스크리너 설정
- `core/strategies/price_position_strategy.py` - 전략 클래스
- `core/stock_screener.py` - 실시간 종목 스크리너
- `simulate_with_screener.py` - 스크리너 통합 시뮬레이션

---

## 현재 시스템 설정

### 투자 비율 (config/trading_config.json)
- **buy_budget_ratio**: 0.20 (건당 가용잔고의 20%)

### 손익비 (config/trading_config.json)
- **stop_loss_ratio**: 0.05 (-5.0%)
- **take_profit_ratio**: 0.06 (+6.0%)

### 서킷브레이커 (config/strategy_settings.py > PreMarket)
- 전일 KOSPI/KOSDAQ -2% → 매수 완전 중단
- 전일 -1% + NXT 갭 -0.5% → 매수 완전 중단
- NXT sentiment <= -0.7 → 매수 완전 중단
- 상세: [docs/pre_market_circuit_breaker.md](docs/pre_market_circuit_breaker.md)

---

## 주요 파일 구조

```
config/
├── trading_config.json          # 거래 설정 (투자비율, 손익비)
├── strategy_settings.py         # 전략/스크리너/프리마켓 설정

core/
├── trading_decision_engine.py   # 매매 판단 엔진
├── trade_executor.py            # 매수/매도 실행 로직
├── order_manager.py             # 주문 관리
├── stock_screener.py            # 실시간 종목 스크리너
├── trading_stock_manager.py     # 종목 상태 관리
├── intraday_stock_manager.py    # 장중 데이터 관리
├── pre_market_analyzer.py       # 프리마켓 분석 & 서킷브레이커
├── post_market_data_saver.py    # 장 마감 데이터 저장
├── fund_manager.py              # 자금 관리
├── strategies/
│   └── price_position_strategy.py  # 가격 위치 전략

utils/
├── data_cache.py               # PostgreSQL 데이터 캐시

db/
└── database_manager.py         # PostgreSQL 데이터 관리
```

---

## 분석 방법

### 실시간 거래 분석
```bash
# 매수 신호
grep "가격위치전략.*매수 신호" logs/trading_YYYYMMDD.log

# 거래 기록 확인
grep "거래 기록 추가" logs/trading_YYYYMMDD.log

# 스크리너 결과
grep "\[스크리너\]" logs/trading_YYYYMMDD.log
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
