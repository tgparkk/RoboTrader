# MV-B exit overlay summary

## Baseline ([off, off, off]) — 4 dataset 평균

| dataset | calmar | return | mdd |
|---------|--------|--------|-----|
| fold1 | 36.43 | 0.1130 | -0.0219 |
| fold2 | -2.80 | -0.0314 | -0.0608 |
| fold3 | 182.46 | 0.1867 | -0.0098 |
| oos | 45.67 | 0.1032 | -0.0194 |

## Top 5 improvers (Calmar delta vs baseline 평균 = 65.44)

| sl | tp | reversal | calmar | Δcalmar | return | win_rate |
|----|----|----------|--------|---------|--------|----------|
| off | off | on | 71.56 | +6.12 | 0.0958 | 0.501 |

## Fold 2 (fail fold) MDD 개선 cell 수

- baseline Fold 2 MDD: -0.0608
- baseline 보다 MDD 좋은 cell: 8 / 24

## 결론 (spec §4.6 핵심 질문 답변)

### Q1. baseline 대비 개선되는 cell 이 최소 한 개라도 있는가? (도입 가치 1차 판정)
**한 개 있음 — `(off, off, reversal=on)`. 그러나 개선 폭은 미미하고 다른 23 cell 은 모두 악화.**
- baseline (off/off/off) 4ds avg: calmar=**65.44**, return=**9.3%**, mdd=-2.8%, win=49.8%
- Top improver: `sl=off, tp=off, reversal=on` → calmar=**71.56 (+6.12)**, return=9.6% (+0.3pp), mdd=-3.0%, win=50.1%
- 나머지 23 cell 전부 calmar 악화. 특히 SL 도입 시 calmar 65 → 8~46 으로 큰 폭 하락.
  - SL 5%: calmar 44 (-21), SL 3%: calmar 41~42 (-23), SL 7%: calmar 39~40 (-26)
  - TP 도 단독·결합 모두 악화 (TP 5%: calmar 18~21, TP 10%: calmar 22~28)
- exit_reason 분포 (top cell): hold_limit ~83%, **macd_reversal 5~13%**, eod_forced 3~12%, sl/tp 0%
- → reversal 만 약한 추가 효과. SL/TP 는 도입 가치 없음.

### Q2. Fold 2 에서 MDD 가 줄어드는 cell 이 있는가? (하방 보호)
**있음 — 8/24 cell.** 다만 **모든 개선 cell 이 fold2 calmar 는 여전히 음수**.
- Fold 2 baseline: calmar=**-2.80**, return=**-3.1%**, mdd=**-6.08%**
- MDD 개선 Top 4 (모두 reversal=on 또는 on/off 혼합):
  | cell | mdd | dmdd | dret | calmar |
  |------|-----|------|------|--------|
  | sl=0.03 / tp=0.05 / rev=on | -5.3% | +0.8pp | +1.1pp | -2.17 |
  | sl=off / tp=0.10 / rev=on  | -5.3% | +0.8pp | +1.9pp | -1.30 |
  | sl=0.07 / tp=0.05 / rev=on | -5.5% | +0.6pp | +1.3pp | -1.90 |
  | sl=0.03 / tp=0.05 / rev=off| -5.6% | +0.5pp | +0.7pp | -2.35 |
- 8 cell 모두 return 도 동시 개선 (dret +0.7~+1.9pp). reversal=on 5/8, TP 7/8 → reversal+TP 콤보가 fold2 손실 일부 줄임
- 그러나 **음의 calmar 자체는 못 뒤집음** → 하방 완화는 가능하지만 fold2 레짐 자체를 극복하진 못함.

### Q3. 개선 영역이 plateau 인가 single-point (cherry-pick) 인가?
**single-point cherry-pick.**
- 4-dataset 평균 calmar 가 baseline (65.44) 보다 좋은 cell: **1/24** (= reversal-only)
- 4-dataset 평균 return 도 동일하게 1/24 만 개선
- baseline 주변에 plateau 가 형성되지 않음 — 인접 cell 들이 모두 악화
- 따라서 reversal-only 도입 시 +6 calmar 의 조심스러운 알파, 그 이상은 over-engineering 위험

### 종합 판정
1. **SL/TP overlay 는 도입 거부** — 4ds avg 기준 일관 악화.
2. **intraday MACD reversal exit 는 단독 도입 검토 가치 있음** — Δcalmar +6, fold2 손실 일부 완화 효과 동시.
3. **fold2 레짐 회피 효과 제한적** — overlay 만으로는 부족, 별도 레짐 필터 또는 거래 중단 정책이 필요.

heatmap PNG 8장 (heatmaps/) 으로 시각 검증 가능.
