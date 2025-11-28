# 실시간 거래 1건 문제 - 원인 및 해결책

## 🔴 핵심 문제 3가지

### 1. **실시간에서 패턴 데이터 로깅이 없음**
```python
# ❌ 현재 상태
core/indicators/pullback_candle_pattern.py:
- generate_improved_signals() 메서드에서 패턴 감지
- PatternDataLogger를 사용하지 않음
- pattern_data에 signal_type, confidence가 없음

# ✅ 해결 필요
- 실시간에서도 PatternDataLogger 사용
- signal_type과 confidence를 pattern_data에 포함
```

### 2. **ML 예측이 패턴 데이터 부족으로 작동 안함**
```python
# trading_decision_engine.py:244
pattern_features = price_info.get('pattern_data', {})

if pattern_features:  # ← 여기서 걸림
    should_trade, ml_prob = self.ml_predictor.should_trade(...)
else:
    logger.warning(f"⚠️ {stock_code} 패턴 데이터 없음 - ML 필터 건너뜀")
```

**문제:**
- `pattern_data`가 있지만 `signal_type`과 `confidence`가 None
- ML 예측에 필요한 필수 필드가 누락됨

### 3. **실시간은 조건검색 결과로만 매수**
```python
# 현재 플로우:
1. 조건검색 편입 (신뢰도 17.27%)
2. 패턴 검증 → signal_type = None
3. ML 필터 → 데이터 없음으로 건너뜀
4. 매수 체결

# 시뮬레이션 플로우:
1. 3분봉 데이터 로드 (완전한 과거 데이터)
2. 패턴 감지 → signal_type, confidence 완전히 생성
3. PatternDataLogger로 로깅
4. ML 필터 → 정상 작동
5. 매수 체결
```

---

## 📋 해결책

### 해결책 1: **실시간 패턴 로깅 추가** (즉시 적용 가능)

#### A. `pullback_candle_pattern.py` 수정

**위치:** `generate_improved_signals()` 메서드 내부

```python
# core/indicators/pullback_candle_pattern.py

def generate_improved_signals(self, current_data, ...):
    """눌림목 패턴 신호 생성"""

    # ... 기존 패턴 감지 로직 ...

    if signal_strength:
        # 🆕 실시간 패턴 데이터 로깅
        try:
            from core.pattern_data_logger import PatternDataLogger

            # 실시간 로깅 (simulation_date=None)
            pattern_logger = PatternDataLogger()

            if hasattr(signal_strength, 'pattern_data') and signal_strength.pattern_data:
                pattern_id = pattern_logger.log_pattern_data(
                    stock_code=stock_code,
                    signal_type=signal_strength.signal_type.value if signal_strength.signal_type else "UNKNOWN",
                    confidence=signal_strength.confidence if signal_strength.confidence else 0.0,
                    support_pattern_info=signal_strength.pattern_data,
                    data_3min=current_data,
                    data_1min=None  # 실시간에서는 3분봉만 사용
                )

                # ML 예측 추가
                if pattern_logger.log_file.exists():
                    # 저장된 패턴에 ML 예측 승률 추가
                    self._add_ml_prediction_to_pattern(pattern_id, signal_strength.pattern_data)

        except Exception as log_err:
            logger.warning(f"⚠️ 실시간 패턴 데이터 로깅 실패: {log_err}")

    return signal_strength
```

#### B. `TradingDecisionEngine` 개선

**위치:** `should_buy_signal()` 메서드

```python
# core/trading_decision_engine.py:244

# 🔧 개선 전
pattern_features = price_info.get('pattern_data', {})

if pattern_features:  # 너무 엄격함
    should_trade, ml_prob = self.ml_predictor.should_trade(...)

# ✅ 개선 후
pattern_features = price_info.get('pattern_data', {})

# pattern_data가 있고 pattern_stages가 있으면 ML 예측 수행
if pattern_features and pattern_features.get('pattern_stages'):
    try:
        # signal_type과 confidence 기본값 설정
        if not pattern_features.get('signal_type'):
            pattern_features['signal_type'] = 'pullback_pattern'
        if not pattern_features.get('confidence'):
            pattern_features['confidence'] = 50.0  # 기본 신뢰도

        should_trade, ml_prob = self.ml_predictor.should_trade(
            pattern_features,
            threshold=self.ml_threshold,
            stock_code=stock_code
        )

        if not should_trade:
            self.logger.info(f"🤖 {stock_code} ML 필터 차단: 승률 {ml_prob:.1%} < {self.ml_threshold:.1%}")
            return False, f"눌림목캔들패턴: {reason} + ML필터차단 (승률: {ml_prob:.1%})", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
        else:
            self.logger.info(f"✅ {stock_code} ML 필터 통과: 승률 {ml_prob:.1%}")

    except Exception as e:
        self.logger.error(f"❌ {stock_code} ML 필터 오류: {e} - 신호 허용")
        # ML 오류 시 신호 허용
else:
    self.logger.warning(f"⚠️ {stock_code} 패턴 구조 없음 - ML 필터 건너뜀")
```

---

### 해결책 2: **signal_type과 confidence 누락 문제 해결**

#### A. `SignalStrength` 클래스 확인

```python
# core/indicators/pullback_candle_pattern.py

@dataclass
class SignalStrength:
    signal_type: SignalType  # ← None이 되면 안됨
    confidence: float = 0.0
    should_buy: bool = False
    reason: str = ""
    price_info: Dict[str, Any] = field(default_factory=dict)
    pattern_data: Dict[str, Any] = field(default_factory=dict)  # ← 여기에 signal_type, confidence 포함 필요
```

**문제:** `pattern_data`에 `signal_type`과 `confidence`가 포함되어 있지 않음

**해결:**
```python
# generate_improved_signals() 메서드 내부

signal_strength = SignalStrength(
    signal_type=SignalType.STRONG_BUY,  # 또는 CAUTIOUS_BUY
    confidence=confidence_score,
    should_buy=True,
    reason=reason,
    price_info=price_info,
    pattern_data={
        'signal_type': SignalType.STRONG_BUY.value,  # ← 추가
        'confidence': confidence_score,              # ← 추가
        'pattern_stages': pattern_stages,
        'debug_info': debug_info,
        # ... 기타 필드
    }
)
```

---

### 해결책 3: **실시간 데이터 수집 개선**

#### 현재 문제
- 실시간은 3분봉 완성까지 기다려야 함 (2~3분 지연)
- 시뮬레이션은 모든 데이터를 가지고 있음

#### 개선 방안
```python
# core/realtime_candle_builder.py (있다면)

class RealtimeCandleBuilder:
    """실시간 캔들 빌더"""

    def get_partial_candle(self, current_time):
        """현재 진행 중인 캔들 정보 반환 (미완성 캔들)"""
        # 3분봉이 완성되지 않아도 현재까지의 데이터 반환
        # 조기 신호 감지용
        pass

    def is_pattern_forming(self, partial_candle):
        """패턴이 형성 중인지 확인 (조기 감지)"""
        # 돌파 양봉이 형성되는 중인지 실시간 체크
        pass
```

---

## 🎯 우선 순위별 적용 순서

### 🔥 Priority 1: **즉시 적용** (1시간 내)

**해결책 1-B만 적용** (가장 빠른 효과)
```python
# trading_decision_engine.py:244
# pattern_features 체크 로직 완화
if pattern_features and pattern_features.get('pattern_stages'):
    # 기본값 설정 추가
    if not pattern_features.get('signal_type'):
        pattern_features['signal_type'] = 'pullback_pattern'
    if not pattern_features.get('confidence'):
        pattern_features['confidence'] = 50.0
```

**효과:**
- 즉시 ML 필터가 작동하기 시작
- 패턴 구조(`pattern_stages`)만 있으면 예측 가능
- 코드 수정 최소화

---

### ⚡ Priority 2: **단기 적용** (1일 내)

**해결책 2 적용** (pattern_data에 필수 필드 추가)
```python
# pullback_candle_pattern.py
pattern_data={
    'signal_type': signal_type.value,  # ← 추가
    'confidence': confidence_score,     # ← 추가
    'pattern_stages': pattern_stages,
}
```

**효과:**
- 패턴 데이터가 완전하게 생성됨
- ML 예측 정확도 향상
- 로깅 데이터 품질 개선

---

### 🎨 Priority 3: **중기 적용** (1주 내)

**해결책 1-A 적용** (실시간 패턴 로깅)
```python
# pullback_candle_pattern.py에 PatternDataLogger 추가
```

**효과:**
- 실시간과 시뮬레이션 로직 통일
- 패턴 데이터가 실시간으로 저장됨
- 사후 분석 가능

---

### 🚀 Priority 4: **장기 적용** (2주 이상)

**해결책 3 적용** (실시간 조기 감지)
```python
# 미완성 캔들로도 패턴 예측
```

**효과:**
- 타이밍 개선 (2~3분 단축)
- 더 많은 신호 포착
- 수익 기회 증가

---

## 📝 테스트 계획

### 1. Priority 1 적용 후 테스트
```bash
# 실시간 로그 확인
tail -f logs/trading_*.log | grep "ML 필터"

# 예상 출력:
# ✅ 950160 ML 필터 통과: 승률 63.4%
# 🤖 448900 ML 필터 차단: 승률 41.2% < 50.0%
```

### 2. Priority 2 적용 후 테스트
```bash
# 패턴 데이터 확인
python -c "
import json
with open('pattern_data_log/pattern_data_$(date +%Y%m%d).jsonl', 'r') as f:
    pattern = json.loads(f.readlines()[-1])
    print(f'signal_type: {pattern.get(\"signal_type\")}')
    print(f'confidence: {pattern.get(\"confidence\")}')
"

# 예상 출력:
# signal_type: STRONG_BUY (또는 pullback_pattern)
# confidence: 87.5 (또는 50.0 이상)
```

### 3. 시뮬레이션 재실행으로 검증
```bash
python batch_signal_replay_ml.py -s 20251128 -e 20251128

# 예상 결과:
# - 패턴 데이터 27개 (중복 없음)
# - ML 필터 정상 작동 (5건 차단)
# - 결과: 7승 4패 (63.6%)
```

---

## 🎁 예상 개선 효과

| 항목 | 현재 | Priority 1 적용 후 | 최종 목표 |
|------|------|-------------------|-----------|
| **실시간 거래 수** | 1건 | 7~11건 | 11~16건 |
| **ML 필터 작동** | ❌ 미작동 | ✅ 작동 | ✅ 완전 작동 |
| **패턴 로깅** | ⚠️ 불완전 | ⚠️ 불완전 | ✅ 완전 |
| **예상 승률** | 100% (운) | 60~65% | 65~70% |
| **거래 타이밍** | 2분 지연 | 2분 지연 | 즉시 |

---

## ✅ 권장 실행 순서

1. **지금 당장:** Priority 1 적용 → 테스트
2. **내일:** Priority 2 적용 → 시뮬 검증
3. **이번 주:** Priority 3 적용 → 실거래 모니터링
4. **다음 주:** Priority 4 검토 → 성능 측정

**Priority 1만 적용해도 실시간 거래가 7~11건으로 증가할 것으로 예상됩니다!** 🎯
