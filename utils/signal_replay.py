"""
실데이터 기반 매매신호(눌림목/3분봉) 재현 리포트 스크립트

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
- 전략은 눌림목만 사용합니다. 재매수 정책에는 영향 주지 않습니다(리포팅 전용).
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Dict, List, Tuple, Optional
import io
import logging
from datetime import datetime
import sys
import os
import sqlite3
import concurrent.futures
import time

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 전역 변수로 현재 처리 중인 종목코드 추적
current_processing_stock = {'code': 'UNKNOWN'}

import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import KST
from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
from api.kis_api_manager import KISAPIManager
from visualization.data_processor import DataProcessor
from core.trading_decision_engine import TradingDecisionEngine
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


def calculate_trading_signals_once(df_3min: pd.DataFrame, *, debug_logs: bool = False, 
                                 logger: Optional[logging.Logger] = None,
                                 log_level: int = logging.INFO,
                                 stock_code: str = "UNKNOWN") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """3분봉 데이터에 대해 한 번만 신호를 계산하여 재사용. (성능 최적화)
    
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
    
    # 이제 signals에 신호 강도 정보가 포함되어 있음 (use_improved_logic=True)
    if logger:
        logger.debug(f"⚡ {stock_code} 신호 계산 완료: {elapsed:.2f}초, {len(signals)}행")
        
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


def list_all_buy_signals(df_3min: pd.DataFrame, *, logger: Optional[logging.Logger] = None, stock_code: str = "UNKNOWN") -> List[Dict[str, object]]:
    """전체 3분봉에서 매수 신호 전체 리스트를 반환 (실시간과 동일한 방식)"""
    
    if df_3min is None or df_3min.empty:
        return []
    
    try:
        from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
        
        buy_signals = []
        
        # 각 3분봉 시점에서 실시간과 동일한 방식으로 신호 체크
        for i in range(len(df_3min)):
            # 해당 시점까지의 데이터만 사용 (실시간과 동일)
            current_data = df_3min.iloc[:i+1].copy()
            
            if len(current_data) < 5:  # 최소 데이터 요구사항
                continue
            
            # ==================== 실시간과 동일한 신호 생성 ====================
            signal_strength = PullbackCandlePattern.generate_improved_signals(
                current_data,
                stock_code=stock_code,
                debug=False
            )
            
            if signal_strength is None:
                continue
            
            # 매수 신호 확인 (실시간과 동일한 조건)
            if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                # 현재 3분봉 정보
                current_row = df_3min.iloc[i]
                datetime_val = current_row.get('datetime')
                close_val = current_row.get('close', 0)
                volume_val = current_row.get('volume', 0)
                low_val = current_row.get('low', 0)
                
                # 3분봉 완성 시점 (실제 신호 발생 시점)
                signal_completion_time = datetime_val + pd.Timedelta(minutes=3) if datetime_val else datetime_val
                
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
                    'reasons': ' | '.join(signal_strength.reasons)  # 신호 사유
                }
                buy_signals.append(signal_info)
        
        if logger:
            logger.info(f"🎯 [{stock_code}] 총 {len(buy_signals)}개 매수 신호 발견 (실시간 방식)")
            
        return buy_signals
        
    except Exception as e:
        if logger:
            logger.error(f"매수 신호 리스트 생성 실패 [{stock_code}]: {e}")
        return []


def simulate_trades(df_3min: pd.DataFrame, df_1min: Optional[pd.DataFrame] = None, *, logger: Optional[logging.Logger] = None, stock_code: str = "UNKNOWN") -> List[Dict[str, object]]:
    """매수신호 발생 시점에서 1분봉 기준으로 실제 거래를 시뮬레이션"""
    
    if df_3min is None or df_3min.empty:
        return []
        
    if df_1min is None or df_1min.empty:
        if logger:
            logger.warning(f"1분봉 데이터 없음 - 거래 시뮬레이션 불가 [{stock_code}]")
        return []
    
    try:
        # 매수 신호 리스트 가져오기
        buy_signals = list_all_buy_signals(df_3min, logger=logger, stock_code=stock_code)
        
        if not buy_signals:
            if logger:
                logger.info(f"매수 신호 없음 - 거래 시뮬레이션 불가 [{stock_code}]")
            return []
        
        trades = []
        current_position = None  # 현재 포지션 추적 (실시간과 동일하게 한 번에 하나만)
        
        for signal in buy_signals:
            signal_datetime = signal['datetime']
            signal_index = signal['index']
            
            # ==================== 실시간과 동일: 포지션 보유 중이면 매수 금지 ====================
            if current_position is not None:
                # 현재 시간이 포지션 매도 이후인지 확인
                if signal_datetime <= current_position['sell_time']:
                    if logger:
                        logger.debug(f"⚠️ [{signal_datetime.strftime('%H:%M')}] 포지션 보유 중으로 매수 건너뜀")
                    continue  # 포지션 보유 중이므로 매수 불가
                else:
                    # 포지션이 매도되었으므로 새로운 매수 가능
                    current_position = None
            
            # ==================== 실시간과 완전 동일한 매수 로직 ====================
            
            # 신호 강도에 따른 목표 수익률 (실시간과 동일)
            target_profit_rate = signal.get('target_profit', 0.015)
            if target_profit_rate <= 0:
                target_profit_rate = 0.015
                
            # 손익비 2:1로 손절매 비율 설정
            stop_loss_rate = target_profit_rate / 2.0
            
            # 실시간과 동일한 3/5가 및 진입저가 사용
            three_fifths_price = signal.get('buy_price', 0)  # 이미 계산된 3/5가 사용
            entry_low = signal.get('entry_low', 0)  # 이미 계산된 진입저가 사용
            
            if three_fifths_price <= 0:
                if logger:
                    logger.warning(f"⚠️ [{stock_code}] 3/5가 정보 없음, 거래 건너뜀")
                continue
            
            # ==================== 매수 체결 가능성 검증 (5분 내) ====================
            
            # 3분봉 라벨 기준으로 완성 시점 계산
            # 예: 09:30 라벨 → 09:30~09:32 구간이 09:33에 완성되어 09:33부터 매수 시도
            signal_candle_completion = signal_datetime + pd.Timedelta(minutes=3)  # 3분봉 완성 시점
            signal_time_start = signal_candle_completion  # 완성 시점부터 매수 시도
            signal_time_end = signal_time_start + pd.Timedelta(minutes=5)  # 5분 내
            
            # 디버그: 시간 정보 출력
            if logger:
                logger.debug(f"🕐 신호 라벨: {signal_datetime.strftime('%H:%M')}, "
                           f"3분봉 완성: {signal_candle_completion.strftime('%H:%M')}, "
                           f"매수 윈도우: {signal_time_start.strftime('%H:%M')}~{signal_time_end.strftime('%H:%M')}")
            
            check_candles = df_1min[
                (df_1min['datetime'] >= signal_time_start) & 
                (df_1min['datetime'] < signal_time_end)
            ].copy()
            
            if check_candles.empty:
                if logger:
                    logger.debug(f"⚠️ [{stock_code}] 체결 검증용 1분봉 데이터 없음, 거래 건너뜀")
                continue
            
            # 5분 내에 3/5가 이하로 떨어지는 시점 찾기
            buy_time = None
            buy_executed_price = three_fifths_price
            
            for _, candle in check_candles.iterrows():
                # 해당 1분봉의 저가가 3/5가 이하면 체결 가능
                if candle['low'] <= three_fifths_price:
                    buy_time = candle['datetime']
                    # 체결가는 3/5가로 고정 (지정가 주문과 동일)
                    break
            
            if buy_time is None:
                # 5분 내에 3/5가 이하로 떨어지지 않음 → 매수 미체결
                if logger:
                    logger.debug(f"💸 [{stock_code}] 매수 미체결: 5분 내 3/5가({three_fifths_price:,.0f}원) 도달 실패")
                continue
            
            # 체결 성공
            buy_price = buy_executed_price
            if logger:
                logger.debug(f"💰 [{stock_code}] 매수 체결: {buy_price:,.0f}원 @ {buy_time.strftime('%H:%M:%S')}")
            
            # 진입 저가 추적 (실시간과 동일)
            entry_low = signal.get('entry_low', 0)
            if entry_low <= 0:
                entry_low = signal.get('low', 0)  # 3분봉 저가를 대체
            
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
                candle_high = row['high']
                candle_low = row['low'] 
                candle_close = row['close']
                
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
                
                # 3. 진입저가 -0.2% 이탈 - 1분봉 저가가 기준가 터치 시
                if entry_low_break_price > 0 and candle_low <= entry_low_break_price:
                    sell_time = row['datetime']
                    sell_price = entry_low_break_price  # 기준가로 매도
                    sell_reason = f"entry_low_break"
                    break
                
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
                
                # ==================== 포지션 업데이트: 매도 완료 ====================
                current_position = {
                    'buy_time': buy_time,
                    'sell_time': sell_time,
                    'status': 'completed'
                }
                
                trades.append({
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
                eod_time = buy_time.replace(hour=15, minute=30, second=0, microsecond=0)  # 15:30 장 마감
                
                current_position = {
                    'buy_time': buy_time,
                    'sell_time': eod_time,  # 장 마감 시간으로 설정하여 이후 매수 허용
                    'status': 'eod_open'
                }
                
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
            
            logger.info(f"📈 [{stock_code}] 거래 시뮬레이션 완료:")
            logger.info(f"   전체 거래: {len(trades)}건")
            logger.info(f"   완료 거래: {len(completed_trades)}건")
            logger.info(f"   성공 거래: {len(successful_trades)}건")
            
            if completed_trades:
                avg_profit = sum(t['profit_rate'] for t in completed_trades) / len(completed_trades)
                logger.info(f"   평균 수익률: {avg_profit:.2f}%")
        
        return trades
    
    except Exception as e:
        if logger:
            logger.error(f"거래 시뮬레이션 실패 [{stock_code}]: {e}")
        return []


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

    args = parser.parse_args()

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

    logger.info(f"🎯 대상 날짜: {date_str}")
    logger.info(f"📊 처리할 종목 수: {len(codes_union)}개")
    
    if times_map:
        specified_count = sum(1 for times_list in times_map.values() if times_list)
        logger.info(f"⏰ 특정 시각 지정된 종목: {specified_count}개")

    # API 매니저 초기화
    try:
        api_manager = KISAPIManager()
        if not api_manager.initialize():
            logger.error("❌ KIS API 설정이 누락되었습니다. config/config.yaml을 확인하세요.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ KIS API 매니저 초기화 실패: {e}")
        sys.exit(1)

    # 병렬 처리를 위한 함수 정의
    def process_single_stock(stock_code: str) -> Tuple[str, List[Dict[str, object]], pd.DataFrame]:
        """단일 종목 처리 함수"""
        try:
            logger.info(f"🔄 [{stock_code}] 처리 시작...")
            
            # 데이터 조회 (DataProcessor 사용)
            from visualization.data_processor import DataProcessor
            from core.timeframe_converter import TimeFrameConverter
            from utils.korean_time import now_kst
            from datetime import datetime
            
            # 오늘 날짜인지 확인
            today_str = now_kst().strftime("%Y%m%d")
            
            if date_str == today_str:
                # 오늘 날짜면 실시간 데이터 사용
                from api.kis_chart_api import get_full_trading_day_data
                df_1min = get_full_trading_day_data(stock_code, date_str)
            else:
                # 과거 날짜는 DataProcessor 사용
                dp = DataProcessor()
                # 동기 호출로 변경
                import asyncio
                try:
                    # 새로운 이벤트 루프 생성하여 충돌 방지
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        df_1min = loop.run_until_complete(dp.get_historical_chart_data(stock_code, date_str))
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

            # 거래 시뮬레이션 실행
            trades = simulate_trades(df_3min, df_1min, logger=logger, stock_code=stock_code)
            
            # 차트 생성 (옵션)
            if args.charts and trades:
                try:
                    # 신호 계산 (차트용)
                    signals, _ = calculate_trading_signals_once(df_3min, logger=logger, stock_code=stock_code)
                    generate_chart_for_stock(stock_code, date_str, df_3min, signals, trades, logger)
                except Exception as chart_error:
                    logger.warning(f"⚠️  [{stock_code}] 차트 생성 실패: {chart_error}")
            
            logger.info(f"✅ [{stock_code}] 처리 완료 - {len(trades)}건 거래")
            return stock_code, trades, df_1min
            
        except Exception as e:
            logger.error(f"❌ [{stock_code}] 처리 실패: {e}")
            return stock_code, [], pd.DataFrame()

    # 병렬 처리 실행
    all_trades: Dict[str, List[Dict[str, object]]] = {}
    all_stock_data: Dict[str, pd.DataFrame] = {}  # 🆕 상세 분석용 데이터 저장
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # 모든 종목을 병렬로 처리
        future_to_stock = {
            executor.submit(process_single_stock, code): code 
            for code in codes_union
        }
        
        for future in concurrent.futures.as_completed(future_to_stock):
            stock_code = future_to_stock[future]
            try:
                processed_code, trades, stock_data = future.result()
                all_trades[processed_code] = trades
                all_stock_data[processed_code] = stock_data  # 🆕 1분봉 데이터 저장
            except Exception as exc:
                logger.error(f"❌ [{stock_code}] 병렬 처리 중 예외 발생: {exc}")
                all_trades[stock_code] = []
                all_stock_data[stock_code] = pd.DataFrame()

    # 결과 요약
    total_trades = sum(len(trades) for trades in all_trades.values())
    successful_stocks = sum(1 for trades in all_trades.values() if trades)
    
    logger.info(f"" + "="*60)
    logger.info(f"🎯 전체 처리 완료")
    logger.info(f"📊 처리된 종목: {len(codes_union)}개")
    logger.info(f"✅ 거래가 있는 종목: {successful_stocks}개")
    logger.info(f"💰 총 거래 건수: {total_trades}건")

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
    if args.export and total_trades > 0:
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
                    
                    # 전체 승패 통계 계산
                    total_wins = sum(1 for trades in all_trades.values() for trade in trades if trade.get('profit_rate', 0) > 0 and trade.get('sell_time'))
                    total_losses = sum(1 for trades in all_trades.values() for trade in trades if trade.get('profit_rate', 0) <= 0 and trade.get('sell_time'))
                    
                    lines.append(f"=== 총 승패: {total_wins}승 {total_losses}패 ===")
                    lines.append(f"=== selection_date 이후 승패: {total_wins}승 {total_losses}패 ===")
                    lines.append("")
                    
                    for stock_code in codes_union:
                        trades = all_trades.get(stock_code, [])
                        stock_selection_date = stock_selection_map.get(stock_code, "알수없음")
                        
                        # 종목별 승패 계산
                        wins = sum(1 for trade in trades if trade.get('profit_rate', 0) > 0 and trade.get('sell_time'))
                        losses = sum(1 for trade in trades if trade.get('profit_rate', 0) <= 0 and trade.get('sell_time'))
                        
                        lines.append(f"=== {stock_code} - {date_str} 눌림목(3분) 신호 재현 ===")
                        lines.append(f"  selection_date: {stock_selection_date}")
                        lines.append(f"  승패: {wins}승 {losses}패")
                        lines.append(f"  selection_date 이후 승패: {wins}승 {losses}패")
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
                                if trade.get('sell_time'):
                                    profit_rate = trade.get('profit_rate', 0)
                                    if profit_rate > 0:
                                        reason = f"profit_{profit_rate:.1f}pct"
                                    else:
                                        reason = f"stop_loss_{abs(profit_rate):.1f}pct"
                                    
                                    lines.append(f"    {trade['buy_time']} 매수[pullback_pattern] @{trade['buy_price']:,.0f} → {trade['sell_time']} 매도[{reason}] @{trade['sell_price']:,.0f} ({profit_rate:+.2f}%)")
                                else:
                                    lines.append(f"    {trade['buy_time']} 매수[pullback_pattern] @{trade['buy_price']:,.0f} → 미결제 ({trade.get('reason', '알수없음')})")
                        else:
                            lines.append("    없음")
                        
                        # ==================== 🆕 상세 3분봉 분석 추가 ====================
                        lines.append("")
                        lines.append("  🔍 상세 3분봉 분석 (09:00~15:30):")
                        
                        # 해당 종목의 상세 분석을 위한 데이터 재처리
                        try:
                            # 해당 종목의 3분봉 데이터 재조회
                            all_data_for_stock = all_stock_data.get(stock_code)
                            if all_data_for_stock is not None and not all_data_for_stock.empty:
                                # 3분봉 변환
                                from core.timeframe_converter import TimeFrameConverter
                                df_3min_detailed = TimeFrameConverter.convert_to_3min_data(all_data_for_stock)
                                
                                if df_3min_detailed is not None and not df_3min_detailed.empty:
                                    # 매수/매도 시점 매핑
                                    trade_times = {}
                                    for trade in trades:
                                        buy_time_str = trade['buy_time']
                                        trade_times[buy_time_str] = {
                                            'type': 'buy',
                                            'price': trade['buy_price'],
                                            'sell_time': trade.get('sell_time', ''),
                                            'sell_price': trade.get('sell_price', 0),
                                            'reason': trade.get('reason', '')
                                        }
                                    
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
                                            
                                            signal_strength = PullbackCandlePattern.generate_improved_signals(
                                                current_data,
                                                stock_code=stock_code,
                                                debug=False
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
                                                if signal_strength.signal_type == SignalType.STRONG_BUY:
                                                    status_parts.append("🟢강매수")
                                                elif signal_strength.signal_type == SignalType.CAUTIOUS_BUY:
                                                    status_parts.append("🟡조건부매수")
                                                elif signal_strength.signal_type == SignalType.AVOID:
                                                    status_parts.append("🔴회피")
                                                elif signal_strength.signal_type == SignalType.WAIT:
                                                    status_parts.append("⚪대기")
                                                else:
                                                    status_parts.append("⚫조건미충족")
                                                    
                                                # 신뢰도 표시
                                                status_parts.append(f"신뢰도:{signal_strength.confidence:.0f}%")
                                            else:
                                                status_parts.append("❌신호없음")
                                            
                                            # 3. 매매 실행 여부
                                            if signal_time_str in trade_times:
                                                trade_info = trade_times[signal_time_str]
                                                if trade_info['type'] == 'buy':
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
                
        except Exception as e:
            logger.error(f"❌ 파일 내보내기 실패: {e}")

    logger.info(f"🏁 신호 재현 리포트 완료!")


if __name__ == "__main__":
    main()