# Weighted Score Strategy — 파라미터 탐색 프로젝트

1년치 분봉 데이터(527종목)로 가중 점수 전략의 최적 파라미터를 **무(無)에서** 탐색한다.

- **목적함수**: Calmar (연수익률 / MDD)
- **전략**: 24개 정규화 피처의 가중합 > 임계치
- **2단계 탐색**: Phase A(L1 로지스틱) → Phase B(Optuna TPE)
- **평가**: 앞 8개월 train / 뒤 4개월 test

설계 상세: `C:\Users\sttgp\.claude\plans\500-1-1-distributed-hearth.md`

---

## 디렉토리

**연구 (analysis/research/weighted_score/)**

```
analysis/research/weighted_score/
├── export_params.py         # Trial weights+분포 → core/strategies/weighted_score_params.json
├── INTEGRATION_PLAN.md      # 실거래 통합 설계 + 진행 상태
├── FINAL_SUMMARY.md         # Phase B 결과 요약 (artifacts/)
├── config.py                # 상수 (DATA_START/END, 비용, 자본, 시드, 경로)
├── universe.py              # 260일+ 풀커버 종목 선정 + snapshot
├── data/
│   ├── pg_loader.py         # PostgreSQL 분봉/일봉/지수 로더
│   ├── daily_bars.py        # 분봉 → 일봉 집계
│   └── feature_store.py     # parquet 캐시 R/W
├── features/
│   ├── price_momentum.py    # 5개 (pct_from_open, ret_1/5/15/30min)
│   ├── volume_volatility.py # 4개 (vol_ratio_5d, atr_pct_14d, ...)
│   ├── technical.py         # 5개 (rsi_14, macd_hist, bb_pct_b, stoch, adx) — ta lib
│   ├── relative_market.py   # 4개 (vs KS11/KQ11 daily broadcast)
│   ├── temporal.py          # 3개 (hour_sin/cos, minutes_since_open)
│   ├── prior_day.py         # 3개 (gap_pct, prior_day_range, cum_ret_3d)
│   ├── normalize.py         # rolling_percentile, sigmoid, zscore_clip, scale_to_unit
│   └── pipeline.py          # raw + normalize 오케스트레이터
├── strategy/
│   ├── weighted_score.py    # WeightedScoreStrategy (가중합 + 임계치)
│   └── exit_rules.py        # ExitPolicy (SL/TP/trail/time/max_hold/score_flip)
├── sim/
│   ├── engine.py            # 레퍼런스 엔진 (slow, dict/pandas 기반)
│   ├── fast_engine.py       # 매트릭스 기반 고속 엔진 (112x speedup)
│   ├── portfolio.py         # Position, Trade, Portfolio 상태 머신
│   ├── metrics.py           # Calmar/MDD/Sharpe/승률 + realized_equity_curve
│   └── cost_model.py        # 편도 0.28% 고정 슬리피지
├── phase_a/
│   ├── labeling.py          # triple-barrier (+1.5%/-1.5%/60bars)
│   ├── train_logreg.py      # L1 로지스틱 + TimeSeriesSplit CV
│   ├── exit_grid.py         # 청산 파라미터 그리드 서치
│   └── run.py               # 엔드투엔드 CLI
├── phase_b/
│   ├── search_space.py      # Optuna distributions (가중치 부호는 Phase A seed)
│   ├── objective.py         # trial → simulate_fast → Calmar
│   ├── runner.py            # Study + SQLite storage + n_jobs
│   └── validate.py          # top-K trial → test 재시뮬 + 리포트
├── artifacts/               # (gitignore) 실행 결과물
│   ├── features/*.parquet   # 종목별 피처 캐시
│   ├── phase_a/<run_id>/    # weights.json, exit_grid.csv, report.md
│   └── phase_b/<study>/     # study.db, best_params.json, trials.csv, validation.csv, report.md
└── tests/
    ├── test_features_smoke.py       # Step 2: 1종목 왕복
    ├── test_features_all.py         # Step 3: 24피처 통합
    ├── test_metrics.py              # Step 4: 손계산 검증
    ├── test_engine_smoke.py         # Step 5: 3종목×5일 엔진
    ├── test_phase_a_smoke.py        # Step 6: 라벨링 + logreg
    ├── test_fast_engine_parity.py   # Step 7+: fast vs slow parity
    └── test_integration_smoke.py    # Phase 3 통합 스모크 (2종목 daily+intraday)
```

**실거래 통합 (core/strategies/)**

```
core/strategies/
├── price_position_strategy.py      # (기존) 폐기 예정, 롤백용 유지
├── closing_trade_strategy.py       # (기존)
├── weighted_score_strategy.py      # 🆕 Trial #1600 기반 전략
├── weighted_score_features.py      # 🆕 Daily/Intraday raw + 정규화 + score
├── weighted_score_daily_prep.py    # 🆕 pre_market 용 준비 모듈
└── weighted_score_params.json      # 🆕 Trial #1600 파라미터 (270 KB)
```

---

## 현재 상태 (2026-04-21)

### 연구 단계 완료 Step
1. ✅ config + universe + pg_loader (517종목, 262 거래일)
2. ✅ 5개 price/momentum 피처 + parquet 캐시
3. ✅ 나머지 5 카테고리 → 총 24 피처
4. ✅ Cost model + metrics (Calmar/MDD/Sharpe, 손계산 단위테스트)
5. ✅ Strategy + Portfolio + Engine + 3종목 스모크
6. ✅ Phase A 라벨링 + L1 로지스틱 (CV AUC 0.70)
7. ✅ Phase A 그리드 서치 + run.py
8. ✅ **FastEngine** (112x speedup, 시계열 무결성 보존)
9. ✅ Phase B (Optuna TPE + SQLite + validate)
10. ✅ 풀 Phase A (200종목, 640 combos, ~39분)
11. ✅ 풀 Phase B (2000 trials, n_jobs=4, ~31분)
12. ✅ Validate → Trial #1600 선정 (test Calmar 162.75, return +74.2%)

### 실거래 통합 Phase (INTEGRATION_PLAN.md)
- ✅ Phase 1: 파라미터 추출 (`core/strategies/weighted_score_params.json`)
- ✅ Phase 2: 전략 클래스 + 피처 계산기
- ✅ Phase 3: strategy_settings + trading_decision_engine 통합 (VIRTUAL_ONLY 가드)
- ✅ Phase 4: 통합 스모크 테스트 통과
- ✅ **price_position 전략 완전 폐기** (파일·설정·신호경로·ATR dead code 제거)
- ⏸ Phase 5: main.py 훅 연결 + 가상 매매 1~2주 (미착수)

### 안전 상태
- `ACTIVE_STRATEGY = 'weighted_score'` 로 전환됨
- 단 `WeightedScore.VIRTUAL_ONLY = True` → 실제 주문 명시적 차단
- `run_all_robotraders.bat` 에서 RoboTrader 자동 실행 주석 처리

---

## 설계 결정

| 항목 | 값 | 비고 |
|---|---|---|
| Universe | 260일+ 풀커버 **517종목** | `config.MIN_TRADING_DAYS` |
| Train/Test | 앞 8개월 / 뒤 4개월 (174일/88일) | 실제 거래일 기반 자동 계산 |
| 목적함수 | `Calmar = 연수익률 / MDD` | `sim.metrics.PerfMetrics.calmar` |
| 거래비용 | 편도 0.28% (수수료+세금+슬리피지 0.05%) | `sim.cost_model.CostModel` |
| 포지션 사이즈 | 고정 1,000만원/건 | `config.POSITION_SIZE_KRW` |
| 동시 보유 | 3~10 (변수) | Optuna search |
| 홀딩 상한 | 3일 또는 5일 (categorical) | Optuna search |
| 라벨링 | Triple-barrier (+1.5%/-1.5%/60bars) | `phase_a.labeling` |

---

## 피처 목록 (24개, 전부 shift(1) 적용)

| 카테고리 | 피처 | 정규화 |
|---|---|---|
| price_momentum (5) | pct_from_open, ret_1/5/15/30min | rolling_percentile |
| volume_volatility (4) | vol_ratio_5d, atr_pct_14d, realized_vol_30min, obv_slope_5d | rolling_percentile |
| technical (5) | rsi_14, macd_hist, bb_percent_b, stoch_k_14, adx_14 | scale_to_unit / zscore_clip |
| relative_market (4) | rel_ret_20d_kospi/kosdaq, kospi_trend_5d, kospi_vol_20d | zscore_clip |
| temporal (3) | hour_sin, hour_cos, minutes_since_open | 선형 shift / scale |
| prior_day (3) | gap_pct, prior_day_range, cum_ret_3d | zscore_clip |

**Plan 대비 차이**:
- MA deviation (5/20/60), VWAP 편차, OBV 원시값, NXT sentiment 3개 누락 (향후 확장 여지)
- 실제 24개 피처로도 CV AUC 0.65~0.70 확보

---

## 실행 방법

```bash
# 0) Universe 갱신 (최초 1회)
python -m analysis.research.weighted_score.universe

# 1) Phase A 스모크 (3종목, 수십 초)
python -m analysis.research.weighted_score.phase_a.run --smoke

# 2) Phase A 풀런 (원하는 universe 크기)
python -m analysis.research.weighted_score.phase_a.run --universe-size 200

# 3) Phase B 스모크 (50 trials, 3종목)
python -m analysis.research.weighted_score.phase_b.runner --smoke

# 4) Phase B 풀런 (최신 Phase A 자동 사용)
python -m analysis.research.weighted_score.phase_b.runner --trials 2000 --universe-size 200

# 5) 검증 (top 20 trial 을 test 구간에 재시뮬)
python -m analysis.research.weighted_score.phase_b.validate --study phaseb_YYYYMMDD_HHMMSS --top 20

# 단위/통합 테스트
python -m analysis.research.weighted_score.tests.test_metrics
python -m analysis.research.weighted_score.tests.test_fast_engine_parity
```

---

## Fast Engine 성능 (Step 7+ 최적화)

- **112x speedup** 대 slow engine (parity test 확인)
- 3종목 × 174일 시뮬: 2.36s → 0.021s
- Phase A 24 combos: 345s → 2.6s (133x)
- 0.31s/trial 으로 Phase B 2000 trials: **~10분** 가능 (3종목 기준)

**시계열 무결성 보장**:
- 모든 피처는 shift(1) 적용 (look-ahead 차단)
- SL/TP/MaxHold 는 진입 후 forward scan (결정론, 상태 불변)
- 포지션 슬롯 관리는 작은 루프 (chronological)

**v1 제약**: trailing stop / score_exit_threshold 미지원 → 필요 시 fast_engine v2 에서 추가.

---

## 아티팩트 관리

`artifacts/` 하위 전체는 .gitignore 대상 (용량 大):
- `features/` — 종목당 ~4MB × 500 = ~2GB
- `phase_a/<run_id>/` — 수 MB
- `phase_b/<study>/study.db` — SQLite, trial 수에 비례 (~수 MB)

재실행 시 피처 캐시가 있으면 재사용됨 (`feature_store.has_features()` + schema 검증).

---

## 위험 요소 & 완화

| 위험 | 완화 |
|---|---|
| Look-ahead leak | shift(1) 강제 + `tests/test_features_*` parity |
| Overfit (3종목 스모크) | Phase B validate 에서 train/test 비율 < 2.0 필터 |
| 메모리 폭주 (500종목 × 24피처) | 종목별 parquet 분할, 캐시 재사용 |
| EOS vs MAX_HOLD 라벨 불일치 | parity test 에서 등가 취급 (메트릭 무영향) |
| Optuna 조건부 파라미터 경고 | `time_exit_bars` random 폴백 (성능 영향 경미) |
