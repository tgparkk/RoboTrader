# 분봉 수집 확대 플랜

**목표**: 매일 장 마감 후 거래대금 상위 300종목의 당일 분봉을 `minute_candles`에 저장하여 시뮬-실거래 괴리 해소.

**결정된 옵션**:
- **Q1 일상 운영**: 옵션 B (KIS 거래량순위 API) — 전문가 토론(2:1) 결과
- **Q2 수집 종목 수**: 300종목
- **Q3 백필 범위**: 최근 100거래일 (주말 1회, pykrx 보조)
- **Q4 트리거 시각**: 15:45

## 전문가 토론 요약
- 시스템 신뢰성: **B 지지** (pykrx 크롤링 리스크 회피)
- 실무 운영자: **B 지지** (1인 운영 현실성, 단일 API 디버깅)
- 데이터 엔지니어: C 지지 (백필 용이)
- **최종 합의: B(일상) + pykrx(백필 전용, 주말 일회성)**

## 구현 단계

### 1단계 MVP (Day 1)
- `core/expanded_minute_collector.py` 신규
  - `select_top_stocks_via_volume_rank(top_n=300)` — KIS 거래량순위 API 다회 호출
  - `collect_minute_candles(stock_codes, date)` — get_full_trading_day_data 재활용
  - `run(date, top_n=300)` 엔트리포인트
- `main.py` `_system_monitoring_task`에 15:45 트리거 추가 (플래그 기반 1회 실행)
- `scripts/collect_expanded_minutes.py` CLI (수동 실행용)

### 2단계 안정성 (Day 2)
- Progress 파일 (`.omc/state/minute_collection_{YYYYMMDD}.json`)
- 당일 1회 자동 재시도
- 연속 실패 10건 → 1분 대기, 30건 → 중단
- 텔레그램 완료/실패 알림

### 3단계 백필 (주말)
- `scripts/backfill_minutes_pykrx.py` — pykrx로 최근 100거래일 × 상위 300종목
- 예상 소요: ~11시간 (주말 야간 실행)
- progress 파일로 재개 가능

## 리스크
- DB 용량: 현재 616MB → 100일 백필 후 ~1.8GB, 1년 운영 ~5GB (PostgreSQL 문제 없음)
- 기존 봇 영향 0: 15:45 실행 (매매 종료 후), try/except 감싸기
- KIS API 장애: 기존 40종목 수집과 독립, 매매 로직 무영향
