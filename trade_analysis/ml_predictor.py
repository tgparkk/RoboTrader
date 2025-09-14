#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실전 트레이딩을 위한 ML 예측 시스템
- 저장된 ML 모델을 로드하여 실시간 예측
- 매수 신호 발생 시 승패 확률과 수익률 예측
- 신뢰도가 높은 거래만 필터링
"""

import os
import sys
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import logging
from datetime import datetime

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from .ml_data_collector import MLDataCollector
from utils.logger import setup_logger

logger = setup_logger(__name__)

class MLPredictor:
    """실전 트레이딩용 ML 예측기"""
    
    def __init__(self):
        self.model_dir = Path("trade_analysis/ml_models")
        self.models = {}
        self.scaler = None
        self.label_encoders = {}
        self.data_collector = MLDataCollector()
        
        # 모델 로드
        self.load_models()
        
    def load_models(self):
        """저장된 모델들을 로드"""
        try:
            if not self.model_dir.exists():
                logger.error("모델 디렉토리가 존재하지 않습니다. 먼저 ML 학습을 실행하세요.")
                return False
            
            # 모델 로드
            for model_file in self.model_dir.glob("*.pkl"):
                if model_file.name not in ["scaler.pkl", "label_encoders.pkl"]:
                    model_name = model_file.stem
                    with open(model_file, 'rb') as f:
                        self.models[model_name] = pickle.load(f)
                    logger.info(f"모델 로드: {model_name}")
            
            # 스케일러 로드
            scaler_path = self.model_dir / "scaler.pkl"
            if scaler_path.exists():
                with open(scaler_path, 'rb') as f:
                    self.scaler = pickle.load(f)
                logger.info("스케일러 로드 완료")
            
            # 라벨 인코더 로드
            encoders_path = self.model_dir / "label_encoders.pkl"
            if encoders_path.exists():
                with open(encoders_path, 'rb') as f:
                    self.label_encoders = pickle.load(f)
                logger.info("라벨 인코더 로드 완료")
            
            logger.info(f"총 {len(self.models)}개 모델 로드 완료!")
            return True
            
        except Exception as e:
            logger.error(f"모델 로드 실패: {e}")
            return False
    
    def predict_trade_outcome(self, stock_code: str, date: str, signal_type: str = "pullback_pattern") -> Dict[str, Any]:
        """
        매수 신호 발생 시 거래 결과 예측
        
        Args:
            stock_code: 종목 코드 (예: "381620")
            date: 날짜 (예: "20250912")
            signal_type: 신호 타입 (예: "pullback_pattern")
        
        Returns:
            예측 결과 딕셔너리
        """
        try:
            logger.info(f"{stock_code} 예측 시작 - {signal_type}")
            
            # 1. 분봉 데이터 로드
            minute_data = self.data_collector.load_minute_data(stock_code, date)
            if minute_data is None or minute_data.empty:
                return {"error": "분봉 데이터가 없습니다"}
            
            # 2. 일봉 데이터 수집
            daily_data = self.data_collector.collect_daily_data(stock_code, 60)
            if daily_data is None or daily_data.empty:
                return {"error": "일봉 데이터 수집 실패"}
            
            # 3. 가상의 거래 정보 생성 (현재 시점 기준)
            current_time = datetime.now().strftime("%H:%M")
            trade_info = {
                'stock_code': stock_code,
                'date': date,
                'buy_time': current_time,
                'sell_time': current_time,  # 임시값
                'signal_type': signal_type,
                'sell_reason': 'prediction',
                'buy_price': float(minute_data['close'].iloc[-1]),
                'sell_price': 0,
                'profit_pct': 0,
                'is_win': False
            }
            
            # 4. 특성 추출
            features = self.data_collector.feature_engineer.extract_comprehensive_features(
                minute_data, daily_data, trade_info
            )
            
            if not features:
                return {"error": "특성 추출 실패"}
            
            # 5. 예측 실행
            predictions = self._make_predictions(features)
            
            # 6. 결과 해석 및 권장사항 생성
            recommendation = self._generate_recommendation(predictions, trade_info)
            
            return {
                'stock_code': stock_code,
                'current_price': trade_info['buy_price'],
                'signal_type': signal_type,
                'predictions': predictions,
                'recommendation': recommendation,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except Exception as e:
            logger.error(f"예측 실패: {e}")
            return {"error": str(e)}
    
    def _make_predictions(self, features: Dict) -> Dict[str, Any]:
        """모든 모델을 사용하여 예측"""
        try:
            # DataFrame으로 변환
            feature_df = pd.DataFrame([features])
            
            # 범주형 변수 인코딩
            for col, encoder in self.label_encoders.items():
                if col in feature_df.columns:
                    try:
                        feature_df[f"{col}_encoded"] = encoder.transform(feature_df[col].astype(str))
                    except:
                        # 학습 시 보지 못한 값이면 기본값으로 처리
                        feature_df[f"{col}_encoded"] = 0
                elif f"{col}_encoded" not in feature_df.columns:
                    # 인코딩된 컬럼이 없으면 기본값 추가
                    feature_df[f"{col}_encoded"] = 0
            
            # 특성 선택
            feature_columns = feature_df.select_dtypes(include=[np.number]).columns.tolist()
            target_columns = ['is_win', 'profit_pct', 'stock_code_encoded']
            feature_columns = [col for col in feature_columns if col not in target_columns]
            
            X = feature_df[feature_columns].fillna(0)
            
            # 스케일링
            if self.scaler:
                X_scaled = self.scaler.transform(X)
            else:
                X_scaled = X.values
            
            predictions = {}
            
            # 1. 승패 예측 (분류)
            classifier_predictions = {}
            for name, model in self.models.items():
                if 'classifier' in name:
                    pred = model.predict(X_scaled)[0]
                    prob = model.predict_proba(X_scaled)[0]
                    
                    classifier_predictions[name] = {
                        'prediction': bool(pred),
                        'win_probability': float(prob[1]) if len(prob) > 1 else float(prob[0])
                    }
            
            predictions['classifiers'] = classifier_predictions
            
            # 2. 수익률 예측 (회귀)
            regressor_predictions = {}
            for name, model in self.models.items():
                if 'regressor' in name:
                    pred = model.predict(X_scaled)[0]
                    regressor_predictions[name] = float(pred)
            
            predictions['regressors'] = regressor_predictions
            
            # 3. 앙상블 예측 (여러 모델의 평균)
            if classifier_predictions:
                avg_win_prob = np.mean([p['win_probability'] for p in classifier_predictions.values()])
                predictions['ensemble_win_probability'] = float(avg_win_prob)
                predictions['ensemble_prediction'] = bool(avg_win_prob > 0.5)
            
            if regressor_predictions:
                avg_profit = np.mean(list(regressor_predictions.values()))
                predictions['ensemble_profit_prediction'] = float(avg_profit)
            
            return predictions
            
        except Exception as e:
            logger.error(f"예측 실행 실패: {e}")
            return {}
    
    def _generate_recommendation(self, predictions: Dict, trade_info: Dict) -> Dict[str, Any]:
        """예측 결과를 바탕으로 거래 권장사항 생성"""
        try:
            if not predictions:
                return {"action": "SKIP", "reason": "예측 데이터 없음"}
            
            # XGBoost 분류기 결과 우선 사용 (정확도 100%)
            xgb_result = predictions.get('classifiers', {}).get('xgb_classifier', {})
            win_prob = xgb_result.get('win_probability', 0.5)
            
            # 앙상블 결과도 참고
            ensemble_win_prob = predictions.get('ensemble_win_probability', 0.5)
            ensemble_profit = predictions.get('ensemble_profit_prediction', 0)
            
            # 거래 권장사항 결정
            if win_prob >= 0.8 and ensemble_win_prob >= 0.7:
                action = "STRONG_BUY"
                confidence = "매우 높음"
                reason = f"승률 예측: {win_prob:.1%}, 앙상블 승률: {ensemble_win_prob:.1%}"
            elif win_prob >= 0.65 and ensemble_win_prob >= 0.6:
                action = "BUY"
                confidence = "높음"
                reason = f"승률 예측: {win_prob:.1%}, 예상 수익률: {ensemble_profit:.2f}%"
            elif win_prob >= 0.5 and ensemble_profit > 1.0:
                action = "WEAK_BUY"
                confidence = "보통"
                reason = f"수익 가능성 있음 (승률: {win_prob:.1%}, 예상 수익: {ensemble_profit:.2f}%)"
            else:
                action = "SKIP"
                confidence = "낮음"
                reason = f"리스크 높음 (승률: {win_prob:.1%}, 예상 수익: {ensemble_profit:.2f}%)"
            
            return {
                "action": action,
                "confidence": confidence,
                "reason": reason,
                "win_probability": win_prob,
                "expected_profit": ensemble_profit,
                "current_price": trade_info['buy_price']
            }
            
        except Exception as e:
            logger.error(f"권장사항 생성 실패: {e}")
            return {"action": "SKIP", "reason": f"분석 오류: {e}"}


def main():
    """사용 예시"""
    predictor = MLPredictor()
    
    # 예측 테스트
    result = predictor.predict_trade_outcome("381620", "20250912", "pullback_pattern")
    
    print("=" * 60)
    print("ML 예측 결과")
    print("=" * 60)
    
    if "error" in result:
        print(f"오류: {result['error']}")
        return
    
    print(f"종목: {result['stock_code']}")
    print(f"현재가: {result['current_price']:,}원")
    print(f"신호: {result['signal_type']}")
    print(f"시간: {result['timestamp']}")
    print()
    
    # 권장사항
    rec = result['recommendation']
    action_emoji = {"STRONG_BUY": "[강매수]", "BUY": "[매수]", "WEAK_BUY": "[약매수]", "SKIP": "[건너뛰기]"}
    
    print(f"{action_emoji.get(rec['action'], '[?]')} 권장사항: {rec['action']}")
    print(f"신뢰도: {rec['confidence']}")
    print(f"근거: {rec['reason']}")
    print(f"승률 예측: {rec['win_probability']:.1%}")
    print(f"예상 수익률: {rec['expected_profit']:.2f}%")
    print()
    
    # 상세 예측 결과
    if 'predictions' in result:
        preds = result['predictions']
        
        print("상세 예측 결과:")
        print("-" * 40)
        
        # 분류 모델 결과
        if 'classifiers' in preds:
            print("승패 예측 모델:")
            for name, pred in preds['classifiers'].items():
                model_name = name.replace('_classifier', '').upper()
                win_prob = pred['win_probability']
                print(f"   {model_name}: {win_prob:.1%} 승률")
        
        # 회귀 모델 결과
        if 'regressors' in preds:
            print("\n수익률 예측 모델:")
            for name, pred in preds['regressors'].items():
                model_name = name.replace('_regressor', '').upper()
                print(f"   {model_name}: {pred:.2f}% 수익률")


    def predict_trade_outcome_realtime(self, stock_code: str, minute_data: pd.DataFrame, daily_data: pd.DataFrame, signal_type: str = "pullback_pattern") -> Dict[str, Any]:
        """
        실시간 매수 신호 발생 시 거래 결과 예측 (메모리 데이터 사용)
        
        Args:
            stock_code: 종목 코드 (예: "381620")
            minute_data: 실시간 분봉 데이터 (IntradayStockManager에서 제공)
            daily_data: 일봉 데이터 (IntradayStockManager에서 제공)
            signal_type: 신호 타입 (예: "pullback_pattern")
        
        Returns:
            예측 결과 딕셔너리
        """
        try:
            logger.info(f"{stock_code} 실시간 예측 시작 - {signal_type}")
            
            # 1. 데이터 검증
            if minute_data is None or minute_data.empty:
                return {"error": "분봉 데이터가 없습니다"}
            
            if daily_data is None or daily_data.empty:
                return {"error": "일봉 데이터가 없습니다"}
            
            # 2. 가상의 거래 정보 생성 (현재 시점 기준)
            current_time = datetime.now().strftime("%H:%M")
            current_date = datetime.now().strftime("%Y%m%d")
            
            trade_info = {
                'stock_code': stock_code,
                'date': current_date,
                'buy_time': current_time,
                'sell_time': current_time,  # 임시값
                'signal_type': signal_type,
                'sell_reason': 'prediction',
                'buy_price': float(minute_data['close'].iloc[-1]),
                'sell_price': 0,
                'profit_pct': 0,
                'is_win': False
            }
            
            # 3. 특성 추출
            features = self.data_collector.feature_engineer.extract_comprehensive_features(
                minute_data, daily_data, trade_info
            )
            
            if not features:
                return {"error": "특성 추출 실패"}
            
            # 4. 예측 실행
            predictions = self._make_predictions(features)
            
            if not predictions:
                return {"error": "ML 예측 실패"}
            
            # 5. 결과 생성
            result = self._generate_recommendation(predictions, trade_info)
            
            logger.info(f"{stock_code} 실시간 예측 완료 - 액션: {result['recommendation']['action']}")
            
            return result
            
        except Exception as e:
            logger.error(f"실시간 예측 실행 오류: {e}")
            return {"error": f"실시간 예측 오류: {str(e)}"}


if __name__ == "__main__":
    main()