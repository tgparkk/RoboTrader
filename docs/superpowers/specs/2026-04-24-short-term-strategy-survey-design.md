# 단타 전략 서베이 & 최적화 설계서

**작성일**: 2026-04-24
**목적**: 15+α 단타 전략을 독립적으로 조사·최적화해 실거래 투입 후보 선정
**비교 기준선**: weighted_score Trial 837 (Calmar 25.10, test 88일) — 재최적화 대상 아님, 리포트 비교용으로만 동일 엔진에 1회 실행

---

## 0. 전제 원칙 (비협상)

모든 작업은 **멀티버스 시뮬 3대 원칙** 준수가 전제다. 하나라도 어기면 결과 무효.

1. **미래 데이터 금지**: 모든 피처 `.shift(1)` 또는 `prev_*`. daily→분봉 broadcast 시 shift 누락 검증.
2. **시계열 자원 제약**: 각 시점 `available_cash = 초기자본 + 누적실현손익 − 미청산원금`. 매도 선처리 → 현금화 → 매수 순서. 포지션 상한·쿨다운 반영.
3. **현실 마찰**: 왕복 수수료 0.26% + 슬리피지 0.25%(실측 기반), 다음 분봉 시가 체결, 거래량 상한, 상·하한가 제약, 서킷브레이커 규칙, 시뮬 스크리너 = 실거래 스크리너.

단타 범위: **hold 0~2일** (당일 청산 + 1~2일 오버나잇 스윙). 데이트레이딩 필수 아님.

---

## 1. Scope & Deliverable

### 목표

N개 단타 전략을 **각각 독립적으로 최적화**하는 A × N 방식. 앙상블 결정은 차후 단계.

**최적화 대상**: 15 Classic + α Data-driven (= N) 전략
**비교 baseline**: weighted_score Trial 837 — 기존 실거래 전략. 재최적화하지 않고 동일 엔진에 1회 실행해 리포트 테이블에 병기.

### 전략 카탈로그 (15 신규 + 1 baseline + α)

#### Classic Intraday (hold=0, 10개)

| # | 전략 | 핵심 아이디어 |
|---|------|--------------|
| 1 | ORB (Opening Range Breakout) | 09:00~09:30 고점 돌파 |
| 2 | VWAP 반등 | VWAP 상·하단 터치 후 복귀 |
| 3 | 갭다운 역행 | 시가 −2% 이상 갭다운 → 09:30까지 반등 |
| 4 | 거래량 급증 추격 | 분봉 거래량 N배 + 가격 돌파 |
| 5 | 장중 눌림목 | 상승 추세 중 20EMA 근접 눌림목 |
| 6 | 볼린저 하단 반등 | 하단 이탈 후 복귀 |
| 7 | RSI 과매도 반등 | 1분·5분 RSI<25 반전 |
| 8 | 오후 풀백 / 장마감 드리프트 | 기존 closing_trade 계승 |
| 9 | 갭업 추격 | 강한 갭업(+3%↑) + 거래량 폭발 지속 |
| 10 | 상한가 따라잡기 | +20% 근접 종목 브레이크아웃 |

#### Classic Overnight Swing (hold=1~2일, 5개)

| # | 전략 | 핵심 아이디어 |
|---|------|--------------|
| 11 | 종가 매수→시가 매도 | 강한 종가(+3%↑) 종목 매수, 다음날 시가 청산 |
| 12 | 52주 신고가 돌파 | 돌파 당일 매수, 2일 홀드 |
| 13 | 낙주 반등 | 전일 −5% 이상 + 거래량 급증 → 1~2일 홀드 |
| 14 | 추세 돌파 follow-through | 5일 고점 돌파, 2일 홀드 |
| 15 | MACD 골든크로스 | 일봉 MACD 히스토그램 음→양, 2~3일 홀드 |

#### Baseline (비교군, 재최적화 안 함)

| # | 전략 | 비고 |
|---|------|------|
| B1 | weighted_score (기존 Trial 837) | 5일 홀드 — 단타 범위 초과. 동일 엔진에 1회 실행해 리포트 병기 |

#### Data-driven Discovered (α개, 3~5 예상)

16,200 팩터 조합 그리드 스윕 → 클러스터링 → 규칙화된 신규 전략.

### 전략별 산출물

- 최적 파라미터 JSON (Stage 2 베스트)
- 성과 리포트: Calmar / Sharpe / Return / MDD / Win% / PF / 거래수 / 평균 보유일
- Walk-forward 3폴드 개별 결과 + 평균
- 3원칙 준수 감사 체크리스트
- OOS(out-of-sample) 검증 결과

### 비교 리포트

15 신규 + α discovered + weighted_score baseline 을 동일 단위 랭킹 테이블.
위치: `backtests/reports/YYYY-MM-DD/`

---

## 2. 데이터 & 유니버스

| 층위 | 데이터 | 기간 | 용도 |
|------|--------|------|------|
| 분봉 | `minute_candles` | 2025-02-24 ~ 현재 (~14개월) | Intraday 전략 (10개) |
| 일봉 | `daily_candles` | 2022 ~ 현재 (~4년) | Overnight 전략 (5개) + baseline + 팩터 |
| 지수 | `daily_candles` (KS11/KQ11) | 2021 ~ 현재 (5년) | 레짐·서킷브레이커 판단 |

### 종목 풀

- KOSPI + KOSDAQ 약 2,472종
- 공통 필터: 가격 5,000~500,000원, 최소 일평균 거래대금 30억
- 전략별 추가 필터는 각 파라미터에서 탐색

### 현실 제약

분봉 데이터 기간 제약으로 **Intraday 전략은 최대 14개월 train+test**. Walk-forward 3폴드로 쪼개면 한 폴드당 test ~2개월. 이 한계 인정하고 **Overnight 전략은 4년 일봉 기반 더 긴 검증** 허용.

---

## 3. Evaluation Framework

### Walk-forward 3폴드 구조

**Intraday (14개월 분봉)**:
```
Fold 1:  train 2025-03~08 (6M)  → test 2025-09~10 (2M)
Fold 2:  train 2025-05~10 (6M)  → test 2025-11~12 (2M)
Fold 3:  train 2025-07~12 (6M)  → test 2026-01~02 (2M)
OOS:     2026-03~04 (2M) — 최종 선정 후 1회만 사용
```

**Overnight (4년 일봉)**:
```
Fold 1:  train 2022~2023           → test 2024 H1
Fold 2:  train 2022~2024 H1        → test 2024 H2
Fold 3:  train 2022~2024 H2        → test 2025 H1
OOS:     2025 H2 ~ 2026-04 — 최종 선정 후 1회만 사용
```

### 지표 & 게이트

```
주지표: Calmar (3폴드 평균)

게이트 (전부 통과해야 Stage 2 진입):
  overfit_ratio        ≥ 0.5    (test 평균 / train 평균)
  MDD (3폴드 최악)      ≤ 15%
  총 거래건수 (test 합)  ≥ 30건
  승률 (test 평균)       ≥ 35%
  월평균 거래건수        ≥ 3건

보조지표 (랭킹 무관, 리포트 병기):
  Sharpe, Total Return, PF, Win%, Avg Hold Days,
  일별 수익 변동성, 최악의 월 수익률
```

### OOS 검증

Stage 2 완료 후 상위 전략만 OOS 기간에 1회 적용. OOS 성과가 Stage 2 대비 크게 열화되면 overfitting 판정, 실거래 투입 탈락.

---

## 4. 2-Stage 최적화 방식

### Stage 1 (Coarse Filter)

- **목적**: 15+α 전략 중 가망 없는 건 빠르게 탈락 (baseline 제외)
- **방식**: 랜덤 서치 **200 trials** × 전략당
- **평가**: Fold 1 train → Fold 1 test (단일 폴드, 빠른 탐색)
- **통과 조건**: 게이트 5개 중 **3개 이상** + Calmar ≥ 3
- **시간 예산**: 전략당 ~2시간
- **결과**: 가망 전략 리스트 (~5~10개 예상)

### Stage 2 (Fine Search)

- **대상**: Stage 1 통과 전략만
- **방식**: Optuna TPE **1,000 trials** × 전략당
- **평가**: 3폴드 walk-forward 평균 Calmar
- **제약**: 게이트 5개 **전부** 통과해야 유효 trial
- **시간 예산**: 전략당 ~8시간
- **결과**: 전략별 최적 파라미터 + OOS 성과

### TPE 선택 근거

weighted_score Trial 837 이 Optuna TPE 로 찾은 결과. 같은 인프라 재사용 → 파라미터 탐색 일관성 + 코드 재사용. `core/strategies/weighted_score_params.json` 포맷 따름.

---

## 5. 엔진 설계 (3원칙 강제)

### 디렉토리 구조 (신규)

```
backtests/
├── common/
│   ├── engine.py             # 공통 백테스트 엔진 (시간순 시뮬)
│   ├── execution_model.py    # 슬리피지·수수료·체결지연
│   ├── capital_manager.py    # 자금 제약 (원칙 2)
│   ├── feature_audit.py      # shift(1) 자동 검증 (원칙 1)
│   └── metrics.py            # Calmar/Sharpe/MDD/PF/Win%
├── strategies/
│   ├── base.py               # 전략 추상 베이스
│   ├── orb.py                # 01_ORB
│   ├── vwap_bounce.py        # 02_VWAP 반등
│   ├── gap_down_reversal.py  # 03_갭다운 역행
│   ├── volume_surge.py       # 04_거래량 급증 추격
│   ├── intraday_pullback.py  # 05_장중 눌림목
│   ├── bb_lower_bounce.py    # 06_볼린저 하단 반등
│   ├── rsi_oversold.py       # 07_RSI 과매도 반등
│   ├── closing_drift.py      # 08_오후 풀백 (closing_trade 계승)
│   ├── gap_up_chase.py       # 09_갭업 추격
│   ├── limit_up_chase.py     # 10_상한가 따라잡기
│   ├── close_to_open.py      # 11_종가매수→시가매도
│   ├── breakout_52w.py       # 12_52주 신고가 돌파
│   ├── post_drop_rebound.py  # 13_낙주 반등
│   ├── trend_followthrough.py # 14_추세 돌파 follow-through
│   ├── macd_cross.py         # 15_MACD 골든크로스
│   └── discovered/           # Data-driven 발굴 전략
├── multiverse/
│   ├── stage1_coarse.py      # 랜덤 서치 200 trials
│   ├── stage2_fine.py        # Optuna TPE 1000 trials
│   └── data_driven_sweep.py  # 16,200 그리드 스윕
└── reports/
    └── YYYY-MM-DD/
        ├── summary.md
        ├── principle_audit.md
        └── <strategy>/
            ├── best_params.json
            ├── trials.csv
            ├── folds.md
            └── trades.csv
```

### 공통 체결 모델 (전략 무관, 강제 적용)

```python
# execution_model.py 상수
BUY_COMMISSION = 0.00015    # 매수 0.015%
SELL_COMMISSION = 0.00245   # 매도 0.245% (거래세 포함)
SLIPPAGE_ONE_WAY = 0.00225  # 편방향 0.225% (2/27~3/26 RoboTrader 81건 실측)
FILL_DELAY_MINUTES = 1      # 신호 발생 → 다음 분봉 시가 체결
VOLUME_LIMIT_RATIO = 0.02   # 일평균 거래대금의 2% 이하만 체결 가정
LIMIT_PRICE_BUFFER = 0.01   # 상·하한가 1% 이내 근접 시 체결 거부
```

### 전략 베이스 클래스

```python
# backtests/strategies/base.py
class StrategyBase:
    name: str
    hold_days: int            # 0, 1, 2
    param_space: Dict          # Optuna suggest 형식

    def prepare_features(self, df_minute, df_daily) -> pd.DataFrame:
        """피처 계산. 모든 컬럼은 shift(1) 또는 prev_* 규약."""
        raise NotImplementedError

    def entry_signal(self, features, t) -> Optional[Order]:
        """t 시점에서 매수 신호. features 는 t-1까지의 정보만."""
        raise NotImplementedError

    def exit_signal(self, position, features, t) -> Optional[Order]:
        """t 시점에서 매도 신호. hold_days / TP / SL / 시간만료 판단."""
        raise NotImplementedError
```

### 3원칙 자동 감사

- **원칙 1 (look-ahead)**: `feature_audit.py` 가 각 전략의 `prepare_features` 반환 DataFrame 을 검사. 특정 시점 t 에서 `features.loc[t]` 의 모든 값이 t-1 이전 데이터로 계산 가능한지 확인. 불가 시 테스트 실패.
- **원칙 2 (자금 제약)**: `capital_manager.py` 가 각 시점 `available_cash` 추적. 초과 주문은 거부·우선순위 자름. 매도 선처리 → 현금화 → 매수 순서 강제.
- **원칙 3 (현실 마찰)**: `execution_model.py` 를 거치지 않고 직접 시가 체결하는 코드는 린터로 차단 (ban list).

### 기존 코드 재사용

- `analysis/walkforward_*.py` — walk-forward 로직 패턴
- `core/strategies/weighted_score_strategy.py` — TPE + 피처 계산 패턴
- `analysis/simulate_track_common.py` — 분봉 로드·체결 시뮬 유틸

---

## 6. Data-driven (C) 발굴 방법

### 팩터 그리드

```
진입 팩터 (5축):
  volume_ratio:   [1.5x, 2x, 3x, 5x]           (20일 평균 대비)
  gap_pct:        [<-3%, -3~0%, 0~+2%, +2~+5%, >+5%]
  momentum_5d:    [<-5%, -5~0%, 0~+5%, >+5%]
  volatility_20d: [<2%, 2~4%, >4%]
  price_position: [신저가, 중간, 신고가]         (52주 기준)

진입 시간 (4축): 09:00~09:30, 09:30~11:00, 11:00~14:00, 14:00~15:20
보유 기간 (3축): hold_0, hold_1, hold_2
청산 규칙 (3축): profit_target_3%, profit_target_5%, 시간만료

= 4 × 5 × 4 × 3 × 3 × 4 × 3 × 3 = 17,280 조합 (실무: 무효 조합 제거 후 ~16,200)
```

### 파이프라인

1. **Stage 1-Grid**: 16,200 조합 × Fold 1 성과 계산 (멀티프로세싱)
2. **상위 10% 추출**: Calmar 상위 1,620 조합
3. **클러스터링**: 팩터 공간에서 K-means 또는 수동 분류 → 패턴 N개 추출
4. **각 패턴을 전략으로 규칙화**: `backtests/strategies/discovered/pattern_<n>.py`
5. **Stage 2 정밀 최적화**: Classic 과 동일 파이프라인 진입

**예상 발굴 수**: 3~5개 신규 전략 (경험상 16,200 조합 중 유의미한 클러스터는 소수).

---

## 7. 실행 계획 & 산출물

### 작업 순서

```
Phase 1 (인프라, 3~4일)
  ├─ backtests/common/ 엔진 구축
  ├─ feature_audit.py + ban-list 린터
  └─ 검증: weighted_score Trial 837 재현 (기존 결과와 일치 확인)

Phase 2 (전략 구현, 5~7일)
  ├─ strategies/base.py 추상 클래스
  ├─ Classic 15개 전략 구현 (전략당 0.5일) + baseline 어댑터 (weighted_score를 엔진에 태울 얇은 래퍼)
  └─ 각 전략 smoke test (1주 분봉으로 돌려보고 오류 없음)

Phase 3 (Stage 1, 1~2일)
  ├─ 15개 × 200 trials = ~3,000 runs (baseline 제외)
  └─ 게이트 통과 리스트 확정

Phase 4 (Data-driven 발굴, 2~3일)
  ├─ 16,200 그리드 스윕
  ├─ 클러스터링 → 3~5개 신규 전략 규칙화
  └─ Stage 1 재적용

Phase 5 (Stage 2, 2~3일, 병렬 가능)
  └─ 통과 전략 × 1,000 trials TPE

Phase 6 (리포트 & 결정, 1일)
  ├─ summary.md 랭킹 테이블
  ├─ OOS 검증
  └─ 실거래 투입 후보 선정 (사용자 최종 결정)

총 예상: 14~20일 (단일 작업자 기준, 컴퓨팅 시간 포함)
```

### 최종 산출물 예시

```
backtests/reports/2026-05-XX/summary.md

| 순위 | 전략              | Calmar | Sharpe | Return | MDD   | Win%  | 거래 | 게이트 |
|------|-------------------|--------|--------|--------|-------|-------|------|--------|
| 1    | weighted_score*   | 25.10  | 4.10   | +9.6%  | 2.4%  | 55.7% | 65   | ✅     |
| 2    | ORB_v2            | 18.30  | 3.22   | ...    | ...   | ...   | ...  | ✅     |
| 3    | discovered_2      | 15.70  | 2.85   | ...    | ...   | ...   | ...  | ✅     |
| ...  | ...               | ...    | ...    | ...    | ...   | ...   | ...  | ...    |
| 14   | 상한가따라잡기      | 2.10   | 0.45   | ...    | 28%   | ...   | ...  | ❌ MDD |

* weighted_score 는 baseline (5일 홀드, 단타 범위 초과). 비교 용도.
```

---

## 8. 가정 & 리스크

### 가정

- 분봉 데이터 품질: `minute_candles` 가 2025-02-24 이후 공백 없이 채워져 있음 (백필 필요 시 선행 작업)
- 일봉 데이터 품질: `daily_candles` 가 2022-01 ~ 현재 연속 존재
- 실측 슬리피지 0.225%: 2/27~3/26 RoboTrader 81건 기준. 단타 전략별 실측은 다를 수 있음 (향후 교정)

### 리스크

- **분봉 데이터 기간 부족**: Intraday 전략 test 각 2개월은 표본 부족. 결과 해석 시 신뢰구간 넓게 봐야 함
- **상한가 따라잡기 유동성**: 상한가 근접 종목은 체결 불확실성 큼. 시뮬 결과 과대평가 가능성 → VOLUME_LIMIT_RATIO 엄격 적용
- **Data-driven 과적합**: 16,200 조합에서 top 10% 골라내는 과정 자체가 selection bias. OOS 검증 필수
- **레짐 의존성**: 2025-03~04 하락장, 2026-03~04 위기 등 특수 시기가 walk-forward 폴드 분포에 편향 줄 수 있음

### 완화

- OOS 기간 엄격 분리 (fold 탐색 중 절대 안 봄)
- Overfit Ratio 게이트 (≥ 0.5) 로 1차 방어
- 최종 투입 결정 전 **최근 2주 paper trading** 으로 실거래 일치도 확인 (weighted_score 절차 참고)

---

## 9. 성공 기준

- Phase 6 완료 시 **최소 1개 전략**이 아래 조건 충족:
  - Walk-forward 3폴드 평균 Calmar > 10
  - OOS Calmar > 5 (train→test 열화 50% 이내)
  - 게이트 5개 전부 통과
  - 3원칙 감사 통과
- 결과 리포트 `summary.md` 완성 + 실거래 후보 1~3개 추천

---

## 10. 다음 단계

1. 이 설계서 사용자 검토
2. 승인 시 `writing-plans` 스킬로 Phase 별 구현 계획 상세화
3. Phase 1 인프라 구축부터 착수
