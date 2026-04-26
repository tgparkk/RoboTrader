"""체결 모델 — 수수료·슬리피지·체결지연·거래량·가격제한 (원칙 3)."""

BUY_COMMISSION = 0.00015
SELL_COMMISSION = 0.00245
SLIPPAGE_ONE_WAY = 0.00225
FILL_DELAY_MINUTES = 1
VOLUME_LIMIT_RATIO = 0.02
LIMIT_PRICE_BUFFER = 0.01

# 한국장 가격 제한폭 (±30% 전후, 실제는 29.97% 근방이나 단순화)
PRICE_LIMIT_RATIO = 0.2997


class ExecutionModel:
    """전략이 직접 시가체결하지 않도록 강제하는 단일 진입점."""

    @staticmethod
    def compute_buy_fill_price(next_bar_open: float) -> float:
        return next_bar_open * (1 + SLIPPAGE_ONE_WAY)

    @staticmethod
    def compute_sell_fill_price(next_bar_open: float) -> float:
        return next_bar_open * (1 - SLIPPAGE_ONE_WAY)

    @staticmethod
    def compute_trade_net_pnl(
        buy_next_open: float, sell_next_open: float, quantity: int
    ) -> float:
        """매수·매도 (다음 분봉 시가 기준) 왕복 순손익. 수수료·슬리피지·세금 포함."""
        buy_fill = ExecutionModel.compute_buy_fill_price(buy_next_open)
        sell_fill = ExecutionModel.compute_sell_fill_price(sell_next_open)
        buy_cost = buy_fill * quantity * (1 + BUY_COMMISSION)
        sell_proceed = sell_fill * quantity * (1 - SELL_COMMISSION)
        return sell_proceed - buy_cost

    @staticmethod
    def is_volume_feasible(order_value_krw: float, daily_volume_krw: float) -> bool:
        if daily_volume_krw <= 0:
            return False
        return order_value_krw <= daily_volume_krw * VOLUME_LIMIT_RATIO

    @staticmethod
    def is_price_limit_safe(current_price: float, prev_close: float, side: str) -> bool:
        """상·하한가에서 LIMIT_PRICE_BUFFER 이내면 체결 불확실 → 거부."""
        upper_limit = prev_close * (1 + PRICE_LIMIT_RATIO)
        lower_limit = prev_close * (1 - PRICE_LIMIT_RATIO)
        if side == "buy":
            return current_price < upper_limit * (1 - LIMIT_PRICE_BUFFER)
        elif side == "sell":
            return current_price > lower_limit * (1 + LIMIT_PRICE_BUFFER)
        raise ValueError(f"unknown side: {side}")

    @staticmethod
    def next_fill_index(signal_idx: int) -> int:
        return signal_idx + FILL_DELAY_MINUTES
