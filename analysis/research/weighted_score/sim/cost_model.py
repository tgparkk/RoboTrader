"""거래비용 모델.

편도 비용 = 수수료(~0.015%) + 매도 세금(증권거래세 0.18% + 농특세 0.15%→매도시만)
         + 슬리피지 고정 0.05%
  ≈ 약 0.28% 편도 (평균적으로 매수/매도 섞으면)

여기서는 편도 비용을 고정 상수로 단순화하고, 진입/청산 시 각각 차감한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis.research.weighted_score import config


@dataclass(frozen=True)
class CostModel:
    one_way_pct: float = config.COST_ONE_WAY_PCT  # 편도 비용 (%)

    @property
    def round_trip_pct(self) -> float:
        return 2.0 * self.one_way_pct

    def apply_round_trip(self, gross_pct: float) -> float:
        """총 수익률(%)에서 왕복 거래비용을 차감해 순 수익률 반환."""
        return gross_pct - self.round_trip_pct

    def apply_one_way(self, gross_pct: float) -> float:
        """편도 비용만 차감 (현재 보유 중인 포지션 평가 시)."""
        return gross_pct - self.one_way_pct

    def entry_fill_adjusted(self, price: float) -> float:
        """진입가에 슬리피지·비용을 반영한 유효 매수단가.

        매수 시 슬리피지·수수료로 인해 표시가보다 약간 높은 가격에 체결됐다고 가정.
        """
        return price * (1.0 + self.one_way_pct / 100.0)

    def exit_fill_adjusted(self, price: float) -> float:
        """청산가에 비용 반영 — 매도 시 표시가보다 약간 낮은 가격에 체결."""
        return price * (1.0 - self.one_way_pct / 100.0)


DEFAULT_COST = CostModel()
