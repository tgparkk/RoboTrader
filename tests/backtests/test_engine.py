"""backtests.common.engine 단위 테스트.

합성 데이터로 엔진 동작 검증 (DB 불필요).
"""
import pandas as pd

from backtests.common.engine import BacktestEngine, BacktestResult
from backtests.strategies.base import StrategyBase, EntryOrder, ExitOrder, Position


class BuyAtBar5Sell3BarsLater(StrategyBase):
    """bar_idx=5 에서 모든 종목 매수. 진입 3 bar 경과 후 exit 신호 emit.

    세부 타이밍:
      - 신호 at bar 5 → fill at bar 6 (entry_bar_idx=6)
      - 매 bar 후 exit_signal 체크: bar_idx - entry_bar_idx >= 3 이면 emit
      - 첫 exit 신호 at bar 9 (9-6=3) → fill at bar 10 (exit_bar_idx=10)
    """
    name = "buy5_sell3bars_later"
    hold_days = 0
    param_space = {}

    def prepare_features(self, df_minute, df_daily):
        return pd.DataFrame({"prev_close": df_minute["close"].shift(1)}, index=df_minute.index)

    def entry_signal(self, features, bar_idx, stock_code):
        if bar_idx == 5:
            return EntryOrder(stock_code=stock_code, priority=1, budget_ratio=0.5)
        return None

    def exit_signal(self, position, features, bar_idx):
        if bar_idx - position.entry_bar_idx >= 3:
            return ExitOrder(stock_code=position.stock_code, reason="hold_limit")
        return None


def _make_bars(stock_code: str, n: int, start_price: float = 10000.0, drift: float = 0.01):
    """단순 증가 합성 분봉. close[t] = start * (1+drift)^t."""
    closes = [start_price * (1 + drift) ** i for i in range(n)]
    return pd.DataFrame({
        "stock_code": [stock_code] * n,
        "trade_date": ["20260401"] * n,
        "trade_time": [f"{9+i//60:02d}{i%60:02d}00" for i in range(n)],
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def test_engine_executes_buy_and_sell():
    stock_code = "TEST"
    df_minute = _make_bars(stock_code, n=20, start_price=10000.0, drift=0.01)

    engine = BacktestEngine(
        strategy=BuyAtBar5Sell3BarsLater(),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df_minute},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    assert isinstance(result, BacktestResult)
    assert len(result.trades) == 1
    trade = result.trades[0]
    # Signal at bar 5 → fill at bar 6 (entry_bar_idx=6)
    # First exit signal at bar 9 (9-6=3) → fill at bar 10 (exit_bar_idx=10)
    assert trade["entry_bar_idx"] == 6
    assert trade["exit_bar_idx"] == 10
    assert trade["stock_code"] == "TEST"


def test_engine_respects_budget_and_cap():
    """n=10 이라 exit signal 발생 전 백테스트 종료 → 강제청산 발생."""
    stock_code = "TEST"
    df_minute = _make_bars(stock_code, n=10)
    engine = BacktestEngine(
        strategy=BuyAtBar5Sell3BarsLater(),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df_minute},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    # budget_ratio=0.5 → 500만원 매수. 최종 equity >= 0
    assert result.final_equity >= 0
    # 강제청산 1건
    assert len(result.trades) == 1
    assert result.trades[0]["reason"] == "eod_forced"


def test_engine_reports_metrics():
    stock_code = "TEST"
    df_minute = _make_bars(stock_code, n=20, start_price=10000.0, drift=0.01)
    engine = BacktestEngine(
        strategy=BuyAtBar5Sell3BarsLater(),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df_minute},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    assert "total_trades" in result.metrics
    assert result.metrics["total_trades"] == 1
    assert "calmar" in result.metrics
    assert "sharpe" in result.metrics
    assert "mdd" in result.metrics


def test_engine_no_trades_when_no_signals():
    class SilentStrategy(StrategyBase):
        name = "silent"
        hold_days = 0
        param_space = {}

        def prepare_features(self, df_minute, df_daily):
            return pd.DataFrame({"x": range(len(df_minute))}, index=df_minute.index)

        def entry_signal(self, features, bar_idx, stock_code):
            return None

        def exit_signal(self, position, features, bar_idx):
            return None

    stock_code = "TEST"
    df_minute = _make_bars(stock_code, n=20)
    engine = BacktestEngine(
        strategy=SilentStrategy(),
        initial_capital=10_000_000,
        universe=[stock_code],
        minute_df_by_code={stock_code: df_minute},
        daily_df_by_code={stock_code: pd.DataFrame()},
    )
    result = engine.run()
    assert len(result.trades) == 0
    # 현금만 있고 positions 없음 → equity = initial_capital
    assert result.final_equity == 10_000_000
