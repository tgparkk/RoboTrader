"""
향상된 특성 추출기
기존 10개 특성에 추가로 20개 이상의 특성을 추출
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

# talib 대신 직접 구현한 기술적 지표 함수들
try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    print("⚠️ talib 모듈이 없습니다. 기본 기술적 지표만 사용합니다.")

class EnhancedFeatureExtractor:
    """향상된 특성 추출기"""
    
    def __init__(self):
        self.features = {}
    
    def extract_all_features(self, daily_data: pd.DataFrame, signal_date: str) -> Dict[str, float]:
        """모든 특성 추출"""
        features = {}
        
        try:
            if daily_data is None or daily_data.empty:
                return features
            
            # 신호 날짜 이전 데이터만 사용
            signal_dt = pd.to_datetime(signal_date)
            historical_data = daily_data[daily_data['date'] < signal_dt].copy()
            
            if len(historical_data) < 20:
                return features
            
            # 기본 특성 (기존 10개)
            features.update(self._extract_basic_features(historical_data))
            
            # 기술적 지표 특성 (20개)
            features.update(self._extract_technical_indicators(historical_data))
            
            # 거래량 특성 (10개)
            features.update(self._extract_volume_features(historical_data))
            
            # 가격 패턴 특성 (15개)
            features.update(self._extract_price_patterns(historical_data))
            
            # 시장 상황 특성 (10개)
            features.update(self._extract_market_conditions(historical_data))
            
            # 시간대별 특성 (5개)
            features.update(self._extract_time_features(historical_data, signal_date))
            
        except Exception as e:
            print(f"특성 추출 실패: {e}")
        
        return features
    
    def _extract_basic_features(self, data: pd.DataFrame) -> Dict[str, float]:
        """기본 특성 (기존 10개)"""
        features = {}
        
        # 최근 5일, 10일, 20일 데이터
        recent_5d = data.tail(5)
        recent_10d = data.tail(10)
        recent_20d = data.tail(20)
        
        # 1. 가격 모멘텀
        features['price_momentum_5d'] = self._calculate_price_momentum(recent_5d)
        features['price_momentum_10d'] = self._calculate_price_momentum(recent_10d)
        features['price_momentum_20d'] = self._calculate_price_momentum(recent_20d)
        
        # 2. 변동성
        features['volatility_5d'] = self._calculate_volatility(recent_5d)
        features['volatility_10d'] = self._calculate_volatility(recent_10d)
        features['volatility_20d'] = self._calculate_volatility(recent_20d)
        
        # 3. 추세 강도
        features['trend_strength_5d'] = self._calculate_trend_strength(recent_5d)
        features['trend_strength_10d'] = self._calculate_trend_strength(recent_10d)
        features['trend_strength_20d'] = self._calculate_trend_strength(recent_20d)
        
        # 4. 연속 상승/하락일
        features['consecutive_up_days'] = self._calculate_consecutive_days(recent_10d, 'up')
        features['consecutive_down_days'] = self._calculate_consecutive_days(recent_10d, 'down')
        
        return features
    
    def _extract_technical_indicators(self, data: pd.DataFrame) -> Dict[str, float]:
        """기술적 지표 특성 (20개)"""
        features = {}
        
        try:
            if TALIB_AVAILABLE:
                # talib 사용
                # RSI (14일, 21일)
                if len(data) >= 21:
                    rsi_14 = talib.RSI(data['close'].values, timeperiod=14)
                    rsi_21 = talib.RSI(data['close'].values, timeperiod=21)
                    features['rsi_14'] = rsi_14[-1] if not np.isnan(rsi_14[-1]) else 50
                    features['rsi_21'] = rsi_21[-1] if not np.isnan(rsi_21[-1]) else 50
                    features['rsi_14_oversold'] = 1 if features['rsi_14'] < 30 else 0
                    features['rsi_14_overbought'] = 1 if features['rsi_14'] > 70 else 0
                
                # MACD
                if len(data) >= 26:
                    macd, macd_signal, macd_hist = talib.MACD(data['close'].values)
                    features['macd'] = macd[-1] if not np.isnan(macd[-1]) else 0
                    features['macd_signal'] = macd_signal[-1] if not np.isnan(macd_signal[-1]) else 0
                    features['macd_histogram'] = macd_hist[-1] if not np.isnan(macd_hist[-1]) else 0
                    features['macd_bullish'] = 1 if features['macd'] > features['macd_signal'] else 0
                
                # 볼린저 밴드
                if len(data) >= 20:
                    bb_upper, bb_middle, bb_lower = talib.BBANDS(data['close'].values, timeperiod=20)
                    features['bb_position'] = (data['close'].iloc[-1] - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) if not np.isnan(bb_upper[-1]) else 0.5
                    features['bb_squeeze'] = 1 if (bb_upper[-1] - bb_lower[-1]) / bb_middle[-1] < 0.1 else 0
                
                # 스토캐스틱
                if len(data) >= 14:
                    stoch_k, stoch_d = talib.STOCH(data['high'].values, data['low'].values, data['close'].values)
                    features['stoch_k'] = stoch_k[-1] if not np.isnan(stoch_k[-1]) else 50
                    features['stoch_d'] = stoch_d[-1] if not np.isnan(stoch_d[-1]) else 50
                    features['stoch_oversold'] = 1 if features['stoch_k'] < 20 else 0
                    features['stoch_overbought'] = 1 if features['stoch_k'] > 80 else 0
                
                # 이동평균선
                if len(data) >= 20:
                    ma_5 = talib.SMA(data['close'].values, timeperiod=5)
                    ma_10 = talib.SMA(data['close'].values, timeperiod=10)
                    ma_20 = talib.SMA(data['close'].values, timeperiod=20)
                    features['ma_5'] = ma_5[-1] if not np.isnan(ma_5[-1]) else data['close'].iloc[-1]
                    features['ma_10'] = ma_10[-1] if not np.isnan(ma_10[-1]) else data['close'].iloc[-1]
                    features['ma_20'] = ma_20[-1] if not np.isnan(ma_20[-1]) else data['close'].iloc[-1]
                    features['ma_alignment'] = 1 if ma_5[-1] > ma_10[-1] > ma_20[-1] else 0
                    features['price_vs_ma20'] = (data['close'].iloc[-1] - ma_20[-1]) / ma_20[-1] if not np.isnan(ma_20[-1]) else 0
                
                # CCI (Commodity Channel Index)
                if len(data) >= 20:
                    cci = talib.CCI(data['high'].values, data['low'].values, data['close'].values, timeperiod=20)
                    features['cci'] = cci[-1] if not np.isnan(cci[-1]) else 0
                    features['cci_oversold'] = 1 if features['cci'] < -100 else 0
                    features['cci_overbought'] = 1 if features['cci'] > 100 else 0
            else:
                # talib 없이 기본 지표만 계산
                # 이동평균선
                if len(data) >= 20:
                    ma_5 = data['close'].rolling(5).mean()
                    ma_10 = data['close'].rolling(10).mean()
                    ma_20 = data['close'].rolling(20).mean()
                    features['ma_5'] = ma_5.iloc[-1] if not np.isnan(ma_5.iloc[-1]) else data['close'].iloc[-1]
                    features['ma_10'] = ma_10.iloc[-1] if not np.isnan(ma_10.iloc[-1]) else data['close'].iloc[-1]
                    features['ma_20'] = ma_20.iloc[-1] if not np.isnan(ma_20.iloc[-1]) else data['close'].iloc[-1]
                    features['ma_alignment'] = 1 if ma_5.iloc[-1] > ma_10.iloc[-1] > ma_20.iloc[-1] else 0
                    features['price_vs_ma20'] = (data['close'].iloc[-1] - ma_20.iloc[-1]) / ma_20.iloc[-1] if not np.isnan(ma_20.iloc[-1]) else 0
                
                # 간단한 RSI 계산
                if len(data) >= 21:
                    features['rsi_14'] = self._calculate_simple_rsi(data['close'], 14)
                    features['rsi_21'] = self._calculate_simple_rsi(data['close'], 21)
                    features['rsi_14_oversold'] = 1 if features['rsi_14'] < 30 else 0
                    features['rsi_14_overbought'] = 1 if features['rsi_14'] > 70 else 0
                
                # 간단한 MACD 계산
                if len(data) >= 26:
                    macd, macd_signal = self._calculate_simple_macd(data['close'])
                    features['macd'] = macd
                    features['macd_signal'] = macd_signal
                    features['macd_histogram'] = macd - macd_signal
                    features['macd_bullish'] = 1 if macd > macd_signal else 0
            
        except Exception as e:
            print(f"기술적 지표 추출 실패: {e}")
        
        return features
    
    def _extract_volume_features(self, data: pd.DataFrame) -> Dict[str, float]:
        """거래량 특성 (10개)"""
        features = {}
        
        try:
            if 'volume' not in data.columns:
                return features
            
            # 거래량 이동평균
            if len(data) >= 20:
                vol_ma_5 = data['volume'].rolling(5).mean()
                vol_ma_10 = data['volume'].rolling(10).mean()
                vol_ma_20 = data['volume'].rolling(20).mean()
                
                features['volume_ratio_5d'] = data['volume'].iloc[-1] / vol_ma_5.iloc[-1] if vol_ma_5.iloc[-1] > 0 else 1
                features['volume_ratio_10d'] = data['volume'].iloc[-1] / vol_ma_10.iloc[-1] if vol_ma_10.iloc[-1] > 0 else 1
                features['volume_ratio_20d'] = data['volume'].iloc[-1] / vol_ma_20.iloc[-1] if vol_ma_20.iloc[-1] > 0 else 1
                
                # 거래량 급증
                features['volume_surge'] = 1 if features['volume_ratio_5d'] > 2.0 else 0
                features['volume_dry'] = 1 if features['volume_ratio_5d'] < 0.5 else 0
                
                # 거래량 추세
                features['volume_trend'] = 1 if vol_ma_5.iloc[-1] > vol_ma_10.iloc[-1] > vol_ma_20.iloc[-1] else 0
                
                # 가격-거래량 상관관계
                price_change = data['close'].pct_change()
                volume_change = data['volume'].pct_change()
                correlation = price_change.corr(volume_change)
                features['price_volume_correlation'] = correlation if not np.isnan(correlation) else 0
                
                # 거래량 변동성
                features['volume_volatility'] = data['volume'].rolling(10).std().iloc[-1] / vol_ma_10.iloc[-1] if vol_ma_10.iloc[-1] > 0 else 0
                
        except Exception as e:
            print(f"거래량 특성 추출 실패: {e}")
        
        return features
    
    def _extract_price_patterns(self, data: pd.DataFrame) -> Dict[str, float]:
        """가격 패턴 특성 (15개)"""
        features = {}
        
        try:
            # 갭 분석
            data['gap'] = data['open'] - data['close'].shift(1)
            data['gap_pct'] = data['gap'] / data['close'].shift(1) * 100
            
            features['gap_frequency'] = (data['gap_pct'].abs() > 1).sum() / len(data)
            features['gap_magnitude'] = data['gap_pct'].abs().mean()
            features['gap_up_frequency'] = (data['gap_pct'] > 1).sum() / len(data)
            features['gap_down_frequency'] = (data['gap_pct'] < -1).sum() / len(data)
            
            # 캔들 패턴
            features['doji_frequency'] = self._calculate_doji_frequency(data)
            features['hammer_frequency'] = self._calculate_hammer_frequency(data)
            features['shooting_star_frequency'] = self._calculate_shooting_star_frequency(data)
            
            # 지지/저항
            features['support_resistance_ratio'] = self._calculate_support_resistance_ratio(data)
            features['resistance_breaks'] = self._calculate_resistance_breaks(data)
            features['support_breaks'] = self._calculate_support_breaks(data)
            
            # 가격 채널
            features['price_channel_position'] = self._calculate_price_channel_position(data)
            features['channel_width'] = self._calculate_channel_width(data)
            
            # 고점/저점 분석
            features['new_highs'] = self._calculate_new_highs(data)
            features['new_lows'] = self._calculate_new_lows(data)
            features['higher_highs'] = self._calculate_higher_highs(data)
            features['lower_lows'] = self._calculate_lower_lows(data)
            
        except Exception as e:
            print(f"가격 패턴 특성 추출 실패: {e}")
        
        return features
    
    def _extract_market_conditions(self, data: pd.DataFrame) -> Dict[str, float]:
        """시장 상황 특성 (10개)"""
        features = {}
        
        try:
            # 시장 강도
            features['market_strength'] = self._calculate_market_strength(data)
            features['trend_consistency'] = self._calculate_trend_consistency(data)
            features['volatility_regime'] = self._calculate_volatility_regime(data)
            
            # 리스크 지표
            features['max_drawdown'] = self._calculate_max_drawdown(data)
            features['sharpe_ratio'] = self._calculate_sharpe_ratio(data)
            features['calmar_ratio'] = self._calculate_calmar_ratio(data)
            
            # 시장 효율성
            features['market_efficiency'] = self._calculate_market_efficiency(data)
            features['price_momentum_persistence'] = self._calculate_momentum_persistence(data)
            
            # 변동성 클러스터링
            features['volatility_clustering'] = self._calculate_volatility_clustering(data)
            features['mean_reversion'] = self._calculate_mean_reversion(data)
            
        except Exception as e:
            print(f"시장 상황 특성 추출 실패: {e}")
        
        return features
    
    def _extract_time_features(self, data: pd.DataFrame, signal_date: str) -> Dict[str, float]:
        """시간대별 특성 (5개)"""
        features = {}
        
        try:
            # 요일 효과
            signal_dt = pd.to_datetime(signal_date)
            features['day_of_week'] = signal_dt.weekday()  # 0=월요일, 6=일요일
            features['is_monday'] = 1 if signal_dt.weekday() == 0 else 0
            features['is_friday'] = 1 if signal_dt.weekday() == 4 else 0
            
            # 월말/월초 효과
            features['is_month_end'] = 1 if signal_dt.day >= 25 else 0
            features['is_month_start'] = 1 if signal_dt.day <= 5 else 0
            
        except Exception as e:
            print(f"시간대별 특성 추출 실패: {e}")
        
        return features
    
    # 기존 메서드들 (간단한 구현)
    def _calculate_price_momentum(self, data: pd.DataFrame) -> float:
        if len(data) < 2:
            return 0.0
        start_price = data['close'].iloc[0]
        end_price = data['close'].iloc[-1]
        return (end_price - start_price) / start_price * 100 if start_price > 0 else 0
    
    def _calculate_volatility(self, data: pd.DataFrame) -> float:
        if len(data) < 2:
            return 0.0
        returns = data['close'].pct_change().dropna()
        return returns.std() * 100 if len(returns) > 0 else 0
    
    def _calculate_trend_strength(self, data: pd.DataFrame) -> float:
        if len(data) < 2:
            return 0.0
        returns = data['close'].pct_change().dropna()
        return returns.mean() * 100 if len(returns) > 0 else 0
    
    def _calculate_consecutive_days(self, data: pd.DataFrame, direction: str) -> int:
        if len(data) < 2:
            return 0
        returns = data['close'].pct_change().dropna()
        if direction == 'up':
            return (returns > 0).sum()
        else:
            return (returns < 0).sum()
    
    def _calculate_support_resistance_ratio(self, data: pd.DataFrame) -> float:
        if len(data) < 20:
            return 0.5
        high_20 = data['high'].rolling(20).max()
        low_20 = data['low'].rolling(20).min()
        current_price = data['close'].iloc[-1]
        return (current_price - low_20.iloc[-1]) / (high_20.iloc[-1] - low_20.iloc[-1]) if high_20.iloc[-1] > low_20.iloc[-1] else 0.5
    
    # 추가 메서드들 (간단한 구현)
    def _calculate_doji_frequency(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        body_size = abs(data['close'] - data['open'])
        total_range = data['high'] - data['low']
        doji_count = (body_size / total_range < 0.1).sum()
        return doji_count / len(data)
    
    def _calculate_hammer_frequency(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        # 간단한 해머 패턴 (실제로는 더 복잡한 로직 필요)
        body_size = abs(data['close'] - data['open'])
        lower_shadow = data[['open', 'close']].min(axis=1) - data['low']
        hammer_count = ((body_size / (data['high'] - data['low']) < 0.3) & 
                       (lower_shadow / (data['high'] - data['low']) > 0.6)).sum()
        return hammer_count / len(data)
    
    def _calculate_shooting_star_frequency(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        # 간단한 슈팅스타 패턴
        body_size = abs(data['close'] - data['open'])
        upper_shadow = data['high'] - data[['open', 'close']].max(axis=1)
        shooting_star_count = ((body_size / (data['high'] - data['low']) < 0.3) & 
                             (upper_shadow / (data['high'] - data['low']) > 0.6)).sum()
        return shooting_star_count / len(data)
    
    def _calculate_resistance_breaks(self, data: pd.DataFrame) -> int:
        if len(data) < 20:
            return 0
        high_20 = data['high'].rolling(20).max()
        breaks = (data['close'] > high_20.shift(1)).sum()
        return breaks
    
    def _calculate_support_breaks(self, data: pd.DataFrame) -> int:
        if len(data) < 20:
            return 0
        low_20 = data['low'].rolling(20).min()
        breaks = (data['close'] < low_20.shift(1)).sum()
        return breaks
    
    def _calculate_price_channel_position(self, data: pd.DataFrame) -> float:
        if len(data) < 20:
            return 0.5
        high_20 = data['high'].rolling(20).max()
        low_20 = data['low'].rolling(20).min()
        current_price = data['close'].iloc[-1]
        return (current_price - low_20.iloc[-1]) / (high_20.iloc[-1] - low_20.iloc[-1]) if high_20.iloc[-1] > low_20.iloc[-1] else 0.5
    
    def _calculate_channel_width(self, data: pd.DataFrame) -> float:
        if len(data) < 20:
            return 0.0
        high_20 = data['high'].rolling(20).max()
        low_20 = data['low'].rolling(20).min()
        return (high_20.iloc[-1] - low_20.iloc[-1]) / data['close'].iloc[-1] if data['close'].iloc[-1] > 0 else 0
    
    def _calculate_new_highs(self, data: pd.DataFrame) -> int:
        if len(data) < 20:
            return 0
        high_20 = data['high'].rolling(20).max()
        return (data['high'] > high_20.shift(1)).sum()
    
    def _calculate_new_lows(self, data: pd.DataFrame) -> int:
        if len(data) < 20:
            return 0
        low_20 = data['low'].rolling(20).min()
        return (data['low'] < low_20.shift(1)).sum()
    
    def _calculate_higher_highs(self, data: pd.DataFrame) -> int:
        if len(data) < 10:
            return 0
        highs = data['high'].rolling(5).max()
        return (highs > highs.shift(5)).sum()
    
    def _calculate_lower_lows(self, data: pd.DataFrame) -> int:
        if len(data) < 10:
            return 0
        lows = data['low'].rolling(5).min()
        return (lows < lows.shift(5)).sum()
    
    def _calculate_market_strength(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        returns = data['close'].pct_change().dropna()
        return returns.mean() * 100 if len(returns) > 0 else 0
    
    def _calculate_trend_consistency(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        returns = data['close'].pct_change().dropna()
        positive_days = (returns > 0).sum()
        return positive_days / len(returns) if len(returns) > 0 else 0.5
    
    def _calculate_volatility_regime(self, data: pd.DataFrame) -> float:
        if len(data) < 20:
            return 0.0
        returns = data['close'].pct_change().dropna()
        vol_10 = returns.rolling(10).std().iloc[-1]
        vol_20 = returns.rolling(20).std().iloc[-1]
        return vol_10 / vol_20 if vol_20 > 0 else 1
    
    def _calculate_max_drawdown(self, data: pd.DataFrame) -> float:
        if len(data) < 2:
            return 0.0
        cumulative = (1 + data['close'].pct_change()).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        return drawdown.min() * 100
    
    def _calculate_sharpe_ratio(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        returns = data['close'].pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        return returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    
    def _calculate_calmar_ratio(self, data: pd.DataFrame) -> float:
        if len(data) < 20:
            return 0.0
        returns = data['close'].pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        annual_return = returns.mean() * 252
        max_dd = abs(self._calculate_max_drawdown(data))
        return annual_return / max_dd if max_dd > 0 else 0
    
    def _calculate_market_efficiency(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        returns = data['close'].pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        # 간단한 효율성 지표 (실제로는 더 복잡한 로직 필요)
        return 1 - abs(returns.autocorr(lag=1)) if not np.isnan(returns.autocorr(lag=1)) else 0
    
    def _calculate_momentum_persistence(self, data: pd.DataFrame) -> float:
        if len(data) < 10:
            return 0.0
        returns = data['close'].pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        # 모멘텀 지속성 (실제로는 더 복잡한 로직 필요)
        return returns.rolling(5).mean().iloc[-1] if len(returns) >= 5 else 0
    
    def _calculate_volatility_clustering(self, data: pd.DataFrame) -> float:
        if len(data) < 20:
            return 0.0
        returns = data['close'].pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        # 변동성 클러스터링 (실제로는 더 복잡한 로직 필요)
        vol_5 = returns.rolling(5).std()
        vol_10 = returns.rolling(10).std()
        return vol_5.iloc[-1] / vol_10.iloc[-1] if vol_10.iloc[-1] > 0 else 1
    
    def _calculate_mean_reversion(self, data: pd.DataFrame) -> float:
        if len(data) < 20:
            return 0.0
        returns = data['close'].pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        # 평균 회귀 (실제로는 더 복잡한 로직 필요)
        ma_10 = returns.rolling(10).mean()
        current_return = returns.iloc[-1]
        ma_return = ma_10.iloc[-1]
        return (current_return - ma_return) / ma_return if ma_return != 0 else 0
    
    def _calculate_simple_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """간단한 RSI 계산"""
        try:
            if len(prices) < period + 1:
                return 50.0
            
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else 50.0
            
        except Exception:
            return 50.0
    
    def _calculate_simple_macd(self, prices: pd.Series) -> Tuple[float, float]:
        """간단한 MACD 계산"""
        try:
            if len(prices) < 26:
                return 0.0, 0.0
            
            ema_12 = prices.ewm(span=12).mean()
            ema_26 = prices.ewm(span=26).mean()
            macd = ema_12 - ema_26
            macd_signal = macd.ewm(span=9).mean()
            
            return macd.iloc[-1], macd_signal.iloc[-1]
            
        except Exception:
            return 0.0, 0.0
