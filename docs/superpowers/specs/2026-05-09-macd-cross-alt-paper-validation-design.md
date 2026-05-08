# macd_cross_alt (16/32) 페이퍼 검증 설계

작성일: 2026-05-09
관련 산출물:
- `backtests/reports/macd_cross_mv/param_grid/summary.md` (MV-A 멀티버스 결과)
- `backtests/reports/macd_cross_mv/param_grid/cells.csv`
- `docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md` (MV 설계서)
- `docs/superpowers/specs/2026-04-26-macd-cross-live-integration-design.md` (기존 paper 통합 설계 — 본 spec 의 패턴 baseline)

## 1. 배경

MV-A 멀티버스 (360 cell × 4 dataset = 1,440 evaluation, 2026-05-08 commit `133828c3`) 결과:

- 현재 라이브 파라미터 `fast=14, slow=34, signal=12, entry_hhmm_min=1431` 의 4ds-avg Calmar = 65.44 (23/360 위, top 6%, plateau robust)
- **글로벌 best**: `fast=16, slow=32, signal=12, entry_hhmm_min=1430` → 4ds-avg Calmar = **127.69** (현 라이브 대비 +95%)
- 인접 36 cell (best ±1 step) 86% 가 calmar > 30 → 단일 cherry-pick 아님
- Fragility (top1>0.6) 측면에서도 16/32 영역이 14/34 보다 낮음

backtest 우월성은 강하지만 **단일 OOS fold (39 trading days)** 만으로는 라이브 즉시 swap 결정에 부족. 기존 macd_cross paper 통합 (2026-04-26) 와 동일 패턴으로 **4주 / 30 trades paper 검증** 후 승격 결정.

라이브 14/34 가 현재 실거래 운영 중 (2026-04-27~) 이라 paper 16/32 는 **alongside 가상매매** 로 띄움 — 라이브 수익 손실 없이 검증 가능.

## 2. 핵심 결정 (인터뷰 결과)

| 항목 | 결정 | 근거 |
|------|------|------|
| 공존 모델 | **나란히 운영** — 라이브 14/34 (실거래) 유지 + paper 16/32 (가상) | 4주간 라이브 수익 손실 없이 검증 |
| 구현 접근 | **별도 파라미터 클래스** (`MacdCrossAlt`) | 라이브와 paper 완전 격리, 회귀 위험 0, 기존 dual-strategy dispatch 패턴 일관성 |
| 페이퍼 기간 | **4주 또는 30 trades 도달 시 (먼저 충족)** — 기존 macd_cross paper 동일 | OOS fold (39 days) 동등 표본 확보 |
| 승격 게이트 | 6 KPI 게이트 — 기존 macd_cross paper 동일 | 일관성 유지, 새 임계값 도입은 추가 검증 부담 |
| 승격 시 액션 | **In-place swap** — `MacdCross` 클래스 값 16/32 로 일괄 교체, `MacdCrossAlt` + `PAPER_STRATEGY` 삭제 | 단일 전략 운영 일관성 |
| 위험 오버레이 | **G1 — 백테스트 100% 재현** (SL/TP 없음, 라이브 필터 미적용, hold_days=2 시간청산만) | MV-A 결과의 OOS 재현성 검증이 목적, overlay 도입 시 평가 대상 흐림 |

## 3. 승격 게이트 (paper 종료 시 모두 충족 시 회의 진입)

기존 macd_cross paper 와 동일:

1. paper Calmar ≥ 30
2. paper return ≥ 0
3. paper MDD ≤ 5%
4. paper 승률 ≥ 50%
5. top1 trade P&L 점유율 ≤ 60%
6. max consecutive losses ≤ 4

**중도 안전 정지** (paper 즉시 중단):
- 누적 가상손실 ≥ -5%
- 연속 손실 ≥ 5건

게이트 통과 시 액션:

| 결과 | 액션 |
|------|------|
| 6/6 통과 | swap PR — `MacdCross.FAST_PERIOD = 16, SLOW_PERIOD = 32` 일괄 교체. `MacdCrossAlt` + `PAPER_STRATEGY` 삭제. paper KPI / virtual records 보존 (사후 분석용) |
| 5/6 통과 | 사람 검토 — 미통과 KPI 가 critical 인지 판단. 추가 4주 paper 또는 revert |
| 4 이하 통과 | revert — `MacdCrossAlt` 비활성, paper 결과 archive. MV-A top cell list 의 다른 후보 (예: 14/36 calmar=97) 후속 검토 |
| 중도 안전정지 발동 | `PAPER_STRATEGY=None` 자동 정지, 사람 검토 |

## 4. 아키텍처 변경

### 4.1 신규 파라미터 클래스

`config/strategy_settings.py` 에 `MacdCross` 옆에 `MacdCrossAlt` 신설. 기존 `MacdCross` 는 일절 수정 없음.

```python
class StrategySettings:
    ACTIVE_STRATEGY = 'macd_cross'                 # 실거래 14/34 그대로
    PAPER_STRATEGY = 'macd_cross_alt'              # 신규 paper key

    class MacdCross:                               # 라이브 (변경 없음)
        FAST_PERIOD = 14
        SLOW_PERIOD = 34
        SIGNAL_PERIOD = 12
        ENTRY_HHMM_MIN = 1431
        ENTRY_HHMM_MAX = 1500
        HOLD_DAYS = 2
        VIRTUAL_CAPITAL = 10_000_000
        BUY_BUDGET_RATIO = 0.20
        MAX_DAILY_POSITIONS = 5
        UNIVERSE_TOP_N = 30
        APPLY_LIVE_OVERLAY = False
        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]
        VIRTUAL_ONLY = False                       # 실거래

    class MacdCrossAlt:                            # 신규 paper-only
        """16/32 paper 검증 (MV-A best). docs/superpowers/specs/2026-05-09-macd-cross-alt-paper-validation-design.md."""
        FAST_PERIOD = 16
        SLOW_PERIOD = 32
        SIGNAL_PERIOD = 12
        ENTRY_HHMM_MIN = 1431                      # 라이브와 동일 (next_bar_open 정렬)
        ENTRY_HHMM_MAX = 1500
        HOLD_DAYS = 2
        VIRTUAL_CAPITAL = 10_000_000
        BUY_BUDGET_RATIO = 0.20
        MAX_DAILY_POSITIONS = 5
        UNIVERSE_TOP_N = 30                        # 라이브와 동일 universe 공유
        APPLY_LIVE_OVERLAY = False
        ALLOWED_WEEKDAYS = [0, 1, 2, 3, 4]
        VIRTUAL_ONLY = True                        # paper 는 항상 가상

    # validate_settings 에 macd_cross_alt 동일 가드 추가
```

### 4.2 Dispatch 분기 추가

main.py 의 5개 분기에 `PAPER_STRATEGY=='macd_cross_alt'` 케이스 추가:

| 위치 | 변경 |
|------|------|
| `__init__` (universe preload) | universe top 30 은 **단일 preload 결과를 두 인스턴스가 공유** (KIS API 중복 호출 방지). `MacdCrossAlt.UNIVERSE_TOP_N` 와 `MacdCross.UNIVERSE_TOP_N` 가 동일 (30) 한지 `validate_settings` 에서 강제 |
| `__init__` (FundManager) | paper 인스턴스용 `VirtualFundManager(MacdCrossAlt.VIRTUAL_CAPITAL)` 추가 |
| `_evaluate_macd_cross_window` | 두 인스턴스 (`MacdCrossStrategy(cfg=MacdCross)` / `MacdCrossStrategy(cfg=MacdCrossAlt)`) 각각 시그널 평가 → 라우팅 |
| `_macd_cross_exit_dispatcher` | 보유 포지션 분기 — strategy_label 로 라이브/paper 구분 후 각각 청산 |
| 텔레그램 EOD 보고 | 두 KPI 인스턴스 출력 (label='macd_cross' real / label='macd_cross_alt' paper) |

### 4.3 MacdCrossStrategy 인스턴스화 변경

현재 `core/strategies/macd_cross_strategy.py` 의 `MacdCrossStrategy.__init__` 가 `StrategySettings.MacdCross` 를 하드코딩으로 import. **변경**: 생성자가 cfg 클래스를 인자로 받도록.

```python
class MacdCrossStrategy:
    def __init__(self, cfg=None, label='macd_cross'):
        self.cfg = cfg or StrategySettings.MacdCross
        self.label = label                       # KPI / 로깅용
        self.fast = self.cfg.FAST_PERIOD
        ...
```

main.py 에서:
```python
self.live_macd = MacdCrossStrategy(cfg=StrategySettings.MacdCross,    label='macd_cross')
self.paper_macd = MacdCrossStrategy(cfg=StrategySettings.MacdCrossAlt, label='macd_cross_alt')  # PAPER_STRATEGY 활성화 시만
```

### 4.4 KPI 집계 분리

`core/strategies/macd_cross_kpi.py` 의 `MacdCrossKpi.__init__` 에 `strategy_label` 인자 추가 — DB 쿼리 시 필터로 사용.

| 인스턴스 | 데이터 소스 | 게이트 평가 |
|----------|-------------|-------------|
| `MacdCrossKpi(label='macd_cross')` | `real_trading_records WHERE strategy='macd_cross'` | 라이브 KPI |
| `MacdCrossKpi(label='macd_cross_alt')` | `virtual_trading_records WHERE strategy_label='macd_cross_alt'` | paper 게이트 평가 (4주/30 trades 통과 판정) |

### 4.5 DB 스키마 (변경 없음)

`virtual_trading_records.strategy` 컬럼이 **이미 존재** (기존 `save_virtual_buy/sell` signature 의 `strategy` 인자가 그대로 저장됨). 마이그레이션 불필요.

호출자만 변경:
- 라이브 매수 (실 거래) → `real_trading_records` 별도 테이블 (영향 없음)
- 기존 paper macd_cross → `save_virtual_buy(..., strategy='macd_cross', ...)` (변경 없음)
- 신규 paper macd_cross_alt → `save_virtual_buy(..., strategy='macd_cross_alt', ...)` (호출 인자만 다름)

KPI 쿼리는 `SELECT ... FROM virtual_trading_records WHERE strategy='macd_cross_alt'` 로 분리.

## 5. 데이터 흐름

```
config 로드 (StrategySettings, validate_settings 포함)
  ├─ ACTIVE_STRATEGY='macd_cross'     → MacdCross (14/34)  [실거래]
  └─ PAPER_STRATEGY='macd_cross_alt'  → MacdCrossAlt (16/32) [가상]

main._system_monitoring_task → _evaluate_macd_cross_window
  ├─ live_macd (cfg=MacdCross, label='macd_cross')
  │   → 14:31 시그널 hit → execute_buy (실주문) → real_trading_records (strategy='macd_cross')
  └─ paper_macd (cfg=MacdCrossAlt, label='macd_cross_alt')
      → 14:31 시그널 hit → execute_virtual_buy → virtual_trading_records (strategy_label='macd_cross_alt')

청산 (_macd_cross_exit_dispatcher)
  ├─ 라이브 보유: D+2 morning / EOD → 실주문 시장가 매도
  └─ paper 보유 : 동일 dispatcher 호출, virtual_trading_manager 가 가상 청산

KPI 집계 (일일 EOD 텔레그램 보고)
  ├─ MacdCrossKpi('macd_cross')      → real_trading_records
  └─ MacdCrossKpi('macd_cross_alt')  → virtual_trading_records WHERE strategy_label='macd_cross_alt'

텔레그램 출력:
  [macd_cross] real:  trades=N1, win=W1%, calmar=C1, MDD=M1
  [macd_cross_alt] paper: trades=N2, win=W2%, calmar=C2, MDD=M2
  [Δ] alt vs real: +<diff>%
```

## 6. 격리 보장

| 자원 | 격리 방식 |
|------|-----------|
| 자금 (capital pool) | `FundManager` (real) ↔ `VirtualFundManager` (virtual) — 완전 분리 |
| 포지션 (보유 종목) | real → KIS 계좌 / virtual → in-memory ledger — 충돌 X |
| 종목 한도 | 각 인스턴스 5종목 독립 카운트 |
| KPI 추적 | DB 쿼리 시 `strategy='macd_cross'` (real) vs `strategy_label='macd_cross_alt'` (virtual) 으로 필터 |
| 시그널 평가 | 두 인스턴스가 같은 분봉 데이터를 받지만 MACD 계산 파라미터 다름 → 자연스럽게 다른 시그널 발생 |

**동시 매수 케이스**: 라이브 14/34 hit + paper 16/32 hit 둘 다 14:31 → 라이브 실주문 + paper 가상 buy 동시 기록. 자원 충돌 없음.

## 7. Testing 전략

| 테스트 | 위치 | 검증 |
|--------|------|------|
| Unit: `MacdCrossAlt` 인스턴스화 + signal 계산 | `tests/strategies/test_macd_cross_alt.py` (신규) | fast=16/slow=32 MACD hist 정확성 |
| Parity: backtest signal == live paper signal (16/32) | `tests/strategies/test_macd_cross_alt_signal_parity.py` (신규) | 4-dataset OOS 분봉으로 backtest vs adapter 비교 |
| Integration: paper flow E2E | `tests/integration/test_macd_cross_alt_paper_flow.py` (신규) | 시그널 hit → virtual_buy → D+2 청산 → KPI 집계 풀스택 |
| Regression: 기존 macd_cross 라이브 무영향 | 기존 270+ tests | 14/34 라이브 경로 변경 없음 확인 |
| Manual: 텔레그램 보고 출력 | 운영 첫날 | 두 strategy_label KPI 분리 표시 확인 |

## 8. 롤백 안전망

- `PAPER_STRATEGY=None` 으로 즉시 paper 정지 가능 (기존 인프라 재사용)
- DB `strategy_label` 컬럼은 NOT NULL DEFAULT 'macd_cross' → 신규 컬럼이 기존 레코드와 호환
- `MacdCrossStrategy(cfg=...)` 변경은 기본값을 `StrategySettings.MacdCross` 로 둠 → cfg 인자 미지정 시 기존 동작 그대로

## 9. 범위 밖 (Out of Scope)

- Sub-project B (reversal-only overlay paper) — 별도 spec, A 통과 또는 4주 후 진행
- Sub-project C (fold2 regime filter) — 별도 spec, 병행 진행 가능
- Stage 2 16/32 재훈련 (단일 16/32 cell 의 1000 trial 재 fine-tune) — paper 만으로 부족 시 후속
- Dual-live (14/34 + 16/32 동시 실거래) — paper 통과 후 별도 결정

## 10. 산출물

- 코드: `config/strategy_settings.py` 수정 (MacdCrossAlt 추가), `core/strategies/macd_cross_strategy.py` label 파라미터 추가, `main.py` dispatch 분기 추출 + paper 인스턴스 + 호출 5곳, 텔레그램 EOD dual KPI. KPI/DB 모듈 변경 없음 (기존 `strategy` 컬럼 + DataFrame-driven KPI 재사용).
- 테스트: 신규 3개 (`test_macd_cross_alt.py`, `test_macd_cross_alt_signal_parity.py`, `test_macd_cross_alt_paper_flow.py`)
- 문서: `docs/macd_cross_operation.md` 운영 노트 추가

승격 결정 후 별도 swap PR 로 16/32 라이브 적용 + paper 비활성화.
