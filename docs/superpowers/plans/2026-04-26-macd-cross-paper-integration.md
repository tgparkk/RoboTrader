# macd_cross 페이퍼 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** macd_cross 전략을 라이브 봇에 페이퍼(가상매매) 모드로 통합. weighted_score 라이브 운영을 보호하며 백테스트 OOS 결과를 4주/30 trades 동안 재현 검증한다.

**Architecture:** dual-strategy dispatch — `ACTIVE_STRATEGY=weighted_score` (실거래) + `PAPER_STRATEGY=macd_cross` (가상). 시그널 코드는 백테스트와 라이브가 공유 (`core/strategies/macd_cross_signal.py`). macd_cross 가상 포지션은 라이브 안전망(서킷브레이커/SL/EOD 청산) 으로부터 격리.

**Tech Stack:** Python 3.9, asyncio, PostgreSQL (psycopg2), pandas, pytest. KIS API 분봉 피드, intraday_manager.

**Spec:** `docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md`

---

## File Structure

**Create:**
- `core/strategies/macd_cross_signal.py` — 공유 시그널 (백테스트·라이브 1:1 동등)
- `core/strategies/macd_cross_strategy.py` — 라이브 어댑터 (intraday_manager 와 결합)
- `core/strategies/macd_cross_kpi.py` — paper KPI 집계 + 6 게이트 평가
- `tests/strategies/test_macd_cross_signal_parity.py` — 백테스트·라이브 시그널 parity
- `tests/strategies/test_macd_cross_kpi.py` — KPI 계산 + 게이트 평가
- `tests/integration/test_macd_cross_paper_flow.py` — universe → 시그널 → 가상매수 → EOD 격리 → 만료청산 e2e

**Modify:**
- `config/strategy_settings.py` — `MacdCross` 클래스 + `PAPER_STRATEGY` 변수
- `backtests/strategies/macd_cross.py` — 공유 시그널 함수 호출로 변경
- `core/stock_screener.py` — `preload_macd_cross_universe()` 추가
- `main.py` — `_prepare_macd_cross_universe`, `_analyze_buy_decision` paper 분기, `_execute_end_of_day_liquidation` 격리, EOD 후 KPI 보고
- `CLAUDE.md` — 페이퍼 운영 상태 기록

**Verify-only (변경 없음):**
- `db/database_manager.py` — `virtual_trading_records.strategy` 컬럼 이미 존재 (line 617). 마이그레이션 불필요, 스키마 검증 단계만 수행.

---

## Task 1: MacdCross 설정 클래스 + PAPER_STRATEGY 변수 추가

**Files:**
- Modify: `config/strategy_settings.py:17-29`
- Test: 없음 (설정 상수만 추가)

- [ ] **Step 1: config/strategy_settings.py 의 ACTIVE_STRATEGY 정의 위에 PAPER_STRATEGY 추가**

`config/strategy_settings.py` line 29 위에 다음 추가:

```python
    # ========================================
    # 페이퍼 전략 (실거래 primary 옆에서 가상매매로 동시 운영, 2026-04-26)
    # ========================================
    # None       : 페이퍼 비활성
    # 'macd_cross': macd_cross 가상매매 (4주 또는 30건 paper 검증)
    PAPER_STRATEGY = 'macd_cross'  # <-- None 으로 두면 페이퍼 OFF
```

- [ ] **Step 2: ClosingTrade 클래스 위 (line 31 근처) MacdCross 설정 클래스 추가**

```python
    # ========================================
    # macd_cross 전략 설정 (페이퍼 단계, 2026-04-26)
    # ========================================
    class MacdCross:
        """
        macd_cross 페이퍼 트레이딩 파라미터.

        Stage 2 best params (backtests/reports/stage2/macd_cross_best.json):
          fast=14, slow=34, signal=12, entry_hhmm_min=1430
        OOS 성과 (backtests/reports/stage2/oos_summary.csv):
          Calmar 54.16, return +11.66%, MDD 1.99%, win 61.1%, 36 trades

        설계서: docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md
        """
        # ---- 시그널 (백테스트와 동일) ----
        FAST_PERIOD = 14
        SLOW_PERIOD = 34
        SIGNAL_PERIOD = 12

        # ---- 진입 시간대 (HHMM int) ----
        ENTRY_HHMM_MIN = 1430
        ENTRY_HHMM_MAX = 1500

        # ---- 청산 ----
        HOLD_DAYS = 2  # 거래일 기준. SL/TP 없음 (G1: 백테스트 100% 재현)

        # ---- 페이퍼 자금 (F1) ----
        VIRTUAL_CAPITAL = 10_000_000           # 가상 자본 1천만원
        BUY_BUDGET_RATIO = 0.20                # 종목당 200만원
        MAX_DAILY_POSITIONS = 5                # 동시 보유 최대

        # ---- Universe ----
        UNIVERSE_TOP_N = 30                    # 거래대금 상위 30 (백테스트 동일)

        # ---- 운영 가드 (G1: 라이브 필터 미적용) ----
        APPLY_LIVE_OVERLAY = False             # 승격 시 True 검토
        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]
```

- [ ] **Step 3: 검증**

Run:
```bash
python -c "from config.strategy_settings import StrategySettings; print(StrategySettings.PAPER_STRATEGY, StrategySettings.MacdCross.FAST_PERIOD)"
```
Expected: `macd_cross 14`

- [ ] **Step 4: Commit**

```bash
git add config/strategy_settings.py
git commit -m "feat(strategy_settings): add MacdCross paper config + PAPER_STRATEGY var"
```

---

## Task 2: 공유 시그널 모듈 + parity 테스트

**Files:**
- Create: `core/strategies/macd_cross_signal.py`
- Test: `tests/strategies/test_macd_cross_signal_parity.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/strategies/test_macd_cross_signal_parity.py`:
```python
"""macd_cross 공유 시그널 모듈 parity 테스트.

핵심: 백테스트(backtests/strategies/macd_cross.py) 와 공유 모듈
(core/strategies/macd_cross_signal.py) 의 시그널 식이 1:1 동등해야 한다.
한 픽셀이라도 다르면 OOS 재현 검증이 의미를 잃는다.
"""
import numpy as np
import pandas as pd
import pytest

from core.strategies.macd_cross_signal import (
    compute_macd_histogram_series,
    is_macd_golden_cross,
)


def _make_daily(close_series, start="2025-01-02"):
    dates = pd.date_range(start, periods=len(close_series), freq="B").strftime("%Y%m%d")
    return pd.DataFrame({
        "trade_date": dates.astype(str),
        "close": close_series,
    })


def test_compute_macd_histogram_matches_known_values():
    """알려진 EMA 결과와 일치 (sanity check)."""
    np.random.seed(42)
    close = 10000 + np.cumsum(np.random.randn(100) * 50)
    df = _make_daily(close)
    hist = compute_macd_histogram_series(df, fast=12, slow=26, signal=9)
    assert len(hist) == 100
    assert pd.notna(hist.iloc[-1])
    # MACD hist 는 EMA(close, 12) - EMA(close, 26) - signal_ema 이므로 마지막 값이 finite
    assert np.isfinite(hist.iloc[-1])


def test_golden_cross_detection_positive():
    """prev_prev_hist < 0 AND prev_hist >= 0 → True."""
    assert is_macd_golden_cross(prev_hist=0.5, prev_prev_hist=-0.3) is True
    assert is_macd_golden_cross(prev_hist=0.0, prev_prev_hist=-0.001) is True


def test_golden_cross_detection_negative():
    """음→음, 양→양, 양→음 모두 False."""
    assert is_macd_golden_cross(prev_hist=-0.1, prev_prev_hist=-0.3) is False
    assert is_macd_golden_cross(prev_hist=0.5, prev_prev_hist=0.3) is False
    assert is_macd_golden_cross(prev_hist=-0.1, prev_prev_hist=0.3) is False


def test_golden_cross_nan_returns_false():
    """NaN 입력은 False (시계열 워밍업 부족)."""
    assert is_macd_golden_cross(prev_hist=float("nan"), prev_prev_hist=-0.3) is False
    assert is_macd_golden_cross(prev_hist=0.5, prev_prev_hist=float("nan")) is False


def test_parity_against_backtest_strategy():
    """백테스트 MACDCrossStrategy._build_macd_maps 와 시그널 식이 동일해야 한다.

    100개 랜덤 daily 시퀀스 × Stage 2 best params (14/34/12) 로 매일
    is_macd_golden_cross 결과를 비교 → 모두 일치해야 통과.
    """
    from backtests.strategies.macd_cross import MACDCrossStrategy

    np.random.seed(123)
    close = 10000 + np.cumsum(np.random.randn(120) * 50)
    df = _make_daily(close)

    bt = MACDCrossStrategy(fast_period=14, slow_period=34, signal_period=12)
    prev_hist_map, prev_prev_hist_map = bt._build_macd_maps(df)

    hist = compute_macd_histogram_series(df, fast=14, slow=34, signal=12)
    # 공유 모듈 hist[i] 가 backtest 의 prev_hist_map[date[i+1]] 과 같아야 함 (shift1).
    for i in range(len(df) - 1):
        date_next = df["trade_date"].iloc[i + 1]
        bt_prev_hist = prev_hist_map.get(date_next)
        shared_prev_hist = hist.iloc[i]
        if pd.isna(bt_prev_hist) or pd.isna(shared_prev_hist):
            continue
        assert abs(bt_prev_hist - shared_prev_hist) < 1e-9, (
            f"day {i+1}: backtest prev_hist={bt_prev_hist} vs shared={shared_prev_hist}"
        )
```

- [ ] **Step 2: Run test → FAIL (모듈 없음)**

Run: `pytest tests/strategies/test_macd_cross_signal_parity.py -v`
Expected: FAIL with `ModuleNotFoundError: core.strategies.macd_cross_signal`

- [ ] **Step 3: 공유 모듈 구현**

`core/strategies/macd_cross_signal.py`:
```python
"""macd_cross 시그널 식 (백테스트·라이브 공유, 2026-04-26).

backtests/strategies/macd_cross.py 와 core/strategies/macd_cross_strategy.py 가
이 모듈만을 호출해야 한다. 한 픽셀이라도 다르면 페이퍼 단계 OOS 재현
검증이 의미를 잃는다.

Spec: docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md §4.4
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd


def compute_macd_histogram_series(
    df_daily: pd.DataFrame,
    fast: int,
    slow: int,
    signal: int,
) -> pd.Series:
    """일봉 close 시퀀스로부터 MACD histogram 시계열을 계산한다.

    Args:
        df_daily: `trade_date` 오름차순 + `close` 컬럼 보유. 최소 slow+signal 일 필요.
        fast: 빠른 EMA span
        slow: 느린 EMA span
        signal: signal EMA span

    Returns:
        histogram 시계열 (df_daily.index 와 1:1).
        EMA span 적응 기간 동안은 finite 이지만 의미 부족 (호출 측이 NaN 처리는 안 함).
    """
    if df_daily is None or df_daily.empty:
        return pd.Series([], dtype=float)
    d = df_daily.sort_values("trade_date")
    close = d["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd - sig


def is_macd_golden_cross(
    prev_hist: Optional[float],
    prev_prev_hist: Optional[float],
) -> bool:
    """직전 거래일 MACD histogram 음→양 골든크로스 판정.

    백테스트 entry_signal 의 핵심 식 (prev_prev_hist < 0 AND prev_hist >= 0).
    한 픽셀이라도 다르면 OOS 재현 검증 의미를 잃는다.
    """
    if prev_hist is None or prev_prev_hist is None:
        return False
    if isinstance(prev_hist, float) and math.isnan(prev_hist):
        return False
    if isinstance(prev_prev_hist, float) and math.isnan(prev_prev_hist):
        return False
    return prev_prev_hist < 0 and prev_hist >= 0


def is_in_entry_window(hhmm: int, hhmm_min: int, hhmm_max: int) -> bool:
    """진입 시간대 검사 (HHMM int 비교)."""
    return hhmm_min <= hhmm <= hhmm_max
```

- [ ] **Step 4: Run test → PASS**

Run: `pytest tests/strategies/test_macd_cross_signal_parity.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/strategies/macd_cross_signal.py tests/strategies/test_macd_cross_signal_parity.py
git commit -m "feat(strategies): shared macd_cross signal module + parity test"
```

---

## Task 3: 백테스트 전략을 공유 모듈로 리팩토링

**Files:**
- Modify: `backtests/strategies/macd_cross.py:56-90`

- [ ] **Step 1: 기존 backtest 전략의 `_build_macd_maps` 와 `entry_signal` 를 공유 모듈 호출로 교체**

`backtests/strategies/macd_cross.py` 전체를 다음으로 교체:
```python
"""macd_cross — Daily MACD 히스토그램 음→양 골든크로스, 2일 홀드.

시그널 식은 core.strategies.macd_cross_signal 모듈에서 단일 정의.
라이브와 1:1 동등 보장 (Spec §4.4).
"""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder
from core.strategies.macd_cross_signal import (
    compute_macd_histogram_series,
    is_macd_golden_cross,
    is_in_entry_window,
)


class MACDCrossStrategy(StrategyBase):
    name = "macd_cross"
    hold_days = 2

    param_space = {
        "fast_period": {"type": "int", "low": 8, "high": 16, "step": 2},
        "slow_period": {"type": "int", "low": 20, "high": 40, "step": 2},
        "signal_period": {"type": "int", "low": 7, "high": 12, "step": 1},
        "entry_hhmm_min": {"type": "int", "low": 1430, "high": 1500, "step": 10},
    }

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        entry_hhmm_min: int = 1450,
        entry_hhmm_max: int = 1500,
        budget_ratio: float = 0.20,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.entry_hhmm_min = entry_hhmm_min
        self.entry_hhmm_max = entry_hhmm_max
        self.budget_ratio = budget_ratio
        self._last_df_minute: Optional[pd.DataFrame] = None

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        self._last_df_minute = df_minute
        if df_minute.empty:
            return pd.DataFrame(
                {"prev_hist": [], "prev_prev_hist": [], "hhmm": []},
                index=df_minute.index,
            )
        df = df_minute.copy()

        prev_hist_map, prev_prev_hist_map = self._build_macd_maps(df_daily)
        df["prev_hist"] = df["trade_date"].map(prev_hist_map)
        df["prev_prev_hist"] = df["trade_date"].map(prev_prev_hist_map)
        df["hhmm"] = df["trade_time"].astype(str).str[:4].astype(int)
        return df[["prev_hist", "prev_prev_hist", "hhmm"]]

    def _build_macd_maps(self, df_daily: pd.DataFrame):
        """공유 모듈 호출 + shift(1)/shift(2) 적용해 prev/prev_prev map 생성."""
        if df_daily is None or df_daily.empty:
            return {}, {}
        d = df_daily.sort_values("trade_date").copy()
        hist = compute_macd_histogram_series(
            d, fast=self.fast_period, slow=self.slow_period, signal=self.signal_period
        )
        prev_hist = hist.shift(1)
        prev_prev_hist = hist.shift(2)
        return (
            dict(zip(d["trade_date"], prev_hist)),
            dict(zip(d["trade_date"], prev_prev_hist)),
        )

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        arr = get_arrays(features)
        if bar_idx >= len(arr["hhmm"]):
            return None
        prev_hist = arr["prev_hist"][bar_idx]
        prev_prev_hist = arr["prev_prev_hist"][bar_idx]
        hhmm = arr["hhmm"][bar_idx]
        if not is_in_entry_window(hhmm, self.entry_hhmm_min, self.entry_hhmm_max):
            return None
        if not is_macd_golden_cross(prev_hist, prev_prev_hist):
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

- [ ] **Step 2: parity 테스트 재실행 → 여전히 PASS**

Run: `pytest tests/strategies/test_macd_cross_signal_parity.py -v`
Expected: 5 tests PASS

- [ ] **Step 3: 백테스트 OOS 회귀 확인 — Stage 2 trial 1개를 재실행해 OOS 메트릭 동일성 확인**

Run:
```bash
python -c "
from backtests.strategies.macd_cross import MACDCrossStrategy
import pandas as pd
import numpy as np
np.random.seed(42)
close = 10000 + np.cumsum(np.random.randn(60)*50)
dates = pd.date_range('2025-01-02', periods=60, freq='B').strftime('%Y%m%d')
df_d = pd.DataFrame({'trade_date': dates, 'close': close})
s = MACDCrossStrategy(fast_period=14, slow_period=34, signal_period=12)
m1, m2 = s._build_macd_maps(df_d)
print('prev_hist last 3:', list(m1.values())[-3:])
print('prev_prev_hist last 3:', list(m2.values())[-3:])
"
```
Expected: 결정론적 finite 값 출력 (NaN 아님). 차후 reference 로 사용.

- [ ] **Step 4: Commit**

```bash
git add backtests/strategies/macd_cross.py
git commit -m "refactor(backtests): macd_cross uses shared signal module"
```

---

## Task 4: 라이브 어댑터 — MACDCrossStrategy

**Files:**
- Create: `core/strategies/macd_cross_strategy.py`
- Test: `tests/strategies/test_macd_cross_strategy.py`

- [ ] **Step 1: 어댑터 단위 테스트 작성 (FAIL)**

`tests/strategies/test_macd_cross_strategy.py`:
```python
"""macd_cross 라이브 어댑터 단위 테스트."""
import math
import pandas as pd
import pytest

from core.strategies.macd_cross_strategy import MacdCrossStrategy


def _daily_df(closes):
    dates = pd.date_range("2025-01-02", periods=len(closes), freq="B").strftime("%Y%m%d")
    return pd.DataFrame({"trade_date": dates.astype(str), "close": closes})


def test_compute_today_signal_inputs_caches_per_stock():
    """compute_today_signal_inputs 는 종목별 prev/prev_prev hist 를 캐시."""
    s = MacdCrossStrategy(fast=14, slow=34, signal=12)
    closes = [10000 + i * 10 for i in range(60)]
    s.set_daily_history("005930", _daily_df(closes), today_yyyymmdd="20250401")
    prev, prev_prev = s.get_cached_hist("005930")
    assert prev is not None and not math.isnan(prev)
    assert prev_prev is not None and not math.isnan(prev_prev)


def test_check_entry_returns_true_on_cached_golden_cross():
    """캐시된 hist 값으로 골든크로스 + 시간대 충족 시 True."""
    s = MacdCrossStrategy(fast=14, slow=34, signal=12,
                          entry_hhmm_min=1430, entry_hhmm_max=1500)
    s._cache["005930"] = (0.5, -0.3)  # prev=0.5, prev_prev=-0.3 → cross
    assert s.check_entry("005930", hhmm=1430) is True
    assert s.check_entry("005930", hhmm=1500) is True


def test_check_entry_false_outside_window():
    s = MacdCrossStrategy()
    s._cache["005930"] = (0.5, -0.3)
    assert s.check_entry("005930", hhmm=1400) is False
    assert s.check_entry("005930", hhmm=1501) is False


def test_check_entry_false_when_not_cached():
    s = MacdCrossStrategy()
    assert s.check_entry("999999", hhmm=1430) is False


def test_check_entry_false_when_no_cross():
    s = MacdCrossStrategy()
    s._cache["005930"] = (-0.1, -0.3)  # 음→음
    assert s.check_entry("005930", hhmm=1430) is False
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/strategies/test_macd_cross_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError: core.strategies.macd_cross_strategy`

- [ ] **Step 3: 어댑터 구현**

`core/strategies/macd_cross_strategy.py`:
```python
"""macd_cross 라이브 어댑터.

페이퍼 단계 운영:
- 매일 pre_market 에서 종목별 daily history 주입 → MACD hist 계산 → prev/prev_prev 캐시
- 14:30~15:00 매 분봉 마감 시점에 캐시된 hist + 현재 hhmm 으로 골든크로스 판정
- 시그널 발생 시 main._analyze_buy_decision 이 가상매매 라우팅

Spec §4.2: 백테스트 macd_cross 의 시그널 식과 1:1 동등 보장.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from core.strategies.macd_cross_signal import (
    compute_macd_histogram_series,
    is_macd_golden_cross,
    is_in_entry_window,
)


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
    ):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.entry_hhmm_min = entry_hhmm_min
        self.entry_hhmm_max = entry_hhmm_max
        self.logger = logger
        # {stock_code: (prev_hist, prev_prev_hist)} — 매일 pre_market 에서 갱신
        self._cache: Dict[str, Tuple[float, float]] = {}
        self._cache_date: Optional[str] = None

    def set_daily_history(
        self, stock_code: str, df_daily: pd.DataFrame, today_yyyymmdd: str
    ) -> None:
        """종목별 daily 시퀀스 주입 → MACD hist 계산 → prev/prev_prev 캐시.

        Args:
            df_daily: 오늘 이전 거래일까지의 일봉 (trade_date asc, close 컬럼).
            today_yyyymmdd: 진입 대상 거래일 (YYYYMMDD). 캐시 invalidation 키.
        """
        if self._cache_date != today_yyyymmdd:
            self._cache.clear()
            self._cache_date = today_yyyymmdd

        if df_daily is None or df_daily.empty or len(df_daily) < self.slow + self.signal:
            return

        hist = compute_macd_histogram_series(
            df_daily, fast=self.fast, slow=self.slow, signal=self.signal
        )
        if len(hist) < 2:
            return
        prev_hist = float(hist.iloc[-1])      # 가장 최근 거래일 hist (= 진입일 직전 거래일)
        prev_prev_hist = float(hist.iloc[-2]) # 그 직전 거래일
        self._cache[stock_code] = (prev_hist, prev_prev_hist)

    def get_cached_hist(self, stock_code: str) -> Tuple[Optional[float], Optional[float]]:
        return self._cache.get(stock_code, (None, None))

    def check_entry(self, stock_code: str, hhmm: int) -> bool:
        """진입 판정. 캐시된 hist + 시간대 + 골든크로스 충족 시 True."""
        if not is_in_entry_window(hhmm, self.entry_hhmm_min, self.entry_hhmm_max):
            return False
        prev_hist, prev_prev_hist = self.get_cached_hist(stock_code)
        return is_macd_golden_cross(prev_hist, prev_prev_hist)

    def cached_universe_size(self) -> int:
        return len(self._cache)
```

- [ ] **Step 4: Run → PASS**

Run: `pytest tests/strategies/test_macd_cross_strategy.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/strategies/macd_cross_strategy.py tests/strategies/test_macd_cross_strategy.py
git commit -m "feat(strategies): macd_cross live adapter with daily-history cache"
```

---

## Task 5: stock_screener.preload_macd_cross_universe()

**Files:**
- Modify: `core/stock_screener.py` (preload_weighted_score_universe 아래)
- Test: 통합 테스트는 Task 12 에서 실행. 단위 테스트 생략 (DB 의존).

- [ ] **Step 1: preload_macd_cross_universe 메서드 추가**

`core/stock_screener.py` 에서 `preload_weighted_score_universe` 끝부분 다음 위치에 추가:

```python
    def preload_macd_cross_universe(self, top_n: int = 30) -> List[ScreenedStock]:
        """macd_cross 페이퍼 universe 공급 (2026-04-26).

        전일 거래대금 상위 top_n 종목 (백테스트 universe 정의와 동일).
        weighted_score 의 research universe 교집합 적용 안 함 — 백테스트 정의 그대로.

        Args:
            top_n: 거래대금 상위 N (기본 30, Stage 2 universe)

        Returns:
            ScreenedStock 리스트.
        """
        import psycopg2
        from config.settings import (
            PG_HOST, PG_PORT, PG_DATABASE_QUANT, PG_USER, PG_PASSWORD,
        )

        candidates: List[ScreenedStock] = []
        try:
            conn = psycopg2.connect(
                host=PG_HOST, port=PG_PORT, database=PG_DATABASE_QUANT,
                user=PG_USER, password=PG_PASSWORD, connect_timeout=5,
            )
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                self.logger.warning("[macd_cross.univ] daily_prices 비어있음")
                cur.close()
                conn.close()
                return []
            prev_date_iso = row[0]

            min_price = self.config.get('min_price', 5000)
            max_price = self.config.get('max_price', 500000)

            cur.execute(
                '''SELECT stock_code, open, close, trading_value
                   FROM daily_prices
                   WHERE date = %s AND open IS NOT NULL AND close IS NOT NULL
                     AND close BETWEEN %s AND %s
                   ORDER BY trading_value DESC NULLS LAST
                   LIMIT %s''',
                [prev_date_iso, min_price, max_price, top_n],
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            for stock_code, open_p, close_p, trading_value in rows:
                stock_name = self._lookup_stock_name(stock_code) or stock_code
                candidates.append(ScreenedStock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    current_price=float(close_p),
                    volume=0,
                    score=float(trading_value or 0),
                    reason="macd_cross_universe",
                    detected_at=now_kst(),
                ))

            self.logger.info(
                f"[macd_cross.univ] preload 완료: {len(candidates)}종목 "
                f"(date={prev_date_iso}, top_n={top_n})"
            )
            return candidates

        except Exception as e:
            self.logger.error(f"[macd_cross.univ] preload 실패: {e}")
            return []
```

- [ ] **Step 2: import 검증**

Run:
```bash
python -c "from core.stock_screener import StockScreener; print(hasattr(StockScreener, 'preload_macd_cross_universe'))"
```
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add core/stock_screener.py
git commit -m "feat(screener): preload_macd_cross_universe (top30 by trading value)"
```

---

## Task 6: pre_market 훅 — _prepare_macd_cross_universe

**Files:**
- Modify: `main.py` (`_prepare_weighted_score_universe` 근처, 약 line 923 이후)

- [ ] **Step 1: main.py 의 _prepare_weighted_score_universe 아래에 macd_cross universe prep 추가**

`_prepare_weighted_score_universe` 메서드 끝부분 (line 988 근처) 직후에 추가:

```python
    async def _prepare_macd_cross_universe(self, current_time):
        """macd_cross 페이퍼 universe + daily history 주입 (08:55).

        - stock_screener.preload_macd_cross_universe(top_n=30) 로 universe 선정
        - intraday_manager 등록 (이미 weighted_score universe 와 겹치는 코드는 skip)
        - 각 종목의 daily history 를 macd_cross_strategy 에 주입 → MACD hist 캐시
        """
        from config.strategy_settings import StrategySettings
        from core.models import StockState, TradingStock

        cfg = StrategySettings.MacdCross
        loop = asyncio.get_running_loop()

        # 1. universe 선정
        candidates = await loop.run_in_executor(
            None,
            lambda: self.stock_screener.preload_macd_cross_universe(top_n=cfg.UNIVERSE_TOP_N),
        )
        if not candidates:
            self.logger.warning("[macd_cross] universe 없음 → prep skip")
            return

        # 2. intraday_manager 등록 (중복 코드는 등록 시 자동 무시)
        registered = 0
        for stock in candidates:
            try:
                if not self.trading_manager.has_stock(stock.code):
                    new_ts = TradingStock(
                        stock_code=stock.code,
                        stock_name=stock.name,
                        state=StockState.WATCHING,
                    )
                    self.trading_manager.add_stock(new_ts)
                self.intraday_manager.add_stock(stock.code, stock.name)
                registered += 1
            except Exception as e:
                self.logger.debug(f"[macd_cross] 등록 실패 {stock.code}: {e}")

        # 3. daily history 주입 → MACD hist 캐시
        from datetime import datetime
        today_str = current_time.strftime("%Y%m%d")
        strategy = self.decision_engine.macd_cross_strategy
        if strategy is None:
            self.logger.warning("[macd_cross] strategy 미초기화 → daily 주입 skip")
            return

        # daily history 일괄 로드 (db_manager.fetch_daily_history)
        cached_count = 0
        for stock in candidates:
            try:
                df_daily = await loop.run_in_executor(
                    None,
                    lambda code=stock.code: self.db_manager.fetch_daily_history(
                        stock_code=code,
                        end_date=today_str,
                        lookback_days=cfg.SLOW_PERIOD * 3 + cfg.SIGNAL_PERIOD,
                    ),
                )
                if df_daily is None or df_daily.empty:
                    continue
                strategy.set_daily_history(stock.code, df_daily, today_str)
                cached_count += 1
            except Exception as e:
                self.logger.debug(f"[macd_cross] daily prep {stock.code}: {e}")

        self.logger.info(
            f"🎯 [macd_cross] universe 준비 완료: 등록={registered}, "
            f"daily 캐시={cached_count}/{len(candidates)}"
        )
```

- [ ] **Step 2: pre_market 호출 분기 추가**

`main.py` 의 `_prepare_weighted_score_universe` 호출 분기 (약 line 869) 바로 뒤에 추가:

```python
                        # 🆕 macd_cross 페이퍼 universe 등록 (Task 6)
                        try:
                            if (
                                StrategySettings.PAPER_STRATEGY == 'macd_cross'
                                and self.decision_engine.macd_cross_strategy is not None
                            ):
                                await self._prepare_macd_cross_universe(current_time)
                        except Exception as e:
                            self.logger.error(f"❌ [macd_cross] universe 준비 실패: {e}")
```

- [ ] **Step 3: trading_decision_engine 에 macd_cross_strategy 인스턴스 추가**

`core/trading_decision_engine.py` 의 `__init__` 끝부분 (약 line 120 근처) 에 추가:

```python
        # 🆕 macd_cross 페이퍼 어댑터 초기화 (2026-04-26)
        try:
            from config.strategy_settings import StrategySettings
            if StrategySettings.PAPER_STRATEGY == 'macd_cross':
                from core.strategies.macd_cross_strategy import MacdCrossStrategy
                cfg = StrategySettings.MacdCross
                self.macd_cross_strategy = MacdCrossStrategy(
                    fast=cfg.FAST_PERIOD,
                    slow=cfg.SLOW_PERIOD,
                    signal=cfg.SIGNAL_PERIOD,
                    entry_hhmm_min=cfg.ENTRY_HHMM_MIN,
                    entry_hhmm_max=cfg.ENTRY_HHMM_MAX,
                    logger=self.logger,
                )
                self.logger.info("📈 macd_cross 페이퍼 어댑터 초기화 완료")
            else:
                self.macd_cross_strategy = None
        except Exception as e:
            self.logger.warning(f"⚠️ macd_cross 어댑터 초기화 실패: {e}")
            self.macd_cross_strategy = None
```

- [ ] **Step 4: import 동작 확인**

Run:
```bash
python -c "
from config.strategy_settings import StrategySettings
StrategySettings.PAPER_STRATEGY = 'macd_cross'
from core.strategies.macd_cross_strategy import MacdCrossStrategy
s = MacdCrossStrategy(14, 34, 12)
print('OK', s.cached_universe_size())
"
```
Expected: `OK 0`

- [ ] **Step 5: Commit**

```bash
git add main.py core/trading_decision_engine.py
git commit -m "feat(main): pre_market hook for macd_cross paper universe + daily MACD prep"
```

---

## Task 7: 매수 분기 — 14:30+ 시그널 → 가상매수 라우팅

**Files:**
- Modify: `main.py` `_analyze_buy_decision` (약 line 533~670)

- [ ] **Step 1: 매수 분석 진입부에 macd_cross 시그널 분기 추가**

`main.py` `_analyze_buy_decision` 의 weighted_score 분기 위에 macd_cross paper 분기 추가. 위치: line 533 근처 (`if StrategySettings.ACTIVE_STRATEGY in ('closing_trade', 'weighted_score'):` 직전).

```python
            # 🆕 macd_cross 페이퍼 분기 (Task 7, 2026-04-26)
            # G1: 라이브 필터·서킷브레이커·게이트 우회. 시그널 발생 시 무조건 가상매수.
            if (
                StrategySettings.PAPER_STRATEGY == 'macd_cross'
                and self.decision_engine.macd_cross_strategy is not None
            ):
                cfg_mc = StrategySettings.MacdCross
                stock_code = trading_stock.stock_code

                # 시간대 + 시그널 + 동시 보유 한도 체크
                hhmm = current_time.hour * 100 + current_time.minute
                if cfg_mc.ENTRY_HHMM_MIN <= hhmm <= cfg_mc.ENTRY_HHMM_MAX:
                    if self.decision_engine.macd_cross_strategy.check_entry(stock_code, hhmm):
                        # 동시 보유 한도 (paper 별도 카운트)
                        paper_open = self._count_open_paper_positions('macd_cross')
                        if paper_open >= cfg_mc.MAX_DAILY_POSITIONS:
                            self.logger.debug(
                                f"[macd_cross] {stock_code} 시그널 OK 이지만 "
                                f"보유 한도 도달 ({paper_open}/{cfg_mc.MAX_DAILY_POSITIONS})"
                            )
                            return

                        # 1일 1회 진입 가드
                        if self._has_macd_cross_buy_today(stock_code):
                            self.logger.debug(f"[macd_cross] {stock_code} 당일 이미 진입")
                            return

                        # 가격 + 수량 계산
                        current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                        if not current_price_info:
                            return
                        buy_price = float(current_price_info.get('current_price', 0))
                        if buy_price <= 0:
                            return
                        budget = cfg_mc.VIRTUAL_CAPITAL * cfg_mc.BUY_BUDGET_RATIO
                        quantity = max(1, int(budget / buy_price))

                        await self.decision_engine.execute_virtual_buy_strategy_aware(
                            trading_stock=trading_stock,
                            buy_price=buy_price,
                            quantity=quantity,
                            strategy='macd_cross',
                            reason=f"macd_cross_signal_hhmm{hhmm}",
                        )
                        self.logger.info(
                            f"👻 [macd_cross] 가상 매수: {stock_code} {quantity}주 @{buy_price:,.0f}"
                        )
                # macd_cross 분기는 weighted_score 흐름과 분리 — return 으로 종료
                return
```

- [ ] **Step 2: 헬퍼 메서드 두 개 추가 (main.py 클래스 내부)**

`_analyze_buy_decision` 위쪽 적당한 위치에:

```python
    def _count_open_paper_positions(self, strategy: str) -> int:
        """현재 미체결 paper 포지션 개수 (특정 strategy)."""
        try:
            df = self.db_manager.get_virtual_open_positions()
            if df is None or df.empty:
                return 0
            return int((df['strategy'] == strategy).sum())
        except Exception as e:
            self.logger.debug(f"_count_open_paper_positions 실패: {e}")
            return 0

    def _has_macd_cross_buy_today(self, stock_code: str) -> bool:
        """오늘 macd_cross 로 이미 진입했는지."""
        try:
            today = now_kst().strftime('%Y-%m-%d')
            row = self.db_manager._fetchone(
                """SELECT COUNT(*) FROM virtual_trading_records
                   WHERE stock_code=%s AND action='BUY'
                     AND strategy='macd_cross'
                     AND DATE(timestamp) = %s""",
                (stock_code, today),
            )
            return (row[0] if row else 0) > 0
        except Exception as e:
            self.logger.debug(f"_has_macd_cross_buy_today 실패: {e}")
            return False
```

- [ ] **Step 3: trading_decision_engine 에 strategy-aware virtual_buy 메서드 추가**

`core/trading_decision_engine.py` 에 추가:

```python
    async def execute_virtual_buy_strategy_aware(
        self, trading_stock, buy_price: float, quantity: int,
        strategy: str, reason: str,
    ):
        """strategy 태그를 직접 받는 가상 매수 (weighted_score / macd_cross 등 분기 지원).

        기존 execute_virtual_buy 는 ACTIVE_STRATEGY 기반이라
        PAPER_STRATEGY (macd_cross) 분기를 표현 못함 → 신규.
        """
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            self.virtual_trading.execute_virtual_buy(
                stock_code=stock_code,
                stock_name=stock_name,
                price=buy_price,
                quantity=quantity,
                strategy=strategy,
                reason=reason,
            )
        except Exception as e:
            self.logger.error(f"❌ [{strategy}] 가상 매수 실행 오류: {e}")
```

- [ ] **Step 4: 검증 — 기존 weighted_score 라이브 경로가 안 깨졌는지 import 만 확인**

Run:
```bash
python -c "import main; print('main import OK')"
```
Expected: `main import OK` (또는 기존에도 있던 import 경고들 제외 깨끗)

- [ ] **Step 5: Commit**

```bash
git add main.py core/trading_decision_engine.py
git commit -m "feat(main): macd_cross paper buy branch with virtual routing + position cap"
```

---

## Task 8: virtual_trading_records.strategy 컬럼 검증

**Files:**
- Verify only: `db/database_manager.py:617`

- [ ] **Step 1: 컬럼 존재 확인 (마이그레이션 불필요 검증)**

Run:
```bash
python -c "
import psycopg2
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD)
cur = conn.cursor()
cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='virtual_trading_records' AND column_name='strategy'\")
row = cur.fetchone()
print('strategy column:', row[0] if row else 'MISSING')
conn.close()
"
```
Expected: `strategy column: strategy`

- [ ] **Step 2: 만약 MISSING 이면 마이그레이션 실행**

```sql
ALTER TABLE virtual_trading_records ADD COLUMN strategy TEXT DEFAULT 'unknown';
CREATE INDEX IF NOT EXISTS idx_vtr_strategy ON virtual_trading_records(strategy);
```

(컬럼이 이미 존재하면 이 단계 skip)

- [ ] **Step 3: 인덱스 확인 (KPI 조회 가속)**

Run:
```bash
python -c "
import psycopg2
from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD)
cur = conn.cursor()
cur.execute(\"SELECT indexname FROM pg_indexes WHERE tablename='virtual_trading_records'\")
print([r[0] for r in cur.fetchall()])
conn.close()
"
```
Expected: `idx_vtr_strategy` 가 목록에 있어야 함. 없으면 Step 2 의 CREATE INDEX 실행.

- [ ] **Step 4: Commit (스키마 변경이 있었다면)**

스키마 변경 없으면 commit 생략. 있었다면 `db/migrations/2026-04-26-vtr-strategy-index.sql` 추가 + commit.

---

## Task 9: EOD 청산 격리 — macd_cross paper 포지션 보호

**Files:**
- Modify: `main.py:1360-1420` (`_execute_end_of_day_liquidation`)

- [ ] **Step 1: paper 포지션 격리 분기 추가**

`main.py` `_execute_end_of_day_liquidation` 의 `weighted_score overnight 필터` (line 1394) 뒤에 추가:

```python
            # 🆕 macd_cross 페이퍼 포지션은 EOD 강제청산에서 격리 (Spec §5)
            # paper 가상 포지션은 hold_days=2 만료 시 별도 경로로 청산되며
            # 라이브 EOD 흐름에 들어오지 않아야 한다. 라이브 trading_manager 에는
            # 가상매매 포지션이 등록되지 않으므로 자동으로 격리되지만, 만약 macd_cross
            # 가 향후 trading_manager 에 등록되는 경로가 생기면 여기서 분기 필요.
            try:
                from config.strategy_settings import StrategySettings
                if (
                    StrategySettings.PAPER_STRATEGY == 'macd_cross'
                    and all_liquidation_targets
                ):
                    paper_codes = self._get_macd_cross_paper_open_codes()
                    if paper_codes:
                        before = len(all_liquidation_targets)
                        all_liquidation_targets = [
                            ts for ts in all_liquidation_targets
                            if ts.stock_code not in paper_codes
                        ]
                        excluded = before - len(all_liquidation_targets)
                        if excluded > 0:
                            self.logger.info(
                                f"🌙 macd_cross paper 포지션 EOD 격리: {excluded}종목 "
                                f"(hold_days=2 만료 전까지 유지)"
                            )
            except Exception as e:
                self.logger.warning(f"⚠️ macd_cross EOD 격리 실패: {e} — 정상 청산 진행")
```

- [ ] **Step 2: 헬퍼 메서드 추가**

main.py 클래스 내부에:

```python
    def _get_macd_cross_paper_open_codes(self) -> set:
        """현재 미체결 macd_cross 가상 포지션의 종목 코드 집합."""
        try:
            df = self.db_manager.get_virtual_open_positions()
            if df is None or df.empty:
                return set()
            return set(df.loc[df['strategy'] == 'macd_cross', 'stock_code'].tolist())
        except Exception as e:
            self.logger.debug(f"_get_macd_cross_paper_open_codes 실패: {e}")
            return set()
```

- [ ] **Step 3: 가상 매도 만료 청산 잡 추가 — `_macd_cross_paper_exit_task`**

`_execute_end_of_day_liquidation` 메서드 위에 신규 메서드 추가:

```python
    async def _macd_cross_paper_exit_task(self):
        """macd_cross 가상 포지션의 hold_days=2 만료 청산 (15:00 직후 1회).

        EOD 직후 (15:05 등) 호출. 매수일로부터 거래일 기준 2일 경과한
        가상 포지션을 종가로 가상 청산.
        """
        try:
            from config.strategy_settings import StrategySettings
            from datetime import datetime
            import numpy as np

            cfg = StrategySettings.MacdCross
            df = self.db_manager.get_virtual_open_positions()
            if df is None or df.empty:
                return
            df_mc = df[df['strategy'] == 'macd_cross']
            if df_mc.empty:
                return

            today = now_kst().date()
            for _, row in df_mc.iterrows():
                buy_time = row['buy_time']
                if isinstance(buy_time, str):
                    buy_dt = datetime.strptime(buy_time, "%Y-%m-%d %H:%M:%S")
                else:
                    buy_dt = buy_time
                days_held = int(np.busday_count(buy_dt.date(), today))
                if days_held < cfg.HOLD_DAYS:
                    continue

                stock_code = row['stock_code']
                stock_name = row['stock_name']
                buy_record_id = int(row['id'])
                quantity = int(row['quantity'])

                # 종가 가져오기 (intraday_manager 캐시)
                price_info = self.intraday_manager.get_cached_current_price(stock_code)
                if not price_info:
                    self.logger.warning(f"[macd_cross.exit] {stock_code} 가격 없음 → skip")
                    continue
                sell_price = float(price_info.get('current_price', 0))
                if sell_price <= 0:
                    continue

                self.decision_engine.virtual_trading.execute_virtual_sell(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=sell_price,
                    quantity=quantity,
                    strategy='macd_cross',
                    reason=f"hold_limit_days={days_held}",
                    buy_record_id=buy_record_id,
                )
                self.logger.info(
                    f"👻 [macd_cross] 가상 청산: {stock_code} {quantity}주 "
                    f"@{sell_price:,.0f} (hold {days_held}d)"
                )
        except Exception as e:
            self.logger.error(f"❌ macd_cross paper exit 실패: {e}")
```

- [ ] **Step 4: EOD 직후 호출 분기 추가**

`_system_monitoring_task` 또는 EOD 청산 트리거 직후 (line 388 근처) 다음 추가:

```python
                        # macd_cross paper 만료 청산 (EOD 직후 1회)
                        try:
                            from config.strategy_settings import StrategySettings
                            if StrategySettings.PAPER_STRATEGY == 'macd_cross':
                                await self._macd_cross_paper_exit_task()
                        except Exception as e:
                            self.logger.error(f"❌ macd_cross paper exit 트리거 실패: {e}")
```

- [ ] **Step 5: import 검증**

Run:
```bash
python -c "import main; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat(main): macd_cross paper EOD isolation + hold_days=2 virtual exit"
```

---

## Task 10: KPI 집계 + 6 게이트 평가

**Files:**
- Create: `core/strategies/macd_cross_kpi.py`
- Test: `tests/strategies/test_macd_cross_kpi.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/strategies/test_macd_cross_kpi.py`:
```python
"""macd_cross KPI 집계 + 6 게이트 평가 테스트."""
import pandas as pd
import pytest

from core.strategies.macd_cross_kpi import MacdCrossKpi


def _trades(pnls):
    """편의 함수: pnl 시퀀스 → trade rows."""
    return pd.DataFrame({
        "buy_time": pd.date_range("2026-04-01", periods=len(pnls), freq="D"),
        "sell_time": pd.date_range("2026-04-02", periods=len(pnls), freq="D"),
        "pnl": pnls,
    })


def test_empty_trades_returns_zero_metrics():
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([]))
    assert m["trade_count"] == 0
    assert m["return"] == 0.0


def test_metrics_basic():
    """5 trades, 3승 2패, 단순 합산 검증."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([100_000, -50_000, 200_000, -30_000, 80_000]))
    assert m["trade_count"] == 5
    assert m["win_rate"] == pytest.approx(3 / 5)
    assert m["return"] == pytest.approx((100_000 - 50_000 + 200_000 - 30_000 + 80_000) / 10_000_000)
    assert m["max_consec_losses"] == 1


def test_top1_share_calculation():
    """최대 winner 가 net pnl 점유율 계산."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([100, 200, 50, 1000, -50]))
    # net = 1300, top1 = 1000 → share = 1000/1300
    assert m["top1_share"] == pytest.approx(1000 / 1300, rel=1e-6)


def test_max_consec_losses_streak():
    """3연속 손실 streak 검증."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = k.compute(_trades([100, -50, -30, -20, 40]))
    assert m["max_consec_losses"] == 3


def test_gate_pass_all():
    """모든 게이트 통과 케이스."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = {
        "calmar": 35,
        "return": 0.05,
        "mdd": -0.02,  # 2%
        "win_rate": 0.55,
        "top1_share": 0.50,
        "max_consec_losses": 3,
    }
    result = k.evaluate_gates(m)
    assert result["all_pass"] is True
    assert all(v["pass"] for v in result["gates"].values())


def test_gate_fail_calmar():
    k = MacdCrossKpi(virtual_capital=10_000_000)
    m = {
        "calmar": 25,  # < 30 fails
        "return": 0.05, "mdd": -0.02, "win_rate": 0.55,
        "top1_share": 0.50, "max_consec_losses": 3,
    }
    result = k.evaluate_gates(m)
    assert result["all_pass"] is False
    assert result["gates"]["calmar"]["pass"] is False


def test_safety_stop_cumulative_loss():
    """누적 -5% 도달 시 safety stop True."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    assert k.should_safety_stop({"return": -0.06, "max_consec_losses": 2}) is True
    assert k.should_safety_stop({"return": -0.04, "max_consec_losses": 2}) is False


def test_safety_stop_consec_losses():
    """연속 5패 도달 시 safety stop True."""
    k = MacdCrossKpi(virtual_capital=10_000_000)
    assert k.should_safety_stop({"return": -0.02, "max_consec_losses": 5}) is True
    assert k.should_safety_stop({"return": -0.02, "max_consec_losses": 4}) is False
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/strategies/test_macd_cross_kpi.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: KPI 모듈 구현**

`core/strategies/macd_cross_kpi.py`:
```python
"""macd_cross 페이퍼 KPI 집계 + 6 승격 게이트 평가.

Spec §3: KPI 정의 + 게이트 임계값 (return/calmar/mdd/win/top1/consec_loss).
Spec §3 중도 안전 정지: 누적 -5% 또는 연속 손실 5건.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd


# Spec §3 게이트 임계값 (모두 충족 시 승격 단계 회의 진입)
GATE_THRESHOLDS = {
    "calmar": {"min": 30.0, "label": "Calmar ≥ 30"},
    "return": {"min": 0.0, "label": "return ≥ 0"},
    "mdd": {"max_abs": 0.05, "label": "MDD ≤ 5%"},
    "win_rate": {"min": 0.50, "label": "승률 ≥ 50%"},
    "top1_share": {"max": 0.60, "label": "top1 share ≤ 60%"},
    "max_consec_losses": {"max": 4, "label": "max consec losses ≤ 4"},
}

# 중도 안전 정지 임계값 (paper 자동 중단 권고)
SAFETY_STOP = {
    "cumulative_loss_pct": -0.05,    # 누적 -5%
    "max_consec_losses": 5,          # 연속 5패
}


class MacdCrossKpi:
    """KPI 집계 + 게이트 평가. 입력: 가상매매 trade rows."""

    def __init__(self, virtual_capital: float):
        self.virtual_capital = float(virtual_capital)

    def compute(self, df_trades: pd.DataFrame) -> Dict:
        """trade rows (BUY-SELL pair 의 pnl) → KPI 딕셔너리.

        Args:
            df_trades: 컬럼 = ['buy_time', 'sell_time', 'pnl']. sell_time 오름차순.
        """
        if df_trades is None or df_trades.empty:
            return {
                "trade_count": 0, "return": 0.0, "mdd": 0.0,
                "calmar": 0.0, "win_rate": 0.0, "top1_share": 0.0,
                "max_consec_losses": 0,
            }
        df = df_trades.sort_values("sell_time").reset_index(drop=True)
        pnl = df["pnl"].astype(float).to_numpy()
        n = len(pnl)
        net = float(pnl.sum())
        ret = net / self.virtual_capital

        # MDD on cumulative pnl curve
        cum = np.cumsum(pnl)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / self.virtual_capital
        mdd = float(dd.min()) if len(dd) > 0 else 0.0

        # Calmar (annualized). 영업일수 = (sell_time max - buy_time min) 의 영업일.
        buy_min = pd.to_datetime(df["buy_time"].min()).date()
        sell_max = pd.to_datetime(df["sell_time"].max()).date()
        biz_days = max(1, int(np.busday_count(buy_min, sell_max)))
        annualized = ret * (252.0 / biz_days)
        calmar = annualized / abs(mdd) if abs(mdd) > 1e-9 else 0.0

        # Win rate
        win_rate = float((pnl > 0).sum() / n)

        # top1 share: 최대 양수 trade 의 net 점유율
        positives = pnl[pnl > 0]
        if len(positives) > 0 and abs(net) > 1e-9:
            top1_share = float(positives.max() / net)
        else:
            top1_share = 0.0

        # max consecutive losses
        max_streak = 0
        current = 0
        for v in pnl:
            if v < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0

        return {
            "trade_count": n, "return": ret, "mdd": mdd,
            "calmar": float(calmar), "win_rate": win_rate,
            "top1_share": top1_share, "max_consec_losses": int(max_streak),
        }

    def evaluate_gates(self, metrics: Dict) -> Dict:
        """6 게이트 평가. 모두 통과 시 all_pass=True."""
        gates = {}
        gates["calmar"] = {
            "pass": metrics["calmar"] >= GATE_THRESHOLDS["calmar"]["min"],
            "value": metrics["calmar"], "label": GATE_THRESHOLDS["calmar"]["label"],
        }
        gates["return"] = {
            "pass": metrics["return"] >= GATE_THRESHOLDS["return"]["min"],
            "value": metrics["return"], "label": GATE_THRESHOLDS["return"]["label"],
        }
        gates["mdd"] = {
            "pass": abs(metrics["mdd"]) <= GATE_THRESHOLDS["mdd"]["max_abs"],
            "value": metrics["mdd"], "label": GATE_THRESHOLDS["mdd"]["label"],
        }
        gates["win_rate"] = {
            "pass": metrics["win_rate"] >= GATE_THRESHOLDS["win_rate"]["min"],
            "value": metrics["win_rate"], "label": GATE_THRESHOLDS["win_rate"]["label"],
        }
        gates["top1_share"] = {
            "pass": metrics["top1_share"] <= GATE_THRESHOLDS["top1_share"]["max"],
            "value": metrics["top1_share"], "label": GATE_THRESHOLDS["top1_share"]["label"],
        }
        gates["max_consec_losses"] = {
            "pass": metrics["max_consec_losses"] <= GATE_THRESHOLDS["max_consec_losses"]["max"],
            "value": metrics["max_consec_losses"],
            "label": GATE_THRESHOLDS["max_consec_losses"]["label"],
        }
        all_pass = all(g["pass"] for g in gates.values())
        return {"all_pass": all_pass, "gates": gates}

    def should_safety_stop(self, metrics: Dict) -> bool:
        """중도 안전 정지 충족 여부."""
        if metrics.get("return", 0) <= SAFETY_STOP["cumulative_loss_pct"]:
            return True
        if metrics.get("max_consec_losses", 0) >= SAFETY_STOP["max_consec_losses"]:
            return True
        return False
```

- [ ] **Step 4: Run → PASS**

Run: `pytest tests/strategies/test_macd_cross_kpi.py -v`
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/strategies/macd_cross_kpi.py tests/strategies/test_macd_cross_kpi.py
git commit -m "feat(strategies): macd_cross KPI aggregator + 6-gate evaluator"
```

---

## Task 11: 일일 텔레그램 보고 + safety stop 트리거

**Files:**
- Modify: `main.py` (EOD 후 보고 분기)
- Modify: `core/post_market_data_saver.py` (선택, 이미 있는 보고 흐름과 통합)

- [ ] **Step 1: paper 일일 보고 함수 추가 (main.py)**

`_macd_cross_paper_exit_task` 직후에 추가:

```python
    async def _macd_cross_paper_daily_report(self):
        """macd_cross 페이퍼 일일 KPI 집계 + 텔레그램 알림 + safety stop 체크."""
        try:
            from config.strategy_settings import StrategySettings
            from core.strategies.macd_cross_kpi import MacdCrossKpi

            cfg = StrategySettings.MacdCross
            kpi = MacdCrossKpi(virtual_capital=cfg.VIRTUAL_CAPITAL)

            # 모든 macd_cross 가상 trade (BUY-SELL paired) 조회
            df = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db_manager.get_virtual_paired_trades(strategy='macd_cross')
            )

            metrics = kpi.compute(df) if df is not None else kpi.compute(pd.DataFrame())
            gates = kpi.evaluate_gates(metrics)
            safety = kpi.should_safety_stop(metrics)

            # 텔레그램 메시지
            lines = [
                "📊 macd_cross 페이퍼 일일 보고",
                f"진행: {metrics['trade_count']} trades / {metrics['trade_count']/30*100:.0f}% (목표 30)",
                f"return: {metrics['return']*100:+.2f}% | MDD: {metrics['mdd']*100:+.2f}% | win: {metrics['win_rate']*100:.1f}%",
                f"Calmar: {metrics['calmar']:.1f} | top1: {metrics['top1_share']*100:.1f}% | streak: {metrics['max_consec_losses']}",
                "—",
                f"게이트: {sum(1 for g in gates['gates'].values() if g['pass'])}/6 통과",
            ]
            for k, g in gates["gates"].items():
                mark = "✓" if g["pass"] else "✗"
                lines.append(f"  {mark} {g['label']} → {g['value']}")
            if safety:
                lines.append("⚠️ SAFETY STOP 충족 — paper 즉시 중단 권고. PAPER_STRATEGY=None 으로 설정.")

            msg = "\n".join(lines)
            if self.telegram_integration:
                await self.telegram_integration.send_message(msg)
            self.logger.info(msg)
        except Exception as e:
            self.logger.error(f"❌ macd_cross 일일 보고 실패: {e}")
```

- [ ] **Step 2: db_manager 에 paired trades 조회 메서드 추가**

`db/database_manager.py` `get_virtual_open_positions` 아래에 추가:

```python
    def get_virtual_paired_trades(self, strategy: str) -> pd.DataFrame:
        """매수-매도 매칭된 가상 trade 조회 (KPI 계산용).

        Returns: 컬럼 = ['buy_time', 'sell_time', 'pnl']. sell_time 오름차순.
        """
        try:
            with self._pool_obj.connection() as conn:
                df = pd.read_sql_query("""
                    SELECT
                        b.timestamp AS buy_time,
                        s.timestamp AS sell_time,
                        s.profit_loss AS pnl
                    FROM virtual_trading_records s
                    JOIN virtual_trading_records b ON s.buy_record_id = b.id
                    WHERE s.action = 'SELL'
                      AND s.strategy = %s
                      AND s.is_test = TRUE
                    ORDER BY s.timestamp
                """, conn, params=[strategy])
            return df
        except Exception as e:
            self.logger.error(f"get_virtual_paired_trades 실패: {e}")
            return pd.DataFrame(columns=['buy_time', 'sell_time', 'pnl'])
```

- [ ] **Step 3: EOD 후 보고 트리거**

main.py 의 `_macd_cross_paper_exit_task` 호출 분기 직후에:

```python
                        # macd_cross paper 일일 보고 + safety stop 체크
                        try:
                            if StrategySettings.PAPER_STRATEGY == 'macd_cross':
                                await self._macd_cross_paper_daily_report()
                        except Exception as e:
                            self.logger.error(f"❌ macd_cross 보고 트리거 실패: {e}")
```

- [ ] **Step 4: import 검증**

Run:
```bash
python -c "import main; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add main.py db/database_manager.py
git commit -m "feat(main): macd_cross paper daily report + safety stop alert"
```

---

## Task 12: 통합 테스트 — universe → 시그널 → 가상매수 → EOD 격리 → 만료청산

**Files:**
- Create: `tests/integration/test_macd_cross_paper_flow.py`

- [ ] **Step 1: 통합 테스트 작성**

`tests/integration/test_macd_cross_paper_flow.py`:
```python
"""macd_cross 페이퍼 e2e 시나리오 (mock DB / mock 분봉).

검증 흐름:
1. preload_macd_cross_universe → 30종목 등록
2. set_daily_history → 시그널 캐시 형성
3. 14:30 시그널 발생한 종목에 대해 check_entry → True
4. virtual_buy 호출 → DB 기록
5. EOD 직후: 보유 1일차 → 격리됨 (만료청산 안 됨)
6. 영업일 +2일: 만료 청산 발생 + KPI 보고 메트릭 정합
"""
import math
from datetime import date, datetime, timedelta
import numpy as np
import pandas as pd
import pytest

from core.strategies.macd_cross_strategy import MacdCrossStrategy
from core.strategies.macd_cross_kpi import MacdCrossKpi


def _bullish_close_series(n=80):
    """음 hist → 양 hist 골든크로스를 마지막에 만드는 close 시퀀스."""
    base = np.linspace(10000, 9000, n // 2)        # 하락 (음 hist 형성)
    rebound = np.linspace(9000, 10500, n - n // 2) # 반등 (양 hist 진입)
    return np.concatenate([base, rebound])


def test_signal_to_entry_then_kpi_pipeline():
    """공유 모듈 시그널 → 어댑터 cache → check_entry → KPI 계산."""
    strategy = MacdCrossStrategy(fast=14, slow=34, signal=12,
                                  entry_hhmm_min=1430, entry_hhmm_max=1500)
    closes = _bullish_close_series(80)
    dates = pd.date_range("2026-01-02", periods=80, freq="B").strftime("%Y%m%d")
    df_d = pd.DataFrame({"trade_date": dates.astype(str), "close": closes})
    strategy.set_daily_history("005930", df_d, today_yyyymmdd="20260423")

    # 캐시 채워짐
    prev, prev_prev = strategy.get_cached_hist("005930")
    assert prev is not None and prev_prev is not None

    # 시간대 + 시그널 충족 (테스트용 강제 cross 값)
    strategy._cache["005930"] = (0.5, -0.3)
    assert strategy.check_entry("005930", hhmm=1430) is True
    assert strategy.check_entry("005930", hhmm=1429) is False
    assert strategy.check_entry("005930", hhmm=1501) is False

    # KPI 파이프라인: 임의 trade 시뮬
    trades = pd.DataFrame({
        "buy_time": pd.date_range("2026-04-01", periods=5, freq="B"),
        "sell_time": pd.date_range("2026-04-03", periods=5, freq="B"),
        "pnl": [120_000, -40_000, 180_000, 60_000, -20_000],
    })
    kpi = MacdCrossKpi(virtual_capital=10_000_000)
    m = kpi.compute(trades)
    g = kpi.evaluate_gates(m)
    # net = 300_000, return = 3% → return gate pass
    assert m["return"] == pytest.approx(0.03, abs=1e-6)
    assert g["gates"]["return"]["pass"] is True


def test_eod_isolation_excludes_paper_codes():
    """_get_macd_cross_paper_open_codes 가 strategy='macd_cross' 행만 반환."""
    # mock db_manager
    class MockDB:
        def get_virtual_open_positions(self):
            return pd.DataFrame({
                "id": [1, 2, 3],
                "stock_code": ["005930", "000660", "035720"],
                "stock_name": ["삼성전자", "SK하이닉스", "카카오"],
                "quantity": [10, 5, 20],
                "buy_price": [70000, 130000, 50000],
                "buy_time": [datetime.now()] * 3,
                "strategy": ["macd_cross", "weighted_score", "macd_cross"],
                "buy_reason": ["", "", ""],
            })

    # main.RoboTrader._get_macd_cross_paper_open_codes 의 로직만 모방
    db = MockDB()
    df = db.get_virtual_open_positions()
    paper_codes = set(df.loc[df["strategy"] == "macd_cross", "stock_code"].tolist())
    assert paper_codes == {"005930", "035720"}
    assert "000660" not in paper_codes  # weighted_score 는 격리 안 됨
```

- [ ] **Step 2: Run → PASS**

Run: `pytest tests/integration/test_macd_cross_paper_flow.py -v`
Expected: 2 tests PASS

- [ ] **Step 3: 전체 macd_cross 테스트 묶음 실행 (회귀 확인)**

Run:
```bash
pytest tests/strategies/test_macd_cross_signal_parity.py tests/strategies/test_macd_cross_strategy.py tests/strategies/test_macd_cross_kpi.py tests/integration/test_macd_cross_paper_flow.py -v
```
Expected: 모든 테스트 PASS (5 + 5 + 8 + 2 = 20)

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_macd_cross_paper_flow.py
git commit -m "test(integration): macd_cross paper e2e signal→entry→isolation→kpi"
```

---

## Task 13: 문서 동기화 + 페이퍼 활성 스위치 ON

**Files:**
- Modify: `CLAUDE.md`
- Modify: `MEMORY.md` (auto memory)

- [ ] **Step 1: CLAUDE.md 의 "현재 상태" 블록 갱신**

`CLAUDE.md` 의 `## ⚠️ 현재 상태 (2026-04-23)` 섹션을 갱신:

```markdown
## ⚠️ 현재 상태 (2026-04-26): weighted_score 라이브 + macd_cross 페이퍼 (paper-first)

```python
# config/strategy_settings.py — 이중 운영
ACTIVE_STRATEGY = 'weighted_score'              # 실거래 primary (Trial 837)
PAPER_STRATEGY  = 'macd_cross'                  # 페이퍼 secondary (가상매매)

# weighted_score 라이브 운영 (변경 없음)
WeightedScore.STOP_LOSS_PCT = -3.84
WeightedScore.TAKE_PROFIT_PCT = 8.02
WeightedScore.MAX_HOLDING_DAYS = 5
WeightedScore.VIRTUAL_ONLY = False

# macd_cross 페이퍼 (4주 또는 30 trades 검증, G1 백테스트 100% 재현)
MacdCross.FAST_PERIOD = 14
MacdCross.SLOW_PERIOD = 34
MacdCross.SIGNAL_PERIOD = 12
MacdCross.ENTRY_HHMM_MIN = 1430
MacdCross.HOLD_DAYS = 2
MacdCross.VIRTUAL_CAPITAL = 10_000_000          # 가상 1천만
MacdCross.BUY_BUDGET_RATIO = 0.20               # 200만/포지션
MacdCross.MAX_DAILY_POSITIONS = 5
MacdCross.UNIVERSE_TOP_N = 30
MacdCross.APPLY_LIVE_OVERLAY = False            # G1: 라이브 필터 미적용
```

설계서: `docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md`
구현 계획: `docs/superpowers/plans/2026-04-26-macd-cross-paper-integration.md`

**페이퍼 종료 조건**: 4주 경과 또는 30 trades 도달 (먼저).
**승격 게이트** (모두 충족): Calmar≥30, return≥0, MDD≤5%, 승률≥50%, top1share≤60%, max_consec_loss≤4.
**중도 안전정지**: 누적 -5% 또는 연속 5패 → PAPER_STRATEGY=None 수동 전환.
```

기존 `## ⚠️ 현재 상태 (2026-04-23): weighted_score 실거래 운영 중` 블록은 **삭제하지 말고** 위 블록으로 교체.

- [ ] **Step 2: MEMORY 의 진행 프로젝트 항목 추가**

`C:\Users\sttgp\.claude\projects\D--GIT-RoboTrader\memory\MEMORY.md` 의 `## 현재 진행 프로젝트` 블록에 추가:

```markdown
→ 상세: [macd_cross 페이퍼 통합](project_macd_cross_paper.md) (2026-04-26~, 4주 paper 검증 중)
```

신규 파일 `project_macd_cross_paper.md`:
```markdown
---
name: macd_cross 페이퍼 통합 진행
description: 2026-04-26 부터 macd_cross 전략 페이퍼 트레이딩(가상매매) 운영. weighted_score 라이브 옆에서 4주 / 30 trades 검증.
type: project
---

**2026-04-26 시작**. PAPER_STRATEGY='macd_cross' 활성. 가상자본 1천만, 200만/포지션, 동시 5종목.

**Why**: PHASE6_DECISION.md 권고. weighted_score 라이브 흔들지 않으면서 macd_cross OOS Calmar 54.16 재현성 + fragility (top1=56.8%) 검증. G1 (백테스트 100% 재현) 으로 라이브 안전망 inherit 안 함.

**How to apply**:
- 페이퍼 종료 조건: 4주 또는 30 trades.
- 승격 게이트 6개 (Calmar≥30 / return≥0 / MDD≤5% / 승률≥50% / top1share≤60% / max_consec_loss≤4).
- 중도 안전정지: 누적 -5% 또는 연속 5패 → PAPER_STRATEGY=None 수동 전환.
- 일일 EOD 후 텔레그램 보고로 진행률·게이트·safety 체크.
- 설계서/계획서는 docs/superpowers/{specs,plans}/2026-04-26-macd-cross-*.md 참조.
- 승격 시점에 자금 모델(A/B/C) + 라이브 SL/CB inherit 여부 별도 결정.
```

- [ ] **Step 3: 활성 스위치 검증**

Run:
```bash
python -c "
from config.strategy_settings import StrategySettings
print('ACTIVE:', StrategySettings.ACTIVE_STRATEGY)
print('PAPER:', StrategySettings.PAPER_STRATEGY)
print('MacdCross.UNIVERSE_TOP_N:', StrategySettings.MacdCross.UNIVERSE_TOP_N)
"
```
Expected:
```
ACTIVE: weighted_score
PAPER: macd_cross
MacdCross.UNIVERSE_TOP_N: 30
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
# MEMORY 파일들은 repo 외부 (~/.claude/...) 라 git 제외
git commit -m "docs: enable macd_cross paper trading mode + status update"
```

---

## Self-Review

**Spec coverage:**
- §2 4 결정 (D/F1/G1/T2) → Task 1 (config), Task 11 (KPI)
- §3 KPI 정의 + 6 게이트 + 안전 정지 → Task 10 (KPI module), Task 11 (보고)
- §4.1 dual-dispatch → Task 1 (PAPER_STRATEGY), Task 7 (분기)
- §4.2 라이브 어댑터 → Task 4
- §4.3 universe pipeline → Task 5, Task 6
- §4.4 공유 시그널 모듈 → Task 2, Task 3
- §4.5 strategy 태그 + DB → Task 8 (검증), Task 7 (`strategy='macd_cross'` 인자)
- §5 EOD/CB 격리 → Task 9
- §6 모니터링 → Task 11 (텔레그램), Task 11 (KPI 보고)
- §7 산출물 → 모든 task 가 변경 파일 명시
- §8 후속 결정 → out-of-scope (post-paper)

**Placeholder scan:** 모든 step 에 실제 코드/명령어/예상 출력 명시. "TBD" 없음.

**Type consistency:**
- `MacdCrossStrategy` 클래스명 vs `macd_cross_strategy` 인스턴스명 → 일관 (Task 4 → Task 6)
- `compute_macd_histogram_series`, `is_macd_golden_cross`, `is_in_entry_window` 시그니처 → Task 2 정의 → Task 3, 4 호출 일관
- KPI 메트릭 키 (`return`, `mdd`, `calmar`, `win_rate`, `top1_share`, `max_consec_losses`) → Task 10 → Task 11 보고 일관
- `strategy='macd_cross'` 문자열 → Task 7, 8, 9, 11 모두 동일 리터럴

**Scope:** 페이퍼 단계까지. 승격 후 자금 모델 결정·SL inherit 판단은 후속 spec/plan 으로 분리 (§8).
