# 실시간 분봉 데이터 수집 잠재적 문제점 분석

## 🔍 분석 대상 코드
- `core/intraday_stock_manager.py`
- 데이터 수집 → 병합 → 필터링 → 정렬 전 과정

---

## ⚠️ 예상 문제점

### 1. **초기 데이터 수집 (`_collect_historical_data`)**

#### 문제 1-1: 전날 데이터 혼입 가능
**코드** (211-216번째 줄):
```python
historical_data = await get_full_trading_day_data_async(
    stock_code=stock_code,
    target_date=target_date,
    selected_time=target_hour,
    start_time="090000"
)
```

**문제**:
- `get_full_trading_day_data_async`가 반환한 데이터에 전날 데이터 포함 가능
- 260-276번째 줄에서 `selected_time` 이전만 필터링하지만 **날짜는 체크 안 함**

**증거**:
```
030530_20251013.pkl:
- 2025-10-10 13:26 (전날)
- 2025-10-13 09:00 (오늘)
```

**해결책**:
```python
# 선정 시점 필터링 후 당일 데이터만 추가 필터링 필요
if 'date' in filtered_data.columns:
    today_str = selected_time.strftime('%Y%m%d')
    filtered_data = filtered_data[filtered_data['date'].astype(str) == today_str].copy()
```

#### 문제 1-2: 선정 시점 필터링 불완전
**코드** (261-276번째 줄):
```python
if 'datetime' in historical_data.columns:
    selected_time_naive = selected_time.replace(tzinfo=None)
    filtered_data = historical_data[historical_data['datetime'] <= selected_time_naive].copy()
elif 'time' in historical_data.columns:
    selected_time_str = selected_time.strftime("%H%M%S")
    historical_data['time_str'] = historical_data['time'].astype(str).str.zfill(6)
    filtered_data = historical_data[historical_data['time_str'] <= selected_time_str].copy()
```

**문제**:
- `datetime` 컬럼 사용 시: 날짜 + 시간 모두 비교 ✅
- `time` 컬럼만 사용 시: **시간만 비교 (날짜 무시!)** ❌

**위험 시나리오**:
```
선정 시간: 2025-10-13 09:30
API 반환 데이터:
  - 2025-10-10 13:26 (time=132600)
  - 2025-10-13 09:00 (time=090000)

time 컬럼 필터링:
  time_str <= "093000"
  → 132600 > 093000 → 제외 ❌ (운 좋게 제외됨)
  → 090000 <= 093000 → 포함 ✅

하지만 만약:
  - 2025-10-10 08:50 (time=085000) 있었다면?
  → 085000 <= 093000 → 포함 ❌ (전날 데이터!)
```

---

### 2. **실시간 업데이트 (`_get_latest_minute_bar`)**

#### 문제 2-1: 1분 전 시간 계산 오류 가능
**코드** (673-681번째 줄):
```python
# 1분 전 시간 계산
prev_hour = int(target_hour[:2])
prev_min = int(target_hour[2:4])
if prev_min == 0:
    prev_hour = prev_hour - 1
    prev_min = 59
else:
    prev_min = prev_min - 1
prev_time = prev_hour * 10000 + prev_min * 100  # HHMMSS 형식
```

**문제**:
- 09:00:00의 1분 전 = 08:59:00
- 하지만 KRX는 09:00부터 시작!
- 08:59:00 데이터는 없음

**위험 시나리오**:
```
현재 시간: 09:01:30
target_hour: "090000" (09:00분봉 요청)
prev_time: 85900 (08:59)

API 조회: time.isin([85900, 90000])
→ 08:59 데이터 없음 (정상)
→ 09:00 데이터만 반환 (정상)

하지만 NXT 거래소(08:30 시작)라면?
→ 08:59 데이터 있을 수 있음 (혼란)
```

#### 문제 2-2: 2개 분봉 수집의 부작용
**코드** (683-695번째 줄):
```python
target_times = [prev_time, target_time]
matched_data = chart_df_sorted[chart_df_sorted['time'].isin(target_times)]
```

**문제**:
- API가 30개 반환 → 그 중 2개만 추출
- 나머지 28개는 버려짐
- **API 호출 낭비** (비효율)

**대안**:
```python
# past_data_yn="N"으로 1개만 가져오기
# 누락 복구는 다음 업데이트에서 자연스럽게 해결
```

---

### 3. **데이터 병합 (`update_realtime_data`)**

#### 문제 3-1: 병합 순서 문제
**코드** (522-530번째 줄):
```python
# 중복 제거하면서 병합
updated_realtime = pd.concat([current_realtime, latest_minute_data], ignore_index=True)

if 'datetime' in updated_realtime.columns:
    updated_realtime = updated_realtime.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime').reset_index(drop=True)
elif 'time' in updated_realtime.columns:
    updated_realtime = updated_realtime.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
```

**분석**:
- concat → drop_duplicates → sort_values ✅
- 순서는 정상

**하지만**:
- `current_realtime`이 이미 정렬되어 있다고 가정
- 만약 정렬 안 되어 있으면? → concat 후 섞임 → drop_duplicates가 잘못된 행 유지 가능

**위험 시나리오**:
```
current_realtime: [10:00(old), 10:03, 10:01(new)]  # 정렬 안 됨
latest_minute_data: [10:03(newest), 10:04]

concat: [10:00(old), 10:03, 10:01(new), 10:03(newest), 10:04]
drop_duplicates(keep='last'): [10:00(old), 10:01(new), 10:03(newest), 10:04]
sort: [10:00, 10:01, 10:03, 10:04] ✅

결과는 정상이지만, current_realtime이 정렬 안 되어 있을 위험
```

---

### 4. **데이터 병합 (`get_combined_chart_data`)**

#### 문제 4-1: 중복 제거와 정렬 순서
**코드** (895-900번째 줄):
```python
# 중복 제거 (같은 시간대 데이터가 있을 수 있음)
before_count = len(combined_data)
if 'datetime' in combined_data.columns:
    combined_data = combined_data.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime').reset_index(drop=True)
elif 'time' in combined_data.columns:
    combined_data = combined_data.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
```

**분석**:
- drop_duplicates → sort_values ✅
- 순서는 정상

**하지만 문제**:
```python
# 870번째 줄
combined_data = pd.concat([historical_data, realtime_data], ignore_index=True)
```

- concat 시점에 정렬 안 됨
- 876번째 줄에서 당일 필터링
- 895번째 줄에서 중복 제거 + 정렬

**순서**:
```
1. concat (정렬 안 됨)
2. 당일 필터링 (정렬 안 됨)
3. 중복 제거 + 정렬 (✅)
```

**위험**:
- 2번과 3번 사이에 문제 가능
- 당일 필터링이 정렬 안 된 상태에서 실행
- 하지만 날짜 비교는 순서 무관하므로 정상 ✅

#### 문제 4-2: 시간순 정렬이 2번 발생
**코드**:
```python
# 895번째 줄: 중복 제거 + 정렬
combined_data = combined_data.drop_duplicates(...).sort_values('datetime')...

# 908-910번째 줄: 또 정렬
if 'datetime' in combined_data.columns:
    combined_data = combined_data.sort_values('datetime').reset_index(drop=True)
```

**문제**:
- 불필요한 중복 정렬
- 성능 낭비 (하지만 심각하진 않음)

---

### 5. **품질 검사 (`_check_data_quality`)**

#### 문제 5-1: 품질 검사 시점에 데이터 변경
**코드** (1294-1303번째 줄):
```python
# historical_data와 realtime_data를 합쳐서 전체 분봉 데이터 생성
all_data = pd.concat([stock_data.historical_data, stock_data.realtime_data], ignore_index=True)

# 시간순 정렬 및 중복 제거 (품질 검사 전 필수)
if 'time' in all_data.columns:
    all_data = all_data.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
```

**문제**:
- `get_combined_chart_data`와 별도로 병합
- **같은 데이터를 2번 병합** (중복 작업)
- 결과가 다를 수 있음?

**위험 시나리오**:
```
get_combined_chart_data:
  - historical + realtime 병합
  - 당일 필터링 ✅
  - 중복 제거
  
_check_data_quality:
  - historical + realtime 병합 (다시!)
  - 당일 필터링 없음! ❌
  - 중복 제거

→ 전날 데이터 포함 가능!
```

---

### 6. **당일 데이터 필터링 누락**

#### 문제 6-1: _check_data_quality에서 당일 필터링 없음
**코드** (1294번째 줄):
```python
all_data = pd.concat([stock_data.historical_data, stock_data.realtime_data], ignore_index=True)
# → 바로 중복 제거 및 정렬
# → 당일 필터링 없음! ❌
```

**해결책**:
```python
# 품질 검사 전에도 당일 필터링 필요
all_data = pd.concat([...])
# 당일 필터링 추가
if 'date' in all_data.columns:
    today_str = now_kst().strftime('%Y%m%d')
    all_data = all_data[all_data['date'].astype(str) == today_str].copy()
```

#### 문제 6-2: _collect_historical_data에서 당일 필터링 없음
**코드** (260-276번째 줄):
```python
# 선정 시간을 timezone-naive로 변환하여 pandas datetime64[ns]와 비교
selected_time_naive = selected_time.replace(tzinfo=None)
filtered_data = historical_data[historical_data['datetime'] <= selected_time_naive].copy()
```

**문제**:
- 시간만 필터링, **날짜는 체크 안 함**
- 전날 13:30 < 오늘 09:30 → 전날 데이터 포함 가능!

**해결책**:
```python
# 선정 시점 필터링 전에 당일 필터링 먼저
today_str = selected_time.strftime('%Y%m%d')
if 'date' in historical_data.columns:
    historical_data = historical_data[historical_data['date'].astype(str) == today_str].copy()

# 그 다음 시간 필터링
filtered_data = historical_data[historical_data['datetime'] <= selected_time_naive].copy()
```

---

### 7. **API 응답 데이터 신뢰성**

#### 문제 7-1: get_full_trading_day_data_async 반환값 불확실
**위치**: `api/kis_chart_api.py`

**의심**:
- API가 왜 전날 데이터를 반환하는가?
- `target_date`를 명시했는데도?

**확인 필요**:
```python
# 해당 함수 내부에서 당일 필터링 하는지?
# 아니면 API 서버가 여러 날짜 반환하는지?
```

---

### 8. **시간 비교 로직 취약점**

#### 문제 8-1: time 컬럼만 있을 때 날짜 무시
**여러 곳에서 발생**:
```python
# time 컬럼 기준 필터링 (날짜 무시!)
filtered_data = data[data['time_str'] <= selected_time_str].copy()
```

**위험**:
```
전날: time=143000 (14:30)
오늘: time=093000 (09:30)
선정: time=120000 (12:00)

필터링: time <= 120000
→ 오늘 09:30 포함 ✅
→ 전날 14:30 제외 (14 > 12) ✅

운 좋게 정상!

하지만:
전날: time=103000 (10:30)
선정: time=120000 (12:00)

필터링: time <= 120000
→ 전날 10:30 포함 ❌ (날짜 무시!)
```

---

### 9. **중복 데이터 처리 순서**

#### 문제 9-1: 정렬 전 vs 후 중복 제거

**현재 코드**:
```python
# update_realtime_data (527번째 줄)
updated_realtime = pd.concat([current_realtime, latest_minute_data])
updated_realtime = updated_realtime.drop_duplicates(..., keep='last').sort_values(...)
```

**문제**:
- `drop_duplicates(keep='last')`는 **DataFrame 순서 기준**
- 정렬 전이면 "마지막"이 시간상 마지막이 아닐 수 있음

**위험 시나리오**:
```
current_realtime: [10:00(v1), 10:03(v1)]
latest_minute_data: [10:00(v2), 10:01]

concat: [10:00(v1), 10:03(v1), 10:00(v2), 10:01]
              ↑ 먼저                  ↑ 나중

drop_duplicates(keep='last'):
  10:00 중복 → 마지막(v2) 유지 ✅
  결과: [10:03(v1), 10:00(v2), 10:01]

sort:
  [10:00(v2), 10:01, 10:03(v1)] ✅

결과는 정상! 하지만 논리적으로 혼란스러움
```

**권장**:
```python
# 1. 먼저 정렬
combined = pd.concat([...]).sort_values('datetime')
# 2. 중복 제거 (이제 keep='last'가 시간상 마지막)
combined = combined.drop_duplicates(subset=['datetime'], keep='last')
```

---

### 10. **날짜 경계 문제 (금요일 → 월요일)**

#### 문제 10-1: 주말 데이터 처리
**시나리오**:
```
금요일 (2025-10-10) 장 마감 후
월요일 (2025-10-13) 09:00 종목 선정

API 호출: target_date=20251013
API 반환: 
  - 2025-10-10 데이터 (마지막 거래일)
  - 2025-10-13 데이터

당일 필터링 없으면:
  → 금요일 데이터 포함 ❌
```

**증거**: 오늘 파일이 정확히 이 케이스!

---

## 🎯 종합 평가

### 현재 상태:
```
전날 데이터 혼입 가능성: ⚠️ 높음
  - _collect_historical_data: 당일 필터링 없음 ❌
  - _check_data_quality: 당일 필터링 없음 ❌
  - save_minute_data_to_cache: 당일 필터링 추가 ✅ (방금 수정)

API 비효율:
  - 30개 가져와서 2개만 사용 ⚠️

로직 복잡도:
  - 같은 병합을 2번 수행 ⚠️
  - 정렬도 2번 수행 ⚠️
```

---

## 📋 권장 수정사항

### 우선순위 1: 당일 필터링 강화 (필수!)

```python
# _collect_historical_data (260번째 줄 이전 추가)
# API 반환 데이터를 먼저 당일로 필터링
if 'date' in historical_data.columns:
    today_str = selected_time.strftime('%Y%m%d')
    historical_data = historical_data[historical_data['date'].astype(str) == today_str].copy()
    self.logger.info(f"   당일 데이터만 필터링: {today_str}")

# 그 다음 선정 시점 필터링
if 'datetime' in historical_data.columns:
    ...
```

```python
# _check_data_quality (1300번째 줄 이후 추가)
all_data = pd.concat([stock_data.historical_data, stock_data.realtime_data])

# 당일 필터링 추가
today_str = now_kst().strftime('%Y%m%d')
if 'date' in all_data.columns:
    all_data = all_data[all_data['date'].astype(str) == today_str].copy()

# 시간순 정렬 및 중복 제거
all_data = all_data.drop_duplicates(...).sort_values(...)
```

### 우선순위 2: 비효율 개선 (선택)

```python
# _get_latest_minute_bar
# past_data_yn="N"으로 변경 (1개만 가져오기)
result = get_inquire_time_itemchartprice(
    div_code=div_code,
    stock_code=stock_code,
    input_hour=target_hour,
    past_data_yn="N"  # Y → N
)
```

### 우선순위 3: 중복 작업 제거 (선택)

```python
# _check_data_quality에서 별도 병합 대신
# get_combined_chart_data 결과 재사용
```

---

## 🚨 즉시 수정 필요

**당일 필터링이 2곳에서 누락됨**:
1. `_collect_historical_data` (초기 수집)
2. `_check_data_quality` (품질 검사)

→ **전날 데이터 혼입의 주범!**

