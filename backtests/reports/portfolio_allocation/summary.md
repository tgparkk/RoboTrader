# MV-F portfolio_allocation summary

## Baseline — macd_cross 단독 (corner cell w=(1,0,0))

- 4ds-avg calmar = **65.44**
- fold1=36.43 / fold2=-2.80 / fold3=182.46 / oos=45.67
- fold2 MDD = -0.0608

## Gate 정의

- **G1** portfolio 4ds-avg calmar > baseline (65.44)
- **G2a** fold2 calmar > baseline (-2.80)
- **G2b** fold2 MDD ≥ baseline × 0.95
- **G3** fold1/3/oos 손실율 ≤ 10%
- **G4** w_macd ≥ 0.4 (운영 제약)
- **G5** 4ds-avg MDD ≥ baseline × 0.95
- 판정: PASS (G1+G2a+G2b + 보조 ≥2) / PARTIAL (G1 또는 G2a) / FAIL

## Top 20 by 4ds-avg calmar

|   w_macd |   w_breakout |   w_trend | verdict   |   calmar_4ds |   fold1 |   fold2 |   fold3 |   oos | G1    | G2a   | G2b   | G3    | G4   | G5    |
|---------:|-------------:|----------:|:----------|-------------:|--------:|--------:|--------:|------:|:------|:------|:------|:------|:-----|:------|
|     0.80 |         0.20 |      0.00 | PARTIAL   |        71.39 |   46.73 |   -3.97 |  207.43 | 35.38 | True  | False | False | False | True | False |
|     0.90 |         0.10 |      0.00 | PARTIAL   |        68.73 |   42.99 |   -3.47 |  194.79 | 40.61 | True  | False | False | False | True | False |
|     1.00 |         0.00 |      0.00 | FAIL      |        65.44 |   36.43 |   -2.80 |  182.46 | 45.67 | False | False | False | True  | True | False |
|     0.70 |         0.30 |      0.00 | FAIL      |        62.20 |   50.75 |   -4.10 |  173.42 | 28.70 | False | False | False | False | True | False |
|     0.70 |         0.20 |      0.10 | FAIL      |        54.41 |   63.53 |   -4.15 |  141.47 | 16.81 | False | False | False | False | True | False |
|     0.80 |         0.10 |      0.10 | FAIL      |        52.42 |   58.61 |   -3.96 |  131.75 | 23.30 | False | False | False | False | True | False |
|     0.60 |         0.40 |      0.00 | FAIL      |        52.20 |   55.08 |   -4.17 |  143.04 | 14.87 | False | False | False | False | True | False |
|     0.60 |         0.30 |      0.10 | FAIL      |        49.85 |   66.32 |   -4.23 |  127.44 |  9.89 | False | False | False | False | True | False |
|     0.90 |         0.00 |      0.10 | FAIL      |        49.60 |   54.04 |   -3.37 |  119.54 | 28.18 | False | False | False | False | True | False |
|     0.50 |         0.50 |      0.00 | FAIL      |        46.63 |   58.31 |   -4.21 |  125.45 |  6.98 | False | False | False | False | True | False |
|     0.60 |         0.20 |      0.20 | FAIL      |        46.59 |   75.64 |   -4.28 |  110.05 |  4.97 | False | False | False | False | True | False |
|     0.70 |         0.10 |      0.20 | FAIL      |        45.54 |   75.21 |   -4.21 |  101.30 |  9.84 | False | False | False | False | True | False |
|     0.50 |         0.40 |      0.10 | FAIL      |        45.13 |   66.94 |   -4.26 |  113.67 |  4.16 | False | False | False | False | True | False |
|     0.50 |         0.30 |      0.20 | FAIL      |        44.03 |   76.13 |   -4.32 |  103.37 |  0.96 | False | False | False | False | True | False |
|     0.80 |         0.00 |      0.20 | FAIL      |        43.91 |   73.14 |   -3.87 |   91.43 | 14.94 | False | False | False | False | True | False |
|     0.50 |         0.20 |      0.30 | FAIL      |        43.10 |   85.91 |   -4.37 |   91.77 | -0.89 | False | False | False | False | True | False |
|     0.40 |         0.60 |      0.00 | FAIL      |        42.80 |   59.08 |   -4.22 |  114.29 |  2.04 | False | False | False | False | True | False |
|     0.40 |         0.50 |      0.10 | FAIL      |        41.97 |   67.59 |   -4.27 |  104.78 | -0.24 | False | False | False | False | True | False |
|     0.40 |         0.30 |      0.30 | FAIL      |        41.92 |   86.31 |   -4.33 |   88.68 | -2.96 | False | False | False | False | True | False |
|     0.40 |         0.40 |      0.20 | FAIL      |        41.64 |   76.66 |   -4.32 |   96.29 | -2.08 | False | False | False | False | True | False |

## fold2 calmar top 10 (fold2 회복 관점)

|   w_macd |   w_breakout |   w_trend | verdict   |   fold2 |   fold2_mdd |   calmar_4ds |
|---------:|-------------:|----------:|:----------|--------:|------------:|-------------:|
|     1.00 |         0.00 |      0.00 | FAIL      |   -2.80 |       -0.06 |        65.44 |
|     0.90 |         0.00 |      0.10 | FAIL      |   -3.37 |       -0.06 |        49.60 |
|     0.90 |         0.10 |      0.00 | PARTIAL   |   -3.47 |       -0.06 |        68.73 |
|     0.80 |         0.00 |      0.20 | FAIL      |   -3.87 |       -0.07 |        43.91 |
|     0.00 |         0.00 |      1.00 | FAIL      |   -3.94 |       -0.13 |        30.26 |
|     0.00 |         0.10 |      0.90 | FAIL      |   -3.96 |       -0.13 |        31.50 |
|     0.80 |         0.10 |      0.10 | FAIL      |   -3.96 |       -0.07 |        52.42 |
|     0.80 |         0.20 |      0.00 | PARTIAL   |   -3.97 |       -0.07 |        71.39 |
|     0.00 |         0.20 |      0.80 | FAIL      |   -3.98 |       -0.13 |        33.14 |
|     0.00 |         0.30 |      0.70 | FAIL      |   -4.00 |       -0.13 |        35.32 |

## 종합 판정

**PARTIAL** — 2 cell 이 G1 또는 G2a 만 통과. 최고: w=(0.8, 0.2, 0.0) calmar_4ds=+71.39, fold2=-3.97. 사람 판단.

heatmaps/ + cells.csv 참조.

## 사람 보강 결론 (2026-05-14)

### 자동 평가 결과
- 264 evaluation (66 weight cells × 4 fold), additive 모델, 실행 30초
- **PASS=0, PARTIAL=2, FAIL=64**
- PARTIAL 둘 다 G1 (4ds calmar 우월) 만 통과, G2a (fold2 개선) 미통과

### 사실상 portfolio 가설 기각
**fold2 top 10 cells 의 최고 fold2 calmar = baseline w=(1,0,0) 의 -2.80**.
즉 다른 모든 weight 조합에서 fold2 calmar 가 -2.80 보다 나쁘다 (-3.47 ~ -4.13 범위).

**이유**:
- breakout_52w 단독 fold2 calmar = -4.13 (MV-E)
- trend_followthrough 단독 fold2 calmar = -3.94 (MV-E)
- macd_cross 단독 fold2 calmar = **-2.80**
- 가중 평균 (양의 가중치) → 항상 -2.80 ~ -4.13 사이 → 단독 macd_cross 보다 악화

**가설 기각 결론**: MV-E 가 발견한 "breakout/trend 가 fold1·3 강함" 은 사실이지만, **그 fold2 손실이 macd_cross 의 fold2 손실보다 더 깊다** → portfolio 평균이 fold2 에서 항상 악화. 시기별 보완 가설은 **두 strategy 의 손실 시기가 fold2 에서 겹쳤기 때문에 작동하지 않음**.

### 한계적 부산물 (실용성 낮음)
- **w=(0.8, 0.2, 0.0)**: calmar_4ds=71.39 (+5.95 vs baseline)
  - G1 통과: ✓
  - G2a (fold2): ✗ -3.97 (baseline -2.80 보다 악화)
  - G3 (fold1/3/oos 손실): ✗ oos 손실율 -22.5% (baseline 45.67 → 35.38)
  - **운영 가치**: 4ds 평균 5% 개선 vs fold2/oos 악화 trade-off — 가치 없음

### Caveat (additive 모델 한계)
- 자본 공유 미반영. 실제 portfolio 운영 시 종목 중복 매수 reject → 결과가 더 보수적일 가능성. 하지만 본 결과가 이미 부정적이라 integrated 모델 검증 무의미.

### 시리즈 (MV-A→B→C→D→E→F) 최종 결론

| MV | 시도 | 결과 |
|----|------|------|
| MV-A | macd_cross param grid | fold2 기간 의존 |
| MV-B | exit overlay 정적 | 거부 |
| MV-C v1/v2 | entry filter | fold2 회복 불가 |
| MV-D | exit-side dynamic | fold2 회복 불가 |
| MV-E | 17 strategy 재평가 | fold2-robust 부재 |
| **MV-F** | **3 strategy 분배** | **portfolio 가설 기각** |

**macd_cross 의 fold2 약점은 현재 가용 자산 (단독·overlay·entry filter·외부 strategy·portfolio) 모든 방식으로 회복 불가**. 구조적 한계 — fold2 (2025-11~12 KOSDAQ 약세) 자체가 강세장 친화 strategy 들에게 일률적으로 적자 시기.

### 운영 정책 (변경 없음)
- ACTIVE_STRATEGY=macd_cross 유지, 안전망 (서킷브레이커 -3% + 킬스위치) 만
- 외부 strategy 도입·portfolio 분배 모두 거부

### 다음 단계 후보
- **MV-G 신규 family**: ML 기반 시그널 / multi-stock interaction / microstructure — 시간 비용 큼
- **운영 안정화**: 신규 시도 보류, 현 macd_cross 단독 라이브 운영에 집중 + 정기 KPI 모니터링
- **데이터 기간 확장**: fold2 와 유사한 다른 약세 기간 데이터 확보 → 일반화된 약세장 패턴 분석