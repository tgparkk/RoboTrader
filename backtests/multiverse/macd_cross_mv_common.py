"""macd_cross 멀티버스 공통 유틸 — KPI extras, dataset 로더, cell evaluator."""
from typing import Iterable

import pandas as pd


def compute_top1_share(trade_pnls: pd.Series) -> float:
    """단일 최대 P&L / 전체 net 합 (signed). PHASE6 OOS 와 동일 정의.

    분모는 net (signed) sum 이므로 sum<0 일 때 share 도 음수가 될 수 있다.
    거래 0 또는 sum=0 시 0.0 반환.
    """
    if len(trade_pnls) == 0:
        return 0.0
    total = float(trade_pnls.sum())
    if total == 0:
        return 0.0
    return float(trade_pnls.max() / total)


def compute_max_consec_loss(trade_pnls: Iterable[float]) -> int:
    """시간순 trade pnl 시퀀스에서 음수 연속 카운트 최댓값.

    pnl == 0 은 streak 를 끊는 (loss 가 아님) 것으로 처리.
    """
    max_run = 0
    cur_run = 0
    for p in trade_pnls:
        if p < 0:
            cur_run += 1
            if cur_run > max_run:
                max_run = cur_run
        else:
            cur_run = 0
    return max_run
