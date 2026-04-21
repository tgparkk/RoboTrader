"""Portfolio / Position / Trade.

- Position: 보유 중인 포지션 (미청산)
- Trade: 청산된 거래 기록 (실현 PnL 기록용)
- Portfolio: 동시 보유 슬롯 관리 + 진입/청산 로직
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from analysis.research.weighted_score.sim.cost_model import CostModel
from analysis.research.weighted_score.strategy.exit_rules import ExitPolicy


# ---------------- Position / Trade ----------------


@dataclass
class Position:
    stock_code: str
    entry_date: str          # YYYYMMDD
    entry_idx: int           # 분봉 idx
    entry_time: str          # HHMMSS
    entry_price: float
    entry_score: float
    size_krw: float
    high_water_mark: float   # 보유 중 최고가 (trail 계산용)
    bars_held: int = 0       # 분봉 단위
    trading_days_held: int = 0  # 거래일 단위
    last_seen_date: str = ""   # bars_held 증가 시 날짜 전환 체크용

    def update_bar(self, trade_date: str, high: float) -> None:
        """매 bar 호출: bars/days 증가 + high_water_mark 갱신."""
        if not self.last_seen_date:
            self.last_seen_date = self.entry_date
        if trade_date != self.last_seen_date:
            self.trading_days_held += 1
            self.last_seen_date = trade_date
        self.bars_held += 1
        if high > self.high_water_mark:
            self.high_water_mark = high


@dataclass
class Trade:
    stock_code: str
    entry_date: str
    entry_idx: int
    entry_time: str
    entry_price: float
    entry_score: float
    exit_date: str
    exit_idx: int
    exit_time: str
    exit_price: float
    exit_reason: str
    size_krw: float
    bars_held: int
    trading_days_held: int
    gross_pct: float
    net_pct: float
    pnl_krw: float

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "entry_date": self.entry_date,
            "entry_idx": self.entry_idx,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "entry_score": self.entry_score,
            "exit_date": self.exit_date,
            "exit_idx": self.exit_idx,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "size_krw": self.size_krw,
            "bars_held": self.bars_held,
            "trading_days_held": self.trading_days_held,
            "gross_pct": self.gross_pct,
            "net_pct": self.net_pct,
            "pnl_krw": self.pnl_krw,
        }


# ---------------- Portfolio ----------------


@dataclass
class Portfolio:
    max_positions: int
    size_krw: float
    cost_model: CostModel
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[Trade] = field(default_factory=list)

    # ---- 조회 ----

    def is_holding(self, code: str) -> bool:
        return code in self.positions

    def has_slot(self) -> bool:
        return len(self.positions) < self.max_positions

    def n_open(self) -> int:
        return len(self.positions)

    # ---- 진입 ----

    def try_enter(
        self,
        stock_code: str,
        date: str,
        idx: int,
        time: str,
        price: float,
        score: float,
    ) -> bool:
        """슬롯 비어있고 미보유면 진입. 진입가는 비용 반영된 유효가.

        반환: 성공 여부.
        """
        if self.is_holding(stock_code) or not self.has_slot():
            return False
        effective_entry = self.cost_model.entry_fill_adjusted(price)
        self.positions[stock_code] = Position(
            stock_code=stock_code,
            entry_date=date,
            entry_idx=idx,
            entry_time=time,
            entry_price=effective_entry,
            entry_score=score,
            size_krw=self.size_krw,
            high_water_mark=effective_entry,
            last_seen_date=date,
        )
        return True

    # ---- 청산 ----

    def close_position(
        self,
        stock_code: str,
        date: str,
        idx: int,
        time: str,
        exit_price_raw: float,
        reason: str,
    ) -> Trade:
        """포지션 청산 → Trade 생성.

        exit_price_raw: 규칙이 지정한 이론 청산가 (예: SL 가, TP 가, 현재 close).
        최종 체결가는 cost_model.exit_fill_adjusted 적용.
        gross/net 계산은 entry_price(비용반영된) vs exit_price(비용반영된) 기준.
        """
        pos = self.positions.pop(stock_code)
        effective_exit = self.cost_model.exit_fill_adjusted(exit_price_raw)
        gross_pct = (effective_exit / pos.entry_price - 1.0) * 100.0
        # 주의: entry/exit 둘 다 이미 비용 반영된 값이므로 round_trip 차감 불필요.
        # gross_pct 자체가 net 이 된다.
        net_pct = gross_pct
        pnl_krw = pos.size_krw * net_pct / 100.0

        trade = Trade(
            stock_code=stock_code,
            entry_date=pos.entry_date,
            entry_idx=pos.entry_idx,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            entry_score=pos.entry_score,
            exit_date=date,
            exit_idx=idx,
            exit_time=time,
            exit_price=effective_exit,
            exit_reason=reason,
            size_krw=pos.size_krw,
            bars_held=pos.bars_held,
            trading_days_held=pos.trading_days_held,
            gross_pct=gross_pct,
            net_pct=net_pct,
            pnl_krw=pnl_krw,
        )
        self.closed_trades.append(trade)
        return trade

    # ---- Exit 평가 (한 포지션) ----

    @staticmethod
    def evaluate_exit(
        pos: Position,
        bar_high: float,
        bar_low: float,
        bar_close: float,
        current_score: float,
        policy: ExitPolicy,
    ) -> Optional[tuple[str, float]]:
        """포지션 청산 조건 평가. 청산되면 (reason, exit_price_raw) 반환.

        우선순위: SL → TP → Trail → Time(분봉) → MaxHolding(일) → ScoreFlip.
        SL/TP 는 인트라바 high/low 로 트리거 판정.
        """
        entry = pos.entry_price
        sl_price = entry * (1.0 + policy.stop_loss_pct / 100.0)
        tp_price = entry * (1.0 + policy.take_profit_pct / 100.0)

        # 1) SL (저가가 sl_price 이하 → sl_price 에서 체결 가정)
        if bar_low <= sl_price:
            return "SL", sl_price

        # 2) TP (고가가 tp_price 이상 → tp_price 에서 체결 가정)
        if bar_high >= tp_price:
            return "TP", tp_price

        # 3) Trailing (high_water_mark 는 이미 업데이트된 상태)
        if policy.trail_pct is not None:
            trail_trigger = pos.high_water_mark * (1.0 - policy.trail_pct / 100.0)
            if bar_low <= trail_trigger:
                return "TRAIL", trail_trigger

        # 4) Time exit (분봉 단위)
        if policy.time_exit_bars is not None and pos.bars_held >= policy.time_exit_bars:
            return "TIME", bar_close

        # 5) Max holding days
        if pos.trading_days_held >= policy.max_holding_days:
            return "MAX_HOLD", bar_close

        # 6) Score flip
        if (
            policy.score_exit_threshold is not None
            and current_score == current_score  # NaN 체크
            and current_score <= policy.score_exit_threshold
        ):
            return "SCORE", bar_close

        return None
