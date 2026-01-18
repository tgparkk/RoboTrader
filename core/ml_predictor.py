#!/usr/bin/env python3
"""
ML 기반 승률 예측기

실시간 트레이딩에서 패턴 신호에 대한 ML 승률 예측을 수행합니다.
"""

import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime
from utils.logger import setup_logger

logger = setup_logger(__name__)


class MLPredictor:
    """ML 모델 기반 승률 예측기 (12개 특징 최적화)"""

    def __init__(self, model_path: str = "ml_model.pkl"):
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
            logger.info(f"✅ ML 모델 로드 완료 (최적화 버전)")
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

            # 🔍 디버그: 특성 벡터 로깅 (440110 종목만)
            if stock_code == '440110':
                logger.info(f"[실시간ML] {stock_code} 특성 벡터:")
                for col in features_df.columns:
                    logger.info(f"  {col}: {features_df[col].iloc[0]}")

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
        패턴 데이터에서 ML 특성 추출 (12개 특징만 - 최적화)
        
        현재 모델 특징 (12개):
        1. decline_pct
        2. volume_ratio_breakout_to_uptrend
        3. breakout_body_ratio
        4. uptrend_gain
        5. uptrend_max_volume
        6. decline_candles
        7. support_candles
        8. support_volatility
        9. decline_depth
        10. uptrend_gain_per_candle
        11. volume_concentration
        12. uptrend_volume_std

        Args:
            pattern: 패턴 딕셔너리 (debug_info 또는 pattern_stages 구조)

        Returns:
            특성 DataFrame (1행)
        """
        features = {}

        # 패턴 구조 파싱
        pattern_stages = pattern.get('pattern_stages', {})
        debug_info = pattern.get('debug_info', {})

        # ===== 상승 구간 =====
        uptrend = pattern_stages.get('1_uptrend', debug_info.get('uptrend', {}))
        uptrend_candles_list = uptrend.get('candles', [])
        
        uptrend_candles = uptrend.get('bar_count', uptrend.get('candle_count', len(uptrend_candles_list)))
        uptrend_gain = self._safe_float(uptrend.get('gain_pct', uptrend.get('price_gain', 0.0)))
        uptrend_max_volume = self._safe_float(
            uptrend.get('max_volume_numeric', uptrend.get('max_volume', 0))
        )

        # uptrend_volume_std 계산
        uptrend_volume_std = 0
        if uptrend_candles_list and len(uptrend_candles_list) > 1:
            volumes = [c.get('volume', 0) for c in uptrend_candles_list]
            uptrend_volume_std = float(np.std(volumes))

        # volume_concentration 계산
        volume_concentration = 0
        if uptrend_candles_list and uptrend_max_volume > 0:
            uptrend_volume_avg = sum(c.get('volume', 0) for c in uptrend_candles_list) / len(uptrend_candles_list)
            if uptrend_volume_avg > 0:
                volume_concentration = uptrend_max_volume / uptrend_volume_avg

        # uptrend_gain_per_candle 계산
        uptrend_gain_per_candle = uptrend_gain / uptrend_candles if uptrend_candles > 0 else 0

        # ===== 하락 구간 =====
        decline = pattern_stages.get('2_decline', debug_info.get('decline', {}))
        decline_candles_list = decline.get('candles', [])
        
        decline_candles = decline.get('bar_count', decline.get('candle_count', len(decline_candles_list)))
        decline_pct = abs(self._safe_float(decline.get('decline_pct', 0.0)))

        # decline_depth 계산
        decline_depth = 0
        if uptrend_candles_list and decline_candles_list:
            uptrend_max_price = max(c.get('high', 0) for c in uptrend_candles_list)
            decline_min_price = min(c.get('low', float('inf')) for c in decline_candles_list)
            if uptrend_max_price > 0 and decline_min_price < float('inf'):
                decline_depth = (uptrend_max_price - decline_min_price) / uptrend_max_price

        # ===== 지지 구간 =====
        support = pattern_stages.get('3_support', debug_info.get('support', {}))
        support_candles_list = support.get('candles', [])
        
        support_candles = support.get('bar_count', support.get('candle_count', len(support_candles_list)))
        support_volatility = self._safe_float(support.get('price_volatility', 0.0))

        # ===== 돌파 구간 =====
        breakout = pattern_stages.get('4_breakout', debug_info.get('breakout', {}))
        best_breakout = debug_info.get('best_breakout', {})
        
        # 거래량
        breakout_volume = breakout.get('volume')
        if breakout_volume is None:
            breakout_candle = breakout.get('candle', best_breakout)
            breakout_volume = breakout_candle.get('volume', 0)
        else:
            breakout_volume = self._safe_float(breakout_volume)

        # 범위 크기
        breakout_candle = breakout.get('candle', best_breakout)
        if breakout_candle:
            high_p = breakout_candle.get('high', 0)
            low_p = breakout_candle.get('low', 0)
            open_p = breakout_candle.get('open', 0)
            close_p = breakout_candle.get('close', 0)
            
            if low_p > 0:
                breakout_range = (high_p - low_p) / low_p * 100
            else:
                breakout_range = 0.0
                
            # breakout_body (몸통 크기)
            if open_p > 0:
                breakout_body = abs((close_p - open_p) / open_p * 100)
            else:
                breakout_body = 0.0
        else:
            breakout_range = 0.0
            breakout_body = 0.0

        # breakout_body_ratio 계산
        breakout_body_ratio = breakout_body / breakout_range if breakout_range > 0 else 0

        # volume_ratio_breakout_to_uptrend 계산
        volume_ratio_breakout_to_uptrend = (
            breakout_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        )

        # ===== 12개 특징 구성 =====
        features = {
            'decline_pct': decline_pct,
            'volume_ratio_breakout_to_uptrend': volume_ratio_breakout_to_uptrend,
            'breakout_body_ratio': breakout_body_ratio,
            'uptrend_gain': uptrend_gain,
            'uptrend_max_volume': uptrend_max_volume,
            'decline_candles': decline_candles,
            'support_candles': support_candles,
            'support_volatility': support_volatility,
            'decline_depth': decline_depth,
            'uptrend_gain_per_candle': uptrend_gain_per_candle,
            'volume_concentration': volume_concentration,
            'uptrend_volume_std': uptrend_volume_std,
        }

        # DataFrame으로 변환
        try:
            feature_values = [features.get(fname, 0) for fname in self.feature_names]
            df = pd.DataFrame([feature_values], columns=self.feature_names)
            return df

        except Exception as e:
            logger.error(f"특성 추출 오류: {e}")
            # 기본값으로 채워진 DataFrame 반환
            default_features = {fname: 0 for fname in self.feature_names}
            return pd.DataFrame([default_features])

    def _safe_float(self, value, default=0.0):
        """안전하게 float로 변환 (시뮬레이션과 동일)"""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # "3.52%" -> 0.0352, "162,154" -> 162154
            value = value.replace(',', '').replace('%', '').strip()
            try:
                return float(value)
            except:
                return default
        return default


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


# 싱글톤 인스턴스 (프로세스별)
_predictor_instance: Optional[MLPredictor] = None
_predictor_pid: Optional[int] = None


def get_ml_predictor(model_path: str = "ml_model.pkl") -> MLPredictor:
    """
    ML 예측기 싱글톤 인스턴스 반환 (최적화 버전, 프로세스 안전)
    
    멀티프로세싱 환경에서 각 프로세스가 독립적인 인스턴스를 가집니다.
    """
    global _predictor_instance, _predictor_pid

    current_pid = os.getpid()

    # 프로세스가 변경되었거나 인스턴스가 없으면 새로 생성
    if _predictor_instance is None or _predictor_pid != current_pid:
        _predictor_instance = MLPredictor(model_path)
        _predictor_instance.load_model()
        _predictor_pid = current_pid

    return _predictor_instance
