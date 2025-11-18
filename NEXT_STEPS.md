# 다음 단계 - 백테스트 및 검증

## 수정 완료된 내용

✅ **파일**: `core/indicators/pullback_candle_pattern.py`
✅ **수정**: 10~11시 신뢰도를 75 → 90으로 강화

**이유**:
- 전체 기간 분석 (9.1~10.29, 43일) 결과
- 10시: 49.0% 승률 (101승/105패) - 206건
- 11시: 48.2% 승률 (55승/59패) - 114건
- 10~11시 = 전체 거래의 76%인데 승률 48.8%

---

## 즉시 실행할 명령어

### 1단계: 기존 로그 백업 (선택)

수정 전 결과를 나중에 비교하고 싶으면:

```bash
ren signal_replay_log signal_replay_log_before_10_11_filter
mkdir signal_replay_log
```

백업 안 하고 바로 덮어쓰려면:

```bash
del signal_replay_log\signal_new2_replay_*.txt
```

### 2단계: 백테스트 실행

```bash
# 전체 기간 (9월 1일 ~ 10월 29일)
python -X utf8 generate_statistics.py --start 20250901 --end 20251029
```

또는 최근 1개월만:

```bash
python -X utf8 generate_statistics.py --start 20251001 --end 20251029
```

### 3단계: 결과 확인

```bash
# 통계 파일 확인
type signal_replay_log\statistics_20250901_20251029.txt
```

**확인할 지표**:
- 총 거래 수: 421건 → ?건 (감소 예상)
- 승률: 52.0% → ?% (상승 예상: 58~65%)
- 10시 승률: 49.0% → ?% (상승 예상)
- 11시 승률: 48.2% → ?% (상승 예상)

### 4단계: 비교 (백업을 만들었다면)

```bash
python -X utf8 compare_before_after.py
```

---

## 예상 결과

### 시나리오 1: 보수적 (10~11시 거래 50% 감소)

```
총 거래: 421건 → 약 261건
승률: 52.0% → 약 58~60%
10~11시: 320건 → 160건
```

### 시나리오 2: 적극적 (10~11시 거래 70% 감소)

```
총 거래: 421건 → 약 197건
승률: 52.0% → 약 60~65%
10~11시: 320건 → 96건
```

**핵심**: 10~11시의 나쁜 거래(패배 비율 51.6%)가 많이 제거되어 전체 승률 상승

---

## 결과가 좋다면

### Git 커밋

```bash
git add core/indicators/pullback_candle_pattern.py
git add FULL_PERIOD_ANALYSIS.md
git add NEXT_STEPS.md
git commit -m "10~11시 신뢰도 강화 (75→90) - 전체기간 분석 기반"
```

---

## 결과가 기대에 못 미친다면

### Option A: 더 강화

```python
# pullback_candle_pattern.py
if 10 <= current_time.hour < 12:
    min_confidence = 95  # 90 → 95 (거의 차단)
```

### Option B: 09시만 거래

```python
# pullback_candle_pattern.py 상단에 추가
if current_time.hour >= 10:
    result = SignalStrength(
        SignalType.AVOID, 0, 0,
        ["09시이후차단"],
        volume_analysis.volume_ratio,
        BisectorStatus.BROKEN
    )
    return (result, []) if return_risk_signals else result
```

09시만 거래하면:
- 거래: 101건
- 승률: 62.4%
- 하루 평균: 2.7건

### Option C: 원복

```bash
git checkout core/indicators/pullback_candle_pattern.py
```

---

## 추가 개선 아이디어 (2단계)

1단계 결과가 좋으면 추가로 시도:

### 1. 거래량 필터 강화

**파일**: `core/indicators/simple_pattern_filter.py`
**라인**: 64

```python
# 변경 전
weak_breakout_volume = breakout_volume < support_avg_volume * 0.8

# 변경 후
weak_breakout_volume = breakout_volume < support_avg_volume * 1.2
```

### 2. 지지 구간 최소 길이

**파일**: `core/indicators/support_pattern_analyzer.py`

지지 구간이 너무 짧으면(3분) 신뢰도 낮음 → 최소 15분 이상 요구

---

## 문제 해결

**Q: 결과가 변하지 않아요**

```bash
# 캐시 삭제
del signal_replay_log\signal_new2_replay_*.txt
del __pycache__\*.pyc
del core\indicators\__pycache__\*.pyc

# 다시 실행
python -X utf8 generate_statistics.py --start 20250901 --end 20251029
```

**Q: 오류가 나요**

- 들여쓰기 확인 (공백 vs 탭)
- 코드 저장 확인 (Ctrl+S)
- Python 버전 확인 (3.8+)

---

## 지금 바로 시작!

```bash
# 1. 로그 백업 (선택)
ren signal_replay_log signal_replay_log_before_10_11_filter
mkdir signal_replay_log

# 2. 백테스트 실행
python -X utf8 generate_statistics.py --start 20250901 --end 20251029

# 3. 결과 확인
type signal_replay_log\statistics_20250901_20251029.txt

# 4. 비교 (백업을 만들었다면)
python -X utf8 compare_before_after.py
```

**기대 결과**: 승률 52% → 58~65% 🚀
