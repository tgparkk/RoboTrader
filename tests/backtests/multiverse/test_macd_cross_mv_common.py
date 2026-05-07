"""macd_cross 멀티버스 공통 유틸 단위 테스트."""
import pandas as pd

from backtests.multiverse.macd_cross_mv_common import (
    compute_top1_share, compute_max_consec_loss,
)


def test_top1_share_basic():
    pnls = pd.Series([100, 50, -30, 200, -10])
    # sum = 310, top1 (max) = 200, share = 200/310
    assert abs(compute_top1_share(pnls) - 200 / 310) < 1e-9


def test_top1_share_zero_with_no_trades():
    assert compute_top1_share(pd.Series([], dtype=float)) == 0.0


def test_top1_share_zero_when_sum_zero():
    pnls = pd.Series([100, -100])
    assert compute_top1_share(pnls) == 0.0


def test_top1_share_negative_sum_returns_signed():
    pnls = pd.Series([-100, -50, 30])
    # sum = -120, top1 = 30, share = 30 / -120 (음수 sum 이면 share 도 음수)
    assert abs(compute_top1_share(pnls) - 30 / -120) < 1e-9


def test_max_consec_loss_basic():
    # streaks: [-10] streak=1, [-5,-30,-40] streak=3 → max=3
    pnls = [100, -10, -20, 50, -5, -30, -40, 10]
    assert compute_max_consec_loss(pnls) == 3


def test_max_consec_loss_all_wins():
    assert compute_max_consec_loss([10, 20, 30]) == 0


def test_max_consec_loss_all_losses():
    assert compute_max_consec_loss([-10, -20, -30]) == 3


def test_max_consec_loss_empty():
    assert compute_max_consec_loss([]) == 0


def test_max_consec_loss_zero_breaks_streak():
    # -10 streak=1, 0 breaks, -20 -30 streak=2 → max=2
    pnls = [-10, 0, -20, -30]
    assert compute_max_consec_loss(pnls) == 2


from backtests.multiverse.macd_cross_mv_common import build_cell_kpis


def _fake_trades(pnls):
    return [{"pnl": p, "stock_code": f"S{i:03d}"} for i, p in enumerate(pnls)]


def test_build_cell_kpis_with_trades():
    equity = pd.Series([10_000_000, 10_050_000, 10_020_000, 10_100_000, 10_080_000])
    trades = _fake_trades([50_000, -30_000, 80_000, -20_000])
    kpis = build_cell_kpis(equity=equity, trades=trades, trading_days=20)
    # 필수 키 존재
    assert {"calmar", "return", "mdd", "trades", "win_rate",
            "top1_share", "max_consec_loss", "monthly_trades"} <= kpis.keys()
    assert kpis["trades"] == 4
    assert kpis["win_rate"] == 0.5
    assert abs(kpis["return"] - 0.008) < 1e-6  # 10080000/10000000 - 1
    # monthly_trades = trades * 21 / trading_days = 4 * 21 / 20 = 4.2
    assert abs(kpis["monthly_trades"] - 4.2) < 1e-9


def test_build_cell_kpis_no_trades():
    equity = pd.Series([10_000_000, 10_000_000])
    kpis = build_cell_kpis(equity=equity, trades=[], trading_days=10)
    assert kpis["trades"] == 0
    assert kpis["win_rate"] == 0.0
    assert kpis["top1_share"] == 0.0
    assert kpis["max_consec_loss"] == 0
    assert kpis["return"] == 0.0


def test_build_cell_kpis_nan_pnl_does_not_undercount_trades():
    """trades 카운트는 NaN 이 있어도 raw 입력 길이 유지 (NaN 은 win_rate 등에서만 제외)."""
    import math
    equity = pd.Series([10_000_000, 10_010_000, 10_020_000])
    trades = [
        {"pnl": 50_000, "stock_code": "S001"},
        {"pnl": math.nan, "stock_code": "S002"},  # NaN 제거되면 안 됨
        {"pnl": -20_000, "stock_code": "S003"},
    ]
    kpis = build_cell_kpis(equity=equity, trades=trades, trading_days=10)
    assert kpis["trades"] == 3  # raw count, NaN 포함
    # win_rate 는 NaN 제외 → wins=1 (50k), losses=1 (-20k) = 0.5
    assert kpis["win_rate"] == 0.5
