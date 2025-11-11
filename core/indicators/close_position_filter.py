"""
종가 위치 필터 - 돌파봉 종가가 캔들 하단에 위치한 패턴 차단
승률 50.6% → 72.9% 개선 효과
"""

import logging
from typing import Dict, Tuple, Optional


class ClosePositionFilter:
    """종가 위치 기반 필터"""

    def __init__(self, logger: Optional[logging.Logger] = None, min_close_position: float = 0.55):
        """
        Args:
            logger: 로거
            min_close_position: 최소 종가 위치 (0~1, 기본 0.55 = 55%)
        """
        self.logger = logger or logging.getLogger(__name__)
        self.min_close_position = min_close_position

    def should_exclude(self, debug_info: Dict) -> Tuple[bool, Optional[str]]:
        """
        종가 위치 기준으로 패턴 제외 여부 판단

        Args:
            debug_info: 패턴 디버그 정보 (best_breakout 포함)

        Returns:
            (should_exclude, reason): 제외 여부와 사유
        """
        # best_breakout 정보 확인
        best_breakout = debug_info.get('best_breakout')

        if not best_breakout:
            # best_breakout 정보 없으면 통과 (다른 필터에서 처리)
            return False, None

        # 캔들 정보 추출
        candle_high = best_breakout.get('high', 0)
        candle_low = best_breakout.get('low', 0)
        candle_close = best_breakout.get('close', 0)

        # 캔들 범위 계산
        candle_range = candle_high - candle_low

        if candle_range <= 0:
            # 범위가 0이면 통과 (이상한 데이터)
            return False, None

        # 종가 위치 계산 (0 = 저가, 1 = 고가)
        close_position = (candle_close - candle_low) / candle_range

        # 종가가 캔들 하단에 위치하면 차단
        if close_position < self.min_close_position:
            reason = f"돌파봉 종가 하단위치 {close_position:.1%} < {self.min_close_position:.0%} (위에서 저항받음)"
            self.logger.info(f"🚫 {reason}")
            return True, reason

        # 통과
        return False, None
