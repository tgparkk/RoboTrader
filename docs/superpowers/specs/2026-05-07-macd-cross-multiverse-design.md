# macd_cross 멀티버스 설계 (파라미터 robustness + exit overlay)

작성일: 2026-05-07
관련 산출물:
- `backtests/strategies/macd_cross.py` — 백테스트 본체 (라이브 1:1 동등)
- `backtests/reports/stage2/macd_cross_best.json` — Stage 2 Optuna best (fast=14, slow=34, signal=12, entry=1430)
- `backtests/reports/stage2/PHASE6_DECISION.md` — 4-pillar audit
- `docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md` — 라이브 통합 설계

## 1. 배경 및 목적

Stage 2 Phase 3 (1000 trials × 3-fold WF) + OOS hold-out 으로 macd_cross 가 유일하게 게이트를 통과했으나, 4-pillar audit 결과 두 가지 잔존 우려:
- **fragility**: top1 trade P&L 점유율 56.8%, top5 100.8% — 한 종목 빠지면 결과 무너짐
- **fold 2 fail**: 3-fold 중 2025-11~12 fold 만 Calmar -3.12 / WR 34% 로 불통과

본 설계는 **두 가지 멀티버스를 직교 실행**하여 위 우려를 정량화하고, 동시에 **exit overlay 도입 가치**를 가설검증한다.

| 멀티버스 | 목적 | 변량 | 고정 |
|----------|------|------|------|
| MV-A: 파라미터 robustness | best 가 plateau 위인가 절벽 위인가 | MACD 4축 fine grid | exit overlay 없음 (현재 라이브 동등) |
| MV-B: exit overlay | SL/TP/MACD reversal 도입 가치 | exit 3축 joint | best params 고정 |

`feedback_paper_no_live_overlay.md` 와의 정합: 본 작업은 **백테스트 가설탐색** 단계라 overlay 탐색이 정당. 발견된 좋은 overlay 는 별도 페이퍼/OOS 검증 단계로 후속 (본 spec 범위 밖).

## 2. 데이터·기간·평가 매트릭스

### 2.1 데이터
- **분봉**: 2025-03-01 ~ 2026-04-24 (PostgreSQL `minute_candles`, 기존 cache 재사용)
- **일봉**: 2025-01-01 ~ 2026-04-24 (`daily_candles`, MACD warm-up 충분)
- **Universe**: `backtests/reports/universe_cache/top30_20250301_20260228_min120.json` — Stage 2 와 동일 (재산출 금지, 일관성 보장)

### 2.2 평가 매트릭스 — 모든 cell 을 4 dataset 에서 평가

| Dataset | 기간 | 출처 |
|---------|------|------|
| Fold 1 test | 2025-09-01 ~ 2025-10-31 | `backtests/multiverse/fold.py:stage2_folds` |
| Fold 2 test | 2025-11-01 ~ 2025-12-31 | 동일 |
| Fold 3 test | 2026-01-01 ~ 2026-02-28 | 동일 |
| OOS hold-out | 2026-03-01 ~ 2026-04-24 | Stage 2 OOS 와 동일 |

### 2.3 KPI (cell × dataset 별 기록)
- `calmar` — 연환산 = (return × 252 / 영업일수) / |MDD|
- `return` — 종료시점 누적 net pnl / VIRTUAL_CAPITAL (10,000,000)
- `mdd` — 일별 누적 net pnl 곡선의 최대 낙폭 / VIRTUAL_CAPITAL
- `trades` — 거래 건수
- `win_rate` — count(pnl > 0) / count(trade)
- `top1_share` — sum(top1 positive trade pnl) / sum(all trade pnl)
- `max_consec_loss` — 시간순 trade 시퀀스 음pnl 연속 최댓값
- `monthly_trades` — trades × (21 / 영업일수). 21 = 월 평균 영업일.
- `exit_reason_dist` (MV-B 만) — {hold_limit, sl, tp, macd_reversal} 비율

### 2.4 슬리피지·수수료
Stage 2 와 동일 — `backtests/common/engine.py` 의 기본값 그대로 사용 (별도 sweep 없음).

## 3. MV-A: 파라미터 Robustness Fine Grid

### 3.1 그리드

| 축 | 값 | best |
|----|----|------|
| `fast_period` | {8, 10, 12, 14, 16} | 14 |
| `slow_period` | {24, 28, 32, 34, 36, 40} | 34 |
| `signal_period` | {9, 10, 11, 12} | 12 |
| `entry_hhmm_min` | {1430, 1440, 1450} | 1430 |

5 × 6 × 4 × 3 = **360 cell × 4 dataset = 1,440 evaluation**.
필터: `slow_period > fast_period` 위반 cell 제외 (예: fast=16/slow=16 등 — 본 그리드에선 미발생이지만 향후 확장 대비 가드 적용).

### 3.2 고정값
- `hold_days` = 2
- `entry_hhmm_max` = 1500
- `budget_ratio` = 0.20 (종목당 200만원)
- `MAX_DAILY_POSITIONS` = 5
- exit overlay 없음 (시간청산만)

### 3.3 산출물
- `backtests/reports/macd_cross_mv/param_grid/cells.csv`
  - long-format: `fast,slow,signal,entry,dataset,calmar,return,mdd,trades,win_rate,top1_share,max_consec_loss,monthly_trades`
- `backtests/reports/macd_cross_mv/param_grid/heatmaps/`
  - 6장 PNG: 축 페어별 heatmap. cell 값 = 나머지 2축 marginalize 한 **평균 Calmar** (median 도 summary.md 표에 병기 — outlier robustness 비교)
  - 파일: `fast_slow.png`, `fast_signal.png`, `fast_entry.png`, `slow_signal.png`, `slow_entry.png`, `signal_entry.png`
  - 각 PNG 는 3 subplot: (a) 4 dataset 평균, (b) Fold 2 단독, (c) OOS 단독 — fold-별 패턴 차이 시각화
- `backtests/reports/macd_cross_mv/param_grid/summary.md`
  - best cell 주변 plateau 폭 (Calmar > 30 인 인접 cell 개수)
  - edge 검증 (best 가 grid 경계에 있는지)
  - fragility 분포 (top1_share > 60% 인 cell 비율)
  - Fold 2 fail 의 grid-wide 패턴 (대부분 cell 에서 fail 인지 best 부근만 fail 인지)

### 3.4 핵심 질문
1. Stage 2 best (fast=14, slow=34, signal=12, entry=1430) 가 **plateau 위인가 절벽 위인가**
2. Fold 2 fail 이 **best 주변 모든 cell 에서 발생하는가** — 기간 의존 vs 파라미터 sensitivity 분리
3. fragility (top1_share > 60%) 가 best cell 만의 문제인가 grid 전반 문제인가

## 4. MV-B: Exit / Defense Overlay

### 4.1 그리드 (3축 joint, 24 cell)

| 축 | 값 |
|----|----|
| `stop_loss_pct` | {off, 3%, 5%, 7%} |
| `take_profit_pct` | {off, 5%, 10%} |
| `intraday_macd_reversal_exit` | {off, on} |

4 × 3 × 2 = **24 cell × 4 dataset = 96 evaluation**.
[off, off, off] = baseline = 현재 라이브 = MV-A best cell 동일.

### 4.2 파라미터 고정
MV-A best 결과와 무관하게 **Stage 2 best 고정**: fast=14, slow=34, signal=12, entry_hhmm_min=1430, hold_days=2. (MV-A 와 직교성 유지)

### 4.3 Overlay 시맨틱 (정확한 정의 — 재현성)
모든 overlay 는 `hold_days` 시간청산보다 **우선** (= 더 빨리 발동 시 그쪽이 청산).

- **stop_loss_pct (SL)**: 보유 중 분봉 `low ≤ entry_price × (1 - sl_pct)` 도달 시 ExitOrder(reason="sl") 발동. 실제 fill 가격은 엔진의 `next_fill_index(t)` next-bar open + 슬리피지 (`backtests/common/engine.py` 컨벤션, 기존 hold_limit 와 동일).
- **take_profit_pct (TP)**: 보유 중 분봉 `high ≥ entry_price × (1 + tp_pct)` 도달 시 ExitOrder(reason="tp") 발동. fill 컨벤션 SL 동일.
- **SL/TP 동시 충족** (한 분봉 안에서 low/high 둘 다 트리거): **SL 우선** (보수적). 실거래는 어떤 게 먼저 찍혔는지 알 수 없으므로 worst-case 가정.
- **intraday_macd_reversal_exit**: 보유 시작 **다음 영업일부터** EOD 시점 (15:00 직전 마지막 분봉) 에 그날 daily hist 재계산. `hist < 0` 이면 그 분봉 종가로 청산. `reason="macd_reversal"`. (보유 시작 당일은 partial daily 로 hist 가 불안정하므로 평가 제외 — D+1 부터만 evaluate)
- 어느 것도 미발동 시 hold_days=2 시간청산. `reason="hold_limit"`.

### 4.4 구현 방식
`MACDCrossStrategy` 본체 미수정 (라이브 동등성 보호). **상속 wrapper 신규 작성**:
```
backtests/strategies/macd_cross_exit_overlay.py
  class MACDCrossExitOverlayStrategy(MACDCrossStrategy):
      def __init__(self, sl_pct=None, tp_pct=None, intraday_reversal=False, **kwargs)
      def prepare_features(...)  # OHLC + per-bar daily hist 캐싱 추가
      def exit_signal(...)        # SL/TP/reversal 우선 평가 후 super().exit_signal()
```

엔진 `Position` 객체에 `entry_price` 가 있는지 확인 — 없으면 wrapper 내부 dict 로 추적.

### 4.5 산출물
- `backtests/reports/macd_cross_mv/exit_overlay/cells.csv` — cell × dataset KPI + exit_reason 분포
- `backtests/reports/macd_cross_mv/exit_overlay/heatmaps/`
  - 8장 PNG: SL × TP heatmap × { reversal off, reversal on } × { Calmar, return, MDD, win_rate }
- `backtests/reports/macd_cross_mv/exit_overlay/summary.md`
  - baseline ([off,off,off]) 대비 best overlay cell 의 KPI delta
  - 청산 reason 분포 변화
  - Fold 2 (실패 fold) 에서 overlay 가 MDD 를 줄여주는 cell 이 있는지

### 4.6 핵심 질문
1. baseline 대비 **최소 한 cell 이라도 Calmar/return 개선되는가** — 도입 가치 1차 판정
2. Fold 2 에서 **MDD 가 줄어드는 cell 이 있는가** — 하방 보호 효과
3. 개선 cell 이 있다면 그 영역이 **plateau 인가 단일점 (cherry-pick) 인가**

## 5. 코드 배치 및 실행

### 5.1 신규 파일
```
backtests/
  strategies/
    macd_cross_exit_overlay.py       # MV-B 용 wrapper
  multiverse/
    macd_cross_mv_common.py          # 4 dataset 로드, KPI 계산, CSV writer 공통
    macd_cross_param_grid.py         # MV-A 러너
    macd_cross_exit_overlay_mv.py    # MV-B 러너
    plot_macd_cross_mv.py            # heatmap PNG + summary.md 생성기
```

### 5.2 기존 재사용
- `backtests/multiverse/fold.py:stage2_folds` — fold 정의
- `backtests/common/data_loader.py:load_minute_df, load_daily_df`
- `backtests/common/engine.py` — 시뮬 엔진
- `backtests/reports/universe_cache/top30_20250301_20260228_min120.json`

### 5.3 실행 순서
1. **데이터 1회 로드** (`macd_cross_mv_common.py:load_all_datasets()`): minute + daily + universe → 메모리 dict, 두 멀티버스 공유
2. **MV-A 실행** → `param_grid/cells.csv`
3. **MV-B 실행** → `exit_overlay/cells.csv`
4. **plot_macd_cross_mv.py** → 양쪽 heatmap + summary.md
5. **git commit** — 코드 + report

### 5.4 런타임 예상
- Stage 2 reference: 3,000 evaluation × 3-fold WF, ~1~2 시간 (Optuna parallel)
- 본 작업: 1,440 + 96 = 1,536 evaluation. 동일 인프라 + 4 worker 병렬 → **30~50분** 추정. 데이터 로드 5~10분.

## 6. 리스크 및 결정 보류 항목

### 6.1 구현 리스크
- **분봉 OHLC 접근**: `MACDCrossStrategy.exit_signal` 시그니처에 분봉 high/low 가 안 들어올 수 있음. wrapper `prepare_features` 에서 OHLC 캐싱하여 `bar_idx` 로 lookup. 엔진 코드 일독 후 결정.
- **`Position.entry_price`**: 엔진 Position 객체에 entry_price 가 있는지 확인. 없으면 wrapper 내부 `dict[stock_code] = entry_price` 로 추적.
- **intraday daily hist 재계산 비용**: 매일 EOD 마다 daily hist 를 다시 계산하면 비쌈. → daily 시리즈는 fold 시작 전 1회 계산 후 trade_date 별 lookup map 으로 캐싱.

### 6.2 본 spec 범위 밖 (후속 작업)
- trailing stop 멀티버스 (cell 폭발로 보류)
- universe N 변량 (top30 외 — Stage 2 일관성 우선)
- hold_days 변량 (별도 멀티버스로 후속)
- 발견된 좋은 overlay 의 페이퍼/OOS 재현 검증
- Fold 2 fail 종목/날짜 단위 trade-level forensic (oos_trades_analyze 패턴)

### 6.3 KPI 정의 일관성
top1_share, MDD, Calmar 모두 PHASE6 OOS 측정과 **동일 정의** 사용 (위 §2.3). 비교 가능성 보장.

## 7. 승인 게이트 (본 spec 종료 시점)

본 spec 자체는 "결과 도출" 이 목적이라 별도 승격 게이트 없음. 다만 결과 해석 시 다음을 명시적으로 답변해야 함:

1. **MV-A**: best 가 plateau 위인가? Fold 2 fail 이 grid-wide 인가 spot 인가?
2. **MV-B**: baseline 개선 cell 이 존재하는가? plateau 인가?
3. **결론**: 라이브 운영 변경 권고 사항 (있으면 별도 변경 spec 으로, 없으면 "현재 운영 유지" 명시)
