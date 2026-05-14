# MV-D exit_regime_v2 summary

## Baseline (family=off) — per param × dataset

| param_label     |   ('calmar', 'fold1') |   ('calmar', 'fold2') |   ('calmar', 'fold3') |   ('calmar', 'oos') |   ('mdd', 'fold1') |   ('mdd', 'fold2') |   ('mdd', 'fold3') |   ('mdd', 'oos') |
|:----------------|----------------------:|----------------------:|----------------------:|--------------------:|-------------------:|-------------------:|-------------------:|-----------------:|
| mva_global_best |                103.74 |                 -1.31 |                289.15 |              119.19 |              -0.01 |              -0.05 |              -0.01 |            -0.01 |
| stage2_best     |                 36.43 |                 -2.80 |                182.46 |               45.67 |              -0.02 |              -0.06 |              -0.01 |            -0.02 |

## Per-family best cell (gate_score desc)

| family    | cell_label       | param_label     |   fold2_delta |   f2_mdd_cell |   f1_pct |   f3_pct |   oos_pct |   fired_f2 |   top1_f2 |   gate_score |
|:----------|:-----------------|:----------------|--------------:|--------------:|---------:|---------:|----------:|-----------:|----------:|-------------:|
| trailing  | trail_p03_a02    | stage2_best     |          1.30 |         -0.05 |   -46.37 |   -77.47 |   -101.87 |       0.34 |     -1.35 |            4 |
| reversal  | rev_t1500_b+0_h1 | stage2_best     |          1.12 |         -0.04 |   -30.95 |   -39.37 |    122.49 |       0.13 |     -1.73 |            4 |
| tiered_sl | tsl_d1_X_d2_03   | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.32 |     -1.92 |            5 |

## All cells — 7-gate evaluation

| family    | cell_label       | param_label     |   fold2_delta |   f2_mdd_cell |   f1_pct |   f3_pct |   oos_pct |   fired_f2 |   top1_f2 | G1    | G2    | G3    | G4    | G5   | G6    | G7    | primary_pass   |   gate_score |
|:----------|:-----------------|:----------------|--------------:|--------------:|---------:|---------:|----------:|-----------:|----------:|:------|:------|:------|:------|:-----|:------|:------|:---------------|-------------:|
| tiered_sl | tsl_d1_X_d2_03   | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.32 |     -1.92 | False | False | True  | True  | True | True  | True  | False          |            5 |
| tiered_sl | tsl_d1_X_d2_03   | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.35 |     -0.67 | False | False | True  | True  | True | True  | True  | False          |            5 |
| tiered_sl | tsl_d1_X_d2_05   | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.16 |     -0.67 | False | False | True  | True  | True | True  | True  | False          |            5 |
| trailing  | trail_p03_a02    | stage2_best     |          1.30 |         -0.05 |   -46.37 |   -77.47 |   -101.87 |       0.34 |     -1.35 | False | True  | False | True  | True | True  | False | False          |            4 |
| reversal  | rev_t1500_b+0_h1 | stage2_best     |          1.12 |         -0.04 |   -30.95 |   -39.37 |    122.49 |       0.13 |     -1.73 | False | True  | False | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1500_b-1_h1 | stage2_best     |          1.12 |         -0.04 |   -30.95 |   -39.37 |    122.49 |       0.13 |     -1.73 | False | True  | False | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1400_b+0_h1 | stage2_best     |          0.43 |         -0.05 |   -34.35 |   -42.08 |     40.89 |       0.13 |     -0.95 | False | True  | False | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1400_b-1_h1 | stage2_best     |          0.43 |         -0.05 |   -34.35 |   -42.08 |     41.39 |       0.13 |     -0.95 | False | True  | False | False | True | True  | True  | False          |            4 |
| reversal  | rev_tlast_b+0_h1 | mva_global_best |          0.09 |         -0.04 |     0.00 |     2.47 |      2.07 |       0.10 |     -2.13 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_tlast_b-1_h1 | mva_global_best |          0.09 |         -0.04 |     0.00 |     2.47 |      2.07 |       0.10 |     -2.13 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1400_b+0_h2 | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.00 |     -1.92 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1400_b+0_h2 | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.00 |     -0.67 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1400_b-1_h2 | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.00 |     -1.92 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1400_b-1_h2 | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.00 |     -0.67 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1500_b+0_h2 | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.00 |     -1.92 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1500_b+0_h2 | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.00 |     -0.67 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1500_b-1_h2 | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.00 |     -1.92 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_t1500_b-1_h2 | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.00 |     -0.67 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_tlast_b+0_h2 | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.00 |     -1.92 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_tlast_b+0_h2 | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.00 |     -0.67 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_tlast_b-1_h2 | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.00 |     -1.92 | False | False | True  | False | True | True  | True  | False          |            4 |
| reversal  | rev_tlast_b-1_h2 | stage2_best     |          0.00 |         -0.06 |     0.00 |     0.00 |      0.00 |       0.00 |     -0.67 | False | False | True  | False | True | True  | True  | False          |            4 |
| tiered_sl | tsl_d1_X_d2_05   | mva_global_best |          0.00 |         -0.05 |     0.00 |     0.00 |      0.00 |       0.13 |     -1.92 | False | False | True  | False | True | True  | True  | False          |            4 |
| tiered_sl | tsl_d1_07_d2_03  | stage2_best     |         -0.36 |         -0.07 |     6.97 |    12.67 |    -32.81 |       0.39 |     -0.49 | False | False | True  | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_07_d2_05  | stage2_best     |         -0.36 |         -0.07 |     6.97 |    12.67 |    -32.81 |       0.23 |     -0.49 | False | False | True  | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_07_d2_X   | stage2_best     |         -0.36 |         -0.07 |     6.97 |    12.67 |    -32.81 |       0.19 |     -0.49 | False | False | True  | True  | True | True  | False | False          |            4 |
| trailing  | trail_p03_a00    | mva_global_best |         -0.49 |         -0.03 |   -86.01 |   -80.67 |   -101.18 |       0.68 |     -1.84 | False | True  | False | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_05_d2_03  | mva_global_best |         -0.56 |         -0.05 |    -2.62 |    12.07 |    -63.46 |       0.35 |     -1.08 | False | False | True  | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_05_d2_05  | mva_global_best |         -0.56 |         -0.05 |    -2.62 |    12.07 |    -63.46 |       0.23 |     -1.08 | False | False | True  | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_05_d2_X   | mva_global_best |         -0.56 |         -0.05 |    -2.62 |    12.07 |    -63.46 |       0.23 |     -1.08 | False | False | True  | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_07_d2_03  | mva_global_best |         -0.93 |         -0.06 |     0.00 |    44.70 |    -25.94 |       0.35 |     -0.82 | False | False | True  | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_07_d2_05  | mva_global_best |         -0.93 |         -0.06 |     0.00 |    44.70 |    -25.94 |       0.19 |     -0.82 | False | False | True  | True  | True | True  | False | False          |            4 |
| tiered_sl | tsl_d1_07_d2_X   | mva_global_best |         -0.93 |         -0.06 |     0.00 |    44.70 |    -25.94 |       0.16 |     -0.82 | False | False | True  | True  | True | True  | False | False          |            4 |
| trailing  | trail_p03_a02    | mva_global_best |          3.86 |         -0.03 |   -58.09 |   -84.65 |    -84.68 |       0.35 |      1.07 | False | True  | False | True  | True | False | False | False          |            3 |
| trailing  | trail_p02_a02    | mva_global_best |          3.05 |         -0.04 |   -52.88 |   -90.14 |    -81.73 |       0.42 |      1.26 | False | True  | False | True  | True | False | False | False          |            3 |
| trailing  | trail_p04_a02    | mva_global_best |          2.66 |         -0.04 |   -50.06 |   -90.35 |    -88.76 |       0.29 |      1.74 | False | True  | False | True  | True | False | False | False          |            3 |
| reversal  | rev_t1500_b+0_h1 | mva_global_best |          1.20 |         -0.04 |   -11.24 |     0.30 |     -7.06 |       0.10 |    837.20 | False | True  | False | False | True | False | True  | False          |            3 |
| reversal  | rev_t1500_b-1_h1 | mva_global_best |          1.20 |         -0.04 |    -9.13 |     0.30 |     -7.06 |       0.10 |    837.20 | False | True  | False | False | True | False | True  | False          |            3 |
| trailing  | trail_p05_a02    | mva_global_best |          1.13 |         -0.05 |   -53.62 |   -80.11 |    -72.33 |       0.23 |    -17.83 | False | False | False | True  | True | True  | False | False          |            3 |
| reversal  | rev_t1400_b+0_h1 | mva_global_best |          1.13 |         -0.04 |   -14.76 |     1.35 |    -20.21 |       0.10 |    -45.89 | False | True  | False | False | True | True  | False | False          |            3 |
| reversal  | rev_t1400_b-1_h1 | mva_global_best |          1.13 |         -0.04 |   -14.76 |     1.35 |    -19.94 |       0.10 |    -45.89 | False | True  | False | False | True | True  | False | False          |            3 |
| trailing  | trail_p02_a02    | stage2_best     |          1.04 |         -0.06 |   -47.90 |   -83.38 |    -94.92 |       0.41 |     -0.79 | False | False | False | True  | True | True  | False | False          |            3 |
| trailing  | trail_p04_a02    | stage2_best     |          0.68 |         -0.06 |   -50.28 |   -84.53 |    -97.22 |       0.28 |     -0.74 | False | False | False | True  | True | True  | False | False          |            3 |
| trailing  | trail_p02_a00    | stage2_best     |          0.43 |         -0.06 |   -67.68 |   -89.67 |   -107.49 |       0.94 |     -0.58 | False | True  | False | False | True | True  | False | False          |            3 |
| trailing  | trail_p05_a02    | stage2_best     |          0.37 |         -0.07 |   -51.01 |   -84.82 |    -88.04 |       0.22 |     -0.45 | False | False | False | True  | True | True  | False | False          |            3 |
| reversal  | rev_tlast_b+0_h1 | stage2_best     |         -0.01 |         -0.06 |   -33.31 |     2.49 |     70.27 |       0.12 |     -0.65 | False | False | False | False | True | True  | True  | False          |            3 |
| reversal  | rev_tlast_b-1_h1 | stage2_best     |         -0.01 |         -0.06 |   -33.31 |     2.49 |     70.27 |       0.12 |     -0.65 | False | False | False | False | True | True  | True  | False          |            3 |
| tiered_sl | tsl_d1_05_d2_03  | stage2_best     |         -0.18 |         -0.06 |   -28.60 |     7.63 |    -62.15 |       0.39 |     -0.57 | False | False | False | True  | True | True  | False | False          |            3 |
| tiered_sl | tsl_d1_05_d2_05  | stage2_best     |         -0.18 |         -0.06 |   -28.60 |     7.63 |    -62.15 |       0.26 |     -0.57 | False | False | False | True  | True | True  | False | False          |            3 |
| tiered_sl | tsl_d1_05_d2_X   | stage2_best     |         -0.18 |         -0.06 |   -28.60 |     7.63 |    -62.15 |       0.26 |     -0.57 | False | False | False | True  | True | True  | False | False          |            3 |
| trailing  | trail_p04_a00    | mva_global_best |         -0.18 |         -0.05 |   -60.21 |   -81.70 |    -99.71 |       0.58 |     -1.38 | False | False | False | True  | True | True  | False | False          |            3 |
| trailing  | trail_p05_a00    | stage2_best     |         -0.20 |         -0.08 |   -57.61 |   -89.29 |   -101.56 |       0.47 |     -0.29 | False | False | False | True  | True | True  | False | False          |            3 |
| trailing  | trail_p04_a00    | stage2_best     |         -0.30 |         -0.07 |   -59.45 |   -88.14 |   -107.52 |       0.59 |     -0.37 | False | False | False | True  | True | True  | False | False          |            3 |
| trailing  | trail_p02_a00    | mva_global_best |         -0.38 |         -0.04 |   -80.61 |   -88.23 |   -101.81 |       0.91 |     -1.21 | False | True  | False | False | True | True  | False | False          |            3 |
| trailing  | trail_p05_a00    | mva_global_best |         -0.45 |         -0.06 |   -56.40 |   -61.61 |    -91.19 |       0.45 |     -0.69 | False | False | False | True  | True | True  | False | False          |            3 |
| trailing  | trail_p03_a00    | stage2_best     |         -0.69 |         -0.06 |   -72.95 |   -82.28 |   -106.72 |       0.72 |     -0.47 | False | True  | False | False | True | True  | False | False          |            3 |

## Gate 정의

- **G1** fold2 Δcalmar ≥ +10
- **G2** fold2 MDD 감소 (cell_mdd ≥ off_mdd × 0.95)
- **G3** fold1/3 손실 ≤ 5%
- **G4** fired ratio fold2 ∈ [15%, 70%] (cherry-pick 회피)
- **G5** fold2 trade count 안정성 (±30%)
- **G6** fold2 top1_share ≤ 0.6
- **G7** OOS Δcalmar 손실율 ≤ 10%

## 종합

**FAIL** — primary gate (G1+G2+G3) 통과 cell 없음. 결론: fold2 unrecoverable on exit-side as well. paper macd_cross_alt + circuit breaker only 유지.

heatmaps/ 와 cells.csv 함께 검토.