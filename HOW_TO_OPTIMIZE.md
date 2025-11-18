# 파라미터 최적화 - 실전 사용법

## 🎯 목표
코드의 파라미터를 수정하고, 백테스트를 실행하여 결과를 비교합니다.

---

## 📋 전체 프로세스 (3단계)

```
1. 백테스트 실행 (현재 설정)
   → 결과 확인 & 저장

2. 코드 수정 (파라미터 조정)
   → 파일 저장 (Ctrl+S)

3. 백테스트 재실행
   → 결과 비교
```

---

## 🚀 실전 예제: 오후 시간대 차단하기

### STEP 1: 현재 상태 백테스트

**터미널에서 실행:**
```bash
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
```

**결과 확인:**
```
총 거래: 213개
승률: 47.4%
총 수익금: +245,400원
거래당 평균: +1,152원
```

**📝 메모장에 기록:**
```
[Baseline - 현재 설정]
- 거래: 213건
- 승률: 47.4%
- 수익: +245,400원
```

---

### STEP 2: 코드 수정

**파일 열기:**
`core/indicators/pullback_candle_pattern.py`

**찾기 (Ctrl+F):**
```python
# 개선사항: 신뢰도 상한선 94%
```

**그 아래에 다음 코드 추가:**
```python
# 🔴 TEST: 오후 시간대 완전 차단 (12~15시)
if 12 <= current_time.hour < 15:
    result = SignalStrength(
        SignalType.AVOID, 0, 0,
        ["오후시간대차단"],
        volume_analysis.volume_ratio,
        BisectorStatus.BROKEN
    )
    return (result, []) if return_risk_signals else result
```

**저장 (Ctrl+S)**

---

### STEP 3: 수정 후 백테스트

**⚠️ 중요: 캐시된 로그 파일 삭제**

기존 결과 파일을 삭제해야 새로운 백테스트가 실행됩니다:

```bash
# Windows
del signal_replay_log\signal_new2_replay_2025*.txt

# 또는 폴더 이름 변경
ren signal_replay_log signal_replay_log_backup
mkdir signal_replay_log
```

**다시 백테스트 실행:**
```bash
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
```

**결과 예상:**
```
총 거래: 180~190건 (감소)
승률: 50~52% (상승)
총 수익금: +280,000~320,000원 (증가)
```

---

## 💡 더 간단한 방법: 단일 날짜 테스트

전체 기간 대신 **하루만 먼저 테스트**하여 빠르게 확인:

```bash
# 1. 현재 설정으로 10월 29일 테스트
python -X utf8 utils/signal_replay.py --date 20251029 --hour 9 --minute 0 --second 0

# 결과 확인
type signal_replay_log\signal_new2_replay_20251029_9_00_0.txt | findstr "총 거래"

# 2. 코드 수정 (오후 차단 추가)

# 3. 로그 삭제
del signal_replay_log\signal_new2_replay_20251029_9_00_0.txt

# 4. 다시 실행
python -X utf8 utils/signal_replay.py --date 20251029 --hour 9 --minute 0 --second 0

# 5. 결과 비교
type signal_replay_log\signal_new2_replay_20251029_9_00_0.txt | findstr "총 거래"
```

---

## 📊 주요 수정 포인트

### 1. 시간대별 신뢰도 조정

**파일:** `pullback_candle_pattern.py`
**위치:** line 546-560 부근

```python
# 현재
elif 9 <= current_time.hour < 10:
    min_confidence = 70  # 👈 이 숫자 변경

# 테스트
min_confidence = 65  # 완화 (거래 증가, 승률 하락)
min_confidence = 75  # 강화 (거래 감소, 승률 상승)
min_confidence = 80  # 더 강화
```

### 2. 오후 시간대 차단

**추가할 코드 (line 538 근처):**
```python
# 오후 완전 차단
if 12 <= current_time.hour < 15:
    result = SignalStrength(SignalType.AVOID, 0, 0,
                          ["오후차단"],
                          volume_analysis.volume_ratio,
                          BisectorStatus.BROKEN)
    return (result, []) if return_risk_signals else result
```

### 3. 10~11시 강화

**위치:** line 553-560 부근

```python
# 현재
else:  # 오전/늦은시간
    min_confidence = 75

# 변경
else:
    if 10 <= current_time.hour < 12:
        min_confidence = 85  # 10~11시 강화
    else:
        min_confidence = 75
```

---

## 🔍 결과 파일 확인

**통계 파일 위치:**
```
signal_replay_log/statistics_20251001_20251029.txt
```

**확인할 내용:**
```
총 거래 수: XXX개
승리 수: XXX개
패배 수: XXX개
승률: XX.X%
총 수익금: +XXX,XXX원
거래당 평균 수익금: +XXX원
```

**시간대별 통계:**
```
09시 |    101 |   63 |   38 |  62.4% |   +1.06%
10시 |    206 |  101 |  105 |  49.0% |   +0.34%
11시 |    114 |   55 |   59 |  48.2% |   +0.05%
12시 |      7 |    2 |    5 |  28.6% |   -0.79%
14시 |     65 |   28 |   37 |  43.1% |   -0.25%
```

---

## 📝 결과 비교표 양식

엑셀이나 메모장에 다음 표를 만들어서 기록:

```
| 테스트 | 날짜 | 거래수 | 승률 | 총수익 | 거래당평균 | 수정내용 |
|--------|------|--------|------|--------|------------|----------|
| 기본   | 1029 | 213건 | 47.4% | +245K | +1,152원 | 현재 설정 |
| TEST1  | 1029 | ?건   | ?%   | ?    | ?        | 오후차단 |
| TEST2  | 1029 | ?건   | ?%   | ?    | ?        | 10시강화 |
```

---

## ⚠️ 주의사항

### 1. **반드시 로그 파일 삭제**

```bash
# 백테스트 전에 기존 로그 삭제
del signal_replay_log\signal_new2_replay_*.txt
```

안 그러면 캐시된 결과를 재사용합니다!

### 2. **코드 저장 확인 (Ctrl+S)**

수정 후 반드시 저장하세요.

### 3. **한 번에 하나씩 수정**

여러 파라미터를 동시에 바꾸면 어떤 것이 효과적인지 알 수 없습니다.

### 4. **원본 백업**

```bash
git add .
git commit -m "백테스트 시작 전 백업"
```

---

## 🎯 추천 테스트 순서

### Phase 1: 시간대 최적화
1. ✅ 오후 차단 (12~15시)
2. ✅ 10~11시 강화 (신뢰도 85)
3. ✅ 09시만 거래 (10시 이후 차단)

### Phase 2: 신뢰도 최적화
4. 전체적으로 +5 증가
5. 전체적으로 +10 증가
6. 09시만 70, 나머지 90

### Phase 3: 거래량 필터
7. 돌파 거래량 0.8 → 1.0
8. 돌파 거래량 0.8 → 1.2
9. 지지 변동성 3.0 → 2.5

---

## 🚨 문제 해결

**Q: 결과가 안 바뀌어요**
```bash
# 로그 파일 삭제
del signal_replay_log\signal_new2_replay_*.txt

# Python 캐시 삭제
del __pycache__\*.pyc
del core\indicators\__pycache__\*.pyc
```

**Q: 오류가 나요**
- 들여쓰기 확인 (공백 4개 또는 탭)
- 따옴표 확인 (복사할 때 깨지지 않았는지)
- 괄호 짝 확인

**Q: 어떤 조합이 제일 좋나요?**
- 데이터마다 다릅니다
- 여러 기간으로 테스트 필요
- 과최적화 주의 (과거 데이터에만 맞추면 실전 실패)

---

## 📞 다음 단계

1. **오후 차단 테스트**
   - 코드 수정
   - 로그 삭제
   - 백테스트 실행
   - 결과 비교

2. **결과가 좋으면 커밋**
   ```bash
   git add core/indicators/pullback_candle_pattern.py
   git commit -m "오후 시간대 차단 추가 - 승률 +4.6%p"
   ```

3. **다음 개선 사항 테스트**
   - 10~11시 강화
   - 거래량 필터 등

---

## 💪 지금 바로 시작!

```bash
# 1. 현재 결과 확인
python -X utf8 generate_statistics.py --start 20251001 --end 20251029

# 2. pullback_candle_pattern.py 파일 열기
# 3. line 538 근처에 오후 차단 코드 추가
# 4. 저장 (Ctrl+S)
# 5. 로그 삭제
del signal_replay_log\signal_new2_replay_*.txt

# 6. 다시 실행
python -X utf8 generate_statistics.py --start 20251001 --end 20251029

# 7. 결과 비교!
```

**파이팅! 🚀**
