"""
고급 필터 모듈
데이터 분석 기반 승률 개선 필터

사용법:
    from core.indicators.advanced_filters import AdvancedFilterManager

    # 초기화
    filter_manager = AdvancedFilterManager()

    # 신호 검증
    result = filter_manager.check_signal(
        ohlcv_sequence=lookback_1min,  # 최근 1분봉 시퀀스 (list of dict)
        rsi=65.0,                       # RSI 값 (optional)
        stock_code='005930',            # 종목 코드
        signal_time=datetime.now()      # 신호 시간
    )

    if result['passed']:
        # 신호 통과
        pass
    else:
        # 신호 차단
        print(f"차단 사유: {result['blocked_by']}")
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """필터 결과"""
    passed: bool
    blocked_by: Optional[str] = None
    blocked_reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class AdvancedFilterManager:
    """고급 필터 매니저"""

    def __init__(self, settings=None):
        """
        Args:
            settings: AdvancedFilterSettings 클래스 또는 None (기본 설정 사용)
        """
        if settings is None:
            from config.advanced_filter_settings import AdvancedFilterSettings
            settings = AdvancedFilterSettings

        self.settings = settings
        self._load_preset()

        # 당일 거래 카운터 (첫 거래 필터용)
        self._daily_trade_count: Dict[str, int] = {}
        self._last_reset_date: Optional[str] = None

        # 일봉 데이터 캐시
        self._daily_cache = None
        if self._has_daily_filters_enabled():
            from utils.data_cache import DailyDataCache
            self._daily_cache = DailyDataCache()
            logger.info("일봉 필터 활성화 - DailyDataCache 초기화")

    def _load_preset(self):
        """프리셋 로드 (3분봉 + 일봉)"""
        # 3분봉 프리셋
        preset_name = getattr(self.settings, 'ACTIVE_PRESET', None)
        if preset_name and hasattr(self.settings, 'PRESETS'):
            preset = self.settings.PRESETS.get(preset_name)
            if preset:
                logger.info(f"고급 필터 프리셋 로드: {preset_name}")
                for filter_name, config in preset.items():
                    if hasattr(self.settings, filter_name) and isinstance(config, dict):
                        current = getattr(self.settings, filter_name)
                        current.update(config)

        # 일봉 프리셋
        daily_preset_name = getattr(self.settings, 'ACTIVE_DAILY_PRESET', None)
        if daily_preset_name and hasattr(self.settings, 'DAILY_PRESETS'):
            daily_preset = self.settings.DAILY_PRESETS.get(daily_preset_name)
            if daily_preset:
                logger.info(f"일봉 필터 프리셋 로드: {daily_preset_name}")
                for filter_name, config in daily_preset.items():
                    if hasattr(self.settings, filter_name) and isinstance(config, dict):
                        current = getattr(self.settings, filter_name)
                        current.update(config)

    def _has_daily_filters_enabled(self) -> bool:
        """일봉 필터가 하나라도 활성화되어 있는지 확인"""
        daily_filters = ['DAILY_CONSECUTIVE_UP', 'DAILY_PREV_CHANGE', 'DAILY_VOLUME_RATIO', 'DAILY_PRICE_POSITION']
        for filter_name in daily_filters:
            config = getattr(self.settings, filter_name, {})
            if config.get('enabled', False):
                return True
        return False

    def check_signal(
        self,
        ohlcv_sequence: Optional[List[Dict]] = None,
        rsi: Optional[float] = None,
        stock_code: Optional[str] = None,
        signal_time: Optional[datetime] = None,
        volume_ma_ratio: Optional[float] = None,
        pattern_stages: Optional[Dict] = None,
        trade_date: Optional[str] = None,
    ) -> FilterResult:
        """
        신호에 대해 모든 필터 적용

        Args:
            ohlcv_sequence: 최근 1분봉 시퀀스 (OHLCV dict 리스트, 최소 5개 권장)
            rsi: RSI 값 (3분봉 기준)
            stock_code: 종목 코드
            signal_time: 신호 발생 시간
            volume_ma_ratio: 거래량 MA 비율 (없으면 ohlcv에서 계산)
            pattern_stages: 눌림목 패턴 4단계 데이터 (1_uptrend, 2_decline, 3_support, 4_breakout)
            trade_date: 거래일 (YYYYMMDD 형식, 일봉 필터용)

        Returns:
            FilterResult
        """
        # 마스터 스위치 확인
        if not getattr(self.settings, 'ENABLED', True):
            return FilterResult(passed=True, details={'reason': 'advanced_filters_disabled'})

        details = {}

        # 1. 저승률 종목 필터
        result = self._check_low_winrate_stocks(stock_code)
        if not result.passed:
            return result
        details['low_winrate_stocks'] = 'passed'

        # 2. 화요일 필터
        result = self._check_tuesday(signal_time)
        if not result.passed:
            return result
        details['tuesday'] = 'passed'

        # 3. 시간대-요일 조합 필터
        result = self._check_time_day_combination(signal_time)
        if not result.passed:
            return result
        details['time_day'] = 'passed'

        # OHLCV 기반 필터 (시퀀스 필요)
        if ohlcv_sequence and len(ohlcv_sequence) >= 5:
            features = self._extract_ohlcv_features(ohlcv_sequence)
            details['ohlcv_features'] = features

            # 4. 연속 양봉 필터
            result = self._check_consecutive_bullish(features)
            if not result.passed:
                return result
            details['consecutive_bullish'] = 'passed'

            # 5. 가격 위치 필터
            result = self._check_price_position(features)
            if not result.passed:
                return result
            details['price_position'] = 'passed'

            # 6. 윗꼬리 비율 필터
            result = self._check_upper_wick(features)
            if not result.passed:
                return result
            details['upper_wick'] = 'passed'

            # 7. 거래량 비율 필터
            vol_ratio = volume_ma_ratio or features.get('volume_vs_avg', 1.0)
            result = self._check_volume_ratio(vol_ratio)
            if not result.passed:
                return result
            details['volume_ratio'] = 'passed'

        # 8. RSI 필터
        if rsi is not None:
            result = self._check_rsi(rsi)
            if not result.passed:
                return result
            details['rsi'] = 'passed'

        # pattern_stages 기반 필터 (9~11)
        if pattern_stages:
            # 9. 상승폭 필터
            result = self._check_uptrend_gain(pattern_stages)
            if not result.passed:
                return result
            details['uptrend_gain'] = 'passed'

            # 10. 하락폭 필터
            result = self._check_decline_pct(pattern_stages)
            if not result.passed:
                return result
            details['decline_pct'] = 'passed'

            # 11. 지지구간 캔들 수 필터
            result = self._check_support_candle(pattern_stages)
            if not result.passed:
                return result
            details['support_candle'] = 'passed'

        # 일봉 기반 필터 (12~15)
        if self._daily_cache and stock_code and trade_date:
            daily_features = self._extract_daily_features(stock_code, trade_date)
            if daily_features:
                details['daily_features'] = daily_features

                # 12. 일봉 연속 상승일 필터
                result = self._check_daily_consecutive_up(daily_features)
                if not result.passed:
                    return result
                details['daily_consecutive_up'] = 'passed'

                # 13. 일봉 전일 등락률 필터
                result = self._check_daily_prev_change(daily_features)
                if not result.passed:
                    return result
                details['daily_prev_change'] = 'passed'

                # 14. 일봉 거래량 비율 필터
                result = self._check_daily_volume_ratio(daily_features)
                if not result.passed:
                    return result
                details['daily_volume_ratio'] = 'passed'

                # 15. 일봉 가격 위치 필터
                result = self._check_daily_price_position(daily_features)
                if not result.passed:
                    return result
                details['daily_price_position'] = 'passed'

        return FilterResult(passed=True, details=details)

    def _extract_ohlcv_features(self, sequence: List[Dict]) -> Dict:
        """OHLCV 시퀀스에서 특징 추출"""
        if not sequence or len(sequence) < 5:
            return {}

        recent = sequence[-5:]

        # 캔들 데이터
        candle_bodies = []
        volumes = []
        closes = []

        for candle in recent:
            o = candle.get('open', 0)
            c = candle.get('close', 0)
            candle_bodies.append(c - o)
            volumes.append(candle.get('volume', 0))
            closes.append(c)

        # 연속 양봉 수
        consecutive_bullish = 0
        for body in reversed(candle_bodies):
            if body > 0:
                consecutive_bullish += 1
            else:
                break

        # 거래량 비율
        avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
        volume_vs_avg = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

        # 가격 위치
        high_5 = max(c.get('high', c.get('close', 0)) for c in recent)
        low_5 = min(c.get('low', c.get('close', 0)) for c in recent)
        price_position = (closes[-1] - low_5) / (high_5 - low_5) if high_5 > low_5 else 0.5

        # 윗꼬리 비율
        last = recent[-1]
        last_high = last.get('high', 0)
        last_low = last.get('low', 0)
        last_open = last.get('open', 0)
        last_close = last.get('close', 0)
        last_range = last_high - last_low

        if last_range > 0:
            upper_wick = last_high - max(last_open, last_close)
            upper_wick_ratio = upper_wick / last_range
        else:
            upper_wick_ratio = 0

        return {
            'consecutive_bullish': consecutive_bullish,
            'volume_vs_avg': volume_vs_avg,
            'price_position': price_position,
            'upper_wick_ratio': upper_wick_ratio,
        }

    def _check_consecutive_bullish(self, features: Dict) -> FilterResult:
        """연속 양봉 필터"""
        config = getattr(self.settings, 'CONSECUTIVE_BULLISH', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        min_count = config.get('min_count', 1)
        actual = features.get('consecutive_bullish', 0)

        if actual < min_count:
            return FilterResult(
                passed=False,
                blocked_by='consecutive_bullish',
                blocked_reason=f'연속 양봉 {actual}개 < 최소 {min_count}개',
                details={'actual': actual, 'required': min_count}
            )

        return FilterResult(passed=True)

    def _check_price_position(self, features: Dict) -> FilterResult:
        """가격 위치 필터"""
        config = getattr(self.settings, 'PRICE_POSITION', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        min_position = config.get('min_position', 0.70)
        actual = features.get('price_position', 0)

        if actual < min_position:
            return FilterResult(
                passed=False,
                blocked_by='price_position',
                blocked_reason=f'가격 위치 {actual*100:.1f}% < 최소 {min_position*100:.0f}%',
                details={'actual': actual, 'required': min_position}
            )

        return FilterResult(passed=True)

    def _check_upper_wick(self, features: Dict) -> FilterResult:
        """윗꼬리 비율 필터"""
        config = getattr(self.settings, 'UPPER_WICK', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        max_ratio = config.get('max_ratio', 0.10)
        actual = features.get('upper_wick_ratio', 0)

        if actual > max_ratio:
            return FilterResult(
                passed=False,
                blocked_by='upper_wick',
                blocked_reason=f'윗꼬리 {actual*100:.1f}% > 최대 {max_ratio*100:.0f}%',
                details={'actual': actual, 'max': max_ratio}
            )

        return FilterResult(passed=True)

    def _check_volume_ratio(self, volume_ratio: float) -> FilterResult:
        """거래량 비율 필터"""
        config = getattr(self.settings, 'VOLUME_RATIO', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        avoid_range = config.get('avoid_range', (1.0, 1.5))

        if avoid_range[0] <= volume_ratio <= avoid_range[1]:
            return FilterResult(
                passed=False,
                blocked_by='volume_ratio',
                blocked_reason=f'거래량 {volume_ratio:.2f}x가 회피 구간 {avoid_range[0]}-{avoid_range[1]}x',
                details={'actual': volume_ratio, 'avoid_range': avoid_range}
            )

        return FilterResult(passed=True)

    def _check_rsi(self, rsi: float) -> FilterResult:
        """RSI 필터"""
        config = getattr(self.settings, 'RSI_FILTER', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        avoid_range = config.get('avoid_range', (50, 70))

        if avoid_range[0] <= rsi <= avoid_range[1]:
            return FilterResult(
                passed=False,
                blocked_by='rsi',
                blocked_reason=f'RSI {rsi:.1f}이 회피 구간 {avoid_range[0]}-{avoid_range[1]}',
                details={'actual': rsi, 'avoid_range': avoid_range}
            )

        return FilterResult(passed=True)

    def _check_tuesday(self, signal_time: Optional[datetime]) -> FilterResult:
        """화요일 필터"""
        config = getattr(self.settings, 'TUESDAY_FILTER', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        if signal_time is None:
            return FilterResult(passed=True)

        if signal_time.weekday() == 1:  # 화요일 = 1
            return FilterResult(
                passed=False,
                blocked_by='tuesday',
                blocked_reason='화요일 거래 회피 (승률 36.2%)',
                details={'weekday': 1}
            )

        return FilterResult(passed=True)

    def _check_time_day_combination(self, signal_time: Optional[datetime]) -> FilterResult:
        """시간대-요일 조합 필터"""
        config = getattr(self.settings, 'TIME_DAY_FILTER', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        if signal_time is None:
            return FilterResult(passed=True)

        hour = signal_time.hour
        weekday = signal_time.weekday()

        avoid_combinations = config.get('avoid_combinations', [])

        if (hour, weekday) in avoid_combinations:
            day_names = ['월', '화', '수', '목', '금', '토', '일']
            return FilterResult(
                passed=False,
                blocked_by='time_day_combination',
                blocked_reason=f'{hour}시 {day_names[weekday]}요일 회피 (저승률 조합)',
                details={'hour': hour, 'weekday': weekday}
            )

        return FilterResult(passed=True)

    def _check_low_winrate_stocks(self, stock_code: Optional[str]) -> FilterResult:
        """저승률 종목 필터"""
        config = getattr(self.settings, 'LOW_WINRATE_STOCKS', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        if stock_code is None:
            return FilterResult(passed=True)

        blacklist = config.get('blacklist', [])

        if stock_code in blacklist:
            return FilterResult(
                passed=False,
                blocked_by='low_winrate_stock',
                blocked_reason=f'종목 {stock_code}은 저승률 종목',
                details={'stock_code': stock_code}
            )

        return FilterResult(passed=True)

    def _check_uptrend_gain(self, pattern_stages: Dict) -> FilterResult:
        """상승폭 필터 (pattern_stages 기반)"""
        config = getattr(self.settings, 'UPTREND_GAIN_FILTER', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        uptrend = pattern_stages.get('1_uptrend', {})
        price_gain = uptrend.get('price_gain', 0) * 100  # %로 변환

        max_gain = config.get('max_gain', 15.0)

        if price_gain >= max_gain:
            return FilterResult(
                passed=False,
                blocked_by='uptrend_gain',
                blocked_reason=f'상승폭 {price_gain:.1f}% >= {max_gain}% (과열 진입 회피)',
                details={'actual': price_gain, 'max': max_gain}
            )

        return FilterResult(passed=True)

    def _check_decline_pct(self, pattern_stages: Dict) -> FilterResult:
        """하락폭 필터 (pattern_stages 기반)"""
        config = getattr(self.settings, 'DECLINE_PCT_FILTER', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        decline = pattern_stages.get('2_decline', {})
        decline_pct = decline.get('decline_pct', 0)

        max_decline = config.get('max_decline', 5.0)

        if decline_pct >= max_decline:
            return FilterResult(
                passed=False,
                blocked_by='decline_pct',
                blocked_reason=f'하락폭 {decline_pct:.1f}% >= {max_decline}% (추세 반전 위험)',
                details={'actual': decline_pct, 'max': max_decline}
            )

        return FilterResult(passed=True)

    def _check_support_candle(self, pattern_stages: Dict) -> FilterResult:
        """지지구간 캔들 수 필터 (pattern_stages 기반)"""
        config = getattr(self.settings, 'SUPPORT_CANDLE_FILTER', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        support = pattern_stages.get('3_support', {})
        candle_count = support.get('candle_count', 0)

        avoid_counts = config.get('avoid_counts', [3])

        if candle_count in avoid_counts:
            return FilterResult(
                passed=False,
                blocked_by='support_candle',
                blocked_reason=f'지지구간 캔들 {candle_count}개 (회피 대상)',
                details={'actual': candle_count, 'avoid': avoid_counts}
            )

        return FilterResult(passed=True)

    def _extract_daily_features(self, stock_code: str, trade_date: str) -> Optional[Dict]:
        """일봉 데이터에서 특징 추출 (거래일 기준 과거 20일)"""
        if not self._daily_cache:
            return None

        # 일봉 데이터 로드
        daily_df = self._daily_cache.load_data(stock_code)
        if daily_df is None or daily_df.empty:
            return None

        # 숫자 변환
        daily_df = daily_df.copy()
        for col in ['stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'acml_vol']:
            daily_df[col] = pd.to_numeric(daily_df[col], errors='coerce')

        # 거래일 이전 데이터만 (당일 제외)
        daily_df = daily_df[daily_df['stck_bsop_date'] < trade_date].copy()
        daily_df = daily_df.sort_values('stck_bsop_date').tail(20)

        if len(daily_df) < 5:
            return None

        features = {}

        # 1. 20일 가격 위치
        high_20d = daily_df['stck_hgpr'].max()
        low_20d = daily_df['stck_lwpr'].min()
        last_close = daily_df['stck_clpr'].iloc[-1]

        if high_20d > low_20d:
            features['price_position_20d'] = (last_close - low_20d) / (high_20d - low_20d)
        else:
            features['price_position_20d'] = 0.5

        # 2. 거래량 비율
        if len(daily_df) >= 2:
            vol_ma20 = daily_df['acml_vol'].mean()
            last_vol = daily_df['acml_vol'].iloc[-1]
            if vol_ma20 > 0:
                features['volume_ratio_20d'] = last_vol / vol_ma20
            else:
                features['volume_ratio_20d'] = 1.0

        # 3. 연속 상승일 수
        consecutive_up = 0
        closes = daily_df['stck_clpr'].values
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i - 1]:
                consecutive_up += 1
            else:
                break
        features['consecutive_up_days'] = consecutive_up

        # 4. 전일 대비 등락률
        if len(daily_df) >= 2:
            prev_close = daily_df['stck_clpr'].iloc[-2]
            if prev_close > 0:
                features['prev_day_change'] = (last_close - prev_close) / prev_close * 100
            else:
                features['prev_day_change'] = 0

        return features

    def _check_daily_consecutive_up(self, features: Dict) -> FilterResult:
        """일봉 연속 상승일 필터"""
        config = getattr(self.settings, 'DAILY_CONSECUTIVE_UP', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        min_days = config.get('min_days', 1)
        actual = features.get('consecutive_up_days', 0)

        if actual < min_days:
            return FilterResult(
                passed=False,
                blocked_by='daily_consecutive_up',
                blocked_reason=f'일봉 연속 상승 {actual}일 < 최소 {min_days}일',
                details={'actual': actual, 'required': min_days}
            )

        return FilterResult(passed=True)

    def _check_daily_prev_change(self, features: Dict) -> FilterResult:
        """일봉 전일 등락률 필터"""
        config = getattr(self.settings, 'DAILY_PREV_CHANGE', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        min_change = config.get('min_change', 0.0)
        actual = features.get('prev_day_change', -999)

        if actual < min_change:
            return FilterResult(
                passed=False,
                blocked_by='daily_prev_change',
                blocked_reason=f'전일 등락률 {actual:.2f}% < 최소 {min_change}%',
                details={'actual': actual, 'required': min_change}
            )

        return FilterResult(passed=True)

    def _check_daily_volume_ratio(self, features: Dict) -> FilterResult:
        """일봉 거래량 비율 필터"""
        config = getattr(self.settings, 'DAILY_VOLUME_RATIO', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        min_ratio = config.get('min_ratio', 1.5)
        actual = features.get('volume_ratio_20d', 0)

        if actual < min_ratio:
            return FilterResult(
                passed=False,
                blocked_by='daily_volume_ratio',
                blocked_reason=f'전일 거래량 비율 {actual:.2f}x < 최소 {min_ratio}x',
                details={'actual': actual, 'required': min_ratio}
            )

        return FilterResult(passed=True)

    def _check_daily_price_position(self, features: Dict) -> FilterResult:
        """일봉 가격 위치 필터"""
        config = getattr(self.settings, 'DAILY_PRICE_POSITION', {})
        if not config.get('enabled', False):
            return FilterResult(passed=True)

        min_position = config.get('min_position', 0.5)
        actual = features.get('price_position_20d', 0)

        if actual < min_position:
            return FilterResult(
                passed=False,
                blocked_by='daily_price_position',
                blocked_reason=f'20일 가격 위치 {actual*100:.1f}% < 최소 {min_position*100:.0f}%',
                details={'actual': actual, 'required': min_position}
            )

        return FilterResult(passed=True)

    def get_active_filters(self) -> List[str]:
        """현재 활성화된 필터 목록"""
        active = []

        filters = [
            ('CONSECUTIVE_BULLISH', '연속양봉'),
            ('PRICE_POSITION', '가격위치'),
            ('UPPER_WICK', '윗꼬리'),
            ('VOLUME_RATIO', '거래량'),
            ('RSI_FILTER', 'RSI'),
            ('TUESDAY_FILTER', '화요일'),
            ('TIME_DAY_FILTER', '시간대-요일'),
            ('LOW_WINRATE_STOCKS', '저승률종목'),
            ('UPTREND_GAIN_FILTER', '상승폭제한'),
            ('DECLINE_PCT_FILTER', '하락폭제한'),
            ('SUPPORT_CANDLE_FILTER', '지지캔들'),
            ('DAILY_CONSECUTIVE_UP', '일봉연속상승'),
            ('DAILY_PREV_CHANGE', '일봉전일상승'),
            ('DAILY_VOLUME_RATIO', '일봉거래량'),
            ('DAILY_PRICE_POSITION', '일봉가격위치'),
        ]

        for attr_name, display_name in filters:
            config = getattr(self.settings, attr_name, {})
            if config.get('enabled', False):
                active.append(display_name)

        return active

    def get_summary(self) -> str:
        """필터 설정 요약"""
        if not getattr(self.settings, 'ENABLED', True):
            return "고급 필터: 비활성화"

        active = self.get_active_filters()

        if not active:
            return "고급 필터: 활성화 (개별 필터 없음)"

        preset = getattr(self.settings, 'ACTIVE_PRESET', None)
        daily_preset = getattr(self.settings, 'ACTIVE_DAILY_PRESET', None)

        preset_parts = []
        if preset:
            preset_parts.append(f"3분봉:{preset}")
        if daily_preset:
            preset_parts.append(f"일봉:{daily_preset}")

        preset_str = f" ({', '.join(preset_parts)})" if preset_parts else ""

        return f"고급 필터: {', '.join(active)}{preset_str}"


# 싱글톤 인스턴스 (선택적 사용)
_instance: Optional[AdvancedFilterManager] = None


def get_filter_manager() -> AdvancedFilterManager:
    """싱글톤 필터 매니저 반환"""
    global _instance
    if _instance is None:
        _instance = AdvancedFilterManager()
    return _instance
