"""macd_cross 라이브 어댑터 단위 테스트."""
import math
import pandas as pd
import pytest

from core.strategies.macd_cross_strategy import MacdCrossStrategy


def _daily_df(closes):
    dates = pd.date_range("2025-01-02", periods=len(closes), freq="B").strftime("%Y%m%d")
    return pd.DataFrame({"trade_date": dates.astype(str), "close": closes})


def test_compute_today_signal_inputs_caches_per_stock():
    """compute_today_signal_inputs 는 종목별 prev/prev_prev hist 를 캐시."""
    s = MacdCrossStrategy(fast=14, slow=34, signal=12)
    closes = [10000 + i * 10 for i in range(60)]
    s.set_daily_history("005930", _daily_df(closes), today_yyyymmdd="20250401")
    prev, prev_prev = s.get_cached_hist("005930")
    assert prev is not None and not math.isnan(prev)
    assert prev_prev is not None and not math.isnan(prev_prev)


def test_check_entry_returns_true_on_cached_golden_cross():
    """캐시된 hist 값으로 골든크로스 + 시간대 충족 시 True."""
    s = MacdCrossStrategy(fast=14, slow=34, signal=12,
                          entry_hhmm_min=1430, entry_hhmm_max=1500)
    s._cache["005930"] = (0.5, -0.3)  # prev=0.5, prev_prev=-0.3 → cross
    assert s.check_entry("005930", hhmm=1430) is True
    assert s.check_entry("005930", hhmm=1500) is True


def test_check_entry_false_outside_window():
    s = MacdCrossStrategy()
    s._cache["005930"] = (0.5, -0.3)
    assert s.check_entry("005930", hhmm=1400) is False
    assert s.check_entry("005930", hhmm=1501) is False


def test_check_entry_false_when_not_cached():
    s = MacdCrossStrategy()
    assert s.check_entry("999999", hhmm=1430) is False


def test_check_entry_false_when_no_cross():
    s = MacdCrossStrategy()
    s._cache["005930"] = (-0.1, -0.3)  # 음→음
    assert s.check_entry("005930", hhmm=1430) is False
