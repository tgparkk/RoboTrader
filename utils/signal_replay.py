from __future__ import annotations

"""
실데이터 기반 매매신호(눌림목/3분봉) 재현 리포트 스크립트

🎯 손절/익절 설정:
  config/trading_config.json 파일에서 자동으로 로드됩니다.
  (risk_management.take_profit_ratio / stop_loss_ratio)
  
🔄 로직 전환 방법:
  # v2 로직 사용 (SHA-1: 4d2836c2 복원):
    - 157-164 라인 주석 해제
    - 167-171 라인 주석 처리
    - 999-1006 라인 주석 해제  
    - 1009-1013 라인 주석 처리
  
  # 현재 로직 사용 (개선된 버전):
    - 157-164 라인 주석 처리
    - 167-171 라인 주석 해제
    - 999-1006 라인 주석 처리
    - 1009-1013 라인 주석 해제

사용 예 (Windows PowerShell):
  # candidate_stocks 테이블에서 자동으로 종목 조회
  python utils\signal_replay.py --date 20250825 --export txt --charts
  
  # 특정 종목 직접 지정
  python utils\signal_replay.py --date 20250808 \
    --codes 034230,078520,107600,214450 \
    --times "034230=14:39;078520=11:33;107600=11:24,11:27,14:51;214450=12:00,14:39" \
    --export csv

동작:
- 각 종목의 당일 1분봉(09:00~15:30)을 실데이터로 조회
- 3분봉으로 변환 후 PullbackCandlePattern.generate_trading_signals 계산
- 지정 시각에서 매수신호(buy_pullback_pattern / buy_bisector_recovery) ON/OFF 확인
- OFF면 핵심 미충족 조건(저거래 3봉, 회복양봉, 거래량 회복, 이등분선 지지/회복)을 요약

주의:
- 더미 데이터 사용 없음. KIS API 설정이 유효해야 합니다.
- 전략은 눌림목만 사용합니다. 동일 캔들 중복 신호 차단으로 정확한 재매수 시뮬레이션.
"""

# ==================== 손절/익절 설정 ====================
# 📊 config/trading_config.json 에서 손절/익절 비율 로드
# (하드코딩 제거 - 실시간 매매와 동일한 설정 사용)
# =========================================================

import argparse
import asyncio
from typing import Dict, List, Tuple, Optional
import io
import logging
from datetime import datetime, timedelta, time
import sys
import os
import sqlite3
import concurrent.futures
import time
import pickle
from pathlib import Path

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.data_cache import DailyDataCache

# 전역 변수로 현재 처리 중인 종목코드 추적
current_processing_stock = {'code': 'UNKNOWN'}

# 일봉 캐시 매니저 (전역)
_daily_cache = None

def _get_daily_cache():
    """일봉 캐시 매니저 가져오기 (싱글톤)"""
    global _daily_cache
    if _daily_cache is None:
        _daily_cache = DailyDataCache()
    return _daily_cache

def load_daily_data(stock_code: str) -> Optional[pd.DataFrame]:
    """일봉 데이터 로드 (PG 우선, pkl 폴백)"""
    try:
        # PG에서 먼저 시도
        daily_cache = _get_daily_cache()
        data = daily_cache.load_data(stock_code)

        if data is None:
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
        print(f"일봉 데이터 로드 실패 {stock_code}: {e}")
        return None

import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import KST
from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
from api.kis_api_manager import KISAPIManager
from visualization.data_processor import DataProcessor
from config.settings import load_trading_config
from utils.signal_replay_utils import (
    parse_times_mapping,
    get_stocks_with_selection_date,
    calculate_selection_date_stats,
    get_target_profit_from_signal_strength,
    locate_row_for_time,
    to_csv_rows,
    generate_chart_for_stock,
    generate_timeline_analysis_log
)


try:
    # PowerShell cp949 콘솔에서 이모지/UTF-8 로그 출력 오류 방지
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logger = setup_logger(__name__)

# 설정 파일에서 손절/익절 비율 로드
_trading_config = load_trading_config()
PROFIT_TAKE_RATE = _trading_config.risk_management.take_profit_ratio * 100  # 0.035 -> 3.5%
STOP_LOSS_RATE = _trading_config.risk_management.stop_loss_ratio * 100      # 0.025 -> 2.5%

# 🔧 동적 손익비 플래그 확인
USE_DYNAMIC_PROFIT_LOSS = hasattr(_trading_config.risk_management, 'use_dynamic_profit_loss') and _trading_config.risk_management.use_dynamic_profit_loss

if USE_DYNAMIC_PROFIT_LOSS:
    print(f"[시뮬레이션 설정] 🔧 동적 손익비 활성화 (패턴별 최적화)")
else:
    print(f"[시뮬레이션 설정] 익절 +{PROFIT_TAKE_RATE}% / 손절 -{STOP_LOSS_RATE}% (고정)")
print("=" * 60)


def load_stock_names() -> Dict[str, str]:
    """DB에서 종목 코드-종목명 매핑 로드"""
    try:
        conn = sqlite3.connect('data/robotrader.db')
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT stock_code, stock_name FROM candidate_stocks WHERE stock_name IS NOT NULL")
        stock_map = {code: name for code, name in cursor.fetchall()}

        conn.close()
        print(f"✅ 종목명 로드 완료: {len(stock_map)}개")
        return stock_map
    except Exception as e:
        print(f"⚠️  종목명 로드 실패: {e}")
        return {}


def calculate_max_concurrent_holdings(all_trades: Dict[str, List[Dict[str, object]]]) -> int:
    """최대 동시 보유 종목 수를 계산

    Args:
        all_trades: {종목코드: [거래내역]} 딕셔너리

    Returns:
        int: 특정 시점에 최대로 동시에 보유한 종목 수
    """
    if not all_trades:
        return 0

    # 모든 매수/매도 이벤트를 시간순으로 정렬
    events = []
    for stock_code, trades in all_trades.items():
        for trade in trades:
            if trade.get('buy_time') and trade.get('sell_time'):
                # 매수 시간
                buy_time = trade['buy_time']
                events.append((buy_time, 'buy', stock_code))

                # 매도 시간
                sell_time = trade['sell_time']
                events.append((sell_time, 'sell', stock_code))

    if not events:
        return 0

    # 시간순으로 정렬
    events.sort(key=lambda x: x[0])

    # 각 시점별로 보유 종목 수 추적
    current_holdings = set()
    max_holdings = 0

    for time_str, event_type, stock_code in events:
        if event_type == 'buy':
            current_holdings.add(stock_code)
        elif event_type == 'sell':
            current_holdings.discard(stock_code)

        max_holdings = max(max_holdings, len(current_holdings))

    return max_holdings


def calculate_trading_signals_once(df_3min: pd.DataFrame, *, debug_logs: bool = False, 
                                 logger: Optional[logging.Logger] = None,
                                 log_level: int = logging.INFO,
                                 stock_code: str = "UNKNOWN") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """3분봉 데이터에 대해 신호를 계산
    
    모든 함수에서 공통으로 사용하는 신호 계산 함수
    09시 이전 데이터는 PullbackCandlePattern 내부에서 제외
    
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (기본 신호, 신호 강도 정보)
    """
    if df_3min is None or df_3min.empty or 'datetime' not in df_3min.columns:
        return pd.DataFrame(), pd.DataFrame()
    
    start_time = time.time()
    
    # 로거에 종목코드 설정 (타임라인 로그용)  
    if logger:
        logger._stock_code = stock_code
    
    # 전역 변수에도 현재 처리 중인 종목코드 설정
    current_processing_stock['code'] = stock_code
    
    if logger:
        logger.info(f"🔧 [{stock_code}] 신호 계산 시작...")
        
    signals = PullbackCandlePattern.generate_trading_signals(
        df_3min,
        enable_candle_shrink_expand=False,
        enable_divergence_precondition=False,
        enable_overhead_supply_filter=True,
        use_improved_logic=True,  # ✅ main.py와 일치하도록 개선된 로직 사용
        candle_expand_multiplier=1.10,
        overhead_lookback=10,
        overhead_threshold_hits=2,
        debug=debug_logs,
        logger=logger,
        log_level=log_level,
        stock_code=stock_code,  # ✅ 종목코드 전달하여 UNKNOWN 문제 해결
    )
    
    elapsed = time.time() - start_time
    
    # 결과 반환
    result = (signals, pd.DataFrame())  # 신호 강도 정보는 signals에 포함됨
    
    # 이제 signals에 신호 강도 정보가 포함되어 있음 (use_improved_logic=True)
    if logger:
        logger.info(f"✅ [{stock_code}] 신호 계산 완료: {elapsed:.2f}초, {len(signals)}행")
        
        # 신호 강도 정보가 있는지 확인
        if signals is not None and not signals.empty:
            has_signal_type = 'signal_type' in signals.columns
            has_target_profit = 'target_profit' in signals.columns
            has_confidence = 'confidence' in signals.columns
            
            if has_signal_type or has_target_profit or has_confidence:
                logger.debug(f"📊 {stock_code} 신호 강도 정보 포함: signal_type={has_signal_type}, target_profit={has_target_profit}, confidence={has_confidence}")
    
    # signals 자체에 signal_type, confidence, target_profit이 포함됨
    # 기존의 sig_improved는 signals와 동일
    return signals, signals


def list_all_buy_signals(df_3min: pd.DataFrame, df_1min: Optional[pd.DataFrame] = None, *, logger: Optional[logging.Logger] = None, stock_code: str = "UNKNOWN", simulation_date: Optional[str] = None) -> List[Dict[str, object]]:
    """전체 3분봉에서 매수 신호 전체 리스트를 반환 (실시간과 동일한 방식)"""

    if df_3min is None or df_3min.empty:
        return []
    
    try:
        from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
        
        buy_signals = []

        # 각 3분봉 시점에서 실시간과 동일한 방식으로 신호 체크 (시계열 순서 유지)
        for i in range(len(df_3min)):
            # 해당 시점까지의 데이터만 사용 (실시간과 동일)
            current_data = df_3min.iloc[:i+1].copy()

            if len(current_data) < 5:  # 최소 데이터 요구사항
                continue

            # ⚡ 성능 최적화: 12시 이후 신호는 건너뛰기
            current_row = df_3min.iloc[i]
            if 'datetime' in current_row:
                current_time = current_row['datetime']
                if hasattr(current_time, 'hour') and current_time.hour >= 12:
                    continue  # 12시 이후는 신호 계산 생략
            
            # ==================== 신호 생성 로직 선택 ====================
            # 🔄 현재 로직 사용 (개선된 버전)
            signal_strength = PullbackCandlePattern.generate_improved_signals(
                current_data,
                stock_code=stock_code,
                debug=True
            )
            
            if signal_strength is None:
                continue
            
            # 매수 신호 확인 (실시간과 동일한 조건)
            if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                print(f"✅ {stock_code} 매수 신호 감지: {signal_strength.signal_type.value} (신뢰도: {signal_strength.confidence:.1f}%)")

                # 🎯 간단한 패턴 필터 적용 (명백히 약한 패턴만 차단)
                try:
                    from core.indicators.simple_pattern_filter import SimplePatternFilter

                    pattern_filter = SimplePatternFilter()

                    # 패턴 요약 정보
                    pattern_summary = pattern_filter.get_pattern_summary(stock_code, signal_strength, current_data)
                    print(f"📊 {pattern_summary}")

                    # 약한 패턴 필터링
                    should_filter, filter_reason = pattern_filter.should_filter_out(stock_code, signal_strength, current_data)

                    if should_filter:
                        print(f"🚫 {stock_code} 약한 패턴으로 매수 차단: {filter_reason}")
                        continue  # 매수 신호 무시
                    else:
                        print(f"✅ {stock_code} 패턴 필터 통과: {filter_reason}")

                except Exception as e:
                    print(f"⚠️ {stock_code} 패턴 필터 오류: {e}")
                    # 필터 오류 시에도 매수 신호 진행 (안전장치)

                # 📊 4단계 패턴 구간 데이터 로깅 (시뮬레이션)
                # ENABLE_PATTERN_LOGGING 환경 변수가 설정된 경우에만 로깅
                if os.environ.get('ENABLE_PATTERN_LOGGING') == 'true':
                    try:
                        from core.pattern_data_logger import PatternDataLogger

                        # USE_DYNAMIC_PROFIT_LOSS 환경 변수 확인하여 폴더 선택
                        # (PatternDataLogger 내부에서 자동 처리됨)
                        pattern_logger = PatternDataLogger(simulation_date=simulation_date)

                        if hasattr(signal_strength, 'pattern_data') and signal_strength.pattern_data:
                            pattern_id = pattern_logger.log_pattern_data(
                                stock_code=stock_code,
                                signal_type=signal_strength.signal_type.value,
                                confidence=signal_strength.confidence,
                                support_pattern_info=signal_strength.pattern_data,
                                data_3min=current_data,
                                data_1min=df_1min  # 🆕 1분봉 데이터 전달
                            )
                            # pattern_id를 나중에 사용하기 위해 저장
                            signal_strength._pattern_id = pattern_id
                            print(f"📝 패턴 데이터 로깅 완료: {pattern_id}")
                        else:
                            print(f"⚠️ pattern_data가 없음: hasattr={hasattr(signal_strength, 'pattern_data')}, data={signal_strength.pattern_data if hasattr(signal_strength, 'pattern_data') else 'N/A'}")
                    except Exception as log_err:
                        print(f"⚠️ 패턴 데이터 로깅 실패: {log_err}")
                        import traceback
                        traceback.print_exc()

                # 현재 3분봉 정보
                current_row = df_3min.iloc[i]
                datetime_val = current_row.get('datetime')
                close_val = current_row.get('close', 0)
                volume_val = current_row.get('volume', 0)
                low_val = current_row.get('low', 0)
                
                # 3분봉 완성 시점 (실제 신호 발생 시점)
                signal_completion_time = datetime_val + pd.Timedelta(minutes=3) if datetime_val else datetime_val
                
                # 🔧 동적 손익비용 debug_info 추출
                debug_info = None
                if hasattr(signal_strength, 'pattern_data') and signal_strength.pattern_data:
                    debug_info = signal_strength.pattern_data.get('debug_info')

                signal_info = {
                    'index': i,
                    'datetime': datetime_val,  # 원본 라벨 시간 (내부 처리용)
                    'signal_time': signal_completion_time,  # 실제 신호 발생 시간 (표시용)
                    'time': signal_completion_time.strftime('%H:%M') if signal_completion_time else 'Unknown',
                    'close': close_val,
                    'volume': volume_val,
                    'signal_type': signal_strength.signal_type.value,
                    'confidence': signal_strength.confidence,
                    'target_profit': signal_strength.target_profit,
                    'buy_price': signal_strength.buy_price,  # 실시간과 동일한 3/5가
                    'entry_low': signal_strength.entry_low,  # 실시간과 동일한 진입저가
                    'low': low_val,
                    'reasons': ' | '.join(signal_strength.reasons),  # 신호 사유
                    'pattern_id': getattr(signal_strength, '_pattern_id', None),  # 📊 패턴 ID 저장
                    'debug_info': debug_info
                }
                buy_signals.append(signal_info)
        
        if logger:
            logger.info(f"🎯 [{stock_code}] 총 {len(buy_signals)}개 매수 신호 발견 (실시간 방식)")
            
        return buy_signals
        
    except Exception as e:
        if logger:
            logger.error(f"매수 신호 리스트 생성 실패 [{stock_code}]: {e}")
        return []


def simulate_trades(df_3min: pd.DataFrame, df_1min: Optional[pd.DataFrame] = None, *, logger: Optional[logging.Logger] = None, stock_code: str = "UNKNOWN", selection_date: Optional[str] = None, simulation_date: Optional[str] = None, ml_filter_enabled: bool = False, ml_model=None, ml_feature_names=None, ml_threshold: float = 0.5, pattern_data_cache: Optional[Dict] = None, advanced_filter_enabled: bool = False, advanced_filter_manager=None) -> List[Dict[str, object]]:
    """매수신호 발생 시점에서 1분봉 기준으로 실제 거래를 시뮬레이션 (ML 필터 실시간 적용)

    Args:
        ml_filter_enabled: ML 필터 사용 여부
        ml_model: ML 모델 객체
        ml_feature_names: ML 모델 특성 이름 목록
        ml_threshold: ML 임계값 (기본 0.5)
        pattern_data_cache: 패턴 데이터 캐시 (signal_time -> pattern_data)
        advanced_filter_enabled: 고급 필터 사용 여부
        advanced_filter_manager: 고급 필터 매니저 인스턴스
    """

    if df_3min is None or df_3min.empty:
        return []

    if df_1min is None or df_1min.empty:
        if logger:
            logger.warning(f"1분봉 데이터 없음 - 거래 시뮬레이션 불가 [{stock_code}]")
        return []

    try:
        # 매수 신호 리스트 가져오기 (🆕 1분봉 데이터 전달)
        buy_signals = list_all_buy_signals(df_3min, df_1min, logger=logger, stock_code=stock_code, simulation_date=simulation_date)

        if not buy_signals:
            if logger:
                logger.info(f"매수 신호 없음 - 거래 시뮬레이션 불가 [{stock_code}]")
            return []
        
        
        # 🆕 일봉 기반 패턴 필터 초기화 (시뮬레이션용)
        daily_filter_enabled = False
        daily_pattern_filter = None
        
        try:
            from core.indicators.daily_pattern_filter import DailyPatternFilter
            daily_pattern_filter = DailyPatternFilter(logger=logger)
            daily_filter_enabled = True
            if logger:
                logger.info(f"📊 [{stock_code}] 일봉 패턴 필터 초기화 완료")
        except Exception as e:
            daily_filter_enabled = False
            if logger:
                logger.warning(f"⚠️ [{stock_code}] 일봉 패턴 필터 초기화 실패: {e}")
        
        trades = []
        missed_opportunities = []  # 매수 못한 종목들 추적
        current_position = None  # 현재 포지션 추적 (실시간과 동일하게 한 번에 하나만)
        last_signal_candle_time = None  # 마지막 신호 발생 캔들 시점 추적 (중복 신호 방지)
        # 🆕 설정 파일에서 쿨다운 시간 로드
        from config.settings import load_trading_config
        trading_config = load_trading_config()
        buy_cooldown_minutes = trading_config.order_management.buy_cooldown_minutes
        
        stock_cooldown_end = {}  # 종목별 쿨다운 종료 시간 추적
        
        for signal in buy_signals:
            signal_datetime = signal['datetime']  # 라벨 시간 (09:42)
            signal_completion_time = signal['signal_time']  # 실제 신호 발생 시간 (09:45:00)
            signal_index = signal['index']

            # 🔍 디버그: 308080 종목 신호 처리 추적
            if stock_code == "308080" and logger:
                logger.info(f"🔍 [308080] 신호 처리 시작: {signal_completion_time.strftime('%H:%M')} (라벨: {signal_datetime.strftime('%H:%M')})")

            # ==================== selection_date 필터링 ====================
            if selection_date:
                try:
                    # selection_date 파싱
                    if len(selection_date) >= 19:  # YYYY-MM-DD HH:MM:SS 형식
                        selection_dt = datetime.strptime(selection_date[:19], '%Y-%m-%d %H:%M:%S')
                    elif len(selection_date) >= 16:  # YYYY-MM-DD HH:MM 형식
                        selection_dt = datetime.strptime(selection_date[:16], '%Y-%m-%d %H:%M')
                    else:  # 날짜만
                        selection_dt = datetime.strptime(selection_date[:10], '%Y-%m-%d')
                    
                    # 신호 발생 시간이 selection_date 이후인지 확인
                    if signal_completion_time < selection_dt:
                        if logger:
                            logger.debug(f"⚠️ [{signal_completion_time.strftime('%H:%M')}] selection_date({selection_dt.strftime('%H:%M')}) 이전 신호로 건너뜀")
                        if stock_code == "308080" and logger:
                            logger.info(f"🚫 [308080] 차단: selection_date 이전 신호")
                        continue  # selection_date 이전 신호는 무시
                except Exception as e:
                    if logger:
                        logger.warning(f"selection_date 파싱 실패: {e}")
            
            # ==================== 동일 캔들 중복 신호 차단 (실시간과 동일) ====================
            # 3분 단위로 정규화하여 정확한 캔들 시점 비교
            minute_normalized = (signal_datetime.minute // 3) * 3
            normalized_signal_time = signal_datetime.replace(minute=minute_normalized, second=0, microsecond=0)
            
            if last_signal_candle_time and last_signal_candle_time == normalized_signal_time:
                if logger:
                    logger.debug(f"⚠️ [{signal_completion_time.strftime('%H:%M')}] 동일 캔들 중복신호 차단 ({normalized_signal_time.strftime('%H:%M')})")
                if stock_code == "308080" and logger:
                    logger.info(f"🚫 [308080] 차단: 동일 캔들 중복신호 (last={last_signal_candle_time.strftime('%H:%M') if last_signal_candle_time else 'None'})")
                continue  # 동일한 캔들에서 발생한 신호는 무시
            
            # ==================== 🆕 25분 매수 쿨다운 체크 ====================
            if stock_code in stock_cooldown_end:
                if signal_completion_time < stock_cooldown_end[stock_code]:
                    remaining_minutes = (stock_cooldown_end[stock_code] - signal_completion_time).total_seconds() / 60
                    if logger:
                        logger.info(f"⚠️ [{signal_completion_time.strftime('%H:%M')}] 매수 쿨다운 활성화 (남은 시간: {remaining_minutes:.0f}분)")
                    if stock_code == "308080" and logger:
                        logger.info(f"🚫 [308080] 차단: 쿨다운 (종료시간: {stock_cooldown_end[stock_code].strftime('%H:%M')}, 남은시간: {remaining_minutes:.0f}분)")
                    continue

            # ==================== 실시간과 동일: 포지션 보유 중이면 매수 금지 ====================
            if current_position is not None:
                # 현재 신호 시간이 포지션 매도 시간 이전인지 확인 (매도 전이면 매수 불가)
                if signal_completion_time < current_position['sell_time']:
                    if logger:
                        logger.debug(f"⚠️ [{signal_completion_time.strftime('%H:%M')}] 포지션 보유 중(매도예정: {current_position['sell_time'].strftime('%H:%M')})으로 매수 건너뜀")
                    if stock_code == "308080" and logger:
                        logger.info(f"🚫 [308080] 차단: 포지션 보유 중 (매도예정: {current_position['sell_time'].strftime('%H:%M')})")
                    continue  # 포지션 보유 중이므로 매수 불가
                else:
                    # 매도 완료 후 새로운 매수 가능 (쿨다운 제거)
                    if logger:
                        logger.debug(f"✅ [{signal_completion_time.strftime('%H:%M')}] 매도 완료, 새 매수 가능")
                    current_position = None
            
            # ==================== 쿨다운 체크 ====================
            if stock_code in stock_cooldown_end:
                cooldown_end_time = stock_cooldown_end[stock_code]
                if signal_completion_time < cooldown_end_time:
                    remaining_minutes = int((cooldown_end_time - signal_completion_time).total_seconds() / 60)
                    if logger:
                        logger.debug(f"🚫 [{signal_completion_time.strftime('%H:%M')}] {stock_code} 쿨다운 중: {remaining_minutes}분 남음")
                    continue  # 쿨다운 중이므로 매수 신호 건너뜀
            
            # ==================== 매수 중단 시간 이후 매수 금지 체크 (동적 시간 적용) ====================
            from config.market_hours import MarketHours
            market_hours = MarketHours.get_market_hours('KRX', signal_completion_time)
            buy_cutoff_hour = market_hours['buy_cutoff_hour']

            signal_hour = signal_completion_time.hour
            signal_minute = signal_completion_time.minute

            # 매수 중단 시간부터 매수 금지 (신호 표시는 유지)
            if signal_hour >= buy_cutoff_hour:
                if logger:
                    logger.debug(f"[{signal_completion_time.strftime('%H:%M')}] {buy_cutoff_hour}시 이후 매수금지")
                if stock_code == "308080" and logger:
                    logger.info(f"🚫 [308080] 차단: 매수 중단 시간 이후 ({buy_cutoff_hour}시)")
                continue  # 매수 중단 시간 이후 매수 신호 건너뜀
            
            # ==================== 실시간과 완전 동일한 매수 로직 ====================
            
            # 🔧 동적 손익비 체크 (플래그가 true이고 패턴 정보가 있으면 동적 손익비 사용)
            if hasattr(_trading_config.risk_management, 'use_dynamic_profit_loss') and _trading_config.risk_management.use_dynamic_profit_loss:
                # debug_info에서 패턴 추출 시도
                from config.dynamic_profit_loss_config import DynamicProfitLossConfig

                debug_info = signal.get('debug_info')
                if debug_info:
                    # debug_info에서 패턴 분류 추출
                    support_volume, decline_volume = DynamicProfitLossConfig.extract_pattern_from_debug_info(debug_info)

                    if support_volume and decline_volume:
                        # 패턴 기반 동적 손익비 적용
                        ratio = DynamicProfitLossConfig.get_ratio_by_pattern(support_volume, decline_volume)
                        target_profit_rate = ratio['take_profit'] / 100.0
                        stop_loss_rate = abs(ratio['stop_loss']) / 100.0

                        if logger:
                            logger.info(f"🔧 [{stock_code}] 동적 손익비: {support_volume}+{decline_volume}, "
                                       f"손절 {ratio['stop_loss']:.1f}% / 익절 {ratio['take_profit']:.1f}%")
                        else:
                            print(f"🔧 [{stock_code}] 동적 손익비: {support_volume}+{decline_volume}, "
                                f"손절 {ratio['stop_loss']:.1f}% / 익절 {ratio['take_profit']:.1f}%")
                    else:
                        # 패턴 정보 없으면 기본값
                        target_profit_rate = PROFIT_TAKE_RATE / 100.0
                        stop_loss_rate = STOP_LOSS_RATE / 100.0
                else:
                    # debug_info 없으면 기본값
                    target_profit_rate = PROFIT_TAKE_RATE / 100.0
                    stop_loss_rate = STOP_LOSS_RATE / 100.0
            else:
                # 플래그가 false이거나 없으면 기본값 사용
                target_profit_rate = PROFIT_TAKE_RATE / 100.0  # % -> 소수점 변환
                stop_loss_rate = STOP_LOSS_RATE / 100.0        # % -> 소수점 변환
            
            # 실시간과 동일한 3/5가 및 진입저가 사용
            three_fifths_price = float(str(signal.get('buy_price', 0)).replace(',', ''))  # 이미 계산된 3/5가 사용 (float 변환, 천단위구분자 제거)
            entry_low = float(str(signal.get('entry_low', 0)).replace(',', ''))  # 이미 계산된 진입저가 사용 (float 변환, 천단위구분자 제거)
            
            if three_fifths_price <= 0:
                if logger:
                    logger.warning(f"⚠️ [{stock_code}] 3/5가 정보 없음, 거래 건너뜀")
                if stock_code == "308080" and logger:
                    logger.info(f"🚫 [308080] 차단: 3/5가 정보 없음")
                continue
            
            # ==================== 🆕 일봉 기반 패턴 필터 적용 (시뮬레이션) ====================
            if daily_filter_enabled and daily_pattern_filter:
                try:
                    signal_date = signal_completion_time.strftime("%Y%m%d")
                    signal_time = signal_completion_time.strftime("%H:%M")
                    
                    filter_result = daily_pattern_filter.apply_filter(
                        stock_code, signal_date, signal_time
                    )
                    
                    if not filter_result.passed:
                        if logger:
                            logger.debug(f"🚫 [{signal_completion_time.strftime('%H:%M')}] {stock_code} 일봉 필터 차단: {filter_result.reason}")
                        if stock_code == "308080" and logger:
                            logger.info(f"🚫 [308080] 차단: 일봉 필터 ({filter_result.reason})")
                        continue  # 일봉 필터에 걸리면 거래 건너뜀
                    else:
                        if logger:
                            logger.debug(f"✅ [{signal_completion_time.strftime('%H:%M')}] {stock_code} 일봉 필터 통과: {filter_result.reason} (점수: {filter_result.score:.2f})")
                            
                except Exception as e:
                    if logger:
                        logger.warning(f"⚠️ [{stock_code}] 일봉 필터 적용 실패: {e}")
                    # 필터 오류 시에도 거래 진행 (안전장치)

            # ==================== 🆕 ML 필터 실시간 적용 ====================
            # 실전과 동일하게 패턴 신호 발생 시점에 즉시 ML 필터 적용
            # ML 필터에서 차단되면 쿨다운을 설정하지 않고 다음 신호로 넘어감
            if ml_filter_enabled and ml_model is not None and ml_feature_names is not None:
                try:
                    # 패턴 데이터 캐시에서 해당 신호의 패턴 찾기
                    signal_time_key = signal_completion_time.strftime('%H:%M')
                    pattern_data = None

                    if pattern_data_cache:
                        # 정확히 일치하는 시간 또는 ±3분 이내의 패턴 찾기
                        for pattern_key, pdata in pattern_data_cache.items():
                            if stock_code in pattern_key:
                                pattern_signal_time = pdata.get('signal_time', '')
                                if pattern_signal_time:
                                    try:
                                        pst = datetime.strptime(pattern_signal_time, '%Y-%m-%d %H:%M:%S')
                                        # signal_completion_time과 3분 이내 매칭
                                        time_diff = abs((pst - signal_completion_time).total_seconds())
                                        if time_diff <= 180:  # 3분 이내
                                            pattern_data = pdata
                                            break
                                    except:
                                        pass

                    if pattern_data:
                        # apply_ml_filter.py의 extract_features_from_pattern 함수 사용
                        from apply_ml_filter import extract_features_from_pattern, predict_win_probability

                        win_prob, status = predict_win_probability(
                            ml_model, ml_feature_names, signal, pattern_data
                        )

                        if win_prob < ml_threshold:
                            if logger:
                                logger.info(f"🤖 [{signal_completion_time.strftime('%H:%M')}] {stock_code} ML 필터 차단: {win_prob:.1%} < {ml_threshold:.1%}")
                            # ML 필터에서 차단 - 쿨다운 설정하지 않고 다음 신호로
                            continue
                        else:
                            if logger:
                                logger.debug(f"✅ [{signal_completion_time.strftime('%H:%M')}] {stock_code} ML 필터 통과: {win_prob:.1%}")
                    else:
                        if logger:
                            logger.debug(f"⚠️ [{signal_completion_time.strftime('%H:%M')}] {stock_code} ML 필터용 패턴 데이터 없음 - 거래 진행")

                except Exception as e:
                    if logger:
                        logger.warning(f"⚠️ [{stock_code}] ML 필터 적용 실패: {e}")
                    # ML 필터 오류 시에도 거래 진행 (안전장치)

            # ==================== 🆕 고급 필터 (승률 개선 필터) 적용 ====================
            if advanced_filter_enabled and advanced_filter_manager is not None:
                try:
                    # 패턴 데이터에서 필터 입력 추출
                    signal_time_key = signal_completion_time.strftime('%H:%M')
                    adv_pattern_data = None

                    if pattern_data_cache:
                        for pattern_key, pdata in pattern_data_cache.items():
                            if stock_code in pattern_key:
                                pattern_signal_time = pdata.get('signal_time', '')
                                if pattern_signal_time:
                                    try:
                                        pst = datetime.strptime(pattern_signal_time, '%Y-%m-%d %H:%M:%S')
                                        time_diff = abs((pst - signal_completion_time).total_seconds())
                                        if time_diff <= 180:
                                            adv_pattern_data = pdata
                                            break
                                    except:
                                        pass

                    # 필터 입력 데이터 추출 (3분봉 사용 - 실시간과 동일)
                    ohlcv_sequence = []
                    rsi = None
                    volume_ma_ratio = None

                    # df_3min에서 직접 3분봉 OHLCV 추출
                    signal_index = signal['index']
                    start_idx = max(0, signal_index - 4)  # 최근 5개 봉 (돌파봉 포함)
                    end_idx = signal_index + 1

                    if end_idx <= len(df_3min):
                        recent_candles = df_3min.iloc[start_idx:end_idx]
                        for _, row in recent_candles.iterrows():
                            ohlcv_sequence.append({
                                'open': float(row.get('open', 0)),
                                'high': float(row.get('high', 0)),
                                'low': float(row.get('low', 0)),
                                'close': float(row.get('close', 0)),
                                'volume': float(row.get('volume', 0))
                            })

                    # RSI와 volume_ma_ratio, pattern_stages는 pattern_data에서 가져옴
                    pattern_stages = None
                    if adv_pattern_data:
                        signal_snapshot = adv_pattern_data.get('signal_snapshot', {})
                        tech = signal_snapshot.get('technical_indicators_3min', {})
                        rsi = tech.get('rsi_14')
                        volume_ma_ratio = tech.get('volume_vs_ma_ratio')
                        pattern_stages = adv_pattern_data.get('pattern_stages')

                    # 거래일 추출 (일봉 필터용)
                    trade_date = signal_completion_time.strftime('%Y%m%d') if signal_completion_time else None

                    # 고급 필터 체크
                    adv_result = advanced_filter_manager.check_signal(
                        ohlcv_sequence=ohlcv_sequence,
                        rsi=rsi,
                        stock_code=stock_code,
                        signal_time=signal_completion_time,
                        volume_ma_ratio=volume_ma_ratio,
                        pattern_stages=pattern_stages,
                        trade_date=trade_date
                    )

                    if not adv_result.passed:
                        if logger:
                            logger.info(f"🔰 [{signal_completion_time.strftime('%H:%M')}] {stock_code} 고급 필터 차단: {adv_result.blocked_by} - {adv_result.blocked_reason}")
                        continue  # 고급 필터에서 차단되면 다음 신호로

                except Exception as e:
                    if logger:
                        logger.warning(f"⚠️ [{stock_code}] 고급 필터 적용 실패: {e}")
                    # 고급 필터 오류 시에도 거래 진행 (안전장치)

            # ==================== 🆕 돌파봉 4/5 가격 조건 체크 ====================
            
            # 돌파봉이 확정된 후, 다음 2개의 3분봉에서 4/5가에 도달하는지 확인
            signal_index = signal['index']
            next_2_candles_start = signal_index + 1  # 돌파봉 다음 봉부터
            next_2_candles_end = signal_index + 3    # 돌파봉 + 다음 2개 봉
            
            # 4/5가 도달 여부 확인
            price_reached = False
            
            if logger:
                logger.debug(f"🔍 [{stock_code}] 4/5가 체크: 돌파봉인덱스={signal_index}, 4/5가={three_fifths_price:,.0f}원, "
                           f"다음2봉범위={next_2_candles_start}~{next_2_candles_end-1}, 전체데이터길이={len(df_3min)}")
            
            # 다음 2개 3분봉 데이터가 있는지 확인
            if next_2_candles_end <= len(df_3min):
                next_2_candles = df_3min.iloc[next_2_candles_start:next_2_candles_end]
                
                if logger:
                    logger.debug(f"🔍 [{stock_code}] 다음 2개 3분봉 데이터: {len(next_2_candles)}개")
                    for idx, (_, candle) in enumerate(next_2_candles.iterrows()):
                        actual_idx = next_2_candles_start + idx
                        logger.debug(f"  봉{idx+1}(인덱스{actual_idx}): {candle['datetime'].strftime('%H:%M')} "
                                   f"저가={candle['low']:,.0f}원, 4/5가={three_fifths_price:,.0f}원, "
                                   f"도달여부={candle['low'] <= three_fifths_price}")
                
                # 다음 2개 3분봉 중 하나라도 4/5 가격 이하로 떨어지는지 확인
                for idx, (_, candle) in enumerate(next_2_candles.iterrows()):
                    if candle['low'] <= three_fifths_price:
                        price_reached = True
                        actual_idx = next_2_candles_start + idx
                        if logger:
                            logger.debug(f"✅ [{stock_code}] 4/5가 도달: {candle['datetime'].strftime('%H:%M')} "
                                       f"저가 {candle['low']:,.0f}원 ≤ 4/5가 {three_fifths_price:,.0f}원 (인덱스{actual_idx})")
                        break
            else:
                # 데이터가 부족한 경우도 4/5가 미도달로 처리
                if logger:
                    logger.debug(f"⚠️ [{stock_code}] 다음 2개 3분봉 데이터 부족 - 4/5가 미도달로 처리")
            
            # 4/5가 도달 조건을 제거하고 5분 타임아웃 조건으로 통합
            
            # ==================== 매수 체결 가정 ====================
            
            # 3/5 가격 조건을 통과한 경우에만 매수 실행
            signal_time_start = signal_completion_time  # 신호 발생 시점에 매수
            
            # 디버그: 시간 정보 출력
            if logger:
                logger.debug(f"🕐 신호 라벨: {signal_datetime.strftime('%H:%M')}, "
                           f"신호 발생: {signal_completion_time.strftime('%H:%M')}, "
                           f"매수가: {three_fifths_price:,.0f}원")
            
            # 3/5 가격 조건 통과 시 매수 성공으로 가정
            buy_executed = True
            buy_executed_price = three_fifths_price
            actual_execution_time = signal_completion_time
            
            # 매수 성공 시 신호 캔들 시점 저장 (중복 신호 방지)
            last_signal_candle_time = normalized_signal_time
            
            # 🆕 실시간과 동일: 5분 타임아웃 적용
            signal_time_start = signal_completion_time
            signal_time_end = signal_completion_time + timedelta(minutes=5)  # 5분 타임아웃 (실시간과 동일)
            
            check_candles = df_1min[
                (df_1min['datetime'] >= signal_time_start) & 
                (df_1min['datetime'] < signal_time_end)
            ].copy()
            
            if check_candles.empty:
                if logger:
                    logger.debug(f"⚠️ [{stock_code}] 체결 검증용 1분봉 데이터 없음, 거래 건너뜀")
                if stock_code == "308080" and logger:
                    logger.info(f"🚫 [308080] 차단: 체결 검증용 1분봉 데이터 없음")
                continue
            
            # 5분 내에 3/5가 이하로 떨어지는 시점 찾기 (체결 가능성만 확인)
            buy_executed = False
            for _, candle in check_candles.iterrows():
                # 해당 1분봉의 저가가 3/5가 이하면 체결 가능
                if candle['low'] <= three_fifths_price:
                    buy_executed = True
                    actual_execution_time = candle['datetime']
                    # 체결가는 3/5가로 고정 (지정가 주문과 동일)
                    break
            
            if not buy_executed:
                # 5분 내에 3/5가 이하로 떨어지지 않음 → 매수 미체결
                if logger:
                    logger.debug(f"💸 [{stock_code}] 매수 미체결: 5분 내 3/5가({three_fifths_price:,.0f}원) 도달 실패")
                if stock_code == "308080" and logger:
                    logger.info(f"❌ [308080] 미체결: 5분 내 3/5가({three_fifths_price:,.0f}원) 도달 실패")

                # 미체결 신호도 기록에 추가
                trades.append({
                    'buy_time': signal_completion_time.strftime('%H:%M'),
                    'buy_price': 0,
                    'sell_time': '',
                    'sell_price': 0,
                    'profit_rate': 0.0,
                    'status': 'unexecuted',
                    'signal_type': signal.get('signal_type', ''),
                    'confidence': signal.get('confidence', 0),
                    'target_profit': target_profit_rate,
                    'max_profit_rate': 0.0,
                    'max_loss_rate': 0.0,
                    'duration_minutes': 0,
                    'reason': f'미체결: 5분 내 3/5가({three_fifths_price:,.0f}원) 도달 실패'
                })
                continue
            
            # 체결 성공 - 매수 시간은 실제 체결 시점으로 기록
            buy_time = actual_execution_time  # 실제 체결 시점 (selection_date 이후)
            buy_price = buy_executed_price
            if logger:
                logger.debug(f"💰 [{stock_code}] 매수 체결: {buy_price:,.0f}원 @ {buy_time.strftime('%H:%M:%S')} (실제 체결: {actual_execution_time.strftime('%H:%M:%S')})")
            if stock_code == "308080" and logger:
                logger.info(f"✅ [308080] 매수 체결 성공: {buy_price:,.0f}원 @ {buy_time.strftime('%H:%M:%S')}")

            # 🆕 쿨다운 설정 (매수 성공 시)
            cooldown_end_time = actual_execution_time + timedelta(minutes=buy_cooldown_minutes)
            stock_cooldown_end[stock_code] = cooldown_end_time
            if logger:
                logger.debug(f"⏰ [{stock_code}] {buy_cooldown_minutes}분 쿨다운 설정: {cooldown_end_time.strftime('%H:%M')}까지")
            
            # 진입 저가 추적 (실시간과 동일)
            entry_low = float(str(signal.get('entry_low', 0)).replace(',', ''))
            if entry_low <= 0:
                entry_low = float(str(signal.get('low', 0)).replace(',', ''))  # 3분봉 저가를 대체 (float 변환, 천단위구분자 제거)
            
            # 매수 후부터 장 마감까지의 1분봉 데이터로 매도 시뮬레이션
            remaining_data = df_1min[df_1min['datetime'] > buy_time].copy()
            
            if remaining_data.empty:
                # 매도 기회 없음 - 미결제
                trades.append({
                    'buy_time': buy_time.strftime('%H:%M'),
                    'buy_price': buy_price,
                    'sell_time': '',
                    'sell_price': 0,
                    'profit_rate': 0.0,
                    'status': 'open',
                    'signal_type': signal.get('signal_type', ''),
                    'confidence': signal.get('confidence', 0),
                    'target_profit': target_profit_rate,
                    'max_profit_rate': 0.0,
                    'max_loss_rate': 0.0,
                    'duration_minutes': 0,
                    'reason': '거래시간 종료'
                })
                continue
            
            # 매도 조건 체크 (실시간 매매와 동일한 로직)
            sell_time = None
            sell_price = 0
            max_profit_rate = 0.0
            max_loss_rate = 0.0
            sell_reason = ""
            
            for i, row in remaining_data.iterrows():
                candle_time = row['datetime']
                candle_high = row['high']
                candle_low = row['low'] 
                candle_close = row['close']
                
                # ==================== 장마감 시간 매도 (최우선) - 동적 시간 적용 ====================
                from config.market_hours import MarketHours
                market_hours = MarketHours.get_market_hours('KRX', candle_time)
                eod_hour = market_hours['eod_liquidation_hour']
                eod_minute = market_hours['eod_liquidation_minute']

                if candle_time.hour >= eod_hour and candle_time.minute >= eod_minute:
                    sell_time = candle_time
                    sell_price = candle_close  # 장마감 종가로 매도
                    sell_reason = f"market_close_{eod_hour}h"
                    if logger:
                        logger.debug(f"[{stock_code}] {eod_hour}:{eod_minute:02d} 장마감 매도: {sell_price:,.0f}원")
                    break
                
                # 최대/최소 수익률 추적 (종가 기준)
                close_profit_rate = ((candle_close - buy_price) / buy_price) * 100
                high_profit_rate = ((candle_high - buy_price) / buy_price) * 100
                low_profit_rate = ((candle_low - buy_price) / buy_price) * 100
                
                if high_profit_rate > max_profit_rate:
                    max_profit_rate = high_profit_rate
                if low_profit_rate < max_loss_rate:
                    max_loss_rate = low_profit_rate
                
                # ==================== 1분봉 고가/저가에서 매도 조건 체크 ====================
                
                # 익절 목표가
                profit_target_price = buy_price * (1.0 + target_profit_rate)
                # 손절 목표가  
                stop_loss_target_price = buy_price * (1.0 - stop_loss_rate)
                # 진입저가 -0.2% 기준가
                entry_low_break_price = entry_low * 0.998 if entry_low > 0 else 0
                
                # 1. 신호강도별 익절 - 1분봉 고가가 익절 목표가 터치 시
                if candle_high >= profit_target_price:
                    sell_time = row['datetime']
                    sell_price = profit_target_price  # 목표가로 매도
                    sell_reason = f"profit_{target_profit_rate*100:.1f}pct"
                    break
                    
                # 2. 신호강도별 손절 - 1분봉 저가가 손절 목표가 터치 시
                if candle_low <= stop_loss_target_price:
                    sell_time = row['datetime']
                    sell_price = stop_loss_target_price  # 손절가로 매도
                    sell_reason = f"stop_loss_{stop_loss_rate*100:.1f}pct"
                    break
                
                # 3. 진입저가 -0.2% 이탈 - 1분봉 저가가 기준가 터치 시 (주석처리: 손익비로만 판단)
                # if entry_low_break_price > 0 and candle_low <= entry_low_break_price:
                #     sell_time = row['datetime']
                #     sell_price = entry_low_break_price  # 기준가로 매도
                #     sell_reason = f"entry_low_break"
                #     break
                
                # 4. 3분봉 기반 기술적 분석 매도 신호 (3분봉 완성 시점에만 체크 - 실시간과 동일)
                current_time = row['datetime']
                
                # 3분봉 완성 시점에만 기술적 분석 실행 (실시간과 동일)
                if current_time.minute % 3 == 0:  # 3분 단위 시점에만 실행
                    # 해당 시점까지의 1분봉 데이터를 3분봉으로 변환
                    data_until_now = df_1min[df_1min['datetime'] <= current_time]
                    if len(data_until_now) >= 15:  # 최소 15개 1분봉 필요
                        try:
                            from core.timeframe_converter import TimeFrameConverter
                            data_3min_current = TimeFrameConverter.convert_to_3min_data(data_until_now)
                            
                            if data_3min_current is not None and len(data_3min_current) >= 5:
                                # 3분봉 기반 매도 신호 계산
                                technical_sell, technical_reason = _check_technical_sell_signals(
                                    data_3min_current, entry_low
                                )
                                
                                if technical_sell:
                                    sell_time = row['datetime']
                                    # 기술적 분석 신호 시 종가로 매도 (실시간과 동일)
                                    sell_price = candle_close
                                    sell_reason = technical_reason
                                    break
                                    
                        except Exception as e:
                            if logger:
                                logger.debug(f"기술적 분석 매도 신호 체크 오류: {e}")
                            continue
            
            # 거래 결과 기록 및 포지션 업데이트
            if sell_time is not None:
                duration_minutes = int((sell_time - buy_time).total_seconds() / 60)
                profit_rate = ((sell_price - buy_price) / buy_price) * 100

                # 📊 패턴 데이터 매매 결과 업데이트 (시뮬레이션)
                # ENABLE_PATTERN_LOGGING 환경 변수가 설정된 경우에만 업데이트
                if os.environ.get('ENABLE_PATTERN_LOGGING') == 'true':
                    try:
                        from core.pattern_data_logger import PatternDataLogger
                        pattern_logger = PatternDataLogger(simulation_date=simulation_date)

                        if signal.get('pattern_id'):
                            # 🆕 매수~매도 구간 상세 데이터 준비
                            trade_data = {
                                'buy_time': buy_time,
                                'sell_time': sell_time,
                                'buy_price': buy_price,
                                'sell_price': sell_price,
                                'max_profit_rate': max_profit_rate,
                                'max_loss_rate': max_loss_rate,
                                'duration_minutes': duration_minutes,
                                'df_1min_during_trade': df_1min  # 전체 1분봉 데이터 전달
                            }

                            pattern_logger.update_trade_result(
                                pattern_id=signal['pattern_id'],
                                trade_executed=True,
                                profit_rate=profit_rate,
                                sell_reason=sell_reason,
                                trade_data=trade_data  # 🆕 상세 데이터 전달
                            )
                    except Exception as log_err:
                        if logger:
                            logger.debug(f"⚠️ 패턴 매매 결과 업데이트 실패: {log_err}")

                # ==================== 포지션 업데이트: 매도 완료 ====================
                current_position = {
                    'buy_time': buy_time,
                    'sell_time': sell_time,
                    'status': 'completed'
                }
                
                # 매도 완료 시 신호 시점 초기화 (새로운 매수 신호 허용)
                # 단, 쿨다운 로직이 있으므로 즉시 재매수되지는 않음
                last_signal_candle_time = None

                # 🆕 매수 완료 시 25분 쿨다운 설정
                stock_cooldown_end[stock_code] = buy_time + timedelta(minutes=buy_cooldown_minutes)
                if logger:
                    logger.info(f"🕰️ [{stock_code}] 매수 쿨다운 설정: {buy_time.strftime('%H:%M')} + {buy_cooldown_minutes}분 = {stock_cooldown_end[stock_code].strftime('%H:%M')}")
                
                trades.append({
                    'stock_code': stock_code,
                    'buy_time': buy_time.strftime('%H:%M'),
                    'buy_price': buy_price,
                    'sell_time': sell_time.strftime('%H:%M'),
                    'sell_price': sell_price,
                    'profit_rate': profit_rate,
                    'status': 'completed',
                    'signal_type': signal.get('signal_type', ''),
                    'confidence': signal.get('confidence', 0),
                    'target_profit': target_profit_rate,
                    'max_profit_rate': max_profit_rate,
                    'max_loss_rate': max_loss_rate,
                    'duration_minutes': duration_minutes,
                    'reason': sell_reason
                })
            else:
                # ==================== 포지션 업데이트: 미결제 (장 마감까지 보유) ====================
                from utils.korean_time import now_kst
                from config.market_hours import MarketHours

                # 장마감 시간 동적으로 가져오기 (특수일 대응)
                market_hours = MarketHours.get_market_hours('KRX', buy_time)
                market_close_time = market_hours['market_close']
                eod_time = buy_time.replace(hour=market_close_time.hour, minute=market_close_time.minute, second=0, microsecond=0)
                
                current_position = {
                    'buy_time': buy_time,
                    'sell_time': eod_time,  # 장 마감 시간으로 설정하여 이후 매수 허용
                    'status': 'eod_open'
                }

                # 🆕 미결제 포지션에서도 매수 완료 시 25분 쿨다운 설정
                stock_cooldown_end[stock_code] = buy_time + timedelta(minutes=buy_cooldown_minutes)
                if logger:
                    logger.info(f"🕰️ [{stock_code}] 매수 쿨다운 설정 (미결제): {buy_time.strftime('%H:%M')} + {buy_cooldown_minutes}분 = {stock_cooldown_end[stock_code].strftime('%H:%M')}")
                
                trades.append({
                    'buy_time': buy_time.strftime('%H:%M'),
                    'buy_price': buy_price,
                    'sell_time': '',
                    'sell_price': 0,
                    'profit_rate': 0.0,
                    'status': 'open',
                    'signal_type': signal.get('signal_type', ''),
                    'confidence': signal.get('confidence', 0),
                    'target_profit': target_profit_rate,
                    'max_profit_rate': max_profit_rate,
                    'max_loss_rate': max_loss_rate,
                    'duration_minutes': 0,
                    'reason': '거래시간 종료'
                })
        
        if logger:
            completed_trades = [t for t in trades if t['status'] == 'completed']
            successful_trades = [t for t in completed_trades if t['profit_rate'] > 0]

            # 🆕 매수 중단 시간 이전 매수 종목들 필터링 (동적 시간 적용)
            from config.market_hours import MarketHours
            if simulation_date:
                market_hours = MarketHours.get_market_hours('KRX', datetime.strptime(simulation_date, '%Y%m%d'))
            else:
                # simulation_date가 없으면 오늘 날짜 사용
                market_hours = MarketHours.get_market_hours('KRX', datetime.now())
            buy_cutoff_hour = market_hours.get('buy_cutoff_hour', 12)

            morning_trades = []
            for trade in completed_trades:
                try:
                    buy_hour = int(trade['buy_time'].split(':')[0])
                    if buy_hour < buy_cutoff_hour:
                        morning_trades.append(trade)
                except (ValueError, IndexError):
                    continue

            morning_successful = [t for t in morning_trades if t['profit_rate'] > 0]

            logger.info(f"📈 [{stock_code}] 거래 시뮬레이션 완료:")
            logger.info(f"   전체 거래: {len(trades)}건")
            logger.info(f"   완료 거래: {len(completed_trades)}건")
            logger.info(f"   성공 거래: {len(successful_trades)}건")
            logger.info(f"   매수 못한 기회: {len(missed_opportunities)}건")

            # 🆕 12시 이전 매수 종목 승패 표시
            if morning_trades:
                morning_win_rate = len(morning_successful) / len(morning_trades) * 100
                morning_avg_profit = sum(t['profit_rate'] for t in morning_trades) / len(morning_trades)

                logger.info(f"🌅 {buy_cutoff_hour}시 이전 매수 거래:")
                logger.info(f"   오전 거래 수: {len(morning_trades)}건")
                logger.info(f"   오전 성공: {len(morning_successful)}건")
                logger.info(f"   오전 실패: {len(morning_trades) - len(morning_successful)}건")
                logger.info(f"   오전 승률: {morning_win_rate:.1f}%")
                logger.info(f"   오전 평균 수익률: {morning_avg_profit:+.2f}%")

                # 개별 거래 상세 표시
                for trade in morning_trades:
                    status_icon = "🟢" if trade['profit_rate'] > 0 else "🔴"
                    logger.info(f"   {status_icon} {trade['buy_time']} 매수 → {trade['profit_rate']:+.2f}%")

            if completed_trades:
                avg_profit = sum(t['profit_rate'] for t in completed_trades) / len(completed_trades)
                logger.info(f"   평균 수익률: {avg_profit:.2f}%")

            if missed_opportunities:
                virtual_profits = [m['virtual_profit_rate'] for m in missed_opportunities if m['virtual_profit_rate'] is not None]
                if virtual_profits:
                    avg_virtual_profit = sum(virtual_profits) / len(virtual_profits)
                    logger.info(f"   매수 못한 기회 평균 가상 수익률: {avg_virtual_profit:.2f}%")
        
        # trades와 missed_opportunities를 함께 반환
        return {
            'trades': trades,
            'missed_opportunities': missed_opportunities
        }
    
    except Exception as e:
        if logger:
            logger.error(f"거래 시뮬레이션 실패 [{stock_code}]: {e}")
        return {'trades': [], 'missed_opportunities': []}


def _calculate_virtual_profit_rate(df_1min: pd.DataFrame, signal_time, target_price: float, entry_low: float) -> float:
    """매수 성공했다면 결과가 어땠을지 가상 수익률 계산"""
    try:
        if df_1min is None or df_1min.empty:
            return 0.0
        
        # 신호 시간 이후의 1분봉 데이터 필터링
        signal_datetime = pd.to_datetime(signal_time)
        future_data = df_1min[df_1min['datetime'] >= signal_datetime].copy()
        
        if future_data.empty:
            return 0.0
        
        # 매수가를 target_price로 가정
        buy_price = target_price
        
        # 손절가 설정 (entry_low 기준)
        stop_loss_price = entry_low * 0.98  # 2% 추가 손절
        
        # 목표가 설정 (매수가 대비 3% 수익)
        target_profit_price = buy_price * 1.03
        
        # 최대 보유 시간 (2시간 = 120분)
        max_hold_minutes = 120
        end_time = signal_datetime + pd.Timedelta(minutes=max_hold_minutes)
        future_data = future_data[future_data['datetime'] <= end_time]
        
        if future_data.empty:
            return 0.0
        
        # 각 1분봉에서 매도 조건 확인
        for _, candle in future_data.iterrows():
            # 손절 조건 확인
            if candle['low'] <= stop_loss_price:
                return (stop_loss_price / buy_price - 1) * 100
            
            # 목표가 도달 조건 확인
            if candle['high'] >= target_profit_price:
                return (target_profit_price / buy_price - 1) * 100
        
        # 2시간 후에도 조건 미달성 시 마지막 가격으로 계산
        last_price = future_data.iloc[-1]['close']
        return (last_price / buy_price - 1) * 100
        
    except Exception as e:
        return 0.0


def _check_technical_sell_signals(data_3min: pd.DataFrame, entry_low: float):
    """3분봉 기반 기술적 분석 매도 신호 체크 (실시간과 동일)"""
    try:
        from core.indicators.pullback_candle_pattern import PullbackCandlePattern
        
        # 매도 신호 계산
        sell_signals = PullbackCandlePattern.generate_sell_signals(
            data_3min,
            entry_low=entry_low if entry_low > 0 else None
        )
        
        if sell_signals is None or sell_signals.empty:
            return False, ""
        
        # 최신 봉의 매도 신호 체크
        latest_signals = sell_signals.iloc[-1]
        
        # 매도 조건 1: 이등분선 이탈 (0.2% 기준)
        if hasattr(latest_signals, 'sell_bisector_break') and bool(latest_signals.get('sell_bisector_break', False)):
            return True, "bisector_break"
        
        # 매도 조건 2: 지지 저점 이탈
        if hasattr(latest_signals, 'sell_support_break') and bool(latest_signals.get('sell_support_break', False)):
            return True, "support_break"
        
        # 매도 조건 3: 진입 양봉 저가 0.2% 이탈
        if hasattr(latest_signals, 'stop_entry_low_break') and bool(latest_signals.get('stop_entry_low_break', False)):
            return True, "entry_low_technical_break"
            
        return False, ""
        
    except Exception as e:
        return False, ""


def main():
    parser = argparse.ArgumentParser(description="눌림목(3분) 매수신호 재현 리포트")
    parser.add_argument("--date", required=True, help="대상 날짜 (YYYYMMDD) - candidate_stocks 테이블에서 해당 날짜의 종목 자동 조회")
    parser.add_argument("--codes", required=False, default=None, help="종목코드 콤마구분 예: 034230,078520 (생략 시 DB에서 자동 조회)")
    parser.add_argument("--times", required=False, default=None, help="종목별 확인시각 매핑 예: 034230=14:39;078520=11:33")
    parser.add_argument("--export", choices=["csv", "txt"], default=None, help="결과를 파일로 저장 (csv|txt)")
    parser.add_argument("--csv-path", default="signal_replay.csv", help="CSV 저장 경로 (기본: signal_replay.csv)")
    parser.add_argument("--txt-path", default="signal_replay.txt", help="TXT 저장 경로 (기본: signal_replay.txt)")
    parser.add_argument("--charts", action="store_true", help="3분봉 차트 생성 (거래량, 이등분선, 매수/매도 포인트 포함)")
    parser.add_argument("--use-dynamic-profit-loss", action="store_true", help="동적 손익비 모드 사용 (환경 변수 설정용)")
    parser.add_argument("--ml-filter", action="store_true", help="ML 필터 실시간 적용 (실전과 동일하게 신호 시점에 즉시 필터링)")
    parser.add_argument("--ml-model", default="ml_model.pkl", help="ML 모델 파일 경로 (기본: ml_model.pkl)")
    parser.add_argument("--ml-threshold", type=float, default=None, help="ML 필터 임계값 (기본: config/ml_settings.py의 ML_THRESHOLD)")
    parser.add_argument("--advanced-filter", action="store_true", help="고급 필터 적용 (승률 개선 필터: 연속양봉, 가격위치, 화요일제외 등)")

    args = parser.parse_args()

    # --use-dynamic-profit-loss 옵션이 있으면 환경 변수로 설정
    if args.use_dynamic_profit_loss:
        os.environ['USE_DYNAMIC_PROFIT_LOSS'] = 'true'

    def normalize_code(code: str) -> str:
        return str(code).strip().zfill(6)


    # 날짜는 필수 파라미터
    date_str: str = args.date.strip()
    
    # codes가 지정되지 않으면 candidate_stocks 테이블에서 조회
    stock_selection_map: Dict[str, str] = {}  # {종목코드: selection_date} 매핑
    if args.codes:
        codes_input = args.codes
        codes: List[str] = [normalize_code(c) for c in codes_input.split(",") if str(c).strip()]
        # 중복 제거(입력 순서 유지)
        codes = list(dict.fromkeys(codes))
        logger.info(f"📝 명시적으로 지정된 종목: {len(codes)}개")
        # 직접 지정된 종목의 경우에도 selection_date 정보 시도
        stock_selection_map = get_stocks_with_selection_date(date_str)
    else:
        # candidate_stocks 테이블에서 해당 날짜의 종목과 selection_date 조회
        stock_selection_map = get_stocks_with_selection_date(date_str)
        codes = list(stock_selection_map.keys())
        if not codes:
            logger.error(f"❌ {date_str} 날짜에 해당하는 candidate_stocks가 없습니다.")
            print(f"\n❌ {date_str} 날짜에 해당하는 candidate_stocks가 없습니다.")
            print("   --codes 파라미터로 직접 종목을 지정하거나, 해당 날짜에 종목 선정 작업을 먼저 실행하세요.")
            sys.exit(1)
    
    times_input = args.times or ""
    raw_times_map: Dict[str, List[str]] = parse_times_mapping(times_input)
    # 키도 6자리로 정규화
    times_map: Dict[str, List[str]] = {normalize_code(k): v for k, v in raw_times_map.items()}

    # 코드 집합: codes + times에 언급된 종목들의 합집합(순서: codes → times)
    codes_union: List[str] = list(codes)
    for k in times_map.keys():
        if k not in codes_union:
            codes_union.append(k)
    # 누락된 종목 키에 대해 빈 리스트 보정
    for code in codes_union:
        if code not in times_map:
            times_map[code] = []

    logger.info(f"대상 날짜: {date_str}")
    logger.info(f"처리할 종목 수: {len(codes_union)}개")
    logger.info(f"손익 설정: 익절 +{PROFIT_TAKE_RATE}% / 손절 -{STOP_LOSS_RATE}%")

    if times_map:
        specified_count = sum(1 for times_list in times_map.values() if times_list)
        logger.info(f"특정 시각 지정된 종목: {specified_count}개")

    # 종목명 매핑 로드
    stock_names = load_stock_names()

    # API 매니저 초기화
    try:
        api_manager = KISAPIManager()
        if not api_manager.initialize():
            logger.error("❌ KIS API 설정이 누락되었습니다. config/config.yaml을 확인하세요.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ KIS API 매니저 초기화 실패: {e}")
        sys.exit(1)

    # ==================== 🆕 ML 필터 초기화 ====================
    ml_filter_enabled = args.ml_filter
    ml_model = None
    ml_feature_names = None
    ml_threshold = 0.5
    pattern_data_cache = {}  # {pattern_id: pattern_data}

    if ml_filter_enabled:
        logger.info(f"🤖 ML 필터 실시간 적용 모드 활성화")

        # ML 임계값 로드
        if args.ml_threshold is not None:
            ml_threshold = args.ml_threshold
        else:
            try:
                from config.ml_settings import MLSettings
                ml_threshold = MLSettings.ML_THRESHOLD
            except:
                ml_threshold = 0.5
        logger.info(f"   ML 임계값: {ml_threshold:.1%}")

        # ML 모델 로드
        try:
            from apply_ml_filter import load_ml_model
            ml_model, ml_feature_names = load_ml_model(args.ml_model)
            if ml_model is None:
                logger.warning(f"⚠️ ML 모델 로드 실패 - ML 필터 비활성화")
                ml_filter_enabled = False
        except Exception as e:
            logger.warning(f"⚠️ ML 모델 로드 실패: {e} - ML 필터 비활성화")
            ml_filter_enabled = False

        # 패턴 데이터 로드
        if ml_filter_enabled:
            try:
                import json
                pattern_log_file = Path(f"pattern_data_log/pattern_data_{date_str}.jsonl")
                if pattern_log_file.exists():
                    with open(pattern_log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip():
                                try:
                                    record = json.loads(line)
                                    pattern_id = record.get('pattern_id', '')
                                    if pattern_id:
                                        pattern_data_cache[pattern_id] = record
                                except:
                                    pass
                    logger.info(f"   패턴 데이터 로드: {len(pattern_data_cache)}개")
                else:
                    logger.warning(f"⚠️ 패턴 데이터 파일 없음: {pattern_log_file}")
            except Exception as e:
                logger.warning(f"⚠️ 패턴 데이터 로드 실패: {e}")

    # ==================== 🆕 고급 필터 초기화 ====================
    advanced_filter_enabled = args.advanced_filter
    advanced_filter_manager = None

    if advanced_filter_enabled:
        try:
            from core.indicators.advanced_filters import AdvancedFilterManager
            advanced_filter_manager = AdvancedFilterManager()
            active_filters = advanced_filter_manager.get_active_filters()
            logger.info(f"🔰 고급 필터 활성화: {', '.join(active_filters) if active_filters else '없음'}")
            logger.info(f"   {advanced_filter_manager.get_summary()}")
        except Exception as e:
            logger.warning(f"⚠️ 고급 필터 초기화 실패: {e} - 고급 필터 비활성화")
            advanced_filter_enabled = False

    # 병렬 처리를 위한 함수 정의
    def process_single_stock(stock_code: str) -> Tuple[str, List[Dict[str, object]], pd.DataFrame]:
        """단일 종목 처리 함수"""
        try:
            logger.info(f"🔄 [{stock_code}] 처리 시작...")

            # 데이터 조회 (파일 캐시 우선, 없으면 API 호출)
            from core.timeframe_converter import TimeFrameConverter
            from utils.korean_time import now_kst

            # 오늘 날짜인지 확인
            today_str = now_kst().strftime("%Y%m%d")

            df_1min = None

            # 과거 날짜인 경우 캐시 먼저 확인
            if date_str != today_str:
                # PG 캐시에서 먼저 시도
                from utils.data_cache import DataCache
                minute_cache = DataCache()
                cached_data = minute_cache.load_data(stock_code, date_str)

                if cached_data is not None:
                    try:

                        # 데이터 품질 검증: 동적 시장 시간대 포함 확인
                        if not cached_data.empty and 'datetime' in cached_data.columns:
                            cached_data['datetime'] = pd.to_datetime(cached_data['datetime'])

                            # 해당 날짜의 시장 거래시간 가져오기
                            from config.market_hours import MarketHours
                            target_date = datetime.strptime(date_str, '%Y%m%d')
                            market_hours = MarketHours.get_market_hours('KRX', target_date)
                            market_open_time = market_hours['market_open']
                            market_close_time = market_hours['market_close']

                            # 시간대 추출
                            times = cached_data['datetime'].dt.time

                            # 시장 시작 시간 이후 데이터 확인
                            has_morning = any(t >= market_open_time for t in times)
                            # 시장 마감 시간 이전 데이터 확인 (15:00 또는 16:00 체크)
                            check_time = time(market_close_time.hour - 1, 0)  # 마감 1시간 전 체크
                            has_afternoon = any(t >= check_time for t in times)

                            if has_morning and has_afternoon:
                                df_1min = cached_data
                                logger.info(f"💾 [{stock_code}] 캐시 데이터 사용 - {len(df_1min)}개 봉")
                            else:
                                logger.warning(f"⚠️  [{stock_code}] 캐시 데이터 불완전 ({market_open_time.strftime('%H:%M')}~{market_close_time.strftime('%H:%M')} 미포함), API 재조회")
                        else:
                            logger.warning(f"⚠️  [{stock_code}] 캐시 데이터 형식 오류, API 재조회")
                    except Exception as e:
                        logger.warning(f"⚠️  [{stock_code}] 캐시 로드 실패: {e}, API 재조회")
                        df_1min = None

            # 캐시가 없거나 오늘 날짜면 API 호출
            if df_1min is None:
                if date_str == today_str:
                    # 오늘 날짜면 실시간 데이터 사용
                    from api.kis_chart_api import get_full_trading_day_data
                    logger.info(f"📡 [{stock_code}] 실시간 API 호출 (오늘 날짜)")
                    df_1min = get_full_trading_day_data(stock_code, date_str)
                else:
                    # 과거 날짜는 DataProcessor 사용
                    logger.info(f"📡 [{stock_code}] API 호출 시작 (캐시 없음)")
                    dp = DataProcessor()
                    try:
                        # 새로운 이벤트 루프 생성하여 충돌 방지
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            df_1min = loop.run_until_complete(dp.get_historical_chart_data(stock_code, date_str))
                            logger.info(f"✅ [{stock_code}] API 데이터 수신 완료")

                            # API로 조회한 데이터를 PG에 캐시 저장
                            if df_1min is not None and not df_1min.empty:
                                minute_cache.save_data(stock_code, date_str, df_1min)

                                # 시간 범위 정보
                                time_info = ""
                                if 'time' in df_1min.columns:
                                    start_time = df_1min.iloc[0]['time']
                                    end_time = df_1min.iloc[-1]['time']
                                    time_info = f" ({start_time}~{end_time})"
                                elif 'datetime' in df_1min.columns:
                                    start_dt = df_1min.iloc[0]['datetime']
                                    end_dt = df_1min.iloc[-1]['datetime']
                                    if hasattr(start_dt, 'strftime') and hasattr(end_dt, 'strftime'):
                                        time_info = f" ({start_dt.strftime('%H%M%S')}~{end_dt.strftime('%H%M%S')})"

                                logger.info(f"💾 [{stock_code}] PG 캐시 저장 완료: {len(df_1min)}건{time_info}")
                        finally:
                            loop.close()
                    except Exception as e:
                        df_1min = None
                        logger.warning(f"⚠️  [{stock_code}] 비동기 데이터 조회 실패: {e}")
                        return stock_code, []
            
            if df_1min is None or df_1min.empty:
                logger.warning(f"⚠️  [{stock_code}] 1분봉 데이터 없음")
                return stock_code, []

            # 3분봉 변환
            df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)
            if df_3min is None or df_3min.empty:
                logger.warning(f"⚠️  [{stock_code}] 3분봉 변환 실패")
                return stock_code, []

            # 거래 시뮬레이션 실행 (🆕 ML 필터 + 고급 필터 매개변수 전달)
            selection_date = stock_selection_map.get(stock_code)
            simulation_result = simulate_trades(
                df_3min, df_1min,
                logger=logger,
                stock_code=stock_code,
                selection_date=selection_date,
                simulation_date=date_str,
                ml_filter_enabled=ml_filter_enabled,
                ml_model=ml_model,
                ml_feature_names=ml_feature_names,
                ml_threshold=ml_threshold,
                pattern_data_cache=pattern_data_cache,
                advanced_filter_enabled=advanced_filter_enabled,
                advanced_filter_manager=advanced_filter_manager
            )
            
            # 반환값 처리 (기존 호환성 유지)
            if isinstance(simulation_result, dict):
                trades = simulation_result.get('trades', [])
                missed_opportunities = simulation_result.get('missed_opportunities', [])
            else:
                # 기존 형식 (리스트)인 경우
                trades = simulation_result
                missed_opportunities = []
            
            # 차트 생성 (옵션)
            if args.charts and trades:
                try:
                    # 신호 계산 (차트용)
                    signals, _ = calculate_trading_signals_once(df_3min, logger=logger, stock_code=stock_code)
                    generate_chart_for_stock(stock_code, date_str, df_3min, signals, trades, logger)
                except Exception as chart_error:
                    logger.warning(f"⚠️  [{stock_code}] 차트 생성 실패: {chart_error}")
            
            logger.info(f"✅ [{stock_code}] 처리 완료 - {len(trades)}건 거래, {len(missed_opportunities)}건 매수 못한 기회")
            return stock_code, trades, df_1min, missed_opportunities
            
        except Exception as e:
            logger.error(f"❌ [{stock_code}] 처리 실패: {e}")
            return stock_code, [], pd.DataFrame(), []

    # 병렬 처리 실행
    all_trades: Dict[str, List[Dict[str, object]]] = {}
    all_stock_data: Dict[str, pd.DataFrame] = {}  # 🆕 상세 분석용 데이터 저장
    all_missed_opportunities: Dict[str, List[Dict[str, object]]] = {}  # 🆕 매수 못한 기회들
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # 모든 종목을 병렬로 처리
        future_to_stock = {
            executor.submit(process_single_stock, code): code 
            for code in codes_union
        }
        
        for future in concurrent.futures.as_completed(future_to_stock):
            stock_code = future_to_stock[future]
            try:
                result = future.result()
                if len(result) == 4:  # 새로운 형식 (missed_opportunities 포함)
                    processed_code, trades, stock_data, missed_opportunities = result
                    all_missed_opportunities[processed_code] = missed_opportunities
                else:  # 기존 형식 (하위 호환성)
                    processed_code, trades, stock_data = result
                    all_missed_opportunities[processed_code] = []
                
                all_trades[processed_code] = trades
                all_stock_data[processed_code] = stock_data  # 🆕 1분봉 데이터 저장
            except Exception as exc:
                logger.error(f"❌ [{stock_code}] 병렬 처리 중 예외 발생: {exc}")
                all_trades[stock_code] = []
                all_stock_data[stock_code] = pd.DataFrame()
                all_missed_opportunities[stock_code] = []

    # 결과 요약
    total_trades = sum(len(trades) for trades in all_trades.values())
    total_missed_opportunities = sum(len(missed) for missed in all_missed_opportunities.values())
    successful_stocks = sum(1 for trades in all_trades.values() if trades)
    stocks_with_missed_opportunities = sum(1 for missed in all_missed_opportunities.values() if missed)

    # 🆕 최대 동시 보유 종목 수 계산
    max_concurrent_holdings = calculate_max_concurrent_holdings(all_trades)

    logger.info(f"" + "="*60)
    logger.info(f"🎯 전체 처리 완료")
    logger.info(f"📊 처리된 종목: {len(codes_union)}개")
    logger.info(f"✅ 거래가 있는 종목: {successful_stocks}개")
    logger.info(f"💰 총 거래 건수: {total_trades}건")
    logger.info(f"🚫 매수 못한 기회: {total_missed_opportunities}건 ({stocks_with_missed_opportunities}개 종목)")
    logger.info(f"📊 최대 동시 보유 종목 수: {max_concurrent_holdings}개")

    # 선택 날짜별 통계 (DB에서 selection_date 정보가 있을 때만)
    if stock_selection_map:
        try:
            selection_stats = calculate_selection_date_stats(all_trades, stock_selection_map, date_str)
            if selection_stats:
                logger.info(f"" + "="*60)
                logger.info(f"📅 선택 날짜별 거래 통계")
                for selection_date, stats in selection_stats.items():
                    success_rate = (stats['성공거래수'] / stats['총거래수'] * 100) if stats['총거래수'] > 0 else 0
                    avg_profit = (stats['총수익률'] / stats['총거래수']) if stats['총거래수'] > 0 else 0
                    logger.info(f"📅 {selection_date}: 총{stats['총거래수']}건 | 성공{stats['성공거래수']}건 | 성공률{success_rate:.1f}% | 평균수익률{avg_profit:.2f}%")
        except Exception as e:
            logger.warning(f"선택 날짜별 통계 계산 실패: {e}")

    # 파일 내보내기
    if args.export:
        try:
            if args.export == "csv":
                # CSV 형식으로 내보내기
                all_csv_rows = []
                for stock_code, trades in all_trades.items():
                    if trades:
                        csv_rows = to_csv_rows(stock_code, date_str, trades)
                        all_csv_rows.extend(csv_rows)
                
                if all_csv_rows:
                    df_export = pd.DataFrame(all_csv_rows)
                    df_export.to_csv(args.csv_path, index=False, encoding='utf-8-sig')
                    logger.info(f"📁 CSV 파일 저장 완료: {args.csv_path} ({len(all_csv_rows)}건)")
                
            elif args.export == "txt":
                # TXT 형식으로 내보내기 (원본 형식에 맞게)
                try:
                    lines = []
                    
                    # 전체 승패 통계 계산 (미체결 제외 - 현재는 항상 체결)
                    all_completed_trades = [trade for trades in all_trades.values() for trade in trades]  # 미체결 개념 제거
                    total_wins = sum(1 for trade in all_completed_trades if trade.get('profit_rate', 0) > 0 and trade.get('sell_time'))
                    total_losses = sum(1 for trade in all_completed_trades if trade.get('profit_rate', 0) <= 0 and trade.get('sell_time'))
                    
                    # selection_date 이후 승패 계산 (필터링 적용)
                    selection_date_wins = 0
                    selection_date_losses = 0
                    
                    for stock_code, trades in all_trades.items():
                        selection_date = stock_selection_map.get(stock_code)
                        if selection_date and selection_date != "알수없음":
                            try:
                                # selection_date를 datetime으로 변환 (시간,분 포함)
                                from datetime import datetime
                                if len(selection_date) >= 19:  # YYYY-MM-DD HH:MM:SS 형식
                                    selection_dt = datetime.strptime(selection_date[:19], '%Y-%m-%d %H:%M:%S')
                                elif len(selection_date) >= 16:  # YYYY-MM-DD HH:MM 형식
                                    selection_dt = datetime.strptime(selection_date[:16], '%Y-%m-%d %H:%M')
                                else:  # 날짜만
                                    selection_dt = datetime.strptime(selection_date[:10], '%Y-%m-%d')
                                
                                # 각 거래 시간과 selection_date 비교 (미체결 개념 제거)
                                for trade in trades:
                                    # if trade.get('status') == 'unexecuted':
                                    #     continue  # 미체결 제외
                                    if trade.get('sell_time'):  # 완료된 거래만
                                        # 거래 시간을 datetime으로 변환
                                        buy_time_str = trade.get('buy_time', '')
                                        if buy_time_str:
                                            try:
                                                # 시뮬레이션 날짜 + 거래 시간으로 완전한 datetime 생성
                                                trade_datetime_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {buy_time_str}:00"
                                                trade_dt = datetime.strptime(trade_datetime_str, '%Y-%m-%d %H:%M:%S')
                                                
                                                # selection_date 이후인 거래만 포함
                                                if trade_dt >= selection_dt:
                                                    if trade.get('profit_rate', 0) > 0:
                                                        selection_date_wins += 1
                                                    else:
                                                        selection_date_losses += 1
                                            except:
                                                # 시간 파싱 실패 시 포함
                                                if trade.get('profit_rate', 0) > 0:
                                                    selection_date_wins += 1
                                                else:
                                                    selection_date_losses += 1
                            except:
                                # 날짜 파싱 실패 시 전체 포함
                                for trade in trades:
                                    if trade.get('sell_time'):
                                        if trade.get('profit_rate', 0) > 0:
                                            selection_date_wins += 1
                                        else:
                                            selection_date_losses += 1
                        else:
                            # selection_date 정보가 없는 경우 전체 포함
                            for trade in trades:
                                if trade.get('sell_time'):
                                    if trade.get('profit_rate', 0) > 0:
                                        selection_date_wins += 1
                                    else:
                                        selection_date_losses += 1
                    
                    # 🆕 12시 이전 매수 종목 승패 계산
                    morning_wins = 0
                    morning_losses = 0
                    morning_trades_details = []

                    # 동적 매수 중단 시간 적용
                    from config.market_hours import MarketHours
                    market_hours = MarketHours.get_market_hours('KRX', datetime.strptime(date_str, '%Y%m%d'))
                    buy_cutoff_hour = market_hours.get('buy_cutoff_hour', 12)

                    # ✅ all_completed_trades 사용으로 변경 (all_trades 대신)
                    for trade in all_completed_trades:
                        if trade.get('sell_time'):  # 완료된 거래만
                            buy_time_str = trade.get('buy_time', '')
                            stock_code = trade.get('stock_code', '')
                            if buy_time_str and stock_code:
                                try:
                                    buy_hour = int(buy_time_str.split(':')[0])
                                    if buy_hour < buy_cutoff_hour:  # 매수 중단 시간 이전 매수
                                        profit_rate = trade.get('profit_rate', 0)
                                        if profit_rate > 0:
                                            morning_wins += 1
                                            status_icon = "🟢"
                                        else:
                                            morning_losses += 1
                                            status_icon = "🔴"

                                        morning_trades_details.append({
                                            'stock_code': stock_code,
                                            'buy_time': buy_time_str,
                                            'profit_rate': profit_rate,
                                            'status_icon': status_icon
                                        })
                                except (ValueError, IndexError):
                                    continue

                    # 💰 수익 요약 정보 추가
                    total_trades = total_wins + total_losses
                    if total_trades > 0:
                        profit_loss_ratio = PROFIT_TAKE_RATE / STOP_LOSS_RATE
                        investment_per_trade = 1_000_000  # 거래당 100만원

                        # 실제 수익률을 기반으로 계산
                        total_profit = 0
                        total_loss = 0
                        for trade in all_completed_trades:
                            if trade.get('sell_time'):  # 매도된 거래만
                                profit_rate = trade.get('profit_rate', 0)
                                if profit_rate > 0:
                                    total_profit += investment_per_trade * (profit_rate / 100)
                                else:
                                    total_loss += investment_per_trade * abs(profit_rate / 100)

                        net_profit = total_profit - total_loss
                        net_profit_rate = (net_profit / investment_per_trade) * 100

                        lines.append(f"=== 📊 거래 설정 ===")
                        if USE_DYNAMIC_PROFIT_LOSS:
                            lines.append(f"🔧 동적 손익비: 패턴별 최적화 적용 (손절 -1.0% ~ -5.0% / 익절 +5.0% ~ +7.5%)")
                        else:
                            lines.append(f"손익비: {profit_loss_ratio:.1f}:1 (익절 +{PROFIT_TAKE_RATE:.1f}% / 손절 -{STOP_LOSS_RATE:.1f}%)")
                        lines.append(f"거래당 투자금: {investment_per_trade:,}원")
                        lines.append("")
                        lines.append(f"=== 💰 당일 수익 요약 ===")
                        lines.append(f"총 거래: {total_trades}건 ({total_wins}승 {total_losses}패)")
                        lines.append(f"총 수익금: {net_profit:+,.0f}원 ({net_profit_rate:+.1f}%)")
                        lines.append(f"  ㄴ 승리 수익: +{total_profit:,.0f}원 (실제 수익률 합계)")
                        lines.append(f"  ㄴ 손실 금액: -{total_loss:,.0f}원 (실제 손실률 합계)")
                        lines.append("")

                    # 🆕 필터 통계 추가
                    try:
                        from core.indicators.filter_stats import filter_stats
                        stats = filter_stats.get_stats()
                        total_checked = stats.get('total_patterns_checked', 0)
                        combo_blocked = stats.get('pattern_combination_filter', 0)
                        close_blocked = stats.get('close_position_filter', 0)

                        if total_checked > 0:
                            passed = total_checked - combo_blocked - close_blocked
                            lines.append(f"=== 📊 필터 통계 ===")
                            lines.append(f"전체 패턴 체크: {total_checked}건")
                            lines.append(f"  ✅ 통과: {passed}건 ({passed/total_checked*100:.1f}%)")
                            lines.append(f"  🚫 마이너스 조합 필터 차단: {combo_blocked}건 ({combo_blocked/total_checked*100:.1f}%)")
                            lines.append(f"  🚫 종가 위치 필터 차단: {close_blocked}건 ({close_blocked/total_checked*100:.1f}%)")
                            lines.append("")
                    except Exception as e:
                        pass  # 필터 통계 오류는 무시

                    lines.append(f"=== 총 승패: {total_wins}승 {total_losses}패 ===")
                    lines.append(f"=== selection_date 이후 승패: {selection_date_wins}승 {selection_date_losses}패 ===")
                    lines.append(f"=== 📊 최대 동시 보유 종목 수: {max_concurrent_holdings}개 ===")

                    # 🆕 12시 이전 매수 종목 승패 표시 추가
                    if morning_wins + morning_losses > 0:
                        morning_total = morning_wins + morning_losses
                        morning_win_rate = (morning_wins / morning_total * 100) if morning_total > 0 else 0

                        # 12시 이전 매수 종목 수익 계산
                        morning_profit = 0
                        morning_loss = 0
                        for detail in morning_trades_details:
                            profit_rate = detail['profit_rate']
                            if profit_rate > 0:
                                morning_profit += investment_per_trade * (profit_rate / 100)
                            else:
                                morning_loss += investment_per_trade * abs(profit_rate / 100)

                        morning_net_profit = morning_profit - morning_loss
                        morning_net_profit_rate = (morning_net_profit / investment_per_trade) * 100 if investment_per_trade > 0 else 0

                        # 동적으로 시간 표시
                        from config.market_hours import MarketHours
                        market_hours_display = MarketHours.get_market_hours('KRX', datetime.strptime(date_str, '%Y%m%d'))
                        buy_cutoff_display = market_hours_display.get('buy_cutoff_hour', 12)

                        lines.append(f"=== 🌅 {buy_cutoff_display}시 이전 매수 종목: {morning_wins}승 {morning_losses}패 (승률 {morning_win_rate:.1f}%) ===")
                        lines.append(f"총 수익금: {morning_net_profit:+,.0f}원 ({morning_net_profit_rate:+.1f}%)")
                        lines.append(f"  ㄴ 승리 수익: +{morning_profit:,.0f}원")
                        lines.append(f"  ㄴ 손실 금액: -{morning_loss:,.0f}원")
                        lines.append("")

                        # 개별 거래 상세 표시
                        for detail in sorted(morning_trades_details, key=lambda x: x['buy_time']):
                            stock_code = detail['stock_code']
                            stock_name = stock_names.get(stock_code, '???')
                            lines.append(f"   {detail['status_icon']} {stock_code}({stock_name}) {detail['buy_time']} 매수 → {detail['profit_rate']:+.2f}%")

                    lines.append("")
                    
                    for stock_code in codes_union:
                        trades = all_trades.get(stock_code, [])
                        stock_selection_date = stock_selection_map.get(stock_code, "알수없음")
                        
                        # 종목별 승패 계산 (미체결 개념 제거)
                        completed_trades_only = [trade for trade in trades]  # 미체결 개념 제거
                        wins = sum(1 for trade in completed_trades_only if trade.get('profit_rate', 0) > 0 and trade.get('sell_time'))
                        losses = sum(1 for trade in completed_trades_only if trade.get('profit_rate', 0) <= 0 and trade.get('sell_time'))
                        
                        # 종목별 selection_date 이후 승패 계산
                        selection_wins = 0
                        selection_losses = 0
                        
                        if stock_selection_date and stock_selection_date != "알수없음":
                            try:
                                # selection_date를 datetime으로 변환 (시간,분 포함)
                                if len(stock_selection_date) >= 19:  # YYYY-MM-DD HH:MM:SS 형식
                                    selection_dt = datetime.strptime(stock_selection_date[:19], '%Y-%m-%d %H:%M:%S')
                                elif len(stock_selection_date) >= 16:  # YYYY-MM-DD HH:MM 형식
                                    selection_dt = datetime.strptime(stock_selection_date[:16], '%Y-%m-%d %H:%M')
                                else:  # 날짜만
                                    selection_dt = datetime.strptime(stock_selection_date[:10], '%Y-%m-%d')
                                
                                # 각 거래 시간과 selection_date 비교 (미체결 개념 제거)
                                for trade in trades:
                                    # if trade.get('status') == 'unexecuted':
                                    #     continue  # 미체결 제외
                                    if trade.get('sell_time'):  # 완료된 거래만
                                        # 거래 시간을 datetime으로 변환
                                        buy_time_str = trade.get('buy_time', '')
                                        if buy_time_str:
                                            try:
                                                # 시뮬레이션 날짜 + 거래 시간으로 완전한 datetime 생성
                                                trade_datetime_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {buy_time_str}:00"
                                                trade_dt = datetime.strptime(trade_datetime_str, '%Y-%m-%d %H:%M:%S')
                                                
                                                # selection_date 이후인 거래만 포함
                                                if trade_dt >= selection_dt:
                                                    if trade.get('profit_rate', 0) > 0:
                                                        selection_wins += 1
                                                    else:
                                                        selection_losses += 1
                                            except:
                                                # 시간 파싱 실패 시 포함
                                                if trade.get('profit_rate', 0) > 0:
                                                    selection_wins += 1
                                                else:
                                                    selection_losses += 1
                            except:
                                # 날짜 파싱 실패 시 전체 포함
                                selection_wins = wins
                                selection_losses = losses
                        else:
                            # selection_date 정보가 없는 경우 전체 포함
                            selection_wins = wins
                            selection_losses = losses
                        
                        lines.append(f"=== {stock_code} - {date_str} 눌림목(3분) 신호 재현 ===")
                        lines.append(f"  selection_date: {stock_selection_date}")
                        lines.append(f"  승패: {wins}승 {losses}패")
                        lines.append(f"  selection_date 이후 승패: {selection_wins}승 {selection_losses}패")
                        lines.append("  매매신호:")
                        
                        if trades:
                            # 매매 신호 표시
                            signals_shown = set()
                            for trade in trades:
                                signal_key = f"{trade['buy_time']} [pullback_pattern]"
                                if signal_key not in signals_shown:
                                    lines.append(f"    {trade['buy_time']} [pullback_pattern]")
                                    signals_shown.add(signal_key)
                        else:
                            lines.append("    없음")
                        
                        lines.append("  체결 시뮬레이션:")
                        if trades:
                            for trade in trades:
                                # if trade.get('status') == 'unexecuted':
                                #     # 미체결 신호
                                #     lines.append(f"    {trade['buy_time']} 신호[pullback_pattern] → {trade.get('reason', '미체결')}")
                                if trade.get('sell_time'):
                                    # 체결 + 매도 완료
                                    profit_rate = trade.get('profit_rate', 0)
                                    if profit_rate > 0:
                                        reason = f"profit_{profit_rate:.1f}pct"
                                    else:
                                        reason = f"stop_loss_{abs(profit_rate):.1f}pct"
                                    
                                    lines.append(f"    {trade['buy_time']} 매수[pullback_pattern] @{trade['buy_price']:,.0f} → {trade['sell_time']} 매도[{reason}] @{trade['sell_price']:,.0f} ({profit_rate:+.2f}%)")
                                else:
                                    # 체결 + 미결제
                                    lines.append(f"    {trade['buy_time']} 매수[pullback_pattern] @{trade['buy_price']:,.0f} → 미결제 ({trade.get('reason', '알수없음')})")
                        else:
                            lines.append("    없음")
                        
                        # 🆕 매수 못한 기회 섹션 추가
                        missed_opportunities = all_missed_opportunities.get(stock_code, [])
                        if missed_opportunities:
                            lines.append("  매수 못한 기회:")
                            for missed in missed_opportunities:
                                signal_time = missed['signal_time'].strftime('%H:%M')
                                target_price = missed['target_price']
                                virtual_profit = missed.get('virtual_profit_rate', 0)
                                reason = missed.get('reason', '알수없음')
                                
                                if virtual_profit is not None:
                                    profit_status = f"가상수익률: {virtual_profit:+.2f}%"
                                else:
                                    profit_status = "가상수익률: 계산불가"
                                
                                lines.append(f"    {signal_time} 신호[pullback_pattern] @{target_price:,.0f} → {reason} ({profit_status})")
                        else:
                            lines.append("  매수 못한 기회:")
                            lines.append("    없음")
                        
                        # ==================== 🆕 상세 3분봉 분석 추가 ====================
                        lines.append("")
                        # 동적 시장 시간 표시
                        from config.market_hours import MarketHours
                        target_date_display = datetime.strptime(date_str, '%Y%m%d')
                        market_hours_display = MarketHours.get_market_hours('KRX', target_date_display)
                        market_open_str = market_hours_display['market_open'].strftime('%H:%M')
                        market_close_str = market_hours_display['market_close'].strftime('%H:%M')
                        lines.append(f"  🔍 상세 3분봉 분석 ({market_open_str}~{market_close_str}):")
                        
                        # 해당 종목의 상세 분석을 위한 데이터 재처리
                        try:
                            # 해당 종목의 3분봉 데이터 재조회
                            all_data_for_stock = all_stock_data.get(stock_code)
                            if all_data_for_stock is not None and not all_data_for_stock.empty:
                                # 3분봉 변환
                                from core.timeframe_converter import TimeFrameConverter
                                df_3min_detailed = TimeFrameConverter.convert_to_3min_data(all_data_for_stock)
                                
                                if df_3min_detailed is not None and not df_3min_detailed.empty:
                                    # 매수/매도 시점 매핑 - 실제 신호 발생 시점에 표시하도록 수정
                                    trade_times = {}
                                    signal_to_buy_mapping = {}  # 신호 시점 → 매수 기록 매핑
                                    
                                    # 실제 매수 신호를 다시 분석하여 신호 발생 시점을 찾기
                                    buy_signals_for_mapping = list_all_buy_signals(df_3min_detailed, logger=logger, stock_code=stock_code, simulation_date=date_str)
                                    
                                    # 거래와 신호의 정확한 1:1 매핑을 위한 처리
                                    used_signals = set()  # 이미 매핑된 신호들
                                    
                                    for trade in trades:
                                        buy_time_str = trade['buy_time']
                                        # 기존 매수 시간 기반 매핑 (하위 호환)
                                        trade_times[buy_time_str] = {
                                            'type': 'buy',
                                            'price': trade['buy_price'],
                                            'sell_time': trade.get('sell_time', ''),
                                            'sell_price': trade.get('sell_price', 0),
                                            'reason': trade.get('reason', '')
                                        }
                                        
                                        # 각 거래에 대해 가장 가까운 시간의 신호 하나만 매핑
                                        best_match_signal = None
                                        best_match_diff = float('inf')
                                        
                                        for signal in buy_signals_for_mapping:
                                            signal_completion_time = signal.get('signal_time')
                                            if signal_completion_time:
                                                signal_completion_str = signal_completion_time.strftime('%H:%M')
                                                
                                                # 이미 사용된 신호는 건너뜀
                                                if signal_completion_str in used_signals:
                                                    continue
                                                
                                                try:
                                                    from datetime import datetime
                                                    buy_time_obj = datetime.strptime(f"2025-01-01 {buy_time_str}:00", '%Y-%m-%d %H:%M:%S')
                                                    signal_time_obj = datetime.strptime(f"2025-01-01 {signal_completion_str}:00", '%Y-%m-%d %H:%M:%S')
                                                    time_diff = abs((buy_time_obj - signal_time_obj).total_seconds())
                                                    
                                                    # 5분(300초) 이내이고 가장 가까운 신호 찾기
                                                    if time_diff <= 300 and time_diff < best_match_diff:
                                                        best_match_signal = signal_completion_str
                                                        best_match_diff = time_diff
                                                except:
                                                    continue
                                        
                                        # 가장 적합한 신호에 거래 매핑
                                        if best_match_signal:
                                            signal_to_buy_mapping[best_match_signal] = {
                                                'type': 'buy',
                                                'price': trade['buy_price'],
                                                'sell_time': trade.get('sell_time', ''),
                                                'sell_price': trade.get('sell_price', 0),
                                                'reason': trade.get('reason', '')
                                            }
                                            used_signals.add(best_match_signal)
                                    
                                    # 3분봉별 상세 분석
                                    for i, row in df_3min_detailed.iterrows():
                                        candle_time = row['datetime']
                                        if candle_time.hour < 9 or candle_time.hour > 15:
                                            continue
                                        if candle_time.hour == 15 and candle_time.minute >= 30:
                                            continue
                                            
                                        time_str = candle_time.strftime('%H:%M')
                                        signal_time_str = (candle_time + pd.Timedelta(minutes=3)).strftime('%H:%M')
                                        
                                        # 신호 생성 및 분석
                                        current_data = df_3min_detailed.iloc[:i+1]
                                        if len(current_data) >= 5:
                                            from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
                                            
                                            # ==================== 신호 생성 로직 선택 ====================
                                            # 🔄 v2 로직 사용 (SHA-1: 4d2836c2 복원) - 주석 처리하여 비활성화
                                            # signal_strength, risk_signals = PullbackCandlePattern.generate_improved_signals_v2(
                                            #     current_data,
                                            #     entry_price=None,
                                            #     entry_low=None,
                                            #     debug=True,
                                            #     logger=logger
                                            # )
                                            
                                            # 🔄 현재 로직 사용 (개선된 버전) - 주석 해제하여 사용
                                            signal_strength = PullbackCandlePattern.generate_improved_signals(
                                                current_data,
                                                stock_code=stock_code,
                                                debug=True
                                            )
                                            
                                            # 상태 표시
                                            status_parts = []
                                            
                                            # 1. 기본 정보
                                            close_price = row['close']
                                            volume = row['volume']
                                            status_parts.append(f"종가:{close_price:,.0f}")
                                            status_parts.append(f"거래량:{volume:,.0f}")
                                            
                                            # 2. 신호 상태
                                            if signal_strength:
                                                # 15시 이후 매수금지 표시
                                                signal_completion_time = candle_time + pd.Timedelta(minutes=3)
                                                is_after_15h = signal_completion_time.hour >= 15

                                                # 패턴 검증 제거 (모든 종목 동일하게 처리)
                                                is_buy_signal = signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]

                                                if signal_strength.signal_type == SignalType.STRONG_BUY:
                                                    if is_after_15h:
                                                        status_parts.append("🟢강매수(15시이후매수금지)")
                                                    else:
                                                        status_parts.append("🟢강매수")
                                                elif signal_strength.signal_type == SignalType.CAUTIOUS_BUY:
                                                    if is_after_15h:
                                                        status_parts.append("🟡조건부매수(15시이후매수금지)")
                                                    else:
                                                        status_parts.append("🟡조건부매수")
                                                elif signal_strength.signal_type == SignalType.AVOID:
                                                    # 회피 이유 추가
                                                    avoid_reason = ""
                                                    if signal_strength.reasons:
                                                        avoid_reason = f"({signal_strength.reasons[0]})"
                                                    status_parts.append(f"🔴회피{avoid_reason}")
                                                elif signal_strength.signal_type == SignalType.WAIT:
                                                    # 대기 이유 추가
                                                    wait_reason = ""
                                                    if signal_strength.reasons:
                                                        wait_reason = f"({signal_strength.reasons[0]})"
                                                    status_parts.append(f"⚪대기{wait_reason}")
                                                else:
                                                    status_parts.append("⚫조건미충족")
                                                    
                                                # 신뢰도 표시
                                                status_parts.append(f"신뢰도:{signal_strength.confidence:.0f}%")
                                            else:
                                                status_parts.append("❌신호없음")
                                            
                                            # 3. 매매 실행 여부 - 신호 발생 시점에서 표시
                                            trade_info = None
                                            
                                            # 먼저 신호 발생 시점(signal_time_str)에서 매수 기록 확인
                                            if signal_time_str in signal_to_buy_mapping:
                                                trade_info = signal_to_buy_mapping[signal_time_str]
                                            # 기존 매수 시점에서도 확인 (하위 호환)
                                            elif signal_time_str in trade_times:
                                                trade_info = trade_times[signal_time_str]
                                                
                                            if trade_info and trade_info['type'] == 'buy':
                                                status_parts.append(f"💰매수@{trade_info['price']:,.0f}")
                                                if trade_info['sell_time']:
                                                    status_parts.append(f"→{trade_info['sell_time']}매도@{trade_info['sell_price']:,.0f}")
                                            
                                            status_text = " | ".join(status_parts)
                                            lines.append(f"    {time_str}→{signal_time_str}: {status_text}")
                                        else:
                                            lines.append(f"    {time_str}→{signal_time_str}: 데이터부족")
                                else:
                                    lines.append("    3분봉 변환 실패")
                            else:
                                lines.append("    데이터 없음")
                        except Exception as e:
                            lines.append(f"    분석 오류: {str(e)[:50]}")
                        
                        lines.append("")
                    
                    content = "\n".join(lines).rstrip() + "\n"
                    with open(args.txt_path, "w", encoding="utf-8-sig") as f:
                        f.write(content)
                    print(f"\n📄 TXT 저장 완료: {args.txt_path}")
                except Exception as e:
                    print(f"\n❌ TXT 저장 실패: {e}")
                    import traceback
                    print(f"상세 오류: {traceback.format_exc()}")
                
        except Exception as e:
            logger.error(f"❌ 파일 내보내기 실패: {e}")

    logger.info(f"🏁 신호 재현 리포트 완료!")


if __name__ == "__main__":
    # 시뮬레이션에서는 패턴 로깅 활성화
    import os
    os.environ['ENABLE_PATTERN_LOGGING'] = 'true'

    main()