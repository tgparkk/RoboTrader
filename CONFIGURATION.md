# RoboTrader 설정 가이드

## 설정 파일 구조

```
config/
├── trading_config.json          # 거래 설정 (투자비율, 손익비, 리스크)
├── ml_settings.py               # ML 필터 설정
├── advanced_filter_settings.py  # 고급 필터 설정
├── dynamic_profit_loss_config.py  # 동적 손익비 (비활성화)
└── key.ini                      # API 키 (git 제외)
```

---

## 1. trading_config.json

### 현재 설정
```json
{
  "order_management": {
    "buy_budget_ratio": 0.20,      // 건당 투자 비율 (20% = 1/5)
    "buy_cooldown_minutes": 25     // 동일 종목 재매수 대기
  },
  "risk_management": {
    "max_position_count": 20,       // 최대 보유 종목 수
    "max_position_ratio": 0.3,      // 종목당 최대 비율
    "stop_loss_ratio": 0.025,       // 손절 (-2.5%)
    "take_profit_ratio": 0.035,     // 익절 (+3.5%)
    "use_dynamic_profit_loss": false  // 동적 손익비 (비활성화)
  }
}
```

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

## 3. advanced_filter_settings.py

### 마스터 스위치
```python
ENABLED = True  # False면 모든 고급 필터 비활성화
```

### 현재 활성화된 필터

#### 3분봉 기반 필터
| 필터 | 설정 | 효과 |
|------|------|------|
| CONSECUTIVE_BULLISH | min_count: 1 | 연속 양봉 1개 이상 |
| PRICE_POSITION | min_position: 0.80 | 가격위치 80% 이상 |
| TUESDAY_FILTER | enabled: True | 화요일 회피 |
| TIME_DAY_FILTER | avoid: 9시화, 10시화, 11시화, 10시수 | 저승률 시간대 회피 |
| LOW_WINRATE_STOCKS | blacklist: 101170, 394800 | 저승률 종목 회피 |

#### pattern_stages 기반 필터
| 필터 | 설정 | 회피 조건 |
|------|------|----------|
| UPTREND_GAIN_FILTER | max_gain: 15.0 | 상승폭 >= 15% |
| DECLINE_PCT_FILTER | max_decline: 5.0 | 하락폭 >= 5% |
| SUPPORT_CANDLE_FILTER | avoid_counts: [3] | 지지캔들 = 3개 |

### 비활성화된 필터
- UPPER_WICK: 윗꼬리 비율 (효과 미미)
- VOLUME_RATIO: 거래량 비율 (연속양봉+가격위치가 더 효과적)
- RSI_FILTER: RSI (단독 효과 보통)
- FIRST_TRADE_FILTER: 첫 거래 (구현 복잡)

### 프리셋
```python
PRESETS = {
    'conservative': {...},   # 보수적: 승률 75.5%, 거래 21%
    'balanced': {...},       # 균형: 승률 69.3%, 거래 26%
    'aggressive': {...},     # 공격적: 승률 50%, 거래 81%
    'highest_winrate': {...} # 최고승률: 71.6%
}
ACTIVE_PRESET = None  # None이면 개별 설정 사용
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
- [README_DYNAMIC_PROFIT_LOSS.md](README_DYNAMIC_PROFIT_LOSS.md)
- [QUICK_START_동적손익비.md](QUICK_START_동적손익비.md)

---

## 설정 변경 시 주의사항

1. **투자 비율 변경**: `trading_config.json`과 `fund_manager.py` 모두 수정
2. **ML 필터**: 활성화 전 충분한 백테스트 필요
3. **고급 필터**: 개별 필터 ON/OFF로 미세 조정 가능
4. **동적 손익비**: 시뮬레이션 테스트 후 활성화 권장

---

## 시뮬레이션 명령어

```bash
# 기본 시뮬레이션
python batch_signal_replay.py --start 20250901 --end 20260123

# 고급 필터 적용
python batch_signal_replay.py --start 20250901 --end 20260123 --advanced-filter

# ML 필터 적용
python batch_signal_replay.py --start 20250901 --end 20260123 --ml-filter
```
