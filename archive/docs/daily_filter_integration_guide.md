# 일봉 필터 실시간 통합 가이드

## 목적
실시간 거래 시 일봉 필터가 모든 종목에 대해 정상 작동하도록 자동 데이터 수집 구현

## 구현 개요

### 문제
- 신규 선정 종목의 경우 일봉 데이터가 없으면 필터가 작동하지 않음
- 승률 52.7% 대신 49.6%로 저하 (필터 효과 상실)

### 해결 방안
- 종목 선정 시점에 일봉 데이터 자동 수집
- 이미 최신 데이터가 있으면 스킵 (중복 방지)

---

## 구현 위치

### 옵션 1: candidate_selector.py에 통합 (추천)

**파일:** `core/candidate_selector.py`

**적용 위치:** 종목 선정 직후

#### 구현 예시

```python
# core/candidate_selector.py

class CandidateSelector:
    def __init__(self, ...):
        # 기존 코드
        ...

        # 일봉 데이터 헬퍼 추가
        from utils.daily_data_helper import ensure_daily_data_for_stock
        self.ensure_daily_data = ensure_daily_data_for_stock

    async def select_candidates(self):
        """종목 선정 (기존 로직)"""
        # ... 기존 선정 로직 ...

        # 선정 완료 후
        selected_stocks = [...]  # 선정된 종목 리스트

        # 🆕 일봉 데이터 확보
        for stock in selected_stocks:
            try:
                # 비동기 안전하게 실행
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.ensure_daily_data,
                    stock.code
                )
                await asyncio.sleep(0.05)  # API 제한
            except Exception as e:
                self.logger.warning(f"일봉 데이터 수집 실패: {stock.code} - {e}")

        return selected_stocks
```

**장점:**
- 종목 선정과 동시에 데이터 확보
- 이후 매수 신호에서 즉시 필터 적용 가능

**단점:**
- 종목 선정 시간 약간 증가 (종목당 0.1초)

---

### 옵션 2: main.py에 통합

**파일:** `main.py`

**적용 위치:** 장 시작 전 또는 종목 선정 직후

#### 구현 예시 A: 장 시작 전 일괄 수집

```python
# main.py

async def pre_market_routine():
    """장 시작 전 루틴 (08:30~09:00)"""
    from utils.daily_data_helper import ensure_daily_data_for_candidates_async
    import sqlite3

    logger.info("🔄 일봉 데이터 사전 수집 시작")

    # 최근 7일 후보 종목 조회
    conn = sqlite3.connect('data/robotrader.db')
    cursor = conn.execute("""
        SELECT DISTINCT stock_code
        FROM candidate_stocks
        WHERE selection_date >= date('now', '-7 days')
    """)
    stock_codes = [row[0] for row in cursor.fetchall()]
    conn.close()

    # 일괄 수집
    results = await ensure_daily_data_for_candidates_async(stock_codes)

    success = sum(1 for v in results.values() if v)
    logger.info(f"✅ 일봉 데이터 수집 완료: {success}/{len(stock_codes)}건")


async def main():
    # 장 시작 전 루틴 실행
    await pre_market_routine()

    # 기존 메인 루프
    ...
```

#### 구현 예시 B: 종목 선정 직후 수집

```python
# main.py

async def on_candidate_selected(stock_code: str):
    """종목 선정 콜백"""
    from utils.daily_data_helper import ensure_daily_data_async

    # 일봉 데이터 확보
    await ensure_daily_data_async(stock_code, sleep_interval=0.05)

    # 기존 로직
    ...
```

**장점:**
- main.py에서 전체 흐름 통제
- 디버깅 편리

**단점:**
- 코드 분산

---

### 옵션 3: trading_decision_engine.py에 통합

**파일:** `core/trading_decision_engine.py`

**적용 위치:** 매수 신호 검증 직전 (fallback)

#### 구현 예시

```python
# core/trading_decision_engine.py

def check_buy_signal(self, stock_code, ...):
    """매수 신호 검증"""

    # 🆕 일봉 데이터 확보 (fallback)
    if self.use_advanced_filter:
        from utils.daily_data_helper import ensure_daily_data_for_stock
        ensure_daily_data_for_stock(stock_code)

    # 기존 검증 로직
    ...
```

**장점:**
- 최후 안전망
- 다른 옵션과 병행 가능

**단점:**
- 매수 신호마다 확인 (약간의 지연)
- 이미 데이터 있으면 스킵되므로 실제 영향은 미미

---

## 권장 구현 방식

### 최종 권장: 옵션 1 (candidate_selector.py) + 옵션 3 (fallback)

**이유:**
1. 종목 선정 시 데이터 확보 → 대부분 케이스 커버
2. 매수 신호 시 fallback 확인 → 누락 방지
3. 중복 확인은 캐시로 빠르게 스킵

---

## 단계별 구현

### Step 1: 헬퍼 함수 테스트

```bash
# 헬퍼 함수 정상 작동 확인
python test_daily_data_helper.py
```

**예상 출력:**
```
======================================================================
테스트 1: 단일 종목 일봉 데이터 확보
======================================================================

종목: 005930
✅ 일봉 데이터 수집 완료: 005930 (30일)
✅ 성공: 005930 일봉 데이터 확보

======================================================================
테스트 2: 일봉 데이터 커버리지 확인
======================================================================

최근 7일 후보 종목: 15개

📊 커버리지 리포트:
  - 총 종목: 15개
  - 데이터 최신: 12개 (80.0%)
  - 데이터 없음: 3개
  - 데이터 오래됨: 0개
```

### Step 2: candidate_selector.py 수정

**before:**
```python
# core/candidate_selector.py
async def select_candidates(self):
    # 선정 로직
    selected = [...]
    return selected
```

**after:**
```python
# core/candidate_selector.py
async def select_candidates(self):
    # 선정 로직
    selected = [...]

    # 🆕 일봉 데이터 확보
    from utils.daily_data_helper import ensure_daily_data_for_stock
    import asyncio

    for stock in selected:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, ensure_daily_data_for_stock, stock.code
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            self.logger.warning(f"일봉 데이터 수집 실패: {stock.code} - {e}")

    return selected
```

### Step 3: (선택) trading_decision_engine.py fallback 추가

**위치:** `check_buy_signal` 함수 시작 부분

```python
# core/trading_decision_engine.py
def check_buy_signal(self, stock_code, ...):
    # 🆕 일봉 데이터 fallback 확보
    if self.use_advanced_filter and hasattr(self, 'advanced_filter_manager'):
        if self.advanced_filter_manager._daily_cache:
            from utils.daily_data_helper import ensure_daily_data_for_stock
            ensure_daily_data_for_stock(stock_code)

    # 기존 로직
    ...
```

### Step 4: 실시간 테스트

```bash
# 실시간 봇 실행
python main.py

# 로그 모니터링 (별도 터미널)
tail -f logs/trading_*.log | grep "일봉"
```

**예상 로그:**
```
[09:05:23] 일봉 데이터 최신: 005930 (최근: 20260130)
[09:05:24] ✅ 일봉 데이터 수집 완료: 000660 (28일)
[09:12:45] ✅ 005930 고급 필터 통과
[09:13:12] 🔰 000660 고급 필터 차단: daily_volume_ratio - 전일 거래량 비율 1.20x < 최소 1.50x
```

### Step 5: 효과 검증

#### 데이터 커버리지 확인
```bash
python test_daily_data_helper.py
```

#### 필터 적용 확인
```bash
python test_daily_filter.py
```

#### 실거래 로그 확인
```bash
grep "고급 필터 차단" logs/trading_*.log | grep "daily_" | wc -l
# 일봉 필터로 차단된 신호 수 확인
```

---

## 성능 영향 분석

### API 호출 추가

**시나리오:** 하루 10개 종목 선정

- 기존 API 호출: ~100회 (분봉 데이터 등)
- 추가 API 호출: ~10회 (일봉 데이터, 신규 종목만)
- 증가율: +10%
- 시간 증가: ~1초 (종목 선정 시점, 비동기 처리)

### 메모리 사용

- DuckDB 캐시: ~15MB (변화 없음)
- 추가 메모리: 없음

### 지연 시간

- 종목 선정: +0.1초/종목 (이미 데이터 있으면 즉시 스킵)
- 매수 신호: 변화 없음 (DuckDB 조회 1ms 이하)

---

## 트러블슈팅

### Q1: 일봉 데이터 수집이 실패합니다

**원인:**
- API 키 만료
- 네트워크 오류
- 종목 코드 오류

**해결:**
```python
# 로그 확인
tail -f logs/trading_*.log | grep "일봉 데이터"

# 수동 테스트
python -c "
from utils.daily_data_helper import ensure_daily_data_for_stock
ensure_daily_data_for_stock('005930')
"
```

### Q2: 일봉 필터가 작동하지 않습니다

**확인 사항:**
1. ACTIVE_DAILY_PRESET 설정 확인
2. 일봉 데이터 존재 확인
3. 로그 메시지 확인

```bash
# 1. 설정 확인
python test_daily_filter.py

# 2. 데이터 확인
python test_daily_data_helper.py

# 3. 로그 확인
grep "일봉 필터" logs/trading_*.log
```

### Q3: 성능이 느려졌습니다

**원인:**
- 너무 많은 종목에 대해 동시 수집

**해결:**
```python
# candidate_selector.py
# 병렬 처리 대신 순차 처리 + 스킵 로직
for stock in selected:
    if is_new_stock(stock):  # 신규 종목만
        ensure_daily_data_for_stock(stock.code)
```

---

## 체크리스트

### 구현 전
- [ ] `utils/daily_data_helper.py` 파일 확인
- [ ] `test_daily_data_helper.py` 실행 및 테스트
- [ ] 기존 일봉 데이터 커버리지 확인

### 구현 중
- [ ] `core/candidate_selector.py` 수정
- [ ] (선택) `core/trading_decision_engine.py` fallback 추가
- [ ] 로그 메시지 추가

### 구현 후
- [ ] 테스트 환경에서 실행
- [ ] 일봉 데이터 수집 로그 확인
- [ ] 필터 차단 로그 확인 (daily_ 관련)
- [ ] 성능 영향 확인 (지연 시간)
- [ ] 실거래 적용

---

## 참고 문서

- [daily_filter_realtime_check.md](daily_filter_realtime_check.md) - 실시간 동작 점검 보고서
- [daily_filter_usage.md](daily_filter_usage.md) - 일봉 필터 사용 가이드
- [일봉필터_사용법.md](../일봉필터_사용법.md) - 빠른 시작 가이드
