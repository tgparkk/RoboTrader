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


def main():
    if (PG_DIR / "cells.csv").exists():
        plot_param_grid()
        write_param_grid_summary()
    if (EO_DIR / "cells.csv").exists():
        plot_exit_overlay()
        write_exit_overlay_summary()


if __name__ == "__main__":
    main()
