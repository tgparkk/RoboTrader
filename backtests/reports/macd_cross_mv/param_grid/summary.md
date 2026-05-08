# MV-A 파라미터 fine grid summary

## Best cell (Stage 2 best: fast=14, slow=34, signal=12, entry=1430)

| dataset | calmar |
|---------|--------|
| fold1 | 36.43 |
| fold2 | -2.80 |
| fold3 | 182.46 |
| oos | 45.67 |

## Plateau 분석 (best ±1 step 주변 cell)

- 인접 cell 수: 36
- Calmar > 30 인 cell: 31 (86%)
- 판정: plateau (robust)

## Fragility (top1_share > 60% cell)

- 69/360 cells (19%)

## Fold 2 fail 분포

- 음 calmar cell 비율: 92% (전체 cell 중 fold2 에서 fail)
- 판정: 기간 의존 (대부분 cell fail)

## 결론 (spec §3.4 핵심 질문 답변)

### Q1. Stage 2 best (14/34/12/1430) 가 plateau 위인가 절벽 위인가?
**plateau 위** (단, 글로벌 최고점은 아님).
- 4-dataset 평균 calmar 65.44 — 360 cell 중 **23위** (top 6%)
- Top 1 cell: fast=16/slow=32/sig=12/entry=1430, calmar=**127.69**
- best ±1 step 인접 36 cell 전수 calmar > 0; 31/36 (86%) > 30; 21/36 (58%) > 50; min=17.12 / median=55.09
- → 인접 영역 전체가 안정적으로 양수, "plateau (robust)" 판정. 다만 Stage 2 가 골랐던 best 는 plateau 의 중심이 아니라 등성이 — fast=16 / slow=32 쪽이 더 좋음.
- **Edge check**: signal_period=12 는 grid 상한 경계, entry_hhmm_min=1430 은 하한 경계. plateau 가 grid 안쪽으로 잘 내려와 있어 경계 의존성은 약함.

### Q2. Fold 2 fail 이 기간 의존인가 파라미터 sensitivity 인가?
**기간 의존 (period-bound).**
- Fold 2 cell 360개 중 calmar<0 : **333개 (92%)**, return<0 : 333개 (92%)
- return mean/median = **-3.4% / -3.7%** → 거의 모든 파라미터가 음수
- 4-dataset 평균 calmar Top 13 cell 도 **13/13 모두 fold2 fail** (mean return -3.3%)
- → 어떤 파라미터로도 fold2 (2025-11~12, MACD 골든크로스 전략 비호환 시장 레짐) 를 회피할 수 없음. 파라미터 튜닝 문제 아님.

### Q3. Fragility (top1_share > 0.6) 가 best cell 만의 문제인가 grid 전반 문제인가?
**부분 문제** — best cell 자체가 fragility 경계에 걸쳐있고, grid 전반의 19% 가 동일 증상.
- 전체 360 cell 중 top1_avg>0.6: **69 cell (19%)**
- best 인접 36 cell 중 top1_avg>0.6: **4 cell (11%)** → 인접 영역은 grid 평균보다 깨끗함
- best cell 자체 dataset별 top1_share: fold1=**0.62**, oos=**0.61**, fold3=0.34, fold2=-0.67 (sum<0)
- → fold1·oos 두 dataset 에서 단일 거래가 이익의 60%+ 차지. cherry-pick 위험 존재. fast=16/slow=32 영역 (top1_avg=-0.20) 으로 이동하면 fragility 가 크게 완화됨.

### 종합 판정
1. **plateau robust** → 라이브 운영을 14/34 영역에 두는 결정은 안전.
2. **fold2 회피 불가** → 별도 레짐 필터 없이는 macd_cross 전략의 구조적 약점.
3. **fast=16/slow=32 로 이동 검토 가치 있음** — 4ds avg calmar +95%, fragility 동시 완화.

heatmap PNG 6장 (heatmaps/) 으로 시각 검증 가능.
