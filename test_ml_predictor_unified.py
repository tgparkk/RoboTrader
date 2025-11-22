"""
ML Predictor Unified Test - Real-time debug_info structure
"""
import json
from core.ml_predictor import MLPredictor

def test_debug_info_structure():
    """Test real-time data structure (debug_info)"""
    print("=" * 60)
    print("[Test] Real-time Data Structure (debug_info)")
    print("=" * 60)

    # Simulated real-time data structure
    pattern_data = {
        'signal_time': '2025-11-22 10:30:00',
        'signal_info': {
            'signal_type': 'STRONG_BUY',
            'confidence': 85.5
        },
        'debug_info': {
            'uptrend': {
                'start_idx': 0,
                'end_idx': 5,
                'gain_pct': 0.0523,
                'avg_volume': 245000,
                'max_volume_numeric': 350000,
                'total_volume': 1470000,
                'avg_body': 1.2,
                'bar_count': 6
            },
            'decline': {
                'start_idx': 6,
                'end_idx': 10,
                'decline_pct': 0.0215,
                'avg_volume': 125000,
                'max_volume': 180000,
                'total_volume': 625000,
                'avg_body': 0.8,
                'bar_count': 5
            },
            'support': {
                'start_idx': 11,
                'end_idx': 15,
                'candle_count': 5,
                'avg_volume_ratio': 0.45,
                'price_volatility': 0.008,
                'avg_volume': 90000,
                'max_volume': 120000,
                'total_volume': 450000,
                'avg_body': 0.5,
                'bar_count': 5
            },
            'breakout': {
                'idx': 16,
                'volume': 280000,
                'body': 1.5,
                'gain_pct': 2.1
            },
            'best_breakout': {
                'high': 52500,
                'low': 51200,
                'close': 52400,
                'open': 51300,
                'volume': 280000
            }
        }
    }

    print(f"Real-time data created")
    print(f"Has pattern_stages: {('pattern_stages' in pattern_data)}")
    print(f"Has debug_info: {('debug_info' in pattern_data)}")

    # Initialize ML predictor
    print("\nInitializing ML Predictor...")
    predictor = MLPredictor()

    # Load ML model
    print("Loading ML model...")
    if not predictor.load_model():
        raise Exception("Failed to load ML model")
    print("ML Predictor initialized successfully")

    # Extract features
    print("\nExtracting features from debug_info structure...")
    features_df = predictor.extract_features_from_pattern(pattern_data)
    print(f"Extracted features ({len(features_df.columns)} total):")

    # Display key features
    key_features = [
        'hour', 'minute', 'signal_type', 'confidence',
        'uptrend_candles', 'uptrend_gain', 'uptrend_max_volume',
        'uptrend_avg_body', 'uptrend_total_volume',
        'decline_candles', 'decline_pct', 'decline_avg_volume',
        'support_candles', 'support_volatility', 'support_avg_volume',
        'breakout_volume', 'breakout_body', 'breakout_range'
    ]

    for feat in key_features:
        if feat in features_df.columns:
            val = features_df[feat].iloc[0]
            print(f"  {feat:30s}: {val:15.4f}")

    # ML prediction
    print("\nRunning ML prediction...")
    should_trade, ml_prob = predictor.should_trade(
        pattern_data,
        threshold=0.5,
        stock_code='TEST001'
    )

    print(f"\nML Prediction Result:")
    print(f"  Should trade: {should_trade}")
    print(f"  Win probability: {ml_prob:.1%}")
    print(f"  Threshold: 50.0%")

    if should_trade:
        print(f"\n  => PASS: ML filter allows trading (prob >= threshold)")
    else:
        print(f"\n  => BLOCK: ML filter blocks trading (prob < threshold)")


if __name__ == '__main__':
    try:
        test_debug_info_structure()

        print("\n" + "=" * 60)
        print("Test passed! Real-time debug_info structure works correctly.")
        print("=" * 60)

    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
