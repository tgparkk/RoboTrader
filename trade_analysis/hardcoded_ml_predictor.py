#!/usr/bin/env python3
"""
하드코딩된 경량화 ML 예측기
- 파일 로딩 없이 즉시 예측
- 실시간 성능 최적화
- 자동 생성됨 - 수동 편집하지 마세요
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple
from datetime import datetime
import logging

# 추출된 파라미터 import
from .extracted_model_params import EXTRACTED_PARAMS, get_model_params, get_feature_importances, get_scaler_params

logger = logging.getLogger(__name__)

class HardcodedMLPredictor:
    """하드코딩된 경량화 ML 예측기"""
    
    def __init__(self):
        """초기화 - 파일 로딩 없이 메모리에서 즉시 초기화"""
        self.scaler_params = get_scaler_params()
        self.model_params = {}
        self.is_ready = False
        
        # 사용 가능한 모델들 확인
        for model_name in EXTRACTED_PARAMS.keys():
            if model_name not in ['scaler', 'label_encoders']:
                params = get_model_params(model_name)
                if 'error' not in params:
                    self.model_params[model_name] = params
        
        if self.model_params:
            self.is_ready = True
            logger.info(f"경량화 ML 예측기 초기화 완료: {len(self.model_params)}개 모델")
        else:
            logger.error("사용 가능한 모델이 없습니다")
    
    def _scale_features(self, features: np.ndarray) -> np.ndarray:
        """특성 스케일링 (하드코딩된 파라미터 사용)"""
        if not self.scaler_params or 'mean' not in self.scaler_params:
            return features
        
        try:
            mean = np.array(self.scaler_params['mean'])
            scale = np.array(self.scaler_params['scale'])
            
            # StandardScaler 공식: (x - mean) / scale
            return (features - mean) / scale
            
        except Exception as e:
            logger.warning(f"특성 스케일링 실패: {e}")
            return features
    
    def _predict_with_feature_importance(self, features: np.ndarray, model_name: str) -> float:
        """
        특성 중요도를 이용한 간단한 예측
        실제 트리 구조 대신 선형 결합으로 근사
        """
        try:
            importances = get_feature_importances(model_name)
            if not importances:
                return 0.5  # 기본값
            
            # 특성과 중요도의 가중 합
            importances = np.array(importances)
            
            # 특성 개수 맞추기
            min_len = min(len(features), len(importances))
            if min_len == 0:
                return 0.5
            
            weighted_sum = np.sum(features[:min_len] * importances[:min_len])
            
            # 시그모이드 함수로 0-1 범위로 변환
            prediction = 1 / (1 + np.exp(-weighted_sum))
            
            return prediction
            
        except Exception as e:
            logger.warning(f"예측 실패 ({model_name}): {e}")
            return 0.5
    
    def predict_trade_outcome_fast(self, features: Dict[str, float]) -> Dict[str, Any]:
        """
        빠른 거래 결과 예측
        
        Args:
            features: 추출된 특성 딕셔너리
        
        Returns:
            예측 결과 딕셔너리
        """
        try:
            if not self.is_ready:
                return {"error": "예측기가 준비되지 않았습니다"}
            
            # 특성을 numpy 배열로 변환
            feature_values = list(features.values())
            X = np.array(feature_values).reshape(1, -1)
            
            # 스케일링
            X_scaled = self._scale_features(X[0])
            
            predictions = {}
            
            # 각 모델로 예측
            for model_name, params in self.model_params.items():
                if 'classifier' in model_name:
                    # 분류 예측 (승률)
                    win_prob = self._predict_with_feature_importance(X_scaled, model_name)
                    predictions[f"{model_name}_win_prob"] = win_prob
                elif 'regressor' in model_name:
                    # 회귀 예측 (수익률)
                    profit = self._predict_with_feature_importance(X_scaled, model_name)
                    # -10% ~ +10% 범위로 변환
                    profit_pct = (profit - 0.5) * 20
                    predictions[f"{model_name}_profit"] = profit_pct
            
            # 앙상블 예측
            win_probs = [v for k, v in predictions.items() if 'win_prob' in k]
            profit_pcts = [v for k, v in predictions.items() if 'profit' in k]
            
            if win_probs:
                avg_win_prob = np.mean(win_probs)
            else:
                avg_win_prob = 0.5
                
            if profit_pcts:
                avg_profit = np.mean(profit_pcts)
            else:
                avg_profit = 0.0
            
            # 액션 결정
            if avg_win_prob >= 0.80:
                action = "STRONG_BUY"
            elif avg_win_prob >= 0.65:
                action = "BUY"
            elif avg_win_prob >= 0.55:
                action = "WEAK_BUY"
            else:
                action = "SKIP"
            
            # 신뢰도 계산
            confidence_score = max(0.5, min(1.0, (abs(avg_win_prob - 0.5) * 2)))
            
            result = {
                'recommendation': {
                    'action': action,
                    'win_probability': avg_win_prob,
                    'expected_profit': avg_profit,
                    'confidence': confidence_score
                },
                'predictions': predictions,
                'model_count': len(self.model_params),
                'prediction_time': datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"빠른 예측 실패: {e}")
            return {"error": str(e)}
    
    def get_status(self) -> Dict[str, Any]:
        """예측기 상태 조회"""
        return {
            'is_ready': self.is_ready,
            'model_count': len(self.model_params),
            'models': list(self.model_params.keys()),
            'has_scaler': bool(self.scaler_params),
            'scaler_features': self.scaler_params.get('n_features', 0) if self.scaler_params else 0
        }


# 테스트 코드
if __name__ == "__main__":
    print("🧪 하드코딩된 ML 예측기 테스트")
    print("=" * 40)
    
    # 예측기 초기화
    predictor = HardcodedMLPredictor()
    
    # 상태 확인
    status = predictor.get_status()
    print(f"예측기 상태: {status}")
    
    if status['is_ready']:
        # 가상의 특성으로 테스트
        test_features = {
            f'feature_{i}': np.random.random() for i in range(50)
        }
        
        print(f"\n테스트 특성: {len(test_features)}개")
        
        # 예측 실행
        result = predictor.predict_trade_outcome_fast(test_features)
        
        if 'error' in result:
            print(f"❌ 예측 실패: {result['error']}")
        else:
            rec = result['recommendation']
            print(f"\n🎯 예측 결과:")
            print(f"   액션: {rec['action']}")
            print(f"   승률: {rec['win_probability']:.1%}")
            print(f"   예상수익: {rec['expected_profit']:.2f}%")
            print(f"   신뢰도: {rec['confidence']:.1%}")
    else:
        print("❌ 예측기 초기화 실패")
