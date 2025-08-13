"""
눌림목 캔들패턴 지표 (3분봉 권장)
주가 상승 후 저거래 조정(기준 거래량의 1/4) → 회복 양봉에서 거래량 회복 → 이등분선 지지/회복 확인
손절: 진입 양봉 저가 0.2% 이탈, 또는 이등분선 기준 아래로 0.2% 이탈, 또는 지지 저점 이탈
익절: 매수가 대비 +3%
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from core.indicators.bisector_line import BisectorLine


@dataclass
class VolumeAnalysis:
    """거래량 분석 결과"""
    baseline_volume: float  # 기준 거래량 (당일 최대량)
    current_volume: float   # 현재 거래량
    avg_recent_volume: float  # 최근 평균 거래량
    volume_trend: str      # 'increasing', 'decreasing', 'stable'
    is_volume_surge: bool  # 거래량 급증 여부
    is_low_volume: bool    # 저거래량 여부 (기준의 1/4 이하)
    is_high_volume: bool   # 고거래량 여부 (기준의 1/2 이상)


@dataclass
class CandleAnalysis:
    """캔들 분석 결과"""
    current_candle_size: float    # 현재 캔들 크기 (high-low)
    avg_recent_candle_size: float # 최근 평균 캔들 크기
    candle_trend: str            # 'expanding', 'shrinking', 'stable'
    is_small_candle: bool        # 작은 캔들 여부
    is_large_candle: bool        # 큰 캔들 여부


class PullbackCandlePattern:
    """눌림목 캔들패턴 분석기"""
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10) -> VolumeAnalysis:
        """거래량 분석"""
        if 'volume' not in data.columns or len(data) < period:
            return VolumeAnalysis(0, 0, 0, 'stable', False, False, False)
        
        volumes = data['volume'].values
        current_volume = volumes[-1]
        
        # 기준 거래량: 당일 최대 거래량 (최근 50봉 중)
        baseline_volume = np.max(volumes[-min(50, len(volumes)):])
        
        # 최근 평균 거래량
        avg_recent_volume = np.mean(volumes[-period:])
        
        # 거래량 추세 분석
        if len(volumes) >= 3:
            recent_3 = volumes[-3:]
            if recent_3[-1] > recent_3[-2] > recent_3[-3]:
                volume_trend = 'increasing'
            elif recent_3[-1] < recent_3[-2] < recent_3[-3]:
                volume_trend = 'decreasing'
            else:
                volume_trend = 'stable'
        else:
            volume_trend = 'stable'
        
        # 거래량 상태 분석
        is_volume_surge = current_volume > avg_recent_volume * 1.5
        is_low_volume = current_volume < baseline_volume * 0.25  # 기준의 1/4 이하
        is_high_volume = current_volume > baseline_volume * 0.5  # 기준의 1/2 이상
        
        return VolumeAnalysis(
            baseline_volume=baseline_volume,
            current_volume=current_volume,
            avg_recent_volume=avg_recent_volume,
            volume_trend=volume_trend,
            is_volume_surge=is_volume_surge,
            is_low_volume=is_low_volume,
            is_high_volume=is_high_volume
        )
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10) -> CandleAnalysis:
        """캔들 분석"""
        if len(data) < period:
            return CandleAnalysis(0, 0, 'stable', False, False)
        
        # 캔들 크기 계산 (high - low)
        candle_sizes = data['high'].values - data['low'].values
        current_candle_size = candle_sizes[-1]
        avg_recent_candle_size = np.mean(candle_sizes[-period:])
        
        # 캔들 크기 추세 분석
        if len(candle_sizes) >= 3:
            recent_3 = candle_sizes[-3:]
            if recent_3[-1] > recent_3[-2] > recent_3[-3]:
                candle_trend = 'expanding'
            elif recent_3[-1] < recent_3[-2] < recent_3[-3]:
                candle_trend = 'shrinking'
            else:
                candle_trend = 'stable'
        else:
            candle_trend = 'stable'
        
        # 캔들 크기 상태
        is_small_candle = current_candle_size < avg_recent_candle_size * 0.7
        is_large_candle = current_candle_size > avg_recent_candle_size * 1.3
        
        return CandleAnalysis(
            current_candle_size=current_candle_size,
            avg_recent_candle_size=avg_recent_candle_size,
            candle_trend=candle_trend,
            is_small_candle=is_small_candle,
            is_large_candle=is_large_candle
        )
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위에 있는지 확인"""
        try:
            from core.indicators.bisector_line import BisectorLine
            bisector_signals = BisectorLine.generate_trading_signals(data)
            return bisector_signals['bullish_zone'].iloc[-1]
        except:
            return False
    
    @staticmethod
    def check_price_trend(data: pd.DataFrame, period: int = 10) -> str:
        """주가 추세 확인"""
        if len(data) < period:
            return 'stable'
        
        closes = data['close'].values
        recent_closes = closes[-period:]
        
        # 선형 회귀로 추세 판단
        x = np.arange(len(recent_closes))
        slope = np.polyfit(x, recent_closes, 1)[0]
        
        if slope > 0:
            return 'uptrend'
        elif slope < 0:
            return 'downtrend'
        else:
            return 'stable'
    
    @staticmethod
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기 (최근 5개 봉)"""
        if len(data) < period:
            return None
        
        recent_lows = data['low'].values[-period:]
        return np.min(recent_lows)
    
    @staticmethod
    def generate_trading_signals(
        data: pd.DataFrame,
        *,
        enable_candle_shrink_expand: bool = False,
        enable_divergence_precondition: bool = False,
        enable_overhead_supply_filter: bool = False,
        candle_expand_multiplier: float = 1.10,
        overhead_lookback: int = 10,
        overhead_threshold_hits: int = 2,
    ) -> pd.DataFrame:
        """눌림목 캔들패턴 매매 신호 생성 (3분봉 권장)

        반환 컬럼:
        - buy_pullback_pattern: 저거래 조정 후 회복 양봉 매수
        - buy_bisector_recovery: 이등분선 회복/상향 돌파 매수
        - sell_bisector_break: 이등분선 기준 아래로 0.2% 이탈
        - sell_support_break: 최근 저점 이탈
        - stop_entry_low_break: 진입 양봉 저가 0.2% 이탈
        - take_profit_3pct: 매수가 대비 +3% 도달
        - bisector_line: 이등분선 값(보조)
        """
        try:
            if data is None or data.empty or len(data) < 10:
                return pd.DataFrame()

            df = data.copy()
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                return pd.DataFrame()

            # 이등분선(누적 고/저가 기반)
            bisector_line = BisectorLine.calculate_bisector_line(df['high'], df['low'])

            signals = pd.DataFrame(index=df.index)
            signals['buy_pullback_pattern'] = False
            signals['buy_bisector_recovery'] = False
            signals['sell_bisector_break'] = False
            signals['sell_support_break'] = False
            signals['stop_entry_low_break'] = False
            signals['take_profit_3pct'] = False
            signals['bisector_line'] = bisector_line

            # 파라미터 (완화 적용)
            retrace_lookback = 1      # 저거래 조정 연속 봉 (기존 3 → 2)
            low_vol_ratio = 0.25      # 기준 거래량의 25% 
            stop_leeway = 0.002       # 0.2%
            take_profit = 0.02        # +2%

            # 기준 거래량(최근 50봉 최대)을 시계열로 계산
            rolling_baseline = df['volume'].rolling(window=min(50, len(df)), min_periods=1).max()

            # 포지션 추적(차트 표시용 시뮬레이션)
            in_position = False
            entry_price = None
            entry_low = None

            # 캔들 크기(고-저) 사전 계산
            candle_sizes = (df['high'] - df['low']).astype(float)
            closes = df['close'].astype(float)
            volumes = df['volume'].astype(float)

            for i in range(len(df)):
                if i < retrace_lookback + 2:
                    continue

                current = df.iloc[i]
                bl = bisector_line.iloc[i] if not pd.isna(bisector_line.iloc[i]) else None
                # 위/아래 판단 (pullback 용도): 종가가 이등분선 이상이면 위로 간주
                above_bisector = (bl is not None) and (current['close'] >= bl)
                # 이등분선 회복(매수) 엄격 조건: 종가가 이등분선을 '넘어야' 함(>)
                crosses_bisector_up = (bl is not None) and (current['open'] <= bl and current['close'] > bl)

                # 최근 저점(최근 5봉 저가 최저)
                recent_low = float(df['low'].iloc[max(0, i-5):i+1].min())

                # 최근 N봉 저거래 하락 조정
                window = df.iloc[i - retrace_lookback:i]
                baseline_now = rolling_baseline.iloc[i]
                low_volume_all = (window['volume'] < baseline_now * low_vol_ratio).all()
                downtrend_all = (window['close'].diff().fillna(0) < 0).iloc[1:].all()
                is_low_volume_retrace = low_volume_all and downtrend_all

                # 회복 양봉 + 거래량 회복
                is_bullish = current['close'] > current['open']
                max_low_vol = float(window['volume'].max())
                avg_recent_vol = float(df['volume'].iloc[max(0, i-10):i].mean()) if i > 0 else 0.0
                volume_recovers = (current['volume'] > max_low_vol) or (current['volume'] > avg_recent_vol)

                # 옵션: 가격↑·거래량↓ 발산(배경) 조건
                divergence_ok = True
                if enable_divergence_precondition and i >= 20:
                    try:
                        x = np.arange(20)
                        price_window = closes.iloc[i-19:i+1].values
                        vol_window = volumes.iloc[i-19:i+1].values
                        price_slope = np.polyfit(x, price_window, 1)[0]
                        vol_slope = np.polyfit(x, vol_window, 1)[0]
                        divergence_ok = (price_slope > 0) and (vol_slope < 0)
                    except Exception:
                        divergence_ok = False

                # 옵션: 캔들 축소→확대 패턴
                shrink_expand_ok = True
                if enable_candle_shrink_expand and i >= max(retrace_lookback + 2, 10):
                    recent_avg_size = float(candle_sizes.iloc[max(0, i-10):i].mean()) if i > 0 else 0.0
                    # 조정 구간의 작은 캔들(축소) 확인
                    shrink_ok = True
                    try:
                        shrink_window = candle_sizes.iloc[i - retrace_lookback:i]
                        shrink_ok = bool((shrink_window < recent_avg_size * 0.9).all()) if recent_avg_size > 0 else False
                    except Exception:
                        shrink_ok = False
                    # 현재 봉의 확대 + 최근 3봉 크기 증가 추세
                    try:
                        expand_now = candle_sizes.iloc[i] > recent_avg_size * candle_expand_multiplier
                        inc_trend = True
                        if i >= 2:
                            inc_trend = bool(candle_sizes.iloc[i-2] <= candle_sizes.iloc[i-1] <= candle_sizes.iloc[i])
                        shrink_expand_ok = shrink_ok and expand_now and inc_trend
                    except Exception:
                        shrink_expand_ok = False

                # 옵션: 오버헤드 서플라이(하락봉에서 기준의 1/2 이상 거래량 반복) 필터
                allow_signal = True
                if enable_overhead_supply_filter and i >= 1:
                    try:
                        lb = max(0, i - overhead_lookback)
                        down_mask = (closes.diff().iloc[lb:i] < 0)
                        baseline_now = float(rolling_baseline.iloc[i]) if not pd.isna(rolling_baseline.iloc[i]) else 0.0
                        vol_mask = (volumes.iloc[lb:i] >= baseline_now * 0.5) if baseline_now > 0 else (volumes.iloc[lb:i] > 0)
                        hits = int((down_mask & vol_mask).sum())
                        if hits >= overhead_threshold_hits:
                            allow_signal = False
                    except Exception:
                        allow_signal = True

                # 대안 진입 조건: "직전 강한 양봉의 1/2 구간 되돌림" 확인
                # 최근 6개의 봉에서 강한 양봉(몸통이 최근 평균 대비 크고, 거래량이 평균 이상)을 찾음
                recent_start = max(0, i-12)
                recent_range = df.iloc[recent_start:i]
                half_retrace_ok = False
                if len(recent_range) > 0:
                    recent_candle_size = (recent_range['high'] - recent_range['low']).mean()
                    recent_vol_mean = recent_range['volume'].mean()
                    impulse_idx = None
                    for j in range(i-1, recent_start-1, -1):
                        if j < 0:
                            break
                        open_j = float(df['open'].iloc[j])
                        close_j = float(df['close'].iloc[j])
                        high_j = float(df['high'].iloc[j])
                        low_j = float(df['low'].iloc[j])
                        vol_j = float(df['volume'].iloc[j])
                        body = abs(close_j - open_j)
                        size = high_j - low_j
                        # 완화: 최근 평균 대비 0.8배 이상 몸통, 거래량 0.8배 이상
                        if close_j > open_j and size > 0 and body >= recent_candle_size * 0.8 and vol_j >= recent_vol_mean * 0.8:
                            impulse_idx = j
                            break
                    if impulse_idx is not None:
                        ih = float(df['high'].iloc[impulse_idx])
                        il = float(df['low'].iloc[impulse_idx])
                        half_point = il + (ih - il) * 0.5
                        # 현재 캔들이 절반값 근처이거나, 저가가 하회 후 회복해 종가가 절반 이상
                        eps = max(half_point * 0.01, 1.0)  # 1.0% 또는 1원 허용 (완화)
                        cur_low = float(current['low'])
                        cur_close = float(current['close'])
                        if (abs(cur_close - half_point) <= eps) or (cur_low <= half_point <= cur_close):
                            half_retrace_ok = True

                if not in_position:
                    # 매수 신호 1: 저거래 조정 후 회복 양봉(+이등분선 지지/회복)
                    # 또는 강한 양봉의 1/2 되돌림 + 회복 양봉(+이등분선 지지/회복)
                    # 완화: 1/2 되돌림 케이스에서는 거래량 회복(volume_recovers)을 필수에서 제외
                    base_buy_pb = (
                        (is_low_volume_retrace and is_bullish and volume_recovers and (above_bisector or crosses_bisector_up))
                        or
                        (half_retrace_ok and is_bullish and (above_bisector or crosses_bisector_up))
                    )
                    if (
                        allow_signal and base_buy_pb and
                        (not enable_divergence_precondition or divergence_ok) and
                        (not enable_candle_shrink_expand or shrink_expand_ok)
                    ):
                        signals.iloc[i, signals.columns.get_loc('buy_pullback_pattern')] = True
                        in_position = True
                        entry_price = float(current['close'])
                        entry_low = float(current['low'])
                        continue

                    # 매수 신호 2: 이등분선 회복 양봉(종가가 이등분선을 넘어야 함) + 거래량 회복
                    if (
                        allow_signal and is_bullish and crosses_bisector_up and volume_recovers and
                        (not enable_divergence_precondition or divergence_ok) and
                        (not enable_candle_shrink_expand or shrink_expand_ok)
                    ):
                        signals.iloc[i, signals.columns.get_loc('buy_bisector_recovery')] = True
                        in_position = True
                        entry_price = float(current['close'])
                        entry_low = float(current['low'])
                        continue
                else:
                    # 손절/익절 신호
                    # 이등분선 이탈: 이등분선 기준 아래로 0.2% 이탈 시 매도
                    if bl is not None and current['close'] < bl * (1.0 - 0.002):
                        signals.iloc[i, signals.columns.get_loc('sell_bisector_break')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

                    if current['close'] < recent_low:
                        signals.iloc[i, signals.columns.get_loc('sell_support_break')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

                    if entry_low is not None and current['close'] <= entry_low * (1.0 - stop_leeway):
                        signals.iloc[i, signals.columns.get_loc('stop_entry_low_break')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

                    if entry_price is not None and current['close'] >= entry_price * (1.0 + take_profit):
                        signals.iloc[i, signals.columns.get_loc('take_profit_3pct')] = True
                        in_position = False
                        entry_price = None
                        entry_low = None
                        continue

            return signals

        except Exception as e:
            print(f"눌림목 캔들패턴 신호 생성 오류: {e}")
            return pd.DataFrame()

    @staticmethod
    def generate_sell_signals(
        data: pd.DataFrame,
        entry_low: Optional[float] = None,
        support_lookback: int = 5,
        bisector_leeway: float = 0.002,
    ) -> pd.DataFrame:
        """눌림목 캔들패턴 - 매도 신호 전용 계산 (현재 상태 기반, in_position 비의존)

        반환 컬럼:
        - sell_bisector_break: 종가가 이등분선 대비 0.2% 하회
        - sell_support_break: 종가가 직전 구간의 최근 저점(lookback) 하회(현재 캔들 제외)
        - stop_entry_low_break: 종가가 진입 양봉의 저가 대비 0.2% 하회 (entry_low 제공 시)
        - bisector_line: 이등분선 값(보조)
        """
        try:
            if data is None or data.empty:
                return pd.DataFrame()

            required_cols = ['open', 'high', 'low', 'close']
            if not all(col in data.columns for col in required_cols):
                return pd.DataFrame(index=data.index)

            df = data.copy()

            # 이등분선 계산
            bl = BisectorLine.calculate_bisector_line(df['high'], df['low'])

            # 최근 저점(현재 캔들 제외: 직전 N봉 기준)
            recent_low_prev = df['low'].shift(1).rolling(window=max(1, support_lookback), min_periods=1).min()

            closes = df['close']

            sell_bisector_break = (closes < (bl * (1.0 - bisector_leeway)))
            sell_support_break = (closes < recent_low_prev)

            if entry_low is not None and entry_low > 0:
                stop_entry_low_break = (closes <= entry_low * (1.0 - bisector_leeway))
            else:
                stop_entry_low_break = pd.Series(False, index=df.index)

            out = pd.DataFrame(index=df.index)
            out['sell_bisector_break'] = sell_bisector_break.fillna(False)
            out['sell_support_break'] = sell_support_break.fillna(False)
            out['stop_entry_low_break'] = stop_entry_low_break.fillna(False)
            out['bisector_line'] = bl

            return out

        except Exception as e:
            print(f"눌림목 캔들패턴 매도 신호 계산 오류: {e}")
            return pd.DataFrame(index=(data.index if data is not None else None))

    @staticmethod
    def generate_buy_signals(
        data: pd.DataFrame,
        retrace_lookback: int = 2,
        low_vol_ratio: float = 0.25,
    ) -> pd.DataFrame:
        """눌림목 캔들패턴 - 매수 신호 전용 계산 (현재 상태 기반, in_position 비의존)

        반환 컬럼:
        - buy_pullback_pattern
        - buy_bisector_recovery
        - bisector_line
        """
        try:
            if data is None or data.empty or len(data) < retrace_lookback + 3:
                return pd.DataFrame()

            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in data.columns for col in required_cols):
                return pd.DataFrame(index=data.index)

            df = data.copy()
            bl = BisectorLine.calculate_bisector_line(df['high'], df['low'])

            buy_pullback = pd.Series(False, index=df.index)
            buy_bis_up = pd.Series(False, index=df.index)

            # 기준 거래량 (최근 50봉 최대) 시계열
            rolling_baseline = df['volume'].rolling(window=min(50, len(df)), min_periods=1).max()

            for i in range(len(df)):
                if i < retrace_lookback + 2:
                    continue

                current_open = float(df['open'].iloc[i])
                current_close = float(df['close'].iloc[i])
                current_high = float(df['high'].iloc[i])
                current_low = float(df['low'].iloc[i])
                current_vol = float(df['volume'].iloc[i])
                bl_i = float(bl.iloc[i]) if not pd.isna(bl.iloc[i]) else None

                # 이등분선 위/회복
                above_bisector = (bl_i is not None) and (current_close >= bl_i)
                crosses_bisector_up = (bl_i is not None) and (current_open <= bl_i < current_close)

                # 저거래 하락 조정
                window = df.iloc[i - retrace_lookback:i]
                baseline_now = float(rolling_baseline.iloc[i]) if not pd.isna(rolling_baseline.iloc[i]) else 0.0
                low_volume_all = (window['volume'] < baseline_now * low_vol_ratio).all() if baseline_now > 0 else False
                downtrend_all = (window['close'].diff().fillna(0) < 0).iloc[1:].all() if len(window) >= 2 else False
                is_low_volume_retrace = low_volume_all and downtrend_all

                # 회복 양봉 + 거래량 회복
                is_bullish = current_close > current_open
                max_low_vol = float(window['volume'].max()) if len(window) > 0 else 0.0
                avg_recent_vol = float(df['volume'].iloc[max(0, i - 10):i].mean()) if i > 0 else 0.0
                volume_recovers = (current_vol > max_low_vol) or (current_vol > avg_recent_vol)

                # 1/2 되돌림 허용
                recent_start = max(0, i - 12)
                recent_range = df.iloc[recent_start:i]
                half_retrace_ok = False
                if len(recent_range) > 0:
                    recent_candle_size = (recent_range['high'] - recent_range['low']).mean()
                    recent_vol_mean = recent_range['volume'].mean()
                    impulse_idx = None
                    for j in range(i - 1, recent_start - 1, -1):
                        open_j = float(df['open'].iloc[j])
                        close_j = float(df['close'].iloc[j])
                        high_j = float(df['high'].iloc[j])
                        low_j = float(df['low'].iloc[j])
                        vol_j = float(df['volume'].iloc[j])
                        body = abs(close_j - open_j)
                        size = high_j - low_j
                        if close_j > open_j and size > 0:
                            if body >= float(recent_candle_size) * 0.8 and vol_j >= float(recent_vol_mean) * 0.8:
                                impulse_idx = j
                                break
                    if impulse_idx is not None:
                        ih = float(df['high'].iloc[impulse_idx])
                        il = float(df['low'].iloc[impulse_idx])
                        half_point = il + (ih - il) * 0.5
                        eps = max(half_point * 0.01, 1.0)
                        if (abs(current_close - half_point) <= eps) or (current_low <= half_point <= current_close):
                            half_retrace_ok = True

                # 매수 신호 판정
                if (
                    (is_low_volume_retrace and is_bullish and volume_recovers and (above_bisector or crosses_bisector_up))
                    or
                    (half_retrace_ok and is_bullish and (above_bisector or crosses_bisector_up))
                ):
                    buy_pullback.iloc[i] = True

                if is_bullish and crosses_bisector_up and volume_recovers:
                    buy_bis_up.iloc[i] = True

            out = pd.DataFrame(index=df.index)
            out['buy_pullback_pattern'] = buy_pullback
            out['buy_bisector_recovery'] = buy_bis_up
            out['bisector_line'] = bl
            return out

        except Exception as e:
            print(f"눌림목 캔들패턴 매수 신호 계산 오류: {e}")
            return pd.DataFrame(index=(data.index if data is not None else None))
    
    @staticmethod
    def get_pattern_info(data: pd.DataFrame) -> Dict:
        """현재 패턴 정보 반환"""
        try:
            if len(data) < 20:
                return {}
            
            volume_analysis = PullbackCandlePattern.analyze_volume(data)
            candle_analysis = PullbackCandlePattern.analyze_candle(data)
            price_trend = PullbackCandlePattern.check_price_trend(data)
            above_bisector = PullbackCandlePattern.check_price_above_bisector(data)
            
            return {
                'price_trend': price_trend,
                'above_bisector': above_bisector,
                'volume_trend': volume_analysis.volume_trend,
                'candle_trend': candle_analysis.candle_trend,
                'baseline_volume': volume_analysis.baseline_volume,
                'current_volume': volume_analysis.current_volume,
                'volume_ratio': volume_analysis.current_volume / volume_analysis.baseline_volume if volume_analysis.baseline_volume > 0 else 0,
                'is_low_volume': volume_analysis.is_low_volume,
                'is_high_volume': volume_analysis.is_high_volume,
                'current_candle_size': candle_analysis.current_candle_size,
                'avg_candle_size': candle_analysis.avg_recent_candle_size,
                'is_small_candle': candle_analysis.is_small_candle,
                'is_large_candle': candle_analysis.is_large_candle
            }
            
        except Exception as e:
            print(f"패턴 정보 분석 오류: {e}")
            return {}