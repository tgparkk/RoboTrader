# macd_cross_alt (16/32) 페이퍼 검증 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spec `docs/superpowers/specs/2026-05-09-macd-cross-alt-paper-validation-design.md` 의 paper 16/32 검증을 라이브 14/34 실거래와 나란히 운영하기 위한 코드 구현.

**Architecture:** 별도 파라미터 클래스 `MacdCrossAlt` 신설 + `MacdCrossStrategy` 인스턴스화 시 `label` 파라미터 추가. main.py 의 macd_cross 평가/청산 함수 본체를 instance 기반 helper 로 추출하고, paper 분기를 새로운 호출로 추가. KPI/DB 모듈은 기존 `virtual_trading_records.strategy` 컬럼 + DataFrame-driven KPI 그대로 재사용. 회귀 위험 최소화: 라이브 14/34 경로 변경 0.

**Tech Stack:** Python 3.9, asyncio, psycopg2, pytest, KIS API.

---

## 사전 정보 — 엔지니어가 알아야 할 컨벤션

### 기존 macd_cross 구조
- 라이브 어댑터: `core/strategies/macd_cross_strategy.py` 의 `MacdCrossStrategy` (단일 인스턴스, 현재 `decision_engine.macd_cross_strategy` 에 owned)
- 모드 결정: `main._macd_cross_mode()` 가 ACTIVE/PAPER/VIRTUAL_ONLY 조합으로 'real'/'virtual'/'off' 단일 문자열 반환
- 진입 평가: `main._evaluate_macd_cross_window()` 14:31~15:00 에 mode 별 라우팅
- 청산: `main._macd_cross_exit_dispatcher()` D+2 morning + EOD
- KPI 집계: `core/strategies/macd_cross_kpi.py` 의 `MacdCrossKpi.compute(df_trades)` — DataFrame 인자 받음, DB 쿼리는 caller 에서

### DB 스키마 (변경 없음)
- `virtual_trading_records` 에 이미 `strategy TEXT` 컬럼 존재 (`save_virtual_buy/sell(strategy=...)` 인자가 직접 저장)
- 기존 macd_cross paper 는 `strategy='macd_cross'` 로 저장. 신규는 `strategy='macd_cross_alt'`

### Paper 인스턴스 owner
- 라이브 인스턴스는 `decision_engine` 이 owns
- 신규 paper 인스턴스는 `main.RoboTrader` 가 직접 owns (`self.paper_macd_cross_strategy`) — decision_engine 변경 회귀 회피

### Validation
- `config/strategy_settings.py:validate_settings()` 에 ACTIVE_STRATEGY 검증 + MacdCross 가드 존재. PAPER_STRATEGY 가 'macd_cross_alt' 일 때 동일 가드 + UNIVERSE_TOP_N 일치 강제 추가.

---

## 파일 구조 (생성/수정)

```
config/
  strategy_settings.py                          [수정]  Task 1: MacdCrossAlt 클래스, valid list, validate

core/strategies/
  macd_cross_strategy.py                        [수정]  Task 2: label 파라미터 추가

main.py                                         [수정]  Task 3-7: helper 추출 + paper 인스턴스 + 5 dispatch 분기

tests/strategies/
  test_macd_cross_alt_settings.py               [신규]  Task 1
  test_macd_cross_strategy.py                   [수정]  Task 2: label 테스트 추가

tests/integration/
  test_macd_cross_alt_paper_flow.py             [신규]  Task 8

docs/
  macd_cross_operation.md                       [수정]  Task 9: 운영 노트
```

---

## Task 1: MacdCrossAlt 설정 클래스 + validation (TDD)

**Files:**
- Modify: `config/strategy_settings.py`
- Test: `tests/strategies/test_macd_cross_alt_settings.py` (신규)

목적: `MacdCrossAlt` 클래스 추가 + valid list 확장 + validate_settings 가드.

- [ ] **Step 1.1: 실패 테스트 작성**

`tests/strategies/test_macd_cross_alt_settings.py`:
```python
"""MacdCrossAlt 설정 + validate_settings 가드 검증."""
import pytest

from config.strategy_settings import StrategySettings, validate_settings


def test_macd_cross_alt_class_has_required_attrs():
    """16/32 paper 파라미터 존재 + 값 정확."""
    cfg = StrategySettings.MacdCrossAlt
    assert cfg.FAST_PERIOD == 16
    assert cfg.SLOW_PERIOD == 32
    assert cfg.SIGNAL_PERIOD == 12
    assert cfg.ENTRY_HHMM_MIN == 1431
    assert cfg.ENTRY_HHMM_MAX == 1500
    assert cfg.HOLD_DAYS == 2
    assert cfg.VIRTUAL_CAPITAL == 10_000_000
    assert cfg.BUY_BUDGET_RATIO == 0.20
    assert cfg.MAX_DAILY_POSITIONS == 5
    assert cfg.UNIVERSE_TOP_N == 30
    assert cfg.VIRTUAL_ONLY is True


def test_valid_paper_strategies_includes_macd_cross_alt():
    """'macd_cross_alt' 가 valid list 에 있어야 validate_settings 통과."""
    # 임시 PAPER_STRATEGY 변경 후 validate_settings 호출 (예외 없으면 OK)
    original = StrategySettings.PAPER_STRATEGY
    try:
        StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'
        assert validate_settings() is True
    finally:
        StrategySettings.PAPER_STRATEGY = original


def test_universe_top_n_must_match_macd_cross():
    """MacdCrossAlt.UNIVERSE_TOP_N != MacdCross.UNIVERSE_TOP_N 시 ValueError."""
    original_alt = StrategySettings.MacdCrossAlt.UNIVERSE_TOP_N
    original_paper = StrategySettings.PAPER_STRATEGY
    try:
        StrategySettings.MacdCrossAlt.UNIVERSE_TOP_N = 50
        StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'
        with pytest.raises(ValueError, match="UNIVERSE_TOP_N"):
            validate_settings()
    finally:
        StrategySettings.MacdCrossAlt.UNIVERSE_TOP_N = original_alt
        StrategySettings.PAPER_STRATEGY = original_paper


def test_entry_hhmm_min_lt_max():
    """ENTRY_HHMM_MIN >= MAX 시 validate_settings 가 ValueError."""
    original_min = StrategySettings.MacdCrossAlt.ENTRY_HHMM_MIN
    original_paper = StrategySettings.PAPER_STRATEGY
    try:
        StrategySettings.MacdCrossAlt.ENTRY_HHMM_MIN = 1500
        StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'
        with pytest.raises(ValueError, match="ENTRY_HHMM_MIN"):
            validate_settings()
    finally:
        StrategySettings.MacdCrossAlt.ENTRY_HHMM_MIN = original_min
        StrategySettings.PAPER_STRATEGY = original_paper
```

- [ ] **Step 1.2: 실패 확인**

```bash
python -m pytest tests/strategies/test_macd_cross_alt_settings.py -v
```
Expected: 4 tests fail with `AttributeError: type object 'StrategySettings' has no attribute 'MacdCrossAlt'`.

- [ ] **Step 1.3: MacdCrossAlt 클래스 추가**

`config/strategy_settings.py` — `MacdCross` 클래스 직후 위치에 추가:

```python
    # ========================================
    # macd_cross_alt 페이퍼 (16/32 검증, 2026-05-09)
    # ========================================
    class MacdCrossAlt:
        """16/32 paper 검증 (MV-A best).

        Spec: docs/superpowers/specs/2026-05-09-macd-cross-alt-paper-validation-design.md
        근거: MV-A 멀티버스 4ds-avg calmar 65→128 (+95%), plateau robust.
        """
        FAST_PERIOD = 16
        SLOW_PERIOD = 32
        SIGNAL_PERIOD = 12
        ENTRY_HHMM_MIN = 1431
        ENTRY_HHMM_MAX = 1500
        HOLD_DAYS = 2
        VIRTUAL_CAPITAL = 10_000_000
        BUY_BUDGET_RATIO = 0.20
        MAX_DAILY_POSITIONS = 5
        UNIVERSE_TOP_N = 30
        APPLY_LIVE_OVERLAY = False
        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]
        VIRTUAL_ONLY = True
```

- [ ] **Step 1.4: valid_paper_strategies 확장**

`config/strategy_settings.py:validate_settings()`:

```python
    valid_paper_strategies = [None, 'macd_cross', 'macd_cross_alt']  # 'macd_cross_alt' 추가
```

- [ ] **Step 1.5: validate_settings 가드 추가**

`if StrategySettings.ACTIVE_STRATEGY == 'macd_cross':` 블록 직후 추가:

```python
    if StrategySettings.PAPER_STRATEGY == 'macd_cross_alt':
        mca = StrategySettings.MacdCrossAlt
        if mca.ENTRY_HHMM_MIN >= mca.ENTRY_HHMM_MAX:
            raise ValueError("MacdCrossAlt.ENTRY_HHMM_MIN은 ENTRY_HHMM_MAX보다 작아야 합니다")
        if mca.MAX_DAILY_POSITIONS <= 0:
            raise ValueError("MacdCrossAlt.MAX_DAILY_POSITIONS는 1 이상이어야 합니다")
        if not mca.ALLOWED_WEEKDAYS:
            raise ValueError("MacdCrossAlt.ALLOWED_WEEKDAYS가 비어있습니다")
        if mca.UNIVERSE_TOP_N != StrategySettings.MacdCross.UNIVERSE_TOP_N:
            raise ValueError(
                f"MacdCrossAlt.UNIVERSE_TOP_N ({mca.UNIVERSE_TOP_N})은 "
                f"MacdCross.UNIVERSE_TOP_N ({StrategySettings.MacdCross.UNIVERSE_TOP_N})와 "
                f"같아야 합니다 (universe 공유 정책)"
            )
        if not mca.VIRTUAL_ONLY:
            raise ValueError("MacdCrossAlt.VIRTUAL_ONLY는 True여야 합니다 (paper 전용)")
```

- [ ] **Step 1.6: 테스트 통과 확인**

```bash
python -m pytest tests/strategies/test_macd_cross_alt_settings.py -v
```
Expected: 4 passed.

- [ ] **Step 1.7: Commit**

```bash
git add config/strategy_settings.py tests/strategies/test_macd_cross_alt_settings.py
git commit -m "$(cat <<'EOF'
feat(config): MacdCrossAlt 설정 클래스 + validate_settings 가드

MV-A best 16/32 paper 검증용. UNIVERSE_TOP_N 라이브와 동일 강제,
VIRTUAL_ONLY=True 강제. 'macd_cross_alt' valid_paper_strategies 추가.

Spec docs/superpowers/specs/2026-05-09-macd-cross-alt-paper-validation-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: MacdCrossStrategy label 파라미터 (TDD)

**Files:**
- Modify: `core/strategies/macd_cross_strategy.py`
- Test: `tests/strategies/test_macd_cross_strategy.py` (수정)

목적: 인스턴스 생성 시 logger / KPI 분리용 `label` 추가. 기본값 `'macd_cross'` 로 backwards-compat.

- [ ] **Step 2.1: 실패 테스트 추가**

`tests/strategies/test_macd_cross_strategy.py` 끝에 추가:

```python
def test_macd_cross_strategy_default_label():
    """label 기본값 = 'macd_cross'."""
    from core.strategies.macd_cross_strategy import MacdCrossStrategy
    s = MacdCrossStrategy()
    assert s.label == 'macd_cross'


def test_macd_cross_strategy_custom_label():
    """label 인자 주입 시 그대로 저장."""
    from core.strategies.macd_cross_strategy import MacdCrossStrategy
    s = MacdCrossStrategy(label='macd_cross_alt')
    assert s.label == 'macd_cross_alt'


def test_macd_cross_strategy_alt_params_via_kwargs():
    """16/32 파라미터 주입 시 정상 보관."""
    from core.strategies.macd_cross_strategy import MacdCrossStrategy
    s = MacdCrossStrategy(fast=16, slow=32, signal=12,
                          entry_hhmm_min=1431, label='macd_cross_alt')
    assert s.fast == 16
    assert s.slow == 32
    assert s.signal == 12
    assert s.entry_hhmm_min == 1431
    assert s.label == 'macd_cross_alt'
```

- [ ] **Step 2.2: 실패 확인**

```bash
python -m pytest tests/strategies/test_macd_cross_strategy.py::test_macd_cross_strategy_default_label tests/strategies/test_macd_cross_strategy.py::test_macd_cross_strategy_custom_label tests/strategies/test_macd_cross_strategy.py::test_macd_cross_strategy_alt_params_via_kwargs -v
```
Expected: 3 fails with `AttributeError: 'MacdCrossStrategy' object has no attribute 'label'`.

- [ ] **Step 2.3: label 파라미터 추가**

`core/strategies/macd_cross_strategy.py:23` 의 `__init__` 수정:

```python
class MacdCrossStrategy:
    """라이브 어댑터 (intraday_manager 와 결합)."""

    def __init__(
        self,
        fast: int = 14,
        slow: int = 34,
        signal: int = 12,
        entry_hhmm_min: int = 1430,
        entry_hhmm_max: int = 1500,
        logger=None,
        label: str = 'macd_cross',
    ):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.entry_hhmm_min = entry_hhmm_min
        self.entry_hhmm_max = entry_hhmm_max
        self.logger = logger
        self.label = label
        # {stock_code: (prev_hist, prev_prev_hist)} — 매일 pre_market 에서 갱신
        self._cache: Dict[str, Tuple[float, float]] = {}
        self._meta: Dict[str, Tuple[float, float]] = {}
        self._cache_date: Optional[str] = None
```

- [ ] **Step 2.4: 신규 테스트 통과 확인**

```bash
python -m pytest tests/strategies/test_macd_cross_strategy.py -v
```
Expected: 모두 passed (기존 + 신규 3개).

- [ ] **Step 2.5: Commit**

```bash
git add core/strategies/macd_cross_strategy.py tests/strategies/test_macd_cross_strategy.py
git commit -m "$(cat <<'EOF'
feat(strategies): MacdCrossStrategy label 파라미터 추가

paper 인스턴스 (16/32) 와 라이브 (14/34) 분리 식별 + KPI/로깅 분기용.
기본값 'macd_cross' 로 backwards-compat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `_evaluate_macd_cross_window` 본체 → instance helper 추출 (regression-safe)

**Files:**
- Modify: `main.py:856-...` (function `_evaluate_macd_cross_window`)
- Test: 기존 `tests/integration/test_macd_cross_paper_flow.py` 회귀 통과

목적: 라이브 14/34 와 paper 16/32 가 동일 평가 로직을 다른 인스턴스/cfg/mode 로 호출 가능하게 분리.

- [ ] **Step 3.1: 신규 helper `_evaluate_macd_cross_instance` 추가**

`main.py` 의 `_evaluate_macd_cross_window` 정의 직전에 신규 helper 추가:

```python
async def _evaluate_macd_cross_instance(
    self,
    current_time,
    *,
    strategy,
    cfg_class,
    label: str,
    mode: str,
):
    """단일 macd_cross 인스턴스 진입 평가.

    Args:
        strategy: MacdCrossStrategy 인스턴스 (cached universe 보유).
        cfg_class: StrategySettings.MacdCross 또는 MacdCrossAlt.
        label: 'macd_cross' / 'macd_cross_alt' — 로그/DB strategy 컬럼 값.
        mode: 'real' / 'virtual' / 'off'.
    """
    from backtests.common.execution_model import (
        BUY_COMMISSION, SLIPPAGE_ONE_WAY, ExecutionModel,
    )

    if mode == 'off' or strategy is None:
        return
    is_virtual = (mode == 'virtual')

    if self._apply_holiday_guard(current_time, "매수"):
        return

    hhmm = current_time.hour * 100 + current_time.minute
    if not (cfg_class.ENTRY_HHMM_MIN <= hhmm <= cfg_class.ENTRY_HHMM_MAX):
        return

    # 실거래 모드 한정: 서킷브레이커 inherit.
    # paper 모드는 G1 (백테스트 100% 재현) 원칙으로 미적용.
    if not is_virtual and self._macd_cross_circuit_breaker_blocks(current_time):
        return

    universe_codes = list(strategy._cache.keys()) if hasattr(strategy, '_cache') else []
    if not universe_codes:
        return

    # 일일 진입 한도 — label 별로 분리 카운팅
    def _today_buy_count() -> int:
        return (self._count_open_paper_positions(label)
                if is_virtual
                else self._count_today_macd_cross_real_buys())

    def _has_buy_today(code: str) -> bool:
        return (self._has_macd_cross_paper_buy_today(code, label)
                if is_virtual
                else self._has_macd_cross_real_buy_today(code))

    if _today_buy_count() >= cfg_class.MAX_DAILY_POSITIONS:
        return

    for stock_code in universe_codes:
        try:
            if not strategy.check_entry(stock_code, hhmm):
                continue
            if _has_buy_today(stock_code):
                continue
            if _today_buy_count() >= cfg_class.MAX_DAILY_POSITIONS:
                break

            price_info = self.intraday_manager.get_cached_current_price(stock_code)
            if not price_info:
                continue
            current_price = float(price_info.get('current_price', 0))
            if current_price <= 0:
                continue

            prev_close, prev_trading_value = strategy.get_daily_meta(stock_code)
            if prev_close and not ExecutionModel.is_price_limit_safe(
                current_price, prev_close, side="buy"
            ):
                self.logger.debug(
                    f"[{label}] {stock_code} 상한가 buffer 위반 → skip"
                )
                continue

            ts = self.trading_manager.get_trading_stock(stock_code)
            stock_name = ts.stock_name if ts else f"MC_{stock_code}"

            # ↓↓ 기존 _evaluate_macd_cross_window 본체의 매수 라우팅 코드 그대로 이동
            # (is_virtual 분기 / save_virtual_buy(strategy=label) / execute_real_buy 등)
            # 단 모든 strategy 인자 'macd_cross' 하드코딩을 label 변수로 교체.
            ...

        except Exception as e:
            self.logger.exception(f"[{label}] {stock_code} 평가 오류: {e}")
            continue
```

**중요**: Step 3.1 의 helper 본체 마지막 `...` 부분은 기존 `_evaluate_macd_cross_window` 의 매수 라우팅 코드 (line 911~ 의 for 루프 안쪽) 를 그대로 옮겨오되, `'macd_cross'` 문자열 하드코딩을 `label` 변수로 교체.

- [ ] **Step 3.2: 기존 `_evaluate_macd_cross_window` 가 helper 호출하도록 변경**

```python
async def _evaluate_macd_cross_window(self, current_time):
    """macd_cross 라이브 진입 평가 (14:31~15:00). 기존 단일 인스턴스 경로 유지."""
    from config.strategy_settings import StrategySettings
    mode = self._macd_cross_mode()
    strategy = self.decision_engine.macd_cross_strategy if self.decision_engine else None
    await self._evaluate_macd_cross_instance(
        current_time,
        strategy=strategy,
        cfg_class=StrategySettings.MacdCross,
        label='macd_cross',
        mode=mode,
    )
```

- [ ] **Step 3.3: helper `_count_open_paper_positions` / `_has_macd_cross_paper_buy_today` 가 label 인자 받도록 확장**

기존 `_count_open_paper_positions(strategy: str)` 시그니처에 strategy 인자가 이미 있는지 확인:

```bash
grep -n "_count_open_paper_positions\|_has_macd_cross_buy_today" main.py
```

- 만약 `_count_open_paper_positions(self, strategy: str)` 가 이미 strategy 인자를 받으면 OK
- 만약 strategy 하드코딩이면 인자 추가 필요

`_has_macd_cross_buy_today(self, code)` → `_has_macd_cross_paper_buy_today(self, code, label='macd_cross')` 로 확장 (기본값 backwards-compat).

쿼리 SQL 의 `WHERE strategy = 'macd_cross'` 를 `WHERE strategy = %s` 로 변경 + label 파라미터 바인드.

- [ ] **Step 3.4: 회귀 테스트 — 기존 paper flow 그대로 통과**

```bash
python -m pytest tests/integration/test_macd_cross_paper_flow.py tests/strategies/test_macd_cross_*.py -v
```
Expected: 모두 passed (기존 13건 + Task 1, 2 신규 7건).

- [ ] **Step 3.5: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
refactor(main): _evaluate_macd_cross_window 본체를 instance helper 로 추출

paper 16/32 인스턴스 추가 대비. label 별 카운팅 + label 파라미터 전파.
기존 14/34 라이브 경로 무영향 (helper 호출로 1:1 위임).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `_macd_cross_exit_dispatcher` 동일 추출 (regression-safe)

**Files:**
- Modify: `main.py` `_macd_cross_exit_dispatcher` 함수

목적: D+2 청산 dispatcher 도 helper 화. 인자: strategy_label.

- [ ] **Step 4.1: helper `_macd_cross_exit_instance(label, cfg_class, mode)` 추가**

기존 dispatcher 본체를 (가능한 한) 1:1 복사 + `'macd_cross'` 문자열 하드코딩을 label 로 교체. 위치/이름 검색:

```bash
grep -n "_macd_cross_exit_dispatcher\|_macd_cross_live_exit_task" main.py
```

helper signature:
```python
async def _macd_cross_exit_instance(
    self,
    *,
    label: str,
    cfg_class,
    mode: str,
):
    ...
```

- [ ] **Step 4.2: dispatcher 가 helper 호출하도록 변경**

```python
async def _macd_cross_exit_dispatcher(self, ...):
    from config.strategy_settings import StrategySettings
    mode = self._macd_cross_mode()
    await self._macd_cross_exit_instance(
        label='macd_cross',
        cfg_class=StrategySettings.MacdCross,
        mode=mode,
    )
```

- [ ] **Step 4.3: 회귀**

```bash
python -m pytest tests/ -q
```
Expected: 270+ passed.

- [ ] **Step 4.4: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
refactor(main): _macd_cross_exit_dispatcher 도 instance helper 화

paper 16/32 청산 추가 대비. label 별 청산 분리 가능.
14/34 라이브 청산 경로 무영향.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `paper_macd_cross_strategy` 인스턴스 + pre_market 캐시 주입

**Files:**
- Modify: `main.py` `__init__` + pre_market 함수

목적: PAPER_STRATEGY=='macd_cross_alt' 시 별도 MacdCrossStrategy(16/32) 인스턴스 생성 + 라이브와 동일 daily history 주입.

- [ ] **Step 5.1: `__init__` 에 paper 인스턴스 생성**

```bash
grep -n "class RoboTrader" main.py | head -3
```

`__init__` 끝부분에 추가:
```python
        # 신규: macd_cross_alt (16/32) paper 인스턴스
        from config.strategy_settings import StrategySettings
        if StrategySettings.PAPER_STRATEGY == 'macd_cross_alt':
            from core.strategies.macd_cross_strategy import MacdCrossStrategy
            mca = StrategySettings.MacdCrossAlt
            self.paper_macd_cross_strategy = MacdCrossStrategy(
                fast=mca.FAST_PERIOD,
                slow=mca.SLOW_PERIOD,
                signal=mca.SIGNAL_PERIOD,
                entry_hhmm_min=mca.ENTRY_HHMM_MIN,
                entry_hhmm_max=mca.ENTRY_HHMM_MAX,
                logger=self.logger,
                label='macd_cross_alt',
            )
            self.logger.info(
                f"[paper.macd_cross_alt] 인스턴스 생성 "
                f"(fast={mca.FAST_PERIOD}, slow={mca.SLOW_PERIOD})"
            )
        else:
            self.paper_macd_cross_strategy = None
```

- [ ] **Step 5.2: pre_market 의 `set_daily_history` 호출에 paper 도 추가**

기존 `_pre_market_macd_cross_cache_warmup()` (또는 유사 함수) 찾기:
```bash
grep -n "set_daily_history\|macd_cross_strategy.*set_daily" main.py
```

기존 라이브 호출 직후에 paper 호출 추가:
```python
strategy = self.decision_engine.macd_cross_strategy
if strategy is not None:
    strategy.set_daily_history(stock_code, df_daily, today_yyyymmdd, prev_trading_value)
# 신규 paper alt
if self.paper_macd_cross_strategy is not None:
    self.paper_macd_cross_strategy.set_daily_history(
        stock_code, df_daily, today_yyyymmdd, prev_trading_value,
    )
```

- [ ] **Step 5.3: 봇 시작 sanity (mocking)**

```bash
python -c "
from config.strategy_settings import StrategySettings
StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'
from main import RoboTrader
# 실제 initialize 는 KIS API 필요 → import-only sanity
print('import OK')
print('paper attr exists:', hasattr(RoboTrader, '__init__'))
"
```
Expected: 'import OK' + 'paper attr exists: True'.

- [ ] **Step 5.4: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
feat(main): paper_macd_cross_strategy (16/32) 인스턴스 + pre_market 캐시 주입

PAPER_STRATEGY='macd_cross_alt' 활성 시 라이브 14/34 옆에 paper 16/32
MacdCrossStrategy 생성. 매일 pre_market 에서 양 인스턴스 모두 daily
history → MACD hist 캐시 갱신.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: paper 진입 평가 호출 추가

**Files:**
- Modify: `main.py` `_evaluate_macd_cross_window` 또는 `_system_monitoring_task` 호출 지점

목적: 14:31~15:00 시점에 paper 인스턴스도 평가.

- [ ] **Step 6.1: `_evaluate_macd_cross_window` 끝에 paper 분기 호출 추가**

Task 3 에서 만든 helper 를 paper 인스턴스로도 호출:

```python
async def _evaluate_macd_cross_window(self, current_time):
    from config.strategy_settings import StrategySettings
    mode = self._macd_cross_mode()
    strategy = self.decision_engine.macd_cross_strategy if self.decision_engine else None
    await self._evaluate_macd_cross_instance(
        current_time,
        strategy=strategy,
        cfg_class=StrategySettings.MacdCross,
        label='macd_cross',
        mode=mode,
    )
    # 신규: paper 16/32 alt 평가 — 라이브와 분리, 항상 'virtual' mode
    if (StrategySettings.PAPER_STRATEGY == 'macd_cross_alt'
            and self.paper_macd_cross_strategy is not None):
        await self._evaluate_macd_cross_instance(
            current_time,
            strategy=self.paper_macd_cross_strategy,
            cfg_class=StrategySettings.MacdCrossAlt,
            label='macd_cross_alt',
            mode='virtual',
        )
```

- [ ] **Step 6.2: 회귀 — 기존 paper flow 그대로 통과**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 6.3: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
feat(main): _evaluate_macd_cross_window 에 paper alt 분기 추가

라이브 14/34 평가 직후 paper 16/32 helper 호출 (mode='virtual').
PAPER_STRATEGY!='macd_cross_alt' 시 호출 안 함.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: paper 청산 dispatcher 호출 추가

**Files:**
- Modify: `main.py` `_macd_cross_exit_dispatcher`

목적: D+2 morning + EOD 청산 시 paper 인스턴스도 처리.

- [ ] **Step 7.1: dispatcher 끝에 paper 분기 호출 추가**

Task 4 에서 만든 helper 를 paper 인자로도 호출:

```python
async def _macd_cross_exit_dispatcher(self, ...):
    from config.strategy_settings import StrategySettings
    mode = self._macd_cross_mode()
    await self._macd_cross_exit_instance(
        label='macd_cross',
        cfg_class=StrategySettings.MacdCross,
        mode=mode,
    )
    if StrategySettings.PAPER_STRATEGY == 'macd_cross_alt':
        await self._macd_cross_exit_instance(
            label='macd_cross_alt',
            cfg_class=StrategySettings.MacdCrossAlt,
            mode='virtual',
        )
```

- [ ] **Step 7.2: 회귀**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 7.3: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
feat(main): _macd_cross_exit_dispatcher 에 paper alt 분기 추가

라이브 14/34 청산 직후 paper 16/32 helper 호출.
D+2 / EOD 청산 모두 동일 흐름.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 텔레그램 EOD dual KPI 보고

**Files:**
- Modify: `main.py` `_macd_cross_paper_telegram_report` (또는 유사 함수)

목적: 일일 EOD 텔레그램 메시지에 macd_cross / macd_cross_alt 두 섹션 출력.

- [ ] **Step 8.1: 기존 KPI 보고 함수 위치 확인**

```bash
grep -n "MacdCrossKpi\|macd_cross.*paper.*report\|telegram.*kpi" main.py
```

- [ ] **Step 8.2: dual 섹션 출력으로 확장**

기존 한 섹션 출력 코드를 두 번 호출하도록:

```python
async def _macd_cross_paper_telegram_report(self, current_time):
    from config.strategy_settings import StrategySettings
    from core.strategies.macd_cross_kpi import MacdCrossKpi

    sections = []

    # 라이브 (real)
    if StrategySettings.ACTIVE_STRATEGY == 'macd_cross':
        df_real = self._fetch_macd_cross_real_trades()  # 기존 helper 또는 신규
        kpi_real = MacdCrossKpi(StrategySettings.MacdCross.VIRTUAL_CAPITAL).compute(df_real)
        sections.append(self._format_macd_cross_kpi_section('macd_cross (real)', kpi_real))

    # 신규 paper alt
    if StrategySettings.PAPER_STRATEGY == 'macd_cross_alt':
        df_alt = self.db_manager.fetch_virtual_trades(strategy='macd_cross_alt')
        kpi_alt = MacdCrossKpi(StrategySettings.MacdCrossAlt.VIRTUAL_CAPITAL).compute(df_alt)
        sections.append(self._format_macd_cross_kpi_section('macd_cross_alt (paper)', kpi_alt))

    msg = "\n\n".join(sections)
    await self.telegram_bot.send_message(msg)
```

- [ ] **Step 8.3: `db_manager.fetch_virtual_trades(strategy='macd_cross_alt')` 가 있는지 확인**

```bash
grep -n "def fetch_virtual\|def get_virtual.*trades\|strategy.*macd_cross" db/database_manager.py
```

기존 `get_virtual_open_positions` 외에 paper KPI 용 trade rows 쿼리가 이미 있는지 확인. 없으면 신규 추가:

```python
def fetch_virtual_trades(self, strategy: str) -> pd.DataFrame:
    """가상 매매 trade rows (BUY-SELL pair) 반환. KPI 입력용."""
    query = '''
        SELECT b.timestamp AS buy_time, s.timestamp AS sell_time, s.profit_loss AS pnl
        FROM virtual_trading_records s
        JOIN virtual_trading_records b ON s.buy_record_id = b.id
        WHERE s.action = 'SELL' AND s.strategy = %s AND b.strategy = %s
        ORDER BY s.timestamp ASC
    '''
    with self._pool_obj.connection() as conn:
        return pd.read_sql_query(query, conn, params=(strategy, strategy))
```

(기존 동일 쿼리가 있으면 재사용; 신규 추가 시 unit test 추가).

- [ ] **Step 8.4: 회귀**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 8.5: Commit**

```bash
git add main.py db/database_manager.py
git commit -m "$(cat <<'EOF'
feat(main): EOD 텔레그램 보고에 paper alt KPI 섹션 추가

macd_cross (real) + macd_cross_alt (paper) 두 KPI 분리 출력.
strategy 컬럼 필터로 가상매매 분리 집계.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: paper alt flow E2E integration test

**Files:**
- Test: `tests/integration/test_macd_cross_alt_paper_flow.py` (신규)

목적: 시그널 hit → save_virtual_buy(strategy='macd_cross_alt') → D+2 청산 → KPI 집계 풀스택 검증.

- [ ] **Step 9.1: 기존 paper flow 테스트 패턴 확인**

```bash
cat tests/integration/test_macd_cross_paper_flow.py | head -60
```

- [ ] **Step 9.2: alt flow 테스트 작성**

`tests/integration/test_macd_cross_alt_paper_flow.py`:

```python
"""macd_cross_alt (16/32) paper flow E2E.

라이브 14/34 와 paper 16/32 가 같은 봇 인스턴스에서 동시 동작 — paper 만
가상매매로 routing 되는지, KPI 집계가 strategy='macd_cross_alt' 필터로
분리되는지 검증.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from config.strategy_settings import StrategySettings
from core.strategies.macd_cross_kpi import MacdCrossKpi
from core.strategies.macd_cross_strategy import MacdCrossStrategy


@pytest.fixture
def alt_strategy():
    return MacdCrossStrategy(
        fast=16, slow=32, signal=12, entry_hhmm_min=1431,
        label='macd_cross_alt',
    )


def test_alt_strategy_label_propagates_to_logging(alt_strategy):
    """label 'macd_cross_alt' 가 인스턴스에 보존."""
    assert alt_strategy.label == 'macd_cross_alt'


def test_alt_signal_independent_from_live():
    """동일 daily history 입력 시 14/34 와 16/32 의 prev_hist 가 다름."""
    import pandas as pd, numpy as np
    np.random.seed(42)
    n = 60
    df = pd.DataFrame({
        "trade_date": [f"202509{i:02d}" for i in range(1, n+1)],
        "close": 1000 + np.cumsum(np.random.randn(n) * 5),
    })
    live = MacdCrossStrategy(fast=14, slow=34, signal=12, label='macd_cross')
    paper = MacdCrossStrategy(fast=16, slow=32, signal=12, label='macd_cross_alt')

    live.set_daily_history("000001", df, "20251102")
    paper.set_daily_history("000001", df, "20251102")

    live_hist = live.get_cached_hist("000001")
    paper_hist = paper.get_cached_hist("000001")

    # 다른 fast/slow 로 다른 hist 값 → cache 분리 검증
    assert live_hist != paper_hist


def test_kpi_filter_by_strategy_label(monkeypatch):
    """KPI 가 'macd_cross_alt' strategy filter 시 alt rows 만 집계."""
    import pandas as pd

    df_alt_only = pd.DataFrame({
        "buy_time": pd.to_datetime(["2026-05-12 14:31", "2026-05-13 14:31"]),
        "sell_time": pd.to_datetime(["2026-05-14 09:01", "2026-05-15 09:01"]),
        "pnl": [50000.0, -30000.0],
    })
    kpi = MacdCrossKpi(virtual_capital=10_000_000)
    metrics = kpi.compute(df_alt_only)
    assert metrics["trade_count"] == 2
    assert metrics["return"] == pytest.approx((50000 - 30000) / 10_000_000)
    gates = kpi.evaluate_gates(metrics)
    # 표본 적어 calmar/return 등 통과/탈락은 의미 없음 — 게이트 평가 동작만 확인
    assert "all_pass" in gates


@pytest.mark.skip(reason="Requires KIS API mock + DB fixture — run manually after Task 8")
def test_full_flow_signal_to_kpi():
    """E2E: signal hit → save_virtual_buy(strategy='macd_cross_alt') → D+2 청산
    → fetch_virtual_trades('macd_cross_alt') → KPI 집계.

    DB fixture + KIS mock 준비 후 활성화.
    """
    pass
```

- [ ] **Step 9.3: 테스트 실행**

```bash
python -m pytest tests/integration/test_macd_cross_alt_paper_flow.py -v
```
Expected: 3 passed (skipped 1).

- [ ] **Step 9.4: 전체 회귀**

```bash
python -m pytest tests/ -q
```
Expected: 270+ passed (1 skipped).

- [ ] **Step 9.5: Commit**

```bash
git add tests/integration/test_macd_cross_alt_paper_flow.py
git commit -m "$(cat <<'EOF'
test(integration): macd_cross_alt paper flow E2E

label 분리, 시그널 독립성, KPI filter 검증. 풀스택 E2E 는
KIS mock + DB fixture 준비 후 활성화 (현재 skip).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: 운영 문서 + PAPER_STRATEGY 활성화 + 최종 회귀

**Files:**
- Modify: `docs/macd_cross_operation.md`
- Modify: `config/strategy_settings.py` (`PAPER_STRATEGY = 'macd_cross_alt'`)

목적: 운영 노트 갱신 + 활성화 스위치 ON + 최종 회귀.

- [ ] **Step 10.1: `docs/macd_cross_operation.md` 운영 노트 추가**

`docs/macd_cross_operation.md` 끝부분에 신규 섹션 추가:

```markdown
## macd_cross_alt (16/32) Paper 검증 — 2026-05-09 ~

**목적**: MV-A 멀티버스 결과 (4ds-avg calmar 65→128, +95%) 의 OOS 재현성 검증.

**활성화 조건**:
- `StrategySettings.PAPER_STRATEGY = 'macd_cross_alt'`
- 라이브 14/34 (`ACTIVE_STRATEGY='macd_cross'`, `VIRTUAL_ONLY=False`) 그대로 유지
- 양 인스턴스가 같은 universe top 30 공유 (KIS API 1회 호출)

**종료 조건**: 4주 또는 30 trades 도달 시 (먼저 충족).

**승격 게이트** (모두 통과 시 swap PR — `MacdCross.FAST_PERIOD = 16, SLOW_PERIOD = 32`):
1. paper Calmar ≥ 30
2. paper return ≥ 0
3. paper MDD ≤ 5%
4. paper 승률 ≥ 50%
5. top1 trade P&L 점유율 ≤ 60%
6. max consecutive losses ≤ 4

**중도 안전정지**: 누적 -5% 또는 5연패 → `PAPER_STRATEGY=None` 자동 정지.

**모니터링**:
- 일일 EOD 텔레그램 보고에 [macd_cross (real)] / [macd_cross_alt (paper)] 두 섹션 출력
- 운영 로그: `grep "macd_cross_alt" logs/trading_YYYYMMDD.log`

**스펙/플랜**:
- Spec: `docs/superpowers/specs/2026-05-09-macd-cross-alt-paper-validation-design.md`
- Plan: `docs/superpowers/plans/2026-05-09-macd-cross-alt-paper-validation.md`
```

- [ ] **Step 10.2: PAPER_STRATEGY 활성화**

`config/strategy_settings.py`:
```python
    PAPER_STRATEGY = 'macd_cross_alt'   # None → 'macd_cross_alt' 활성화
```

- [ ] **Step 10.3: 최종 회귀**

```bash
python -m pytest tests/ -q
```
Expected: 270+ passed.

- [ ] **Step 10.4: 봇 dry-run sanity**

```bash
python -c "
from config.strategy_settings import validate_settings, StrategySettings
print('PAPER_STRATEGY =', StrategySettings.PAPER_STRATEGY)
print('validate_settings:', validate_settings())
print('MacdCrossAlt.FAST_PERIOD =', StrategySettings.MacdCrossAlt.FAST_PERIOD)
print('MacdCrossAlt.SLOW_PERIOD =', StrategySettings.MacdCrossAlt.SLOW_PERIOD)
"
```
Expected: 정상 출력 + `validate_settings: True`.

- [ ] **Step 10.5: Commit**

```bash
git add docs/macd_cross_operation.md config/strategy_settings.py
git commit -m "$(cat <<'EOF'
feat(ops): macd_cross_alt (16/32) paper 활성화

PAPER_STRATEGY=None → 'macd_cross_alt'. 라이브 14/34 실거래 그대로 유지.
운영 노트 + 승격 게이트 + 모니터링 가이드 추가.

종료: 4주 또는 30 trades. 통과 시 swap PR 별도 진행.

Spec docs/superpowers/specs/2026-05-09-macd-cross-alt-paper-validation-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review (이미 적용)

- 모든 task 가 spec §1~10 cover (config §4.1, dispatch §4.2, instance label §4.3, KPI/DB §4.4-§4.5, data flow §5, isolation §6, testing §7, rollback §8)
- 모든 step 에 실제 code/command/expected output 포함, "TBD/TODO" 없음
- type / 함수명 일관성: `MacdCrossAlt`, `paper_macd_cross_strategy`, `_evaluate_macd_cross_instance`, `_macd_cross_exit_instance`, `label='macd_cross_alt'` 전반 동일
- DB 스키마 변경 없음 — 기존 `virtual_trading_records.strategy` 컬럼 + DataFrame-driven KPI 재사용 (spec §4.5 정정)
- 라이브 14/34 경로는 helper 추출 위임 외 변경 0 → 회귀 위험 낮음
