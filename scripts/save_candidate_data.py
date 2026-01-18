"""
후보 종목 데이터 저장 스크립트

candidate_stocks 테이블의 selection_date를 기준으로 해당 날짜(기간)에 선정된 종목들의
분봉 데이터와 과거 100일치 일봉 데이터를 cache 폴더에 저장합니다.

KIS API 제한사항:
- 분봉 데이터: 한 번 호출에 최대 120건 (기존 get_full_trading_day_data_async 활용)
- 일봉 데이터: 한 번 호출에 최대 100건

사용법:
1. 단일 날짜: python save_candidate_data.py 20250918
2. 기간 입력: python save_candidate_data.py 20250915 20250918

파라미터:
- start_date: 시작 날짜 (YYYYMMDD 형식)
- end_date: 종료 날짜 (YYYYMMDD 형식, 선택사항 - 없으면 start_date와 동일)
"""
import sys
import asyncio
import sqlite3
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
import pandas as pd

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from utils.logger import setup_logger
from utils.data_cache import DataCache, DailyDataCache
from api.kis_api_manager import KISAPIManager
from api.kis_chart_api import get_full_trading_day_data_async
from api.kis_market_api import get_inquire_daily_itemchartprice
from config.market_hours import MarketHours


class CandidateDataSaver:
    """후보 종목 데이터 저장기"""

    def __init__(self):
        self.logger = setup_logger(__name__)
        self.api_manager = None

        # 데이터베이스 경로
        self.db_path = Path(__file__).parent / "data" / "robotrader.db"

        # 캐시 디렉토리 경로
        self.cache_dir = Path("cache")
        self.daily_dir = self.cache_dir / "daily"
        self.minute_dir = self.cache_dir / "minute_data"

        # DuckDB 캐시 매니저
        self.minute_cache = DataCache()
        self.daily_cache = DailyDataCache()

        # 디렉토리 생성
        self._ensure_directories()

    def _ensure_directories(self):
        """필요한 디렉토리 생성"""
        try:
            self.cache_dir.mkdir(exist_ok=True)
            self.daily_dir.mkdir(exist_ok=True)
            self.minute_dir.mkdir(exist_ok=True)

            self.logger.info(f"캐시 디렉토리 준비 완료: {self.cache_dir}")

        except Exception as e:
            self.logger.error(f"캐시 디렉토리 생성 오류: {e}")

    def initialize_api(self) -> bool:
        """API 매니저 초기화"""
        try:
            self.logger.info("📡 API 매니저 초기화 시작...")
            self.api_manager = KISAPIManager()

            if not self.api_manager.initialize():
                self.logger.error("API 초기화 실패")
                return False

            self.logger.info("API 매니저 초기화 완료")
            return True

        except Exception as e:
            self.logger.error(f"API 초기화 오류: {e}")
            return False

    def get_candidate_stocks_by_date(self, target_date: str) -> List[Dict[str, Any]]:
        """
        특정 날짜에 선정된 후보 종목 조회

        Args:
            target_date: 대상 날짜 (YYYYMMDD 형식)

        Returns:
            List[Dict]: 후보 종목 리스트
        """
        try:
            if not self.db_path.exists():
                self.logger.error(f"❌ 데이터베이스 파일 없음: {self.db_path}")
                return []

            # 날짜 형식 변환 (YYYYMMDD -> YYYY-MM-DD)
            try:
                date_obj = datetime.strptime(target_date, '%Y%m%d')
                target_date_str = date_obj.strftime('%Y-%m-%d')
            except ValueError:
                self.logger.error(f"❌ 잘못된 날짜 형식: {target_date} (YYYYMMDD 형식이어야 함)")
                return []

            with sqlite3.connect(self.db_path) as conn:
                # SQLite에서 날짜 비교를 위해 DATE() 함수 사용
                query = """
                SELECT DISTINCT stock_code, stock_name, selection_date, score, reasons
                FROM candidate_stocks
                WHERE DATE(selection_date) = ?
                ORDER BY selection_date, score DESC
                """

                cursor = conn.cursor()
                cursor.execute(query, (target_date_str,))
                rows = cursor.fetchall()

                candidates = []
                for row in rows:
                    candidates.append({
                        'stock_code': row[0],
                        'stock_name': row[1],
                        'selection_date': row[2],
                        'score': row[3],
                        'reasons': row[4]
                    })

                self.logger.info(f"📋 {target_date} 후보 종목 조회 완료: {len(candidates)}개")

                # 종목 리스트 로깅
                for i, candidate in enumerate(candidates[:10]):  # 상위 10개만 로깅
                    self.logger.info(f"  {i+1}. {candidate['stock_code']}({candidate['stock_name']}) "
                                   f"점수: {candidate['score']:.1f}")

                if len(candidates) > 10:
                    self.logger.info(f"  ... 외 {len(candidates) - 10}개 종목")

                return candidates

        except Exception as e:
            self.logger.error(f"❌ 후보 종목 조회 오류: {e}")
            return []

    def get_candidate_stocks_by_date_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        특정 기간에 선정된 후보 종목 조회 (중복 제거)

        Args:
            start_date: 시작 날짜 (YYYYMMDD 형식)
            end_date: 종료 날짜 (YYYYMMDD 형식)

        Returns:
            List[Dict]: 후보 종목 리스트 (날짜별로 그룹화)
        """
        try:
            if not self.db_path.exists():
                self.logger.error(f"❌ 데이터베이스 파일 없음: {self.db_path}")
                return []

            # 날짜 형식 변환 및 검증
            try:
                start_date_obj = datetime.strptime(start_date, '%Y%m%d')
                end_date_obj = datetime.strptime(end_date, '%Y%m%d')

                if start_date_obj > end_date_obj:
                    self.logger.error(f"❌ 시작날짜가 종료날짜보다 늦음: {start_date} > {end_date}")
                    return []

                start_date_str = start_date_obj.strftime('%Y-%m-%d')
                end_date_str = end_date_obj.strftime('%Y-%m-%d')

            except ValueError:
                self.logger.error(f"❌ 잘못된 날짜 형식: {start_date}, {end_date} (YYYYMMDD 형식이어야 함)")
                return []

            with sqlite3.connect(self.db_path) as conn:
                # 기간별 후보 종목 조회 (날짜별로 그룹화)
                query = """
                SELECT DISTINCT stock_code, stock_name,
                       DATE(selection_date) as selection_date,
                       score, reasons
                FROM candidate_stocks
                WHERE DATE(selection_date) BETWEEN ? AND ?
                ORDER BY selection_date, score DESC
                """

                cursor = conn.cursor()
                cursor.execute(query, (start_date_str, end_date_str))
                rows = cursor.fetchall()

                candidates = []
                for row in rows:
                    # 날짜를 YYYYMMDD 형식으로 다시 변환
                    selection_date_obj = datetime.strptime(row[2], '%Y-%m-%d')
                    selection_date_formatted = selection_date_obj.strftime('%Y%m%d')

                    candidates.append({
                        'stock_code': row[0],
                        'stock_name': row[1],
                        'selection_date': row[2],  # DB 형식 (YYYY-MM-DD)
                        'selection_date_formatted': selection_date_formatted,  # YYYYMMDD 형식
                        'score': row[3],
                        'reasons': row[4]
                    })

                # 날짜별 통계 로깅
                date_stats = {}
                for candidate in candidates:
                    date = candidate['selection_date_formatted']
                    if date not in date_stats:
                        date_stats[date] = 0
                    date_stats[date] += 1

                self.logger.info(f"📋 {start_date}~{end_date} 기간 후보 종목 조회 완료:")
                for date, count in sorted(date_stats.items()):
                    self.logger.info(f"  {date}: {count}개 종목")

                self.logger.info(f"📊 총 {len(candidates)}개 종목 (날짜별 중복 포함)")

                return candidates

        except Exception as e:
            self.logger.error(f"❌ 기간별 후보 종목 조회 오류: {e}")
            return []

    async def save_minute_data(self, stock_code: str, target_date: str) -> bool:
        """
        종목의 분봉 데이터 저장 (기존 get_full_trading_day_data_async 활용)

        Args:
            stock_code: 종목코드
            target_date: 대상 날짜 (YYYYMMDD)

        Returns:
            bool: 저장 성공 여부
        """
        try:
            # DuckDB에 데이터 존재 확인
            if self.minute_cache.has_data(stock_code, target_date):
                self.logger.debug(f"📉 {stock_code} 분봉 데이터 이미 존재 (스킵)")
                return True

            # 🆕 동적 시장 거래시간 가져오기
            target_date_obj = datetime.strptime(target_date, '%Y%m%d')
            market_hours = MarketHours.get_market_hours('KRX', target_date_obj)
            market_open = market_hours['market_open']
            market_close = market_hours['market_close']

            start_time_str = market_open.strftime('%H%M%S')
            end_time_str = market_close.strftime('%H%M%S')

            # 기존 함수 활용해서 전체 거래시간 분봉 데이터 수집 (동적 시간 적용)
            self.logger.info(f"📉 {stock_code} 분봉 데이터 수집 중... ({target_date} {start_time_str}~{end_time_str})")

            minute_data = await get_full_trading_day_data_async(
                stock_code=stock_code,
                target_date=target_date,
                selected_time=end_time_str,   # 동적 장마감 시간
                start_time=start_time_str     # 동적 장시작 시간
            )

            if minute_data is None or minute_data.empty:
                self.logger.warning(f"❌ {stock_code} 분봉 데이터 없음 ({target_date})")
                return False

            # 데이터 검증
            data_count = len(minute_data)
            if data_count == 0:
                self.logger.warning(f"❌ {stock_code} 분봉 데이터 비어있음")
                return False

            # DuckDB에 저장
            self.minute_cache.save_data(stock_code, target_date, minute_data)

            # 시간 범위 정보
            time_info = ""
            if 'time' in minute_data.columns and not minute_data.empty:
                start_time = minute_data.iloc[0]['time']
                end_time = minute_data.iloc[-1]['time']
                time_info = f" ({start_time}~{end_time})"
            elif 'datetime' in minute_data.columns and not minute_data.empty:
                start_dt = minute_data.iloc[0]['datetime']
                end_dt = minute_data.iloc[-1]['datetime']
                if hasattr(start_dt, 'strftime') and hasattr(end_dt, 'strftime'):
                    time_info = f" ({start_dt.strftime('%H%M%S')}~{end_dt.strftime('%H%M%S')})"

            self.logger.info(f"✅ {stock_code} 분봉 데이터 DuckDB 저장 완료: {data_count}건{time_info}")
            return True

        except Exception as e:
            self.logger.error(f"❌ {stock_code} 분봉 데이터 저장 오류: {e}")
            return False

    async def save_daily_data(self, stock_code: str, target_date: str, days_back: int = 100) -> bool:
        """
        종목의 일봉 데이터 저장 (KIS API 100건 제한 고려)

        Args:
            stock_code: 종목코드
            target_date: 대상 날짜 (YYYYMMDD)
            days_back: 과거 몇일치 (기본 100일, API 제한과 동일)

        Returns:
            bool: 저장 성공 여부
        """
        try:
            # DuckDB에 충분한 데이터 존재 확인
            if self.daily_cache.has_data(stock_code, min_records=days_back):
                self.logger.debug(f"{stock_code} 일봉 데이터 이미 존재 (스킵)")
                return True

            # 날짜 계산 (주말/휴일 고려해서 여유있게)
            target_date_obj = datetime.strptime(target_date, '%Y%m%d')
            start_date_obj = target_date_obj - timedelta(days=days_back + 50)  # 여유있게 50일 더

            start_date = start_date_obj.strftime('%Y%m%d')
            end_date = target_date

            self.logger.info(f"{stock_code} 일봉 데이터 수집 중... ({start_date} ~ {end_date})")

            # KIS API로 일봉 데이터 수집 (최대 100건)
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",          # 2: 차트 데이터 (output2), 1: 현재가 정보 (output1)
                div_code="J",           # KRX 시장
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",        # 일봉
                adj_prc="0"            # 0:수정주가, 1:원주가
            )

            if daily_data is None or daily_data.empty:
                self.logger.warning(f"{stock_code} 일봉 데이터 없음")
                return False

            # 데이터 검증 및 최신 100일만 유지
            original_count = len(daily_data)
            if original_count > days_back:
                daily_data = daily_data.tail(days_back)
                self.logger.debug(f"📈 {stock_code} 일봉 데이터 {original_count}건 → {days_back}건으로 조정")

            # DuckDB에 저장
            self.daily_cache.save_data(stock_code, daily_data)

            # 날짜 범위 정보
            date_info = ""
            if 'stck_bsop_date' in daily_data.columns and not daily_data.empty:
                start_date_actual = daily_data.iloc[0]['stck_bsop_date']
                end_date_actual = daily_data.iloc[-1]['stck_bsop_date']
                date_info = f" ({start_date_actual}~{end_date_actual})"

            self.logger.info(f"{stock_code} 일봉 데이터 DuckDB 저장 완료: {len(daily_data)}일치{date_info}")
            return True

        except Exception as e:
            self.logger.error(f"{stock_code} 일봉 데이터 저장 오류: {e}")
            return False

    async def save_all_candidate_data_range(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        특정 기간의 모든 후보 종목 데이터 저장

        Args:
            start_date: 시작 날짜 (YYYYMMDD)
            end_date: 종료 날짜 (YYYYMMDD)

        Returns:
            Dict: 저장 결과 통계
        """
        try:
            self.logger.info(f"🗄️ {start_date}~{end_date} 기간 후보 종목 데이터 저장 시작")

            # 1. API 초기화
            if not self.initialize_api():
                return {
                    'success': False,
                    'error': 'API 초기화 실패',
                    'date_range': f"{start_date}~{end_date}",
                    'total_stocks': 0,
                    'saved_minute': 0,
                    'saved_daily': 0
                }

            # 2. 기간별 후보 종목 조회
            candidates = self.get_candidate_stocks_by_date_range(start_date, end_date)

            if not candidates:
                return {
                    'success': True,
                    'message': f'{start_date}~{end_date} 기간에 선정된 후보 종목 없음',
                    'date_range': f"{start_date}~{end_date}",
                    'total_stocks': 0,
                    'saved_minute': 0,
                    'saved_daily': 0
                }

            # 3. 각 종목별 데이터 저장 (날짜별로 처리)
            total_stocks = len(candidates)
            saved_minute = 0
            saved_daily = 0
            failed_stocks = []

            for i, candidate in enumerate(candidates, 1):
                stock_code = candidate['stock_code']
                stock_name = candidate['stock_name']
                selection_date = candidate['selection_date_formatted']  # YYYYMMDD 형식

                try:
                    self.logger.info(f"📊 [{i}/{total_stocks}] {stock_code}({stock_name}) - {selection_date} 처리 중...")

                    # 분봉 데이터 저장 (해당 선정일 기준)
                    minute_success = await self.save_minute_data(stock_code, selection_date)
                    if minute_success:
                        saved_minute += 1

                    # API 호출 간격
                    await asyncio.sleep(0.5)

                    # 일봉 데이터 저장 (해당 선정일 기준)
                    daily_success = await self.save_daily_data(stock_code, selection_date)
                    if daily_success:
                        saved_daily += 1

                    # API 호출 간격
                    if i < total_stocks:
                        await asyncio.sleep(1.0)

                    self.logger.info(f"  ✅ {stock_code} ({selection_date}) 완료 - "
                                   f"분봉: {'✓' if minute_success else '✗'}, "
                                   f"일봉: {'✓' if daily_success else '✗'}")

                except Exception as e:
                    self.logger.error(f"❌ {stock_code}({stock_name}) - {selection_date} 처리 실패: {e}")
                    failed_stocks.append(f"{stock_code}({stock_name}) - {selection_date}")

            # 4. 결과 정리
            result = {
                'success': True,
                'date_range': f"{start_date}~{end_date}",
                'total_stocks': total_stocks,
                'saved_minute': saved_minute,
                'saved_daily': saved_daily,
                'failed_stocks': failed_stocks
            }

            self.logger.info(f"🎯 {start_date}~{end_date} 기간 데이터 저장 완료!")
            self.logger.info(f"   📊 총 종목: {total_stocks}개")
            self.logger.info(f"   📉 분봉 저장: {saved_minute}개")
            self.logger.info(f"   📈 일봉 저장: {saved_daily}개")
            if failed_stocks:
                self.logger.warning(f"   ❌ 실패: {len(failed_stocks)}개")
                for failed_stock in failed_stocks[:5]:  # 상위 5개만 로깅
                    self.logger.warning(f"      - {failed_stock}")

            return result

        except Exception as e:
            self.logger.error(f"❌ 기간별 후보 종목 데이터 저장 오류: {e}")
            return {
                'success': False,
                'error': str(e),
                'date_range': f"{start_date}~{end_date}",
                'total_stocks': 0,
                'saved_minute': 0,
                'saved_daily': 0
            }

    async def save_all_candidate_data(self, target_date: str) -> Dict[str, Any]:
        """
        특정 날짜의 모든 후보 종목 데이터 저장

        Args:
            target_date: 대상 날짜 (YYYYMMDD)

        Returns:
            Dict: 저장 결과 통계
        """
        try:
            self.logger.info(f"🗄️ {target_date} 후보 종목 데이터 저장 시작")

            # 1. API 초기화
            if not self.initialize_api():
                return {
                    'success': False,
                    'error': 'API 초기화 실패',
                    'total_stocks': 0,
                    'saved_minute': 0,
                    'saved_daily': 0
                }

            # 2. 후보 종목 조회
            candidates = self.get_candidate_stocks_by_date(target_date)

            if not candidates:
                return {
                    'success': True,
                    'message': f'{target_date} 날짜에 선정된 후보 종목 없음',
                    'total_stocks': 0,
                    'saved_minute': 0,
                    'saved_daily': 0
                }

            # 3. 각 종목별 데이터 저장
            total_stocks = len(candidates)
            saved_minute = 0
            saved_daily = 0
            failed_stocks = []

            for i, candidate in enumerate(candidates, 1):
                stock_code = candidate['stock_code']
                stock_name = candidate['stock_name']

                try:
                    self.logger.info(f"📊 [{i}/{total_stocks}] {stock_code}({stock_name}) 처리 중...")

                    # 분봉 데이터 저장 (120건 제한 자동 우회)
                    minute_success = await self.save_minute_data(stock_code, target_date)
                    if minute_success:
                        saved_minute += 1

                    # API 호출 간격 (분봉 처리 후 잠시 대기)
                    await asyncio.sleep(0.5)

                    # 일봉 데이터 저장 (100건 제한 고려)
                    daily_success = await self.save_daily_data(stock_code, target_date)
                    if daily_success:
                        saved_daily += 1

                    # API 호출 간격 (다음 종목 처리 전 대기)
                    if i < total_stocks:
                        await asyncio.sleep(1.0)

                    self.logger.info(f"  ✅ {stock_code} 완료 - "
                                   f"분봉: {'✓' if minute_success else '✗'}, "
                                   f"일봉: {'✓' if daily_success else '✗'}")

                except Exception as e:
                    self.logger.error(f"❌ {stock_code}({stock_name}) 처리 실패: {e}")
                    failed_stocks.append(f"{stock_code}({stock_name})")

            # 4. 결과 정리
            result = {
                'success': True,
                'target_date': target_date,
                'total_stocks': total_stocks,
                'saved_minute': saved_minute,
                'saved_daily': saved_daily,
                'failed_stocks': failed_stocks
            }

            self.logger.info(f"🎯 {target_date} 데이터 저장 완료!")
            self.logger.info(f"   📊 총 종목: {total_stocks}개")
            self.logger.info(f"   📉 분봉 저장: {saved_minute}개")
            self.logger.info(f"   📈 일봉 저장: {saved_daily}개")
            if failed_stocks:
                self.logger.warning(f"   ❌ 실패: {len(failed_stocks)}개")
                for failed_stock in failed_stocks[:5]:  # 상위 5개만 로깅
                    self.logger.warning(f"      - {failed_stock}")

            return result

        except Exception as e:
            self.logger.error(f"❌ 후보 종목 데이터 저장 오류: {e}")
            return {
                'success': False,
                'error': str(e),
                'total_stocks': 0,
                'saved_minute': 0,
                'saved_daily': 0
            }

    def get_cache_summary(self, target_date: str = None) -> Dict[str, Any]:
        """
        캐시 상태 요약

        Args:
            target_date: 대상 날짜 (YYYYMMDD, None이면 전체)

        Returns:
            Dict: 캐시 상태 정보
        """
        try:
            summary = {
                'cache_dir': str(self.cache_dir),
                'daily_dir': str(self.daily_dir),
                'minute_dir': str(self.minute_dir)
            }

            # 일봉 파일 수
            if target_date:
                daily_files = list(self.daily_dir.glob(f"*_{target_date}_daily.pkl"))
                summary['target_date'] = target_date
                summary['daily_files_count'] = len(daily_files)
            else:
                daily_files = list(self.daily_dir.glob("*_daily.pkl"))
                summary['daily_files_count'] = len(daily_files)

            # 분봉 파일 수
            if target_date:
                minute_files = list(self.minute_dir.glob(f"*_{target_date}.pkl"))
                summary['minute_files_count'] = len(minute_files)
            else:
                minute_files = list(self.minute_dir.glob("*.pkl"))
                summary['minute_files_count'] = len(minute_files)

            # 총 캐시 크기
            total_size = 0
            for file_path in self.cache_dir.rglob("*.pkl"):
                try:
                    total_size += file_path.stat().st_size
                except:
                    pass

            summary['total_cache_size_mb'] = round(total_size / (1024 * 1024), 2)

            return summary

        except Exception as e:
            self.logger.error(f"❌ 캐시 요약 생성 오류: {e}")
            return {}


async def main():
    """메인 함수"""

    # 명령행 인수 확인
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("사용법:")
        print("  1. 단일 날짜: python save_candidate_data.py <날짜>")
        print("  2. 기간 입력: python save_candidate_data.py <시작날짜> <종료날짜>")
        print("")
        print("예시:")
        print("  python save_candidate_data.py 20250918")
        print("  python save_candidate_data.py 20250915 20250918")
        print("")
        print("기능:")
        print("- candidate_stocks 테이블에서 해당 날짜(기간) 선정 종목 조회")
        print("- 분봉 데이터: 09:00~15:30 전체 수집 (120건 제한 자동 우회)")
        print("- 일봉 데이터: 과거 100일치 수집")
        print("- cache/minute_data 및 cache/daily 폴더에 저장")
        sys.exit(1)

    # 날짜 파라미터 처리
    if len(sys.argv) == 2:
        # 단일 날짜
        start_date = end_date = sys.argv[1]
        is_range = False
    else:
        # 기간 입력
        start_date = sys.argv[1]
        end_date = sys.argv[2]
        is_range = True

    # 날짜 형식 검증
    try:
        start_date_obj = datetime.strptime(start_date, '%Y%m%d')
        end_date_obj = datetime.strptime(end_date, '%Y%m%d')

        if start_date_obj > end_date_obj:
            print(f"시작날짜가 종료날짜보다 늦음: {start_date} > {end_date}")
            sys.exit(1)

    except ValueError:
        print(f"잘못된 날짜 형식: {start_date}, {end_date}")
        print("YYYYMMDD 형식으로 입력해주세요 (예: 20250918)")
        sys.exit(1)

    # 데이터 저장 실행
    if is_range:
        print(f"{start_date}~{end_date} 기간 후보 종목 데이터 저장 시작...")
    else:
        print(f"{start_date} 후보 종목 데이터 저장 시작...")

    print("KIS API 제한 고려하여 자동으로 여러 번 호출 처리")
    print("")

    saver = CandidateDataSaver()

    # 기간별 또는 단일 날짜 처리
    if is_range:
        result = await saver.save_all_candidate_data_range(start_date, end_date)
    else:
        result = await saver.save_all_candidate_data(start_date)

    # 결과 출력
    if result['success']:
        date_display = result.get('date_range', start_date)
        print(f"\n{date_display} 데이터 저장 완료!")
        print(f"   총 종목: {result['total_stocks']}개")
        print(f"   분봉 저장: {result['saved_minute']}개")
        print(f"   일봉 저장: {result['saved_daily']}개")

        if result.get('failed_stocks'):
            print(f"   실패: {len(result['failed_stocks'])}개")
            for failed_stock in result['failed_stocks'][:3]:
                print(f"     - {failed_stock}")

        # 캐시 상태 출력
        if is_range:
            # 기간별 캐시 상태는 전체 조회
            cache_summary = saver.get_cache_summary()
            print(f"\n📁 캐시 상태 (전체):")
            print(f"   일봉 파일: {cache_summary.get('daily_files_count', 0)}개")
            print(f"   분봉 파일: {cache_summary.get('minute_files_count', 0)}개")
        else:
            # 단일 날짜는 해당 날짜만
            cache_summary = saver.get_cache_summary(start_date)
            print(f"\n📁 캐시 상태:")
            print(f"   일봉 파일 ({start_date}): {cache_summary.get('daily_files_count', 0)}개")
            print(f"   분봉 파일 ({start_date}): {cache_summary.get('minute_files_count', 0)}개")

        print(f"   총 캐시 크기: {cache_summary.get('total_cache_size_mb', 0)}MB")

    else:
        print(f"\n데이터 저장 실패!")
        print(f"   오류: {result.get('error', '알 수 없는 오류')}")
        if result.get('message'):
            print(f"   메시지: {result['message']}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n실행 오류: {e}")
        sys.exit(1)