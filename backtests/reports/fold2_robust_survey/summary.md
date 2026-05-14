# MV-E fold2_robust_survey summary

## macd_cross baseline (비교용)

- stage2_best 4ds-avg calmar = **65.44** (fold1=36.43, fold2=-2.80, fold3=182.46, oos=45.67)
- mva_global_best 4ds-avg calmar = **127.69** (fold1=103.74, fold2=-1.31, fold3=289.15, oos=119.19)
- macd_cross fold2 calmar **< 0** — 본 멀티버스가 발굴할 fold2-robust 의 기준

## Gate 정의

- **G1** fold2 calmar > 10
- **G2** fold1/3/oos calmar 모두 > 30
- **G3** 4ds-avg calmar > 30
- **G4** monthly_trades (4ds avg) 5~30
- **G5** top1_share (각 fold 최댓값) < 0.6
- **G6** max_consec_loss (각 fold 최댓값) ≤ 5
- 판정: PASS (G1+G2 + 보조 ≥3) / PORTFOLIO (G2+보조 ≥3, G1 미달) / FAIL

## Per-strategy best cell

| strategy            | cell_label                  | verdict   |   gate_score |   fold1 |   fold2 |   fold3 |   oos |   avg |   monthly_trades_avg |   top1_max |   mcl_max |
|:--------------------|:----------------------------|:----------|-------------:|--------:|--------:|--------:|------:|------:|---------------------:|-----------:|----------:|
| breakout_52w        | lb60_bf0.0_hh1500           | FAIL      |            4 |   62.36 |   -4.13 |   95.75 | -3.92 | 37.52 |                24.61 |       0.40 |         5 |
| trend_followthrough | lb3_bf0.6_hh1430            | FAIL      |            2 |   95.83 |   -3.94 |   33.06 | -3.93 | 30.26 |                66.42 |       0.44 |        18 |
| vwap_bounce         | dev-0.5_tp1.5_sl-1.0        | FAIL      |            1 |   -2.12 |   -1.48 |   -1.68 | -1.30 | -1.64 |              1226.56 |      -0.01 |        76 |
| bb_lower_bounce     | ns2.5_tp1.5_sl-1.0          | FAIL      |            1 |   -1.85 |   -1.50 |   -1.59 | -1.22 | -1.54 |              1698.15 |      -0.01 |        82 |
| rsi_oversold        | ov35_tp1.5_sl-1.0           | FAIL      |            1 |   -2.24 |   -1.61 |   -1.83 | -1.37 | -1.76 |              1054.44 |      -0.01 |        55 |
| gap_down_reversal   | gap-1.0_rev0.5_tp1.5        | FAIL      |            1 |   -3.82 |   -2.63 |   -2.77 | -2.82 | -3.01 |               253.01 |      -0.01 |        32 |
| closing_drift       | body1.0_decl-3.5_w1400_1500 | FAIL      |            1 |    6.36 |   -3.77 |    9.83 | -2.90 |  2.38 |                71.79 |       0.36 |        13 |

## fold2 calmar top 20 cells (전체)

| strategy        | cell_label           | verdict   |   fold1 |   fold2 |   fold3 |   oos |   monthly_trades_avg |   top1_max |
|:----------------|:---------------------|:----------|--------:|--------:|--------:|------:|---------------------:|-----------:|
| vwap_bounce     | dev-0.5_tp1.5_sl-1.0 | FAIL      |   -2.12 |   -1.48 |   -1.68 | -1.30 |              1226.56 |      -0.01 |
| vwap_bounce     | dev-1.0_tp1.5_sl-1.0 | FAIL      |   -2.06 |   -1.50 |   -1.70 | -1.34 |               895.74 |      -0.01 |
| bb_lower_bounce | ns2.5_tp1.5_sl-1.0   | FAIL      |   -1.85 |   -1.50 |   -1.59 | -1.22 |              1698.15 |      -0.01 |
| bb_lower_bounce | ns2.0_tp1.5_sl-1.0   | FAIL      |   -1.85 |   -1.50 |   -1.59 | -1.23 |              1695.10 |      -0.01 |
| bb_lower_bounce | ns1.5_tp1.5_sl-1.0   | FAIL      |   -1.79 |   -1.51 |   -1.58 | -1.23 |              1671.50 |      -0.01 |
| vwap_bounce     | dev-1.5_tp1.5_sl-1.0 | FAIL      |   -2.21 |   -1.52 |   -1.69 | -1.43 |               583.98 |      -0.01 |
| vwap_bounce     | dev-0.5_tp2.0_sl-1.0 | FAIL      |   -2.56 |   -1.60 |   -1.92 | -1.37 |              1117.38 |      -0.01 |
| rsi_oversold    | ov35_tp1.5_sl-1.0    | FAIL      |   -2.24 |   -1.61 |   -1.83 | -1.37 |              1054.44 |      -0.01 |
| vwap_bounce     | dev-1.0_tp2.0_sl-1.0 | FAIL      |   -2.44 |   -1.62 |   -1.95 | -1.37 |               830.15 |      -0.01 |
| rsi_oversold    | ov30_tp1.5_sl-1.0    | FAIL      |   -2.26 |   -1.65 |   -1.88 | -1.43 |               872.35 |      -0.01 |
| vwap_bounce     | dev-1.5_tp2.0_sl-1.0 | FAIL      |   -2.46 |   -1.67 |   -1.87 | -1.50 |               545.59 |      -0.02 |
| bb_lower_bounce | ns1.5_tp2.5_sl-1.0   | FAIL      |   -2.62 |   -1.70 |   -1.92 | -1.33 |              1330.29 |      -0.02 |
| bb_lower_bounce | ns2.5_tp2.5_sl-1.0   | FAIL      |   -2.60 |   -1.73 |   -2.08 | -1.35 |              1337.98 |      -0.02 |
| bb_lower_bounce | ns2.0_tp2.5_sl-1.0   | FAIL      |   -2.65 |   -1.75 |   -1.99 | -1.36 |              1339.23 |      -0.02 |
| vwap_bounce     | dev-1.0_tp3.0_sl-1.0 | FAIL      |   -2.87 |   -1.76 |   -2.19 | -1.57 |               760.03 |      -0.01 |
| rsi_oversold    | ov35_tp2.0_sl-1.0    | FAIL      |   -2.50 |   -1.76 |   -2.02 | -1.42 |               967.09 |      -0.01 |
| rsi_oversold    | ov30_tp2.0_sl-1.0    | FAIL      |   -2.43 |   -1.80 |   -2.10 | -1.46 |               817.17 |      -0.01 |
| vwap_bounce     | dev-1.5_tp3.0_sl-1.0 | FAIL      |   -2.84 |   -1.80 |   -2.11 | -1.59 |               513.74 |      -0.02 |
| vwap_bounce     | dev-0.5_tp3.0_sl-1.0 | FAIL      |   -3.54 |   -1.81 |   -2.38 | -1.48 |               970.52 |      -0.01 |
| vwap_bounce     | dev-2.0_tp1.5_sl-1.0 | FAIL      |   -2.44 |   -1.81 |   -1.80 | -1.58 |               380.26 |      -0.02 |

## 종합 판정

**FAIL** — G1+G2 동시 통과 cell 없음. 17 strategy 자산으로 fold2 견고 + 다른 fold 도 강한 family 부재. MV-F (신규 family) 권고.

heatmaps/ 와 cells.csv 함께 검토.