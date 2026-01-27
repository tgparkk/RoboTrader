# 동적 손익비 사용 가이드

## 🔧 ON/OFF 방법 (C++ #ifndef 스타일)

### 1️⃣ 활성화 (동적 손익비 사용)

`config/trading_config.json` 파일 수정:

```json
{
  "risk_management": {
    "max_position_count": 20,
    "max_position_ratio": 0.3,
    "stop_loss_ratio": 0.025,
    "take_profit_ratio": 0.035,
    "max_daily_loss": 0.1,
    "use_dynamic_profit_loss": true    // ✅ true로 변경
  }
}
```

### 2️⃣ 비활성화 (기존 고정 손익비 사용)

```json
{
  "risk_management": {
    "max_position_count": 20,
    "max_position_ratio": 0.3,
    "stop_loss_ratio": 0.025,
    "take_profit_ratio": 0.035,
    "max_daily_loss": 0.1,
    "use_dynamic_profit_loss": false   // ⚙️ false로 변경 (기본값)
  }
}
```

---

## 📊 동작 방식

### C++ 스타일 플래그 체크

```python
# config/dynamic_profit_loss_config.py

@classmethod
def get_profit_loss_ratio(cls, ...):
    # ⚙️ 동적 손익비 비활성화 시 기본값 반환 (C++ ifndef 스타일)
    if not cls.is_dynamic_enabled():
        return {'stop_loss': -2.5, 'take_profit': 3.5}  # 기존 로직

    # ✅ 동적 손익비 활성화 시 패턴 기반 계산
    # ... 패턴 분석 및 최적 손익비 계산 ...
```

### 플래그 상태

| 플래그 값 | 사용하는 손익비 | 설명 |
|----------|---------------|------|
| `false` (기본) | **고정 손익비** (-2.5% / +3.5%) | 기존 로직 그대로 |
| `true` | **동적 손익비** (패턴별 최적화) | 패턴 특성에 따라 자동 조정 |

---

## 🎯 실제 코드에 적용 방법

### 현재 상태
- ✅ `config/trading_config.json` - 플래그 추가 완료
- ✅ `config/dynamic_profit_loss_config.py` - 플래그 체크 로직 완료
- ⚠️ 실제 거래 엔진 연결은 **아직 안 됨**

### 적용이 필요한 부분

#### A. `core/trading_decision_engine.py` (핵심)

현재 고정 손익비를 사용하는 부분을 찾아서:

```python
# 기존 코드 (예상)
stop_loss_ratio = config.risk_management.stop_loss_ratio  # 0.025
take_profit_ratio = config.risk_management.take_profit_ratio  # 0.035

stop_loss_price = buy_price * (1 - stop_loss_ratio)
take_profit_price = buy_price * (1 + take_profit_ratio)
```

아래처럼 수정:

```python
from config.dynamic_profit_loss_config import DynamicProfitLossConfig

# 동적 손익비 계산 (플래그가 false면 자동으로 기본값 반환)
ratio = DynamicProfitLossConfig.get_profit_loss_ratio(
    current_volume=current_3min_volume,      # 현재 3분봉 거래량
    reference_volume=max_volume_today,       # 당일 최대 거래량
    current_time=datetime.now()              # 현재 시간
)

# 손익비 적용
stop_loss_price = buy_price * (1 + ratio['stop_loss'] / 100)   # -2.5 → 0.975
take_profit_price = buy_price * (1 + ratio['take_profit'] / 100)  # +3.5 → 1.035
```

#### B. 패턴 정보 활용 (더 정확한 분류)

`support_pattern_analyzer.py`의 결과를 활용하는 경우:

```python
# 패턴 분석 결과에서 지지/하락 거래량 정보 추출
pattern_result = analyzer.analyze(data)

if pattern_result.has_pattern:
    # 패턴의 debug_info 또는 직접 계산
    uptrend = pattern_result.uptrend_phase
    decline = pattern_result.decline_phase
    support = pattern_result.support_phase

    # 지지 거래량 분류
    support_volume_ratio = support.avg_volume / uptrend.max_volume
    if support_volume_ratio < 0.15:
        support_volume_class = 'very_low'
    elif support_volume_ratio < 0.25:
        support_volume_class = 'low'
    else:
        support_volume_class = 'normal'

    # 하락 시 거래량 분류
    decline_volume_ratio = decline.avg_volume / uptrend.volume_avg
    if decline_volume_ratio < 0.3:
        decline_volume_class = 'strong_decrease'
    elif decline_volume_ratio < 0.6:
        decline_volume_class = 'normal_decrease'
    else:
        decline_volume_class = 'weak_decrease'

    # 조합 기반 최적 손익비 (더욱 정확)
    from config.dynamic_profit_loss_config import DynamicProfitLossConfig

    # 내부에서 패턴 조합 테이블 참조
    ratio = DynamicProfitLossConfig.get_ratio_by_pattern(
        support_volume_class,
        decline_volume_class
    )
```

---

## 🧪 테스트 방법

### 1. 비활성화 상태 테스트 (기본 동작 확인)

```bash
# config.json에서 "use_dynamic_profit_loss": false 설정

# 시뮬레이션 실행
python -m utils.signal_replay --date 20251222 --export txt

# 결과 확인: 손익비 -2.5% / +3.5% 사용 확인
```

### 2. 활성화 상태 테스트

```bash
# config.json에서 "use_dynamic_profit_loss": true 설정

# 시뮬레이션 실행
python -m utils.signal_replay --date 20251222 --export txt

# 결과 확인: 패턴별 다른 손익비 사용 확인
```

### 3. 백테스트 비교

```bash
# 동적 손익비 백테스트
python test_dynamic_profit_loss.py --start 20251201 --end 20251222

# 결과 분석
- 고정 손익비 vs 동적 손익비 성과 비교
- 패턴별 손익비 적용 확인
```

---

## 🔄 롤백 방법 (문제 발생 시)

### 즉시 원복

```json
// config/trading_config.json
{
  "risk_management": {
    "use_dynamic_profit_loss": false  // ⚙️ false로 변경
  }
}
```

**저장 후 즉시 적용됨** (10초 이내 반영)

---

## 📋 체크리스트

### 동적 손익비 활성화 전

- [ ] 백테스트 결과 확인 ([DYNAMIC_PROFIT_LOSS_BACKTEST_RESULT.md](DYNAMIC_PROFIT_LOSS_BACKTEST_RESULT.md))
- [ ] 패턴 분석 리포트 검토 ([PATTERN_PROFIT_LOSS_ANALYSIS_REPORT.md](PATTERN_PROFIT_LOSS_ANALYSIS_REPORT.md))
- [ ] 시뮬레이션으로 최소 1주일 테스트
- [ ] 현재 코드 백업 완료

### 동적 손익비 활성화 후

- [ ] 로그에서 손익비 적용 확인
- [ ] 패턴별 손익비 다르게 적용되는지 확인
- [ ] 실거래 결과 모니터링 (최소 1주일)
- [ ] 문제 발생 시 즉시 롤백

---

## 💡 추가 최적화 옵션

### 1. 패턴별 조합 테이블 직접 참조

`config/dynamic_profit_loss_config.py`에 메서드 추가:

```python
@classmethod
def get_ratio_by_pattern(cls, support_volume_class, decline_volume_class):
    """패턴 조합으로 직접 손익비 조회"""
    if not cls.is_dynamic_enabled():
        return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}

    # 조합 테이블 (백테스트 결과 기반)
    PATTERN_COMBINATION_RATIOS = {
        ('very_low', 'weak_decrease'): {'stop_loss': -4.5, 'take_profit': 7.0},
        ('very_low', 'normal_decrease'): {'stop_loss': -5.0, 'take_profit': 7.0},
        ('low', 'weak_decrease'): {'stop_loss': -5.0, 'take_profit': 7.5},
        ('low', 'normal_decrease'): {'stop_loss': -1.5, 'take_profit': 7.5},
        ('normal', 'normal_decrease'): {'stop_loss': -5.0, 'take_profit': 5.0},
        # ... 더 많은 조합
    }

    key = (support_volume_class, decline_volume_class)
    if key in PATTERN_COMBINATION_RATIOS:
        return PATTERN_COMBINATION_RATIOS[key]

    return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}
```

### 2. 로깅 강화

```python
import logging

logger = logging.getLogger(__name__)

ratio = DynamicProfitLossConfig.get_profit_loss_ratio(...)

logger.info(f"[손익비] 동적: {DynamicProfitLossConfig.is_dynamic_enabled()}, "
           f"손절: {ratio['stop_loss']:.1f}%, 익절: +{ratio['take_profit']:.1f}%")
```

---

## 🚨 주의사항

### 1. 성능 최적화
- 플래그 체크는 **10초마다** 캐싱됨
- 설정 변경 후 최대 10초 이내 반영
- 실시간 성능에 영향 없음

### 2. 기본값 유지
- `use_dynamic_profit_loss` 미설정 시 자동으로 `false`
- 오류 발생 시 자동으로 기본 손익비 사용
- 안전 장치 내장

### 3. 실거래 적용
- 반드시 시뮬레이션 충분히 테스트 후 적용
- 소액으로 시작하여 점진적 확대
- 일일 손실 한도 준수

---

## 📞 문제 해결

### Q1. 플래그를 true로 했는데 여전히 고정 손익비가 적용됩니다.
**A**:
1. `config/trading_config.json` 파일 저장 확인
2. 10초 대기 (캐싱 갱신)
3. 로그에서 "동적 손익비 설정 로드 실패" 메시지 확인

### Q2. 동적 손익비 적용 후 수익률이 하락했습니다.
**A**:
1. 즉시 `use_dynamic_profit_loss: false`로 롤백
2. 패턴별 성과 재분석
3. 특정 패턴만 선택적으로 적용 검토

### Q3. 일부 종목만 동적 손익비를 적용하고 싶습니다.
**A**:
코드에서 조건부 적용:
```python
if stock_code in ['000390', '001430']:  # 특정 종목만
    ratio = DynamicProfitLossConfig.get_profit_loss_ratio(...)
else:
    ratio = {'stop_loss': -2.5, 'take_profit': 3.5}
```

---

**작성일**: 2025-12-22
**버전**: 1.0
