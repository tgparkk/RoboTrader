# Phase 2B-1: 브레이크아웃 계열 단타 전략 3개 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단타 카탈로그 15개 중 3개 브레이크아웃 계열(ORB, 갭다운역행, 갭업추격)을 `StrategyBase` 인터페이스로 구현해 엔진에서 최적화·평가 가능하게 함.

**Architecture:** 각 전략은 `backtests/strategies/<name>.py` 단일 파일. `prepare_features` 에서 당일 open·prev_close·opening-range 등 계산(shift(1) 원칙 준수). `entry_signal` 은 features+bar_idx 기반으로 시점 조건 확인. `exit_signal` 은 `current_price` 기반 TP/SL + 당일 청산(hold_days=0).

**Tech Stack:** Python 3.x, pandas, pytest. 공통 지표 모듈은 아직 만들지 않음 (3개 전략 간 공유 로직 적음). Phase 2B-2 에서 VWAP/RSI/BB 등 공통 지표 필요 시 그때 추출.

**Scope:** 3개 전략만. Phase 2B-2~4 는 별도 플랜.

**Reference:**
- Spec: [docs/superpowers/specs/2026-04-24-short-term-strategy-survey-design.md](../specs/2026-04-24-short-term-strategy-survey-design.md)
- Phase 2A 완료: weighted_score_full 어댑터 + current_price 훅 + trading_day 유틸 완비

---

## 설계 노트 (3 전략 공통)

### feature_audit 적용 정책 (중요)

Phase 1 의 `feature_audit.py` 는 `feature[t]` 가 `data[t:]` (현재 바 포함) 에 의존하지 않을 것을 요구 (strict shift(1)).
Intraday 전략은 **당일 현재 바의 close 를 보고 다음 바에 체결** 하는 실거래 규약이라, 당일 바 close 를 feature 에 포함하는 것이 정상.
**따라서 3 전략 모두 feature_audit 를 직접 적용하지 않음**. 대신:
- daily-level 피처(prev_close, prev_volume 등)는 반드시 `shift(1)` 로 계산 (look-ahead 없음)
- intraday-level 피처(opening_range, 당일 누적 volume 등)는 "현재 바 data 까지" 허용 (실거래 가능)
- 엔진의 `FILL_DELAY_MINUTES=1` 이 실제 체결 지연을 반영하므로 look-ahead 우려 없음

### 공통 테스트 헬퍼

각 테스트에서 합성 분봉을 만드는 헬퍼는 전략별 특성에 맞게 인라인으로 작성 (재사용 가능한 공통화는 Phase 2B-2 에서 판단).

### Parameter space 표기 규약

`param_space` 는 Phase 3 Optuna 탐색용. 각 param 마다 `{"type": "float", "low": x, "high": y}` 형식.
구현 시점에는 default 값만 쓰고 param_space 는 자료로만 기록 (옵티마이저 연결은 별도 플랜).

---

## Task 1: ORB (Opening Range Breakout) 전략

**Files:**
- Create: `backtests/strategies/orb.py`
- Test: `tests/backtests/test_orb.py`

**전략 개요:**
- 장 시작 N분 동안 형성된 고점·저점 (Opening Range) 을 기록
- Opening Range 종료 후 고점 × (1 + buffer) 위로 break 시 매수
- TP/SL 은 current_price 기반, 당일 EOD 강제 청산

**Parameter space (참고, 구현 시 default 사용):**
```python
param_space = {
    "opening_window_min": {"type": "int", "low": 10, "high": 60, "step": 5},
    "breakout_buffer_pct": {"type": "float", "low": 0.0, "high": 0.5, "step": 0.05},
    "entry_end_bar": {"type": "int", "low": 60, "high": 240, "step": 30},  # 진입 마감 시점 (분)
    "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
    "stop_loss_pct": {"type": "float", "low": -4.0, "high": -1.0, "step": 0.5},
}
```

### Steps

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/backtests/test_orb.py`:
```python
"""ORB (Opening Range Breakout) 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.orb import ORBStrategy
from backtests.strategies.base import Position, EntryOrder, ExitOrder


def _make_day_bars(
    trade_date: str,
    n_bars: int,
    base_price: float = 10000.0,
    or_high_delta: float = 50.0,
    breakout_bar: int = None,
    breakout_delta: float = 100.0,
):
    """합성 분봉.

    - bar 0 ~ 29: opening range (base_price ± or_high_delta)
    - bar 30 이후: base_price 중심
    - breakout_bar 가 지정되면 해당 bar 의 close 를 base_price + breakout_delta 로 설정
    """
    rows = []
    for i in range(n_bars):
        if i < 30:
            # opening range: high 변동
            high = base_price + or_high_delta
            low = base_price - or_high_delta
            close = base_price
        else:
            high = base_price + 10
            low = base_price - 10
            close = base_price
        if breakout_bar is not None and i == breakout_bar:
            close = base_price + breakout_delta
            high = close + 5
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_orb_defaults_loadable():
    s = ORBStrategy()
    assert s.name == "orb"
    assert s.hold_days == 0
    assert s.opening_window_min == 30
    assert s.breakout_buffer_pct == 0.2
    assert s.take_profit_pct == 3.0
    assert s.stop_loss_pct == -2.0


def test_orb_prepare_features_creates_or_high_low():
    s = ORBStrategy()
    df = _make_day_bars("20260401", n_bars=100, base_price=10000.0, or_high_delta=50.0)
    features = s.prepare_features(df, pd.DataFrame())
    assert "or_high" in features.columns
    assert "or_low" in features.columns
    assert "close" in features.columns
    # opening range 구간 (bar 0~29) 은 or_high/or_low 가 NaN
    assert features["or_high"].iloc[15] != features["or_high"].iloc[15]  # NaN
    # bar 30 이후 or_high = 10050 (base + 50)
    assert features["or_high"].iloc[50] == 10050.0
    assert features["or_low"].iloc[50] == 9950.0


def test_orb_entry_signal_fires_on_breakout():
    s = ORBStrategy()
    # bar 50 에서 10150 으로 breakout (OR high 10050 × 1.002 = 10070.1 초과)
    df = _make_day_bars(
        "20260401", n_bars=100, base_price=10000.0,
        or_high_delta=50.0, breakout_bar=50, breakout_delta=150.0,
    )
    features = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(features, bar_idx=50, stock_code="TEST")
    assert order is not None
    assert order.stock_code == "TEST"


def test_orb_entry_signal_ignored_during_or_window():
    s = ORBStrategy()
    df = _make_day_bars("20260401", n_bars=100, base_price=10000.0, breakout_bar=10, breakout_delta=200.0)
    features = s.prepare_features(df, pd.DataFrame())
    # OR 구간 내 (bar 10) 은 진입 불가
    assert s.entry_signal(features, bar_idx=10, stock_code="TEST") is None


def test_orb_entry_signal_ignored_after_entry_window():
    s = ORBStrategy(entry_end_bar=120)
    df = _make_day_bars("20260401", n_bars=200, base_price=10000.0, breakout_bar=150, breakout_delta=200.0)
    features = s.prepare_features(df, pd.DataFrame())
    # 진입 마감(120) 이후인 bar 150 에서는 breakout 이어도 신호 미발동
    assert s.entry_signal(features, bar_idx=150, stock_code="TEST") is None


def test_orb_entry_signal_requires_breakout_above_buffer():
    s = ORBStrategy(breakout_buffer_pct=1.0)  # 1% 이상 뚫어야 함
    # OR high = 10050. 1% buffer = 10150.5. breakout close = 10100 은 buffer 못 넘김
    df = _make_day_bars("20260401", n_bars=100, breakout_bar=50, breakout_delta=100.0)
    features = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(features, bar_idx=50, stock_code="TEST") is None


def test_orb_exit_signal_tp():
    s = ORBStrategy(take_profit_pct=3.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=50, entry_price=10000.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # +3.5% → TP
    order = s.exit_signal(pos, features, bar_idx=60, current_price=10350.0)
    assert order is not None
    assert order.reason == "tp"


def test_orb_exit_signal_sl():
    s = ORBStrategy(stop_loss_pct=-2.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=50, entry_price=10000.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # -2.5% → SL
    order = s.exit_signal(pos, features, bar_idx=60, current_price=9750.0)
    assert order is not None
    assert order.reason == "sl"


def test_orb_exit_signal_eod_force_exit():
    """당일 청산 강제: 세션 마지막 5분 이내 진입 중이면 EOD 사유로 exit."""
    s = ORBStrategy()
    # 전략은 hold_days=0 이라 엔진이 최종 bar 에서 eod_forced 처리. 전략 자체는
    # 당일 마감 시간 (15:25 근방, bar_idx >= 385) 에서 선제적으로 exit 낼 수도 있음.
    # 단순 구현: exit_signal 내에서 EOD 체크 안 함. 엔진의 강제 청산에 위임.
    # 이 테스트는 exit_signal 이 None 을 반환하는지 확인.
    pos = Position(
        stock_code="TEST", entry_bar_idx=100, entry_price=10000.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 400})
    order = s.exit_signal(pos, features, bar_idx=380, current_price=10020.0)
    assert order is None  # TP/SL 없으면 엔진에 위임
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_orb.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: orb.py 구현**

Create `backtests/strategies/orb.py`:
```python
"""ORB (Opening Range Breakout) — 장 시작 N분 고점 돌파 전략."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class ORBStrategy(StrategyBase):
    name = "orb"
    hold_days = 0  # 당일 청산

    param_space = {
        "opening_window_min": {"type": "int", "low": 10, "high": 60, "step": 5},
        "breakout_buffer_pct": {"type": "float", "low": 0.0, "high": 0.5, "step": 0.05},
        "entry_end_bar": {"type": "int", "low": 60, "high": 240, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -4.0, "high": -1.0, "step": 0.5},
    }

    def __init__(
        self,
        opening_window_min: int = 30,
        breakout_buffer_pct: float = 0.2,
        entry_end_bar: int = 240,  # 13:00 (당일 시작 기준)
        take_profit_pct: float = 3.0,
        stop_loss_pct: float = -2.0,
        budget_ratio: float = 0.30,
    ):
        self.opening_window_min = opening_window_min
        self.breakout_buffer_pct = breakout_buffer_pct
        self.entry_end_bar = entry_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        """각 거래일에 대해 opening range (OR) high/low 계산 후 분봉에 broadcast."""
        if df_minute.empty:
            return pd.DataFrame(
                {"or_high": [], "or_low": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )

        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        # OR 구간 마스크 (bar 0 ~ opening_window_min-1)
        or_mask = df["bar_in_day"] < self.opening_window_min

        # OR 구간 집계 — 각 date 의 high max, low min
        or_high_per_date = df[or_mask].groupby("trade_date")["high"].max()
        or_low_per_date = df[or_mask].groupby("trade_date")["low"].min()

        df["or_high"] = df["trade_date"].map(or_high_per_date)
        df["or_low"] = df["trade_date"].map(or_low_per_date)

        # OR 구간 내 (bar < opening_window_min) 에서는 OR 값 NaN (아직 확정 안 됨)
        df.loc[or_mask, "or_high"] = float("nan")
        df.loc[or_mask, "or_low"] = float("nan")

        return df[["or_high", "or_low", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]

        # OR 구간 이내면 진입 불가
        if pd.isna(row["or_high"]):
            return None
        # 진입 윈도우 마감
        if row["bar_in_day"] > self.entry_end_bar:
            return None
        # Breakout 체크: close > OR high × (1 + buffer)
        threshold = row["or_high"] * (1 + self.breakout_buffer_pct / 100.0)
        if row["close"] <= threshold:
            return None

        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self,
        position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        # TP/SL only — hold_days=0 이므로 EOD 청산은 엔진이 처리
        if current_price is None or position.entry_price <= 0:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.take_profit_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.stop_loss_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None
```

- [ ] **Step 4: 테스트 재실행 → 통과**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_orb.py -v`

Expected: 9 passed.

- [ ] **Step 5: 전체 스위트**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ -v 2>&1 | tail -3`

Expected: 76 + 9 = 85 passed, 2 skipped.

- [ ] **Step 6: Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/orb.py tests/backtests/test_orb.py
git commit -m "feat(backtests): add ORB (opening range breakout) strategy"
```

---

## Task 2: 갭다운 역행 (Gap-Down Reversal) 전략

**Files:**
- Create: `backtests/strategies/gap_down_reversal.py`
- Test: `tests/backtests/test_gap_down_reversal.py`

**전략 개요:**
- 시가 갭다운 ≤ gap_threshold (예: -2%) 발생 종목
- 장 초반 N분 이내 저점 대비 reversal_threshold (예: +1%) 반등 시 매수
- TP/SL 기반, 당일 EOD 청산 (hold_days=0)

**Parameter space:**
```python
param_space = {
    "gap_threshold_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
    "reversal_threshold_pct": {"type": "float", "low": 0.3, "high": 3.0, "step": 0.3},
    "entry_window_end_bar": {"type": "int", "low": 30, "high": 120, "step": 15},
    "take_profit_pct": {"type": "float", "low": 1.5, "high": 6.0, "step": 0.5},
    "stop_loss_pct": {"type": "float", "low": -5.0, "high": -1.5, "step": 0.5},
}
```

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_gap_down_reversal.py`:
```python
"""갭다운 역행 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.gap_down_reversal import GapDownReversalStrategy
from backtests.strategies.base import Position


def _make_daily_df(stock_code: str, close_prev: float):
    """전일 close 가 close_prev 인 합성 일봉."""
    return pd.DataFrame([{
        "stock_code": stock_code,
        "trade_date": "20260331",
        "open": close_prev,
        "high": close_prev * 1.01,
        "low": close_prev * 0.99,
        "close": close_prev,
        "volume": 100000.0,
    }])


def _make_minute_df(
    stock_code: str,
    trade_date: str,
    n_bars: int,
    open_price: float,
    day_low: float = None,
    rebound_bar: int = None,
    rebound_price: float = None,
):
    """합성 분봉. open_price 에서 시작. day_low 에 도달 후 rebound_bar 에서 rebound_price."""
    if day_low is None:
        day_low = open_price * 0.99
    rows = []
    for i in range(n_bars):
        hh = 9 + i // 60
        mm = i % 60
        # 기본 경로: bar 10 까지 open_price→day_low 하향, 그 후 평탄
        if i < 10:
            price = open_price - (open_price - day_low) * (i / 9)
        else:
            price = day_low
        if rebound_bar is not None and i == rebound_bar and rebound_price is not None:
            price = rebound_price
        rows.append({
            "stock_code": stock_code,
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": price,
            "high": price * 1.001,
            "low": price * 0.999,
            "close": price,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_defaults_loadable():
    s = GapDownReversalStrategy()
    assert s.name == "gap_down_reversal"
    assert s.hold_days == 0
    assert s.gap_threshold_pct == -2.0
    assert s.reversal_threshold_pct == 1.0


def test_prepare_features_computes_gap_and_rolling_low():
    s = GapDownReversalStrategy()
    minute = _make_minute_df("TEST", "20260401", n_bars=30, open_price=9800.0, day_low=9700.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    # gap_pct = (9800 - 10000) / 10000 * 100 = -2%
    assert abs(features["gap_pct"].iloc[0] - (-2.0)) < 0.01
    # day_low (누적 최저) 는 bar 가 진행되면서 갱신
    assert "day_low_so_far" in features.columns
    assert features["day_low_so_far"].iloc[15] <= 9700.0
    # rebound_pct = (close - day_low) / day_low * 100
    assert "rebound_pct" in features.columns


def test_entry_signal_fires_when_gap_down_and_rebound():
    s = GapDownReversalStrategy(
        gap_threshold_pct=-2.0, reversal_threshold_pct=1.0, entry_window_end_bar=60
    )
    # open 9800 (-2% gap), day_low 9700, rebound at bar 20 to 9800 (+1.03%)
    minute = _make_minute_df(
        "TEST", "20260401", n_bars=60, open_price=9800.0,
        day_low=9700.0, rebound_bar=20, rebound_price=9800.0,
    )
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    order = s.entry_signal(features, bar_idx=20, stock_code="TEST")
    assert order is not None


def test_entry_signal_no_fire_without_gap_down():
    s = GapDownReversalStrategy(gap_threshold_pct=-2.0)
    # open 9950 (-0.5% gap) → 갭 기준 미충족
    minute = _make_minute_df("TEST", "20260401", n_bars=60, open_price=9950.0, day_low=9900.0, rebound_bar=20, rebound_price=10000.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    assert s.entry_signal(features, bar_idx=20, stock_code="TEST") is None


def test_entry_signal_no_fire_after_window_end():
    s = GapDownReversalStrategy(entry_window_end_bar=30)
    minute = _make_minute_df("TEST", "20260401", n_bars=100, open_price=9800.0, day_low=9700.0, rebound_bar=50, rebound_price=9800.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    # bar 50 은 window(30) 이후
    assert s.entry_signal(features, bar_idx=50, stock_code="TEST") is None


def test_entry_signal_no_fire_without_rebound():
    s = GapDownReversalStrategy(reversal_threshold_pct=2.0)
    # rebound 1% 만 → 2% 기준 미충족
    minute = _make_minute_df("TEST", "20260401", n_bars=60, open_price=9800.0, day_low=9700.0, rebound_bar=20, rebound_price=9797.0)
    daily = _make_daily_df("TEST", close_prev=10000.0)
    features = s.prepare_features(minute, daily)
    assert s.entry_signal(features, bar_idx=20, stock_code="TEST") is None


def test_exit_signal_tp_sl():
    s = GapDownReversalStrategy(take_profit_pct=3.0, stop_loss_pct=-2.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=20, entry_price=9800.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # +3.5% from 9800 = 10143 → TP
    assert s.exit_signal(pos, features, bar_idx=30, current_price=10143.0).reason == "tp"
    # -2.5% = 9555 → SL
    assert s.exit_signal(pos, features, bar_idx=30, current_price=9555.0).reason == "sl"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_gap_down_reversal.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: gap_down_reversal.py 구현**

Create `backtests/strategies/gap_down_reversal.py`:
```python
"""갭다운 역행 (Gap-Down Reversal) — 시가 갭다운 후 반등 매수."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class GapDownReversalStrategy(StrategyBase):
    name = "gap_down_reversal"
    hold_days = 0

    param_space = {
        "gap_threshold_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
        "reversal_threshold_pct": {"type": "float", "low": 0.3, "high": 3.0, "step": 0.3},
        "entry_window_end_bar": {"type": "int", "low": 30, "high": 120, "step": 15},
        "take_profit_pct": {"type": "float", "low": 1.5, "high": 6.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -5.0, "high": -1.5, "step": 0.5},
    }

    def __init__(
        self,
        gap_threshold_pct: float = -2.0,
        reversal_threshold_pct: float = 1.0,
        entry_window_end_bar: int = 60,
        take_profit_pct: float = 3.0,
        stop_loss_pct: float = -2.0,
        budget_ratio: float = 0.30,
    ):
        self.gap_threshold_pct = gap_threshold_pct
        self.reversal_threshold_pct = reversal_threshold_pct
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"gap_pct": [], "day_low_so_far": [], "rebound_pct": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )

        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        # 전일 close 매핑 (daily_df 에서 shift(1))
        prev_close_by_date = self._build_prev_close_map(df, df_daily)
        df["prev_close"] = df["trade_date"].map(prev_close_by_date)

        # 시가갭 (각 날의 첫 bar open 기준)
        day_open_per_date = df.groupby("trade_date")["open"].first()
        df["day_open"] = df["trade_date"].map(day_open_per_date)
        df["gap_pct"] = (df["day_open"] - df["prev_close"]) / df["prev_close"] * 100.0

        # 당일 누적 최저가 (bar 진행에 따라 갱신)
        df["day_low_so_far"] = df.groupby("trade_date")["low"].cummin()

        # 반등률: (현재 close - day_low_so_far) / day_low_so_far * 100
        df["rebound_pct"] = (
            (df["close"] - df["day_low_so_far"]) / df["day_low_so_far"] * 100.0
        )

        return df[["gap_pct", "day_low_so_far", "rebound_pct", "close", "bar_in_day"]]

    @staticmethod
    def _build_prev_close_map(df_minute, df_daily):
        """각 trade_date 에 대해 그 전 거래일의 daily close 반환."""
        if df_daily is None or df_daily.empty:
            return {}
        daily = df_daily.sort_values("trade_date").copy()
        daily["prev_close"] = daily["close"].shift(-1)  # next row's close
        # Actually we want for each minute's trade_date, the close of the PRIOR daily.
        # daily sorted asc → shift(1) to get prev.
        daily = daily.sort_values("trade_date")
        daily["prev_close"] = daily["close"].shift(1)
        return dict(zip(daily["trade_date"], daily["prev_close"]))

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]

        # 진입 윈도우 체크
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        # gap 조건
        if pd.isna(row["gap_pct"]) or row["gap_pct"] > self.gap_threshold_pct:
            return None
        # 반등 조건
        if pd.isna(row["rebound_pct"]) or row["rebound_pct"] < self.reversal_threshold_pct:
            return None

        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self,
        position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        if current_price is None or position.entry_price <= 0:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.take_profit_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.stop_loss_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None
```

- [ ] **Step 4: 테스트 재실행 → 통과**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_gap_down_reversal.py -v`

Expected: 7 passed.

- [ ] **Step 5: 전체 스위트**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ -v 2>&1 | tail -3`

Expected: 85 + 7 = 92 passed, 2 skipped.

- [ ] **Step 6: Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/gap_down_reversal.py tests/backtests/test_gap_down_reversal.py
git commit -m "feat(backtests): add gap-down reversal strategy"
```

---

## Task 3: 갭업 추격 (Gap-Up Continuation) 전략

**Files:**
- Create: `backtests/strategies/gap_up_chase.py`
- Test: `tests/backtests/test_gap_up_chase.py`

**전략 개요:**
- 시가 갭업 ≥ gap_threshold (예: +3%) 발생 종목
- 장 초반 N분 이내 volume_ratio ≥ N× (예: 2×) 되면 매수 (강한 수급 동반 추격)
- TP/SL 기반, 당일 EOD 청산

**Parameter space:**
```python
param_space = {
    "gap_threshold_pct": {"type": "float", "low": 1.5, "high": 7.0, "step": 0.5},
    "volume_mult": {"type": "float", "low": 1.5, "high": 5.0, "step": 0.5},
    "entry_window_end_bar": {"type": "int", "low": 15, "high": 90, "step": 15},
    "take_profit_pct": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
    "stop_loss_pct": {"type": "float", "low": -4.0, "high": -1.0, "step": 0.5},
}
```

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_gap_up_chase.py`:
```python
"""갭업 추격 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.gap_up_chase import GapUpChaseStrategy
from backtests.strategies.base import Position


def _make_daily_df(stock_code: str, close_prev: float, avg_vol: float = 1000.0):
    """전일 일봉 + 과거 N일 (avg_vol 유지 위해 5일치)."""
    rows = []
    dates = ["20260326", "20260327", "20260328", "20260329", "20260330", "20260331"]
    for d in dates:
        rows.append({
            "stock_code": stock_code,
            "trade_date": d,
            "open": close_prev,
            "high": close_prev * 1.01,
            "low": close_prev * 0.99,
            "close": close_prev,
            "volume": avg_vol,
        })
    return pd.DataFrame(rows)


def _make_minute_df(
    stock_code: str,
    trade_date: str,
    n_bars: int,
    open_price: float,
    high_volume_bar: int = None,
    high_volume_mult: float = 5.0,
    base_vol: float = 100.0,
):
    rows = []
    for i in range(n_bars):
        hh = 9 + i // 60
        mm = i % 60
        vol = base_vol
        if high_volume_bar is not None and i == high_volume_bar:
            vol = base_vol * high_volume_mult
        rows.append({
            "stock_code": stock_code,
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": open_price,
            "high": open_price * 1.002,
            "low": open_price * 0.998,
            "close": open_price,
            "volume": vol,
        })
    return pd.DataFrame(rows)


def test_defaults_loadable():
    s = GapUpChaseStrategy()
    assert s.name == "gap_up_chase"
    assert s.hold_days == 0
    assert s.gap_threshold_pct == 3.0
    assert s.volume_mult == 2.0


def test_prepare_features_computes_gap_and_volume_ratio():
    s = GapUpChaseStrategy()
    minute = _make_minute_df("TEST", "20260401", n_bars=30, open_price=10300.0, base_vol=100.0)
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_vol=1000.0)
    features = s.prepare_features(minute, daily)
    # gap = (10300 - 10000) / 10000 * 100 = +3%
    assert abs(features["gap_pct"].iloc[0] - 3.0) < 0.01
    assert "vol_ratio" in features.columns
    assert "close" in features.columns
    assert "bar_in_day" in features.columns


def test_entry_signal_fires_on_gap_up_and_volume_surge():
    s = GapUpChaseStrategy(
        gap_threshold_pct=3.0, volume_mult=2.0, entry_window_end_bar=30
    )
    # open 10300 (+3% gap) + bar 15 에서 거래량 5× → 매수
    minute = _make_minute_df(
        "TEST", "20260401", n_bars=30, open_price=10300.0,
        high_volume_bar=15, high_volume_mult=5.0, base_vol=100.0,
    )
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_vol=100.0)
    features = s.prepare_features(minute, daily)
    order = s.entry_signal(features, bar_idx=15, stock_code="TEST")
    assert order is not None


def test_entry_signal_no_fire_without_gap_up():
    s = GapUpChaseStrategy(gap_threshold_pct=3.0)
    minute = _make_minute_df("TEST", "20260401", n_bars=30, open_price=10100.0, high_volume_bar=15, high_volume_mult=5.0, base_vol=100.0)
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_vol=100.0)
    features = s.prepare_features(minute, daily)
    # +1% gap → 3% 기준 미충족
    assert s.entry_signal(features, bar_idx=15, stock_code="TEST") is None


def test_entry_signal_no_fire_without_volume_surge():
    s = GapUpChaseStrategy(volume_mult=5.0)
    minute = _make_minute_df("TEST", "20260401", n_bars=30, open_price=10300.0, high_volume_bar=15, high_volume_mult=2.0, base_vol=100.0)
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_vol=100.0)
    features = s.prepare_features(minute, daily)
    # volume 2× → 5× 기준 미충족
    assert s.entry_signal(features, bar_idx=15, stock_code="TEST") is None


def test_entry_signal_no_fire_after_window():
    s = GapUpChaseStrategy(entry_window_end_bar=15)
    minute = _make_minute_df("TEST", "20260401", n_bars=60, open_price=10300.0, high_volume_bar=30, high_volume_mult=5.0, base_vol=100.0)
    daily = _make_daily_df("TEST", close_prev=10000.0, avg_vol=100.0)
    features = s.prepare_features(minute, daily)
    # bar 30 은 window(15) 이후
    assert s.entry_signal(features, bar_idx=30, stock_code="TEST") is None


def test_exit_signal_tp_sl():
    s = GapUpChaseStrategy(take_profit_pct=4.0, stop_loss_pct=-2.0)
    pos = Position(
        stock_code="TEST", entry_bar_idx=15, entry_price=10300.0,
        quantity=10, entry_date="20260401",
    )
    features = pd.DataFrame({"close": [float("nan")] * 100})
    # +4.5% from 10300 ≈ 10763 → TP
    assert s.exit_signal(pos, features, bar_idx=30, current_price=10763.0).reason == "tp"
    # -2.5% ≈ 10042 → SL
    assert s.exit_signal(pos, features, bar_idx=30, current_price=10042.0).reason == "sl"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_gap_up_chase.py -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: gap_up_chase.py 구현**

Create `backtests/strategies/gap_up_chase.py`:
```python
"""갭업 추격 (Gap-Up Continuation) — 시가 갭업 + 거래량 급증 추격."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class GapUpChaseStrategy(StrategyBase):
    name = "gap_up_chase"
    hold_days = 0

    param_space = {
        "gap_threshold_pct": {"type": "float", "low": 1.5, "high": 7.0, "step": 0.5},
        "volume_mult": {"type": "float", "low": 1.5, "high": 5.0, "step": 0.5},
        "entry_window_end_bar": {"type": "int", "low": 15, "high": 90, "step": 15},
        "take_profit_pct": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -4.0, "high": -1.0, "step": 0.5},
    }

    def __init__(
        self,
        gap_threshold_pct: float = 3.0,
        volume_mult: float = 2.0,
        entry_window_end_bar: int = 30,
        take_profit_pct: float = 4.0,
        stop_loss_pct: float = -2.0,
        budget_ratio: float = 0.30,
    ):
        self.gap_threshold_pct = gap_threshold_pct
        self.volume_mult = volume_mult
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"gap_pct": [], "vol_ratio": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )

        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        # 전일 close + 과거 5일 avg volume (shift(1) 로 look-ahead 없음)
        prev_close_by_date, avg_vol_by_date = self._build_daily_context_maps(df_daily)
        df["prev_close"] = df["trade_date"].map(prev_close_by_date)
        df["avg_vol_5d"] = df["trade_date"].map(avg_vol_by_date)

        # gap%
        day_open_per_date = df.groupby("trade_date")["open"].first()
        df["day_open"] = df["trade_date"].map(day_open_per_date)
        df["gap_pct"] = (df["day_open"] - df["prev_close"]) / df["prev_close"] * 100.0

        # 분봉 volume vs daily avg_vol 비율 — 당일 bars 수만큼 나누는 것이 정확하지만
        # 여기서는 단순화: vol_ratio = current_bar_vol × (bars_per_day_estimate) / avg_vol_5d
        # 실용상 vol_ratio = current_bar_vol / (avg_vol_5d / 390) 로 분봉 단위 비교
        df["vol_ratio"] = df["volume"] / (df["avg_vol_5d"] / 390.0)

        return df[["gap_pct", "vol_ratio", "close", "bar_in_day"]]

    @staticmethod
    def _build_daily_context_maps(df_daily: pd.DataFrame):
        """각 trade_date 에 대해 (prev_close, avg_vol_5d) 반환. shift(1) 엄수."""
        if df_daily is None or df_daily.empty:
            return {}, {}
        d = df_daily.sort_values("trade_date").copy()
        d["prev_close"] = d["close"].shift(1)
        d["avg_vol_5d"] = d["volume"].rolling(5, min_periods=1).mean().shift(1)
        prev_close_map = dict(zip(d["trade_date"], d["prev_close"]))
        avg_vol_map = dict(zip(d["trade_date"], d["avg_vol_5d"]))
        return prev_close_map, avg_vol_map

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]

        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        if pd.isna(row["gap_pct"]) or row["gap_pct"] < self.gap_threshold_pct:
            return None
        if pd.isna(row["vol_ratio"]) or row["vol_ratio"] < self.volume_mult:
            return None

        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self,
        position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        if current_price is None or position.entry_price <= 0:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.take_profit_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.stop_loss_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None
```

- [ ] **Step 4: 테스트 재실행 → 통과**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_gap_up_chase.py -v`

Expected: 7 passed.

- [ ] **Step 5: 전체 스위트 최종 확인**

Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ -v 2>&1 | tail -3`

Expected: 92 + 7 = 99 passed, 2 skipped.

- [ ] **Step 6: Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/gap_up_chase.py tests/backtests/test_gap_up_chase.py
git commit -m "feat(backtests): add gap-up continuation strategy"
```

---

## Phase 2B-1 Wrap-up

- [ ] **Phase 2B-1 완료 노트**

Append to `backtests/reports/phase1_baseline_notes.md`:
```markdown

---

## Phase 2B-1 완료 (YYYY-MM-DD)

- [x] ORB (Opening Range Breakout)
- [x] 갭다운 역행 (Gap-Down Reversal)
- [x] 갭업 추격 (Gap-Up Continuation)

전체 tests: 99 passed + 2 skipped.

**남은 classic 전략 (Phase 2B-2, 2B-3, 2B-4 예정)**:
- VWAP 반등, 볼린저 하단, RSI 과매도 (평균회귀)
- 거래량 급증, 장중 눌림목, 오후 풀백 (추세·거래량)
- 상한가 따라잡기 (특수)
```

- [ ] **Commit**

```bash
cd D:/GIT/RoboTrader
git add backtests/reports/phase1_baseline_notes.md
git commit -m "docs(backtests): Phase 2B-1 complete (3 breakout strategies)"
```

---

## Summary of Changes

**New files**:
- `backtests/strategies/orb.py` — ORB 전략
- `backtests/strategies/gap_down_reversal.py` — 갭다운 역행
- `backtests/strategies/gap_up_chase.py` — 갭업 추격
- `tests/backtests/test_orb.py` — ORB 단위 테스트 (9 tests)
- `tests/backtests/test_gap_down_reversal.py` — 갭다운 단위 테스트 (7 tests)
- `tests/backtests/test_gap_up_chase.py` — 갭업 단위 테스트 (7 tests)

**Modified**:
- `backtests/reports/phase1_baseline_notes.md` — Phase 2B-1 완료 섹션 추가

**Phase 2B-1 목표**:
- 99 tests passing
- 3개 전략이 StrategyBase 계약 준수, 엔진에서 end-to-end 실행 가능
- param_space 가 Phase 3 최적화용으로 문서화됨

**Phase 2B-2 시작 조건**: 이 플랜 모든 task 완료 + 엔진 동작 확인.
