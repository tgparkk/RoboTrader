"""Stage 2 best params 로 인스턴스화한 전략의 look-ahead audit.

특별히 macd_cross 는 daily-side _build_macd_maps 가 핵심 — 여기에 perturbation 적용.
다른 후보 전략 (close_to_open, breakout_52w, trend_followthrough, limit_up_chase) 도
동일 절차로 daily 피처 검증.

Test:
  1. 합성 daily df 생성 (60+ 일)
  2. full prepare_features 호출 → 결과 row[t]
  3. daily df 의 t 이상 인덱스 값을 랜덤 교란
  4. perturbed prepare_features 호출 → 결과 row[t]
  5. row[t] 가 전부 동일하면 → look-ahead 없음
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtests.strategies.macd_cross import MACDCrossStrategy
from backtests.strategies.close_to_open import CloseToOpenStrategy
from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy
from backtests.strategies.limit_up_chase import LimitUpChaseStrategy


def _make_synthetic_daily(n_days=80, base=10000.0, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    close = base
    for i in range(n_days):
        d_open = close * (1 + rng.normal(0, 0.01))
        close = d_open * (1 + rng.normal(0, 0.015))
        rows.append({
            "stock_code": "TEST",
            "trade_date": f"2026{(1 + i // 30):02d}{((i % 30) + 1):02d}"[:8],
            "open": d_open,
            "high": max(d_open, close) * (1 + abs(rng.normal(0, 0.005))),
            "low": min(d_open, close) * (1 - abs(rng.normal(0, 0.005))),
            "close": close,
            "volume": float(rng.integers(50_000, 500_000)),
        })
    return pd.DataFrame(rows)


def _make_synthetic_minute(trade_dates, bars_per_day=390):
    rows = []
    for td in trade_dates:
        for i in range(bars_per_day):
            hh = 9 + i // 60
            mm = i % 60
            close = 10000.0 + i * 0.1
            rows.append({
                "stock_code": "TEST",
                "trade_date": td,
                "trade_time": f"{hh:02d}{mm:02d}00",
                "open": close, "high": close * 1.001, "low": close * 0.999,
                "close": close, "volume": 1000.0,
            })
    return pd.DataFrame(rows)


def audit_strategy(strategy_class, params, target_idx_in_minute, target_trade_date):
    """전략 인스턴스에 대해 daily 교란 검증.

    Args:
        target_idx_in_minute: prepare_features 결과 DF 의 row index 검증할 위치
        target_trade_date: 그 시점의 trade_date (교란 시작점)
    """
    s = strategy_class(**params)
    daily = _make_synthetic_daily(n_days=80, seed=42)
    trade_dates = sorted(daily["trade_date"].unique())[-30:]  # 최근 30 거래일 분봉
    minute = _make_synthetic_minute(trade_dates)

    # full
    feats_full = s.prepare_features(minute, daily)
    if feats_full is None or len(feats_full) <= target_idx_in_minute:
        return ("SKIP", "결과 row 부족")

    full_row = feats_full.iloc[target_idx_in_minute].to_dict()

    # perturbed: target_trade_date 이상의 daily rows 교란 (high/low/close/open/volume)
    perturbed = daily.copy()
    rng = np.random.default_rng(99)
    mask = perturbed["trade_date"] >= target_trade_date
    n_change = int(mask.sum())
    for col in ["open", "high", "low", "close", "volume"]:
        perturbed.loc[mask, col] = rng.uniform(1e6, 1e7, size=n_change)

    feats_pert = s.prepare_features(minute, perturbed)
    pert_row = feats_pert.iloc[target_idx_in_minute].to_dict()

    # 각 컬럼 비교 — 동일해야 통과
    failures = []
    for col, v_full in full_row.items():
        v_pert = pert_row.get(col)
        a_nan = pd.isna(v_full) if not isinstance(v_full, (int, float, str)) or isinstance(v_full, str) else (
            pd.isna(v_full) if not isinstance(v_full, str) else False
        )
        b_nan = pd.isna(v_pert) if v_pert is not None else True
        if a_nan and b_nan:
            continue
        try:
            if abs(float(v_full) - float(v_pert)) > 1e-6:
                failures.append((col, v_full, v_pert))
        except (TypeError, ValueError):
            if v_full != v_pert:
                failures.append((col, v_full, v_pert))
    return ("PASS" if not failures else "FAIL", failures)


def main():
    print("=== Stage 2 winning params look-ahead audit ===\n")
    print("방법: target_trade_date 이상의 daily row 값을 1e6~1e7 랜덤으로 교란 후")
    print("       해당 시점 prev_* 피처가 변하지 않는지 검증\n")

    strategy_map = {
        "macd_cross": MACDCrossStrategy,
        "close_to_open": CloseToOpenStrategy,
        "breakout_52w": Breakout52wStrategy,
        "trend_followthrough": TrendFollowthroughStrategy,
        "limit_up_chase": LimitUpChaseStrategy,
    }

    stage2_dir = Path("backtests/reports/stage2")
    for name, cls in strategy_map.items():
        best_path = stage2_dir / f"{name}_best.json"
        if not best_path.exists():
            print(f"  {name}: best.json 없음 → skip")
            continue
        d = json.loads(best_path.read_text(encoding="utf-8"))
        params = d["best_params"]

        # 분봉 마지막 trade_date 의 첫 bar (target_idx ~= 29 * 390)
        # 최근 30 거래일 중 25번째 거래일 = idx 24 * 390 정도
        target_idx = 24 * 390
        # 교란 시작 trade_date 도 최근 30 일 중 25번째
        target_date = sorted(_make_synthetic_daily(80, seed=42)["trade_date"].unique())[-6]
        try:
            status, detail = audit_strategy(cls, params, target_idx, target_date)
        except Exception as e:
            status, detail = ("ERROR", str(e))
        print(f"  {name:<22} best_params: {params}")
        if status == "PASS":
            print(f"      ✅ PASS — daily 피처 모든 컬럼 시점 교란에 불변")
        elif status == "FAIL":
            print(f"      ❌ FAIL — 교란 후 값 변경:")
            for col, v_f, v_p in detail[:5]:
                print(f"        {col}: full={v_f} pert={v_p}")
        elif status == "ERROR":
            print(f"      ⚠️ ERROR — {detail}")
        else:
            print(f"      SKIP — {detail}")
        print()


if __name__ == "__main__":
    main()
