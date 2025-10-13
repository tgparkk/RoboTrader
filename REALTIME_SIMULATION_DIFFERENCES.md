# 실시간 거래 vs 시뮬레이션 주요 차이점 분석

## 🎯 분석 목적
동일한 분봉 데이터를 사용해도 실시간 거래와 시뮬레이션에서 결과가 다를 수 있는 모든 원인을 파악

---

## ✅ 1. 동일한 부분 (일치성 확인됨)

### 1.1 3분봉 변환 로직
- **함수**: 둘 다 `TimeFrameConverter.convert_to_3min_data()` 사용
- **방식**: floor 방식 (09:00, 09:03, 09:06...)
- **집계**: OHLCV 동일하게 계산

### 1.2 신호 생성 함수
- **함수**: 둘 다 `PullbackCandlePattern.generate_improved_signals()` 사용
- **파라미터**: `use_improved_logic=True` 동일

### 1.3 손익비 설정
- **소스**: 둘 다 `trading_config.json` 사용
- **익절**: `take_profit_ratio` (0.035 = 3.5%)
- **손절**: `stop_loss_ratio` (0.025 = 2.5%)

---

## ⚠️ 2. 데이터 수집 차이점

### 2.1 실시간 데이터 수집

**파일**: `core/intraday_stock_manager.py`

**과정**:
```
1. 종목 선정 시 (예: 09:35)
   → 09:00~09:35 분봉 수집 (historical_data)

2. 실시간 업데이트 (매분 10~45초, 10초 간격)
   → 완성된 최신 2개 분봉 수집 (realtime_data)
   → 중복 제거 후 병합

3. 병합 결과
   combined_data = historical_data + realtime_data
   중복 제거: drop_duplicates(subset=['datetime'], keep='last')
```

**잠재적 문제점**:
- ❌ `past_data_yn="Y"`로 30개 가져온 후 2개만 추출 → API 부하
- ❌ historical과 realtime 경계에서 중복 발생 가능
- ❌ 품질 검사 시점에 따라 순서/중복 이슈 가능

### 2.2 시뮬레이션 데이터 수집

**파일**: `utils/signal_replay.py`

**과정**:
```
1. 캐시 파일 확인
   cache/minute_data/{stock_code}_{date}.pkl

2. 캐시 있으면 로드, 없으면 API 호출
   → 09:00~15:30 전체 데이터 일괄 수집

3. 수집 후 캐시 저장
```

**장점**:
- ✅ 단일 소스 (병합 불필요)
- ✅ 중복 없음
- ✅ 전체 데이터 일관성 보장

### 🔍 핵심 차이: 데이터 병합 여부
| 항목 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| 데이터 소스 | 2개 (historical + realtime) | 1개 (전체 일괄) |
| 병합 필요 | ✅ 필요 | ❌ 불필요 |
| 중복 가능성 | ⚠️ 있음 | ✅ 없음 |
| 순서 보장 | ⚠️ 정렬 필요 | ✅ 보장됨 |

---

## ⚠️ 3. 3분봉 완성 판단 차이점

### 3.1 실시간 (`TimeFrameConverter.convert_to_3min_data`)

**코드** (lines 136-169):
```python
# 현재 시간 기준으로 완성된 봉만 필터링
current_time = now_kst()
current_3min_floor = pd.Timestamp(current_time).floor('3min')

# 현재 진행중인 3분봉은 제외
completed_data = resampled[
    resampled['datetime'] < current_3min_floor
].copy()
```

**예시**:
```
현재 시간: 10:44:30
current_3min_floor: 10:42:00
완성된 봉: ~10:39까지 (10:42는 진행 중이므로 제외)
```

### 3.2 시뮬레이션 (`signal_replay.py`)

**코드**:
```python
# 과거 데이터이므로 모든 3분봉이 완성됨
# 별도 필터링 없음
df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)
```

**예시**:
```
과거 데이터: 09:00~15:30 전체
모든 3분봉 완성됨 (필터링 불필요)
```

### 🔍 핵심 차이: 완성 판단 시점
| 항목 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| 필터링 | ✅ 진행중 봉 제외 | ❌ 불필요 (모두 완성) |
| 확정 기준 | `current_time >= candle_end_time` | 과거 데이터 (항상 확정) |
| 지연 체크 | ✅ 5분 초과 시 무효 | ❌ 없음 |

---

## ⚠️ 4. 매수 판단 시점 차이점

### 4.1 실시간 (`main.py` → `_execute_trading_decision`)

**실행 주기**: 5초마다

**판단 로직** (`_analyze_buy_decision`):
```python
# 1. 완성된 3분봉 데이터 가져오기
combined_data = intraday_manager.get_combined_chart_data(stock_code)
data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)

# 2. 3분봉 품질 검증
if not data_3min.empty and len(data_3min) >= 2:
    # 시간 간격 검증 (3분봉 연속성)
    # candle_count 검증 (HTS 분봉 누락)
    # 09:00 시작 확인

# 3. 매수 신호 확인
buy_signal, buy_reason, buy_info = await decision_engine.analyze_buy_decision(
    trading_stock, data_3min
)

# 4. 중복 신호 차단
# - 동일 캔들 시점 체크
# - 25분 쿨다운 체크
```

**특징**:
- ⏱️ **5초 주기**로 지속적인 판단
- 🔄 **완성된 3분봉이 나올 때마다** 즉시 체크
- 🎯 **실시간성**: 신호 발생 즉시 매수 가능

### 4.2 시뮬레이션 (`signal_replay.py` → `simulate_trades`)

**실행 주기**: 전체 3분봉을 순회

**판단 로직**:
```python
# 1. 전체 매수 신호 리스트 생성
buy_signals = list_all_buy_signals(df_3min)

# 2. 각 신호별로 순회하며 매수 판단
for signal in buy_signals:
    # - selection_date 필터링
    # - 동일 캔들 중복 차단
    # - 25분 쿨다운 체크
    # - 포지션 보유 중 차단
    # - 15시 이후 차단
    
    # 3. 매수 체결 시뮬레이션 (5분 타임아웃)
    # 4. 매도 시뮬레이션
```

**특징**:
- 📊 **시계열 순서**로 전체 신호 처리
- 🎯 **완벽한 재현**: 모든 신호를 순서대로 시뮬레이션
- ⏱️ **후행성**: 과거 데이터 기반

### 🔍 핵심 차이: 신호 처리 방식
| 항목 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| 처리 방식 | 5초 주기 실시간 체크 | 전체 신호 순차 처리 |
| 신호 발생 | 최신 3분봉만 체크 | 모든 3분봉 체크 |
| 중복 방지 | last_signal_candle_time | last_signal_candle_time |
| 타이밍 | 신호 발생 즉시 | 신호 발생 시점 시뮬 |

---

## ⚠️ 5. 매수 체결 로직 차이점

### 5.1 실시간 (`main.py`)

```python
# 매수 신호 발생 시
buy_signal, buy_reason, buy_info = await decision_engine.analyze_buy_decision(...)

if buy_signal and buy_info.get('quantity', 0) > 0:
    # 즉시 매수 주문 실행
    await decision_engine.execute_real_buy(
        trading_stock,
        buy_reason,
        buy_info['buy_price'],  # 4/5가
        buy_info['quantity'],
        candle_time=current_candle_time
    )
```

**특징**:
- 💰 **즉시 주문**: 신호 발생 즉시 지정가 주문
- ⏱️ **체결 시간 불확실**: 주문 후 체결까지 대기
- 📊 **OrderManager**가 체결 모니터링

### 5.2 시뮬레이션 (`signal_replay.py`)

```python
# 신호 발생 후 5분 타임아웃 내에 4/5가 도달 여부 확인
signal_time_start = signal_completion_time
signal_time_end = signal_completion_time + timedelta(minutes=5)

check_candles = df_1min[
    (df_1min['datetime'] >= signal_time_start) & 
    (df_1min['datetime'] < signal_time_end)
].copy()

# 5분 내에 4/5가 이하로 떨어지는 시점 찾기
buy_executed = False
for _, candle in check_candles.iterrows():
    if candle['low'] <= three_fifths_price:
        buy_executed = True
        actual_execution_time = candle['datetime']
        break

if not buy_executed:
    # 미체결 처리
    status = 'unexecuted'
```

**특징**:
- 📊 **체결 검증**: 5분 내 4/5가 도달 여부 확인
- ⏱️ **체결 시간 명확**: 정확한 체결 시점 파악
- 💸 **미체결 처리**: 5분 내 미도달 시 미체결

### 🔍 핵심 차이: 체결 가정
| 항목 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| 체결 판단 | OrderManager 모니터링 | 5분 타임아웃 검증 |
| 미체결 처리 | 타임아웃 후 취소 | 기록에 포함 |
| 체결가 | 실제 체결가 | 4/5가 (가정) |
| 체결 시점 | 실제 체결 시점 | 1분봉 저가 도달 시점 |

---

## ⚠️ 6. 매도 판단 로직 차이점

### 6.1 실시간 (`trading_decision_engine.py`)

**파일**: `core/trading_decision_engine.py`

**함수**: `analyze_sell_decision()` → `_check_simple_stop_profit_conditions()`

```python
def _check_simple_stop_profit_conditions(self, trading_stock, current_price):
    """간단한 손절/익절 조건 확인"""
    
    buy_price = trading_stock.position.avg_price
    profit_rate_percent = (current_price - buy_price) / buy_price * 100
    
    # trading_config.json에서 로드
    config = load_trading_config()
    take_profit_percent = config.risk_management.take_profit_ratio * 100  # 3.5%
    stop_loss_percent = config.risk_management.stop_loss_ratio * 100      # 2.5%
    
    # 익절
    if profit_rate_percent >= take_profit_percent:
        return True, f"익절 {profit_rate_percent:.1f}%"
    
    # 손절
    if profit_rate_percent <= -stop_loss_percent:
        return True, f"손절 {profit_rate_percent:.1f}%"
```

**데이터 소스**: `intraday_manager.get_cached_current_price()` (현재가 API)

**실행 주기**: 5초마다 (매매 판단 루프)

### 6.2 시뮬레이션 (`signal_replay.py`)

**함수**: `simulate_trades()`

```python
# 매수 후 1분봉마다 체크
for i, row in remaining_data.iterrows():
    candle_high = row['high']
    candle_low = row['low']
    candle_close = row['close']
    
    # 익절 목표가
    profit_target_price = buy_price * (1.0 + target_profit_rate)
    # 손절 목표가
    stop_loss_target_price = buy_price * (1.0 - stop_loss_rate)
    
    # 1. 신호강도별 익절 - 1분봉 고가가 익절 목표가 터치
    if candle_high >= profit_target_price:
        sell_price = profit_target_price
        sell_reason = f"profit_{target_profit_rate*100:.1f}pct"
        break
    
    # 2. 신호강도별 손절 - 1분봉 저가가 손절 목표가 터치
    if candle_low <= stop_loss_target_price:
        sell_price = stop_loss_target_price
        sell_reason = f"stop_loss_{stop_loss_rate*100:.1f}pct"
        break
    
    # 3. 15시 장마감
    if candle_time.hour >= 15 and candle_time.minute >= 0:
        sell_price = candle_close
        sell_reason = "market_close_15h"
        break
    
    # 4. 3분봉 기술적 분석 (3분 단위로만)
    if current_time.minute % 3 == 0:
        technical_sell, technical_reason = _check_technical_sell_signals(...)
        if technical_sell:
            sell_price = candle_close
            break
```

**데이터 소스**: 1분봉 고가/저가

**실행 주기**: 1분봉마다 체크

### 🔍 핵심 차이: 매도 판단 기준
| 항목 | 실시간 | 시뮬레이션 |
|------|--------|-----------|
| 판단 기준 | 현재가 (종가 기준) | 1분봉 고가/저가 |
| 체크 주기 | 5초 (연속) | 1분봉마다 |
| 익절 체결가 | 실제 체결가 | 목표가 (가정) |
| 손절 체결가 | 실제 체결가 | 손절가 (가정) |
| 15시 매도 | 15:00 이후 시장가 | 15:00 이후 종가 |

---

## ⚠️ 7. 중요한 차이점 정리

### 7.1 매도 타이밍 차이

**예시 상황**: 매수가 10,000원, 익절 +3.5% (10,350원)

**실시간**:
```
10:45:15 - 현재가: 10,340원 → 익절 미도달
10:45:20 - 현재가: 10,360원 → 익절 신호! → 매도 주문
10:45:25 - 체결가: 10,355원 (실제 체결가)
```

**시뮬레이션**:
```
10:45 1분봉: 고가 10,400원, 저가 10,300원, 종가 10,320원
→ 고가(10,400) >= 익절가(10,350) → 익절!
→ 매도가: 10,350원 (목표가로 가정)
```

**차이**:
- ✅ 실시간: 실제 체결가 10,355원
- ⚠️ 시뮬: 목표가 10,350원 (이상적 가정)

### 7.2 데이터 품질 차이

**실시간**:
- ⚠️ HTS 분봉 누락 가능성 있음
- ⚠️ API 지연으로 인한 데이터 불완전
- ⚠️ historical + realtime 병합 과정에서 중복/순서 이슈

**시뮬레이션**:
- ✅ 장 마감 후 완전한 데이터 수집
- ✅ 단일 소스로 일관성 보장
- ✅ 모든 분봉 완성됨

---

## 🎯 8. 결과가 다를 수 있는 시나리오

### 시나리오 1: 분봉 데이터 차이

**원인**: 실시간에서 HTS 분봉 누락 또는 API 지연

**현상**:
```
실시간: 10:39, 10:42, 10:45 (10:40, 10:41 누락)
시뮬: 10:39, 10:40, 10:41, 10:42, 10:45 (완전)
```

**결과**:
- 3분봉 개수 다름
- 신호 발생 시점 다를 수 있음
- candle_count < 3 경고 발생

### 시나리오 2: 매도가 차이

**원인**: 실시간은 현재가 기준, 시뮬은 1분봉 고가/저가 기준

**현상**:
```
실시간: 
  10:45:20 현재가 10,360원 → 익절 신호
  실제 체결: 10,355원

시뮬:
  10:45 1분봉 고가 10,400원 → 익절
  가정 체결: 10,350원 (목표가)
```

**결과**:
- 매도가 차이: 5~10원
- 수익률 차이: 0.05~0.1%

### 시나리오 3: 중복 제거 이슈

**원인**: historical + realtime 병합 시 중복/순서 문제

**현상**:
```
실시간:
  historical: [..., 10:36, 10:39]
  realtime: [10:39, 10:42]
  병합 전: [..., 10:36, 10:39, 10:39, 10:42]
  품질 검사 (정렬 안 됨): 10:39→10:39 누락 감지!

시뮬:
  단일 소스: [..., 10:36, 10:39, 10:42]
  정상
```

**해결책**: ✅ 이미 적용 (`_check_data_quality`에서 정렬 + 중복 제거)

### 시나리오 4: 3분봉 확정 타이밍

**원인**: 실시간은 현재 시간 기준, 시뮬은 과거 데이터

**현상**:
```
실시간 (10:44:30):
  마지막 3분봉: 10:39 (10:42는 미확정)
  
시뮬 (과거):
  마지막 3분봉: 15:27 (모두 확정)
```

**결과**:
- 실시간은 최신 신호를 놓칠 수 있음 (미확정)
- 시뮬은 모든 신호를 포함

---

## 🔧 9. 검증 방법

### 9.1 데이터 일치성 검증

```bash
# 1. 실시간 거래 실행 (15:30까지)
python main.py

# 2. 15:30에 자동 저장된 캐시와 시뮬 데이터 비교
python compare_realtime_vs_simulation_data.py --date 20251013
```

### 9.2 신호 생성 일치성 검증

```bash
# 특정 종목의 신호 생성 일치성 테스트
python verify_realtime_simulation_consistency.py --stock 003160 --date 20251013
```

### 9.3 실제 비교 시뮬레이션

```bash
# 실시간 수집 데이터로 시뮬레이션 실행
python utils\signal_replay.py --date 20251013 --export txt
```

---

## 📋 10. 핵심 결론

### 동일한 데이터를 사용해도 결과가 다를 수 있는 경우:

1. ✅ **매도가 차이** (가장 큰 원인)
   - 실시간: 현재가 기준 → 실제 체결가
   - 시뮬: 1분봉 고가/저가 → 목표가 가정
   - 영향: 수익률 0.05~0.5% 차이 가능

2. ✅ **타이밍 차이**
   - 실시간: 5초 주기 체크 → 미세한 타이밍 차이
   - 시뮬: 1분봉 단위 → 정확한 시점
   - 영향: 매수/매도 시점 최대 5초 차이

3. ⚠️ **데이터 불완전** (수정 완료)
   - 실시간: HTS 분봉 누락, API 지연
   - 해결: 15:30 완전한 데이터 저장, 품질 검사 강화

4. ⚠️ **중복/순서 이슈** (수정 완료)
   - 실시간: historical + realtime 병합
   - 해결: 품질 검사 시 정렬 + 중복 제거 추가

### 데이터가 완전히 동일하다면:

| 항목 | 일치 여부 | 비고 |
|------|-----------|------|
| 3분봉 변환 | ✅ 일치 | 동일 함수 사용 |
| 신호 생성 | ✅ 일치 | 동일 함수 사용 |
| 매수 신호 | ✅ 일치 | 동일 로직 |
| 매수 가격 | ✅ 일치 | 4/5가 동일 계산 |
| 매도 신호 | ✅ 일치 | 동일 손익비 |
| **매도 가격** | ❌ **다를 수 있음** | 현재가 vs 목표가 |
| 최종 수익률 | ⚠️ 유사 | 매도가 차이만큼 |

---

## 🚀 11. 권장 사항

### 11.1 데이터 일치성 보장

1. ✅ **15:30 자동 저장** (이미 구현됨)
   - `intraday_manager._save_minute_data_to_cache()`
   - cache/minute_data/{stock_code}_{date}.pkl

2. ✅ **DB 복원** (이미 구현됨)
   - `main.py._restore_todays_candidates()`
   - 프로그램 재시작 시 오늘 종목 복원

3. ✅ **품질 검사** (이미 구현됨)
   - 시간순 정렬 + 중복 제거
   - 분봉 누락 감지 및 재수집

### 11.2 비교 검증 프로세스

```bash
# Step 1: 실시간 거래 실행
python main.py

# Step 2: 15:30 자동 저장된 데이터 확인
ls cache/minute_data/*_20251013.pkl

# Step 3: 시뮬레이션 실행
python utils\signal_replay.py --date 20251013 --export txt

# Step 4: 데이터 비교
python compare_realtime_vs_simulation_data.py --date 20251013

# Step 5: 신호 일치성 검증
python verify_realtime_simulation_consistency.py --stock 003160 --date 20251013
```

### 11.3 불일치 허용 범위

**데이터가 완전 동일한 경우**:
- 신호 생성: 100% 일치 (동일 함수)
- 매수 시점: ±5초 허용 (5초 주기 차이)
- 매수 가격: 100% 일치 (4/5가)
- 매도 시점: ±1분 허용 (체크 주기 차이)
- **매도 가격**: 0.05~0.5% 차이 허용 (현재가 vs 목표가)
- **최종 수익률**: 0.1~1.0% 차이 허용

**데이터 불완전한 경우**:
- 분봉 누락: 신호 발생 시점 달라질 수 있음
- API 지연: 3분봉 확정 타이밍 다를 수 있음
- 허용 불가: 수동 재수집 필요

---

## 📊 12. 체크리스트

### 데이터 수집
- [x] 15:30 자동 저장 구현
- [x] 2개 분봉 수집으로 누락 방지
- [x] 품질 검사 시 정렬 + 중복 제거

### 로직 일치성
- [x] 3분봉 변환: 동일 함수
- [x] 신호 생성: 동일 함수
- [x] 손익비: 동일 설정 파일

### 검증 도구
- [x] compare_realtime_vs_simulation_data.py
- [x] verify_realtime_simulation_consistency.py
- [x] 차이점 분석 문서

### 향후 개선
- [ ] 매도가 차이 최소화 (현재가 API 대신 1분봉 사용 고려)
- [ ] 실시간 체결 정보를 DB에 저장하여 시뮬과 비교
- [ ] 일일 검증 자동화 스크립트

