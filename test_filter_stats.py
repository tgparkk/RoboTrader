"""필터 통계 테스트"""
import sys
import io

# UTF-8 인코딩 설정 (Windows)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

from core.indicators.filter_stats import filter_stats

# 통계 초기화
filter_stats.reset()

# 시뮬레이션
print("시뮬레이션 시작...")
print()

# 패턴 1: 통과
filter_stats.increment_total()
print("패턴 1: ✅ 통과 → 실제 매매")

# 패턴 2: 마이너스 조합 필터 차단 (필터 없었다면 손실)
filter_stats.increment_total()
filter_stats.increment('pattern_combination_filter', 'Stage 1 상승 지속성 부족', would_win=False)
print("패턴 2: 🚫 마이너스 조합 필터 차단 (필터 없었다면 손실)")

# 패턴 3: 통과
filter_stats.increment_total()
print("패턴 3: ✅ 통과 → 실제 매매")

# 패턴 4: 종가 위치 필터 차단 (필터 없었다면 손실)
filter_stats.increment_total()
filter_stats.increment('close_position_filter', '종가 하단위치 45.2% < 55%', would_win=False)
print("패턴 4: 🚫 종가 위치 필터 차단 (필터 없었다면 손실)")

# 패턴 5: 종가 위치 필터 차단 (필터 없었다면 손실)
filter_stats.increment_total()
filter_stats.increment('close_position_filter', '종가 하단위치 38.5% < 55%', would_win=False)
print("패턴 5: 🚫 종가 위치 필터 차단 (필터 없었다면 손실)")

# 패턴 6: 마이너스 조합 필터 차단 (필터 없었다면 승리) - 잘못된 차단 사례
filter_stats.increment_total()
filter_stats.increment('pattern_combination_filter', 'Stage 2 거래량 조건 부족', would_win=True)
print("패턴 6: 🚫 마이너스 조합 필터 차단 (필터 없었다면 승리 - 아쉬운 차단)")

# 패턴 7: 종가 위치 필터 차단 (필터 없었다면 손실)
filter_stats.increment_total()
filter_stats.increment('close_position_filter', '종가 하단위치 48.5% < 55%', would_win=False)
print("패턴 7: 🚫 종가 위치 필터 차단 (필터 없었다면 손실)")

# 패턴 8: 통과
filter_stats.increment_total()
print("패턴 8: ✅ 통과 → 실제 매매")

print()
print("="*60)
print(filter_stats.get_summary())
print("="*60)
