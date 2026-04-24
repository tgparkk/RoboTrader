"""엔진이 exit_signal 에 current_price 를 전달하는지 검증."""
from typing import Optional

import pandas as pd

from backtests.common.engine import BacktestEngine
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder


class TPSLStrategy(StrategyBase):
    """current_price 기반 TP/SL 전략."""
    name = "tp_sl"
    hold_days = 0
    param_space = {}

    def __init__(self, tp_pct=5.0, sl_pct=-3.0):
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct

    def prepare_features(self, df_minute, df_daily):
        return pd.DataFrame(index=df_minute.index)

    def entry_signal(self, features, bar_idx, stock_code):
        if bar_idx == 5:
            return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.5)
        return None

    def exit_signal(
        self, position, features, bar_idx, current_price: Optional[float] = None
    ):
        if current_price is None:
            return None
        pnl_pct = (current_price - position.entry_price) / position.entry_price * 100.0
        if pnl_pct >= self.tp_pct:
            return ExitOrder(stock_code=position.stock_code, reason="tp")
        if pnl_pct <= self.sl_pct:
            return ExitOrder(stock_code=position.stock_code, reason="sl")
        return None


def _ramping_bars(stock_code, n, start=10000.0, tp_target_bar=None, tp_pct=0.06):
    """tp_target_bar 에서 tp_pct% 급등하는 합성 분봉."""
    closes = [start] * n
    for i in range(1, n):
        closes[i] = closes[i - 1] * 1.001  # 완만한 상승
    if tp_target_bar is not None:
        closes[tp_target_bar] = start * (1 + tp_pct)  # 급등
    return pd.DataFrame({
        "stock_code": [stock_code] * n,
        "trade_date": ["20260401"] * n,
        "trade_time": [f"{9 + i // 60:02d}{i % 60:02d}00" for i in range(n)],
        "open": closes,
        "high": [c * 1.001 for c in closes],
        "low": [c * 0.999 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def test_engine_passes_current_price_to_exit_signal():
    """엔진이 current_price 전달 → TP 규칙 작동."""
    stock_code = "TEST"
    # bar 5 매수 (fill at bar 6, entry ≈ 10010)
    # bar 10 에서 close = 10000 * 1.06 = 10600 → +5.9% → TP 발동
    df = _ramping_bars(stock_code, n=20, tp_target_bar=10, tp_pct=0.06)
    engine = BacktestEngine(
        strategy=TPSLStrategy(tp_pct=5.0, sl_pct=-3.0),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["reason"] == "tp", f"기대 'tp', 실제 '{trade['reason']}'"


class _HoldLimitStrategy(StrategyBase):
    """current_price 를 사용하지 않는 기존 스타일 전략 (backward-compat 검증용)."""
    name = "hold_limit_legacy"
    hold_days = 0
    param_space = {}

    def prepare_features(self, df_minute, df_daily):
        return pd.DataFrame({"prev_close": df_minute["close"].shift(1)}, index=df_minute.index)

    def entry_signal(self, features, bar_idx, stock_code):
        if bar_idx == 5:
            return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.5)
        return None

    def exit_signal(self, position, features, bar_idx, current_price=None):
        if bar_idx - position.entry_bar_idx >= 3:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None


def test_engine_exit_signal_no_current_price_backward_compat():
    """current_price 미사용 전략 (기존 Phase 1 테스트 스타일) 여전히 동작."""
    stock_code = "TEST"
    closes = [10000.0 * (1.01 ** i) for i in range(20)]
    df = pd.DataFrame({
        "stock_code": [stock_code] * 20,
        "trade_date": ["20260401"] * 20,
        "trade_time": [f"{9 + i // 60:02d}{i % 60:02d}00" for i in range(20)],
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1_000_000.0] * 20,
    })
    engine = BacktestEngine(
        strategy=_HoldLimitStrategy(),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    assert len(result.trades) == 1
    assert result.trades[0]["entry_bar_idx"] == 6
    assert result.trades[0]["exit_bar_idx"] == 10
