# RoboTrader 설정 가이드

## 설정 파일 구조

```
config/
├── trading_config.json          # 거래 설정 (투자비율, 손익비, 리스크)
├── strategy_settings.py         # 전략/스크리너/프리마켓 설정
├── ml_settings.py               # ML 필터 설정 (현재 비활성)
├── advanced_filter_settings.py  # 고급 필터 설정 (pullback 전략용)
├── market_hours.py              # 장 시간 설정 (EOD 청산 15:00, 특별일 시프트)
├── settings.py                  # 일반 설정 (DB 접속 정보)
├── dynamic_profit_loss_config.py # 동적 손익비 설정 (현재 비활성)
└── key.ini                      # API 키 (git 제외)
```

---

## 1. trading_config.json

### 현재 설정
```json
{
  "data_collection": {
    "interval_seconds": 30,            // 데이터 수집 주기
    "candidate_stocks": []             // 수동 후보 종목 (비어있으면 스크리너 사용)
  },
  "order_management": {
    "buy_timeout_seconds": 300,        // 매수 주문 타임아웃 (5분)
    "sell_timeout_seconds": 180,       // 매도 주문 타임아웃 (3분)
    "max_adjustments": 3,              // 주문 정정 최대 횟수
    "adjustment_threshold_percent": 0.5, // 정정 임계값 (%)
    "market_order_threshold_percent": 2.0, // 시장가 전환 임계값 (%)
    "buy_budget_ratio": 0.20,          // 건당 투자 비율 (20% = 1/5)
    "buy_cooldown_minutes": 25         // 동일 종목 재매수 대기
  },
  "risk_management": {
    "max_position_count": 20,          // 최대 보유 종목 수
    "max_position_ratio": 0.3,         // 종목당 최대 비율
    "stop_loss_ratio": 0.05,           // 손절 (-5.0%)
    "take_profit_ratio": 0.06,         // 익절 (+6.0%)
    "max_daily_loss": 0.1,             // 일일 최대 손실 (10%)
    "use_dynamic_profit_loss": false   // 동적 손익비 (비활성화)
  },
  "fee": {
    "tax_rate": 0.0018,                // 매도 세금 (0.18%)
    "commission_rate": 0.00014         // 수수료 (0.014%)
  },
  "logging": {
    "level": "INFO",
    "file_retention_days": 30,
    "enable_pattern_logging": true     // 패턴 상세 로깅
  }
}
```

> **참고**: `strategy` 섹션(`simple_momentum`)과 `duplicate_signal_prevention` 섹션은 레거시 설정으로 현재 코드에서 미참조. 실제 전략은 `strategy_settings.py`에서 관리.

### 투자 비율 권장값

| 비율 | 건당 투자금 (1100만 기준) | 특징 |
|------|--------------------------|------|
| 1/3 (0.33) | 367만원 | 수익 최대화, MDD 높음 |
| **1/4 (0.25)** | 275만원 | **수익/리스크 최적** |
| **1/5 (0.20)** | 220만원 | **균형적 선택** (현재) |
| 1/11 (0.09) | 100만원 | 안정적, 수익 제한 |

---

## 2. ml_settings.py

### 클래스: MLSettings
```python
class MLSettings:
    USE_ML_FILTER = False      # ML 필터 사용 여부
    MODEL_PATH = "ml_model.pkl"  # 모델 파일
    ML_THRESHOLD = 0.4         # 임계값 (40%)
    ON_ML_ERROR_PASS_SIGNAL = True  # 에러시 신호 통과
```

### ML 필터 활성화/비활성화
```python
# 활성화
USE_ML_FILTER = True

# 비활성화 (현재)
USE_ML_FILTER = False
```

---

## 3. advanced_filter_settings.py (pullback 전략 전용)

> **참고**: 현재 활성 전략은 `price_position`이며, 이 필터들은 pullback 전략에서만 사용됩니다.
> price_position 전략의 필터는 `strategy_settings.py > PricePosition` 클래스를 참조하세요.

### 마스터 스위치
```python
ENABLED = True  # False면 모든 고급 필터 비활성화
```

---

## 4. fund_manager.py

### 주요 설정
```python
class FundManager:
    max_position_ratio = 0.20      # 종목당 최대 투자 비율
    max_total_investment_ratio = 0.9  # 전체 자금 대비 최대 투자 비율
```

**주의**: `max_position_ratio`는 `trading_config.json`의 `buy_budget_ratio`와 동일하게 유지

---

## 5. 동적 손익비 (비활성화)

### 상태
- **use_dynamic_profit_loss**: false (현재 비활성화)
- **구현 완료**: 실거래 코드 통합 100% 완료

### 활성화 방법
```json
// trading_config.json
{
  "risk_management": {
    "use_dynamic_profit_loss": true  // true로 변경
  }
}
```

### 관련 문서
- [archive/docs/README_DYNAMIC_PROFIT_LOSS.md](archive/docs/README_DYNAMIC_PROFIT_LOSS.md)
- [archive/docs/QUICK_START_동적손익비.md](archive/docs/QUICK_START_동적손익비.md)

---

## 6. strategy_settings.py - 전략 & 스크리너 & 프리마켓 설정

### 가격 위치 전략 (PricePosition) - 진입 조건
```python
class PricePosition:
    CANDLE_INTERVAL = 1              # 1분봉
    MIN_PCT_FROM_OPEN = 1.0          # 시가 대비 최소 상승률 (%)
    MAX_PCT_FROM_OPEN = 3.0          # 시가 대비 최대 상승률 (%)
    ENTRY_START_HOUR = 9             # 진입 시작 (9시)
    ENTRY_END_HOUR = 12              # 진입 종료 (12시)
    MAX_PRE_VOLATILITY = 1.2         # 변동성 상한 (%)
    MAX_PRE20_MOMENTUM = 2.0         # 모멘텀 상한 (%)
    MAX_DAILY_POSITIONS = 5          # 동시 보유 최대
```

> **주의**: 스크리너 Phase 3 필터(0.8~4.0%)는 후보 종목 발굴용이고,
> PricePosition 진입 조건(1.0~3.0%)은 실제 매수 판단용입니다. 범위가 다릅니다.

### 실시간 종목 스크리너 (Screener)
```python
class Screener:
    ENABLED = True                    # 스크리너 사용 여부
    SCAN_INTERVAL_SECONDS = 120       # 스캔 주기 (2분)
    SCAN_START_HOUR = 9               # 9:05부터
    SCAN_START_MINUTE = 5
    SCAN_END_HOUR = 11                # 11:50까지
    SCAN_END_MINUTE = 50

    # 기본 필터 (거래량순위 API 기반)
    MIN_CHANGE_RATE = 0.5             # 최소 등락률 (%)
    MAX_CHANGE_RATE = 5.0             # 최대 등락률 (%)
    MIN_PRICE = 5000                  # 최소 가격 (원)
    MAX_PRICE = 500000                # 최대 가격 (원)
    MIN_TRADING_AMOUNT = 1_000_000_000  # 최소 거래대금 (10억)

    # 정밀 필터 (현재가 API 기반)
    MIN_PCT_FROM_OPEN = 0.8           # 시가 대비 최소 상승률 (%)
    MAX_PCT_FROM_OPEN = 4.0           # 시가 대비 최대 상승률 (%)
    MAX_GAP_PCT = 3.0                 # 시가 vs 전일종가 갭 최대 (%)
```

### 스크리너 3단계 파이프라인
1. **Phase 1**: KOSPI+KOSDAQ 거래량순위 API (4회 호출) → ~80-100개 후보
2. **Phase 2**: 기본 필터 (등락률, 가격, 거래대금) → ~20-30개
3. **Phase 3**: 현재가 API로 정밀 검증 (시가대비, 갭) → 최대 5개 추가

### 프리마켓 & 서킷브레이커 (PreMarket)
```python
class PreMarket:
    ENABLED = True
    SNAPSHOT_INTERVAL_SECONDS = 300   # NXT 스냅샷 5분 간격
    MAX_BELLWETHER_STOCKS = 30        # 모니터링 대표 종목 수

    # NXT 심리 판단 임계값 (5단계)
    BEARISH_THRESHOLD = -0.3         # 약세 → 3종목, 손절3%/익절4%
    VERY_BEARISH_THRESHOLD = -0.7    # 강약세 → 3종목, 손절3%/익절4% (매수 허용)
    EXTREME_BEARISH_THRESHOLD = -0.9 # 극약세 → 매수 완전 중단 (0종목)
    BULLISH_THRESHOLD = 0.3          # 강세 → 정상 5종목

    # 약세장 파라미터
    BEARISH_MAX_POSITIONS = 3
    BEARISH_STOP_LOSS_RATIO = 0.03   # 5% → 3%
    BEARISH_TAKE_PROFIT_RATIO = 0.04 # 6% → 4%

    # 강약세장 파라미터 (-0.7 ~ -0.9)
    VERY_BEARISH_MAX_POSITIONS = 3
    VERY_BEARISH_STOP_LOSS_RATIO = 0.03
    VERY_BEARISH_TAKE_PROFIT_RATIO = 0.04

    # 극약세장 (<= -0.9)
    EXTREME_BEARISH_MAX_POSITIONS = 0

    # 서킷브레이커 (전일 지수 기반)
    CIRCUIT_BREAKER_PREV_DAY_PCT = -3.0          # 조건1: 전일 -3% → 매수 중단
    PREV_DAY_DECLINE_THRESHOLD = -1.0            # 조건1b: 전일 -1% → 손절 축소
    PREV_DAY_DECLINE_STOP_LOSS_RATIO = 0.03      # 조건1b: 손절 3%
    PREV_DAY_DECLINE_TAKE_PROFIT_RATIO = 0.04    # 조건1b: 익절 4%
    CIRCUIT_BREAKER_PREV_DAY_PCT_WITH_GAP = -1.0 # 조건2: 전일 -1% +
    CIRCUIT_BREAKER_NXT_GAP_PCT = -0.5           #        NXT 갭 -0.5% → 매수 중단
    CIRCUIT_BREAKER_RELEASE_GAP_PCT = 3.0        # 해제: NXT 갭 +3% → 정상 복귀 (5종목)

    # 장 시작 갭 체크 (09:01)
    MARKET_OPEN_GAP_THRESHOLD_PCT = -1.5         # 지수 시가 갭 -1.5% → 매수 중단

    # 장중 지수 모니터링 (30분 주기)
    INTRADAY_INDEX_DROP_THRESHOLD_PCT = -2.0     # 전일 대비 -2% → 매수 중단
    INTRADAY_INDEX_RECOVERY_PCT = -1.0           # -1% 이상 회복 시 → 매수 재개
```

상세: [docs/pre_market_circuit_breaker.md](docs/pre_market_circuit_breaker.md)

---

## 설정 변경 시 주의사항

1. **투자 비율 변경**: `trading_config.json`과 `fund_manager.py` 모두 수정
2. **ML 필터**: 활성화 전 충분한 백테스트 필요
3. **고급 필터**: 개별 필터 ON/OFF로 미세 조정 가능
4. **동적 손익비**: 시뮬레이션 테스트 후 활성화 권장

---

## 시뮬레이션 명령어

```bash
# 스크리너 통합 시뮬레이션 (price_position 전략)
python simulate_with_screener.py --start 20250224 --end 20260223

# 데이터 수집 + 시뮬레이션 파이프라인
python collect_and_simulate.py --phase ABCD --start 20250224 --end 20260223
# Phase A: 일봉 수집 (FinanceDataReader)
# Phase B: 스크리너 후보 선정
# Phase C: 분봉 수집 (KIS API → PostgreSQL)
# Phase D: 시뮬레이션 실행
```
