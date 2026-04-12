"""
분봉 수집 확대 모듈

매일 장 마감 후 KIS 거래량순위 API로 상위 300종목을 선정하고,
해당 종목의 당일 분봉을 minute_candles 테이블에 저장합니다.

목적: 시뮬-실거래 후보 풀 격차 해소 (시뮬이 실거래와 동일한 상위 종목으로 백테스트 가능)

주요 설계:
- 옵션 B (KIS 거래량순위 API 직접 호출) — 전문가 토론 결과
- 트리거: 15:45 (장 마감 + 청산 + 기존 save_all_data 완료 후)
- 실패 처리: 개별 종목 실패는 로그만, 연속 실패 30건이면 중단
- 기존 봇 영향 0: try/except 감싸기, 별도 DB 커넥션

사용:
    from core.expanded_minute_collector import ExpandedMinuteCollector
    collector = ExpandedMinuteCollector(logger=logger)
    await collector.run(target_date='20260412', top_n=300)
"""
import asyncio
import time
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set

import psycopg2
import pandas as pd

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from api.kis_market_api import get_volume_rank
from api.kis_chart_api import get_full_trading_day_data


class ExpandedMinuteCollector:
    """거래대금 상위 N종목 분봉 수집기"""

    STATE_DIR = Path(__file__).parent.parent / '.omc' / 'state'

    def __init__(self, logger=None):
        self.logger = logger
        self.stats = {
            'target_count': 0,
            'collected': 0,
            'failed': 0,
            'skipped': 0,
            'elapsed_sec': 0,
            'failed_codes': [],
        }

    def _log(self, msg: str, level: str = 'info'):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(msg)
        else:
            print(f'[{level.upper()}] {msg}')

    # ============================================================
    # 1. 종목 선정 (KIS 거래량순위 API)
    # ============================================================

    def select_top_stocks(self, top_n: int = 300) -> List[str]:
        """
        KIS 거래량순위 API로 거래대금 상위 N종목 선정

        거래량순위 API는 1회당 최대 30건 반환.
        KOSPI(0001) + KOSDAQ(1001) × 거래금액순(3) = 60건/쌍.
        N=300이면 5쌍 정도 필요하지만, 실제로는 중복 많으므로 여유있게 8~10회 호출.

        Returns:
            종목코드 리스트 (중복 제거, 거래대금순 정렬)
        """
        self._log(f'종목 선정 시작 (목표 {top_n}개)')

        all_stocks = []
        seen = set()

        # 가격 범위 슬라이딩 (각 구간 × 2시장 × 30건 = 60 × 구간수 종목)
        # 300종목 목표: 구간 5개 필요 (5 × 2 × 30 = 300)
        price_ranges = [
            (5000, 15000),    # 초저가
            (15000, 30000),   # 저가
            (30000, 60000),   # 중저가
            (60000, 120000),  # 중가
            (120000, 250000), # 고가
            (250000, 500000), # 초고가
        ]

        for price_min, price_max in price_ranges:
            for market_code, market_name in [('0001', 'KOSPI'), ('1001', 'KOSDAQ')]:
                try:
                    df = get_volume_rank(
                        fid_cond_mrkt_div_code='J',
                        fid_input_iscd=market_code,
                        fid_blng_cls_code='3',  # 거래금액순
                        fid_input_price_1=str(price_min),
                        fid_input_price_2=str(price_max),
                    )
                    if df is None or df.empty:
                        continue

                    # 종목코드 컬럼 (mksc_shrn_iscd)
                    code_col = 'mksc_shrn_iscd' if 'mksc_shrn_iscd' in df.columns else df.columns[0]
                    amount_col = 'acml_tr_pbmn' if 'acml_tr_pbmn' in df.columns else None

                    for _, row in df.iterrows():
                        code = str(row[code_col]).strip()
                        if not code or code in seen:
                            continue
                        # 우선주 제외 (5로 끝나는 종목)
                        if code.endswith('5'):
                            continue
                        amount = float(row[amount_col]) if amount_col and row.get(amount_col) else 0
                        seen.add(code)
                        all_stocks.append({'code': code, 'amount': amount, 'market': market_name})

                    time.sleep(0.08)  # API rate limit (KIS 초당 3call)

                except Exception as e:
                    self._log(f'거래량순위 조회 실패 ({market_name} {price_min}~{price_max}): {e}', 'warning')
                    continue

        # 거래대금 기준 정렬
        all_stocks.sort(key=lambda x: x['amount'], reverse=True)
        selected = [s['code'] for s in all_stocks[:top_n]]

        self._log(f'종목 선정 완료: {len(selected)}/{top_n} 종목 (전체 풀 {len(all_stocks)})')
        return selected

    # ============================================================
    # 2. 분봉 수집 및 저장
    # ============================================================

    def _get_db_connection(self):
        return psycopg2.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD,
        )

    def _get_existing_codes(self, cur, trade_date: str) -> Set[str]:
        """이미 저장된 (stock_code, trade_date) 조회"""
        cur.execute('''
            SELECT DISTINCT stock_code FROM minute_candles
            WHERE trade_date = %s
        ''', [trade_date])
        return set(r[0] for r in cur.fetchall())

    def _save_minute_data(self, cur, stock_code: str, trade_date: str, df: pd.DataFrame):
        """분봉 DataFrame을 minute_candles에 저장 (collect_and_simulate.py 로직 재활용)"""
        cur.execute(
            'DELETE FROM minute_candles WHERE stock_code = %s AND trade_date = %s',
            [stock_code, trade_date]
        )

        for idx, (_, row) in enumerate(df.iterrows()):
            try:
                time_val = str(row.get('time', row.get('stck_cntg_hour', '')))
                close_val = int(float(row.get('close', row.get('stck_prpr', 0))))
                open_val = int(float(row.get('open', row.get('stck_oprc', 0))))
                high_val = int(float(row.get('high', row.get('stck_hgpr', 0))))
                low_val = int(float(row.get('low', row.get('stck_lwpr', 0))))
                volume_val = int(float(row.get('volume', row.get('cntg_vol', 0))))
                amount_val = int(float(row.get('amount', row.get('acml_tr_pbmn', 0))))

                datetime_val = None
                if len(time_val) >= 6:
                    try:
                        datetime_val = datetime.strptime(
                            f'{trade_date}{time_val[:6]}', '%Y%m%d%H%M%S'
                        )
                    except Exception:
                        pass

                cur.execute('''
                    INSERT INTO minute_candles
                        (stock_code, trade_date, idx, date, time, close, open, high, low,
                         volume, amount, datetime)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stock_code, trade_date, idx) DO NOTHING
                ''', [
                    stock_code, trade_date, idx,
                    trade_date, time_val, close_val, open_val, high_val, low_val,
                    volume_val, amount_val, datetime_val,
                ])
            except Exception:
                continue

    # ============================================================
    # 3. 메인 실행
    # ============================================================

    def run(self, target_date: Optional[str] = None, top_n: int = 300,
            skip_existing: bool = True, auto_retry: bool = True) -> Dict:
        """
        전체 파이프라인 실행

        Args:
            target_date: 대상 거래일 (YYYYMMDD, None이면 오늘)
            top_n: 수집 목표 종목 수
            skip_existing: 이미 저장된 종목 스킵 여부
            auto_retry: 실패한 종목 1회 자동 재시도

        Returns:
            수집 통계 딕셔너리
        """
        start_ts = time.time()

        if target_date is None:
            target_date = datetime.now().strftime('%Y%m%d')

        self._log(f'=== 분봉 확대 수집 시작: {target_date}, 목표 {top_n}종목 ===')

        # 1. 종목 선정
        try:
            target_codes = self.select_top_stocks(top_n=top_n)
        except Exception as e:
            self._log(f'종목 선정 실패: {e}', 'error')
            return self.stats

        if not target_codes:
            self._log('선정된 종목 없음', 'warning')
            return self.stats

        self.stats['target_count'] = len(target_codes)

        # 2. DB 연결 및 기존 데이터 확인
        conn = self._get_db_connection()
        cur = conn.cursor()

        if skip_existing:
            existing = self._get_existing_codes(cur, target_date)
            to_collect = [c for c in target_codes if c not in existing]
            self.stats['skipped'] = len(target_codes) - len(to_collect)
            self._log(f'기존 데이터 있음: {self.stats["skipped"]}종목 스킵')
        else:
            to_collect = target_codes

        # 3. 분봉 수집 루프
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 30
        CIRCUIT_BREAKER_THRESHOLD = 10

        # 과거 거래일은 15:30까지 전체 분봉 수집, 당일은 실시간까지
        today_str = datetime.now().strftime('%Y%m%d')
        selected_time = '' if target_date == today_str else '153000'

        for i, code in enumerate(to_collect):
            try:
                df = get_full_trading_day_data(code, target_date, selected_time)

                if df is not None and len(df) > 0:
                    self._save_minute_data(cur, code, target_date, df)
                    self.stats['collected'] += 1
                    consecutive_failures = 0
                else:
                    self.stats['failed'] += 1
                    self.stats['failed_codes'].append(code)
                    consecutive_failures += 1

            except Exception as e:
                self.stats['failed'] += 1
                self.stats['failed_codes'].append(code)
                consecutive_failures += 1
                self._log(f'{code} 수집 실패: {str(e)[:80]}', 'debug')

            # 진행률 로그 (20건마다)
            if (i + 1) % 20 == 0:
                conn.commit()
                elapsed = time.time() - start_ts
                eta = elapsed / (i + 1) * (len(to_collect) - i - 1)
                self._log(
                    f'진행 {i+1}/{len(to_collect)} '
                    f'(성공:{self.stats["collected"]} 실패:{self.stats["failed"]}) '
                    f'ETA {eta:.0f}초'
                )

            # 서킷: 연속 10건 실패 → 1분 대기
            if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                self._log(f'연속 {consecutive_failures}건 실패 → 60초 대기', 'warning')
                time.sleep(60)
                consecutive_failures = 0

            # 최악: 연속 30건 실패 → 전체 중단
            if self.stats['failed'] >= MAX_CONSECUTIVE_FAILURES and self.stats['collected'] == 0:
                self._log(f'수집 실패 {self.stats["failed"]}건 누적 → 중단', 'error')
                break

            time.sleep(0.3)  # API rate limit 여유

        # 4. 자동 재시도 (실패 종목 1회 더 시도)
        if auto_retry and self.stats['failed_codes']:
            retry_codes = list(self.stats['failed_codes'])
            self.stats['failed_codes'] = []
            retry_failed = 0
            retry_ok = 0
            self._log(f'재시도: {len(retry_codes)}종목')

            for code in retry_codes:
                try:
                    df = get_full_trading_day_data(code, target_date, selected_time)
                    if df is not None and len(df) > 0:
                        self._save_minute_data(cur, code, target_date, df)
                        retry_ok += 1
                        self.stats['collected'] += 1
                        self.stats['failed'] -= 1  # 성공한 만큼 실패 카운트 감소
                    else:
                        retry_failed += 1
                        self.stats['failed_codes'].append(code)
                except Exception:
                    retry_failed += 1
                    self.stats['failed_codes'].append(code)
                time.sleep(0.3)

            self._log(f'재시도 결과: 성공 {retry_ok}, 실패 {retry_failed}')

        # 5. 마무리
        conn.commit()
        cur.close()
        conn.close()

        self.stats['elapsed_sec'] = time.time() - start_ts
        self._log(
            f'=== 수집 완료: 대상 {self.stats["target_count"]}종목, '
            f'성공 {self.stats["collected"]}, 실패 {self.stats["failed"]}, '
            f'스킵 {self.stats["skipped"]}, '
            f'소요 {self.stats["elapsed_sec"]:.0f}초 ==='
        )

        # 상태 파일 저장 (2단계 재시도에서 활용)
        try:
            self.STATE_DIR.mkdir(parents=True, exist_ok=True)
            state_file = self.STATE_DIR / f'minute_collection_{target_date}.json'
            state_file.write_text(json.dumps({
                'date': target_date,
                'target': self.stats['target_count'],
                'collected': self.stats['collected'],
                'failed': self.stats['failed'],
                'skipped': self.stats['skipped'],
                'elapsed_sec': int(self.stats['elapsed_sec']),
                'failed_codes': self.stats['failed_codes'],
                'completed_at': datetime.now().isoformat(),
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            self._log(f'상태 파일 저장 실패: {e}', 'warning')

        return self.stats

    async def run_async(self, target_date: Optional[str] = None, top_n: int = 300) -> Dict:
        """비동기 래퍼 (asyncio 태스크에서 호출용, blocking을 executor에 위임)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run, target_date, top_n)
