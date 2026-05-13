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
RF_DIR = Path("backtests/reports/macd_cross_mv/regime_filter")
RFv2_DIR = Path("backtests/reports/macd_cross_mv/regime_filter_v2")


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


def _heatmap_signal_dataset(pivot, out_path, title, center=None):
    """signal × dataset heatmap 1장 → PNG.

    Args:
        pivot: pd.DataFrame, index=signal_label, columns=dataset, value=숫자.
        center: 색 중심값 (None = 자동 min~max, 0 = diverging cmap).
    """
    fig, ax = plt.subplots(figsize=(8, max(4, 0.5 * len(pivot.index) + 1)))
    finite_vals = pivot.values[~np.isnan(pivot.values)]
    if center is not None and finite_vals.size > 0:
        vmax = max(abs(finite_vals.min()), abs(finite_vals.max()), 1.0)
        im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn",
                       vmin=-vmax, vmax=vmax)
    else:
        im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=9)
    ax.set_title(title)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:+.1f}" if center is not None else f"{v:.1f}",
                        ha="center", va="center", fontsize=8, color="black")
    plt.colorbar(im, ax=ax, fraction=0.04)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def plot_regime_filter_v2():
    df = pd.read_csv(RFv2_DIR / "cells.csv")
    out = RFv2_DIR / "heatmaps"
    out.mkdir(exist_ok=True)
    signal_order = list(dict.fromkeys(df["signal_label"]))
    dataset_order = ["fold1", "fold2", "fold3", "oos"]

    for param_label in df["param_label"].unique():
        sub = df[df["param_label"] == param_label]
        pivot = sub.pivot_table(
            index="signal_label", columns="dataset",
            values="calmar", aggfunc="mean",
        )
        pivot = pivot.reindex(index=signal_order, columns=dataset_order)
        # (1) absolute
        _heatmap_signal_dataset(
            pivot, out / f"calmar_abs_{param_label}.png",
            title=f"Calmar — {param_label}", center=None,
        )
        # (2) delta vs off
        if "off" in pivot.index:
            off_row = pivot.loc["off"]
            delta = pivot.subtract(off_row, axis=1)
            _heatmap_signal_dataset(
                delta, out / f"calmar_delta_{param_label}.png",
                title=f"Calmar Δ vs off — {param_label}", center=0,
            )
    print(f"[plot] regime_filter_v2 heatmaps → {out}")


def write_regime_filter_v2_summary():
    df = pd.read_csv(RFv2_DIR / "cells.csv")
    off_df = df[df["signal_label"] == "off"]
    on_df = df[df["signal_label"] != "off"]

    off_calmar = off_df.set_index(["param_label", "dataset"])["calmar"]

    rows = []
    for (sig, param), grp in on_df.groupby(["signal_label", "param_label"]):
        ds_calmar = grp.set_index("dataset")["calmar"]
        ds_block = grp.set_index("dataset")["block_days"]
        try:
            off_for_param = off_calmar.xs(param, level="param_label")
        except KeyError:
            continue
        delta = ds_calmar - off_for_param

        f2d = float(delta.get("fold2", 0.0))
        f1d = float(delta.get("fold1", 0.0))
        f3d = float(delta.get("fold3", 0.0))
        oosd = float(delta.get("oos", 0.0))
        f1_off = float(off_for_param.get("fold1", 0.0))
        f3_off = float(off_for_param.get("fold3", 0.0))
        f1_pct = (f1d / f1_off * 100) if abs(f1_off) > 1e-6 else 0.0
        f3_pct = (f3d / f3_off * 100) if abs(f3_off) > 1e-6 else 0.0

        g1 = f2d >= 20.0
        g2 = abs(f1_pct) <= 5.0 and abs(f3_pct) <= 5.0
        g3 = oosd >= 0.0
        b_f2 = int(ds_block.get("fold2", 0))
        b_f1 = int(ds_block.get("fold1", 0))
        b_f3 = int(ds_block.get("fold3", 0))
        g4 = (b_f2 > 5) and (max(b_f1, b_f3) <= 2)
        score = int(g1) + int(g2) + int(g3) + int(g4)

        rows.append({
            "signal_label": sig, "param_label": param,
            "fold2_delta": f2d, "fold1_pct": f1_pct, "fold3_pct": f3_pct,
            "oos_delta": oosd,
            "block_f2": b_f2, "block_f1": b_f1, "block_f3": b_f3,
            "g1_f2_+20": g1, "g2_f13_5pct": g2, "g3_oos_0": g3,
            "g4_select": g4, "gate_score": score,
        })

    res = pd.DataFrame(rows).sort_values(
        ["gate_score", "fold2_delta"], ascending=[False, False],
    ).reset_index(drop=True)

    body = ["# MV-C v2 regime filter summary\n"]
    body.append("## Per-cell 4-gate evaluation\n")
    body.append("sorted by gate_score desc, fold2_delta desc.\n")
    body.append(res.to_markdown(index=False, floatfmt=".2f"))
    body.append("")

    full_pass = res[res["gate_score"] == 4]
    partial_pass = res[(res["gate_score"] >= 2) & (res["gate_score"] < 4)]
    body.append("## 종합")
    if not full_pass.empty:
        best = full_pass.iloc[0]
        body.append(
            f"\n**PASS** — `{best['signal_label']}` × `{best['param_label']}` "
            f"(gate_score=4, fold2_delta={best['fold2_delta']:+.2f}). "
            f"Phase 2 라이브 적용 검토."
        )
    elif not partial_pass.empty:
        body.append(
            f"\n**PARTIAL** — {len(partial_pass)} cell 이 2~3 gate 통과. "
            "사람 판단 필요 (trade-off 검토)."
        )
    else:
        body.append(
            "\n**FAIL** — 모든 cell 이 4-gate 통과 불가. "
            "결론: fold2 unrecoverable, paper macd_cross_alt + circuit breaker "
            "만으로 운영."
        )
    body.append("\nheatmaps/ 와 cells.csv 함께 검토.")
    (RFv2_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
    print(f"[summary] {RFv2_DIR / 'summary.md'}")


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
    if (RFv2_DIR / "cells.csv").exists():
        plot_regime_filter_v2()
        write_regime_filter_v2_summary()


if __name__ == "__main__":
    main()
