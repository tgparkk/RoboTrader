"""Stage 1 결과 분석 — trials.csv 들을 읽어 게이트 통과 / 상위 trial 리포트.

CLI:
  python -m backtests.multiverse.analyze_stage1 --fold fold1
"""
import argparse
from pathlib import Path

import pandas as pd


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--fold", default="fold1")
    p.add_argument("--top-k", type=int, default=5,
                   help="strategy 별 상위 K trial 출력")
    return p.parse_args()


def main():
    args = parse_args()
    out_dir = Path(f"backtests/reports/stage1/{args.fold}")
    if not out_dir.exists():
        print(f"directory missing: {out_dir}")
        return

    # 전략별 trials.csv 로드
    trials_files = sorted(out_dir.glob("*_trials.csv"))
    if not trials_files:
        print(f"no trials.csv found in {out_dir}")
        return

    print(f"=== Stage 1 분석 ({args.fold}) ===")
    print(f"전략 {len(trials_files)}개 — {[f.stem.replace('_trials', '') for f in trials_files]}\n")

    summary = []
    for f in trials_files:
        name = f.stem.replace("_trials", "")
        df = pd.read_csv(f)
        n_pass = int(df["pass_stage1"].sum())
        valid = df[df["error"].fillna("") == ""].copy()
        if len(valid) == 0:
            summary.append({"strategy": name, "n_trials": len(df), "n_pass": 0,
                            "n_valid": 0, "best_calmar": float("nan")})
            continue
        valid_calmar = valid[valid["test_calmar"].notna()]
        if len(valid_calmar) == 0:
            best_calmar = float("nan")
        else:
            best_calmar = valid_calmar["test_calmar"].max()
        summary.append({
            "strategy": name,
            "n_trials": len(df),
            "n_valid": len(valid),
            "n_pass": n_pass,
            "best_calmar": best_calmar,
            "median_calmar": valid_calmar["test_calmar"].median() if len(valid_calmar) else float("nan"),
            "best_return": valid_calmar.loc[valid_calmar["test_calmar"].idxmax(), "test_total_return"]
                           if len(valid_calmar) else float("nan"),
            "best_trades": int(valid_calmar.loc[valid_calmar["test_calmar"].idxmax(), "test_total_trades"])
                           if len(valid_calmar) else 0,
        })

    # 전략 요약
    s_df = pd.DataFrame(summary).sort_values("best_calmar", ascending=False)
    print("=== 전략 요약 (Calmar best 기준 정렬) ===")
    print(s_df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    # 게이트 통과한 전략
    passing = s_df[s_df["n_pass"] > 0]
    print(f"\n=== 게이트 통과 전략 ({len(passing)}개) ===")
    if len(passing) == 0:
        print("(없음 — Stage 2 진입 불가. 임계 완화 또는 Phase 4 (data-driven) 고려)")
    else:
        for _, row in passing.iterrows():
            print(f"  {row['strategy']:<22} pass={row['n_pass']}/{row['n_trials']}  "
                  f"best_calmar={row['best_calmar']:.2f}  return={row['best_return']:.2%}  "
                  f"trades={row['best_trades']}")

    # 전략별 상위 K trial 상세
    print(f"\n=== 전략별 상위 {args.top_k} trials (test Calmar 기준) ===")
    for f in trials_files:
        name = f.stem.replace("_trials", "")
        df = pd.read_csv(f)
        valid = df[df["error"].fillna("") == ""].dropna(subset=["test_calmar"])
        if len(valid) == 0:
            continue
        top = valid.nlargest(args.top_k, "test_calmar")
        cols = ["trial_id", "test_calmar", "test_total_return", "test_total_trades",
                "test_mdd", "test_win_rate", "overfit_ratio", "gates_passed", "pass_stage1"]
        print(f"\n--- {name} ---")
        print(top[cols].to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
