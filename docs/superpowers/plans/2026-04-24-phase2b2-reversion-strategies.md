# Phase 2B-2: 평균회귀 계열 단타 전략 3개 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 단타 카탈로그 15개 중 3개 평균회귀 전략(VWAP 반등, 볼린저 하단 반등, RSI 과매도 반등)을 `StrategyBase` 계약으로 구현.

**Architecture:** 각 전략은 단일 파일로 자기 지표를 inline 계산 (DRY 희생, 독립성 우선). 모든 지표는 shift(1) 적용해 look-ahead 없음. 진입 조건은 "지표 신호 + 반전 확인 (close[t] > close[t-1])" 패턴.

**Tech Stack:** Python 3.x, pandas, pytest. 공통 지표 모듈 없음 (각 지표가 한 전략에서만 쓰이므로).

**Scope:** VWAP 반등 + 볼린저 하단 + RSI 과매도. Phase 2B-3 (추세·거래량 3개) 과 2B-4 (상한가) 는 별도 플랜.

---

## Task 1: VWAP 반등 전략

**Files:** Create `backtests/strategies/vwap_bounce.py`, `tests/backtests/test_vwap_bounce.py`

**개요:** 당일 cumulative VWAP 대비 close 가 vwap_deviation_pct 이상 하회 후 반등(close[t] > close[t-1]) 시 매수.

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_vwap_bounce.py`:
```python
"""VWAP 반등 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.vwap_bounce import VWAPBounceStrategy
from backtests.strategies.base import Position


def _make_bars(trade_date: str, closes, volumes=None):
    if volumes is None:
        volumes = [1000.0] * len(closes)
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c,
            "high": c * 1.001,
            "low": c * 0.999,
            "close": c,
            "volume": v,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = VWAPBounceStrategy()
    assert s.name == "vwap_bounce"
    assert s.hold_days == 0
    assert s.vwap_deviation_pct == -1.0
    assert s.take_profit_pct == 2.0


def test_prepare_features_produces_vwap_columns():
    s = VWAPBounceStrategy()
    # 100 bars of stable price → VWAP ~ 10000
    closes = [10000.0] * 100
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_vwap" in feats.columns
    assert "deviation_pct" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    # 안정 가격 → deviation 0 근접
    assert abs(feats["deviation_pct"].iloc[50]) < 0.01


def test_entry_fires_on_deviation_and_rebound():
    s = VWAPBounceStrategy(
        vwap_deviation_pct=-1.0, rebound_min_bars=3, entry_window_end_bar=240
    )
    # bar 0~29: 10000. bar 30~34: 9800 (-2% below VWAP). bar 35: 9850 (반등)
    closes = [10000.0] * 30 + [9800.0] * 5 + [9850.0] + [10000.0] * 10
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(feats, bar_idx=35, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_without_deviation():
    s = VWAPBounceStrategy(vwap_deviation_pct=-2.0)
    # deviation 만 약간 (-0.5%) → 임계 -2% 미충족
    closes = [10000.0] * 30 + [9950.0] * 5 + [9960.0] + [10000.0] * 10
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=35, stock_code="TEST") is None


def test_entry_no_fire_without_rebound():
    s = VWAPBounceStrategy(vwap_deviation_pct=-1.0)
    # 계속 하락 → 반등 없음
    closes = [10000.0] * 30 + [9800.0, 9790.0, 9780.0, 9770.0, 9760.0, 9750.0] + [9700.0] * 10
    df = _make_bars("20260401", closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=35, stock_code="TEST") is None


def test_exit_tp_sl():
    s = VWAPBounceStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=35, entry_price=9850.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=10050.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=9700.0).reason == "sl"
```

- [ ] **Step 2: pytest 실패 확인**
Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_vwap_bounce.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: vwap_bounce.py 구현**

Create `backtests/strategies/vwap_bounce.py`:
```python
"""VWAP 반등 (VWAP Bounce) — 당일 누적 VWAP 대비 하회 후 반등 매수."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class VWAPBounceStrategy(StrategyBase):
    name = "vwap_bounce"
    hold_days = 0

    param_space = {
        "vwap_deviation_pct": {"type": "float", "low": -3.0, "high": -0.3, "step": 0.3},
        "rebound_min_bars": {"type": "int", "low": 1, "high": 10, "step": 1},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.3},
    }

    def __init__(
        self,
        vwap_deviation_pct: float = -1.0,
        rebound_min_bars: int = 3,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.vwap_deviation_pct = vwap_deviation_pct
        self.rebound_min_bars = rebound_min_bars
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_vwap": [], "deviation_pct": [], "prev_close": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()
        # VWAP = 누적(typical_price × volume) / 누적(volume), 각 거래일 내에서
        typ = (df["high"] + df["low"] + df["close"]) / 3.0
        df["_pv"] = typ * df["volume"]
        df["_cum_pv"] = df.groupby("trade_date")["_pv"].cumsum()
        df["_cum_v"] = df.groupby("trade_date")["volume"].cumsum()
        df["vwap"] = df["_cum_pv"] / df["_cum_v"].replace(0, float("nan"))
        # shift(1) — 전 bar 까지의 VWAP
        df["prev_vwap"] = df.groupby("trade_date")["vwap"].shift(1)
        df["prev_close"] = df.groupby("trade_date")["close"].shift(1)
        df["deviation_pct"] = (df["prev_close"] - df["prev_vwap"]) / df["prev_vwap"] * 100.0
        return df[["prev_vwap", "deviation_pct", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["deviation_pct"]) or pd.isna(row["prev_close"]):
            return None
        # 장 초반 rebound_min_bars 이상 VWAP 완성 후에만
        if row["bar_in_day"] < self.rebound_min_bars:
            return None
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        # deviation 이 임계 이하 (큰 하회)
        if row["deviation_pct"] > self.vwap_deviation_pct:
            return None
        # 반등 확인: 현재 close > 전 close
        if row["close"] <= row["prev_close"]:
            return None
        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self, position, features, bar_idx, current_price: Optional[float] = None
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

- [ ] **Step 4: pytest PASS 확인**
Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_vwap_bounce.py -v`
Expected: 6 passed.

- [ ] **Step 5: 전체 스위트**
Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/ 2>&1 | tail -3`
Expected: 99 + 6 = 105 passed + 2 skipped.

- [ ] **Step 6: Commit**
```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/vwap_bounce.py tests/backtests/test_vwap_bounce.py
git commit -m "feat(backtests): add VWAP bounce strategy"
```

---

## Task 2: 볼린저 하단 반등 전략

**Files:** Create `backtests/strategies/bb_lower_bounce.py`, `tests/backtests/test_bb_lower_bounce.py`

**개요:** 분봉 close 의 N-period 볼린저 하단 이탈 → 다음 바에서 반등(close > prev_close) 시 매수.

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_bb_lower_bounce.py`:
```python
"""볼린저 하단 반등 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.bb_lower_bounce import BBLowerBounceStrategy
from backtests.strategies.base import Position


def _make_bars(closes, trade_date="20260401"):
    rows = []
    for i, c in enumerate(closes):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c, "high": c * 1.001, "low": c * 0.999,
            "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = BBLowerBounceStrategy()
    assert s.name == "bb_lower_bounce"
    assert s.hold_days == 0
    assert s.bb_period == 20
    assert s.bb_num_std == 2.0


def test_prepare_features_has_bb_columns():
    s = BBLowerBounceStrategy()
    closes = [10000.0 + (i % 10 - 5) * 10 for i in range(100)]  # 변동
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_lower" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    # 초반 20 bars 는 NaN (min_periods=20)
    assert pd.isna(feats["prev_lower"].iloc[15])
    # 30 bar 이후 유효
    assert not pd.isna(feats["prev_lower"].iloc[50])


def test_entry_fires_on_bb_lower_bounce():
    s = BBLowerBounceStrategy(bb_period=20, bb_num_std=2.0, entry_window_end_bar=240)
    # bar 0~40: stable 10000. bar 41~45: 9800 (하단 이탈). bar 46: 9850 (반등)
    closes = [10000.0] * 41 + [9800.0] * 5 + [9850.0] + [10000.0] * 10
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(feats, bar_idx=46, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_without_lower_band_break():
    s = BBLowerBounceStrategy()
    closes = [10000.0] * 60  # 전부 stable → 하단 근처 안 감
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=50, stock_code="TEST") is None


def test_entry_no_fire_without_rebound():
    s = BBLowerBounceStrategy()
    # 지속 하락
    closes = [10000.0] * 40 + [9900, 9800, 9700, 9600, 9500, 9400, 9300, 9200]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    # close 는 계속 떨어지므로 반등 확인 실패
    assert s.entry_signal(feats, bar_idx=46, stock_code="TEST") is None


def test_exit_tp_sl():
    s = BBLowerBounceStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=46, entry_price=9850.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=60, current_price=10050.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=60, current_price=9700.0).reason == "sl"
```

- [ ] **Step 2: 실패 확인**
Run: `python -m pytest tests/backtests/test_bb_lower_bounce.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: bb_lower_bounce.py 구현**

Create `backtests/strategies/bb_lower_bounce.py`:
```python
"""볼린저 하단 반등 (BB Lower Bounce) — 하단밴드 이탈 후 반등 매수."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class BBLowerBounceStrategy(StrategyBase):
    name = "bb_lower_bounce"
    hold_days = 0

    param_space = {
        "bb_period": {"type": "int", "low": 10, "high": 40, "step": 5},
        "bb_num_std": {"type": "float", "low": 1.5, "high": 3.0, "step": 0.25},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 4.0, "step": 0.25},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        bb_period: int = 20,
        bb_num_std: float = 2.0,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.bb_period = bb_period
        self.bb_num_std = bb_num_std
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_lower": [], "prev_close": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()
        # 거래일 내 rolling mean/std (min_periods=bb_period)
        def _per_day(g):
            m = g["close"].rolling(self.bb_period, min_periods=self.bb_period).mean()
            s = g["close"].rolling(self.bb_period, min_periods=self.bb_period).std()
            lower = (m - self.bb_num_std * s).shift(1)
            prev_close = g["close"].shift(1)
            return pd.DataFrame({"prev_lower": lower, "prev_close": prev_close}, index=g.index)

        bb = df.groupby("trade_date", group_keys=False).apply(_per_day)
        df = df.join(bb)
        return df[["prev_lower", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_lower"]) or pd.isna(row["prev_close"]):
            return None
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        # 전 bar 가 하단밴드 이탈
        if row["prev_close"] >= row["prev_lower"]:
            return None
        # 반등 확인
        if row["close"] <= row["prev_close"]:
            return None
        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self, position, features, bar_idx, current_price: Optional[float] = None
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

- [ ] **Step 4: PASS 확인**
Run: `python -m pytest tests/backtests/test_bb_lower_bounce.py -v`
Expected: 6 passed.

- [ ] **Step 5: 전체 스위트**
Expected: 105 + 6 = 111 passed + 2 skipped.

- [ ] **Step 6: Commit**
```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/bb_lower_bounce.py tests/backtests/test_bb_lower_bounce.py
git commit -m "feat(backtests): add Bollinger Bands lower bounce strategy"
```

---

## Task 3: RSI 과매도 반등 전략

**Files:** Create `backtests/strategies/rsi_oversold.py`, `tests/backtests/test_rsi_oversold.py`

**개요:** 분봉 N-period RSI 가 threshold 이하 (과매도) 진입 후 RSI 가 반전(prev RSI < current RSI) + close 반등 시 매수.

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_rsi_oversold.py`:
```python
"""RSI 과매도 반등 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.rsi_oversold import RSIOversoldStrategy
from backtests.strategies.base import Position


def _make_bars(closes, trade_date="20260401"):
    rows = []
    for i, c in enumerate(closes):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c, "high": c * 1.001, "low": c * 0.999,
            "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = RSIOversoldStrategy()
    assert s.name == "rsi_oversold"
    assert s.hold_days == 0
    assert s.rsi_period == 14
    assert s.oversold_threshold == 30.0


def test_prepare_features_has_rsi():
    s = RSIOversoldStrategy()
    closes = [10000.0 + (i % 10 - 5) * 50 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_rsi" in feats.columns
    assert "prev_prev_rsi" in feats.columns
    assert "prev_close" in feats.columns
    # bar 20+ 에서는 RSI 유효
    assert not pd.isna(feats["prev_rsi"].iloc[30])


def test_entry_fires_on_rsi_reversal():
    s = RSIOversoldStrategy(
        rsi_period=14, oversold_threshold=30.0, entry_window_end_bar=240
    )
    # 지속 하락 → RSI 낮음. 마지막에 반등
    closes = [10000.0 - i * 50 for i in range(30)]  # 10000 → 8550 (하락)
    closes += [8600.0]  # 반등 한 bar
    closes += [8650.0]  # 반등 지속
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    # 반등 지점에서 RSI 가 oversold 이후 회복
    # test 값 확인용 — 엄격한 assert 대신 로직 동작만 검증
    for idx in range(28, 32):
        r = feats["prev_rsi"].iloc[idx]
        if pd.notna(r):
            print(f"bar {idx} prev_rsi={r:.2f}")
    # bar 30 (반등 시작) 또는 31 에서 signal 발생 기대
    orders = [s.entry_signal(feats, bar_idx=i, stock_code="TEST") for i in range(28, 32)]
    assert any(o is not None for o in orders)


def test_entry_no_fire_without_oversold():
    s = RSIOversoldStrategy(oversold_threshold=20.0)  # 아주 낮은 임계
    # 완만한 변동 → RSI 가 20 밑으로 가지 않음
    closes = [10000.0 + (i % 10 - 5) * 10 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    for idx in range(20, 60):
        assert s.entry_signal(feats, bar_idx=idx, stock_code="TEST") is None


def test_exit_tp_sl():
    s = RSIOversoldStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=30, entry_price=8600.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=8800.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=8400.0).reason == "sl"
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: rsi_oversold.py 구현**

Create `backtests/strategies/rsi_oversold.py`:
```python
"""RSI 과매도 반등 전략 — 분봉 RSI oversold 후 반전 매수."""
from typing import Optional

import numpy as np
import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class RSIOversoldStrategy(StrategyBase):
    name = "rsi_oversold"
    hold_days = 0

    param_space = {
        "rsi_period": {"type": "int", "low": 7, "high": 21, "step": 2},
        "oversold_threshold": {"type": "float", "low": 15.0, "high": 35.0, "step": 2.5},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 4.0, "step": 0.25},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_threshold: float = 30.0,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_rsi": [], "prev_prev_rsi": [], "prev_close": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        def _rsi_per_day(g: pd.DataFrame) -> pd.DataFrame:
            close = g["close"].astype(float)
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(self.rsi_period, min_periods=self.rsi_period).mean()
            avg_loss = loss.rolling(self.rsi_period, min_periods=self.rsi_period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100.0 - 100.0 / (1.0 + rs)
            return pd.DataFrame({
                "prev_rsi": rsi.shift(1),
                "prev_prev_rsi": rsi.shift(2),
                "prev_close": close.shift(1),
            }, index=g.index)

        rsi_df = df.groupby("trade_date", group_keys=False).apply(_rsi_per_day)
        df = df.join(rsi_df)
        return df[["prev_rsi", "prev_prev_rsi", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_rsi"]) or pd.isna(row["prev_prev_rsi"]) or pd.isna(row["prev_close"]):
            return None
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        # 전 bar 의 RSI 가 과매도 진입한 상태였거나 직전에 과매도
        if row["prev_rsi"] >= self.oversold_threshold and row["prev_prev_rsi"] >= self.oversold_threshold:
            return None
        # RSI 반전 (상승 전환)
        if row["prev_rsi"] <= row["prev_prev_rsi"]:
            return None
        # 가격 반등 확인
        if row["close"] <= row["prev_close"]:
            return None
        return EntryOrder(
            stock_code=stock_code, priority=1, budget_ratio=self.budget_ratio
        )

    def exit_signal(
        self, position, features, bar_idx, current_price: Optional[float] = None
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

- [ ] **Step 4: PASS 확인**
Expected: 5 passed.

- [ ] **Step 5: 전체 스위트**
Expected: 111 + 5 = 116 passed + 2 skipped.

- [ ] **Step 6: Commit**
```bash
cd D:/GIT/RoboTrader
git add backtests/strategies/rsi_oversold.py tests/backtests/test_rsi_oversold.py
git commit -m "feat(backtests): add RSI oversold rebound strategy"
```

---

## Summary

**New files (6):**
- `backtests/strategies/vwap_bounce.py` + test (6 tests)
- `backtests/strategies/bb_lower_bounce.py` + test (6 tests)
- `backtests/strategies/rsi_oversold.py` + test (5 tests)

**Phase 2B-2 목표**: 116 tests passed + 2 skipped.
**Phase 2B-3 시작 조건**: 이 플랜 완료 (3 전략 동작).
