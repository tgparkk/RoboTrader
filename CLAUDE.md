# RoboTrader - Claude 컨텍스트

## Claude 작업 지침

**상세 정보가 필요할 때 참조할 문서**:
- 데이터 흐름, 디버깅, 실시간 vs 시뮬 차이 → `DEVELOPMENT.md` 읽기
- 설정값 변경, 필터 설정, 투자비율 조정 → `CONFIGURATION.md` 읽기

---

## 프로젝트 개요

한국투자증권 KIS API 기반 자동매매 시스템

---

## 현재 활성 전략: 가격 위치 기반 전략 (price_position)

### 전략 설정 (config/strategy_settings.py)
```python
ACTIVE_STRATEGY = 'price_position'
```

### 진입 조건
| 항목 | 설정값 |
|------|--------|
| 시가 대비 | 2% ~ 4% 상승 |
| 거래 시간 | 10:00 ~ 12:00 |
| 거래 요일 | 월/수/목/금 (화요일만 제외) |
| 일 최대 종목 | 5개 |

### 청산 조건
- **손절**: -2.5%
- **익절**: +3.5%

### 관련 파일
- `config/strategy_settings.py` - 전략 선택 및 설정
- `core/strategies/price_position_strategy.py` - 전략 클래스
- `simulate_price_position_strategy.py` - 시뮬레이션

---

## 현재 시스템 설정

### 투자 비율 (config/trading_config.json)
- **buy_budget_ratio**: 0.20 (건당 가용잔고의 20%)

### 손익비 (config/trading_config.json)
- **stop_loss_ratio**: 0.025 (-2.5%)
- **take_profit_ratio**: 0.035 (+3.5%)

---

## 주요 파일 구조

```
config/
├── trading_config.json          # 거래 설정 (투자비율, 손익비)
├── strategy_settings.py         # 전략 선택 설정

core/
├── trading_decision_engine.py   # 매매 판단 엔진
├── trade_executor.py            # 매수/매도 실행 로직
├── intraday_stock_manager.py    # 장중 데이터 관리
├── fund_manager.py              # 자금 관리
├── strategies/
│   └── price_position_strategy.py  # 가격 위치 전략

cache/
└── market_data_v2.duckdb    # 분봉/일봉 캐시 데이터
```

---

## 분석 방법

### 실시간 거래 분석
```bash
# 매수 신호
grep "가격위치전략.*매수 신호" logs/trading_YYYYMMDD.log

# 거래 기록 확인
grep "거래 기록 추가" logs/trading_YYYYMMDD.log
```

### 시뮬레이션
```bash
# price_position 전략 시뮬레이션
python simulate_price_position_strategy.py --start 20250901 --end 20260130
```

---

## 상세 문서 참조

- [DEVELOPMENT.md](DEVELOPMENT.md) - 개발자용 상세 가이드
- [CONFIGURATION.md](CONFIGURATION.md) - 설정 파일 상세 설명
- [README.md](README.md) - 프로젝트 소개 및 설치 방법
