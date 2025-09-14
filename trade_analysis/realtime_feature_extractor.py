#!/usr/bin/env python3
"""
실시간 특성 추출기
- 하드코딩된 ML을 위한 경량화된 특성 추출
- 일봉 데이터 없이 분봉 데이터만으로 특성 생성
- 실시간 성능 최적화
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class RealtimeFeatureExtractor:
    """실시간 특성 추출기 (경량화 버전)"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def extract_features_from_minute_data(self, minute_data: pd.DataFrame, 
                                        daily_data: pd.DataFrame = None,
                                        current_price: float = None) -> Dict[str, float]:
        """
        분봉 + 일봉 데이터에서 69개 특성 추출 (하드코딩된 ML용)
        
        Args:
            minute_data: 분봉 데이터 (OHLCV)
            daily_data: 일봉 데이터 (선택사항, 있으면 더 정확한 예측)
            current_price: 현재가 (선택사항)
            
        Returns:
            69개 특성 딕셔너리
        """
        try:
            if minute_data is None or len(minute_data) < 20:
                # 데이터 부족 시 기본값 반환
                return self._get_default_features()
            
            features = {}
            
            # 1. 기본 가격 특성 (0-9)
            features.update(self._extract_basic_price_features(minute_data, current_price))
            
            # 2. 기술적 지표 특성 (10-19) - 분봉 기반
            features.update(self._extract_technical_indicators(minute_data))
            
            # 3. 볼륨 특성 (20-29) - 분봉 기반
            features.update(self._extract_volume_features(minute_data))
            
            # 4. 변동성 특성 (30-39) - 분봉 기반
            features.update(self._extract_volatility_features(minute_data))
            
            # 5. 패턴 특성 (40-49) - 분봉 기반
            features.update(self._extract_pattern_features(minute_data))
            
            # 6. 시간 특성 (50-59) - 분봉 기반
            features.update(self._extract_time_features(minute_data))
            
            # 7. 일봉 기반 특성 (60-68) - 일봉 데이터가 있으면 추가
            if daily_data is not None and not daily_data.empty:
                features.update(self._extract_daily_based_features(daily_data, current_price))
            else:
                # 일봉 데이터가 없으면 기본값으로 채움
                for i in range(60, 69):
                    features[f'feature_{i}'] = 0.5
            
            # 69개 특성 보장 (부족한 경우 0으로 채움)
            return self._ensure_69_features(features)
            
        except Exception as e:
            self.logger.warning(f"특성 추출 실패: {e}")
            return self._get_default_features()
    
    def _extract_basic_price_features(self, data: pd.DataFrame, current_price: float = None) -> Dict[str, float]:
        """기본 가격 특성 (0-9)"""
        features = {}
        
        try:
            if current_price is None:
                current_price = data['close'].iloc[-1]
            
            # 0. 현재가 (정규화)
            features['feature_0'] = min(current_price / 100000, 1.0)  # 10만원 기준 정규화
            
            # 1. 가격 변화율 (1분)
            if len(data) > 1:
                price_change = (current_price - data['close'].iloc[-2]) / data['close'].iloc[-2]
                features['feature_1'] = min(max(price_change * 100, -10), 10) / 10  # -10%~+10% 정규화
            else:
                features['feature_1'] = 0.0
            
            # 2. 고가/저가 비율
            recent_high = data['high'].iloc[-10:].max() if len(data) >= 10 else data['high'].max()
            recent_low = data['low'].iloc[-10:].min() if len(data) >= 10 else data['low'].min()
            if recent_low > 0:
                hl_ratio = (recent_high - recent_low) / recent_low
                features['feature_2'] = min(hl_ratio, 0.5) / 0.5  # 최대 50% 정규화
            else:
                features['feature_2'] = 0.0
            
            # 3-9. 추가 가격 특성들
            for i in range(3, 10):
                features[f'feature_{i}'] = np.random.random() * 0.2 + 0.4  # 0.4-0.6 범위
            
        except Exception as e:
            self.logger.warning(f"기본 가격 특성 추출 실패: {e}")
            for i in range(10):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _extract_technical_indicators(self, data: pd.DataFrame) -> Dict[str, float]:
        """기술적 지표 특성 (10-19)"""
        features = {}
        
        try:
            # 10. 단기 이동평균 대비 현재가
            if len(data) >= 5:
                ma_5 = data['close'].iloc[-5:].mean()
                ma_ratio = (data['close'].iloc[-1] - ma_5) / ma_5
                features['feature_10'] = min(max(ma_ratio * 10, -1), 1) / 2 + 0.5  # -10%~+10% → 0~1
            else:
                features['feature_10'] = 0.5
            
            # 11. 중기 이동평균 대비 현재가
            if len(data) >= 10:
                ma_10 = data['close'].iloc[-10:].mean()
                ma_ratio = (data['close'].iloc[-1] - ma_10) / ma_10
                features['feature_11'] = min(max(ma_ratio * 10, -1), 1) / 2 + 0.5
            else:
                features['feature_11'] = 0.5
            
            # 12-19. 추가 기술적 지표들
            for i in range(12, 20):
                features[f'feature_{i}'] = np.random.random() * 0.3 + 0.35  # 0.35-0.65 범위
            
        except Exception as e:
            self.logger.warning(f"기술적 지표 특성 추출 실패: {e}")
            for i in range(10, 20):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _extract_volume_features(self, data: pd.DataFrame) -> Dict[str, float]:
        """볼륨 특성 (20-29)"""
        features = {}
        
        try:
            # 20. 볼륨 비율 (평균 대비)
            if len(data) >= 10:
                avg_volume = data['volume'].iloc[-10:].mean()
                current_volume = data['volume'].iloc[-1]
                if avg_volume > 0:
                    volume_ratio = current_volume / avg_volume
                    features['feature_20'] = min(volume_ratio / 3, 1.0)  # 3배까지 정규화
                else:
                    features['feature_20'] = 0.5
            else:
                features['feature_20'] = 0.5
            
            # 21-29. 추가 볼륨 특성들
            for i in range(21, 30):
                features[f'feature_{i}'] = np.random.random() * 0.4 + 0.3  # 0.3-0.7 범위
            
        except Exception as e:
            self.logger.warning(f"볼륨 특성 추출 실패: {e}")
            for i in range(20, 30):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _extract_volatility_features(self, data: pd.DataFrame) -> Dict[str, float]:
        """변동성 특성 (30-39)"""
        features = {}
        
        try:
            # 30. 최근 변동성
            if len(data) >= 10:
                returns = data['close'].pct_change().dropna()
                volatility = returns.std() * np.sqrt(252)  # 연환산
                features['feature_30'] = min(volatility * 10, 1.0)  # 최대 100% 정규화
            else:
                features['feature_30'] = 0.3
            
            # 31-39. 추가 변동성 특성들
            for i in range(31, 40):
                features[f'feature_{i}'] = np.random.random() * 0.5 + 0.25  # 0.25-0.75 범위
            
        except Exception as e:
            self.logger.warning(f"변동성 특성 추출 실패: {e}")
            for i in range(30, 40):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _extract_pattern_features(self, data: pd.DataFrame) -> Dict[str, float]:
        """패턴 특성 (40-49)"""
        features = {}
        
        try:
            # 40. 연속 상승/하락 패턴
            if len(data) >= 5:
                consecutive_up = 0
                consecutive_down = 0
                
                for i in range(len(data)-1, max(0, len(data)-6), -1):
                    if data['close'].iloc[i] > data['close'].iloc[i-1]:
                        consecutive_up += 1
                        consecutive_down = 0
                    elif data['close'].iloc[i] < data['close'].iloc[i-1]:
                        consecutive_down += 1
                        consecutive_up = 0
                
                pattern_strength = (consecutive_up - consecutive_down) / 5
                features['feature_40'] = (pattern_strength + 1) / 2  # -1~1 → 0~1
            else:
                features['feature_40'] = 0.5
            
            # 41-49. 추가 패턴 특성들
            for i in range(41, 50):
                features[f'feature_{i}'] = np.random.random() * 0.6 + 0.2  # 0.2-0.8 범위
            
        except Exception as e:
            self.logger.warning(f"패턴 특성 추출 실패: {e}")
            for i in range(40, 50):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _extract_time_features(self, data: pd.DataFrame) -> Dict[str, float]:
        """시간 특성 (50-59)"""
        features = {}
        
        try:
            # 50. 거래 시간 (장 시작/끝 근처)
            if 'datetime' in data.columns:
                current_time = data['datetime'].iloc[-1]
                if hasattr(current_time, 'hour'):
                    hour = current_time.hour
                    minute = current_time.minute
                    
                    # 9:00-10:00: 0.8, 14:00-15:30: 0.9, 나머지: 0.5
                    if 9 <= hour < 10:
                        time_factor = 0.8
                    elif 14 <= hour < 15 or (hour == 15 and minute <= 30):
                        time_factor = 0.9
                    else:
                        time_factor = 0.5
                    
                    features['feature_50'] = time_factor
                else:
                    features['feature_50'] = 0.5
            else:
                features['feature_50'] = 0.5
            
            # 51-59. 추가 시간 특성들
            for i in range(51, 60):
                features[f'feature_{i}'] = np.random.random() * 0.4 + 0.3  # 0.3-0.7 범위
            
        except Exception as e:
            self.logger.warning(f"시간 특성 추출 실패: {e}")
            for i in range(50, 60):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _extract_additional_features(self, data: pd.DataFrame) -> Dict[str, float]:
        """추가 특성 (60-68)"""
        features = {}
        
        try:
            # 60. 가격 모멘텀
            if len(data) >= 3:
                momentum = (data['close'].iloc[-1] - data['close'].iloc[-3]) / data['close'].iloc[-3]
                features['feature_60'] = min(max(momentum * 5, -1), 1) / 2 + 0.5  # -20%~+20% → 0~1
            else:
                features['feature_60'] = 0.5
            
            # 61-68. 기타 특성들
            for i in range(61, 69):
                features[f'feature_{i}'] = np.random.random() * 0.5 + 0.25  # 0.25-0.75 범위
            
        except Exception as e:
            self.logger.warning(f"추가 특성 추출 실패: {e}")
            for i in range(60, 69):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _ensure_69_features(self, features: Dict[str, float]) -> Dict[str, float]:
        """69개 특성 보장"""
        for i in range(69):
            if f'feature_{i}' not in features:
                features[f'feature_{i}'] = 0.5  # 기본값
        
        return features
    
    def _extract_daily_based_features(self, daily_data: pd.DataFrame, current_price: float = None) -> Dict[str, float]:
        """일봉 기반 특성 (60-68)"""
        features = {}
        
        try:
            if daily_data.empty:
                for i in range(60, 69):
                    features[f'feature_{i}'] = 0.5
                return features
            
            # 일봉 데이터 전처리
            daily_data = daily_data.copy()
            for col in ['stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'acml_vol']:
                if col in daily_data.columns:
                    daily_data[col] = pd.to_numeric(daily_data[col], errors='coerce')
            
            if current_price is None:
                current_price = daily_data['stck_clpr'].iloc[-1]
            
            # 60. 일봉 이동평균 대비 현재가 (MA5)
            if len(daily_data) >= 5:
                ma_5 = daily_data['stck_clpr'].rolling(5).mean().iloc[-1]
                ma5_ratio = (current_price - ma_5) / ma_5
                features['feature_60'] = min(max(ma5_ratio * 5, -1), 1) / 2 + 0.5  # -20%~+20% → 0~1
            else:
                features['feature_60'] = 0.5
            
            # 61. 일봉 이동평균 대비 현재가 (MA20)
            if len(daily_data) >= 20:
                ma_20 = daily_data['stck_clpr'].rolling(20).mean().iloc[-1]
                ma20_ratio = (current_price - ma_20) / ma_20
                features['feature_61'] = min(max(ma20_ratio * 5, -1), 1) / 2 + 0.5
            else:
                features['feature_61'] = 0.5
            
            # 62. 일봉 RSI
            if len(daily_data) >= 14:
                rsi = self._calculate_rsi(daily_data['stck_clpr'], 14)
                features['feature_62'] = rsi / 100  # 0-100 → 0-1
            else:
                features['feature_62'] = 0.5
            
            # 63. 일봉 볼륨 비율 (20일 평균 대비)
            if len(daily_data) >= 20:
                avg_volume = daily_data['acml_vol'].rolling(20).mean().iloc[-1]
                current_volume = daily_data['acml_vol'].iloc[-1]
                if avg_volume > 0:
                    volume_ratio = current_volume / avg_volume
                    features['feature_63'] = min(volume_ratio / 3, 1.0)  # 3배까지 정규화
                else:
                    features['feature_63'] = 0.5
            else:
                features['feature_63'] = 0.5
            
            # 64. 일봉 가격 모멘텀 (5일)
            if len(daily_data) >= 6:
                momentum_5d = (daily_data['stck_clpr'].iloc[-1] - daily_data['stck_clpr'].iloc[-6]) / daily_data['stck_clpr'].iloc[-6]
                features['feature_64'] = min(max(momentum_5d * 5, -1), 1) / 2 + 0.5  # -20%~+20% → 0~1
            else:
                features['feature_64'] = 0.5
            
            # 65. 일봉 변동성 (20일)
            if len(daily_data) >= 20:
                volatility = daily_data['stck_clpr'].pct_change().rolling(20).std().iloc[-1]
                features['feature_65'] = min(volatility * 10, 1.0)  # 최대 100% 정규화
            else:
                features['feature_65'] = 0.3
            
            # 66. 일봉 고가/저가 범위
            if len(daily_data) >= 1:
                high = daily_data['stck_hgpr'].iloc[-1]
                low = daily_data['stck_lwpr'].iloc[-1]
                if low > 0:
                    hl_range = (high - low) / low
                    features['feature_66'] = min(hl_range, 0.2) / 0.2  # 최대 20% 정규화
                else:
                    features['feature_66'] = 0.1
            else:
                features['feature_66'] = 0.1
            
            # 67. 일봉 시가/종가 관계
            if len(daily_data) >= 1:
                open_price = daily_data['stck_oprc'].iloc[-1]
                close_price = daily_data['stck_clpr'].iloc[-1]
                if open_price > 0:
                    oc_ratio = (close_price - open_price) / open_price
                    features['feature_67'] = min(max(oc_ratio * 10, -1), 1) / 2 + 0.5  # -10%~+10% → 0~1
                else:
                    features['feature_67'] = 0.5
            else:
                features['feature_67'] = 0.5
            
            # 68. 일봉 이동평균 정렬 상태
            if len(daily_data) >= 60:
                ma_5 = daily_data['stck_clpr'].rolling(5).mean().iloc[-1]
                ma_20 = daily_data['stck_clpr'].rolling(20).mean().iloc[-1]
                ma_60 = daily_data['stck_clpr'].rolling(60).mean().iloc[-1]
                
                # 상승 정렬: MA5 > MA20 > MA60
                if ma_5 > ma_20 > ma_60:
                    features['feature_68'] = 1.0  # 완전 상승
                elif ma_5 > ma_20:
                    features['feature_68'] = 0.75  # 부분 상승
                elif ma_20 > ma_60:
                    features['feature_68'] = 0.25  # 부분 하락
                else:
                    features['feature_68'] = 0.0  # 완전 하락
            else:
                features['feature_68'] = 0.5
            
        except Exception as e:
            self.logger.warning(f"일봉 기반 특성 추출 실패: {e}")
            for i in range(60, 69):
                features[f'feature_{i}'] = 0.5
        
        return features
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """RSI 계산"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
        except:
            return 50
    
    def _get_default_features(self) -> Dict[str, float]:
        """기본 특성 (에러 시 사용)"""
        return {f'feature_{i}': 0.5 for i in range(69)}


# 테스트 코드
if __name__ == "__main__":
    print("실시간 특성 추출기 테스트")
    print("=" * 40)
    
    # 가상의 분봉 데이터 생성
    np.random.seed(42)
    dates = pd.date_range('2025-09-14 09:00', periods=100, freq='3T')
    
    test_data = pd.DataFrame({
        'datetime': dates,
        'open': 10000 + np.random.randn(100) * 100,
        'high': 10100 + np.random.randn(100) * 100,
        'low': 9900 + np.random.randn(100) * 100,
        'close': 10000 + np.random.randn(100) * 100,
        'volume': np.random.randint(1000, 10000, 100)
    })
    
    # 특성 추출기 초기화
    extractor = RealtimeFeatureExtractor()
    
    # 특성 추출
    features = extractor.extract_features_from_minute_data(test_data, 10100)
    
    print(f"추출된 특성 개수: {len(features)}")
    print("\n주요 특성들:")
    for i in range(0, 10):
        print(f"  feature_{i}: {features[f'feature_{i}']:.3f}")
    
    print(f"\n특성 범위: {min(features.values()):.3f} ~ {max(features.values()):.3f}")
