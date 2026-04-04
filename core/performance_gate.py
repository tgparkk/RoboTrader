"""
매매 성과 기반 매수 게이트

- 롤링 승률 게이트: 최근 N건 승률 < threshold → 매수 차단
- 연속 손실 당일중단: 당일 M연패 → 당일 매수 차단
- 가상 추적: 차단 중에도 장 마감 후 결과를 deque에 반영 (영구 차단 방지)
- 10일 하드캡: 연속 차단 10일 초과 시 deque 리셋 (안전장치)
"""

from collections import deque
from typing import Tuple, Optional, List, Dict
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst


class PerformanceGate:
    """매매 성과 기반 매수 게이트"""

    def __init__(
        self,
        rolling_n: int = 20,
        rolling_threshold: float = 0.45,
        consec_loss_limit: int = 3,
        hard_cap_days: int = 10,
        logger=None,
    ):
        self.logger = logger or setup_logger(__name__)
        self.rolling_n = rolling_n
        self.rolling_threshold = rolling_threshold
        self.consec_loss_limit = consec_loss_limit
        self.hard_cap_days = hard_cap_days

        # 롤링 승패 기록 (1=승, 0=패)
        self.recent_results = deque(maxlen=rolling_n)

        # 당일 연속 손실 카운터
        self._daily_consec_loss = 0
        self._current_date = None

        # 차단 상태 추적
        self._consecutive_block_days = 0
        self._last_block_date = None

        # 가상 추적 목록 (차단된 진입 후보)
        self._shadow_entries: List[Dict] = []

    def load_from_db(self, db_manager):
        """봇 시작 시 DB에서 최근 N건 매도 결과 로드"""
        try:
            import psycopg2
            from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
            conn = psycopg2.connect(
                host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                user=PG_USER, password=PG_PASSWORD
            )
            cur = conn.cursor()
            cur.execute('''
                SELECT profit_rate
                FROM real_trading_records
                WHERE action = 'SELL'
                ORDER BY timestamp DESC
                LIMIT %s
            ''', [self.rolling_n])
            rows = cur.fetchall()
            cur.close()
            conn.close()

            # 역순으로 넣어야 최신이 마지막
            for row in reversed(rows):
                is_win = 1 if float(row[0]) > 0 else 0
                self.recent_results.append(is_win)

            wr = self.get_rolling_winrate()
            self.logger.info(
                f"📊 성과 게이트 초기화: 최근 {len(self.recent_results)}건 로드, "
                f"롤링 승률 {wr:.0f}%"
            )
        except Exception as e:
            self.logger.warning(f"⚠️ 성과 게이트 DB 로드 실패: {e}")

    def get_rolling_winrate(self) -> float:
        """현재 롤링 승률 (0~100)"""
        if len(self.recent_results) < self.rolling_n:
            return 100.0  # 데이터 부족 시 차단하지 않음
        return sum(self.recent_results) / len(self.recent_results) * 100

    def check_gate(self) -> Tuple[bool, str]:
        """
        매수 가능 여부 확인

        Returns:
            (allowed, reason): allowed=True면 매수 가능
        """
        today = now_kst().strftime('%Y%m%d')

        # 날짜 변경 시 당일 카운터 리셋
        if today != self._current_date:
            self._current_date = today
            self._daily_consec_loss = 0

        # 1. 롤링 승률 게이트
        if len(self.recent_results) >= self.rolling_n:
            wr = sum(self.recent_results) / len(self.recent_results)
            if wr < self.rolling_threshold:
                # 하드캡 체크
                if self._last_block_date != today:
                    if self._last_block_date:
                        self._consecutive_block_days += 1
                    self._last_block_date = today

                if self._consecutive_block_days >= self.hard_cap_days:
                    self.logger.warning(
                        f"⚠️ 성과 게이트 하드캡 도달 ({self.hard_cap_days}일) → 강제 리셋"
                    )
                    self._reset_to_neutral()
                    return True, "하드캡 리셋"

                return False, f"롤링승률 {wr*100:.0f}% < {self.rolling_threshold*100:.0f}%"

        # 2. 연속 손실 당일중단
        if self.consec_loss_limit > 0 and self._daily_consec_loss >= self.consec_loss_limit:
            return False, f"당일 {self._daily_consec_loss}연패"

        # 통과 시 연속 차단일 리셋
        self._consecutive_block_days = 0
        self._last_block_date = None
        return True, ""

    def record_result(self, is_win: bool):
        """
        매도 체결 시 결과 기록

        Args:
            is_win: True=수익, False=손실
        """
        self.recent_results.append(1 if is_win else 0)

        if is_win:
            self._daily_consec_loss = 0
        else:
            self._daily_consec_loss += 1

        wr = self.get_rolling_winrate()
        n = len(self.recent_results)
        self.logger.info(
            f"📊 성과 게이트: {'WIN' if is_win else 'LOSS'} 기록 → "
            f"롤링 {n}건 승률 {wr:.0f}%, 당일연패 {self._daily_consec_loss}"
        )

    def add_shadow_entry(self, stock_code: str, entry_price: float,
                         entry_idx: int, trade_date: str, candle_df=None):
        """
        차단된 진입 후보를 가상 추적 목록에 추가

        장 마감 후 process_shadow_entries()로 결과 계산
        """
        self._shadow_entries.append({
            'stock_code': stock_code,
            'entry_price': entry_price,
            'entry_idx': entry_idx,
            'trade_date': trade_date,
            'candle_df': candle_df,  # None이면 EOD에 DB에서 조회
        })

    def process_shadow_entries(self):
        """
        장 마감 후 가상 추적 결과 계산 → deque 갱신

        core/strategies/price_position_strategy.py의 simulate_trade() 활용
        """
        if not self._shadow_entries:
            return

        from core.strategies.price_position_strategy import PricePositionStrategy
        strategy = PricePositionStrategy()

        processed = 0
        for entry in self._shadow_entries:
            try:
                df = entry.get('candle_df')

                # candle_df가 없으면 DB에서 조회
                if df is None:
                    import psycopg2
                    import pandas as pd
                    from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
                    conn = psycopg2.connect(
                        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                        user=PG_USER, password=PG_PASSWORD
                    )
                    cur = conn.cursor()
                    cur.execute(
                        'SELECT idx,date,time,close,open,high,low,volume,amount '
                        'FROM minute_candles WHERE stock_code=%s AND trade_date=%s ORDER BY idx',
                        [entry['stock_code'], entry['trade_date']]
                    )
                    rows = cur.fetchall()
                    cur.close()
                    conn.close()
                    if len(rows) < 50:
                        continue
                    df = pd.DataFrame(rows, columns=[
                        'idx', 'date', 'time', 'close', 'open', 'high', 'low', 'volume', 'amount'
                    ])

                result = strategy.simulate_trade(df, entry['entry_idx'])
                if result:
                    is_win = result['result'] == 'WIN'
                    self.recent_results.append(1 if is_win else 0)
                    processed += 1
                    self.logger.debug(
                        f"👻 가상 추적: {entry['stock_code']} → "
                        f"{'WIN' if is_win else 'LOSS'} ({result['pnl']:+.2f}%)"
                    )
            except Exception as e:
                self.logger.warning(f"⚠️ 가상 추적 실패 ({entry['stock_code']}): {e}")

        if processed > 0:
            wr = self.get_rolling_winrate()
            self.logger.info(
                f"👻 가상 추적 완료: {processed}/{len(self._shadow_entries)}건 처리 → "
                f"롤링 승률 {wr:.0f}%"
            )
        self._shadow_entries.clear()

    def _reset_to_neutral(self):
        """deque를 중립 상태(50%)로 리셋"""
        self.recent_results.clear()
        half = self.rolling_n // 2
        for _ in range(half):
            self.recent_results.append(1)
        for _ in range(self.rolling_n - half):
            self.recent_results.append(0)
        self._consecutive_block_days = 0
        self._last_block_date = None

    def get_status(self) -> dict:
        """텔레그램 등에서 사용할 상태 정보"""
        allowed, reason = self.check_gate()
        return {
            'rolling_winrate': self.get_rolling_winrate(),
            'rolling_n': len(self.recent_results),
            'rolling_max': self.rolling_n,
            'daily_consec_loss': self._daily_consec_loss,
            'gate_allowed': allowed,
            'gate_reason': reason,
            'shadow_pending': len(self._shadow_entries),
            'consecutive_block_days': self._consecutive_block_days,
        }
