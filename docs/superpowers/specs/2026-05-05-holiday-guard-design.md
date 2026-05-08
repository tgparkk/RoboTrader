# Holiday Guard 설계서

- **작성일**: 2026-05-05 (어린이날, 휴일 점검 중 발견)
- **대상**: macd_cross 라이브 매매 경로
- **트리거 이슈**: `MarketHours.is_trading_day()` 가 구현되어 있으나 `main.py` 어디서도 호출되지 않음. 휴일에는 KIS API·분봉 미수집·universe 빈 캐시 등 자연 차단 메커니즘에 의존 중. 명시적 가드 부재로 인한 잠재 위험 + 분봉 백필 prev_date 휴일 미스킵 버그 동시 해결.

---

## 1. 아키텍처 개요

### 1.1 목적

한국 공휴일에 macd_cross 매수/매도 트리거가 실행되지 않도록 명시적 가드를 추가하고, 휴일 다음 영업일 데이터 백필 시 prev_date 가 휴일로 잡히는 버그를 차단한다.

### 1.2 원칙

- `MarketHours.is_trading_day()` 는 이미 `KOREAN_HOLIDAYS` + 주말을 모두 처리하므로 **신규 로직 추가 없이 호출만 박는다**
- 봇 가동 자체는 차단하지 않음 (휴일에 켜놔도 무해)
- 자연 차단 메커니즘(KIS 분봉 미수집 → universe 비어 자연 종료)은 그대로 두고 그 위에 "안전한 명시적 가드" 한 겹 추가

### 1.3 보유기간 정책 (변경 없음, 명시화)

D+2 청산은 영업일 기준. 공휴일·주말은 카운트되지 않으며 청산이 자동으로 다음 영업일로 이연된다. `_count_krx_trading_days_between` (`main.py:553~600`) 의 DB-driven 카운팅으로 자연 처리되며 추가 코드 불필요.

**예시** (5/4 월 매수, D+2 청산):

| 날짜 | morning trigger | past_count | today_count | days_held | 결과 |
|------|----|----|----|----|----|
| 5/5 화 어린이날 | **휴일가드 차단** (신규) | — | — | — | 트리거 미실행 |
| 5/6 수 09:01 | 실행 | 0 (5/5 휴일 row 없음) | 1 | 1 | D+2 미달, 보호 |
| 5/7 목 09:01 | 실행 | 1 (5/6 row) | 1 | 2 | D+2 도달, 청산 |

### 1.4 변경 영역

`main.py` 단일 파일:
1. `_evaluate_macd_cross_window` — 진입부 휴일 가드
2. `_macd_cross_exit_dispatcher` — 진입부 휴일 가드
3. line 2397~2399 분봉 백필 prev_date 계산 — `is_trading_day()` 기반 헬퍼로 교체
4. 헬퍼 `_previous_trading_day()` 신규 추가

---

## 2. 컴포넌트 상세

### 2.1 신규 헬퍼

**`RoboTrader._previous_trading_day(dt: datetime) -> datetime`** (인스턴스 메서드)

- 주어진 `dt` 의 직전 영업일 반환 (자기 자신 제외)
- `MarketHours.is_trading_day()` 가 True 가 될 때까지 `timedelta(days=-1)` 반복
- 안전장치: 최대 14일 거슬러 올라가도 못 찾으면 `ValueError` (설/추석 대형 연휴 + KOREAN_HOLIDAYS 미등록 케이스 방어)
- line 2397 의 인라인 `while` 루프 대체용

```python
def _previous_trading_day(self, dt: datetime) -> datetime:
    """주어진 dt 의 직전 영업일을 반환 (자기 자신 제외).

    KOREAN_HOLIDAYS + 주말 모두 스킵. 14일 안에 못 찾으면 ValueError.
    """
    from datetime import timedelta
    candidate = dt - timedelta(days=1)
    for _ in range(14):
        if MarketHours.is_trading_day(dt=candidate):
            return candidate
        candidate -= timedelta(days=1)
    raise ValueError(f"_previous_trading_day: {dt} 14일 내 영업일 없음 (KOREAN_HOLIDAYS 갱신 필요?)")
```

### 2.2 1회 로깅 인프라

**`RoboTrader._holiday_logged_date: Optional[date]`** (인스턴스 변수)

- `__init__` 에서 `None` 초기화
- 가드가 첫 차단할 때 today 저장 → 같은 날 두 번째 호출부터는 로그 생략
- 자정 넘어가면 새 날짜라 자동 reset (별도 reset 코드 불필요)

**가드 호출 패턴** (재사용 가능한 4줄):

```python
if not MarketHours.is_trading_day(dt=current_time):
    if self._holiday_logged_date != current_time.date():
        self.logger.info(f"[휴일가드] {current_time.date()} 비영업일 — {trigger_name} 차단")
        self._holiday_logged_date = current_time.date()
    return
```

### 2.3 변경 지점 3곳

| # | 위치 | 변경 |
|---|------|------|
| 1 | `_evaluate_macd_cross_window` (line 815~) | 함수 진입부 시간 윈도우 체크(line 840) **직전**에 휴일 가드 삽입. trigger_name="매수" |
| 2 | `_macd_cross_exit_dispatcher` (line 1690~) | 함수 진입부 첫 줄에 휴일 가드 삽입. trigger_name="청산". `now_kst()` 사용 (current_time 인자 없음). 일관성·로그 노이즈 감소 위해 가드 추가 (자연 차단되는 경로지만 명시화) |
| 3 | line 2392~2399 (분봉 백필 prev_date) | `while _prev.weekday() >= 5: _prev -= timedelta(days=1)` → `_prev = self._previous_trading_day(_ct)` 한 줄로 교체 |

### 2.4 가드 미적용 영역 (의도적, YAGNI)

- `_pre_market_task` — 휴일에 NXT 스냅샷 시도해도 KIS 가 자연 거부, 비용 무시 가능 수준
- `_data_collection_task` / `_system_monitoring_task` 의 분봉 수집 — KIS 가 자연 거부, 별도 가드 추가 시 코드 복잡도만 증가
- `_count_krx_trading_days_between` — DB-driven 으로 이미 휴일 자동 스킵 (§1.3 참조)

### 2.5 자료 흐름

```
14:31~ system_monitoring_task tick
  → _evaluate_macd_cross_window(current_time)
    → [신규] is_trading_day(current_time)? No → [1회 로깅] return
    → (기존 로직)

09:01~ trading_decision_task tick (D+2 morning)
  → _macd_cross_exit_dispatcher()
    → [신규] is_trading_day(now_kst())? No → [1회 로깅] return
    → (기존 로직)

매일 첫 가동 시 분봉 백필 prev_date 계산
  → _previous_trading_day(now_kst()) [신규]
    → 5/6 수요일 가동 시: 5/5 → 휴일 → 5/4 월 반환 ✅
    → 기존: 5/6 → 5/5 화 (휴일이지만 평일이라 통과) → 잘못된 prev_date ❌
```

---

## 3. 테스트 전략

### 3.1 신규 테스트 파일

**`tests/integration/test_macd_cross_holiday_guard.py`**

기존 macd_cross 테스트 13건과 동일 디렉토리·네이밍 컨벤션.

### 3.2 테스트 케이스 (6건)

| # | 테스트명 | 검증 내용 |
|---|---------|----------|
| 1 | `test_previous_trading_day_skips_weekend` | `_previous_trading_day(2026-05-04 월)` → `2026-05-01 금` 반환 |
| 2 | `test_previous_trading_day_skips_holiday` | `_previous_trading_day(2026-05-06 수)` → `2026-05-04 월` 반환 (5/5 어린이날 스킵) |
| 3 | `test_previous_trading_day_skips_long_holiday_chain` | `_previous_trading_day(2026-09-28 월)` → `2026-09-23 수` 반환 (9/24~26 추석 + 9/27 일 스킵) |
| 4 | `test_previous_trading_day_raises_on_runaway` | 14일 거슬러 못 찾으면 `ValueError` (KOREAN_HOLIDAYS 를 monkeypatch 로 비워서 검증) |
| 5 | `test_evaluate_macd_cross_window_skips_holiday` | 5/5 14:31 datetime mock 주입 → `decision_engine.execute_real_buy` / `db_manager.save_virtual_buy` 모두 0회 호출 + 첫 호출 시 INFO 로그 발생 + 두 번째 호출 시 로그 추가 발생 안 함 |
| 6 | `test_macd_cross_exit_dispatcher_skips_holiday` | 5/5 09:01 datetime mock → dispatcher 가 immediate return, 매도 주문 0회 |

### 3.3 기존 테스트 회귀 방지

- `pytest tests/integration/test_macd_cross_*.py` 13건 전체 재실행 → 평일 동작 무변화 확인
- `pytest tests/` 217건 전체 실행 → 그린 유지

### 3.4 모킹 전략

- `_evaluate_macd_cross_window(current_time)` 는 인자로 5/5 datetime 직접 전달
- `_macd_cross_exit_dispatcher` 는 내부에서 `now_kst()` 호출 — `monkeypatch.setattr('main.now_kst', lambda: ...)` 로 처리
- DB·KIS API 는 `Mock()` 으로 대체 (기존 macd_cross 테스트 패턴)

### 3.5 수동 검증

- 2026-05-05(어린이날) 봇 가동 후 로그 확인:
  - `grep "휴일가드" logs/trading_20260505.log` → 1회만 출력
  - `grep "매수 주문\|시장가 청산" logs/trading_20260505.log` → 0건
- 5/6 수요일 봇 시작 시 분봉 백필 prev_date 가 `20260504` (월) 인지 로그로 확인

---

## 4. 롤아웃 & 리스크

### 4.1 배포 절차

1. 신규 브랜치 `feat/holiday-guard` 에서 작업
2. `pytest tests/integration/test_macd_cross_holiday_guard.py` + `pytest tests/` 그린 확인
3. main merge → 다음 영업일(5/6 수) 가동 전 배포
4. 5/5 는 휴일이므로 봇이 안 돌아도 무관, 5/6 수요일 첫 가동 시 즉시 검증

### 4.2 리스크 평가

| 항목 | 영향도 | 완화책 |
|------|--------|--------|
| 가드 오작동으로 영업일에 매수 차단 | **높음** (수익 손실) | 단위 테스트 + 평일 회귀 217건 |
| `_previous_trading_day` 무한 루프 | 낮음 | 14일 cap + ValueError |
| `_holiday_logged_date` 동시성 race | 무시 가능 | 단일 asyncio 이벤트 루프(협조적 멀티태스킹). 두 태스크가 동일 날짜에 거의 동시 호출해도 idempotent 할당이라 무해. 최악 케이스 = 같은 날짜를 2회 INFO 로그(노이즈 1줄). |
| KOREAN_HOLIDAYS 미등록 휴일 (2028+) | 낮음 | `config/market_hours.py:12~14` 주석에 갱신 알람 명시, 별도 작업 |

### 4.3 롤백 전략

- 단순 revert 가능 (3개 함수의 진입부 가드만 추가, 인터페이스 변경 없음)
- 헬퍼 `_previous_trading_day` 는 새 메서드라 제거해도 회귀 없음
- 분봉 백필 line 2397 교체는 의미상 동등 + 더 정확 → 롤백해도 기존 버그(휴일 미스킵)로 돌아갈 뿐

### 4.4 성공 기준

- 5/5 휴일 봇 가동 시 매수/매도 0건 + `[휴일가드]` 로그 1회 출력
- 5/6 수요일 정상 매매 재개 + 분봉 백필 prev_date = `20260504`
- 회귀 테스트 217건 그린 유지

---

## 5. 참고

- `config/market_hours.py:15~50` — KOREAN_HOLIDAYS set (2025~2027)
- `config/market_hours.py:159~186` — `is_trading_day()` 구현
- `main.py:553~600` — `_count_krx_trading_days_between` (DB-driven 보유기간 카운트)
- `docs/macd_cross_operation.md` — macd_cross 운영 정책
- `CLAUDE.md` — 안전장치 표
