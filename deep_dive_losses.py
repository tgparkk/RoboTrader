# -*- coding: utf-8 -*-
"""
손실 거래 심층 분석 - 분봉 데이터 확인
"""
import pickle
import os
from pathlib import Path

def analyze_loss_with_minute_data():
    """손실 거래의 실제 분봉 데이터 분석"""

    # 분석할 손실 케이스 (10시대 집중)
    loss_cases = [
        ('20251029', '117730', '10:25'),  # -2.50%
        ('20251029', '340930', '10:34'),  # -2.50%
        ('20251029', '114190', '10:48'),  # -2.50%
        ('20251028', '382900', '10:39'),  # -2.50%
        ('20251028', '090360', '10:45'),  # -2.50%
    ]

    print("="*70)
    print("손실 거래 심층 분석 (10시대 집중)")
    print("="*70)

    for date, stock, buy_time in loss_cases:
        print(f"\n{'='*70}")
        print(f"종목: {stock} | 매수 시간: {date[-4:]} {buy_time}")
        print(f"{'='*70}")

        # 분봉 데이터 파일
        minute_file = f"cache/minute_data/{stock}_{date}.pkl"

        if not os.path.exists(minute_file):
            print(f"  분봉 데이터 없음: {minute_file}")
            continue

        try:
            with open(minute_file, 'rb') as f:
                data = pickle.load(f)

            if data is None or len(data) == 0:
                print(f"  데이터 비어있음")
                continue

            # 매수 시간 인덱스 찾기
            buy_hour = int(buy_time.split(':')[0])
            buy_min = int(buy_time.split(':')[1])

            # 해당 시간대 전후 데이터 분석
            relevant_data = []
            for i, row in data.iterrows():
                try:
                    time_str = str(row.get('datetime', ''))
                    if not time_str:
                        continue

                    # 시간 파싱
                    if ' ' in time_str:
                        time_part = time_str.split()[1]
                    else:
                        time_part = time_str

                    if ':' in time_part:
                        hour = int(time_part.split(':')[0])
                        minute = int(time_part.split(':')[1])

                        # 매수 시간 전후 30분
                        time_in_min = hour * 60 + minute
                        buy_time_in_min = buy_hour * 60 + buy_min

                        if abs(time_in_min - buy_time_in_min) <= 30:
                            relevant_data.append({
                                'time': f"{hour:02d}:{minute:02d}",
                                'close': float(row.get('close', 0)),
                                'volume': int(row.get('volume', 0)),
                                'open': float(row.get('open', 0)),
                                'high': float(row.get('high', 0)),
                                'low': float(row.get('low', 0))
                            })
                except Exception as e:
                    continue

            if not relevant_data:
                print(f"  관련 시간대 데이터 없음")
                continue

            # 분석
            print(f"\n  전후 30분 데이터 ({len(relevant_data)}개 캔들):")

            # 매수가 추정 (매수 시간의 종가)
            buy_candle = None
            for candle in relevant_data:
                if candle['time'] == buy_time:
                    buy_candle = candle
                    break

            if not buy_candle:
                # 가장 가까운 시간
                for candle in relevant_data:
                    if candle['time'] >= buy_time:
                        buy_candle = candle
                        break

            if not buy_candle:
                buy_candle = relevant_data[len(relevant_data)//2]

            buy_price = buy_candle['close']
            print(f"  매수가(추정): {buy_price:,.0f}원")

            # 이후 가격 변동
            max_price = buy_price
            min_price = buy_price
            found_buy = False

            print(f"\n  시간   종가      변화율  거래량")
            print(f"  {'-'*40}")

            for candle in relevant_data:
                price = candle['close']

                if candle['time'] == buy_time:
                    found_buy = True
                    change_pct = 0.0
                    print(f"  {candle['time']} {price:7,.0f}원  [매수]  {candle['volume']:,}주")
                elif found_buy:
                    change_pct = (price - buy_price) / buy_price * 100
                    max_price = max(max_price, candle['high'])
                    min_price = min(min_price, candle['low'])
                    indicator = ""
                    if change_pct >= 3.0:
                        indicator = "✅익절"
                    elif change_pct <= -2.5:
                        indicator = "🔴손절"
                    print(f"  {candle['time']} {price:7,.0f}원 {change_pct:+6.2f}% {candle['volume']:8,}주 {indicator}")
                else:
                    change_pct = (price - buy_price) / buy_price * 100
                    print(f"  {candle['time']} {price:7,.0f}원 {change_pct:+6.2f}% {candle['volume']:8,}주")

            # 요약
            max_gain = (max_price - buy_price) / buy_price * 100
            max_loss = (min_price - buy_price) / buy_price * 100

            print(f"\n  최고점: {max_price:,.0f}원 ({max_gain:+.2f}%)")
            print(f"  최저점: {min_price:,.0f}원 ({max_loss:+.2f}%)")

            # 패턴 분석
            if max_gain > 1.0:
                print(f"  ⚠️ 패턴: 초반 상승 후 하락 (최고 {max_gain:.2f}%)")
            elif max_loss < -2.5:
                print(f"  ⚠️ 패턴: 매수 직후 급락")
            else:
                print(f"  ⚠️ 패턴: 횡보 후 하락")

        except Exception as e:
            print(f"  오류: {e}")

    print(f"\n{'='*70}")
    print("분석 완료")
    print(f"{'='*70}")

if __name__ == '__main__':
    analyze_loss_with_minute_data()
