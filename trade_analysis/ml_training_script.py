#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
머신러닝 학습 스크립트
- 승/패 분류 모델 학습
- 수익률 회귀 모델 학습
- 특성 중요도 분석
- 모델 성능 평가
"""

import os
import sys
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import logging
import warnings
from pathlib import Path
warnings.filterwarnings('ignore')

# 머신러닝 라이브러리
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.svm import SVC, SVR
from sklearn.metrics import classification_report, confusion_matrix, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
import xgboost as xgb
import lightgbm as lgb

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ml_data_collector import MLDataCollector
from ml_feature_engineer import MLFeatureEngineer
from utils.logger import setup_logger

logger = setup_logger(__name__)

class MLTrainingPipeline:
    """머신러닝 학습 파이프라인"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_collector = MLDataCollector()
        self.feature_engineer = MLFeatureEngineer()
        
        # 모델 저장 경로
        self.model_dir = Path("trade_analysis/ml_models")
        self.model_dir.mkdir(exist_ok=True)
        
        # 특성 스케일러
        self.scaler = StandardScaler()
        self.label_encoders = {}
        
        # 학습된 모델들
        self.models = {}
        
    def run_full_pipeline(self, start_date: str, end_date: str):
        """전체 학습 파이프라인 실행"""
        self.logger.info(f"ML 학습 파이프라인 시작: {start_date} ~ {end_date}")
        
        try:
            # 1. 데이터 수집
            self.logger.info("1단계: 학습 데이터 수집")
            raw_data = self.data_collector.collect_ml_training_data(start_date, end_date)
            
            if raw_data.empty:
                self.logger.error("수집된 데이터가 없습니다")
                return
            
            # 2. 특성 추출
            self.logger.info("2단계: 고급 특성 추출")
            processed_data = self._process_training_data(raw_data)
            
            if processed_data.empty:
                self.logger.error("특성 추출 실패")
                return
            
            # 3. 데이터 전처리
            self.logger.info("3단계: 데이터 전처리")
            X_train, X_test, y_train, y_test = self._prepare_training_data(processed_data)
            
            # 4. 모델 학습
            self.logger.info("4단계: 모델 학습")
            self._train_models(X_train, X_test, y_train, y_test)
            
            # 5. 모델 평가
            self.logger.info("5단계: 모델 평가")
            self._evaluate_models(X_test, y_test)
            
            # 6. 특성 중요도 분석
            self.logger.info("6단계: 특성 중요도 분석")
            self._analyze_feature_importance()
            
            # 7. 모델 저장
            self.logger.info("7단계: 모델 저장")
            self._save_models()
            
            self.logger.info("ML 학습 파이프라인 완료!")
            
        except Exception as e:
            self.logger.error(f"학습 파이프라인 실패: {e}")
            raise
    
    def _process_training_data(self, raw_data: pd.DataFrame) -> pd.DataFrame:
        """학습 데이터 전처리 및 특성 추출"""
        processed_trades = []
        
        for _, trade in raw_data.iterrows():
            try:
                # 분봉 데이터 로드
                minute_data = self.data_collector.load_minute_data(trade['stock_code'], trade['date'])
                if minute_data is None:
                    continue
                
                # 일봉 데이터 수집
                daily_data = self.data_collector.collect_daily_data(trade['stock_code'], 60)
                if daily_data is None:
                    continue
                
                # 고급 특성 추출
                features = self.feature_engineer.extract_comprehensive_features(
                    minute_data, daily_data, trade.to_dict()
                )
                
                if features:
                    processed_trades.append(features)
                    
            except Exception as e:
                self.logger.error(f"{trade['stock_code']} 특성 추출 실패: {e}")
                continue
        
        if processed_trades:
            df = pd.DataFrame(processed_trades)
            self.logger.info(f"특성 추출 완료: {len(df)}개 샘플")
            return df
        else:
            self.logger.error("처리된 데이터가 없습니다")
            return pd.DataFrame()
    
    def _prepare_training_data(self, data: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """학습 데이터 준비"""
        try:
            # 범주형 변수 인코딩
            categorical_columns = ['signal_type', 'sell_reason', 'stock_code']
            for col in categorical_columns:
                if col in data.columns:
                    le = LabelEncoder()
                    data[f'{col}_encoded'] = le.fit_transform(data[col].astype(str))
                    self.label_encoders[col] = le
            
            # 특성 선택 (숫자형 컬럼만)
            feature_columns = data.select_dtypes(include=[np.number]).columns.tolist()
            
            # 타겟 변수 제외
            target_columns = ['is_win', 'profit_pct', 'stock_code_encoded']
            feature_columns = [col for col in feature_columns if col not in target_columns]
            
            X = data[feature_columns].fillna(0)
            y_classification = data['is_win'].astype(int)
            y_regression = data['profit_pct']
            
            # 데이터 분할
            X_train, X_test, y_train_class, y_test_class = train_test_split(
                X, y_classification, test_size=0.2, random_state=42, stratify=y_classification
            )
            
            _, _, y_train_reg, y_test_reg = train_test_split(
                X, y_regression, test_size=0.2, random_state=42
            )
            
            # 특성 스케일링
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            self.logger.info(f"학습 데이터 준비 완료:")
            self.logger.info(f"   - 특성 수: {len(feature_columns)}")
            self.logger.info(f"   - 학습 샘플: {len(X_train)}")
            self.logger.info(f"   - 테스트 샘플: {len(X_test)}")
            self.logger.info(f"   - 승률: {y_classification.mean():.2%}")
            
            return X_train_scaled, X_test_scaled, (y_train_class, y_train_reg), (y_test_class, y_test_reg)
            
        except Exception as e:
            self.logger.error(f"데이터 준비 실패: {e}")
            raise
    
    def _train_models(self, X_train: np.ndarray, X_test: np.ndarray, 
                     y_train: Tuple[np.ndarray, np.ndarray], 
                     y_test: Tuple[np.ndarray, np.ndarray]):
        """모델 학습"""
        y_train_class, y_train_reg = y_train
        y_test_class, y_test_reg = y_test
        
        # 1. 분류 모델들
        self.logger.info("분류 모델 학습 시작")
        
        # Random Forest 분류기
        rf_classifier = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1
        )
        rf_classifier.fit(X_train, y_train_class)
        self.models['rf_classifier'] = rf_classifier
        
        # XGBoost 분류기
        xgb_classifier = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=42,
            n_jobs=-1
        )
        xgb_classifier.fit(X_train, y_train_class)
        self.models['xgb_classifier'] = xgb_classifier
        
        # LightGBM 분류기
        lgb_classifier = lgb.LGBMClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )
        lgb_classifier.fit(X_train, y_train_class)
        self.models['lgb_classifier'] = lgb_classifier
        
        # 2. 회귀 모델들
        self.logger.info("회귀 모델 학습 시작")
        
        # Random Forest 회귀기
        rf_regressor = RandomForestRegressor(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1
        )
        rf_regressor.fit(X_train, y_train_reg)
        self.models['rf_regressor'] = rf_regressor
        
        # XGBoost 회귀기
        xgb_regressor = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=42,
            n_jobs=-1
        )
        xgb_regressor.fit(X_train, y_train_reg)
        self.models['xgb_regressor'] = xgb_regressor
        
        # LightGBM 회귀기
        lgb_regressor = lgb.LGBMRegressor(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )
        lgb_regressor.fit(X_train, y_train_reg)
        self.models['lgb_regressor'] = lgb_regressor
        
        self.logger.info("모델 학습 완료")
    
    def _evaluate_models(self, X_test: np.ndarray, y_test: Tuple[np.ndarray, np.ndarray]):
        """모델 평가"""
        y_test_class, y_test_reg = y_test
        
        # 분류 모델 평가
        self.logger.info("분류 모델 성능 평가")
        for name, model in self.models.items():
            if 'classifier' in name:
                y_pred = model.predict(X_test)
                accuracy = (y_pred == y_test_class).mean()
                
                self.logger.info(f"   {name}: 정확도 {accuracy:.3f}")
                
                # 상세 성능 리포트
                if name == 'rf_classifier':  # 대표 모델만 상세 출력
                    self.logger.info(f"   분류 리포트:\n{classification_report(y_test_class, y_pred)}")
        
        # 회귀 모델 평가
        self.logger.info("회귀 모델 성능 평가")
        for name, model in self.models.items():
            if 'regressor' in name:
                y_pred = model.predict(X_test)
                mse = mean_squared_error(y_test_reg, y_pred)
                r2 = r2_score(y_test_reg, y_pred)
                
                self.logger.info(f"   {name}: MSE {mse:.4f}, R² {r2:.3f}")
    
    def _analyze_feature_importance(self):
        """특성 중요도 분석"""
        self.logger.info("특성 중요도 분석")
        
        # Random Forest 특성 중요도
        if 'rf_classifier' in self.models:
            importance = self.models['rf_classifier'].feature_importances_
            
            # 특성 이름 가져오기 (스케일링 전 원본 컬럼명)
            feature_names = [f"feature_{i}" for i in range(len(importance))]
            
            # 중요도 순으로 정렬
            importance_df = pd.DataFrame({
                'feature': feature_names,
                'importance': importance
            }).sort_values('importance', ascending=False)
            
            self.logger.info("   상위 10개 중요 특성:")
            for i, row in importance_df.head(10).iterrows():
                self.logger.info(f"   {row['feature']}: {row['importance']:.4f}")
    
    def _save_models(self):
        """모델 저장"""
        try:
            # 모델 저장
            for name, model in self.models.items():
                model_path = self.model_dir / f"{name}.pkl"
                with open(model_path, 'wb') as f:
                    pickle.dump(model, f)
            
            # 스케일러 저장
            scaler_path = self.model_dir / "scaler.pkl"
            with open(scaler_path, 'wb') as f:
                pickle.dump(self.scaler, f)
            
            # 라벨 인코더 저장
            encoders_path = self.model_dir / "label_encoders.pkl"
            with open(encoders_path, 'wb') as f:
                pickle.dump(self.label_encoders, f)
            
            self.logger.info(f"모델 저장 완료: {self.model_dir}")
            
        except Exception as e:
            self.logger.error(f"모델 저장 실패: {e}")
    
    def load_models(self):
        """저장된 모델 로드"""
        try:
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
            
            self.logger.info("모델 로드 완료")
            
        except Exception as e:
            self.logger.error(f"모델 로드 실패: {e}")
    
    def predict_trade_outcome(self, minute_data: pd.DataFrame, daily_data: pd.DataFrame, 
                            trade_info: Dict) -> Dict[str, Any]:
        """거래 결과 예측"""
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
                if f"{col}_encoded" in feature_df.columns:
                    feature_df[f"{col}_encoded"] = encoder.transform(feature_df[col].astype(str))
            
            # 특성 선택 및 전처리
            feature_columns = feature_df.select_dtypes(include=[np.number]).columns.tolist()
            target_columns = ['is_win', 'profit_pct', 'stock_code_encoded']
            feature_columns = [col for col in feature_columns if col not in target_columns]
            
            X = feature_df[feature_columns].fillna(0)
            X_scaled = self.scaler.transform(X)
            
            # 예측
            predictions = {}
            
            # 분류 예측
            for name, model in self.models.items():
                if 'classifier' in name:
                    pred = model.predict(X_scaled)[0]
                    prob = model.predict_proba(X_scaled)[0]
                    predictions[f"{name}_win_probability"] = prob[1] if len(prob) > 1 else prob[0]
                    predictions[f"{name}_prediction"] = pred
            
            # 회귀 예측
            for name, model in self.models.items():
                if 'regressor' in name:
                    pred = model.predict(X_scaled)[0]
                    predictions[f"{name}_profit_prediction"] = pred
            
            return predictions
            
        except Exception as e:
            self.logger.error(f"예측 실패: {e}")
            return {"error": str(e)}

def main():
    """메인 실행 함수"""
    pipeline = MLTrainingPipeline()
    
    # 최근 2주간 데이터로 학습
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
    
    logger.info(f"ML 학습 시작: {start_date} ~ {end_date}")
    
    # 전체 파이프라인 실행
    pipeline.run_full_pipeline(start_date, end_date)
    
    logger.info("ML 학습 완료!")

if __name__ == "__main__":
    main()
