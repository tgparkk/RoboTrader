"""backtests.common.trading_day 단위 테스트."""
import pandas as pd
import pytest

from backtests.common.trading_day import (
    count_trading_days_between,
    bar_idx_to_trade_date,
)


def _make_df(dates):
    """dates: [trade_date] → DataFrame."""
    return pd.DataFrame({"trade_date": dates})


def test_count_zero_days_same_date():
    df = _make_df(["20260401", "20260401", "20260401"])
    # 같은 날짜 내에서는 0일 경과
    assert count_trading_days_between(df, from_idx=0, to_idx=2) == 0


def test_count_one_day_next_date():
    df = _make_df(["20260401", "20260401", "20260402", "20260402"])
    # 20260401 → 20260402: 1일 경과
    assert count_trading_days_between(df, from_idx=1, to_idx=2) == 1


def test_count_multiple_days():
    df = _make_df(["20260401", "20260402", "20260403", "20260404", "20260405"])
    # idx 0 (01) → idx 4 (05): 4일 경과
    assert count_trading_days_between(df, from_idx=0, to_idx=4) == 4


def test_count_from_equals_to():
    df = _make_df(["20260401", "20260402"])
    assert count_trading_days_between(df, from_idx=1, to_idx=1) == 0


def test_count_handles_weekend_gap():
    # 금 → 월: 주말 건너뜀 (거래일 기준 1일)
    df = _make_df(["20260403", "20260406"])  # 금, 월
    assert count_trading_days_between(df, from_idx=0, to_idx=1) == 1


def test_count_invalid_range_raises():
    df = _make_df(["20260401", "20260402"])
    with pytest.raises(ValueError):
        count_trading_days_between(df, from_idx=1, to_idx=0)  # from > to


def test_bar_idx_to_trade_date():
    df = _make_df(["20260401", "20260401", "20260402", "20260403"])
    assert bar_idx_to_trade_date(df, 0) == "20260401"
    assert bar_idx_to_trade_date(df, 2) == "20260402"
    assert bar_idx_to_trade_date(df, 3) == "20260403"


def test_bar_idx_out_of_range():
    df = _make_df(["20260401", "20260402"])
    with pytest.raises(IndexError):
        bar_idx_to_trade_date(df, 5)
