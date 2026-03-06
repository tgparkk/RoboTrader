# RoboTrader - 주식 단타 거래 시스템

한국투자증권 KIS API를 활용한 자동 주식 단타 거래 시스템입니다.

## 주요 기능

### 🔄 실시간 데이터 수집
- 30초/1분 주기로 OHLCV 데이터 수집
- 후보 종목들의 가격 변동 실시간 모니터링
- 비동기 처리로 다중 종목 동시 추적

### 📊 자동 매매 시스템
- 설정 가능한 매매 전략
- 실시간 매수/매도 신호 생성
- 자동 주문 실행 및 관리

### 🛡️ 리스크 관리
- 손절/익절 자동 실행
- 계좌 잔고 대비 투자 한도 관리
- 동시 보유 종목 수 제한

### 📋 주문 관리
- 미체결 주문 자동 모니터링
- 타임아웃 시 자동 취소
- 가격 변동 시 자동 정정

### 📱 텔레그램 모니터링
- 실시간 거래 상황 알림
- 주문 실행/체결 알림
- 매매 신호 감지 알림
- 원격 명령어 지원 (/status, /positions, /orders)

## 시스템 구조

```
RoboTrader/
├── api/                    # KIS API 연동
│   ├── kis_api_manager.py  # API 통합 관리자
│   ├── kis_auth.py         # 인증 관리
│   ├── kis_account_api.py  # 계좌 조회
│   ├── kis_market_api.py   # 시장 데이터
│   └── kis_order_api.py    # 주문 처리
├── core/                   # 핵심 비즈니스 로직
│   ├── models.py           # 데이터 모델
│   ├── data_collector.py   # 실시간 데이터 수집
│   ├── trading_decision_engine.py  # 매매 판단 엔진
│   ├── trade_executor.py   # 매수/매도 실행
│   ├── stock_screener.py   # 실시간 종목 스크리너
│   ├── pre_market_analyzer.py  # 프리마켓 분석 & 서킷브레이커
│   ├── order_manager.py    # 주문 관리
│   └── strategies/
│       └── price_position_strategy.py  # 가격 위치 전략
├── utils/                  # 유틸리티
│   ├── data_cache.py       # PostgreSQL 데이터 캐시
│   ├── logger.py           # 로깅 시스템
│   ├── korean_time.py      # 한국 시간 처리
│   └── telegram/           # 텔레그램 모듈
│       └── telegram_notifier.py
├── config/                 # 설정 파일
│   ├── strategy_settings.py  # 전략/스크리너 설정
│   ├── trading_config.json   # 거래 설정 (투자비율, 손익비)
│   └── key.ini               # API 키 (git 제외)
├── db/
│   └── database_manager.py # PostgreSQL 데이터 관리
├── main.py                # 메인 실행 파일
└── requirements.txt       # 의존성 패키지
```

## 설치 및 실행

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. API 키 및 텔레그램 설정
`config/key.ini` 파일에 다음을 설정하세요:
- 한국투자증권 API 키
- 텔레그램 봇 토큰 (선택사항)
- 텔레그램 Chat ID (선택사항)

상세한 텔레그램 설정은 `docs/telegram_setup.md` 참고

### 3. 거래 설정
`config/trading_config.json`에서 거래 설정을 조정하세요:
- 후보 종목 리스트
- 리스크 관리 설정
- 주문 관리 설정

### 4. 실행
```bash
python main.py
```

## 주요 클래스

### DayTradingBot
- 전체 시스템 관리
- 일일 거래 사이클 실행
- 비동기 태스크 관리

### RealTimeDataCollector
- 실시간 OHLCV 데이터 수집
- 후보 종목 관리
- 데이터 저장 및 제공

### OrderManager
- 주문 실행 및 관리
- 미체결 주문 모니터링
- 자동 정정/취소 처리

### KISAPIManager
- KIS API 통합 관리
- 인증 및 API 호출
- 오류 처리 및 재시도

## 안전 기능

### 🛡️ 프리마켓 분석 & 서킷브레이커
장전 NXT 프리마켓 데이터(08:00~08:55)로 시장 심리를 판단하여 위험 시 매수를 자동 중단합니다.
- 전일 지수 급락(-2%) 시 매수 완전 중단
- 전일 하락(-1%) + NXT 갭다운(-0.5%) 복합 조건
- NXT 심리 극약세(score <= -0.7) 시 전일 지수 무관 매수 중단
- 강한 반등(NXT 갭 +3%) 시 절반 투입으로 해제

상세 문서: [`docs/pre_market_circuit_breaker.md`](docs/pre_market_circuit_breaker.md)

### 🔒 리스크 제한
- 최대 투자 비율 제한
- 일일 최대 손실 한도
- 종목별 손절/익절 자동 실행

### 📡 모니터링
- 실시간 시스템 상태 로깅
- API 호출 통계 추적
- 주문 실행 내역 기록

### ⚠️ 오류 처리
- API 호출 실패 시 자동 재시도
- 네트워크 오류 대응
- 예외 상황 로깅

## 주의사항

1. **모의투자 환경에서 충분한 테스트 후 실투자 적용**
2. **API 호출 한도 준수 (분당 최대 호출 수 확인)**
3. **장중에만 실행 (09:00~15:30)**
4. **충분한 계좌 잔고 확보**

## 라이선스

이 프로젝트는 교육 및 연구 목적으로 제작되었습니다.
실제 투자에 사용 시 발생하는 손실에 대해 책임지지 않습니다.

## ML 필터 (현재 비활성)

ML 필터 기능이 구현되어 있으나 현재 비활성 상태입니다 (`USE_ML_FILTER = False`).
관련 파일: `config/ml_settings.py`, `archive/` 디렉토리의 ML 관련 문서 참조.

---

## 데이터 저장소

**PostgreSQL 테이블**:
- `minute_candles`: 분봉 데이터 (PK: stock_code, trade_date, idx)
- `daily_candles`: 일봉 데이터 (PK: stock_code, stck_bsop_date) — 지수(KS11, KQ11) 포함

**파일 기반 데이터**:
```
RoboTrader/
├── stock_list.json                # KOSPI+KOSDAQ 종목 리스트 (2472종목)
└── logs/                          # 거래 로그
    └── trading_YYYYMMDD.log
```