"""
시뮬레이션 거래 로직 모듈

signal_replay.py에서 분리된 거래 시뮬레이션 로직
"""
from typing import Dict, List, Optional, Tuple
import pandas as pd
from datetime import datetime, timedelta
import logging


class SignalFilterChain:
    """신호 필터링 체인 클래스"""

    def __init__(self, stock_code: str, logger: Optional[logging.Logger] = None):
        self.stock_code = stock_code
        self.logger = logger

    def check_selection_date(self, signal_completion_time: datetime,
                             selection_date: Optional[str]) -> Tuple[bool, str]:
        """selection_date 이후 신호인지 확인"""
        if not selection_date:
            return True, ""

        try:
            if len(selection_date) >= 19:
                selection_dt = datetime.strptime(selection_date[:19], '%Y-%m-%d %H:%M:%S')
            elif len(selection_date) >= 16:
                selection_dt = datetime.strptime(selection_date[:16], '%Y-%m-%d %H:%M')
            else:
                selection_dt = datetime.strptime(selection_date[:10], '%Y-%m-%d')

            if signal_completion_time < selection_dt:
                return False, f"selection_date({selection_dt.strftime('%H:%M')}) 이전 신호"

        except Exception as e:
            if self.logger:
                self.logger.warning(f"selection_date 파싱 실패: {e}")

        return True, ""

    def check_duplicate_candle(self, signal_datetime: datetime,
                               last_signal_candle_time: Optional[datetime]) -> Tuple[bool, datetime]:
        """동일 캔들 중복 신호 차단"""
        minute_normalized = (signal_datetime.minute // 3) * 3
        normalized_signal_time = signal_datetime.replace(minute=minute_normalized, second=0, microsecond=0)

        if last_signal_candle_time and last_signal_candle_time == normalized_signal_time:
            return False, normalized_signal_time

        return True, normalized_signal_time

    def check_cooldown(self, signal_completion_time: datetime,
                       cooldown_end_time: Optional[datetime]) -> Tuple[bool, float]:
        """쿨다운 체크"""
        if cooldown_end_time and signal_completion_time < cooldown_end_time:
            remaining_minutes = (cooldown_end_time - signal_completion_time).total_seconds() / 60
            return False, remaining_minutes
        return True, 0.0

    def check_position(self, signal_completion_time: datetime,
                       current_position: Optional[Dict]) -> bool:
        """포지션 보유 중인지 체크"""
        if current_position is not None:
            if signal_completion_time < current_position['sell_time']:
                return False
        return True

    def check_buy_cutoff(self, signal_completion_time: datetime) -> bool:
        """매수 중단 시간 체크"""
        from config.market_hours import MarketHours
        market_hours = MarketHours.get_market_hours('KRX', signal_completion_time)
        buy_cutoff_hour = market_hours['buy_cutoff_hour']

        if signal_completion_time.hour >= buy_cutoff_hour:
            return False
        return True


class FilterApplicationManager:
    """필터 적용 관리 클래스"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger

    def apply_daily_filter(self, daily_pattern_filter, stock_code: str,
                           signal_completion_time: datetime) -> Tuple[bool, str]:
        """일봉 필터 적용"""
        if not daily_pattern_filter:
            return True, ""

        try:
            signal_date = signal_completion_time.strftime("%Y%m%d")
            signal_time = signal_completion_time.strftime("%H:%M")

            filter_result = daily_pattern_filter.apply_filter(
                stock_code, signal_date, signal_time
            )

            if not filter_result.passed:
                return False, filter_result.reason

            return True, filter_result.reason

        except Exception as e:
            if self.logger:
                self.logger.warning(f"[{stock_code}] 일봉 필터 적용 실패: {e}")
            return True, ""  # 오류 시 통과

    def apply_ml_filter(self, ml_model, ml_feature_names, ml_threshold: float,
                        pattern_data_cache: Optional[Dict], stock_code: str,
                        signal_completion_time: datetime, signal: Dict) -> Tuple[bool, float]:
        """ML 필터 적용"""
        if ml_model is None or ml_feature_names is None:
            return True, 0.0

        try:
            signal_time_key = signal_completion_time.strftime('%H:%M')
            pattern_data = self._find_pattern_data(
                pattern_data_cache, stock_code, signal_completion_time
            )

            if pattern_data:
                from apply_ml_filter import predict_win_probability
                win_prob, status = predict_win_probability(
                    ml_model, ml_feature_names, signal, pattern_data
                )

                if win_prob < ml_threshold:
                    return False, win_prob

                return True, win_prob

            return True, 0.0

        except Exception as e:
            if self.logger:
                self.logger.warning(f"[{stock_code}] ML 필터 적용 실패: {e}")
            return True, 0.0

    def apply_advanced_filter(self, advanced_filter_manager, df_3min: pd.DataFrame,
                              pattern_data_cache: Optional[Dict], stock_code: str,
                              signal_completion_time: datetime, signal: Dict) -> Tuple[bool, str]:
        """고급 필터 적용"""
        if not advanced_filter_manager:
            return True, ""

        try:
            adv_pattern_data = self._find_pattern_data(
                pattern_data_cache, stock_code, signal_completion_time
            )

            # OHLCV 시퀀스 추출
            ohlcv_sequence = self._extract_ohlcv_sequence(df_3min, signal['index'])

            # 패턴 데이터에서 기술 지표 추출
            rsi, volume_ma_ratio, pattern_stages = self._extract_technical_data(adv_pattern_data)

            trade_date = signal_completion_time.strftime('%Y%m%d')

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
                return False, f"{adv_result.blocked_by} - {adv_result.blocked_reason}"

            return True, ""

        except Exception as e:
            if self.logger:
                self.logger.warning(f"[{stock_code}] 고급 필터 적용 실패: {e}")
            return True, ""

    def _find_pattern_data(self, pattern_data_cache: Optional[Dict],
                           stock_code: str, signal_completion_time: datetime) -> Optional[Dict]:
        """패턴 데이터 캐시에서 해당 신호의 패턴 찾기"""
        if not pattern_data_cache:
            return None

        for pattern_key, pdata in pattern_data_cache.items():
            if stock_code in pattern_key:
                pattern_signal_time = pdata.get('signal_time', '')
                if pattern_signal_time:
                    try:
                        pst = datetime.strptime(pattern_signal_time, '%Y-%m-%d %H:%M:%S')
                        time_diff = abs((pst - signal_completion_time).total_seconds())
                        if time_diff <= 180:  # 3분 이내
                            return pdata
                    except:
                        pass
        return None

    def _extract_ohlcv_sequence(self, df_3min: pd.DataFrame, signal_index: int) -> List[Dict]:
        """3분봉에서 OHLCV 시퀀스 추출"""
        ohlcv_sequence = []
        start_idx = max(0, signal_index - 4)
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

        return ohlcv_sequence

    def _extract_technical_data(self, pattern_data: Optional[Dict]) -> Tuple:
        """패턴 데이터에서 기술 지표 추출"""
        rsi = None
        volume_ma_ratio = None
        pattern_stages = None

        if pattern_data:
            signal_snapshot = pattern_data.get('signal_snapshot', {})
            tech = signal_snapshot.get('technical_indicators_3min', {})
            rsi = tech.get('rsi_14')
            volume_ma_ratio = tech.get('volume_vs_ma_ratio')
            pattern_stages = pattern_data.get('pattern_stages')

        return rsi, volume_ma_ratio, pattern_stages


class TradeSellSimulator:
    """매도 시뮬레이션 클래스"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger

    def simulate_sell(self, df_1min: pd.DataFrame, buy_time: datetime, buy_price: float,
                      target_profit_rate: float, stop_loss_rate: float,
                      entry_low: float, stock_code: str) -> Dict:
        """매도 시뮬레이션 실행"""
        remaining_data = df_1min[df_1min['datetime'] > buy_time].copy()

        if remaining_data.empty:
            return {
                'sell_time': None,
                'sell_price': 0,
                'max_profit_rate': 0.0,
                'max_loss_rate': 0.0,
                'reason': '거래시간 종료',
                'status': 'open'
            }

        sell_time = None
        sell_price = 0
        max_profit_rate = 0.0
        max_loss_rate = 0.0
        sell_reason = ""

        # 가격 목표
        profit_target_price = buy_price * (1.0 + target_profit_rate)
        stop_loss_target_price = buy_price * (1.0 - stop_loss_rate)

        for i, row in remaining_data.iterrows():
            candle_time = row['datetime']
            candle_high = row['high']
            candle_low = row['low']
            candle_close = row['close']

            # 장마감 시간 매도
            from config.market_hours import MarketHours
            market_hours = MarketHours.get_market_hours('KRX', candle_time)
            eod_hour = market_hours['eod_liquidation_hour']
            eod_minute = market_hours['eod_liquidation_minute']

            if candle_time.hour >= eod_hour and candle_time.minute >= eod_minute:
                return {
                    'sell_time': candle_time,
                    'sell_price': candle_close,
                    'max_profit_rate': max_profit_rate,
                    'max_loss_rate': max_loss_rate,
                    'reason': f'market_close_{eod_hour}h',
                    'status': 'market_close'
                }

            # 수익률 추적
            high_profit_rate = ((candle_high - buy_price) / buy_price) * 100
            low_profit_rate = ((candle_low - buy_price) / buy_price) * 100

            if high_profit_rate > max_profit_rate:
                max_profit_rate = high_profit_rate
            if low_profit_rate < max_loss_rate:
                max_loss_rate = low_profit_rate

            # 익절 체크
            if candle_high >= profit_target_price:
                return {
                    'sell_time': candle_time,
                    'sell_price': profit_target_price,
                    'max_profit_rate': max_profit_rate,
                    'max_loss_rate': max_loss_rate,
                    'reason': f'profit_{target_profit_rate*100:.1f}pct',
                    'status': 'profit'
                }

            # 손절 체크
            if candle_low <= stop_loss_target_price:
                return {
                    'sell_time': candle_time,
                    'sell_price': stop_loss_target_price,
                    'max_profit_rate': max_profit_rate,
                    'max_loss_rate': max_loss_rate,
                    'reason': f'stop_loss_{stop_loss_rate*100:.1f}pct',
                    'status': 'stop_loss'
                }

            # 3분봉 기반 기술적 분석 매도 신호
            if candle_time.minute % 3 == 0:
                technical_result = self._check_technical_sell(
                    df_1min, candle_time, entry_low
                )
                if technical_result['should_sell']:
                    return {
                        'sell_time': candle_time,
                        'sell_price': candle_close,
                        'max_profit_rate': max_profit_rate,
                        'max_loss_rate': max_loss_rate,
                        'reason': technical_result['reason'],
                        'status': 'technical'
                    }

        # 루프 완료 후 매도 없음
        return {
            'sell_time': None,
            'sell_price': 0,
            'max_profit_rate': max_profit_rate,
            'max_loss_rate': max_loss_rate,
            'reason': '조건 미충족',
            'status': 'open'
        }

    def _check_technical_sell(self, df_1min: pd.DataFrame,
                              current_time: datetime, entry_low: float) -> Dict:
        """3분봉 기반 기술적 분석 매도 신호"""
        try:
            data_until_now = df_1min[df_1min['datetime'] <= current_time]
            if len(data_until_now) < 15:
                return {'should_sell': False, 'reason': ''}

            from core.timeframe_converter import TimeFrameConverter
            data_3min_current = TimeFrameConverter.convert_to_3min_data(data_until_now)

            if data_3min_current is None or len(data_3min_current) < 5:
                return {'should_sell': False, 'reason': ''}

            technical_sell, technical_reason = self._check_technical_sell_signals(
                data_3min_current, entry_low
            )

            return {'should_sell': technical_sell, 'reason': technical_reason}

        except Exception:
            return {'should_sell': False, 'reason': ''}

    def _check_technical_sell_signals(self, data_3min: pd.DataFrame, entry_low: float) -> Tuple[bool, str]:
        """3분봉 기반 기술적 분석 매도 신호 계산 (간소화 버전)"""
        try:
            if data_3min is None or len(data_3min) < 5:
                return False, ""

            # 마지막 5개 봉 기준으로 분석
            recent_5 = data_3min.tail(5)
            last_candle = recent_5.iloc[-1]

            # 1. 연속 3개 음봉 체크
            recent_3 = recent_5.tail(3)
            bearish_count = sum(
                row['close'] < row['open'] for _, row in recent_3.iterrows()
            )

            if bearish_count >= 3:
                return True, "bearish_3_candles"

            # 2. 진입저가 이탈 체크
            if entry_low > 0 and last_candle['close'] < entry_low * 0.998:
                return True, "entry_low_break"

            return False, ""

        except Exception:
            return False, ""
