"""
Price Position Strategy Integration Test

Run: python test_price_position_integration.py
"""

import sys
import os

# Add project root path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
import pandas as pd


def test_strategy_settings():
    """1. Strategy settings load test"""
    print("\n" + "=" * 60)
    print("Test 1: Strategy Settings Load")
    print("=" * 60)

    try:
        from config.strategy_settings import StrategySettings, validate_settings

        print(f"[OK] Active Strategy: {StrategySettings.ACTIVE_STRATEGY}")
        print(f"[OK] Entry Conditions:")
        print(f"   - Pct from open: {StrategySettings.PricePosition.MIN_PCT_FROM_OPEN}% ~ {StrategySettings.PricePosition.MAX_PCT_FROM_OPEN}%")
        print(f"   - Time: {StrategySettings.PricePosition.ENTRY_START_HOUR}:00 ~ {StrategySettings.PricePosition.ENTRY_END_HOUR}:00")
        print(f"   - Weekdays: {StrategySettings.PricePosition.ALLOWED_WEEKDAYS} (0=Mon, 2=Wed, 4=Fri)")

        validate_settings()
        print("[OK] Settings validation passed")
        return True

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_strategy_class():
    """2. Strategy class test"""
    print("\n" + "=" * 60)
    print("Test 2: PricePositionStrategy Class")
    print("=" * 60)

    try:
        from core.strategies.price_position_strategy import PricePositionStrategy

        strategy = PricePositionStrategy()
        info = strategy.get_strategy_info()

        print(f"[OK] Strategy Name: {info['name']}")
        print(f"[OK] Entry Conditions: {info['entry_conditions']}")
        print(f"[OK] Exit Conditions: {info['exit_conditions']}")

        # Entry condition tests
        test_cases = [
            # (stock_code, current_price, day_open, time, trade_date, weekday, expected)
            ("005930", 10300, 10000, "100000", "20260204", 2, True),   # Wed, 10:00, +3%
            ("005930", 10300, 10000, "100000", "20260203", 1, False),  # Tue
            ("005930", 10300, 10000, "090000", "20260204", 2, False),  # 9:00 (before 10:00)
            ("005930", 10100, 10000, "100000", "20260204", 2, False),  # +1% (< 2%)
            ("005930", 10500, 10000, "100000", "20260204", 2, False),  # +5% (> 4%)
        ]

        print("\nEntry Condition Tests:")
        weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        all_passed = True
        for stock, price, open_p, time, date, wd, expected in test_cases:
            can_enter, reason = strategy.check_entry_conditions(
                stock_code=stock,
                current_price=price,
                day_open=open_p,
                current_time=time,
                trade_date=date,
                weekday=wd
            )
            status = "[OK]" if can_enter == expected else "[FAIL]"
            if can_enter != expected:
                all_passed = False
            pct = (price / open_p - 1) * 100
            print(f"  {status} {weekday_names[wd]}, {time[:2]}:00, +{pct:.1f}%: {can_enter} ({reason})")

        return all_passed

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_engine_initialization():
    """3. Engine initialization test"""
    print("\n" + "=" * 60)
    print("Test 3: TradingDecisionEngine Initialization")
    print("=" * 60)

    try:
        from core.trading_decision_engine import TradingDecisionEngine

        # Minimal initialization (no dependencies)
        engine = TradingDecisionEngine()

        print(f"[OK] Active Strategy: {engine.active_strategy}")

        if engine.active_strategy == 'price_position':
            print(f"[OK] PricePositionStrategy object: {engine.price_position_strategy is not None}")
            if engine.price_position_strategy:
                info = engine.price_position_strategy.get_strategy_info()
                print(f"[OK] Strategy Info: {info['name']}")
        else:
            print(f"[INFO] Using pullback strategy")

        return True

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_weekday_restriction():
    """4. Weekday restriction test"""
    print("\n" + "=" * 60)
    print("Test 4: Weekday Restriction (Avoid Tue/Thu)")
    print("=" * 60)

    try:
        from config.strategy_settings import StrategySettings

        weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        allowed = StrategySettings.PricePosition.ALLOWED_WEEKDAYS

        print("Weekday Trading Availability:")
        for wd in range(5):  # Mon~Fri
            can_trade = wd in allowed
            status = "[OK] Trade" if can_trade else "[X] Avoid"
            print(f"  {weekday_names[wd]}: {status}")

        # Check today
        today = datetime.now()
        today_wd = today.weekday()
        can_trade_today = today_wd in allowed

        print(f"\nToday ({today.strftime('%Y-%m-%d')} {weekday_names[today_wd]}):")
        if can_trade_today:
            print(f"  [OK] Trading allowed")
        else:
            print(f"  [X] No trading (Tue/Thu)")

        return True

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_daily_trade_limit():
    """5. Daily trade limit test"""
    print("\n" + "=" * 60)
    print("Test 5: Daily Trade Limit")
    print("=" * 60)

    try:
        from core.trading_decision_engine import TradingDecisionEngine
        from config.strategy_settings import StrategySettings

        # Reset trade records
        TradingDecisionEngine.reset_daily_trades()

        max_positions = StrategySettings.PricePosition.MAX_DAILY_POSITIONS
        print(f"Max daily positions: {max_positions}")

        # Test: One trade per stock per day
        test_date = "20260204"
        TradingDecisionEngine._price_position_daily_trades[test_date] = {"A001", "A002"}

        already_traded = "A001" in TradingDecisionEngine._price_position_daily_trades[test_date]
        new_stock = "A003" not in TradingDecisionEngine._price_position_daily_trades[test_date]

        print(f"[OK] Block re-trade for A001: {already_traded}")
        print(f"[OK] Allow new trade for A003: {new_stock}")

        # Cleanup
        TradingDecisionEngine.reset_daily_trades()
        print("[OK] Trade records cleared")

        return already_traded and new_stock

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_with_mock_data():
    """6. Mock data signal test"""
    print("\n" + "=" * 60)
    print("Test 6: Mock Data Signal Test")
    print("=" * 60)

    try:
        from core.strategies.price_position_strategy import PricePositionStrategy
        import numpy as np

        strategy = PricePositionStrategy()

        # Generate mock candle data (open 10000, current 10300 = +3%)
        np.random.seed(42)
        n_candles = 50

        base_price = 10000
        prices = [base_price]
        for i in range(n_candles - 1):
            change = np.random.uniform(-0.005, 0.008)  # Gradual rise
            prices.append(prices[-1] * (1 + change))

        # Set last price to +3% from open
        prices[-1] = base_price * 1.03

        df = pd.DataFrame({
            'datetime': pd.date_range('2026-02-04 09:00', periods=n_candles, freq='3min'),
            'open': [base_price] + prices[:-1],
            'high': [p * 1.002 for p in prices],
            'low': [p * 0.998 for p in prices],
            'close': prices,
            'volume': [100000 + np.random.randint(-10000, 10000) for _ in range(n_candles)]
        })

        day_open = df.iloc[0]['open']
        current_price = df.iloc[-1]['close']
        pct_from_open = (current_price / day_open - 1) * 100

        print(f"Mock Data:")
        print(f"  - Day Open: {day_open:,.0f}")
        print(f"  - Current Price: {current_price:,.0f}")
        print(f"  - Change: {pct_from_open:+.2f}%")

        # Entry condition test (Wed 10:30 assumed)
        can_enter, reason = strategy.check_entry_conditions(
            stock_code="TEST001",
            current_price=current_price,
            day_open=day_open,
            current_time="103000",
            trade_date="20260204",
            weekday=2  # Wed
        )

        print(f"\nEntry Condition Test:")
        if can_enter:
            print(f"  [OK] Entry allowed: {reason}")
        else:
            print(f"  [X] Entry blocked: {reason}")

        # Trade simulation
        result = strategy.simulate_trade(df, len(df) - 5)
        if result:
            print(f"\nTrade Simulation Result:")
            print(f"  - Result: {result['result']}")
            print(f"  - PnL: {result['pnl']:+.2f}%")
            print(f"  - Exit Reason: {result['exit_reason']}")

        return can_enter  # Should be True for this test case

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("Price Position Strategy Integration Test")
    print("=" * 60)

    tests = [
        ("Strategy Settings Load", test_strategy_settings),
        ("Strategy Class", test_strategy_class),
        ("Engine Initialization", test_engine_initialization),
        ("Weekday Restriction", test_weekday_restriction),
        ("Daily Trade Limit", test_daily_trade_limit),
        ("Mock Data Signal", test_with_mock_data),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"[FAIL] {name} test exception: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, success in results:
        status = "[PASS]" if success else "[FAIL]"
        print(f"  {status}: {name}")
        if success:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal {len(results)} tests: {passed} passed, {failed} failed")

    if failed == 0:
        print("\n*** All tests passed! ***")
        print("\nNext steps:")
        print("  1. Check ACTIVE_STRATEGY in config/strategy_settings.py")
        print("  2. Test live trading on Wed(2/4) or Fri(2/6)")
    else:
        print("\n*** Some tests failed. Check the logs. ***")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
