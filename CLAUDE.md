# RoboTrader - Claude 컨텍스트

## Claude 작업 지침

**상세 정보가 필요할 때 참조할 문서**:
- 데이터 흐름, 디버깅, 실시간 vs 시뮬 차이 → `DEVELOPMENT.md` 읽기
- 설정값 변경, 필터 설정, 투자비율 조정 → `CONFIGURATION.md` 읽기
- 분석 명령어, 로그 검색 상세 → `ROBOTRADER_ANALYSIS_GUIDE.md` 읽기

---

## 프로젝트 개요

한국투자증권 KIS API 기반 **눌림목 캔들패턴** 자동매매 시스템

## 핵심 전략: 눌림목 캔들패턴

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

### 일봉 필터 (config/advanced_filter_settings.py)
- **ACTIVE_DAILY_PRESET**: None (기본값: 일봉 필터 미사용)
- **사용 가능한 프리셋**:
  - `'volume_surge'`: 최고 수익 전략 (승률 52.7%, 수익 200만원) ⭐ 추천
  - `'consecutive_2days'`: 최고 승률 전략 (승률 53.3%, 수익 185만원)
  - `'prev_day_up'`: 거래 빈도 유지 (승률 52.7%, 수익 184만원)
  - `'consecutive_1day'`: 균형잡힌 선택 (승률 52.8%, 수익 182만원)
  - `'balanced'`: 복합 조건 (승률 52.5%, 수익 173만원)
- **필터 없을 때**: 승률 49.6%, 수익 144만원 (비추천)
- **빠른 사용법**: [일봉필터_사용법.md](일봉필터_사용법.md) 참조

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
├── trading_config.json      # 거래 설정 (투자비율, 손익비)
├── ml_settings.py           # ML 필터 설정
├── advanced_filter_settings.py  # 고급 필터 설정

core/
├── trading_decision_engine.py   # 매매 판단 엔진
├── fund_manager.py              # 자금 관리
├── indicators/
│   ├── advanced_filters.py      # 고급 필터 로직
│   └── pullback_candle_pattern.py  # 눌림목 패턴 감지

utils/
├── signal_replay.py         # 시뮬레이션 (순수 패턴)
├── data_cache.py            # DuckDB 캐시 관리

cache/
└── market_data_v2.duckdb    # 분봉/일봉 캐시 데이터
```

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

## 상세 문서 참조

- [DEVELOPMENT.md](DEVELOPMENT.md) - 개발자용 상세 가이드 (데이터 흐름, 디버깅)
- [CONFIGURATION.md](CONFIGURATION.md) - 설정 파일 상세 설명
- [README.md](README.md) - 프로젝트 소개 및 설치 방법
- [docs/trading_logic_documentation.md](docs/trading_logic_documentation.md) - 매매 로직 상세
- [일봉필터_사용법.md](일봉필터_사용법.md) - 일봉 필터 빠른 시작 가이드 (1줄 요약)
- [docs/daily_filter_usage.md](docs/daily_filter_usage.md) - 일봉 필터 상세 사용 가이드
