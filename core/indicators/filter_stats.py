"""
필터 통계 수집 모듈
각 필터의 차단 횟수를 추적하여 통계에 기록
"""

from typing import Dict
import threading


class FilterStats:
    """필터 통계 수집기 (싱글톤)"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """내부 초기화"""
        self.stats = {
            'pattern_combination_filter': 0,  # 마이너스 수익 조합 필터
            'close_position_filter': 0,       # 종가 위치 필터
            'total_patterns_checked': 0,      # 전체 체크된 패턴 수
        }
        self.blocked_details = {
            'pattern_combination_filter': [],
            'close_position_filter': []
        }

    def reset(self):
        """통계 초기화"""
        self._initialize()

    def increment(self, filter_name: str, reason: str = None):
        """필터 차단 횟수 증가

        Args:
            filter_name: 필터 이름 ('pattern_combination_filter' 또는 'close_position_filter')
            reason: 차단 사유 (선택)
        """
        if filter_name in self.stats:
            self.stats[filter_name] += 1

            if reason and filter_name in self.blocked_details:
                self.blocked_details[filter_name].append(reason)

    def increment_total(self):
        """전체 체크 횟수 증가"""
        self.stats['total_patterns_checked'] += 1

    def get_stats(self) -> Dict:
        """통계 조회"""
        return self.stats.copy()

    def get_summary(self) -> str:
        """통계 요약 문자열"""
        total = self.stats['total_patterns_checked']
        combo_blocked = self.stats['pattern_combination_filter']
        close_blocked = self.stats['close_position_filter']

        if total == 0:
            return "필터 통계: 데이터 없음"

        passed = total - combo_blocked - close_blocked

        summary = f"""
=== 📊 필터 통계 ===
전체 패턴 체크: {total}건
  ✅ 통과: {passed}건 ({passed/total*100:.1f}%)
  🚫 마이너스 조합 필터 차단: {combo_blocked}건 ({combo_blocked/total*100:.1f}%)
  🚫 종가 위치 필터 차단: {close_blocked}건 ({close_blocked/total*100:.1f}%)
"""
        return summary.strip()


# 싱글톤 인스턴스
filter_stats = FilterStats()
