# MV-C v2 regime filter summary

## Per-cell 4-gate evaluation

sorted by gate_score desc, fold2_delta desc.

| signal_label       | param_label     |   fold2_delta |   fold1_pct |   fold3_pct |   oos_delta |   block_f2 |   block_f1 |   block_f3 | g1_f2_+20   | g2_f13_5pct   | g3_oos_0   | g4_select   |   gate_score |
|:-------------------|:----------------|--------------:|------------:|------------:|------------:|-----------:|-----------:|-----------:|:------------|:--------------|:-----------|:------------|-------------:|
| 5d_drop_-2pct      | stage2_best     |         -0.34 |        0.21 |        0.00 |       38.44 |         11 |          1 |          1 | False       | True          | True       | True        |            3 |
| 5d_drop_-2pct      | mva_global_best |         -0.39 |       -3.04 |        0.00 |        0.39 |         11 |          1 |          1 | False       | True          | True       | True        |            3 |
| 5d_drop_-3pct      | mva_global_best |          0.59 |        0.00 |        0.00 |      -54.92 |          9 |          0 |          0 | False       | True          | False      | True        |            2 |
| 5d_drop_-3pct      | stage2_best     |          0.42 |        0.00 |        0.00 |       -3.05 |          9 |          0 |          0 | False       | True          | False      | True        |            2 |
| 5d_drop_-5pct      | stage2_best     |          0.00 |        0.00 |        0.00 |        0.00 |          2 |          0 |          0 | False       | True          | True       | False       |            2 |
| 20d_neg_-3pct      | stage2_best     |         -0.54 |        0.00 |        0.00 |       44.05 |          5 |          0 |          0 | False       | True          | True       | False       |            2 |
| ma20_and_ma5_below | mva_global_best |         -1.18 |       -1.48 |        0.00 |        5.06 |          9 |          3 |          0 | False       | True          | True       | False       |            2 |
| 5d_drop_-1pct      | stage2_best     |          1.14 |       29.00 |        0.00 |       48.98 |         15 |          4 |          2 | False       | False         | True       | False       |            1 |
| 20d_neg_-5pct      | mva_global_best |          0.00 |        0.00 |        0.00 |      -49.49 |          1 |          0 |          0 | False       | True          | False      | False       |            1 |
| 20d_neg_-5pct      | stage2_best     |          0.00 |        0.00 |        0.00 |       -3.05 |          1 |          0 |          0 | False       | True          | False      | False       |            1 |
| 5d_drop_-5pct      | mva_global_best |          0.00 |        0.00 |        0.00 |       -9.81 |          2 |          0 |          0 | False       | True          | False      | False       |            1 |
| ma20_and_ma5_below | stage2_best     |         -0.55 |        8.68 |        0.00 |        7.11 |          9 |          3 |          0 | False       | False         | True       | False       |            1 |
| ma20_below_prev    | stage2_best     |         -0.57 |        8.68 |        0.00 |       37.21 |         14 |          3 |          0 | False       | False         | True       | False       |            1 |
| 20d_neg_0pct       | stage2_best     |         -0.67 |       -7.39 |        0.00 |       41.33 |         11 |          3 |          0 | False       | False         | True       | False       |            1 |
| ma20_below_prev    | mva_global_best |         -1.22 |       -1.48 |        0.00 |       -6.63 |         14 |          3 |          0 | False       | True          | False      | False       |            1 |
| 20d_neg_-3pct      | mva_global_best |         -1.45 |        0.00 |        0.00 |      -42.37 |          5 |          0 |          0 | False       | True          | False      | False       |            1 |
| 5d_drop_-1pct      | mva_global_best |          1.31 |       12.22 |        0.00 |      -16.78 |         15 |          4 |          2 | False       | False         | False      | False       |            0 |
| 20d_neg_0pct       | mva_global_best |         -1.80 |      -55.57 |        0.00 |      -48.72 |         11 |          3 |          0 | False       | False         | False      | False       |            0 |

## 종합

**PARTIAL** — 7 cell 이 2~3 gate 통과. 사람 판단 필요 (trade-off 검토).

heatmaps/ 와 cells.csv 함께 검토.

## 사람 보강 결론 (2026-05-13)

자동 평가: PARTIAL (최고 gate_score=3, Gate 1 미통과 전원).

**가장 근접한 신호 패밀리**: `5d_drop_-2pct` (gate_score=3, fold2_delta=-0.34~-0.39).
Gates 2/3/4 통과 — fold1/3 손실 없음, OOS calmar 양수, selectivity OK.
단, Gate 1 (fold2 Δcalmar ≥ +20) 은 전 신호에서 미통과 (최고 fold2_delta = +1.31 by `5d_drop_-1pct`).

**fold2 개선 불가 원인**:
fold2 block_days 는 충분히 존재 (5d_drop 계열 9~15일, ma20 계열 9~14일).
그러나 block 된 날이 손실일과 불일치 — fold2 의 손실은 필터가 차단하지 못한 날에 집중.
v1 과 동일한 구조적 실패: 기간 자체가 손실 원인 (fold2 = 2023-01~06, KOSDAQ 약세 장기화),
개별 진입일 필터로는 구제 불가.

**최종 권고**: FAIL 에 준하는 PARTIAL.
fold2 레짐 필터는 모든 신호 설계에서 회복 불가 판정.
현행 안전장치(서킷브레이커 -3% + 성과 게이트)가 사실상 레짐 필터 역할을 대체하고 있으며,
추가 신호 기반 레짐 필터 개발은 우선순위 낮음.
→ 기존 결론 유지: paper macd_cross_alt + circuit breaker only.