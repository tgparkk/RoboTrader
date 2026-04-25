"""Walk-forward Fold 정의 — Stage 1 (단일 폴드) + Stage 2 (3폴드).

분봉 데이터: 2025-02-24 ~ 현재 (~14개월).
Spec 의 Stage 1 Fold 1:
  train: 2025-09 ~ 2026-02 (6 months)
  test:  2026-03 ~ 2026-04 (2 months)

universe 는 외부 (loader) 에서 결정 — Fold 는 dates 와 식별자만 보유.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class Fold:
    name: str
    train_start: str   # YYYYMMDD
    train_end: str
    test_start: str
    test_end: str
    universe: List[str] = field(default_factory=list)

    @property
    def daily_history_start(self) -> str:
        """일봉 history 시작일 — train_start 의 1년 전 (overnight 전략 충분).

        실제 사용 시 strategy 가 prepare_features 에서 적절한 lookback 만 본다는 가정.
        """
        y = int(self.train_start[:4])
        return f"{y - 1}{self.train_start[4:]}"


# Stage 1 default fold (Spec § 3 Walk-forward 3폴드 중 Fold 1)
STAGE1_FOLD1 = Fold(
    name="fold1",
    train_start="20250901",
    train_end="20260229",
    test_start="20260301",
    test_end="20260424",
)


# 작은 smoke fold (디버깅 + 인프라 검증용)
SMOKE_FOLD = Fold(
    name="smoke",
    train_start="20260101",
    train_end="20260228",
    test_start="20260301",
    test_end="20260331",
)
