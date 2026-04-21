# weighted_score 실거래 통합 계획

**결정사항 (2026-04-21)**:
- A. 완전 대체: `price_position` → `weighted_score` 단독 운영
- A. Trial #1600 단일 (test Calmar 162.75)
- A. 실시간 피처 계산 (분봉 완성 훅)

**사전 조치**: `D:\GIT\run_all_robotraders.bat` 에서 RoboTrader 실행 라인 주석 처리 완료.

---

## 진행 상태 (2026-04-21 야간 업데이트)

| Phase | 항목 | 상태 |
|---|---|---|
| 1 | `weighted_score_params.json` 추출 | ✅ 완료 (270 KB, threshold_abs=-0.127) |
| 2 | `weighted_score_features.py` + `weighted_score_strategy.py` | ✅ 완료 |
| 3 | strategy_settings.py + trading_decision_engine.py 통합 | ✅ 완료 (VIRTUAL_ONLY 가드) |
| 3 | `weighted_score_daily_prep.py` (pre_market 준비 모듈) | ✅ 완료 |
| 4 | 통합 스모크 테스트 | ✅ 완료 (`tests/test_integration_smoke.py`) |
| 4+ | **price_position 전략 완전 폐기** | ✅ 완료 (파일/설정/신호경로/ATR dead code 제거) |
| 5 | main.py `_pre_market_task()` 훅 연결 | ✅ 완료 (`_prepare_weighted_score_for_today`) |
| 5 | stock_screener universe 공급 | ✅ 완료 (`preload_weighted_score_universe`) |
| 5 | 실거래/가상 분기 (VIRTUAL_ONLY 가드 해제) | ✅ 완료 (main.py 분기 + execute_virtual_buy 라우팅) |
| 5 | 가상 매매 1~2주 운영·관찰 | 📝 실 운영 시작 전 |
| 5 | 괴리 리포트 + 실 자본 소액 테스트 | 📝 운영 후 |

**현재 안전 상태 (Phase 5 연결 후)**:
- `ACTIVE_STRATEGY = 'weighted_score'` 로 설정됨
- `StrategySettings.WeightedScore.VIRTUAL_ONLY = True` → main.py 분기에서 **가상매매 경로**로 라우팅 (실제 주문 없음)
- 신호 자체는 발생 가능 (Phase 4 가드 해제). `execute_virtual_buy` → `virtual_trading_records` 테이블에 기록
- 실 주문을 열려면: `VIRTUAL_ONLY = False` 변경 필요 (의도적 수동 스위치)
- `run_all_robotraders.bat` 자동 실행에서 RoboTrader 제외됨 (주석)
- 가상매매 1~2주 관찰 → 시뮬 예측 vs 가상 체결 괴리 분석 후 실 자본 투입 판단

---

## 최적 파라미터 (Trial #1600)

**성과 (백테스트)**: train Calmar 96.18, test Calmar **162.75**, test return **+74.2%**, MDD 2.84%, Sharpe 9.69, win 62.2%, 394건

**진입**: entry_pct 96.15 (상위 4%), max_positions 9, max_holding_days 3

**청산**: SL -5.04%, TP +7.07%, max_hold 3일, 시간청산 비활성 (1680 bars → 사실상 max_hold 우선)

**가중치 (23개, stoch_k_14 제외)**: obv_slope_5d +2.88, hour_sin +1.64, minutes_since_open +1.22, kospi_trend_5d +1.20, cum_ret_3d **-2.93**, rel_ret_20d_kospi -1.96, gap_pct -1.88, ret_1min -1.54, adx_14 -1.27, rsi_14 -1.07, ...

---

## 수정/생성 파일 (실제 구현 결과)

### 신규 파일 (5개 — 생성 완료)
| 파일 | 역할 | 상태 |
|---|---|---|
| `core/strategies/weighted_score_strategy.py` | 전략 클래스 (PricePositionStrategy 인터페이스 유지) | ✅ |
| `core/strategies/weighted_score_features.py` | Daily/Intraday raw 계산 + 정규화 + score | ✅ |
| `core/strategies/weighted_score_daily_prep.py` | pre_market 에서 종목별 daily 피처/past_volume 주입 | ✅ |
| `core/strategies/weighted_score_params.json` | Trial 1600 가중치 + threshold_abs + 정규화 분포 (270 KB) | ✅ |
| `analysis/research/weighted_score/export_params.py` | 위 JSON 을 추출하는 스크립트 | ✅ |

### 수정 파일 (실제 수정된 위치)
| 파일 | 변경 | 상태 |
|---|---|---|
| `config/strategy_settings.py` | `ACTIVE_STRATEGY='weighted_score'`, `class WeightedScore`, validate, `get_candle_interval`, `is_overnight_strategy` | ✅ |
| `core/trading_decision_engine.py` | 초기화 블록, 신호 분기, `_check_weighted_score_buy_signal` (VIRTUAL_ONLY 가드 포함) | ✅ |
| `D:\GIT\run_all_robotraders.bat` | RoboTrader 실행 라인 주석 처리 | ✅ |
| `core/intraday_stock_manager.py` | 분봉 완성 훅 | ⏸ (Phase 5 직전 연결 — 현재 불필요) |
| `core/stock_screener.py` | `preload_weighted_score_universe()` | ⏸ (Phase 5 직전 연결) |
| `main.py._pre_market_task()` | `prepare_for_trade_date()` 호출 훅 | ⏸ (Phase 5 직전 연결) |

---

## 실시간 피처 계산 설계

### 피처 분류 (23개, Trial 1600 기준)

**Daily broadcast (장 시작 전 1회 계산)** — 12개
- 기술지표: rsi_14, macd_hist, bb_percent_b, adx_14 (atr_pct_14d, obv_slope_5d)
- 상대강도·시장: rel_ret_20d_kospi, rel_ret_20d_kosdaq, kospi_trend_5d, kospi_vol_20d
- 이전 데이터: gap_pct, prior_day_range, cum_ret_3d

**분봉 실시간** — 8개
- 가격·모멘텀: pct_from_open, ret_1min, ret_5min, ret_15min, ret_30min
- 변동성: realized_vol_30min
- 거래량: vol_ratio_5d (당일 누적 vs 최근 5일 평균 같은 시간대)

**시간 (초경량)** — 3개
- hour_sin, hour_cos, minutes_since_open

### 정규화 방식
연구 단계의 `features/pipeline.normalize_features()` 와 **동일** 적용:
- rolling_percentile: 분봉 기반 피처 → **학습 시점의 분포를 고정 사용** (아래 참조)
- scale_to_unit: rsi/adx (0~100), minutes_since_open (0~390)
- zscore_clip: macd_hist, relative_market, prior_day — **학습 분포의 mean/std 고정**
- 선형: hour_sin/cos, bb_percent_b

### **분포 고정 전략** (핵심 설계)
- 학습 기간 train 분봉 데이터(2025-04~2025-12)로 각 피처의 **정렬된 분포 스냅샷** 저장
- 실거래 시 해당 분포 대비 현재값의 percentile 을 `np.searchsorted` 로 계산
- → 장중 rolling 재계산 불필요, 속도·메모리 경량

### ENTRY_THRESHOLD_ABS 계산
- Trial 1600 weights × train ctx features 의 score matrix 에서 **96.15 percentile 값**을 구함
- 이 절대값을 `weighted_score_params.json` 에 저장 → 실거래 시 `score > THRESHOLD_ABS` 로 판정
- entry_pct(96.15) 은 참고용, 실제 판단은 절대값 기준

### 데이터 요구사항
- **전일 daily_candles**: 장 시작 전 준비 (pre_market_analyzer 훅)
- **KOSPI/KOSDAQ 일봉**: 장 시작 전 로드, 20일 history 필요
- **당일 분봉**: 실시간 업데이트 (기존 `intraday_stock_manager` 활용)
- **장 시작 시각 이전 30분봉**: ret_30min 초기화용 — 09:00 기준 이전 분봉이 없으므로 워밍업 약 30분 필요

---

## 527종목 풀 공급

**채택**: **전일 거래대금 상위 300 종목 + weighted_score universe 교집합** 

이유:
- weighted_score universe (260일+ 풀커버 517종목) 는 유동성 검증된 집합
- 전일 거래대금 상위 300 종목은 당일 움직임 높음
- 교집합 (대략 200~300종목) 이 실전 관점에서 가장 적절

구현: `stock_screener.preload_weighted_score_universe()` — pre_market 에서 1회 호출

---

## 구현 순서 (단계별)

### Phase 1: 파라미터 정지 데이터 구축 (15분)
1. `weighted_score_params.json` 생성 스크립트 작성 (analysis/research/weighted_score/export_params.py)
2. Trial 1600 weights + 학습 분포 스냅샷 + ENTRY_THRESHOLD_ABS 저장
3. JSON 스키마:
```json
{
  "trial_number": 1600,
  "threshold_abs": 10.2345,
  "weights": {...},
  "exit_policy": {"stop_loss_pct": -5.04, ...},
  "max_positions": 9,
  "feature_distributions": {
    "rolling_percentile": {"pct_from_open": [sorted values...], ...},
    "zscore_params": {"macd_hist": {"mean": X, "std": Y}, ...}
  },
  "daily_reference_dates": "20250417-20251215"
}
```

### Phase 2: 신규 전략 클래스 (1시간)
4. `core/strategies/weighted_score_strategy.py`
   - `check_entry_conditions()`: 시간·요일·기본 필터
   - `check_advanced_conditions()`: score 계산 → `score > threshold_abs`
   - `check_exit_conditions()`: SL/TP 검사 (분봉 high/low 로 인트라바 체크)
   - `record_trade()`: 당일 거래 기록

5. `core/strategies/weighted_score_features.py`
   - `DailyFeatureCalculator`: 장 시작 전 1회 (daily 피처 12개)
   - `IntradayFeatureCalculator`: 매 분봉 완성 시 (분봉 피처 8개 + 시간 3개)
   - `normalize_to_unit(raw, feature_name)`: 분포 기반 정규화

### Phase 3: 실거래 코드 통합 (1시간)
6. `config/strategy_settings.py` — `class WeightedScore` 추가, 검증 분기 추가
7. `core/trading_decision_engine.py` — 전략 초기화 + 신호 분기 + 매도 처리
8. `core/intraday_stock_manager.py` — 분봉 완성 훅 (피처 캐시 갱신)
9. `core/stock_screener.py` — `preload_weighted_score_universe()`

### Phase 4: 검증 (✅ 완료 — 통합 스모크 통과)
10. `analysis/research/weighted_score/tests/test_integration_smoke.py` (완료):
    - 2종목 `prepare_for_trade_date` 호출 → daily 피처 주입 확인
    - past_volume_by_idx 맵 생성 (390 entries/종목)
    - 분봉 시점별 `get_score()` 정상 반환
    - `check_advanced_conditions` 동작 확인 (threshold 비교)
    - 소요: 14.6s / 2종목

**추가 필요 테스트 (Phase 5 시작 전)**:
- 연구 파이프라인(`features/pipeline`) 과 `weighted_score_features` **수치 parity** 검증
- 동일 종목/일자 — 연구 normalize vs 실거래 normalize 결과 비교
- 24 피처 값 모두 일치하는지 (오차 1e-6 이내)

### Phase 5: 가상 매매 (운영 1~2주, 미착수)
11. main.py._pre_market_task() 에 `prepare_for_trade_date()` 호출 추가
12. stock_screener 에 universe 공급 메서드 추가 (전일 거래대금 상위 300)
13. `VIRTUAL_ONLY` 플래그 해제 + `use_virtual_trading=true` (config/trading_config.json)
14. 1~2주 가상 매매 로그 수집
15. 시뮬 예측 vs 가상 체결 괴리 리포트
16. OK 시 실 반영 (buy_budget_ratio 소액 5%부터)

---

## 위험 완화

| 위험 | 완화 |
|---|---|
| 시뮬-실거래 괴리 (역사적 -50% gap) | Phase 5 가상매매 단계 필수, 괴리 리포트 |
| 실시간 피처 정규화 drift | 학습 시점 분포 고정, 월 1회 재학습 |
| 워밍업 구간 거래 배제 | 09:30 이후 진입 허용 (30분 warmup) |
| 장중 하락 리스크 | EOD 15:00 강제청산 유지 (기존 로직) |
| max_positions=9 과밀 | 초기 운영은 max_positions=5 로 축소 (하드오버라이드 옵션) |
| OBV_slope_5d 전일 종가 의존 | daily_candles 테이블에서 자동 조회, 누락 시 매매 차단 |
| 기술지표 계산 시점 차이 | ta 라이브러리 동일 사용, shift(1) 유지 |

---

## 롤백 계획

문제 발생 시 즉시 복귀:
1. `config/strategy_settings.py:26` → `ACTIVE_STRATEGY = 'price_position'`
2. `run_all_robotraders.bat` 의 RoboTrader 라인 주석 해제
3. 기존 전략 로직 전부 보존되어 있으므로 재시작만 하면 즉시 복귀

---

## 진행 방식

다음 단계:
1. 이 계획서 검토
2. 승인 시 Phase 1 (파라미터 추출) 부터 순차 구현
3. 각 Phase 완료 시 간단 리포트 + 계속 진행 여부 컨펌
4. Phase 4 검증까지 완료 후 Phase 5 가상매매는 **별도 결정**

**즉시 실 운영 반영 없음**. Phase 1~4 는 코드 작업, Phase 5 는 가상 매매, 실 자본 투입은 그 이후.
