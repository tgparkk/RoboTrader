# macd_cross fold2 Regime Filter Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spec `docs/superpowers/specs/2026-05-09-macd-cross-fold2-regime-filter-design.md` Phase 1 — KOSPI MA20 regime filter wrapper + 멀티버스 4-fold 리플레이로 fold2 회피 효과 검증. 4-gate 통과 시 Phase 2 라이브 plan.

**Architecture:** `MACDCrossRegimeFilterStrategy` wrapper (exit_overlay 패턴 답습) + `Dataset.kospi_daily_df` 첨부 + MV-C runner (16 eval) + plotter heatmap + summary. 라이브 코드 (`core/`, `main.py`) 미수정.

**Tech Stack:** Python 3.9, pandas, numpy, matplotlib, psycopg2, pytest. PostgreSQL `daily_candles` (KS11) + `daily_prices` (universe). Windows PowerShell.

---

## 사전 정보 — 엔지니어가 알아야 할 컨벤션

### 기존 인프라 재사용
- **`backtests/common/data_loader.py:load_index_df(index_code, start, end)`** — `'KS11'` 호출 가능. 반환 DataFrame: `trade_date, open, high, low, close` (trade_date 는 YYYYMMDD 문자열, close 는 float).
- **`backtests/strategies/macd_cross.py:MACDCrossStrategy`** — 라이브 동등성 보호 위해 미수정. wrapper 가 상속.
- **`backtests/multiverse/macd_cross_mv_common.py`** — `Dataset` dataclass + `load_all_datasets()` + `evaluate_cell()` + `build_cell_kpis()` 가 이미 존재. `Dataset` 만 확장.
- **`backtests/multiverse/plot_macd_cross_mv.py`** — 기존 plotter (MV-A/B). 신규 RF section 추가.

### Engine fill 모델 (변경 없음)
`backtests/common/engine.py` 의 next-bar open + 슬리피지 모델 그대로. filter 는 `entry_signal` 단계에서 차단할 뿐 engine 수정 0.

### Lookahead 방지 (3대 원칙 ①)
신호 = `KOSPI close[D-1] < MA20[D-1]`. `prepare_features` 에서 `shift(1)` 명시 적용. unit test 로 강제.

### 테스트 디렉토리
- 신규: `tests/backtests/strategies/test_macd_cross_regime_filter.py`

---

## 파일 구조 (생성/수정)

```
backtests/
  strategies/
    macd_cross_regime_filter.py            [신규]  Task 1-4: MACDCrossRegimeFilterStrategy
  multiverse/
    macd_cross_mv_common.py                [수정]  Task 5: Dataset.kospi_daily_df 필드 + load_all_datasets KOSPI 추가
    macd_cross_regime_filter_mv.py         [신규]  Task 6: MV-C runner
    plot_macd_cross_mv.py                  [수정]  Task 7: plot_regime_filter + write_regime_filter_summary

tests/backtests/
  strategies/
    test_macd_cross_regime_filter.py       [신규]  Task 1-4

backtests/reports/macd_cross_mv/
  regime_filter/                           [신규 디렉토리, Task 8 채움]
    cells.csv
    heatmaps/calmar_summary.png
    summary.md
```

---

## Task 1: Strategy wrapper 골격 (filter OFF = base 동등)

**Files:**
- Create: `backtests/strategies/macd_cross_regime_filter.py`
- Test: `tests/backtests/strategies/test_macd_cross_regime_filter.py`

목적: wrapper 클래스 골격 + `regime_filter_enabled=False` 일 때 base `MACDCrossStrategy` 와 동일 거동 검증.

- [ ] **Step 1.1: 실패 테스트 작성**

`tests/backtests/strategies/test_macd_cross_regime_filter.py`:
```python
"""MACDCrossRegimeFilterStrategy unit tests — KOSPI MA20 regime filter wrapper."""
import numpy as np
import pandas as pd
import pytest

from backtests.strategies.macd_cross_regime_filter import (
    MACDCrossRegimeFilterStrategy,
)


def _mock_minute_df():
    """5일치 분봉 mock — golden cross 환경 가정 (간단 fixture)."""
    rows = []
    for d in range(5):
        date = f"2025090{d+1}"
        for m in range(1430, 1432):  # 14:30 ~ 14:31 두 봉
            rows.append({
                "stock_code": "000001",
                "trade_date": date,
                "trade_time": f"{m // 100:02d}{m % 100:02d}00",
                "open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1005.0,
                "volume": 1000,
            })
    return pd.DataFrame(rows)


def _mock_daily_df():
    """5일치 daily mock — MACD hist 양수 (golden cross 사전조건)."""
    return pd.DataFrame({
        "trade_date": [f"2025090{d+1}" for d in range(5)],
        "close": [1000, 1005, 1010, 1015, 1020],  # 단조 증가 → MACD>0
    })


def test_filter_off_matches_base_no_kospi_needed():
    """regime_filter_enabled=False 면 kospi_daily_df 없이도 정상 — base 동등."""
    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=False,
        fast_period=14, slow_period=34, signal_period=12,
    )
    feat = strat.prepare_features(_mock_minute_df(), _mock_daily_df())
    # base 가 만든 컬럼만 존재해야 함
    assert "kospi_below_ma20" not in feat.columns
    assert "prev_hist" in feat.columns
```

- [ ] **Step 1.2: 실패 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py::test_filter_off_matches_base_no_kospi_needed -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'backtests.strategies.macd_cross_regime_filter'`.

- [ ] **Step 1.3: wrapper 클래스 골격 작성**

`backtests/strategies/macd_cross_regime_filter.py`:
```python
"""macd_cross 에 KOSPI MA20 regime filter 를 얹은 백테스트 wrapper.

본체 backtests/strategies/macd_cross.py 는 라이브 동등성 보호 위해 미수정.
filter 활성 시 KOSPI close < MA20 (전일 기준, lookahead 방지) 인 날 entry 차단.
"""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import EntryOrder
from backtests.strategies.macd_cross import MACDCrossStrategy


class MACDCrossRegimeFilterStrategy(MACDCrossStrategy):
    """KOSPI MA20 regime filter overlay.

    Args:
        regime_filter_enabled: True 면 KOSPI close < MA20 (전일) 인 날 entry block.
        kospi_daily_df: KOSPI 일봉 DataFrame (columns: trade_date YYYYMMDD str, close float).
            None 이고 regime_filter_enabled=True 면 ValueError.
        ma_period: MA window. 기본 20.
    """
    name = "macd_cross_regime_filter"

    def __init__(
        self,
        regime_filter_enabled: bool = False,
        kospi_daily_df: Optional[pd.DataFrame] = None,
        ma_period: int = 20,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.regime_filter_enabled = regime_filter_enabled
        self.kospi_daily_df = kospi_daily_df
        self.ma_period = ma_period
        if regime_filter_enabled and kospi_daily_df is None:
            raise ValueError(
                "regime_filter_enabled=True 인데 kospi_daily_df 가 None"
            )

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        feat = super().prepare_features(df_minute, df_daily).copy()
        if not self.regime_filter_enabled:
            return feat
        if df_minute.empty:
            return feat
        # Task 2 에서 채울 자리
        return feat
```

- [ ] **Step 1.4: 테스트 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py::test_filter_off_matches_base_no_kospi_needed -v
```
Expected: PASS.

- [ ] **Step 1.5: ValueError 가드 테스트 추가**

`tests/backtests/strategies/test_macd_cross_regime_filter.py` 끝에 추가:
```python
def test_filter_on_without_kospi_df_raises():
    """regime_filter_enabled=True + kospi_daily_df=None 시 ValueError."""
    with pytest.raises(ValueError, match="kospi_daily_df"):
        MACDCrossRegimeFilterStrategy(
            regime_filter_enabled=True,
            kospi_daily_df=None,
        )
```

- [ ] **Step 1.6: 테스트 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py -v
```
Expected: 2 passed.

- [ ] **Step 1.7: Commit**

```bash
git add backtests/strategies/macd_cross_regime_filter.py tests/backtests/strategies/test_macd_cross_regime_filter.py
git commit -m "$(cat <<'EOF'
feat(strategies): macd_cross_regime_filter wrapper 골격 (filter off=base)

KOSPI MA20 regime filter overlay 첫 단계. filter off 시 base 동작 그대로,
filter on + kospi_daily_df=None 시 ValueError 가드.

Spec docs/superpowers/specs/2026-05-09-macd-cross-fold2-regime-filter-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: KOSPI MA20 신호 계산 (prepare_features)

**Files:**
- Modify: `backtests/strategies/macd_cross_regime_filter.py:prepare_features`
- Test: `tests/backtests/strategies/test_macd_cross_regime_filter.py`

목적: `prepare_features` 가 `kospi_below_ma20: bool[bar_idx]` 컬럼을 추가. shift(1) 적용으로 lookahead 방지.

- [ ] **Step 2.1: 실패 테스트 추가**

`tests/backtests/strategies/test_macd_cross_regime_filter.py` 끝에 추가:
```python
def test_kospi_below_ma20_signal_with_shift1():
    """전일 (D-1) close < MA20 시 진입일 (D) 의 kospi_below_ma20=True.

    KOSPI 30일치 mock: 처음 25일 상승 (close>MA20), 마지막 5일 급락 (close<MA20).
    분봉은 D 일에만 1개. shift(1) 적용으로:
      - D 일 = 25일째 (최초 close<MA20) → MA20 은 D-1 까지로 계산 → D-1 (24일째) close
        가 MA20 위였다면 kospi_below_ma20[D]=False
      - D 일 = 26일째 → D-1 (25일째) close 가 MA20 아래였다면 kospi_below_ma20[D]=True
    """
    # KOSPI 30일치
    n = 30
    closes = list(range(1000, 1000 + 25)) + list(range(1024, 1024 - 5, -1))
    kospi = pd.DataFrame({
        "trade_date": [f"202509{d+1:02d}" for d in range(n)],
        "close": closes,
    })
    # 분봉: D=26일째 (index 25) — D-1=25일째 (closes[24]=1024 = peak, MA20 약간 아래?)
    # 실제로는 D-1 (25일째 = closes[24]=1024) 와 MA20[D-1] 비교. 데이터 의존이지만 핵심은 shift(1).
    target_date = "20250926"  # 26일째
    df_min = pd.DataFrame([{
        "stock_code": "000001",
        "trade_date": target_date,
        "trade_time": "143100",
        "open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1005.0,
        "volume": 1000,
    }])
    df_daily = pd.DataFrame({
        "trade_date": [target_date],
        "close": [1024.0],
    })

    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True,
        kospi_daily_df=kospi,
        ma_period=20,
        fast_period=14, slow_period=34, signal_period=12,
    )
    feat = strat.prepare_features(df_min, df_daily)
    assert "kospi_below_ma20" in feat.columns
    # D-1 = 25일째 close=1024 vs MA20[1..20일째 평균=1009.5]=close>MA20 → False
    # D=26일째 close=1023 — 그러나 D 의 신호는 D-1 의 결과 → False
    assert feat["kospi_below_ma20"].iloc[0] == False  # 첫 분봉

    # 다른 날짜 — D=29일째 → D-1=28일째 close 가 MA20 아래일 가능성
    df_min2 = pd.DataFrame([{
        "stock_code": "000001",
        "trade_date": "20250929",  # 29일째 (index 28)
        "trade_time": "143100",
        "open": 1020.0, "high": 1025.0, "low": 1015.0, "close": 1020.0,
        "volume": 1000,
    }])
    feat2 = strat.prepare_features(df_min2, df_daily)
    # closes[27]=1021, closes[27-19:27+1]=avg of closes[8..27]
    expected_ma20_d_minus_1 = sum(closes[8:28]) / 20
    expected_close_d_minus_1 = closes[27]  # D-1 = 28일째 (index 27)
    expected_below = expected_close_d_minus_1 < expected_ma20_d_minus_1
    assert feat2["kospi_below_ma20"].iloc[0] == expected_below


def test_warmup_insufficient_returns_false():
    """KOSPI lookback 부족 (<20봉) 시 below_prev=False (안전, no block)."""
    kospi = pd.DataFrame({
        "trade_date": [f"2025090{d+1}" for d in range(5)],
        "close": [1000, 990, 980, 970, 960],  # 5봉만 — MA20 NaN
    })
    df_min = pd.DataFrame([{
        "stock_code": "000001",
        "trade_date": "20250905",
        "trade_time": "143100",
        "open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1005.0,
        "volume": 1000,
    }])
    df_daily = pd.DataFrame({"trade_date": ["20250905"], "close": [1000.0]})
    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True,
        kospi_daily_df=kospi,
        fast_period=14, slow_period=34, signal_period=12,
    )
    feat = strat.prepare_features(df_min, df_daily)
    # NaN MA20 → fillna(False) → 안전
    assert feat["kospi_below_ma20"].iloc[0] == False
```

- [ ] **Step 2.2: 실패 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py::test_kospi_below_ma20_signal_with_shift1 tests/backtests/strategies/test_macd_cross_regime_filter.py::test_warmup_insufficient_returns_false -v
```
Expected: 2 fails (KeyError 'kospi_below_ma20' or similar).

- [ ] **Step 2.3: prepare_features 본체 구현**

`backtests/strategies/macd_cross_regime_filter.py:prepare_features` 의 Task 1 placeholder 자리에 추가:
```python
    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        feat = super().prepare_features(df_minute, df_daily).copy()
        if not self.regime_filter_enabled:
            return feat
        if df_minute.empty:
            return feat

        # KOSPI MA20 lookup table — shift(1) 로 D-1 신호만 사용 (lookahead 방지)
        ks = self.kospi_daily_df.sort_values("trade_date").copy()
        ks["ma"] = ks["close"].rolling(self.ma_period).mean()
        ks["below"] = (ks["close"] < ks["ma"]).astype(bool)
        ks["below_prev"] = ks["below"].shift(1).fillna(False).astype(bool)
        block_map = dict(zip(ks["trade_date"].astype(str), ks["below_prev"]))

        feat["kospi_below_ma20"] = (
            df_minute["trade_date"].astype(str)
            .map(block_map).fillna(False).astype(bool).values
        )
        return feat
```

- [ ] **Step 2.4: 테스트 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py -v
```
Expected: 4 passed (Task 1 의 2 + Task 2 의 2).

- [ ] **Step 2.5: Commit**

```bash
git add backtests/strategies/macd_cross_regime_filter.py tests/backtests/strategies/test_macd_cross_regime_filter.py
git commit -m "$(cat <<'EOF'
feat(strategies): regime_filter prepare_features — KOSPI MA20 below_prev

shift(1) 적용으로 D-1 close 와 D-1 MA20 만 사용 (lookahead 방지).
warmup 부족 시 fillna(False) 로 안전 (block 안 함).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: entry_signal block (filter ON 시 차단)

**Files:**
- Modify: `backtests/strategies/macd_cross_regime_filter.py` — `entry_signal` 추가
- Test: `tests/backtests/strategies/test_macd_cross_regime_filter.py`

목적: filter 활성 + `kospi_below_ma20=True` 시 `entry_signal` 이 None 반환.

- [ ] **Step 3.1: 실패 테스트 추가**

```python
def test_filter_blocks_entry_when_below_ma20():
    """filter ON + below_prev=True 시 entry_signal None 반환."""
    # 인위 mock features
    feat = pd.DataFrame({
        "prev_hist": [0.5],
        "prev_prev_hist": [-0.3],
        "hhmm": [1430],
        "kospi_below_ma20": [True],
    })
    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True,
        kospi_daily_df=pd.DataFrame({"trade_date": ["20250101"], "close": [1000]}),
        fast_period=14, slow_period=34, signal_period=12,
    )
    result = strat.entry_signal(feat, bar_idx=0, stock_code="000001")
    assert result is None  # blocked


def test_filter_allows_entry_when_above_ma20():
    """filter ON + below_prev=False + golden cross 시 entry order 반환."""
    feat = pd.DataFrame({
        "prev_hist": [0.5],
        "prev_prev_hist": [-0.3],  # golden cross: prev_prev<0, prev>0
        "hhmm": [1430],
        "kospi_below_ma20": [False],
    })
    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True,
        kospi_daily_df=pd.DataFrame({"trade_date": ["20250101"], "close": [1000]}),
        fast_period=14, slow_period=34, signal_period=12,
        entry_hhmm_min=1430, entry_hhmm_max=1500,
    )
    result = strat.entry_signal(feat, bar_idx=0, stock_code="000001")
    assert result is not None  # allowed
    assert result.stock_code == "000001"


def test_filter_off_does_not_check_kospi():
    """filter OFF 시 kospi_below_ma20 컬럼 없어도 정상 — base 그대로."""
    feat = pd.DataFrame({
        "prev_hist": [0.5],
        "prev_prev_hist": [-0.3],
        "hhmm": [1430],
    })
    strat = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=False,
        fast_period=14, slow_period=34, signal_period=12,
        entry_hhmm_min=1430, entry_hhmm_max=1500,
    )
    result = strat.entry_signal(feat, bar_idx=0, stock_code="000001")
    assert result is not None  # base allows
```

- [ ] **Step 3.2: 실패 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py::test_filter_blocks_entry_when_below_ma20 -v
```
Expected: FAIL — base entry_signal 이 사용되어 None 이 안 됨.

- [ ] **Step 3.3: entry_signal 추가**

`backtests/strategies/macd_cross_regime_filter.py` 의 클래스 끝에 추가:
```python
    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if self.regime_filter_enabled and "kospi_below_ma20" in features.columns:
            arr = get_arrays(features)
            if bool(arr["kospi_below_ma20"][bar_idx]):
                return None  # filter block
        return super().entry_signal(features, bar_idx, stock_code)
```

- [ ] **Step 3.4: 테스트 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py -v
```
Expected: 7 passed.

- [ ] **Step 3.5: Commit**

```bash
git add backtests/strategies/macd_cross_regime_filter.py tests/backtests/strategies/test_macd_cross_regime_filter.py
git commit -m "$(cat <<'EOF'
feat(strategies): regime_filter entry_signal block when below_prev=True

filter ON + kospi_below_ma20[bar_idx]=True 시 None 반환 (entry 차단).
filter OFF 또는 below_prev=False 시 base entry_signal 동작.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Lookahead 강제 검증 + 회귀

**Files:**
- Test: `tests/backtests/strategies/test_macd_cross_regime_filter.py` (끝에 추가)

목적: D 일 종가가 신호 계산에 절대 사용되지 않음을 강제 검증.

- [ ] **Step 4.1: lookahead 검증 테스트 추가**

```python
def test_no_lookahead_d_close_not_used():
    """D 일 종가를 변경해도 D 일 의 kospi_below_ma20 신호가 동일.

    shift(1) 검증: 신호는 D-1 까지만 의존 → D 일 close 는 무관.
    """
    n = 25
    base_closes = list(range(1000, 1000 + n))
    kospi_a = pd.DataFrame({
        "trade_date": [f"202509{d+1:02d}" for d in range(n)],
        "close": base_closes,
    })
    # D 일 (마지막) close 만 다른 사본 — D 일 close=1024 → 9999 변경
    kospi_b = kospi_a.copy()
    kospi_b.loc[n - 1, "close"] = 9999.0  # D 일 close 만 다름

    target_date = f"202509{n:02d}"  # D 일
    df_min = pd.DataFrame([{
        "stock_code": "000001",
        "trade_date": target_date,
        "trade_time": "143100",
        "open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1005.0,
        "volume": 1000,
    }])
    df_daily = pd.DataFrame({"trade_date": [target_date], "close": [1024.0]})

    strat_a = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True, kospi_daily_df=kospi_a,
        fast_period=14, slow_period=34, signal_period=12,
    )
    strat_b = MACDCrossRegimeFilterStrategy(
        regime_filter_enabled=True, kospi_daily_df=kospi_b,
        fast_period=14, slow_period=34, signal_period=12,
    )
    feat_a = strat_a.prepare_features(df_min, df_daily)
    feat_b = strat_b.prepare_features(df_min, df_daily)

    # D 일 close 변경이 D 일 신호에 영향 없어야 — shift(1) lookahead 0 보증
    assert (feat_a["kospi_below_ma20"].values
            == feat_b["kospi_below_ma20"].values).all()
```

- [ ] **Step 4.2: 테스트 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_regime_filter.py -v
```
Expected: 8 passed.

- [ ] **Step 4.3: 전체 회귀**

```bash
python -m pytest tests/ -q
```
Expected: 270+ passed (라이브 코드 무수정이라 회귀 0).

- [ ] **Step 4.4: Commit**

```bash
git add tests/backtests/strategies/test_macd_cross_regime_filter.py
git commit -m "$(cat <<'EOF'
test(strategies): regime_filter lookahead 강제 검증

D 일 close 를 변경해도 D 일 신호 동일 — shift(1) 의 lookahead-zero 보증.
멀티버스 3대 원칙 ① 충족.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Dataset.kospi_daily_df 필드 + load_all_datasets KOSPI 첨부

**Files:**
- Modify: `backtests/multiverse/macd_cross_mv_common.py` — `Dataset` 필드 + `load_all_datasets` KOSPI 로드
- Test: `tests/backtests/multiverse/test_macd_cross_mv_common.py` (기존)

목적: 멀티버스 dataset 4개 모두 KOSPI 일봉 첨부.

- [ ] **Step 5.1: 실패 테스트 추가**

`tests/backtests/multiverse/test_macd_cross_mv_common.py` (기존 파일) 끝에 추가:
```python
def test_dataset_has_kospi_daily_df_field():
    """Dataset dataclass 에 kospi_daily_df: Optional[pd.DataFrame] 필드 존재."""
    from backtests.multiverse.macd_cross_mv_common import Dataset
    ds = Dataset(name="t", minute_start="20250901", minute_end="20250930",
                 daily_start="20250101")
    assert hasattr(ds, "kospi_daily_df")
    assert ds.kospi_daily_df is None  # default
```

- [ ] **Step 5.2: 실패 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py::test_dataset_has_kospi_daily_df_field -v
```
Expected: FAIL — `AttributeError: 'Dataset' object has no attribute 'kospi_daily_df'`.

- [ ] **Step 5.3: Dataset 필드 추가**

`backtests/multiverse/macd_cross_mv_common.py` 의 `Dataset` dataclass:

기존:
```python
@dataclass
class Dataset:
    """단일 평가 dataset — fold1/fold2/fold3/oos."""

    name: str
    minute_start: str
    minute_end: str
    daily_start: str
    minute_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    daily_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    universe: List[str] = field(default_factory=list)
```

→ 필드 추가:
```python
from typing import Optional

@dataclass
class Dataset:
    """단일 평가 dataset — fold1/fold2/fold3/oos."""

    name: str
    minute_start: str
    minute_end: str
    daily_start: str
    minute_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    daily_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    universe: List[str] = field(default_factory=list)
    kospi_daily_df: Optional[pd.DataFrame] = None  # 신규 (regime filter 용)
```

(`Optional` 이 import 안 되어있으면 typing import 에 추가.)

- [ ] **Step 5.4: 테스트 통과 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py::test_dataset_has_kospi_daily_df_field -v
```
Expected: PASS.

- [ ] **Step 5.5: load_all_datasets 에 KOSPI 첨부**

기존 `load_all_datasets()` 함수의 마지막 return 직전에 KOSPI 로드 + 첨부 추가:

```python
def load_all_datasets() -> Dict[str, Dataset]:
    # ... 기존 universe / minute_full / daily_full / fold_specs 루프 ...

    # 신규: KOSPI 일봉 1회 로드 (모든 dataset 공유)
    from backtests.common.data_loader import load_index_df
    kospi_raw = load_index_df("KS11", daily_start, minute_end)
    kospi_norm = pd.DataFrame({
        "trade_date": kospi_raw["trade_date"].astype(str),
        "close": kospi_raw["close"].astype(float),
    }).sort_values("trade_date").reset_index(drop=True)

    for ds_name in datasets:
        datasets[ds_name].kospi_daily_df = kospi_norm

    return datasets
```

- [ ] **Step 5.6: KOSPI 로드 smoke test**

```bash
python -c "
from backtests.multiverse.macd_cross_mv_common import load_all_datasets
ds = load_all_datasets()
fold1 = ds['fold1']
print('kospi_daily_df rows:', len(fold1.kospi_daily_df))
print('first 3:', fold1.kospi_daily_df.head(3).to_dict('records'))
print('last 3:', fold1.kospi_daily_df.tail(3).to_dict('records'))
"
```
Expected: 약 320 rows (2025-01 ~ 2026-04 영업일), trade_date 가 YYYYMMDD 문자열, close 가 float.

- [ ] **Step 5.7: Commit**

```bash
git add backtests/multiverse/macd_cross_mv_common.py tests/backtests/multiverse/test_macd_cross_mv_common.py
git commit -m "$(cat <<'EOF'
feat(mv): Dataset 에 kospi_daily_df 필드 + load_all_datasets KOSPI 로드

regime_filter 용 KOSPI (KS11) 일봉을 1회 로드해 4 dataset 모두 첨부.
load_index_df 재사용. trade_date YYYYMMDD 문자열 / close float 정규화.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: MV-C runner

**Files:**
- Create: `backtests/multiverse/macd_cross_regime_filter_mv.py`

목적: 2 params × 2 filter × 4 dataset = 16 evaluation. cells.csv long-format + block_days 추가 측정.

- [ ] **Step 6.1: runner 작성**

`backtests/multiverse/macd_cross_regime_filter_mv.py`:
```python
"""MV-C: macd_cross regime filter 멀티버스.

Spec docs/superpowers/specs/2026-05-09-macd-cross-fold2-regime-filter-design.md.

2 params (Stage 2 best 14/34, MV-A globally best 16/32) × 2 filter (off, on)
× 4 dataset (fold1/fold2/fold3/oos) = 16 evaluation. cells.csv 에 block_days
까지 기록.
"""
import csv
import time
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_regime_filter import (
    MACDCrossRegimeFilterStrategy,
)


REPORT_DIR = Path("backtests/reports/macd_cross_mv/regime_filter")

PARAM_CELLS = [
    {"label": "stage2_best",
     "fast_period": 14, "slow_period": 34,
     "signal_period": 12, "entry_hhmm_min": 1430},
    {"label": "mva_global_best",
     "fast_period": 16, "slow_period": 32,
     "signal_period": 12, "entry_hhmm_min": 1430},
]
FILTER_FLAGS = [False, True]


def _count_block_days(
    kospi_daily_df: Optional[pd.DataFrame],
    dataset: Dataset,
    ma_period: int,
) -> int:
    """dataset 영업일 중 filter 가 차단했을 일수.

    엔진과 별도로 KOSPI 신호를 재계산해 dataset 의 minute trade_date set 과
    intersect. 차단 일수만 카운트.
    """
    if kospi_daily_df is None:
        return 0
    ks = kospi_daily_df.sort_values("trade_date").copy()
    ks["ma"] = ks["close"].rolling(ma_period).mean()
    ks["below_prev"] = (ks["close"] < ks["ma"]).shift(1).fillna(False)
    ds_dates = set()
    for df_min in dataset.minute_by_code.values():
        if not df_min.empty:
            ds_dates.update(df_min["trade_date"].astype(str).unique())
    sub = ks[ks["trade_date"].astype(str).isin(ds_dates)]
    return int(sub["below_prev"].sum())


def _evaluate(strategy, dataset, ma_period, initial_capital=10_000_000) -> Dict:
    eng = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        universe=dataset.universe,
        minute_df_by_code=dataset.minute_by_code,
        daily_df_by_code=dataset.daily_by_code,
    )
    result = eng.run()
    trading_days = _trading_days_count(dataset.minute_by_code)
    kpis = build_cell_kpis(
        equity=result.equity_curve,
        trades=result.trades,
        trading_days=trading_days,
    )
    if strategy.regime_filter_enabled:
        kpis["block_days"] = _count_block_days(
            strategy.kospi_daily_df, dataset, ma_period,
        )
    else:
        kpis["block_days"] = 0
    return kpis


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("[MV-C] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    total_cells = len(PARAM_CELLS) * len(FILTER_FLAGS) * len(datasets)
    print(f"[MV-C] {total_cells} evaluation 시작")

    out_path = REPORT_DIR / "cells.csv"
    fieldnames = [
        "param_label", "fast_period", "slow_period", "signal_period",
        "entry_hhmm_min", "filter", "dataset",
        "calmar", "return", "mdd", "trades", "win_rate",
        "top1_share", "max_consec_loss", "monthly_trades", "block_days",
    ]
    t0 = time.time()
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for params in PARAM_CELLS:
            label = params["label"]
            params_no_label = {k: v for k, v in params.items() if k != "label"}
            for filter_on in FILTER_FLAGS:
                for ds_name, ds in datasets.items():
                    strat = MACDCrossRegimeFilterStrategy(
                        regime_filter_enabled=filter_on,
                        kospi_daily_df=ds.kospi_daily_df if filter_on else None,
                        ma_period=20,
                        **params_no_label,
                    )
                    kpis = _evaluate(strat, ds, ma_period=20)
                    row = {
                        "param_label": label,
                        **params_no_label,
                        "filter": "on" if filter_on else "off",
                        "dataset": ds_name,
                        **{k: kpis[k] for k in (
                            "calmar","return","mdd","trades","win_rate",
                            "top1_share","max_consec_loss","monthly_trades",
                            "block_days",
                        )},
                    }
                    writer.writerow(row)
                    print(f"  {label} filter={'on' if filter_on else 'off'} {ds_name}: "
                          f"calmar={kpis['calmar']:.2f} block={kpis['block_days']} "
                          f"trades={kpis['trades']}")
    elapsed = time.time() - t0
    print(f"[MV-C] saved → {out_path} ({elapsed:.0f}s)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6.2: 작은 스모크 (1 param × 1 filter × 1 dataset)**

코드 임시 수정 없이 inline:
```bash
python -c "
from backtests.multiverse.macd_cross_mv_common import load_all_datasets
from backtests.multiverse.macd_cross_regime_filter_mv import _evaluate, PARAM_CELLS
from backtests.strategies.macd_cross_regime_filter import MACDCrossRegimeFilterStrategy

ds = load_all_datasets()['fold2']
params = PARAM_CELLS[0]
params_no_label = {k:v for k,v in params.items() if k!='label'}
strat = MACDCrossRegimeFilterStrategy(
    regime_filter_enabled=True,
    kospi_daily_df=ds.kospi_daily_df,
    ma_period=20,
    **params_no_label,
)
kpis = _evaluate(strat, ds, ma_period=20)
print('fold2 stage2_best filter=ON kpis:', kpis)
"
```
Expected: dict 출력, 에러 없음. fold2 의 block_days > 0 이어야 (close<MA20 이 자주 발생).

- [ ] **Step 6.3: Commit**

```bash
git add backtests/multiverse/macd_cross_regime_filter_mv.py
git commit -m "$(cat <<'EOF'
feat(mv): MV-C regime filter 러너 (16 evaluation)

2 params × 2 filter × 4 dataset. cells.csv long-format + block_days.
Stage 2 best (14/34) + MV-A global best (16/32) 둘 다 평가.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Plotter 확장 (heatmap + summary)

**Files:**
- Modify: `backtests/multiverse/plot_macd_cross_mv.py`

목적: cells.csv → heatmap PNG 1장 + summary.md (4-gate 자동 평가).

- [ ] **Step 7.1: plotter 함수 추가**

`backtests/multiverse/plot_macd_cross_mv.py` 의 EO_DIR 정의 직후에 RF_DIR 추가:
```python
RF_DIR = Path("backtests/reports/macd_cross_mv/regime_filter")
```

기존 `write_exit_overlay_summary()` 함수 직후에 추가:
```python
def plot_regime_filter():
    df = pd.read_csv(RF_DIR / "cells.csv")
    out = RF_DIR / "heatmaps"
    out.mkdir(exist_ok=True)
    # heatmap: index=param_label, columns=(filter, dataset), value=calmar
    pivot = df.pivot_table(
        index="param_label", columns=["filter", "dataset"],
        values="calmar", aggfunc="mean",
    )
    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn", origin="lower")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{f}\n{d}" for f, d in pivot.columns], fontsize=8)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_title("Calmar — param × filter × dataset")
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8, color="black")
    plt.colorbar(im, ax=ax, fraction=0.04)
    fig.tight_layout()
    fig.savefig(out / "calmar_summary.png", dpi=110)
    plt.close(fig)
    print(f"[plot] regime_filter heatmap → {out}")


def write_regime_filter_summary():
    df = pd.read_csv(RF_DIR / "cells.csv")
    # ON vs OFF 비교 (param, dataset 별)
    pivot = df.pivot_table(
        index=["param_label", "dataset"], columns="filter",
        values=["calmar", "return", "mdd", "block_days"], aggfunc="mean",
    )
    # delta calmar (on - off), per (param, dataset)
    delta_calmar = pivot[("calmar", "on")] - pivot[("calmar", "off")]
    # gate evaluation
    fold2_delta = delta_calmar.xs("fold2", level="dataset").mean()
    f1_off = pivot[("calmar", "off")].xs("fold1", level="dataset").mean()
    f3_off = pivot[("calmar", "off")].xs("fold3", level="dataset").mean()
    f1_delta = delta_calmar.xs("fold1", level="dataset").mean()
    f3_delta = delta_calmar.xs("fold3", level="dataset").mean()
    # 손실율 % (off 대비)
    f1_loss_pct = (f1_delta / f1_off * 100) if abs(f1_off) > 1e-6 else 0.0
    f3_loss_pct = (f3_delta / f3_off * 100) if abs(f3_off) > 1e-6 else 0.0
    oos_delta = delta_calmar.xs("oos", level="dataset").mean()
    fold2_block = pivot[("block_days", "on")].xs("fold2", level="dataset").mean()
    fold1_block = pivot[("block_days", "on")].xs("fold1", level="dataset").mean()
    fold3_block = pivot[("block_days", "on")].xs("fold3", level="dataset").mean()

    gates = [
        ("fold2 calmar +20+", fold2_delta >= 20.0,
         f"Δcalmar = {fold2_delta:+.2f} (요구: ≥+20)"),
        ("fold1/3 손실 -5% 이내",
         abs(f1_loss_pct) <= 5.0 and abs(f3_loss_pct) <= 5.0,
         f"fold1 {f1_loss_pct:+.1f}% / fold3 {f3_loss_pct:+.1f}% (요구: 둘 다 |-5%| 이내)"),
        ("oos calmar ±0 이상", oos_delta >= 0.0,
         f"Δcalmar = {oos_delta:+.2f} (요구: ≥0)"),
        ("block_days selectivity",
         fold2_block > 5.0 and max(fold1_block, fold3_block) <= 2.0,
         f"f2={fold2_block:.0f} f1={fold1_block:.0f} f3={fold3_block:.0f} "
         f"(요구: f2>5, f1/f3≤2)"),
    ]
    all_pass = all(g[1] for g in gates)

    body = []
    body.append("# MV-C regime filter summary\n")
    body.append("## Calmar (filter on - off, mean over params)\n")
    delta_table = delta_calmar.unstack().to_markdown()
    body.append(delta_table)
    body.append("\n## Decision Gate 4조건 평가\n")
    for name, passed, msg in gates:
        body.append(f"- {'✓' if passed else '✗'} **{name}**: {msg}")
    body.append(f"\n## 종합: {'**PASS** — Phase 2 진입 권고' if all_pass else '**FAIL** — 보완 또는 폐기'}")
    body.append("")
    body.append("heatmaps/calmar_summary.png 와 cells.csv 함께 검토.")

    (RF_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
    print(f"[summary] {RF_DIR / 'summary.md'}")
```

기존 `main()` 함수 수정:
```python
def main():
    if (PG_DIR / "cells.csv").exists():
        plot_param_grid()
        write_param_grid_summary()
    if (EO_DIR / "cells.csv").exists():
        plot_exit_overlay()
        write_exit_overlay_summary()
    if (RF_DIR / "cells.csv").exists():
        plot_regime_filter()
        write_regime_filter_summary()
```

- [ ] **Step 7.2: 더미 cells.csv 로 스모크**

```bash
python -c "
import pandas as pd
from pathlib import Path
Path('backtests/reports/macd_cross_mv/regime_filter').mkdir(parents=True, exist_ok=True)
rows = []
for label, fast, slow in [('stage2_best', 14, 34), ('mva_global_best', 16, 32)]:
    for filt in ['off', 'on']:
        for ds in ['fold1', 'fold2', 'fold3', 'oos']:
            calmar = 50 + (20 if filt == 'on' and ds == 'fold2' else 0) - (5 if filt == 'on' and ds in ('fold1','fold3') else 0)
            block = 8 if filt == 'on' and ds == 'fold2' else (1 if filt == 'on' else 0)
            rows.append({
                'param_label': label,
                'fast_period': fast, 'slow_period': slow,
                'signal_period': 12, 'entry_hhmm_min': 1430,
                'filter': filt, 'dataset': ds,
                'calmar': calmar, 'return': 0.1, 'mdd': -0.02,
                'trades': 30, 'win_rate': 0.5, 'top1_share': 0.5,
                'max_consec_loss': 3, 'monthly_trades': 15,
                'block_days': block,
            })
pd.DataFrame(rows).to_csv('backtests/reports/macd_cross_mv/regime_filter/cells.csv', index=False)
print('dummy cells.csv written:', len(rows), 'rows')
"
python -m backtests.multiverse.plot_macd_cross_mv 2>&1
echo "--- summary ---"
cat backtests/reports/macd_cross_mv/regime_filter/summary.md
```
Expected: heatmap PNG 생성 + summary.md 생성. 4-gate 모두 PASS 또는 일부 FAIL 표시 (더미값 의존).

- [ ] **Step 7.3: 더미 정리**

```bash
rm backtests/reports/macd_cross_mv/regime_filter/cells.csv
rm backtests/reports/macd_cross_mv/regime_filter/summary.md
rm -rf backtests/reports/macd_cross_mv/regime_filter/heatmaps
```

- [ ] **Step 7.4: Commit**

```bash
git add backtests/multiverse/plot_macd_cross_mv.py
git commit -m "$(cat <<'EOF'
feat(mv): regime_filter heatmap + summary 자동 생성

cells.csv → calmar_summary.png + summary.md (4-gate 자동 PASS/FAIL).
fold2 calmar +20+, fold1/3 손실 -5% 이내, oos ±0, block_days
selectivity 4 조건 평가.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Phase 1 풀 실행 + 결과 commit

**Files:** 결과 산출물만 (코드 없음)

목적: MV-C 16 evaluation 풀 실행 → cells.csv → heatmap + summary.md → 4-gate 평가 결과 보고.

- [ ] **Step 8.1: MV-C 풀 실행 (예상 5~10분)**

```bash
python -m backtests.multiverse.macd_cross_regime_filter_mv 2>&1 | tee backtests/reports/macd_cross_mv/regime_filter_run.log
```
Expected: cells.csv (16 rows) 생성, 에러 없음.

- [ ] **Step 8.2: heatmap + summary 생성**

```bash
python -m backtests.multiverse.plot_macd_cross_mv
```
Expected: regime_filter/heatmaps/calmar_summary.png + regime_filter/summary.md 생성.

- [ ] **Step 8.3: Sanity check**

```bash
ls backtests/reports/macd_cross_mv/regime_filter/
ls backtests/reports/macd_cross_mv/regime_filter/heatmaps/
python -c "
import pandas as pd
df = pd.read_csv('backtests/reports/macd_cross_mv/regime_filter/cells.csv')
print('rows:', len(df))
print('shape:', df.shape)
print('block_days by filter+dataset:')
print(df[df['filter']=='on'].groupby('dataset')['block_days'].mean())
"
cat backtests/reports/macd_cross_mv/regime_filter/summary.md
```
Expected: 16 rows, fold2 block_days > 0, fold1/3 block_days 작음, summary.md 의 4-gate PASS/FAIL 판정 출력.

- [ ] **Step 8.4: 결과 보강 (사람 판단)**

`summary.md` 의 종합 결과 (PASS / FAIL) 확인 후, 필요 시 사람이 결론 섹션 추가:
- 추가할 내용: 다음 단계 권고 (Phase 2 진입 / 신호 보완 / 폐기), 후속 조사 항목.
- 자동 4-gate 외에 정성적 관찰 (e.g., trades 수 변화, top1_share 변화, win_rate 변화) 도 함께 검토.

(자동 판정으로 충분하면 보강 생략 가능.)

- [ ] **Step 8.5: 결과 commit**

```bash
git add backtests/reports/macd_cross_mv/regime_filter/
git commit -m "$(cat <<'EOF'
data(mv): MV-C regime filter 결과 산출물 (16 evaluation)

cells.csv 16 rows + heatmap PNG + summary.md (4-gate 평가).
KOSPI close<MA20 (전일) 신호 + 2 params (14/34, 16/32) × 2 filter × 4 dataset.

자동 4-gate 평가:
  - fold2 calmar +20+
  - fold1/3 손실 -5% 이내
  - oos ±0
  - block_days selectivity (fold2>5, fold1/3≤2)

cells.csv / run.log 는 .gitignore 정책 따라 미포함 (러너 재실행으로 재현).

Spec docs/superpowers/specs/2026-05-09-macd-cross-fold2-regime-filter-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(`.gitignore` 가 `*.csv`, `*.log` 차단하면 summary.md + heatmap PNG 만 staged. 정상.)

---

## Self-Review (이미 적용)

- 모든 task 가 spec §1~10 cover (배경 §1, 결정 §2, gate §3, wrapper §4.1, dataset §4.2, runner §4.3, plotter §4.4, 데이터흐름 §5, lookahead §6, testing §7, 산출물 §8)
- 모든 step 에 실제 code/command/expected output 포함, "TBD/TODO" 없음
- type / 함수명 일관성: `MACDCrossRegimeFilterStrategy`, `kospi_daily_df`, `regime_filter_enabled`, `kospi_below_ma20`, `block_days`, `_evaluate`, `_count_block_days`, `MV-C` 전반 동일
- 라이브 코드 (`core/`, `main.py`) 변경 0 — Phase 1 분석 전용
- Phase 2 (라이브 적용) 는 본 plan 범위 밖. 4-gate PASS 시 별도 spec/plan 으로 진행.
