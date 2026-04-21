"""
종가매매(오버나이트) 전략 - ClosingTradeStrategy

멀티버스 시뮬 검증 (2025-04~2026-04, 보수화·자본제약):
  +53.7% / MDD 3.56% / 승률 60.6% / 404건 / gap_down_rate 4.93%
최근 1개월(2026-04): +6.56%

진입:
  - 시간창: 14:00~14:20
  - 신호 (prev_body_momentum):
    1) 전일 양봉 몸통 ≥ 1.0%
    2) 당일 최저점 시가 대비 ≥ -3%
    3) 14:50 close > 당일 VWAP
    4) 14:50 close > 당일 시가 (본전 이상)
  * 실거래에서는 14:00~14:20 진입 시점의 현재가로 평가 (14:50 대신 현재 분봉 기준)

청산:
  - 장중에는 절대 매도 신호 생성 X (오버나이트 홀드)
  - 익일 09:00 시장가 매도 (main.py에서 별도 트리거)

trading_decision_engine 전략 공통 인터페이스 유지.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd


class ClosingTradeStrategy:
    """오버나이트 종가매매 전략"""

    DEFAULT_CONFIG = None  # lazy 로드

    @staticmethod
    def _load_default_config():
        from config.strategy_settings import StrategySettings
        ct = StrategySettings.ClosingTrade
        return {
            'entry_hhmm_start': ct.ENTRY_HHMM_START,
            'entry_hhmm_end': ct.ENTRY_HHMM_END,
            'min_prev_body_pct': ct.MIN_PREV_BODY_PCT,
            'max_day_decline_pct': ct.MAX_DAY_DECLINE_PCT,
            'require_vwap_above': ct.REQUIRE_VWAP_ABOVE,
            'min_gap_pct': ct.MIN_GAP_PCT,
            'max_gap_pct': ct.MAX_GAP_PCT,
            'max_abs_gap_pct': ct.MAX_ABS_GAP_PCT,
            'min_gap_down_pct': ct.MIN_GAP_DOWN_PCT,
            'exit_hhmm': ct.EXIT_HHMM,
            'exit_deadline_hhmm': ct.EXIT_DEADLINE_HHMM,
            'gap_sl_limit_pct': ct.GAP_SL_LIMIT_PCT,
            'allowed_weekdays': list(ct.ALLOWED_WEEKDAYS),
            'max_daily_positions': ct.MAX_DAILY_POSITIONS,
            'surge_avoidance_enabled': ct.SURGE_AVOIDANCE_ENABLED,
            'surge_max_prev_to_last_pct': ct.SURGE_MAX_PREV_TO_LAST_PCT,
            'surge_max_intraday_range_pct': ct.SURGE_MAX_INTRADAY_RANGE_PCT,
            'surge_max_pct_from_open': ct.SURGE_MAX_PCT_FROM_OPEN,
        }

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None):
        if ClosingTradeStrategy.DEFAULT_CONFIG is None:
            ClosingTradeStrategy.DEFAULT_CONFIG = self._load_default_config()
        self.config = {**ClosingTradeStrategy.DEFAULT_CONFIG, **(config or {})}
        self.logger = logger
        self.daily_trades: Dict[str, set] = {}

        # 전일 양봉 몸통/종가 맵 (pre_market_analyzer가 채움)
        self.prev_body_map: Dict[str, float] = {}
        self.prev_close_map: Dict[str, float] = {}

    def _log(self, message: str, level: str = 'info'):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message)
        else:
            print(f"[{level.upper()}] {message}")

    def reset_daily_trades(self, trade_date: Optional[str] = None):
        if trade_date:
            self.daily_trades.pop(trade_date, None)
        else:
            self.daily_trades.clear()

    def record_trade(self, stock_code: str, trade_date: str):
        self.daily_trades.setdefault(trade_date, set()).add(stock_code)

    def update_prev_body_map(self, body_map: Dict[str, float]):
        """pre_market_analyzer가 08:00~09:00에 전일 양봉 몸통 맵 주입."""
        self.prev_body_map = dict(body_map)
        if self.logger:
            self.logger.info(f"[종가매매] 전일 양봉 몸통 맵 갱신: {len(self.prev_body_map)}종목")

    def load_prev_body_map_from_db(self, prev_date: str,
                                   stock_codes: Optional[list] = None) -> int:
        """
        전일 양봉 몸통 맵을 robotrader_quant.daily_prices 에서 직접 로드.
        2026-04-18 전환: minute_candles SUM → daily_prices (전체 2,485종목, 2023-06~)

        Args:
            prev_date: 전일 거래일 YYYYMMDD (내부에서 YYYY-MM-DD 로 변환)
            stock_codes: 대상 종목 리스트 (None 이면 전체)
        Returns:
            로드된 종목 수
        """
        import psycopg2
        try:
            from config.settings import (
                PG_HOST, PG_PORT, PG_DATABASE_QUANT, PG_USER, PG_PASSWORD,
            )
        except Exception as e:
            if self.logger:
                self.logger.warning(f"[종가매매] DB 설정 로드 실패: {e}")
            return 0

        # YYYYMMDD → YYYY-MM-DD
        if prev_date and len(prev_date) == 8 and '-' not in prev_date:
            prev_date_iso = f"{prev_date[:4]}-{prev_date[4:6]}-{prev_date[6:8]}"
        else:
            prev_date_iso = prev_date

        try:
            conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE_QUANT,
                                    user=PG_USER, password=PG_PASSWORD,
                                    connect_timeout=10)
            cur = conn.cursor()
            if stock_codes:
                placeholders = ','.join(['%s'] * len(stock_codes))
                sql = f'''
                    SELECT stock_code, open, close
                    FROM daily_prices
                    WHERE date = %s AND stock_code IN ({placeholders})
                '''
                cur.execute(sql, [prev_date_iso, *stock_codes])
            else:
                cur.execute('''
                    SELECT stock_code, open, close
                    FROM daily_prices
                    WHERE date = %s
                ''', [prev_date_iso])
            body_map = {}
            close_map = {}
            for code, d_open, d_close in cur.fetchall():
                if d_open and d_close and d_open > 0:
                    body = (float(d_close) / float(d_open) - 1) * 100
                    body_map[code] = body
                    close_map[code] = float(d_close)
            cur.close()
            conn.close()
            self.update_prev_body_map(body_map)
            self.prev_close_map = close_map
            if self.logger:
                self.logger.info(
                    f"[종가매매] 전일 종가 맵 갱신: {len(close_map)}종목"
                )
            return len(body_map)
        except Exception as e:
            if self.logger:
                self.logger.error(f"[종가매매] 전일 양봉 몸통 로드 실패: {e}")
            return 0

    # -------- 외부 인터페이스 (trading_decision_engine 공통 시그니처) --------

    def check_entry_conditions(
        self,
        stock_code: str,
        current_price: float,
        day_open: float,
        current_time: str,  # "HHMMSS" or "HHMM"
        trade_date: str,
        weekday: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        1차 진입 조건 확인 (시간대·요일·중복·전일 양봉).
        2차 (신호) 평가는 check_advanced_conditions 에서.
        """
        if day_open <= 0:
            return False, "시가 없음"

        if weekday is None:
            try:
                weekday = datetime.strptime(trade_date, '%Y%m%d').weekday()
            except Exception:
                return False, "날짜 파싱 실패"
        if weekday not in self.config['allowed_weekdays']:
            return False, "허용되지 않은 요일"

        # 시간창: HHMMSS -> HHMM int
        try:
            t = int(str(current_time)[:4])
        except Exception:
            return False, "시간 파싱 실패"

        if t < self.config['entry_hhmm_start']:
            return False, f"{self.config['entry_hhmm_start']} 이전"
        if t >= self.config['entry_hhmm_end']:
            return False, f"{self.config['entry_hhmm_end']} 이후"

        # 전일 양봉 체크
        prev_body = self.prev_body_map.get(stock_code, None)
        if prev_body is None:
            return False, "전일 몸통 데이터 없음"
        if prev_body < self.config['min_prev_body_pct']:
            return False, f"전일 몸통 {prev_body:+.2f}% < {self.config['min_prev_body_pct']}%"

        # 시뮬 정합 갭 필터: 당일 시가/전일 종가 기준
        prev_close = self.prev_close_map.get(stock_code, 0.0)
        if prev_close and prev_close > 0:
            gap = (day_open / prev_close - 1) * 100
            if gap < self.config['min_gap_pct']:
                return False, f"갭 {gap:+.2f}% < {self.config['min_gap_pct']}%"
            if gap > self.config['max_gap_pct']:
                return False, f"갭 {gap:+.2f}% > {self.config['max_gap_pct']}%"
            if abs(gap) > self.config['max_abs_gap_pct']:
                return False, f"|갭| {gap:+.2f}% > {self.config['max_abs_gap_pct']}%"
            if gap < self.config['min_gap_down_pct']:
                return False, f"갭다운 {gap:+.2f}% < {self.config['min_gap_down_pct']}%"
        else:
            return False, "전일 종가 데이터 없음"

        # 당일 중복 거래 확인
        if stock_code in self.daily_trades.get(trade_date, set()):
            return False, "당일 이미 거래"

        # 본전 이상 (현재가 > 시가)
        if current_price <= day_open:
            pct = (current_price / day_open - 1) * 100
            return False, f"시가 미복귀 {pct:+.2f}%"

        return True, f"1차 통과 (전일 body {prev_body:+.2f}%, 갭 {gap:+.2f}%)"

    def check_advanced_conditions(
        self,
        df: pd.DataFrame,
        candle_idx: int,
    ) -> Tuple[bool, str]:
        """
        신호 2차 평가: 당일 VWAP 상회 + 당일 최저점 제한.
        df: 당일 분봉 (columns: open, high, low, close, volume).
        candle_idx: 현재 봉 인덱스.
        """
        if candle_idx < 20 or candle_idx >= len(df):
            return False, "candle_idx 범위 부족"

        # 당일 시가 (09:00 첫 봉 open)
        day_open = float(df.iloc[0]['open'])
        if day_open <= 0:
            return False, "day_open 0"

        # 현재 봉까지의 최저가 (시가 대비)
        low_so_far = float(df.iloc[:candle_idx + 1]['low'].min())
        min_pct = (low_so_far / day_open - 1) * 100
        if min_pct < self.config['max_day_decline_pct']:
            return False, f"최저 {min_pct:+.2f}% < {self.config['max_day_decline_pct']}%"

        # VWAP 상회 체크
        if self.config['require_vwap_above']:
            sub = df.iloc[:candle_idx + 1]
            typical = (sub['high'].to_numpy(dtype=np.float64)
                       + sub['low'].to_numpy(dtype=np.float64)
                       + sub['close'].to_numpy(dtype=np.float64)) / 3.0
            vol = sub['volume'].to_numpy(dtype=np.float64)
            vsum = vol.sum()
            if vsum <= 0:
                return False, "거래량 0"
            vwap = float((typical * vol).sum() / vsum)
            cur_close = float(df.iloc[candle_idx]['close'])
            if cur_close <= vwap:
                return False, f"VWAP {vwap:.0f} 이하 (close {cur_close:.0f})"

        return True, "종가매매 신호 확정"

    def check_surge_avoidance(
        self,
        df: pd.DataFrame,
        candle_idx: int,
        day_open: float,
        prev_close: float,
    ) -> Tuple[bool, str]:
        """
        급등/VI 종목 배제 (시뮬 filter_surge_avoidance 정합).
        True=통과(진입 허용), False=배제.
        """
        if not self.config.get('surge_avoidance_enabled', True):
            return True, "surge 필터 비활성"
        if candle_idx < 0 or candle_idx >= len(df) or day_open <= 0:
            return False, "data 부족"

        last_close = float(df.iloc[candle_idx]['close'])

        # 전일 종가 대비 급등
        if prev_close and prev_close > 0:
            chg_prev = (last_close / prev_close - 1) * 100
            if chg_prev > self.config['surge_max_prev_to_last_pct']:
                return False, f"전일대비 +{chg_prev:.2f}% > {self.config['surge_max_prev_to_last_pct']}%"

        # 장중 range
        sub = df.iloc[:candle_idx + 1]
        day_high = float(sub['high'].max())
        low_pos = sub['low'][sub['low'] > 0]
        day_low = float(low_pos.min()) if len(low_pos) > 0 else 0
        if day_low > 0:
            rng_pct = (day_high / day_low - 1) * 100
            if rng_pct > self.config['surge_max_intraday_range_pct']:
                return False, f"장중range {rng_pct:.2f}% > {self.config['surge_max_intraday_range_pct']}%"

        # 시가 대비
        pct_open = (last_close / day_open - 1) * 100
        if pct_open > self.config['surge_max_pct_from_open']:
            return False, f"시가대비 +{pct_open:.2f}% > {self.config['surge_max_pct_from_open']}%"

        return True, "OK"

    def check_exit_conditions(
        self,
        entry_price: float,
        current_high: float,
        current_low: float,
        current_close: float,
    ) -> Tuple[bool, str, float]:
        """
        장중 청산 신호: **항상 False** (오버나이트 홀드).
        실제 청산은 main.py의 overnight_exit 로직이 익일 09:00에 실행.
        """
        return False, "오버나이트 홀드", (
            (current_close / entry_price - 1) * 100 if entry_price > 0 else 0.0
        )

    def simulate_trade(self, df, entry_idx: int, max_holding_minutes: int = 0):
        """
        호환성 유지용 stub.
        실거래 시뮬레이션은 simulate_closing_trade.py (worktree 전용) 참조.
        """
        raise NotImplementedError(
            "ClosingTradeStrategy.simulate_trade는 오버나이트 시뮬 엔진 필요. "
            "track_b_closing_sim.py 참조."
        )

    def get_strategy_info(self) -> Dict[str, Any]:
        weekday_names = ['월', '화', '수', '목', '금']
        allowed = [weekday_names[d] for d in self.config['allowed_weekdays']]
        return {
            'name': 'ClosingTradeStrategy',
            'description': '종가매매 오버나이트 전략 (14:00~14:20 진입, 익일 09:00 청산)',
            'entry_conditions': {
                'time_range': f"{self.config['entry_hhmm_start']}~{self.config['entry_hhmm_end']}",
                'min_prev_body_pct': f"{self.config['min_prev_body_pct']}%",
                'max_day_decline_pct': f"{self.config['max_day_decline_pct']}%",
                'weekdays': ', '.join(allowed),
            },
            'exit_conditions': {
                'exit_hhmm': self.config['exit_hhmm'],
                'gap_sl_limit_pct': f"{self.config['gap_sl_limit_pct']}%",
            },
            'expected_performance': {
                'win_rate': '60.6%',
                'total_return_compound': '+53.7% (1년)',
                'mdd': '3.56%',
            },
        }

    def __repr__(self):
        c = self.config
        return (f"ClosingTradeStrategy(entry={c['entry_hhmm_start']}-{c['entry_hhmm_end']}, "
                f"exit={c['exit_hhmm']}, body>={c['min_prev_body_pct']}%, "
                f"max_daily={c['max_daily_positions']})")
