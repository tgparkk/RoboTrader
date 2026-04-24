"""전략 추상 베이스 — 모든 단타 전략이 상속."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any

import pandas as pd


@dataclass
class Position:
    stock_code: str
    entry_bar_idx: int
    entry_price: float
    quantity: int
    entry_date: str


@dataclass
class EntryOrder:
    stock_code: str
    priority: int           # 낮을수록 먼저 체결 시도
    budget_ratio: float     # 가용현금 대비 비율 (0~1)


@dataclass
class ExitOrder:
    stock_code: str
    reason: str             # 'tp', 'sl', 'hold_limit', 'signal', 'eod'


class StrategyBase(ABC):
    name: str = "base"
    hold_days: int = 0
    param_space: Dict[str, Any] = {}

    @abstractmethod
    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        """피처 계산. 반드시 shift(1) 또는 prev_* 규약. feature_audit 로 검증 대상."""

    @abstractmethod
    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        """bar_idx 시점에서 stock_code 에 대한 매수 신호. 없으면 None."""

    @abstractmethod
    def exit_signal(
        self,
        position: Position,
        features: pd.DataFrame,
        bar_idx: int,
        current_price: Optional[float] = None,
    ) -> Optional[ExitOrder]:
        """보유 중인 position 에 대한 매도 신호.

        Args:
            position: 보유 포지션.
            features: 전략이 prepare_features 로 계산한 DF.
            bar_idx: 현재 분봉 인덱스.
            current_price: 현재 분봉 close (TP/SL 체크용). None 이면 훅 미사용 전략.
        """
