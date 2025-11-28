# 🚨 ML 예측값 차이 분석 보고서
**날짜**: 2025-11-27
**문제**: 시뮬레이션 ML과 실시간 ML의 예측값이 크게 차이남

## 📊 실측 데이터 비교

| 종목 | 결과 | 시뮬ML | 실시간ML | 차이 | 평가 |
|------|------|--------|---------|------|------|
| 440110 | ✅ +3.5% | 50.0% | 44.7% | **+5.3%p** | 시뮬 통과, 실시간 차단 |
| 094170 | ✅ +3.5% | 52.4% | 29.0% | **+23.4%p** | 🚨 큰 차이 |
| 084670 | ❌ -2.5% | 66.6% | 21.3% | **+45.3%p** | 🚨 정반대 |
| 039200 | ❌ -2.5% | 50.0% | 45.1% | **+4.9%p** | 근소한 차이 |

## 🔍 근본 원인 분석

### 1. 데이터 구조 차이

#### 실시간 거래 (`core/ml_predictor.py`)
```python
# pattern_stages 구조 사용 (pattern_data_logger.py가 생성)
pattern_stages = {
    '1_uptrend': {
        'candle_count': 9,          # ✅ 개수만 있음
        'max_volume': '93,000',     # ✅ 문자열 (쉼표 포함)
        'price_gain': '5.94%',      # ✅ 퍼센트 기호 포함
        'candles': [...]            # ✅ 실제 캔들 리스트
    },
    ...
}
```

#### 시뮬레이션 (`utils/signal_replay_ml.py`)
```python
# pattern_stages 구조 사용 (동일한 소스)
# 하지만 특성 추출 시 candles 리스트를 **직접 계산**
uptrend_avg_body = calculate_avg_body_pct(uptrend_candles_list)  # 캔들에서 계산
uptrend_total_volume = sum(c.get('volume', 0) for c in uptrend_candles_list)
```

### 2. 코드 비교

#### `core/ml_predictor.py` (실시간) - Line 156-175
```python
# 평균 몸통 크기 퍼센트 (avg_body_pct 우선, 없으면 계산)
uptrend_avg_body = uptrend.get('avg_body_pct')
if uptrend_avg_body is None:
    uptrend_avg_body = self._calculate_avg_body_pct(uptrend_candles_list)
else:
    uptrend_avg_body = self._safe_float(uptrend_avg_body)  # ⚠️ pattern_stages에 저장된 값 사용

# 총 거래량 (total_volume 우선, 없으면 계산)
uptrend_total_volume = uptrend.get('total_volume')
if uptrend_total_volume is None:
    uptrend_total_volume = sum(c.get('volume', 0) for c in uptrend_candles_list)
else:
    uptrend_total_volume = self._safe_float(uptrend_total_volume)  # ⚠️ pattern_stages에 저장된 값 사용
```

#### `utils/signal_replay_ml.py` (시뮬레이션) - Line 144-145
```python
# 상승 구간 캔들에서 평균 계산
uptrend_candles_list = uptrend.get('candles', [])
uptrend_avg_body = calculate_avg_body_pct(uptrend_candles_list)  # ✅ 항상 캔들에서 계산
uptrend_total_volume = sum(c.get('volume', 0) for c in uptrend_candles_list)  # ✅ 항상 캔들에서 계산
```

### 3. 문제점

**`pattern_data_logger.py`가 저장하는 값**을 확인해보면:

```python
# Line 141-151
'1_uptrend': {
    'start_idx': uptrend_info.get('start_idx'),
    'end_idx': uptrend_info.get('end_idx'),
    'candle_count': len(uptrend_candles),
    'max_volume': uptrend_info.get('max_volume'),      # ⚠️ 이 값이 문제!
    'volume_avg': uptrend_info.get('volume_avg'),      # ⚠️ 없을 수 있음
    'price_gain': uptrend_info.get('price_gain'),      # ⚠️ 이미 계산된 값
    'high_price': uptrend_info.get('high_price'),
    'candles': uptrend_candles                         # ✅ 원본 캔들 리스트
}
```

**`debug_info`에서 가져오는 값**들이 패턴 분석 시점에 계산된 값인데:
- `avg_body_pct` - pattern_stages에 **저장되지 않음!**
- `total_volume` - pattern_stages에 **저장되지 않음!**

따라서:
- 실시간: `uptrend.get('avg_body_pct')` → **None** → candles에서 계산
- 시뮬: 항상 candles에서 계산

**결론**: 실시간도 시뮬도 candles에서 계산해야 하는데, 실시간 코드가 `get()` 우선으로 되어 있어서 None일 때만 계산함.

### 4. 실제 440110 데이터 검증

#### Pattern Stages (저장된 데이터)
```json
{
  "1_uptrend": {
    "max_volume": "93,000",        // 문자열
    "price_gain": "5.94%",         // 문자열
    "candle_count": 9,
    // ❌ avg_body_pct 없음!
    // ❌ total_volume 없음!
    "candles": [...]               // ✅ 9개 캔들
  }
}
```

#### 실시간 ML 특성 추출 결과
```python
uptrend_avg_body = uptrend.get('avg_body_pct')  # None
if uptrend_avg_body is None:
    uptrend_avg_body = self._calculate_avg_body_pct([...9 candles...])  # ✅ 계산됨

uptrend_total_volume = uptrend.get('total_volume')  # None
if uptrend_total_volume is None:
    uptrend_total_volume = sum([...9 candles...])  # ✅ 계산됨
```

**그렇다면 왜 차이가 날까?**

## 🎯 진짜 문제 발견!

실시간과 시뮬레이션 코드를 다시 비교하니 **중요한 차이**를 발견:

### 실시간 (`core/ml_predictor.py`) - Line 142-176
```python
# ===== 상승 구간 특성 =====
uptrend = pattern_stages.get('1_uptrend', debug_info.get('uptrend', {}))  # ⚠️ debug_info 폴백!
uptrend_candles_list = uptrend.get('candles', [])
```

### 시뮬레이션 (`utils/signal_replay_ml.py`) - Line 136-145
```python
# 상승 구간
uptrend = pattern_stages.get('1_uptrend', {})  # ⚠️ debug_info 없음!
uptrend_candles_list = uptrend.get('candles', [])
```

**실시간은 `debug_info` 폴백이 있고, 시뮬은 없음!**

하지만 이것도 차이의 근본 원인은 아닌 것 같습니다. 왜냐하면 `pattern_stages`가 존재하면 둘 다 같은 값을 쓰니까요.

## 💡 최종 진단 필요

440110의 경우:
- 시뮬ML: 50.0%
- 실시간ML: 44.7%
- 차이: 5.3%p

이 차이는 **모델이 다른 특성 값을 받았을 때** 발생합니다.

다음을 확인해야 합니다:
1. ✅ 모델 파일이 동일한가? → 둘 다 `ml_model_stratified.pkl` 사용
2. ✅ 특성 이름 순서가 동일한가? → `feature_names` 사용
3. ❓ **특성 값이 정말 동일한가?** → 확인 필요!

## 🔧 해결 방안

### 방안 1: 디버그 로깅 추가
실시간과 시뮬레이션 모두에서 **실제 특성 값**을 로깅하여 비교

### 방안 2: 통일된 특성 추출 함수 사용
`core/ml_predictor.py`와 `utils/signal_replay_ml.py`가 **완전히 동일한 로직**을 쓰도록 공통 함수로 분리

### 방안 3: 패턴 데이터 저장 시 모든 특성 포함
`pattern_data_logger.py`가 저장할 때 **ML에서 사용하는 모든 특성**을 미리 계산해서 저장

## 📝 권장 조치

**즉시 조치**: 440110 패턴에 대해 실시간과 시뮬에서 추출한 **전체 특성 벡터**를 출력하여 정확히 어떤 특성이 다른지 확인

```python
# 실시간
print(f"[실시간] {stock_code} 특성:", features_df.to_dict('records')[0])

# 시뮬
print(f"[시뮬] {stock_code} 특성:", features)
```

이렇게 하면 어떤 특성이 차이를 만드는지 명확히 알 수 있습니다.
