"""
간단한 패턴 필터 - 명백히 약한 패턴만 차단
복잡한 4단계 패턴 분석 대신 신호 강도와 기본 지표만 활용
"""

import pandas as pd
import logging
from typing import Dict, Tuple, Optional

class SimplePatternFilter:
    """간단한 패턴 필터 - 명백히 약한 패턴만 차단"""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    def should_filter_out(self, stock_code: str, signal_strength, data_3min: pd.DataFrame) -> Tuple[bool, str]:
        """
        명백히 약한 패턴인지 판단

        Args:
            stock_code: 종목 코드
            signal_strength: 신호 강도 객체
            data_3min: 3분봉 데이터

        Returns:
            Tuple[차단여부, 차단사유]
        """
        try:
            # 신호 신뢰도만으로는 판단 불가 - 실제 시장 상황 분석 우선

            # 1. 신호 신뢰도가 극도로 낮은 경우 (30% 미만)
            if signal_strength.confidence < 30.0:
                return True, f"신호 신뢰도 극도로 낮음 ({signal_strength.confidence:.1f}% < 30%)"

            # 2. 지지 구간 품질 분석 - 약한 지지는 실패 확률 높음
            if len(data_3min) >= 15:
                # 최근 15봉에서 지지 구간 (돌파봉 제외 직전 10봉) 분석
                support_candles = data_3min.iloc[-11:-1]  # 돌파봉 직전 10봉
                breakout_candle = data_3min.iloc[-1]      # 돌파봉

                if len(support_candles) >= 8:
                    # 지지 구간 강화 조건들

                    # 조건 1: 지지 구간 가격 변동성 (너무 큰 변동은 불안정)
                    support_closes = support_candles['close']
                    support_volatility = (support_closes.std() / support_closes.mean()) * 100
                    high_volatility = support_volatility > 3.0  # 3% 이상 변동성은 불안정

                    # 조건 2: 지지 구간 거래량 추세 (지속적 감소는 관심 부족)
                    first_half_vol = support_candles['volume'].head(5).mean()
                    second_half_vol = support_candles['volume'].tail(5).mean()
                    volume_decline_trend = (second_half_vol - first_half_vol) / first_half_vol * 100 if first_half_vol > 0 else 0
                    severe_volume_decline = volume_decline_trend < -50  # 50% 이상 거래량 감소

                    # 조건 3: 지지선 이탈 (최저가가 계속 갱신되는 경우)
                    support_lows = support_candles['low']
                    recent_low = support_lows.tail(3).min()  # 최근 3봉 최저가
                    earlier_low = support_lows.head(7).min()  # 이전 7봉 최저가
                    support_break = recent_low < earlier_low * 0.98  # 2% 이상 지지선 이탈

                    # 조건 4: 돌파봉 거래량 부족 (돌파에 확신 부족)
                    support_avg_volume = support_candles['volume'].mean()
                    breakout_volume = breakout_candle['volume']
                    weak_breakout_volume = breakout_volume < support_avg_volume * 0.8  # 지지 구간 대비 80% 미만

                    # 약한 지지 조건: 4개 중 2개 이상 해당시 차단
                    weak_support_count = sum([high_volatility, severe_volume_decline, support_break, weak_breakout_volume])

                    if weak_support_count >= 2:
                        conditions = []
                        if high_volatility: conditions.append(f"변동성{support_volatility:.1f}%")
                        if severe_volume_decline: conditions.append(f"거래량감소{volume_decline_trend:.0f}%")
                        if support_break: conditions.append("지지선이탈")
                        if weak_breakout_volume: conditions.append("돌파량부족")

                        return True, f"약한지지구간 ({'/'.join(conditions[:2])})"

            # 3. 최근 가격 변동성이 극도로 높은 경우 (7% 이상)
            if len(data_3min) >= 10:
                recent_closes = data_3min['close'].tail(10)
                price_volatility = (recent_closes.std() / recent_closes.mean()) * 100
                if price_volatility > 7.0:
                    return True, f"최근 가격 변동성 과도 ({price_volatility:.1f}% > 7%)"

            # 4. 약한 패턴 감지: 실패 확률 높은 패턴
            if self._is_weak_pattern(data_3min, signal_strength):
                return True, "실패 위험 높은 약한 패턴"

            return False, "패턴 필터 통과"

        except Exception as e:
            self.logger.error(f"패턴 필터 오류: {e}")
            return False, "필터 오류로 통과 처리"

    def _is_weak_pattern(self, data_3min: pd.DataFrame, signal_strength) -> bool:
        """약한 패턴 감지 - 더 엄격한 조건으로 패배만 차단"""
        try:
            if len(data_3min) < 15:
                return False

            # 최근 15봉 분석
            recent_data = data_3min.tail(15).copy()

            # 가격 변화율 계산
            first_price = recent_data['close'].iloc[0]
            last_price = recent_data['close'].iloc[-1]
            total_gain = (last_price - first_price) / first_price * 100

            # 최고점과 최저점
            max_price = recent_data['high'].max()
            min_price = recent_data['low'].min()
            max_gain = (max_price - first_price) / first_price * 100
            max_decline = (min_price - max_price) / max_price * 100

            # 더 엄격한 약한 패턴 조건 (확실한 패배 패턴만 차단):
            # 1. 전체 상승률이 극도로 낮거나 마이너스 (1% 미만)
            # 2. 최대 상승 후 급속한 하락 (4% 이상 하락)
            # 3. 신고 신뢰도가 낮음 (70% 미만)
            # 4. 현재 가격이 하락 추세 (최근 가격 < 0%)

            very_weak_gain = total_gain < 1.0  # 더 엄격하게
            severe_decline = max_decline < -4.0  # 더 엄격하게
            very_low_confidence = signal_strength.confidence < 70.0  # 더 엄격하게
            current_declining = total_gain < 0  # 현재 하락 중인 경우

            # 4개 조건 중 3개 이상 해당하면 확실한 패배 패턴
            risk_factors = [very_weak_gain, severe_decline, very_low_confidence, current_declining]
            risk_count = sum(risk_factors)

            if risk_count >= 3:  # 더 엄격하게
                self.logger.debug(f"확실한 패배 패턴 감지: 전체상승{total_gain:.1f}%, 최대하락{max_decline:.1f}%, 신뢰도{signal_strength.confidence:.1f}%, 조건{risk_count}/4개")
                return True

            return False

        except Exception as e:
            self.logger.debug(f"약한 패턴 분석 오류: {e}")
            return False

    def get_pattern_summary(self, stock_code: str, signal_strength, data_3min: pd.DataFrame) -> str:
        """패턴 요약 정보 반환"""
        try:
            if len(data_3min) < 5:
                return f"{stock_code}: 데이터 부족"

            recent_data = data_3min.tail(10)

            # 기본 통계
            price_change = (recent_data['close'].iloc[-1] - recent_data['close'].iloc[0]) / recent_data['close'].iloc[0] * 100
            avg_volume = recent_data['volume'].mean()
            volume_trend = "증가" if recent_data['volume'].iloc[-1] > avg_volume else "감소"

            return f"{stock_code}: 가격변화 {price_change:+.1f}%, 거래량 {volume_trend}, 신뢰도 {signal_strength.confidence:.0f}%"

        except Exception as e:
            return f"{stock_code}: 분석 오류 - {e}"