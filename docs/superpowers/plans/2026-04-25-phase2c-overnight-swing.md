# Phase 2C: Overnight Swing 5 전략 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans.

**Goal:** Classic Overnight Swing 5 전략 (`close_to_open`, `breakout_52w`, `post_drop_rebound`, `trend_followthrough`, `macd_cross`) 을 백테스트 엔진 계약으로 구현.

**Architecture:** 모든 전략 daily-level 피처 계산 → 분봉에 broadcast. 진입은 장 후반(default 14:50 이후) 한 번만 발생. 청산은 `_last_df_minute` + `count_trading_days_between` >= hold_days (closing_drift 패턴).

**Tech Stack:** Python 3.x, pandas, pytest.

---

## 공통 패턴

```python
class OvernightStrategyTemplate(StrategyBase):
    name = "..."
    hold_days = 1 or 2

    def __init__(self, ..., entry_hhmm_min=1450, entry_hhmm_max=1500):
        ...
        self._last_df_minute = None

    def prepare_features(self, df_minute, df_daily):
        self._last_df_minute = df_minute
        # daily 에서 시그널 계산 (shift(1) 엄수) → trade_date map
        # 분봉에 hhmm 추가
        # 매도/매수 컬럼 broadcast
        return features

    def entry_signal(self, features, bar_idx, stock_code):
        row = features.iloc[bar_idx]
        if not (entry_hhmm_min <= row["hhmm"] <= entry_hhmm_max):
            return None
        # 시그널 컬럼 검사
        ...

    def exit_signal(self, position, features, bar_idx, current_price=None):
        # hold_limit only (TP/SL 옵션은 일부 전략만)
        days_held = count_trading_days_between(self._last_df_minute, ...)
        if days_held >= self.hold_days:
            return ExitOrder(reason="hold_limit")
        return None
```

---

## Task 1: close_to_open (종가매수 → 시가매도)

**Files:** `backtests/strategies/close_to_open.py` + test

**전략:** 강한 종가(전일대비 ≥ +3%) 종목 14:50~15:00 매수, 다음날 시가 매도. hold_days=1.

**피처:** `today_close_change_pct = (close - prev_close) / prev_close * 100` (분봉 close vs daily prev_close).

**진입:** `today_close_change_pct >= min_change_pct (3.0)`, 14:50~15:00.

**Parameter space:**
```python
{
    "min_change_pct": {"type": "float", "low": 1.5, "high": 6.0, "step": 0.5},
    "entry_hhmm_min": {"type": "int", "low": 1430, "high": 1500, "step": 10},
}
```

---

## Task 2: breakout_52w (52주 신고가 돌파)

**Files:** `backtests/strategies/breakout_52w.py` + test

**전략:** daily close 가 252일 rolling high(`shift(1)`) 돌파 → 14:50 이후 진입. hold_days=2.

**피처:** `prev_52w_high = daily.high.rolling(252, min_periods=60).max().shift(1)`. 분봉 close 가 prev_52w_high 초과 시 매수 (현재 분봉 close 기준 — intraday confirmation).

**Parameter space:**
```python
{
    "lookback_days": {"type": "int", "low": 60, "high": 252, "step": 30},
    "buffer_pct": {"type": "float", "low": 0.0, "high": 1.0, "step": 0.1},
}
```

---

## Task 3: post_drop_rebound (낙주 반등)

**Files:** `backtests/strategies/post_drop_rebound.py` + test

**전략:** 전일 daily return ≤ -5% + 당일 거래량 5일 평균의 N배 이상 → 14:50 진입, hold_days=2.

**피처:** `prev_day_return = (prev_close - prev_prev_close) / prev_prev_close * 100`, `vol_ratio_5d = today_intraday_vol_so_far / avg_vol_5d` (당일 누적 거래량 / 5일 평균).

**Parameter space:**
```python
{
    "max_prev_return_pct": {"type": "float", "low": -8.0, "high": -3.0, "step": 0.5},
    "vol_mult": {"type": "float", "low": 1.5, "high": 4.0, "step": 0.25},
}
```

---

## Task 4: trend_followthrough (5일 고점 돌파)

**Files:** `backtests/strategies/trend_followthrough.py` + test

**전략:** 분봉 close 가 직전 5일 daily high (`shift(1)`) 돌파 → 14:50 진입, hold_days=2.

**Parameter space:**
```python
{
    "lookback_days": {"type": "int", "low": 3, "high": 20, "step": 1},
    "buffer_pct": {"type": "float", "low": 0.0, "high": 1.0, "step": 0.1},
}
```

---

## Task 5: macd_cross (MACD 골든크로스)

**Files:** `backtests/strategies/macd_cross.py` + test

**전략:** Daily MACD 히스토그램이 음→양으로 전환된 날 14:50 진입. hold_days=2.

**피처:** EMA12, EMA26, MACD = EMA12 - EMA26, signal = MACD.EMA(9), hist = MACD - signal. 모두 daily, shift(1) 후 신호: `prev_hist >= 0 AND prev_prev_hist < 0` (직전 세션에 골든크로스 확정).

**Parameter space:**
```python
{
    "fast_period": {"type": "int", "low": 8, "high": 16, "step": 2},
    "slow_period": {"type": "int", "low": 20, "high": 40, "step": 2},
    "signal_period": {"type": "int", "low": 7, "high": 12, "step": 1},
}
```

---

## 각 Task 의 Steps (5 전략 동일)

- [ ] **Step 1: 테스트 작성** (~5~7 tests/전략)
- [ ] **Step 2: 실패 확인** — ModuleNotFoundError
- [ ] **Step 3: 구현**
- [ ] **Step 4: PASS 확인**
- [ ] **Step 5: 전체 스위트 누적 확인**
- [ ] **Step 6: Commit**: `feat(backtests): add <strategy_name> overnight swing strategy`

---

## Phase 2C Wrap-up

- [ ] `backtests/reports/phase1_baseline_notes.md` 업데이트
- [ ] Commit: `docs(backtests): Phase 2C complete (5 overnight swing strategies)`

---

## Summary

**New files (10):** 5 strategies + 5 tests

**Phase 2C 목표:** 146 + ~30 tests = ~176 passed + 2 skipped, 15 classic + 1 baseline = 16 전략 완성.

**Phase 3 시작 조건:** 이 플랜 완료 + 엔진 속도 검토.
