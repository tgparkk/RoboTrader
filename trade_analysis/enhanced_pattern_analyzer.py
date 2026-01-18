"""
향상된 패턴 분석기
70개 이상의 특성을 사용하여 더 정확한 패턴 분석 수행
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
import re
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix

from utils.logger import setup_logger
from utils.korean_time import now_kst
from utils.data_cache import DailyDataCache
from enhanced_feature_extractor import EnhancedFeatureExtractor

@dataclass
class EnhancedPatternFeature:
    """향상된 패턴 특성 데이터 클래스"""
    feature_name: str
    value: float
    weight: float = 1.0
    importance: float = 0.0
    p_value: float = 1.0
    description: str = ""

@dataclass
class EnhancedWinLossPattern:
    """향상된 승리/패배 패턴 데이터 클래스"""
    stock_code: str
    signal_date: str
    signal_time: str
    is_win: bool
    return_pct: float
    enhanced_features: Dict[str, float]
    combined_score: float = 0.0
    prediction_confidence: float = 0.0

class EnhancedPatternAnalyzer:
    """향상된 패턴 분석기"""
    
    def __init__(self, logger=None):
        self.logger = logger or setup_logger(__name__)
        self.patterns: List[EnhancedWinLossPattern] = []
        self.feature_extractor = EnhancedFeatureExtractor()
        self.feature_importance: Dict[str, float] = {}
        self.model = None
        self.scaler = StandardScaler()
        self.win_threshold: float = 0.6
        
    def load_trade_logs(self, log_dir: str = "signal_replay_log") -> List[Dict]:
        """거래 로그 로드"""
        try:
            log_path = Path(log_dir)
            if not log_path.exists():
                self.logger.warning(f"로그 디렉토리가 존재하지 않습니다: {log_dir}")
                return []
            
            all_logs = []
            log_files = list(log_path.glob("*.txt"))
            
            self.logger.info(f"📁 {len(log_files)}개 로그 파일 발견")
            
            for log_file in log_files:
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    logs = self._parse_log_content(content, log_file.name)
                    all_logs.extend(logs)
                    
                except Exception as e:
                    self.logger.error(f"로그 파일 읽기 실패 {log_file.name}: {e}")
                    continue
            
            self.logger.info(f"✅ 총 {len(all_logs)}개의 거래 로그 로드 완료")
            return all_logs
            
        except Exception as e:
            self.logger.error(f"거래 로그 로드 실패: {e}")
            return []
    
    def _parse_log_content(self, content: str, filename: str) -> List[Dict]:
        """로그 내용 파싱"""
        logs = []
        lines = content.split('\n')
        
        # 파일명에서 날짜 추출
        date_match = re.search(r'(\d{8})', filename)
        signal_date = date_match.group(1) if date_match else now_kst().strftime("%Y%m%d")
        
        current_stock = None
        
        for line in lines:
            line = line.strip()
            
            # 종목코드 추출
            stock_match = re.search(r'=== (\d{6}) -', line)
            if stock_match:
                current_stock = stock_match.group(1)
                continue
            
            # 매수/매도 정보 추출
            trade_match = re.search(r'(\d{2}:\d{2}) 매수\[.*?\] @([\d,]+) → (\d{2}:\d{2}) 매도\[.*?\] @([\d,]+) \(([+-]?\d+\.\d+)%\)', line)
            if trade_match and current_stock:
                buy_time = trade_match.group(1)
                buy_price = float(trade_match.group(2).replace(',', ''))
                sell_time = trade_match.group(3)
                sell_price = float(trade_match.group(4).replace(',', ''))
                return_pct = float(trade_match.group(5))
                
                is_win = return_pct > 0
                
                log_data = {
                    'stock_code': current_stock,
                    'signal_date': signal_date,
                    'signal_time': buy_time,
                    'is_win': is_win,
                    'return_pct': return_pct,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'raw_line': line
                }
                
                logs.append(log_data)
        
        return logs
    
    def analyze_patterns(self, log_dir: str = "signal_replay_log") -> Dict[str, Any]:
        """향상된 패턴 분석"""
        try:
            self.logger.info("🔍 향상된 승리/패배 패턴 분석 시작...")
            
            # 1. 거래 로그 로드
            trade_logs = self.load_trade_logs(log_dir)
            if not trade_logs:
                self.logger.warning("분석할 거래 로그가 없습니다.")
                return {}
            
            # 2. 향상된 특성 추출
            patterns = []
            for log in trade_logs:
                try:
                    # 일봉 데이터 로드
                    daily_data = self._load_daily_data(log['stock_code'])
                    if daily_data is None or daily_data.empty:
                        continue
                    
                    # 향상된 특성 추출
                    enhanced_features = self.feature_extractor.extract_all_features(
                        daily_data, log['signal_date']
                    )
                    
                    if not enhanced_features:
                        continue
                    
                    # 패턴 생성
                    pattern = EnhancedWinLossPattern(
                        stock_code=log['stock_code'],
                        signal_date=log['signal_date'],
                        signal_time=log['signal_time'],
                        is_win=log['is_win'],
                        return_pct=log['return_pct'],
                        enhanced_features=enhanced_features
                    )
                    
                    patterns.append(pattern)
                    
                except Exception as e:
                    self.logger.debug(f"패턴 생성 실패 {log['stock_code']}: {e}")
                    continue
            
            self.patterns = patterns
            self.logger.info(f"✅ {len(patterns)}개 향상된 패턴 분석 완료")
            
            # 3. 특성별 분석
            analysis_result = self._analyze_enhanced_features(patterns)
            
            # 4. 머신러닝 모델 학습
            ml_result = self._train_ml_model(patterns)
            
            # 5. 결과 통합
            final_result = {
                **analysis_result,
                'ml_model': ml_result,
                'total_patterns': len(patterns),
                'win_patterns': len([p for p in patterns if p.is_win]),
                'loss_patterns': len([p for p in patterns if not p.is_win]),
                'win_rate': len([p for p in patterns if p.is_win]) / len(patterns) if patterns else 0
            }
            
            # 6. 결과 저장
            self._save_analysis_result(final_result)
            
            return final_result
            
        except Exception as e:
            self.logger.error(f"향상된 패턴 분석 실패: {e}")
            return {}
    
    def _load_daily_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드 (DuckDB)"""
        try:
            daily_cache = DailyDataCache()
            data = daily_cache.load_data(stock_code)

            if data is None or data.empty:
                return None
            
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
    
    def _analyze_enhanced_features(self, patterns: List[EnhancedWinLossPattern]) -> Dict[str, Any]:
        """향상된 특성 분석"""
        try:
            if not patterns:
                return {}
            
            # 승리/패배 그룹 분리
            win_patterns = [p for p in patterns if p.is_win]
            loss_patterns = [p for p in patterns if not p.is_win]
            
            self.logger.info(f"승리 패턴: {len(win_patterns)}개, 패배 패턴: {len(loss_patterns)}개")
            
            # 모든 특성 수집
            all_features = set()
            for pattern in patterns:
                all_features.update(pattern.enhanced_features.keys())
            
            # 특성별 분석
            feature_analysis = {}
            for feature in all_features:
                win_values = [p.enhanced_features.get(feature, 0) for p in win_patterns]
                loss_values = [p.enhanced_features.get(feature, 0) for p in loss_patterns]
                
                if not win_values or not loss_values:
                    continue
                
                win_mean = np.mean(win_values)
                loss_mean = np.mean(loss_values)
                win_std = np.std(win_values)
                loss_std = np.std(loss_values)
                
                # 통계적 유의성 검정
                t_stat, p_value = self._enhanced_t_test(win_values, loss_values)
                
                # 특성 가중치 계산
                weight = abs(win_mean - loss_mean) / (win_std + loss_std + 1e-8)
                
                feature_analysis[feature] = {
                    'win_mean': win_mean,
                    'loss_mean': loss_mean,
                    'win_std': win_std,
                    'loss_std': loss_std,
                    'difference': win_mean - loss_mean,
                    'weight': weight,
                    't_stat': t_stat,
                    'p_value': p_value,
                    'significance': p_value < 0.05,
                    'effect_size': abs(win_mean - loss_mean) / np.sqrt((win_std**2 + loss_std**2) / 2)
                }
            
            # 가중치 정규화
            max_weight = max([fa['weight'] for fa in feature_analysis.values()]) if feature_analysis else 1
            for feature in feature_analysis:
                feature_analysis[feature]['normalized_weight'] = feature_analysis[feature]['weight'] / max_weight
            
            # 상위 특성 선택
            top_features = self._get_top_enhanced_features(feature_analysis)
            
            return {
                'feature_analysis': feature_analysis,
                'top_features': top_features,
                'total_features': len(feature_analysis),
                'significant_features': len([f for f in feature_analysis.values() if f['significance']])
            }
            
        except Exception as e:
            self.logger.error(f"향상된 특성 분석 실패: {e}")
            return {}
    
    def _enhanced_t_test(self, group1: List[float], group2: List[float]) -> Tuple[float, float]:
        """향상된 t-test"""
        try:
            n1, n2 = len(group1), len(group2)
            if n1 < 2 or n2 < 2:
                return 0.0, 1.0
            
            mean1, mean2 = np.mean(group1), np.mean(group2)
            var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
            
            # Welch's t-test (이분산 가정)
            se = np.sqrt(var1/n1 + var2/n2)
            t_stat = (mean1 - mean2) / se
            
            # 자유도 계산
            df = (var1/n1 + var2/n2)**2 / ((var1/n1)**2/(n1-1) + (var2/n2)**2/(n2-1))
            
            # p-value 계산 (간단한 근사)
            p_value = 2 * (1 - self._t_cdf(abs(t_stat), df))
            
            return t_stat, p_value
            
        except Exception as e:
            self.logger.debug(f"t-test 계산 실패: {e}")
            return 0.0, 1.0
    
    def _t_cdf(self, t: float, df: float) -> float:
        """t-분포 누적분포함수 근사"""
        # 간단한 근사 (실제로는 더 정확한 구현 필요)
        if df > 30:
            return 0.5 + 0.5 * np.tanh(t / 2)
        else:
            return 0.5 + 0.5 * np.tanh(t / (1 + df/10))
    
    def _get_top_enhanced_features(self, feature_analysis: Dict[str, Dict]) -> List[Dict]:
        """상위 향상된 특성 선택"""
        try:
            # 가중치 기준으로 정렬
            sorted_features = sorted(
                feature_analysis.items(),
                key=lambda x: x[1]['normalized_weight'],
                reverse=True
            )
            
            top_features = []
            for feature, analysis in sorted_features[:20]:  # 상위 20개
                top_features.append({
                    'feature': feature,
                    'analysis': analysis,
                    'rank': len(top_features) + 1
                })
            
            return top_features
            
        except Exception as e:
            self.logger.error(f"상위 특성 선택 실패: {e}")
            return []
    
    def _train_ml_model(self, patterns: List[EnhancedWinLossPattern]) -> Dict[str, Any]:
        """머신러닝 모델 학습"""
        try:
            if len(patterns) < 50:
                self.logger.warning("머신러닝 모델 학습을 위한 데이터가 부족합니다.")
                return {}
            
            # 특성 매트릭스 생성
            feature_matrix = []
            labels = []
            
            for pattern in patterns:
                features = []
                for feature_name in sorted(pattern.enhanced_features.keys()):
                    features.append(pattern.enhanced_features[feature_name])
                feature_matrix.append(features)
                labels.append(1 if pattern.is_win else 0)
            
            X = np.array(feature_matrix)
            y = np.array(labels)
            
            # 특성 정규화
            X_scaled = self.scaler.fit_transform(X)
            
            # 특성 선택
            selector = SelectKBest(f_classif, k=min(20, X.shape[1]))
            X_selected = selector.fit_transform(X_scaled, y)
            
            # 랜덤 포레스트 모델 학습
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42
            )
            
            # 교차 검증
            cv_scores = cross_val_score(self.model, X_selected, y, cv=5)
            
            # 모델 학습
            self.model.fit(X_selected, y)
            
            # 특성 중요도
            feature_names = [name for name in sorted(patterns[0].enhanced_features.keys())]
            selected_features = [feature_names[i] for i in selector.get_support(indices=True)]
            feature_importance = dict(zip(selected_features, self.model.feature_importances_))
            
            # 예측 성능 평가
            y_pred = self.model.predict(X_selected)
            accuracy = np.mean(y_pred == y)
            
            return {
                'model_type': 'RandomForest',
                'cv_scores': cv_scores.tolist(),
                'cv_mean': np.mean(cv_scores),
                'cv_std': np.std(cv_scores),
                'accuracy': accuracy,
                'feature_importance': feature_importance,
                'selected_features': selected_features,
                'n_features': len(selected_features)
            }
            
        except Exception as e:
            self.logger.error(f"머신러닝 모델 학습 실패: {e}")
            return {}
    
    def _save_analysis_result(self, result: Dict[str, Any]):
        """분석 결과 저장"""
        try:
            # JSON 저장
            with open('enhanced_pattern_analysis.json', 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            
            # 모델 저장
            if self.model is not None:
                import joblib
                joblib.dump(self.model, 'enhanced_pattern_model.pkl')
                joblib.dump(self.scaler, 'enhanced_pattern_scaler.pkl')
            
            self.logger.info("✅ 향상된 분석 결과 저장 완료")
            
        except Exception as e:
            self.logger.error(f"분석 결과 저장 실패: {e}")
    
    def generate_enhanced_filter_rules(self, analysis_result: Dict[str, Any]) -> Dict[str, Dict]:
        """향상된 필터 규칙 생성"""
        try:
            if 'feature_analysis' not in analysis_result:
                return {}
            
            feature_analysis = analysis_result['feature_analysis']
            filter_rules = {}
            
            # 상위 특성에 대한 필터 규칙 생성
            for feature, analysis in feature_analysis.items():
                if analysis['significance'] and analysis['normalized_weight'] > 0.3:
                    # 승리 패턴의 특성값 범위 계산
                    win_mean = analysis['win_mean']
                    win_std = analysis['win_std']
                    
                    # 필터 규칙 생성
                    if analysis['difference'] > 0:
                        # 승리가 더 높은 값을 가지는 경우
                        threshold = win_mean - 0.5 * win_std
                        rule = {
                            'condition': f"{feature} >= {threshold:.3f}",
                            'weight': analysis['normalized_weight'],
                            'description': f"{feature}이 {threshold:.3f} 이상이어야 함",
                            'threshold': threshold,
                            'operator': '>='
                        }
                    else:
                        # 승리가 더 낮은 값을 가지는 경우
                        threshold = win_mean + 0.5 * win_std
                        rule = {
                            'condition': f"{feature} <= {threshold:.3f}",
                            'weight': analysis['normalized_weight'],
                            'description': f"{feature}이 {threshold:.3f} 이하여야 함",
                            'threshold': threshold,
                            'operator': '<='
                        }
                    
                    filter_rules[feature] = rule
            
            return filter_rules
            
        except Exception as e:
            self.logger.error(f"향상된 필터 규칙 생성 실패: {e}")
            return {}


def main():
    """메인 실행 함수"""
    logger = setup_logger(__name__)
    
    # 향상된 패턴 분석기 실행
    analyzer = EnhancedPatternAnalyzer(logger)
    
    # 패턴 분석 실행
    results = analyzer.analyze_patterns()
    
    if results:
        print("\n" + "="*80)
        print("📊 향상된 일봉 기반 승리/패배 패턴 분석 결과")
        print("="*80)
        print(f"총 패턴 수: {results['total_patterns']}")
        print(f"승리 패턴: {results['win_patterns']}")
        print(f"패배 패턴: {results['loss_patterns']}")
        print(f"전체 승률: {results['win_rate']:.1%}")
        print(f"총 특성 수: {results['total_features']}")
        print(f"유의한 특성 수: {results['significant_features']}")
        
        print("\n🔝 상위 특성:")
        for i, feature_info in enumerate(results['top_features'][:10], 1):
            feature = feature_info['feature']
            analysis = feature_info['analysis']
            print(f"{i:2d}. {feature}")
            print(f"    승리 평균: {analysis['win_mean']:.3f}")
            print(f"    패배 평균: {analysis['loss_mean']:.3f}")
            print(f"    차이: {analysis['difference']:+.3f}")
            print(f"    가중치: {analysis['normalized_weight']:.3f}")
            print(f"    유의성: {'✅' if analysis['significance'] else '❌'}")
            print(f"    효과크기: {analysis['effect_size']:.3f}")
            print()
        
        # 머신러닝 모델 결과
        if 'ml_model' in results and results['ml_model']:
            ml_result = results['ml_model']
            print("🤖 머신러닝 모델 성능:")
            print(f"  - 교차검증 평균: {ml_result['cv_mean']:.3f} ± {ml_result['cv_std']:.3f}")
            print(f"  - 정확도: {ml_result['accuracy']:.3f}")
            print(f"  - 선택된 특성 수: {ml_result['n_features']}")
            print()
        
        # 필터 규칙 생성
        filter_rules = analyzer.generate_enhanced_filter_rules(results)
        print("🎯 생성된 향상된 필터 규칙:")
        for feature, rule in filter_rules.items():
            print(f"• {rule['description']} (가중치: {rule['weight']:.3f})")
    
    else:
        print("❌ 분석할 데이터가 없습니다.")


if __name__ == "__main__":
    main()
