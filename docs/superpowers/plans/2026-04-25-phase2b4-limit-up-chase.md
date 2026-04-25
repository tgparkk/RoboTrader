# Phase 2B-4: 상한가 따라잡기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** 단타 카탈로그 마지막 classic intraday 전략 — 상한가 따라잡기 (Limit-Up Chase).

**Architecture:** 단일 파일 `backtests/strategies/limit_up_chase.py`. 전일 close 대비 큰 상승 + 거래량 폭증 종목을 추격. 한국 일일 한도 +30% 임박 직전(`limit_proximity_pct`)까지만 추격. hold_days=0.

**Tech Stack:** Python 3.x, pandas, pytest.

**Scope:** 1 전략. Phase 2C (overnight swing 5개) 는 별도 플랜.

**위험 인자:** 상한가 근접 종목은 호가·체결 불확실성 큼. `execution_model.py` 의 `VOLUME_LIMIT_RATIO=0.02` + `LIMIT_PRICE_BUFFER=0.01` 이 엔진 차원에서 강제됨. 전략은 `limit_proximity_pct` 로 한도 직전 진입 회피.

---

## Task 1: 상한가 따라잡기 (Limit-Up Chase)

**Files:**
- Create: `backtests/strategies/limit_up_chase.py`
- Test: `tests/backtests/test_limit_up_chase.py`

**Parameter space:**
```python
param_space = {
    "chase_threshold_pct": {"type": "float", "low": 8.0, "high": 22.0, "step": 1.0},
    "limit_proximity_pct": {"type": "float", "low": 24.0, "high": 29.0, "step": 0.5},
    "vol_lookback_bars": {"type": "int", "low": 10, "high": 30, "step": 5},
    "volume_mult": {"type": "float", "low": 3.0, "high": 10.0, "step": 0.5},
    "entry_window_end_bar": {"type": "int", "low": 60, "high": 300, "step": 30},
    "take_profit_pct": {"type": "float", "low": 2.0, "high": 8.0, "step": 0.5},
    "stop_loss_pct": {"type": "float", "low": -5.0, "high": -1.5, "step": 0.5},
}
```

**진입 조건:**
1. 분봉 close 가 전일 close 대비 `+chase_threshold_pct` ~ `+limit_proximity_pct` 사이 (너무 낮지도 너무 한도근접도 아님)
2. 직전 K bars 거래량 대비 분봉 거래량 `volume_mult` 이상 (강한 수급)
3. close > prev_close (현 분봉이 여전히 상승)
4. 진입 시간 `entry_window_end_bar` 이전

**청산:** TP/SL only, hold_days=0 (엔진이 EOD 강제 청산).

### Steps

- [ ] **Step 1: 테스트 작성** (Create `tests/backtests/test_limit_up_chase.py`)

- [ ] **Step 2: 실패 확인** — ModuleNotFoundError

- [ ] **Step 3: 구현** (`backtests/strategies/limit_up_chase.py`)

- [ ] **Step 4: PASS 확인** — 8 passed

- [ ] **Step 5: 전체 스위트** — 138 + 8 = 146 passed + 2 skipped

- [ ] **Step 6: Commit**
```bash
git add backtests/strategies/limit_up_chase.py tests/backtests/test_limit_up_chase.py
git commit -m "feat(backtests): add limit-up chase strategy"
```

---

## Phase 2B-4 Wrap-up

- [ ] **완료 노트** (append to `backtests/reports/phase1_baseline_notes.md`)
- [ ] **Commit**: `docs(backtests): Phase 2B-4 complete (limit-up chase)`

---

## Summary

**New files (2):**
- `backtests/strategies/limit_up_chase.py` + test (~8 tests)

**Phase 2B-4 목표**: 146 tests passed + 2 skipped.
**Phase 2C 시작 조건**: 이 플랜 완료. Classic intraday 10개 전체 완성.
