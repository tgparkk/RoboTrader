#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
머신러닝을 위한 고급 특성 추출 엔진
- 분봉 패턴 특성 추출
- 일봉 기술적 지표 계산
- 시장 컨텍스트 특성
- 시간적 특성
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import logging
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)

class MLFeatureEngineer:
    """머신러닝 특성 추출 엔진"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def extract_comprehensive_features(self, minute_data: pd.DataFrame, 
                                     daily_data: pd.DataFrame, 
                                     trade: Dict) -> Dict[str, Any]:
        """종합적인 특성 추출"""
        features = {}
        
        try:
            # 1. 기본 거래 정보
            features.update(self._extract_basic_trade_features(trade))
            
            # 2. 분봉 패턴 특성
            features.update(self._extract_minute_pattern_features(minute_data, trade))
            
            # 3. 일봉 기술적 지표
            features.update(self._extract_daily_technical_features(daily_data, trade))
            
            # 4. 시장 컨텍스트 특성
            features.update(self._extract_market_context_features(daily_data, trade))
            
            # 5. 시간적 특성
            features.update(self._extract_temporal_features(trade))
            
            # 6. 고급 패턴 특성
            features.update(self._extract_advanced_pattern_features(minute_data, daily_data, trade))
            
            return features
            
        except Exception as e:
            self.logger.error(f"특성 추출 실패: {e}")
            return {}
    
    def _extract_basic_trade_features(self, trade: Dict) -> Dict[str, Any]:
        """기본 거래 특성"""
        return {
            'stock_code': trade['stock_code'],
            'date': trade['date'],
            'buy_time': trade['buy_time'],
            'sell_time': trade['sell_time'],
            'profit_pct': trade['profit_pct'],
            'is_win': trade['is_win'],
            'signal_type': trade['signal_type'],
            'sell_reason': trade['sell_reason'],
            'holding_minutes': self._calculate_holding_minutes(trade['buy_time'], trade['sell_time'])
        }
    
    def _extract_minute_pattern_features(self, minute_data: pd.DataFrame, trade: Dict) -> Dict[str, Any]:
        """분봉 패턴 특성 추출"""
        features = {}
        
        try:
            if minute_data.empty:
                return features
            
            # 기본 통계
            features['minute_count'] = len(minute_data)
            features['avg_volume'] = minute_data['volume'].mean()
            features['max_volume'] = minute_data['volume'].max()
            features['min_volume'] = minute_data['volume'].min()
            features['volume_std'] = minute_data['volume'].std()
            features['volume_cv'] = minute_data['volume'].std() / minute_data['volume'].mean()
            
            # 가격 통계
            features['price_volatility'] = minute_data['close'].std() / minute_data['close'].mean()
            features['price_range_pct'] = (minute_data['high'].max() - minute_data['low'].min()) / minute_data['close'].mean()
            features['avg_body_ratio'] = (minute_data['close'] - minute_data['open']).abs().mean() / (minute_data['high'] - minute_data['low']).mean()
            
            # 거래량 패턴
            features['volume_trend'] = self._calculate_volume_trend(minute_data)
            features['volume_acceleration'] = self._calculate_volume_acceleration(minute_data)
            features['volume_consistency'] = 1 - (minute_data['volume'].std() / minute_data['volume'].mean())
            
            # 가격 모멘텀
            features['price_momentum_5min'] = self._calculate_price_momentum(minute_data, 5)
            features['price_momentum_15min'] = self._calculate_price_momentum(minute_data, 15)
            features['price_momentum_30min'] = self._calculate_price_momentum(minute_data, 30)
            
            # 캔들 패턴 특성
            features.update(self._extract_candle_pattern_features(minute_data))
            
            # 시간대별 특성
            buy_time = trade['buy_time']
            hour = int(buy_time.split(':')[0])
            minute = int(buy_time.split(':')[1])
            
            features['buy_hour'] = hour
            features['buy_minute'] = minute
            features['is_morning_session'] = 1 if 9 <= hour < 12 else 0
            features['is_afternoon_session'] = 1 if 12 <= hour < 15 else 0
            features['is_opening_hour'] = 1 if 9 <= hour < 10 else 0
            features['is_closing_hour'] = 1 if 14 <= hour < 15 else 0
            
            return features
            
        except Exception as e:
            self.logger.error(f"분봉 패턴 특성 추출 실패: {e}")
            return {}
    
    def _extract_daily_technical_features(self, daily_data: pd.DataFrame, trade: Dict) -> Dict[str, Any]:
        """일봉 기술적 지표 특성"""
        features = {}
        
        try:
            if daily_data.empty:
                return features
            
            # 데이터 타입 변환 (문자열을 숫자로)
            daily_data = daily_data.copy()
            numeric_columns = ['stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'acml_vol', 'acml_tr_pbmn', 'prdy_vrss']
            for col in numeric_columns:
                if col in daily_data.columns:
                    daily_data[col] = pd.to_numeric(daily_data[col], errors='coerce')
            
            # 이동평균선
            daily_data['ma5'] = daily_data['stck_clpr'].rolling(5).mean()
            daily_data['ma10'] = daily_data['stck_clpr'].rolling(10).mean()
            daily_data['ma20'] = daily_data['stck_clpr'].rolling(20).mean()
            daily_data['ma60'] = daily_data['stck_clpr'].rolling(60).mean()
            
            current_price = daily_data['stck_clpr'].iloc[-1]
            
            # 이동평균선 위치
            features['ma5_position'] = (current_price - daily_data['ma5'].iloc[-1]) / daily_data['ma5'].iloc[-1]
            features['ma10_position'] = (current_price - daily_data['ma10'].iloc[-1]) / daily_data['ma10'].iloc[-1]
            features['ma20_position'] = (current_price - daily_data['ma20'].iloc[-1]) / daily_data['ma20'].iloc[-1]
            features['ma60_position'] = (current_price - daily_data['ma60'].iloc[-1]) / daily_data['ma60'].iloc[-1]
            
            # 이동평균선 배열
            features['ma_alignment'] = self._calculate_ma_alignment(daily_data)
            features['ma_slope_5'] = self._calculate_ma_slope(daily_data['ma5'])
            features['ma_slope_20'] = self._calculate_ma_slope(daily_data['ma20'])
            
            # RSI
            features['rsi_14'] = self._calculate_rsi(daily_data['stck_clpr'], 14)
            features['rsi_5'] = self._calculate_rsi(daily_data['stck_clpr'], 5)
            
            # MACD
            macd_line, signal_line, histogram = self._calculate_macd(daily_data['stck_clpr'])
            features['macd'] = macd_line.iloc[-1] if not pd.isna(macd_line.iloc[-1]) else 0
            features['macd_signal'] = signal_line.iloc[-1] if not pd.isna(signal_line.iloc[-1]) else 0
            features['macd_histogram'] = histogram.iloc[-1] if not pd.isna(histogram.iloc[-1]) else 0
            features['macd_cross'] = 1 if macd_line.iloc[-1] > signal_line.iloc[-1] else 0
            
            # 볼린저 밴드
            bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(daily_data['stck_clpr'])
            features['bb_position'] = (current_price - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1])
            features['bb_width'] = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1]
            features['bb_squeeze'] = 1 if features['bb_width'] < 0.1 else 0
            
            # 거래량 지표
            features['volume_ma20_ratio'] = daily_data['acml_vol'].iloc[-1] / daily_data['acml_vol'].rolling(20).mean().iloc[-1]
            features['volume_trend_5d'] = self._calculate_volume_trend(daily_data.tail(5))
            features['volume_trend_20d'] = self._calculate_volume_trend(daily_data.tail(20))
            
            # 가격 모멘텀
            features['price_momentum_5d'] = (daily_data['stck_clpr'].iloc[-1] - daily_data['stck_clpr'].iloc[-6]) / daily_data['stck_clpr'].iloc[-6]
            features['price_momentum_10d'] = (daily_data['stck_clpr'].iloc[-1] - daily_data['stck_clpr'].iloc[-11]) / daily_data['stck_clpr'].iloc[-11]
            features['price_momentum_20d'] = (daily_data['stck_clpr'].iloc[-1] - daily_data['stck_clpr'].iloc[-21]) / daily_data['stck_clpr'].iloc[-21]
            
            # 변동성
            features['volatility_5d'] = daily_data['stck_clpr'].pct_change().rolling(5).std().iloc[-1]
            features['volatility_20d'] = daily_data['stck_clpr'].pct_change().rolling(20).std().iloc[-1]
            
            return features
            
        except Exception as e:
            self.logger.error(f"일봉 기술적 지표 특성 추출 실패: {e}")
            return {}
    
    def _extract_market_context_features(self, daily_data: pd.DataFrame, trade: Dict) -> Dict[str, Any]:
        """시장 컨텍스트 특성"""
        features = {}
        
        try:
            if daily_data.empty:
                return features
            
            # 시장 강도
            features['market_strength'] = self._calculate_market_strength(daily_data)
            
            # 트렌드 강도
            features['trend_strength'] = self._calculate_trend_strength(daily_data)
            
            # 지지/저항 레벨
            features['support_resistance_strength'] = self._calculate_support_resistance_strength(daily_data)
            
            # 거래량 패턴
            features['volume_pattern'] = self._classify_volume_pattern(daily_data)
            
            return features
            
        except Exception as e:
            self.logger.error(f"시장 컨텍스트 특성 추출 실패: {e}")
            return {}
    
    def _extract_temporal_features(self, trade: Dict) -> Dict[str, Any]:
        """시간적 특성"""
        features = {}
        
        try:
            date_str = trade['date']
            buy_time = trade['buy_time']
            
            # 날짜 파싱
            trade_date = datetime.strptime(date_str, '%Y%m%d')
            features['day_of_week'] = trade_date.weekday()  # 0=월요일, 6=일요일
            features['is_monday'] = 1 if trade_date.weekday() == 0 else 0
            features['is_friday'] = 1 if trade_date.weekday() == 4 else 0
            features['is_month_end'] = 1 if trade_date.day >= 28 else 0
            features['is_quarter_end'] = 1 if trade_date.month in [3, 6, 9, 12] and trade_date.day >= 28 else 0
            
            # 시간 파싱
            hour = int(buy_time.split(':')[0])
            minute = int(buy_time.split(':')[1])
            features['time_of_day'] = hour + minute / 60.0
            features['is_opening_30min'] = 1 if 9 <= hour < 9.5 else 0
            features['is_lunch_time'] = 1 if 12 <= hour < 13 else 0
            features['is_closing_30min'] = 1 if 14.5 <= hour < 15 else 0
            
            return features
            
        except Exception as e:
            self.logger.error(f"시간적 특성 추출 실패: {e}")
            return {}
    
    def _extract_advanced_pattern_features(self, minute_data: pd.DataFrame, 
                                         daily_data: pd.DataFrame, 
                                         trade: Dict) -> Dict[str, Any]:
        """고급 패턴 특성"""
        features = {}
        
        try:
            # 분봉-일봉 상관관계
            if not minute_data.empty and not daily_data.empty:
                features['minute_daily_correlation'] = self._calculate_minute_daily_correlation(minute_data, daily_data)
            
            # 패턴 일관성
            features['pattern_consistency'] = self._calculate_pattern_consistency(minute_data, daily_data)
            
            # 신호 강도
            features['signal_strength'] = self._calculate_signal_strength(minute_data, trade)
            
            return features
            
        except Exception as e:
            self.logger.error(f"고급 패턴 특성 추출 실패: {e}")
            return {}
    
    # 헬퍼 메서드들
    def _calculate_holding_minutes(self, buy_time: str, sell_time: str) -> int:
        """보유 시간 계산 (분)"""
        try:
            buy_dt = datetime.strptime(buy_time, '%H:%M')
            sell_dt = datetime.strptime(sell_time, '%H:%M')
            return int((sell_dt - buy_dt).total_seconds() / 60)
        except:
            return 0
    
    def _calculate_volume_trend(self, data: pd.DataFrame) -> float:
        """거래량 트렌드 계산"""
        try:
            if len(data) < 2:
                return 0.0
            
            volumes = data['volume'] if 'volume' in data.columns else data['acml_vol']
            x = np.arange(len(volumes))
            y = volumes.values
            
            slope = np.polyfit(x, y, 1)[0]
            return slope / volumes.mean()
        except:
            return 0.0
    
    def _calculate_volume_acceleration(self, data: pd.DataFrame) -> float:
        """거래량 가속도 계산"""
        try:
            if len(data) < 3:
                return 0.0
            
            volumes = data['volume'] if 'volume' in data.columns else data['acml_vol']
            x = np.arange(len(volumes))
            y = volumes.values
            
            # 2차 다항식으로 가속도 계산
            coeffs = np.polyfit(x, y, 2)
            return coeffs[0]  # 2차 계수 (가속도)
        except:
            return 0.0
    
    def _calculate_price_momentum(self, data: pd.DataFrame, periods: int) -> float:
        """가격 모멘텀 계산"""
        try:
            if len(data) < periods + 1:
                return 0.0
            
            prices = data['close']
            return (prices.iloc[-1] - prices.iloc[-periods-1]) / prices.iloc[-periods-1]
        except:
            return 0.0
    
    def _extract_candle_pattern_features(self, data: pd.DataFrame) -> Dict[str, Any]:
        """캔들 패턴 특성"""
        features = {}
        
        try:
            if data.empty:
                return features
            
            # 몸통과 꼬리 비율
            body = (data['close'] - data['open']).abs()
            upper_shadow = data['high'] - data[['open', 'close']].max(axis=1)
            lower_shadow = data[['open', 'close']].min(axis=1) - data['low']
            total_range = data['high'] - data['low']
            
            features['avg_body_ratio'] = (body / total_range).mean()
            features['avg_upper_shadow_ratio'] = (upper_shadow / total_range).mean()
            features['avg_lower_shadow_ratio'] = (lower_shadow / total_range).mean()
            
            # 양봉/음봉 비율
            bullish_candles = (data['close'] > data['open']).sum()
            features['bullish_ratio'] = bullish_candles / len(data)
            
            # 연속 패턴
            features['max_consecutive_bullish'] = self._max_consecutive_bullish(data)
            features['max_consecutive_bearish'] = self._max_consecutive_bearish(data)
            
            return features
            
        except Exception as e:
            self.logger.error(f"❌ 캔들 패턴 특성 추출 실패: {e}")
            return {}
    
    def _max_consecutive_bullish(self, data: pd.DataFrame) -> int:
        """최대 연속 양봉 수"""
        try:
            bullish = data['close'] > data['open']
            max_consecutive = 0
            current_consecutive = 0
            
            for is_bullish in bullish:
                if is_bullish:
                    current_consecutive += 1
                    max_consecutive = max(max_consecutive, current_consecutive)
                else:
                    current_consecutive = 0
            
            return max_consecutive
        except:
            return 0
    
    def _max_consecutive_bearish(self, data: pd.DataFrame) -> int:
        """최대 연속 음봉 수"""
        try:
            bearish = data['close'] < data['open']
            max_consecutive = 0
            current_consecutive = 0
            
            for is_bearish in bearish:
                if is_bearish:
                    current_consecutive += 1
                    max_consecutive = max(max_consecutive, current_consecutive)
                else:
                    current_consecutive = 0
            
            return max_consecutive
        except:
            return 0
    
    def _calculate_ma_alignment(self, data: pd.DataFrame) -> int:
        """이동평균선 배열 점수 (상승=1, 하락=-1, 혼재=0)"""
        try:
            ma5 = data['ma5'].iloc[-1]
            ma10 = data['ma10'].iloc[-1]
            ma20 = data['ma20'].iloc[-1]
            ma60 = data['ma60'].iloc[-1]
            
            if ma5 > ma10 > ma20 > ma60:
                return 1  # 완전 상승 배열
            elif ma5 < ma10 < ma20 < ma60:
                return -1  # 완전 하락 배열
            else:
                return 0  # 혼재
        except:
            return 0
    
    def _calculate_ma_slope(self, ma_series: pd.Series) -> float:
        """이동평균선 기울기"""
        try:
            if len(ma_series) < 2:
                return 0.0
            
            x = np.arange(len(ma_series))
            y = ma_series.dropna().values
            
            if len(y) < 2:
                return 0.0
            
            slope = np.polyfit(x[-len(y):], y, 1)[0]
            return slope / y.mean()  # 정규화
        except:
            return 0.0
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """RSI 계산"""
        try:
            if len(prices) < period + 1:
                return 50.0
            
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
        except:
            return 50.0
    
    def _calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD 계산"""
        try:
            ema_fast = prices.ewm(span=fast).mean()
            ema_slow = prices.ewm(span=slow).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal).mean()
            histogram = macd_line - signal_line
            
            return macd_line, signal_line, histogram
        except:
            return pd.Series(), pd.Series(), pd.Series()
    
    def _calculate_bollinger_bands(self, prices: pd.Series, period: int = 20, std_dev: float = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """볼린저 밴드 계산"""
        try:
            ma = prices.rolling(period).mean()
            std = prices.rolling(period).std()
            
            upper = ma + (std * std_dev)
            lower = ma - (std * std_dev)
            
            return upper, ma, lower
        except:
            return pd.Series(), pd.Series(), pd.Series()
    
    def _calculate_market_strength(self, data: pd.DataFrame) -> float:
        """시장 강도 계산"""
        try:
            # 가격 상승일 비율
            price_changes = data['stck_clpr'].pct_change().dropna()
            positive_days = (price_changes > 0).sum()
            total_days = len(price_changes)
            
            return positive_days / total_days if total_days > 0 else 0.5
        except:
            return 0.5
    
    def _calculate_trend_strength(self, data: pd.DataFrame) -> float:
        """트렌드 강도 계산"""
        try:
            # 최근 20일 가격 변화의 일관성
            price_changes = data['stck_clpr'].pct_change().dropna().tail(20)
            if len(price_changes) < 10:
                return 0.0
            
            # 상승/하락 방향의 일관성
            positive_changes = (price_changes > 0).sum()
            negative_changes = (price_changes < 0).sum()
            
            return abs(positive_changes - negative_changes) / len(price_changes)
        except:
            return 0.0
    
    def _calculate_support_resistance_strength(self, data: pd.DataFrame) -> float:
        """지지/저항 강도 계산"""
        try:
            # 최근 고점/저점의 반복성
            highs = data['stck_hgpr'].rolling(5).max()
            lows = data['stck_lwpr'].rolling(5).min()
            
            # 고점/저점 근처에서의 반응
            high_touches = 0
            low_touches = 0
            
            for i in range(5, len(data)):
                current_high = data['stck_hgpr'].iloc[i]
                current_low = data['stck_lwpr'].iloc[i]
                
                if abs(current_high - highs.iloc[i-1]) / highs.iloc[i-1] < 0.02:
                    high_touches += 1
                if abs(current_low - lows.iloc[i-1]) / lows.iloc[i-1] < 0.02:
                    low_touches += 1
            
            total_touches = high_touches + low_touches
            return total_touches / len(data) if len(data) > 0 else 0.0
        except:
            return 0.0
    
    def _classify_volume_pattern(self, data: pd.DataFrame) -> int:
        """거래량 패턴 분류"""
        try:
            if len(data) < 10:
                return 0
            
            volumes = data['acml_vol'].tail(10)
            volume_trend = self._calculate_volume_trend(data.tail(10))
            
            if volume_trend > 0.1:
                return 1  # 증가 패턴
            elif volume_trend < -0.1:
                return -1  # 감소 패턴
            else:
                return 0  # 횡보 패턴
        except:
            return 0
    
    def _calculate_minute_daily_correlation(self, minute_data: pd.DataFrame, daily_data: pd.DataFrame) -> float:
        """분봉-일봉 상관관계"""
        try:
            if minute_data.empty or daily_data.empty:
                return 0.0
            
            # 분봉 가격 변화율
            minute_returns = minute_data['close'].pct_change().dropna()
            
            # 일봉 가격 변화율
            daily_returns = daily_data['stck_clpr'].pct_change().dropna()
            
            # 상관계수 계산
            correlation = minute_returns.corr(daily_returns)
            return correlation if not pd.isna(correlation) else 0.0
        except:
            return 0.0
    
    def _calculate_pattern_consistency(self, minute_data: pd.DataFrame, daily_data: pd.DataFrame) -> float:
        """패턴 일관성 계산"""
        try:
            if minute_data.empty or daily_data.empty:
                return 0.0
            
            # 분봉과 일봉의 방향성 일치도
            minute_direction = (minute_data['close'].iloc[-1] > minute_data['open'].iloc[0]).astype(int)
            daily_direction = (daily_data['stck_clpr'].iloc[-1] > daily_data['stck_oprc'].iloc[-1]).astype(int)
            
            return 1.0 if minute_direction == daily_direction else 0.0
        except:
            return 0.0
    
    def _calculate_signal_strength(self, minute_data: pd.DataFrame, trade: Dict) -> float:
        """신호 강도 계산"""
        try:
            if minute_data.empty:
                return 0.0
            
            # 거래량 급증 정도
            recent_volume = minute_data['volume'].tail(5).mean()
            avg_volume = minute_data['volume'].mean()
            volume_surge = recent_volume / avg_volume if avg_volume > 0 else 1.0
            
            # 가격 모멘텀
            price_momentum = self._calculate_price_momentum(minute_data, 5)
            
            # 신호 강도 (0-1 정규화)
            signal_strength = min(1.0, (volume_surge - 1.0) * 0.5 + abs(price_momentum) * 10)
            
            return signal_strength
        except:
            return 0.0
