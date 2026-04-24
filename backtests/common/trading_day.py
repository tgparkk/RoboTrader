"""거래일 카운팅 유틸 — trade_date 컬럼 기반."""
import pandas as pd


def count_trading_days_between(
    df_minute: pd.DataFrame, from_idx: int, to_idx: int
) -> int:
    """df_minute[from_idx] ~ df_minute[to_idx] 사이 고유 trade_date 의 개수 - 1.

    Args:
        df_minute: trade_date 컬럼 포함된 분봉 DF.
        from_idx: 시작 bar 인덱스 (inclusive).
        to_idx: 종료 bar 인덱스 (inclusive).

    Returns:
        경과한 거래일 수. 같은 날짜 안에서는 0.
    """
    if from_idx > to_idx:
        raise ValueError(f"from_idx {from_idx} > to_idx {to_idx}")
    subset = df_minute["trade_date"].iloc[from_idx : to_idx + 1]
    return int(subset.nunique() - 1)


def bar_idx_to_trade_date(df_minute: pd.DataFrame, bar_idx: int) -> str:
    """bar_idx 시점의 trade_date 반환."""
    if bar_idx < 0 or bar_idx >= len(df_minute):
        raise IndexError(f"bar_idx {bar_idx} out of range [0, {len(df_minute)})")
    return str(df_minute["trade_date"].iloc[bar_idx])
