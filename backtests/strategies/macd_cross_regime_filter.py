"""macd_cross 에 KOSPI MA20 regime filter 를 얹은 백테스트 wrapper.

본체 backtests/strategies/macd_cross.py 는 라이브 동등성 보호 위해 미수정.
filter 활성 시 KOSPI close < MA20 (전일 기준, lookahead 방지) 인 날 entry 차단.
"""
from typing import Optional

import pandas as pd

from backtests.common.feature_cache import get_arrays
from backtests.strategies.base import EntryOrder
from backtests.strategies.macd_cross import MACDCrossStrategy

SIGNAL_TYPES = (
    "ma20_below_prev",
    "ma20_and_ma5_below",
    "5d_return_drop",
    "20d_return_neg",
)


class MACDCrossRegimeFilterStrategy(MACDCrossStrategy):
    """KOSPI regime filter overlay.

    Args:
        regime_filter_enabled: True 면 signal_type 에 따라 entry block.
        kospi_daily_df: KOSPI 일봉 DataFrame (trade_date YYYYMMDD str, close float).
            None 이고 regime_filter_enabled=True 면 ValueError.
        signal_type: 어떤 신호로 차단할지. SIGNAL_TYPES 중 하나.
        signal_threshold: return 기반 신호의 임계값 (None 이면 signal_type 별 default).
        ma_period: MA 장기 window (ma20_below_prev / ma20_and_ma5_below 용).
        ma_short_period: MA 단기 window (ma20_and_ma5_below 용).
    """
    name = "macd_cross_regime_filter"

    def __init__(
        self,
        regime_filter_enabled: bool = False,
        kospi_daily_df: Optional[pd.DataFrame] = None,
        signal_type: str = "ma20_below_prev",
        signal_threshold: Optional[float] = None,
        ma_period: int = 20,
        ma_short_period: int = 5,
        **kwargs,
    ):
        super().__init__(**kwargs)
        if signal_type not in SIGNAL_TYPES:
            raise ValueError(
                f"unknown signal_type: {signal_type!r}, "
                f"expected one of {SIGNAL_TYPES}"
            )
        self.regime_filter_enabled = regime_filter_enabled
        self.kospi_daily_df = kospi_daily_df
        self.signal_type = signal_type
        self.signal_threshold = signal_threshold
        self.ma_period = ma_period
        self.ma_short_period = ma_short_period
        if regime_filter_enabled and kospi_daily_df is None:
            raise ValueError(
                "regime_filter_enabled=True 인데 kospi_daily_df 가 None"
            )

    def compute_block_series(self, kospi: pd.DataFrame) -> pd.Series:
        """signal_type 분기 → 'below_prev' boolean Series 반환.

        Args:
            kospi: KOSPI daily DataFrame, **assumed sorted by trade_date with
                reset RangeIndex** (caller responsibility). 정렬 안 된 입력 시
                결과가 잘못됨.

        Returns:
            boolean Series, index = RangeIndex same as input. True 인 행의
            date 에는 진입 차단해야 함.

        shift(1) 명시 적용으로 D 일 신호는 D-1 까지 데이터만 의존 (lookahead 0).
        """
        if self.signal_type == "ma20_below_prev":
            ma = kospi["close"].rolling(self.ma_period).mean()
            cond = kospi["close"] < ma
        elif self.signal_type == "ma20_and_ma5_below":
            ma_long = kospi["close"].rolling(self.ma_period).mean()
            ma_short = kospi["close"].rolling(self.ma_short_period).mean()
            cond = (kospi["close"] < ma_long) & (ma_short < ma_long)
        elif self.signal_type == "5d_return_drop":
            thr = self.signal_threshold if self.signal_threshold is not None else -0.03
            ret5 = kospi["close"] / kospi["close"].shift(5) - 1
            cond = ret5 <= thr
        else:
            raise NotImplementedError(
                f"signal_type {self.signal_type!r} 는 아직 미구현. "
                f"현재 지원: 'ma20_below_prev', 'ma20_and_ma5_below'"
            )
        return cond.fillna(False).astype(bool).shift(1).fillna(False).astype(bool)

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        feat = super().prepare_features(df_minute, df_daily).copy()
        if not self.regime_filter_enabled:
            return feat
        if df_minute.empty:
            return feat

        ks_sorted = self.kospi_daily_df.sort_values("trade_date").reset_index(drop=True)
        below_prev = self.compute_block_series(ks_sorted)
        block_map = dict(zip(ks_sorted["trade_date"].astype(str), below_prev))

        feat["kospi_below_ma20"] = (
            df_minute["trade_date"].astype(str)
            .map(block_map).fillna(False).astype(bool).values
        )
        return feat

    def entry_signal(
        self, features: pd.DataFrame, bar_idx: int, stock_code: str
    ) -> Optional[EntryOrder]:
        if self.regime_filter_enabled and "kospi_below_ma20" in features.columns:
            arr = get_arrays(features)
            if bool(arr["kospi_below_ma20"][bar_idx]):
                return None  # filter block
        return super().entry_signal(features, bar_idx, stock_code)
