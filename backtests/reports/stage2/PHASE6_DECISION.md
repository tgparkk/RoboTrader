# Phase 6 결정 — 실거래 후보 선정 (2026-04-26)

## 결과 요약

**유일한 통과 전략: `macd_cross`**

| 단계 | 지표 |
|------|------|
| Stage 1 (random 200 trials, fold 1) | 128/200 통과 (5/5 게이트), best Calmar 123 |
| Stage 2 (TPE 1000 trials × 3-fold WF) | 754/1000 valid, 3-fold avg Calmar 87.84 |
| OOS (2026-03-01 ~ 04-24, 미관측) | **Calmar 54.16, return +11.66%, MDD 1.99%, 36 trades, 61.1% win** |
| Spec § 9 통과 | OOS Calmar > 5 ✅, 열화 ratio 0.62 (≥ 0.5) ✅ |

**Best params** (macd_cross):
```python
fast_period = 14
slow_period = 34
signal_period = 12
entry_hhmm_min = 1430   # 14:30 ~ 15:00 진입 윈도우
```

진입 조건: 직전 거래일 MACD histogram 음→양 골든크로스 + 14:30~15:00 진입.
청산: hold_days=2 (2 거래일 보유).

**Universe**: 거래대금 상위 30 종목 (KOSPI/KOSDAQ 혼합, Stage 1/2/OOS 동일).

---

## 탈락 전략 분석

OOS 실패 4 전략의 공통 패턴: Stage 2 avg Calmar 26~139 — fold1+fold3 강세에 의해 inflate, fold2 (2025-11~12) 와 OOS (2026-03~04) 처럼 변동성 큰 약세장에서 모두 음수 Calmar 기록.

| 전략 | Stage 2 best | fold2 calmar | OOS calmar | 열화 ratio |
|------|:------------:|:------------:|:----------:|:----------:|
| limit_up_chase | 138.95 | -1.67 | 1.37 | 0.01 |
| trend_followthrough | 126.56 | -4.75 | -4.70 | -0.04 |
| breakout_52w | 100.09 | -4.74 | -5.43 | -0.05 |
| close_to_open | 26.53 | -4.53 | -0.24 | -0.01 |

**해석**: 강화된 게이트 (5/5 + Calmar floor) + 3-fold WF + OOS 가 멀티버스 시뮬 3대 원칙 (look-ahead 금지·자금 제약·현실 마찰) 과 함께 정상 작동. spec § 9 "성공 기준" 의 정확한 식별 — overfit 4 + generalize 1.

---

## 추가 검토 (2026-04-26 paper trading 전 실행)

스크립트 4종으로 macd_cross OOS 결과 신뢰성 검증:

| 항목 | 결과 | 스크립트 | 코멘트 |
|------|:----:|----------|--------|
| (1) Fold2 vs OOS 레짐 | ✅ PASS | `regime_compare.py` | OOS = 고변동성 (연환산 67.9%) + 추세 (slope 41.1bps/일). fold2 (slope 7.5, 변동성 28%, 횡보 약세) 와 다른 레짐 → OOS 통과는 운 아님. 단, **fold2 류 횡보 약세 시장에서 약점 명확 (Stage 2 fold2 Calmar -3.12)**. |
| (2) Look-ahead audit | ✅ PASS | `audit_winning_params.py` | 5 winning 전략 모두 daily 피처 perturbation 검증 통과. shift(1)/shift(2) 정상. |
| (3) Universe selection bias | ✅ PASS | `universe_bias_check.py` | 12mo/6mo/3mo/1mo 4가지 universe 정의 (overlap 70~100%) 모두 OOS Calmar 36~107 + return 10~16%. 종목 선택 무관하게 강건. |
| (4) 거래 분포 | ⚠️ CAUTION | `oos_trades_analyze.py` | 종목 25/30 분산 ✓, 거래일 22 분산 ✓, win 61%/RR 1.79 ✓. **그러나 top1 trade 점유 56.8%, top5 점유 100.8%** → outlier 거래 의존. 큰 winner 안 잡히는 횡보장에서 break-even or loss. |

### 4 검토 종합

- (1)(2)(3) 통과 → 데이터 무결성 + 전략 일반화 입증
- (4) fragility 는 추세 추종 전략의 본성 (winner-takes-most). 통계적 의미 있지만 **모니터링 필수**

## 다음 단계 권장

### 1. macd_cross paper trading 2~4주 (필수)
- 현 weighted_score 라이브 운영 중이므로 직접 실거래 투입 대신 paper trading 으로 검증
- 실거래 시뮬레이션 / 가상매매 로 OOS 결과 재현 여부 확인
- 시뮬-실거래 괴리 (스크리너 차이, 슬리피지, 체결 지연) 측정
- **모니터링 핵심 지표 (4 검토 결과 반영)**:
  - top1 / top5 trade P&L 점유율 (50% / 100% 초과 시 fragility 경보)
  - 누적 P&L 추세 (큰 winner 없이 break-even 횡보 시 횡보장 진입 의심)
  - KOSPI 직전 20일 변동성 + cumret slope (fold2 류 레짐 감지)
  - max consecutive losses (3 이상 시 일시 정지 검토)

### 2. 실거래 투입 시 자금 배분 결정
- weighted_score 와 macd_cross 동시 운영 시 자금 분리 또는 통합 자금 풀 결정
- macd_cross 는 hold=2 overnight (오버나이트 리스크), weighted_score 는 hold=5 — 두 전략의 동시 보유 한도 / 종목 중복 처리 정책 필요

### 3. Phase 4 (Data-driven 발굴) 선택사항
- Spec § 6 의 16,200 그리드 스윕 → 클러스터링 → 신규 전략 3-5 개 발굴
- 시간 비용 ~3-4일. macd_cross 단일 전략이 충분하면 생략 가능.
- 추천: paper trading 결과 확인 후 결정

### 4. 게이트 calibration 재검토 (선택사항)
- 현 aggregate gate 는 fold-별 약세를 가린다는 한계 노출
- "최악 fold Calmar > 0" 또는 "fold-wise 통과율 2/3" 같은 추가 게이트 검토
- 다음 Stage 2 실행 시 파일터 강화로 OOS 통과율 ↑ 기대

---

## 산출물

- `backtests/reports/stage2/<strategy>_trials.csv`: 1000 trials 메트릭
- `backtests/reports/stage2/<strategy>_best.json`: best params + 3-fold detail
- `backtests/reports/stage2/oos_summary.csv`: OOS 검증 결과
- `backtests/reports/stage2/run.log`: Stage 2 실행 로그 (~8.6h)

Optuna study (PostgreSQL `robotrader_optuna` DB):
- `stage2_macd_cross`, `stage2_close_to_open`, `stage2_breakout_52w`, ...

---

## 비교: 기존 weighted_score Trial 837 vs macd_cross

| 메트릭 | weighted_score (Trial 837) | macd_cross (Stage 2 best) |
|--------|:--------------------------:|:-------------------------:|
| Universe | top 300 (research) | top 30 (백테스트) |
| Hold | 5 거래일 | 2 거래일 |
| Test Calmar | 25.10 (88일) | OOS 54.16 (40일) |
| Return | +9.6% | +11.66% |
| MDD | 2.40% | 1.99% |
| Win% | 55.7% | 61.1% |
| Sharpe | 4.10 | (계산 필요) |
| 운영 상태 | LIVE (2026-04-23~) | 신규 후보, paper trading 권장 |

> 직접 비교 주의: Universe 크기 / 기간 / hold 가 다르므로 "동등 조건" 비교 아님. 다만 두 전략 모두 spec § 9 충족.
