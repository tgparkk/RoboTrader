"""
가격 위치 기반 전략 (Price Position Strategy)

데이터 분석 기반으로 발견된 수익 패턴:
- 시가 대비 1~3% 상승 구간에서 진입
- 월~금 전체 거래
- 9시~12시 사이 진입
- 손절 -4.0%, 익절 +5.0%
- 진입 전 변동성 > 0.8% 제외, 20봉 모멘텀 > +2.0% 제외
"""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import pandas as pd


class PricePositionStrategy:
    """
    가격 위치 기반 매매 전략

    기존 눌림목 패턴과 무관하게 순수 데이터 분석으로 발견된 규칙
    """

    @staticmethod
    def _load_default_config():
        """설정 파일에서 기본값 로드"""
        import json, os
        from config.strategy_settings import StrategySettings
        pp = StrategySettings.PricePosition

        config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'trading_config.json')
        try:
            with open(config_path, 'r') as f:
                tc = json.load(f)
            rm = tc.get('risk_management', {})
            stop_loss = -rm.get('stop_loss_ratio', 0.05) * 100
            take_profit = rm.get('take_profit_ratio', 0.06) * 100
        except Exception:
            stop_loss = -5.0
            take_profit = 6.0

        return {
            'min_pct_from_open': pp.MIN_PCT_FROM_OPEN,
            'max_pct_from_open': pp.MAX_PCT_FROM_OPEN,
            'entry_start_hour': pp.ENTRY_START_HOUR,
            'entry_end_hour': pp.ENTRY_END_HOUR,
            'allowed_weekdays': list(pp.ALLOWED_WEEKDAYS),
            'stop_loss_pct': stop_loss,
            'take_profit_pct': take_profit,
            'one_trade_per_stock_per_day': pp.ONE_TRADE_PER_STOCK_PER_DAY,
            'max_pre_volatility': pp.MAX_PRE_VOLATILITY,
            'max_pre20_momentum': pp.MAX_PRE20_MOMENTUM,
            'min_rising_candles': pp.MIN_RISING_CANDLES,
        }

    # 기본 설정값 (설정 파일에서 로드, 클래스 초기화 시 사용)
    DEFAULT_CONFIG = None  # __init__에서 lazy 로드

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None):
        """
        전략 초기화

        Args:
            config: 사용자 정의 설정 (없으면 기본값 사용)
            logger: 로거 객체
        """
        if PricePositionStrategy.DEFAULT_CONFIG is None:
            PricePositionStrategy.DEFAULT_CONFIG = self._load_default_config()
        self.config = {**PricePositionStrategy.DEFAULT_CONFIG, **(config or {})}
        self.logger = logger

        # 당일 거래 기록 (종목별)
        self.daily_trades: Dict[str, set] = {}  # {trade_date: {stock_code, ...}}

    def _log(self, message: str, level: str = 'info'):
        """로그 출력"""
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message)
        else:
            print(f"[{level.upper()}] {message}")

    def reset_daily_trades(self, trade_date: str = None):
        """일별 거래 기록 초기화"""
        if trade_date:
            self.daily_trades.pop(trade_date, None)
        else:
            self.daily_trades.clear()

    def check_entry_conditions(
        self,
        stock_code: str,
        current_price: float,
        day_open: float,
        current_time: str,  # "HHMMSS" 또는 "HHMM" 형식
        trade_date: str,    # "YYYYMMDD" 형식
        weekday: int = None,  # 0=월, 4=금 (None이면 trade_date에서 계산)
    ) -> Tuple[bool, str]:
        """
        진입 조건 확인

        Args:
            stock_code: 종목 코드
            current_price: 현재가
            day_open: 당일 시가
            current_time: 현재 시간 (HHMMSS 또는 HHMM)
            trade_date: 거래일 (YYYYMMDD)
            weekday: 요일 (0=월요일, 4=금요일)

        Returns:
            (진입 가능 여부, 사유 메시지)
        """
        # 시가 검증
        if day_open <= 0:
            return False, "시가 데이터 없음"

        # 요일 확인
        if weekday is None:
            try:
                dt = datetime.strptime(trade_date, '%Y%m%d')
                weekday = dt.weekday()
            except:
                return False, "날짜 파싱 실패"

        if weekday not in self.config['allowed_weekdays']:
            weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            return False, f"허용되지 않은 요일: {weekday_names[weekday]}"

        # 시간 확인
        try:
            hour = int(str(current_time)[:2])
        except:
            return False, "시간 파싱 실패"

        if hour < self.config['entry_start_hour']:
            return False, f"{self.config['entry_start_hour']}시 이전"

        if hour >= self.config['entry_end_hour']:
            return False, f"{self.config['entry_end_hour']}시 이후"

        # 시가 대비 상승률 확인
        pct_from_open = (current_price / day_open - 1) * 100

        if pct_from_open < self.config['min_pct_from_open']:
            return False, f"시가 대비 {pct_from_open:.1f}% < {self.config['min_pct_from_open']}%"

        if pct_from_open >= self.config['max_pct_from_open']:
            return False, f"시가 대비 {pct_from_open:.1f}% >= {self.config['max_pct_from_open']}%"

        # 당일 중복 거래 확인
        if self.config['one_trade_per_stock_per_day']:
            if trade_date in self.daily_trades:
                if stock_code in self.daily_trades[trade_date]:
                    return False, "당일 이미 거래함"

        return True, f"진입 조건 충족 (시가+{pct_from_open:.1f}%)"

    def check_advanced_conditions(
        self,
        df: pd.DataFrame,
        candle_idx: int,
    ) -> Tuple[bool, str]:
        """
        고급 진입 필터 (캔들 데이터 기반)

        Args:
            df: 분봉 데이터프레임
            candle_idx: 현재 캔들 인덱스

        Returns:
            (통과 여부, 사유 메시지)
        """
        # 진입 전 10봉 변동성 체크
        max_vol = self.config.get('max_pre_volatility')
        if max_vol is not None:
            pre_start = max(0, candle_idx - 10)
            pre_candles = df.iloc[pre_start:candle_idx]
            if len(pre_candles) > 0:
                pre_volatility = ((pre_candles['high'] - pre_candles['low']) / pre_candles['low'] * 100).mean()
                if pre_volatility > max_vol:
                    return False, f"진입전 변동성 {pre_volatility:.2f}% > {max_vol}%"

        # 진입 전 20봉 모멘텀 체크
        max_mom = self.config.get('max_pre20_momentum')
        if max_mom is not None:
            pre20_start = max(0, candle_idx - 20)
            pre20_candles = df.iloc[pre20_start:candle_idx]
            if len(pre20_candles) >= 2:
                pre20_momentum = (pre20_candles.iloc[-1]['close'] / pre20_candles.iloc[0]['open'] - 1) * 100
                if pre20_momentum > max_mom:
                    return False, f"20봉 모멘텀 {pre20_momentum:+.2f}% > +{max_mom}%"

        # 방향성 필터: 직전 N봉 대비 상승 확인
        rising_n = self.config.get('min_rising_candles', 0)
        if rising_n and rising_n > 0:
            if candle_idx < rising_n:
                return False, f"방향성 필터: 캔들 부족 ({candle_idx+1}/{rising_n}봉)"
            past_close = df.iloc[candle_idx - rising_n]['close']
            current_close = df.iloc[candle_idx]['close']
            if past_close <= 0 or current_close <= 0:
                return False, f"방향성 필터: 유효하지 않은 가격 데이터"
            if current_close < past_close:
                pct_change = (current_close / past_close - 1) * 100
                return False, f"방향성 필터: {rising_n}봉전 대비 {pct_change:+.2f}% (상승 필요)"

        return True, "고급 필터 통과"

    def record_trade(self, stock_code: str, trade_date: str):
        """거래 기록"""
        if trade_date not in self.daily_trades:
            self.daily_trades[trade_date] = set()
        self.daily_trades[trade_date].add(stock_code)

    def check_exit_conditions(
        self,
        entry_price: float,
        current_high: float,
        current_low: float,
        current_close: float,
    ) -> Tuple[bool, str, float]:
        """
        청산 조건 확인

        Args:
            entry_price: 진입가
            current_high: 현재 캔들 고가
            current_low: 현재 캔들 저가
            current_close: 현재 캔들 종가

        Returns:
            (청산 여부, 청산 사유, 수익률)
        """
        if entry_price <= 0:
            return False, "진입가 없음", 0.0

        # 익절 체크 (고가 기준)
        high_pnl = (current_high / entry_price - 1) * 100
        if high_pnl >= self.config['take_profit_pct']:
            return True, "익절", self.config['take_profit_pct']

        # 손절 체크 (저가 기준)
        low_pnl = (current_low / entry_price - 1) * 100
        if low_pnl <= self.config['stop_loss_pct']:
            return True, "손절", self.config['stop_loss_pct']

        return False, "홀딩", (current_close / entry_price - 1) * 100

    def simulate_trade(
        self,
        df: pd.DataFrame,
        entry_idx: int,
        max_holding_minutes: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        진입 후 거래 시뮬레이션

        Args:
            df: 분봉 데이터프레임 (columns: open, high, low, close, time, ...)
            entry_idx: 진입 캔들 인덱스
            max_holding_minutes: 최대 보유 시간(분). 0이면 제한 없음.

        Returns:
            거래 결과 딕셔너리 또는 None
        """
        if entry_idx + 1 >= len(df) - 5:
            return None

        # 신호 캔들 확인 후 다음 캔들 시가에 체결 (현실적 시뮬레이션)
        entry_price = df.iloc[entry_idx + 1]['open']
        entry_time = df.iloc[entry_idx + 1]['time']

        if entry_price <= 0:
            return None

        # 이후 캔들 검사
        max_profit_pct = 0.0
        min_profit_pct = 0.0
        for i in range(entry_idx + 1, len(df)):
            row = df.iloc[i]
            holding_candles = i - entry_idx

            # 최대 보유시간 초과 시 강제 청산
            if max_holding_minutes > 0 and holding_candles > max_holding_minutes:
                time_pnl = (row['close'] / entry_price - 1) * 100
                return {
                    'result': 'WIN' if time_pnl > 0 else 'LOSS',
                    'pnl': time_pnl,
                    'exit_reason': '시간청산',
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                    'holding_candles': holding_candles,
                    'max_profit_pct': round(max_profit_pct, 2),
                    'min_profit_pct': round(min_profit_pct, 2),
                }

            # 장중 최고/최저 수익률 추적
            high_pnl = (row['high'] / entry_price - 1) * 100
            low_pnl = (row['low'] / entry_price - 1) * 100
            if high_pnl > max_profit_pct:
                max_profit_pct = high_pnl
            if low_pnl < min_profit_pct:
                min_profit_pct = low_pnl

            should_exit, reason, pnl = self.check_exit_conditions(
                entry_price=entry_price,
                current_high=row['high'],
                current_low=row['low'],
                current_close=row['close'],
            )

            if should_exit:
                return {
                    'result': 'WIN' if pnl > 0 else 'LOSS',
                    'pnl': pnl,
                    'exit_reason': reason,
                    'entry_time': entry_time,
                    'exit_time': row['time'],
                    'entry_price': entry_price,
                    'holding_candles': holding_candles,
                    'max_profit_pct': round(max_profit_pct, 2),
                    'min_profit_pct': round(min_profit_pct, 2),
                }

        # 장 마감 시 청산
        last_row = df.iloc[-1]
        last_pnl = (last_row['close'] / entry_price - 1) * 100

        return {
            'result': 'WIN' if last_pnl > 0 else 'LOSS',
            'pnl': last_pnl,
            'exit_reason': '장마감',
            'entry_time': entry_time,
            'exit_time': last_row['time'],
            'entry_price': entry_price,
            'holding_candles': len(df) - 1 - entry_idx,
            'max_profit_pct': round(max_profit_pct, 2),
            'min_profit_pct': round(min_profit_pct, 2),
        }

    def get_strategy_info(self) -> Dict[str, Any]:
        """전략 정보 반환"""
        weekday_names = ['월', '화', '수', '목', '금']
        allowed_days = [weekday_names[d] for d in self.config['allowed_weekdays']]

        return {
            'name': 'PricePositionStrategy',
            'description': '가격 위치 기반 전략 (데이터 분석 기반)',
            'entry_conditions': {
                'pct_from_open': f"{self.config['min_pct_from_open']}% ~ {self.config['max_pct_from_open']}%",
                'time_range': f"{self.config['entry_start_hour']}시 ~ {self.config['entry_end_hour']}시",
                'weekdays': ', '.join(allowed_days),
            },
            'exit_conditions': {
                'stop_loss': f"{self.config['stop_loss_pct']}%",
                'take_profit': f"+{self.config['take_profit_pct']}%",
            },
            'expected_performance': {
                'win_rate': '58.5%',
                'profit_loss_ratio': '1.4:1',
            }
        }

    def __repr__(self):
        return f"PricePositionStrategy(config={self.config})"
