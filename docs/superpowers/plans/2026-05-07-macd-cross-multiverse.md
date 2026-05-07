# macd_cross Multiverse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spec `docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md` 의 두 멀티버스 (MV-A 파라미터 robustness, MV-B exit overlay) 를 실행 가능한 코드 + 결과 산출물로 구현한다.

**Architecture:** 기존 `backtests/common/engine.py` 와 `backtests/multiverse/` 인프라 재사용. wrapper 전략 1개 (`MACDCrossExitOverlayStrategy`) + 공통 유틸 1개 (KPI extras, dataset loader, cell evaluator) + 러너 2개 + 플로터 1개 추가. 본체 `backtests/strategies/macd_cross.py` 는 라이브 동등성 보호 위해 미수정.

**Tech Stack:** Python 3.9, pandas, numpy, matplotlib, psycopg2, pytest. 실행 환경 Windows PowerShell.

---

## 사전 정보 — 엔지니어가 알아야 할 컨벤션

### 엔진 fill 모델
`backtests/common/engine.py:71-75` 보면 ExitOrder 가 반환되면 엔진은 `next_fill_index(t)` 의 **next-bar open** 에 슬리피지 모델로 매도 체결. spec §4.3 의 "그 분봉 종가" 는 trigger 시점 의미일 뿐, **실제 체결은 엔진 컨벤션 (t+1 open) 따른다**. 기존 `hold_limit` 도 동일.

### Strategy interface
- `prepare_features(df_minute, df_daily) -> pd.DataFrame` — features 컬럼은 자유, `bar_idx` 로 인덱싱
- `entry_signal(features, bar_idx, stock_code) -> Optional[EntryOrder]`
- `exit_signal(position, features, bar_idx, current_price) -> Optional[ExitOrder]`
  - `current_price` = `df_min["close"].iloc[bar_idx]` (close 만 전달, high/low 는 features 에 직접 캐싱 필요)
- features 내부 array 접근은 `from backtests.common.feature_cache import get_arrays` 사용 (numpy O(1))

### Position 객체
`backtests/strategies/base.py:Position` — `stock_code, entry_bar_idx, entry_price, quantity, entry_date` 필드 모두 사용 가능. `entry_price` 가 SL/TP 기준점.

### Universe / Fold 재사용
- `backtests/multiverse/universe.py:select_top_universe` — `top30_20250301_20260228_min120.json` 캐시 자동 사용
- `backtests/multiverse/fold.py:STAGE2_FOLDS` — 3 folds 정의 보유. OOS 는 별도 Fold 인스턴스로 정의.

### 평가 dataset 4개
| 이름 | period | source |
|------|--------|--------|
| `fold1` | 2025-09-01 ~ 2025-10-31 | STAGE2_FOLDS[0].test_* |
| `fold2` | 2025-11-01 ~ 2025-12-31 | STAGE2_FOLDS[1].test_* |
| `fold3` | 2026-01-01 ~ 2026-02-28 | STAGE2_FOLDS[2].test_* |
| `oos` | 2026-03-01 ~ 2026-04-24 | 신규 정의 |

모든 dataset 의 universe 는 stage 2 cache (`top30_20250301_20260228_min120.json`) 동일 사용. minute_df 로드 범위는 dataset 별 (test 구간), daily_df 는 warm-up 위해 1년 전부터.

### 테스트 디렉토리
- 기존: `tests/backtests/test_*.py`
- 신규: `tests/backtests/multiverse/test_*.py` (디렉토리 신설)

---

## 파일 구조 (생성/수정)

```
backtests/
  strategies/
    macd_cross_exit_overlay.py            [신규]  Task 5-8
  multiverse/
    macd_cross_mv_common.py               [신규]  Task 1-4
    macd_cross_param_grid.py              [신규]  Task 9
    macd_cross_exit_overlay_mv.py         [신규]  Task 10
    plot_macd_cross_mv.py                 [신규]  Task 11-12

tests/backtests/
  multiverse/
    __init__.py                           [신규]  Task 1
    test_macd_cross_mv_common.py          [신규]  Task 1, 4
  strategies/
    __init__.py                           [신규 if 없음]  Task 5
    test_macd_cross_exit_overlay.py       [신규]  Task 5-8

backtests/reports/macd_cross_mv/         [신규 디렉토리, Task 13 채움]
  param_grid/cells.csv
  param_grid/heatmaps/*.png
  param_grid/summary.md
  exit_overlay/cells.csv
  exit_overlay/heatmaps/*.png
  exit_overlay/summary.md

docs/superpowers/specs/
  2026-05-07-macd-cross-multiverse-design.md  [수정]  Task 5: spec §4.3 fill 컨벤션 보강
```

---

## Task 1: KPI 추가 함수 (top1_share, max_consec_loss)

**Files:**
- Create: `tests/backtests/multiverse/__init__.py` (빈 파일)
- Create: `tests/backtests/multiverse/test_macd_cross_mv_common.py`
- Create: `backtests/multiverse/macd_cross_mv_common.py`

- [ ] **Step 1: 빈 init 파일 생성**

```bash
New-Item -ItemType File -Path tests/backtests/multiverse/__init__.py -Force
```

- [ ] **Step 2: 테스트 작성**

`tests/backtests/multiverse/test_macd_cross_mv_common.py`:
```python
"""macd_cross 멀티버스 공통 유틸 단위 테스트."""
import pandas as pd

from backtests.multiverse.macd_cross_mv_common import (
    compute_top1_share, compute_max_consec_loss,
)


def test_top1_share_basic():
    pnls = pd.Series([100, 50, -30, 200, -10])
    # sum = 310, top1 (max) = 200, share = 200/310
    assert abs(compute_top1_share(pnls) - 200 / 310) < 1e-9


def test_top1_share_zero_with_no_trades():
    assert compute_top1_share(pd.Series([], dtype=float)) == 0.0


def test_top1_share_zero_when_sum_zero():
    pnls = pd.Series([100, -100])
    assert compute_top1_share(pnls) == 0.0


def test_top1_share_negative_sum_returns_signed():
    pnls = pd.Series([-100, -50, 30])
    # sum = -120, top1 = 30, share = -0.25 (음수 sum 이면 share 도 음수)
    assert abs(compute_top1_share(pnls) - 30 / -120) < 1e-9


def test_max_consec_loss_basic():
    # streaks: 1 (-10), 3 (-5,-30,-40)
    pnls = [100, -10, -20, 50, -5, -30, -40, 10]
    assert compute_max_consec_loss(pnls) == 3


def test_max_consec_loss_all_wins():
    assert compute_max_consec_loss([10, 20, 30]) == 0


def test_max_consec_loss_all_losses():
    assert compute_max_consec_loss([-10, -20, -30]) == 3


def test_max_consec_loss_empty():
    assert compute_max_consec_loss([]) == 0


def test_max_consec_loss_zero_breaks_streak():
    # -10 streak=1, 0 breaks, -20 -30 streak=2 → max=2
    pnls = [-10, 0, -20, -30]
    assert compute_max_consec_loss(pnls) == 2
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py -v
```
Expected: FAIL with `ModuleNotFoundError: backtests.multiverse.macd_cross_mv_common`

- [ ] **Step 4: 구현 추가**

`backtests/multiverse/macd_cross_mv_common.py`:
```python
"""macd_cross 멀티버스 공통 유틸 — KPI extras, dataset 로더, cell evaluator."""
from typing import Iterable

import pandas as pd


def compute_top1_share(trade_pnls: pd.Series) -> float:
    """단일 최대 P&L / 전체 net 합 (signed). PHASE6 OOS 와 동일 정의.

    분모는 net (signed) sum 이므로 sum<0 일 때 share 도 음수가 될 수 있다.
    거래 0 또는 sum=0 시 0.0 반환.
    """
    if len(trade_pnls) == 0:
        return 0.0
    total = float(trade_pnls.sum())
    if total == 0:
        return 0.0
    return float(trade_pnls.max() / total)


def compute_max_consec_loss(trade_pnls: Iterable[float]) -> int:
    """시간순 trade pnl 시퀀스에서 음수 연속 카운트 최댓값.

    pnl == 0 은 streak 를 끊는 (loss 가 아님) 것으로 처리.
    """
    max_run = 0
    cur_run = 0
    for p in trade_pnls:
        if p < 0:
            cur_run += 1
            if cur_run > max_run:
                max_run = cur_run
        else:
            cur_run = 0
    return max_run
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py -v
```
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/backtests/multiverse/__init__.py tests/backtests/multiverse/test_macd_cross_mv_common.py backtests/multiverse/macd_cross_mv_common.py
git commit -m "$(cat <<'EOF'
feat(mv): macd_cross 멀티버스 KPI 추가 함수 (top1_share, max_consec_loss)

Spec docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md
§2.3 의 KPI 정의 구현. PHASE6 OOS 와 동일 정의 (top1_share = max/sum 시그너처).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Dataset 데이터클래스 + cell KPI 빌더

**Files:**
- Modify: `backtests/multiverse/macd_cross_mv_common.py` — Dataset, build_cell_kpis 추가
- Modify: `tests/backtests/multiverse/test_macd_cross_mv_common.py` — KPI 빌더 테스트 추가

목적: BacktestResult + trades 리스트 → 단일 dict (KPI 8종) 변환. cell × dataset 별 row 가 이 dict.

- [ ] **Step 1: 테스트 추가**

`tests/backtests/multiverse/test_macd_cross_mv_common.py` 끝에 추가:
```python
import pandas as pd

from backtests.multiverse.macd_cross_mv_common import build_cell_kpis


def _fake_trades(pnls):
    return [{"pnl": p, "stock_code": f"S{i:03d}"} for i, p in enumerate(pnls)]


def test_build_cell_kpis_with_trades():
    equity = pd.Series([10_000_000, 10_050_000, 10_020_000, 10_100_000, 10_080_000])
    trades = _fake_trades([50_000, -30_000, 80_000, -20_000])
    kpis = build_cell_kpis(equity=equity, trades=trades, trading_days=20)
    # 필수 키 존재
    assert {"calmar", "return", "mdd", "trades", "win_rate",
            "top1_share", "max_consec_loss", "monthly_trades"} <= kpis.keys()
    assert kpis["trades"] == 4
    assert kpis["win_rate"] == 0.5
    assert abs(kpis["return"] - 0.008) < 1e-6  # 10080000/10000000 - 1
    # monthly_trades = trades * 21 / trading_days = 4 * 21 / 20 = 4.2
    assert abs(kpis["monthly_trades"] - 4.2) < 1e-9


def test_build_cell_kpis_no_trades():
    equity = pd.Series([10_000_000, 10_000_000])
    kpis = build_cell_kpis(equity=equity, trades=[], trading_days=10)
    assert kpis["trades"] == 0
    assert kpis["win_rate"] == 0.0
    assert kpis["top1_share"] == 0.0
    assert kpis["max_consec_loss"] == 0
    assert kpis["return"] == 0.0
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py::test_build_cell_kpis_with_trades -v
```
Expected: FAIL with `ImportError: cannot import name 'build_cell_kpis'`

- [ ] **Step 3: 구현**

`backtests/multiverse/macd_cross_mv_common.py` 끝에 추가:
```python
from dataclasses import dataclass, field
from typing import Dict, List

from backtests.common.metrics import (
    compute_calmar, compute_max_drawdown, compute_win_rate,
)


@dataclass
class Dataset:
    """단일 평가 dataset — fold1/fold2/fold3/oos."""
    name: str
    minute_start: str
    minute_end: str
    daily_start: str
    minute_by_code: Dict[str, "pd.DataFrame"] = field(default_factory=dict)
    daily_by_code: Dict[str, "pd.DataFrame"] = field(default_factory=dict)
    universe: List[str] = field(default_factory=list)


def build_cell_kpis(
    equity: pd.Series,
    trades: List[Dict],
    trading_days: int,
) -> Dict[str, float]:
    """단일 cell × dataset 평가 결과 → KPI dict.

    Args:
        equity: 매 bar 의 cm.available_cash + 보유포지션 가치 시계열.
        trades: BacktestResult.trades.
        trading_days: dataset 의 영업일수 (monthly_trades 계산용).

    Returns:
        {calmar, return, mdd, trades, win_rate, top1_share, max_consec_loss, monthly_trades}
    """
    pnl_series = pd.Series([t["pnl"] for t in trades]) if trades else pd.Series(dtype=float)

    if len(equity) >= 2:
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    else:
        total_return = 0.0

    return {
        "calmar": compute_calmar(equity, trading_days),
        "return": total_return,
        "mdd": compute_max_drawdown(equity),
        "trades": int(len(pnl_series)),
        "win_rate": compute_win_rate(pnl_series),
        "top1_share": compute_top1_share(pnl_series),
        "max_consec_loss": compute_max_consec_loss(pnl_series.tolist()),
        "monthly_trades": (
            float(len(pnl_series) * 21 / trading_days)
            if trading_days > 0 else 0.0
        ),
    }
```

`pd` import 가 파일 상단에 있는지 확인 (Task 1 에서 추가됨).

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py -v
```
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/backtests/multiverse/test_macd_cross_mv_common.py backtests/multiverse/macd_cross_mv_common.py
git commit -m "$(cat <<'EOF'
feat(mv): Dataset dataclass + cell KPI builder (8 KPIs)

cell × dataset 평가 결과를 단일 dict 로 정규화. compute_calmar 등
backtests.common.metrics 재사용 + top1_share/max_consec_loss 만 자체 계산.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 4-Dataset 로더

**Files:**
- Modify: `backtests/multiverse/macd_cross_mv_common.py` — `load_all_datasets()` 추가

목적: minute/daily 데이터 1회 로드 후 4 dataset dict 반환. 두 멀티버스가 메모리 공유.

성능: 30 stocks × 14개월 분봉 ~ 수 GB. 한 번 로드 후 dict 분할.

- [ ] **Step 1: 구현 추가** (테스트 없이 — DB I/O 의존, 다음 task 의 smoke 로 확인)

`backtests/multiverse/macd_cross_mv_common.py` 끝에 추가:
```python
from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.multiverse.fold import STAGE2_FOLDS
from backtests.multiverse.universe import select_top_universe


# OOS hold-out 정의 (Stage 2 fold 와 동일 universe 캐시 사용)
OOS_TEST_START = "20260301"
OOS_TEST_END = "20260424"


def _trading_days_count(minute_by_code: Dict[str, pd.DataFrame]) -> int:
    """모든 종목 분봉의 unique trade_date 수 — dataset 의 영업일수 추정."""
    all_dates = set()
    for df in minute_by_code.values():
        if not df.empty:
            all_dates.update(df["trade_date"].unique().tolist())
    return len(all_dates)


def load_all_datasets() -> Dict[str, Dataset]:
    """4 dataset 일괄 로드 — Stage 2 와 동일 universe 사용.

    분봉 1회 광역 로드 (2025-03 ~ 2026-04) 후 dataset 별 슬라이스.
    daily 도 동일 (2025-01 ~ 2026-04, MACD warm-up 충분).

    Returns:
        {"fold1": Dataset, "fold2": Dataset, "fold3": Dataset, "oos": Dataset}
    """
    # 1. universe — Stage 2 캐시 재사용
    universe = select_top_universe(
        fold_train_start="20250301",
        fold_test_end="20260228",
        n_stocks=30,
        min_days_present=120,
    )

    # 2. 광역 로드 (1회)
    minute_start = STAGE2_FOLDS[0].test_start  # 20250901 — fold1 시작
    minute_end = OOS_TEST_END                    # 20260424
    daily_start = "20250101"

    print(f"[load_all_datasets] universe={len(universe)}, "
          f"minute {minute_start}~{minute_end}, daily {daily_start}~{minute_end}")

    minute_df = load_minute_df(universe, minute_start, minute_end)
    daily_df = load_daily_df(universe, daily_start, minute_end)

    # 3. 종목별 dict
    minute_full = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_full = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }

    # 4. dataset 4개 만들기
    datasets: Dict[str, Dataset] = {}
    fold_specs = [
        ("fold1", STAGE2_FOLDS[0].test_start, STAGE2_FOLDS[0].test_end),
        ("fold2", STAGE2_FOLDS[1].test_start, STAGE2_FOLDS[1].test_end),
        ("fold3", STAGE2_FOLDS[2].test_start, STAGE2_FOLDS[2].test_end),
        ("oos", OOS_TEST_START, OOS_TEST_END),
    ]
    for name, start, end in fold_specs:
        m_by = {
            c: minute_full[c][
                (minute_full[c]["trade_date"] >= start)
                & (minute_full[c]["trade_date"] <= end)
            ].reset_index(drop=True)
            for c in universe
        }
        # daily 는 warm-up 위해 dataset 시작일 이전 모두 포함
        d_by = {
            c: daily_full[c][daily_full[c]["trade_date"] <= end].reset_index(drop=True)
            for c in universe
        }
        nonempty = [c for c in universe if len(m_by[c]) > 0]
        datasets[name] = Dataset(
            name=name,
            minute_start=start, minute_end=end,
            daily_start=daily_start,
            minute_by_code={c: m_by[c] for c in nonempty},
            daily_by_code={c: d_by[c] for c in nonempty},
            universe=nonempty,
        )
        print(f"  {name}: {start}~{end}, "
              f"{len(nonempty)}/{len(universe)} stocks, "
              f"{_trading_days_count(m_by)} trading days")

    return datasets
```

- [ ] **Step 2: 스모크 검증 (수동)**

```bash
python -c "from backtests.multiverse.macd_cross_mv_common import load_all_datasets; ds = load_all_datasets(); print({k: len(v.universe) for k, v in ds.items()})"
```
Expected: 출력 `{'fold1': N, 'fold2': N, 'fold3': N, 'oos': N}` — 각 N 은 ~30 (휴장으로 빠진 종목 제외 가능). 에러 없으면 통과. 30~50 초 소요 (DB I/O).

- [ ] **Step 3: Commit**

```bash
git add backtests/multiverse/macd_cross_mv_common.py
git commit -m "$(cat <<'EOF'
feat(mv): 4-dataset 일괄 로더 (fold1/fold2/fold3/oos)

minute/daily 광역 1회 로드 후 dataset 별 슬라이스. Stage 2 universe
캐시 재사용으로 일관성 보장.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Cell evaluator (engine + KPI 통합)

**Files:**
- Modify: `backtests/multiverse/macd_cross_mv_common.py` — `evaluate_cell` 추가
- Modify: `tests/backtests/multiverse/test_macd_cross_mv_common.py` — synthetic dataset 으로 evaluate_cell 통합 테스트

- [ ] **Step 1: 테스트 추가**

`tests/backtests/multiverse/test_macd_cross_mv_common.py` 끝에 추가:
```python
import pandas as pd
import pytest

from backtests.multiverse.macd_cross_mv_common import (
    Dataset, evaluate_cell,
)
from backtests.strategies.macd_cross import MACDCrossStrategy


def _make_flat_minute(stock, dates, n_bars_per_day=390, base_price=10000.0):
    rows = []
    for td in dates:
        for i in range(n_bars_per_day):
            hh = 9 + i // 60
            mm = i % 60
            rows.append({
                "stock_code": stock, "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": base_price, "high": base_price * 1.001,
                "low": base_price * 0.999, "close": base_price,
                "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_flat_daily(stock, dates, base_price=10000.0):
    return pd.DataFrame([{
        "stock_code": stock, "trade_date": d,
        "open": base_price, "high": base_price,
        "low": base_price, "close": base_price, "volume": 100000.0,
    } for d in dates])


def test_evaluate_cell_returns_kpi_dict():
    """평탄 시세 (no signal) → 0 trades 시 KPI dict 정상 반환."""
    dates = [f"2026010{i+1}" for i in range(5)]  # 5 영업일
    minute = _make_flat_minute("TEST", dates)
    daily_dates = [f"202512{i+1:02d}" for i in range(20)] + dates
    daily = _make_flat_daily("TEST", daily_dates)
    ds = Dataset(
        name="synth",
        minute_start=dates[0], minute_end=dates[-1],
        daily_start=daily_dates[0],
        minute_by_code={"TEST": minute},
        daily_by_code={"TEST": daily},
        universe=["TEST"],
    )
    strat = MACDCrossStrategy()
    kpis = evaluate_cell(strategy=strat, dataset=ds, initial_capital=10_000_000)
    assert kpis["trades"] == 0
    assert kpis["return"] == 0.0
    assert kpis["mdd"] == 0.0
    # 모든 KPI 필드 존재
    assert {"calmar", "return", "mdd", "trades", "win_rate",
            "top1_share", "max_consec_loss", "monthly_trades"} <= kpis.keys()
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py::test_evaluate_cell_returns_kpi_dict -v
```
Expected: FAIL — `evaluate_cell` 미정의

- [ ] **Step 3: 구현**

`backtests/multiverse/macd_cross_mv_common.py` 끝에 추가:
```python
from backtests.common.engine import BacktestEngine
from backtests.strategies.base import StrategyBase


def evaluate_cell(
    strategy: StrategyBase,
    dataset: Dataset,
    initial_capital: float = 10_000_000,
) -> Dict[str, float]:
    """단일 cell × dataset 평가. engine 실행 + KPI 빌드.

    Returns:
        build_cell_kpis 와 동일 dict.
    """
    eng = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        universe=dataset.universe,
        minute_df_by_code=dataset.minute_df_by_code if False else dataset.minute_by_code,
        daily_df_by_code=dataset.daily_by_code,
    )
    result = eng.run()
    trading_days = _trading_days_count(dataset.minute_by_code)
    return build_cell_kpis(
        equity=result.equity_curve,
        trades=result.trades,
        trading_days=trading_days,
    )
```

(주의: `minute_df_by_code` 필드명은 `Dataset.minute_by_code` — 위 코드의 ternary `if False` 는 단순 파라미터 매핑 클러터. **수정 — 한 줄로**:)

```python
    eng = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        universe=dataset.universe,
        minute_df_by_code=dataset.minute_by_code,
        daily_df_by_code=dataset.daily_by_code,
    )
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/backtests/multiverse/test_macd_cross_mv_common.py -v
```
Expected: PASS (전체 12 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/backtests/multiverse/test_macd_cross_mv_common.py backtests/multiverse/macd_cross_mv_common.py
git commit -m "$(cat <<'EOF'
feat(mv): cell evaluator — engine 실행 + KPI 통합

evaluate_cell(strategy, dataset) → KPI dict. 두 멀티버스 러너에서 동일 호출.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Wrapper baseline (overlay 모두 off → base 와 동일 거동)

**Files:**
- Create: `backtests/strategies/macd_cross_exit_overlay.py`
- Create: `tests/backtests/strategies/__init__.py` (없으면)
- Create: `tests/backtests/strategies/test_macd_cross_exit_overlay.py`
- Modify: `docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md` — fill 컨벤션 보강

- [ ] **Step 1: spec 보강 (사전 정리)**

`docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md` §4.3 에서:
```
- **stop_loss_pct (SL)**: 보유 중 분봉 `low ≤ entry_price × (1 - sl_pct)` 도달 시, 그 분봉 **종가** 로 청산. `reason="sl"`.
- **take_profit_pct (TP)**: 보유 중 분봉 `high ≥ entry_price × (1 + tp_pct)` 도달 시, 그 분봉 **종가** 로 청산. `reason="tp"`.
```
다음으로 교체:
```
- **stop_loss_pct (SL)**: 보유 중 분봉 `low ≤ entry_price × (1 - sl_pct)` 도달 시 ExitOrder(reason="sl") 발동. 실제 fill 가격은 엔진의 `next_fill_index(t)` next-bar open + 슬리피지 (`backtests/common/engine.py` 컨벤션, 기존 hold_limit 와 동일).
- **take_profit_pct (TP)**: 보유 중 분봉 `high ≥ entry_price × (1 + tp_pct)` 도달 시 ExitOrder(reason="tp") 발동. fill 컨벤션 SL 동일.
```

- [ ] **Step 2: __init__.py 생성 (없으면)**

```bash
if (-not (Test-Path tests/backtests/strategies/__init__.py)) { New-Item -ItemType File -Path tests/backtests/strategies/__init__.py -Force }
```

- [ ] **Step 3: baseline 동등성 테스트 작성**

`tests/backtests/strategies/test_macd_cross_exit_overlay.py`:
```python
"""macd_cross exit overlay wrapper 단위 테스트."""
import pandas as pd
import pytest

from backtests.strategies.base import Position
from backtests.strategies.macd_cross import MACDCrossStrategy
from backtests.strategies.macd_cross_exit_overlay import MACDCrossExitOverlayStrategy


def _make_minute_df(trade_dates, close_per_day=None, base=10000.0):
    """390 bars × N day. close_per_day[i] 가 None 이면 base 사용."""
    rows = []
    for d_idx, td in enumerate(trade_dates):
        c = (close_per_day[d_idx] if close_per_day else base)
        for i in range(390):
            hh = 9 + i // 60
            mm = i % 60
            rows.append({
                "stock_code": "TEST", "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": c, "high": c * 1.001, "low": c * 0.999,
                "close": c, "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def _make_daily_df(closes, dates):
    return pd.DataFrame([{
        "stock_code": "TEST", "trade_date": d,
        "open": c, "high": c * 1.005, "low": c * 0.995,
        "close": c, "volume": 100000.0,
    } for d, c in zip(dates, closes)])


def test_no_overlay_matches_base_exit():
    """모든 overlay off → base 와 동일하게 hold_days=2 까지 None 반환."""
    minute = _make_minute_df(["20260331", "20260401", "20260402"])
    closes = [10000.0] * 60
    dates = [f"2026{(1 + i // 30):02d}{(i % 30) + 1:02d}" for i in range(57)]
    daily = _make_daily_df(closes, dates + ["20260331", "20260401", "20260402"])

    base = MACDCrossStrategy()
    wrap = MACDCrossExitOverlayStrategy(sl_pct=None, tp_pct=None, intraday_reversal=False)
    base.prepare_features(minute, daily)
    wrap.prepare_features(minute, daily)

    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    feats_dummy = pd.DataFrame()
    # D+1 동안 (bar 390~779) 둘 다 None
    assert base.exit_signal(pos, feats_dummy, bar_idx=500, current_price=10000.0) is None
    assert wrap.exit_signal(pos, feats_dummy, bar_idx=500, current_price=10000.0) is None
    # D+2 (bar 780+) 둘 다 hold_limit
    base_out = base.exit_signal(pos, feats_dummy, bar_idx=780, current_price=10000.0)
    wrap_out = wrap.exit_signal(pos, feats_dummy, bar_idx=780, current_price=10000.0)
    assert base_out.reason == "hold_limit"
    assert wrap_out.reason == "hold_limit"
```

- [ ] **Step 4: 실패 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py -v
```
Expected: FAIL — `MACDCrossExitOverlayStrategy` 미정의

- [ ] **Step 5: 구현**

`backtests/strategies/macd_cross_exit_overlay.py`:
```python
"""macd_cross 에 SL/TP/intraday MACD reversal exit overlay 를 얹은 백테스트 wrapper.

본체 backtests/strategies/macd_cross.py 는 라이브 동등성 보호 위해 미수정.
실제 fill 가격은 engine 의 next_fill_index(t) next-bar open 모델을 따른다
(spec § 4.3, 기존 hold_limit 와 동일).
"""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.common.trading_day import count_trading_days_between
from backtests.strategies.base import ExitOrder, Position
from backtests.strategies.macd_cross import MACDCrossStrategy
from core.strategies.macd_cross_signal import compute_macd_histogram_series


class MACDCrossExitOverlayStrategy(MACDCrossStrategy):
    """SL / TP / intraday MACD reversal exit overlay.

    Args:
        sl_pct: 0~1 fractional. None 이면 SL 비활성.
        tp_pct: 0~1 fractional. None 이면 TP 비활성.
        intraday_reversal: True 면 D+1 부터 매일 last bar 에서 today_hist<0 시 청산.
    """
    name = "macd_cross_exit_overlay"

    def __init__(
        self,
        sl_pct: Optional[float] = None,
        tp_pct: Optional[float] = None,
        intraday_reversal: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.intraday_reversal = intraday_reversal

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        feat = super().prepare_features(df_minute, df_daily).copy()
        if df_minute.empty:
            return feat
        # SL/TP 용 OHLC 캐시
        feat["high"] = df_minute["high"].astype(float).values
        feat["low"] = df_minute["low"].astype(float).values
        feat["trade_date"] = df_minute["trade_date"].astype(str).values
        # intraday reversal 용 today_hist (no shift)
        if self.intraday_reversal:
            today_hist_map = self._build_today_hist_map(df_daily)
            feat["today_hist"] = (
                df_minute["trade_date"].astype(str).map(today_hist_map).values
            )
        return feat

    def _build_today_hist_map(self, df_daily: pd.DataFrame):
        if df_daily is None or df_daily.empty:
            return {}
        d = df_daily.sort_values("trade_date").copy()
        hist = compute_macd_histogram_series(
            d, fast=self.fast_period, slow=self.slow_period, signal=self.signal_period
        )
        # NO shift — 오늘 hist 값
        return dict(zip(d["trade_date"].astype(str), hist))

    def exit_signal(
        self,
        position: Position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        # 모든 overlay off 시 base 동일
        if (self.sl_pct is None and self.tp_pct is None
                and not self.intraday_reversal):
            return super().exit_signal(position, features, bar_idx, current_price)

        # features 가 비어있으면 (테스트의 dummy DF) base 만 호출
        if features.empty:
            return super().exit_signal(position, features, bar_idx, current_price)

        arr = get_arrays(features)
        if bar_idx >= len(arr.get("high", [])):
            return super().exit_signal(position, features, bar_idx, current_price)

        # === Task 6 에서 SL 추가 ===
        # === Task 7 에서 TP 추가 ===
        # === Task 8 에서 reversal 추가 ===

        return super().exit_signal(position, features, bar_idx, current_price)
```

- [ ] **Step 6: 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py -v
```
Expected: PASS (1 test)

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md tests/backtests/strategies/__init__.py tests/backtests/strategies/test_macd_cross_exit_overlay.py backtests/strategies/macd_cross_exit_overlay.py
git commit -m "$(cat <<'EOF'
feat(strategies): macd_cross exit overlay wrapper 골격 (overlay off=baseline)

본체 macd_cross.py 미수정. wrapper 가 OHLC 캐시 + 향후 SL/TP/reversal
추가 지점 마련. spec §4.3 fill 컨벤션 (next-bar open) 명시.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: SL overlay

**Files:**
- Modify: `backtests/strategies/macd_cross_exit_overlay.py`
- Modify: `tests/backtests/strategies/test_macd_cross_exit_overlay.py`

- [ ] **Step 1: 테스트 추가**

`tests/backtests/strategies/test_macd_cross_exit_overlay.py` 끝에 추가:
```python
def test_sl_triggers_when_low_breaks_threshold():
    """SL=5%, 보유 중 low 가 entry × 0.94 까지 떨어지면 reason='sl'."""
    minute = _make_minute_df(["20260331", "20260401"])
    # entry 가격 10000, low 9400 = -6% (5% 깨짐)
    minute.loc[400, "low"] = 9400.0
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])

    s = MACDCrossExitOverlayStrategy(sl_pct=0.05)
    s.prepare_features(minute, daily)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=9500.0)
    assert out is not None
    assert out.reason == "sl"


def test_sl_no_trigger_when_low_above_threshold():
    """SL=5%, low 가 9600 (4% 하락) 이면 미발동."""
    minute = _make_minute_df(["20260331", "20260401"])
    minute.loc[400, "low"] = 9600.0
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])

    s = MACDCrossExitOverlayStrategy(sl_pct=0.05)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=9700.0)
    assert out is None
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py::test_sl_triggers_when_low_breaks_threshold -v
```
Expected: FAIL — wrapper 가 SL 무시 → None 반환 vs expected reason="sl"

- [ ] **Step 3: SL 로직 추가**

`backtests/strategies/macd_cross_exit_overlay.py` 의 `exit_signal` 안 `# === Task 6 에서 SL 추가 ===` 주석 자리에 다음 삽입:
```python
        # SL: low ≤ entry × (1 - sl_pct)
        if self.sl_pct is not None:
            low = float(arr["low"][bar_idx])
            if low <= position.entry_price * (1 - self.sl_pct):
                return ExitOrder(stock_code=position.stock_code, reason="sl")
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/backtests/strategies/test_macd_cross_exit_overlay.py backtests/strategies/macd_cross_exit_overlay.py
git commit -m "$(cat <<'EOF'
feat(strategies): macd_cross exit overlay — SL%

분봉 low 가 entry × (1 - sl_pct) 도달 시 ExitOrder(reason='sl').
hold_limit 보다 우선.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: TP overlay + SL/TP 동시충족 시 SL 우선

**Files:**
- Modify: `backtests/strategies/macd_cross_exit_overlay.py`
- Modify: `tests/backtests/strategies/test_macd_cross_exit_overlay.py`

- [ ] **Step 1: 테스트 추가**

테스트 파일 끝에 추가:
```python
def test_tp_triggers_when_high_breaks_threshold():
    minute = _make_minute_df(["20260331", "20260401"])
    minute.loc[400, "high"] = 10600.0  # +6%
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])
    s = MACDCrossExitOverlayStrategy(tp_pct=0.05)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=10500.0)
    assert out is not None
    assert out.reason == "tp"


def test_sl_takes_priority_over_tp_in_same_bar():
    """한 분봉에서 low/high 둘 다 트리거 시 SL 우선 (보수적)."""
    minute = _make_minute_df(["20260331", "20260401"])
    minute.loc[400, "high"] = 10600.0  # +6% TP=5% 트리거
    minute.loc[400, "low"] = 9300.0    # -7% SL=5% 트리거
    daily = _make_daily_df([10000.0] * 30,
                           [f"202602{i+1:02d}" for i in range(28)] + ["20260331", "20260401"])
    s = MACDCrossExitOverlayStrategy(sl_pct=0.05, tp_pct=0.05)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    out = s.exit_signal(pos, feats, bar_idx=400, current_price=10000.0)
    assert out is not None
    assert out.reason == "sl"  # SL 우선
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py -v
```
Expected: 2 새 테스트 FAIL (TP 미구현 → None)

- [ ] **Step 3: TP 로직 추가**

`backtests/strategies/macd_cross_exit_overlay.py` 의 `exit_signal` 안 SL 블록 바로 뒤 (`# === Task 7 에서 TP 추가 ===` 자리) 에 삽입:
```python
        # TP: high ≥ entry × (1 + tp_pct). SL 우선이므로 SL 블록 뒤.
        if self.tp_pct is not None:
            high = float(arr["high"][bar_idx])
            if high >= position.entry_price * (1 + self.tp_pct):
                return ExitOrder(stock_code=position.stock_code, reason="tp")
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/backtests/strategies/test_macd_cross_exit_overlay.py backtests/strategies/macd_cross_exit_overlay.py
git commit -m "$(cat <<'EOF'
feat(strategies): macd_cross exit overlay — TP% (SL 우선)

분봉 high 가 entry × (1 + tp_pct) 도달 시 ExitOrder(reason='tp').
한 분봉 동시 충족 시 SL 우선 (보수적, spec §4.3).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Intraday MACD reversal exit (D+1 부터 last bar 에서 today_hist<0 시)

**Files:**
- Modify: `backtests/strategies/macd_cross_exit_overlay.py`
- Modify: `tests/backtests/strategies/test_macd_cross_exit_overlay.py`

- [ ] **Step 1: 테스트 추가**

테스트 파일 끝에 추가:
```python
def test_intraday_reversal_at_last_bar_of_d_plus_1():
    """D+1 의 last bar 에서 today_hist<0 → reason='macd_reversal'."""
    # 일봉을 일부러 하락시켜 D+1 의 hist 가 음수가 되도록
    minute = _make_minute_df(["20260331", "20260401"])
    closes = [10000.0] * 50 + [9000.0] * 5  # 끝에 급락 → D+1 hist 음수 가능
    dates = [f"2026{(2 + (i // 30)):02d}{(i % 30) + 1:02d}" for i in range(50)]
    dates += ["20260331", "20260401"] + [f"202604{i+2:02d}" for i in range(3)]
    # closes 길이 55, dates 55 매핑
    daily = _make_daily_df(closes, dates)

    s = MACDCrossExitOverlayStrategy(intraday_reversal=True,
                                      fast_period=3, slow_period=6, signal_period=2)
    feats = s.prepare_features(minute, daily)

    # D+1 의 last bar = bar_idx 779 (390 + 389)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")

    # today_hist 가 음수인지 사전 확인 (테스트 진단용)
    today_hist_at_d1 = feats["today_hist"].iloc[779]
    assert today_hist_at_d1 < 0, f"테스트 setup 실패: today_hist={today_hist_at_d1}"

    out = s.exit_signal(pos, feats, bar_idx=779, current_price=9000.0)
    assert out is not None
    assert out.reason == "macd_reversal"


def test_intraday_reversal_skipped_on_entry_day():
    """진입일 (D) last bar 에서 today_hist<0 이어도 미발동 — D+1 부터만."""
    minute = _make_minute_df(["20260331", "20260401"])
    closes = [10000.0] * 50 + [9000.0] * 5
    dates = [f"2026{(2 + (i // 30)):02d}{(i % 30) + 1:02d}" for i in range(50)]
    dates += ["20260331", "20260401"] + [f"202604{i+2:02d}" for i in range(3)]
    daily = _make_daily_df(closes, dates)

    s = MACDCrossExitOverlayStrategy(intraday_reversal=True,
                                      fast_period=3, slow_period=6, signal_period=2)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    # D 의 last bar = 389
    out = s.exit_signal(pos, feats, bar_idx=389, current_price=10000.0)
    assert out is None  # 진입일에는 미발동


def test_intraday_reversal_skipped_mid_day():
    """D+1 의 mid-day bar 에서는 미발동 — last bar of day 만 평가."""
    minute = _make_minute_df(["20260331", "20260401"])
    closes = [10000.0] * 50 + [9000.0] * 5
    dates = [f"2026{(2 + (i // 30)):02d}{(i % 30) + 1:02d}" for i in range(50)]
    dates += ["20260331", "20260401"] + [f"202604{i+2:02d}" for i in range(3)]
    daily = _make_daily_df(closes, dates)

    s = MACDCrossExitOverlayStrategy(intraday_reversal=True,
                                      fast_period=3, slow_period=6, signal_period=2)
    feats = s.prepare_features(minute, daily)
    pos = Position(stock_code="TEST", entry_bar_idx=355, entry_price=10000.0,
                   quantity=10, entry_date="20260331")
    # D+1 의 mid bar = 500 (last bar 779 가 아님)
    out = s.exit_signal(pos, feats, bar_idx=500, current_price=9000.0)
    assert out is None
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py -v
```
Expected: 3 새 테스트 FAIL — reversal 로직 없음

- [ ] **Step 3: reversal 로직 추가**

`backtests/strategies/macd_cross_exit_overlay.py` 의 `exit_signal` 안 TP 블록 바로 뒤 (`# === Task 8 에서 reversal 추가 ===` 자리) 에 삽입:
```python
        # intraday MACD reversal: D+1 부터 each day's last bar 에서 today_hist<0 시
        if self.intraday_reversal and "today_hist" in arr:
            trade_date_arr = arr["trade_date"]
            today_hist_arr = arr["today_hist"]
            current_date = trade_date_arr[bar_idx]
            is_last_bar_of_day = (
                bar_idx == len(trade_date_arr) - 1
                or trade_date_arr[bar_idx + 1] != current_date
            )
            if is_last_bar_of_day and self._last_df_minute is not None:
                days_held = count_trading_days_between(
                    self._last_df_minute,
                    from_idx=position.entry_bar_idx, to_idx=bar_idx,
                )
                if days_held >= 1:
                    h = today_hist_arr[bar_idx]
                    if not pd.isna(h) and h < 0:
                        return ExitOrder(
                            stock_code=position.stock_code,
                            reason="macd_reversal",
                        )
```

- [ ] **Step 4: 통과 확인**

```bash
python -m pytest tests/backtests/strategies/test_macd_cross_exit_overlay.py -v
```
Expected: PASS (8 tests). 만약 `today_hist` 가 0 또는 양수로 나와 setup 실패 시, closes 를 더 급락 (예: `[10000.0] * 50 + [7000.0] * 5`) 하여 hist 충분히 음수화.

- [ ] **Step 5: 전체 회귀**

```bash
python -m pytest tests/backtests/ -v
```
Expected: PASS — 기존 전체 테스트 + 새 테스트.

- [ ] **Step 6: Commit**

```bash
git add tests/backtests/strategies/test_macd_cross_exit_overlay.py backtests/strategies/macd_cross_exit_overlay.py
git commit -m "$(cat <<'EOF'
feat(strategies): macd_cross exit overlay — intraday MACD reversal

D+1 부터 매일 last bar 에서 today_hist<0 시 ExitOrder(reason='macd_reversal').
진입일 D 는 partial daily 라 평가 제외 (spec §4.3).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: MV-A 러너 (파라미터 fine grid)

**Files:**
- Create: `backtests/multiverse/macd_cross_param_grid.py`

목적: 360 cell × 4 dataset 평가 → `cells.csv` 생성.

- [ ] **Step 1: 러너 작성**

`backtests/multiverse/macd_cross_param_grid.py`:
```python
"""MV-A: macd_cross 파라미터 fine grid 멀티버스.

Spec docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md §3.

각 cell × dataset 평가 결과를 cells.csv 에 long-format 으로 저장.
heatmap PNG 와 summary.md 는 plot_macd_cross_mv.py 가 생성.
"""
import csv
import itertools
import time
from pathlib import Path
from typing import Dict, List

from backtests.multiverse.macd_cross_mv_common import (
    Dataset, evaluate_cell, load_all_datasets,
)
from backtests.strategies.macd_cross import MACDCrossStrategy


REPORT_DIR = Path("backtests/reports/macd_cross_mv/param_grid")


PARAM_GRID = {
    "fast_period": [8, 10, 12, 14, 16],
    "slow_period": [24, 28, 32, 34, 36, 40],
    "signal_period": [9, 10, 11, 12],
    "entry_hhmm_min": [1430, 1440, 1450],
}


def _enumerate_cells():
    keys = list(PARAM_GRID.keys())
    for combo in itertools.product(*[PARAM_GRID[k] for k in keys]):
        params = dict(zip(keys, combo))
        if params["slow_period"] <= params["fast_period"]:
            continue
        yield params


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("[MV-A] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    cells = list(_enumerate_cells())
    print(f"[MV-A] {len(cells)} cells × {len(datasets)} datasets "
          f"= {len(cells) * len(datasets)} evaluations")

    out_path = REPORT_DIR / "cells.csv"
    fieldnames = [
        "fast_period", "slow_period", "signal_period", "entry_hhmm_min",
        "dataset", "calmar", "return", "mdd", "trades",
        "win_rate", "top1_share", "max_consec_loss", "monthly_trades",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        t0 = time.time()
        for ci, params in enumerate(cells, 1):
            for ds_name, ds in datasets.items():
                strategy = MACDCrossStrategy(**params)
                kpis = evaluate_cell(strategy=strategy, dataset=ds)
                row = {**params, "dataset": ds_name, **kpis}
                writer.writerow(row)
            if ci % 20 == 0 or ci == len(cells):
                elapsed = time.time() - t0
                print(f"  cell {ci}/{len(cells)} ({elapsed:.0f}s elapsed, "
                      f"{elapsed / ci * (len(cells) - ci):.0f}s eta)")

    print(f"[MV-A] saved → {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 작은 스모크 (5 cell × 1 dataset 임시)**

cells 와 datasets 를 각각 줄여 빠른 검증. 일회성이므로 코드 임시 수정 후 복원.

```bash
python -c "
from backtests.multiverse.macd_cross_param_grid import _enumerate_cells
cells = list(_enumerate_cells())
print(f'cell count = {len(cells)}')
print('first 3:', cells[:3])
print('last 3:', cells[-3:])
"
```
Expected: cell count = 320 (slow > fast 필터 후 — 5×6×4×3 - 무효 조합).

실제 검증: 5 cell + 1 dataset 만 돌려보기:
```bash
python -c "
from backtests.multiverse.macd_cross_mv_common import load_all_datasets, evaluate_cell
from backtests.strategies.macd_cross import MACDCrossStrategy
ds = load_all_datasets()['fold1']
for fast in [10, 12, 14]:
    for slow in [26, 34]:
        s = MACDCrossStrategy(fast_period=fast, slow_period=slow)
        kpis = evaluate_cell(s, ds)
        print(f'fast={fast} slow={slow}: trades={kpis[\"trades\"]}, return={kpis[\"return\"]:.3f}, calmar={kpis[\"calmar\"]:.2f}')
"
```
Expected: 6 줄 출력. trades > 0 일 것 (fold1 에 신호 존재 확인). 에러 없으면 통과.

- [ ] **Step 3: Commit**

```bash
git add backtests/multiverse/macd_cross_param_grid.py
git commit -m "$(cat <<'EOF'
feat(mv): MV-A 파라미터 fine grid 러너 (360 cell × 4 dataset)

cells.csv long-format 출력. slow_period > fast_period 가드 적용으로
320 유효 cell. heatmap/summary 는 별도 plotter 가 처리.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: MV-B 러너 (exit overlay grid)

**Files:**
- Create: `backtests/multiverse/macd_cross_exit_overlay_mv.py`

목적: 24 cell × 4 dataset → `exit_overlay/cells.csv`.

- [ ] **Step 1: 러너 작성**

`backtests/multiverse/macd_cross_exit_overlay_mv.py`:
```python
"""MV-B: macd_cross exit overlay 멀티버스.

Spec docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md §4.

best params 고정 (fast=14, slow=34, signal=12, entry=1430). SL × TP × reversal
24 cell 평가. exit_reason 분포까지 기록.
"""
import csv
import itertools
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_exit_overlay import MACDCrossExitOverlayStrategy


REPORT_DIR = Path("backtests/reports/macd_cross_mv/exit_overlay")
BEST_PARAMS_PATH = Path("backtests/reports/stage2/macd_cross_best.json")


SL_GRID = [None, 0.03, 0.05, 0.07]
TP_GRID = [None, 0.05, 0.10]
REVERSAL_GRID = [False, True]


def _exit_reason_dist(trades) -> Dict[str, float]:
    if not trades:
        return {"hold_limit": 0.0, "sl": 0.0, "tp": 0.0, "macd_reversal": 0.0, "eod_forced": 0.0}
    cnt = Counter(t["reason"] for t in trades)
    total = len(trades)
    return {k: cnt.get(k, 0) / total
            for k in ("hold_limit", "sl", "tp", "macd_reversal", "eod_forced")}


def _evaluate_with_reasons(strategy, dataset, initial_capital=10_000_000):
    """evaluate_cell 과 동일하지만 exit_reason 분포 추가 반환."""
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
    kpis.update(_exit_reason_dist(result.trades))
    return kpis


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    best = json.loads(BEST_PARAMS_PATH.read_text(encoding="utf-8"))["best_params"]
    print(f"[MV-B] best params = {best}")

    print("[MV-B] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()

    cells = list(itertools.product(SL_GRID, TP_GRID, REVERSAL_GRID))
    print(f"[MV-B] {len(cells)} cells × {len(datasets)} datasets "
          f"= {len(cells) * len(datasets)} evaluations")

    out_path = REPORT_DIR / "cells.csv"
    fieldnames = [
        "sl_pct", "tp_pct", "intraday_reversal",
        "dataset", "calmar", "return", "mdd", "trades",
        "win_rate", "top1_share", "max_consec_loss", "monthly_trades",
        "reason_hold_limit", "reason_sl", "reason_tp",
        "reason_macd_reversal", "reason_eod_forced",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        t0 = time.time()
        for ci, (sl, tp, rev) in enumerate(cells, 1):
            for ds_name, ds in datasets.items():
                strat = MACDCrossExitOverlayStrategy(
                    sl_pct=sl, tp_pct=tp, intraday_reversal=rev, **best,
                )
                kpis = _evaluate_with_reasons(strat, ds)
                row = {
                    "sl_pct": "off" if sl is None else f"{sl:.2f}",
                    "tp_pct": "off" if tp is None else f"{tp:.2f}",
                    "intraday_reversal": "on" if rev else "off",
                    "dataset": ds_name,
                    **{k: kpis[k] for k in (
                        "calmar", "return", "mdd", "trades", "win_rate",
                        "top1_share", "max_consec_loss", "monthly_trades",
                    )},
                    "reason_hold_limit": kpis["hold_limit"],
                    "reason_sl": kpis["sl"],
                    "reason_tp": kpis["tp"],
                    "reason_macd_reversal": kpis["macd_reversal"],
                    "reason_eod_forced": kpis["eod_forced"],
                }
                writer.writerow(row)
            elapsed = time.time() - t0
            print(f"  cell {ci}/{len(cells)} sl={sl} tp={tp} rev={rev} "
                  f"({elapsed:.0f}s)")

    print(f"[MV-B] saved → {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 1 cell 스모크**

```bash
python -c "
import json
from backtests.multiverse.macd_cross_mv_common import load_all_datasets
from backtests.multiverse.macd_cross_exit_overlay_mv import _evaluate_with_reasons
from backtests.strategies.macd_cross_exit_overlay import MACDCrossExitOverlayStrategy
best = json.loads(open('backtests/reports/stage2/macd_cross_best.json').read())['best_params']
ds = load_all_datasets()['fold1']
s = MACDCrossExitOverlayStrategy(sl_pct=0.05, tp_pct=None, intraday_reversal=False, **best)
print(_evaluate_with_reasons(s, ds))
"
```
Expected: dict 출력, 에러 없음. trades 수 보고 SL 발동 비율 확인.

- [ ] **Step 3: Commit**

```bash
git add backtests/multiverse/macd_cross_exit_overlay_mv.py
git commit -m "$(cat <<'EOF'
feat(mv): MV-B exit overlay 러너 (24 cell × 4 dataset)

SL{off,3%,5%,7%} × TP{off,5%,10%} × reversal{off,on}. exit_reason
분포까지 cells.csv 에 기록 (overlay 발동률 분석용).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Heatmap PNG 플로터

**Files:**
- Create: `backtests/multiverse/plot_macd_cross_mv.py`

목적: cells.csv → heatmap PNG 다수 + summary.md.

- [ ] **Step 1: 플로터 작성**

`backtests/multiverse/plot_macd_cross_mv.py`:
```python
"""MV-A/B cells.csv → heatmap PNG + summary.md 생성.

MV-A: 축 페어별 marginal 평균 Calmar heatmap 6장 (각 3 subplot: 4ds avg / fold2 / oos).
MV-B: SL × TP heatmap × {reversal off, reversal on} × {calmar, return, mdd, win_rate} = 8장.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PG_DIR = Path("backtests/reports/macd_cross_mv/param_grid")
EO_DIR = Path("backtests/reports/macd_cross_mv/exit_overlay")


def _heatmap(ax, df, x_col, y_col, value_col, title):
    pivot = df.pivot_table(
        index=y_col, columns=x_col, values=value_col, aggfunc="mean",
    )
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn",
                   origin="lower")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    ax.set_title(title)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                        fontsize=7, color="black")
    plt.colorbar(im, ax=ax, fraction=0.04)


def plot_param_grid():
    df = pd.read_csv(PG_DIR / "cells.csv")
    out = PG_DIR / "heatmaps"
    out.mkdir(exist_ok=True)
    pairs = [
        ("fast_period", "slow_period"),
        ("fast_period", "signal_period"),
        ("fast_period", "entry_hhmm_min"),
        ("slow_period", "signal_period"),
        ("slow_period", "entry_hhmm_min"),
        ("signal_period", "entry_hhmm_min"),
    ]
    for x, y in pairs:
        fig, axes = plt.subplots(1, 3, figsize=(18, 5))
        # (a) 4 dataset 평균
        avg = df.groupby([x, y, "dataset"]).agg(calmar=("calmar", "mean")).reset_index()
        avg_all = avg.groupby([x, y]).agg(calmar=("calmar", "mean")).reset_index()
        _heatmap(axes[0], avg_all, x, y, "calmar", "4 dataset avg")
        # (b) Fold 2 only
        f2 = df[df["dataset"] == "fold2"]
        _heatmap(axes[1], f2, x, y, "calmar", "Fold 2 (fail fold)")
        # (c) OOS only
        oos = df[df["dataset"] == "oos"]
        _heatmap(axes[2], oos, x, y, "calmar", "OOS hold-out")
        fig.suptitle(f"Calmar heatmap: {x} × {y}")
        fig.tight_layout()
        fig.savefig(out / f"{x}_{y}.png", dpi=110)
        plt.close(fig)
    print(f"[plot] param_grid heatmaps → {out}")


def plot_exit_overlay():
    df = pd.read_csv(EO_DIR / "cells.csv")
    out = EO_DIR / "heatmaps"
    out.mkdir(exist_ok=True)
    metrics = [("calmar", "Calmar"), ("return", "Return"),
               ("mdd", "MDD"), ("win_rate", "Win rate")]
    for rev_value, rev_label in [("off", "reversal_off"), ("on", "reversal_on")]:
        sub = df[df["intraday_reversal"] == rev_value]
        for metric, ml in metrics:
            avg = sub.groupby(["sl_pct", "tp_pct"]).agg({metric: "mean"}).reset_index()
            fig, ax = plt.subplots(figsize=(7, 5))
            _heatmap(ax, avg, "tp_pct", "sl_pct", metric,
                     f"{ml} — {rev_label} (4 dataset avg)")
            fig.tight_layout()
            fig.savefig(out / f"{rev_label}_{metric}.png", dpi=110)
            plt.close(fig)
    print(f"[plot] exit_overlay heatmaps → {out}")


def main():
    if (PG_DIR / "cells.csv").exists():
        plot_param_grid()
    if (EO_DIR / "cells.csv").exists():
        plot_exit_overlay()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: cells.csv 가 있는 상태에서 스모크**

(Task 9, 10 결과가 있을 때만 실행 가능. 만약 없으면 더미 cells.csv 만들어 검증:)
```bash
python -c "
import pandas as pd
from pathlib import Path
Path('backtests/reports/macd_cross_mv/param_grid').mkdir(parents=True, exist_ok=True)
rows = []
for f in [10, 12, 14]:
    for s in [26, 34]:
        for sig in [9, 11]:
            for e in [1430, 1450]:
                for ds in ['fold1','fold2','fold3','oos']:
                    rows.append({'fast_period': f, 'slow_period': s, 'signal_period': sig,
                                 'entry_hhmm_min': e, 'dataset': ds, 'calmar': 50 - f, 'return': 0.1,
                                 'mdd': -0.02, 'trades': 30, 'win_rate': 0.5, 'top1_share': 0.5,
                                 'max_consec_loss': 3, 'monthly_trades': 15})
pd.DataFrame(rows).to_csv('backtests/reports/macd_cross_mv/param_grid/cells.csv', index=False)
print('wrote dummy cells.csv')
"
python -m backtests.multiverse.plot_macd_cross_mv
```
Expected: 6 PNG 생성, 에러 없음. 검증 후 더미 cells.csv 삭제.

```bash
Remove-Item backtests/reports/macd_cross_mv/param_grid/cells.csv
Remove-Item -Recurse backtests/reports/macd_cross_mv/param_grid/heatmaps
```

- [ ] **Step 3: Commit**

```bash
git add backtests/multiverse/plot_macd_cross_mv.py
git commit -m "$(cat <<'EOF'
feat(mv): cells.csv → heatmap PNG 플로터 (MV-A 6장 + MV-B 8장)

MV-A 는 축 페어별 3 subplot (4ds avg / fold2 / oos).
MV-B 는 reversal × KPI = 8장.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Summary.md 생성기

**Files:**
- Modify: `backtests/multiverse/plot_macd_cross_mv.py` — `write_summary_*` 함수 추가

목적: cells.csv → spec §3.3 / §4.5 의 summary.md 생성. spec §3.4 / §4.6 핵심 질문 답변까지.

- [ ] **Step 1: 함수 추가**

`backtests/multiverse/plot_macd_cross_mv.py` 끝에 추가 (그리고 `main()` 도 호출하도록 업데이트):
```python
def write_param_grid_summary():
    df = pd.read_csv(PG_DIR / "cells.csv")
    # best cell = Stage 2 best (fast=14, slow=34, signal=12, entry=1430)
    best_mask = (
        (df["fast_period"] == 14) & (df["slow_period"] == 34)
        & (df["signal_period"] == 12) & (df["entry_hhmm_min"] == 1430)
    )
    best_avg = df[best_mask].groupby("dataset")["calmar"].mean().to_dict()

    grid_avg = df.groupby(
        ["fast_period", "slow_period", "signal_period", "entry_hhmm_min"]
    ).agg(
        calmar_avg=("calmar", "mean"),
        return_avg=("return", "mean"),
        mdd_avg=("mdd", "mean"),
        top1_avg=("top1_share", "mean"),
    ).reset_index()

    # plateau: best 주변 (±1 step) cell 중 calmar > 30 비율
    plateau_count = 0
    plateau_total = 0
    for _, row in grid_avg.iterrows():
        if (abs(row["fast_period"] - 14) <= 2
                and abs(row["slow_period"] - 34) <= 4
                and abs(row["signal_period"] - 12) <= 1
                and abs(row["entry_hhmm_min"] - 1430) <= 10):
            plateau_total += 1
            if row["calmar_avg"] > 30:
                plateau_count += 1

    fragility = (grid_avg["top1_avg"] > 0.6).sum()
    total_cells = len(grid_avg)
    fold2_fail = df[(df["dataset"] == "fold2") & (df["calmar"] < 0)]
    fold2_fail_pct = len(fold2_fail) / (df["dataset"] == "fold2").sum() * 100

    out = PG_DIR / "summary.md"
    out.write_text(f"""# MV-A 파라미터 fine grid summary

## Best cell (Stage 2 best: fast=14, slow=34, signal=12, entry=1430)

| dataset | calmar |
|---------|--------|
{chr(10).join(f"| {k} | {v:.2f} |" for k, v in best_avg.items())}

## Plateau 분석 (best ±1 step 주변 cell)

- 인접 cell 수: {plateau_total}
- Calmar > 30 인 cell: {plateau_count} ({plateau_count/max(1,plateau_total)*100:.0f}%)
- 판정: {"plateau (robust)" if plateau_count / max(1, plateau_total) > 0.6 else "절벽 (fragile)"}

## Fragility (top1_share > 60% cell)

- {fragility}/{total_cells} cells ({fragility/total_cells*100:.0f}%)

## Fold 2 fail 분포

- 음 calmar cell 비율: {fold2_fail_pct:.0f}% (전체 cell 중 fold2 에서 fail)
- 판정: {"기간 의존 (대부분 cell fail)" if fold2_fail_pct > 70 else "파라미터 sensitivity (일부만 fail)"}

## 결론 (자동)

자동 텍스트 — 사람이 데이터 보고 보강 필요. heatmaps/ 6장 PNG 와 cells.csv 직접 조회.
""", encoding="utf-8")
    print(f"[summary] {out}")


def write_exit_overlay_summary():
    df = pd.read_csv(EO_DIR / "cells.csv")
    baseline_mask = (
        (df["sl_pct"] == "off") & (df["tp_pct"] == "off")
        & (df["intraday_reversal"] == "off")
    )
    baseline = df[baseline_mask].groupby("dataset").agg({
        "calmar": "mean", "return": "mean", "mdd": "mean",
    }).reset_index()

    cell_avg = df.groupby(["sl_pct", "tp_pct", "intraday_reversal"]).agg(
        calmar=("calmar", "mean"), ret=("return", "mean"),
        mdd=("mdd", "mean"), wr=("win_rate", "mean"),
    ).reset_index()
    baseline_calmar = baseline["calmar"].mean()
    cell_avg["delta_calmar"] = cell_avg["calmar"] - baseline_calmar
    improvers = cell_avg[cell_avg["delta_calmar"] > 0].sort_values(
        "delta_calmar", ascending=False
    ).head(5)

    # Fold 2 MDD 개선
    f2 = df[df["dataset"] == "fold2"].copy()
    base_f2 = f2[(f2["sl_pct"] == "off") & (f2["tp_pct"] == "off")
                 & (f2["intraday_reversal"] == "off")]["mdd"].mean()
    f2_improve = f2[f2["mdd"] > base_f2].copy()
    f2_improve["mdd_delta"] = f2_improve["mdd"] - base_f2

    out = EO_DIR / "summary.md"
    out.write_text(f"""# MV-B exit overlay summary

## Baseline ([off, off, off]) — 4 dataset 평균

| dataset | calmar | return | mdd |
|---------|--------|--------|-----|
{chr(10).join(f"| {row['dataset']} | {row['calmar']:.2f} | {row['return']:.4f} | {row['mdd']:.4f} |" for _, row in baseline.iterrows())}

## Top 5 improvers (Calmar delta vs baseline 평균 = {baseline_calmar:.2f})

| sl | tp | reversal | calmar | Δcalmar | return | win_rate |
|----|----|----------|--------|---------|--------|----------|
{chr(10).join(f"| {r['sl_pct']} | {r['tp_pct']} | {r['intraday_reversal']} | {r['calmar']:.2f} | +{r['delta_calmar']:.2f} | {r['ret']:.4f} | {r['wr']:.3f} |" for _, r in improvers.iterrows())}

## Fold 2 (fail fold) MDD 개선 cell 수

- baseline Fold 2 MDD: {base_f2:.4f}
- baseline 보다 MDD 좋은 cell: {len(f2_improve)} / {len(f2)}

## 결론

자동 텍스트 — heatmaps/*.png 와 cells.csv 직접 조회 필수.
""", encoding="utf-8")
    print(f"[summary] {out}")


# main() 업데이트
def main():
    if (PG_DIR / "cells.csv").exists():
        plot_param_grid()
        write_param_grid_summary()
    if (EO_DIR / "cells.csv").exists():
        plot_exit_overlay()
        write_exit_overlay_summary()
```

(기존 `main()` 정의 삭제 후 위 새 main 으로 교체.)

- [ ] **Step 2: 동일 더미 cells.csv 로 스모크**

```bash
# Task 11 의 더미 cells.csv 다시 생성하는 일회성 셸 한 줄
python -c "
import pandas as pd
from pathlib import Path
Path('backtests/reports/macd_cross_mv/param_grid').mkdir(parents=True, exist_ok=True)
rows = []
for f in [10,12,14]:
  for s in [26,34]:
    for sig in [9,11]:
      for e in [1430,1450]:
        for ds in ['fold1','fold2','fold3','oos']:
          rows.append({'fast_period':f,'slow_period':s,'signal_period':sig,'entry_hhmm_min':e,
                       'dataset':ds,'calmar':50-f,'return':0.1,'mdd':-0.02,'trades':30,
                       'win_rate':0.5,'top1_share':0.5,'max_consec_loss':3,'monthly_trades':15})
pd.DataFrame(rows).to_csv('backtests/reports/macd_cross_mv/param_grid/cells.csv', index=False)
"
python -m backtests.multiverse.plot_macd_cross_mv
```
Expected: summary.md 생성, 에러 없음. 그 다음 더미 정리:
```bash
Remove-Item backtests/reports/macd_cross_mv/param_grid/cells.csv
Remove-Item backtests/reports/macd_cross_mv/param_grid/summary.md
Remove-Item -Recurse -Force backtests/reports/macd_cross_mv/param_grid/heatmaps
```

- [ ] **Step 3: Commit**

```bash
git add backtests/multiverse/plot_macd_cross_mv.py
git commit -m "$(cat <<'EOF'
feat(mv): summary.md 자동 생성기 (MV-A plateau/fragility/fold2-fail, MV-B baseline delta)

cells.csv → spec §3.4/§4.6 핵심 질문 자동 응답 텍스트.
heatmap PNG 와 함께 사람이 최종 결론 보강 가정.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: 최종 실행 + 결과 commit

**Files:** 결과 산출물만 (코드 없음)

- [ ] **Step 1: MV-A 풀 실행** (예상 30~50분)

```bash
python -m backtests.multiverse.macd_cross_param_grid 2>&1 | Tee-Object -FilePath backtests/reports/macd_cross_mv/param_grid_run.log
```
Expected: cells.csv (320 cells × 4 datasets = 1,280 rows) 생성, 에러 없음.

- [ ] **Step 2: MV-B 풀 실행** (예상 5~10분)

```bash
python -m backtests.multiverse.macd_cross_exit_overlay_mv 2>&1 | Tee-Object -FilePath backtests/reports/macd_cross_mv/exit_overlay_run.log
```
Expected: cells.csv (24 cells × 4 datasets = 96 rows) 생성.

- [ ] **Step 3: heatmap + summary 생성**

```bash
python -m backtests.multiverse.plot_macd_cross_mv
```
Expected: param_grid/heatmaps/ (6 PNG) + summary.md, exit_overlay/heatmaps/ (8 PNG) + summary.md.

- [ ] **Step 4: 결과 sanity check**

```bash
ls backtests/reports/macd_cross_mv/param_grid/
ls backtests/reports/macd_cross_mv/param_grid/heatmaps/
ls backtests/reports/macd_cross_mv/exit_overlay/
ls backtests/reports/macd_cross_mv/exit_overlay/heatmaps/
```
Expected: 모든 산출물 존재.

cells.csv 행수 확인:
```bash
python -c "
import pandas as pd
print('MV-A:', len(pd.read_csv('backtests/reports/macd_cross_mv/param_grid/cells.csv')), 'rows')
print('MV-B:', len(pd.read_csv('backtests/reports/macd_cross_mv/exit_overlay/cells.csv')), 'rows')
"
```
Expected: MV-A 1280, MV-B 96.

- [ ] **Step 5: summary.md 사람이 최종 보강**

`param_grid/summary.md` 와 `exit_overlay/summary.md` 의 "결론 (자동)" / "결론" 섹션을 heatmap PNG 와 cells.csv 보고 사람이 직접 작성. spec §3.4 / §4.6 의 핵심 질문 3개씩 답변 명시 (plateau/edge, fold2 패턴, fragility / baseline-improver, fold2 MDD 개선, plateau-vs-cherry-pick).

- [ ] **Step 6: Commit (보강된 summary + 산출물)**

```bash
git add backtests/reports/macd_cross_mv/
git commit -m "$(cat <<'EOF'
data(mv): macd_cross 멀티버스 결과 산출물 (MV-A 1,280 rows + MV-B 96 rows)

MV-A: 320 valid cell × 4 dataset, fine grid heatmap 6장.
MV-B: 24 cell × 4 dataset, exit overlay heatmap 8장.
summary.md 사람 보강 결론 포함.

Spec docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review (이미 적용)

- 모든 task 가 spec §1~7 을 cover (MV-A §3, MV-B §4, 산출물 §3.3/§4.5, 결론 §3.4/§4.6 → Task 13 사람 보강)
- 모든 step 에 실제 code/command/expected output 포함, "TBD/TODO" 없음
- type / 함수명 일관성: `MACDCrossExitOverlayStrategy`, `Dataset`, `evaluate_cell`, `build_cell_kpis`, `load_all_datasets`, `compute_top1_share`, `compute_max_consec_loss` 전반에 동일 사용
- 엔진 fill 컨벤션 (next-bar open) 명시 + spec 보강 자체를 Task 5 step 1 로 포함
