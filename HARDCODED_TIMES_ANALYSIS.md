# Hardcoded Time References Analysis Report

## Executive Summary

**Total Files Scanned:** 172 Python files (excluding venv)
**Files with Hardcoded Times:** 47+ files identified
**Critical Issues Found:** 13 HIGH RISK items that will break on special market days

## MarketHours Class Reference

Location: `d:\GIT\RoboTrader\config\market_hours.py`

The MarketHours class provides dynamic market hours configuration:
- Market support: KRX (Korea), NYSE, NASDAQ, TSE (Japan)
- Special day handling: e.g., 수능일 (2025-11-13): 10:00-16:30
- Key methods: get_market_hours(), is_market_open(), should_stop_buying(), is_eod_liquidation_time()

---

## HIGH RISK - WILL BREAK ON SPECIAL DAYS (13 issues)

### 1. main.py Line 404
**Issue:** Hardcoded 09:00 start time check
**Code:**
```
if first_time.hour == 9 and first_time.minute not in [0, 3, 6, ...]:
```
**Impact:** Validation fails on special days (e.g., 수능일 10:00 start)
**Fix:** Use MarketHours.get_market_hours()['market_open']

### 2. main.py Line 575
**Issue:** Hardcoded 15:30 data update window
**Code:**
```
if is_market_open() or (current_time.hour == 15 and 30 <= current_time.minute <= 40):
```
**Impact:** Misses data saving window on special days (16:30 on 수능일)
**Fix:** Use MarketHours.is_eod_liquidation_time()

### 3. main.py Lines 665-705
**Issue:** "15시 시장가 일괄매도" hardcoded liquidation
**Impact:** Wrong liquidation time on special days (16:00 on 수능일)
**Fix:** Use MarketHours.get_market_hours()['eod_liquidation_hour']

### 4. core/intraday_stock_manager.py Line 155
**Issue:** Hardcoded 09:00 early morning retry check
**Code:**
```
if not success and (current_time.hour == 9 and current_time.minute < 5):
```
**Impact:** Won't retry within 5 min of market open on special days
**Fix:** Use dynamic market open time

### 5. core/intraday_stock_manager.py Line 1255
**Issue:** Hardcoded 15:30 end-of-day data save
**Code:**
```
if current_time.hour == 15 and current_time.minute >= 30:
```
**Impact:** Data not saved at correct time on special days
**Fix:** Use MarketHours.is_eod_liquidation_time()

### 6. core/intraday_data_utils.py Line 70
**Issue:** Hardcoded 09:00 data validation
**Code:**
```
if first_time.hour != 9 or first_time.minute != 0:
    return {'valid': False, 'reason': 'First candle not 09:00'}
```
**Impact:** Rejects valid data starting at 10:00 on 수능일
**Fix:** Get dynamic market open from MarketHours

### 7. core/indicators/pullback_candle_pattern.py Line 505
**Issue:** Hardcoded 09:00 for day open price calculation
**Code:**
```
if first_candle_time.hour == 9 and first_candle_time.minute == 0:
```
**Impact:** Wrong day open price on special days
**Fix:** Use dynamic market open time

### 8. core/order_manager.py Lines 42, 52
**Issue:** Hardcoded 09:00 and 15:30 for 3-minute candle calculation
**Code:**
```
market_open = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
market_close = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
```
**Impact:** 3-minute candle calculation wrong on special days
**Fix:** Use MarketHours.get_market_hours()

### 9. core/timeframe_converter.py Line 243
**Issue:** Hardcoded 15:30 limit for timeframe conversion
**Code:**
```
if target_hour > 15 or (target_hour == 15 and target_min > 30):
    end_time = pd.Timestamp.combine(base_date, time(hour=15, minute=30))
```
**Impact:** Data truncated at wrong time on special days
**Fix:** Use dynamic market close time

### 10. utils/signal_replay.py Lines 483-486
**Issue:** Hardcoded 15:00 buy cutoff time
**Code:**
```
if signal_hour >= 15:
    continue  # Skip after 15:00
```
**Impact:** Buying allowed past cutoff on special days (13:00 on 수능일)
**Fix:** Use MarketHours.should_stop_buying()

### 11. utils/signal_replay.py Lines 688-693
**Issue:** Hardcoded 15:00+ for end-of-day liquidation
**Code:**
```
if candle_time.hour >= 15 and candle_time.minute >= 0:
    sell_price = candle_close  # Sell at 15:00
```
**Impact:** Wrong liquidation time on special days
**Fix:** Use MarketHours.is_eod_liquidation_time()

### 12. visualization/chart_renderer.py Lines 731-732
**Issue:** Hardcoded 09:00 for chart time axis
**Code:**
```
if first_hour >= 9:
    start_minutes = 9 * 60  # 09:00 = 540 minutes
```
**Impact:** Wrong chart time axis on special days
**Fix:** Use dynamic market open time

### 13. visualization/chart_renderer.py Line 879
**Issue:** Hardcoded 390 minutes (09:00-15:30)
**Code:**
```
total_trading_minutes = 390  # 09:00-15:30 = 6.5 hours
```
**Impact:** Chart time span wrong on special days (420 min on 수능일)
**Fix:** Calculate from market open/close times

---

## MEDIUM RISK - SHOULD FIX (5 issues)

### 14. auto_verify_consistency.py Lines 88-89
**Issue:** Hardcoded 09:00 data validation
**Risk:** Offline validation tool

### 15. signal_log_analyzer.py Lines 157-180
**Issue:** Hardcoded hour ranges for time-of-day analysis
**Risk:** Analysis/reporting accuracy

### 16. trade_analysis/data_collector.py Lines 102-104
**Issue:** Hardcoded hour values
**Risk:** Backtesting/analysis accuracy

### 17. trade_analysis/data_sufficiency_checker.py Lines 73, 75
**Issue:** Hardcoded hour checks
**Risk:** Validation accuracy

### 18. analysis_tools/improved_signal_analyzer.py Line 343
**Issue:** Hardcoded "12:00" selection time
**Risk:** Analysis tool accuracy

---

## LOW RISK - LOGGING/COMMENTS ONLY (15+ files)

Files with non-critical time references:
- collect_specific_times.py
- collect_minute_data.py
- full_comparison.py
- morning_trade_analysis.py
- visualization/data_processor.py
- batch_signal_replay.py
- Various test/analysis scripts

These do not affect trading logic.

---

## MIGRATION CHECKLIST

### Phase 1: Core Trading (HIGH RISK - 8 files)
- [ ] core/order_manager.py
- [ ] core/intraday_stock_manager.py
- [ ] core/intraday_data_utils.py
- [ ] core/indicators/pullback_candle_pattern.py
- [ ] core/timeframe_converter.py
- [ ] utils/signal_replay.py
- [ ] main.py
- [ ] visualization/chart_renderer.py

### Phase 2: Supporting (MEDIUM RISK - 5 files)
- [ ] auto_verify_consistency.py
- [ ] signal_log_analyzer.py
- [ ] trade_analysis/data_collector.py
- [ ] trade_analysis/data_sufficiency_checker.py
- [ ] analysis_tools/improved_signal_analyzer.py

### Phase 3: Analysis Tools (LOW RISK - optional)
- [ ] Batch/test/analysis scripts

---

## TESTING DATES

1. 수능일 (Exam Day): 2025-11-13
   - Market hours: 10:00-16:30
   - Buy cutoff: 13:00
   - EOD liquidation: 16:00

2. Normal days: Verify no regression

---

## Template Code

Replace hardcoded times with:

```python
from config.market_hours import MarketHours

# Get dynamic market hours
market_hours = MarketHours.get_market_hours('KRX', current_time)
market_open_hour = market_hours['market_open'].hour
market_open_min = market_hours['market_open'].minute
market_close_hour = market_hours['market_close'].hour
market_close_min = market_hours['market_close'].minute
buy_cutoff_hour = market_hours['buy_cutoff_hour']

# Use in calculations
market_open = current_time.replace(
    hour=market_open_hour,
    minute=market_open_min,
    second=0,
    microsecond=0
)
```

