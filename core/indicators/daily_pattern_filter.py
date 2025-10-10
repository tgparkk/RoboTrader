"""
일봉 기반 패턴 필터링 시스템
분석된 패턴을 바탕으로 승리 확률을 높이는 필터링 로직 구현
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from pathlib import Path
import pickle
import json

from utils.logger import setup_logger
from utils.korean_time import now_kst


@dataclass
class FilterResult:
    """필터링 결과"""
    passed: bool
    score: float
    reason: str
    details: Dict[str, Any]


class DailyPatternFilter:
    """일봉 기반 패턴 필터"""
    
    def __init__(self, logger=None):
        self.logger = logger or setup_logger(__name__)
        self.filter_rules = {}
        self.feature_weights = {}
        self.load_filter_config()
    
    def load_filter_config(self, config_file: str = "daily_pattern_analysis.json"):
        """필터 설정 로드"""
        try:
            if Path(config_file).exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 특성 분석 결과에서 필터 규칙 생성
                if 'feature_analysis' in data:
                    self._create_filter_rules_from_analysis(data['feature_analysis'])
                
                self.logger.info(f"✅ 필터 설정 로드 완료: {len(self.filter_rules)}개 규칙")
            else:
                self.logger.warning(f"설정 파일이 없습니다: {config_file}")
                self._create_default_filter_rules()
                
        except Exception as e:
            self.logger.error(f"필터 설정 로드 실패: {e}")
            self._create_default_filter_rules()
    
    def _create_filter_rules_from_analysis(self, feature_analysis: Dict[str, Any]):
        """분석 결과에서 필터 규칙 생성"""
        try:
            # 상위 특성들을 기반으로 필터 규칙 생성
            sorted_features = sorted(
                feature_analysis.items(),
                key=lambda x: x[1]['normalized_weight'],
                reverse=True
            )
            
            for feature, analysis in sorted_features[:10]:  # 상위 10개 특성만 사용
                if not analysis['significance']:
                    continue
                
                win_mean = analysis['win_mean']
                win_std = analysis['win_std']
                difference = analysis['difference']
                weight = analysis['normalized_weight']
                
                # 필터 임계값 설정
                if difference > 0:
                    # 승리 패턴이 더 높은 값을 가짐
                    threshold = win_mean - 0.5 * win_std
                    condition = "greater_than"
                else:
                    # 승리 패턴이 더 낮은 값을 가짐
                    threshold = win_mean + 0.5 * win_std
                    condition = "less_than"
                
                self.filter_rules[feature] = {
                    'threshold': threshold,
                    'condition': condition,
                    'weight': weight,
                    'description': f"{feature}: {condition} {threshold:.3f}",
                    'win_mean': win_mean,
                    'loss_mean': analysis['loss_mean'],
                    'difference': difference
                }
                
        except Exception as e:
            self.logger.error(f"필터 규칙 생성 실패: {e}")
    
    def _create_default_filter_rules(self):
        """기본 필터 규칙 생성"""
        # 분석 결과를 바탕으로 한 기본 규칙들
        self.filter_rules = {
            'consecutive_down_days': {
                'threshold': 0.5,
                'condition': 'greater_than',
                'weight': 1.0,
                'description': "연속 하락일: 0.5일 이상",
                'win_mean': 0.769,
                'loss_mean': 0.538,
                'difference': 0.231
            },
            'gap_magnitude': {
                'threshold': 0.8,
                'condition': 'less_than',
                'weight': 0.663,
                'description': "갭 크기: 0.8% 미만",
                'win_mean': 0.794,
                'loss_mean': 0.964,
                'difference': -0.170
            },
            'volatility_10d': {
                'threshold': 7.0,
                'condition': 'less_than',
                'weight': 0.342,
                'description': "10일 변동성: 7.0% 미만",
                'win_mean': 6.606,
                'loss_mean': 6.896,
                'difference': -0.291
            },
            'trend_strength_5d': {
                'threshold': 2.0,
                'condition': 'greater_than',
                'weight': 0.295,
                'description': "5일 추세강도: 2.0% 이상",
                'win_mean': 2.835,
                'loss_mean': 2.638,
                'difference': 0.197
            },
            'support_resistance_ratio': {
                'threshold': 0.7,
                'condition': 'greater_than',
                'weight': 0.490,
                'description': "지지/저항 비율: 0.7 이상",
                'win_mean': 0.708,
                'loss_mean': 0.732,
                'difference': -0.023
            }
        }
        
        self.logger.info(f"✅ 기본 필터 규칙 생성: {len(self.filter_rules)}개")
    
    def load_daily_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드"""
        try:
            daily_cache_dir = Path("cache/daily_data")
            daily_file = daily_cache_dir / f"{stock_code}_daily.pkl"
            
            if not daily_file.exists():
                return None
                
            with open(daily_file, 'rb') as f:
                data = pickle.load(f)
            
            # 컬럼명 정리 및 데이터 타입 변환
            if 'stck_bsop_date' in data.columns:
                data['date'] = pd.to_datetime(data['stck_bsop_date'])
            if 'stck_clpr' in data.columns:
                data['close'] = pd.to_numeric(data['stck_clpr'], errors='coerce')
            if 'stck_oprc' in data.columns:
                data['open'] = pd.to_numeric(data['stck_oprc'], errors='coerce')
            if 'stck_hgpr' in data.columns:
                data['high'] = pd.to_numeric(data['stck_hgpr'], errors='coerce')
            if 'stck_lwpr' in data.columns:
                data['low'] = pd.to_numeric(data['stck_lwpr'], errors='coerce')
            if 'acml_vol' in data.columns:
                data['volume'] = pd.to_numeric(data['acml_vol'], errors='coerce')
                
            return data.sort_values('date').reset_index(drop=True)
            
        except Exception as e:
            self.logger.debug(f"일봉 데이터 로드 실패 {stock_code}: {e}")
            return None
    
    def extract_daily_features(self, daily_data: pd.DataFrame, signal_date: str) -> Dict[str, float]:
        """일봉 데이터에서 특성 추출 (패턴 분석기와 동일한 로직)"""
        features = {}
        
        try:
            if daily_data is None or daily_data.empty:
                return features
            
            # 신호 날짜 이전 데이터만 사용
            signal_dt = pd.to_datetime(signal_date)
            historical_data = daily_data[daily_data['date'] < signal_dt].copy()
            
            if len(historical_data) < 5:
                return features
            
            # 최근 5일, 10일, 20일 데이터
            recent_5d = historical_data.tail(5)
            recent_10d = historical_data.tail(10)
            recent_20d = historical_data.tail(20)
            
            # 1. 가격 모멘텀 특성
            features['price_momentum_5d'] = self._calculate_price_momentum(recent_5d)
            features['price_momentum_10d'] = self._calculate_price_momentum(recent_10d)
            features['price_momentum_20d'] = self._calculate_price_momentum(recent_20d)
            
            # 2. 거래량 특성
            features['volume_ratio_5d'] = self._calculate_volume_ratio(recent_5d)
            features['volume_ratio_10d'] = self._calculate_volume_ratio(recent_10d)
            features['volume_ratio_20d'] = self._calculate_volume_ratio(recent_20d)
            
            # 3. 변동성 특성
            features['volatility_5d'] = self._calculate_volatility(recent_5d)
            features['volatility_10d'] = self._calculate_volatility(recent_10d)
            features['volatility_20d'] = self._calculate_volatility(recent_20d)
            
            # 4. 추세 특성
            features['trend_strength_5d'] = self._calculate_trend_strength(recent_5d)
            features['trend_strength_10d'] = self._calculate_trend_strength(recent_10d)
            features['trend_strength_20d'] = self._calculate_trend_strength(recent_20d)
            
            # 5. 지지/저항 특성
            features['support_resistance_ratio'] = self._calculate_support_resistance_ratio(historical_data)
            
            # 6. 연속 상승/하락 특성
            features['consecutive_up_days'] = self._calculate_consecutive_days(recent_10d, 'up')
            features['consecutive_down_days'] = self._calculate_consecutive_days(recent_10d, 'down')
            
            # 7. 갭 특성
            features['gap_frequency'] = self._calculate_gap_frequency(recent_10d)
            features['gap_magnitude'] = self._calculate_gap_magnitude(recent_10d)
            
        except Exception as e:
            self.logger.debug(f"일봉 특성 추출 실패: {e}")
        
        return features
    
    def _calculate_price_momentum(self, data: pd.DataFrame) -> float:
        """가격 모멘텀 계산"""
        if len(data) < 2:
            return 0.0
        
        start_price = data['close'].iloc[0]
        end_price = data['close'].iloc[-1]
        
        if start_price == 0:
            return 0.0
        
        return (end_price - start_price) / start_price * 100
    
    def _calculate_volume_ratio(self, data: pd.DataFrame) -> float:
        """거래량 비율 계산 (평균 대비)"""
        if len(data) < 2:
            return 1.0
        
        recent_volume = data['volume'].iloc[-1]
        avg_volume = data['volume'].mean()
        
        if avg_volume == 0:
            return 1.0
        
        return recent_volume / avg_volume
    
    def _calculate_volatility(self, data: pd.DataFrame) -> float:
        """변동성 계산 (일일 수익률의 표준편차)"""
        if len(data) < 2:
            return 0.0
        
        returns = data['close'].pct_change().dropna()
        return returns.std() * 100
    
    def _calculate_trend_strength(self, data: pd.DataFrame) -> float:
        """추세 강도 계산 (선형 회귀 기울기)"""
        if len(data) < 3:
            return 0.0
        
        x = np.arange(len(data))
        y = data['close'].values
        
        # 선형 회귀
        coeffs = np.polyfit(x, y, 1)
        slope = coeffs[0]
        
        # 정규화 (가격 대비)
        avg_price = data['close'].mean()
        if avg_price == 0:
            return 0.0
        
        return (slope / avg_price) * 100
    
    def _calculate_support_resistance_ratio(self, data: pd.DataFrame) -> float:
        """지지/저항 비율 계산"""
        if len(data) < 10:
            return 0.5
        
        recent_20d = data.tail(20)
        current_price = recent_20d['close'].iloc[-1]
        
        # 최근 20일 고가/저가 범위에서 현재가 위치
        high_20d = recent_20d['high'].max()
        low_20d = recent_20d['low'].min()
        
        if high_20d == low_20d:
            return 0.5
        
        return (current_price - low_20d) / (high_20d - low_20d)
    
    def _calculate_consecutive_days(self, data: pd.DataFrame, direction: str) -> int:
        """연속 상승/하락 일수 계산"""
        if len(data) < 2:
            return 0
        
        consecutive = 0
        for i in range(len(data) - 1, 0, -1):
            if direction == 'up' and data['close'].iloc[i] > data['close'].iloc[i-1]:
                consecutive += 1
            elif direction == 'down' and data['close'].iloc[i] < data['close'].iloc[i-1]:
                consecutive += 1
            else:
                break
        
        return consecutive
    
    def _calculate_gap_frequency(self, data: pd.DataFrame) -> float:
        """갭 빈도 계산"""
        if len(data) < 2:
            return 0.0
        
        gaps = 0
        for i in range(1, len(data)):
            prev_close = data['close'].iloc[i-1]
            curr_open = data['open'].iloc[i]
            
            # 갭 크기가 1% 이상인 경우
            if abs(curr_open - prev_close) / prev_close > 0.01:
                gaps += 1
        
        return gaps / (len(data) - 1)
    
    def _calculate_gap_magnitude(self, data: pd.DataFrame) -> float:
        """갭 크기 계산"""
        if len(data) < 2:
            return 0.0
        
        gap_magnitudes = []
        for i in range(1, len(data)):
            prev_close = data['close'].iloc[i-1]
            curr_open = data['open'].iloc[i]
            
            if prev_close != 0:
                gap_mag = (curr_open - prev_close) / prev_close * 100
                gap_magnitudes.append(gap_mag)
        
        return np.mean(gap_magnitudes) if gap_magnitudes else 0.0
    
    def apply_filter(self, stock_code: str, signal_date: str, signal_time: str) -> FilterResult:
        """일봉 기반 필터 적용"""
        try:
            # 일봉 데이터 로드
            daily_data = self.load_daily_data(stock_code, signal_date)
            if daily_data is None:
                return FilterResult(
                    passed=False,
                    score=0.0,
                    reason="일봉 데이터 없음",
                    details={}
                )
            
            # 특성 추출
            features = self.extract_daily_features(daily_data, signal_date)
            if not features:
                return FilterResult(
                    passed=False,
                    score=0.0,
                    reason="특성 추출 실패",
                    details={}
                )
            
            # 필터 규칙 적용
            passed_rules = 0
            total_rules = 0
            total_score = 0.0
            details = {}
            
            for feature, rule in self.filter_rules.items():
                if feature not in features:
                    continue
                
                total_rules += 1
                feature_value = features[feature]
                threshold = rule['threshold']
                condition = rule['condition']
                weight = rule['weight']
                
                # 조건 확인
                if condition == 'greater_than':
                    passed = feature_value > threshold
                elif condition == 'less_than':
                    passed = feature_value < threshold
                else:
                    passed = False
                
                if passed:
                    passed_rules += 1
                    total_score += weight
                
                details[feature] = {
                    'value': feature_value,
                    'threshold': threshold,
                    'condition': condition,
                    'passed': passed,
                    'weight': weight
                }
            
            # 최종 판정
            pass_rate = passed_rules / total_rules if total_rules > 0 else 0
            min_pass_rate = 0.6  # 60% 이상의 규칙을 통과해야 함
            
            passed = pass_rate >= min_pass_rate
            reason = f"통과율: {pass_rate:.1%} ({passed_rules}/{total_rules})"
            
            if not passed:
                reason += f" (최소 요구: {min_pass_rate:.1%})"
            
            return FilterResult(
                passed=passed,
                score=total_score,
                reason=reason,
                details=details
            )
            
        except Exception as e:
            self.logger.error(f"필터 적용 실패 {stock_code}: {e}")
            return FilterResult(
                passed=False,
                score=0.0,
                reason=f"필터 오류: {str(e)[:50]}",
                details={}
            )
    
    def get_filter_summary(self) -> Dict[str, Any]:
        """필터 요약 정보 반환"""
        return {
            'total_rules': len(self.filter_rules),
            'rules': self.filter_rules,
            'description': "일봉 기반 패턴 필터링 시스템"
        }


def main():
    """테스트 실행"""
    filter_system = DailyPatternFilter()
    
    # 필터 요약 출력
    summary = filter_system.get_filter_summary()
    print("🎯 일봉 기반 패턴 필터링 시스템")
    print("=" * 50)
    print(f"총 규칙 수: {summary['total_rules']}")
    print("\n📋 필터 규칙:")
    
    for feature, rule in summary['rules'].items():
        print(f"• {rule['description']} (가중치: {rule['weight']:.3f})")
        print(f"  승리 평균: {rule['win_mean']:.3f}, 패배 평균: {rule['loss_mean']:.3f}")
        print(f"  차이: {rule['difference']:+.3f}")
        print()


if __name__ == "__main__":
    main()
