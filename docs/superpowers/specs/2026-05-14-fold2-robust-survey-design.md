# MV-E: fold2-robust 진입 전략 발굴 멀티버스 — Design

**날짜**: 2026-05-14
**상태**: Spec (구현 전, user review 대기)
**관련**: docs/superpowers/specs/2026-04-24-short-term-strategy-survey-design.md (선행 survey)
**관련 결론**: memory/project_macd_cross_paper.md (MV-A→B→C→D 모두 FAIL — fold2 회복 불가 확정)

---

## Context

macd_cross 멀티버스 시리즈 MV-A/B/C/D 가 모두 FAIL 로 종결. **fold2 (2025-11~12 KOSDAQ 약세) 손실은 macd_cross 의 entry/exit 어떤 조합으로도 회복 불가** — 기간 자체가 손실 원인. 운영 정책은 macd_cross 단일 라이브 + 서킷브레이커 -3% + 킬스위치 만 유지.

본 멀티버스(MV-E)는 macd_cross 외부에서 답을 찾는다 — **fold2 에서 견고한(또는 양수 calmar 인) 진입 전략을 발굴**하여 macd_cross 와 portfolio 운영 가능성을 검증.

신규 구현 부담을 최소화하기 위해 **이미 존재하는 17 strategy 자산을 재평가**한다. 선행 단계에서 2026-04-24 survey 가 있었으나, 본 MV-E 는 동일 인프라(`backtests/multiverse/macd_cross_mv_common.py` + 4 fold + 동일 universe)로 macd_cross 와 직접 비교 가능한 형태로 재평가한다.

---

## Goal

다음 조건을 모두 만족하는 strategy 를 1개 이상 발견:

1. **fold2 calmar > 10** (macd_cross fold2 calmar -2.80 보다 명백 우월)
2. **fold1/3/oos calmar 모두 > 30** (다른 시기에도 acceptable 수준 유지)
3. monthly_trades 5~30 범위 (운영 가능)
4. top1_share < 0.6 (단일 trade 가 결과 결정 안 함)
5. max_consec_loss ≤ 5

PASS 시 paper 30일 검증 → macd_cross 와 portfolio 동시 운영 검토.
FAIL 시 17 strategy 자산 부족 결론 → 신규 family 설계 (MV-F) 우선순위 상향.

---

## Decided Scope (사용자 확정)

| 차원 | 결정 |
|------|------|
| Discovery 출발점 | 기존 17 strategy 재평가 (analysis/signal_*.py 의 결과는 참고만, 동일 인프라 재평가) |
| Sweep 구조 | **Stage 2 직행** (각 strategy 의 param fine sweep — 사용자 7개 후보 직접 선정) |
| 후보 strategy 수 | **7개** (약세장 친화 4 + 중립 1 + 상승장 친화 2) |
| 평가 기준 | fold2 견고성 우월 — 위 G1~G5 게이트 |
| Dataset | macd_cross 와 동일 — fold1/2/3/oos 4개 (`load_all_datasets()` 재사용) |
| Universe | macd_cross 와 동일 — Stage 2 캐시 top 30 (변경 없음) |
| 초기 자본 | 1천만 (build_cell_kpis 기본값) |

---

## 평가 대상 7 Strategy

| # | strategy class | hold | 시그널 분류 | fold2 기대 |
|---|---|:--:|---|---|
| 1 | `GapDownReversalStrategy` | 0 (intraday) | 갭하락 → 일중 반등 | ◎◎ 약세장 시그널 多 |
| 2 | `RSIOversoldStrategy` | 0 | 과매도 (RSI<X) → 반등 | ◎◎ 약세장 시그널 多 |
| 3 | `BBLowerBounceStrategy` | 0 | BB 하단 터치 → 반등 | ◎ 약세장 친화 |
| 4 | `VWAPBounceStrategy` | 0 | VWAP 하단 이탈 → 회귀 | ○ 중립 (양방향) |
| 5 | `ClosingDriftStrategy` | 1 (overnight) | 종가 부근 진입 → 익일 시가 청산 | ○ 시장 무관 가설 |
| 6 | `Breakout52wStrategy` | 2 (swing) | 52주 신고가 돌파 | ✗ 약세장 시그널 부족 (대조군) |
| 7 | `TrendFollowthroughStrategy` | 2 (swing) | 추세 follow | ✗ 약세장 손실 가능 (대조군) |

**6/7 (상승장 친화) 의 포함 의도**: portfolio 다변화 + 데이터로 가설 검증 — fold1/3 강한 strategy 가 macd_cross 와 시기별 보완 가능한지.

**제외된 10 strategy** (사용자 선정에서 배제):
- 폐기 예정: weighted_score_baseline, weighted_score_full
- 상승장 친화 추가 후보 (이번엔 제외): gap_up_chase, limit_up_chase, volume_surge, intraday_pullback, post_drop_rebound, orb, close_to_open

---

## 평가 게이트

### Primary (모두 통과 필요)
| Gate | 정의 | 임계 |
|------|------|------|
| **G1** | fold2 calmar | > **+10** |
| **G2** | fold1 / fold3 / oos calmar 모두 | > **+30** |

### Secondary (보조 — cherry-pick / 운영불가 회피)
| Gate | 정의 | 임계 |
|------|------|------|
| **G3** | 4ds-avg calmar | > **+30** |
| **G4** | monthly_trades (4ds avg) | **5~30** |
| **G5** | top1_share (각 fold 최댓값) | < **0.6** |
| **G6** | max_consec_loss (각 fold 최댓값) | ≤ **5** |

### 종합 판정
- **PASS**: 어느 1 strategy 의 ≥1 cell 이 G1+G2 통과 AND G3~G6 중 ≥3 통과
- **PORTFOLIO 후보**: G1 미통과지만 G2 통과 AND G3~G6 중 ≥3 통과 — macd_cross 와 시기별 보완 strategy 로 분류 (자체 단독 운영 PASS 는 아니지만 자본 분배 검토 가치)
- **FAIL**: G1 또는 G2 통과 cell 0건 (또는 통과해도 G3~G6 다수 미달 = garbage)

---

## Sweep 구조 (디테일은 implementation plan 에서 확정)

각 strategy 의 `param_space` 클래스 속성을 활용하여 fine sweep grid 구성:
- 4 strategy 당 ~30~80 cell 예상 (param 차원 갯수에 따라)
- 7 strategy × 평균 70 cell × 4 dataset ≈ **2000 eval 추정** (plan agent 가 정확 계산)
- 예상 실행시간 ≈ 1.5~2 시간 (MV-D 232 eval 16분 비례)

**축소안** (cell 수 폭발 시): 각 strategy 의 param 차원 중 2~3개만 sweep, 나머지는 default. cell 수 ~50/strategy 로 제한.

---

## 코드 파일 구조

### 신규 파일 1
- `backtests/multiverse/fold2_robust_survey_mv.py` (runner)
  - 7 strategy 의 param grid 정의 (또는 plan agent 가 정의)
  - 각 cell 에 대해 `build_cell_kpis()` 호출 + reason 분포
  - `cells.csv` 작성: `strategy, cell_label, dataset, <params...>, calmar, return, mdd, trades, win_rate, top1_share, max_consec_loss, monthly_trades, reason_<*>`
  - `--smoke` 옵션 (1 strategy × 1 cell × 1 ds 빠른 sanity)

### 수정 파일 1
- `backtests/multiverse/plot_macd_cross_mv.py`
  - `FR_DIR = Path("backtests/reports/fold2_robust_survey")` 추가
  - `plot_fold2_robust_survey()` — strategy 별 param heatmap (각 strategy 의 핵심 param 2축)
  - `write_fold2_robust_survey_summary()` — G1~G6 자동 평가, per-strategy best, PASS/PARTIAL/FAIL/PORTFOLIO 후보 분류
  - `main()` 분기 추가

### 변경 금지 파일 (라이브 동등성)
- `backtests/strategies/<7 strategy>.py` — 모두 수정 금지
- `core/strategies/macd_cross_signal.py`, `backtests/strategies/macd_cross.py`, `engine.py`, `execution_model.py`

### 재사용 함수
- `backtests/multiverse/macd_cross_mv_common.py`: `load_all_datasets`, `Dataset`, `build_cell_kpis`, `_trading_days_count`, `compute_top1_share`, `compute_max_consec_loss`
- `backtests/common/{engine, execution_model}` (자동 적용)

---

## 산출물 구조

```
backtests/reports/fold2_robust_survey/
├── cells.csv                          # ~2000 행
├── summary.md                         # G1~G6 자동 평가, per-strategy best, 판정
├── heatmaps/                          # strategy 별 param heatmap
│   ├── gap_down_reversal_calmar_<pair>.png
│   ├── rsi_oversold_calmar_<pair>.png
│   └── ...
└── fold2_robust_survey_run.log
```

`summary.md` 구조:
1. 개요 + 평가 cell 수 + 실행시간
2. macd_cross baseline 비교 (4ds calmar 65.44 / 127.69 기준선)
3. Per-strategy best cell (G1~G6 통과 여부)
4. PASS / PORTFOLIO 후보 / FAIL 분류표
5. fold2 calmar 정렬 top 20 cells
6. 종합 판정 + 다음 단계 권고
7. "사람 보강 결론" 섹션 (구현 후 사람 판정 추가)

---

## 검증

### Smoke run (S0 단계)
- `--smoke` 로 1 strategy × 1 cell × 1 dataset 빠른 sanity
- cells.csv 컬럼·reason 분포 합=1.0 확인

### 통합 검증 (본 시뮬 후)
- cells.csv 행 수 = 예상 eval 수 일치
- 각 strategy 의 default param cell 의 결과가 (기존 단위 테스트 또는 analysis/signal_*.py 의 산출물 있다면) 합리적 범위인지 spot check
- reason 분포 합 = 1.0 per row

### 멀티버스 3원칙 준수
1. **미래 데이터 금지**: 기존 strategy 들의 `prepare_features` 가 이미 shift(1) 또는 prev_* 규약 사용 (StrategyBase docstring). 신규 wrapper 없으므로 lookahead 위험 추가 없음.
2. **시계열 자원 제약**: capital_manager 자동 적용
3. **현실 마찰**: slippage 0.225%, 수수료 0.015%/0.245%, 1-bar 체결지연 자동 적용

---

## 실행 단계 (high-level — 디테일은 plan)

| 단계 | 작업 |
|---|---|
| S0 | 7 strategy 의 `param_space` + 기본 동작 확인 (default param 으로 단일 dataset 실행) |
| S1 | runner 작성 + smoke run |
| S2 | plot/summary 함수 추가 + smoke 결과로 sanity |
| S3 | 본 시뮬 (~1.5~2시간) — background |
| S4 | heatmap + summary.md 생성 |
| S5 | 사람 판정 (PASS / PORTFOLIO 후보 / FAIL) + memory 업데이트 |
| S6 | (PASS 시) paper 통합 plan 별도 — 본 MV-E scope 밖 |

---

## 성공/실패 판정 후속

### PASS (1 strategy 가 G1+G2 통과)
- 다음 단계: paper 30일 trial 설계 → 별도 spec
- 이 시점에서 paper 자본 분배, macd_cross 와 portfolio 운영 모드 결정

### PORTFOLIO 후보 (G1 미통과, G2 통과)
- macd_cross 와 시기별 보완 가설 — 약세장(fold2) 은 macd_cross 가 못 견디고 다른 strategy 도 못 견디지만, 다른 시기엔 보완
- 검토: 자본 분배 비율 vs 단일 macd_cross 의 4ds-avg calmar 와 비교
- 사람 판정 단계에서 명시적으로 검토

### FAIL (모든 strategy G1, G2 동시 미통과)
- 결론: 17 strategy 자산 부족, fold2 견고 + 다른 fold 도 강한 family 부재
- 다음 작업: MV-F 신규 family 설계 (ML 기반, multi-stock interaction 등)

---

## Out of scope

- 새 strategy 코드 작성 (MV-F 에서)
- ML 기반 시그널 (MV-F)
- macd_cross 와의 자본 분배 모델 (paper trial plan 에서)
- 라이브 통합 (paper 검증 후)
