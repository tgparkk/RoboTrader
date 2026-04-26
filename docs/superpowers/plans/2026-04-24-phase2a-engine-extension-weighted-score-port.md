# Phase 2A: 엔진 확장 + weighted_score 완전 포팅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 엔진에 TP/SL bar-level 훅과 trading-day 기반 day counting 을 추가하고, 기존 `core/strategies/weighted_score_features.py` 를 재사용해 Trial 837 baseline 을 새 엔진에서 ±30% 이내 재현.

**Architecture:** `backtests/strategies/base.py` 의 `exit_signal` 시그니처에 `current_price` 파라미터 추가 (기본값 None — backward-compat). 엔진은 매 bar 의 현재 close 를 exit_signal 에 전달. `trading_day_count` 유틸은 `trade_date` 기반으로 보유 거래일수 계산. weighted_score full adapter 는 `compute_daily_raw` / `compute_intraday_raw` / `compute_score` 를 직접 호출.

**Tech Stack:** Python 3.x, pandas, numpy, pytest, psycopg2. `core/strategies/weighted_score_features.py` 와 `weighted_score_params.json` 를 dependency 로 사용.

**Scope:** Phase 2A 만 (엔진 확장 + full adapter + Trial 837 재현). Phase 2B (10 intraday classic) 와 Phase 2C (5 overnight classic) 는 별도 플랜.

**Reference:**
- Spec: [docs/superpowers/specs/2026-04-24-short-term-strategy-survey-design.md](../specs/2026-04-24-short-term-strategy-survey-design.md)
- Phase 1 Plan: [docs/superpowers/plans/2026-04-24-phase1-backtest-infrastructure.md](2026-04-24-phase1-backtest-infrastructure.md)

---

## File Structure

### New files
```
backtests/
├── common/
│   └── trading_day.py                    # 거래일 카운팅 유틸
└── strategies/
    └── weighted_score_full.py            # Trial 837 완전 포팅

tests/backtests/
├── test_trading_day.py
├── test_engine_tp_sl_hook.py             # 엔진 current_price 훅 테스트
└── test_weighted_score_full.py

backtests/reports/
└── phase2a_trial837_reproduction.md      # 재현 결과 기록
```

### Modified files
```
backtests/strategies/base.py              # exit_signal(..., current_price=None)
backtests/common/engine.py                # current_price 전달 + trading_day 사용
tests/backtests/test_engine.py            # 기존 테스트 유지 (backward compat)
```

---

## Task 1: 거래일 카운팅 유틸 (trading_day.py)

**Files:**
- Create: `backtests/common/trading_day.py`
- Test: `tests/backtests/test_trading_day.py`

**Responsibility:** `trade_date` 컬럼 기반으로 "매수 시점 ~ 현재 시점" 사이 경과한 거래일 수 계산. `bar_idx // 390` 같은 고정 가정 제거.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/backtests/test_trading_day.py`:
```python
"""backtests.common.trading_day 단위 테스트."""
import pandas as pd
import pytest

from backtests.common.trading_day import (
    count_trading_days_between,
    bar_idx_to_trade_date,
)


def _make_df(dates):
    """dates: [trade_date] → DataFrame."""
    return pd.DataFrame({"trade_date": dates})


def test_count_zero_days_same_date():
    df = _make_df(["20260401", "20260401", "20260401"])
    # 같은 날짜 내에서는 0일 경과
    assert count_trading_days_between(df, from_idx=0, to_idx=2) == 0


def test_count_one_day_next_date():
    df = _make_df(["20260401", "20260401", "20260402", "20260402"])
    # 20260401 → 20260402: 1일 경과
    assert count_trading_days_between(df, from_idx=1, to_idx=2) == 1


def test_count_multiple_days():
    df = _make_df(["20260401", "20260402", "20260403", "20260404", "20260405"])
    # idx 0 (01) → idx 4 (05): 4일 경과
    assert count_trading_days_between(df, from_idx=0, to_idx=4) == 4


def test_count_from_equals_to():
    df = _make_df(["20260401", "20260402"])
    assert count_trading_days_between(df, from_idx=1, to_idx=1) == 0


def test_count_handles_weekend_gap():
    # 금 → 월: 주말 건너뜀 (거래일 기준 1일)
    df = _make_df(["20260403", "20260406"])  # 금, 월
    assert count_trading_days_between(df, from_idx=0, to_idx=1) == 1


def test_count_invalid_range_raises():
    df = _make_df(["20260401", "20260402"])
    with pytest.raises(ValueError):
        count_trading_days_between(df, from_idx=1, to_idx=0)  # from > to


def test_bar_idx_to_trade_date():
    df = _make_df(["20260401", "20260401", "20260402", "20260403"])
    assert bar_idx_to_trade_date(df, 0) == "20260401"
    assert bar_idx_to_trade_date(df, 2) == "20260402"
    assert bar_idx_to_trade_date(df, 3) == "20260403"


def test_bar_idx_out_of_range():
    df = _make_df(["20260401", "20260402"])
    with pytest.raises(IndexError):
        bar_idx_to_trade_date(df, 5)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_trading_day.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: trading_day.py 구현**

Create `backtests/common/trading_day.py`:
```python
"""거래일 카운팅 유틸 — trade_date 컬럼 기반."""
import pandas as pd


def count_trading_days_between(
    df_minute: pd.DataFrame, from_idx: int, to_idx: int
) -> int:
    """df_minute[from_idx] ~ df_minute[to_idx] 사이 고유 trade_date 의 개수 - 1.

    Args:
        df_minute: trade_date 컬럼 포함된 분봉 DF.
        from_idx: 시작 bar 인덱스 (inclusive).
        to_idx: 종료 bar 인덱스 (inclusive).

    Returns:
        경과한 거래일 수. 같은 날짜 안에서는 0.
    """
    if from_idx > to_idx:
        raise ValueError(f"from_idx {from_idx} > to_idx {to_idx}")
    subset = df_minute["trade_date"].iloc[from_idx : to_idx + 1]
    return int(subset.nunique() - 1)


def bar_idx_to_trade_date(df_minute: pd.DataFrame, bar_idx: int) -> str:
    """bar_idx 시점의 trade_date 반환."""
    if bar_idx < 0 or bar_idx >= len(df_minute):
        raise IndexError(f"bar_idx {bar_idx} out of range [0, {len(df_minute)})")
    return str(df_minute["trade_date"].iloc[bar_idx])
```

- [ ] **Step 4: 테스트 재실행 → 통과**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_trading_day.py -v`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/common/trading_day.py tests/backtests/test_trading_day.py
git commit -m "feat(backtests): add trading_day utility for date-based day counting"
```

---

## Task 2: 엔진 exit_signal 에 current_price 전달 (backward compat)

**Files:**
- Modify: `backtests/strategies/base.py` — exit_signal 시그니처 변경
- Modify: `backtests/common/engine.py` — current_price 전달
- Create: `tests/backtests/test_engine_tp_sl_hook.py` — TP/SL 훅 검증

**Responsibility:** `exit_signal(..., current_price=None)` 로 확장. 기존 구현은 param 무시하면 되므로 backward-compat. 엔진은 각 bar 의 close 를 읽어 전달.

- [ ] **Step 1: 기존 테스트가 영향 없는지 확인 (baseline)**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ -v 2>&1 | tail -5`

Expected: 59 passed, 2 skipped (Phase 1 말 상태).

- [ ] **Step 2: 새 테스트 작성 (실패)**

Create `tests/backtests/test_engine_tp_sl_hook.py`:
```python
"""엔진이 exit_signal 에 current_price 를 전달하는지 검증."""
from typing import Optional

import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class TPSLStrategy(StrategyBase):
    """current_price 기반 TP/SL 전략."""
    name = "tp_sl"
    hold_days = 0
    param_space = {}

    def __init__(self, tp_pct=5.0, sl_pct=-3.0):
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct

    def prepare_features(self, df_minute, df_daily):
        return pd.DataFrame(index=df_minute.index)

    def entry_signal(self, features, bar_idx, stock_code):
        if bar_idx == 5:
            return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.5)
        return None

    def exit_signal(
        self, position, features, bar_idx, current_price: Optional[float] = None
    ):
        if current_price is None:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.tp_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.sl_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None


def _ramping_bars(stock_code, n, start=10000.0, tp_target_bar=None, tp_pct=0.06):
    """tp_target_bar 에서 tp_pct% 급등하는 합성 분봉."""
    closes = [start] * n
    for i in range(1, n):
        closes[i] = closes[i - 1] * 1.001  # 완만한 상승
    if tp_target_bar is not None:
        closes[tp_target_bar] = start * (1 + tp_pct)  # 급등
    return pd.DataFrame({
        "stock_code": [stock_code] * n,
        "trade_date": ["20260401"] * n,
        "trade_time": [f"{9 + i // 60:02d}{i % 60:02d}00" for i in range(n)],
        "open": closes,
        "high": [c * 1.001 for c in closes],
        "low": [c * 0.999 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def test_engine_passes_current_price_to_exit_signal():
    """엔진이 current_price 전달 → TP 규칙 작동."""
    stock_code = "TEST"
    # bar 5 매수 (fill at bar 6, entry ≈ 10010)
    # bar 10 에서 close = 10000 * 1.06 = 10600 → +5.9% → TP 발동
    df = _ramping_bars(stock_code, n=20, tp_target_bar=10, tp_pct=0.06)
    engine = BacktestEngine(
        strategy=TPSLStrategy(tp_pct=5.0, sl_pct=-3.0),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["reason"] == "tp", f"기대 'tp', 실제 '{trade['reason']}'"


def test_engine_exit_signal_no_current_price_backward_compat():
    """current_price 미사용 전략 (기존 Phase 1 테스트 스타일) 여전히 동작."""
    from tests.backtests.test_engine import BuyAtBar5Sell3BarsLater, _make_bars

    stock_code = "TEST"
    df = _make_bars(stock_code, n=20)
    engine = BacktestEngine(
        strategy=BuyAtBar5Sell3BarsLater(),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    assert len(result.trades) == 1
    assert result.trades[0]["entry_bar_idx"] == 6
    assert result.trades[0]["exit_bar_idx"] == 10
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_engine_tp_sl_hook.py -v`

Expected: `test_engine_passes_current_price_to_exit_signal` FAIL (엔진이 아직 current_price 전달 안 함). 
`test_engine_exit_signal_no_current_price_backward_compat` PASS.

- [ ] **Step 4: base.py 수정 — exit_signal 시그니처 확장**

Modify `backtests/strategies/base.py`:

Replace:
```python
    @abstractmethod
    def exit_signal(
        self, position: Position, features: pd.DataFrame, bar_idx: int
    ) -> Optional[ExitOrder]:
        """보유 중인 position 에 대한 매도 신호. 없으면 None."""
```

With:
```python
    @abstractmethod
    def exit_signal(
        self,
        position: Position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        """보유 중인 position 에 대한 매도 신호.

        Args:
            position: 보유 포지션.
            features: 전략이 prepare_features 로 계산한 DF.
            bar_idx: 현재 분봉 인덱스.
            current_price: 현재 분봉 close (TP/SL 체크용). None 이면 훅 미사용 전략.
        """
```

- [ ] **Step 5: engine.py 수정 — current_price 전달**

Modify `backtests/common/engine.py`, inside `run()` method, the exit check loop:

Replace:
```python
            # 1. 보유 포지션 exit 체크
            for code, pos in list(positions.items()):
                features = features_by_code[code]
                if t >= len(features):
                    continue
                exit_order = self.strategy.exit_signal(pos, features, bar_idx=t)
                if exit_order is None:
                    continue
```

With:
```python
            # 1. 보유 포지션 exit 체크
            for code, pos in list(positions.items()):
                features = features_by_code[code]
                if t >= len(features):
                    continue
                df_min = self.minute_df_by_code[code]
                current_price = float(df_min["close"].iloc[t]) if t < len(df_min) else None
                exit_order = self.strategy.exit_signal(
                    pos, features, bar_idx=t, current_price=current_price
                )
                if exit_order is None:
                    continue
```

- [ ] **Step 6: 기존 concrete 전략 시그니처 업데이트**

Modify `backtests/strategies/weighted_score_baseline.py`:

Replace:
```python
    def exit_signal(self, position, features, bar_idx) -> Optional[ExitOrder]:
        held_bars = bar_idx - position.entry_bar_idx
        if held_bars <= 0:
            return None
        days_held = held_bars // BARS_PER_TRADING_DAY
        if days_held >= self.max_holding_days:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
```

With:
```python
    def exit_signal(
        self, position, features, bar_idx, current_price: Optional[float] = None
    ) -> Optional[ExitOrder]:
        held_bars = bar_idx - position.entry_bar_idx
        if held_bars <= 0:
            return None
        days_held = held_bars // BARS_PER_TRADING_DAY
        if days_held >= self.max_holding_days:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
```

- [ ] **Step 7: 기존 엔진 테스트 의 전략 클래스들도 업데이트**

Modify `tests/backtests/test_engine.py` — `BuyAtBar5Sell3BarsLater.exit_signal`:

Replace:
```python
    def exit_signal(self, position, features, bar_idx):
        if bar_idx - position.entry_bar_idx >= 3:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
```

With:
```python
    def exit_signal(self, position, features, bar_idx, current_price=None):
        if bar_idx - position.entry_bar_idx >= 3:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
```

Also `SilentStrategy.exit_signal` in the same file:
Replace:
```python
        def exit_signal(self, position, features, bar_idx):
            return None
```

With:
```python
        def exit_signal(self, position, features, bar_idx, current_price=None):
            return None
```

- [ ] **Step 8: strategy_base 테스트 의 DummyStrategy 도 업데이트**

Modify `tests/backtests/test_strategy_base.py` — `DummyStrategy.exit_signal`:

Replace:
```python
    def exit_signal(self, position, features, bar_idx):
        if bar_idx - position.entry_bar_idx >= 5:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
```

With:
```python
    def exit_signal(self, position, features, bar_idx, current_price=None):
        if bar_idx - position.entry_bar_idx >= 5:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
```

- [ ] **Step 9: 전체 테스트 재실행**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ -v`

Expected: 59 (Phase 1) + 8 (Task 1 trading_day) + 2 (this task) = 69 passed, 2 skipped.

If any test fails, STOP and investigate. Do not hack tests.

- [ ] **Step 10: Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/base.py backtests/common/engine.py \
        backtests/strategies/weighted_score_baseline.py \
        tests/backtests/test_engine.py tests/backtests/test_strategy_base.py \
        tests/backtests/test_engine_tp_sl_hook.py
git commit -m "feat(backtests): pass current_price to exit_signal for TP/SL hook"
```

---

## Task 3: weighted_score full adapter (기존 features.py 재사용)

**Files:**
- Create: `backtests/strategies/weighted_score_full.py`
- Test: `tests/backtests/test_weighted_score_full.py`

**Responsibility:** `core/strategies/weighted_score_features.py` 의 `compute_daily_raw`, `compute_intraday_raw`, `compute_score`, `normalize_feature_dict`, `past_volume_by_idx_from_minutes` 를 그대로 호출해 Trial 837 파라미터로 채점하는 어댑터.

> **주의**: 기존 features.py 의 `compute_intraday_raw` 는 `bars` 에 `time`, `idx` 컬럼을 요구함. 우리 `data_loader.load_minute_df` 는 `trade_time` 반환 → 어댑터 `prepare_features` 에서 컬럼 리네임 및 `idx` 재생성 필요.

- [ ] **Step 1: 테스트 작성 (실패)**

Create `tests/backtests/test_weighted_score_full.py`:
```python
"""weighted_score full adapter 단위 테스트 (합성 데이터 + 실제 params.json)."""
import pandas as pd
import pytest

from backtests.strategies.weighted_score_full import WeightedScoreFull


def _make_minute_df(stock_code: str, n_days: int, bars_per_day: int = 20):
    """합성 분봉 DF — n_days 거래일, 각 날 bars_per_day 개 분봉."""
    rows = []
    for d in range(n_days):
        date = f"2026030{d+1:02d}" if d < 9 else f"202603{d+1:02d}"
        for b in range(bars_per_day):
            hh = 9 + b // 60
            mm = b % 60
            rows.append({
                "stock_code": stock_code,
                "trade_date": date,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": 10000.0 + d * 100 + b,
                "high": 10005.0 + d * 100 + b,
                "low": 9995.0 + d * 100 + b,
                "close": 10000.0 + d * 100 + b,
                "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_daily_df(stock_code: str, n_days: int = 60):
    """합성 일봉 — 충분한 과거 (지표 계산용 최소 30일+)."""
    rows = []
    start_date = pd.Timestamp("2026-01-01")
    for d in range(n_days):
        date = (start_date + pd.Timedelta(days=d)).strftime("%Y%m%d")
        price = 10000.0 + d * 10
        rows.append({
            "stock_code": stock_code,
            "trade_date": date,
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": 100000.0,
        })
    return pd.DataFrame(rows)


def test_adapter_loads_trial837_params():
    s = WeightedScoreFull()
    assert s.name == "weighted_score_full"
    assert s.params.meta.get("trial_number") == 837
    assert s.params.max_positions == 3
    assert abs(s.params.threshold_abs - (-0.35)) < 0.01


def test_adapter_prepare_features_returns_score_column():
    s = WeightedScoreFull()
    minute_df = _make_minute_df("005930", n_days=5, bars_per_day=20)
    daily_df = _make_daily_df("005930", n_days=60)
    # 지수 데이터 없이 호출
    features = s.prepare_features(
        df_minute=minute_df,
        df_daily=daily_df,
        df_kospi=pd.DataFrame(),
        df_kosdaq=pd.DataFrame(),
    )
    assert "score" in features.columns
    assert len(features) == len(minute_df)


def test_adapter_entry_signal_never_fires_on_nan():
    s = WeightedScoreFull()
    # 데이터가 적어 피처 대부분 NaN → score NaN → entry 0건
    minute_df = _make_minute_df("005930", n_days=1, bars_per_day=5)
    daily_df = _make_daily_df("005930", n_days=10)
    features = s.prepare_features(
        df_minute=minute_df, df_daily=daily_df,
        df_kospi=pd.DataFrame(), df_kosdaq=pd.DataFrame(),
    )
    for idx in range(len(features)):
        order = s.entry_signal(features, bar_idx=idx, stock_code="005930")
        assert order is None


def test_adapter_exit_signal_tp_via_current_price():
    s = WeightedScoreFull()
    # tp 파라미터 = +8.02% (Trial 837). 매수가 10000 → +8.02% = 10802
    from backtests.strategies.base import Position
    pos = Position(
        stock_code="005930", entry_bar_idx=100, entry_price=10000.0,
        quantity=10, entry_date="20260301",
    )
    features = pd.DataFrame({"score": [float("nan")] * 1000})
    # 현재가 10900 (+9%) → TP 발동
    order = s.exit_signal(pos, features, bar_idx=150, current_price=10900.0)
    assert order is not None
    assert order.reason == "tp"


def test_adapter_exit_signal_sl_via_current_price():
    s = WeightedScoreFull()
    from backtests.strategies.base import Position
    pos = Position(
        stock_code="005930", entry_bar_idx=100, entry_price=10000.0,
        quantity=10, entry_date="20260301",
    )
    features = pd.DataFrame({"score": [float("nan")] * 1000})
    # 현재가 9500 (-5%) → SL (-3.84%) 발동
    order = s.exit_signal(pos, features, bar_idx=150, current_price=9500.0)
    assert order is not None
    assert order.reason == "sl"


def test_adapter_exit_signal_hold_limit_via_trading_day_count():
    """5 거래일 경과 시 hold_limit."""
    s = WeightedScoreFull()
    from backtests.strategies.base import Position
    # 6일치 분봉 (최소 6 거래일 포함)
    minute_df = _make_minute_df("005930", n_days=6, bars_per_day=10)
    # 어댑터는 features 에 trade_date 정보 필요. prepare_features 결과 대신 minute_df 를 features 에 포함시켜야 함.
    features = s.prepare_features(
        df_minute=minute_df,
        df_daily=_make_daily_df("005930", n_days=30),
        df_kospi=pd.DataFrame(),
        df_kosdaq=pd.DataFrame(),
    )
    # 진입: 첫날 10번째 bar (idx=9 가정)
    pos = Position(
        stock_code="005930", entry_bar_idx=5,
        entry_price=10000.0, quantity=10, entry_date="20260301",
    )
    # 5일 후 bar (5 거래일 경과)
    # bars_per_day=10, 5일 후 = idx 50+
    order = s.exit_signal(pos, features, bar_idx=55, current_price=10050.0)
    assert order is not None
    assert order.reason == "hold_limit"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_weighted_score_full.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: weighted_score_full.py 구현**

Create `backtests/strategies/weighted_score_full.py`:
```python
"""weighted_score Trial 837 full adapter.

기존 core/strategies/weighted_score_features.py 의 피처 계산을 그대로 재사용.
엔진 인터페이스 (StrategyBase) 에 맞춰 포장.

Responsibilities:
- prepare_features: 종목별 daily_raw 계산 후 분봉별 intraday_raw + 정규화 + score
- entry_signal: score ≤ threshold 일 때 EntryOrder emit
- exit_signal: TP/SL (current_price 기준) + hold_limit (trade_date 기준 max_holding_days)
"""
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from core.strategies.weighted_score_features import (
    WeightedScoreParams,
    compute_daily_raw,
    compute_intraday_raw,
    compute_score,
    normalize_feature_dict,
    past_volume_by_idx_from_minutes,
)
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


PARAMS_FILE = (
    Path(__file__).parent.parent.parent
    / "core" / "strategies" / "weighted_score_params.json"
)


class WeightedScoreFull(StrategyBase):
    name = "weighted_score_full"
    hold_days = 5
    param_space = {}

    def __init__(self):
        self.params = WeightedScoreParams.load(PARAMS_FILE)
        self._last_df_minute: Optional[pd.DataFrame] = None  # trading_day 계산용

    def prepare_features(
        self,
        df_minute: pd.DataFrame,
        df_daily: pd.DataFrame,
        df_kospi: pd.DataFrame = None,
        df_kosdaq: pd.DataFrame = None,
    ) -> pd.DataFrame:
        """score 컬럼을 포함한 피처 DF 반환. look-ahead 없음 (daily 는 shift(1)).

        Note: df_kospi/df_kosdaq 는 지수 일봉 (KS11/KQ11). None 이면 rel_ret/kospi_*
              피처가 NaN 이 되어 score 가 NaN 이 됨 (가중치 큰 피처 누락 시 전체 NaN).
        """
        self._last_df_minute = df_minute  # exit_signal 에서 참조

        n = len(df_minute)
        scores = [float("nan")] * n

        if df_minute.empty or df_daily is None or df_daily.empty:
            return pd.DataFrame({"score": scores}, index=df_minute.index)

        # 지수 DF 는 features.py 규약에 따라 'date' 컬럼 필요
        kospi = self._prepare_index_df(df_kospi)
        kosdaq = self._prepare_index_df(df_kosdaq)

        # 분봉에 idx (1-based) 및 'time' 컬럼 (features.py 규약)
        bars = df_minute.copy()
        bars["time"] = bars["trade_time"]
        bars["idx"] = bars.groupby("trade_date").cumcount() + 1

        # 날짜별 daily_raw 사전 계산 (종일 불변)
        unique_dates = bars["trade_date"].unique()
        daily_raw_by_date: Dict[str, Dict[str, float]] = {}
        for target_date in unique_dates:
            daily_raw_by_date[target_date] = compute_daily_raw(
                stock_daily=df_daily,
                kospi_daily=kospi,
                kosdaq_daily=kosdaq,
                target_trade_date=str(target_date),
            )

        # 과거 5거래일 volume 맵 (vol_ratio_5d 용)
        past_vol_map = past_volume_by_idx_from_minutes(bars, n_days=5)

        # bar 별 intraday_raw 계산은 비용 큼 — 필요시 샘플링 가능하지만 여기선 정확성 우선
        # day_open: 각 trade_date 의 첫 bar open
        day_open_by_date = bars.groupby("trade_date")["open"].first().to_dict()

        for i in range(n):
            td = bars.iloc[i]["trade_date"]
            # 당일 bars 누적 (현재 i 포함)
            day_bars = bars[bars["trade_date"] == td]
            day_bars = day_bars[day_bars["idx"] <= bars.iloc[i]["idx"]]
            intraday = compute_intraday_raw(
                bars=day_bars,
                day_open=float(day_open_by_date[td]),
                past_volume_by_idx=past_vol_map,
            )
            merged = {**daily_raw_by_date[td], **intraday}
            normalized = normalize_feature_dict(merged, self.params)
            scores[i] = compute_score(normalized, self.params)

        return pd.DataFrame({"score": scores}, index=df_minute.index)

    @staticmethod
    def _prepare_index_df(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        """data_loader 는 'trade_date' 반환. features.py 는 'date' 요구 → 리네임."""
        if df is None or df.empty:
            return None
        out = df.copy()
        if "date" not in out.columns and "trade_date" in out.columns:
            out = out.rename(columns={"trade_date": "date"})
        return out

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        score = features["score"].iloc[bar_idx]
        if pd.isna(score):
            return None
        if score >= self.params.threshold_abs:
            return None
        # Trial 837: 3 종목 × 30% = 90% 운용. budget_ratio 은 엔진이 상한만 보장하므로 0.30 고정.
        return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.30)

    def exit_signal(
        self,
        position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        # TP/SL: current_price 기준
        if current_price is not None and position.entry_price > 0:
            pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
            if pnl_pct >= self.params.take_profit_pct:
                return ExitOrder(stock_code=position.stock_code, reason="tp")
            if pnl_pct <= self.params.stop_loss_pct:
                return ExitOrder(stock_code=position.stock_code, reason="sl")

        # hold_limit: trade_date 기반 경과 거래일
        if self._last_df_minute is not None:
            days_held = count_trading_days_between(
                self._last_df_minute,
                from_idx=position.entry_bar_idx,
                to_idx=bar_idx,
            )
            if days_held >= self.params.max_holding_days:
                return ExitOrder(stock_code=position.stock_code, reason="hold_limit")

        return None
```

- [ ] **Step 4: 테스트 재실행 → 통과**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_weighted_score_full.py -v`

Expected: 6 passed.

> **만약 `normalize_feature_dict` import 가 실패하면**: `core/strategies/weighted_score_features.py` Line 186 근처 함수명 확인 (`normalize_feature_dict` 예상). 실제 이름이 다르면 import 수정.

> **만약 test_adapter_exit_signal_hold_limit_via_trading_day_count 가 실패하면**: `prepare_features` 호출 시 `_last_df_minute` 이 올바르게 세팅되는지 로깅. `count_trading_days_between` 의 반환값이 `max_holding_days=5` 이상인지 bar_idx=55 기준 확인.

- [ ] **Step 5: 전체 스위트 재실행**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ -v 2>&1 | tail -5`

Expected: 69 + 6 = 75 passed, 2 skipped.

- [ ] **Step 6: Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/weighted_score_full.py tests/backtests/test_weighted_score_full.py
git commit -m "$(cat <<'EOF'
feat(backtests): add full weighted_score adapter reusing existing features.py

Wraps compute_daily_raw/compute_intraday_raw/compute_score/normalize_feature_dict
from core/strategies/weighted_score_features.py in StrategyBase interface.
TP/SL via current_price, hold_limit via trade_date-based day counting.
EOF
)"
```

---

## Task 4: Trial 837 재현 검증 (실제 DB)

**Files:**
- Create: `tests/backtests/test_trial837_reproduction.py`
- Create: `backtests/reports/phase2a_trial837_reproduction.md`

**Responsibility:** WeightedScoreFull 을 Trial 837 train 구간(20250417~20251215)에 돌려 Calmar 를 측정. 원래 학습 시 test Calmar 25.10 이었으므로, 우리 새 엔진에서도 ±30% (17.57~32.63) 이내면 검증 성공. 큰 괴리 시 원인 분석 후 이관 이슈 기록.

- [ ] **Step 1: 재현 테스트 작성**

Create `tests/backtests/test_trial837_reproduction.py`:
```python
"""Trial 837 train 구간 재현 검증.

DB 접속 필요. minute_candles 에 2025-04 ~ 2025-12 데이터가 충분해야 함.
"""
import pandas as pd
import psycopg2
import pytest

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from backtests.common.engine import BacktestEngine
from backtests.common.data_loader import load_minute_df, load_daily_df, load_index_df
from backtests.strategies.weighted_score_full import WeightedScoreFull


def _db_available() -> bool:
    try:
        c = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD, connect_timeout=2,
        )
        c.close()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="DB 접속 불가")


@requires_db
def test_trial837_train_period_reproduction():
    """Trial 837 train 구간에서 엔진 end-to-end 실행. Calmar 의 order of magnitude 확인."""
    # 대표 종목 소수로 스모크 — 전체 universe 는 시간 과다
    universe = ["005930", "000660", "035720", "035420", "005380"]
    start = "20250417"
    end = "20251215"

    minute_df = load_minute_df(codes=universe, start_date=start, end_date=end)
    if minute_df.empty:
        pytest.skip(f"분봉 데이터 없음: {start}~{end}")

    daily_df = load_daily_df(
        codes=universe, start_date="20250101", end_date=end
    )
    kospi_df = load_index_df(index_code="KS11", start_date="20250101", end_date=end)
    kosdaq_df = load_index_df(index_code="KQ11", start_date="20250101", end_date=end)

    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }

    # Adapter 에 지수 DF 도 전달하려면 strategy 의 prepare_features 가 받아야 함.
    # 엔진은 prepare_features 를 (df_minute, df_daily) 로 호출하므로, 어댑터의
    # prepare_features 를 오버라이드하거나 adapter 내부에서 지수 로드 필요.
    # 여기서는 월크어라운드: adapter 인스턴스 속성으로 지수 DF 주입.
    strategy = WeightedScoreFull()
    # monkey-patch: prepare_features 를 지수 포함 버전으로 교체
    original = strategy.prepare_features

    def prepare_with_indexes(df_minute, df_daily):
        return original(df_minute, df_daily, df_kospi=kospi_df, df_kosdaq=kosdaq_df)

    strategy.prepare_features = prepare_with_indexes

    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=10_000_000,
        universe=list(minute_by_code.keys()),
        minute_df_by_code=minute_by_code,
        daily_df_by_code=daily_by_code,
    )
    result = engine.run()

    print(
        f"\n[Trial 837 재현] "
        f"trades={result.metrics['total_trades']} "
        f"return={result.metrics['total_return']:.2%} "
        f"mdd={result.metrics['mdd']:.2%} "
        f"calmar={result.metrics.get('calmar', float('nan')):.2f} "
        f"sharpe={result.metrics.get('sharpe', float('nan')):.2f}"
    )

    # 최소 조건만 assert — 정확한 Calmar 매칭은 리포트에 기록
    assert result.final_equity > 0
    assert "calmar" in result.metrics
```

- [ ] **Step 2: 테스트 실행 (시간 오래 걸림, -s 로 stdout 확인)**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_trial837_reproduction.py -v -s`

Expected: PASS with stdout output, e.g. `[Trial 837 재현] trades=N return=X% mdd=Y% calmar=Z`

> **시간 제약**: 5 종목 × 170+ 거래일 × ~390 bars/day = ~330k bars. compute_intraday_raw 호출이 느릴 수 있음. 실행이 10분 초과하면 BLOCKED 로 보고하고 universe 를 3 종목으로 축소.

- [ ] **Step 3: 재현 결과 기록**

Create `backtests/reports/phase2a_trial837_reproduction.md` with this template (fill in actual numbers from the test output):

```markdown
# Phase 2A Trial 837 재현 검증 결과

**일자**: (테스트 실행 일자)
**기간**: 20250417~20251215 (Trial 837 train span)
**유니버스**: 005930, 000660, 035720, 035420, 005380 (대표 5종목)
**초기자본**: 10,000,000

## 원 Trial 837 결과 (core/strategies/weighted_score_params.json)
- test Calmar: 25.10
- test Return: +9.60% (88일)
- test MDD: 2.40%
- test Sharpe: 4.10
- test Win%: 55.7%
- Overfit ratio: 0.62

## 우리 엔진 재현 결과 (5종목 부분 universe)
- 거래수: _
- 총 수익률: _
- MDD: _
- Calmar: _
- Sharpe: _

## 비교

| 지표 | 원 Trial 837 | 우리 엔진 | 비율 |
|------|--------------|-----------|------|
| Calmar | 25.10 | _ | _ |
| Return | +9.60% | _ | _ |
| MDD | 2.40% | _ | _ |

## 해석

- [ ] Calmar 가 ±30% (17.57~32.63) 이내 → 엔진 신뢰성 OK
- [ ] Return·MDD 도 합리적 범위 → OK
- [ ] 차이가 큰 이유 (해당 시):
  - 원 Trial 837 은 전체 universe (200 종목), 우리는 5종목만
  - 슬리피지·수수료 모델 차이
  - 체결 시점 (다음 분봉 시가) 차이
  - 가변 bars-per-day 가 아닌 근사치 사용

## Phase 2B 로 이관할 이슈

- [ ] 전체 universe 재현 필요 (현재 5종목 스모크)
- [ ] 발견된 기타 차이점 (위에 기록)
```

Fill in the actual numbers based on Step 2's output.

- [ ] **Step 4: 결과 기반 판정 + 커밋**

Case 1: Calmar 가 ±30% 이내 → DONE.
Case 2: 큰 괴리 → Phase 2B 로 이관 (리포트에 원인 가설 기록).

Commit:
```bash
cd D:/GIT/RoboTrader
git add tests/backtests/test_trial837_reproduction.py \
        backtests/reports/phase2a_trial837_reproduction.md
git commit -m "test(backtests): add Trial 837 reproduction verification on train span"
```

---

## Phase 2A Wrap-up

- [ ] **최종 전체 스위트**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ -v 2>&1 | tail -5`

Expected: 69 + 6 + 1 = 76 passed, 2 skipped (skipped 는 DB 나 데이터 부재로 인한 기존 스킵).

- [ ] **완료 노트 추가**

Append to `backtests/reports/phase1_baseline_notes.md`:
```markdown

---

## Phase 2A 완료 (YYYY-MM-DD)

- [x] Task 1: trading_day 유틸 (거래일 경과 카운팅)
- [x] Task 2: 엔진에 current_price 전달 (TP/SL 훅)
- [x] Task 3: weighted_score_full 어댑터 (features.py 재사용)
- [x] Task 4: Trial 837 train 재현 검증 → 결과는
   `backtests/reports/phase2a_trial837_reproduction.md` 참조.

## Phase 2B 시작 조건

- Phase 2A 전체 테스트 통과
- Trial 837 재현 리포트 검토 완료
- 15 classic 전략 구현 시 `weighted_score_full` 패턴 (features.py 재사용
  스타일, StrategyBase 인터페이스) 을 참고해 일관성 유지
```

- [ ] **최종 Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/reports/phase1_baseline_notes.md
git commit -m "docs(backtests): Phase 2A complete — engine extension + Trial 837 reproduction"
```

---

## Summary of Changes

**New files**:
- `backtests/common/trading_day.py`
- `backtests/strategies/weighted_score_full.py`
- `tests/backtests/test_trading_day.py`
- `tests/backtests/test_engine_tp_sl_hook.py`
- `tests/backtests/test_weighted_score_full.py`
- `tests/backtests/test_trial837_reproduction.py`
- `backtests/reports/phase2a_trial837_reproduction.md`

**Modified**:
- `backtests/strategies/base.py` — exit_signal 시그니처 (backward-compat default=None)
- `backtests/common/engine.py` — current_price 계산·전달
- `backtests/strategies/weighted_score_baseline.py` — 새 시그니처 준수
- `tests/backtests/test_engine.py` — concrete strategies 시그니처 업데이트
- `tests/backtests/test_strategy_base.py` — DummyStrategy 시그니처 업데이트
- `backtests/reports/phase1_baseline_notes.md` — Phase 2A 완료 섹션 추가

**Phase 2A 목표 달성 기준**:
- 76 tests passing (2 skipped acceptable)
- weighted_score_full adapter 가 엔진 end-to-end 로 돌아감
- Trial 837 Calmar 재현 리포트 작성 (±30% 달성 or 이관 이슈 기록)

**Phase 2B 시작 조건**: 이 플랜 모든 task 완료 + Trial 837 리포트 검토.
