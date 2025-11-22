#!/usr/bin/env python3
"""
ML 기반 승률 예측기

실시간 트레이딩에서 패턴 신호에 대한 ML 승률 예측을 수행합니다.
"""

import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
from utils.logger import setup_logger

logger = setup_logger(__name__)


class MLPredictor:
    """ML 모델 기반 승률 예측기"""

    def __init__(self, model_path: str = "ml_model_stratified.pkl"):
        self.model = None
        self.label_encoder = None
        self.feature_names = None
        self.model_version = None
        self.model_path = model_path
        self.is_loaded = False

    def load_model(self) -> bool:
        """ML 모델 로드"""
        try:
            model_file = Path(self.model_path)
            if not model_file.exists():
                logger.error(f"ML 모델 파일을 찾을 수 없습니다: {self.model_path}")
                return False

            with open(model_file, 'rb') as f:
                model_data = pickle.load(f)

            self.model = model_data.get('model')
            self.label_encoder = model_data.get('label_encoder')
            self.feature_names = model_data.get('feature_names', [])
            self.model_version = model_data.get('version', 'unknown')

            if self.model is None:
                logger.error("ML 모델 로드 실패: 모델 객체가 없습니다")
                return False

            self.is_loaded = True
            logger.info(f"✅ ML 모델 로드 완료: {self.model_version}")
            logger.info(f"   특성 수: {len(self.feature_names)}개")
            return True

        except Exception as e:
            logger.error(f"ML 모델 로드 오류: {e}")
            return False

    def predict_win_probability(
        self,
        pattern_features: Dict,
        stock_code: Optional[str] = None
    ) -> float:
        """
        승률 예측 (0.0 ~ 1.0)

        Args:
            pattern_features: 패턴 특성 딕셔너리
            stock_code: 종목 코드 (로깅용)

        Returns:
            승률 예측값 (0.0 ~ 1.0)
        """
        if not self.is_loaded:
            logger.warning("ML 모델이 로드되지 않았습니다")
            return 0.5  # 중립값 반환

        try:
            # 특성 추출
            features_df = self.extract_features_from_pattern(pattern_features)

            # 예측
            win_prob = self.model.predict(
                features_df,
                num_iteration=self.model.best_iteration
            )[0]

            return float(win_prob)

        except Exception as e:
            logger.error(f"ML 예측 오류 ({stock_code}): {e}")
            return 0.5  # 중립값 반환

    def extract_features_from_pattern(self, pattern: Dict) -> pd.DataFrame:
        """
        패턴 데이터에서 ML 특성 추출

        Args:
            pattern: 패턴 딕셔너리

        Returns:
            특성 DataFrame (1행)
        """
        # 기본 특성 추출
        features = {}

        # 실시간과 시뮬레이션 모두 지원하도록 키 매핑
        # 실시간: 'uptrend', 'decline', 'support', 'breakout'
        # 시뮬레이션: 'uptrend_stats', 'decline_stats', 'support_stats', 'breakout_stats'

        # 1. 하락 구간 특성
        decline_stats = pattern.get('decline_stats', pattern.get('decline', {}))
        # decline_pct는 문자열(시뮬레이션) 또는 숫자(실시간) 가능
        decline_pct_raw = decline_stats.get('decline_pct', 0)
        if isinstance(decline_pct_raw, str):
            features['decline_pct'] = float(decline_pct_raw.replace('%', ''))
        else:
            features['decline_pct'] = abs(float(decline_pct_raw)) if decline_pct_raw else 0

        features['decline_bar_count'] = decline_stats.get('bar_count', 0)
        features['decline_avg_volume'] = decline_stats.get('avg_volume', 0)
        features['decline_max_volume'] = decline_stats.get('max_volume', 0)
        features['decline_total_volume'] = decline_stats.get('total_volume', 0)
        features['decline_avg_body'] = decline_stats.get('avg_body', 0)

        # 2. 지지 구간 특성
        support_stats = pattern.get('support_stats', pattern.get('support', {}))
        features['support_bar_count'] = support_stats.get('bar_count', 0)
        features['support_avg_volume'] = support_stats.get('avg_volume', 0)
        features['support_max_volume'] = support_stats.get('max_volume', 0)
        features['support_total_volume'] = support_stats.get('total_volume', 0)
        features['support_avg_body'] = support_stats.get('avg_body', 0)

        # 3. 돌파 구간 특성
        breakout_stats = pattern.get('breakout_stats', pattern.get('breakout', {}))
        features['breakout_volume'] = breakout_stats.get('volume', 0)
        features['breakout_body'] = breakout_stats.get('body', 0)
        features['breakout_gain_pct'] = breakout_stats.get('gain_pct', 0)

        # 4. 상승 구간 특성
        uptrend_stats = pattern.get('uptrend_stats', pattern.get('uptrend', {}))
        features['uptrend_gain'] = uptrend_stats.get('gain_pct', 0)
        features['uptrend_bar_count'] = uptrend_stats.get('bar_count', 0)
        features['uptrend_avg_volume'] = uptrend_stats.get('avg_volume', 0)
        # max_volume은 문자열(시뮬레이션) 또는 숫자(실시간) 가능
        max_vol_raw = uptrend_stats.get('max_volume', uptrend_stats.get('max_volume_numeric', 0))
        if isinstance(max_vol_raw, str):
            features['uptrend_max_volume'] = float(max_vol_raw.replace(',', ''))
        else:
            features['uptrend_max_volume'] = float(max_vol_raw) if max_vol_raw else 0
        features['uptrend_total_volume'] = uptrend_stats.get('total_volume', 0)
        features['uptrend_avg_body'] = uptrend_stats.get('avg_body', 0)

        # 5. 비율 특성
        ratios = pattern.get('ratios', {})
        features['support_avg_volume_ratio'] = ratios.get('support_avg_volume_ratio', 0)
        features['volume_ratio_breakout_to_uptrend'] = ratios.get('volume_ratio_breakout_to_uptrend', 0)
        features['volume_ratio_decline_to_uptrend'] = ratios.get('volume_ratio_decline_to_uptrend', 0)
        features['volume_ratio_support_to_uptrend'] = ratios.get('volume_ratio_support_to_uptrend', 0)
        features['price_gain_to_decline_ratio'] = ratios.get('price_gain_to_decline_ratio', 0)

        # 6. 시간 특성
        timestamp_str = pattern.get('timestamp', '')
        if timestamp_str:
            try:
                dt = datetime.fromisoformat(timestamp_str)
                features['hour'] = dt.hour
                features['minute'] = dt.minute
            except:
                features['hour'] = 9
                features['minute'] = 0
        else:
            features['hour'] = 9
            features['minute'] = 0

        # 7. 신호 타입 (인코딩)
        signal_type = pattern.get('signal_type', 'pullback_pattern')
        if self.label_encoder and hasattr(self.label_encoder, 'transform'):
            try:
                features['signal_type'] = self.label_encoder.transform([signal_type])[0]
            except:
                features['signal_type'] = 0
        else:
            features['signal_type'] = 0

        # DataFrame 생성 (모델이 기대하는 순서대로)
        df = pd.DataFrame([features])

        # 모델 특성 순서에 맞춰 정렬 (누락된 특성은 0으로 채움)
        for feat in self.feature_names:
            if feat not in df.columns:
                df[feat] = 0

        # 순서 맞추기
        df = df[self.feature_names]

        return df

    def should_trade(
        self,
        pattern_features: Dict,
        threshold: float = 0.5,
        stock_code: Optional[str] = None
    ) -> tuple[bool, float]:
        """
        거래 여부 판단

        Args:
            pattern_features: 패턴 특성 딕셔너리
            threshold: 승률 임계값 (기본 0.5 = 50%)
            stock_code: 종목 코드 (로깅용)

        Returns:
            (거래 허용 여부, 예측 승률)
        """
        if not self.is_loaded:
            logger.warning("ML 모델이 로드되지 않았습니다. 모든 신호 허용.")
            return True, 0.5

        try:
            win_prob = self.predict_win_probability(pattern_features, stock_code)

            should_trade = win_prob >= threshold

            if stock_code:
                status = "✅ 통과" if should_trade else "❌ 차단"
                logger.info(f"[ML 필터] {stock_code}: {win_prob:.1%} {status} (임계값: {threshold:.1%})")

            return should_trade, win_prob

        except Exception as e:
            logger.error(f"ML 필터 판단 오류 ({stock_code}): {e}")
            return True, 0.5  # 오류 시 허용


# 싱글톤 인스턴스
_predictor_instance: Optional[MLPredictor] = None


def get_ml_predictor(model_path: str = "ml_model_stratified.pkl") -> MLPredictor:
    """ML 예측기 싱글톤 인스턴스 반환"""
    global _predictor_instance

    if _predictor_instance is None:
        _predictor_instance = MLPredictor(model_path)
        _predictor_instance.load_model()

    return _predictor_instance
