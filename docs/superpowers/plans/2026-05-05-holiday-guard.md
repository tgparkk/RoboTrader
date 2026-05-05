# Holiday Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** macd_cross 라이브 매매 경로에 한국 공휴일 명시적 가드를 추가하고, 분봉 백필 prev_date 휴일 미스킵 버그를 수정한다.

**Architecture:** `MarketHours.is_trading_day()` 호출만 추가하고, 신규 헬퍼 `_previous_trading_day` 로 line 2397 의 weekday-only 루프를 교체한다. `_holiday_logged_date` 인스턴스 변수로 1회 로깅 정책 구현.

**Tech Stack:** Python 3.x, asyncio, pytest, pytest-asyncio, unittest.mock, pytz.

**Spec:** [docs/superpowers/specs/2026-05-05-holiday-guard-design.md](../specs/2026-05-05-holiday-guard-design.md)

---

## Task 1: `_previous_trading_day` 헬퍼 (TDD)

**Files:**
- Modify: `main.py` (DayTradingBot 클래스에 메서드 추가, 위치는 `_count_krx_trading_days_between` 근처 line 600 부근 권장)
- Create: `tests/integration/test_macd_cross_holiday_guard.py`

- [ ] **Step 1.1: 테스트 파일 스켈레톤 + 실패 테스트 1 작성**

Create `tests/integration/test_macd_cross_holiday_guard.py`:

```python
"""macd_cross 휴일 가드 회귀 방지 (2026-05-05).

수정 대상:
- `_previous_trading_day` 헬퍼 (KOREAN_HOLIDAYS + 주말 모두 스킵)
- `_evaluate_macd_cross_window` / `_macd_cross_exit_dispatcher` 진입부 휴일 가드
- 분봉 백필 prev_date 계산 (line 2397) 헬퍼로 교체
"""
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from config.market_hours import MarketHours, KOREAN_HOLIDAYS

KST = pytz.timezone('Asia/Seoul')


class _FakeBot:
    def __init__(self):
        self.logger = MagicMock()
        self._holiday_logged_date = None


def _bind(bot, *method_names):
    from main import DayTradingBot
    for name in method_names:
        setattr(bot, name, DayTradingBot.__dict__[name].__get__(bot, _FakeBot))


# ---------------------------------------------------------------------------
# Task 1: _previous_trading_day 헬퍼
# ---------------------------------------------------------------------------

def test_previous_trading_day_skips_weekend():
    """월요일에서 호출하면 직전 금요일을 반환 (토/일 스킵)."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    # 2026-05-04 (월) → 2026-05-01 (금)
    monday = KST.localize(datetime(2026, 5, 4, 9, 0))
    result = bot._previous_trading_day(monday)

    assert result.date() == date(2026, 5, 1)
```

- [ ] **Step 1.2: 실패 테스트 1 실행 (메서드 미존재로 실패 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_previous_trading_day_skips_weekend -v`

Expected: FAIL with `AttributeError: type object 'DayTradingBot' has no attribute '_previous_trading_day'`

- [ ] **Step 1.3: 헬퍼 구현 (main.py)**

`main.py` 의 `_count_krx_trading_days_between` 메서드(line 553~600) 직후에 추가:

```python
    def _previous_trading_day(self, dt: datetime) -> datetime:
        """주어진 dt 의 직전 영업일을 반환 (자기 자신 제외).

        KOREAN_HOLIDAYS + 주말 모두 스킵. 14일 안에 못 찾으면 ValueError.
        설/추석 대형 연휴(최대 6~7일) + KOREAN_HOLIDAYS 미등록 케이스 방어.
        """
        from datetime import timedelta
        candidate = dt - timedelta(days=1)
        for _ in range(14):
            if MarketHours.is_trading_day(dt=candidate):
                return candidate
            candidate -= timedelta(days=1)
        raise ValueError(
            f"_previous_trading_day: {dt.date()} 14일 내 영업일 없음 "
            f"(KOREAN_HOLIDAYS 갱신 필요?)"
        )
```

- [ ] **Step 1.4: 테스트 1 실행 (PASS 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_previous_trading_day_skips_weekend -v`

Expected: PASS

- [ ] **Step 1.5: 테스트 2 추가 (어린이날 스킵)**

`tests/integration/test_macd_cross_holiday_guard.py` 끝에 추가:

```python
def test_previous_trading_day_skips_holiday():
    """5/6 수요일에서 호출하면 5/5 어린이날을 스킵하고 5/4 월요일 반환."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    wed = KST.localize(datetime(2026, 5, 6, 9, 0))
    result = bot._previous_trading_day(wed)

    assert result.date() == date(2026, 5, 4)
    # KOREAN_HOLIDAYS 등록 확인
    assert '20260505' in KOREAN_HOLIDAYS
```

- [ ] **Step 1.6: 테스트 2 실행 (PASS 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_previous_trading_day_skips_holiday -v`

Expected: PASS

- [ ] **Step 1.7: 테스트 3 추가 (추석 연휴 스킵)**

`tests/integration/test_macd_cross_holiday_guard.py` 끝에 추가:

```python
def test_previous_trading_day_skips_long_holiday_chain():
    """9/28 월요일에서 호출하면 9/24~26 추석 + 9/27 일요일을 스킵하고 9/23 수요일 반환."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    mon = KST.localize(datetime(2026, 9, 28, 9, 0))
    result = bot._previous_trading_day(mon)

    assert result.date() == date(2026, 9, 23)
    # KOREAN_HOLIDAYS 등록 확인
    for holi in ('20260924', '20260925', '20260926'):
        assert holi in KOREAN_HOLIDAYS
```

- [ ] **Step 1.8: 테스트 3 실행 (PASS 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_previous_trading_day_skips_long_holiday_chain -v`

Expected: PASS

- [ ] **Step 1.9: 테스트 4 추가 (14일 cap ValueError)**

`tests/integration/test_macd_cross_holiday_guard.py` 끝에 추가:

```python
def test_previous_trading_day_raises_on_runaway(monkeypatch):
    """KOREAN_HOLIDAYS 가 모든 평일을 휴일로 마킹하면 14일 cap 으로 ValueError."""
    bot = _FakeBot()
    _bind(bot, '_previous_trading_day')

    # 30일치 평일을 모두 휴일로 monkeypatch
    fake_holidays = set()
    base = date(2026, 5, 1)
    for i in range(30):
        d = base - timedelta(days=i)
        fake_holidays.add(d.strftime('%Y%m%d'))

    monkeypatch.setattr('config.market_hours.KOREAN_HOLIDAYS', fake_holidays)

    dt = KST.localize(datetime(2026, 5, 1, 9, 0))
    with pytest.raises(ValueError, match='14일 내 영업일 없음'):
        bot._previous_trading_day(dt)
```

- [ ] **Step 1.10: 테스트 4 실행 (PASS 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_previous_trading_day_raises_on_runaway -v`

Expected: PASS

- [ ] **Step 1.11: Task 1 전체 4개 재실행 (그린 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py -v`

Expected: 4 passed

- [ ] **Step 1.12: Commit**

```bash
git add main.py tests/integration/test_macd_cross_holiday_guard.py
git commit -m "feat(main): _previous_trading_day 헬퍼 추가 (KOREAN_HOLIDAYS 스킵)"
```

---

## Task 2: 분봉 백필 prev_date 헬퍼 적용

**Files:**
- Modify: `main.py` line 2392~2399

- [ ] **Step 2.1: 현재 코드 확인**

Read `main.py` line 2390~2410. 현재 코드:

```python
            try:
                from datetime import timedelta
                import psycopg2
                from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
                _ct = now_kst()
                _prev = _ct - timedelta(days=1)
                while _prev.weekday() >= 5:
                    _prev -= timedelta(days=1)
                _prev_date = _prev.strftime('%Y%m%d')
```

- [ ] **Step 2.2: 헬퍼 호출로 교체**

`main.py` 위 블록을 다음으로 교체:

```python
            try:
                import psycopg2
                from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
                _ct = now_kst()
                _prev = self._previous_trading_day(_ct)
                _prev_date = _prev.strftime('%Y%m%d')
```

- [ ] **Step 2.3: 회귀 검증 (기존 macd_cross 테스트 그린 유지)**

Run: `python -m pytest tests/integration/test_macd_cross_premarket_sync.py tests/integration/test_macd_cross_paper_flow.py tests/integration/test_macd_cross_live_flow.py -v`

Expected: 모두 PASS

- [ ] **Step 2.4: Commit**

```bash
git add main.py
git commit -m "fix(main): 분봉 백필 prev_date 휴일 미스킵 버그 수정"
```

---

## Task 3: `_holiday_logged_date` 초기화 + `_evaluate_macd_cross_window` 가드 (TDD)

**Files:**
- Modify: `main.py` `__init__` (line 45 부근), `_evaluate_macd_cross_window` (line 815~)
- Modify: `tests/integration/test_macd_cross_holiday_guard.py`

- [ ] **Step 3.1: 실패 테스트 5 작성**

`tests/integration/test_macd_cross_holiday_guard.py` 끝에 추가:

```python
# ---------------------------------------------------------------------------
# Task 3: _evaluate_macd_cross_window 휴일 가드
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_macd_cross_window_skips_holiday():
    """5/5 어린이날 14:31 호출 시 매수 트리거 미실행 + 1회만 로그."""
    bot = _FakeBot()
    bot.decision_engine = MagicMock()
    bot.decision_engine.macd_cross_strategy = MagicMock()
    bot.decision_engine.macd_cross_strategy._cache = {'005930': MagicMock()}
    bot.decision_engine.execute_real_buy = AsyncMock()
    bot.db_manager = MagicMock()
    bot._macd_cross_mode = MagicMock(return_value='real')
    _bind(bot, '_evaluate_macd_cross_window')

    holiday_dt = KST.localize(datetime(2026, 5, 5, 14, 31))

    # 첫 호출: return + 로그 1회
    await bot._evaluate_macd_cross_window(holiday_dt)
    bot.decision_engine.execute_real_buy.assert_not_awaited()
    info_calls = [c for c in bot.logger.info.call_args_list
                  if '[휴일가드]' in str(c)]
    assert len(info_calls) == 1
    assert bot._holiday_logged_date == date(2026, 5, 5)

    # 두 번째 호출: 동일 날짜 → 로그 추가 안 됨
    bot.logger.reset_mock()
    await bot._evaluate_macd_cross_window(holiday_dt)
    bot.decision_engine.execute_real_buy.assert_not_awaited()
    info_calls = [c for c in bot.logger.info.call_args_list
                  if '[휴일가드]' in str(c)]
    assert len(info_calls) == 0
```

- [ ] **Step 3.2: 실패 테스트 5 실행 (가드 미존재로 실패 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_evaluate_macd_cross_window_skips_holiday -v`

Expected: FAIL — execute_real_buy 가 호출되거나 다른 에러

- [ ] **Step 3.3: `__init__` 에 `_holiday_logged_date` 초기화 추가**

`main.py` line 46 (`self.logger = setup_logger(__name__)`) 직후에 추가:

```python
        self._holiday_logged_date = None  # 휴일 가드 1회 로깅용 (KST date)
```

(주의: `__init__` 의 다른 인스턴스 변수들과 같은 들여쓰기로 추가. 정확한 위치는 `self.logger = ...` 라인 바로 다음.)

- [ ] **Step 3.4: `_evaluate_macd_cross_window` 진입부에 가드 삽입**

`main.py` `_evaluate_macd_cross_window` 함수 (line 815~). 현재 구조:

```python
    async def _evaluate_macd_cross_window(self, current_time):
        """..."""
        from config.strategy_settings import StrategySettings
        from backtests.common.execution_model import (
            BUY_COMMISSION, SLIPPAGE_ONE_WAY, ExecutionModel,
        )

        mode = self._macd_cross_mode()
        if mode == 'off' or self.decision_engine.macd_cross_strategy is None:
            return
        is_virtual = (mode == 'virtual')

        cfg_mc = StrategySettings.MacdCross
        hhmm = current_time.hour * 100 + current_time.minute
        if not (cfg_mc.ENTRY_HHMM_MIN <= hhmm <= cfg_mc.ENTRY_HHMM_MAX):
            return
```

`is_virtual = (mode == 'virtual')` 직후 + `cfg_mc = StrategySettings.MacdCross` 직전에 가드 삽입:

```python
        is_virtual = (mode == 'virtual')

        # 휴일 가드 (KOREAN_HOLIDAYS + 주말 차단)
        if not MarketHours.is_trading_day(dt=current_time):
            if self._holiday_logged_date != current_time.date():
                self.logger.info(
                    f"[휴일가드] {current_time.date()} 비영업일 — 매수 차단"
                )
                self._holiday_logged_date = current_time.date()
            return

        cfg_mc = StrategySettings.MacdCross
```

(`MarketHours` import 가 main.py 상단에 이미 있는지 확인 — 없으면 함수 내부 `from config.market_hours import MarketHours` 로 인라인 import)

- [ ] **Step 3.5: MarketHours import 확인**

Run: `grep -n "from config.market_hours import\|import MarketHours" main.py`

이미 import 되어 있으면 OK. 없으면 Step 3.4 의 가드 블록 첫 줄을 다음으로 교체:

```python
        from config.market_hours import MarketHours
        if not MarketHours.is_trading_day(dt=current_time):
```

- [ ] **Step 3.6: 테스트 5 실행 (PASS 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_evaluate_macd_cross_window_skips_holiday -v`

Expected: PASS

- [ ] **Step 3.7: 평일 회귀 — 기존 paper_flow 테스트 그린 유지**

Run: `python -m pytest tests/integration/test_macd_cross_paper_flow.py tests/integration/test_macd_cross_live_flow.py -v`

Expected: 모두 PASS (가드는 휴일에만 trip 되므로 평일 동작 무변)

- [ ] **Step 3.8: Commit**

```bash
git add main.py tests/integration/test_macd_cross_holiday_guard.py
git commit -m "feat(main): _evaluate_macd_cross_window 휴일 가드 추가"
```

---

## Task 4: `_macd_cross_exit_dispatcher` 가드 (TDD)

**Files:**
- Modify: `main.py` `_macd_cross_exit_dispatcher` (line 1690~)
- Modify: `tests/integration/test_macd_cross_holiday_guard.py`

- [ ] **Step 4.1: 실패 테스트 6 작성**

`tests/integration/test_macd_cross_holiday_guard.py` 끝에 추가:

```python
# ---------------------------------------------------------------------------
# Task 4: _macd_cross_exit_dispatcher 휴일 가드
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_macd_cross_exit_dispatcher_skips_holiday():
    """5/5 어린이날 09:01 호출 시 dispatcher 즉시 return + paper/live 미호출."""
    bot = _FakeBot()
    bot._macd_cross_paper_exit_task = AsyncMock()
    bot._macd_cross_live_exit_task = AsyncMock()
    bot._macd_cross_mode = MagicMock(return_value='real')
    _bind(bot, '_macd_cross_exit_dispatcher')

    holiday_dt = KST.localize(datetime(2026, 5, 5, 9, 1))
    with patch('main.now_kst', return_value=holiday_dt):
        result = await bot._macd_cross_exit_dispatcher()

    # 휴일이라 즉시 return True (가드 set 가능 — off 모드와 동일 의미)
    assert result is True
    bot._macd_cross_paper_exit_task.assert_not_awaited()
    bot._macd_cross_live_exit_task.assert_not_awaited()
    # 첫 호출이라 로그 1회
    info_calls = [c for c in bot.logger.info.call_args_list
                  if '[휴일가드]' in str(c)]
    assert len(info_calls) == 1
```

- [ ] **Step 4.2: 실패 테스트 6 실행 (가드 미존재로 실패 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_macd_cross_exit_dispatcher_skips_holiday -v`

Expected: FAIL — `_macd_cross_live_exit_task.assert_not_awaited()` 가 실패하거나 mock 설정 오류

- [ ] **Step 4.3: `_macd_cross_exit_dispatcher` 진입부에 가드 삽입**

`main.py` line 1703 (`mode = self._macd_cross_mode()`) **직전**에 가드 삽입:

```python
    async def _macd_cross_exit_dispatcher(self) -> bool:
        """macd_cross 청산 dispatcher — virtual/real 모드 분기.
        ...
        """
        # 휴일 가드 (KOREAN_HOLIDAYS + 주말 차단)
        current_time = now_kst()
        if not MarketHours.is_trading_day(dt=current_time):
            if self._holiday_logged_date != current_time.date():
                self.logger.info(
                    f"[휴일가드] {current_time.date()} 비영업일 — 청산 차단"
                )
                self._holiday_logged_date = current_time.date()
            return True  # 가드 set 가능 — off 모드와 동일 의미

        mode = self._macd_cross_mode()
        if mode == 'virtual':
            return await self._macd_cross_paper_exit_task()
        elif mode == 'real':
            return await self._macd_cross_live_exit_task()
        return True
```

(MarketHours import 는 Task 3 에서 이미 처리. 함수 docstring 은 기존 그대로 유지.)

- [ ] **Step 4.4: 테스트 6 실행 (PASS 확인)**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py::test_macd_cross_exit_dispatcher_skips_holiday -v`

Expected: PASS

- [ ] **Step 4.5: 평일 회귀 — 기존 premarket_sync 테스트 그린 유지**

Run: `python -m pytest tests/integration/test_macd_cross_premarket_sync.py -v`

Expected: 모두 PASS (가드는 휴일에만 trip)

- [ ] **Step 4.6: Commit**

```bash
git add main.py tests/integration/test_macd_cross_holiday_guard.py
git commit -m "feat(main): _macd_cross_exit_dispatcher 휴일 가드 추가"
```

---

## Task 5: 전체 회귀 + 수동 검증

**Files:**
- 없음 (검증만)

- [ ] **Step 5.1: 신규 holiday_guard 테스트 6건 전체 그린 확인**

Run: `python -m pytest tests/integration/test_macd_cross_holiday_guard.py -v`

Expected: 6 passed

- [ ] **Step 5.2: macd_cross 테스트 13건 전체 그린 확인**

Run: `python -m pytest tests/integration/test_macd_cross_*.py -v`

Expected: 13(기존) + 6(신규) = 19 passed (또는 그 이상)

- [ ] **Step 5.3: 전체 217건 회귀 그린 확인**

Run: `python -m pytest tests/`

Expected: All passed (failure 발생 시 롤백 또는 원인 분석)

- [ ] **Step 5.4: 수동 검증 가이드 (다음 영업일 5/6 수요일에 실행)**

봇 가동 후 다음 명령으로 검증:

```bash
# 5/5 휴일 봇 가동 시 (만약 가동했다면)
grep "휴일가드" logs/trading_20260505.log         # 1회만 출력 기대
grep "매수 주문\|시장가 청산" logs/trading_20260505.log  # 0건 기대

# 5/6 수요일 첫 가동 시 분봉 백필 prev_date 검증
grep "분봉.*백필\|prev_date\|전일.*분봉" logs/trading_20260506.log
# → prev_date 가 20260504 (월) 인지 확인 (5/5 어린이날 스킵 검증)
```

- [ ] **Step 5.5: Final commit (있을 경우만)**

회귀 중 발견된 사소한 lint/format 변경이 있다면:

```bash
git add -p   # 의도한 변경만 선택
git commit -m "chore: holiday-guard 후속 정리"
```

없으면 skip.

---

## 완료 기준

- [ ] 신규 테스트 6건 모두 PASS
- [ ] 기존 macd_cross 13건 회귀 PASS
- [ ] 전체 tests/ PASS
- [ ] `main.py` 변경 4곳 commit 완료 (Task 1~4 = 4 commits)
- [ ] 수동 검증 가이드 (Step 5.4) 5/6 수요일 첫 가동 시 실행
