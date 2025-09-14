#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
머신러닝 모델을 활용한 신호 강화 시스템
- 기존 신호와 ML 예측 결과 결합
- 신호 신뢰도 향상
- 리스크 관리 개선
"""

import os
import sys
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import logging
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml_data_collector import MLDataCollector
from ml_feature_engineer import MLFeatureEngineer
from utils.logger import setup_logger

logger = setup_logger(__name__)

class MLSignalEnhancer:
    """머신러닝 신호 강화 시스템"""
    
    def __init__(self, model_dir: str = "trade_analysis/ml_models"):
        self.logger = logging.getLogger(__name__)
        self.model_dir = Path(model_dir)
        
        # 데이터 수집기 및 특성 추출기
        self.data_collector = MLDataCollector()
        self.feature_engineer = MLFeatureEngineer()
        
        # 학습된 모델들
        self.models = {}
        self.scaler = None
        self.label_encoders = {}
        
        # 모델 로드
        self.load_models()
        
        # 신호 강화 설정
        self.enhancement_config = {
            'min_win_probability': 0.6,  # 최소 승률 확률
            'min_profit_prediction': 1.0,  # 최소 예상 수익률 (%)
            'max_risk_score': 0.4,  # 최대 리스크 점수
            'confidence_boost_factor': 1.2,  # 신뢰도 부스트 계수
        }
    
    def load_models(self):
        """저장된 모델 로드"""
        try:
            if not self.model_dir.exists():
                self.logger.warning("⚠️ 모델 디렉토리가 없습니다. 먼저 학습을 실행하세요.")
                return False
            
            # 모델 로드
            for model_file in self.model_dir.glob("*.pkl"):
                if model_file.name not in ["scaler.pkl", "label_encoders.pkl"]:
                    model_name = model_file.stem
                    with open(model_file, 'rb') as f:
                        self.models[model_name] = pickle.load(f)
            
            # 스케일러 로드
            scaler_path = self.model_dir / "scaler.pkl"
            if scaler_path.exists():
                with open(scaler_path, 'rb') as f:
                    self.scaler = pickle.load(f)
            
            # 라벨 인코더 로드
            encoders_path = self.model_dir / "label_encoders.pkl"
            if encoders_path.exists():
                with open(encoders_path, 'rb') as f:
                    self.label_encoders = pickle.load(f)
            
            self.logger.info(f"📂 모델 로드 완료: {len(self.models)}개 모델")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 모델 로드 실패: {e}")
            return False
    
    def enhance_signal(self, stock_code: str, date: str, 
                      original_signal: Dict[str, Any]) -> Dict[str, Any]:
        """신호 강화"""
        try:
            if not self.models:
                self.logger.warning("⚠️ 모델이 로드되지 않았습니다")
                return original_signal
            
            # 분봉 데이터 로드
            minute_data = self.data_collector.load_minute_data(stock_code, date)
            if minute_data is None:
                self.logger.warning(f"⚠️ {stock_code} {date} 분봉 데이터 없음")
                return original_signal
            
            # 일봉 데이터 수집
            daily_data = self.data_collector.collect_daily_data(stock_code, 60)
            if daily_data is None:
                self.logger.warning(f"⚠️ {stock_code} 일봉 데이터 없음")
                return original_signal
            
            # 거래 정보 구성
            trade_info = {
                'stock_code': stock_code,
                'date': date,
                'buy_time': original_signal.get('buy_time', '10:00'),
                'sell_time': original_signal.get('sell_time', '15:00'),
                'profit_pct': 0.0,  # 예측용이므로 0
                'is_win': True,  # 예측용이므로 True
                'signal_type': original_signal.get('signal_type', 'unknown'),
                'sell_reason': 'prediction'
            }
            
            # ML 예측 수행
            ml_predictions = self._predict_with_ml(minute_data, daily_data, trade_info)
            
            if 'error' in ml_predictions:
                self.logger.warning(f"⚠️ ML 예측 실패: {ml_predictions['error']}")
                return original_signal
            
            # 신호 강화 적용
            enhanced_signal = self._apply_enhancement(original_signal, ml_predictions)
            
            return enhanced_signal
            
        except Exception as e:
            self.logger.error(f"❌ 신호 강화 실패 {stock_code}: {e}")
            return original_signal
    
    def _predict_with_ml(self, minute_data: pd.DataFrame, daily_data: pd.DataFrame, 
                        trade_info: Dict) -> Dict[str, Any]:
        """ML 모델로 예측"""
        try:
            # 특성 추출
            features = self.feature_engineer.extract_comprehensive_features(
                minute_data, daily_data, trade_info
            )
            
            if not features:
                return {"error": "특성 추출 실패"}
            
            # DataFrame으로 변환
            feature_df = pd.DataFrame([features])
            
            # 범주형 변수 인코딩
            for col, encoder in self.label_encoders.items():
                if col in feature_df.columns:
                    try:
                        feature_df[f"{col}_encoded"] = encoder.transform(feature_df[col].astype(str))
                    except:
                        feature_df[f"{col}_encoded"] = 0
            
            # 특성 선택 및 전처리
            feature_columns = feature_df.select_dtypes(include=[np.number]).columns.tolist()
            target_columns = ['is_win', 'profit_pct', 'stock_code_encoded']
            feature_columns = [col for col in feature_columns if col not in target_columns]
            
            X = feature_df[feature_columns].fillna(0)
            
            if self.scaler:
                X_scaled = self.scaler.transform(X)
            else:
                X_scaled = X.values
            
            # 예측 수행
            predictions = {}
            
            # 분류 모델 예측 (승률)
            win_probabilities = []
            for name, model in self.models.items():
                if 'classifier' in name:
                    try:
                        prob = model.predict_proba(X_scaled)[0]
                        win_prob = prob[1] if len(prob) > 1 else prob[0]
                        win_probabilities.append(win_prob)
                        predictions[f"{name}_win_probability"] = win_prob
                    except:
                        continue
            
            # 회귀 모델 예측 (수익률)
            profit_predictions = []
            for name, model in self.models.items():
                if 'regressor' in name:
                    try:
                        pred = model.predict(X_scaled)[0]
                        profit_predictions.append(pred)
                        predictions[f"{name}_profit_prediction"] = pred
                    except:
                        continue
            
            # 평균 예측값 계산
            if win_probabilities:
                predictions['avg_win_probability'] = np.mean(win_probabilities)
            else:
                predictions['avg_win_probability'] = 0.5
            
            if profit_predictions:
                predictions['avg_profit_prediction'] = np.mean(profit_predictions)
            else:
                predictions['avg_profit_prediction'] = 0.0
            
            # 리스크 점수 계산
            predictions['risk_score'] = self._calculate_risk_score(predictions)
            
            return predictions
            
        except Exception as e:
            self.logger.error(f"❌ ML 예측 실패: {e}")
            return {"error": str(e)}
    
    def _apply_enhancement(self, original_signal: Dict, ml_predictions: Dict) -> Dict[str, Any]:
        """신호 강화 적용"""
        enhanced_signal = original_signal.copy()
        
        try:
            # ML 예측 결과 추가
            enhanced_signal['ml_predictions'] = ml_predictions
            
            # 신호 강화 로직
            win_prob = ml_predictions.get('avg_win_probability', 0.5)
            profit_pred = ml_predictions.get('avg_profit_prediction', 0.0)
            risk_score = ml_predictions.get('risk_score', 0.5)
            
            # 신호 필터링
            should_enhance = (
                win_prob >= self.enhancement_config['min_win_probability'] and
                profit_pred >= self.enhancement_config['min_profit_prediction'] and
                risk_score <= self.enhancement_config['max_risk_score']
            )
            
            if should_enhance:
                # 신호 강화
                original_confidence = original_signal.get('confidence', 0)
                enhanced_confidence = min(100, original_confidence * self.enhancement_config['confidence_boost_factor'])
                
                enhanced_signal.update({
                    'enhanced': True,
                    'confidence': enhanced_confidence,
                    'ml_win_probability': win_prob,
                    'ml_profit_prediction': profit_pred,
                    'ml_risk_score': risk_score,
                    'enhancement_reason': 'ML 예측 결과 양호'
                })
            else:
                # 신호 약화 또는 제외
                enhanced_signal.update({
                    'enhanced': False,
                    'ml_win_probability': win_prob,
                    'ml_profit_prediction': profit_pred,
                    'ml_risk_score': risk_score,
                    'enhancement_reason': self._get_enhancement_reason(win_prob, profit_pred, risk_score)
                })
            
            return enhanced_signal
            
        except Exception as e:
            self.logger.error(f"❌ 신호 강화 적용 실패: {e}")
            return original_signal
    
    def _calculate_risk_score(self, predictions: Dict) -> float:
        """리스크 점수 계산 (0-1, 낮을수록 안전)"""
        try:
            win_prob = predictions.get('avg_win_probability', 0.5)
            profit_pred = predictions.get('avg_profit_prediction', 0.0)
            
            # 승률이 낮을수록, 수익률 예측이 낮을수록 리스크 높음
            risk_score = (1 - win_prob) * 0.7 + max(0, (2 - profit_pred) / 2) * 0.3
            
            return min(1.0, max(0.0, risk_score))
            
        except:
            return 0.5
    
    def _get_enhancement_reason(self, win_prob: float, profit_pred: float, risk_score: float) -> str:
        """강화 이유 설명"""
        reasons = []
        
        if win_prob < self.enhancement_config['min_win_probability']:
            reasons.append(f"승률 낮음 ({win_prob:.2%})")
        
        if profit_pred < self.enhancement_config['min_profit_prediction']:
            reasons.append(f"예상수익률 낮음 ({profit_pred:.1f}%)")
        
        if risk_score > self.enhancement_config['max_risk_score']:
            reasons.append(f"리스크 높음 ({risk_score:.2f})")
        
        return ", ".join(reasons) if reasons else "기타"
    
    def batch_enhance_signals(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """배치 신호 강화"""
        enhanced_signals = []
        
        for signal in signals:
            try:
                stock_code = signal.get('stock_code')
                date = signal.get('date')
                
                if not stock_code or not date:
                    enhanced_signals.append(signal)
                    continue
                
                enhanced_signal = self.enhance_signal(stock_code, date, signal)
                enhanced_signals.append(enhanced_signal)
                
            except Exception as e:
                self.logger.error(f"❌ 신호 강화 실패: {e}")
                enhanced_signals.append(signal)
        
        return enhanced_signals
    
    def get_enhancement_summary(self, enhanced_signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """강화 결과 요약"""
        total_signals = len(enhanced_signals)
        enhanced_count = sum(1 for s in enhanced_signals if s.get('enhanced', False))
        
        win_probs = [s.get('ml_win_probability', 0.5) for s in enhanced_signals if 'ml_win_probability' in s]
        profit_preds = [s.get('ml_profit_prediction', 0) for s in enhanced_signals if 'ml_profit_prediction' in s]
        risk_scores = [s.get('ml_risk_score', 0.5) for s in enhanced_signals if 'ml_risk_score' in s]
        
        summary = {
            'total_signals': total_signals,
            'enhanced_signals': enhanced_count,
            'enhancement_rate': enhanced_count / total_signals if total_signals > 0 else 0,
            'avg_win_probability': np.mean(win_probs) if win_probs else 0,
            'avg_profit_prediction': np.mean(profit_preds) if profit_preds else 0,
            'avg_risk_score': np.mean(risk_scores) if risk_scores else 0,
        }
        
        return summary

def main():
    """테스트 실행"""
    enhancer = MLSignalEnhancer()
    
    # 테스트 신호
    test_signal = {
        'stock_code': '054540',
        'date': '20250905',
        'buy_time': '10:30',
        'signal_type': 'pullback_pattern',
        'confidence': 75
    }
    
    # 신호 강화
    enhanced = enhancer.enhance_signal('054540', '20250905', test_signal)
    
    print("원본 신호:", test_signal)
    print("강화된 신호:", enhanced)

if __name__ == "__main__":
    main()
