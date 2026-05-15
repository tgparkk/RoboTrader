# macd_cross fold2 Regime Filter v2 설계 (Phase 1 — 대체 신호 멀티버스 분석)

작성일: 2026-05-13
관련 산출물:
- `docs/superpowers/specs/2026-05-09-macd-cross-fold2-regime-filter-design.md` (v1 설계서)
- `backtests/reports/macd_cross_mv/regime_filter/summary.md` (v1 결과 — FAIL)
- `backtests/reports/macd_cross_mv/param_grid/cells.csv` (MV-A 결과)

## 1. 배경

v1 (commit `429d41a1`, 2026-05-09): KOSPI `close < MA20` 단일 신호 + 2 params × 2 filter × 4 ds = 16 eval. **FAIL**.

핵심 결과:

| signal | param_label | fold1 Δ | fold2 Δ | fold3 Δ | oos Δ |
|---|---|---:|---:|---:|---:|
| `close<MA20` (v1) | stage2_best (14/34) | +3.16 | **-0.57** | 0 | +37.21 |
| `close<MA20` (v1) | mva_global_best (16/32) | -1.54 | **-1.22** | 0 | -6.63 |

**Insight (v1 summary.md 사람 보강 결론)**:
1. fold2 block_days = 14 (vs fold1 = 3, fold3 = 0) — 신호 자체는 distinguishing
2. 그러나 fold2 Δcalmar -0.57 ~ -1.22 → **차단된 14일이 모두 손실일이 아니었음** (signal precision 부족)
3. mva_global_best 영역에서 일관 악화 → MA20 단순 break 가 16/32 fast/slow 영역과 부조화

v1 summary.md 가 직접 추천한 후속 신호 후보:
- **`(close<MA20) AND (MA5<MA20)`** — trend confirmation, 단발 break 제외
- **`5d_return ≤ -3%`** — sharp drop reactive
- **`20d_return ≤ 0%`** — sustained negative

본 spec 은 위 3 후보 + 임계값 sweep + v1 in-run baseline 으로 정밀 검증.

## 2. 핵심 결정

| 항목 | 결정 | 근거 |
|------|------|------|
| 신호 후보 | 3 신호 family + v1 baseline | v1 summary 추천 + 직접 비교 |
| 임계값 sweep | return 기반 신호는 다중 임계값 | "모든 케이스" — local optimum 회피 |
| Wrapper 구조 | 기존 wrapper 확장 (signal_type 분기) | 별도 3 wrapper 보다 코드 중복 적고 확장 용이 |
| v1 wrapper 호환 | `signal_type` default = `"ma20_below_prev"` | 기존 8 tests 그대로 통과 |
| 컬럼명 | 기존 `kospi_below_ma20` 유지 | 의미는 "regime says block". v1 backward compat |
| MA periods | fixed (MA20, MA5) | 본 spec 범위 밖 — 향후 별도 sweep 검토 |
| 라이브 코드 | **무수정** (Phase 1 분석 전용) | v1 과 동일 — 통과 시 Phase 2 별도 plan |

## 3. Cell 구성 (10 cells × 2 params × 4 datasets = 80 eval)

### 3.1 Signal cells (10개)

| cell # | signal_type | threshold | lookback | 차단 조건 (D-1 기준) |
|---|---|---|---|---|
| 1 | `off` | — | — | filter 비활성 (baseline) |
| 2 | `ma20_below_prev` | — | 20 | `close[D-1] < MA20[D-1]` (v1, in-run 비교용) |
| 3 | `ma20_and_ma5_below` | — | 20 | `(close[D-1]<MA20[D-1]) AND (MA5[D-1]<MA20[D-1])` |
| 4 | `5d_return_drop` | -0.01 | 5 | `close[D-1]/close[D-6] - 1 ≤ -1%` |
| 5 | `5d_return_drop` | -0.02 | 5 | `≤ -2%` |
| 6 | `5d_return_drop` | -0.03 | 5 | `≤ -3%` |
| 7 | `5d_return_drop` | -0.05 | 5 | `≤ -5%` |
| 8 | `20d_return_neg` | 0.0 | 20 | `close[D-1]/close[D-21] - 1 ≤ 0%` |
| 9 | `20d_return_neg` | -0.03 | 20 | `≤ -3%` |
| 10 | `20d_return_neg` | -0.05 | 20 | `≤ -5%` |

### 3.2 Param cells (2개)

| label | fast | slow | signal | entry |
|---|---|---|---|---|
| stage2_best | 14 | 34 | 12 | 1430 |
| mva_global_best | 16 | 32 | 12 | 1430 |

### 3.3 Datasets (4개, 기존)

`fold1` / `fold2` / `fold3` / `oos` — `load_all_datasets()` 그대로.

## 4. Decision Gate

### 4.1 Per-cell 4-gate (v1 과 동일, 각 9 cell × 2 params = 18 평가 단위)

| 조건 | 임계 | 의미 |
|------|------|------|
| ✓ fold2 calmar 개선 (vs off) | ≥ +20 | fold2 92% loss cell 문제 완화 |
| ✓ fold1/3 calmar 손실 | abs(%) ≤ 5% | 호황기 false positive 비용 합리 |
| ✓ oos calmar 변화 | ≥ ±0 | 미래 유사 시장 일반화 가능성 |
| ✓ block_days selectivity | fold2 > 5, fold1/3 ≤ 2 | 신호 정밀도 |

### 4.2 Best signal 추출

per-(signal_type, threshold, param_label) 단위로 4-gate score 계산:
- 4 gate 통과 카운트 (0~4)
- tiebreak: fold2 Δcalmar 큰 순 → fold1/3 손실 작은 순 → trades 수 충분 (≥ 20) 순

→ **하나라도 4-gate full PASS** 시 Phase 2 진입 검토 cell.
→ **모든 cell FAIL** 시 결론 "fold2 unrecoverable" → paper macd_cross_alt + circuit breaker 만으로 운영.

### 4.3 부분 PASS 처리

partial PASS (3-gate) 도 summary.md 에 별도 표기 — 사람 판단으로 trade-off 검토 가능. 자동 결론은 "needs human review".

## 5. 아키텍처 변경

### 5.1 Wrapper 확장 — `MACDCrossRegimeFilterStrategy`

`backtests/strategies/macd_cross_regime_filter.py` 수정 (기존 클래스 확장):

```python
SIGNAL_TYPES = (
    "ma20_below_prev",
    "ma20_and_ma5_below",
    "5d_return_drop",
    "20d_return_neg",
)


class MACDCrossRegimeFilterStrategy(MACDCrossStrategy):
    name = "macd_cross_regime_filter"

    def __init__(
        self,
        regime_filter_enabled: bool = False,
        kospi_daily_df: Optional[pd.DataFrame] = None,
        signal_type: str = "ma20_below_prev",  # NEW
        signal_threshold: Optional[float] = None,  # NEW (return 기반 신호 전용)
        ma_period: int = 20,
        ma_short_period: int = 5,  # NEW (ma20_and_ma5_below 용)
        **kwargs,
    ):
        super().__init__(**kwargs)
        if signal_type not in SIGNAL_TYPES:
            raise ValueError(f"unknown signal_type: {signal_type}")
        self.regime_filter_enabled = regime_filter_enabled
        self.kospi_daily_df = kospi_daily_df
        self.signal_type = signal_type
        self.signal_threshold = signal_threshold
        self.ma_period = ma_period
        self.ma_short_period = ma_short_period
        if regime_filter_enabled and kospi_daily_df is None:
            raise ValueError("regime_filter_enabled=True 인데 kospi_daily_df 가 None")

    def _compute_block_series(self, kospi: pd.DataFrame) -> pd.Series:
        """signal_type 분기 → 'below_prev' boolean Series 반환 (shift(1) 적용)."""
        ks = kospi.sort_values("trade_date").copy()
        if self.signal_type == "ma20_below_prev":
            ks["ma"] = ks["close"].rolling(self.ma_period).mean()
            cond = ks["close"] < ks["ma"]
        elif self.signal_type == "ma20_and_ma5_below":
            ks["ma_long"] = ks["close"].rolling(self.ma_period).mean()
            ks["ma_short"] = ks["close"].rolling(self.ma_short_period).mean()
            cond = (ks["close"] < ks["ma_long"]) & (ks["ma_short"] < ks["ma_long"])
        elif self.signal_type == "5d_return_drop":
            thr = self.signal_threshold if self.signal_threshold is not None else -0.03
            ret5 = ks["close"] / ks["close"].shift(5) - 1
            cond = ret5 <= thr
        elif self.signal_type == "20d_return_neg":
            thr = self.signal_threshold if self.signal_threshold is not None else 0.0
            ret20 = ks["close"] / ks["close"].shift(20) - 1
            cond = ret20 <= thr
        else:
            raise AssertionError(f"unreachable: {self.signal_type}")
        return cond.fillna(False).astype(bool).shift(1).fillna(False).astype(bool)

    def prepare_features(self, df_minute, df_daily):
        feat = super().prepare_features(df_minute, df_daily).copy()
        if not self.regime_filter_enabled or df_minute.empty:
            return feat
        ks = self.kospi_daily_df.sort_values("trade_date").copy()
        below_prev = self._compute_block_series(ks)
        block_map = dict(zip(ks["trade_date"].astype(str), below_prev))
        feat["kospi_below_ma20"] = (
            df_minute["trade_date"].astype(str)
            .map(block_map).fillna(False).astype(bool).values
        )
        return feat

    # entry_signal: 기존 그대로 (kospi_below_ma20 컬럼만 체크)
```

**컬럼명 `kospi_below_ma20` 유지 이유**: v1 8 tests 통과 + entry_signal 메서드 무수정. 의미적으로는 "regime says block" 의 generic flag.

### 5.2 MV-C v2 runner — `macd_cross_regime_filter_v2_mv.py` (신규)

```python
"""MV-C v2: macd_cross regime filter 대체 신호 멀티버스.

10 signal cells × 2 params × 4 datasets = 80 evaluation.
"""
import csv, time
from pathlib import Path
from typing import Dict, List, Optional

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_regime_filter import (
    MACDCrossRegimeFilterStrategy,
)


REPORT_DIR = Path("backtests/reports/macd_cross_mv/regime_filter_v2")

SIGNAL_CELLS: List[Dict] = [
    {"label": "off",                  "enabled": False, "signal_type": "ma20_below_prev",   "threshold": None},
    {"label": "ma20_below_prev",      "enabled": True,  "signal_type": "ma20_below_prev",   "threshold": None},
    {"label": "ma20_and_ma5_below",   "enabled": True,  "signal_type": "ma20_and_ma5_below","threshold": None},
    {"label": "5d_drop_-1pct",        "enabled": True,  "signal_type": "5d_return_drop",    "threshold": -0.01},
    {"label": "5d_drop_-2pct",        "enabled": True,  "signal_type": "5d_return_drop",    "threshold": -0.02},
    {"label": "5d_drop_-3pct",        "enabled": True,  "signal_type": "5d_return_drop",    "threshold": -0.03},
    {"label": "5d_drop_-5pct",        "enabled": True,  "signal_type": "5d_return_drop",    "threshold": -0.05},
    {"label": "20d_neg_0pct",         "enabled": True,  "signal_type": "20d_return_neg",    "threshold":  0.0 },
    {"label": "20d_neg_-3pct",        "enabled": True,  "signal_type": "20d_return_neg",    "threshold": -0.03},
    {"label": "20d_neg_-5pct",        "enabled": True,  "signal_type": "20d_return_neg",    "threshold": -0.05},
]

PARAM_CELLS = [
    {"label": "stage2_best",     "fast_period": 14, "slow_period": 34, "signal_period": 12, "entry_hhmm_min": 1430},
    {"label": "mva_global_best", "fast_period": 16, "slow_period": 32, "signal_period": 12, "entry_hhmm_min": 1430},
]


def _count_block_days(strategy, dataset):
    """dataset 영업일 중 filter 가 entry 차단했을 일수."""
    if not strategy.regime_filter_enabled or strategy.kospi_daily_df is None:
        return 0
    below_prev = strategy._compute_block_series(strategy.kospi_daily_df)
    block_map = dict(zip(strategy.kospi_daily_df.sort_values("trade_date")["trade_date"].astype(str), below_prev))
    ds_dates = set()
    for df_min in dataset.minute_by_code.values():
        if not df_min.empty:
            ds_dates.update(df_min["trade_date"].astype(str).unique())
    return int(sum(1 for d in ds_dates if block_map.get(d, False)))


def _evaluate(strategy, dataset, initial_capital=10_000_000):
    eng = BacktestEngine(
        strategy=strategy, initial_capital=initial_capital,
        universe=dataset.universe,
        minute_df_by_code=dataset.minute_by_code,
        daily_df_by_code=dataset.daily_by_code,
    )
    result = eng.run()
    trading_days = _trading_days_count(dataset.minute_by_code)
    kpis = build_cell_kpis(
        equity=result.equity_curve, trades=result.trades,
        trading_days=trading_days,
    )
    kpis["block_days"] = _count_block_days(strategy, dataset)
    return kpis


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("[MV-C v2] datasets 로드...")
    datasets = load_all_datasets()
    total = len(SIGNAL_CELLS) * len(PARAM_CELLS) * len(datasets)
    print(f"[MV-C v2] {total} evaluation 시작")

    out = REPORT_DIR / "cells.csv"
    fields = [
        "signal_label","signal_type","signal_threshold","filter_enabled",
        "param_label","fast_period","slow_period","signal_period","entry_hhmm_min",
        "dataset","calmar","return","mdd","trades","win_rate",
        "top1_share","max_consec_loss","monthly_trades","block_days",
    ]
    t0 = time.time()
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for sc in SIGNAL_CELLS:
            for pc in PARAM_CELLS:
                p = {k: v for k, v in pc.items() if k != "label"}
                for ds_name, ds in datasets.items():
                    strat = MACDCrossRegimeFilterStrategy(
                        regime_filter_enabled=sc["enabled"],
                        kospi_daily_df=ds.kospi_daily_df if sc["enabled"] else None,
                        signal_type=sc["signal_type"],
                        signal_threshold=sc["threshold"],
                        **p,
                    )
                    kpis = _evaluate(strat, ds)
                    writer.writerow({
                        "signal_label": sc["label"],
                        "signal_type": sc["signal_type"],
                        "signal_threshold": sc["threshold"],
                        "filter_enabled": sc["enabled"],
                        "param_label": pc["label"], **p,
                        "dataset": ds_name,
                        **{k: kpis[k] for k in (
                            "calmar","return","mdd","trades","win_rate",
                            "top1_share","max_consec_loss","monthly_trades","block_days",
                        )},
                    })
                    print(f"  {sc['label']:<22} {pc['label']:<16} {ds_name}: "
                          f"calmar={kpis['calmar']:>+7.2f} block={kpis['block_days']:>3} trades={kpis['trades']}")
    print(f"[MV-C v2] saved → {out} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
```

### 5.3 Plotter 확장 — `plot_macd_cross_mv.py`

`RFv2_DIR = Path("backtests/reports/macd_cross_mv/regime_filter_v2")` 추가 + 신규 함수:

```python
def plot_regime_filter_v2():
    """heatmap PNG 2장:
       1) calmar absolute heatmap (signal × dataset, param_label 별 1장)
       2) delta calmar (signal - off, signal × dataset, param_label 별 1장)
    """
    df = pd.read_csv(RFv2_DIR / "cells.csv")
    out = RFv2_DIR / "heatmaps"
    out.mkdir(exist_ok=True)
    for param_label in df["param_label"].unique():
        sub = df[df["param_label"] == param_label]
        pivot = sub.pivot_table(index="signal_label", columns="dataset", values="calmar")
        # absolute heatmap
        _heatmap_simple(pivot, out / f"calmar_abs_{param_label}.png",
                        title=f"Calmar — {param_label}")
        # delta vs off
        off_row = pivot.loc["off"]
        delta = pivot.subtract(off_row, axis=1)
        _heatmap_simple(delta, out / f"calmar_delta_{param_label}.png",
                        title=f"Calmar Δ vs off — {param_label}", center=0)


def write_regime_filter_v2_summary():
    """per-cell 4-gate 평가 → 최고 cell + 결론."""
    df = pd.read_csv(RFv2_DIR / "cells.csv")
    off = df[df["signal_label"] == "off"].set_index(["param_label","dataset"])["calmar"]

    rows = []
    for (sig, param), grp in df[df["signal_label"] != "off"].groupby(["signal_label","param_label"]):
        ds_calmar = grp.set_index("dataset")["calmar"]
        ds_block = grp.set_index("dataset")["block_days"]
        off_calmar = off.xs(param, level="param_label")
        delta = ds_calmar - off_calmar

        f2d = delta.get("fold2", 0.0)
        f1d = delta.get("fold1", 0.0)
        f3d = delta.get("fold3", 0.0)
        oosd = delta.get("oos", 0.0)
        f1_off = off_calmar.get("fold1", 0.0)
        f3_off = off_calmar.get("fold3", 0.0)
        f1_pct = (f1d / f1_off * 100) if abs(f1_off) > 1e-6 else 0.0
        f3_pct = (f3d / f3_off * 100) if abs(f3_off) > 1e-6 else 0.0

        g1 = f2d >= 20.0
        g2 = abs(f1_pct) <= 5.0 and abs(f3_pct) <= 5.0
        g3 = oosd >= 0.0
        g4 = (ds_block.get("fold2", 0) > 5
              and max(ds_block.get("fold1", 0), ds_block.get("fold3", 0)) <= 2)
        score = sum([g1, g2, g3, g4])

        rows.append({
            "signal_label": sig, "param_label": param,
            "fold2_delta": f2d, "fold1_pct": f1_pct, "fold3_pct": f3_pct, "oos_delta": oosd,
            "block_f2": int(ds_block.get("fold2", 0)),
            "block_f1": int(ds_block.get("fold1", 0)),
            "block_f3": int(ds_block.get("fold3", 0)),
            "gate_score": score, "g1": g1, "g2": g2, "g3": g3, "g4": g4,
        })

    res = pd.DataFrame(rows).sort_values(
        ["gate_score", "fold2_delta"], ascending=[False, False],
    )
    body = ["# MV-C v2 regime filter summary\n"]
    body.append("## Per-cell 4-gate evaluation (sorted by gate_score desc, fold2_delta desc)\n")
    body.append(res.to_markdown(index=False))

    full_pass = res[res["gate_score"] == 4]
    partial_pass = res[(res["gate_score"] >= 2) & (res["gate_score"] < 4)]
    body.append("\n## 종합")
    if not full_pass.empty:
        best = full_pass.iloc[0]
        body.append(f"\n**PASS** — `{best['signal_label']}` × `{best['param_label']}` "
                    f"(gate_score=4, fold2_delta={best['fold2_delta']:+.2f}). Phase 2 진입 검토.")
    elif not partial_pass.empty:
        body.append(f"\n**PARTIAL** — {len(partial_pass)} cell 이 2~3 gate 통과. "
                    "사람 판단 필요 (trade-off 검토).")
    else:
        body.append("\n**FAIL** — 모든 cell 이 4-gate 통과 불가. "
                    "결론: fold2 unrecoverable, paper macd_cross_alt + circuit breaker 만으로 운영.")
    body.append("\nheatmaps/ 와 cells.csv 함께 검토.")
    (RFv2_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
```

`main()` 에 호출 추가:
```python
if (RFv2_DIR / "cells.csv").exists():
    plot_regime_filter_v2()
    write_regime_filter_v2_summary()
```

## 6. 데이터 흐름

```
load_all_datasets()  (변경 없음 — v1 에서 kospi_daily_df 첨부 완료)

MV-C v2 runner (80 evaluation):
  for signal_cell in 10 SIGNAL_CELLS:
    for param in 2 PARAM_CELLS:
      for ds in [fold1, fold2, fold3, oos]:
        strategy = MACDCrossRegimeFilterStrategy(
            regime_filter_enabled=signal_cell.enabled,
            kospi_daily_df=ds.kospi_daily_df,
            signal_type=signal_cell.signal_type,
            signal_threshold=signal_cell.threshold,
            **param,
        )
        BacktestEngine(strategy, ds.*).run()
        → cells.csv row (calmar, return, mdd, ..., block_days)

plotter:
  cells.csv → heatmap PNG 4장 (abs/delta × 2 param) + summary.md (per-cell gate + 종합)
```

## 7. Lookahead 방지 (3대 원칙 ①)

**모든 4 signal_type 에 `shift(1)` 적용 보증**:

- `ma20_below_prev`: 기존 v1 — `cond.shift(1)`
- `ma20_and_ma5_below`: `(close<MA20) & (MA5<MA20)` 계산 후 `cond.shift(1)`
- `5d_return_drop`: `close/close.shift(5) - 1` 계산 후 `cond.shift(1)` — D-1 close 와 D-6 close 만 사용
- `20d_return_neg`: `close/close.shift(20) - 1` 계산 후 `cond.shift(1)` — D-1 close 와 D-21 close 만 사용

검증: 모든 signal_type 별로 lookahead 회귀 테스트 1건씩 추가 (D 일 close 변경 → D 일 신호 불변).

## 8. Testing 전략

| # | 테스트 | 위치 | 검증 |
|---|--------|------|------|
| 1 | v1 기존 8 tests | `tests/backtests/strategies/test_macd_cross_regime_filter.py` | backward compat |
| 2 | `signal_type="ma20_and_ma5_below"` basic | 동 | D-1 (close<MA20)∧(MA5<MA20) 정확 |
| 3 | `signal_type="ma20_and_ma5_below"` lookahead | 동 | D close 변경 → D 신호 불변 |
| 4 | `signal_type="5d_return_drop"` basic + threshold | 동 | close[D-1]/close[D-6]-1 ≤ threshold 정확 |
| 5 | `signal_type="5d_return_drop"` lookahead | 동 | D close 변경 → D 신호 불변 |
| 6 | `signal_type="20d_return_neg"` basic + threshold | 동 | close[D-1]/close[D-21]-1 ≤ threshold 정확 |
| 7 | `signal_type="20d_return_neg"` lookahead | 동 | D close 변경 → D 신호 불변 |
| 8 | invalid signal_type → ValueError | 동 | enum 가드 |
| 9 | Regression: 전체 280 tests | `tests/` | 라이브 코드 무수정이라 자동 그린 |
| 10 | Manual: MV-C v2 풀 실행 | `python -m backtests.multiverse.macd_cross_regime_filter_v2_mv` | 80 eval, cells.csv + 4 heatmap + summary.md |

총 v1 8 + v2 6 + invalid 1 = **15 unit tests**.

## 9. 산출물

**코드**:
- `backtests/strategies/macd_cross_regime_filter.py` (수정 — `signal_type`/`signal_threshold`/`ma_short_period` 추가 + `_compute_block_series` 메서드)
- `backtests/multiverse/macd_cross_regime_filter_v2_mv.py` (신규)
- `backtests/multiverse/plot_macd_cross_mv.py` (수정 — RFv2 section + main 호출)

**테스트**:
- `tests/backtests/strategies/test_macd_cross_regime_filter.py` (수정 — 7 신규 tests 추가)

**데이터 산출물 (Phase 1 v2 실행 후)**:
- `backtests/reports/macd_cross_mv/regime_filter_v2/cells.csv` (80 rows)
- `backtests/reports/macd_cross_mv/regime_filter_v2/heatmaps/calmar_abs_{stage2_best,mva_global_best}.png`
- `backtests/reports/macd_cross_mv/regime_filter_v2/heatmaps/calmar_delta_{stage2_best,mva_global_best}.png`
- `backtests/reports/macd_cross_mv/regime_filter_v2/summary.md` (per-cell 4-gate + 종합)

## 10. 범위 밖 (Out of Scope)

- **Phase 2: 라이브 적용** — full PASS cell 발견 시 별도 spec/plan
- **MA period sweep** (MA10/MA20 vs MA5/MA10 등) — 본 spec 범위 밖, 후속
- **신호 조합 (AND/OR ensemble)** — 사용자 결정에 따라 제외 (단일 신호만)
- **KOSDAQ 지수** — KOSPI 단일로 진행
- **Threshold 더 세밀 (-1.5%, -2.5% 등)** — 4 / 3 단계로 충분, 후속 보완 가능

## 11. 결론 시나리오 (자동 판정)

| 결과 | 종합 | 후속 |
|------|------|------|
| 1+ cell full PASS (gate_score=4) | **PASS** | best cell 로 Phase 2 spec 작성 |
| 0 full PASS, 1+ partial PASS (2~3) | **PARTIAL** | 사람 판단 — trade-off 비교 |
| 모든 cell gate_score ≤ 1 | **FAIL** | fold2 unrecoverable 결론, paper macd_cross_alt 운영 |
