"""청산 규칙 (ExitPolicy).

청산 조건은 우선순위 순서로 평가된다:
1. Stop Loss (SL)      — 저가가 SL 트리거 가격 이하면 SL 가에서 청산
2. Take Profit (TP)    — 고가가 TP 트리거 가격 이상이면 TP 가에서 청산
3. Trailing Stop       — high_water_mark 대비 trail_pct 하락 시 당시 close 청산
4. Time Exit           — bars_held 가 time_exit_bars 초과 시 close 청산
5. Max Holding Days    — trading_days_held 가 max_holding_days 도달 시 close 청산
6. Score Flip          — 현재 score 가 score_exit_threshold 이하면 close 청산
7. EOD (설정 있으면)   — 당일 마지막 바 강제 청산 (옵션)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ExitPolicy:
    stop_loss_pct: float                    # 예: -3.0  (진입가 대비 %)
    take_profit_pct: float                  # 예: 5.0
    max_holding_days: int                   # 3 or 5 (거래일 단위)
    trail_pct: Optional[float] = None       # None → 트레일 미사용
    time_exit_bars: Optional[int] = None    # None → 분봉 시간 청산 미사용
    score_exit_threshold: Optional[float] = None  # None → 점수 반전 청산 미사용
    force_eod: bool = False                 # True 면 장마감 직전 강제 청산

    def __post_init__(self) -> None:
        if self.stop_loss_pct >= 0:
            raise ValueError(f"stop_loss_pct must be negative: {self.stop_loss_pct}")
        if self.take_profit_pct <= 0:
            raise ValueError(f"take_profit_pct must be positive: {self.take_profit_pct}")
        if self.max_holding_days < 1:
            raise ValueError(f"max_holding_days must be >= 1: {self.max_holding_days}")
        if self.trail_pct is not None and self.trail_pct <= 0:
            raise ValueError(f"trail_pct must be > 0 or None: {self.trail_pct}")


# 편의: 기본 policy 팩토리
def default_policy(max_holding_days: int = 3) -> ExitPolicy:
    return ExitPolicy(
        stop_loss_pct=-3.0,
        take_profit_pct=5.0,
        max_holding_days=max_holding_days,
    )
