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
ER2_DIR = Path("backtests/reports/macd_cross_mv/exit_regime_v2")
FR_DIR = Path("backtests/reports/fold2_robust_survey")
PA_DIR = Path("backtests/reports/portfolio_allocation")


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


def plot_exit_regime_v2():
    df = pd.read_csv(ER2_DIR / "cells.csv")
    out = ER2_DIR / "heatmaps"
    out.mkdir(exist_ok=True)

    # Family A — trailing: trailing_pct × trailing_activate (per param × dataset 4-avg)
    famA = df[df["family"] == "trailing"].copy()
    for param in famA["param_label"].unique():
        sub = famA[famA["param_label"] == param]
        for metric, ml in [("calmar", "Calmar"), ("mdd", "MDD"),
                            ("fired_ratio", "Fired ratio")]:
            avg = sub.groupby(["trailing_pct", "trailing_activate"]).agg(
                {metric: "mean"}).reset_index()
            fig, ax = plt.subplots(figsize=(6, 4))
            _heatmap(ax, avg, "trailing_activate", "trailing_pct", metric,
                     f"Family A {ml} — {param} (4ds avg)")
            fig.tight_layout()
            fig.savefig(out / f"familyA_{metric}_{param}.png", dpi=110)
            plt.close(fig)

    # Family B — reversal: eval_hhmm × threshold per min_hold layer (per param × dataset 4-avg)
    famB = df[df["family"] == "reversal"].copy()
    # eval_hhmm 결측은 "last" 라벨로 표시 (heatmap 축용)
    famB["hhmm_label"] = famB["reversal_eval_hhmm"].apply(
        lambda x: "last" if pd.isna(x) else str(int(x))
    )
    for param in famB["param_label"].unique():
        for mh in sorted(famB["reversal_min_hold"].dropna().unique()):
            sub = famB[(famB["param_label"] == param)
                       & (famB["reversal_min_hold"] == mh)]
            for metric, ml in [("calmar", "Calmar"), ("mdd", "MDD"),
                                ("fired_ratio", "Fired ratio")]:
                avg = sub.groupby(["hhmm_label", "reversal_hist_threshold"]).agg(
                    {metric: "mean"}).reset_index()
                fig, ax = plt.subplots(figsize=(6, 4))
                _heatmap(ax, avg, "reversal_hist_threshold", "hhmm_label", metric,
                         f"Family B {ml} — {param} min_hold={int(mh)} (4ds avg)")
                fig.tight_layout()
                fig.savefig(
                    out / f"familyB_{metric}_{param}_minh{int(mh)}.png", dpi=110)
                plt.close(fig)

    # Family C — tiered SL: sl_d1 × sl_d2 (per param × dataset 4-avg)
    famC = df[df["family"] == "tiered_sl"].copy()
    famC["d1_label"] = famC["sl_d1_pct"].apply(
        lambda x: "off" if pd.isna(x) else f"{x:.2f}"
    )
    famC["d2_label"] = famC["sl_d2_pct"].apply(
        lambda x: "off" if pd.isna(x) else f"{x:.2f}"
    )
    for param in famC["param_label"].unique():
        sub = famC[famC["param_label"] == param]
        for metric, ml in [("calmar", "Calmar"), ("mdd", "MDD"),
                            ("fired_ratio", "Fired ratio")]:
            avg = sub.groupby(["d1_label", "d2_label"]).agg(
                {metric: "mean"}).reset_index()
            fig, ax = plt.subplots(figsize=(6, 4))
            _heatmap(ax, avg, "d2_label", "d1_label", metric,
                     f"Family C {ml} — {param} (4ds avg)")
            fig.tight_layout()
            fig.savefig(out / f"familyC_{metric}_{param}.png", dpi=110)
            plt.close(fig)

    print(f"[plot] exit_regime_v2 heatmaps → {out}")


def write_exit_regime_v2_summary():
    df = pd.read_csv(ER2_DIR / "cells.csv")

    off_df = df[df["family"] == "off"]
    # baseline (per param × dataset)
    off_calmar = off_df.set_index(["param_label", "dataset"])["calmar"]
    off_mdd = off_df.set_index(["param_label", "dataset"])["mdd"]
    off_trades = off_df.set_index(["param_label", "dataset"])["trades"]

    rows = []
    for (cell_label, param, family), grp in df[df["family"] != "off"].groupby(
            ["cell_label", "param_label", "family"]):
        ds_calmar = grp.set_index("dataset")["calmar"]
        ds_mdd = grp.set_index("dataset")["mdd"]
        ds_trades = grp.set_index("dataset")["trades"]
        ds_top1 = grp.set_index("dataset")["top1_share"]
        ds_fired = grp.set_index("dataset")["fired_ratio"]
        try:
            off_c = off_calmar.xs(param, level="param_label")
            off_m = off_mdd.xs(param, level="param_label")
            off_t = off_trades.xs(param, level="param_label")
        except KeyError:
            continue

        def _f(s, k):
            return float(s.get(k, 0.0)) if k in s.index else 0.0

        f2_delta = _f(ds_calmar, "fold2") - _f(off_c, "fold2")
        f1_delta = _f(ds_calmar, "fold1") - _f(off_c, "fold1")
        f3_delta = _f(ds_calmar, "fold3") - _f(off_c, "fold3")
        oos_delta = _f(ds_calmar, "oos") - _f(off_c, "oos")
        f1_off = _f(off_c, "fold1")
        f3_off = _f(off_c, "fold3")
        oos_off = _f(off_c, "oos")
        f1_pct = (f1_delta / f1_off * 100) if abs(f1_off) > 1e-6 else 0.0
        f3_pct = (f3_delta / f3_off * 100) if abs(f3_off) > 1e-6 else 0.0
        oos_pct = (oos_delta / oos_off * 100) if abs(oos_off) > 1e-6 else 0.0

        # G1: fold2 Δcalmar ≥ +10
        g1 = f2_delta >= 10.0
        # G2: fold2 MDD 감소 — cell_mdd ≥ baseline_mdd × 0.95 (mdd 음수, 95%면 절대값 5% 개선)
        f2_mdd_cell = _f(ds_mdd, "fold2")
        f2_mdd_off = _f(off_m, "fold2")
        g2 = f2_mdd_cell >= f2_mdd_off * 0.95
        # G3: fold1/3 손실 ≤ 5%
        g3 = min(f1_pct, f3_pct) >= -5.0
        # G4: fired ratio fold2 (15~70%)
        fired_f2 = float(ds_fired.get("fold2", 0.0))
        g4 = 0.15 <= fired_f2 <= 0.70
        # G5: trade count 안정성 (fold2, ±30%)
        cell_t_f2 = int(ds_trades.get("fold2", 0))
        off_t_f2 = int(off_t.get("fold2", 0))
        g5 = abs(cell_t_f2 - off_t_f2) / off_t_f2 <= 0.30 if off_t_f2 > 0 else False
        # G6: top1_share fold2 ≤ 0.6
        top1_f2 = float(ds_top1.get("fold2", 0.0))
        g6 = top1_f2 <= 0.6
        # G7: oos Δcalmar ≥ -10%
        g7 = oos_pct >= -10.0

        primary = g1 and g2 and g3
        secondary_count = int(g4) + int(g5) + int(g6) + int(g7)
        gate_score = int(g1) + int(g2) + int(g3) + secondary_count

        rows.append({
            "family": family, "cell_label": cell_label, "param_label": param,
            "fold2_delta": f2_delta, "f2_mdd_cell": f2_mdd_cell,
            "f2_mdd_off": f2_mdd_off,
            "f1_pct": f1_pct, "f3_pct": f3_pct, "oos_pct": oos_pct,
            "fired_f2": fired_f2, "top1_f2": top1_f2,
            "trades_f2": cell_t_f2, "trades_off_f2": off_t_f2,
            "G1": g1, "G2": g2, "G3": g3,
            "G4": g4, "G5": g5, "G6": g6, "G7": g7,
            "primary_pass": primary, "secondary_count": secondary_count,
            "gate_score": gate_score,
        })

    res = pd.DataFrame(rows).sort_values(
        ["gate_score", "fold2_delta"], ascending=[False, False],
    ).reset_index(drop=True)

    # per-family best (gate_score 최고)
    per_family_best = []
    for family in ["trailing", "reversal", "tiered_sl"]:
        sub = res[res["family"] == family]
        if not sub.empty:
            per_family_best.append(sub.iloc[0])

    body = ["# MV-D exit_regime_v2 summary\n"]
    body.append("## Baseline (family=off) — per param × dataset\n")
    body.append(
        off_df.pivot_table(index="param_label", columns="dataset",
                           values=["calmar", "mdd"], aggfunc="mean")
        .to_markdown(floatfmt=".2f")
    )

    body.append("\n## Per-family best cell (gate_score desc)\n")
    if per_family_best:
        body.append(pd.DataFrame(per_family_best)[[
            "family", "cell_label", "param_label", "fold2_delta",
            "f2_mdd_cell", "f1_pct", "f3_pct", "oos_pct",
            "fired_f2", "top1_f2", "gate_score",
        ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## All cells — 7-gate evaluation\n")
    body.append(res[[
        "family", "cell_label", "param_label", "fold2_delta", "f2_mdd_cell",
        "f1_pct", "f3_pct", "oos_pct", "fired_f2", "top1_f2",
        "G1", "G2", "G3", "G4", "G5", "G6", "G7",
        "primary_pass", "gate_score",
    ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## Gate 정의\n")
    body.append("- **G1** fold2 Δcalmar ≥ +10")
    body.append("- **G2** fold2 MDD 감소 (cell_mdd ≥ off_mdd × 0.95)")
    body.append("- **G3** fold1/3 손실 ≤ 5%")
    body.append("- **G4** fired ratio fold2 ∈ [15%, 70%] (cherry-pick 회피)")
    body.append("- **G5** fold2 trade count 안정성 (±30%)")
    body.append("- **G6** fold2 top1_share ≤ 0.6")
    body.append("- **G7** OOS Δcalmar 손실율 ≤ 10%")

    body.append("\n## 종합")
    passing = res[res["primary_pass"] & (res["secondary_count"] >= 3)]
    partial = res[res["primary_pass"] & (res["secondary_count"] < 3)]
    if not passing.empty:
        best = passing.iloc[0]
        body.append(
            f"\n**PASS** — `{best['family']}/{best['cell_label']}` × "
            f"`{best['param_label']}` (gate_score={best['gate_score']}, "
            f"fold2_delta={best['fold2_delta']:+.2f}). "
            f"Phase 2 paper 30일 검증 권고."
        )
    elif not partial.empty:
        body.append(
            f"\n**PARTIAL** — {len(partial)} cell 이 primary(G1+G2+G3) 통과, "
            "보조 게이트 미달. 사람 판단 필요 (trade-off 검토)."
        )
    else:
        body.append(
            "\n**FAIL** — primary gate (G1+G2+G3) 통과 cell 없음. "
            "결론: fold2 unrecoverable on exit-side as well. "
            "paper macd_cross_alt + circuit breaker only 유지."
        )

    body.append("\nheatmaps/ 와 cells.csv 함께 검토.")
    (ER2_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
    print(f"[summary] {ER2_DIR / 'summary.md'}")


def plot_fold2_robust_survey():
    """Per-strategy heatmap of calmar — fold2 + 4ds-avg.

    각 strategy 의 첫 2개 sweep dim (param_json 키) 을 x/y 로 사용.
    strategy 당 2장 (fold2, 4ds-avg) × 7 strategy = 14 PNG.
    """
    import json
    df = pd.read_csv(FR_DIR / "cells.csv")
    out = FR_DIR / "heatmaps"
    out.mkdir(exist_ok=True)

    for sname in df["strategy_name"].unique():
        sub = df[df["strategy_name"] == sname].copy()
        if sub.empty:
            continue
        param_keys = list(json.loads(sub.iloc[0]["param_json"]).keys())
        if len(param_keys) < 2:
            continue
        x_key, y_key = param_keys[0], param_keys[1]
        sub["x_val"] = sub["param_json"].apply(lambda s: json.loads(s)[x_key])
        sub["y_val"] = sub["param_json"].apply(lambda s: json.loads(s)[y_key])
        # fold2 calmar
        f2 = sub[sub["dataset"] == "fold2"]
        if not f2.empty:
            avg = f2.groupby(["x_val", "y_val"]).agg(calmar=("calmar", "mean")).reset_index()
            fig, ax = plt.subplots(figsize=(7, 5))
            _heatmap(ax, avg, "x_val", "y_val", "calmar",
                     f"{sname} fold2 calmar — {x_key} × {y_key}")
            fig.tight_layout()
            fig.savefig(out / f"{sname}_fold2_calmar.png", dpi=110)
            plt.close(fig)
        # 4ds avg calmar
        avg4 = sub.groupby(["x_val", "y_val"]).agg(calmar=("calmar", "mean")).reset_index()
        fig, ax = plt.subplots(figsize=(7, 5))
        _heatmap(ax, avg4, "x_val", "y_val", "calmar",
                 f"{sname} 4ds-avg calmar — {x_key} × {y_key}")
        fig.tight_layout()
        fig.savefig(out / f"{sname}_4ds_calmar.png", dpi=110)
        plt.close(fig)

    print(f"[plot] fold2_robust_survey heatmaps → {out}")


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

        secondary_count = int(g3) + int(g4) + int(g5) + int(g6)
        gate_score = int(g1) + int(g2) + secondary_count

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

    res = pd.DataFrame(rows)
    verdict_order = {"PASS": 0, "PORTFOLIO": 1, "FAIL": 2}
    res["_v_order"] = res["verdict"].map(verdict_order)
    res = res.sort_values(
        ["_v_order", "gate_score", "fold2"], ascending=[True, False, False],
    ).drop(columns=["_v_order"]).reset_index(drop=True)

    body = ["# MV-E fold2_robust_survey summary\n"]
    body.append("## macd_cross baseline (비교용)\n")
    body.append("- stage2_best 4ds-avg calmar = **65.44** (fold1=36.43, fold2=-2.80, fold3=182.46, oos=45.67)")
    body.append("- mva_global_best 4ds-avg calmar = **127.69** (fold1=103.74, fold2=-1.31, fold3=289.15, oos=119.19)")
    body.append("- macd_cross fold2 calmar **< 0** — 본 멀티버스가 발굴할 fold2-robust 의 기준")

    body.append("\n## Gate 정의\n")
    body.append("- **G1** fold2 calmar > 10")
    body.append("- **G2** fold1/3/oos calmar 모두 > 30")
    body.append("- **G3** 4ds-avg calmar > 30")
    body.append("- **G4** monthly_trades (4ds avg) 5~30")
    body.append("- **G5** top1_share (각 fold 최댓값) < 0.6")
    body.append("- **G6** max_consec_loss (각 fold 최댓값) ≤ 5")
    body.append("- 판정: PASS (G1+G2 + 보조 ≥3) / PORTFOLIO (G2+보조 ≥3, G1 미달) / FAIL")

    body.append("\n## Per-strategy best cell\n")
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

    body.append("\n## fold2 calmar top 20 cells (전체)\n")
    top_f2 = res.sort_values("fold2", ascending=False).head(20)
    body.append(top_f2[[
        "strategy", "cell_label", "verdict", "fold1", "fold2", "fold3", "oos",
        "monthly_trades_avg", "top1_max",
    ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## 종합 판정")
    if not pass_cells.empty:
        best = pass_cells.iloc[0]
        body.append(
            f"\n**PASS** — `{best['strategy']}/{best['cell_label']}` "
            f"(fold2={best['fold2']:+.2f}, avg={best['avg']:+.2f}, "
            f"gate_score={int(best['gate_score'])}). Paper 30일 검증 권고."
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
            "fold2 견고 + 다른 fold 도 강한 family 부재. MV-F (신규 family) 권고."
        )

    body.append("\nheatmaps/ 와 cells.csv 함께 검토.")
    (FR_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
    print(f"[summary] {FR_DIR / 'summary.md'}")


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
    if (ER2_DIR / "cells.csv").exists():
        plot_exit_regime_v2()
        write_exit_regime_v2_summary()
    if (FR_DIR / "cells.csv").exists():
        plot_fold2_robust_survey()
        write_fold2_robust_survey_summary()
    if (PA_DIR / "cells.csv").exists():
        plot_portfolio_allocation()
        write_portfolio_allocation_summary()


def plot_portfolio_allocation():
    """Simplex triangle heatmap per fold + 4ds-avg."""
    df = pd.read_csv(PA_DIR / "cells.csv")
    out = PA_DIR / "heatmaps"
    out.mkdir(exist_ok=True)

    avg4 = df.groupby(["w_macd", "w_breakout", "w_trend"]).agg(
        portfolio_calmar=("portfolio_calmar", "mean"),
        portfolio_return=("portfolio_return", "mean"),
        portfolio_mdd=("portfolio_mdd", "mean"),
    ).reset_index()

    def _tri(ws, vals, title, path):
        w_m = ws["w_macd"].values
        w_b = ws["w_breakout"].values
        x = w_b + 0.5 * w_m
        y = (np.sqrt(3) / 2) * w_m
        fig, ax = plt.subplots(figsize=(7, 6))
        tcf = ax.tricontourf(x, y, vals, levels=20, cmap="RdYlGn")
        ax.scatter(x, y, c="black", s=8)
        ax.text(0.5, np.sqrt(3) / 2 + 0.04, "macd_cross (1,0,0)",
                ha="center", fontsize=8)
        ax.text(1.04, -0.03, "breakout (0,1,0)", ha="left", fontsize=8)
        ax.text(-0.04, -0.03, "trend (0,0,1)", ha="right", fontsize=8)
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

    _tri(avg4, avg4["portfolio_calmar"].values,
         "Portfolio Calmar — 4ds avg",
         out / "portfolio_calmar_4dsavg.png")
    _tri(avg4, avg4["portfolio_mdd"].values,
         "Portfolio MDD — 4ds avg",
         out / "portfolio_mdd_4dsavg.png")
    _tri(avg4, avg4["portfolio_return"].values,
         "Portfolio Return — 4ds avg",
         out / "portfolio_return_4dsavg.png")
    for fold in ("fold1", "fold2", "fold3", "oos"):
        sub = df[df["fold"] == fold]
        _tri(sub, sub["portfolio_calmar"].values,
             f"Portfolio Calmar — {fold}",
             out / f"portfolio_calmar_{fold}.png")
    print(f"[plot] portfolio_allocation heatmaps → {out}")


def write_portfolio_allocation_summary():
    """G1~G5 자동 평가 + PASS/PARTIAL/FAIL."""
    df = pd.read_csv(PA_DIR / "cells.csv")

    macd_alone = df[(df["w_macd"] == 1.0) & (df["w_breakout"] == 0.0)]
    baseline = macd_alone.set_index("fold")
    bc_4ds = float(baseline["portfolio_calmar"].mean())
    bc_f1 = float(baseline.loc["fold1", "portfolio_calmar"])
    bc_f2 = float(baseline.loc["fold2", "portfolio_calmar"])
    bc_f3 = float(baseline.loc["fold3", "portfolio_calmar"])
    bc_oos = float(baseline.loc["oos", "portfolio_calmar"])
    bm_f2 = float(baseline.loc["fold2", "portfolio_mdd"])
    bm_4ds = float(baseline["portfolio_mdd"].mean())

    rows = []
    for (wm, wb, wt), grp in df.groupby(["w_macd", "w_breakout", "w_trend"]):
        gset = grp.set_index("fold")
        c4 = float(gset["portfolio_calmar"].mean())
        cf1 = float(gset.loc["fold1", "portfolio_calmar"])
        cf2 = float(gset.loc["fold2", "portfolio_calmar"])
        cf3 = float(gset.loc["fold3", "portfolio_calmar"])
        coos = float(gset.loc["oos", "portfolio_calmar"])
        cf2_mdd = float(gset.loc["fold2", "portfolio_mdd"])
        c4_mdd = float(gset["portfolio_mdd"].mean())

        g1 = c4 > bc_4ds
        g2a = cf2 > bc_f2
        g2b = cf2_mdd >= bm_f2 * 0.95

        def _loss(c, b):
            return (c - b) / b * 100.0 if abs(b) > 1e-6 else 0.0
        f1l = _loss(cf1, bc_f1)
        f3l = _loss(cf3, bc_f3)
        oosl = _loss(coos, bc_oos)
        g3 = min(f1l, f3l, oosl) >= -10.0
        g4 = wm >= 0.4
        g5 = c4_mdd >= bm_4ds * 0.95

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
            "calmar_4ds": c4, "fold1": cf1, "fold2": cf2,
            "fold3": cf3, "oos": coos,
            "fold2_mdd": cf2_mdd, "mdd_4ds": c4_mdd,
            "f1_loss": f1l, "f3_loss": f3l, "oos_loss": oosl,
            "G1": g1, "G2a": g2a, "G2b": g2b,
            "G3": g3, "G4": g4, "G5": g5,
            "verdict": verdict,
        })

    res = pd.DataFrame(rows)
    vo = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}
    res["_v"] = res["verdict"].map(vo)
    res = res.sort_values(["_v", "calmar_4ds"],
                          ascending=[True, False]).drop(columns=["_v"]).reset_index(drop=True)

    body = ["# MV-F portfolio_allocation summary\n"]
    body.append("## Baseline — macd_cross 단독 (corner cell w=(1,0,0))\n")
    body.append(f"- 4ds-avg calmar = **{bc_4ds:.2f}**")
    body.append(f"- fold1={bc_f1:.2f} / fold2={bc_f2:.2f} / fold3={bc_f3:.2f} / oos={bc_oos:.2f}")
    body.append(f"- fold2 MDD = {bm_f2:.4f}")

    body.append("\n## Gate 정의\n")
    body.append(f"- **G1** portfolio 4ds-avg calmar > baseline ({bc_4ds:.2f})")
    body.append(f"- **G2a** fold2 calmar > baseline ({bc_f2:.2f})")
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
            "f1_loss", "f3_loss", "oos_loss",
        ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## Top 20 by 4ds-avg calmar\n")
    body.append(res.head(20)[[
        "w_macd", "w_breakout", "w_trend", "verdict",
        "calmar_4ds", "fold1", "fold2", "fold3", "oos",
        "G1", "G2a", "G2b", "G3", "G4", "G5",
    ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## fold2 calmar top 10 (fold2 회복 관점)\n")
    f2t = res.sort_values("fold2", ascending=False).head(10)
    body.append(f2t[[
        "w_macd", "w_breakout", "w_trend", "verdict",
        "fold2", "fold2_mdd", "calmar_4ds",
    ]].to_markdown(index=False, floatfmt=".2f"))

    body.append("\n## 종합 판정")
    if not pass_cells.empty:
        b = pass_cells.iloc[0]
        body.append(
            f"\n**PASS** — `w=({b['w_macd']:.1f}, {b['w_breakout']:.1f}, {b['w_trend']:.1f})` "
            f"calmar_4ds={b['calmar_4ds']:+.2f} "
            f"(baseline 대비 +{b['calmar_4ds']-bc_4ds:+.2f}) "
            f"fold2={b['fold2']:+.2f}. paper trial 검토 권고."
        )
    else:
        partial = res[res["verdict"] == "PARTIAL"]
        if not partial.empty:
            b = partial.iloc[0]
            body.append(
                f"\n**PARTIAL** — {len(partial)} cell 이 G1 또는 G2a 만 통과. "
                f"최고: w=({b['w_macd']:.1f}, {b['w_breakout']:.1f}, {b['w_trend']:.1f}) "
                f"calmar_4ds={b['calmar_4ds']:+.2f}, fold2={b['fold2']:+.2f}. 사람 판단."
            )
        else:
            body.append(
                "\n**FAIL** — G1 + G2a 동시 통과 cell 없음. portfolio 가설 기각. "
                "MV-G (신규 family — ML / microstructure) 권고."
            )

    body.append("\nheatmaps/ + cells.csv 참조.")
    (PA_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
    print(f"[summary] {PA_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
