# 실시간 거래 vs 시뮬레이션 로직 비교 분석

## 목적
실시간 거래와 시뮬레이션(`signal_replay.py`)에서 동일한 분봉 데이터를 사용해도 결과가 다를 수 있는 원인 분석

---

## 1. 데이터 수집 로직 비교

### 1.1 실시간 (`intraday_stock_manager.py`)

**초기 데이터 수집** (`_collect_historical_data`):
```python
# 종목 선정 시 09:00부터 선정시점까지 전체 분봉 수집
historical_data = await get_full_trading_day_data_async(
    stock_code=stock_code,
    target_date=target_date,
    selected_time=target_hour,  # 선정 시점까지만
    start_time="090000"
)
```

**실시간 업데이트** (`update_realtime_data`):
```python
# 매분 10~45초에 완성된 최신 2개 분봉 수집
latest_minute_data = await self._get_latest_minute_bar(stock_code, current_time)

# _get_latest_minute_bar:
# 1. 현재 시간 - 1분 = 완성된 마지막 분봉 시간
# 2. past_data_yn="Y"로 최근 30개 가져옴
# 3. 요청 시간과 1분 전 시간의 분봉 2개만 추출
```

**데이터 병합**:
```python
# historical_data (선정시 수집) + realtime_data (장중 업데이트)
combined_data = pd.concat([historical_data, realtime_data], ignore_index=True)
combined_data = combined_data.drop_duplicates(subset=['datetime'], keep='last')
```

### 1.2 시뮬레이션 (`signal_replay.py`)

**데이터 수집**:
```python
# 1. 캐시 파일 확인
cache_file = Path(f"cache/minute_data/{stock_code}_{date_str}.pkl")
if cache_file.exists():
    with open(cache_file, 'rb') as f:
        df_1min = pickle.load(f)

# 2. 캐시 없으면 API 호출
df_1min = await dp.get_historical_chart_data(stock_code, date_str)

# 3. 수집 후 캐시 저장
with open(cache_file, 'wb') as f:
    pickle.dump(df_1min, f)
```

### ⚠️ 차이점 1: 데이터 수집 시점
- **실시간**: 선정 시점 + 장중 매분 업데이트 (누적)
- **시뮬**: 전체 09:00~15:30 일괄 수집

### ⚠️ 차이점 2: 데이터 병합 방식
- **실시간**: historical + realtime 병합 (중복 제거 필요)
- **시뮬**: 단일 데이터 소스 (병합 불필요)

---

## 2. 3분봉 변환 로직 비교

### 2.1 실시간 (`main.py` → `TimeFrameConverter.convert_to_3min_data`)

```python
# main.py에서 호출
data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
```

**`TimeFrameConverter.convert_to_3min_data()` 로직**:
```python
# 1. datetime을 인덱스로 설정
df = df.set_index('datetime')

# 2. floor 방식으로 3분봉 경계 계산
df['floor_3min'] = df.index.floor('3min')

# 3. 각 3분봉의 1분봉 개수 카운트
candle_counts = df.groupby('floor_3min').size()

# 4. 3분 구간별 OHLCV 집계
resampled = df.groupby('floor_3min').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}).reset_index()

# 5. candle_count 컬럼 추가
resampled['candle_count'] = resampled['datetime'].map(candle_counts)

# 6. 완성된 봉만 필터링
current_3min_floor = pd.Timestamp(current_time).floor('3min')
completed_data = resampled[resampled['datetime'] < current_3min_floor].copy()
```

### 2.2 시뮬레이션 (`signal_replay.py`)

```python
# signal_replay.py에서 호출 (동일한 함수 사용)
df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)
```

### ✅ 일치: 3분봉 변환은 동일한 함수 사용
- 둘 다 `TimeFrameConverter.convert_to_3min_data()` 사용
- floor 방식으로 09:00, 09:03, 09:06... 시점 생성

### ⚠️ 차이점 3: 완성된 봉 필터링
- **실시간**: `현재시간 < current_3min_floor` 조건으로 진행중인 봉 제외
- **시뮬**: 전체 데이터 사용 (과거 데이터이므로 모두 완성됨)

---

## 3. 신호 생성 로직 비교

### 3.1 실시간 (`trading_decision_engine.py` → `_check_pullback_candle_buy_signal`)

<function_calls>
<invoke name="read_file">
<parameter name="target_file">d:\GIT\RoboTrader\core\trading_decision_engine.py
