# RoboTrader - Claude 컨텍스트

## Claude 작업 지침

**상세 정보가 필요할 때 참조할 문서**:
- 데이터 흐름, 디버깅, 실시간 vs 시뮬 차이 → `DEVELOPMENT.md` 읽기
- 설정값 변경, 필터 설정, 투자비율 조정 → `CONFIGURATION.md` 읽기
- 분석 명령어, 로그 검색 상세 → `ROBOTRADER_ANALYSIS_GUIDE.md` 읽기

---

## 프로젝트 개요

한국투자증권 KIS API 기반 자동매매 시스템

---

## 현재 활성 전략: 가격 위치 기반 전략 (2026-02-02~)

### 전략 설정 (config/strategy_settings.py)
```python
ACTIVE_STRATEGY = 'price_position'  # 현재 활성화
# ACTIVE_STRATEGY = 'pullback'      # 기존 눌림목 전략
```

### 진입 조건
| 항목 | 설정값 |
|------|--------|
| 시가 대비 | 2% ~ 4% 상승 |
| 거래 시간 | 10:00 ~ 12:00 |
| 거래 요일 | 월/수/금 (화/목 회피) |
| 일 최대 종목 | 5개 |

### 청산 조건
- **손절**: -2.5%
- **익절**: +3.5%

### 시뮬레이션 결과 (2025-09-01 ~ 2026-01-30)
| 항목 | 결과 |
|------|------|
| 총 거래 | 315건 (자본금 제한 적용) |
| 승률 | **59.7%** |
| 월평균 순수익 | **+87만원** (1000만원 기준) |
| 누적 수익률 | +43.5% (5개월) |

### 관련 파일
- `config/strategy_settings.py` - 전략 선택 및 설정
- `core/strategies/price_position_strategy.py` - 전략 클래스
- `simulate_price_position_strategy.py` - 시뮬레이션
- `realistic_simulation.py` - 자본금 제한 시뮬레이션

---

## 기존 전략: 눌림목 캔들패턴 (pullback)

**매수 조건**:
- 주가 상승 중 거래량은 하락 추세
- 이등분선 위에서 조정 (거래량 급감, 봉 크기 축소)
- 급감된 거래량 상회 + 캔들 크기 회복 → 매수

**손절 조건**:
- 이등분선 이탈
- 지지 저점 이탈

**거래량 판단**:
- 기준 거래량: 당일 3분봉 최대 거래량
- 1/4 수준: 매물부담 적음 (양호)
- 1/2 수준: 매도세 발생 (주의)

---

## 현재 시스템 설정

### ML 필터 (config/ml_settings.py)
- **USE_ML_FILTER**: False (비활성화)
- **ML_THRESHOLD**: 0.4 (40%)
- **MODEL_PATH**: ml_model.pkl

### 고급 필터 (config/advanced_filter_settings.py)
- **ENABLED**: True
- **활성화된 필터 (3분봉 기준)**:
  - 연속양봉 >= 1개
  - 가격위치 >= 80%
  - 화요일 회피
  - 시간대-요일 회피 (9시화, 10시화, 11시화, 10시수)
  - 저승률 종목 회피 (101170, 394800)
  - pattern_stages 기반: 상승폭 >= 15%, 하락폭 >= 5%, 지지캔들 = 3개 회피

### 일봉 필터 (config/advanced_filter_settings.py) - 효과 미미
- **ACTIVE_DAILY_PRESET**: 'volume_surge' (활성화됨)
- **분석 결과**: 일봉 필터는 3분봉 필터 대비 효과 미미
- **참고**: 기존 3분봉 필터가 이미 충분히 효과적

### 최적 패턴 필터 (2026-01-31 분석) - 비활성화
- **OPTIMAL_UPTREND_FILTER**: 비활성화 (기존 15% 필터와 중복)
- **OPTIMAL_SUPPORT_FILTER**: 비활성화 (8%만 통과, 너무 엄격)
- **OPTIMAL_DECLINE_FILTER**: 비활성화 (최근 시장에서 역효과)

### 투자 비율 (config/trading_config.json)
- **buy_budget_ratio**: 0.20 (건당 가용잔고의 20%)
- **max_position_ratio**: 0.20 (fund_manager.py)

### 손익비 (config/trading_config.json)
- **stop_loss_ratio**: 0.025 (-2.5%)
- **take_profit_ratio**: 0.035 (+3.5%)
- **use_dynamic_profit_loss**: false

---

## 주요 파일 구조

```
config/
├── trading_config.json          # 거래 설정 (투자비율, 손익비)
├── strategy_settings.py         # 전략 선택 설정
├── ml_settings.py               # ML 필터 설정
├── advanced_filter_settings.py  # 고급 필터 설정

core/
├── trading_decision_engine.py   # 매매 판단 엔진 (980 lines)
├── trade_executor.py            # 매수/매도 실행 로직 (325 lines)
├── intraday_stock_manager.py    # 장중 데이터 관리 (794 lines)
├── historical_data_collector.py # 과거 데이터 수집 (368 lines)
├── realtime_data_updater.py     # 실시간 데이터 갱신 (393 lines)
├── data_quality_checker.py      # 데이터 품질 검증 (171 lines)
├── fund_manager.py              # 자금 관리
├── strategies/                  # 전략 모듈
│   ├── __init__.py
│   └── price_position_strategy.py  # 가격 위치 전략
├── indicators/
│   ├── advanced_filters.py      # 고급 필터 로직
│   └── pullback_candle_pattern.py  # 눌림목 패턴 감지

utils/
├── signal_replay.py             # 시뮬레이션 메인 (2,180 lines)
├── signal_replay_simulation.py  # 시뮬레이션 헬퍼 (394 lines)
├── data_cache.py                # DuckDB 캐시 관리

cache/
└── market_data_v2.duckdb    # 분봉/일봉 캐시 데이터
```

### 리팩토링 이력 (2026-02-02)

대형 파일 분리를 통한 코드 가독성 개선:

| 원본 파일 | 원본 라인 | 현재 라인 | 분리된 헬퍼 |
|-----------|-----------|-----------|-------------|
| trading_decision_engine.py | 1,221 | 980 | trade_executor.py |
| intraday_stock_manager.py | 1,624 | 794 | historical_data_collector.py, realtime_data_updater.py, data_quality_checker.py |
| signal_replay.py | 2,180 | 2,180 | signal_replay_simulation.py (신규 헬퍼) |

**설계 패턴**: Composition (위임) 패턴 사용 - 기존 public API 유지하면서 내부 로직만 헬퍼 클래스로 분리

### DB 관리 개선 (2026-02-03)

데이터베이스 동시성 및 안정성 개선:

| 문제 | 해결 방법 | 파일 |
|------|----------|------|
| DuckDB 동시 쓰기 충돌 | 글로벌 Lock + WAL 모드 | `utils/data_cache.py` |
| SQLite 병렬성 낮음 | WAL 모드 + 30초 타임아웃 | `db/database_manager.py` |
| 손익 계산 일관성 | BEGIN IMMEDIATE 트랜잭션 | `db/database_manager.py` |

**주요 변경사항:**
- `_write_lock`: DuckDB 쓰기 작업 직렬화 (동시 쓰기 오류 방지)
- `PRAGMA journal_mode=WAL`: 동시 읽기/쓰기 성능 향상
- `PRAGMA synchronous=NORMAL`: 성능과 안정성 균형
- `BEGIN IMMEDIATE`: 매도 시 매수 조회→손익 계산→저장 원자성 보장

---

## 분석 방법

### 실시간 거래 분석
```bash
# 종목 선정 시점
grep "종목코드" logs/trading_YYYYMMDD.log | grep "선정 완료"

# 매수 신호
grep "종목코드" logs/trading_YYYYMMDD.log | grep "매수 신호 발생"

# 패턴 상세
grep "종목코드" pattern_data_log/pattern_data_YYYYMMDD.jsonl
```

### 시뮬레이션 분석
```bash
# 고급 필터 적용 시뮬레이션
python batch_signal_replay.py --start 20250901 --end 20260123 --advanced-filter

# 일봉 필터 전략별 비교 분석
python compare_daily_filters.py
```

**시뮬레이션 결과 파일**:
- 순수 패턴: `signal_replay_log/signal_new2_replay_YYYYMMDD_9_00_0.txt`
- ML 적용: `signal_replay_log_ml/signal_ml_replay_YYYYMMDD_9_00_0.txt`
- 일봉 필터 비교: `daily_filter_comparison_report.txt`

---

## 핵심 개념

### 3분봉 completion_time
- 라벨 시간 + 3분 = 완성 시간
- 예: 10:42 캔들 → 10:45:00 완성

### selection_date 필터링
- **시뮬레이션에서만 적용** (실시간은 없음)
- completion_time < selection_date → 신호 차단

### 데이터 차이
- 실시간: KIS API (지속 업데이트)
- 캐시: DuckDB (확정값)
- 같은 시간대 캔들도 값이 다를 수 있음

---

---

## 필터 효과 분석 결과 (2026-01-31)

### 전체 기간 비교 (2025-09-01 ~ 2026-01-30)
| 구분 | 거래수 | 승률 | 평균수익 |
|------|--------|------|----------|
| 순수 패턴 | 612 | 45.1% | +0.08% |
| 3분봉 필터 | 291 | 53.6% | +0.61% |

### 결론
- **3분봉 필터**: 효과적 (승률 +8.5%p, 거래 53% 감소)
- **일봉 필터**: 효과 미미
- **신규 최적 패턴 필터**: 효과 없음 (기존 필터와 중복 또는 역효과)

---

## 상세 문서 참조

- [DEVELOPMENT.md](DEVELOPMENT.md) - 개발자용 상세 가이드 (데이터 흐름, 디버깅)
- [CONFIGURATION.md](CONFIGURATION.md) - 설정 파일 상세 설명
- [README.md](README.md) - 프로젝트 소개 및 설치 방법
- [docs/trading_logic_documentation.md](docs/trading_logic_documentation.md) - 매매 로직 상세
