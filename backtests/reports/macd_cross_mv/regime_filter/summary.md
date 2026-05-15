# MV-C regime filter summary

## Calmar (filter on - off, mean over params)

| param_label     |    fold1 |     fold2 |   fold3 |      oos |
|:----------------|---------:|----------:|--------:|---------:|
| mva_global_best | -1.53612 | -1.22451  |       0 | -6.63203 |
| stage2_best     |  3.16055 | -0.565515 |       0 | 37.2143  |

## Decision Gate 4조건 평가

- ✗ **fold2 calmar +20+**: Δcalmar = -0.90 (요구: ≥+20)
- ✓ **fold1/3 손실 -5% 이내**: fold1 +1.2% / fold3 +0.0% (요구: 둘 다 |-5%| 이내)
- ✓ **oos calmar ±0 이상**: Δcalmar = +15.29 (요구: ≥0)
- ✗ **block_days selectivity**: f2=14 f1=3 f3=0 (요구: f2>5, f1/f3≤2)

## 종합: **FAIL** — 보완 또는 폐기

heatmaps/calmar_summary.png 와 cells.csv 함께 검토.

## 사람 보강 결론 (2026-05-09)

**Phase 1 검증 결과: 단순 `close<MA20` 신호로 fold2 회피 실패.**

상세 KPI (calmar, filter on - off):
- mva_global_best (16/32): fold1=-1.54 / fold2=-1.22 / fold3=0 / oos=-6.63 — **모든 dataset 에서 악화**
- stage2_best (14/34): fold1=+3.16 / fold2=-0.57 / fold3=0 / **oos=+37.21** — fold1/oos 만 개선

**Insight:**
1. **fold2 신호 정확성**: filter 가 fold2 14일 차단 (vs fold1 3일, fold3 0일) — 신호는 distinguishing. 하지만 fold2 calmar 개선이 -0.57~-1.22 수준으로 미미함 → **차단된 14일이 모두 손실일이 아니었음**.
2. **stage2_best 의 oos +37 효과**: 우연일 가능성 (단일 fold 표본 39 days). 후속 검증 없이 채택 금지.
3. **mva_global_best 가 일관되게 악화** → filter 가 16/32 영역에서 더 적합한 시그널을 자르는 부작용.

**결정: Phase 2 라이브 적용 보류.**

**후속 옵션:**
- 다른 신호 후보 검토: `(close<MA20) AND (MA5<MA20)` (trend confirmation, 더 selective), `5d_return ≤ -3%` (sharp drop reactive), `20d_return ≤ 0%` (sustained negative)
- fold2 의 거래별 손익 forensic 분석 — 어떤 trade pattern 이 손실을 만드는지 정성 분석 후 신호 재설계
- fold2 를 unrecoverable 로 받아들이고 paper macd_cross_alt (PR #46) + circuit breaker 만으로 운영