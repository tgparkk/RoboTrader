# RoboTrader 분석 가이드

## 📋 목차
1. [실시간 거래 vs 시뮬레이션 차이 분석](#실시간-거래-vs-시뮬레이션-차이-분석)
2. [주요 로그 파일 및 용도](#주요-로그-파일-및-용도)
3. [데이터 소스별 특징](#데이터-소스별-특징)
4. [패턴 신호 타이밍 이해](#패턴-신호-타이밍-이해)
5. [ML 필터링 분석](#ml-필터링-분석)
6. [디버깅 체크리스트](#디버깅-체크리스트)

---

## 실시간 거래 vs 시뮬레이션 차이 분석

### 실시간 거래
- **목적**: 실제 계좌로 거래
- **데이터**: KIS API에서 실시간 분봉 데이터 수집
- **특징**:
  - 분봉 데이터가 지속적으로 업데이트됨
  - 종목 선정 이전 패턴도 감지 가능 (과거 데이터 수집)
  - ML 필터 실시간 적용

### 시뮬레이션 (signal_replay)
- **목적**: 과거 거래 재현 및 백테스트
- **데이터**: 캐시 파일 (`cache/minute_data/`) 사용
- **특징**:
  - **selection_date 필터링 적용** (중요!)
  - 캐시 데이터는 종가 확정 후 저장
  - ML 필터 동일하게 적용

### 🚨 주요 차이점

| 구분 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| **데이터 소스** | KIS API (실시간) | 캐시 파일 (확정) |
| **selection_date 필터** | ❌ 없음 | ✅ 있음 (선정 시점 이전 신호 차단) |
| **분봉 업데이트** | 지속적 업데이트 | 고정된 종가 |
| **신호 타이밍** | 데이터 변화에 따라 가변 | 확정 데이터 기준 |

---

## 주요 로그 파일 및 용도

### 1. 실시간 거래 로그
**위치**: `logs/trading_YYYYMMDD.log`

**용도**:
- 실시간 매수/매도 신호 확인
- 후보 종목 선정 시점 확인
- ML 필터 적용 결과 확인
- 실제 체결 내역

**핵심 검색 패턴**:
```bash
# 특정 종목 후보 선정 시점
grep "006280\|녹십자" logs/trading_20251218.log | grep "후보\|선정\|candidate"

# 매수 판단 과정
grep "006280" logs/trading_20251218.log | grep "매수 판단"

# ML 필터 결과
grep "006280" logs/trading_20251218.log | grep "ML"

# 특정 시간대 매수 신호
grep "006280" logs/trading_20251218.log | grep -E "11:0[0-9]" | grep "매수"
```

**주요 로그 메시지**:
- `✅ 006280(녹십자) 선정 완료 - 시간: 10:45:29` → 후보 선정 시점
- `🔍 매수 판단 시작: 006280(녹십자)` → 매수 분석 시작
- `🤖 [ML 필터] 006280: 67.4% ✅ 통과` → ML 필터 통과
- `🚀 006280(녹십자) 매수 신호 발생` → 실제 매수 신호

### 2. 패턴 데이터 로그
**위치**: `pattern_data_log/pattern_data_YYYYMMDD.jsonl`

**용도**:
- 실시간 매수 신호의 패턴 상세 정보
- ML 예측에 사용된 특성값 확인
- 4단계 패턴 구조 분석 (상승-하락-지지-돌파)

**사용법**:
```bash
# 특정 종목 패턴 데이터 확인
grep "006280" pattern_data_log/pattern_data_20251218.jsonl

# JSON 파싱하여 상세 확인
grep "006280" pattern_data_log/pattern_data_20251218.jsonl | python -c "
import sys, json
data = json.loads(sys.stdin.read())
print('Signal Time:', data['signal_time'])
print('ML Prob:', data['signal_info'].get('ml_prob'))
print('Confidence:', data['signal_info']['confidence'])
"
```

**주요 필드**:
- `signal_time`: 신호 발생 시간
- `pattern_stages`: 4단계 패턴 구조
  - `1_uptrend`: 상승 구간
  - `2_decline`: 하락 구간
  - `3_support`: 지지 구간
  - `4_breakout`: 돌파 캔들
- `signal_info.ml_prob`: ML 예측 확률 (실시간은 null일 수 있음)

### 3. 시뮬레이션 로그 (ML 미적용)
**위치**: `signal_replay_log/signal_new2_replay_YYYYMMDD_9_00_0.txt`

**용도**:
- ML 필터 없이 순수 패턴 신호만 확인
- 3분봉별 신호 발생 여부 추적
- 체결 시뮬레이션 결과

**구조**:
```
=== 006280 - 20251218 눌림목(3분) 신호 재현 ===
  selection_date: 2025-12-18 10:45:30
  승패: 0승 1패
  매매신호:
    11:24 [pullback_pattern]
  체결 시뮬레이션:
    11:24 매수 @167,520 → 15:00 매도 @167,000 (-0.31%)

  🔍 상세 3분봉 분석:
    10:42→10:45: 종가:167,800 | 거래량:2,209 | 🔴회피(4단계패턴없음)
```

### 4. 시뮬레이션 로그 (ML 적용)
**위치**: `signal_replay_log_ml/signal_ml_replay_YYYYMMDD_9_00_0.txt`

**용도**:
- ML 필터 적용 후 최종 매수 신호 확인
- ML 필터링된 신호 추적
- 실시간과 비교 분석

**ML 필터링 표시**:
```
# [ML 필터링: 27.8%]       🔴 006280(녹십자) 11:24 매수 → -0.31%
   ↑ ML 예측 확률이 50% 미만으로 필터링됨
```

### 5. 데이터베이스
**위치**: `data/robotrader.db`

**주요 테이블**:
- `candidate_stocks`: 후보 종목 목록 및 선정 시점
- `trading_stocks`: 거래 중인 종목 상태
- `trades`: 체결 내역 (실시간에서는 사용 안 할 수도 있음)

**주의**: 거래 내역이 DB에 저장되지 않을 수 있으므로 로그 우선 확인

---

## 데이터 소스별 특징

### 1. 실시간 KIS API 데이터
**특징**:
- 1분봉 단위로 계속 업데이트
- 같은 캔들의 값이 시간에 따라 변할 수 있음
- 패턴 로그에 저장된 값 = 신호 발생 당시의 값

### 2. 캐시 파일 데이터
**위치**: `cache/minute_data/XXXXXX_YYYYMMDD.pkl`

**특징**:
- 장 종료 후 또는 특정 시점에 저장된 확정 데이터
- 시뮬레이션에서 사용
- **실시간 데이터와 다를 수 있음** (중요!)

**확인 방법**:
```python
import pickle
import pandas as pd

with open('cache/minute_data/006280_20251218.pkl', 'rb') as f:
    data = pickle.load(f)

# 3분봉으로 변환
data['datetime'] = pd.to_datetime(data['datetime'])
data = data.set_index('datetime')
df_3min = data.resample('3T', label='right', closed='right').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}).dropna()

print(df_3min['2025-12-18 10:42':'2025-12-18 11:00'])
```

### 3. 일봉 캐시
**위치**: `cache/daily/XXXXXX_YYYYMMDD_daily.pkl`

**용도**: 일봉 필터링에 사용

---

## 패턴 신호 타이밍 이해

### 3분봉 라벨 시간 vs 완성 시간

**중요 개념**:
```
10:42 캔들 (라벨 시간)
│
├─ 거래 기간: 10:39:01 ~ 10:42:00
├─ 라벨 시간: 10:42 (datetime)
└─ 완성 시간: 10:45 (signal_completion_time)
   └─ 실제 신호 발생 가능 시점
```

**코드 참조**: [signal_replay.py:358](d:\GIT\RoboTrader\utils\signal_replay.py#L358)
```python
signal_completion_time = datetime_val + pd.Timedelta(minutes=3)
```

### selection_date 필터링 로직

**시뮬레이션에서만 적용**:

```python
# signal_replay.py:456-459
if signal_completion_time < selection_dt:
    continue  # selection_date 이전 신호는 무시
```

**예시**:
- 종목 선정 시점: `2025-12-18 10:45:30`
- 10:42 캔들 완성: `2025-12-18 10:45:00`
- `10:45:00 < 10:45:30` → **차단!**

**따라서**: 선정 시점 직전에 완성된 패턴은 시뮬레이션에서 재현되지 않음

---

## ML 필터링 분석

### 실시간 ML 필터
**위치**: [trading_decision_engine.py:296-298](d:\GIT\RoboTrader\core\trading_decision_engine.py#L296-L298)

**확인 방법**:
```bash
grep "006280" logs/trading_20251218.log | grep "ML 필터"
```

**출력 예시**:
```
[ML 필터] 006280: 67.4% ✅ 통과 (임계값: 50.0%)
🤖 006280 ML 필터 차단: 승률 27.8% < 50.0%
```

### ML 임계값 설정
**위치**: [config/ml_settings.py:20](d:\GIT\RoboTrader\config\ml_settings.py#L20)

```python
ML_THRESHOLD = 0.5  # 50% 이상 승률 예측 시 매수 허용
```

### ML 특성 확인
**로그에서**:
```bash
grep "006280" logs/trading_20251218.log | grep "ML 특성"
```

**패턴 로그에서**:
```python
# pattern_data_log/pattern_data_YYYYMMDD.jsonl
{
  "pattern_stages": {
    "1_uptrend": {
      "candle_count": 15,
      "price_gain": 0.0343
    },
    "2_decline": {
      "decline_pct": 0.89
    }
  }
}
```

---

## 디버깅 체크리스트

### 실시간 vs 시뮬 결과가 다를 때

#### 1단계: 신호 발생 시점 확인
```bash
# 실시간
grep "XXXXXX" logs/trading_YYYYMMDD.log | grep "매수 신호 발생"

# 시뮬레이션
grep "XXXXXX" signal_replay_log/signal_new2_replay_YYYYMMDD*.txt
```

#### 2단계: 후보 선정 시점 확인
```bash
grep "XXXXXX" logs/trading_YYYYMMDD.log | grep "선정 완료"
```

**확인사항**:
- selection_date 시간 확인
- 신호 completion_time과 비교

#### 3단계: ML 필터 결과 비교
```bash
# 실시간 ML 확률
grep "XXXXXX" logs/trading_YYYYMMDD.log | grep "ML 필터"

# 시뮬 ML 확률
grep "XXXXXX" signal_replay_log_ml/signal_ml_replay_YYYYMMDD*.txt
```

#### 4단계: 패턴 데이터 비교
```bash
# 실시간 패턴
grep "XXXXXX" pattern_data_log/pattern_data_YYYYMMDD.jsonl

# 시뮬 상세 로그에서 캔들 데이터 확인
grep -A100 "=== XXXXXX" signal_replay_log/signal_new2_replay_YYYYMMDD*.txt
```

**비교 항목**:
- 돌파 캔들 가격 및 거래량
- 상승/하락 구간 캔들 수
- 신뢰도

#### 5단계: 데이터 소스 비교
```python
# 캐시 데이터 vs 패턴 로그 데이터
import pickle, pandas as pd, json

# 캐시 읽기
with open('cache/minute_data/XXXXXX_YYYYMMDD.pkl', 'rb') as f:
    cache_data = pickle.load(f)

# 3분봉 변환
cache_data['datetime'] = pd.to_datetime(cache_data['datetime'])
cache_3min = cache_data.set_index('datetime').resample('3T').agg({
    'close': 'last', 'volume': 'sum'
})

# 패턴 로그 읽기
with open('pattern_data_log/pattern_data_YYYYMMDD.jsonl') as f:
    for line in f:
        data = json.loads(line)
        if data['stock_code'] == 'XXXXXX':
            breakout = data['pattern_stages']['4_breakout']['candle']
            print(f"패턴 로그: {breakout['datetime']} - {breakout['close']}, {breakout['volume']}")

print("캐시 데이터:")
print(cache_3min[시작:종료])
```

### 일반적인 차이 원인

#### 원인 1: selection_date 필터링
- **증상**: 시뮬에서 신호가 아예 없음
- **확인**: selection_date 시간과 신호 completion_time 비교
- **해결**: 정상 동작 (선정 이전 신호는 실제로 매수 불가)

#### 원인 2: 데이터 불일치
- **증상**: 같은 시간대인데 캔들 값이 다름
- **확인**: 캐시 데이터 vs 패턴 로그 비교
- **원인**: 실시간 데이터 업데이트로 인한 차이
- **해결**: 패턴 로그 데이터가 실제 거래 당시 값

#### 원인 3: ML 확률 차이
- **증상**: 같은 패턴인데 ML 확률이 다름
- **확인**: 패턴 특성값 비교 (상승률, 하락률, 시간 등)
- **원인**: 패턴 구조가 미묘하게 다름
- **해결**: 각 시스템이 감지한 패턴이 실제로 다른 것

---

## 빠른 참조 명령어

### 종목 코드 변환
```bash
# 종목명으로 코드 찾기
grep "녹십자" logs/trading_YYYYMMDD.log | grep -oP "\d{6}" | head -1

# 코드로 종목명 찾기
grep "006280" logs/trading_YYYYMMDD.log | grep -oP "\d{6}\([^)]+\)" | head -1
```

### 시간대별 매수 신호 통계
```bash
# 당일 전체 매수 신호
grep "매수 신호 발생" logs/trading_20251218.log | wc -l

# 시간대별 분포
grep "매수 신호 발생" logs/trading_20251218.log | grep -oP "\d{2}:\d{2}" | cut -d: -f1 | sort | uniq -c
```

### ML 필터링 통계
```bash
# ML 통과율
grep "ML 필터" logs/trading_YYYYMMDD.log | grep "통과\|차단" | wc -l
grep "ML 필터" logs/trading_YYYYMMDD.log | grep "통과" | wc -l
```

---

## 핵심 개념 요약

### 🎯 실시간 거래 분석
1. **로그**: `logs/trading_YYYYMMDD.log`
2. **패턴 상세**: `pattern_data_log/pattern_data_YYYYMMDD.jsonl`
3. **선정 시점**: "선정 완료" 로그 검색
4. **ML 결과**: "ML 필터" 로그 검색

### 🎯 시뮬레이션 분석
1. **순수 패턴**: `signal_replay_log/signal_new2_replay_*.txt`
2. **ML 적용**: `signal_replay_log_ml/signal_ml_replay_*.txt`
3. **selection_date**: 종목별 선정 시점 확인 필수
4. **데이터 소스**: `cache/minute_data/*.pkl`

### 🎯 차이 분석 3단계
1. **신호 시점 비교**: 실시간 vs 시뮬
2. **selection_date 확인**: 필터링 여부
3. **데이터 일치 확인**: 캐시 vs 패턴 로그

### 🎯 ML 분석
1. **임계값**: 50% (config/ml_settings.py)
2. **실시간 적용**: trading_decision_engine.py
3. **시뮬 적용**: signal_replay_ml.py
4. **특성**: 상승/하락률, 캔들 수, 시간

---

## 추가 참고사항

### 로그 레벨
- **INFO**: 주요 이벤트 (선정, 매수, 매도)
- **DEBUG**: 상세 분석 정보 (패턴 검증 과정)
- **WARNING**: 비정상 상황
- **ERROR**: 오류

### 시간대 주의사항
- 모든 시간은 **KST (한국 시간)** 기준
- 3분봉 라벨: 해당 3분 구간의 **종료 시점**
- completion_time: 라벨 시간 + 3분

### 파일 인코딩
- 로그 파일: UTF-8
- JSON 파일: UTF-8
- 캐시 파일: pickle (바이너리)

---

*최종 업데이트: 2025-12-18*
*작성 기준: 006280(녹십자) 실시간 vs 시뮬 차이 분석*
