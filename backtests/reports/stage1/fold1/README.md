# Stage 1 Coarse Search — Fold 1 결과 (2026-04-25)

**실행 환경**: 30 종목 × 200 trials × 15 strategies × 8 workers, 약 62분 소요
**Fold 1**: train 2025-09-01 ~ 2026-02-29 (6개월), test 2026-03-01 ~ 2026-04-24 (~2개월)
**Universe**: 거래대금 상위 30 (KOSPI/KOSDAQ 혼합) — 005930, 000660, 005380, 034020, 086520, 035420, 042700, 042660, 006400, 012450, 196170, 272210, 006800, 402340, 009150, 108490, 007660, 090710, 015760, 035720, 000720, 064350, 000270, 298380, 001440, 079550, 010170, 010140, 009830, 005490

**게이트** (Spec § 3): overfit_ratio ≥ 0.5, |MDD| ≤ 15%, trades ≥ 30, win% ≥ 35%, monthly trades ≥ 3 (5개 중 3+ 통과 + Calmar ≥ 3.0)

---

## 전략 요약 (best test Calmar 기준 정렬)

| 통과 | 전략 | best_Calmar | best_return | best_trades | 분류 |
|------|------|-------------|-------------|-------------|------|
| 101/200 | limit_up_chase | 26,312.41 | +9.2% | 3 | ⚠️ outlier (low trade count) |
| 102/200 | post_drop_rebound | 24,859.72 | +8.8% | 2 | ⚠️ outlier (low trade count) |
| 128/200 | **macd_cross** | 123.37 | +17.0% | 45 | ✅ Stage 2 candidate |
| 149/200 | **close_to_open** | 42.56 | +19.2% | 143 | ✅ Stage 2 candidate (가장 안정) |
| 194/200 | **breakout_52w** | 40.87 | +13.8% | 23 | ✅ Stage 2 candidate (가장 일관) |
| 144/200 | **trend_followthrough** | 29.14 | +12.7% | 44 | ✅ Stage 2 candidate |
| 3/200 | gap_up_chase | 9.89 | +9.6% | 98 | 🟡 marginal pass |
| 0/200 | gap_down_reversal | 2.83 | +3.0% | 147 | ❌ Calmar floor 미달 |
| 0/200 | closing_drift | 2.60 | +1.9% | 80 | ❌ Calmar floor 미달 (live 운영 closing_trade 와 다른 결과 — universe 차이일 가능성) |
| 0/200 | orb | 2.50 | +2.7% | 68 | ❌ Calmar floor 미달 |
| 0/200 | volume_surge | 0.05 | +0.1% | 347 | ❌ 거의 break-even |
| 0/200 | vwap_bounce | -0.32 | -0.7% | 259 | ❌ 손실 |
| 0/200 | bb_lower_bounce | -1.07 | -93.3% | 7,890 | ❌ 과도한 손실 |
| 0/200 | intraday_pullback | -1.09 | -91.7% | 7,045 | ❌ 과도한 손실 |
| 0/200 | rsi_oversold | -1.22 | -82.0% | 2,977 | ❌ 과도한 손실 |

---

## 핵심 관찰

### Stage 2 진입 후보 (4-6개)

**확실한 통과 (4 전략, 모두 overnight swing)**:
- `close_to_open`: 강한 종가 매수 → 익일 시가 매도. test 143 trades, 35.7% win, MDD 5.2%, overfit_ratio 19 (안정)
- `breakout_52w`: 52주 (또는 lookback) 신고가 돌파 후 2일 홀드. 194/200 통과율 최고, test 23 trades (경계), MDD <5%
- `macd_cross`: 일봉 MACD 골든크로스. 62.2% win, MDD 1.5%, 다만 overfit_ratio 165 — train 과대적합 의심, Stage 2 에서 추가 검증 필요
- `trend_followthrough`: N일 고점 돌파, test 47 trades, 36.4% win, MDD 4.2%

**경계 (1 전략)**:
- `gap_up_chase`: 3/200 trials 만 통과, 임계 직전. Stage 2 포함 vs 탈락 사용자 판단

**Outlier 의심 (2 전략)**:
- `limit_up_chase` / `post_drop_rebound`: best Calmar 26K/24K 이지만 trades=2~3, MDD≈0%. **trades 게이트 (≥30) 가 hard 가 아니라 5중 3 OR 조건이라 통과**. 사실상 우연히 1~2 거래로 소수 익절 → MDD 0 → Calmar 천문학적. 통계적 의미 없음.

### 실패 패턴

**평균회귀 4종 모두 실패** (vwap_bounce, bb_lower_bounce, intraday_pullback, rsi_oversold):
- test_total_return 이 -82% ~ -93% (자본 거의 소실)
- trades 가 2,977 ~ 7,890 (광적 매매)
- 원인 추정: stop loss 가 작은 반등 신호에 너무 자주 발동, 실제 평균회귀 윈도우 보다 빨리 손절. 4월 변동성 큰 시장에서 수익 전 손절 누적.

**Intraday momentum 도 약함**: orb (2.5), volume_surge (0.05), gap_down_reversal (2.8) — Calmar floor 3 직전. 임계 완화 시 (2.5) 진입 가능.

### 다음 단계 옵션

1. **Stage 2 (Fine TPE 1000 trials)** — 확실한 4-6 전략에 대해 Optuna TPE 로 정밀 탐색 + 3-fold walk-forward
   - 시간 예산: 전략당 ~8시간 (200 trials = 8분 추정 → 1000 trials × 3 folds = 30분 × 4 = 2시간 with 8 workers)
2. **게이트 calibration**: trades ≥ 30 을 hard gate 로 변경 → outlier 2 종목 자동 탈락 후 재실행
3. **평균회귀 stop_loss 분석**: 왜 4 strategies 가 모두 실패했는지 trial 데이터 (200 × 4 = 800 trials) 분석
4. **Phase 4 (Data-driven 발굴)**: 16,200 그리드 스윕 → 클러스터링 → 신규 전략 3-5개

---

## 파일

- `<strategy>_trials.csv`: 전략별 200 trials 전체 (params, train/test metrics, gates)
- `summary.csv`: 한눈 요약
- `../run.log`: 실행 로그 (stdout)
- 분석: `python -m backtests.multiverse.analyze_stage1 --fold fold1 --top-k 5`
