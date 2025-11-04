"""
승패 거래의 상세 눌림목 패턴 분석
"""
import json
import sys

def show_trade_details(date='20251104'):
    """거래별 상세 패턴 표시"""

    # 로그 파일 읽기
    log_file = f'pattern_data_log/pattern_data_{date}.jsonl'
    with open(log_file, 'r', encoding='utf-8') as f:
        patterns = [json.loads(line) for line in f if line.strip()]

    # 매매 결과가 있는 패턴만 필터링
    traded_patterns = [p for p in patterns if p.get('trade_result') and p['trade_result'].get('trade_executed')]

    print('='*80)
    print('승리한 거래 상세 분석')
    print('='*80)

    wins = [p for p in traded_patterns if p['trade_result']['profit_rate'] > 0]
    for i, pattern in enumerate(wins, 1):
        stock_code = pattern['stock_code']
        profit = pattern['trade_result']['profit_rate']

        print(f'\n[승리 #{i}] {stock_code} - 수익률: {profit:.2f}%')
        print(f'  시각: {pattern["timestamp"]}')
        print(f'  신호타입: {pattern["signal_info"]["signal_type"]} (신뢰도: {pattern["signal_info"]["confidence"]:.1f}%)')
        print(f'  매도이유: {pattern["trade_result"]["sell_reason"]}')

        stages = pattern['pattern_stages']

        # 1단계: 상승 구간
        uptrend = stages.get('1_uptrend', {})
        print(f'\n  [1단계: 상승구간]')
        print(f'    - 캔들수: {uptrend.get("candle_count")}개')
        print(f'    - 가격상승: {uptrend.get("price_gain")}')
        print(f'    - 최대거래량: {uptrend.get("max_volume")}')
        vol_ratio = uptrend.get("max_volume_ratio_vs_avg") or 0
        print(f'    - 거래량비율(당일평균대비): {vol_ratio:.2f}배')

        # 2단계: 하락 구간
        decline = stages.get('2_decline', {})
        print(f'  [2단계: 하락구간]')
        print(f'    - 캔들수: {decline.get("candle_count")}개')
        print(f'    - 하락률: {decline.get("decline_pct")}')

        # 3단계: 지지 구간
        support = stages.get('3_support', {})
        print(f'  [3단계: 지지구간]')
        print(f'    - 캔들수: {support.get("candle_count")}개')
        print(f'    - 가격변동성: {support.get("price_volatility")}')
        print(f'    - 평균거래량비율: {support.get("avg_volume_ratio")}')

        # 4단계: 돌파 양봉
        breakout = stages.get('4_breakout', {})
        print(f'  [4단계: 돌파양봉]')
        print(f'    - 몸통크기: {breakout.get("body_size")}')
        print(f'    - 거래량: {breakout.get("volume")}')
        print(f'    - 직전봉대비 거래량: {breakout.get("volume_ratio_vs_prev")}배')

    print('\n\n' + '='*80)
    print('패배한 거래 상세 분석')
    print('='*80)

    losses = [p for p in traded_patterns if p['trade_result']['profit_rate'] <= 0]
    for i, pattern in enumerate(losses, 1):
        stock_code = pattern['stock_code']
        profit = pattern['trade_result']['profit_rate']

        print(f'\n[패배 #{i}] {stock_code} - 손실률: {profit:.2f}%')
        print(f'  시각: {pattern["timestamp"]}')
        print(f'  신호타입: {pattern["signal_info"]["signal_type"]} (신뢰도: {pattern["signal_info"]["confidence"]:.1f}%)')
        print(f'  매도이유: {pattern["trade_result"]["sell_reason"]}')

        stages = pattern['pattern_stages']

        # 1단계: 상승 구간
        uptrend = stages.get('1_uptrend', {})
        print(f'\n  [1단계: 상승구간]')
        print(f'    - 캔들수: {uptrend.get("candle_count")}개')
        print(f'    - 가격상승: {uptrend.get("price_gain")}')
        print(f'    - 최대거래량: {uptrend.get("max_volume")}')
        vol_ratio = uptrend.get("max_volume_ratio_vs_avg") or 0
        print(f'    - 거래량비율(당일평균대비): {vol_ratio:.2f}배')

        # 2단계: 하락 구간
        decline = stages.get('2_decline', {})
        print(f'  [2단계: 하락구간]')
        print(f'    - 캔들수: {decline.get("candle_count")}개')
        print(f'    - 하락률: {decline.get("decline_pct")}')

        # 3단계: 지지 구간
        support = stages.get('3_support', {})
        print(f'  [3단계: 지지구간]')
        print(f'    - 캔들수: {support.get("candle_count")}개')
        print(f'    - 가격변동성: {support.get("price_volatility")}')
        print(f'    - 평균거래량비율: {support.get("avg_volume_ratio")}')

        # 4단계: 돌파 양봉
        breakout = stages.get('4_breakout', {})
        print(f'  [4단계: 돌파양봉]')
        print(f'    - 몸통크기: {breakout.get("body_size")}')
        print(f'    - 거래량: {breakout.get("volume")}')
        print(f'    - 직전봉대비 거래량: {breakout.get("volume_ratio_vs_prev")}배')


if __name__ == '__main__':
    date = sys.argv[1] if len(sys.argv) > 1 else '20251104'
    show_trade_details(date)
