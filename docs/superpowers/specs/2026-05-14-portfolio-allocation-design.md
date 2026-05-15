# MV-F: Portfolio Allocation 멀티버스 — Design

**날짜**: 2026-05-14
**상태**: Spec (구현 전)
**관련 결론**:
- MV-A~D: macd_cross fold2 회복 불가 (entry/exit 양측)
- MV-E: 17 strategy 자산에 fold2-robust 부재. 부산물 — breakout_52w / trend_followthrough 가 fold1·3 강함.

---

## Context

MV-E 의 사람 보강 결론에서 발견된 가설: **breakout_52w / trend_followthrough 는 fold1·3 강세장에서 우수하고 fold2·oos 약세장에서 음수** → 약세장에서 강한 macd_cross 와 자본 분배 시 portfolio 수준에서 fold2 손실 완화 가능.

본 멀티버스(MV-F)는 이 가설을 정량 검증한다. 라이브 운영을 위한 결정이 아니라 **portfolio 자본 분배가 단독 macd_cross 보다 fold2/4ds-avg calmar 개선시키는지** 의 yes/no 답을 얻는 것이 목표.

---

## Goal

다음 cell 발견:
- **portfolio 4ds-avg calmar > 65.44** (단독 macd_cross stage2_best)
- **portfolio fold2 calmar > -2.80** AND **fold2 MDD 개선**
- **w_macd ≥ 0.4** (운영 제약: macd_cross 메인)

발견 시 다음 단계 = 별도 paper trial spec (자본 분배 라이브 통합 정책 결정).
없으면 = portfolio 가설 기각, 신규 family 설계 (MV-G ML/microstructure) 권고.

---

## Decided Scope (사용자 확정)

| 차원 | 결정 |
|------|------|
| 평가 strategy 수 | **3** — macd_cross, breakout_52w, trend_followthrough |
| 각 strategy 의 param | best param 만 (각자 1개) — Stage 1 sim 12회 (3 × 4 fold) |
| 시뮬 모델 | **Additive** — 각 strategy 독립 sim 후 equity 가중합 |
| Weight grid | simplex (w_m + w_b + w_t = 1.0), step=0.1 → 66 cells |
| Dataset | macd_cross 와 동일 4-fold (`load_all_datasets()`) |
| 평가 게이트 | G1 (4ds avg) / G2 (fold2 개선) / G3 (다른 fold 보존) / G4 (w_macd≥0.4) |

---

## 3 Strategy + Best Param

| name | class | best param | MV-E 결과 |
|---|---|---|---|
| macd_cross | `MACDCrossStrategy` | fast=14, slow=34, signal=12, entry_hhmm_min=1430 (Stage2 best) | fold1=36 / fold2=-2.80 / fold3=182 / oos=46, 4ds-avg=**65.44** |
| breakout_52w | `Breakout52wStrategy` | lookback=60, buffer=0.0, hhmm=1500 | fold1=62 / fold2=-4.13 / fold3=96 / oos=-3.92, 4ds-avg=**37.52** |
| trend_followthrough | `TrendFollowthroughStrategy` | lookback=3, buffer=0.6, hhmm=1430 | fold1=96 / fold2=-3.94 / fold3=33 / oos=-3.93, 4ds-avg=**30.26**, mcl=18 (위험) |

---

## Additive Portfolio 모델 (정확한 정의)

### Stage 1: equity 시계열 캐시
각 strategy × 4 fold = 12 sim 을 `BacktestEngine.run()` 으로 실행. 각 sim 의 `BacktestResult.equity_curve` (pandas Series, bar 단위) 를 NPY 로 저장.

```
backtests/reports/portfolio_allocation/equity_cache/
├── macd_cross_fold1.npy
├── macd_cross_fold2.npy
├── ...
└── trend_followthrough_oos.npy
```

각 NPY 는 1D float array — `equity[t]` (`initial_capital=10_000_000` 시작).

### Stage 2: weight sweep
simplex grid:
```python
weights = []
for wm_int in range(0, 11):          # 0.0, 0.1, ..., 1.0
    for wb_int in range(0, 11 - wm_int):
        wt_int = 10 - wm_int - wb_int
        weights.append((wm_int / 10, wb_int / 10, wt_int / 10))
# 66 cells
```

각 cell × 4 fold = 264 portfolio metric. cell 평가:
```python
# 각 strategy 의 정규화된 수익률
macd_ret = macd_equity / macd_equity[0]     # macd_equity[t] / 1천만
breakout_ret = breakout_equity / breakout_equity[0]
trend_ret = trend_equity / trend_equity[0]

# Portfolio equity (가중합, 초기 자본 1천만)
portfolio_equity = 1e7 * (
    w_m * macd_ret + w_b * breakout_ret + w_t * trend_ret
)

# Portfolio metric
portfolio_return = portfolio_equity[-1] / portfolio_equity[0] - 1
portfolio_mdd = compute_max_drawdown(portfolio_equity)
portfolio_calmar = compute_calmar(portfolio_equity, trading_days)
```

`compute_max_drawdown` / `compute_calmar` 는 기존 `backtests/common/metrics.py` 재사용.

### Caveat (additive 모델의 한계)

- **자본 공유 미반영**: 동일 종목에 동일 시점 매수 신호 발생 시 추가 자본 소모. 실제 portfolio 자본 공유에서는 reject 또는 sub-allocation 발생. additive 는 이를 무시.
- **상관 미반영 (correlation)**: 두 strategy 의 trade 가 서로 hedge 하지 않음을 의미하지 않음.
- 따라서 **결과 portfolio_calmar 는 over-optimistic 가능성** — 결과 해석 시 보수적 보정 필요.
- 추후 integrated 모델 (단일 engine + composite strategy) 검증은 별도 작업.

---

## 평가 게이트

### Primary (모두 통과 필요)
| Gate | 정의 | 임계 |
|------|------|------|
| **G1** | portfolio 4ds-avg calmar | > **65.44** (단독 macd_cross stage2_best) |
| **G2a** | portfolio fold2 calmar | > **-2.80** (단독 macd_cross fold2) |
| **G2b** | portfolio fold2 MDD | ≥ macd_cross fold2 MDD × 0.95 (개선) |

### Secondary
| Gate | 정의 | 임계 |
|------|------|------|
| **G3** | portfolio fold1/3/oos calmar 각각 손실율 | ≤ **10%** (단독 macd_cross 대비) |
| **G4** | w_macd | ≥ **0.4** (운영 제약: macd_cross 메인 유지) |
| **G5** | portfolio 4ds-avg MDD | ≥ macd_cross 4ds-avg MDD × 0.95 |

### 종합 판정
- **PASS**: G1+G2a+G2b 모두 통과 AND G3+G4+G5 중 ≥2 통과
- **PARTIAL**: G1 또는 G2a 만 통과 (사람 판단)
- **FAIL**: G1, G2a 모두 미통과

---

## 산출물

```
backtests/reports/portfolio_allocation/
├── equity_cache/                              # Stage 1 (3 × 4 = 12 NPY)
│   ├── macd_cross_fold1.npy ... oos.npy
│   ├── breakout_52w_fold1.npy ... oos.npy
│   └── trend_followthrough_fold1.npy ... oos.npy
├── cells.csv                                  # 264 행 (66 × 4)
├── summary.md                                 # G1~G5 자동 평가, best cell, PASS/PARTIAL/FAIL
├── heatmaps/
│   ├── portfolio_calmar_fold{1,2,3}_oos_4dsavg.png  # 5장 — simplex triangle heatmap
│   ├── portfolio_mdd_fold2.png
│   └── portfolio_return_4dsavg.png
└── portfolio_allocation_run.log
```

`cells.csv` 컬럼:
```
w_macd, w_breakout, w_trend, fold,
portfolio_calmar, portfolio_return, portfolio_mdd,
macd_calmar, breakout_calmar, trend_calmar  # 비교용 (단독 baseline)
```

---

## 코드 파일 구조

### 신규 파일 1
- `backtests/multiverse/portfolio_allocation_mv.py`:
  - Stage 1: 3 strategy × 4 fold sim → equity NPY 저장
  - Stage 2: weight simplex grid sweep → cells.csv
  - `--smoke` (3 strategy × 1 fold + 5 weight cells)
  - `--stage1` / `--stage2` 분리 옵션 (이미 캐시 있으면 stage2 만)

### 수정 파일 1
- `backtests/multiverse/plot_macd_cross_mv.py`:
  - `PA_DIR = Path("backtests/reports/portfolio_allocation")`
  - `plot_portfolio_allocation()`: simplex triangle heatmap (matplotlib `tricontourf` 또는 scatter)
  - `write_portfolio_allocation_summary()`: G1~G5 자동 평가
  - `main()` 분기

### 재사용
- `backtests.common.engine.BacktestEngine` (Stage 1 sim)
- `backtests.common.metrics.{compute_calmar, compute_max_drawdown}` (cell 재계산)
- `backtests.multiverse.macd_cross_mv_common.{load_all_datasets, Dataset, _trading_days_count}`

### 변경 금지
- 모든 strategy 파일 (`backtests/strategies/*.py`), engine, execution_model

---

## 검증

### Stage 1 검증
- 12 NPY 저장 후 macd_cross fold1 equity 의 마지막 값 ÷ 1천만 - 1 = MV-E baseline return 과 일치 확인 (spot check)
- 각 NPY 길이 = dataset bar 수 일치

### Stage 2 검증
- weight (1.0, 0.0, 0.0) cell 의 portfolio_calmar = macd_cross 단독 calmar (정확 일치)
- weight (0.0, 1.0, 0.0) cell = breakout_52w 단독 (정확 일치)
- 66 weight cells × 4 fold = 264 행 정확

### Smoke run
- `--smoke`: 3 strategy × 1 fold + 5 weight cells = ~10초

---

## 실행 단계

| 단계 | 작업 |
|------|------|
| S0 | runner 작성 (Stage 1+2) + smoke run |
| S1 | plot/summary 함수 추가 |
| S2 | Stage 1 sim (3 × 4 = 12 sim, ~15분) |
| S3 | Stage 2 sweep + cells.csv (1분 이하) |
| S4 | heatmaps + summary.md |
| S5 | 사람 판정 (PASS/PARTIAL/FAIL) + memory 업데이트 |

---

## Out of scope

- Integrated 모델 (composite strategy, capital sharing) — 별도 멀티버스
- Paper trial 통합 (PASS 시 별도 spec)
- 자본 분배 라이브 정책 (paper 후)
