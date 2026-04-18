"""프리마켓 심리 점수 계산 (순수 함수).

PreMarketAnalyzer의 stateless 로직을 분리해 단위 테스트 용이성을 높임.
입력은 `PreMarketSnapshot` 리스트 (duck-typed: timestamp/avg_change_pct/up_count/
down_count/unchanged_count 속성만 요구).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

from utils.logger import setup_logger

if TYPE_CHECKING:
    from core.pre_market_analyzer import PreMarketSnapshot

logger = setup_logger(__name__)


def calculate_sentiment_score(snapshots: List['PreMarketSnapshot']) -> float:
    """심리 점수 계산 (-1.0 ~ +1.0).

    가중치:
    - 방향 점수 (40%): 평균 등락률 정규화
    - 폭 점수 (30%): 상승 종목 비율
    - 추세 점수 (30%): 후반 스냅샷 vs 전반 스냅샷
    - 08:30 이후 스냅샷 가중치 2배
    """
    if not snapshots:
        return 0.0

    weighted_changes: List[float] = []
    weighted_breadths: List[float] = []
    weights: List[float] = []

    for snap in snapshots:
        # 08:30 이후 가중치 2배
        weight = 2.0 if snap.timestamp.hour == 8 and snap.timestamp.minute >= 30 else 1.0
        weights.append(weight)
        weighted_changes.append(snap.avg_change_pct * weight)

        total = snap.up_count + snap.down_count + snap.unchanged_count
        if total > 0:
            breadth = (snap.up_count - snap.down_count) / total
            weighted_breadths.append(breadth * weight)

    total_weight = sum(weights) if weights else 1.0

    # 1) 방향 점수 (40%): 가중 평균 등락률 → [-1, 1] 정규화
    avg_change = sum(weighted_changes) / total_weight
    direction_score = max(-1.0, min(1.0, avg_change / 1.0))  # ±1%를 ±1.0으로

    # 2) 폭 점수 (30%): 가중 평균 상승비율
    avg_breadth = sum(weighted_breadths) / total_weight if weighted_breadths else 0.0
    breadth_score = max(-1.0, min(1.0, avg_breadth))

    # 3) 추세 점수 (30%): 후반 vs 전반 비교
    trend_score = 0.0
    if len(snapshots) >= 2:
        mid = len(snapshots) // 2
        first_half_avg = sum(s.avg_change_pct for s in snapshots[:mid]) / mid
        second_half_avg = sum(s.avg_change_pct for s in snapshots[mid:]) / (len(snapshots) - mid)
        diff = second_half_avg - first_half_avg
        trend_score = max(-1.0, min(1.0, diff / 0.5))  # ±0.5% 차이를 ±1.0으로

    # 가중 합산
    score = direction_score * 0.4 + breadth_score * 0.3 + trend_score * 0.3

    logger.debug(
        f"[프리마켓] 심리 점수: 방향={direction_score:.2f}(40%), "
        f"폭={breadth_score:.2f}(30%), 추세={trend_score:.2f}(30%) → {score:.2f}"
    )
    return round(max(-1.0, min(1.0, score)), 2)


def score_to_sentiment(score: float) -> str:
    """점수를 심리 문자열로 변환 (임계값은 StrategySettings.PreMarket에서 조회)."""
    from config.strategy_settings import StrategySettings
    pm = StrategySettings.PreMarket

    if score <= pm.EXTREME_BEARISH_THRESHOLD:
        return 'extreme_bearish'
    elif score <= pm.VERY_BEARISH_THRESHOLD:
        return 'very_bearish'
    elif score <= pm.BEARISH_THRESHOLD:
        return 'bearish'
    elif score >= pm.BULLISH_THRESHOLD:
        return 'bullish'
    else:
        return 'neutral'


def calculate_expected_gap(snapshots: List['PreMarketSnapshot']) -> float:
    """최근 스냅샷 기반 예상 갭 (%)."""
    if not snapshots:
        return 0.0
    recent = snapshots[-1]
    return round(recent.avg_change_pct, 2)


def calculate_volatility_level(snapshots: List['PreMarketSnapshot']) -> str:
    """스냅샷 간 변동성 수준 판단 ('low' / 'normal' / 'high')."""
    if len(snapshots) < 2:
        return 'normal'

    changes = [s.avg_change_pct for s in snapshots]
    avg = sum(changes) / len(changes)
    variance = sum((c - avg) ** 2 for c in changes) / len(changes)
    std_dev = variance ** 0.5

    if std_dev > 0.5:
        return 'high'
    elif std_dev < 0.1:
        return 'low'
    else:
        return 'normal'
