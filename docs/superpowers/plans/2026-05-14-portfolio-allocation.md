# MV-F: Portfolio Allocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 3 strategy (macd_cross + breakout_52w + trend_followthrough) 의 자본 분배 simplex grid (66 cells × 4 fold = 264) 를 additive 모델로 평가하여 portfolio 4ds-avg calmar > 65.44 + fold2 개선을 만족하는 weight 조합 발견.

**Architecture:** 2-stage. Stage 1 = 각 strategy × fold 의 equity 시계열을 캐시 (12 NPY). Stage 2 = simplex weight grid 의 각 cell 에서 equity 가중합 → portfolio calmar/MDD/return 재계산. plot/summary 는 기존 plot_macd_cross_mv.py 확장.

**Tech Stack:** Python 3.9, pandas, numpy, matplotlib (tricontourf for simplex). 기존 `BacktestEngine`, `compute_calmar`, `compute_max_drawdown` 재사용.

**Spec:** docs/superpowers/specs/2026-05-14-portfolio-allocation-design.md

---

## File Structure

| 파일 | 역할 |
|------|------|
| `backtests/multiverse/portfolio_allocation_mv.py` (신규) | Stage 1 (equity cache) + Stage 2 (weight sweep) runner |
| `backtests/multiverse/plot_macd_cross_mv.py` (수정) | `PA_DIR` + `plot_portfolio_allocation()` + `write_portfolio_allocation_summary()` |
| `backtests/reports/portfolio_allocation/equity_cache/*.npy` (산출) | 12 NPY (3 strategy × 4 fold) |
| `backtests/reports/portfolio_allocation/{cells.csv, summary.md, heatmaps/}` (산출) | Stage 2 결과 |
| `memory/project_macd_cross_paper.md` | MV-F 결론 섹션 추가 (Task 6) |

---

## Task 1: Stage 1 runner (3 strategy × 4 fold equity cache)

**Files:**
- Create: `backtests/multiverse/portfolio_allocation_mv.py`

- [ ] **Step 1: Create runner skeleton + Stage 1 function**

```python
"""MV-F: Portfolio Allocation 멀티버스.

Stage 1: 3 strategy × 4 fold equity 시계열 NPY 캐시 (12 NPY).
Stage 2: simplex weight grid 66 cells × 4 fold = 264 portfolio metric.

Spec: docs/superpowers/specs/2026-05-14-portfolio-allocation-design.md
Plan: docs/superpowers/plans/2026-05-14-portfolio-allocation.md
"""
import argparse
import csv
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.common.metrics import compute_calmar, compute_max_drawdown
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, load_all_datasets, _trading_days_count,
)
from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.macd_cross import MACDCrossStrategy
from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy


REPORT_DIR = Path("backtests/reports/portfolio_allocation")
EQUITY_CACHE_DIR = REPORT_DIR / "equity_cache"


STRATEGY_BUILDERS = {
    "macd_cross": lambda: MACDCrossStrategy(
        fast_period=14, slow_period=34, signal_period=12, entry_hhmm_min=1430,
    ),
    "breakout_52w": lambda: Breakout52wStrategy(
        lookback_days=60, buffer_pct=0.0, entry_hhmm_min=1500, entry_hhmm_max=1500,
    ),
    "trend_followthrough": lambda: TrendFollowthroughStrategy(
        lookback_days=3, buffer_pct=0.6, entry_hhmm_min=1430, entry_hhmm_max=1500,
    ),
}


def run_stage1(datasets: Dict[str, Dataset], initial_capital: float = 10_000_000) -> Dict[Tuple[str, str], int]:
    """3 strategy × 4 fold sim 후 equity NPY 저장.

    Returns:
        {(strategy, fold): trading_days} 매핑 — Stage 2 calmar 계산에 필요.
    """
    EQUITY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    trading_days_map: Dict[Tuple[str, str], int] = {}
    t0 = time.time()
    for sname, builder in STRATEGY_BUILDERS.items():
        for ds_name, ds in datasets.items():
            eng = BacktestEngine(
                strategy=builder(),
                initial_capital=initial_capital,
                universe=ds.universe,
                minute_df_by_code=ds.minute_by_code,
                daily_df_by_code=ds.daily_by_code,
            )
            result = eng.run()
            equity = result.equity_curve.values.astype(float)
            np.save(EQUITY_CACHE_DIR / f"{sname}_{ds_name}.npy", equity)
            td = _trading_days_count(ds.minute_by_code)
            trading_days_map[(sname, ds_name)] = td
            elapsed = time.time() - t0
            print(f"  stage1 {sname:>22} {ds_name}: "
                  f"equity[0]={equity[0]:.0f} equity[-1]={equity[-1]:.0f} "
                  f"trades={len(result.trades)} ({elapsed:.0f}s)")
    return trading_days_map
```

- [ ] **Step 2: Verify import**

Run:
```bash
python -c "from backtests.multiverse.portfolio_allocation_mv import run_stage1, STRATEGY_BUILDERS; print('OK', list(STRATEGY_BUILDERS.keys()))"
```
Expected:
```
OK ['macd_cross', 'breakout_52w', 'trend_followthrough']
```

---

## Task 2: Stage 2 (weight simplex sweep) + main()

**Files:**
- Modify: `backtests/multiverse/portfolio_allocation_mv.py`

- [ ] **Step 1: Add simplex weight generator + Stage 2 function**

Append to `backtests/multiverse/portfolio_allocation_mv.py`:

```python
def simplex_weights(step: float = 0.1) -> List[Tuple[float, float, float]]:
    """w1+w2+w3=1 인 simplex grid. step=0.1 → 66 cells."""
    n = int(round(1.0 / step))
    weights = []
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            weights.append((i / n, j / n, k / n))
    return weights


def load_equity_cache() -> Dict[Tuple[str, str], np.ndarray]:
    """equity_cache/ 에서 모든 NPY 로드."""
    eq: Dict[Tuple[str, str], np.ndarray] = {}
    for sname in STRATEGY_BUILDERS:
        for fname in ("fold1", "fold2", "fold3", "oos"):
            path = EQUITY_CACHE_DIR / f"{sname}_{fname}.npy"
            if path.exists():
                eq[(sname, fname)] = np.load(path)
    return eq


def run_stage2(
    eq: Dict[Tuple[str, str], np.ndarray],
    trading_days_map: Dict[Tuple[str, str], int],
    initial_capital: float = 10_000_000,
) -> pd.DataFrame:
    """simplex weight grid × 4 fold 의 portfolio metric 계산."""
    weights = simplex_weights(step=0.1)
    folds = ("fold1", "fold2", "fold3", "oos")
    rows = []
    for (w_m, w_b, w_t) in weights:
        for fold in folds:
            macd_eq = eq[("macd_cross", fold)]
            brk_eq = eq[("breakout_52w", fold)]
            trn_eq = eq[("trend_followthrough", fold)]
            # 길이 정렬 (모두 같은 dataset 의 분봉 수라 동일 길이 가정)
            n = min(len(macd_eq), len(brk_eq), len(trn_eq))
            macd_ret = macd_eq[:n] / macd_eq[0]
            brk_ret = brk_eq[:n] / brk_eq[0]
            trn_ret = trn_eq[:n] / trn_eq[0]
            port_eq = initial_capital * (w_m * macd_ret + w_b * brk_ret + w_t * trn_ret)
            port_eq_series = pd.Series(port_eq)
            td = trading_days_map.get(("macd_cross", fold), 0)
            rows.append({
                "w_macd": round(w_m, 2),
                "w_breakout": round(w_b, 2),
                "w_trend": round(w_t, 2),
                "fold": fold,
                "portfolio_calmar": compute_calmar(port_eq_series, td),
                "portfolio_return": float(port_eq[-1] / port_eq[0] - 1),
                "portfolio_mdd": compute_max_drawdown(port_eq_series),
                "macd_calmar": compute_calmar(pd.Series(macd_eq[:n]), td),
                "breakout_calmar": compute_calmar(pd.Series(brk_eq[:n]), td),
                "trend_calmar": compute_calmar(pd.Series(trn_eq[:n]), td),
            })
    return pd.DataFrame(rows)


def main(stage: str = "all", smoke: bool = False):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if stage in ("all", "stage1"):
        print("[MV-F] datasets 로드...")
        datasets = load_all_datasets()
        if smoke:
            datasets = {"fold1": datasets["fold1"]}
        td_map = run_stage1(datasets)
    else:
        # stage2 only: trading_days_map 재구성 (cached datasets 로부터)
        print("[MV-F] stage2 only — datasets 로드 (trading_days 재구성용)...")
        datasets = load_all_datasets()
        td_map = {(s, f): _trading_days_count(datasets[f].minute_by_code)
                  for s in STRATEGY_BUILDERS for f in datasets}

    if stage in ("all", "stage2"):
        eq = load_equity_cache()
        if smoke:
            # smoke 에서는 fold1 만 있음 — stage2 도 fold1 만으로 진행
            eq = {k: v for k, v in eq.items() if k[1] == "fold1"}
        if not eq:
            print("[MV-F] equity cache 비어있음 — stage1 먼저 실행 필요")
            return
        df = run_stage2(eq, td_map)
        if smoke:
            out_path = REPORT_DIR / "smoke_cells.csv"
            # smoke 에선 fold1 cell 만 추출
            df = df[df["fold"] == "fold1"]
        else:
            out_path = REPORT_DIR / "cells.csv"
        df.to_csv(out_path, index=False)
        print(f"[MV-F] stage2 saved → {out_path} ({len(df)} rows)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["all", "stage1", "stage2"], default="all")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    main(stage=args.stage, smoke=args.smoke)
```

- [ ] **Step 2: Verify simplex generator**

Run:
```bash
python -c "from backtests.multiverse.portfolio_allocation_mv import simplex_weights; ws = simplex_weights(0.1); print(f'count={len(ws)}'); print('sample:', ws[:3], '...', ws[-3:]); print('all sum to 1:', all(abs(sum(w)-1.0) < 1e-9 for w in ws))"
```
Expected:
```
count=66
sample: [(0.0, 0.0, 1.0), (0.0, 0.1, 0.9), (0.0, 0.2, 0.8)] ... [(0.9, 0.0, 0.1), (0.9, 0.1, 0.0), (1.0, 0.0, 0.0)]
all sum to 1: True
```

---

## Task 3: Smoke run

- [ ] **Step 1: Run smoke**

Run:
```bash
python -m backtests.multiverse.portfolio_allocation_mv --smoke
```
Expected (~30~60s):
- 3 strategy × 1 fold = 3 stage1 sim
- stage2: 66 weight cells × 1 fold = 66 rows
- Output ends with `[MV-F] stage2 saved → backtests\reports\portfolio_allocation\smoke_cells.csv (66 rows)`

- [ ] **Step 2: Verify smoke output**

Run:
```bash
python -c "
import pandas as pd
df = pd.read_csv('backtests/reports/portfolio_allocation/smoke_cells.csv')
print(f'rows: {len(df)}')
# Corner cell sanity: (1,0,0) = macd_cross 단독
corner_macd = df[(df['w_macd']==1.0) & (df['w_breakout']==0.0)]
print('corner (1,0,0):', corner_macd[['portfolio_calmar','macd_calmar']].to_string())
# 비교: portfolio_calmar 가 macd_calmar 와 정확 일치해야
print('match:', float(corner_macd['portfolio_calmar'].iloc[0]) == float(corner_macd['macd_calmar'].iloc[0]))
"
```
Expected:
- rows: 66
- corner (1,0,0): portfolio_calmar == macd_calmar (정확 일치)

---

## Task 4: plot/summary 함수 추가

**Files:**
- Modify: `backtests/multiverse/plot_macd_cross_mv.py`

- [ ] **Step 1: Add PA_DIR constant**

In `backtests/multiverse/plot_macd_cross_mv.py`, find this block:
```python
FR_DIR = Path("backtests/reports/fold2_robust_survey")
```
Add after it:
```python
PA_DIR = Path("backtests/reports/portfolio_allocation")
```

- [ ] **Step 2: Add plot_portfolio_allocation()**

Append before `def main():`:

```python
def plot_portfolio_allocation():
    """Simplex triangle heatmap per fold + 4ds-avg.

    barycentric coordinate: w_macd 가 top vertex, w_breakout right, w_trend left.
    matplotlib tricontourf 사용.
    """
    df = pd.read_csv(PA_DIR / "cells.csv")
    out = PA_DIR / "heatmaps"
    out.mkdir(exist_ok=True)

    # 4ds-avg 계산
    avg4 = df.groupby(["w_macd", "w_breakout", "w_trend"]).agg(
        portfolio_calmar=("portfolio_calmar", "mean"),
        portfolio_return=("portfolio_return", "mean"),
        portfolio_mdd=("portfolio_mdd", "mean"),
    ).reset_index()

    def _simplex_tricontour(ws, vals, title, path):
        # barycentric → 2D 변환: x = w_breakout + 0.5*w_macd, y = (sqrt(3)/2)*w_macd
        w_m = ws["w_macd"].values
        w_b = ws["w_breakout"].values
        w_t = ws["w_trend"].values
        x = w_b + 0.5 * w_m
        y = (np.sqrt(3) / 2) * w_m
        fig, ax = plt.subplots(figsize=(7, 6))
        tcf = ax.tricontourf(x, y, vals, levels=20, cmap="RdYlGn")
        ax.scatter(x, y, c="black", s=8)
        # corner labels
        ax.text(0.5, np.sqrt(3)/2 + 0.04, "macd_cross (1,0,0)", ha="center", fontsize=8)
        ax.text(1.04, -0.03, "breakout (0,1,0)", ha="left", fontsize=8)
        ax.text(-0.04, -0.03, "trend (0,0,1)", ha="right", fontsize=8)
        # G4 line: w_macd=0.4 (수평선 at y=0.4*sqrt(3)/2)
        ax.axhline(0.4 * np.sqrt(3) / 2, color="blue", lw=0.8, ls="--",
                   label="G4: w_macd=0.4")
        ax.legend(loc="lower right", fontsize=8)
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.set_xticks([])
        ax.set_yticks([])
        plt.colorbar(tcf, ax=ax, fraction=0.04)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    # 4ds-avg
    _simplex_tricontour(avg4, avg4["portfolio_calmar"].values,
                        "Portfolio Calmar — 4ds avg",
                        out / "portfolio_calmar_4dsavg.png")
    _simplex_tricontour(avg4, avg4["portfolio_mdd"].values,
                        "Portfolio MDD — 4ds avg",
                        out / "portfolio_mdd_4dsavg.png")
    _simplex_tricontour(avg4, avg4["portfolio_return"].values,
                        "Portfolio Return — 4ds avg",
                        out / "portfolio_return_4dsavg.png")
    # per-fold calmar
    for fold in ("fold1", "fold2", "fold3", "oos"):
        sub = df[df["fold"] == fold]
        _simplex_tricontour(sub, sub["portfolio_calmar"].values,
                            f"Portfolio Calmar — {fold}",
                            out / f"portfolio_calmar_{fold}.png")
    print(f"[plot] portfolio_allocation heatmaps → {out}")
```

- [ ] **Step 3: Add write_portfolio_allocation_summary()**

Append before `def main():`:

```python
def write_portfolio_allocation_summary():
    """G1~G5 자동 평가 + best cell + PASS/PARTIAL/FAIL."""
    df = pd.read_csv(PA_DIR / "cells.csv")

    # macd_cross 단독 baseline (corner (1,0,0))
    macd_alone = df[(df["w_macd"] == 1.0) & (df["w_breakout"] == 0.0)]
    baseline = macd_alone.set_index("fold")
    baseline_calmar_4ds = float(baseline["portfolio_calmar"].mean())
    baseline_f1 = float(baseline.loc["fold1", "portfolio_calmar"])
    baseline_f2 = float(baseline.loc["fold2", "portfolio_calmar"])
    baseline_f3 = float(baseline.loc["fold3", "portfolio_calmar"])
    baseline_oos = float(baseline.loc["oos", "portfolio_calmar"])
    baseline_f2_mdd = float(baseline.loc["fold2", "portfolio_mdd"])
    baseline_4ds_mdd = float(baseline["portfolio_mdd"].mean())

    # cell 평가
    rows = []
    grouped = df.groupby(["w_macd", "w_breakout", "w_trend"])
    for (wm, wb, wt), grp in grouped:
        gset = grp.set_index("fold")
        c4 = float(gset["portfolio_calmar"].mean())
        cf1 = float(gset.loc["fold1", "portfolio_calmar"])
        cf2 = float(gset.loc["fold2", "portfolio_calmar"])
        cf3 = float(gset.loc["fold3", "portfolio_calmar"])
        coos = float(gset.loc["oos", "portfolio_calmar"])
        cf2_mdd = float(gset.loc["fold2", "portfolio_mdd"])
        c4_mdd = float(gset["portfolio_mdd"].mean())

        g1 = c4 > baseline_calmar_4ds
        g2a = cf2 > baseline_f2
        g2b = cf2_mdd >= baseline_f2_mdd * 0.95  # 둘 다 음수: mdd ≥ baseline*0.95 = 절대값 5% 개선
        # G3: 각 다른 fold 의 손실율 ≤ 10%
        def _loss_pct(cell_v, base_v):
            if abs(base_v) < 1e-6:
                return 0.0
            return (cell_v - base_v) / base_v * 100.0
        f1_loss = _loss_pct(cf1, baseline_f1)
        f3_loss = _loss_pct(cf3, baseline_f3)
        oos_loss = _loss_pct(coos, baseline_oos)
        g3 = min(f1_loss, f3_loss, oos_loss) >= -10.0
        g4 = wm >= 0.4
        g5 = c4_mdd >= baseline_4ds_mdd * 0.95

        primary = g1 and g2a and g2b
        secondary = int(g3) + int(g4) + int(g5)
        if primary and secondary >= 2:
            verdict = "PASS"
        elif g1 or g2a:
            verdict = "PARTIAL"
        else:
            verdict = "FAIL"

        rows.append({
            "w_macd": wm, "w_breakout": wb, "w_trend": wt,
            "calmar_4ds": c4, "fold1": cf1, "fold2": cf2, "fold3": cf3, "oos": coos,
            "fold2_mdd": cf2_mdd, "mdd_4ds": c4_mdd,
            "f1_loss_pct": f1_loss, "f3_loss_pct": f3_loss, "oos_loss_pct": oos_loss,
            "G1": g1, "G2a": g2a, "G2b": g2b, "G3": g3, "G4": g4, "G5": g5,
            "verdict": verdict,
        })

    res = pd.DataFrame(rows)
    verdict_order = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}
    res["_v"] = res["verdict"].map(verdict_order)
    res = res.sort_values(["_v", "calmar_4ds"], ascending=[True, False]).drop(columns=["_v"]).reset_index(drop=True)

    body = ["# MV-F portfolio_allocation summary\n"]
    body.append("## Baseline — macd_cross 단독 (corner cell w=(1,0,0))\n")
    body.append(f"- 4ds-avg calmar = **{baseline_calmar_4ds:.2f}**")
    body.append(f"- fold1={baseline_f1:.2f} / fold2={baseline_f2:.2f} / fold3={baseline_f3:.2f} / oos={baseline_oos:.2f}")
    body.append(f"- fold2 MDD = {baseline_f2_mdd:.4f}")

    body.append("\n## Gate 정의\n")
    body.append("- **G1** portfolio 4ds-avg calmar > baseline ({:.2f})".format(baseline_calmar_4ds))
    body.append(f"- **G2a** fold2 calmar > baseline ({baseline_f2:.2f})")
    body.append("- **G2b** fold2 MDD ≥ baseline × 0.95")
    body.append("- **G3** fold1/3/oos 손실율 ≤ 10%")
    body.append("- **G4** w_macd ≥ 0.4 (운영 제약)")
    body.append("- **G5** 4ds-avg MDD ≥ baseline × 0.95")
    body.append("- 판정: PASS (G1+G2a+G2b + 보조 ≥2) / PARTIAL (G1 또는 G2a) / FAIL")

    pass_cells = res[res["verdict"] == "PASS"]
    if not pass_cells.empty:
        body.append(f"\n## PASS cells ({len(pass_cells)}건)\n")
        body.append(pass_cells[[
            "w_macd", "w_breakout", "w_trend",
            "calmar_4ds", "fold1", "fold2", "fold3", "oos",
            "f1_loss_pct", "f3_loss_pct", "oos_loss_pct",
        ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## Top 20 by 4ds-avg calmar\n")
    body.append(res.head(20)[[
        "w_macd", "w_breakout", "w_trend", "verdict",
        "calmar_4ds", "fold1", "fold2", "fold3", "oos",
        "G1", "G2a", "G2b", "G3", "G4", "G5",
    ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## fold2 calmar top 10 (fold2 회복 관점)\n")
    f2_top = res.sort_values("fold2", ascending=False).head(10)
    body.append(f2_top[[
        "w_macd", "w_breakout", "w_trend", "verdict",
        "fold2", "fold2_mdd", "calmar_4ds",
    ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## 종합 판정")
    if not pass_cells.empty:
        best = pass_cells.iloc[0]
        body.append(
            f"\n**PASS** — `w=({best['w_macd']:.1f}, {best['w_breakout']:.1f}, {best['w_trend']:.1f})` "
            f"calmar_4ds={best['calmar_4ds']:+.2f} (baseline +{best['calmar_4ds']-baseline_calmar_4ds:+.2f}) "
            f"fold2={best['fold2']:+.2f}. paper trial 검토 권고."
        )
    else:
        partial = res[res["verdict"] == "PARTIAL"]
        if not partial.empty:
            best = partial.iloc[0]
            body.append(
                f"\n**PARTIAL** — {len(partial)} cell 이 G1 또는 G2a 만 통과. "
                f"최고: w=({best['w_macd']:.1f}, {best['w_breakout']:.1f}, {best['w_trend']:.1f}) "
                f"calmar_4ds={best['calmar_4ds']:+.2f}, fold2={best['fold2']:+.2f}. 사람 판단."
            )
        else:
            body.append(
                "\n**FAIL** — G1 + G2a 동시 통과 cell 없음. portfolio 가설 기각. "
                "MV-G (신규 family — ML / microstructure) 권고."
            )

    body.append("\nheatmaps/ + cells.csv 참조.")
    (PA_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
    print(f"[summary] {PA_DIR / 'summary.md'}")
```

- [ ] **Step 4: Add main() branch**

Find the `def main():` and add this branch before `if __name__ == "__main__":`:
```python
    if (PA_DIR / "cells.csv").exists():
        plot_portfolio_allocation()
        write_portfolio_allocation_summary()
```

- [ ] **Step 5: Verify imports**

Run:
```bash
python -c "from backtests.multiverse.plot_macd_cross_mv import plot_portfolio_allocation, write_portfolio_allocation_summary, PA_DIR; print('OK', PA_DIR)"
```
Expected:
```
OK backtests\reports\portfolio_allocation
```

---

## Task 5: 본 실행 + 리포트

- [ ] **Step 1: Run full sim (stage all)**

Run (in background):
```bash
python -m backtests.multiverse.portfolio_allocation_mv 2>&1 | tee backtests/reports/portfolio_allocation/portfolio_allocation_run.log
```
Expected duration: ~15분 (Stage 1: 12 sim × ~75초 평균. Stage 2: <1초).

Wait for completion notification. Log ends with:
```
[MV-F] stage2 saved → backtests\reports\portfolio_allocation\cells.csv (264 rows)
```

- [ ] **Step 2: Verify cells.csv**

Run:
```bash
python -c "
import pandas as pd
df = pd.read_csv('backtests/reports/portfolio_allocation/cells.csv')
print(f'rows: {len(df)} (expect 264)')
# corner (1,0,0) cell baseline 일치 확인
macd_corner = df[(df['w_macd']==1.0) & (df['w_breakout']==0.0)].sort_values('fold')
print('macd corner per fold:')
print(macd_corner[['fold','portfolio_calmar','macd_calmar']].to_string())
"
```
Expected:
- rows: 264
- macd corner: portfolio_calmar == macd_calmar 4 folds
- macd_calmar fold1≈36, fold2≈-2.8, fold3≈182, oos≈46 (MV-E baseline 와 일치)

- [ ] **Step 3: Generate plots + summary**

Run:
```bash
python -m backtests.multiverse.plot_macd_cross_mv 2>&1 | tail -10
```
Expected last 2 lines:
```
[plot] portfolio_allocation heatmaps → backtests\reports\portfolio_allocation\heatmaps
[summary] backtests\reports\portfolio_allocation\summary.md
```

- [ ] **Step 4: Read summary.md**

Run:
```bash
head -50 backtests/reports/portfolio_allocation/summary.md
```
Expected: section headers — Baseline / Gate / PASS or PARTIAL / Top 20 / 종합 판정

---

## Task 6: 사람 판정 + memory

- [ ] **Step 1: 사용자에게 결과 요약 보고**

요약 텍스트로 보고 — verdict (PASS/PARTIAL/FAIL) + best cell + fold 별 portfolio calmar.

- [ ] **Step 2: Append "사람 보강 결론" to summary.md**

Use Edit tool to append at end of `backtests/reports/portfolio_allocation/summary.md`:

```markdown

## 사람 보강 결론 (2026-05-14)

### 자동 평가 결과
- 264 evaluation (66 weight cells × 4 fold), additive 모델
- <PASS/PARTIAL/FAIL> 분포

### 핵심 발견
<best cell + baseline 대비 개선 + caveat (additive 모델 한계 — over-optimistic 가능성)>

### 다음 단계
<PASS 시 paper trial spec / PARTIAL 시 integrated 모델 재검증 / FAIL 시 MV-G 신규 family>
```

- [ ] **Step 3: Update memory**

Append to `C:\Users\sttgp\.claude\projects\D--GIT-RoboTrader\memory\project_macd_cross_paper.md`:

```markdown

## MV-F 결론 (2026-05-14, portfolio allocation)

**Spec**: docs/superpowers/specs/2026-05-14-portfolio-allocation-design.md
**Plan**: docs/superpowers/plans/2026-05-14-portfolio-allocation.md
**산출물**: backtests/reports/portfolio_allocation/{summary.md, cells.csv, heatmaps/, equity_cache/}
**스코프**: 3 strategy (macd_cross stage2_best + breakout_52w + trend_followthrough) × simplex weight grid step=0.1 = 66 cells × 4 fold = 264 eval. Additive 모델 (equity 가중합).

**결과**: <PASS / PARTIAL / FAIL — Task 6 Step 1 결과 기록>

**Why**: MV-E 부산물 — breakout/trend 가 fold1·3 강함. macd_cross 와 portfolio 시 fold2/MDD 개선 정량 검증.

**Caveat**: additive 모델은 자본 공유 미반영 → over-optimistic 가능성. PASS 시에도 integrated 모델 재검증 권고.

**How to apply**:
- <verdict 에 따라 paper trial / integrated 재검증 / MV-G 권고>
```

---

## Self-Review

### 1. Spec coverage
- ✓ 3 strategy best param 정의 (Task 1 STRATEGY_BUILDERS)
- ✓ Stage 1 equity cache (Task 1)
- ✓ Stage 2 simplex weight sweep (Task 2 simplex_weights)
- ✓ Additive 모델 (Task 2 run_stage2 formula)
- ✓ G1~G5 평가 (Task 4 write_summary)
- ✓ Simplex triangle heatmap (Task 4 plot_portfolio_allocation)
- ✓ Smoke run (Task 3)
- ✓ 사람 판정 + memory (Task 6)

### 2. Placeholder scan
- Task 6 Step 2/3 의 `<...>` 는 결과 의존이라 채울 수밖에 없는 부분. 사용자 보고 후 결과 채움.

### 3. Type consistency
- `STRATEGY_BUILDERS` / `EQUITY_CACHE_DIR` / `REPORT_DIR` / `PA_DIR` 명명 일관
- `simplex_weights` 반환 tuple float — Task 2 stage2 와 Task 4 plot 에서 동일 형식
- corner cell 검증 (1, 0, 0) Task 3/5 동일
