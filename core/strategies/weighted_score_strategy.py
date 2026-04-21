"""Weighted Score 전략 (Trial #1600 파라미터).

`analysis/research/weighted_score/INTEGRATION_PLAN.md` 설계 구현.

**인터페이스**: trading_decision_engine 의 전략 공통 시그니처와 호환.
- `check_entry_conditions(...)`: 시간/요일/중복/워밍업 기본 게이트
- `check_advanced_conditions(df, candle_idx, stock_code=...)`: intraday 피처 + 가중 점수 > threshold_abs
- `check_exit_conditions(...)`: 고정 SL/TP (params.json 기반)
- `record_trade(...)`: 당일 거래 기록

**추가 인터페이스** (WeightedScore 고유):
- `update_daily_features(stock_code, raw_daily)`: pre_market 에서 종목별 daily raw 피처 주입
- `update_past_volume_map(stock_code, map_by_idx)`: vol_ratio_5d 계산용
- `get_score(stock_code, df, candle_idx, day_open)`: 디버그용 현재 score 반환

**실거래 상태 저장** (정확성 보장):
- daily_raw_by_code: `{stock_code: {feature: raw}}`  — 장 시작 전 주입, 종일 불변
- past_volume_by_code: `{stock_code: {idx: avg_vol}}`
- daily_trades: `{trade_date: {stock_code}}`
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from core.strategies.weighted_score_features import (
    WeightedScoreParams,
    compute_intraday_raw,
    compute_score,
    normalize_feature_dict,
)


# 기본 워밍업 — ret_30min·realized_vol 계산에 필요한 분봉 하한
DEFAULT_MIN_BARS = 31   # ret_30min + realized_vol_30min 대비
DEFAULT_WARMUP_MINUTES = 30  # 09:30 이후부터 진입 허용 (워밍업)


class WeightedScoreStrategy:
    """가중 점수 기반 매매 전략."""

    # 클래스 레벨 기본 params 경로
    DEFAULT_PARAMS_PATH = (
        Path(__file__).resolve().parent / "weighted_score_params.json"
    )

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        logger=None,
        params_path: Optional[str | Path] = None,
    ):
        """
        Args:
            config: 오버라이드 설정 (예: max_positions 축소 운영).
            logger: 로거.
            params_path: weighted_score_params.json 경로.
        """
        self.logger = logger
        path = Path(params_path) if params_path else self.DEFAULT_PARAMS_PATH
        self.params = WeightedScoreParams.load(path)

        # 오버라이드
        overrides = config or {}
        self.max_positions_override = int(overrides.get("max_positions",
                                                         self.params.max_positions))
        self.stop_loss_override = float(overrides.get("stop_loss_pct",
                                                       self.params.stop_loss_pct))
        self.take_profit_override = float(overrides.get("take_profit_pct",
                                                         self.params.take_profit_pct))
        self.allowed_weekdays = list(overrides.get("allowed_weekdays", [0, 1, 2, 3, 4]))
        self.entry_start_hour = int(overrides.get("entry_start_hour", 9))
        self.entry_end_hour = int(overrides.get("entry_end_hour", 14))
        self.warmup_minutes = int(overrides.get("warmup_minutes", DEFAULT_WARMUP_MINUTES))
        self.min_bars = int(overrides.get("min_bars", DEFAULT_MIN_BARS))
        self.one_trade_per_stock_per_day = bool(
            overrides.get("one_trade_per_stock_per_day", True)
        )

        # 상태
        self.daily_raw_by_code: Dict[str, Dict[str, float]] = {}
        self.past_volume_by_code: Dict[str, Dict[int, float]] = {}
        self.daily_trades: Dict[str, set] = {}  # {trade_date: {stock_code}}

    # ------------- 로깅 -------------

    def _log(self, message: str, level: str = "info"):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message)
        else:
            print(f"[{level.upper()}] {message}")

    # ------------- 상태 관리 -------------

    def reset_daily_trades(self, trade_date: str = None):
        if trade_date:
            self.daily_trades.pop(trade_date, None)
        else:
            self.daily_trades.clear()

    def update_daily_features(self, stock_code: str, raw_daily: Dict[str, float]):
        """장 시작 전 종목별 daily raw 피처 12개 주입."""
        self.daily_raw_by_code[stock_code] = dict(raw_daily)

    def update_past_volume_map(self, stock_code: str, map_by_idx: Dict[int, float]):
        """vol_ratio_5d 계산용 — 최근 5일 idx별 평균 volume."""
        self.past_volume_by_code[stock_code] = dict(map_by_idx)

    def has_daily_features(self, stock_code: str) -> bool:
        return stock_code in self.daily_raw_by_code

    # ------------- 진입 조건 (기본 게이트) -------------

    def check_entry_conditions(
        self,
        stock_code: str,
        current_price: float,
        day_open: float,
        current_time: str,  # "HHMMSS" or "HHMM"
        trade_date: str,
        weekday: int = None,
    ) -> Tuple[bool, str]:
        """시간/요일/중복/daily feature 준비 여부 확인."""
        if day_open <= 0:
            return False, "시가 데이터 없음"

        if weekday is None:
            try:
                weekday = datetime.strptime(trade_date, "%Y%m%d").weekday()
            except Exception:
                return False, "날짜 파싱 실패"

        if weekday not in self.allowed_weekdays:
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return False, f"허용되지 않은 요일: {names[weekday]}"

        try:
            s = str(current_time).zfill(6)
            hh = int(s[0:2])
            mm = int(s[2:4])
        except Exception:
            return False, "시간 파싱 실패"

        if hh < self.entry_start_hour:
            return False, f"{self.entry_start_hour}시 이전"
        if hh >= self.entry_end_hour:
            return False, f"{self.entry_end_hour}시 이후"

        # 워밍업
        minutes_since_open = (hh - 9) * 60 + mm
        if minutes_since_open < self.warmup_minutes:
            return False, f"워밍업 구간 (장 시작 {minutes_since_open}분)"

        # 당일 중복 거래
        if self.one_trade_per_stock_per_day:
            if trade_date in self.daily_trades:
                if stock_code in self.daily_trades[trade_date]:
                    return False, "당일 이미 거래함"

        # daily 피처 준비
        if not self.has_daily_features(stock_code):
            return False, "daily 피처 미준비 (pre_market 계산 필요)"

        return True, "기본 게이트 통과"

    # ------------- 고급 조건 (score 계산) -------------

    def check_advanced_conditions(
        self,
        df: pd.DataFrame,
        candle_idx: int,
        stock_code: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """현재 분봉까지의 데이터로 score 계산 → threshold_abs 비교."""
        if stock_code is None:
            return False, "stock_code 누락 (WeightedScore 는 종목별 daily 피처 필요)"

        if candle_idx < self.min_bars - 1:
            return False, f"분봉 부족: {candle_idx + 1} < {self.min_bars}"

        if df is None or len(df) == 0:
            return False, "분봉 DF 없음"

        # 현재까지의 bars slice
        sub = df.iloc[: candle_idx + 1]
        if "trade_date" not in sub.columns or "idx" not in sub.columns:
            return False, "분봉 컬럼 미비 (trade_date/idx)"

        # day_open
        same_day = sub[sub["trade_date"] == sub.iloc[-1]["trade_date"]]
        if same_day.empty:
            return False, "당일 bars 없음"
        day_open = float(same_day.iloc[0]["open"])
        if day_open <= 0:
            return False, "day_open 무효"

        # intraday raw 계산
        past_vol_map = self.past_volume_by_code.get(stock_code)
        intraday_raw = compute_intraday_raw(
            bars=same_day,
            day_open=day_open,
            past_volume_by_idx=past_vol_map,
        )

        # daily raw + intraday raw 병합
        daily_raw = self.daily_raw_by_code.get(stock_code, {})
        all_raw: Dict[str, float] = {}
        all_raw.update(daily_raw)
        all_raw.update(intraday_raw)

        # 사용되는 피처가 모두 있는지
        missing = [
            n for n in self.params.feature_names
            if abs(self.params.weights.get(n, 0.0)) > 1e-12 and n not in all_raw
        ]
        if missing:
            return False, f"피처 누락: {missing[:3]}..."

        # 정규화
        normalized = normalize_feature_dict(all_raw, self.params)

        # score
        score = compute_score(normalized, self.params)
        if math.isnan(score):
            # 어느 피처가 NaN 인지 찾기
            nan_feats = [
                n for n in self.params.feature_names
                if abs(self.params.weights.get(n, 0.0)) > 1e-12
                and (math.isnan(normalized.get(n, float("nan"))))
            ]
            return False, f"score NaN (NaN 피처: {nan_feats[:3]}...)"

        if score <= self.params.threshold_abs:
            return False, f"score {score:+.4f} ≤ threshold {self.params.threshold_abs:+.4f}"

        return True, f"score {score:+.4f} > threshold {self.params.threshold_abs:+.4f}"

    # ------------- 거래 기록 -------------

    def record_trade(self, stock_code: str, trade_date: str):
        if trade_date not in self.daily_trades:
            self.daily_trades[trade_date] = set()
        self.daily_trades[trade_date].add(stock_code)

    # ------------- 청산 조건 -------------

    def check_exit_conditions(
        self,
        entry_price: float,
        current_high: float,
        current_low: float,
        current_close: float,
    ) -> Tuple[bool, str, float]:
        """장중 청산 판단 (SL/TP 만, max_hold 는 엔진 측에서 관리)."""
        if entry_price <= 0:
            return False, "진입가 없음", 0.0

        tp = self.take_profit_override
        sl = self.stop_loss_override

        # 고가 기준 TP
        high_pnl = (current_high / entry_price - 1) * 100
        if high_pnl >= tp:
            return True, "익절", tp

        # 저가 기준 SL
        low_pnl = (current_low / entry_price - 1) * 100
        if low_pnl <= sl:
            return True, "손절", sl

        return False, "홀딩", (current_close / entry_price - 1) * 100

    # ------------- 디버그 / 정보 -------------

    def get_score(
        self,
        stock_code: str,
        df: pd.DataFrame,
        candle_idx: int,
    ) -> Optional[float]:
        """디버그용 현재 score 반환 (threshold 통과 여부 무관)."""
        if stock_code not in self.daily_raw_by_code:
            return None
        if df is None or candle_idx < 0:
            return None
        sub = df.iloc[: candle_idx + 1]
        same_day = sub[sub["trade_date"] == sub.iloc[-1]["trade_date"]]
        if same_day.empty:
            return None
        day_open = float(same_day.iloc[0]["open"])
        intraday_raw = compute_intraday_raw(
            same_day, day_open, self.past_volume_by_code.get(stock_code)
        )
        all_raw = {**self.daily_raw_by_code[stock_code], **intraday_raw}
        normalized = normalize_feature_dict(all_raw, self.params)
        s = compute_score(normalized, self.params)
        return None if math.isnan(s) else s

    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "name": "WeightedScoreStrategy",
            "description": "연구용 가중 점수 전략 (Trial #1600, test Calmar 162.75)",
            "entry_conditions": {
                "threshold_abs": self.params.threshold_abs,
                "entry_pct": self.params.entry_pct,
                "max_positions": self.max_positions_override,
                "warmup_minutes": self.warmup_minutes,
                "time_range": f"{self.entry_start_hour}~{self.entry_end_hour}시",
            },
            "exit_conditions": {
                "stop_loss": f"{self.stop_loss_override}%",
                "take_profit": f"+{self.take_profit_override}%",
                "max_holding_days": self.params.max_holding_days,
            },
            "source": {
                "trial": self.params.meta.get("trial_number"),
                "study": self.params.meta.get("study_name"),
                "phase_a": self.params.meta.get("phase_a_run"),
                "test_calmar_reported": 162.75,
            },
            "n_features": len(self.params.feature_names),
            "weights_non_zero": sum(1 for w in self.params.weights.values() if abs(w) > 1e-9),
        }

    def __repr__(self):
        return (f"WeightedScoreStrategy(threshold={self.params.threshold_abs:+.4f}, "
                f"max_pos={self.max_positions_override}, "
                f"SL={self.stop_loss_override}, TP={self.take_profit_override})")
