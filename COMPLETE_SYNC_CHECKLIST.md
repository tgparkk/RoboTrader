# 시뮬레이션 vs 실시간 완전 동일화 체크리스트

## ✅ 이미 동일한 부분
- [x] 패턴 감지 함수: `PullbackCandlePattern.generate_improved_signals()` 동일
- [x] 패턴 필터: `SimplePatternFilter.should_filter_out()` 동일
- [x] 데이터 구조: 3분봉 DataFrame 동일

## ❌ 차이점 및 수정 필요

### 1. PatternDataLogger 사용 여부
**시뮬:**
```python
# utils/signal_replay.py:310-331
pattern_logger = PatternDataLogger(simulation_date=simulation_date)
pattern_id = pattern_logger.log_pattern_data(
    stock_code=stock_code,
    signal_type=signal_strength.signal_type.value,
    confidence=signal_strength.confidence,
    ...
)
```

**실시간:**
```python
# ❌ PatternDataLogger 사용 안함!
```

**수정:** 실시간에도 PatternDataLogger 추가

---

### 2. pattern_data에 signal_type, confidence 포함 여부
**확인 필요:**
```python
# generate_improved_signals()가 반환하는 SignalStrength 객체의
# pattern_data에 signal_type과 confidence가 포함되어 있는가?
```

**수정:** pattern_data에 필수 필드 추가

---

### 3. ML 필터 적용
**시뮬:**
```python
# ❌ ML 필터 없음!
```

**실시간:**
```python
# trading_decision_engine.py:241-264
if self.use_ml_filter and self.ml_predictor:
    should_trade, ml_prob = self.ml_predictor.should_trade(...)
```

**수정:** 시뮬레이션에도 ML 필터 추가 (선택사항)

---

### 4. 3분봉 완성 시점 체크
**시뮬:**
```python
# 자동으로 완성된 캔들만 순회
for i in range(len(df_3min)):
    current_data = df_3min[:i+1]
```

**실시간:**
```python
# ❓ 3분봉 완성 시점에만 체크하는가?
# 확인 필요!
```

**수정:** 실시간도 3분 정각에만 체크하도록 보장

---

## 📋 수정 계획

### Step 1: pattern_data 구조 확인 및 통일
파일: `core/indicators/pullback_candle_pattern.py`

### Step 2: 실시간 PatternDataLogger 추가
파일: `core/trading_decision_engine.py` 또는 `main.py`

### Step 3: 3분봉 완성 시점 체크 보장
파일: 데이터 수집 관련 파일

### Step 4: 테스트 및 검증
- 시뮬 재실행
- 실시간 로그 확인
- 패턴 데이터 비교
