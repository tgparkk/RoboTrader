"""
Signal Replay with ML Filter - 예시 코드
ML 필터가 적용된 signal_replay 버전
"""

async def analyze_signal_with_ml_filter(signal_strength, stock_code, current_data):
    """신호에 ML 필터 적용"""
    if not signal_strength:
        return False, "기본 신호 없음"
    
    try:
        # ML 예측기 초기화
        from trade_analysis.ml_predictor import MLPredictor
        from utils.korean_time import now_kst
        
        ml_predictor = MLPredictor()
        current_date = now_kst().strftime("%Y%m%d")
        
        # ML 예측 실행
        ml_result = ml_predictor.predict_trade_outcome(stock_code, current_date, "pullback_pattern")
        
        if "error" in ml_result:
            return True, "ML 예측 오류 - 기본 신호 통과"
        
        # 예측 결과 분석
        recommendation = ml_result.get('recommendation', {})
        action = recommendation.get('action', 'SKIP')
        win_probability = recommendation.get('win_probability', 0.0)
        
        # ML 필터링 조건
        if action in ['STRONG_BUY', 'BUY']:
            return True, f"ML 승인: {action} (승률:{win_probability:.1%})"
        elif action == 'WEAK_BUY' and win_probability >= 0.55:
            return True, f"ML 조건부승인: (승률:{win_probability:.1%})"
        else:
            return False, f"ML 차단: {action} (승률:{win_probability:.1%})"
            
    except Exception as e:
        return True, f"ML 필터 오류 - 기본 신호 통과: {e}"


# signal_replay.py의 1084라인 이후에 추가할 코드:
"""
# 기존 코드
signal_strength = PullbackCandlePattern.generate_improved_signals(
    current_data,
    stock_code=stock_code,
    debug=True
)

# ML 필터 적용
if signal_strength:
    ml_pass, ml_reason = await analyze_signal_with_ml_filter(
        signal_strength, stock_code, current_data
    )
    if not ml_pass:
        # ML에서 차단한 신호는 SKIP으로 처리
        status_parts.append(f"🚫ML차단: {ml_reason}")
        signal_strength = None  # 신호 무효화
    else:
        # ML 승인된 신호는 추가 정보 표시
        status_parts.append(f"🤖ML승인: {ml_reason}")
"""