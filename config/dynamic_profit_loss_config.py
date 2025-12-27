"""
동적 손익비 설정 모듈

시장 상황(거래량 패턴, 시간대)에 따라 최적화된 손익비를 적용합니다.
분석 결과: analysis_results/optimal_profit_loss_ratio_*.csv

🔧 사용 방법:
    config/trading_config.json 에서 "use_dynamic_profit_loss": true/false 로 ON/OFF
"""

import pandas as pd
import os
import json
import threading
from datetime import datetime

class DynamicProfitLossConfig:
    """동적 손익비 관리 클래스"""

    # 기본 손익비 (분석 결과가 없거나 적용 불가 시)
    DEFAULT_STOP_LOSS = -2.5  # %
    DEFAULT_TAKE_PROFIT = 3.5  # %

    # 플래그 캐싱 (파일 읽기 최소화)
    _use_dynamic_cache = None
    _last_check_time = None
    _cache_lock = threading.Lock()  # 스레드 안전성 보장

    # 분석 기반 최적 손익비 (analysis_results/optimal_profit_loss_ratio_*.csv 기반)
    # 거래량 패턴별 손익비
    VOLUME_PATTERN_RATIOS = {
        'very_low': {'stop_loss': -4.5, 'take_profit': 7.0},  # 매물 부담이 거의 없는 상황
        'low': {'stop_loss': -1.0, 'take_profit': 7.5},       # 거래량이 낮은 상황
        'normal': {'stop_loss': -2.5, 'take_profit': 7.5},    # 일반적인 거래량
        'high': {'stop_loss': -1.0, 'take_profit': 7.5},      # 거래량이 높은 상황
    }

    # 시간대별 손익비
    TIME_ZONE_RATIOS = {
        'early': {'stop_loss': -2.5, 'take_profit': 7.0},     # 9시~10시
        'morning': {'stop_loss': -4.5, 'take_profit': 7.0},   # 10시~12시
        'afternoon': DEFAULT_STOP_LOSS,                        # 12시~14시 (샘플 부족)
        'late': DEFAULT_STOP_LOSS,                             # 14시~ (샘플 부족)
    }

    # 조합별 손익비 (거래량 패턴 + 시간대)
    COMBINATION_RATIOS = {
        ('very_low', 'early'): {'stop_loss': -3.5, 'take_profit': 7.0},
        ('very_low', 'morning'): {'stop_loss': -4.5, 'take_profit': 7.0},
        ('normal', 'early'): {'stop_loss': -3.0, 'take_profit': 7.0},
        ('normal', 'morning'): {'stop_loss': -2.5, 'take_profit': 7.5},
        ('low', 'early'): {'stop_loss': -2.5, 'take_profit': 7.5},
        ('low', 'morning'): {'stop_loss': -1.0, 'take_profit': 7.5},
        ('high', 'morning'): {'stop_loss': -1.0, 'take_profit': 7.5},
    }

    @staticmethod
    def classify_volume_pattern(current_volume, reference_volume):
        """
        거래량 패턴 분류

        Args:
            current_volume: 현재 3분봉 거래량
            reference_volume: 기준 거래량 (당일 최대 거래량)

        Returns:
            'very_low', 'low', 'normal', 'high' 중 하나
        """
        if reference_volume == 0:
            return 'normal'

        ratio = current_volume / reference_volume

        if ratio < 0.25:  # 기준의 1/4 미만
            return 'very_low'
        elif ratio < 0.5:  # 기준의 1/2 미만
            return 'low'
        elif ratio < 0.75:
            return 'normal'
        else:
            return 'high'

    @staticmethod
    def classify_time_zone(current_time):
        """
        시간대 분류

        Args:
            current_time: datetime 또는 'HH:MM' 형식의 문자열

        Returns:
            'early', 'morning', 'afternoon', 'late' 중 하나
        """
        if isinstance(current_time, str):
            hour = int(current_time.split(':')[0])
        elif isinstance(current_time, datetime):
            hour = current_time.hour
        else:
            return 'morning'  # 기본값

        if hour < 10:
            return 'early'
        elif hour < 12:
            return 'morning'
        elif hour < 14:
            return 'afternoon'
        else:
            return 'late'

    @classmethod
    def is_dynamic_enabled(cls):
        """
        동적 손익비 활성화 여부 확인 (캐싱 적용)

        Returns:
            bool: True면 동적 손익비 사용, False면 기본 손익비 사용
        """
        import time
        current_time = time.time()

        # 🆕 환경 변수 우선 확인 (시뮬레이션용)
        env_value = os.environ.get('USE_DYNAMIC_PROFIT_LOSS')
        if env_value == 'true':
            return True
        elif env_value == 'false':
            return False

        # 스레드 안전성 보장
        with cls._cache_lock:
            # 10초마다만 파일 체크 (성능 최적화)
            if cls._use_dynamic_cache is not None and cls._last_check_time is not None:
                if current_time - cls._last_check_time < 10:
                    return cls._use_dynamic_cache

            # config 파일 읽기
            try:
                config_path = os.path.join(os.path.dirname(__file__), 'trading_config.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        enabled = config.get('risk_management', {}).get('use_dynamic_profit_loss', False)
                        cls._use_dynamic_cache = enabled
                        cls._last_check_time = current_time
                        return enabled
            except Exception as e:
                print(f"동적 손익비 설정 로드 실패: {e}")

            # 기본값: False (동적 손익비 비활성화)
            cls._use_dynamic_cache = False
            cls._last_check_time = current_time
            return False

    @classmethod
    def get_profit_loss_ratio(cls, current_volume=None, reference_volume=None, current_time=None):
        """
        시장 상황에 맞는 손익비 반환

        Args:
            current_volume: 현재 거래량 (선택)
            reference_volume: 기준 거래량 (선택)
            current_time: 현재 시간 (선택)

        Returns:
            {'stop_loss': float, 'take_profit': float}
        """
        # ⚙️ 동적 손익비 비활성화 시 기본값 반환 (C++ ifndef 스타일)
        if not cls.is_dynamic_enabled():
            return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}

        # ✅ 동적 손익비 활성화 시 패턴 기반 계산

        # 1. 조합별 손익비 우선 (거래량 패턴 + 시간대)
        if current_volume is not None and reference_volume is not None and current_time is not None:
            volume_pattern = cls.classify_volume_pattern(current_volume, reference_volume)
            time_zone = cls.classify_time_zone(current_time)

            combination_key = (volume_pattern, time_zone)
            if combination_key in cls.COMBINATION_RATIOS:
                return cls.COMBINATION_RATIOS[combination_key].copy()

        # 2. 거래량 패턴만 있는 경우
        if current_volume is not None and reference_volume is not None:
            volume_pattern = cls.classify_volume_pattern(current_volume, reference_volume)
            if volume_pattern in cls.VOLUME_PATTERN_RATIOS:
                return cls.VOLUME_PATTERN_RATIOS[volume_pattern].copy()

        # 3. 시간대만 있는 경우
        if current_time is not None:
            time_zone = cls.classify_time_zone(current_time)
            ratio = cls.TIME_ZONE_RATIOS.get(time_zone)
            if isinstance(ratio, dict):
                return ratio.copy()

        # 4. 기본값
        return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}

    @classmethod
    def extract_pattern_from_debug_info(cls, debug_info):
        """
        debug_info에서 패턴 특성을 추출하여 분류

        Args:
            debug_info: support_pattern_analyzer의 debug_info 또는 get_debug_info() 결과

        Returns:
            (support_volume_class, decline_volume_class) 튜플 또는 (None, None)
        """
        if not debug_info:
            return (None, None)

        try:
            # uptrend, decline, support 정보 추출
            uptrend = debug_info.get('uptrend', {})
            decline = debug_info.get('decline', {})
            support = debug_info.get('support', {})

            # 필수 데이터 확인 (문자열 포맷팅 처리)
            def to_float(val):
                """숫자 또는 콤마 포맷팅된 문자열을 float로 변환"""
                if val is None:
                    return 0.0
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    try:
                        # 콤마와 퍼센트 기호 제거 후 변환
                        cleaned = val.replace(',', '').replace('%', '').strip()
                        return float(cleaned)
                    except (ValueError, AttributeError):
                        return 0.0
                return 0.0

            uptrend_max_volume = to_float(uptrend.get('max_volume', 0))
            uptrend_avg_volume = to_float(uptrend.get('avg_volume', 0))
            support_avg_volume = to_float(support.get('avg_volume', 0))
            decline_avg_volume = to_float(decline.get('avg_volume', 0))

            if uptrend_max_volume == 0 or uptrend_avg_volume == 0:
                return (None, None)

            # 지지 거래량 분류
            support_volume_ratio = support_avg_volume / uptrend_max_volume
            if support_volume_ratio < 0.15:
                support_volume_class = 'very_low'
            elif support_volume_ratio < 0.25:
                support_volume_class = 'low'
            else:
                support_volume_class = 'normal'

            # 하락 거래량 분류
            decline_volume_ratio = decline_avg_volume / uptrend_avg_volume
            if decline_volume_ratio < 0.3:
                decline_volume_class = 'strong_decrease'
            elif decline_volume_ratio < 0.6:
                decline_volume_class = 'normal_decrease'
            else:
                decline_volume_class = 'weak_decrease'

            return (support_volume_class, decline_volume_class)

        except Exception:
            return (None, None)

    @classmethod
    def get_ratio_by_pattern(cls, support_volume_class, decline_volume_class):
        """
        패턴 조합으로 직접 손익비 조회 (백테스트 결과 기반)

        Args:
            support_volume_class: 'very_low', 'low', 'normal' 중 하나
            decline_volume_class: 'strong_decrease', 'normal_decrease', 'weak_decrease' 중 하나

        Returns:
            {'stop_loss': float, 'take_profit': float}
        """
        # ⚙️ 동적 손익비 비활성화 시 기본값 반환
        if not cls.is_dynamic_enabled():
            return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}

        # ✅ 패턴 조합 테이블 (최신 분석 결과 기반 - 20251227_002926)
        PATTERN_COMBINATION_RATIOS = {
            ('very_low', 'weak_decrease'): {'stop_loss': -4.5, 'take_profit': 7.0},   # 평균 +0.75%, 승률 48.2%, 191건
            ('very_low', 'normal_decrease'): {'stop_loss': -5.0, 'take_profit': 7.0}, # 평균 +0.63%, 승률 50.4%, 139건
            ('very_low', 'strong_decrease'): {'stop_loss': -4.0, 'take_profit': 7.0}, # 평균 -0.17%, 승률 36.4%, 22건
            ('low', 'weak_decrease'): {'stop_loss': -5.0, 'take_profit': 7.5},        # 평균 +0.71%, 승률 45.9%, 183건
            ('low', 'normal_decrease'): {'stop_loss': -2.0, 'take_profit': 7.5},      # 평균 +0.49%, 승률 35.8%, 106건
            ('low', 'strong_decrease'): {'stop_loss': -1.0, 'take_profit': 7.5},      # 평균 +4.60%, 승률 80.0%, 10건 ⭐최고
            ('normal', 'weak_decrease'): {'stop_loss': -5.0, 'take_profit': 7.5},     # 평균 +0.45%, 승률 50.8%, 120건
            ('normal', 'normal_decrease'): {'stop_loss': -5.0, 'take_profit': 5.0},   # 평균 +0.29%, 승률 53.7%, 54건
            ('high', 'weak_decrease'): {'stop_loss': -2.0, 'take_profit': 7.5},       # 평균 +0.95%, 승률 39.1%, 23건
        }

        key = (support_volume_class, decline_volume_class)
        if key in PATTERN_COMBINATION_RATIOS:
            return PATTERN_COMBINATION_RATIOS[key]

        # 조합이 없으면 기본값
        return {'stop_loss': cls.DEFAULT_STOP_LOSS, 'take_profit': cls.DEFAULT_TAKE_PROFIT}

    @classmethod
    def get_stop_loss_pct(cls, current_volume=None, reference_volume=None, current_time=None):
        """손절 비율(%) 반환 (음수)"""
        ratio = cls.get_profit_loss_ratio(current_volume, reference_volume, current_time)
        return ratio['stop_loss']

    @classmethod
    def get_take_profit_pct(cls, current_volume=None, reference_volume=None, current_time=None):
        """익절 비율(%) 반환 (양수)"""
        ratio = cls.get_profit_loss_ratio(current_volume, reference_volume, current_time)
        return ratio['take_profit']

    @classmethod
    def load_from_csv(cls, csv_path):
        """
        CSV 파일에서 최적 손익비 로드하여 설정 업데이트

        Args:
            csv_path: optimal_profit_loss_ratio_*.csv 파일 경로
        """
        if not os.path.exists(csv_path):
            print(f"CSV 파일 없음: {csv_path}")
            return

        df = pd.read_csv(csv_path)

        # 거래량 패턴별 업데이트
        volume_patterns = df[df['category'] == 'volume_pattern']
        for _, row in volume_patterns.iterrows():
            pattern = row['value']
            cls.VOLUME_PATTERN_RATIOS[pattern] = {
                'stop_loss': row['stop_loss'],
                'take_profit': row['take_profit']
            }

        # 시간대별 업데이트
        time_zones = df[df['category'] == 'time_zone']
        for _, row in time_zones.iterrows():
            zone = row['value']
            cls.TIME_ZONE_RATIOS[zone] = {
                'stop_loss': row['stop_loss'],
                'take_profit': row['take_profit']
            }

        # 조합별 업데이트
        combinations = df[df['category'] == 'combination']
        for _, row in combinations.iterrows():
            if pd.notna(row['volume_pattern']) and pd.notna(row['time_zone']):
                key = (row['volume_pattern'], row['time_zone'])
                cls.COMBINATION_RATIOS[key] = {
                    'stop_loss': row['stop_loss'],
                    'take_profit': row['take_profit']
                }

        print(f"동적 손익비 설정 로드 완료: {csv_path}")


# 편의 함수
def get_dynamic_stop_loss(current_volume=None, reference_volume=None, current_time=None):
    """동적 손절 비율 반환"""
    return DynamicProfitLossConfig.get_stop_loss_pct(current_volume, reference_volume, current_time)


def get_dynamic_take_profit(current_volume=None, reference_volume=None, current_time=None):
    """동적 익절 비율 반환"""
    return DynamicProfitLossConfig.get_take_profit_pct(current_volume, reference_volume, current_time)


def get_dynamic_profit_loss_ratio(current_volume=None, reference_volume=None, current_time=None):
    """동적 손익비 반환"""
    return DynamicProfitLossConfig.get_profit_loss_ratio(current_volume, reference_volume, current_time)


# 최신 분석 결과 자동 로드
def auto_load_latest_analysis():
    """analysis_results 디렉토리에서 최신 분석 결과 자동 로드"""
    analysis_dir = "analysis_results"
    if not os.path.exists(analysis_dir):
        return

    csv_files = [
        f for f in os.listdir(analysis_dir)
        if f.startswith('optimal_profit_loss_ratio_') and f.endswith('.csv')
    ]

    if not csv_files:
        return

    # 파일명에서 날짜 추출하여 최신 파일 찾기
    csv_files.sort(reverse=True)
    latest_file = os.path.join(analysis_dir, csv_files[0])

    DynamicProfitLossConfig.load_from_csv(latest_file)


# 모듈 로드 시 자동으로 최신 분석 결과 적용
# auto_load_latest_analysis()  # 필요시 주석 해제
