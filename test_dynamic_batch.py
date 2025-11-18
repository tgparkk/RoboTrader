"""
동적 배치 계산기 테스트 스크립트
다양한 종목 수에 따른 배치 크기와 예상 소요 시간 시뮬레이션
"""
from core.dynamic_batch_calculator import DynamicBatchCalculator


def test_various_stock_counts():
    """다양한 종목 수에 대한 배치 전략 테스트"""
    calculator = DynamicBatchCalculator()

    # 테스트할 종목 수
    test_cases = [5, 10, 20, 30, 40, 50, 60, 70, 80, 100]

    print("=" * 100)
    print("🔬 동적 배치 계산기 시뮬레이션")
    print("=" * 100)
    print(f"\n{'종목수':<10} {'배치크기':<12} {'배치수':<10} {'배치지연':<12} "
          f"{'예상시간':<12} {'API속도':<15} {'안전여부':<10}")
    print("-" * 100)

    for stock_count in test_cases:
        batch_size, batch_delay = calculator.calculate_optimal_batch(stock_count)

        # 예상 통계 계산
        num_batches = (stock_count + batch_size - 1) // batch_size
        estimated_time = calculator.get_estimated_time(stock_count, batch_size, batch_delay)
        calls_per_second = calculator.get_estimated_calls_per_second(batch_size, batch_delay)

        # 안전 여부 판단
        is_safe_time = estimated_time <= calculator.TARGET_UPDATE_TIME
        is_safe_speed = calls_per_second <= calculator.safe_calls_per_second
        is_safe = "✅ 안전" if (is_safe_time and is_safe_speed) else "⚠️ 주의"

        print(f"{stock_count:<10} {batch_size:<12} {num_batches:<10} {batch_delay:<12.2f} "
              f"{estimated_time:<12.1f} {calls_per_second:<15.1f} {is_safe:<10}")

    print("=" * 100)
    print("\n📊 분석 결과:")
    print(f"   - API 제한: 초당 최대 {calculator.API_LIMIT_PER_SECOND}개")
    print(f"   - 안전 마진: {calculator.SAFETY_MARGIN * 100:.0f}% (실제 초당 {calculator.safe_calls_per_second}개)")
    print(f"   - 목표 시간: {calculator.TARGET_UPDATE_TIME}초 내 완료")
    print(f"   - 종목당 API: {calculator.APIS_PER_STOCK}개 (분봉 1 + 현재가 1)")
    print()


def test_extreme_cases():
    """극단적인 경우 테스트"""
    calculator = DynamicBatchCalculator()

    print("\n" + "=" * 100)
    print("🧪 극단 케이스 테스트")
    print("=" * 100)

    extreme_cases = [
        (0, "종목 없음"),
        (1, "종목 1개 (최소)"),
        (150, "종목 150개 (과부하)"),
        (200, "종목 200개 (심각한 과부하)")
    ]

    for stock_count, description in extreme_cases:
        print(f"\n[{description}]")
        batch_size, batch_delay = calculator.calculate_optimal_batch(stock_count)

        if stock_count > 0:
            estimated_time = calculator.get_estimated_time(stock_count, batch_size, batch_delay)
            calls_per_second = calculator.get_estimated_calls_per_second(batch_size, batch_delay)

            print(f"   배치 크기: {batch_size}개")
            print(f"   배치 지연: {batch_delay:.2f}초")
            print(f"   예상 시간: {estimated_time:.1f}초")
            print(f"   API 속도: {calls_per_second:.1f}개/초")

            if estimated_time > calculator.TARGET_UPDATE_TIME:
                print(f"   ⚠️ 경고: 목표 시간 {calculator.TARGET_UPDATE_TIME}초 초과!")
            if calls_per_second > calculator.safe_calls_per_second:
                print(f"   ⚠️ 경고: 안전 속도 {calculator.safe_calls_per_second}개/초 초과!")

    print()


def test_70_stocks_detailed():
    """70개 종목 상세 분석 (실전 케이스)"""
    calculator = DynamicBatchCalculator()

    print("\n" + "=" * 100)
    print("🎯 70개 종목 실전 시뮬레이션 (조건검색 전형적인 결과)")
    print("=" * 100)

    stock_count = 70
    batch_size, batch_delay = calculator.calculate_optimal_batch(stock_count)

    num_batches = (stock_count + batch_size - 1) // batch_size
    estimated_time = calculator.get_estimated_time(stock_count, batch_size, batch_delay)
    calls_per_second = calculator.get_estimated_calls_per_second(batch_size, batch_delay)

    print(f"\n📈 배치 전략:")
    print(f"   총 종목 수: {stock_count}개")
    print(f"   배치 크기: {batch_size}개")
    print(f"   총 배치 수: {num_batches}회")
    print(f"   배치당 지연: {batch_delay:.2f}초")

    print(f"\n⏱️ 예상 성능:")
    print(f"   완료 시간: {estimated_time:.2f}초 (목표: {calculator.TARGET_UPDATE_TIME}초)")
    print(f"   API 호출 속도: {calls_per_second:.1f}개/초 (제한: {calculator.API_LIMIT_PER_SECOND}개/초)")
    print(f"   안전 마진 고려: {calls_per_second:.1f}/{calculator.safe_calls_per_second} = "
          f"{(calls_per_second / calculator.safe_calls_per_second * 100):.1f}%")

    print(f"\n📊 배치별 타임라인:")
    cumulative_time = 0
    for i in range(num_batches):
        start_idx = i * batch_size
        end_idx = min((i + 1) * batch_size, stock_count)
        batch_stocks = end_idx - start_idx

        print(f"   배치 {i+1:2d}: {cumulative_time:5.2f}초 - 종목 {start_idx+1:2d}~{end_idx:2d} "
              f"({batch_stocks}개) → API {batch_stocks * 2}개 호출")
        cumulative_time += batch_delay

    print(f"\n   총 소요: {estimated_time:.2f}초")

    # 안전성 평가
    print(f"\n✅ 안전성 평가:")
    if estimated_time <= calculator.TARGET_UPDATE_TIME:
        print(f"   시간: ✅ 통과 ({estimated_time:.1f}초 <= {calculator.TARGET_UPDATE_TIME}초)")
    else:
        print(f"   시간: ⚠️ 주의 ({estimated_time:.1f}초 > {calculator.TARGET_UPDATE_TIME}초)")

    if calls_per_second <= calculator.safe_calls_per_second:
        print(f"   속도: ✅ 통과 ({calls_per_second:.1f} <= {calculator.safe_calls_per_second}개/초)")
    else:
        print(f"   속도: ⚠️ 주의 ({calls_per_second:.1f} > {calculator.safe_calls_per_second}개/초)")

    print()


if __name__ == "__main__":
    test_various_stock_counts()
    test_extreme_cases()
    test_70_stocks_detailed()

    print("\n" + "=" * 100)
    print("🎉 테스트 완료!")
    print("=" * 100)
