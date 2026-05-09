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
    """KOSPI MA20 regime filter overlay.

    Args:
        regime_filter_enabled: True 면 KOSPI close < MA20 (전일) 인 날 entry block.
        kospi_daily_df: KOSPI 일봉 DataFrame (columns: trade_date YYYYMMDD str, close float).
            None 이고 regime_filter_enabled=True 면 ValueError.
        ma_period: MA window. 기본 20.
    """
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
        if regime_filter_enabled and kospi_daily_df is None:
            raise ValueError(
                "regime_filter_enabled=True 인데 kospi_daily_df 가 None"
            )

    def prepare_features(
        self, df_minute: pd.DataFrame, df_daily: pd.DataFrame
    ) -> pd.DataFrame:
        feat = super().prepare_features(df_minute, df_daily).copy()
        if not self.regime_filter_enabled:
            return feat
        if df_minute.empty:
            return feat
        # Task 2 에서 채울 자리
        return feat
