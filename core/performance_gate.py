"""
매매 성과 기반 매수 게이트

- 롤링 승률 게이트: 최근 N건 승률 < threshold → 매수 차단
- 연속 손실 당일중단: 당일 M연패 → 당일 매수 차단
- 가상 추적: 차단 중에도 장 마감 후 결과를 deque에 반영 (영구 차단 방지)
- 10일 하드캡: 연속 차단 10일 초과 시 deque 리셋 (안전장치)
"""

import json
import os
import tempfile
from collections import deque
from typing import Tuple, Optional, List, Dict
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst

# 상태 영속화 파일 경로 (프로젝트 루트의 data/ 디렉토리)
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'gate_state.json'
)


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
        self._current_date = now_kst().strftime('%Y%m%d')

        # 차단 상태 추적
        self._consecutive_block_days = 0
        self._last_block_date = None

        # 가상 추적 목록 (차단된 진입 후보)
        self._shadow_entries: List[Dict] = []

    # ------------------------------------------------------------------
    # 상태 영속화
    # ------------------------------------------------------------------

    def _save_state(self):
        """현재 상태를 JSON 파일로 저장 (실패 시 로그만 남기고 무시)"""
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
            # _shadow_entries에서 candle_df는 제외하고 저장
            shadow_without_df = [
                {k: v for k, v in entry.items() if k != 'candle_df'}
                for entry in self._shadow_entries
            ]
            state = {
                'shadow_entries': shadow_without_df,
                'consecutive_block_days': self._consecutive_block_days,
                'last_block_date': self._last_block_date,
            }
            # 원자적 쓰기: 임시 파일에 쓴 후 교체 (정전/강제종료 시 손상 방지)
            dir_name = os.path.dirname(_STATE_FILE)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, _STATE_FILE)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
        except Exception as e:
            self.logger.warning(f"⚠️ 성과 게이트 상태 저장 실패: {e}")

    def _load_state(self):
        """JSON 파일에서 상태 복원 (파일 없거나 손상 시 초기값 사용)"""
        try:
            if not os.path.exists(_STATE_FILE):
                return
            with open(_STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            # candle_df는 항상 None으로 복원 (EOD에 DB에서 조회)
            loaded_shadow = state.get('shadow_entries', [])
            for entry in loaded_shadow:
                entry['candle_df'] = None
            self._shadow_entries = loaded_shadow
            self._consecutive_block_days = int(state.get('consecutive_block_days', 0))
            self._last_block_date = state.get('last_block_date', None)
            self.logger.info(
                f"📂 성과 게이트 상태 복원: 가상추적 {len(self._shadow_entries)}건, "
                f"연속차단 {self._consecutive_block_days}일"
            )
        except Exception as e:
            self.logger.warning(f"⚠️ 성과 게이트 상태 로드 실패 (초기값 사용): {e}")

    # ------------------------------------------------------------------
    # DB 초기화
    # ------------------------------------------------------------------

    def load_from_db(self, db_manager):
        """봇 시작 시 DB에서 최근 N건 매도 결과 로드 (실거래만 — 가상추적은 런타임 deque에서만 관리)"""
        conn = None
        try:
            import psycopg2
            from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
            conn = psycopg2.connect(
                host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                user=PG_USER, password=PG_PASSWORD
            )
            cur = conn.cursor()
            cur.execute('''
                SELECT profit_rate, timestamp
                FROM real_trading_records
                WHERE action = 'SELL'
                ORDER BY timestamp DESC
                LIMIT %s
            ''', [self.rolling_n])
            rows = cur.fetchall()
            cur.close()

            real_count = len(rows)

            # 역순으로 넣어야 최신이 마지막
            for row in reversed(rows):
                is_win = 1 if float(row[0]) > 0 else 0
                self.recent_results.append(is_win)

            wr = self.get_rolling_winrate()
            self.logger.info(
                f"📊 성과 게이트 초기화: 최근 {len(self.recent_results)}건 로드 "
                f"(실거래 {real_count}건), "
                f"롤링 승률 {wr:.0f}%"
            )
        except Exception as e:
            self.logger.warning(f"⚠️ 성과 게이트 DB 로드 실패: {e}")
        finally:
            if conn:
                conn.close()

        # DB 로드 후 영속 상태 복원
        self._load_state()

    # ------------------------------------------------------------------
    # 핵심 로직
    # ------------------------------------------------------------------

    def get_rolling_winrate(self) -> float:
        """현재 롤링 승률 (0~100)"""
        if len(self.recent_results) < self.rolling_n:
            return 100.0  # 데이터 부족 시 차단하지 않음
        return sum(self.recent_results) / len(self.recent_results) * 100

    def _compute_gate(self, today: str) -> Tuple[bool, str]:
        """
        읽기 전용 게이트 계산 (상태 변경 없음).

        Returns:
            (allowed, reason)
        """
        # 1. 롤링 승률 게이트
        if len(self.recent_results) >= self.rolling_n:
            wr = sum(self.recent_results) / len(self.recent_results)
            if wr < self.rolling_threshold:
                # 하드캡 도달 시 리셋 예정 표시 (읽기 전용이므로 실제 리셋은 check_gate에서)
                if self._consecutive_block_days >= self.hard_cap_days:
                    return True, "하드캡 리셋 예정"
                return False, f"롤링승률 {wr*100:.0f}% < {self.rolling_threshold*100:.0f}%"

        # 2. 연속 손실 당일중단
        if self.consec_loss_limit > 0 and self._daily_consec_loss >= self.consec_loss_limit:
            return False, f"당일 {self._daily_consec_loss}연패"

        return True, ""

    def check_gate(self) -> Tuple[bool, str]:
        """
        매수 가능 여부 확인 (상태 변경 포함: block_days 추적)

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
                # 하드캡 체크: 첫날도 1로 카운트 (거래일만 — 주말/공휴일 방어)
                if self._last_block_date != today and now_kst().weekday() < 5:
                    self._consecutive_block_days += 1
                    self._last_block_date = today
                    self._save_state()

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
        if self._consecutive_block_days != 0 or self._last_block_date is not None:
            self._consecutive_block_days = 0
            self._last_block_date = None
            self._save_state()

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
                         entry_idx: int, trade_date: str, candle_df=None,
                         stop_loss_pct: float = None, take_profit_pct: float = None):
        """
        차단된 진입 후보를 가상 추적 목록에 추가

        장 마감 후 process_shadow_entries()로 결과 계산.
        같은 날 같은 stock_code가 이미 있으면 스킵 (중복 방지).

        Args:
            stop_loss_pct: 실제 적용 손절 비율 (예: -5.0 또는 -3.0). None이면 전략 기본값 사용.
            take_profit_pct: 실제 적용 익절 비율 (예: 6.0 또는 4.0). None이면 전략 기본값 사용.
        """
        # 중복 방지: 같은 날 같은 종목은 스킵
        for existing in self._shadow_entries:
            if existing['stock_code'] == stock_code and existing['trade_date'] == trade_date:
                self.logger.debug(
                    f"👻 가상 추적 중복 스킵: {stock_code} ({trade_date})"
                )
                return

        self._shadow_entries.append({
            'stock_code': stock_code,
            'entry_price': entry_price,
            'entry_idx': entry_idx,
            'trade_date': trade_date,
            'candle_df': candle_df,  # None이면 EOD에 DB에서 조회
            'stop_loss_pct': stop_loss_pct,
            'take_profit_pct': take_profit_pct,
        })
        self._save_state()

    def process_shadow_entries(self):
        """
        장 마감 후 가상 추적 결과 계산 → deque 갱신 + DB 저장

        core/strategies/price_position_strategy.py의 simulate_trade() 활용.
        결과는 virtual_trading_records 테이블에 strategy='gate_shadow'로 저장.
        """
        if not self._shadow_entries:
            self.logger.info("👻 가상 추적: 처리할 항목 없음")
            return

        import psycopg2
        import pandas as pd
        from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
        from core.strategies.price_position_strategy import PricePositionStrategy

        total = len(self._shadow_entries)
        processed = 0

        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD
        )
        try:
            while self._shadow_entries:
                entry = self._shadow_entries[0]  # peek, pop은 처리 완료 후
                try:
                    # entry별 SL/TP로 strategy 생성 (약세장 손절축소 반영)
                    shadow_config = {}
                    if entry.get('stop_loss_pct') is not None:
                        shadow_config['stop_loss_pct'] = entry['stop_loss_pct']
                    if entry.get('take_profit_pct') is not None:
                        shadow_config['take_profit_pct'] = entry['take_profit_pct']
                    strategy = PricePositionStrategy(config=shadow_config if shadow_config else None)

                    df = entry.get('candle_df')

                    # candle_df가 없으면 DB에서 조회
                    if df is None:
                        cur = conn.cursor()
                        cur.execute(
                            'SELECT idx,date,time,close,open,high,low,volume,amount '
                            'FROM minute_candles WHERE stock_code=%s AND trade_date=%s ORDER BY idx',
                            [entry['stock_code'], entry['trade_date']]
                        )
                        rows = cur.fetchall()
                        cur.close()
                        if len(rows) < 50:
                            self.logger.warning(
                                f"⚠️ 가상 추적 스킵 ({entry['stock_code']}): "
                                f"분봉 데이터 부족 ({len(rows)}행 < 50)"
                            )
                            self._shadow_entries.pop(0)
                            self._save_state()
                            continue
                        df = pd.DataFrame(rows, columns=[
                            'idx', 'date', 'time', 'close', 'open', 'high', 'low', 'volume', 'amount'
                        ])

                    result = strategy.simulate_trade(df, entry['entry_idx'])
                    if result:
                        is_win = result['result'] == 'WIN'
                        self.recent_results.append(1 if is_win else 0)
                        processed += 1
                        pnl = result['pnl']
                        self.logger.debug(
                            f"👻 가상 추적: {entry['stock_code']} → "
                            f"{'WIN' if is_win else 'LOSS'} ({pnl:+.2f}%)"
                        )

                        # DB에 결과 저장 (strategy='gate_shadow'로 기존 가상매매와 구분)
                        pnl = float(pnl)  # np.float64 → float (psycopg2 호환)
                        reason_str = f"{'WIN' if is_win else 'LOSS'} {pnl:+.2f}%"
                        actual_entry = float(result.get('entry_price', entry['entry_price']))
                        exit_price = float(actual_entry * (1 + pnl / 100))
                        ts = now_kst().strftime('%Y-%m-%d %H:%M:%S')
                        cur = conn.cursor()
                        cur.execute(
                            '''INSERT INTO virtual_trading_records
                               (stock_code, stock_name, action, quantity, price,
                                timestamp, strategy, reason, profit_rate, profit_loss)
                               VALUES (%s, %s, 'SELL', 0, %s, %s, 'gate_shadow', %s, %s, 0)''',
                            (
                                entry['stock_code'],
                                entry.get('stock_name', ''),
                                exit_price,
                                ts,
                                reason_str,
                                pnl,
                            )
                        )
                        cur.close()
                        conn.commit()  # entry별 즉시 커밋

                    # 성공이든 결과 없음이든 처리 완료 → 제거 후 상태 저장
                    self._shadow_entries.pop(0)
                    self._save_state()

                except Exception as e:
                    self.logger.warning(f"⚠️ 가상 추적 실패 ({entry['stock_code']}): {e}")
                    try:
                        conn.rollback()  # 트랜잭션 중지 상태 리셋 (이후 쿼리 정상 실행 보장)
                    except Exception:
                        pass
                    self._shadow_entries.pop(0)  # 실패 시에도 제거 (무한 재시도 방지)
                    self._save_state()

        finally:
            conn.close()

        wr = self.get_rolling_winrate()
        if processed > 0:
            self.logger.info(
                f"👻 가상 추적 완료: {processed}/{total}건 처리 → "
                f"롤링 승률 {wr:.0f}%"
            )
        else:
            self.logger.info(
                f"👻 가상 추적: {total}건 시도했으나 처리된 항목 없음 → "
                f"롤링 승률 {wr:.0f}%"
            )

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
        self._save_state()

    def get_status(self) -> dict:
        """텔레그램 등에서 사용할 상태 정보 (읽기 전용, 부작용 없음)"""
        today = now_kst().strftime('%Y%m%d')
        allowed, reason = self._compute_gate(today)
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
