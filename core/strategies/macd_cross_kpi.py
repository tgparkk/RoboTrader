"""macd_cross 페이퍼 KPI 집계 + 6 승격 게이트 평가.

Spec §3: KPI 정의 + 게이트 임계값 (return/calmar/mdd/win/top1/consec_loss).
Spec §3 중도 안전 정지: 누적 -5% 또는 연속 손실 5건.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


# Spec §3 게이트 임계값 (모두 충족 시 승격 단계 회의 진입)
GATE_THRESHOLDS = {
    "calmar": {"min": 30.0, "label": "Calmar ≥ 30"},
    "return": {"min": 0.0, "label": "return ≥ 0"},
    "mdd": {"max_abs": 0.05, "label": "MDD ≤ 5%"},
    "win_rate": {"min": 0.50, "label": "승률 ≥ 50%"},
    "top1_share": {"max": 0.60, "label": "top1 share ≤ 60%"},
    "max_consec_losses": {"max": 4, "label": "max consec losses ≤ 4"},
}

# 중도 안전 정지 임계값 (paper 자동 중단 권고)
SAFETY_STOP = {
    "cumulative_loss_pct": -0.05,    # 누적 -5%
    "max_consec_losses": 5,          # 연속 5패
}


class MacdCrossKpi:
    """KPI 집계 + 게이트 평가. 입력: 가상매매 trade rows."""

    def __init__(self, virtual_capital: float):
        self.virtual_capital = float(virtual_capital)

    def compute(self, df_trades: pd.DataFrame) -> Dict:
        """trade rows (BUY-SELL pair 의 pnl) → KPI 딕셔너리.

        Args:
            df_trades: 컬럼 = ['buy_time', 'sell_time', 'pnl']. sell_time 오름차순.
        """
        if df_trades is None or df_trades.empty:
            return {
                "trade_count": 0, "return": 0.0, "mdd": 0.0,
                "calmar": 0.0, "win_rate": 0.0, "top1_share": 0.0,
                "max_consec_losses": 0,
            }
        df = df_trades.sort_values("sell_time").reset_index(drop=True)
        pnl = df["pnl"].astype(float).to_numpy()
        n = len(pnl)
        net = float(pnl.sum())
        ret = net / self.virtual_capital

        # MDD on cumulative pnl curve
        cum = np.cumsum(pnl)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / self.virtual_capital
        mdd = float(dd.min()) if len(dd) > 0 else 0.0

        # Calmar (annualized). 영업일수 = (sell_time max - buy_time min) 의 영업일.
        buy_min = pd.to_datetime(df["buy_time"].min()).date()
        sell_max = pd.to_datetime(df["sell_time"].max()).date()
        biz_days = max(1, int(np.busday_count(buy_min, sell_max)))
        annualized = ret * (252.0 / biz_days)
        calmar = annualized / abs(mdd) if abs(mdd) > 1e-9 else 0.0

        # Win rate
        win_rate = float((pnl > 0).sum() / n)

        # top1 share: 최대 양수 trade 의 net 점유율
        positives = pnl[pnl > 0]
        if len(positives) > 0 and abs(net) > 1e-9:
            top1_share = float(positives.max() / net)
        else:
            top1_share = 0.0

        # max consecutive losses
        max_streak = 0
        current = 0
        for v in pnl:
            if v < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0

        return {
            "trade_count": n, "return": ret, "mdd": mdd,
            "calmar": float(calmar), "win_rate": win_rate,
            "top1_share": top1_share, "max_consec_losses": int(max_streak),
        }

    def evaluate_gates(self, metrics: Dict) -> Dict:
        """6 게이트 평가. 모두 통과 시 all_pass=True."""
        gates = {}
        gates["calmar"] = {
            "pass": metrics["calmar"] >= GATE_THRESHOLDS["calmar"]["min"],
            "value": metrics["calmar"], "label": GATE_THRESHOLDS["calmar"]["label"],
        }
        gates["return"] = {
            "pass": metrics["return"] >= GATE_THRESHOLDS["return"]["min"],
            "value": metrics["return"], "label": GATE_THRESHOLDS["return"]["label"],
        }
        gates["mdd"] = {
            "pass": abs(metrics["mdd"]) <= GATE_THRESHOLDS["mdd"]["max_abs"],
            "value": metrics["mdd"], "label": GATE_THRESHOLDS["mdd"]["label"],
        }
        gates["win_rate"] = {
            "pass": metrics["win_rate"] >= GATE_THRESHOLDS["win_rate"]["min"],
            "value": metrics["win_rate"], "label": GATE_THRESHOLDS["win_rate"]["label"],
        }
        gates["top1_share"] = {
            "pass": metrics["top1_share"] <= GATE_THRESHOLDS["top1_share"]["max"],
            "value": metrics["top1_share"], "label": GATE_THRESHOLDS["top1_share"]["label"],
        }
        gates["max_consec_losses"] = {
            "pass": metrics["max_consec_losses"] <= GATE_THRESHOLDS["max_consec_losses"]["max"],
            "value": metrics["max_consec_losses"],
            "label": GATE_THRESHOLDS["max_consec_losses"]["label"],
        }
        all_pass = all(g["pass"] for g in gates.values())
        return {"all_pass": all_pass, "gates": gates}

    def should_safety_stop(self, metrics: Dict) -> bool:
        """중도 안전 정지 충족 여부."""
        if metrics.get("return", 0) <= SAFETY_STOP["cumulative_loss_pct"]:
            return True
        if metrics.get("max_consec_losses", 0) >= SAFETY_STOP["max_consec_losses"]:
            return True
        return False
