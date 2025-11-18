# Phase 1 즉시 적용 가능한 개선사항

## 개선 1: 캔들 몸통 크기 제한

### 근거
- 승리 종목 평균 body_pct: 0.33%
- 패배 종목 평균 body_pct: 0.46% (40% 더 큼)
- 급격한 상승 이후 매수는 고점 매수 위험

### 적용 위치
파일: `core/indicators/pullback_candle_pattern.py`
함수: `generate_improved_signals` (라인 390~)

### 코드 수정

기존 코드 위치를 찾으세요:
```python
# 3. 시가 대비 2% 이상 상승 체크 (매수 필수 조건)
if day_open_price:
    current_price = float(current['close'])
    price_increase_pct = (current_price - day_open_price) / day_open_price * 100

    if price_increase_pct < 2.0:
        ...
```

**이 코드 블록 바로 뒤에 추가:**

```python
# 5. 캔들 몸통 크기 제한 (급격한 상승 차단)
current_open = float(current['open'])
current_close = float(current['close'])
current_body_pct = abs(current_close - current_open) / current_open * 100 if current_open > 0 else 0

if current_body_pct >= 0.5:  # 0.5% 이상의 급격한 상승 차단
    result = SignalStrength(
        SignalType.AVOID, 0, 0,
        [f"캔들몸통과도({current_body_pct:.2f}%≥0.5%)"],
        volume_analysis.volume_ratio,
        BisectorStatus.BROKEN
    )
    return (result, []) if return_risk_signals else result
```

---

## 개선 2: 10-11시 신뢰도 기준 상향

### 근거
- 09시: 61.0% 승률 ⭐
- 10시: 49.5% 승률 (낮음)
- 11시: 46.7% 승률 (더 낮음)

### 적용 위치
파일: `core/indicators/pullback_candle_pattern.py`
함수: `generate_improved_signals` (라인 538~560)

### 코드 수정

**기존 코드:**
```python
# 기본 시간대별 조건
if 12 <= current_time.hour < 14:  # 오후시간 (승률 29.6%)
    min_confidence = 85
    ...
elif 9 <= current_time.hour < 10:  # 개장시간 (승률 55.4%)
    min_confidence = 70
    ...
else:  # 오전/늦은시간
    min_confidence = 75
    ...
```

**변경 후:**
```python
# 기본 시간대별 조건
if 12 <= current_time.hour < 14:  # 오후시간
    min_confidence = 90  # 85 → 90 (더욱 엄격)
    # 오후시간 일봉 강화 조건
    if daily_strength < 60:
        min_confidence = 95
    elif is_ideal_daily:
        min_confidence = 85
elif 9 <= current_time.hour < 10:  # 개장시간 (높은 승률 유지)
    min_confidence = 70  # 유지
    # 개장시간 일봉 조건
    if daily_strength >= 70:
        min_confidence = 65
    elif daily_strength < 40:
        min_confidence = 80
elif 10 <= current_time.hour < 12:  # 10-11시 강화
    min_confidence = 80  # 75 → 80 (상향)
    # 일봉 조건 추가
    if is_ideal_daily and daily_strength >= 70:
        min_confidence = 75
    elif daily_strength < 50:
        min_confidence = 85
else:  # 기타 시간
    min_confidence = 80  # 75 → 80
```

---

## 개선 3: 신뢰도 상한선 조정

### 근거
- 현재 95% 이상 차단
- 과도하게 높은 신뢰도도 위험할 수 있음

### 적용 위치
파일: `core/indicators/pullback_candle_pattern.py`
라인: 571~573

### 코드 수정

**기존 코드:**
```python
# 신뢰도 상한선 94% 체크 (개선사항 1)
if support_pattern_info['confidence'] >= 95:
    result = SignalStrength(SignalType.AVOID, 0, 0, ["신뢰도95%이상차단"], volume_analysis.volume_ratio, BisectorStatus.BROKEN)
    return (result, []) if return_risk_signals else result
```

**변경 후 (유지):**
- 현재 로직 유지 (95% 이상 차단)
- 실제 데이터에서 95% 이상이 거의 없으므로 영향 미미

---

## 개선 4 (선택사항): 평균 거래량 급증 차단

### 근거
- 패배 종목 평균 거래량: 45,608
- 승리 종목 평균 거래량: 34,153
- 거래량 급증은 상투 가능성

### 적용 위치
파일: `core/indicators/pullback_candle_pattern.py`
함수: `generate_improved_signals`

### 코드 추가 (캔들 몸통 제한 뒤)

```python
# 6. 최근 평균 거래량 급증 체크 (선택사항)
if len(data) >= 10:
    recent_avg_volume = data['volume'].tail(10).mean()
    recent_max_volume = data['volume'].tail(10).max()

    # 평균의 3배 이상 급증시 차단
    if recent_max_volume > recent_avg_volume * 3:
        result = SignalStrength(
            SignalType.AVOID, 0, 0,
            [f"거래량급증(평균{recent_avg_volume:.0f}→최대{recent_max_volume:.0f})"],
            volume_analysis.volume_ratio,
            BisectorStatus.BROKEN
        )
        return (result, []) if return_risk_signals else result
```

---

## 테스트 방법

### 1. 백테스트 실행

기존 시뮬레이션 스크립트 실행:
```bash
python run_backtest_simple.py
```

### 2. 결과 비교

**변경 전:**
```
총 거래: 441개
승률: 51.5%
총 수익: +115,400원
```

**목표:**
```
총 거래: 350~400개
승률: 54~56%
총 수익: +200,000~300,000원
```

### 3. 세부 체크포인트

- [ ] 09시 거래 승률 유지 (61% 이상)
- [ ] 10-11시 거래 건수 감소 확인
- [ ] 큰 캔들 차단 동작 확인
- [ ] 전체 수익성 개선 확인

---

## 롤백 방법

문제 발생시 Git으로 되돌리기:
```bash
git checkout core/indicators/pullback_candle_pattern.py
```

또는 주석 처리:
```python
# 5. 캔들 몸통 크기 제한 (급격한 상승 차단)
# if current_body_pct >= 0.5:
#     ...
```

---

## 예상 효과 요약

| 개선사항 | 거래 감소 | 승률 향상 | 수익 향상 |
|---------|----------|----------|----------|
| 캔들 몸통 제한 | -5% | +2~3%p | +50,000원 |
| 10-11시 강화 | -10% | +1~2%p | +30,000원 |
| 합계 | -15% | +3~5%p | +80,000~150,000원 |

---

*생성일: 2025-11-01*
*우선순위: High*
*리스크: Low*
