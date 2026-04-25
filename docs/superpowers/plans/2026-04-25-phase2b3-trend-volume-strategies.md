# Phase 2B-3: 추세·거래량 계열 단타 전략 3개 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 단타 카탈로그 15개 중 3개 추세·거래량 계열(거래량 급증 추격, 장중 눌림목 20EMA, 종가 드리프트)을 `StrategyBase` 계약으로 구현.

**Architecture:** 각 전략은 단일 파일로 자기 지표를 inline 계산. 모든 daily-level 피처는 `shift(1)` 적용해 look-ahead 없음. Closing Drift 만 `hold_days=1` (오버나이트), 나머지 둘은 `hold_days=0`.

**Tech Stack:** Python 3.x, pandas, pytest. 공통 지표 모듈 없음 — 각 전략 독립.

**Scope:** 3개 전략. Phase 2B-4 (상한가 따라잡기) 와 Phase 2C (overnight swing 5개) 는 별도 플랜.

---

## 설계 노트

### closing_drift = 오버나이트 (hold_days=1)

`core/strategies/closing_trade_strategy.py` 에서 검증된 운영 전략 (멀티버스: +53.7% / MDD 3.56% / 승률 60.6%) 을 백테스트 엔진 계약으로 포팅. 진입 14:00~14:20, 익일 09:00 청산. 엔진의 `count_trading_days_between` + `_last_df_minute` 패턴 (weighted_score_full 의 hold_limit 와 동일).

### Intraday 전략 look-ahead 정책

Phase 2B-1/2 와 동일: feature_audit 직접 호출하지 않음. daily-level 피처는 shift(1), intraday-level 은 "현재 바 close 까지" 허용. 엔진의 `FILL_DELAY_MINUTES=1` 이 다음 bar 체결 강제.

---

## Task 1: 거래량 급증 추격 (Volume Surge Chase) 전략

**Files:**
- Create: `backtests/strategies/volume_surge.py`
- Test: `tests/backtests/test_volume_surge.py`

**전략 개요:**
- 분봉 거래량이 최근 N분 rolling 평균의 K배 이상 (당일 내) → 가격 confirmation (close > prev_close)
- gap_up_chase 와의 차이: gap 무관, 장중 어느 시점이든 거래량 폭발 + 가격 추종
- TP/SL 기반, 당일 EOD 청산

**Parameter space:**
```python
param_space = {
    "vol_lookback_bars": {"type": "int", "low": 5, "high": 30, "step": 5},
    "volume_mult": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
    "entry_window_start_bar": {"type": "int", "low": 5, "high": 60, "step": 5},
    "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
    "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
    "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
}
```

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_volume_surge.py`:
```python
"""거래량 급증 추격 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.volume_surge import VolumeSurgeStrategy
from backtests.strategies.base import Position


def _make_bars(closes, volumes, trade_date="20260401"):
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        hh = 9 + i // 60
        mm = i % 60
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": c, "high": c * 1.001, "low": c * 0.999,
            "close": c, "volume": v,
        })
    return pd.DataFrame(rows)


def test_defaults():
    s = VolumeSurgeStrategy()
    assert s.name == "volume_surge"
    assert s.hold_days == 0
    assert s.vol_lookback_bars == 10
    assert s.volume_mult == 3.0


def test_prepare_features_columns():
    s = VolumeSurgeStrategy()
    closes = [10000.0] * 60
    volumes = [100.0] * 60
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "vol_ratio" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    assert "bar_in_day" in feats.columns
    # 안정 거래량 → vol_ratio ≈ 1
    assert abs(feats["vol_ratio"].iloc[30] - 1.0) < 0.01


def test_entry_fires_on_volume_surge_with_price_up():
    s = VolumeSurgeStrategy(
        vol_lookback_bars=10, volume_mult=3.0,
        entry_window_start_bar=10, entry_window_end_bar=240,
    )
    closes = [10000.0] * 30 + [10100.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [500.0] + [100.0] * 10  # bar 30: 5x surge
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    order = s.entry_signal(feats, bar_idx=30, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_without_volume_surge():
    s = VolumeSurgeStrategy(volume_mult=5.0)
    closes = [10000.0] * 30 + [10100.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [200.0] + [100.0] * 10  # 2x — 5x 기준 미충족
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=30, stock_code="TEST") is None


def test_entry_no_fire_without_price_confirmation():
    s = VolumeSurgeStrategy(volume_mult=3.0)
    # 거래량은 surge 했지만 close 가 prev_close 이하 (가격 약세)
    closes = [10000.0] * 30 + [9900.0] + [10000.0] * 10
    volumes = [100.0] * 30 + [500.0] + [100.0] * 10
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert s.entry_signal(feats, bar_idx=30, stock_code="TEST") is None


def test_entry_no_fire_before_warmup():
    s = VolumeSurgeStrategy(vol_lookback_bars=20, entry_window_start_bar=20)
    closes = [10000.0, 10100.0]
    volumes = [100.0, 500.0]
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    # bar 1 < warmup window
    assert s.entry_signal(feats, bar_idx=1, stock_code="TEST") is None


def test_entry_no_fire_after_window():
    s = VolumeSurgeStrategy(entry_window_end_bar=30)
    closes = [10000.0] * 50 + [10100.0] + [10000.0] * 10
    volumes = [100.0] * 50 + [500.0] + [100.0] * 10
    df = _make_bars(closes, volumes)
    feats = s.prepare_features(df, pd.DataFrame())
    # bar 50 은 entry_window_end_bar(30) 이후
    assert s.entry_signal(feats, bar_idx=50, stock_code="TEST") is None


def test_exit_tp_sl():
    s = VolumeSurgeStrategy(take_profit_pct=3.0, stop_loss_pct=-2.0)
    pos = Position(stock_code="TEST", entry_bar_idx=30, entry_price=10100.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=10500.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=9850.0).reason == "sl"
```

- [ ] **Step 2: pytest 실패 확인**
Run: `cd D:/GIT/RoboTrader && python -m pytest tests/backtests/test_volume_surge.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: volume_surge.py 구현**

Create `backtests/strategies/volume_surge.py`:
```python
"""거래량 급증 추격 (Volume Surge Chase) — 분봉 거래량 폭증 + 가격 추종 매수."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class VolumeSurgeStrategy(StrategyBase):
    name = "volume_surge"
    hold_days = 0

    param_space = {
        "vol_lookback_bars": {"type": "int", "low": 5, "high": 30, "step": 5},
        "volume_mult": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
        "entry_window_start_bar": {"type": "int", "low": 5, "high": 60, "step": 5},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 5.0, "step": 0.5},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        vol_lookback_bars: int = 10,
        volume_mult: float = 3.0,
        entry_window_start_bar: int = 10,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.5,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.vol_lookback_bars = vol_lookback_bars
        self.volume_mult = volume_mult
        self.entry_window_start_bar = entry_window_start_bar
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"vol_ratio": [], "prev_close": [], "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        def _per_day(g: pd.DataFrame) -> pd.DataFrame:
            vol = g["volume"].astype(float)
            # rolling mean 은 현재 bar 제외 (shift(1)) 한 직전 lookback 평균
            roll_mean = vol.rolling(
                self.vol_lookback_bars, min_periods=self.vol_lookback_bars
            ).mean().shift(1)
            ratio = vol / roll_mean.replace(0, float("nan"))
            return pd.DataFrame({
                "vol_ratio": ratio,
                "prev_close": g["close"].shift(1),
            }, index=g.index)

        per_day = df.groupby("trade_date", group_keys=False).apply(_per_day)
        df = df.join(per_day)
        return df[["vol_ratio", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["vol_ratio"]) or pd.isna(row["prev_close"]):
            return None
        if row["bar_in_day"] < self.entry_window_start_bar:
            return None
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        if row["vol_ratio"] < self.volume_mult:
            return None
        # 가격 confirmation: close > prev_close
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
Expected: 8 passed.

- [ ] **Step 5: 전체 스위트**
Expected: 116 + 8 = 124 passed + 2 skipped.

- [ ] **Step 6: Commit**
```bash
git add backtests/strategies/volume_surge.py tests/backtests/test_volume_surge.py
git commit -m "feat(backtests): add volume surge chase strategy"
```

---

## Task 2: 장중 눌림목 (Intraday Pullback to 20EMA) 전략

**Files:**
- Create: `backtests/strategies/intraday_pullback.py`
- Test: `tests/backtests/test_intraday_pullback.py`

**전략 개요:**
- 상승추세 (prev_close > prev_ema20) 종목이 최근 K bars 동안 EMA20 근접까지 눌림 (touched_recent_low ≤ ema20 × (1 + proximity_pct))
- 반등 confirmation: close > prev_close
- TP/SL 기반, 당일 EOD 청산

**Parameter space:**
```python
param_space = {
    "ema_period": {"type": "int", "low": 10, "high": 40, "step": 5},
    "pullback_lookback_bars": {"type": "int", "low": 3, "high": 15, "step": 1},
    "proximity_pct": {"type": "float", "low": 0.0, "high": 1.5, "step": 0.1},
    "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
    "take_profit_pct": {"type": "float", "low": 1.0, "high": 4.0, "step": 0.25},
    "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
}
```

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_intraday_pullback.py`:
```python
"""장중 눌림목 (20EMA) 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.intraday_pullback import IntradayPullbackStrategy
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
    s = IntradayPullbackStrategy()
    assert s.name == "intraday_pullback"
    assert s.hold_days == 0
    assert s.ema_period == 20
    assert s.pullback_lookback_bars == 5


def test_prepare_features_columns():
    s = IntradayPullbackStrategy()
    closes = [10000.0 + i * 5 for i in range(60)]  # 점진 상승
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    assert "prev_ema" in feats.columns
    assert "recent_low" in feats.columns
    assert "prev_close" in feats.columns
    assert "close" in feats.columns
    assert "bar_in_day" in feats.columns
    # 30 bar 이후엔 ema 유효
    assert not pd.isna(feats["prev_ema"].iloc[40])


def test_entry_fires_on_pullback_and_rebound():
    s = IntradayPullbackStrategy(
        ema_period=20, pullback_lookback_bars=5,
        proximity_pct=0.5, entry_window_end_bar=240,
    )
    # 장기 상승 (10000→10500) 후 EMA 근접까지 일시 하락 → 반등
    closes = [10000.0 + i * 25 for i in range(20)]   # 10000→10475 상승
    closes += [10500.0] * 10                          # 횡보 (EMA 가 따라 올라옴)
    closes += [10350.0, 10340.0, 10330.0, 10320.0]    # 4 bars 하락 (EMA 근접)
    closes += [10360.0]                               # 반등
    closes += [10500.0] * 10
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    rebound_idx = 34  # 반등 bar
    # 반등 시점 EMA 와 recent_low 출력 (디버깅용)
    for idx in range(32, 36):
        if idx < len(feats):
            r = feats.iloc[idx]
            print(f"bar {idx}: prev_ema={r['prev_ema']:.1f}, recent_low={r['recent_low']:.1f}, "
                  f"prev_close={r['prev_close']:.1f}, close={r['close']:.1f}")
    orders = [
        s.entry_signal(feats, bar_idx=i, stock_code="TEST")
        for i in range(rebound_idx, rebound_idx + 3)
    ]
    assert any(o is not None for o in orders), \
        "반등 시점에서 매수 신호가 발생해야 함"


def test_entry_no_fire_in_downtrend():
    s = IntradayPullbackStrategy()
    # 지속 하락 → close < ema 이므로 추세 조건 실패
    closes = [10500.0 - i * 30 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    # 어느 bar 에서도 매수 신호 없음
    for idx in range(30, 60):
        assert s.entry_signal(feats, bar_idx=idx, stock_code="TEST") is None


def test_entry_no_fire_without_pullback():
    s = IntradayPullbackStrategy(proximity_pct=0.1)
    # 지속 강한 상승 → EMA 와 거리가 멀어 pullback 미충족
    closes = [10000.0 + i * 30 for i in range(60)]
    df = _make_bars(closes)
    feats = s.prepare_features(df, pd.DataFrame())
    for idx in range(30, 60):
        order = s.entry_signal(feats, bar_idx=idx, stock_code="TEST")
        # close 가 prev_close 보다 높지만 recent_low 도 EMA 와 멀음 → 신호 없음
        if order is not None:
            r = feats.iloc[idx]
            ratio = (r["recent_low"] - r["prev_ema"]) / r["prev_ema"] * 100
            assert ratio <= 0.1, f"bar {idx} pullback proximity {ratio:.2f}%"


def test_exit_tp_sl():
    s = IntradayPullbackStrategy(take_profit_pct=2.0, stop_loss_pct=-1.5)
    pos = Position(stock_code="TEST", entry_bar_idx=30, entry_price=10000.0,
                   quantity=10, entry_date="20260401")
    feats = pd.DataFrame({"close": [float("nan")] * 100})
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=10250.0).reason == "tp"
    assert s.exit_signal(pos, feats, bar_idx=50, current_price=9800.0).reason == "sl"
```

- [ ] **Step 2: 실패 확인**
Expected: ModuleNotFoundError.

- [ ] **Step 3: intraday_pullback.py 구현**

Create `backtests/strategies/intraday_pullback.py`:
```python
"""장중 눌림목 (Intraday Pullback to 20EMA) — 상승추세 중 EMA 근접 눌림 후 반등."""
from typing import Optional

import pandas as pd

from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class IntradayPullbackStrategy(StrategyBase):
    name = "intraday_pullback"
    hold_days = 0

    param_space = {
        "ema_period": {"type": "int", "low": 10, "high": 40, "step": 5},
        "pullback_lookback_bars": {"type": "int", "low": 3, "high": 15, "step": 1},
        "proximity_pct": {"type": "float", "low": 0.0, "high": 1.5, "step": 0.1},
        "entry_window_end_bar": {"type": "int", "low": 60, "high": 360, "step": 30},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 4.0, "step": 0.25},
        "stop_loss_pct": {"type": "float", "low": -3.0, "high": -0.8, "step": 0.25},
    }

    def __init__(
        self,
        ema_period: int = 20,
        pullback_lookback_bars: int = 5,
        proximity_pct: float = 0.5,
        entry_window_end_bar: int = 240,
        take_profit_pct: float = 2.0,
        stop_loss_pct: float = -1.5,
        budget_ratio: float = 0.30,
    ):
        self.ema_period = ema_period
        self.pullback_lookback_bars = pullback_lookback_bars
        self.proximity_pct = proximity_pct
        self.entry_window_end_bar = entry_window_end_bar
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.budget_ratio = budget_ratio

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_ema": [], "recent_low": [], "prev_close": [],
                 "close": [], "bar_in_day": []},
                index=df_minute.index,
            )
        df = df_minute.copy()
        df["bar_in_day"] = df.groupby("trade_date").cumcount()

        def _per_day(g: pd.DataFrame) -> pd.DataFrame:
            close = g["close"].astype(float)
            low = g["low"].astype(float)
            ema = close.ewm(span=self.ema_period, adjust=False).mean()
            # 직전 K bars 의 최저 low (현재 bar 제외)
            recent_low = low.rolling(
                self.pullback_lookback_bars, min_periods=self.pullback_lookback_bars
            ).min().shift(1)
            return pd.DataFrame({
                "prev_ema": ema.shift(1),
                "recent_low": recent_low,
                "prev_close": close.shift(1),
            }, index=g.index)

        per_day = df.groupby("trade_date", group_keys=False).apply(_per_day)
        df = df.join(per_day)
        return df[["prev_ema", "recent_low", "prev_close", "close", "bar_in_day"]]

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_ema"]) or pd.isna(row["recent_low"]) or pd.isna(row["prev_close"]):
            return None
        if row["bar_in_day"] > self.entry_window_end_bar:
            return None
        # 추세 조건: 직전 close 가 EMA 위
        if row["prev_close"] <= row["prev_ema"]:
            return None
        # 눌림 조건: recent_low 가 EMA 근접 (proximity_pct 이내)
        proximity_threshold = row["prev_ema"] * (1.0 + self.proximity_pct / 100.0)
        if row["recent_low"] > proximity_threshold:
            return None
        # 반등 confirmation
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
Expected: 6 passed.

- [ ] **Step 5: 전체 스위트**
Expected: 124 + 6 = 130 passed + 2 skipped.

- [ ] **Step 6: Commit**
```bash
git add backtests/strategies/intraday_pullback.py tests/backtests/test_intraday_pullback.py
git commit -m "feat(backtests): add intraday pullback (20EMA) strategy"
```

---

## Task 3: 종가 드리프트 (Closing Drift, Overnight) 전략

**Files:**
- Create: `backtests/strategies/closing_drift.py`
- Test: `tests/backtests/test_closing_drift.py`

**전략 개요:**
- 라이브 closing_trade (멀티버스 +53.7% / 승률 60.6%) 백테스트 포팅
- 진입 14:00~14:20: 전일 양봉 몸통 ≥ 1%, 당일 최저 ≥ -3% (시가 대비), close > 당일 VWAP, close > day_open
- 청산: 다음 거래일 (`hold_days=1`) → 엔진의 hold_limit 처리
- weighted_score_full 패턴 활용: `_last_df_minute` + `count_trading_days_between`

**Parameter space:**
```python
param_space = {
    "min_prev_body_pct": {"type": "float", "low": 0.5, "high": 3.0, "step": 0.25},
    "max_day_decline_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
    "entry_hhmm_start": {"type": "int", "low": 1300, "high": 1500, "step": 30},
    "entry_hhmm_end": {"type": "int", "low": 1330, "high": 1520, "step": 10},
    "gap_sl_limit_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
}
```

### Steps

- [ ] **Step 1: 테스트 작성**

Create `tests/backtests/test_closing_drift.py`:
```python
"""종가 드리프트 (오버나이트) 전략 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.closing_drift import ClosingDriftStrategy
from backtests.strategies.base import Position


def _make_minute_df(
    trade_date: str,
    n_bars: int,
    open_price: float,
    decline_low: float = None,
    afternoon_close: float = None,
    afternoon_volume_mult: float = 1.0,
):
    """09:00 시작 분봉. n_bars 만큼 생성. 14:00 이후엔 afternoon_close 로 close 고정."""
    rows = []
    for i in range(n_bars):
        hh = 9 + i // 60
        mm = i % 60
        if i == 0:
            close = open_price
            high = open_price * 1.002
            low = open_price * 0.998
        else:
            # 09~13: 시가 근방, 13:00 부터 day_low 로 하락 (조건 검증용)
            if decline_low is not None and 60 <= i < 240:
                close = open_price - (open_price - decline_low) * ((i - 60) / 180)
            else:
                close = open_price * (1.0 - 0.0001 * (i % 5))
            # 14:00 이후 afternoon_close 적용
            if afternoon_close is not None and i >= 300:
                close = afternoon_close
            high = close * 1.001
            low = min(close * 0.999, decline_low if decline_low else close)
        vol = 1000.0 * (afternoon_volume_mult if i >= 300 else 1.0)
        rows.append({
            "stock_code": "TEST",
            "trade_date": trade_date,
            "trade_time": f"{hh:02d}{mm:02d}00",
            "open": close, "high": high, "low": low,
            "close": close, "volume": vol,
        })
    return pd.DataFrame(rows)


def _make_daily_df(stock_code: str, prev_open: float, prev_close: float):
    """전일 + 당일(open만 있어도 됨) 일봉."""
    return pd.DataFrame([
        {"stock_code": stock_code, "trade_date": "20260331",
         "open": prev_open, "high": prev_close * 1.01, "low": prev_open * 0.99,
         "close": prev_close, "volume": 100000.0},
        {"stock_code": stock_code, "trade_date": "20260401",
         "open": 10000.0, "high": 10100.0, "low": 9900.0,
         "close": 10000.0, "volume": 100000.0},
    ])


def _multi_day_minute_df(n_days: int = 2, base_open: float = 10000.0):
    """여러 날짜 분봉 합쳐 hold_days=1 테스트용."""
    dfs = []
    dates = ["20260401", "20260402"][:n_days]
    for d in dates:
        dfs.append(_make_minute_df(d, n_bars=390, open_price=base_open,
                                    afternoon_close=base_open * 1.005))
    return pd.concat(dfs, ignore_index=True)


def test_defaults():
    s = ClosingDriftStrategy()
    assert s.name == "closing_drift"
    assert s.hold_days == 1
    assert s.entry_hhmm_start == 1400
    assert s.entry_hhmm_end == 1420
    assert s.min_prev_body_pct == 1.0


def test_prepare_features_columns():
    s = ClosingDriftStrategy()
    minute = _make_minute_df("20260401", n_bars=390, open_price=10000.0,
                             afternoon_close=10100.0)
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    assert "prev_body_pct" in feats.columns
    assert "day_open" in feats.columns
    assert "day_low_pct" in feats.columns
    assert "vwap" in feats.columns
    assert "close" in feats.columns
    assert "hhmm" in feats.columns
    # prev_body = (9900 - 9800)/9800 = +1.02%
    assert abs(feats["prev_body_pct"].iloc[0] - 1.0204) < 0.01


def test_entry_fires_at_1400_with_signal():
    s = ClosingDriftStrategy(min_prev_body_pct=1.0, max_day_decline_pct=-3.0)
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9800.0,         # 시가 대비 -2% (≥ -3% 통과)
        afternoon_close=10100.0,    # 14:00 이후 +1% (시가 위, VWAP 위 가능)
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)  # body +1.02%
    feats = s.prepare_features(minute, daily)
    # bar 300 = 14:00 → 진입 윈도우 내
    order = s.entry_signal(feats, bar_idx=305, stock_code="TEST")
    assert order is not None


def test_entry_no_fire_outside_time_window():
    s = ClosingDriftStrategy()
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9800.0, afternoon_close=10100.0,
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    # bar 60 (10:00) — 진입 윈도우 이전
    assert s.entry_signal(feats, bar_idx=60, stock_code="TEST") is None
    # bar 350 (14:50) — 진입 윈도우(14:20) 이후
    assert s.entry_signal(feats, bar_idx=350, stock_code="TEST") is None


def test_entry_no_fire_with_weak_prev_body():
    s = ClosingDriftStrategy(min_prev_body_pct=1.0)
    minute = _make_minute_df("20260401", n_bars=390, open_price=10000.0,
                             decline_low=9800.0, afternoon_close=10100.0)
    # 전일 양봉 0.5% — 1% 기준 미충족
    daily = _make_daily_df("TEST", prev_open=9950.0, prev_close=10000.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=305, stock_code="TEST") is None


def test_entry_no_fire_with_deep_decline():
    s = ClosingDriftStrategy(max_day_decline_pct=-3.0)
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9500.0,         # 시가 대비 -5% (< -3% 실패)
        afternoon_close=10100.0,
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=305, stock_code="TEST") is None


def test_entry_no_fire_below_day_open():
    s = ClosingDriftStrategy()
    minute = _make_minute_df(
        "20260401", n_bars=390, open_price=10000.0,
        decline_low=9800.0,
        afternoon_close=9950.0,     # 시가 미복귀
    )
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    feats = s.prepare_features(minute, daily)
    assert s.entry_signal(feats, bar_idx=305, stock_code="TEST") is None


def test_exit_signal_holds_until_next_day():
    s = ClosingDriftStrategy()
    multi = _multi_day_minute_df(n_days=2)
    daily = _make_daily_df("TEST", prev_open=9800.0, prev_close=9900.0)
    s.prepare_features(multi, daily)  # _last_df_minute 캐시
    pos = Position(stock_code="TEST", entry_bar_idx=305, entry_price=10100.0,
                   quantity=10, entry_date="20260401")
    # 같은 날 (bar 350) — 청산 안 함
    assert s.exit_signal(pos, pd.DataFrame(), bar_idx=350, current_price=10120.0) is None
    # 다음 날 첫 bar (bar 390 = 20260402 09:00) — hold_limit 청산
    out = s.exit_signal(pos, pd.DataFrame(), bar_idx=390, current_price=10150.0)
    assert out is not None
    assert out.reason == "hold_limit"
```

- [ ] **Step 2: 실패 확인**
Expected: ModuleNotFoundError.

- [ ] **Step 3: closing_drift.py 구현**

Create `backtests/strategies/closing_drift.py`:
```python
"""종가 드리프트 (Closing Drift) — 14:00~14:20 진입, 익일 청산.

라이브 core/strategies/closing_trade_strategy.py 의 backtest 포팅.
overnight hold (hold_days=1) — 엔진의 _last_df_minute 패턴 (weighted_score_full 동일).
"""
from typing import Optional

import numpy as np
import pandas as pd

from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class ClosingDriftStrategy(StrategyBase):
    name = "closing_drift"
    hold_days = 1

    param_space = {
        "min_prev_body_pct": {"type": "float", "low": 0.5, "high": 3.0, "step": 0.25},
        "max_day_decline_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
        "entry_hhmm_start": {"type": "int", "low": 1300, "high": 1500, "step": 30},
        "entry_hhmm_end": {"type": "int", "low": 1330, "high": 1520, "step": 10},
        "gap_sl_limit_pct": {"type": "float", "low": -5.0, "high": -1.0, "step": 0.5},
    }

    def __init__(
        self,
        min_prev_body_pct: float = 1.0,
        max_day_decline_pct: float = -3.0,
        entry_hhmm_start: int = 1400,
        entry_hhmm_end: int = 1420,
        gap_sl_limit_pct: float = -3.0,
        budget_ratio: float = 0.20,
    ):
        self.min_prev_body_pct = min_prev_body_pct
        self.max_day_decline_pct = max_day_decline_pct
        self.entry_hhmm_start = entry_hhmm_start
        self.entry_hhmm_end = entry_hhmm_end
        self.gap_sl_limit_pct = gap_sl_limit_pct
        self.budget_ratio = budget_ratio
        self._last_df_minute: Optional[pd.DataFrame] = None

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        self._last_df_minute = df_minute
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_body_pct": [], "day_open": [], "day_low_pct": [],
                 "vwap": [], "close": [], "hhmm": []},
                index=df_minute.index,
            )
        df = df_minute.copy()

        # 전일 body% (daily 에서 shift(1) 로 직전 거래일 close/open)
        prev_body_map = self._build_prev_body_map(df_daily)
        df["prev_body_pct"] = df["trade_date"].map(prev_body_map)

        # 시가, 누적 최저 (시가 대비 %)
        day_open_per_date = df.groupby("trade_date")["open"].first()
        df["day_open"] = df["trade_date"].map(day_open_per_date)
        df["day_low_so_far"] = df.groupby("trade_date")["low"].cummin()
        df["day_low_pct"] = (df["day_low_so_far"] - df["day_open"]) / df["day_open"] * 100.0

        # 누적 VWAP
        typ = (df["high"] + df["low"] + df["close"]) / 3.0
        pv = typ * df["volume"]
        cum_pv = df.groupby("trade_date")[pv.name if pv.name else 0].cumsum() if False else pv.groupby(df["trade_date"]).cumsum()
        cum_v = df.groupby("trade_date")["volume"].cumsum()
        df["vwap"] = cum_pv / cum_v.replace(0, np.nan)

        # hhmm (정수, 1400 = 14:00)
        df["hhmm"] = df["trade_time"].astype(str).str[:4].astype(int)

        return df[["prev_body_pct", "day_open", "day_low_pct", "vwap", "close", "hhmm"]]

    @staticmethod
    def _build_prev_body_map(df_daily: pd.DataFrame) -> dict:
        if df_daily is None or df_daily.empty:
            return {}
        d = df_daily.sort_values("trade_date").copy()
        d["prev_open"] = d["open"].shift(1)
        d["prev_close"] = d["close"].shift(1)
        d["prev_body_pct"] = (d["prev_close"] - d["prev_open"]) / d["prev_open"] * 100.0
        return dict(zip(d["trade_date"], d["prev_body_pct"]))

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if bar_idx >= len(features):
            return None
        row = features.iloc[bar_idx]
        if pd.isna(row["prev_body_pct"]) or pd.isna(row["day_open"]):
            return None
        # 시간 윈도우
        if row["hhmm"] < self.entry_hhmm_start or row["hhmm"] >= self.entry_hhmm_end:
            return None
        # 전일 양봉 몸통
        if row["prev_body_pct"] < self.min_prev_body_pct:
            return None
        # 당일 최저점 제한
        if row["day_low_pct"] < self.max_day_decline_pct:
            return None
        # close > day_open (본전 이상)
        if row["close"] <= row["day_open"]:
            return None
        # close > VWAP
        if pd.isna(row["vwap"]) or row["close"] <= row["vwap"]:
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
        # 오버나이트 — 다음 거래일 진입 시점에서 청산 (hold_limit)
        if self._last_df_minute is None:
            return None
        days_held = count_trading_days_between(
            self._last_df_minute,
            from_idx=position.entry_bar_idx,
            to_idx=bar_idx,
        )
        if days_held >= self.hold_days:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None
```

- [ ] **Step 4: PASS 확인**
Expected: 8 passed.

- [ ] **Step 5: 전체 스위트**
Expected: 130 + 8 = 138 passed + 2 skipped.

- [ ] **Step 6: Commit**
```bash
git add backtests/strategies/closing_drift.py tests/backtests/test_closing_drift.py
git commit -m "feat(backtests): add closing drift overnight strategy"
```

---

## Phase 2B-3 Wrap-up

- [ ] **완료 노트**

Append to `backtests/reports/phase1_baseline_notes.md`:
```markdown

---

## Phase 2B-3 완료 (2026-04-25)

- [x] 거래량 급증 추격 (Volume Surge Chase)
- [x] 장중 눌림목 (20EMA Pullback)
- [x] 종가 드리프트 (Closing Drift, overnight hold=1)

전체 tests: 138 passed + 2 skipped.

**남은 classic 전략 (Phase 2B-4, 2C 예정)**:
- 상한가 따라잡기 (Phase 2B-4, 특수)
- Overnight swing 5개 (Phase 2C: 종가매수→시가매도, 52주 신고가, 낙주 반등, 추세 follow-through, MACD 골든크로스)
```

- [ ] **Commit**
```bash
git add backtests/reports/phase1_baseline_notes.md
git commit -m "docs(backtests): Phase 2B-3 complete (3 trend/volume strategies)"
```

---

## Summary

**New files (6):**
- `backtests/strategies/volume_surge.py` + test (8 tests)
- `backtests/strategies/intraday_pullback.py` + test (6 tests)
- `backtests/strategies/closing_drift.py` + test (8 tests)

**Modified:**
- `backtests/reports/phase1_baseline_notes.md` — Phase 2B-3 완료 섹션

**Phase 2B-3 목표**: 138 tests passed + 2 skipped.
**Phase 2B-4 시작 조건**: 이 플랜 완료.
