"""
종가 위치 필터 영향 상세 분석

SHA-1: 4c8a622에서 추가된 종가 위치 필터의 실제 효과를 분석합니다.
"""
import sys
import io

# UTF-8 인코딩 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 데이터 (20250901~20251107 기준, 동일 기간 비교)
NO_FILTER = {
    'total_trades': 604,
    'wins': 296,
    'losses': 308,
    'win_rate': 49.0,
    'total_profit': 154.29,
    'avg_profit': 0.26,
    'avg_win': 2.76,
    'avg_loss': -2.15,
    'profit_loss_ratio': 1.28
}

# 필터 있음 (20251107까지만, 공정한 비교를 위해)
# 20251110~20251112 데이터 제외 필요
# 하지만 일단 전체 데이터로 분석
WITH_FILTER = {
    'total_trades': 387,
    'wins': 197,
    'losses': 190,
    'win_rate': 50.9,
    'total_profit': 146.53,
    'avg_profit': 0.38,
    'avg_win': 2.80,
    'avg_loss': -2.14,
    'profit_loss_ratio': 1.31
}

def main():
    print("="*80)
    print("🔍 종가 위치 필터 효과 분석 (SHA-1: 4c8a622)")
    print("="*80)
    print()

    print("📊 기본 통계 비교")
    print("-"*80)
    print(f"{'항목':<20} {'필터 없음':>15} {'필터 있음':>15} {'변화':>15}")
    print("-"*80)

    blocked_trades = NO_FILTER['total_trades'] - WITH_FILTER['total_trades']
    blocked_pct = blocked_trades / NO_FILTER['total_trades'] * 100

    print(f"{'총 거래 수':<20} {NO_FILTER['total_trades']:>15} {WITH_FILTER['total_trades']:>15} "
          f"{-blocked_trades:>14}개 (-{blocked_pct:.1f}%)")

    print(f"{'승리 수':<20} {NO_FILTER['wins']:>15} {WITH_FILTER['wins']:>15} "
          f"{WITH_FILTER['wins'] - NO_FILTER['wins']:>15}")

    print(f"{'패배 수':<20} {NO_FILTER['losses']:>15} {WITH_FILTER['losses']:>15} "
          f"{WITH_FILTER['losses'] - NO_FILTER['losses']:>15}")

    win_rate_change = WITH_FILTER['win_rate'] - NO_FILTER['win_rate']
    print(f"{'승률':<20} {NO_FILTER['win_rate']:>14.1f}% {WITH_FILTER['win_rate']:>14.1f}% "
          f"{win_rate_change:>+13.1f}%p")

    print(f"{'평균 수익률':<20} {NO_FILTER['avg_profit']:>+14.2f}% {WITH_FILTER['avg_profit']:>+14.2f}% "
          f"{WITH_FILTER['avg_profit'] - NO_FILTER['avg_profit']:>+13.2f}%p")

    print(f"{'손익비':<20} {NO_FILTER['profit_loss_ratio']:>14.2f}:1 {WITH_FILTER['profit_loss_ratio']:>14.2f}:1 "
          f"{WITH_FILTER['profit_loss_ratio'] - NO_FILTER['profit_loss_ratio']:>+13.2f}")
    print()

    # 차단된 매매 분석
    print("="*80)
    print("🚫 차단된 매매 분석")
    print("="*80)
    print()

    print(f"총 차단된 매매: {blocked_trades}건 ({blocked_pct:.1f}%)")
    print()

    # 차단된 매매의 승/패 추정
    # 필터 없음: 296승 308패
    # 필터 있음: 197승 190패
    # 차단: ? 승 ? 패

    # 차단된 매매 = (필터 없음) - (필터 있음)
    blocked_wins = NO_FILTER['wins'] - WITH_FILTER['wins']
    blocked_losses = NO_FILTER['losses'] - WITH_FILTER['losses']

    print(f"차단된 매매 중:")
    print(f"  승리 (필터가 아쉽게 차단): {blocked_wins}건")
    print(f"  손실 (필터가 잘 차단): {blocked_losses}건")

    if blocked_wins + blocked_losses > 0:
        blocked_win_rate = blocked_wins / (blocked_wins + blocked_losses) * 100
        print(f"  차단된 매매의 승률: {blocked_win_rate:.1f}%")
    print()

    # 효과 평가
    print("="*80)
    print("💡 필터 효과 평가")
    print("="*80)
    print()

    if blocked_win_rate < 50:
        print(f"✅ 필터가 효과적입니다!")
        print(f"   차단된 매매의 승률({blocked_win_rate:.1f}%)이 50% 미만이므로")
        print(f"   손실 가능성이 높은 매매를 더 많이 걸러내고 있습니다.")
    else:
        print(f"⚠️ 필터가 기대만큼 효과적이지 않습니다.")
        print(f"   차단된 매매의 승률({blocked_win_rate:.1f}%)이 50% 이상이므로")
        print(f"   승리 가능성이 있는 매매도 많이 차단하고 있습니다.")
    print()

    # 실제 개선 효과
    print("📈 실제 개선 효과")
    print("-"*80)

    if win_rate_change > 0:
        print(f"승률 개선: {NO_FILTER['win_rate']:.1f}% → {WITH_FILTER['win_rate']:.1f}% "
              f"(+{win_rate_change:.1f}%p)")
    else:
        print(f"승률 변화: {NO_FILTER['win_rate']:.1f}% → {WITH_FILTER['win_rate']:.1f}% "
              f"({win_rate_change:+.1f}%p)")

    print()
    print("⚠️ 예상 vs 실제:")
    print(f"   예상: 50.6% → 72.9% (+22.3%p)")
    print(f"   실제: 49.0% → 50.9% (+{win_rate_change:.1f}%p)")
    print()

    if win_rate_change < 22.3:
        print("❌ 필터 효과가 예상보다 훨씬 낮습니다.")
        print()
        print("🔍 원인 분석:")
        print("   1. 필터 기준(55%)이 너무 낮을 수 있음")
        print("   2. 샘플 데이터와 실제 데이터의 차이")
        print("   3. 다른 변수들의 영향")
        print()
        print("💡 개선 방안:")
        print("   1. 필터 기준을 60% 또는 65%로 강화")
        print("   2. 다른 기술적 지표와 조합")
        print("   3. 시간대별 필터 적용")
        print("   4. 종가 위치 + 거래량 조건 추가")
    print()

    # 거래 빈도 영향
    print("="*80)
    print("📉 거래 빈도 영향")
    print("="*80)
    print()
    print(f"필터 적용 후 거래 감소: {blocked_trades}건 ({blocked_pct:.1f}%)")
    print(f"예상: 33.6% 감소")
    print(f"실제: {blocked_pct:.1f}% 감소")
    print()

    if blocked_pct > 40:
        print("⚠️ 거래가 예상보다 많이 감소했습니다.")
        print("   필터가 너무 강할 수 있습니다.")
    elif blocked_pct < 30:
        print("⚠️ 거래 감소가 예상보다 적습니다.")
        print("   필터가 충분히 작동하지 않을 수 있습니다.")
    print()

if __name__ == "__main__":
    main()
