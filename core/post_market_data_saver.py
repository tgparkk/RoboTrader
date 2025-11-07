"""
장 마감 후 데이터 저장 전담 모듈
- 분봉 데이터 저장 (cache/minute_data/)
- 일봉 데이터 저장 (cache/daily/)
- 텍스트 파일 저장 (디버깅용)
"""
import pickle
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from utils.logger import setup_logger
from utils.korean_time import now_kst
from api.kis_market_api import get_inquire_daily_itemchartprice


class PostMarketDataSaver:
    """장 마감 후 데이터 저장 클래스"""

    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.minute_cache_dir = Path("cache/minute_data")
        self.daily_cache_dir = Path("cache/daily")

        # 디렉토리 생성
        self.minute_cache_dir.mkdir(parents=True, exist_ok=True)
        self.daily_cache_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("장 마감 후 데이터 저장기 초기화 완료")

    def save_minute_data_to_cache(self, intraday_manager) -> Dict[str, int]:
        """
        메모리에 있는 모든 종목의 분봉 데이터를 cache/minute_data에 pickle로 저장

        Args:
            intraday_manager: IntradayStockManager 인스턴스

        Returns:
            Dict: {'total': 전체 종목 수, 'saved': 저장 성공 수, 'failed': 실패 수}
        """
        try:
            current_time = now_kst()
            today = current_time.strftime('%Y%m%d')

            # intraday_manager에서 종목 목록 가져오기
            with intraday_manager._lock:
                stock_codes = list(intraday_manager.selected_stocks.keys())

            if not stock_codes:
                self.logger.info("💾 분봉 캐시 저장할 종목 없음")
                return {'total': 0, 'saved': 0, 'failed': 0}

            saved_count = 0
            failed_count = 0

            for stock_code in stock_codes:
                try:
                    # combined_data (historical + realtime 병합) 가져오기
                    combined_data = intraday_manager.get_combined_chart_data(stock_code)

                    if combined_data is None or combined_data.empty:
                        self.logger.warning(f"⚠️ [{stock_code}] 저장할 분봉 데이터 없음")
                        failed_count += 1
                        continue

                    # 당일 데이터만 필터링
                    before_count = len(combined_data)
                    if 'date' in combined_data.columns:
                        combined_data = combined_data[combined_data['date'].astype(str) == today].copy()
                    elif 'datetime' in combined_data.columns:
                        combined_data['date_str'] = pd.to_datetime(combined_data['datetime']).dt.strftime('%Y%m%d')
                        combined_data = combined_data[combined_data['date_str'] == today].copy()
                        if 'date_str' in combined_data.columns:
                            combined_data = combined_data.drop('date_str', axis=1)

                    if before_count != len(combined_data):
                        removed = before_count - len(combined_data)
                        self.logger.warning(f"⚠️ [{stock_code}] 전날 데이터 {removed}건 제외: {before_count} → {len(combined_data)}건")

                    if combined_data.empty:
                        self.logger.warning(f"⚠️ [{stock_code}] 당일 분봉 데이터 없음")
                        failed_count += 1
                        continue

                    # 파일명: 종목코드_날짜.pkl
                    cache_file = self.minute_cache_dir / f"{stock_code}_{today}.pkl"

                    # pickle로 저장
                    with open(cache_file, 'wb') as f:
                        pickle.dump(combined_data, f)

                    saved_count += 1
                    self.logger.debug(f"💾 [{stock_code}] 분봉 캐시 저장: {len(combined_data)}건 → {cache_file.name}")

                except Exception as e:
                    self.logger.error(f"❌ [{stock_code}] 분봉 캐시 저장 실패: {e}")
                    failed_count += 1

            self.logger.info(f"✅ 분봉 데이터 캐시 저장 완료: {saved_count}/{len(stock_codes)}개 종목 성공, {failed_count}개 실패")

            return {
                'total': len(stock_codes),
                'saved': saved_count,
                'failed': failed_count
            }

        except Exception as e:
            self.logger.error(f"❌ 분봉 데이터 캐시 저장 중 오류: {e}")
            return {'total': 0, 'saved': 0, 'failed': 0}

    def save_minute_data_to_file(self, intraday_manager) -> Optional[str]:
        """
        메모리에 있는 모든 종목의 분봉 데이터를 텍스트 파일로 저장 (디버깅용)

        Args:
            intraday_manager: IntradayStockManager 인스턴스

        Returns:
            str: 저장된 파일명 또는 None
        """
        try:
            current_time = now_kst()
            filename = f"memory_minute_data_{current_time.strftime('%Y%m%d_%H%M%S')}.txt"

            with intraday_manager._lock:
                stock_codes = list(intraday_manager.selected_stocks.keys())

            if not stock_codes:
                self.logger.info("📝 텍스트 저장할 종목 없음")
                return None

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"=== 장 마감 후 분봉 데이터 덤프 ===\n")
                f.write(f"저장 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"종목 수: {len(stock_codes)}\n")
                f.write("=" * 80 + "\n\n")

                for stock_code in stock_codes:
                    try:
                        combined_data = intraday_manager.get_combined_chart_data(stock_code)

                        if combined_data is None or combined_data.empty:
                            f.write(f"[{stock_code}] 데이터 없음\n\n")
                            continue

                        f.write(f"[{stock_code}] 분봉 데이터: {len(combined_data)}건\n")
                        f.write("-" * 80 + "\n")
                        f.write(combined_data.to_string())
                        f.write("\n\n")

                    except Exception as e:
                        f.write(f"[{stock_code}] 오류: {e}\n\n")

            self.logger.info(f"✅ 분봉 데이터 텍스트 파일 저장 완료: {filename}")
            return filename

        except Exception as e:
            self.logger.error(f"❌ 분봉 데이터 텍스트 파일 저장 실패: {e}")
            return None

    def save_daily_data(self, stock_codes: List[str], target_date: str = None, days_back: int = 100) -> Dict[str, int]:
        """
        종목들의 일봉 데이터를 API로 조회하여 저장

        Args:
            stock_codes: 저장할 종목 코드 리스트
            target_date: 기준 날짜 (YYYYMMDD), None이면 오늘
            days_back: 과거 몇 일치 데이터 저장 (기본 100일)

        Returns:
            Dict: {'total': 전체 종목 수, 'saved': 저장 성공 수, 'failed': 실패 수}
        """
        try:
            if target_date is None:
                target_date = now_kst().strftime('%Y%m%d')

            if not stock_codes:
                self.logger.info("💾 일봉 저장할 종목 없음")
                return {'total': 0, 'saved': 0, 'failed': 0}

            self.logger.info(f"📊 일봉 데이터 저장 시작: {len(stock_codes)}개 종목 (기준일: {target_date})")

            saved_count = 0
            failed_count = 0

            for stock_code in stock_codes:
                try:
                    # 파일명 생성
                    daily_file = self.daily_cache_dir / f"{stock_code}_{target_date}_daily.pkl"

                    # 이미 파일이 존재하면 스킵
                    if daily_file.exists():
                        self.logger.debug(f"⏭️ [{stock_code}] 일봉 데이터 이미 존재 (스킵): {daily_file.name}")
                        saved_count += 1  # 이미 있는 것도 성공으로 카운트
                        continue

                    # 날짜 계산 (주말/휴일 고려해서 여유있게)
                    target_date_obj = datetime.strptime(target_date, '%Y%m%d')
                    start_date_obj = target_date_obj - timedelta(days=days_back + 50)  # 여유있게 50일 더

                    start_date = start_date_obj.strftime('%Y%m%d')
                    end_date = target_date

                    self.logger.info(f"📡 [{stock_code}] 일봉 데이터 API 조회 중... ({start_date} ~ {end_date})")

                    # KIS API로 일봉 데이터 수집 (최대 100건)
                    daily_data = get_inquire_daily_itemchartprice(
                        output_dv="2",          # 2: 차트 데이터 (output2)
                        div_code="J",           # KRX 시장
                        itm_no=stock_code,
                        inqr_strt_dt=start_date,
                        inqr_end_dt=end_date,
                        period_code="D",        # 일봉
                        adj_prc="0"             # 0:수정주가
                    )

                    if daily_data is None or daily_data.empty:
                        self.logger.warning(f"⚠️ [{stock_code}] 일봉 데이터 없음")
                        failed_count += 1
                        continue

                    # 데이터 검증 및 최신 100일만 유지
                    original_count = len(daily_data)
                    if original_count > days_back:
                        daily_data = daily_data.tail(days_back)
                        self.logger.debug(f"📈 [{stock_code}] 일봉 데이터 {original_count}건 → {days_back}건으로 조정")

                    # pickle로 저장
                    with open(daily_file, 'wb') as f:
                        pickle.dump(daily_data, f)

                    # 날짜 범위 정보
                    date_info = ""
                    if 'stck_bsop_date' in daily_data.columns and not daily_data.empty:
                        start_date_actual = daily_data.iloc[0]['stck_bsop_date']
                        end_date_actual = daily_data.iloc[-1]['stck_bsop_date']
                        date_info = f" ({start_date_actual}~{end_date_actual})"

                    saved_count += 1
                    self.logger.info(f"✅ [{stock_code}] 일봉 데이터 저장 완료: {len(daily_data)}일치{date_info}")

                except Exception as e:
                    self.logger.error(f"❌ [{stock_code}] 일봉 데이터 저장 실패: {e}")
                    failed_count += 1

            self.logger.info(f"✅ 일봉 데이터 저장 완료: {saved_count}/{len(stock_codes)}개 종목 성공, {failed_count}개 실패")

            return {
                'total': len(stock_codes),
                'saved': saved_count,
                'failed': failed_count
            }

        except Exception as e:
            self.logger.error(f"❌ 일봉 데이터 저장 중 오류: {e}")
            return {'total': 0, 'saved': 0, 'failed': 0}

    def save_all_data(self, intraday_manager) -> Dict[str, any]:
        """
        장 마감 후 모든 데이터 저장 (분봉 + 일봉 + 텍스트)

        Args:
            intraday_manager: IntradayStockManager 인스턴스

        Returns:
            Dict: 전체 저장 결과
        """
        try:
            self.logger.info("=" * 80)
            self.logger.info("🏁 장 마감 후 데이터 저장 시작")
            self.logger.info("=" * 80)

            # 종목 목록 가져오기
            with intraday_manager._lock:
                stock_codes = list(intraday_manager.selected_stocks.keys())

            if not stock_codes:
                self.logger.warning("⚠️ 저장할 종목이 없습니다")
                return {
                    'success': False,
                    'message': '저장할 종목 없음',
                    'minute_data': {'total': 0, 'saved': 0, 'failed': 0},
                    'daily_data': {'total': 0, 'saved': 0, 'failed': 0},
                    'text_file': None
                }

            self.logger.info(f"📋 대상 종목: {len(stock_codes)}개")
            self.logger.info(f"   종목 코드: {', '.join(stock_codes)}")

            # 1. 분봉 데이터 저장 (pkl)
            self.logger.info("\n" + "=" * 80)
            self.logger.info("1️⃣ 분봉 데이터 pkl 저장")
            self.logger.info("=" * 80)
            minute_result = self.save_minute_data_to_cache(intraday_manager)

            # 2. 일봉 데이터 저장 (pkl)
            self.logger.info("\n" + "=" * 80)
            self.logger.info("2️⃣ 일봉 데이터 pkl 저장")
            self.logger.info("=" * 80)
            daily_result = self.save_daily_data(stock_codes)

            # 3. 분봉 데이터 텍스트 파일 저장 (디버깅용)
            self.logger.info("\n" + "=" * 80)
            self.logger.info("3️⃣ 분봉 데이터 텍스트 파일 저장 (디버깅용)")
            self.logger.info("=" * 80)
            text_file = self.save_minute_data_to_file(intraday_manager)

            # 결과 요약
            self.logger.info("\n" + "=" * 80)
            self.logger.info("✅ 장 마감 후 데이터 저장 완료")
            self.logger.info("=" * 80)
            self.logger.info(f"📊 분봉 데이터: {minute_result['saved']}/{minute_result['total']}개 저장 성공")
            self.logger.info(f"📊 일봉 데이터: {daily_result['saved']}/{daily_result['total']}개 저장 성공")
            self.logger.info(f"📝 텍스트 파일: {text_file if text_file else '저장 실패'}")
            self.logger.info("=" * 80)

            return {
                'success': True,
                'minute_data': minute_result,
                'daily_data': daily_result,
                'text_file': text_file
            }

        except Exception as e:
            self.logger.error(f"❌ 장 마감 후 데이터 저장 중 오류: {e}")
            return {
                'success': False,
                'error': str(e),
                'minute_data': {'total': 0, 'saved': 0, 'failed': 0},
                'daily_data': {'total': 0, 'saved': 0, 'failed': 0},
                'text_file': None
            }


# 독립 실행용 (테스트)
if __name__ == "__main__":
    print("이 모듈은 직접 실행할 수 없습니다.")
    print("main.py 또는 intraday_stock_manager.py에서 호출하여 사용하세요.")
