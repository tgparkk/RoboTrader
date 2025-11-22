"""
실시간 ML 데이터 구조 검증
"""
import pandas as pd
from core.indicators.pullback.support_pattern_analyzer import SupportPatternAnalyzer

# 테스트용 분봉 데이터 생성 (강력한 4단계 패턴)
# 1단계: 상승 (0-4) - 5% 상승, 거래량 증가
# 2단계: 하락 (5-7) - 2% 하락, 거래량 감소
# 3단계: 지지 (8-10) - 횡보, 거래량 급감
# 4단계: 돌파 (11) - 양봉, 거래량 증가
data = pd.DataFrame({
    'open':   [100, 101, 102, 103, 104, 104, 103, 102, 102, 102, 102, 103],
    'high':   [101, 102, 103, 104, 105, 104.5, 103.5, 102.5, 102.5, 102.5, 102.5, 105],
    'low':    [ 99, 100, 101, 102, 103, 102.5, 101.5, 101, 101.5, 101.5, 101.5, 102],
    'close':  [101, 102, 103, 104, 105, 103, 102, 101.5, 102, 102, 102, 104.5],
    'volume': [1000, 1200, 1500, 1800, 2000, 800, 600, 500, 300, 250, 280, 900]
})

print("=" * 60)
print("실시간 ML 데이터 구조 검증")
print("=" * 60)

# SupportPatternAnalyzer 실행 (올바른 파라미터 사용)
analyzer = SupportPatternAnalyzer(
    uptrend_min_gain=0.03,
    decline_min_pct=0.01,
    support_volume_threshold=0.3,
    support_volatility_threshold=0.015,
    breakout_body_increase=0.1,
    lookback_period=50
)

result = analyzer.analyze(data)
debug_info = analyzer.get_debug_info(data)

print(f"\n패턴 감지: {result.has_pattern}")

if 'uptrend' in debug_info:
    print("\n[상승 구간 debug_info]")
    uptrend = debug_info['uptrend']
    print(f"  avg_body_pct 존재: {'avg_body_pct' in uptrend}")
    if 'avg_body_pct' in uptrend:
        print(f"  avg_body_pct 값: {uptrend['avg_body_pct']:.4f}%")
    print(f"  avg_volume: {uptrend.get('avg_volume', 0):,.0f}")
    print(f"  total_volume: {uptrend.get('total_volume', 0):,.0f}")

if 'decline' in debug_info:
    print("\n[하락 구간 debug_info]")
    decline = debug_info['decline']
    print(f"  avg_body_pct 존재: {'avg_body_pct' in decline}")
    if 'avg_body_pct' in decline:
        print(f"  avg_body_pct 값: {decline['avg_body_pct']:.4f}%")

if 'support' in debug_info:
    print("\n[지지 구간 debug_info]")
    support = debug_info['support']
    print(f"  avg_body_pct 존재: {'avg_body_pct' in support}")
    if 'avg_body_pct' in support:
        print(f"  avg_body_pct 값: {support['avg_body_pct']:.4f}%")

if 'breakout' in debug_info:
    print("\n[돌파 구간 debug_info]")
    breakout = debug_info['breakout']
    print(f"  body_pct 존재: {'body_pct' in breakout}")
    if 'body_pct' in breakout:
        print(f"  body_pct 값: {breakout['body_pct']:.4f}%")

# ML 예측기 테스트
print("\n" + "=" * 60)
print("ML 예측기 특성 추출 테스트")
print("=" * 60)

from core.ml_predictor import MLPredictor

predictor = MLPredictor()
predictor.load_model()

# 실시간에서 전달되는 패턴 데이터 구조
pattern_data = {
    'signal_time': '2025-11-22 10:30:00',
    'signal_info': {
        'signal_type': 'STRONG_BUY',
        'confidence': 85.0
    },
    'debug_info': debug_info
}

features_df = predictor.extract_features_from_pattern(pattern_data)

print(f"\n추출된 특성:")
print(f"  uptrend_avg_body: {features_df['uptrend_avg_body'].iloc[0]:.4f}")
print(f"  breakout_body: {features_df['breakout_body'].iloc[0]:.4f}")

should_trade, ml_prob = predictor.should_trade(pattern_data, threshold=0.5)
print(f"\nML 예측 결과:")
print(f"  거래 허용: {should_trade}")
print(f"  승률: {ml_prob:.1%}")

print("\n" + "=" * 60)
print("검증 완료!")
print("=" * 60)
