"""기존 trials.csv 를 새 게이트 로직 (5/5 mandatory) 으로 재평가.

CSV 의 train/test 메트릭은 그대로 사용. pass_stage1 만 재계산.
원본 보존: pass_stage1_v1 컬럼을 추가, pass_stage1 컬럼 덮어쓰기.
"""
import argparse
from pathlib import Path

import pandas as pd

from backtests.multiverse.stage1_coarse import (
    GATE_OVERFIT_MIN, GATE_MDD_MAX, GATE_TRADES_MIN,
    GATE_WIN_RATE_MIN, GATE_MONTHLY_TRADES_MIN, STAGE1_CALMAR_FLOOR,
)


def reevaluate_row(row: pd.Series) -> dict:
    """단일 trial 행에 대해 새 게이트 로직 적용."""
    overfit_ratio = row.get("overfit_ratio", float("nan"))
    monthly_trades = row.get("monthly_trades", 0)
    test_calmar = row.get("test_calmar", float("nan"))
    test_mdd = row.get("test_mdd", 0)
    test_trades = row.get("test_total_trades", 0)
    test_win_rate = row.get("test_win_rate", 0)

    g_overfit = pd.notna(overfit_ratio) and overfit_ratio >= GATE_OVERFIT_MIN
    g_mdd = abs(test_mdd) <= GATE_MDD_MAX
    g_trades = test_trades >= GATE_TRADES_MIN
    g_win = test_win_rate >= GATE_WIN_RATE_MIN
    g_monthly = monthly_trades >= GATE_MONTHLY_TRADES_MIN
    n_pass = sum([g_overfit, g_mdd, g_trades, g_win, g_monthly])
    calmar_ok = pd.notna(test_calmar) and test_calmar >= STAGE1_CALMAR_FLOOR
    pass_v2 = (n_pass == 5) and calmar_ok
    return {
        "gates_passed_v2": n_pass,
        "pass_stage1_v2": pass_v2,
    }


def reevaluate_file(path: Path) -> tuple:
    df = pd.read_csv(path)
    if "pass_stage1_v1" not in df.columns:
        df["pass_stage1_v1"] = df["pass_stage1"]
    new_cols = df.apply(reevaluate_row, axis=1, result_type="expand")
    df["gates_passed_v2"] = new_cols["gates_passed_v2"]
    df["pass_stage1_v2"] = new_cols["pass_stage1_v2"]
    df["pass_stage1"] = df["pass_stage1_v2"]  # canonical 갱신
    df.to_csv(path, index=False)
    return int(df["pass_stage1_v1"].sum()), int(df["pass_stage1_v2"].sum())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fold", default="fold1")
    args = p.parse_args()

    out_dir = Path(f"backtests/reports/stage1/{args.fold}")
    files = sorted(out_dir.glob("*_trials.csv"))
    if not files:
        print(f"no trials.csv in {out_dir}")
        return

    print(f"=== Re-evaluating gates ({args.fold}) — v1 (3-of-5) → v2 (5-of-5) ===\n")
    print(f"{'strategy':<22} {'v1 pass':>8} {'v2 pass':>8}  delta")
    print("-" * 50)
    summary = []
    for f in files:
        name = f.stem.replace("_trials", "")
        v1, v2 = reevaluate_file(f)
        summary.append({"strategy": name, "v1_pass": v1, "v2_pass": v2,
                        "delta": v2 - v1})
        print(f"{name:<22} {v1:>8} {v2:>8}  {v2-v1:+5}")

    s_df = pd.DataFrame(summary).sort_values("v2_pass", ascending=False)
    s_df.to_csv(out_dir / "regate_summary.csv", index=False)
    print(f"\nDetail saved: {out_dir / 'regate_summary.csv'}")
    print("\n=== v2 통과 전략 (정렬: v2_pass) ===")
    for _, r in s_df[s_df["v2_pass"] > 0].iterrows():
        print(f"  {r['strategy']:<22} {r['v2_pass']:>3} / 200 trials")


if __name__ == "__main__":
    main()
