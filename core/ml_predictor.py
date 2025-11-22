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
        (시뮬레이션과 동일한 로직 사용 - apply_ml_filter.py와 일치)

        Args:
            pattern: 패턴 딕셔너리 (debug_info 또는 pattern_stages 구조)

        Returns:
            특성 DataFrame (1행)
        """
        from datetime import datetime

        # 기본 특성 추출
        features = {}

        # 🔄 시뮬레이션 방식 지원 (pattern_stages 구조)
        # pattern_data_logger.py가 저장한 구조: pattern_stages.1_uptrend, 2_decline, 3_support, 4_breakout
        pattern_stages = pattern.get('pattern_stages', {})

        # 🆕 debug_info 구조도 지원 (실시간 호환성)
        debug_info = pattern.get('debug_info', {})

        # 신호 정보 추출
        signal_info = pattern.get('signal_info', {})
        signal_type = signal_info.get('signal_type', '')
        signal_type_encoded = 1 if signal_type == 'STRONG_BUY' else 0
        confidence = self._safe_float(signal_info.get('confidence', 0.0))

        # 시간 정보 (신호 시간 또는 현재 시간)
        signal_time_str = pattern.get('signal_time', '')
        if signal_time_str:
            try:
                signal_time = datetime.strptime(signal_time_str, '%Y-%m-%d %H:%M:%S')
                hour = signal_time.hour
                minute = signal_time.minute
            except:
                hour, minute = datetime.now().hour, datetime.now().minute
        else:
            hour, minute = datetime.now().hour, datetime.now().minute

        features['hour'] = hour
        features['minute'] = minute
        features['time_in_minutes'] = hour * 60 + minute
        features['is_morning'] = 1 if hour < 12 else 0
        features['signal_type'] = signal_type_encoded
        features['confidence'] = confidence

        # ===== 상승 구간 특성 =====
        uptrend = pattern_stages.get('1_uptrend', debug_info.get('uptrend', {}))
        uptrend_candles_list = uptrend.get('candles', [])

        # 캔들 수 (bar_count 또는 candle_count 우선, 없으면 리스트 길이)
        uptrend_candles = uptrend.get('bar_count', uptrend.get('candle_count', len(uptrend_candles_list)))

        # 상승률 (gain_pct 우선, 없으면 price_gain)
        uptrend_gain = self._safe_float(uptrend.get('gain_pct', uptrend.get('price_gain', 0.0)))

        # 최대 거래량 (max_volume_numeric 우선, 없으면 max_volume)
        uptrend_max_volume = self._safe_float(
            uptrend.get('max_volume_numeric', uptrend.get('max_volume', 0))
        )

        # 평균 몸통 크기 퍼센트 (avg_body_pct 우선, 없으면 계산)
        uptrend_avg_body = uptrend.get('avg_body_pct')
        if uptrend_avg_body is None:
            uptrend_avg_body = self._calculate_avg_body_pct(uptrend_candles_list)
        else:
            uptrend_avg_body = self._safe_float(uptrend_avg_body)

        # 총 거래량 (total_volume 우선, 없으면 계산)
        uptrend_total_volume = uptrend.get('total_volume')
        if uptrend_total_volume is None:
            uptrend_total_volume = sum(c.get('volume', 0) for c in uptrend_candles_list)
        else:
            uptrend_total_volume = self._safe_float(uptrend_total_volume)

        features['uptrend_candles'] = uptrend_candles
        features['uptrend_gain'] = uptrend_gain
        features['uptrend_max_volume'] = uptrend_max_volume
        features['uptrend_avg_body'] = uptrend_avg_body
        features['uptrend_total_volume'] = uptrend_total_volume

        # ===== 하락 구간 특성 =====
        decline = pattern_stages.get('2_decline', debug_info.get('decline', {}))
        decline_candles_list = decline.get('candles', [])

        # 캔들 수 (bar_count 또는 candle_count 우선)
        decline_candles = decline.get('bar_count', decline.get('candle_count', len(decline_candles_list)))

        # 하락률
        decline_pct = abs(self._safe_float(decline.get('decline_pct', 0.0)))

        # 평균 거래량 (avg_volume 우선, 없으면 계산)
        decline_avg_volume = decline.get('avg_volume')
        if decline_avg_volume is None:
            decline_avg_volume = self._calculate_avg_volume_from_candles(decline_candles_list)
        else:
            decline_avg_volume = self._safe_float(decline_avg_volume)

        features['decline_candles'] = decline_candles
        features['decline_pct'] = decline_pct
        features['decline_avg_volume'] = decline_avg_volume

        # ===== 지지 구간 특성 =====
        support = pattern_stages.get('3_support', debug_info.get('support', {}))
        support_candles_list = support.get('candles', [])

        # 캔들 수 (bar_count 또는 candle_count 우선)
        support_candles = support.get('bar_count', support.get('candle_count', len(support_candles_list)))

        # 변동성
        support_volatility = self._safe_float(support.get('price_volatility', 0.0))

        # 평균 거래량 비율
        support_avg_volume_ratio = self._safe_float(support.get('avg_volume_ratio', 1.0))

        # 평균 거래량 (avg_volume 우선, 없으면 계산)
        support_avg_volume = support.get('avg_volume')
        if support_avg_volume is None:
            support_avg_volume = self._calculate_avg_volume_from_candles(support_candles_list)
        else:
            support_avg_volume = self._safe_float(support_avg_volume)

        features['support_candles'] = support_candles
        features['support_volatility'] = support_volatility
        features['support_avg_volume_ratio'] = support_avg_volume_ratio
        features['support_avg_volume'] = support_avg_volume

        # ===== 돌파 구간 특성 =====
        breakout = pattern_stages.get('4_breakout', debug_info.get('breakout', {}))

        # best_breakout에 캔들 정보가 있으면 우선 사용 (debug_info 전용)
        best_breakout = debug_info.get('best_breakout', {})

        # 거래량 (volume 우선, 없으면 candle에서 추출)
        breakout_volume = breakout.get('volume')
        if breakout_volume is None:
            breakout_candle = breakout.get('candle', best_breakout)
            breakout_volume = breakout_candle.get('volume', 0)
        else:
            breakout_volume = self._safe_float(breakout_volume)

        # 몸통 크기 퍼센트 (body_pct, body_size 우선, 없으면 계산)
        breakout_body = breakout.get('body_pct', breakout.get('body_size'))
        if breakout_body is None:
            breakout_candle = breakout.get('candle', best_breakout)
            open_p = breakout_candle.get('open', 0)
            close_p = breakout_candle.get('close', 0)
            if open_p > 0:
                breakout_body = abs((close_p - open_p) / open_p * 100)
            else:
                breakout_body = 0.0
        else:
            breakout_body = self._safe_float(breakout_body)

        # 범위 크기 (candle 또는 best_breakout에서 계산)
        breakout_candle = breakout.get('candle', best_breakout)
        if breakout_candle:
            high_p = breakout_candle.get('high', 0)
            low_p = breakout_candle.get('low', 0)
            if low_p > 0:
                breakout_range = (high_p - low_p) / low_p * 100
            else:
                breakout_range = 0.0
        else:
            breakout_range = 0.0

        features['breakout_volume'] = breakout_volume
        features['breakout_body'] = breakout_body
        features['breakout_range'] = breakout_range

        # ===== 비율 특성 계산 =====
        volume_ratio_decline_to_uptrend = (
            decline_avg_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        )
        volume_ratio_support_to_uptrend = (
            support_avg_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        )
        volume_ratio_breakout_to_uptrend = (
            breakout_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        )
        price_gain_to_decline_ratio = (
            uptrend_gain / decline_pct if decline_pct > 0 else 0
        )
        candle_ratio_support_to_decline = (
            support_candles / decline_candles if decline_candles > 0 else 0
        )

        features['volume_ratio_decline_to_uptrend'] = volume_ratio_decline_to_uptrend
        features['volume_ratio_support_to_uptrend'] = volume_ratio_support_to_uptrend
        features['volume_ratio_breakout_to_uptrend'] = volume_ratio_breakout_to_uptrend
        features['price_gain_to_decline_ratio'] = price_gain_to_decline_ratio
        features['candle_ratio_support_to_decline'] = candle_ratio_support_to_decline

        # DataFrame으로 변환 (모델 입력 형식)
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

    def _calculate_avg_volume_from_candles(self, candles: list) -> float:
        """캔들 리스트에서 평균 거래량 계산 (시뮬레이션과 동일)"""
        if not candles:
            return 0.0
        volumes = [c.get('volume', 0) for c in candles]
        return sum(volumes) / len(volumes) if volumes else 0.0

    def _calculate_avg_body_pct(self, candles: list) -> float:
        """캔들 리스트에서 평균 몸통 비율 계산 (시뮬레이션과 동일)"""
        if not candles:
            return 0.0
        body_pcts = []
        for c in candles:
            open_p = c.get('open', 0)
            close_p = c.get('close', 0)
            if open_p > 0:
                body_pct = abs((close_p - open_p) / open_p * 100)
                body_pcts.append(body_pct)
        return sum(body_pcts) / len(body_pcts) if body_pcts else 0.0

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
