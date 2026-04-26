"""macd_cross OOS 거래 분포 분석.

OOS 36 trades 가 종목·일자별로 어떻게 분포되어 있는지 검사:
  - 종목별 trade 수 + P&L 합계 — 1-2 종목 의존성 검출
  - 일자별 trade 수 — 특정 날짜 집중 검출
  - P&L 분포 — top 5 winner / loser 가 전체 결과 dominate 여부
  - Win/loss 시계열 — 후반부 집중 여부
"""
import json
from pathlib import Path

import pandas as pd

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.common.engine import BacktestEngine
from backtests.multiverse.universe import select_top_universe
from backtests.strategies.macd_cross import MACDCrossStrategy


def main():
    # best params 로드
    best = json.loads(
        Path("backtests/reports/stage2/macd_cross_best.json")
        .read_text(encoding="utf-8")
    )
    params = best["best_params"]
    print(f"macd_cross params: {params}\n")

    # universe (Stage 2 와 동일)
    universe = select_top_universe(
        fold_train_start="20250301", fold_test_end="20260228",
        n_stocks=30, min_days_present=120,
    )

    # OOS 데이터
    minute_df = load_minute_df(universe, "20260301", "20260424")
    daily_df = load_daily_df(universe, "20250101", "20260424")
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in universe
    }
    nonempty = [c for c in universe if len(minute_by_code[c]) > 0]

    # 백테스트 실행 + trades 추출
    eng = BacktestEngine(
        strategy=MACDCrossStrategy(**params),
        initial_capital=100_000_000,
        universe=nonempty,
        minute_df_by_code={c: minute_by_code[c] for c in nonempty},
        daily_df_by_code={c: daily_by_code[c] for c in nonempty},
    )
    result = eng.run()
    trades = result.trades
    print(f"=== OOS 결과: {len(trades)} trades, "
          f"final equity {result.final_equity:,.0f}원 ===\n")

    if not trades:
        print("거래 없음")
        return

    # trade 시점별 trade_date 매핑
    rows = []
    for t in trades:
        code = t["stock_code"]
        df_min = minute_by_code[code]
        entry_date = df_min["trade_date"].iloc[t["entry_bar_idx"]]
        exit_date = df_min["trade_date"].iloc[t["exit_bar_idx"]]
        rows.append({
            "stock": code,
            "entry_date": str(entry_date),
            "exit_date": str(exit_date),
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "qty": t["quantity"],
            "pnl": t["pnl"],
            "ret_pct": (t["exit_price"] / t["entry_price"] - 1) * 100,
            "reason": t["reason"],
        })
    tdf = pd.DataFrame(rows)
    tdf.to_csv("backtests/reports/stage2/macd_cross_oos_trades.csv", index=False)

    # 1. 종목별 분포
    print("--- 종목별 trade 분포 ---")
    by_stock = tdf.groupby("stock").agg(
        n=("pnl", "count"),
        win=("pnl", lambda x: (x > 0).sum()),
        pnl_sum=("pnl", "sum"),
        avg_ret=("ret_pct", "mean"),
    ).sort_values("pnl_sum", ascending=False)
    by_stock["pnl_share"] = by_stock["pnl_sum"] / by_stock["pnl_sum"].sum() * 100
    print(by_stock.to_string(float_format=lambda x: f"{x:.2f}"))
    n_stocks_traded = len(by_stock)
    top1_share = by_stock["pnl_share"].iloc[0] if len(by_stock) else 0
    top3_share = by_stock["pnl_share"].head(3).sum() if len(by_stock) else 0
    print(f"\n  종목 수: {n_stocks_traded}/{len(nonempty)} ({n_stocks_traded/len(nonempty)*100:.0f}%)")
    print(f"  top1 P&L 점유: {top1_share:.1f}%")
    print(f"  top3 P&L 점유: {top3_share:.1f}%\n")

    # 2. 일자별 분포
    print("--- 진입일자별 trade 분포 ---")
    by_date = tdf.groupby("entry_date").agg(
        n=("pnl", "count"),
        pnl_sum=("pnl", "sum"),
    ).sort_index()
    print(by_date.to_string(float_format=lambda x: f"{x:.0f}"))
    print(f"  진입일 수: {len(by_date)}")
    print(f"  최대 1일 trades: {by_date['n'].max()}")
    print(f"  중앙값 trades/일: {by_date['n'].median():.1f}\n")

    # 3. P&L 분포
    print("--- 단일 거래 P&L 분포 ---")
    pnl = tdf["pnl"].sort_values(ascending=False)
    print(f"  top 5 winners:    {[f'{v:>10.0f}' for v in pnl.head(5).tolist()]}")
    print(f"  bot 5 losers:     {[f'{v:>10.0f}' for v in pnl.tail(5).tolist()]}")
    pnl_sum = pnl.sum()
    top1_pnl_share = pnl.iloc[0] / pnl_sum * 100 if pnl_sum != 0 else 0
    top5_pnl_share = pnl.head(5).sum() / pnl_sum * 100 if pnl_sum != 0 else 0
    print(f"  top 1 거래 점유율: {top1_pnl_share:.1f}%")
    print(f"  top 5 거래 점유율: {top5_pnl_share:.1f}%")
    print(f"  win 거래: {(pnl > 0).sum()} / loss: {(pnl < 0).sum()}")
    print(f"  win/loss 평균: +{pnl[pnl>0].mean():,.0f} / {pnl[pnl<0].mean():,.0f}원\n")

    # 4. 시계열 누적 P&L
    print("--- 시계열 누적 P&L (date 별) ---")
    by_day = tdf.groupby("entry_date")["pnl"].sum().sort_index()
    cum = by_day.cumsum()
    print(cum.to_string(float_format=lambda x: f"{x:>12,.0f}"))


if __name__ == "__main__":
    main()
