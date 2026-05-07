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
