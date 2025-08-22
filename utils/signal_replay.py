"""
실데이터 기반 매매신호(눌림목/3분봉) 재현 리포트 스크립트

사용 예 (Windows PowerShell):
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

import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import KST
from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
from api.kis_api_manager import KISAPIManager
from visualization.data_processor import DataProcessor


try:
    # PowerShell cp949 콘솔에서 이모지/UTF-8 로그 출력 오류 방지
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logger = setup_logger(__name__)


def parse_times_mapping(arg_value: str) -> Dict[str, List[str]]:
    """파라미터 --times 파싱
    형식: "034230=14:39;078520=11:33;107600=11:24,11:27,14:51;214450=12:00,14:39"
    반환: {"034230": ["14:39"], "078520": ["11:33"], ...}
    """
    mapping: Dict[str, List[str]] = {}
    if not arg_value:
        return mapping
    for part in arg_value.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            continue
        code, times_str = part.split("=", 1)
        code = code.strip()
        times_list = [t.strip() for t in times_str.split(",") if t.strip()]
        if code and times_list:
            mapping[code] = times_list
    return mapping


def get_target_profit_from_signal_strength(sig_improved: pd.DataFrame, index: int) -> float:
    """신호 강도 정보에서 목표수익률 추출"""
    try:
        if sig_improved is None or sig_improved.empty or index >= len(sig_improved):
            logger.debug(f"신호 강도 정보 없음: empty={sig_improved is None or sig_improved.empty}, index={index}, len={len(sig_improved) if sig_improved is not None else 0}")
            return 0.015  # 기본값 1.5%
        
        # 컬럼 정보 출력
        logger.debug(f"신호 강도 컬럼: {list(sig_improved.columns) if sig_improved is not None else 'None'}")
        
        # 신호 강도 정보에서 목표수익률 확인
        if 'signal_type' in sig_improved.columns:
            signal_type = sig_improved.iloc[index]['signal_type']
            logger.debug(f"신호 타입: {signal_type}")
            if signal_type == SignalType.STRONG_BUY.value:
                logger.debug("STRONG_BUY 신호 → 2.5% 목표수익률")
                return 0.025  # 최고신호: 2.5%
            elif signal_type == SignalType.CAUTIOUS_BUY.value:
                logger.debug("CAUTIOUS_BUY 신호 → 2.0% 목표수익률")
                return 0.02  # 중간신호: 2.0%
        
        # target_profit 컬럼이 있으면 직접 사용
        if 'target_profit' in sig_improved.columns:
            target = sig_improved.iloc[index]['target_profit']
            if pd.notna(target) and target > 0:
                logger.debug(f"target_profit 컬럼에서 {target*100:.0f}% 목표수익률 추출")
                return float(target)
                
        logger.debug("기본값 1.5% 목표수익률 사용")
        return 0.015  # 기본신호: 1.5%
    except Exception as e:
        logger.debug(f"목표수익률 추출 오류: {e}")
        return 0.015  # 기본값 1.5%


def calculate_trading_signals_once(df_3min: pd.DataFrame, *, debug_logs: bool = False, 
                                 logger: Optional[logging.Logger] = None,
                                 log_level: int = logging.INFO) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """3분봉 데이터에 대해 한 번만 신호를 계산하여 재사용.
    
    모든 함수에서 공통으로 사용하는 신호 계산 함수
    09시 이전 데이터는 PullbackCandlePattern 내부에서 제외
    
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (기본 신호, 신호 강도 정보)
    """
    if df_3min is None or df_3min.empty or 'datetime' not in df_3min.columns:
        return pd.DataFrame(), pd.DataFrame()
        
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
    )
    
    # 이제 signals에 신호 강도 정보가 포함되어 있음 (use_improved_logic=True)
    if logger:
        logger.debug(f"신호 계산 완료: {len(signals)}행, 컬럼: {list(signals.columns) if signals is not None and not signals.empty else 'empty'}")
        
        # 신호 강도 정보가 있는지 확인
        if signals is not None and not signals.empty:
            has_signal_type = 'signal_type' in signals.columns
            has_target_profit = 'target_profit' in signals.columns
            logger.debug(f"신호 강도 컬럼 확인: signal_type={has_signal_type}, target_profit={has_target_profit}")
            if has_signal_type:
                non_empty_signals = signals[signals['signal_type'] != '']
                logger.debug(f"비어있지 않은 신호 개수: {len(non_empty_signals)}")
    
    # signals를 두 번 반환 (기존 코드 호환성 유지)
    return signals, signals


def _convert_to_3min_data(data: pd.DataFrame) -> Optional[pd.DataFrame]:
    """1분봉 데이터를 3분봉으로 변환 (main.py _convert_to_3min_data와 동일한 방식)"""
    try:
        if data is None or len(data) < 3:
            return None
        
        df = data.copy()
        
        # datetime 컬럼 확인 및 변환 (main.py 방식과 동일)
        if 'datetime' not in df.columns:
            if 'date' in df.columns and 'time' in df.columns:
                df['datetime'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str))
            elif 'time' in df.columns:
                # time 컬럼만 있는 경우 임시 날짜 추가
                time_str = df['time'].astype(str).str.zfill(6)
                df['datetime'] = pd.to_datetime('2024-01-01 ' + 
                                              time_str.str[:2] + ':' + 
                                              time_str.str[2:4] + ':' + 
                                              time_str.str[4:6])
            else:
                # datetime 컬럼이 없으면 순차적으로 생성 (09:00부터)
                df['datetime'] = pd.date_range(start='09:00', periods=len(df), freq='1min')
        
        # datetime을 인덱스로 설정
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime')
        
        # 3분봉으로 리샘플링 (main.py와 완전히 동일)
        resampled = df.resample('3T').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        })
        
        # NaN 제거 후 인덱스 리셋 (main.py와 동일)
        resampled = resampled.dropna().reset_index()

        # 확정 봉만 사용: 마지막 행은 진행 중일 수 있으므로 제외 (main.py와 동일)
        if resampled is not None and len(resampled) >= 1:
            resampled = resampled.iloc[:-1] if len(resampled) > 0 else resampled
        
        logger.debug(f"📊 3분봉 변환: {len(data)}개 → {len(resampled)}개 (main.py 방식)")
        
        return resampled
        
    except Exception as e:
        logger.error(f"❌ 3분봉 변환 오류: {e}")
        return None

def floor_to_3min(ts: pd.Timestamp) -> pd.Timestamp:
    """주어진 타임스탬프를 3분 경계로 내림(floor)한다."""
    return ts.floor("3T")


def locate_row_for_time(df_3min: pd.DataFrame, target_date: str, hhmm: str) -> Optional[int]:
    """3분봉 DataFrame에서 특정 HH:MM 라벨의 행 인덱스를 찾는다.
    - DataFrame은 'datetime' 컬럼을 가져야 한다(visualization.DataProcessor 기준).
    - 없으면 None.
    """
    if df_3min is None or df_3min.empty or "datetime" not in df_3min.columns:
        return None
    try:
        # target_date(YYYYMMDD) + HH:MM:00 → floor 3분으로 보정
        date_str = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
        target_ts = pd.Timestamp(f"{date_str} {hhmm}:00")
        target_floor = floor_to_3min(target_ts)
        # 정확히 일치하는 라벨 우선
        matches = df_3min.index[df_3min["datetime"] == target_floor].tolist()
        if matches:
            return matches[0]
        # 근접(±2분) 검색: 가장 가까운 인덱스 선택
        deltas = (df_3min["datetime"] - target_ts).abs()
        nearest_idx = int(deltas.idxmin()) if len(deltas) > 0 else None
        if nearest_idx is not None:
            min_delta_sec = abs((df_3min.loc[nearest_idx, "datetime"] - target_ts).total_seconds())
            if min_delta_sec <= 120:  # 2분 이내면 허용
                return nearest_idx
        return None
    except Exception:
        return None




async def fetch_and_prepare_data(stock_code: str, target_date: str) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """실데이터 1분봉을 조회 후 1분봉과 3분봉을 모두 반환."""
    dp = DataProcessor()
    base_1min = await dp.get_historical_chart_data(stock_code, target_date)
    if base_1min is None or base_1min.empty:
        logger.error(f"{stock_code} {target_date} 1분봉 데이터 조회 실패")
        return None, None
    
    # main.py와 동일한 방식으로 3분봉 변환
    df_3min = _convert_to_3min_data(base_1min)
    if df_3min is None or df_3min.empty:
        logger.error(f"{stock_code} {target_date} 3분봉 변환 실패")
        return base_1min, None
    
    return base_1min, df_3min

async def fetch_and_prepare_3min(stock_code: str, target_date: str) -> Optional[pd.DataFrame]:
    """실데이터 1분봉을 조회 후 3분봉으로 변환하여 반환. (호환성 유지)"""
    _, df_3min = await fetch_and_prepare_data(stock_code, target_date)
    return df_3min


def evaluate_signals_at_times(
    df_3min: pd.DataFrame,
    target_date: str,
    times: List[str],
    *,
    logger: Optional[logging.Logger] = None,
    debug_logs: bool = True,
    log_level: int = logging.INFO,
) -> List[Dict[str, object]]:
    """지정 시각들에서 눌림목 매수신호 ON/OFF와 미충족 사유를 평가."""
    results: List[Dict[str, object]] = []
    if df_3min is None or df_3min.empty:
        for t in times:
            results.append({
                "time": t,
                "has_signal": False,
                "signal_types": [],
                "unmet_conditions": ["데이터 없음"],
            })
        return results

    # 공통 신호 계산 함수 사용
    signals, signals_improved = calculate_trading_signals_once(df_3min, debug_logs=debug_logs, logger=logger, log_level=log_level)
    for t in times:
        row_idx = locate_row_for_time(df_3min, target_date, t)
        if row_idx is None:
            results.append({
                "time": t,
                "has_signal": False,
                "signal_types": [],
                "unmet_conditions": ["시각 매칭 실패"],
            })
            continue

        buy1 = bool(signals.get("buy_pullback_pattern", pd.Series([False]*len(df_3min))).iloc[row_idx]) if not signals.empty else False
        buy2 = bool(signals.get("buy_bisector_recovery", pd.Series([False]*len(df_3min))).iloc[row_idx]) if not signals.empty else False
        has_signal = buy1 or buy2
        signal_types = []
        if buy1:
            signal_types.append("buy_pullback_pattern")
        if buy2:
            signal_types.append("buy_bisector_recovery")

        if has_signal:
            results.append({
                "time": t,
                "has_signal": True,
                "signal_types": signal_types,
                "unmet_conditions": [],
            })
        else:
            unmet = analyze_unmet_conditions_at(df_3min, row_idx)
            results.append({
                "time": t,
                "has_signal": False,
                "signal_types": [],
                "unmet_conditions": unmet,
            })

    return results


def list_all_buy_signals(df_3min: pd.DataFrame, *, logger: Optional[logging.Logger] = None) -> List[Dict[str, object]]:
    """해당 3분봉 전체에서 발생한 매수 신호 시각/유형 리스트.

    실전 기준: 눌림목(3분) 신호만 사용 (consolidation breakout 제외)
    """
    out: List[Dict[str, object]] = []
    if df_3min is None or df_3min.empty or 'datetime' not in df_3min.columns:
        return out
    # 공통 신호 계산 함수 사용
    sig, sig_improved = calculate_trading_signals_once(df_3min, debug_logs=False)
    if sig is None or sig.empty:
        sig = pd.DataFrame(index=df_3min.index)
    has_pb = sig.get('buy_pullback_pattern', pd.Series([False]*len(df_3min)))
    has_rc = sig.get('buy_bisector_recovery', pd.Series([False]*len(df_3min)))
    for i in range(len(df_3min)):
        pb = bool(has_pb.iloc[i])
        rc = bool(has_rc.iloc[i])
        if not (pb or rc):
            continue
        ts = df_3min['datetime'].iloc[i]
        hhmm = pd.Timestamp(ts).strftime('%H:%M')
        types = []
        if pb:
            types.append('pullback')
        if rc:
            types.append('bisector_recovery')
        out.append({'time': hhmm, 'types': '+'.join(types)})
    return out


def generate_chart_for_stock(stock_code: str, target_date: str, df_3min: pd.DataFrame, 
                           df_1min: Optional[pd.DataFrame] = None, 
                           chart_renderer = None,
                           strategy_manager = None,
                           signal_calculator = None,
                           logger: Optional[logging.Logger] = None) -> Optional[str]:
    """단일 종목의 3분봉 차트를 생성 (거래량, 이등분선, 매수/매도 포인트 포함)"""
    try:
        # logger가 없으면 기본 로거 사용
        if logger is None:
            logger = setup_logger(__name__)
            
        if df_3min is None or df_3min.empty:
            logger.warning(f"차트 생성 실패: {stock_code} - 3분봉 데이터 없음")
            return None
            
        # 차트 렌더러 초기화
        if chart_renderer is None:
            from visualization.chart_renderer import ChartRenderer
            chart_renderer = ChartRenderer()
        if strategy_manager is None:
            from visualization.strategy_manager import StrategyManager
            strategy_manager = StrategyManager()
        if signal_calculator is None:
            from visualization.signal_calculator import SignalCalculator
            signal_calculator = SignalCalculator()
            
        logger.info(f"📊 차트 생성 시작: {stock_code} ({target_date})")
        
        # 3분봉 풀백 전략 가져오기
        pullback_strategy = strategy_manager.get_strategy("pullback_candle_pattern")
        
        # 지표 데이터 계산
        indicators_data = {}
        
        # 이등분선 계산
        try:
            from core.indicators.bisector_line import BisectorLine
            bisector_line = BisectorLine.calculate_bisector_line(df_3min["high"], df_3min["low"])
            if bisector_line is not None:
                # 차트 렌더러가 기대하는 형식으로 전달
                indicators_data['bisector_line'] = {
                    'line_values': bisector_line
                }
                logger.debug(f"✅ {stock_code} 이등분선 계산 완료: {len(bisector_line)}개 값")
        except Exception as e:
            logger.warning(f"⚠️ {stock_code} 이등분선 계산 오류: {e}")
            
        # 매수/매도 신호 계산
        try:
            signals, signals_improved = calculate_trading_signals_once(df_3min, debug_logs=False)
            
            if signals is not None and not signals.empty:
                # 매수 신호
                buy_pullback = signals.get('buy_pullback_pattern', pd.Series([False]*len(df_3min)))
                buy_bisector = signals.get('buy_bisector_recovery', pd.Series([False]*len(df_3min)))
                indicators_data['buy_signals'] = {
                    'buy_pullback_pattern': buy_pullback,
                    'buy_bisector_recovery': buy_bisector
                }
                
                # 매도 신호 계산 (임시 entry_low로 최근 신호의 저가 사용)
                entry_low = None
                latest_signal_idx = None
                for i in range(len(df_3min)-1, -1, -1):
                    if (bool(buy_pullback.iloc[i]) or bool(buy_bisector.iloc[i])):
                        latest_signal_idx = i
                        entry_low = float(df_3min['low'].iloc[i])
                        break
                
                if entry_low is not None:
                    try:
                        sell_signals = PullbackCandlePattern.generate_sell_signals(df_3min, entry_low=entry_low)
                        if sell_signals is not None and not sell_signals.empty:
                            indicators_data['sell_signals'] = sell_signals
                    except Exception as e:
                        logger.warning(f"⚠️ {stock_code} 매도 신호 계산 오류: {e}")
                
                logger.debug(f"✅ {stock_code} 매수/매도 신호 계산 완료")
            else:
                logger.warning(f"⚠️ {stock_code} 신호 계산 결과 없음")
                
        except Exception as e:
            logger.warning(f"⚠️ {stock_code} 신호 계산 오류: {e}")
        
        # 체결 시뮬레이션 실행
        trades = simulate_trades(df_3min, df_1min, logger=logger) if df_3min is not None else []
        
        # 차트 생성
        try:
            # 종목명 조회 (간단하게 코드만 사용)
            stock_name = f"종목{stock_code}"
            
            chart_path = chart_renderer.create_strategy_chart(
                stock_code=stock_code,
                stock_name=stock_name,
                target_date=target_date,
                strategy=pullback_strategy,
                data=df_3min,
                indicators_data=indicators_data,
                selection_reason="signal_replay 차트 생성",
                chart_suffix="signal_replay",
                timeframe="3min",
                trade_simulation_results=trades  # 체결 시뮬레이션 결과 전달
            )
            
            if chart_path:
                logger.info(f"✅ 차트 생성 완료: {stock_code} -> {chart_path}")
                return chart_path
            else:
                logger.warning(f"⚠️ 차트 생성 실패: {stock_code}")
                return None
                
        except Exception as e:
            logger.error(f"❌ {stock_code} 차트 생성 오류: {e}")
            return None
            
    except Exception as e:
        logger.error(f"❌ {stock_code} 차트 생성 전체 오류: {e}")
        return None


def simulate_trades(df_3min: pd.DataFrame, df_1min: Optional[pd.DataFrame] = None, *, logger: Optional[logging.Logger] = None) -> List[Dict[str, object]]:
    """실전(_execute_trading_decision) 기준에 맞춘 눌림목(3분) 체결 시뮬레이션.

    규칙(실전 근사):
    - 매수: buy_pullback_pattern 또는 buy_bisector_recovery가 True일 때 진입 (3분봉 기준)
      • 체결가: 신호 캔들의 3/5가(low + (high-low)*0.6), 실패 시 해당 캔들 종가
    - 매도 우선순위: (1) 실시간 가격 기준 손절/익절 (1분마다 체크) → (2) 3분봉 기술적 분석 → (3) EOD 청산
    - 종가 체결 가정, 복수 매매 허용, 끝까지 보유 시 EOD 청산
    """
    trades: List[Dict[str, object]] = []
    if df_3min is None or df_3min.empty or 'datetime' not in df_3min.columns:
        return trades
    
    # 공통 신호 계산 함수 사용
    sig, sig_improved = calculate_trading_signals_once(df_3min, debug_logs=False)
    if sig is None or sig.empty:
        sig = pd.DataFrame(index=df_3min.index)

    # 안전: 불리언 시리즈 확보
    buy_pb = sig.get('buy_pullback_pattern', pd.Series([False]*len(df_3min)))
    buy_rc = sig.get('buy_bisector_recovery', pd.Series([False]*len(df_3min)))

    in_pos = False
    pending_entry = None  # {'index_3min': j, 'type': 'pullback'|'bisector_recovery', 'entry_low': float}
    entry_price = None
    entry_time = None
    entry_type = None
    entry_low = None
    entry_datetime = None
    target_profit_rate = 0.015  # 기본 목표수익률 1.5%

    # 당일 손실 2회 시 신규 진입 차단 (해제됨)
    daily_loss_count = 0
    can_enter = True  # 항상 진입 가능

    # 1분봉이 있으면 1분 단위로 매도 체크, 없으면 3분봉 단위로 체크
    if df_1min is not None and not df_1min.empty and 'datetime' in df_1min.columns:
        # 1분봉 기반 매도 체크
        closes_1min = pd.to_numeric(df_1min['close'], errors='coerce')
        
        for i in range(len(df_1min)):
            current_time = df_1min['datetime'].iloc[i]
            current_price = float(closes_1min.iloc[i]) if pd.notna(closes_1min.iloc[i]) else None
            hhmm = pd.Timestamp(current_time).strftime('%H:%M')
            
            if current_price is None:
                continue

            # 매수 신호 체크 (3분봉과 시간 매핑)
            if not in_pos:
                if not can_enter:
                    continue
                # 현재 1분봉 시간에 해당하는 3분봉 찾기
                for j in range(len(df_3min)):
                    ts_3min = df_3min['datetime'].iloc[j]
                    # 3분봉 시간 범위 계산 (예: 10:30~10:32)
                    # 라벨(ts_3min)은 구간 시작 시각이므로 [라벨, 라벨+2분]을 포함
                    start_time = pd.Timestamp(ts_3min)
                    end_time = pd.Timestamp(ts_3min) + pd.Timedelta(minutes=2)
                    
                    if start_time <= pd.Timestamp(current_time) <= end_time:
                        # 신호 봉에서는 즉시 진입하지 않고, 봉 확정 후(라벨+3분 이후) 첫 시점에 진입
                        if pending_entry is None and (bool(buy_pb.iloc[j]) or bool(buy_rc.iloc[j])):
                            typ = 'pullback' if bool(buy_pb.iloc[j]) else 'bisector_recovery'
                            try:
                                pending_entry = {
                                    'index_3min': j,
                                    'type': typ,
                                    'entry_low': float(df_3min['low'].iloc[j])
                                }
                            except Exception:
                                pending_entry = {
                                    'index_3min': j,
                                    'type': typ,
                                    'entry_low': None
                                }
                        break

                # 대기 엔트리가 있고, 해당 3분봉이 확정된 이후(라벨+3분 경과)면 진입
                if (not in_pos) and pending_entry is not None:
                    j = pending_entry['index_3min']
                    ts_close = pd.Timestamp(df_3min['datetime'].iloc[j]) + pd.Timedelta(minutes=3)
                    if pd.Timestamp(current_time) >= ts_close:
                        in_pos = True
                        # 3/5가 우선, 실패 시 현재가
                        try:
                            hi = float(df_3min['high'].iloc[j])
                            lo = float(df_3min['low'].iloc[j])
                            three_fifth_price = lo + (hi - lo) * 0.6
                            entry_price = three_fifth_price if (three_fifth_price > 0 and lo <= three_fifth_price <= hi) else current_price
                        except Exception:
                            entry_price = current_price
                        entry_time = hhmm
                        entry_datetime = current_time
                        entry_low = pending_entry.get('entry_low', None)
                        entry_type = pending_entry.get('type', None)
                        
                        # 신호 강도 기반 목표수익률 설정
                        target_profit_rate = get_target_profit_from_signal_strength(sig_improved, j)
                        logger.debug(f"매수 진입 {j}: 목표수익률 {target_profit_rate*100:.0f}% 설정")
                        
                        pending_entry = None
            else:
                # 매도 체크 (1분마다)
                exit_reason = None
                
                # 신호강도별 손절/익절 (손익비 2:1)
                stop_loss_rate = target_profit_rate / 2.0  # 손익비 2:1
                
                # (1) 신호강도별 손절
                if entry_price is not None and current_price <= entry_price * (1.0 - stop_loss_rate):
                    exit_reason = f'stop_loss_{stop_loss_rate*100:.1f}pct'
                # (2) 신호강도별 익절
                elif entry_price is not None and current_price >= entry_price * (1.0 + target_profit_rate):
                    exit_reason = f'profit_{target_profit_rate*100:.1f}pct'
                # (3) 진입저가 실시간 체크: -0.2%
                elif entry_low is not None and entry_low > 0 and current_price < entry_low * 0.998:
                    exit_reason = 'realtime_entry_low_break'
                
                if exit_reason is not None:
                     # 09시 이전 매수/매도는 승패 계산에서 제외
                     buy_hour = int(entry_time.split(':')[0]) if ':' in entry_time else 0
                     sell_hour = int(hhmm.split(':')[0]) if ':' in hhmm else 0
                     
                     if buy_hour >= 9 and sell_hour >= 9:  # 09시 이후만 승패 계산에 포함
                         profit = (current_price - entry_price) / entry_price * 100.0 if entry_price and entry_price > 0 else 0.0
                         trades.append({
                             'buy_time': entry_time,
                             'buy_type': entry_type,
                             'buy_price': entry_price,
                             'sell_time': hhmm,
                             'sell_reason': exit_reason,
                             'sell_price': current_price,
                             'profit_rate': profit,
                         })
                     else:
                         # 09시 이전 거래는 기록하되 승패 계산에서 제외
                         trades.append({
                             'buy_time': entry_time,
                             'buy_type': entry_type,
                             'buy_price': entry_price,
                             'sell_time': hhmm,
                             'sell_reason': exit_reason,
                             'sell_price': current_price,
                             'profit_rate': 0.0,  # 승패 계산에서 제외
                             'excluded_from_stats': True,  # 통계에서 제외 표시
                         })
                     in_pos = False
                     entry_price = None
                     entry_time = None
                     entry_type = None
                     entry_low = None
                     entry_datetime = None
                     # 손실 집계 및 진입 차단 (해제됨)
                     if 'profit' in locals() and profit < 0:
                         daily_loss_count += 1
                         # if daily_loss_count >= 2:
                         #     can_enter = False
    else:
        # 기존 3분봉 방식 (1분봉 데이터 없는 경우)
        closes = pd.to_numeric(df_3min['close'], errors='coerce')
        
        for i in range(len(df_3min)):
            ts = df_3min['datetime'].iloc[i]
            hhmm = pd.Timestamp(ts).strftime('%H:%M')
            c = float(closes.iloc[i]) if pd.notna(closes.iloc[i]) else None
            if c is None:
                continue

            if not in_pos:
                if not can_enter:
                    continue
                # 직전 신호 봉 대기 중이면, 신호 봉의 다음 봉(i)에서 진입
                if pending_entry is not None:
                    in_pos = True
                    j = pending_entry['index_3min']
                    try:
                        hi = float(df_3min['high'].iloc[j])
                        lo = float(df_3min['low'].iloc[j])
                        three_fifth_price = lo + (hi - lo) * 0.6
                        entry_price = three_fifth_price if (three_fifth_price > 0 and lo <= three_fifth_price <= hi) else c
                    except Exception:
                        entry_price = c
                    entry_time = hhmm
                    entry_low = pending_entry.get('entry_low', None)
                    entry_type = pending_entry.get('type', None)
                    
                    # 신호 강도 기반 목표수익률 설정
                    target_profit_rate = get_target_profit_from_signal_strength(sig_improved, j)
                    logger.debug(f"3분봉 매수 진입 {j}: 목표수익률 {target_profit_rate*100:.0f}% 설정")
                    
                    pending_entry = None
                # 현재 봉이 신호 봉이면 '대기'만 등록(진입은 다음 봉에서)
                elif bool(buy_pb.iloc[i]) or bool(buy_rc.iloc[i]):
                    pending_entry = {
                        'index_3min': i,
                        'type': 'pullback' if bool(buy_pb.iloc[i]) else 'bisector_recovery',
                        'entry_low': float(df_3min['low'].iloc[i]) if not pd.isna(df_3min['low'].iloc[i]) else None,
                    }
            else:
                exit_reason = None
                
                # 실시간과 동일한 매도 로직 적용
                # 신호강도별 손절/익절 (손익비 2:1)
                stop_loss_rate = target_profit_rate / 2.0  # 손익비 2:1
                
                # (1) 신호강도별 손절
                if entry_price is not None and c <= entry_price * (1.0 - stop_loss_rate):
                    exit_reason = f'stop_loss_{stop_loss_rate*100:.1f}pct'
                # (2) 신호강도별 익절
                elif entry_price is not None and c >= entry_price * (1.0 + target_profit_rate):
                    exit_reason = f'profit_{target_profit_rate*100:.1f}pct'
                # (3) 진입저가 실시간 체크: -0.2%
                elif entry_low is not None and entry_low > 0 and c < entry_low * 0.998:
                    exit_reason = 'realtime_entry_low_break'
                else:
                    # (4) 3분봉 기준 기술적 분석 (기존 로직 유지)
                    try:
                        sell_sig = PullbackCandlePattern.generate_sell_signals(df_3min.iloc[:i+1], entry_low=entry_low)
                    except Exception:
                        sell_sig = pd.DataFrame(index=df_3min.index)
                    if not sell_sig.empty:
                        if bool(sell_sig.get('sell_bisector_break', pd.Series([False]*len(df_3min))).iloc[i]):
                            exit_reason = 'pattern_bisector_break'
                        elif bool(sell_sig.get('sell_support_break', pd.Series([False]*len(df_3min))).iloc[i]):
                            exit_reason = 'pattern_support_break'
                        elif bool(sell_sig.get('stop_entry_low_break', pd.Series([False]*len(df_3min))).iloc[i]):
                            exit_reason = 'pattern_entry_low_break'

                if exit_reason is not None:
                    # 09시 이전 매수/매도는 승패 계산에서 제외
                    buy_hour = int(entry_time.split(':')[0]) if ':' in entry_time else 0
                    sell_hour = int(hhmm.split(':')[0]) if ':' in hhmm else 0
                    
                    if buy_hour >= 9 and sell_hour >= 9:  # 09시 이후만 승패 계산에 포함
                        profit = (c - entry_price) / entry_price * 100.0 if entry_price and entry_price > 0 else 0.0
                        trades.append({
                            'buy_time': entry_time,
                            'buy_type': entry_type,
                            'buy_price': entry_price,
                            'sell_time': hhmm,
                            'sell_reason': exit_reason,
                            'sell_price': c,
                            'profit_rate': profit,
                        })
                    else:
                        # 09시 이전 거래는 기록하되 승패 계산에서 제외
                        trades.append({
                            'buy_time': entry_time,
                            'buy_type': entry_type,
                            'buy_price': entry_price,
                            'sell_time': hhmm,
                            'sell_reason': exit_reason,
                            'sell_price': c,
                            'profit_rate': 0.0,  # 승패 계산에서 제외
                            'excluded_from_stats': True,  # 통계에서 제외 표시
                        })
                    in_pos = False
                    entry_price = None
                    entry_time = None
                    entry_type = None
                    entry_low = None
                    # 손실 집계 및 진입 차단 (해제됨)
                    if profit < 0:
                        daily_loss_count += 1
                        # if daily_loss_count >= 2:
                        #     can_enter = False

    # EOD 청산
    if in_pos and entry_price is not None:
        # 1분봉 데이터가 있으면 1분봉의 마지막 가격, 없으면 3분봉 마지막 가격
        if df_1min is not None and not df_1min.empty:
            last_ts = df_1min['datetime'].iloc[-1]
            last_close = float(pd.to_numeric(df_1min['close'], errors='coerce').iloc[-1])
        else:
            last_ts = df_3min['datetime'].iloc[-1]
            closes = pd.to_numeric(df_3min['close'], errors='coerce')
            last_close = float(closes.iloc[-1]) if pd.notna(closes.iloc[-1]) else entry_price
        
        last_hhmm = pd.Timestamp(last_ts).strftime('%H:%M')
        if pd.isna(last_close):
            last_close = entry_price
            
        # 09시 이전 매수는 EOD 청산에서도 승패 계산 제외
        buy_hour = int(entry_time.split(':')[0]) if ':' in entry_time else 0
        
        if buy_hour >= 9:  # 09시 이후 매수만 승패 계산에 포함
            profit = (last_close - entry_price) / entry_price * 100.0 if entry_price and entry_price > 0 else 0.0
            trades.append({
                'buy_time': entry_time,
                'buy_type': entry_type,
                'buy_price': entry_price,
                'sell_time': last_hhmm,
                'sell_reason': 'EOD',
                'sell_price': last_close,
                'profit_rate': profit,
            })
        else:
            # 09시 이전 매수는 기록하되 승패 계산에서 제외
            trades.append({
                'buy_time': entry_time,
                'buy_type': entry_type,
                'buy_price': entry_price,
                'sell_time': last_hhmm,
                'sell_reason': 'EOD',
                'sell_price': last_close,
                'profit_rate': 0.0,  # 승패 계산에서 제외
                'excluded_from_stats': True,  # 통계에서 제외 표시
            })

    return trades


def print_report(stock_code: str, target_date: str, evaluations: List[Dict[str, object]]):
    """콘솔 요약 출력."""
    print(f"\n=== {stock_code} - {target_date} 눌림목(3분) 신호 재현 ===")
    for item in evaluations:
        t = item["time"]
        if item["has_signal"]:
            sig = ",".join(item["signal_types"]) if item["signal_types"] else "(종류 미상)"
            print(f"  {t} → ON [{sig}]")
        else:
            reasons = ", ".join(item["unmet_conditions"]) if item["unmet_conditions"] else "(사유 미상)"
            print(f"  {t} → OFF  (미충족: {reasons})")


def to_csv_rows(stock_code: str, target_date: str, evaluations: List[Dict[str, object]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for item in evaluations:
        rows.append({
            "stock_code": stock_code,
            "date": target_date,
            "time": item["time"],
            "has_signal": item["has_signal"],
            "signal_types": ",".join(item["signal_types"]) if item["signal_types"] else "",
            "unmet_conditions": ", ".join(item["unmet_conditions"]) if item["unmet_conditions"] else "",
        })
    return rows


async def run(
    date_str: str,
    codes: List[str],
    times_map: Dict[str, List[str]],
    *,
    debug_logs: bool = True,
    log_level: int = logging.INFO,
    generate_charts: bool = False,
) -> Tuple[List[Dict[str, object]], Dict[str, List[Dict[str, object]]], Dict[str, List[Dict[str, object]]], str, Dict[str, str]]:
    """메인 실행 코루틴."""
    all_rows: List[Dict[str, object]] = []
    all_signals: Dict[str, List[Dict[str, object]]] = {}
    all_trades: Dict[str, List[Dict[str, object]]] = {}
    chart_paths: Dict[str, str] = {}  # 종목별 생성된 차트 파일 경로
    # 캡처 로거(메모리 버퍼, KST 포맷)
    log_buffer = io.StringIO()
    capture_logger: Optional[logging.Logger] = None
    if debug_logs:
        capture_logger = logging.getLogger('PullbackCandlePattern')
        capture_logger.setLevel(log_level)
        capture_logger.propagate = False
        # 기존 핸들러 제거 후 메모리 핸들러만 부착
        if capture_logger.handlers:
            capture_logger.handlers.clear()
        handler = logging.StreamHandler(log_buffer)
        formatter = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        # 한국시간 변환
        try:
            def _kst_conv(secs: float):
                return datetime.fromtimestamp(secs, KST).timetuple()
            formatter.converter = _kst_conv  # type: ignore[attr-defined]
        except Exception:
            pass
        handler.setFormatter(formatter)
        capture_logger.addHandler(handler)
    
    # 차트 생성용 인스턴스 초기화 (차트 생성이 필요한 경우에만)
    chart_renderer = None
    strategy_manager = None
    signal_calculator = None
    if generate_charts:
        try:
            from visualization.chart_renderer import ChartRenderer
            from visualization.strategy_manager import StrategyManager
            from visualization.signal_calculator import SignalCalculator
            chart_renderer = ChartRenderer()
            strategy_manager = StrategyManager()
            signal_calculator = SignalCalculator()
            logger.info("📊 차트 생성 모듈 초기화 완료")
        except Exception as e:
            logger.warning(f"⚠️ 차트 생성 모듈 초기화 실패: {e}")
            generate_charts = False
    
    for code in codes:
        try:
            # 1분봉과 3분봉 데이터를 모두 가져오기
            df_1min, df_3min = await fetch_and_prepare_data(code, date_str)
            evals = evaluate_signals_at_times(
                df_3min,
                date_str,
                times_map.get(code, []),
                logger=capture_logger,
                debug_logs=debug_logs,
                log_level=log_level,
            )
            print_report(code, date_str, evals)
            all_rows.extend(to_csv_rows(code, date_str, evals))
            # 전체 매수신호 추출
            signals_full = list_all_buy_signals(df_3min, logger=capture_logger) if df_3min is not None else []
            all_signals[code] = signals_full
            # 체결 시뮬레이션 (1분봉 데이터도 전달)
            trades = simulate_trades(df_3min, df_1min, logger=capture_logger) if df_3min is not None else []
            all_trades[code] = trades
            
            # 차트 생성 (요청된 경우에만)
            if generate_charts and df_3min is not None:
                try:
                    chart_path = generate_chart_for_stock(
                        stock_code=code,
                        target_date=date_str,
                        df_3min=df_3min,
                        df_1min=df_1min,
                        chart_renderer=chart_renderer,
                        strategy_manager=strategy_manager,
                        signal_calculator=signal_calculator,
                        logger=capture_logger or logger
                    )
                    if chart_path:
                        chart_paths[code] = chart_path
                        logger.info(f"📊 {code} 차트 생성 완료: {chart_path}")
                except Exception as chart_err:
                    logger.error(f"❌ {code} 차트 생성 오류: {chart_err}")
                    chart_paths[code] = ""
        except Exception as e:
            logger.error(f"{code} 처리 오류: {e}")
            # 실패한 종목도 표에 기록
            for t in times_map.get(code, []):
                all_rows.append({
                    "stock_code": code,
                    "date": date_str,
                    "time": t,
                    "has_signal": False,
                    "signal_types": "",
                    "unmet_conditions": f"에러: {e}",
                })
            all_signals[code] = []
            all_trades[code] = []
            # 실패한 종목의 차트 경로도 빈 문자열로 등록
            if generate_charts:
                chart_paths[code] = ""
    # 캡처된 로그 텍스트
    logs_text = log_buffer.getvalue() if debug_logs else ""
    return all_rows, all_signals, all_trades, logs_text, chart_paths


def main():
    parser = argparse.ArgumentParser(description="눌림목(3분) 매수신호 재현 리포트")
    parser.add_argument("--date", required=False, default=None, help="대상 날짜 (YYYYMMDD)")
    parser.add_argument("--codes", required=False, default=None, help="종목코드 콤마구분 예: 034230,078520")
    parser.add_argument("--times", required=False, default=None, help="종목별 확인시각 매핑 예: 034230=14:39;078520=11:33")
    parser.add_argument("--export", choices=["csv", "txt"], default=None, help="결과를 파일로 저장 (csv|txt)")
    parser.add_argument("--csv-path", default="signal_replay.csv", help="CSV 저장 경로 (기본: signal_replay.csv)")
    parser.add_argument("--txt-path", default="signal_replay.txt", help="TXT 저장 경로 (기본: signal_replay.txt)")
    parser.add_argument("--charts", action="store_true", help="3분봉 차트 생성 (거래량, 이등분선, 매수/매도 포인트 포함)")

    args = parser.parse_args()

    def normalize_code(code: str) -> str:
        return str(code).strip().zfill(6)

    # 기본값 (요청하신 2025-08-08, 4개 종목/시각)
    #DEFAULT_DATE = "20250814"
    #DEFAULT_CODES = "086280,047770,026040,107600,214450,033340,230360,226950,336260,298380,208640,445680,073010,084370,009270,017510,095610,240810,332290,408900,077970,078520,460930"
    #DEFAULT_CODES = "336260"

    #DEFAULT_DATE = "20250813"
    #DEFAULT_CODES = "034220"
    #DEFAULT_CODES = "036200,026040,240810,097230,034220,213420,090460,036010,104040,087010"

    #DEFAULT_DATE = "20250818"
    #DEFAULT_CODES = "078520,104040,298380"

    #DEFAULT_DATE = "20250819"
    #DEFAULT_CODES = "019180,107600,207760,240810,333430,332290,007980,473980,475960,187660"

    #DEFAULT_DATE = "20250820"
    #DEFAULT_CODES = "013310,103840,114450,180400,192250,007980,019180,408900"

    #DEFAULT_DATE = "20250821"
    #DEFAULT_CODES = "180400,318160,019180,134580,049470,160550,310200,207760,007980,006910,017510,138040,114190,005670,464580,475960"

    DEFAULT_DATE = "20250822"
    DEFAULT_CODES = "098070,333430,475960,049470,464580,083650,126340,103840,318160,249420"

    DEFAULT_TIMES = ""

    date_str: str = (args.date or DEFAULT_DATE).strip()
    codes_input = args.codes or DEFAULT_CODES
    times_input = args.times or DEFAULT_TIMES

    codes: List[str] = [normalize_code(c) for c in codes_input.split(",") if str(c).strip()]
    # 중복 제거(입력 순서 유지)
    codes = list(dict.fromkeys(codes))
    raw_times_map: Dict[str, List[str]] = parse_times_mapping(times_input)
    # 키도 6자리로 정규화
    times_map: Dict[str, List[str]] = {normalize_code(k): v for k, v in raw_times_map.items()}

    # 코드 집합: DEFAULT_CODES + DEFAULT_TIMES에 언급된 종목들의 합집합(순서: codes → times)
    codes_union: List[str] = list(codes)
    for k in times_map.keys():
        if k not in codes_union:
            codes_union.append(k)
    # 누락된 종목 키에 대해 빈 리스트 보정
    for c in codes_union:
        times_map.setdefault(c, [])

    logger.info(f"대상 날짜: {date_str}")
    logger.info(f"대상 종목: {codes_union}")
    logger.info(f"시각 매핑: {times_map}")

    # KIS API 인증 선행 (실데이터 조회 필요)
    api_manager = KISAPIManager()
    if not api_manager.initialize():
        print("\n❌ KIS API 인증/초기화 실패. key.ini/환경설정 확인 후 다시 시도하세요.")
        sys.exit(1)

    # 기본 로깅 설정을 한 곳에서 관리
    DEFAULT_LOG_DEBUG = True
    DEFAULT_LOG_LEVEL = 'INFO'
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
    }
    log_level = level_map.get(DEFAULT_LOG_LEVEL.upper(), logging.INFO)

    # 차트 생성 옵션 확인
    generate_charts = args.charts
    if generate_charts:
        logger.info("📊 차트 생성 모드 활성화")

    rows, all_signals, all_trades, logs_text, chart_paths = asyncio.run(
        run(
            date_str,
            codes_union,
            times_map,
            debug_logs=DEFAULT_LOG_DEBUG,
            log_level=log_level,
            generate_charts=generate_charts,
        )
    )

    if args.export == "csv":
        try:
            df = pd.DataFrame(rows)
            df.to_csv(args.csv_path, index=False, encoding="utf-8-sig")
            print(f"\n📄 CSV 저장 완료: {args.csv_path} ({len(df)}행)")
        except Exception as e:
            print(f"\n❌ CSV 저장 실패: {e}")
    elif args.export == "txt":
        try:
            # 종목별로 그룹핑하여 텍스트 리포트 구성 (코드 순서 유지)
            from collections import defaultdict
            code_to_rows = defaultdict(list)
            for r in rows:
                code_to_rows[r.get("stock_code", "")] .append(r)

            lines: list[str] = []
            # 전체 승패 요약 (profit_rate > 0 승, < 0 패, =0 제외, 09시 이전 거래 제외)
            total_wins = 0
            total_losses = 0
            for _code, _trades in all_trades.items():
                for tr in _trades:
                    # 09시 이전 거래는 승패 계산에서 제외
                    if tr.get('excluded_from_stats', False):
                        continue
                    try:
                        pr = float(tr.get('profit_rate', 0.0))
                    except Exception:
                        pr = 0.0
                    if pr > 0:
                        total_wins += 1
                    elif pr < 0:
                        total_losses += 1
            lines.append(f"=== 총 승패: {total_wins}승 {total_losses}패 ===")
            lines.append("")
            for code in codes_union:
                lines.append(f"=== {code} - {date_str} 눌림목(3분) 신호 재현 ===")
                # 종목별 승패 요약 (09시 이전 거래 제외)
                code_wins = 0
                code_losses = 0
                for tr in all_trades.get(code, []):
                    # 09시 이전 거래는 승패 계산에서 제외
                    if tr.get('excluded_from_stats', False):
                        continue
                    try:
                        pr = float(tr.get('profit_rate', 0.0))
                    except Exception:
                        pr = 0.0
                    if pr > 0:
                        code_wins += 1
                    elif pr < 0:
                        code_losses += 1
                lines.append(f"  승패: {code_wins}승 {code_losses}패")
                # 입력 시각 순서를 유지하여 출력
                for t in times_map.get(code, []):
                    # 해당 시각의 레코드 찾기
                    rec = next((x for x in code_to_rows.get(code, []) if x.get("time") == t), None)
                    if rec is None:
                        lines.append(f"  {t} → OFF  (미충족: 시각 매칭 실패)")
                        continue
                    if bool(rec.get("has_signal", False)):
                        sig = rec.get("signal_types", "")
                        sig_disp = sig if sig else "(종류 미상)"
                        lines.append(f"  {t} → ON [{sig_disp}]")
                    else:
                        reasons = rec.get("unmet_conditions", "")
                        reasons_disp = reasons if reasons else "(사유 미상)"
                        lines.append(f"  {t} → OFF  (미충족: {reasons_disp})")
                # 전체 매매신호 요약
                lines.append("  매매신호:")
                signals_list = all_signals.get(code, [])
                if signals_list:
                    for s in signals_list:
                        lines.append(f"    {s['time']} [{s['types']}]")
                else:
                    lines.append("    없음")
                # 체결 시뮬레이션 요약 (매수/매도/%)
                lines.append("  체결 시뮬레이션:")
                trades_list = all_trades.get(code, [])
                if trades_list:
                    for tr in trades_list:
                        bt = tr.get('buy_time', '')
                        btype = tr.get('buy_type', '')
                        bp = tr.get('buy_price', 0.0)
                        st = tr.get('sell_time', '')
                        srsn = tr.get('sell_reason', '')
                        sp = tr.get('sell_price', 0.0)
                        pr = float(tr.get('profit_rate', 0.0))
                        lines.append(f"    {bt} 매수[{btype}] @{bp:,.0f} → {st} 매도[{srsn}] @{sp:,.0f} ({pr:+.2f}%)")
                else:
                    lines.append("    없음")
                lines.append("")

            # 캡처 로그를 텍스트 끝에 덧붙임
            if logs_text and logs_text.strip():
                lines.append("=== Debug Logs (KST) ===")
                lines.extend([ln for ln in logs_text.splitlines()])
            content = "\n".join(lines).rstrip() + "\n"
            with open(args.txt_path, "w", encoding="utf-8-sig") as f:
                f.write(content)
            print(f"\n📄 TXT 저장 완료: {args.txt_path}")
        except Exception as e:
            print(f"\n❌ TXT 저장 실패: {e}")

    # 차트 생성 결과 출력
    if generate_charts:
        print(f"\n📊 차트 생성 결과:")
        chart_success_count = sum(1 for path in chart_paths.values() if path)
        print(f"  - 전체 종목: {len(codes_union)}개")
        print(f"  - 차트 생성 성공: {chart_success_count}개")
        print(f"  - 차트 생성 실패: {len(codes_union) - chart_success_count}개")
        
        if chart_success_count > 0:
            print(f"\n📁 생성된 차트 파일:")
            for code, path in chart_paths.items():
                if path:
                    print(f"  - {code}: {path}")


if __name__ == "__main__":
    main()


