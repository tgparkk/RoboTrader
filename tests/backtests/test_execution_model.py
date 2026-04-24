"""backtests.common.execution_model 단위 테스트."""
import math

import pytest

from backtests.common.execution_model import (
    ExecutionModel,
    BUY_COMMISSION,
    SELL_COMMISSION,
    SLIPPAGE_ONE_WAY,
    FILL_DELAY_MINUTES,
    VOLUME_LIMIT_RATIO,
    LIMIT_PRICE_BUFFER,
)


def test_constants_match_spec():
    # 스펙(docs/superpowers/specs/2026-04-24-short-term-strategy-survey-design.md)에 명시된 값
    assert BUY_COMMISSION == 0.00015
    assert SELL_COMMISSION == 0.00245
    assert SLIPPAGE_ONE_WAY == 0.00225
    assert FILL_DELAY_MINUTES == 1
    assert VOLUME_LIMIT_RATIO == 0.02
    assert LIMIT_PRICE_BUFFER == 0.01


def test_buy_fill_price_adds_slippage():
    # 다음 분봉 시가 10,000원 → 매수 체결가 = 10,000 × (1 + 0.00225) = 10,022.5
    fill = ExecutionModel.compute_buy_fill_price(next_bar_open=10000.0)
    assert math.isclose(fill, 10022.5, abs_tol=1e-6)


def test_sell_fill_price_subtracts_slippage():
    fill = ExecutionModel.compute_sell_fill_price(next_bar_open=10000.0)
    assert math.isclose(fill, 9977.5, abs_tol=1e-6)


def test_trade_pnl_net_of_fees():
    # 매수 체결가 = 10,000 × (1 + 0.00225) = 10,022.5
    # 매도 체결가 = 11,000 × (1 - 0.00225) = 10,975.25
    # 매수 총비용 = 10,022.5 × 100 × (1 + 0.00015) = 1,002,400.34
    # 매도 순수익 = 10,975.25 × 100 × (1 - 0.00245) = 1,094,836.63
    # PnL = 1,094,836.63 - 1,002,400.34 ≈ 92,436.29
    pnl = ExecutionModel.compute_trade_net_pnl(
        buy_next_open=10000.0, sell_next_open=11000.0, quantity=100
    )
    assert 92_000 < pnl < 93_000


def test_volume_feasibility_under_limit():
    # 일평균 거래대금 100억 → 2% = 2억까지 체결 가능
    assert ExecutionModel.is_volume_feasible(
        order_value_krw=1.9e8, daily_volume_krw=1e10
    )


def test_volume_feasibility_over_limit():
    assert not ExecutionModel.is_volume_feasible(
        order_value_krw=2.1e8, daily_volume_krw=1e10
    )


def test_volume_feasibility_zero_volume():
    # 거래대금 0 인 종목 → feasibility 항상 False (분모 0)
    assert not ExecutionModel.is_volume_feasible(
        order_value_krw=1e6, daily_volume_krw=0
    )


def test_price_limit_safe_normal():
    # 전일 종가 10,000 → 상한가 +29.97% = 12,997 / 하한가 -29.97% = 7,003
    # 현재가 11,000 은 상한가에서 멀리 떨어짐 → 매수 OK
    assert ExecutionModel.is_price_limit_safe(
        current_price=11000.0, prev_close=10000.0, side="buy"
    )


def test_price_limit_buy_near_upper_rejected():
    # 전일 종가 10,000 → 상한가 ≈ 12,997. 12,870 은 상한가까지 1% 이내 → 매수 거부
    assert not ExecutionModel.is_price_limit_safe(
        current_price=12870.0, prev_close=10000.0, side="buy"
    )


def test_price_limit_sell_near_lower_rejected():
    # 하한가 ≈ 7,003. 7,073 은 하한가에서 1% 이내 → 매도 거부
    assert not ExecutionModel.is_price_limit_safe(
        current_price=7073.0, prev_close=10000.0, side="sell"
    )


def test_price_limit_invalid_side_raises():
    with pytest.raises(ValueError):
        ExecutionModel.is_price_limit_safe(
            current_price=10000.0, prev_close=10000.0, side="hold"
        )


def test_fill_delay_next_bar():
    # 신호 발생 시점의 분봉 인덱스를 받아 다음 분봉 인덱스 반환
    # signal_idx=5, FILL_DELAY_MINUTES=1 → fill_idx=6
    assert ExecutionModel.next_fill_index(signal_idx=5) == 6
