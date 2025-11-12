"""
시장 거래시간 설정 테스트 스크립트
수능일 및 일반 거래일 시간 설정이 제대로 동작하는지 확인
"""
from datetime import datetime
from config.market_hours import MarketHours

def test_market_hours():
    """시장 거래시간 테스트"""
    print("=" * 80)
    print("시장 거래시간 설정 테스트")
    print("=" * 80)

    # 테스트 케이스: 일반 거래일
    normal_day = datetime(2025, 11, 12)  # 2025년 11월 12일 (화요일)
    print(f"\n[1] 일반 거래일: {normal_day.strftime('%Y-%m-%d (%a)')}")
    print("-" * 80)
    print(MarketHours.get_today_info('KRX'))

    hours_normal = MarketHours.get_market_hours('KRX', normal_day)
    print(f"\n상세 설정:")
    print(f"  - 장 시작: {hours_normal['market_open']}")
    print(f"  - 장 마감: {hours_normal['market_close']}")
    print(f"  - 매수 중단: {hours_normal['buy_cutoff_hour']}:00 이후")
    print(f"  - 일괄 청산: {hours_normal['eod_liquidation_hour']}:{hours_normal['eod_liquidation_minute']:02d}")
    print(f"  - 특수일 여부: {hours_normal['is_special_day']}")

    # 테스트 케이스: 수능일
    suneung_day = datetime(2025, 11, 13)  # 2025년 11월 13일 (수요일) - 수능일
    print(f"\n[2] 수능일: {suneung_day.strftime('%Y-%m-%d (%a)')}")
    print("-" * 80)

    hours_suneung = MarketHours.get_market_hours('KRX', suneung_day)
    print(MarketHours.get_today_info('KRX'))

    print(f"\n상세 설정:")
    print(f"  - 장 시작: {hours_suneung['market_open']}")
    print(f"  - 장 마감: {hours_suneung['market_close']}")
    print(f"  - 매수 중단: {hours_suneung['buy_cutoff_hour']}:00 이후")
    print(f"  - 일괄 청산: {hours_suneung['eod_liquidation_hour']}:{hours_suneung['eod_liquidation_minute']:02d}")
    print(f"  - 특수일 여부: {hours_suneung['is_special_day']}")
    if hours_suneung.get('reason'):
        print(f"  - 사유: {hours_suneung['reason']}")

    # 테스트 케이스: 시간별 체크
    print(f"\n[3] 수능일 시간대별 체크")
    print("-" * 80)

    test_times = [
        datetime(2025, 11, 13, 9, 30),   # 09:30 - 일반일이면 장중, 수능일이면 장전
        datetime(2025, 11, 13, 10, 30),  # 10:30 - 수능일 장중
        datetime(2025, 11, 13, 12, 30),  # 12:30 - 일반일 매수중단, 수능일 매수가능
        datetime(2025, 11, 13, 13, 30),  # 13:30 - 수능일 매수중단
        datetime(2025, 11, 13, 15, 30),  # 15:30 - 일반일 장마감, 수능일 장중
        datetime(2025, 11, 13, 16, 0),   # 16:00 - 수능일 청산시간
        datetime(2025, 11, 13, 16, 30),  # 16:30 - 수능일 장마감
    ]

    for test_time in test_times:
        is_open = MarketHours.is_market_open('KRX', test_time)
        should_stop_buy = MarketHours.should_stop_buying('KRX', test_time)
        is_eod = MarketHours.is_eod_liquidation_time('KRX', test_time)

        status = []
        if is_open:
            status.append("[O] 장중")
        else:
            status.append("[X] 장외")

        if should_stop_buy:
            status.append("[STOP] 매수중단")
        else:
            status.append("[BUY] 매수가능")

        if is_eod:
            status.append("[EOD] 청산시간")

        print(f"{test_time.strftime('%H:%M')} - {' | '.join(status)}")

    # 테스트 케이스: 일반일 vs 수능일 비교
    print(f"\n[4] 일반일 vs 수능일 비교")
    print("-" * 80)
    print(f"{'항목':<20} {'일반일 (11/12)':<20} {'수능일 (11/13)':<20}")
    print("-" * 80)
    print(f"{'장 시작':<20} {hours_normal['market_open'].strftime('%H:%M'):<20} {hours_suneung['market_open'].strftime('%H:%M'):<20}")
    print(f"{'장 마감':<20} {hours_normal['market_close'].strftime('%H:%M'):<20} {hours_suneung['market_close'].strftime('%H:%M'):<20}")
    print(f"{'매수 중단':<20} {hours_normal['buy_cutoff_hour']:02d}:00 이후{'':<9} {hours_suneung['buy_cutoff_hour']:02d}:00 이후{'':<9}")
    print(f"{'일괄 청산':<20} {hours_normal['eod_liquidation_hour']:02d}:{hours_normal['eod_liquidation_minute']:02d}{'':<15} {hours_suneung['eod_liquidation_hour']:02d}:{hours_suneung['eod_liquidation_minute']:02d}{'':<15}")

    # 해외 시장 예시
    print(f"\n[5] 해외 시장 설정 예시 (향후 확장)")
    print("-" * 80)

    for market in ['NYSE', 'NASDAQ', 'TSE']:
        try:
            market_info = MarketHours.get_market_hours(market, normal_day)
            print(f"\n{market}:")
            print(f"  - 타임존: {market_info['timezone']}")
            print(f"  - 장 시작: {market_info['market_open']}")
            print(f"  - 장 마감: {market_info['market_close']}")
        except Exception as e:
            print(f"\n{market}: 설정 확인 필요 - {e}")

    print("\n" + "=" * 80)
    print("[OK] 테스트 완료!")
    print("=" * 80)


if __name__ == "__main__":
    test_market_hours()
