"""
향상된 일봉 분석기

기존 분석을 확장하여 더 구체적이고 코드화 가능한 일봉 특성들을 추가:
1. 연속 상승/하락 일수
2. 캔들 패턴 (도지, 해머, 십자별 등)
3. 갭 패턴 (상승갭, 하락갭, 갭메움)
4. 지지/저항 레벨 돌파 패턴
5. 거래량 급증/급감 패턴
6. 일봉 차트에서의 눌림목 패턴
7. 추세선 각도 및 지속성
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import pickle
import re
import matplotlib.pyplot as plt
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

@dataclass
class EnhancedDailyFeatures:
    """향상된 일봉 특성"""
    # 기본 추세 특성
    trend_days: int  # 연속 상승/하락 일수 (양수=상승, 음수=하락)
    trend_strength: float  # 추세 강도 (기울기)
    trend_consistency: float  # 추세 일관성 (0-1)

    # 캔들 패턴
    doji_pattern: bool  # 도지 캔들 여부
    hammer_pattern: bool  # 해머 캔들 여부
    shooting_star_pattern: bool  # 슈팅스타 캔들 여부
    engulfing_pattern: int  # 포용 캔들 (1=상승포용, -1=하락포용, 0=없음)

    # 갭 패턴
    gap_up_ratio: float  # 상승갭 비율
    gap_down_ratio: float  # 하락갭 비율
    gap_fill_tendency: float  # 갭 메움 경향성

    # 지지/저항
    support_level_distance: float  # 지지선까지 거리 (%)
    resistance_level_distance: float  # 저항선까지 거리 (%)
    breakout_strength: float  # 돌파 강도

    # 거래량 패턴
    volume_surge_days: int  # 최근 거래량 급증 일수
    volume_dry_days: int  # 최근 거래량 급감 일수
    avg_volume_ratio: float  # 평균 거래량 대비 비율

    # 눌림목 패턴 (일봉 기준)
    pullback_from_high: float  # 고점 대비 조정 폭 (%)
    pullback_duration: int  # 조정 지속 일수
    volume_during_pullback: float  # 조정 중 평균 거래량 비율

    # 기술적 지표
    rsi_level: float  # RSI 수준
    bollinger_position: float  # 볼린저밴드 내 위치 (0-1)
    macd_signal: int  # MACD 신호 (1=골든크로스, -1=데드크로스, 0=중립)

class EnhancedDailyAnalyzer:
    """향상된 일봉 분석기"""

    def __init__(self):
        self.cache_dir = Path("cache")
        self.daily_data_dir = self.cache_dir / "daily"

    def load_daily_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드"""
        file_path = self.daily_data_dir / f"{stock_code}_{date}_daily.pkl"
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'rb') as f:
                df = pickle.load(f)

            # 데이터 정리 및 정렬
            df = df.sort_values('stck_bsop_date').reset_index(drop=True)

            # 수치형 변환
            price_cols = ['stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr']
            for col in price_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['acml_vol'] = pd.to_numeric(df['acml_vol'], errors='coerce')

            return df
        except Exception as e:
            print(f"Error loading daily data {file_path}: {e}")
            return None

    def calculate_trend_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """추세 관련 특성 계산"""
        if len(df) < 5:
            return {}

        try:
            closes = df['stck_clpr'].values

            # 연속 상승/하락 일수
            trend_days = 0
            current_trend = 0
            for i in range(len(closes)-1, 0, -1):
                if closes[i] > closes[i-1]:
                    if current_trend >= 0:
                        current_trend += 1
                    else:
                        break
                elif closes[i] < closes[i-1]:
                    if current_trend <= 0:
                        current_trend -= 1
                    else:
                        break
                else:
                    break
            trend_days = current_trend

            # 추세 강도 (최근 20일 기울기)
            recent_period = min(20, len(closes))
            recent_closes = closes[-recent_period:]
            if len(recent_closes) > 1:
                trend_strength = np.polyfit(range(len(recent_closes)), recent_closes, 1)[0] / recent_closes[-1]
            else:
                trend_strength = 0

            # 추세 일관성 (방향 일치도)
            if len(closes) >= 10:
                changes = np.diff(closes[-10:])
                if len(changes) > 0:
                    positive_changes = np.sum(changes > 0)
                    trend_consistency = max(positive_changes, len(changes) - positive_changes) / len(changes)
                else:
                    trend_consistency = 0.5
            else:
                trend_consistency = 0.5

            return {
                'trend_days': trend_days,
                'trend_strength': trend_strength,
                'trend_consistency': trend_consistency
            }
        except Exception as e:
            print(f"Error calculating trend features: {e}")
            return {}

    def detect_candle_patterns(self, df: pd.DataFrame) -> Dict[str, any]:
        """캔들 패턴 감지"""
        if len(df) < 2:
            return {}

        try:
            # 최근 캔들
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else latest

            open_price = float(latest['stck_oprc'])
            close_price = float(latest['stck_clpr'])
            high_price = float(latest['stck_hgpr'])
            low_price = float(latest['stck_lwpr'])

            body_size = abs(close_price - open_price)
            total_range = high_price - low_price

            # 도지 패턴 (몸통이 전체 범위의 10% 이하)
            doji_pattern = body_size / total_range < 0.1 if total_range > 0 else False

            # 해머 패턴 (아래 그림자가 몸통의 2배 이상)
            lower_shadow = min(open_price, close_price) - low_price
            hammer_pattern = lower_shadow > body_size * 2 if body_size > 0 else False

            # 슈팅스타 패턴 (위 그림자가 몸통의 2배 이상)
            upper_shadow = high_price - max(open_price, close_price)
            shooting_star_pattern = upper_shadow > body_size * 2 if body_size > 0 else False

            # 포용 캔들 패턴
            engulfing_pattern = 0
            if len(df) >= 2:
                prev_open = float(prev['stck_oprc'])
                prev_close = float(prev['stck_clpr'])

                # 상승 포용
                if (close_price > open_price and prev_close < prev_open and
                    open_price < prev_close and close_price > prev_open):
                    engulfing_pattern = 1
                # 하락 포용
                elif (close_price < open_price and prev_close > prev_open and
                      open_price > prev_close and close_price < prev_open):
                    engulfing_pattern = -1

            return {
                'doji_pattern': doji_pattern,
                'hammer_pattern': hammer_pattern,
                'shooting_star_pattern': shooting_star_pattern,
                'engulfing_pattern': engulfing_pattern
            }
        except Exception as e:
            print(f"Error detecting candle patterns: {e}")
            return {}

    def analyze_gap_patterns(self, df: pd.DataFrame) -> Dict[str, float]:
        """갭 패턴 분석"""
        if len(df) < 10:
            return {}

        try:
            gaps = []
            gap_fills = []

            for i in range(1, len(df)):
                prev_close = float(df.iloc[i-1]['stck_clpr'])
                curr_open = float(df.iloc[i]['stck_oprc'])
                curr_close = float(df.iloc[i]['stck_clpr'])
                curr_high = float(df.iloc[i]['stck_hgpr'])
                curr_low = float(df.iloc[i]['stck_lwpr'])

                # 갭 계산
                gap_ratio = (curr_open - prev_close) / prev_close
                gaps.append(gap_ratio)

                # 갭 메움 확인 (당일 내 갭이 메워졌는지)
                if gap_ratio > 0:  # 상승갭
                    gap_filled = curr_low <= prev_close
                else:  # 하락갭
                    gap_filled = curr_high >= prev_close
                gap_fills.append(gap_filled)

            gaps = np.array(gaps)
            gap_up_ratio = np.mean(gaps[gaps > 0.01]) if np.any(gaps > 0.01) else 0
            gap_down_ratio = np.mean(gaps[gaps < -0.01]) if np.any(gaps < -0.01) else 0
            gap_fill_tendency = np.mean(gap_fills) if gap_fills else 0

            return {
                'gap_up_ratio': gap_up_ratio,
                'gap_down_ratio': gap_down_ratio,
                'gap_fill_tendency': gap_fill_tendency
            }
        except Exception as e:
            print(f"Error analyzing gap patterns: {e}")
            return {}

    def find_support_resistance(self, df: pd.DataFrame) -> Dict[str, float]:
        """지지/저항 레벨 분석"""
        if len(df) < 20:
            return {}

        try:
            closes = df['stck_clpr'].astype(float).values
            highs = df['stck_hgpr'].astype(float).values
            lows = df['stck_lwpr'].astype(float).values

            current_price = closes[-1]

            # 최근 20일 고점/저점 찾기
            recent_highs = highs[-20:]
            recent_lows = lows[-20:]

            # 지지선 (최근 저점들의 평균)
            support_candidates = []
            for i in range(1, len(recent_lows)-1):
                if recent_lows[i] <= recent_lows[i-1] and recent_lows[i] <= recent_lows[i+1]:
                    support_candidates.append(recent_lows[i])

            support_level = np.mean(support_candidates) if support_candidates else np.min(recent_lows)

            # 저항선 (최근 고점들의 평균)
            resistance_candidates = []
            for i in range(1, len(recent_highs)-1):
                if recent_highs[i] >= recent_highs[i-1] and recent_highs[i] >= recent_highs[i+1]:
                    resistance_candidates.append(recent_highs[i])

            resistance_level = np.mean(resistance_candidates) if resistance_candidates else np.max(recent_highs)

            # 거리 계산
            support_distance = (current_price - support_level) / support_level if support_level > 0 else 0
            resistance_distance = (resistance_level - current_price) / current_price if current_price > 0 else 0

            # 돌파 강도 (최근 돌파가 있었다면)
            breakout_strength = 0
            if len(closes) >= 5:
                recent_max = np.max(closes[-5:])
                prev_resistance = np.max(closes[-20:-5]) if len(closes) >= 20 else recent_max
                if recent_max > prev_resistance:
                    breakout_strength = (recent_max - prev_resistance) / prev_resistance

            return {
                'support_level_distance': support_distance,
                'resistance_level_distance': resistance_distance,
                'breakout_strength': breakout_strength
            }
        except Exception as e:
            print(f"Error finding support/resistance: {e}")
            return {}

    def analyze_volume_patterns(self, df: pd.DataFrame) -> Dict[str, any]:
        """거래량 패턴 분석"""
        if len(df) < 10:
            return {}

        try:
            volumes = df['acml_vol'].astype(float).values

            # 평균 거래량 (최근 20일)
            avg_period = min(20, len(volumes))
            avg_volume = np.mean(volumes[-avg_period:])
            current_volume = volumes[-1]
            avg_volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

            # 거래량 급증 일수 (평균의 1.5배 이상)
            volume_surge_days = 0
            for i in range(len(volumes)-1, -1, -1):
                if volumes[i] > avg_volume * 1.5:
                    volume_surge_days += 1
                else:
                    break

            # 거래량 급감 일수 (평균의 0.7배 이하)
            volume_dry_days = 0
            for i in range(len(volumes)-1, -1, -1):
                if volumes[i] < avg_volume * 0.7:
                    volume_dry_days += 1
                else:
                    break

            return {
                'volume_surge_days': volume_surge_days,
                'volume_dry_days': volume_dry_days,
                'avg_volume_ratio': avg_volume_ratio
            }
        except Exception as e:
            print(f"Error analyzing volume patterns: {e}")
            return {}

    def analyze_pullback_pattern(self, df: pd.DataFrame) -> Dict[str, float]:
        """일봉 눌림목 패턴 분석"""
        if len(df) < 10:
            return {}

        try:
            closes = df['stck_clpr'].astype(float).values
            volumes = df['acml_vol'].astype(float).values

            # 최근 고점 찾기
            recent_high = np.max(closes[-20:]) if len(closes) >= 20 else np.max(closes)
            current_price = closes[-1]

            # 고점 대비 조정 폭
            pullback_from_high = (recent_high - current_price) / recent_high if recent_high > 0 else 0

            # 조정 지속 일수 (고점 이후 계속 하락한 일수)
            pullback_duration = 0
            high_idx = -1
            for i in range(len(closes)-1, -1, -1):
                if closes[i] == recent_high:
                    high_idx = i
                    break

            if high_idx != -1:
                for i in range(high_idx + 1, len(closes)):
                    if closes[i] < closes[i-1]:
                        pullback_duration += 1
                    else:
                        break

            # 조정 중 평균 거래량 비율
            if pullback_duration > 0 and high_idx != -1:
                pullback_volumes = volumes[high_idx+1:high_idx+1+pullback_duration]
                total_avg_volume = np.mean(volumes)
                volume_during_pullback = np.mean(pullback_volumes) / total_avg_volume if total_avg_volume > 0 else 1
            else:
                volume_during_pullback = 1

            return {
                'pullback_from_high': pullback_from_high,
                'pullback_duration': pullback_duration,
                'volume_during_pullback': volume_during_pullback
            }
        except Exception as e:
            print(f"Error analyzing pullback pattern: {e}")
            return {}

    def calculate_technical_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """기술적 지표 계산"""
        if len(df) < 14:
            return {}

        try:
            closes = df['stck_clpr'].astype(float).values

            # RSI 계산
            def calculate_rsi(prices, period=14):
                deltas = np.diff(prices)
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)

                avg_gain = np.mean(gains[-period:])
                avg_loss = np.mean(losses[-period:])

                if avg_loss == 0:
                    return 100
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                return rsi

            rsi_level = calculate_rsi(closes) if len(closes) >= 14 else 50

            # 볼린저밴드 위치
            if len(closes) >= 20:
                sma = np.mean(closes[-20:])
                std = np.std(closes[-20:])
                upper_band = sma + (2 * std)
                lower_band = sma - (2 * std)

                current_price = closes[-1]
                if upper_band > lower_band:
                    bollinger_position = (current_price - lower_band) / (upper_band - lower_band)
                else:
                    bollinger_position = 0.5
            else:
                bollinger_position = 0.5

            # MACD 신호
            macd_signal = 0
            if len(closes) >= 26:
                ema12 = closes[-12:].mean()  # 간단한 평균으로 대체
                ema26 = closes[-26:].mean()
                macd_line = ema12 - ema26

                if len(closes) >= 35:
                    prev_ema12 = closes[-21:-9].mean()
                    prev_ema26 = closes[-35:-9].mean()
                    prev_macd = prev_ema12 - prev_ema26

                    if macd_line > 0 and prev_macd <= 0:
                        macd_signal = 1  # 골든크로스
                    elif macd_line < 0 and prev_macd >= 0:
                        macd_signal = -1  # 데드크로스

            return {
                'rsi_level': rsi_level,
                'bollinger_position': bollinger_position,
                'macd_signal': macd_signal
            }
        except Exception as e:
            print(f"Error calculating technical indicators: {e}")
            return {}

    def extract_all_daily_features(self, stock_code: str, date: str) -> Dict[str, any]:
        """모든 일봉 특성 추출"""
        df = self.load_daily_data(stock_code, date)
        if df is None or df.empty:
            return {}

        features = {}

        # 각 분석 결과 통합
        features.update(self.calculate_trend_features(df))
        features.update(self.detect_candle_patterns(df))
        features.update(self.analyze_gap_patterns(df))
        features.update(self.find_support_resistance(df))
        features.update(self.analyze_volume_patterns(df))
        features.update(self.analyze_pullback_pattern(df))
        features.update(self.calculate_technical_indicators(df))

        return features

def test_enhanced_daily_analyzer():
    """테스트 함수"""
    analyzer = EnhancedDailyAnalyzer()

    # 테스트할 종목들
    test_cases = [
        ("000990", "20250918"),
        ("005290", "20250918"),
        ("006910", "20250918")
    ]

    for stock_code, date in test_cases:
        print(f"\n=== {stock_code} - {date} 일봉 분석 ===")
        features = analyzer.extract_all_daily_features(stock_code, date)

        if features:
            for key, value in features.items():
                print(f"{key:25}: {value}")
        else:
            print("데이터 없음")

if __name__ == "__main__":
    test_enhanced_daily_analyzer()