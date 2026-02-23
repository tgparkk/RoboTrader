"""
실시간 종목 스크리너 - HTS 조건검색 대체

price_position 전략에 최적화된 코드 기반 스크리닝.
3단계 파이프라인으로 거래량순위 API 기반 후보 발굴.

Phase 1: get_volume_rank() 4회 호출 (KOSPI/KOSDAQ × 거래금액순/거래증가율) → ~80-100 후보
Phase 2: 등락률/가격/거래대금 기본 필터 (API 호출 없음)
Phase 3: get_inquire_price()로 시가 대비 정밀 검증
"""
import time
import traceback
from datetime import datetime
from typing import List, Dict, Optional, Set
from dataclasses import dataclass

from api.kis_market_api import get_volume_rank, get_inquire_price
from utils.logger import setup_logger
from utils.korean_time import now_kst


@dataclass
class ScreenedStock:
    """스크리닝된 종목 정보"""
    code: str
    name: str
    market: str
    current_price: int
    change_rate: float      # 전일대비 등락률 (%)
    open_price: int         # 당일 시가
    pct_from_open: float    # 시가 대비 등락률 (%)
    volume: int             # 누적 거래량
    trading_amount: int     # 누적 거래대금
    score: float            # 스크리닝 점수
    reason: str             # 선정 사유


class StockScreener:
    """
    실시간 종목 스크리너

    거래량순위 API 기반 3단계 파이프라인으로
    price_position 전략에 적합한 후보 종목을 발굴합니다.
    """

    def __init__(self, config: dict = None):
        self.logger = setup_logger(__name__)
        self.config = config or {}

        # 당일 이미 추가된 종목 (중복 방지)
        self._added_stocks: Set[str] = set()
        # 당일 총 추가된 후보 수
        self._total_candidates_today: int = 0
        # Phase 3에서 거부된 종목 (재조회 방지)
        self._rejected_stocks: Set[str] = set()
        # 날짜 변경 감지용
        self._current_date: Optional[str] = None

    def reset_daily_state(self):
        """일일 상태 초기화"""
        self._added_stocks.clear()
        self._total_candidates_today = 0
        self._rejected_stocks.clear()
        self.logger.info("[스크리너] 일일 상태 초기화 완료")

    def mark_stock_added(self, stock_code: str):
        """종목이 trading pool에 추가되었음을 기록"""
        self._added_stocks.add(stock_code)
        self._total_candidates_today += 1

    def scan(self) -> List[ScreenedStock]:
        """
        전체 스크리닝 파이프라인 실행

        Returns:
            스크리닝 통과한 종목 리스트 (최대 max_candidates_per_scan개)
        """
        try:
            current_time = now_kst()

            # 날짜 변경 감지 → 자동 리셋
            today = current_time.strftime('%Y%m%d')
            if self._current_date != today:
                self.reset_daily_state()
                self._current_date = today

            # 일일 최대 후보 총수 체크
            max_total = self.config.get('max_total_candidates', 15)
            if self._total_candidates_today >= max_total:
                self.logger.debug(
                    f"[스크리너] 일일 최대 후보 {max_total}개 도달, 스캔 생략"
                )
                return []

            # Phase 1: 거래량순위 API 조회
            raw_stocks = self._scan_volume_rank()
            if not raw_stocks:
                self.logger.debug("[스크리너] Phase1: 후보 없음")
                return []

            # Phase 2: 기본 필터
            filtered_stocks = self._apply_basic_filters(raw_stocks)
            if not filtered_stocks:
                self.logger.debug("[스크리너] Phase2: 필터 통과 종목 없음")
                return []

            # Phase 3: 시가 기반 정밀 검증
            candidates = self._validate_with_price_data(filtered_stocks)

            return candidates

        except Exception as e:
            self.logger.error(f"[스크리너] 스캔 오류: {e}")
            self.logger.error(traceback.format_exc())
            return []

    def _scan_volume_rank(self) -> List[Dict]:
        """
        Phase 1: 거래량순위 API 2회 호출하여 후보 풀 구성

        KOSPI/KOSDAQ 각각 거래금액순 + 거래증가율 = 4회 호출
        → 중복 제거 후 ~80-100개 후보

        Returns:
            중복 제거된 종목 딕셔너리 리스트
        """
        all_stocks = {}  # {stock_code: row_dict} for dedup

        min_price = str(self.config.get('min_price', 5000))
        max_price = str(self.config.get('max_price', 500000))

        # 시장별 × 정렬기준별 스캔 (4회 호출)
        scan_configs = [
            ("0001", "3", "KOSPI-거래금액순"),
            ("0001", "1", "KOSPI-거래증가율"),
            ("1001", "3", "KOSDAQ-거래금액순"),
            ("1001", "1", "KOSDAQ-거래증가율"),
        ]

        for market_code, sort_code, label in scan_configs:
            try:
                df = get_volume_rank(
                    fid_input_iscd=market_code,
                    fid_div_cls_code="1",           # 보통주
                    fid_blng_cls_code=sort_code,
                    fid_input_price_1=min_price,
                    fid_input_price_2=max_price,
                )
                if df is not None and not df.empty:
                    # 첫 호출 시 컬럼명 로깅 (필드 확인용)
                    if not hasattr(self, '_columns_logged'):
                        self.logger.info(
                            f"[스크리너] 거래량순위 API 컬럼: {list(df.columns)}"
                        )
                        self._columns_logged = True

                    new_count = 0
                    for _, row in df.iterrows():
                        code = self._extract_stock_code(row)
                        if code and code not in all_stocks:
                            all_stocks[code] = row.to_dict()
                            new_count += 1
                    self.logger.info(
                        f"[스크리너] Phase1-{label}: {len(df)}건 조회, 신규 {new_count}건"
                    )
            except Exception as e:
                self.logger.error(f"[스크리너] Phase1-{label} 오류: {e}")

            time.sleep(0.1)  # API rate limit 준수

        self.logger.info(
            f"[스크리너] Phase1 완료: 중복제거 후 {len(all_stocks)}개 종목"
        )
        return list(all_stocks.values())

    def _apply_basic_filters(self, raw_stocks: List[Dict]) -> List[Dict]:
        """
        Phase 2: 기본 필터 적용 (API 호출 없음)

        Filters:
        1. 등락률: 0.5% ~ 5.0%
        2. 가격: 5,000 ~ 500,000원
        3. 거래대금: 10억+
        4. 이미 추가된/거부된 종목 제외
        5. 종목명 필터 (우선주, ETF, ETN 등 제외)
        """
        min_change = self.config.get('min_change_rate', 0.5)
        max_change = self.config.get('max_change_rate', 5.0)
        min_price = self.config.get('min_price', 5000)
        max_price = self.config.get('max_price', 500000)
        min_amount = self.config.get('min_trading_amount', 1_000_000_000)

        filtered = []
        stats = {
            'total': len(raw_stocks), 'already_known': 0,
            'name_filter': 0, 'change_rate': 0,
            'price': 0, 'amount': 0, 'passed': 0
        }

        exclude_keywords = ['우B', 'ETF', 'ETN', '스팩', 'SPAC', '리츠']

        for stock in raw_stocks:
            code = self._extract_stock_code(stock)
            name = self._extract_stock_name(stock)

            if not code:
                continue

            # 이미 추가/거부된 종목 제외
            if code in self._added_stocks or code in self._rejected_stocks:
                stats['already_known'] += 1
                continue

            # 종목명 필터 (우선주, ETF, ETN, 스팩, 리츠)
            if any(kw in name for kw in exclude_keywords):
                stats['name_filter'] += 1
                continue
            # 우선주 코드 패턴 (끝자리 5)
            if len(code) == 6 and code[-1] == '5':
                stats['name_filter'] += 1
                continue

            # 등락률 필터
            change_rate = self._safe_float(stock.get('prdy_ctrt', '0'))
            if change_rate < min_change or change_rate > max_change:
                stats['change_rate'] += 1
                continue

            # 가격 필터
            price = self._safe_int(stock.get('stck_prpr', '0'))
            if price < min_price or price > max_price:
                stats['price'] += 1
                continue

            # 거래대금 필터
            tr_amount = self._safe_int(stock.get('acml_tr_pbmn', '0'))
            if tr_amount < min_amount:
                stats['amount'] += 1
                continue

            stats['passed'] += 1
            filtered.append(stock)

        self.logger.info(
            f"[스크리너] Phase2: {stats['total']}개 -> {stats['passed']}개 통과 "
            f"(등락률:{stats['change_rate']}, 가격:{stats['price']}, "
            f"거래대금:{stats['amount']}, 기존:{stats['already_known']}, "
            f"종목명:{stats['name_filter']})"
        )
        return filtered

    def _validate_with_price_data(self, filtered_stocks: List[Dict]) -> List[ScreenedStock]:
        """
        Phase 3: 현재가 API로 시가 기반 정밀 검증

        검증 항목:
        1. 시가 대비 상승률: 0.8% ~ 4.0%
        2. 갭 필터: 시가 vs 전일종가 < 3%
        3. 점수 계산 → 상위 N개 반환
        """
        max_checks = self.config.get('max_phase3_checks', 15)
        min_pct = self.config.get('min_pct_from_open', 0.8)
        max_pct = self.config.get('max_pct_from_open', 4.0)
        max_gap = self.config.get('max_gap_pct', 3.0)
        max_per_scan = self.config.get('max_candidates_per_scan', 5)

        candidates = []
        stocks_to_check = filtered_stocks[:max_checks]
        checked = 0
        rejected_reasons = {'price_fail': 0, 'pct_filter': 0, 'gap_filter': 0, 'error': 0}

        for i, stock in enumerate(stocks_to_check):
            code = self._extract_stock_code(stock)
            name = self._extract_stock_name(stock)

            if not code:
                continue

            try:
                # API rate limiting (80ms 간격)
                if i > 0:
                    time.sleep(0.08)

                price_df = get_inquire_price(itm_no=code)
                if price_df is None or price_df.empty:
                    self.logger.debug(f"[스크리너] {code}({name}): 현재가 조회 실패")
                    self._rejected_stocks.add(code)
                    rejected_reasons['price_fail'] += 1
                    continue

                checked += 1
                row = price_df.iloc[0]

                current_price = self._safe_int(row.get('stck_prpr', '0'))
                open_price = self._safe_int(row.get('stck_oprc', '0'))
                prev_close = self._safe_int(row.get('stck_sdpr', '0'))
                high_price = self._safe_int(row.get('stck_hgpr', '0'))
                low_price = self._safe_int(row.get('stck_lwpr', '0'))
                volume = self._safe_int(row.get('acml_vol', '0'))
                tr_amount = self._safe_int(row.get('acml_tr_pbmn', '0'))
                change_rate = self._safe_float(row.get('prdy_ctrt', '0'))

                if open_price <= 0 or current_price <= 0:
                    self._rejected_stocks.add(code)
                    rejected_reasons['price_fail'] += 1
                    continue

                # 시가 대비 상승률
                pct_from_open = (current_price / open_price - 1) * 100

                # 시가 대비 필터
                if pct_from_open < min_pct or pct_from_open >= max_pct:
                    self.logger.debug(
                        f"[스크리너] {code}({name}): "
                        f"시가대비 {pct_from_open:.1f}% (범위 {min_pct}~{max_pct}%)"
                    )
                    rejected_reasons['pct_filter'] += 1
                    continue

                # 갭 필터 (시가 vs 전일종가)
                if prev_close > 0:
                    gap_pct = abs(open_price / prev_close - 1) * 100
                    if gap_pct > max_gap:
                        self.logger.debug(
                            f"[스크리너] {code}({name}): "
                            f"갭 {gap_pct:.1f}% > {max_gap}%"
                        )
                        self._rejected_stocks.add(code)
                        rejected_reasons['gap_filter'] += 1
                        continue

                # 점수 계산
                score = self._calculate_score(
                    pct_from_open=pct_from_open,
                    change_rate=change_rate,
                    tr_amount=tr_amount,
                    current_price=current_price,
                    high_price=high_price,
                    low_price=low_price,
                )

                candidates.append(ScreenedStock(
                    code=code,
                    name=name,
                    market='KOSPI',
                    current_price=current_price,
                    change_rate=change_rate,
                    open_price=open_price,
                    pct_from_open=pct_from_open,
                    volume=volume,
                    trading_amount=tr_amount,
                    score=score,
                    reason=(
                        f"시가+{pct_from_open:.1f}%, "
                        f"등락{change_rate:+.1f}%, "
                        f"점수{score:.0f}"
                    ),
                ))

            except Exception as e:
                self.logger.warning(
                    f"[스크리너] {code}({name}) Phase3 검증 오류: {e}"
                )
                rejected_reasons['error'] += 1
                continue

        # 점수순 정렬, 상위 N개 반환
        candidates.sort(key=lambda x: x.score, reverse=True)
        result = candidates[:max_per_scan]

        self.logger.info(
            f"[스크리너] Phase3: {checked}개 검증 -> {len(candidates)}개 통과 "
            f"-> 상위 {len(result)}개 선정 "
            f"(시가대비:{rejected_reasons['pct_filter']}, "
            f"갭:{rejected_reasons['gap_filter']}, "
            f"조회실패:{rejected_reasons['price_fail']})"
        )

        for s in result:
            self.logger.info(
                f"[스크리너] 선정: {s.code}({s.name}) "
                f"현재가{s.current_price:,}원, "
                f"시가대비+{s.pct_from_open:.1f}%, "
                f"점수{s.score:.0f}"
            )

        return result

    def _calculate_score(
        self,
        pct_from_open: float,
        change_rate: float,
        tr_amount: int,
        current_price: int,
        high_price: int,
        low_price: int,
    ) -> float:
        """
        스크리닝 점수 계산 (0~100)

        - 시가대비 위치 (40점): sweet spot 1.5~2.5% = 만점
        - 거래대금 (30점): 500억+ = 만점
        - 당일 가격위치 (20점): 고가 근접 = 상승 추세
        - 등락률 적절성 (10점): 1~3% = 만점
        """
        score = 0.0

        # 1. 시가대비 위치 (max 40)
        if 1.5 <= pct_from_open <= 2.5:
            score += 40
        elif 1.0 <= pct_from_open < 1.5:
            score += 30
        elif 2.5 < pct_from_open <= 3.0:
            score += 30
        else:
            score += 20

        # 2. 거래대금 (max 30)
        if tr_amount >= 50_000_000_000:      # 500억+
            score += 30
        elif tr_amount >= 20_000_000_000:    # 200억+
            score += 25
        elif tr_amount >= 10_000_000_000:    # 100억+
            score += 20
        elif tr_amount >= 5_000_000_000:     # 50억+
            score += 15
        else:
            score += 10

        # 3. 당일 가격위치 (max 20) — 고가 근접 = 상승 추세
        if high_price > low_price > 0:
            position = (current_price - low_price) / (high_price - low_price)
            score += position * 20

        # 4. 등락률 적절성 (max 10)
        if 1.0 <= change_rate <= 3.0:
            score += 10
        elif 0.5 <= change_rate < 1.0 or 3.0 < change_rate <= 5.0:
            score += 5

        return round(score, 1)

    # ===== 유틸리티 메서드 =====

    def _extract_stock_code(self, stock: Dict) -> str:
        """종목 코드 추출 (API 필드명 차이 대응)"""
        for key in ('mksc_shrn_iscd', 'stck_shrn_iscd', 'shrn_iscd', 'code'):
            val = str(stock.get(key, '')).strip()
            if val and len(val) == 6 and val.isdigit():
                return val
        return ''

    def _extract_stock_name(self, stock: Dict) -> str:
        """종목명 추출 (API 필드명 차이 대응)"""
        for key in ('hts_kor_isnm', 'kor_isnm', 'name'):
            val = str(stock.get(key, '')).strip()
            if val:
                return val
        return ''

    @staticmethod
    def _safe_int(value) -> int:
        """안전한 int 변환"""
        try:
            return int(str(value).replace(',', '').strip())
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(value) -> float:
        """안전한 float 변환"""
        try:
            return float(str(value).replace(',', '').strip())
        except (ValueError, TypeError):
            return 0.0
