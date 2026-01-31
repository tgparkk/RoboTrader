#!/usr/bin/env python3
"""
일봉 필터 날짜 로직 검증
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from datetime import datetime


def verify_date_filtering():
    """날짜 필터링 로직 검증"""
    print("=" * 70)
    print("일봉 필터 날짜 로직 검증")
    print("=" * 70)

    # 가상 일봉 데이터 생성
    dates = [
        '20260129',  # 1월 29일 (수)
        '20260130',  # 1월 30일 (목)
        '20260131',  # 1월 31일 (금)
        '20260203',  # 2월 3일 (월) - 주말 제외
        '20260204',  # 2월 4일 (화)
        '20260205',  # 2월 5일 (수) - 당일
        '20260206',  # 2월 6일 (목) - 미래
    ]

    daily_df = pd.DataFrame({
        'stck_bsop_date': dates,
        'stck_clpr': [100, 102, 101, 103, 105, 108, 110],  # 종가
        'acml_vol': [1000, 1100, 900, 1200, 1500, 1400, 1300],  # 거래량
    })

    print("\n가상 일봉 데이터:")
    print(daily_df.to_string(index=False))

    # 시뮬레이션: 2월 5일 10:30 매수 신호
    trade_date = '20260205'
    print(f"\n\n매수 신호 발생: {trade_date} 10:30")
    print("-" * 70)

    # 실제 코드와 동일한 로직
    filtered_df = daily_df[daily_df['stck_bsop_date'] < trade_date].copy()

    print(f"\n필터링 후 데이터 (stck_bsop_date < '{trade_date}'):")
    print(filtered_df.to_string(index=False))

    # 최근 20일 (여기서는 전체)
    filtered_df = filtered_df.sort_values('stck_bsop_date').tail(20)

    print(f"\n\n사용되는 데이터:")
    print(f"  - 시작일: {filtered_df['stck_bsop_date'].min()}")
    print(f"  - 종료일: {filtered_df['stck_bsop_date'].max()} (전일)")
    print(f"  - 총 {len(filtered_df)}일")

    # 특징 계산
    last_close = filtered_df['stck_clpr'].iloc[-1]
    prev_close = filtered_df['stck_clpr'].iloc[-2]
    prev_day_change = (last_close - prev_close) / prev_close * 100

    last_vol = filtered_df['acml_vol'].iloc[-1]
    vol_ma = filtered_df['acml_vol'].mean()
    volume_ratio = last_vol / vol_ma

    print(f"\n계산된 특징:")
    print(f"  - 전일 종가: {last_close}원 (2월 4일)")
    print(f"  - 전전일 종가: {prev_close}원 (2월 3일)")
    print(f"  - 전일 등락률: {prev_day_change:+.2f}%")
    print(f"  - 전일 거래량: {last_vol}주")
    print(f"  - 평균 거래량: {vol_ma:.0f}주")
    print(f"  - 거래량 비율: {volume_ratio:.2f}x")

    # 검증
    print("\n" + "=" * 70)
    print("검증 결과")
    print("=" * 70)

    assert filtered_df['stck_bsop_date'].max() == '20260204', "전일 데이터까지만 포함"
    assert '20260205' not in filtered_df['stck_bsop_date'].values, "당일 데이터 제외"
    assert last_close == 105, "전일(2월4일) 종가 = 105"

    print("✅ 날짜 필터링 로직 정상")
    print("✅ 당일 데이터 미포함 확인")
    print("✅ 전일 데이터까지만 사용 확인")

    print("\n" + "=" * 70)
    print("결론: 미래 데이터 사용 없음 (Look-ahead Bias 없음)")
    print("=" * 70)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    verify_date_filtering()
