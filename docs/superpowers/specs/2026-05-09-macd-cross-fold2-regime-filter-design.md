# macd_cross fold2 Regime Filter 설계 (Phase 1: 멀티버스 분석)

작성일: 2026-05-09
관련 산출물:
- `backtests/reports/macd_cross_mv/param_grid/cells.csv` (MV-A 결과)
- `backtests/reports/macd_cross_mv/param_grid/summary.md` (MV-A 결론)
- `docs/superpowers/specs/2026-05-07-macd-cross-multiverse-design.md` (MV 설계서)

## 1. 배경

MV-A 멀티버스 (360 cell × 4 dataset, 2026-05-08 commit `133828c3`) 결과:

- **Fold 2 (2025-11~12)**: 360 cell 중 **333 cell (92%)** 이 calmar < 0
- 4-dataset 평균 calmar Top 13 cell 도 13/13 모두 fold2 fail
- 어떤 macd_cross 파라미터로도 fold2 회피 불가 → **기간 의존**, **파라미터 sensitivity 가 아님**

→ MV-A summary.md 결론: **별도 레짐 필터 또는 거래 중단 정책 필요**.

**KOSPI 일봉 분석 (2026-05-09)**:

| Metric | fold1 (+30%) | **fold2 (-0.2%)** | fold3 (+45%) | oos (+12%) |
|--------|------------|-----------|------------|-----------|
| 20d_return mean | +8.9% | **+4.4%** | +17.0% | +3.0% |
| 20d_return min | -0.7% | **-7.1%** | +7.9% | -15.8% |
| close vs MA20 mean | +4.9% | **+1.2%** | +8.5% | +1.4% |
| close vs MA20 min | -1.3% | **-4.9%** | +1.9% | -8.3% |
| MA5 vs MA20 mean | +3.6% | **+1.1%** | +6.3% | +1.2% |
| 5d_return min | -2.1% | **-6.0%** | -2.6% | -16.4% |

→ **Fold2 의 distinctive marker: 가격이 MA20 이하로 빈번히 하락 (choppy / sideways trend break)**. 다른 fold 는 MA20 위에서 강한 상승 (fold1/3) 또는 극단 변동성 (oos).

기존 `pre_market_analyzer.py` 의 regime filter 3종은 모두 single-day reactive (전일 -3%, 시가갭 +1%, NXT sentiment) — 다중일 trend break 미커버.

## 2. 핵심 결정 (인터뷰 결과)

| 항목 | 결정 | 근거 |
|------|------|------|
| 필터 액션 | **macd_cross 완전 차단** (recommended_max_positions=0 패턴) | 서킷브레이커와 일관성, 명확한 해석 |
| 신호 정의 | **`KOSPI close < MA20`** (전일 종가 기준, single signal) | 가장 단순 + fold2 효과적 + fold1/3 false positive 거의 없음 |
| 신호 lookback | shift(1) — 진입일 D 의 전일 (D-1) close 와 D-1 MA20 비교 | lookahead 방지 (3대 원칙 ①) |
| 지수 | **KOSPI (KS11) 단일** | 보편적 벤치마크 + 데이터 분석 완료 |
| 검증 방식 | **멀티버스 리플레이 (4 fold) 먼저** | 라이브 적용 전 수치 검증 필수 |
| 구현 접근 | **Strategy wrapper** (exit_overlay 패턴) | 라이브 본체 미수정, engine 무수정 |
| Phase 1 범위 | **분석 전용 — 라이브 코드 미수정** | 검증 통과 후 Phase 2 별도 plan |

## 3. Decision Gate (Phase 1 통과 → Phase 2 진입)

| 조건 | 임계 | 의미 |
|------|------|------|
| ✓ fold2 calmar 개선 (off→on) | ≥ +20 | fold2 92% loss cell 문제 완화 입증 |
| ✓ fold1/3 calmar 손실 허용 범위 | ≤ -5% | 호황기 false positive 비용 합리 |
| ✓ oos calmar 변화 | ≥ ±0 | 미래 비슷한 시장 일반화 가능성 |
| ✓ block_days selectivity | fold2 > 5 일 AND fold1/3 ≤ 2 일 | 신호 정밀도 확인 |

4 조건 **모두 충족** → Phase 2 라이브 plan 작성. 일부 미충족 → spec 보완 후 재평가 또는 폐기.

## 4. 아키텍처 변경

### 4.1 신규 Strategy wrapper

`backtests/strategies/macd_cross_regime_filter.py` (신규):

```python
"""macd_cross 에 KOSPI MA20 regime filter 를 얹은 백테스트 wrapper.

본체 backtests/strategies/macd_cross.py 는 라이브 동등성 보호 위해 미수정.
filter 활성 시 KOSPI close < MA20 (전일 기준, lookahead 방지) 인 날 entry 차단.
"""
from typing import Optional
import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import EntryOrder
from backtests.strategies.macd_cross import MACDCrossStrategy


class MACDCrossRegimeFilterStrategy(MACDCrossStrategy):
    name = "macd_cross_regime_filter"

    def __init__(
        self,
        regime_filter_enabled: bool = False,
        kospi_daily_df: Optional[pd.DataFrame] = None,
        ma_period: int = 20,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.regime_filter_enabled = regime_filter_enabled
        self.kospi_daily_df = kospi_daily_df
        self.ma_period = ma_period

    def prepare_features(self, df_minute, df_daily):
        feat = super().prepare_features(df_minute, df_daily).copy()
        if not self.regime_filter_enabled:
            return feat
        if df_minute.empty:
            return feat

        # KOSPI MA20 lookup table
        ks = self.kospi_daily_df.sort_values('trade_date').copy()
        ks['ma'] = ks['close'].rolling(self.ma_period).mean()
        ks['below'] = (ks['close'] < ks['ma']).astype(bool)
        # shift(1): 진입일 D 의 전일 (D-1) 신호만 사용
        ks['below_prev'] = ks['below'].shift(1).fillna(False).astype(bool)
        block_map = dict(zip(ks['trade_date'].astype(str), ks['below_prev']))

        feat['kospi_below_ma20'] = (
            df_minute['trade_date'].astype(str)
            .map(block_map).fillna(False).astype(bool).values
        )
        return feat

    def entry_signal(self, features, bar_idx, stock_code) -> Optional[EntryOrder]:
        if self.regime_filter_enabled and 'kospi_below_ma20' in features.columns:
            arr = get_arrays(features)
            if bool(arr['kospi_below_ma20'][bar_idx]):
                return None  # filter block
        return super().entry_signal(features, bar_idx, stock_code)
```

### 4.2 Dataset 확장 — KOSPI daily 첨부

`backtests/multiverse/macd_cross_mv_common.py` 수정:

```python
@dataclass
class Dataset:
    name: str
    minute_start: str
    minute_end: str
    daily_start: str
    minute_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    daily_by_code: Dict[str, pd.DataFrame] = field(default_factory=dict)
    universe: List[str] = field(default_factory=list)
    kospi_daily_df: Optional[pd.DataFrame] = None  # 신규: KOSPI 일봉 (filter 용)


def load_all_datasets() -> Dict[str, Dataset]:
    # ... 기존 universe / minute / daily 로드 ...

    # 신규: KOSPI daily 1회 로드 (모든 dataset 공유)
    kospi_df = load_daily_df(['KS11'], daily_start, minute_end)
    # daily_candles schema: stock_code, stck_bsop_date, stck_clpr ...
    kospi_norm = pd.DataFrame({
        'trade_date': kospi_df['stck_bsop_date'].astype(str),
        'close': kospi_df['stck_clpr'].astype(float),
    }).sort_values('trade_date').reset_index(drop=True)

    for name in datasets:
        datasets[name].kospi_daily_df = kospi_norm

    return datasets
```

(`load_daily_df` 의 KS11 호출 가능 여부는 구현 시 검증 — 필요 시 별도 SQL helper 추가.)

### 4.3 신규 멀티버스 runner — MV-C

`backtests/multiverse/macd_cross_regime_filter_mv.py` (신규):

```python
"""MV-C: macd_cross regime filter 멀티버스.

2 params (Stage 2 best 14/34, MV-A globally best 16/32) × 2 filter (off, on)
= 4 cell × 4 dataset = 16 evaluation. cells.csv + heatmap + summary.md.
"""
import csv, time
from pathlib import Path
from typing import Dict

from backtests.common.engine import BacktestEngine
from backtests.multiverse.macd_cross_mv_common import (
    Dataset, build_cell_kpis, load_all_datasets, _trading_days_count,
)
from backtests.strategies.macd_cross_regime_filter import (
    MACDCrossRegimeFilterStrategy,
)


REPORT_DIR = Path("backtests/reports/macd_cross_mv/regime_filter")

PARAM_CELLS = [
    {"fast_period": 14, "slow_period": 34, "signal_period": 12, "entry_hhmm_min": 1430,
     "label": "stage2_best"},
    {"fast_period": 16, "slow_period": 32, "signal_period": 12, "entry_hhmm_min": 1430,
     "label": "mva_global_best"},
]
FILTER_FLAGS = [False, True]


def _evaluate_with_block_days(strategy, dataset, kospi_daily_df, initial_capital=10_000_000):
    """evaluate_cell + filter 가 차단한 trading 일수 추가 측정."""
    eng = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        universe=dataset.universe,
        minute_df_by_code=dataset.minute_by_code,
        daily_df_by_code=dataset.daily_by_code,
    )
    result = eng.run()
    trading_days = _trading_days_count(dataset.minute_by_code)
    kpis = build_cell_kpis(
        equity=result.equity_curve,
        trades=result.trades,
        trading_days=trading_days,
    )
    # block_days: dataset 영업일 중 filter 가 entry 차단한 일수
    if strategy.regime_filter_enabled and kospi_daily_df is not None:
        ks = kospi_daily_df.sort_values('trade_date').copy()
        ks['ma'] = ks['close'].rolling(strategy.ma_period).mean()
        ks['below_prev'] = (ks['close'] < ks['ma']).shift(1).fillna(False)
        ds_dates = set()
        for df_min in dataset.minute_by_code.values():
            if not df_min.empty:
                ds_dates.update(df_min['trade_date'].astype(str).unique())
        sub = ks[ks['trade_date'].astype(str).isin(ds_dates)]
        kpis['block_days'] = int(sub['below_prev'].sum())
    else:
        kpis['block_days'] = 0
    return kpis


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("[MV-C] datasets 로드...")
    datasets: Dict[str, Dataset] = load_all_datasets()

    out_path = REPORT_DIR / "cells.csv"
    fieldnames = [
        "param_label", "fast_period", "slow_period", "signal_period", "entry_hhmm_min",
        "filter", "dataset", "calmar", "return", "mdd", "trades", "win_rate",
        "top1_share", "max_consec_loss", "monthly_trades", "block_days",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for params in PARAM_CELLS:
            label = params["label"]
            params_no_label = {k: v for k, v in params.items() if k != "label"}
            for filter_on in FILTER_FLAGS:
                for ds_name, ds in datasets.items():
                    strat = MACDCrossRegimeFilterStrategy(
                        regime_filter_enabled=filter_on,
                        kospi_daily_df=ds.kospi_daily_df,
                        **params_no_label,
                    )
                    kpis = _evaluate_with_block_days(
                        strat, ds, ds.kospi_daily_df,
                    )
                    row = {
                        "param_label": label,
                        **params_no_label,
                        "filter": "on" if filter_on else "off",
                        "dataset": ds_name,
                        **{k: kpis[k] for k in (
                            "calmar","return","mdd","trades","win_rate",
                            "top1_share","max_consec_loss","monthly_trades",
                            "block_days",
                        )},
                    }
                    writer.writerow(row)
                    print(f"  {label} filter={filter_on} {ds_name}: "
                          f"calmar={kpis['calmar']:.2f} block_days={kpis['block_days']}")

    print(f"[MV-C] saved → {out_path}")


if __name__ == "__main__":
    main()
```

### 4.4 Plotter 확장

`backtests/multiverse/plot_macd_cross_mv.py` 에 추가:

```python
RF_DIR = Path("backtests/reports/macd_cross_mv/regime_filter")


def plot_regime_filter():
    df = pd.read_csv(RF_DIR / "cells.csv")
    out = RF_DIR / "heatmaps"
    out.mkdir(exist_ok=True)
    # heatmap: rows=param_label, cols=filter+dataset, value=calmar
    fig, ax = plt.subplots(figsize=(10, 5))
    pivot = df.pivot_table(
        index='param_label', columns=['filter','dataset'],
        values='calmar', aggfunc='mean',
    )
    _heatmap_simple(ax, pivot, "Calmar — param × filter × dataset")
    fig.tight_layout()
    fig.savefig(out / 'calmar_summary.png', dpi=110)
    plt.close(fig)
    print(f"[plot] regime_filter heatmap → {out}")


def write_regime_filter_summary():
    df = pd.read_csv(RF_DIR / "cells.csv")
    # ON vs OFF 비교 (param 별, dataset 별)
    pivot = df.pivot_table(
        index=['param_label','dataset'], columns='filter',
        values=['calmar','return','mdd','block_days'], aggfunc='mean',
    )
    delta_calmar = pivot[('calmar','on')] - pivot[('calmar','off')]
    delta_return = pivot[('return','on')] - pivot[('return','off')]

    out = RF_DIR / "summary.md"
    body = []
    body.append("# MV-C regime filter summary\n")
    body.append("## Calmar 비교 (filter on - off)\n")
    body.append(delta_calmar.unstack().to_markdown())
    body.append("\n## Decision Gate 4조건 평가\n")
    # gate 평가 자동
    fold2_delta = delta_calmar.xs('fold2', level='dataset').mean()
    fold1_loss = (delta_calmar.xs('fold1', level='dataset') / pivot[('calmar','off')].xs('fold1', level='dataset')).mean() * 100
    fold3_loss = (delta_calmar.xs('fold3', level='dataset') / pivot[('calmar','off')].xs('fold3', level='dataset')).mean() * 100
    oos_delta = delta_calmar.xs('oos', level='dataset').mean()
    fold2_block = pivot[('block_days','on')].xs('fold2', level='dataset').mean()
    fold1_block = pivot[('block_days','on')].xs('fold1', level='dataset').mean()
    fold3_block = pivot[('block_days','on')].xs('fold3', level='dataset').mean()

    gates = [
        ("fold2 calmar +20+", fold2_delta >= 20, f"{fold2_delta:+.2f}"),
        ("fold1/3 손실 -5% 이내", abs(fold1_loss) <= 5 and abs(fold3_loss) <= 5,
         f"f1={fold1_loss:+.1f}% f3={fold3_loss:+.1f}%"),
        ("oos calmar ±0", oos_delta >= 0, f"{oos_delta:+.2f}"),
        ("block_days selectivity", fold2_block > 5 and max(fold1_block,fold3_block) <= 2,
         f"f2={fold2_block:.0f} f1={fold1_block:.0f} f3={fold3_block:.0f}"),
    ]
    for name, passed, val in gates:
        body.append(f"- {'✓' if passed else '✗'} {name}: {val}")

    body.append(f"\n## 종합: {'PASS — Phase 2 진입' if all(g[1] for g in gates) else 'FAIL — 보완 또는 폐기'}\n")
    (RF_DIR / "summary.md").write_text("\n".join(body), encoding="utf-8")
```

`main()` 에 호출 추가:
```python
def main():
    if (PG_DIR / "cells.csv").exists(): plot_param_grid(); write_param_grid_summary()
    if (EO_DIR / "cells.csv").exists(): plot_exit_overlay(); write_exit_overlay_summary()
    if (RF_DIR / "cells.csv").exists(): plot_regime_filter(); write_regime_filter_summary()
```

## 5. 데이터 흐름

```
load_all_datasets()
  ├─ universe top 30
  ├─ minute_df 광역 로드 (2025-09 ~ 2026-04)
  ├─ daily_df 광역 로드 (2025-01 ~ 2026-04)
  └─ NEW: KOSPI daily (KS11) 로드 → 모든 dataset 에 첨부

MV-C runner (16 evaluation):
  for param in [stage2_best (14/34), mva_global_best (16/32)]:
    for filter_on in [False, True]:
      for ds in [fold1, fold2, fold3, oos]:
        strategy = MACDCrossRegimeFilterStrategy(
            regime_filter_enabled=filter_on,
            kospi_daily_df=ds.kospi_daily_df,
            **param,
        )
        BacktestEngine(strategy, ds.universe, ds.minute_by_code, ds.daily_by_code).run()
        → cells.csv row (calmar, return, mdd, ..., block_days)

plotter:
  cells.csv → heatmap + summary.md (4-gate 자동 평가 → PASS/FAIL)
```

## 6. Lookahead 방지 보증 (3대 원칙 ①)

filter 신호 = `KOSPI close[D-1] < MA20[D-1]` 비교. 두 값 모두 D-1 종가 시점에 알려진 정보.

D 일 14:31 entry 평가 시점: D-1 종가 / D-1 MA20 둘 다 사용 가능 → **lookahead 0**.

검증: `prepare_features` 에서 `shift(1)` 명시 적용 + unit test 로 강제 (`test_no_lookahead_at_entry_day`).

## 7. Testing 전략

| 테스트 | 위치 | 검증 |
|--------|------|------|
| Unit: KOSPI MA20 신호 정확성 | `tests/backtests/strategies/test_macd_cross_regime_filter.py` | mock daily 60봉으로 below_prev 정확 |
| Unit: filter ON 시 entry block | 동 | golden cross + below_prev=True 시 None 반환 |
| Unit: filter OFF 시 base 동일 | 동 | filter=False 시 super().entry_signal() 결과 그대로 |
| Edge: kospi_daily_df=None 시 filter ON | 동 | 명시적 안전 동작 (block all 또는 raise) |
| Edge: warmup 부족 (<20봉) | 동 | NaN MA20 → below_prev=False (안전) |
| Lookahead: entry 일 종가 미사용 | 동 | shift(1) 적용 → D-1 데이터만 |
| Regression: 기존 macd_cross 280 tests | 기존 | 라이브 코드 무수정이라 자동 그린 |
| Manual: MV-C 풀 실행 | `python -m backtests.multiverse.macd_cross_regime_filter_mv` | 16 eval, cells.csv + heatmap + summary.md |

## 8. 산출물

코드:
- `backtests/strategies/macd_cross_regime_filter.py` (신규)
- `backtests/multiverse/macd_cross_regime_filter_mv.py` (신규)
- `backtests/multiverse/macd_cross_mv_common.py` (수정 — Dataset.kospi_daily_df 추가)
- `backtests/multiverse/plot_macd_cross_mv.py` (수정 — RF_DIR section + main 호출)

테스트:
- `tests/backtests/strategies/test_macd_cross_regime_filter.py` (신규)

데이터 산출물 (Phase 1 실행 후):
- `backtests/reports/macd_cross_mv/regime_filter/cells.csv` (16 rows)
- `backtests/reports/macd_cross_mv/regime_filter/heatmaps/calmar_summary.png`
- `backtests/reports/macd_cross_mv/regime_filter/summary.md` (4-gate 평가)

## 9. 범위 밖 (Out of Scope)

- **Phase 2: 라이브 적용** (`core/strategies/`, `main.py` 수정) — Phase 1 PASS 시 별도 spec/plan
- 다른 신호 후보 (MA5/MA20, 5d_return, KOSDAQ 등) — Phase 1 결과 따라 후속 검토
- Phase 1 PASS 시 `pre_market_analyzer.py` 통합 vs 별도 모듈 결정

## 10. Phase 2 미리보기 (조건부)

Phase 1 4-gate PASS 시 Phase 2 spec:
- `core/strategies/macd_cross_regime_filter_signal.py` — 라이브 어댑터 (KOSPI daily 인입 + below_prev 판정)
- `main.py::_evaluate_macd_cross_window` — entry 직전 filter 호출
- 라이브 테스트 + 봇 재시작 후 첫 영업일 모니터링
