# macd_cross 라이브 통합 설계 (페이퍼 우선)

작성일: 2026-04-26
관련 산출물:
- `backtests/strategies/macd_cross.py` (백테스트 구현)
- `backtests/reports/stage2/macd_cross_best.json` (Trial best params)
- `backtests/reports/stage2/PHASE6_DECISION.md` (선정 근거 + 4-pillar audit)
- `docs/superpowers/specs/2026-04-24-short-term-strategy-survey-design.md` (서베이 spec)

## 1. 배경

Phase 3 Stage 2 (1000 trials × 3-fold WF) + OOS 검증을 통과한 유일 전략이 `macd_cross`. OOS 메트릭은 Calmar 54.16 / +11.66% / MDD 1.99% / 36 trades / 승률 61.1%, 열화 ratio 0.62. 4-pillar audit 결과 데이터 무결성·일반화·universe 안정성 통과, 단 거래 분포 fragility (top1=56.8%, top5=100.8%) ⚠️ 잔존.

`weighted_score` (Trial 837) 가 2026-04-23 부터 라이브 운영 중이라 직접 실거래 투입은 위험. PHASE6_DECISION.md 권고에 따라 **2-4주 페이퍼 트레이딩 후 승격** 경로를 채택.

## 2. 핵심 결정 (인터뷰 결과)

| 항목 | 결정 | 근거 |
|------|------|------|
| 운영 모델 | **D — 페이퍼 우선** | weighted_score 라이브 보호 + macd_cross OOS 재현성·fragility 검증 우선 |
| 자금 사이즈 | **F1 — 가상 자본 1천만원** + budget_ratio=0.20 (=200만/포지션) + MAX_POSITIONS=5 | 백테스트 사이징 그대로 → OOS 와 직접 비교 가능 |
| 위험 오버레이 | **G1 — 백테스트 100% 재현** (SL/TP 없음, 서킷브레이커·성과 게이트 미적용, hold_days=2 시간청산만) | 라이브 필터 inherit 시 검증 대상이 "원전략 + overlay" 로 바뀌어 OOS 재현 여부 판정 불가. 페이퍼는 가상매매라 실손실 0이라 안전망 한계효용 낮음 |
| 페이퍼 기간 | **T2 — 4주 또는 30 trades 도달 시 (먼저 충족)** | OOS 표본 (40일 36 trades) 동등 표본 확보 |

## 3. 승격 게이트 (페이퍼 종료 시 모두 충족 시 라이브 단계 결정 회의 진입)

KPI 정의:
- **return** = 누적 trade net pnl / VIRTUAL_CAPITAL (1천만원). 종료 시점 기준.
- **Calmar** = (return × (252 / paper 영업일수)) / |MDD|. 연환산.
- **MDD** = 일별 누적 net pnl 곡선의 최대 낙폭 / VIRTUAL_CAPITAL.
- **승률** = `count(trade_pnl > 0) / count(trade)`.
- **top1 share** = `sum(top1 positive trade pnl) / sum(all trade pnl)` — 분모는 net (서명 합). PHASE6 OOS 측정과 동일 정의 (top5=100.8% 가능 이유).
- **max consecutive losses** = 시간순 trade 시퀀스에서 음의 pnl 연속 카운트의 최댓값.

게이트:
1. paper Calmar ≥ 30 (OOS 54.16 의 ~55%)
2. paper return ≥ 0
3. paper MDD ≤ 5% (OOS 1.99% × 2.5)
4. paper 승률 ≥ 50% (OOS 61.1% 의 하한)
5. top1 trade P&L 점유율 ≤ 60% (OOS 56.8% + 마진. 초과 시 fragility 경보)
6. max consecutive losses ≤ 4 (PHASE6 권고 "3 이상 시 일시 정지" 보다 한 칸 완화)

**중도 안전 정지 (paper 도 즉시 중단)**:
- 누적 가상손실 ≥ -5% 도달
- 연속 손실 ≥ 5건

게이트 6개 통과 시점에 별도 자금 배분 결정 (단일 전환 / 동시 운영 - 자금 분리 / 동시 운영 - 자금 공유) 회의. 본 설계서 범위 밖.

## 4. 아키텍처 변경

### 4.1 dual-strategy dispatch 도입

현재 `StrategySettings.ACTIVE_STRATEGY` 단일 변수 + 분기 (`if ACTIVE_STRATEGY == 'weighted_score' / 'closing_trade'` 형태가 main.py·trading_decision_engine 곳곳에 산재). 페이퍼 단계는 **두 전략이 동시 살아있는 상태**라 단일 변수로 표현 불가능.

도입:
```python
class StrategySettings:
    ACTIVE_STRATEGY = 'weighted_score'        # 실거래용 primary (live)
    PAPER_STRATEGY = 'macd_cross'             # 페이퍼 secondary (virtual). None 이면 비활성

    class MacdCross:
        # 백테스트 best params (Stage 2)
        FAST_PERIOD = 14
        SLOW_PERIOD = 34
        SIGNAL_PERIOD = 12
        ENTRY_HHMM_MIN = 1430
        ENTRY_HHMM_MAX = 1500
        HOLD_DAYS = 2

        # 페이퍼 운영 파라미터 (F1)
        VIRTUAL_CAPITAL = 10_000_000          # 가상 자본 1천만원 (P&L 보고 기준)
        BUY_BUDGET_RATIO = 0.20               # 종목당 200만원
        MAX_DAILY_POSITIONS = 5

        # Universe
        UNIVERSE_TOP_N = 30                   # 거래대금 상위 30 (백테스트와 동일)

        # G1: SL/TP/CB 미적용. 시간 청산만.
        APPLY_LIVE_OVERLAY = False            # 향후 승격 시 True 로 전환 검토
```

매수 분기 로직:
```python
# main._analyze_buy_decision 내부
if PAPER_STRATEGY and signal_from(macd_cross):
    # 무조건 가상매매 라우팅 (G1: 라이브 필터 무시)
    await execute_virtual_buy(..., strategy='macd_cross')
elif ACTIVE_STRATEGY == 'weighted_score' and signal_from(weighted_score):
    # 기존 분기 그대로 (서킷브레이커·게이트·SL 적용)
    await execute_real_buy_or_virtual(...)
```

`is_virtual` 판정도 strategy 인자에 따라 분기 (현재 `weighted_score + VIRTUAL_ONLY=True` 하드코딩 → strategy-aware 로 일반화).

### 4.2 macd_cross 라이브 어댑터

`core/strategies/macd_cross_strategy.py` 신규 작성. 백테스트 `MACDCrossStrategy` 와 동일한 시그널 로직을 라이브 분봉 피드 위에서 실행:

- 매일 장 시작 전 (08:55) 거래대금 상위 30 universe 선정 → `intraday_manager` 등록
- daily MACD histogram 계산: 전일까지 종가 시퀀스 → 14/34/12 EMA → hist, prev_hist (shift1), prev_prev_hist (shift2). 매일 1회.
- 14:30~15:00 매 1분봉 마감 시점에 `prev_prev_hist < 0 and prev_hist >= 0` 골든크로스 판정 → 시그널
- 동일 종목 1일 1회 진입, MAX_DAILY_POSITIONS=5
- 청산: 진입 후 거래일 2일 경과 → hold_limit. SL/TP 없음. 14:30+ 진입이라 entry day 청산 없음.

`backtests/strategies/macd_cross.py` 와 시그널 식이 1:1 동일해야 함 (재사용 vs 별도 구현 — §4.4).

### 4.3 universe 공급 파이프라인

weighted_score 의 top300 + research universe 와 별도로 macd_cross 전용 top30 universe 가 필요.

`stock_screener.preload_macd_cross_universe(top_n=30)`:
- 전일 거래대금 상위 N (`daily_candles` 기반)
- weighted_score 의 research universe 교집합 **불필요** (백테스트는 거래대금만 기준)
- 결과를 `intraday_manager` 등록 → 14:30+ 분봉 수집 보장

`main.py` `_pre_market_task` 에 신규 단계 추가 (08:55 무렵, weighted_score universe 등록과 별도):
```python
if PAPER_STRATEGY == 'macd_cross':
    await self._prepare_macd_cross_universe(current_time)
```

universe 30종목 중 일부가 weighted_score universe 와 겹치는 경우는 **중복 등록 무시** (`intraday_manager` 가 이미 같은 코드를 가지고 있으면 등록 skip).

### 4.4 시그널 코드 재사용 vs 분리

백테스트 `backtests/strategies/macd_cross.py` 의 시그널 식과 라이브 시그널 식이 1픽셀 다르면 OOS 재현 검증 불가. 두 가지 옵션:

**a. 공유 모듈로 분리 (추천)**: `core/strategies/macd_cross_signal.py` 에 순수 시그널 함수 (`compute_macd_signal(df_daily, fast, slow, signal) -> bool`). 백테스트와 라이브 모두 이 함수 호출.

**b. 라이브에서 백테스트 패키지 직접 import**: 라이브 코드가 `backtests/` 모듈에 의존. 패키지 경계 깨짐.

옵션 a 채택. 마이그레이션: 기존 `backtests/strategies/macd_cross.py::_build_macd_maps` 를 신규 공유 함수로 이전, 백테스트는 wrapper.

### 4.5 가상매매 P&L 트래킹

`core/virtual_trading_manager.py` 에 strategy 태그 추가:
- `execute_virtual_buy(..., strategy='macd_cross')` → DB 기록 시 `virtual_trading_records.strategy` 컬럼에 저장
- 일일 EOD 후 strategy별 집계 (return, MDD, win_rate, top1 share, max consec losses) → 텔레그램 일일 보고
- 가상 자본 1천만원을 시드로 cumulative P&L 계산

`virtual_trading_records` 스키마에 `strategy` 컬럼 없으면 추가 (TEXT, default `'weighted_score'`). 마이그레이션 SQL 별도.

## 5. EOD / 서킷브레이커 / 기존 라이브 안전망과의 상호작용

페이퍼 단계는 G1 (라이브 필터 미적용) 이므로 **macd_cross 의 진입·청산은 weighted_score 의 안전망에 영향받지 않음**:

- 전일 -3% 서킷브레이커 발동 시 → weighted_score 매수 0건. macd_cross 는 시그널 발생 시 그대로 가상 진입.
- 14:30+ KOSPI 갭업 컷 → macd_cross 는 14:30+ 진입이라 09:01 갭업 검사와 무관.
- 장중 동적 SL → weighted_score 만 적용. macd_cross 는 SL 자체가 없음.
- 성과 게이트 (롤링 승률 < 40%) → weighted_score 만 적용.
- EOD 15:00 강제 청산 → **macd_cross 의 가상 포지션은 hold_days=2 만료 전까지 보유 유지** (overnight 가상 보유). 이를 위해 `_execute_end_of_day_liquidation` 에 strategy-aware 분기 추가 필요.

라이브 안전망과 macd_cross 페이퍼의 격리 원칙: **시그널 → 가상 매수**, **시간 만료 → 가상 매도**. 그 사이에 어떤 라이브 이벤트도 가상 포지션을 건드리지 않음.

## 6. 모니터링 / 보고

매일 EOD 후 자동 실행 (post_market_data_saver 단계):
- macd_cross 가상 trade 기록 → DB
- 누적 KPI 계산 + 텔레그램 1회 알림:
  - 진행 일수 / 누적 trade 수 (목표 4주·30건 진행률)
  - 누적 return%, 누적 MDD%, 승률
  - top1 / top5 trade P&L 점유율
  - max consecutive losses
  - 6개 게이트 충족 여부
  - 중도 안전정지 조건 충족 여부 → 충족 시 `PAPER_STRATEGY = None` 자동 비활성 권고 (수동 확정)

추가: 매주 일요일 누적 weekly summary (CSV + 텔레그램).

## 7. 산출물

신규/변경 파일:
- `config/strategy_settings.py` — `MacdCross` 클래스 + `PAPER_STRATEGY` 추가
- `core/strategies/macd_cross_signal.py` (신규) — 공유 시그널 함수
- `core/strategies/macd_cross_strategy.py` (신규) — 라이브 어댑터
- `backtests/strategies/macd_cross.py` — 공유 함수 호출로 변경
- `core/stock_screener.py` — `preload_macd_cross_universe()` 추가
- `main.py` — `_prepare_macd_cross_universe`, dual-dispatch 매수 분기, EOD 분기
- `core/trading_decision_engine.py` — `is_virtual` strategy-aware 일반화, `execute_virtual_buy` strategy 인자
- `core/virtual_trading_manager.py` — strategy 태그 + KPI 집계
- `db/database_manager.py` — `virtual_trading_records.strategy` 컬럼 + 마이그레이션
- `core/post_market_data_saver.py` — daily KPI 보고 단계 추가

테스트:
- `tests/strategies/test_macd_cross_signal_parity.py` — 백테스트와 라이브 시그널 식 1:1 동등성 (랜덤 daily 시퀀스 100개)
- `tests/integration/test_macd_cross_paper_flow.py` — universe 등록 → 14:30 시그널 → 가상 매수 → 2일 후 가상 매도 → DB 기록 확인 (mock 분봉 시퀀스)

## 8. 미결정 / 후속 결정

다음 항목은 페이퍼 진행 중 데이터로 결정:

| 결정 | 시점 | 입력 |
|------|------|------|
| 라이브 승격 시 자금 모델 (A/B/C) | paper 종료 (4주 또는 30건) | paper 6 게이트 통과 + fragility 분포 |
| 라이브 SL 적용 여부 | 승격 결정 시 | paper outlier 분포 + max single-trade loss |
| 서킷브레이커 inherit 여부 | 승격 결정 시 | paper 기간 동안 CB 발동일과 macd_cross trade outcome 사후 비교 |
| weighted_score 와의 종목 중복 처리 | 승격 시 (자금 모델 동시 결정) | 두 universe 의 실제 겹침 빈도 |
| Phase 4 (Data-driven 발굴 그리드 스윕) 진행 여부 | macd_cross 승격 또는 폐기 결정 후 | macd_cross 단독으로 충분한지 |

## 9. 자체 검토

- placeholder 없음
- 내부 일관성: G1 결정 → §5 EOD overnight 가상 보유 명시. §3 게이트 임계값 → §6 모니터링 KPI 와 1:1 매칭
- 범위: 페이퍼 단계까지만. 승격 단계는 §8 후속 결정으로 명시 분리
- 모호성: §4.5 의 `virtual_trading_records.strategy` 컬럼 마이그레이션은 별도 SQL 산출 필요 — §7 산출물에 명시
