"""성과 지표: Calmar / MDD / Sharpe / 승률 / 거래수.

두 가지 입력 방식 지원:
1. `metrics_from_equity(equity)` — 이미 계산된 자본곡선(pandas Series indexed by date)
2. `metrics_from_trades(trades_df, initial_capital)` — 거래 기록에서 realized 자본곡선 생성 후 지표 계산

**목적함수**: Calmar = annualized_return / |MDD|. 플랜 참고.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252
MIN_VALID_CALMAR_MDD = 1e-6  # MDD 가 이보다 작으면 Calmar = inf → 0 으로 처리


@dataclass(frozen=True)
class PerfMetrics:
    calmar: float
    annualized_return: float
    total_return: float
    mdd: float  # 양수 (drawdown magnitude)
    sharpe: float
    win_rate: float
    n_trades: int
    avg_trade_pct: float  # 순수익률 평균 (%) — 참고용

    def to_dict(self) -> dict:
        return asdict(self)


def compute_mdd(equity: pd.Series) -> float:
    """Maximum drawdown (양수, 절대값)."""
    if len(equity) < 2:
        return 0.0
    eq = equity.astype(float).values
    running_max = np.maximum.accumulate(eq)
    dd = (running_max - eq) / running_max  # 비율, 0~1
    return float(dd.max())


def compute_sharpe(daily_returns: pd.Series, rf: float = 0.0) -> float:
    """연율화 Sharpe (일간 수익률 기준)."""
    r = daily_returns.dropna().astype(float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    excess = r - rf / TRADING_DAYS_PER_YEAR
    return float(excess.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def compute_annualized_return(equity: pd.Series) -> float:
    """자본곡선에서 연율화 수익률 추정.

    관측 일수(영업일 가정) 기반 CAGR.
    """
    if len(equity) < 2:
        return 0.0
    start = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    if start <= 0:
        return 0.0
    n_days = len(equity)  # 영업일 index 라고 가정
    if n_days <= 0:
        return 0.0
    total_ret = end / start - 1.0
    years = n_days / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return total_ret
    # (1+ret)^(1/years) - 1. 음수 자본 못 가정하므로 1+ret > 0 체크.
    base = 1.0 + total_ret
    if base <= 0:
        return -1.0
    return float(base ** (1.0 / years) - 1.0)


def metrics_from_equity(
    equity: pd.Series,
    trades_df: Optional[pd.DataFrame] = None,
) -> PerfMetrics:
    """자본곡선 + (선택) 거래 DF 로부터 성과 지표 계산.

    trades_df 가 주어지면 승률/거래수/평균수익률 도 계산.
    trades_df 컬럼: net_pct (%) 만 있으면 충분.
    """
    equity = equity.astype(float).dropna()
    if equity.empty:
        return PerfMetrics(
            calmar=0.0, annualized_return=0.0, total_return=0.0,
            mdd=0.0, sharpe=0.0, win_rate=0.0, n_trades=0, avg_trade_pct=0.0,
        )

    total_ret = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    ann_ret = compute_annualized_return(equity)
    mdd = compute_mdd(equity)
    daily_rets = equity.pct_change()
    sharpe = compute_sharpe(daily_rets)

    if mdd > MIN_VALID_CALMAR_MDD:
        calmar = ann_ret / mdd
    else:
        # MDD 가 ~0 이면 "무위험 수익" 느낌. 상수 cap 으로 처리
        calmar = 0.0

    # 거래 통계
    n_trades = 0
    win_rate = 0.0
    avg_trade = 0.0
    if trades_df is not None and not trades_df.empty and "net_pct" in trades_df.columns:
        n_trades = int(len(trades_df))
        if n_trades > 0:
            win_rate = float((trades_df["net_pct"] > 0).mean())
            avg_trade = float(trades_df["net_pct"].mean())

    return PerfMetrics(
        calmar=calmar,
        annualized_return=ann_ret,
        total_return=total_ret,
        mdd=mdd,
        sharpe=sharpe,
        win_rate=win_rate,
        n_trades=n_trades,
        avg_trade_pct=avg_trade,
    )


def _prior_day_str(date_str: str) -> str:
    """'YYYYMMDD' → 하루 전 'YYYYMMDD'."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return (dt - timedelta(days=1)).strftime("%Y%m%d")


def realized_equity_curve(
    trades_df: pd.DataFrame,
    initial_capital: float,
    size_krw: float,
) -> pd.Series:
    """거래 기록 → 누적 realized 자본곡선 (첫 거래 전날 = initial_capital).

    입력 컬럼: `exit_date` (YYYYMMDD), `net_pct` (%)
    가정: 모든 거래는 동일 size_krw 투입 (고정금액).

    반환: 일자 indexed Series. 첫 원소 = 첫 거래일 전일의 initial_capital.
    """
    if trades_df is None or trades_df.empty:
        return pd.Series({"20000101": initial_capital}, dtype=float)

    tdf = trades_df[["exit_date", "net_pct"]].copy()
    tdf["pnl_krw"] = size_krw * tdf["net_pct"] / 100.0
    daily_pnl = tdf.groupby("exit_date")["pnl_krw"].sum().sort_index()
    cumulative = daily_pnl.cumsum()

    first_date = cumulative.index[0]
    start_date = _prior_day_str(first_date)
    prefix = pd.Series({start_date: initial_capital}, dtype=float)
    equity = pd.concat([prefix, initial_capital + cumulative]).sort_index()
    return equity


def metrics_from_trades(
    trades_df: pd.DataFrame,
    initial_capital: float,
    size_krw: float,
) -> PerfMetrics:
    equity = realized_equity_curve(trades_df, initial_capital, size_krw)
    return metrics_from_equity(equity, trades_df=trades_df)
