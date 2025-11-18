# 전략 최적화 가이드

파라미터를 조정하면서 백테스트 결과를 비교하는 방법을 설명합니다.

## 📁 구조

```
RoboTrader/
├── backtest_configs/          # 전략 설정 파일 (YAML)
│   ├── default.yaml          # 기본 설정 (현재 운영)
│   ├── aggressive_morning.yaml  # 오전 집중 전략
│   └── conservative.yaml     # 보수적 전략
├── backtest_results/          # 백테스트 결과 저장
└── core/indicators/
    └── pullback_candle_pattern.py  # 매매 로직
```

## 🚀 사용법

### 방법 1: 기존 통계 도구 사용 (가장 간단)

```bash
# 1. 기본 전략 테스트 (현재 설정)
python -X utf8 generate_statistics.py --start 20251001 --end 20251029

# 2. 코드 수정 후 다시 테스트
# pullback_candle_pattern.py 파일에서 파라미터 수정
# 예: line 539의 min_confidence 값 변경

# 3. 다시 실행하여 결과 비교
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
```

### 방법 2: 설정 파일 활용 (권장)

**1단계: 설정 파일 수정**

`backtest_configs/test1.yaml` 파일 생성:

```yaml
name: "test1"
description: "10시 이후 차단 테스트"

time_filter:
  enable: true
  hour_9_min_confidence: 70   # 09시
  hour_10_min_confidence: 95  # 10시 차단
  hour_11_min_confidence: 95  # 11시 차단
  block_hours: [12, 13, 14, 15]  # 오후 차단

backtest_period:
  start_date: "20251001"
  end_date: "20251029"
```

**2단계: 코드에 적용**

`pullback_candle_pattern.py`의 line 539-560을 수정:

```python
# 설정 파일에서 읽어온 값 사용
if 9 <= current_time.hour < 10:
    min_confidence = 70  # test1.yaml의 hour_9_min_confidence
elif 10 <= current_time.hour < 11:
    min_confidence = 95  # test1.yaml의 hour_10_min_confidence
# ...
```

**3단계: 백테스트 실행**

```bash
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
```

### 방법 3: 여러 케이스 비교

**A. 케이스별 수정 및 실행**

```bash
# Case 1: 기본 설정
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
# 결과 저장: signal_replay_log/statistics_20251001_20251029.txt

# Case 2: 코드 수정 (10시 차단 강화)
# pullback_candle_pattern.py 수정 후
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
# 결과 저장: signal_replay_log/statistics_20251001_20251029.txt

# Case 3: 코드 수정 (오후 완전 차단)
# pullback_candle_pattern.py 수정 후
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
```

**B. 결과 비교**

각 케이스 실행 후 `signal_replay_log/statistics_*.txt` 파일을 비교합니다.

```
# Case 1 결과
총 거래: 145건
승률: 50.3%
총 수익: +485,000원

# Case 2 결과 (10시 차단)
총 거래: 95건
승률: 57.9%
총 수익: +612,000원  <- 개선!

# Case 3 결과 (오후 차단)
총 거래: 112건
승률: 55.4%
총 수익: +580,000원
```

## 🎯 주요 수정 포인트

### 1. 시간대별 신뢰도 조정

**파일:** `core/indicators/pullback_candle_pattern.py`

**위치:** line 539-560

```python
# 현재
if 9 <= current_time.hour < 10:
    min_confidence = 70  # <-- 이 값 조정

elif 10 <= current_time.hour < 11:
    min_confidence = 75  # <-- 이 값 조정
```

**테스트 값:**
- 완화: 65, 70
- 기본: 75, 80
- 강화: 85, 90, 95

### 2. 오후 시간대 차단

**파일:** `core/indicators/pullback_candle_pattern.py`

**위치:** line 539 바로 다음 추가

```python
# 오후 완전 차단
if 12 <= current_time.hour < 15:
    result = SignalStrength(SignalType.AVOID, 0, 0,
                          ["오후시간대차단"],
                          volume_analysis.volume_ratio,
                          BisectorStatus.BROKEN)
    return (result, []) if return_risk_signals else result
```

### 3. 거래량 필터 강화

**파일:** `core/indicators/simple_pattern_filter.py`

**위치:** line 64

```python
# 현재
weak_breakout_volume = breakout_volume < support_avg_volume * 0.8

# 강화 옵션
weak_breakout_volume = breakout_volume < support_avg_volume * 1.0  # 100%
weak_breakout_volume = breakout_volume < support_avg_volume * 1.2  # 120%
weak_breakout_volume = breakout_volume < support_avg_volume * 1.5  # 150%
```

### 4. 가격 상승률 조건

**파일:** `core/indicators/pullback_candle_pattern.py`

**위치:** line 479-491

```python
# 현재: 시가 대비 2% 이상
if price_increase_pct < 2.0:
    return AVOID

# 테스트 값:
# - 완화: 1.5%, 1.8%
# - 강화: 2.5%, 3.0%
```

## 📊 빠른 비교 체크리스트

다음 단계로 여러 케이스를 테스트:

```
□ Case 1: 기본 설정 (baseline)
  - 결과: ___건, ___%, ___원

□ Case 2: 10~11시 신뢰도 85→90
  - 수정: line 539의 min_confidence = 90
  - 결과: ___건, ___%, ___원

□ Case 3: 오후 시간대 완전 차단
  - 수정: line 539에 if 12 <= hour < 15: return AVOID 추가
  - 결과: ___건, ___%, ___원

□ Case 4: 거래량 필터 1.0x
  - 수정: simple_pattern_filter.py line 64를 1.0으로
  - 결과: ___건, ___%, ___원

□ Case 5: 가격 상승률 2.5%
  - 수정: line 484를 2.5로
  - 결과: ___건, ___%, ___원
```

## 💡 팁

1. **한 번에 하나만 수정**: 여러 파라미터를 동시에 바꾸면 어떤 것이 효과적인지 알 수 없습니다.

2. **결과 기록**: 각 테스트마다 결과를 메모장에 복사해두세요.

3. **백업**: 원본 코드를 git commit하거나 복사해두세요.

4. **충분한 데이터**: 최소 1개월 이상 테스트해야 유의미합니다.

5. **과최적화 주의**: 과거 데이터에만 맞춘 설정은 실전에서 실패할 수 있습니다.

## 🔧 자주 테스트하는 조합

### 조합 A: 오전 집중
```python
# 09시: 70
# 10시: 85
# 11시: 85
# 12시 이후: 차단
```

### 조합 B: 매우 보수적
```python
# 09시: 75
# 10시: 90
# 11시: 90
# 12시 이후: 차단
# 거래량 필터: 1.2x
# 가격 상승률: 2.5%
```

### 조합 C: 09시만
```python
# 09시: 70
# 10시 이후: 차단
```

## 📝 결과 양식

테스트 결과를 다음 형식으로 기록하세요:

```
=== 테스트 결과 ===
날짜: 2025-10-29
케이스: 조합 A (오전 집중)

수정 내역:
- line 539: min_confidence = 85 (10시)
- line 555: min_confidence = 85 (11시)
- line 539 다음: 오후 차단 코드 추가

결과:
- 총 거래: 112건
- 승률: 55.4%
- 총 수익: +580,000원
- 거래당 평균: +5,179원

비교 (baseline):
- 거래 수: 145건 → 112건 (-33건)
- 승률: 50.3% → 55.4% (+5.1%p)
- 총 수익: +485,000원 → +580,000원 (+95,000원)
```

## ❓ 문제 해결

**Q: 코드를 수정했는데 결과가 안 바뀌어요**
- A: Python 파일을 저장하셨나요? (Ctrl+S)
- A: 올바른 파일을 수정하셨나요? (pullback_candle_pattern.py)

**Q: 오류가 나요**
- A: 들여쓰기를 정확히 맞추셨나요?
- A: 코드를 복사할 때 따옴표가 깨지지 않았나요?

**Q: 어떤 조합이 가장 좋나요?**
- A: 데이터마다 다릅니다. 여러 기간으로 테스트해보세요.

## 🎓 다음 단계

1. **기본 백테스트 실행**
   ```bash
   python -X utf8 generate_statistics.py --start 20251001 --end 20251029
   ```

2. **한 가지 수정 (예: 오후 차단)**
   - `pullback_candle_pattern.py` line 539 수정

3. **다시 실행 및 비교**
   ```bash
   python -X utf8 generate_statistics.py --start 20251001 --end 20251029
   ```

4. **결과가 좋으면 git commit**
   ```bash
   git add core/indicators/pullback_candle_pattern.py
   git commit -m "오후 시간대 차단 추가 (승률 +5%)"
   ```
