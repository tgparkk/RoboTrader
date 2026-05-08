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
