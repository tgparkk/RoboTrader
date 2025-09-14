#!/usr/bin/env python3
"""
학습된 ML 모델의 파라미터를 추출하여 하드코딩 가능한 형태로 변환
- 피클 파일에서 모델 파라미터 추출
- Python 코드로 변환하여 경량화된 예측기 생성
"""

import os
import sys
import pickle
import numpy as np
from pathlib import Path
from typing import Dict, Any, List

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def extract_random_forest_params(model) -> Dict[str, Any]:
    """RandomForest 모델 파라미터 추출"""
    try:
        params = {
            'n_estimators': model.n_estimators,
            'max_depth': model.max_depth,
            'min_samples_split': model.min_samples_split,
            'min_samples_leaf': model.min_samples_leaf,
            'n_features': model.n_features_in_,
            'n_classes': getattr(model, 'n_classes_', None),
            'trees': []
        }
        
        # 각 트리의 정보 추출 (간단한 버전)
        for i, tree in enumerate(model.estimators_[:min(5, len(model.estimators_))]):  # 처음 5개만
            tree_info = {
                'tree_id': i,
                'feature_importances': tree.feature_importances_.tolist(),
                'n_nodes': tree.tree_.node_count,
                'max_depth': tree.tree_.max_depth
            }
            params['trees'].append(tree_info)
        
        return params
    except Exception as e:
        return {'error': str(e)}

def extract_xgboost_params(model) -> Dict[str, Any]:
    """XGBoost 모델 파라미터 추출"""
    try:
        params = {
            'n_estimators': model.n_estimators,
            'max_depth': model.max_depth,
            'learning_rate': model.learning_rate,
            'subsample': model.subsample,
            'colsample_bytree': model.colsample_bytree,
            'feature_importances': model.feature_importances_.tolist() if hasattr(model, 'feature_importances_') else None
        }
        
        # 부스터 정보
        if hasattr(model, 'get_booster'):
            booster = model.get_booster()
            params['booster_dump'] = booster.get_dump()[:5]  # 처음 5개 트리만
        
        return params
    except Exception as e:
        return {'error': str(e)}

def extract_lightgbm_params(model) -> Dict[str, Any]:
    """LightGBM 모델 파라미터 추출"""
    try:
        params = {
            'n_estimators': model.n_estimators,
            'max_depth': model.max_depth,
            'learning_rate': model.learning_rate,
            'subsample': model.subsample,
            'colsample_bytree': model.colsample_bytree,
            'feature_importances': model.feature_importances_.tolist() if hasattr(model, 'feature_importances_') else None
        }
        
        # 부스터 정보
        if hasattr(model, 'booster_'):
            params['model_dump'] = model.booster_.dump_model()
            params['num_trees'] = model.booster_.num_trees()
        
        return params
    except Exception as e:
        return {'error': str(e)}

def extract_all_model_params():
    """모든 모델 파라미터 추출"""
    model_dir = Path("ml_models")
    
    if not model_dir.exists():
        print("❌ ML 모델 디렉토리가 존재하지 않습니다.")
        return
    
    print("학습된 ML 모델 파라미터 추출 시작...")
    print("=" * 60)
    
    extracted_params = {}
    
    # 각 모델 파일 처리
    for model_file in model_dir.glob("*.pkl"):
        if model_file.name in ["scaler.pkl", "label_encoders.pkl"]:
            continue
            
        model_name = model_file.stem
        print(f"\n[모델] {model_name} 분석 중...")
        
        try:
            with open(model_file, 'rb') as f:
                model = pickle.load(f)
            
            # 모델 타입에 따라 파라미터 추출
            if 'random_forest' in model_name or 'rf' in model_name:
                params = extract_random_forest_params(model)
            elif 'xgb' in model_name or 'xgboost' in model_name:
                params = extract_xgboost_params(model)
            elif 'lgb' in model_name or 'lightgbm' in model_name:
                params = extract_lightgbm_params(model)
            else:
                params = {'error': f'지원하지 않는 모델 타입: {type(model)}'}
            
            extracted_params[model_name] = params
            
            if 'error' in params:
                print(f"   [실패] 파라미터 추출 실패: {params['error']}")
            else:
                print(f"   [성공] 파라미터 추출 성공")
                if 'n_estimators' in params:
                    print(f"      트리 개수: {params['n_estimators']}")
                if 'max_depth' in params:
                    print(f"      최대 깊이: {params['max_depth']}")
                if 'feature_importances' in params and params['feature_importances']:
                    top_features = sorted(enumerate(params['feature_importances']), 
                                        key=lambda x: x[1], reverse=True)[:5]
                    print(f"      주요 특성: {[f'F{i}({v:.3f})' for i, v in top_features]}")
        
        except Exception as e:
            print(f"   ❌ 모델 로딩 실패: {e}")
            extracted_params[model_name] = {'error': str(e)}
    
    # 스케일러 정보 추출
    print(f"\n[전처리] 스케일러 분석...")
    scaler_path = model_dir / "scaler.pkl"
    if scaler_path.exists():
        try:
            with open(scaler_path, 'rb') as f:
                scaler = pickle.load(f)
            
            scaler_params = {
                'type': type(scaler).__name__,
                'mean': scaler.mean_.tolist() if hasattr(scaler, 'mean_') else None,
                'scale': scaler.scale_.tolist() if hasattr(scaler, 'scale_') else None,
                'n_features': scaler.n_features_in_ if hasattr(scaler, 'n_features_in_') else None
            }
            extracted_params['scaler'] = scaler_params
            print(f"   [성공] 스케일러 파라미터 추출: {scaler_params['type']}")
            
        except Exception as e:
            print(f"   [실패] 스케일러 분석 실패: {e}")
    
    # 라벨 인코더 정보 추출
    encoders_path = model_dir / "label_encoders.pkl"
    if encoders_path.exists():
        try:
            with open(encoders_path, 'rb') as f:
                encoders = pickle.load(f)
            
            encoder_params = {}
            for name, encoder in encoders.items():
                encoder_params[name] = {
                    'classes': encoder.classes_.tolist() if hasattr(encoder, 'classes_') else None
                }
            
            extracted_params['label_encoders'] = encoder_params
            print(f"   [성공] 라벨 인코더 파라미터 추출: {len(encoder_params)}개")
            
        except Exception as e:
            print(f"   [실패] 라벨 인코더 분석 실패: {e}")
    
    # 결과 저장
    output_path = "extracted_model_params.py"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('#!/usr/bin/env python3\n')
        f.write('"""\n')
        f.write('추출된 ML 모델 파라미터\n')
        f.write('자동 생성됨 - 수동 편집하지 마세요\n')
        f.write('"""\n\n')
        f.write('import numpy as np\n\n')
        f.write('# 추출된 모델 파라미터\n')
        f.write(f'EXTRACTED_PARAMS = {repr(extracted_params)}\n\n')
        
        # 간단한 접근 함수들
        f.write('''
def get_model_params(model_name: str):
    """모델 파라미터 조회"""
    return EXTRACTED_PARAMS.get(model_name, {})

def get_feature_importances(model_name: str):
    """특성 중요도 조회"""
    params = get_model_params(model_name)
    return params.get('feature_importances', [])

def get_scaler_params():
    """스케일러 파라미터 조회"""
    return EXTRACTED_PARAMS.get('scaler', {})

def get_top_features(model_name: str, top_k: int = 10):
    """주요 특성 인덱스 조회"""
    importances = get_feature_importances(model_name)
    if not importances:
        return []
    
    indexed = list(enumerate(importances))
    sorted_features = sorted(indexed, key=lambda x: x[1], reverse=True)
    return [idx for idx, _ in sorted_features[:top_k]]

if __name__ == "__main__":
    print("📊 추출된 ML 모델 정보")
    print("=" * 40)
    
    for model_name, params in EXTRACTED_PARAMS.items():
        if 'error' in params:
            continue
        print(f"\\n🤖 {model_name}")
        
        if model_name == 'scaler':
            print(f"   타입: {params.get('type')}")
            print(f"   특성 수: {params.get('n_features')}")
        elif model_name == 'label_encoders':
            print(f"   인코더 수: {len(params)}")
        else:
            if 'n_estimators' in params:
                print(f"   트리 개수: {params['n_estimators']}")
            if 'max_depth' in params:
                print(f"   최대 깊이: {params['max_depth']}")
            
            top_features = get_top_features(model_name, 5)
            if top_features:
                print(f"   주요 특성: {top_features}")
''')
    
    print(f"\n[저장] 추출된 파라미터 저장: {output_path}")
    print("=" * 60)
    
    # 요약 통계
    total_models = len([k for k in extracted_params.keys() 
                      if k not in ['scaler', 'label_encoders'] and 'error' not in extracted_params[k]])
    print(f"[완료] 추출 완료: {total_models}개 모델")
    
    if total_models > 0:
        print("\n[다음단계]")
        print("1. python trade_analysis/extracted_model_params.py  # 추출 결과 확인")
        print("2. python trade_analysis/create_hardcoded_predictor.py  # 경량화 예측기 생성")

if __name__ == "__main__":
    extract_all_model_params()