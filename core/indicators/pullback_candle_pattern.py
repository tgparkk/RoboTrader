"""
눌림목 캔들패턴 지표 (3분봉 권장) - 리팩토링된 버전
주가 상승 후 저거래 조정(기준 거래량의 1/4) → 회복 양봉에서 거래량 회복 → 이등분선 지지/회복 확인
손절: 진입 양봉 저가 0.2% 이탈, 또는 이등분선 기준 아래로 0.2% 이탈, 또는 지지 저점 이탈
익절: 매수가 대비 +3%
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, List, Union
import logging
from utils.logger import setup_logger
from datetime import datetime

from core.indicators.bisector_line import BisectorLine
from core.indicators.pullback_utils import (
    SignalType, BisectorStatus, RiskSignal, SignalStrength, 
    VolumeAnalysis, CandleAnalysis, PullbackUtils
)
from typing import List, Tuple
from core.indicators.pullback.volume_analyzer import VolumeAnalyzer
from core.indicators.pullback.support_pattern_analyzer import SupportPatternAnalyzer
from core.indicators.pullback.technical_filter import TechnicalFilter

def analyze_daily_pattern_strength(stock_code, current_date, daily_data=None):
    """일봉 패턴 강도 분석 (전역 함수) - 임시로 디폴트 값 반환"""
    # 임시로 디폴트 값 반환 (승률 개선을 위해)
    return {'strength': 50, 'ideal_pattern': False}

    # try:
    #     import pandas as pd
    #     import numpy as np
    #     from pathlib import Path
    #     import pickle

    #     # 먼저 전달받은 daily_data 사용 시도
    #     daily_df = None
    #     if daily_data is not None and not daily_data.empty:
    #         daily_df = daily_data.copy()
    #         print(f"[DEBUG] 전달받은 일봉 데이터 사용: {len(daily_df)}행")
    #     else:
    #         # 기존 파일 방식으로 폴백
    #         daily_dir = Path("cache/daily")
    #         date_str = current_date.strftime('%Y%m%d') if hasattr(current_date, 'strftime') else str(current_date)

    #         # 가능한 파일명들 시도
    #         possible_files = [
    #             f"{stock_code}_{date_str}_daily.pkl",
    #             f"{stock_code}_{current_date}_daily.pkl"
    #         ]

    #         for filename in possible_files:
    #             file_path = daily_dir / filename
    #             if file_path.exists():
    #                 try:
    #                     with open(file_path, 'rb') as f:
    #                         daily_df = pickle.load(f)
    #                     print(f"[DEBUG] 파일에서 일봉 데이터 로드 성공: {filename}, 행수: {len(daily_df)}")
    #                     break
    #                 except:
    #                     continue

    #     if daily_df is None or len(daily_df) < 10:
    #         # 디버그: 일봉 데이터 로드 실패 시 로그 출력
    #         date_str = current_date.strftime('%Y%m%d') if hasattr(current_date, 'strftime') else str(current_date)
    #         print(f"[DEBUG] 일봉 데이터 없음: {stock_code}, {date_str}")
    #         return {'strength': 50, 'ideal_pattern': False}  # 중간값 반환

    #     # 컬럼명 정규화
    #     if 'stck_clpr' in daily_df.columns:
    #         daily_df = daily_df.rename(columns={
    #             'stck_clpr': 'close',
    #             'stck_oprc': 'open',
    #             'acml_vol': 'volume'
    #         })

    #     # 최근 5일 데이터
    #     recent_5days = daily_df.tail(5).copy()

    #     # 숫자형 변환
    #     for col in ['close', 'volume']:
    #         if col in recent_5days.columns:
    #             recent_5days[col] = pd.to_numeric(recent_5days[col], errors='coerce')

    #     # 가격 변화율 (5일간)
    #     prices = recent_5days['close'].values
    #     price_change_pct = (prices[-1] - prices[0]) / prices[0] * 100 if len(prices) >= 2 else 0

    #     # 거래량 변화율 (5일간)
    #     volumes = recent_5days['volume'].values
    #     volume_change_pct = (volumes[-1] - volumes[0]) / volumes[0] * 100 if len(volumes) >= 2 else 0

    #     # 이동평균 위치
    #     ma3 = recent_5days['close'].rolling(3).mean().iloc[-1]  # 3일 이평 사용
    #     current_price = recent_5days['close'].iloc[-1]
    #     ma_position = (current_price - ma3) / ma3 * 100 if ma3 > 0 else 0

    #     # 패턴 강도 계산 (0-100)
    #     strength = 50  # 기본값

    #     # 가격 상승 점수 (0-30)
    #     if price_change_pct > 5:
    #         strength += 30
    #     elif price_change_pct > 3:
    #         strength += 20
    #     elif price_change_pct > 1:
    #         strength += 10
    #     elif price_change_pct < -3:
    #         strength -= 20

    #     # 거래량 감소 점수 (0-25)
    #     if volume_change_pct < -20:
    #         strength += 25
    #     elif volume_change_pct < -10:
    #         strength += 15
    #     elif volume_change_pct < 0:
    #         strength += 5
    #     elif volume_change_pct > 20:
    #         strength -= 15

    #     # 이동평균 위치 점수 (0-15)
    #     if ma_position > 3:
    #         strength += 15
    #     elif ma_position > 1:
    #         strength += 10
    #     elif ma_position > 0:
    #         strength += 5
    #     elif ma_position < -3:
    #         strength -= 15

    #     # 이상적 패턴 (주가상승 + 거래량감소)
    #     ideal_pattern = (price_change_pct > 2 and volume_change_pct < -10 and ma_position > 0)
    #     if ideal_pattern:
    #         strength += 10

    #     return {
    #         'strength': max(0, min(100, strength)),
    #         'ideal_pattern': ideal_pattern,
    #         'price_change_pct': price_change_pct,
    #         'volume_change_pct': volume_change_pct,
    #         'ma_position': ma_position
    #     }

    # except Exception as e:
    #     return {'strength': 50, 'ideal_pattern': False}  # 오류시 중간값

class PullbackCandlePattern:
    """눌림목 캔들패턴 분석기 (리팩토링된 버전)"""
    
    # 기본 유틸리티 메서드들 - PullbackUtils로 위임
    @staticmethod
    def calculate_daily_baseline_volume(data: pd.DataFrame) -> pd.Series:
        """당일 기준거래량 계산"""
        return PullbackUtils.calculate_daily_baseline_volume(data)
    
    @staticmethod
    def analyze_volume(data: pd.DataFrame, period: int = 10) -> VolumeAnalysis:
        """거래량 분석"""
        return PullbackUtils.analyze_volume(data, period)
    
    @staticmethod
    def analyze_candle(data: pd.DataFrame, period: int = 10, prev_close: Optional[float] = None) -> CandleAnalysis:
        """캔들 분석"""
        return PullbackUtils.analyze_candle(data, period, prev_close)
    
    @staticmethod
    def get_bisector_status(current_price: float, bisector_line: float) -> BisectorStatus:
        """이등분선 상태 판단"""
        return PullbackUtils.get_bisector_status(current_price, bisector_line)
    
    @staticmethod
    def check_price_above_bisector(data: pd.DataFrame) -> bool:
        """이등분선 위 위치 확인"""
        return PullbackUtils.check_price_above_bisector(data)
    
    @staticmethod
    def check_price_trend(data: pd.DataFrame, period: int = 10) -> str:
        """주가 추세 확인"""
        return PullbackUtils.check_price_trend(data, period)
    
    @staticmethod
    def find_recent_low(data: pd.DataFrame, period: int = 5) -> Optional[float]:
        """최근 저점 찾기"""
        return PullbackUtils.find_recent_low(data, period)
    
    @staticmethod
    def check_prior_uptrend(data: pd.DataFrame, min_gain: float = 0.05) -> bool:
        """선행 상승 확인"""
        return PullbackUtils.check_prior_uptrend(data, min_gain)
    
    # 핵심 비즈니스 로직 메서드들
    @staticmethod
    def _analyze_volume_pattern(data: pd.DataFrame, baseline_volumes: pd.Series, period: int = 3) -> dict:
        """거래량 패턴 분석 (PullbackCandlePattern 전용)"""
        return VolumeAnalyzer._analyze_volume_pattern_internal(data, baseline_volumes, period)
    
    @staticmethod
    def analyze_support_pattern(data: pd.DataFrame, debug: bool = False) -> dict:
        """새로운 지지 패턴 분석 (상승 기준거래량 → 저거래량 하락 → 지지 → 돌파양봉)

        Args:
            data: 분석할 데이터
            debug: 디버그 정보 포함 여부
        """
        # 유연한 파라미터로 분석기 생성 (사용자 패턴에 맞게 조정)
        analyzer = SupportPatternAnalyzer(
            uptrend_min_gain=0.03,  # 3% 상승률 (기본 5% → 3%)
            decline_min_pct=0.005,  # 1.5% 하락률 (기본 1% → 1.5%)
            support_volume_threshold=0.25,  # 25% 거래량
            support_volatility_threshold=0.015,  # 2.5% 가격변동성 (기본 0.5% → 2.5%)
            breakout_body_increase=0.1,  # 1% 몸통 증가율 (기본 50% → 1%)
            lookback_period=200
        )
        result = analyzer.analyze(data)

        pattern_info = {
            'has_support_pattern': result.has_pattern,
            'confidence': result.confidence,
            'entry_price': result.entry_price,
            'reasons': result.reasons
        }

        if debug:
            pattern_info.update(analyzer.get_debug_info(data))

        # 중복 신호 방지를 위해 항상 디버그 정보 포함 (동일한 분석기 사용)
        pattern_info['debug_info'] = analyzer.get_debug_info(data)
        
        
        # 🚫 마이너스 수익 조합 필터링
        if result.has_pattern and pattern_info['debug_info']:
            from core.indicators.pattern_combination_filter import PatternCombinationFilter
            from core.indicators.filter_stats import filter_stats
            import logging
            logger = logging.getLogger(__name__)

            filter_stats.increment_total()  # 전체 체크 횟수

            filter = PatternCombinationFilter(logger=logger)
            should_exclude, exclude_reason = filter.should_exclude(pattern_info['debug_info'])

            if should_exclude:
                logger.info(f"🚫 {exclude_reason}")
                filter_stats.increment('pattern_combination_filter', exclude_reason)  # 통계 기록
                # 패턴을 무효화
                pattern_info['has_support_pattern'] = False
                pattern_info['reasons'].append(exclude_reason)
        

        '''
        # 🆕 시간대별 가중치 필터링 (승률 50.9% → 60-65% 예상)
        # 고위험 시간대(10시, 14시) 강화 필터 적용
        if result.has_pattern and pattern_info['debug_info']:
            from core.indicators.time_weighted_filter import TimeWeightedFilter
            from core.indicators.filter_stats import filter_stats
            from utils.korean_time import now_kst
            import logging
            logger = logging.getLogger(__name__)

            time_filter = TimeWeightedFilter(logger=logger)
            should_exclude, exclude_reason = time_filter.should_exclude(
                pattern_info['debug_info'],
                now_kst()
            )

            if should_exclude:
                filter_stats.increment('time_weighted_filter', exclude_reason)  # 통계 기록
                # 패턴을 무효화
                pattern_info['has_support_pattern'] = False
                pattern_info['reasons'].append(exclude_reason)
        '''
        return pattern_info
    
    @staticmethod
    def is_valid_turning_candle(current_candle: pd.Series, volume_analysis: VolumeAnalysis, 
                              candle_analysis: CandleAnalysis, bisector_line: float = None, 
                              min_body_pct: float = 0.5, debug: bool = False, logger = None) -> bool:
        """변곡캔들 유효성 검증 (제시된 로직에 따른 강화)"""
        
        # 1. 양봉 조건
        if not candle_analysis.is_bullish:
            return False
        
        # 2. 의미있는 실체 크기 (0.5% 이상)
        if not candle_analysis.is_meaningful_body:
            return False
        
        # 3. 이등분선 근접/상승 돌파 (선택사항)
        if bisector_line is not None:
            bisector_status = PullbackUtils.get_bisector_status(current_candle['close'], bisector_line)
            if bisector_status == BisectorStatus.BROKEN:
                return False
        
        return True
    
    @staticmethod
    def _analyze_volume_pattern(data: pd.DataFrame, baseline_volumes: pd.Series, period: int = 3) -> dict:
        """거래량 패턴 분석 (공통 함수)"""
        
        if len(data) < period + 1 or len(baseline_volumes) < len(data):
            return {
                'consecutive_low_count': 0,
                'current_vs_threshold': 0,
                'avg_low_volume_ratio': 0,
                'volume_trend': 'stable'
            }
        
        try:
            # 현재 캔들 정보
            current_volume = float(data['volume'].iloc[-1])
            current_baseline = float(baseline_volumes.iloc[-1])
            
            # 직전 period개 캔들 분석 (현재 제외)
            recent_data = data.iloc[-period-1:-1]  # 현재 캔들 제외
            recent_baselines = baseline_volumes.iloc[-period-1:-1]
            
            # 연속 저거래량 개수 계산
            volume_ratios = recent_data['volume'].astype(float) / recent_baselines.astype(float)
            low_volume_threshold = 0.30  # 30% (하락/지지 구간 최적 기준)
            
            consecutive_low_count = 0
            for ratio in volume_ratios.iloc[::-1]:  # 최근부터 거슬러 올라감
                if ratio <= low_volume_threshold:
                    consecutive_low_count += 1
                else:
                    break
            
            # 현재 캔듡의 거래량 비율
            current_vs_threshold = float(current_volume) / float(current_baseline) if float(current_baseline) > 0 else 0
            
            # 저거래량 구간 평균 비율
            avg_low_volume_ratio = volume_ratios.mean() if len(volume_ratios) > 0 else 0
            
            # 거래량 추세
            if len(volume_ratios) >= 2:
                recent_trend = volume_ratios.iloc[-2:].values
                if recent_trend[-1] > recent_trend[-2]:
                    volume_trend = 'increasing'
                elif recent_trend[-1] < recent_trend[-2]:
                    volume_trend = 'decreasing'
                else:
                    volume_trend = 'stable'
            else:
                volume_trend = 'stable'
            
            return {
                'consecutive_low_count': consecutive_low_count,
                'current_vs_threshold': current_vs_threshold,
                'avg_low_volume_ratio': avg_low_volume_ratio,
                'volume_trend': volume_trend
            }
            
        except Exception:
            return {
                'consecutive_low_count': 0,
                'current_vs_threshold': 0,
                'avg_low_volume_ratio': 0,
                'volume_trend': 'stable'
            }
    
    @staticmethod
    def analyze_pullback_quality(data: pd.DataFrame, baseline_volumes: pd.Series,
                               min_pullback_candles: int = 2,
                               low_volume_threshold: float = 0.30) -> dict:
        """눌림목 품질 분석"""
        
        if len(data) < min_pullback_candles + 1:
            return {'quality_score': 0, 'has_quality_pullback': False}
        
        # 공통 거래량 패턴 분석 활용
        volume_info = PullbackCandlePattern._analyze_volume_pattern(data, baseline_volumes, min_pullback_candles)
        
        quality_score = 0
        
        # 1. 연속 저거래량 개수 (가중치 40%)
        consecutive_score = min(volume_info['consecutive_low_count'] / min_pullback_candles, 1.0) * 40
        quality_score += consecutive_score
        
        # 2. 저거래량 수준 (가중치 30%)
        avg_ratio = volume_info['avg_low_volume_ratio']
        volume_score = max(0, (low_volume_threshold - avg_ratio) / low_volume_threshold) * 30
        quality_score += volume_score
        
        # 3. 가격 안정성 (가중치 30%)
        try:
            recent_closes = data['close'].iloc[-min_pullback_candles-1:-1]
            price_volatility = recent_closes.std() / recent_closes.mean() if recent_closes.mean() > 0 else 1
            stability_score = max(0, (0.05 - price_volatility) / 0.05) * 30  # 5% 기준
            quality_score += stability_score
        except:
            stability_score = 0
        
        has_quality_pullback = (
            volume_info['consecutive_low_count'] >= min_pullback_candles and 
            quality_score >= 60
        )
        
        return {
            'quality_score': quality_score,
            'has_quality_pullback': has_quality_pullback,
            'consecutive_low_count': volume_info['consecutive_low_count'],
            'avg_volume_ratio': avg_ratio
        }
    '''
    @staticmethod  
    def generate_improved_signals_v2(
        data: pd.DataFrame,
        entry_price: Optional[float] = None,
        entry_low: Optional[float] = None,
        debug: bool = False,
        logger: Optional[logging.Logger] = None
    ) -> Tuple[SignalStrength, List[RiskSignal]]:
        """개선된 눌림목 패턴 신호 생성 v2 (SHA-1: 4d2836c2 복원) - 통합된 함수로 위임
        
        Returns:
            Tuple[SignalStrength, List[RiskSignal]]: (신호 강도, 위험 신호 목록)
        """
        # 통합된 generate_improved_signals 함수로 위임 (v2 호환 모드)
        stock_code = getattr(logger, '_stock_code', 'UNKNOWN') if logger else 'UNKNOWN'
        
        return PullbackCandlePattern.generate_improved_signals(
            data=data,
            stock_code=stock_code,
            debug=debug,
            entry_price=entry_price,
            entry_low=entry_low,
            logger=logger,
            return_risk_signals=True  # v2는 항상 위험 신호도 함께 반환
        )
    '''        

    @staticmethod
    def generate_improved_signals(
        data: pd.DataFrame,
        stock_code: str = "UNKNOWN",
        debug: bool = False,
        entry_price: Optional[float] = None,
        entry_low: Optional[float] = None,
        logger: Optional[logging.Logger] = None,
        return_risk_signals: bool = False,
        prev_close: Optional[float] = None,
        daily_data: Optional[pd.DataFrame] = None
    ) -> Union[Optional[SignalStrength], Tuple[SignalStrength, List[RiskSignal]]]:
        """핵심 눌림목 신호 생성 - 4단계 패턴만 허용"""

        # 데이터 전처리
        data = data.copy()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in data.columns:
                if pd.api.types.is_numeric_dtype(data[col]):
                    data[col] = data[col].astype(float)
                else:
                    data[col] = pd.to_numeric(data[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0.0)

        if len(data) < 5:
            result = SignalStrength(SignalType.AVOID, 0, 0, ['데이터 부족'], 0, BisectorStatus.BROKEN) if return_risk_signals else None
            return (result, []) if return_risk_signals else result

        if logger is None:
            logger = setup_logger(f"pullback_pattern_{stock_code}")
            logger._stock_code = stock_code

        try:
            current = data.iloc[-1]

            # 이등분선 계산
            try:
                from core.indicators.bisector_line import BisectorLine
                bisector_line_series = BisectorLine.calculate_bisector_line(data['high'], data['low'])
                bisector_line = bisector_line_series.iloc[-1] if bisector_line_series is not None and not bisector_line_series.empty else None
            except:
                bisector_line = None

            # 위험 신호 체크
            baseline_volumes = PullbackUtils.calculate_daily_baseline_volume(data)
            period = min(10, len(data) - 1)
            volume_analysis = PullbackUtils.analyze_volume(data, period, baseline_volumes)
            candle_analysis = PullbackUtils.analyze_candle(data, period, prev_close)
            recent_low = PullbackUtils.find_recent_low(data) or 0

            risk_signals = PullbackUtils.check_risk_signals(
                current, bisector_line, entry_low, recent_low, entry_price,
                volume_analysis, candle_analysis
            )

            if risk_signals:
                signal_strength = SignalStrength(
                    SignalType.SELL if return_risk_signals else SignalType.AVOID,
                    100 if return_risk_signals else 0,
                    0,
                    [f'위험신호: {r.value}' for r in risk_signals],
                    volume_analysis.volume_ratio,
                    PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN
                )
                return (signal_strength, risk_signals) if return_risk_signals else signal_strength

            # 핵심 매수 조건들만 체크
            # 1. 당일 시가 이상 (시장 시작 3분봉의 시가 = 1분봉 시작시간의 시가) - 동적 시간 적용
            # data는 3분봉이지만, 시작~시작+3분 3분봉의 open은 1분봉 시작시간의 open과 동일
            from config.market_hours import MarketHours

            day_open_price = None
            if len(data) > 0:
                # 첫 번째 3분봉의 datetime 확인
                first_candle_time = pd.to_datetime(data['datetime'].iloc[0]) if 'datetime' in data.columns else None

                if first_candle_time:
                    # 동적 시장 시작 시간 가져오기
                    market_hours = MarketHours.get_market_hours('KRX', first_candle_time)
                    market_open = market_hours['market_open']

                    # 시장 시작 3분봉인 경우만 시가로 인정
                    if first_candle_time.hour == market_open.hour and first_candle_time.minute == market_open.minute:
                        day_open_price = float(data['open'].iloc[0])
                    else:
                        # 시장 시작 3분봉이 아니면 데이터 부족으로 판단
                        result = SignalStrength(SignalType.AVOID, 0, 0, [f"{market_open.strftime('%H:%M')}시가없음"], volume_analysis.volume_ratio, BisectorStatus.BROKEN)
                        return (result, []) if return_risk_signals else result

            if day_open_price and float(current['close']) <= day_open_price:
                result = SignalStrength(SignalType.AVOID, 0, 0, [f"당일시가이하(시가:{day_open_price:.0f})"], volume_analysis.volume_ratio, BisectorStatus.BROKEN)
                return (result, []) if return_risk_signals else result

            # 2. 이등분선 위
            if bisector_line and float(current['close']) < float(bisector_line):
                result = SignalStrength(SignalType.AVOID, 0, 0, ["이등분선아래"], volume_analysis.volume_ratio, BisectorStatus.BROKEN)
                return (result, []) if return_risk_signals else result

            # 3. 시가 대비 2% 이상 상승 체크 (매수 필수 조건)
            if day_open_price:
                current_price = float(current['close'])
                price_increase_pct = (current_price - day_open_price) / day_open_price * 100
                
                if price_increase_pct < 2.0:
                    result = SignalStrength(
                        SignalType.AVOID, 0, 0,
                        [f"시가대비{price_increase_pct:.1f}%상승(2%미만차단)"],
                        volume_analysis.volume_ratio,
                        BisectorStatus.BROKEN
                    )
                    return (result, []) if return_risk_signals else result

            # 4. 시가 대비 22% 상승 체크 (매수 차단)
            if day_open_price:
                current_price = float(current['close'])
                price_increase_pct = (current_price - day_open_price) / day_open_price * 100

                if price_increase_pct >= 22.0:
                    result = SignalStrength(
                        SignalType.AVOID, 0, 0,
                        [f"시가대비{price_increase_pct:.1f}%상승(22%이상차단)"],
                        volume_analysis.volume_ratio,
                        BisectorStatus.BROKEN
                    )
                    return (result, []) if return_risk_signals else result

            # 5. 4단계 지지 패턴 분석 (핵심)
            # 통합된 로직 사용 (현재 시간 기준 분석 + 전체 데이터 분석)
            support_pattern_info = PullbackCandlePattern.analyze_support_pattern(data, debug)

            from datetime import datetime

            # 시간대별 + 일봉 결합 조건
            # 시뮬레이션 테스트에서는 봉의 실제 시간 사용 (datetime 컬럼 우선)
            current_time = None

            # 1순위: datetime 컬럼
            if 'datetime' in data.columns and not pd.isna(data['datetime'].iloc[-1]):
                current_time = pd.to_datetime(data['datetime'].iloc[-1])
            # 2순위: index가 datetime이면 사용
            elif hasattr(data.index, 'to_pydatetime') and len(data.index) > 0:
                try:
                    current_time = data.index[-1].to_pydatetime()
                except:
                    pass
            # 3순위: 현재 시간 (실시간 거래용)
            if current_time is None:
                current_time = datetime.now()

            # 일봉 패턴 분석 (전달받은 daily_data 사용)
            daily_pattern = analyze_daily_pattern_strength(stock_code, current_time.strftime('%Y%m%d'), daily_data)
            daily_strength = daily_pattern['strength']
            is_ideal_daily = daily_pattern['ideal_pattern']

            # 개선사항: 신뢰도 상한선 94% (95% 이상 차단)
            # 시간대 필터는 사용자가 직접 적용

            # 기본 시간대별 조건
            if 12 <= current_time.hour < 14:  # 오후시간 (승률 29.6%)
                min_confidence = 85
                # 오후시간 일봉 강화 조건
                if daily_strength < 60:  # 약한 일봉 패턴
                    min_confidence = 95  # 거의 불가능한 조건
                elif is_ideal_daily:  # 이상적 일봉 패턴
                    min_confidence = 80  # 약간 완화
            elif 9 <= current_time.hour < 10:  # 개장시간 (승률 55.4%)
                min_confidence = 70
                # 개장시간 일봉 조건 (관대하게)
                if daily_strength >= 70:  # 강한 일봉 패턴
                    min_confidence = 65  # 더욱 완화
                elif daily_strength < 40:  # 매우 약한 일봉
                    min_confidence = 80  # 조건 강화
            else:  # 오전/늦은시간
                min_confidence = 75
                # 일반 시간대 일봉 조건
                if is_ideal_daily and daily_strength >= 70:  # 이상적이고 강한 패턴
                    min_confidence = 70  # 완화
                elif daily_strength < 50:  # 약한 일봉 패턴
                    min_confidence = 85  # 강화

            # 디버그 로그 (logger가 없어도 print로 출력)
            if debug:
                if logger:
                    logger.info(f"[{stock_code}] 일봉분석: 강도{daily_strength:.0f}, 이상적패턴{is_ideal_daily}, 요구신뢰도{min_confidence}")
                    logger.info(f"[{stock_code}] 일봉상세: 가격변화{daily_pattern.get('price_change_pct', 0):.1f}%, 거래량변화{daily_pattern.get('volume_change_pct', 0):.1f}%")
                else:
                    print(f"[{stock_code}] 일봉분석: 강도{daily_strength:.0f}, 이상적패턴{is_ideal_daily}, 요구신뢰도{min_confidence}")
                    print(f"[{stock_code}] 일봉상세: 가격변화{daily_pattern.get('price_change_pct', 0):.1f}%, 거래량변화{daily_pattern.get('volume_change_pct', 0):.1f}%")

            # 신뢰도 상한선 94% 체크 (개선사항 1)
            if support_pattern_info['confidence'] >= 95:
                result = SignalStrength(SignalType.AVOID, 0, 0, ["신뢰도95%이상차단"], volume_analysis.volume_ratio, BisectorStatus.BROKEN)
                return (result, []) if return_risk_signals else result

            if support_pattern_info['has_support_pattern'] and support_pattern_info['confidence'] >= min_confidence:
                # ================================
                # 기술 지표 필터 (현재 비활성화 - 성능 저하로 주석 처리)
                # 총 거래 325개 → 110개 감소
                # 승률 52% → 57.3%로 향상했으나
                # 총 수익 2,015,000원 → 1,030,000원으로 감소
                # ================================
                # tech_filter = TechnicalFilter.create_balanced_filter()
                # filter_result = tech_filter.check_filter(
                #     data=data,
                #     current_idx=len(data) - 1,
                #     daily_data=daily_data,
                #     current_time=current_time.time() if hasattr(current_time, 'time') else None
                # )
                #
                # # 필터 통과 체크
                # if not filter_result['passed']:
                #     # 필터 실패시 AVOID 반환
                #     reasons = ['기술지표필터실패'] + filter_result['reasons']
                #     result = SignalStrength(SignalType.AVOID, 0, 0, reasons, volume_analysis.volume_ratio, BisectorStatus.BROKEN)
                #
                #     if debug and logger:
                #         logger.info(f"[{stock_code}] 기술필터실패: {', '.join(filter_result['reasons'])}")
                #
                #     return (result, []) if return_risk_signals else result
                #
                # # 필터 통과시 기존 로직 진행
                # if debug and logger:
                #     logger.info(f"[{stock_code}] 기술필터통과 (초반모드: {filter_result.get('early_mode', False)})")
                #     for reason in filter_result['reasons']:
                #         logger.info(f"  {reason}")

                # 중복 신호 방지 로직 추가
                current_time = datetime.now()

                # 패턴 구간 정보 추출 (디버그 정보에서)
                debug_info = support_pattern_info.get('debug_info', {})
                uptrend_info = debug_info.get('uptrend', {})
                decline_info = debug_info.get('decline', {})
                support_info = debug_info.get('support', {})

                # 구간 인덱스 추출
                uptrend_start = uptrend_info.get('start_idx', 0) if uptrend_info else 0
                uptrend_end = uptrend_info.get('end_idx', 0) if uptrend_info else 0
                decline_start = decline_info.get('start_idx', 0) if decline_info else 0
                decline_end = decline_info.get('end_idx', 0) if decline_info else 0
                support_start = support_info.get('start_idx', 0) if support_info else 0
                support_end = support_info.get('end_idx', 0) if support_info else 0

                # 매수 신호 발생
                signal_strength = SignalStrength(
                    signal_type=SignalType.STRONG_BUY if support_pattern_info['confidence'] >= 80 else SignalType.CAUTIOUS_BUY,
                    confidence=support_pattern_info['confidence'],
                    target_profit=3.0,
                    reasons=support_pattern_info['reasons'] + ['기술필터통과'],
                    volume_ratio=volume_analysis.volume_ratio,
                    bisector_status=PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN,
                    buy_price=support_pattern_info.get('entry_price'),
                    entry_low=support_pattern_info.get('entry_price'),
                    pattern_data=support_pattern_info  # 📊 4단계 패턴 구간 데이터
                )

                if debug and logger:
                    entry_price = support_pattern_info.get('entry_price', 0)
                    entry_price_str = f"{entry_price:,.0f}" if isinstance(entry_price, (int, float)) and entry_price > 0 else "0"
                    logger.info(f"[{stock_code}] 4단계패턴매수: 신뢰도{support_pattern_info['confidence']:.0f}%, 진입가{entry_price_str}원")

                return (signal_strength, []) if return_risk_signals else signal_strength

            # 4단계 패턴이 없으면 매수금지
            result = SignalStrength(SignalType.AVOID, 0, 0, ["4단계패턴없음"], volume_analysis.volume_ratio, BisectorStatus.BROKEN)
            return (result, []) if return_risk_signals else result

        except Exception as e:
            if debug and logger:
                logger.error(f"신호 생성 중 오류: {e}")
            result = SignalStrength(SignalType.AVOID, 0, 0, [f'오류: {str(e)}'], 0, BisectorStatus.BROKEN) if return_risk_signals else None
            return (result, []) if return_risk_signals else result
    
    # 기존 호환성을 위한 메서드들
    @staticmethod
    def check_heavy_selling_pressure(data: pd.DataFrame, baseline_volumes: pd.Series) -> bool:
        """매물 부담 확인"""
        if len(data) < 10:
            return False
        
        try:
            # 최근 5개 봉 중 3% 상승 후 하락하면서 고거래량인 경우가 있는지 확인
            recent_data = data.iloc[-5:].copy()
            for i in range(1, len(recent_data)):
                prev_close = recent_data.iloc[i-1]['close']
                curr = recent_data.iloc[i]
                
                # 3% 상승 달성
                if curr['high'] >= prev_close * 1.03:
                    # 그 후 하락
                    if curr['close'] < curr['open']:
                        # 고거래량 (50% 이상)
                        volume_ratio = curr['volume'] / baseline_volumes.iloc[-5+i] if baseline_volumes.iloc[-5+i] > 0 else 0
                        if volume_ratio > 0.5:
                            return True
            return False
        except:
            return False
    
    @staticmethod
    def check_bearish_volume_restriction(data: pd.DataFrame, baseline_volumes: pd.Series) -> bool:
        """음봉 거래량 제한 확인 (엄격한 조건만 적용)"""
        if len(data) < 2:
            return False
        
        try:
            current_volume = data['volume'].iloc[-1]
            current_is_bullish = data['close'].iloc[-1] > data['open'].iloc[-1]
            
            # 현재 양봉이 아니면 제한 없음
            if not current_is_bullish:
                return False
            
            # 최근 15봉 내에서만 확인 (더 짧은 윈도우)
            recent_data = data.tail(16)  # 현재봉 + 과거 15봉
            recent_bearish = recent_data[recent_data['close'] < recent_data['open']]
            
            if len(recent_bearish) == 0:
                return False
            
            # 최근 15봉 내 최대 음봉 거래량
            max_recent_bearish_volume = recent_bearish['volume'].max()
            
            # 베이스라인 거래량 기준
            baseline_volume = baseline_volumes.iloc[-1] if len(baseline_volumes) > 0 else current_volume
            
            # 더 엄격한 조건: 음봉 거래량이 베이스라인의 2배 이상이고, 
            # 현재 양봉 거래량이 그보다 작을 때만 제한
            if max_recent_bearish_volume > baseline_volume * 2.0:
                return current_volume <= max_recent_bearish_volume
            
            return False
            
        except:
            return False
    
    @staticmethod
    def check_high_volume_decline_recovery(data: pd.DataFrame, baseline_volumes: pd.Series) -> dict:
        """대량 매물 출현 후 회복 여부 확인"""
        if len(data) < 10 or len(baseline_volumes) < 10:
            return {'should_avoid': False, 'reason': '데이터부족'}
        
        try:
            # 전체 캔들 분석 (고거래량 하락은 하루 중 언제든 발생할 수 있음)
            recent_data = data.copy()
            recent_baseline = baseline_volumes
            
            # 대량 음봉 찾기 (기준거래량 50% 이상 + 하락)
            high_volume_declines = []
            
            for i in range(len(recent_data)):
                candle = recent_data.iloc[i]
                baseline_vol = recent_baseline.iloc[i] if i < len(recent_baseline) else 0
                
                # 음봉인지 확인
                is_bearish = candle['close'] < candle['open']
                # 대량거래인지 확인 (기준거래량 50% 이상)
                is_high_volume = candle['volume'] >= baseline_vol * 0.5 if baseline_vol > 0 else False
                
                if is_bearish and is_high_volume:
                    decline_pct = (candle['close'] - candle['open']) / candle['open'] * 100 if candle['open'] > 0 else 0
                    high_volume_declines.append({
                        'index': i,
                        'decline_pct': abs(decline_pct),
                        'low_price': candle['low'],
                        'volume_ratio': candle['volume'] / baseline_vol if baseline_vol > 0 else 0
                    })
            
            # 2개 이상의 대량 음봉이 있는지 확인
            if len(high_volume_declines) < 2:
                return {'should_avoid': False, 'reason': f'대량음봉부족({len(high_volume_declines)}개)'}
            
            # 가장 심각한 하락폭들 선별 (상위 2개)
            top_declines = sorted(high_volume_declines, key=lambda x: x['decline_pct'], reverse=True)[:2]
            total_decline_required = sum([d['decline_pct'] for d in top_declines])
            lowest_point = min([d['low_price'] for d in high_volume_declines])
            
            # 현재가가 하락폭만큼 회복했는지 확인
            current_price = recent_data['close'].iloc[-1]
            recovery_from_low = (current_price - lowest_point) / lowest_point * 100
            
            # 회복 기준: 총 하락폭의 70% 이상 회복해야 거래 허용
            recovery_threshold = total_decline_required * 0.7
            
            if recovery_from_low < recovery_threshold:
                reason = f"하락{total_decline_required:.1f}% vs 회복{recovery_from_low:.1f}% (기준{recovery_threshold:.1f}%)"
                return {'should_avoid': True, 'reason': reason}
            
            return {'should_avoid': False, 'reason': '회복충분'}
            
        except Exception as e:
            # 오류 발생시 안전하게 거래 허용
            return {'should_avoid': False, 'reason': f'분석오류: {str(e)}'}
    
    @staticmethod
    def check_bisector_breakout_volume(data: pd.DataFrame) -> bool:
        """이등분선 돌파 거래량 확인"""
        if len(data) < 2:
            return True  # 기본값
        
        try:
            current_volume = data['volume'].iloc[-1]
            prev_volume = data['volume'].iloc[-2]
            
            # 직전 봉의 2배 이상
            return current_volume >= prev_volume * 2
        except:
            return True
    
    # 기존 메서드들 (단순화된 버전)
    @staticmethod
    def generate_trading_signals(
        data: pd.DataFrame,
        *,
        enable_candle_shrink_expand: bool = False,
        enable_divergence_precondition: bool = False,
        enable_overhead_supply_filter: bool = False,
        use_improved_logic: bool = True,
        candle_expand_multiplier: float = 1.10,
        overhead_lookback: int = 10,
        overhead_threshold_hits: int = 2,
        debug: bool = False,
        logger: Optional[logging.Logger] = None,
        log_level: int = 20,  # logging.INFO = 20
        stock_code: str = "UNKNOWN"
    ) -> pd.DataFrame:
        """거래 신호 생성 (기존 호환성 유지)"""
        # 호환성을 위해 기존 파라미터들을 받지만 새로운 로직에서는 일부만 사용
        # 중복 호출 제거: _generate_signals_with_improved_logic 내부에서 이미 generate_improved_signals를 호출함
        
        # 원본 로직을 따라 DataFrame 형태로 신호 생성
        return PullbackCandlePattern._generate_signals_with_improved_logic(
            data, debug, logger, log_level, stock_code
        )
    
    @staticmethod
    def _generate_signals_with_improved_logic(
        data: pd.DataFrame, 
        debug: bool = False, 
        logger: Optional[logging.Logger] = None,
        log_level: int = 20,
        stock_code: str = "UNKNOWN"
    ) -> pd.DataFrame:
        """개선된 로직을 기존 DataFrame 형식으로 변환 (원본 호환)"""
        try:
            # 이등분선 계산
            bisector_line = BisectorLine.calculate_bisector_line(data['high'], data['low'])
            
            # 결과 DataFrame 초기화 (기존 형식 유지)
            signals = pd.DataFrame(index=data.index)
            signals['buy_pullback_pattern'] = False
            signals['buy_bisector_recovery'] = False  
            signals['sell_bisector_break'] = False
            signals['sell_support_break'] = False
            signals['stop_entry_low_break'] = False
            signals['take_profit_3pct'] = False
            signals['bisector_line'] = bisector_line
            
            # 신호 강도 정보 컬럼 추가
            signals['signal_type'] = ''
            signals['confidence'] = 0.0
            signals['target_profit'] = 0.0
            
            # 포지션 시뮬레이션 변수
            in_position = False
            entry_price = None
            entry_low = None
            
            # 각 시점에서 신호 계산
            for i in range(5, len(data)):  # 최소 5개 데이터 필요
                current_data = data.iloc[:i+1]
                
                # 개선된 신호 생성 (새 인터페이스 사용) - daily_data는 외부에서 전달받아야 함
                signal_strength = PullbackCandlePattern.generate_improved_signals(
                    current_data, stock_code, debug
                )
                
                if signal_strength is None:
                    continue
                
                # 위험 신호 확인 (매도 우선)
                if in_position:
                    risk_signals = PullbackUtils.detect_risk_signals(
                        current_data, entry_price, entry_low
                    )
                    
                    for risk in risk_signals:
                        if risk == RiskSignal.BISECTOR_BREAK:
                            signals.iloc[i, signals.columns.get_loc('sell_bisector_break')] = True
                            in_position = False
                        elif risk == RiskSignal.SUPPORT_BREAK:
                            signals.iloc[i, signals.columns.get_loc('sell_support_break')] = True
                            in_position = False
                        elif risk == RiskSignal.ENTRY_LOW_BREAK:
                            signals.iloc[i, signals.columns.get_loc('stop_entry_low_break')] = True
                            in_position = False
                        elif risk == RiskSignal.TARGET_REACHED:
                            signals.iloc[i, signals.columns.get_loc('take_profit_3pct')] = True
                            in_position = False
                
                if not in_position:
                    # 매수 신호 확인
                    if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                        # 신호 근거에 따라 다른 컬럼 사용
                        if signal_strength.signal_type == SignalType.STRONG_BUY:
                            signals.iloc[i, signals.columns.get_loc('buy_pullback_pattern')] = True
                        else:  # CAUTIOUS_BUY
                            signals.iloc[i, signals.columns.get_loc('buy_bisector_recovery')] = True
                        
                        # 신호 강도 정보 저장
                        signals.iloc[i, signals.columns.get_loc('signal_type')] = signal_strength.signal_type.value
                        signals.iloc[i, signals.columns.get_loc('confidence')] = signal_strength.confidence
                        signals.iloc[i, signals.columns.get_loc('target_profit')] = signal_strength.target_profit
                        
                        # 포지션 진입
                        in_position = True
                        entry_price = current_data.iloc[-1]['close']
                        entry_low = current_data.iloc[-1]['low']
                        
                        if debug and logger:
                            logger.info(f"[{stock_code}] 매수신호: {signal_strength.signal_type.value} "
                                      f"(신뢰도: {signal_strength.confidence:.0f}%)")
            
            return signals
            
        except Exception as e:
            if debug and logger:
                logger.error(f"신호 생성 중 오류: {e}")
            # 빈 DataFrame 반환
            return pd.DataFrame(index=data.index, columns=[
                'buy_pullback_pattern', 'buy_bisector_recovery', 'sell_bisector_break'
            ])
    
    @staticmethod
    def generate_sell_signals(data: pd.DataFrame, entry_price: float, entry_low: float,
                            stock_code: str = "UNKNOWN", debug: bool = False) -> List[RiskSignal]:
        """매도 신호 생성"""
        return PullbackUtils.detect_risk_signals(data, entry_price, entry_low)
