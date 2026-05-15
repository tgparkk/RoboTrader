# MV-E: fold2-robust 진입 전략 발굴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 7 strategy (gap_down_reversal / rsi_oversold / bb_lower_bounce / vwap_bounce / closing_drift / breakout_52w / trend_followthrough) 를 macd_cross 와 동일한 4-fold + OOS 멀티버스 인프라에 얹어 fold2 (2025-11~12 KOSDAQ 약세) 견고 strategy 1개 이상 발굴.

**Architecture:** 새 strategy 코드 없음 — 기존 strategy 클래스를 그대로 import. 신규 runner 1개 (`backtests/multiverse/fold2_robust_survey_mv.py`) 가 7 strategy × ~270 cells × 4 datasets = 1080 eval 실행 후 cells.csv 저장. plot/summary 함수는 기존 `plot_macd_cross_mv.py` 확장. 6 게이트 (G1~G6) 자동 평가 + PASS/PORTFOLIO/FAIL 판정.

**Tech Stack:** Python 3.9, pandas, numpy, matplotlib (Agg backend). 기존 `backtests/multiverse/macd_cross_mv_common.py` 의 `load_all_datasets`, `Dataset`, `build_cell_kpis`, `_trading_days_count` 재사용. `backtests/common/engine.BacktestEngine`.

**Spec:** docs/superpowers/specs/2026-05-14-fold2-robust-survey-design.md

**예상 실행시간**: 본 시뮬 ~75분 (MV-D 232 eval 16분 비례), 전체 task 완료 1.5~2시간.

---

## File Structure

| 파일 | 역할 |
|------|------|
| `backtests/multiverse/fold2_robust_survey_mv.py` (신규) | runner — 7 strategy 셀 정의 + 평가 루프 + cells.csv writer |
| `backtests/multiverse/plot_macd_cross_mv.py` (수정) | `FR_DIR` + `plot_fold2_robust_survey()` + `write_fold2_robust_survey_summary()` + `main()` 분기 |
| `backtests/reports/fold2_robust_survey/` (산출) | cells.csv + summary.md + heatmaps/ + run log |
| `C:\Users\sttgp\.claude\projects\D--GIT-RoboTrader\memory\project_macd_cross_paper.md` | MV-E 결론 섹션 추가 (Task 8) |

**변경 금지** (라이브 동등성):
- `backtests/strategies/{gap_down_reversal,rsi_oversold,bb_lower_bounce,vwap_bounce,closing_drift,breakout_52w,trend_followthrough,macd_cross,macd_cross_signal}.py`
- `backtests/common/{engine,execution_model}.py`

---

## Task 1: Runner skeleton + 7 strategy 셀 정의

**Files:**
- Create: `backtests/multiverse/fold2_robust_survey_mv.py`

- [ ] **Step 1: Create runner skeleton with 7 strategy cells**

```python
"""MV-E: fold2-robust 진입 전략 발굴 멀티버스.

7 strategy × ~270 cells × 4 datasets = ~1080 evaluation.

Spec: docs/superpowers/specs/2026-05-14-fold2-robust-survey-design.md
"""
import argparse
import csv
import itertools
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Type

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.base import StrategyBase
from backtests.strategies.bb_lower_bounce import BBLowerBounceStrategy
from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.closing_drift import ClosingDriftStrategy
from backtests.strategies.gap_down_reversal import GapDownReversalStrategy
from backtests.strategies.rsi_oversold import RSIOversoldStrategy
from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy
from backtests.strategies.vwap_bounce import VWAPBounceStrategy


REPORT_DIR = Path("backtests/reports/fold2_robust_survey")


def _gap_down_reversal_cells() -> List[Dict]:
    cells = []
    for gap in [-1.0, -1.5, -2.0, -3.0]:
        for rev in [0.5, 1.0, 1.5]:
            for tp in [1.5, 2.5, 3.5, 5.0]:
                cells.append({
                    "strategy_name": "gap_down_reversal",
                    "cell_label": f"gap{gap:+.1f}_rev{rev:.1f}_tp{tp:.1f}",
                    "kwargs": {
                        "gap_threshold_pct": gap,
                        "reversal_threshold_pct": rev,
                        "take_profit_pct": tp,
                    },
                })
    return cells


def _rsi_oversold_cells() -> List[Dict]:
    cells = []
    for ov in [20.0, 25.0, 30.0, 35.0]:
        for tp in [1.5, 2.0, 3.0]:
            for sl in [-1.0, -1.5, -2.0, -2.5]:
                cells.append({
                    "strategy_name": "rsi_oversold",
                    "cell_label": f"ov{ov:.0f}_tp{tp:.1f}_sl{sl:.1f}",
                    "kwargs": {
                        "oversold_threshold": ov,
                        "take_profit_pct": tp,
                        "stop_loss_pct": sl,
                    },
                })
    return cells


def _bb_lower_bounce_cells() -> List[Dict]:
    cells = []
    for ns in [1.5, 2.0, 2.5]:
        for tp in [1.5, 2.5, 3.5]:
            for sl in [-1.0, -1.5, -2.0, -2.5]:
                cells.append({
                    "strategy_name": "bb_lower_bounce",
                    "cell_label": f"ns{ns:.1f}_tp{tp:.1f}_sl{sl:.1f}",
                    "kwargs": {
                        "bb_num_std": ns,
                        "take_profit_pct": tp,
                        "stop_loss_pct": sl,
                    },
                })
    return cells


def _vwap_bounce_cells() -> List[Dict]:
    cells = []
    for dev in [-0.5, -1.0, -1.5, -2.0]:
        for tp in [1.5, 2.0, 3.0]:
            for sl in [-1.0, -1.5, -2.0, -2.5]:
                cells.append({
                    "strategy_name": "vwap_bounce",
                    "cell_label": f"dev{dev:.1f}_tp{tp:.1f}_sl{sl:.1f}",
                    "kwargs": {
                        "vwap_deviation_pct": dev,
                        "take_profit_pct": tp,
                        "stop_loss_pct": sl,
                    },
                })
    return cells


def _closing_drift_cells() -> List[Dict]:
    cells = []
    windows = [(1400, 1420), (1430, 1450), (1400, 1500)]
    for body in [0.5, 1.0, 2.0]:
        for decl in [-1.5, -2.5, -3.5]:
            for (hs, he) in windows:
                cells.append({
                    "strategy_name": "closing_drift",
                    "cell_label": f"body{body:.1f}_decl{decl:.1f}_w{hs}_{he}",
                    "kwargs": {
                        "min_prev_body_pct": body,
                        "max_day_decline_pct": decl,
                        "entry_hhmm_start": hs,
                        "entry_hhmm_end": he,
                    },
                })
    return cells


def _breakout_52w_cells() -> List[Dict]:
    cells = []
    for lb in [60, 120, 252]:
        for bf in [0.0, 0.3, 0.6]:
            for hh in [1430, 1450, 1500]:
                cells.append({
                    "strategy_name": "breakout_52w",
                    "cell_label": f"lb{lb}_bf{bf:.1f}_hh{hh}",
                    "kwargs": {
                        "lookback_days": lb,
                        "buffer_pct": bf,
                        "entry_hhmm_min": hh,
                    },
                })
    return cells


def _trend_followthrough_cells() -> List[Dict]:
    cells = []
    for lb in [3, 5, 10, 20]:
        for bf in [0.0, 0.3, 0.6]:
            for hh in [1430, 1450, 1500]:
                cells.append({
                    "strategy_name": "trend_followthrough",
                    "cell_label": f"lb{lb}_bf{bf:.1f}_hh{hh}",
                    "kwargs": {
                        "lookback_days": lb,
                        "buffer_pct": bf,
                        "entry_hhmm_min": hh,
                    },
                })
    return cells


STRATEGY_CLASSES: Dict[str, Type[StrategyBase]] = {
    "gap_down_reversal": GapDownReversalStrategy,
    "rsi_oversold": RSIOversoldStrategy,
    "bb_lower_bounce": BBLowerBounceStrategy,
    "vwap_bounce": VWAPBounceStrategy,
    "closing_drift": ClosingDriftStrategy,
    "breakout_52w": Breakout52wStrategy,
    "trend_followthrough": TrendFollowthroughStrategy,
}


CELLS: List[Dict] = (
    _gap_down_reversal_cells()
    + _rsi_oversold_cells()
    + _bb_lower_bounce_cells()
    + _vwap_bounce_cells()
    + _closing_drift_cells()
    + _breakout_52w_cells()
    + _trend_followthrough_cells()
)


REASON_KEYS = ("hold_limit", "tp", "sl", "eod_forced")


def _exit_reason_dist(trades) -> Dict[str, float]:
    if not trades:
        return {k: 0.0 for k in REASON_KEYS}
    cnt = Counter(t["reason"] for t in trades)
    total = len(trades)
    return {k: cnt.get(k, 0) / total for k in REASON_KEYS}


def _evaluate(strategy, dataset: Dataset, initial_capital: float = 10_000_000) -> Dict:
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
    kpis.update({f"reason_{k}": v for k, v in _exit_reason_dist(result.trades).items()})
    return kpis


def _fields() -> List[str]:
    return [
        "strategy_name", "cell_label", "dataset", "param_json",
        "calmar", "return", "mdd", "trades", "win_rate",
        "top1_share", "max_consec_loss", "monthly_trades",
        *(f"reason_{k}" for k in REASON_KEYS),
    ]


def main(smoke: bool = False):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    cells = CELLS
    if smoke:
        cells = [CELLS[0], CELLS[48], CELLS[96], CELLS[132]]  # 1 cell per first 4 strategies

    print("[MV-E] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()
    if smoke:
        datasets = {"fold1": datasets["fold1"]}

    total = len(cells) * len(datasets)
    print(f"[MV-E] {len(cells)} cells × {len(datasets)} datasets = {total} evaluations"
          f"{' (SMOKE)' if smoke else ''}")

    out_path = REPORT_DIR / ("smoke_cells.csv" if smoke else "cells.csv")
    import json
    t0 = time.time()
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_fields())
        writer.writeheader()
        for ci, cell in enumerate(cells, 1):
            cls = STRATEGY_CLASSES[cell["strategy_name"]]
            for ds_name, ds in datasets.items():
                strat = cls(**cell["kwargs"])
                kpis = _evaluate(strat, ds)
                row = {
                    "strategy_name": cell["strategy_name"],
                    "cell_label": cell["cell_label"],
                    "dataset": ds_name,
                    "param_json": json.dumps(cell["kwargs"], separators=(",", ":")),
                    **{k: kpis.get(k) for k in (
                        "calmar", "return", "mdd", "trades", "win_rate",
                        "top1_share", "max_consec_loss", "monthly_trades",
                    )},
                    **{f"reason_{k}": kpis.get(f"reason_{k}", 0.0) for k in REASON_KEYS},
                }
                writer.writerow(row)
            elapsed = time.time() - t0
            print(f"  cell {ci:>3}/{len(cells)} "
                  f"[{cell['strategy_name']:>20}/{cell['cell_label']}] "
                  f"({elapsed:.0f}s)")

    print(f"[MV-E] saved → {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="4 cell × 1 dataset 빠른 sanity 실행")
    args = parser.parse_args()
    main(smoke=args.smoke)
```

- [ ] **Step 2: Verify imports work**

Run:
```bash
python -c "from backtests.multiverse.fold2_robust_survey_mv import CELLS, STRATEGY_CLASSES; print(f'cells={len(CELLS)} strategies={list(STRATEGY_CLASSES.keys())}')"
```
Expected:
```
cells=270 strategies=['gap_down_reversal', 'rsi_oversold', 'bb_lower_bounce', 'vwap_bounce', 'closing_drift', 'breakout_52w', 'trend_followthrough']
```

- [ ] **Step 3: Commit**

```bash
git add backtests/multiverse/fold2_robust_survey_mv.py
git commit -m "feat(mv): MV-E fold2-robust survey runner (7 strategy / 270 cells)"
```

---

## Task 2: Smoke run

- [ ] **Step 1: Run smoke**

Run:
```bash
python -m backtests.multiverse.fold2_robust_survey_mv --smoke
```
Expected (in ~30~60s):
- Output: `[MV-E] 4 cells × 1 datasets = 4 evaluations (SMOKE)`
- Output: 4 cell lines with elapsed times
- Output: `[MV-E] saved → backtests\reports\fold2_robust_survey\smoke_cells.csv`

- [ ] **Step 2: Verify smoke CSV**

Run:
```bash
python -c "
import pandas as pd
df = pd.read_csv('backtests/reports/fold2_robust_survey/smoke_cells.csv')
print(f'rows: {len(df)}')
print(df[['strategy_name','cell_label','dataset','calmar','trades']].to_string())
reason_cols = [c for c in df.columns if c.startswith('reason_')]
df['rsum'] = df[reason_cols].sum(axis=1)
nz = df[df['trades']>0]
print(f'reason_sum (trades>0): min={nz.rsum.min():.4f} max={nz.rsum.max():.4f}')
"
```
Expected:
- rows: 4 (1 cell × 4 strategies × 1 dataset)
- reason_sum: 1.0000~1.0000 for trades>0 rows
- calmar/trades: 비어있지 않은 숫자

- [ ] **Step 3: Commit smoke output**

Smoke output is in reports/ directory (already gitignored or tracked depending on repo policy). No code commit needed — proceed to next task.

---

## Task 3: plot 함수 추가 (plot_fold2_robust_survey)

**Files:**
- Modify: `backtests/multiverse/plot_macd_cross_mv.py`

- [ ] **Step 1: Add FR_DIR constant**

Modify `backtests/multiverse/plot_macd_cross_mv.py` near the top, where other `*_DIR` constants are defined. Find this block:

```python
PG_DIR = Path("backtests/reports/macd_cross_mv/param_grid")
EO_DIR = Path("backtests/reports/macd_cross_mv/exit_overlay")
RF_DIR = Path("backtests/reports/macd_cross_mv/regime_filter")
RFv2_DIR = Path("backtests/reports/macd_cross_mv/regime_filter_v2")
ER2_DIR = Path("backtests/reports/macd_cross_mv/exit_regime_v2")
```

Add at the end of this block:

```python
FR_DIR = Path("backtests/reports/fold2_robust_survey")
```

- [ ] **Step 2: Add plot_fold2_robust_survey() function**

Append at the end of `backtests/multiverse/plot_macd_cross_mv.py`, BEFORE the `def main():` definition:

```python
def plot_fold2_robust_survey():
    """Per-strategy heatmap of calmar — fold2 colored vs other folds.

    각 strategy 의 sweep dim 중 2개를 선택해 fold2 calmar heatmap 1장 +
    4ds-avg calmar heatmap 1장 = strategy 당 2장.
    """
    import json
    df = pd.read_csv(FR_DIR / "cells.csv")
    out = FR_DIR / "heatmaps"
    out.mkdir(exist_ok=True)

    # 각 strategy 마다 cells.csv 의 param_json 으로부터 첫 2개 키를 x/y 축으로 추출
    for sname in df["strategy_name"].unique():
        sub = df[df["strategy_name"] == sname].copy()
        if sub.empty:
            continue
        # 첫 row 의 param_json 키로 sweep dim 파악
        param_keys = list(json.loads(sub.iloc[0]["param_json"]).keys())
        if len(param_keys) < 2:
            continue
        x_key, y_key = param_keys[0], param_keys[1]
        # 각 cell 에 x/y 값 컬럼 추가
        sub["x_val"] = sub["param_json"].apply(lambda s: json.loads(s)[x_key])
        sub["y_val"] = sub["param_json"].apply(lambda s: json.loads(s)[y_key])
        # fold2 only
        f2 = sub[sub["dataset"] == "fold2"]
        if not f2.empty:
            avg = f2.groupby(["x_val", "y_val"]).agg(calmar=("calmar", "mean")).reset_index()
            fig, ax = plt.subplots(figsize=(7, 5))
            _heatmap(ax, avg, "x_val", "y_val", "calmar",
                     f"{sname} fold2 calmar — {x_key} × {y_key}")
            fig.tight_layout()
            fig.savefig(out / f"{sname}_fold2_calmar.png", dpi=110)
            plt.close(fig)
        # 4ds avg
        avg4 = sub.groupby(["x_val", "y_val"]).agg(calmar=("calmar", "mean")).reset_index()
        fig, ax = plt.subplots(figsize=(7, 5))
        _heatmap(ax, avg4, "x_val", "y_val", "calmar",
                 f"{sname} 4ds-avg calmar — {x_key} × {y_key}")
        fig.tight_layout()
        fig.savefig(out / f"{sname}_4ds_calmar.png", dpi=110)
        plt.close(fig)

    print(f"[plot] fold2_robust_survey heatmaps → {out}")
```

- [ ] **Step 3: Verify plot function imports cleanly**

Run:
```bash
python -c "from backtests.multiverse.plot_macd_cross_mv import plot_fold2_robust_survey; print('OK')"
```
Expected:
```
OK
```

- [ ] **Step 4: Commit**

```bash
git add backtests/multiverse/plot_macd_cross_mv.py
git commit -m "feat(mv): plot_fold2_robust_survey heatmap helper"
```

---

## Task 4: write_fold2_robust_survey_summary() + main() 분기

**Files:**
- Modify: `backtests/multiverse/plot_macd_cross_mv.py`

- [ ] **Step 1: Add write_fold2_robust_survey_summary() function**

Append at the end of `backtests/multiverse/plot_macd_cross_mv.py`, BEFORE `def main()`:

```python
def write_fold2_robust_survey_summary():
    """G1~G6 자동 평가 + PASS/PORTFOLIO/FAIL 판정 + per-strategy best.

    G1: fold2 calmar > 10
    G2: fold1/3/oos calmar 모두 > 30
    G3: 4ds-avg calmar > 30
    G4: monthly_trades 5~30 (4ds avg)
    G5: top1_share < 0.6 (each fold max)
    G6: max_consec_loss ≤ 5 (each fold max)
    """
    df = pd.read_csv(FR_DIR / "cells.csv")

    rows = []
    for (sname, clabel), grp in df.groupby(["strategy_name", "cell_label"]):
        ds_calmar = grp.set_index("dataset")["calmar"]
        ds_trades = grp.set_index("dataset")["trades"]
        ds_top1 = grp.set_index("dataset")["top1_share"]
        ds_mcl = grp.set_index("dataset")["max_consec_loss"]
        ds_mt = grp.set_index("dataset")["monthly_trades"]

        f1 = float(ds_calmar.get("fold1", 0.0))
        f2 = float(ds_calmar.get("fold2", 0.0))
        f3 = float(ds_calmar.get("fold3", 0.0))
        oos = float(ds_calmar.get("oos", 0.0))
        avg = (f1 + f2 + f3 + oos) / 4.0

        g1 = f2 > 10.0
        g2 = f1 > 30.0 and f3 > 30.0 and oos > 30.0
        g3 = avg > 30.0
        mt_avg = float(ds_mt.mean()) if len(ds_mt) else 0.0
        g4 = 5.0 <= mt_avg <= 30.0
        top1_max = float(ds_top1.max()) if len(ds_top1) else 1.0
        g5 = top1_max < 0.6
        mcl_max = int(ds_mcl.max()) if len(ds_mcl) else 99
        g6 = mcl_max <= 5

        primary = g1 and g2
        secondary_count = int(g3) + int(g4) + int(g5) + int(g6)
        gate_score = int(g1) + int(g2) + secondary_count

        # PASS / PORTFOLIO 후보 / FAIL 분류
        if g1 and g2 and secondary_count >= 3:
            verdict = "PASS"
        elif (not g1) and g2 and secondary_count >= 3:
            verdict = "PORTFOLIO"
        else:
            verdict = "FAIL"

        rows.append({
            "strategy": sname, "cell_label": clabel,
            "fold1": f1, "fold2": f2, "fold3": f3, "oos": oos, "avg": avg,
            "trades_avg": float(ds_trades.mean()) if len(ds_trades) else 0.0,
            "monthly_trades_avg": mt_avg,
            "top1_max": top1_max, "mcl_max": mcl_max,
            "G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6,
            "gate_score": gate_score, "verdict": verdict,
        })

    res = pd.DataFrame(rows).sort_values(
        ["verdict", "gate_score", "fold2"], ascending=[True, False, False],
    ).reset_index(drop=True)
    # verdict 정렬 우선순위: PASS > PORTFOLIO > FAIL
    verdict_order = {"PASS": 0, "PORTFOLIO": 1, "FAIL": 2}
    res = res.sort_values(
        by=["verdict", "gate_score", "fold2"],
        key=lambda s: s.map(verdict_order) if s.name == "verdict" else s,
        ascending=[True, False, False],
    ).reset_index(drop=True)

    body = ["# MV-E fold2_robust_survey summary\n"]
    body.append("## macd_cross baseline (비교용)\n")
    body.append("- stage2_best 4ds-avg calmar = **65.44** (fold1=36.43, fold2=-2.80, fold3=182.46, oos=45.67)")
    body.append("- mva_global_best 4ds-avg calmar = **127.69** (fold1=103.74, fold2=-1.31, fold3=289.15, oos=119.19)")
    body.append("- macd_cross fold2 calmar **< 0** — 본 멀티버스가 발굴할 fold2-robust 의 기준")

    body.append("\n## Gate 정의\n")
    body.append("- **G1** fold2 calmar > 10 (macd_cross fold2 -2.80 보다 명백 우월)")
    body.append("- **G2** fold1/3/oos calmar 모두 > 30 (다른 시기 acceptable)")
    body.append("- **G3** 4ds-avg calmar > 30")
    body.append("- **G4** monthly_trades (4ds avg) 5~30 (운영 가능 수준)")
    body.append("- **G5** top1_share (각 fold 최댓값) < 0.6 (cherry-pick 회피)")
    body.append("- **G6** max_consec_loss (각 fold 최댓값) ≤ 5")
    body.append("- 판정: PASS (G1+G2 + 보조 ≥3) / PORTFOLIO (G2+보조 ≥3, G1 미달) / FAIL")

    # Per-strategy best
    body.append("\n## Per-strategy best cell (verdict, gate_score, fold2 desc)\n")
    per_best = []
    for sname in res["strategy"].unique():
        sub = res[res["strategy"] == sname]
        if not sub.empty:
            per_best.append(sub.iloc[0])
    if per_best:
        body.append(pd.DataFrame(per_best)[[
            "strategy", "cell_label", "verdict", "gate_score",
            "fold1", "fold2", "fold3", "oos", "avg",
            "monthly_trades_avg", "top1_max", "mcl_max",
        ]].to_markdown(index=False, floatfmt=".2f"))

    # PASS + PORTFOLIO cells (있으면)
    pass_cells = res[res["verdict"] == "PASS"]
    portfolio_cells = res[res["verdict"] == "PORTFOLIO"]
    if not pass_cells.empty:
        body.append(f"\n## PASS cells ({len(pass_cells)}건)\n")
        body.append(pass_cells[[
            "strategy", "cell_label", "fold1", "fold2", "fold3", "oos",
            "avg", "monthly_trades_avg", "top1_max", "mcl_max",
        ]].to_markdown(index=False, floatfmt=".2f"))
    if not portfolio_cells.empty:
        body.append(f"\n## PORTFOLIO 후보 cells ({len(portfolio_cells)}건)\n")
        body.append(portfolio_cells.head(20)[[
            "strategy", "cell_label", "fold1", "fold2", "fold3", "oos",
            "avg", "monthly_trades_avg", "top1_max", "mcl_max",
        ]].to_markdown(index=False, floatfmt=".2f"))

    # fold2 top 20
    body.append("\n## fold2 calmar top 20 cells (전체)\n")
    top_f2 = res.sort_values("fold2", ascending=False).head(20)
    body.append(top_f2[[
        "strategy", "cell_label", "verdict", "fold1", "fold2", "fold3", "oos",
        "monthly_trades_avg", "top1_max",
    ]].to_markdown(index=False, floatfmt=".2f"))

    # 종합
    body.append("\n## 종합 판정")
    if not pass_cells.empty:
        best = pass_cells.iloc[0]
        body.append(
            f"\n**PASS** — `{best['strategy']}/{best['cell_label']}` "
            f"(fold2={best['fold2']:+.2f}, avg={best['avg']:+.2f}, "
            f"gate_score={int(best['gate_score'])}). "
            f"Paper 30일 검증 권고."
        )
    elif not portfolio_cells.empty:
        best = portfolio_cells.iloc[0]
        body.append(
            f"\n**PORTFOLIO 후보 발견** — `{best['strategy']}/{best['cell_label']}` "
            f"(fold2={best['fold2']:+.2f}, avg={best['avg']:+.2f}). "
            f"G1 미충족이나 G2 + 보조 통과. macd_cross 와 시기별 보완 검토."
        )
    else:
        body.append(
            "\n**FAIL** — G1+G2 동시 통과 cell 없음. 17 strategy 자산으로 "
            "fold2 견고 + 다른 fold 도 강한 family 부재. MV-F (신규 family 설계) 권고."
        )

    body.append("\nheatmaps/ 와 cells.csv 함께 검토.")
    (FR_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
    print(f"[summary] {FR_DIR / 'summary.md'}")
```

- [ ] **Step 2: Add main() branch for FR_DIR**

Find the `def main():` definition near the bottom of `backtests/multiverse/plot_macd_cross_mv.py`. It currently ends with:

```python
    if (ER2_DIR / "cells.csv").exists():
        plot_exit_regime_v2()
        write_exit_regime_v2_summary()


if __name__ == "__main__":
    main()
```

Add a new branch before `if __name__ == "__main__":`:

```python
    if (FR_DIR / "cells.csv").exists():
        plot_fold2_robust_survey()
        write_fold2_robust_survey_summary()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify imports**

Run:
```bash
python -c "from backtests.multiverse.plot_macd_cross_mv import write_fold2_robust_survey_summary, plot_fold2_robust_survey; print('OK')"
```
Expected:
```
OK
```

- [ ] **Step 4: Commit**

```bash
git add backtests/multiverse/plot_macd_cross_mv.py
git commit -m "feat(mv): plot_fold2_robust_survey summary + G1~G6 gates"
```

---

## Task 5: 본 시뮬 실행 (background, ~75분)

- [ ] **Step 1: Launch full sim in background**

Run:
```bash
python -m backtests.multiverse.fold2_robust_survey_mv 2>&1 | tee backtests/reports/fold2_robust_survey/fold2_robust_survey_run.log
```

Use the agent's run_in_background option. Expected log line pattern: `cell 1/270 [...]` to `cell 270/270 [...]` over ~75 minutes.

- [ ] **Step 2: Wait for completion (notification 받을 때까지 대기)**

When the background task completes, verify:
```bash
tail -10 backtests/reports/fold2_robust_survey/fold2_robust_survey_run.log
```
Expected last line:
```
[MV-E] saved → backtests\reports\fold2_robust_survey\cells.csv (NNNNs)
```

- [ ] **Step 3: Verify cells.csv row count + reason sums**

Run:
```bash
python -c "
import pandas as pd
df = pd.read_csv('backtests/reports/fold2_robust_survey/cells.csv')
print(f'rows: {len(df)} (expect 1080 = 270 cells x 4 datasets)')
reason_cols = [c for c in df.columns if c.startswith('reason_')]
df['rsum'] = df[reason_cols].sum(axis=1)
nz = df[df['trades']>0]
print(f'trades>0 rows: {len(nz)}')
print(f'reason_sum (trades>0): min={nz.rsum.min():.4f} max={nz.rsum.max():.4f}')
# fold2 양수 개수
f2pos = df[(df['dataset']=='fold2') & (df['calmar']>10)]
print(f'fold2 calmar>10 cells: {len(f2pos)} (potential PASS G1)')
"
```
Expected:
- rows: 1080
- reason_sum: 1.0000~1.0000 for trades>0 rows

---

## Task 6: 리포트 생성 (heatmaps + summary.md)

- [ ] **Step 1: Run plot module**

Run:
```bash
python -m backtests.multiverse.plot_macd_cross_mv
```
Expected output (last 2 lines):
```
[plot] fold2_robust_survey heatmaps → backtests\reports\fold2_robust_survey\heatmaps
[summary] backtests\reports\fold2_robust_survey\summary.md
```

- [ ] **Step 2: Verify heatmaps**

Run:
```bash
python -c "
import os
files = sorted(os.listdir('backtests/reports/fold2_robust_survey/heatmaps'))
print(f'heatmap count: {len(files)}')
for f in files: print(f)
"
```
Expected:
- 14 heatmap files (7 strategy × 2 = fold2 + 4ds)

- [ ] **Step 3: Read summary.md to confirm structure**

Run:
```bash
head -50 backtests/reports/fold2_robust_survey/summary.md
```
Expected: section headers visible — `# MV-E fold2_robust_survey summary` / `## macd_cross baseline (비교용)` / `## Gate 정의` / `## Per-strategy best cell` / `## 종합 판정`

---

## Task 7: 사람 판정 + memory 업데이트

**Files:**
- Modify: `backtests/reports/fold2_robust_survey/summary.md` (사람 보강 결론 섹션 추가)
- Modify: `C:\Users\sttgp\.claude\projects\D--GIT-RoboTrader\memory\project_macd_cross_paper.md`

- [ ] **Step 1: 사람 판정 — summary.md 읽기 + 사용자에게 결과 요약 보고**

Read the full summary.md. Identify:
1. 종합 판정 (PASS / PORTFOLIO / FAIL)
2. fold2 calmar 최고 strategy/cell (top 1)
3. 각 strategy 의 best cell verdict 표 요약

이 정보를 텍스트 메시지로 사용자에게 보고 (예: "PASS 0건, PORTFOLIO 3건 발견 — rsi_oversold ov30_tp2.0_sl-1.5 가 최고 ...").

- [ ] **Step 2: Append "사람 보강 결론" section to summary.md**

Use Edit tool to append to `backtests/reports/fold2_robust_survey/summary.md`. The exact text depends on results from Step 1. Template:

```markdown

## 사람 보강 결론 (2026-05-14)

### 자동 평가 결과
- 1080 evaluation (7 strategy × ~270 cells × 4 datasets)
- PASS: <N>건 / PORTFOLIO: <N>건 / FAIL 다수

### 핵심 발견
<best cell 분석 + macd_cross 와 비교 + 운영 가능성 평가>

### 다음 단계
<PASS 시 paper 30일 trial 권고 / PORTFOLIO 시 macd_cross 와 자본 분배 검토 / FAIL 시 MV-F (신규 family) 권고>
```

- [ ] **Step 3: Update memory file**

Edit `C:\Users\sttgp\.claude\projects\D--GIT-RoboTrader\memory\project_macd_cross_paper.md`. After the MV-D section, append:

```markdown

## MV-E 결론 (2026-05-14, fold2-robust survey)

**Spec**: docs/superpowers/specs/2026-05-14-fold2-robust-survey-design.md
**Plan**: docs/superpowers/plans/2026-05-14-fold2-robust-survey.md
**산출물**: backtests/reports/fold2_robust_survey/{summary.md, cells.csv, heatmaps/}
**스코프**: 기존 7 strategy 재평가 (gap_down_reversal / rsi_oversold / bb_lower_bounce / vwap_bounce / closing_drift / breakout_52w / trend_followthrough) × ~270 cells × 4 dataset = 1080 eval.

**결과**: <PASS / PORTFOLIO / FAIL — Task 7 Step 1 결과 기록>

**Why**: macd_cross fold2 unrecoverable (MV-A~D) → 외부 strategy 발굴 시도.

**How to apply**:
- <verdict 에 따라 paper 30일 trial / macd_cross + portfolio 검토 / MV-F 권고>
```

- [ ] **Step 4: Commit results + memory**

```bash
git add backtests/reports/fold2_robust_survey/
git add docs/superpowers/specs/2026-05-14-fold2-robust-survey-design.md
git add docs/superpowers/plans/2026-05-14-fold2-robust-survey.md
git commit -m "data(mv): MV-E fold2-robust survey 결과 (7 strategy / 1080 eval)"
```

(memory 파일은 .claude 디렉토리라 git 추적 대상 아님 — 별도 commit 불필요.)

---

## Task 8: 후속 결정 (사용자 협의)

- [ ] **Step 1: 결과에 따른 다음 단계 사용자 협의**

verdict 별 분기:
- **PASS**: paper 30일 trial spec/plan 작성 (별도 사이클) — paper 자본 분배, macd_cross 와 동시 운영 모드, paper 종료 게이트 등
- **PORTFOLIO**: 자본 분배 멀티버스 별도 (e.g. macd_cross 0.5 + portfolio_cand 0.5 vs 0.7+0.3 등)
- **FAIL**: MV-F (신규 family — ML 시그널 또는 multi-stock interaction) 브레인스토밍 새 사이클

→ 사용자와 verdict 보고 다음 사이클 결정.

---

## Self-Review (작성 후 점검)

### 1. Spec coverage
- ✓ 7 strategy 평가 (Task 1)
- ✓ G1~G6 자동 평가 (Task 4)
- ✓ PASS/PORTFOLIO/FAIL 분류 (Task 4)
- ✓ heatmaps + summary 출력 구조 (Task 3, 4)
- ✓ 사람 판정 + memory (Task 7)
- ✓ commit 단계 (각 Task)

### 2. Placeholder scan
- Task 7 Step 2 의 "<best cell 분석>" 등은 결과 의존이라 어쩔 수 없는 placeholder — 실행 시점에 채워야 함. 명시.
- 그 외 코드 블록은 완전한 코드.

### 3. Type consistency
- `cell["strategy_name"]` / `cell["cell_label"]` / `cell["kwargs"]` — Task 1 정의, Task 2/3/4 에서 동일 사용.
- `REASON_KEYS` 와 `reason_<k>` 컬럼 명명 일관.
- `FR_DIR` / `STRATEGY_CLASSES` / `CELLS` — Task 1 export, Task 3/4 사용.
