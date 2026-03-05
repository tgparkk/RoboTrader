"""
NXT 프리마켓 인텔리전스 분석 모듈

08:00-09:00 NXT(넥스트레이드) 시장 데이터를 수집하여
본장 개시 전 시장 심리를 파악하고 거래 파라미터를 동적 조정합니다.

주요 기능:
- NXT 대표 종목 현재가 수집 (5분 주기)
- 시장 심리 점수 계산 (-1.0 ~ +1.0)
- 약세장 시 보수적 파라미터 자동 전환
- 텔레그램 모닝 브리핑 데이터 생성
"""
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)

# KOSPI200 / KOSDAQ150 대표 벨웨더 종목
NXT_BELLWETHER_STOCKS = [
    # KOSPI 대형주
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("035720", "카카오"),
    ("006400", "삼성SDI"),
    ("051910", "LG화학"),
    ("003670", "포스코홀딩스"),
    ("005380", "현대차"),
    ("000270", "기아"),
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    ("068270", "셀트리온"),
    ("207940", "삼성바이오로직스"),
    ("373220", "LG에너지솔루션"),
    ("012330", "현대모비스"),
    # KOSPI 중형주
    ("034730", "SK"),
    ("066570", "LG전자"),
    ("003490", "대한항공"),
    ("028260", "삼성물산"),
    ("032830", "삼성생명"),
    # KOSDAQ 대형주
    ("247540", "에코프로비엠"),
    ("086520", "에코프로"),
    ("041510", "에스엠"),
    ("263750", "펄어비스"),
    ("328130", "루닛"),
    ("196170", "알테오젠"),
    ("403870", "HPSP"),
    ("145020", "휴젤"),
    ("377300", "카카오페이"),
    ("036570", "엔씨소프트"),
]


@dataclass
class PreMarketSnapshot:
    """시점별 NXT 프리마켓 스냅샷"""
    timestamp: datetime
    active_stocks: List[Dict] = field(default_factory=list)
    total_nxt_volume: int = 0
    up_count: int = 0
    down_count: int = 0
    unchanged_count: int = 0
    avg_change_pct: float = 0.0


@dataclass
class PreMarketReport:
    """최종 프리마켓 인텔리전스 리포트"""
    report_time: datetime
    market_sentiment: str           # 'bullish', 'bearish', 'neutral'
    sentiment_score: float          # -1.0 ~ +1.0
    gap_direction: str              # 'gap_up', 'gap_down', 'flat'
    expected_gap_pct: float         # 예상 갭 %
    volatility_level: str           # 'low', 'normal', 'high'
    top_movers: List[Dict] = field(default_factory=list)
    recommended_max_positions: int = 5
    recommended_stop_loss_pct: float = 0.04
    recommended_take_profit_pct: float = 0.05
    nxt_available: bool = False
    snapshot_count: int = 0
    log_lines: List[str] = field(default_factory=list)


class PreMarketAnalyzer:
    """NXT 프리마켓 인텔리전스 분석기"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._snapshots: List[PreMarketSnapshot] = []
        self._report: Optional[PreMarketReport] = None
        self._nxt_available: Optional[bool] = None  # None = 미테스트
        self._circuit_breaker_active: bool = False
        self._circuit_breaker_reason: str = ""

        self._nxt_div_code = self.config.get('nxt_div_code', 'NX')
        self._max_stocks = self.config.get('max_bellwether_stocks', 30)
        self._api_interval_ms = self.config.get('api_call_interval_ms', 100)

    def collect_snapshot(self) -> Optional[PreMarketSnapshot]:
        """
        NXT 프리마켓 스냅샷 1회 수집

        Returns:
            PreMarketSnapshot 또는 None (NXT 불가 시)
        """
        try:
            # 첫 호출 시 NXT API 가용성 테스트
            if self._nxt_available is None:
                self._nxt_available = self._test_nxt_api_availability()
                if not self._nxt_available:
                    logger.warning("[프리마켓] NXT API 사용 불가 - 기존 설정으로 운영합니다")
                    return None

            if not self._nxt_available:
                return None

            # 벨웨더 종목 NXT 현재가 수집
            stock_data = self._collect_nxt_stock_prices()

            if not stock_data:
                logger.warning("[프리마켓] NXT 종목 데이터 수집 실패")
                return None

            # 스냅샷 생성
            up_count = sum(1 for s in stock_data if s['change_pct'] > 0)
            down_count = sum(1 for s in stock_data if s['change_pct'] < 0)
            unchanged_count = sum(1 for s in stock_data if s['change_pct'] == 0)
            total_volume = sum(s['volume'] for s in stock_data)
            avg_change = sum(s['change_pct'] for s in stock_data) / len(stock_data) if stock_data else 0.0

            snapshot = PreMarketSnapshot(
                timestamp=now_kst(),
                active_stocks=stock_data,
                total_nxt_volume=total_volume,
                up_count=up_count,
                down_count=down_count,
                unchanged_count=unchanged_count,
                avg_change_pct=round(avg_change, 4),
            )

            self._snapshots.append(snapshot)
            logger.info(
                f"[프리마켓] 스냅샷 #{len(self._snapshots)}: "
                f"상승={up_count}, 하락={down_count}, 보합={unchanged_count}, "
                f"평균등락={avg_change:+.2f}%, NXT거래량={total_volume:,}"
            )
            return snapshot

        except Exception as e:
            logger.error(f"[프리마켓] 스냅샷 수집 오류: {e}")
            return None

    def generate_report(self) -> PreMarketReport:
        """
        수집된 스냅샷들을 기반으로 최종 프리마켓 리포트 생성

        Returns:
            PreMarketReport
        """
        try:
            report_time = now_kst()

            # 서킷브레이커 체크 (전일 지수 기반)
            self._check_circuit_breaker()

            # NXT 데이터가 없는 경우 중립 리포트
            if not self._snapshots or not self._nxt_available:
                report = self._create_neutral_report(report_time)
                # NXT 없어도 서킷브레이커는 적용
                if self._circuit_breaker_active:
                    report.recommended_max_positions = 0
                    report.market_sentiment = 'circuit_breaker'
                    report.nxt_available = True  # 서킷브레이커가 유효한 신호이므로
                    report.log_lines.insert(0, f"서킷브레이커: {self._circuit_breaker_reason}")
                    logger.warning(f"[프리마켓] 서킷브레이커 발동 (NXT 없음): {self._circuit_breaker_reason}")
                self._report = report
                return self._report

            # 심리 점수 계산
            sentiment_score = self._calculate_sentiment_score()
            sentiment = self._score_to_sentiment(sentiment_score)

            # 갭 분석
            gap_pct = self._calculate_expected_gap()
            gap_direction = 'gap_up' if gap_pct > 0.3 else ('gap_down' if gap_pct < -0.3 else 'flat')

            # 변동성 수준
            volatility = self._calculate_volatility_level()

            # 상위 종목
            top_movers = self._get_top_movers()

            # 추천 파라미터 계산
            from config.strategy_settings import StrategySettings
            pm = StrategySettings.PreMarket

            # 서킷브레이커 발동 시 → NXT 갭으로 해제 가능 여부 체크
            if self._circuit_breaker_active:
                if gap_pct >= pm.CIRCUIT_BREAKER_RELEASE_GAP_PCT:
                    # 강한 반등 신호 → 서킷브레이커 해제, 절반 투입
                    self._circuit_breaker_active = False
                    release_reason = (
                        f"NXT 갭 {gap_pct:+.2f}% >= {pm.CIRCUIT_BREAKER_RELEASE_GAP_PCT}%로 "
                        f"서킷브레이커 해제 (절반 투입)"
                    )
                    self._circuit_breaker_reason = release_reason
                    logger.info(f"[서킷브레이커] {release_reason}")
                    rec_max_pos = max(1, pm.FALLBACK_MAX_POSITIONS // 2)
                    rec_stop_loss = pm.BEARISH_STOP_LOSS_RATIO
                    rec_take_profit = pm.BEARISH_TAKE_PROFIT_RATIO
                    sentiment = 'bearish'  # 완전 해제가 아닌 cautious 모드
                else:
                    rec_max_pos = 0
                    rec_stop_loss = pm.BEARISH_STOP_LOSS_RATIO
                    rec_take_profit = pm.BEARISH_TAKE_PROFIT_RATIO
                    sentiment = 'circuit_breaker'
            elif sentiment == 'bearish':
                # 서킷브레이커 미발동이지만 NXT 약세 → 복합 조건 체크
                if self._check_circuit_breaker_with_gap(gap_pct):
                    rec_max_pos = 0
                    rec_stop_loss = pm.BEARISH_STOP_LOSS_RATIO
                    rec_take_profit = pm.BEARISH_TAKE_PROFIT_RATIO
                    sentiment = 'circuit_breaker'
                else:
                    rec_max_pos = pm.BEARISH_MAX_POSITIONS
                    rec_stop_loss = pm.BEARISH_STOP_LOSS_RATIO
                    rec_take_profit = pm.BEARISH_TAKE_PROFIT_RATIO
            else:
                rec_max_pos = pm.FALLBACK_MAX_POSITIONS
                rec_stop_loss = 0.04
                rec_take_profit = 0.05

            # 로그 라인 생성
            log_lines = []
            if self._circuit_breaker_active or sentiment == 'circuit_breaker':
                log_lines.append(f"서킷브레이커: {self._circuit_breaker_reason}")
            log_lines.extend([
                f"시장 심리: {sentiment.upper()} ({sentiment_score:+.2f})",
                f"예상 갭: {gap_direction} ({gap_pct:+.2f}%)",
                f"변동성: {volatility}",
                f"스냅샷 수: {len(self._snapshots)}",
                f"오늘 설정: 최대 {rec_max_pos}종목, 손절 {rec_stop_loss:.1%}, 익절 {rec_take_profit:.1%}",
            ])

            self._report = PreMarketReport(
                report_time=report_time,
                market_sentiment=sentiment,
                sentiment_score=sentiment_score,
                gap_direction=gap_direction,
                expected_gap_pct=gap_pct,
                volatility_level=volatility,
                top_movers=top_movers,
                recommended_max_positions=rec_max_pos,
                recommended_stop_loss_pct=rec_stop_loss,
                recommended_take_profit_pct=rec_take_profit,
                nxt_available=True,
                snapshot_count=len(self._snapshots),
                log_lines=log_lines,
            )

            logger.info(
                f"[프리마켓] 리포트 생성 완료: "
                f"심리={sentiment}({sentiment_score:+.2f}), "
                f"갭={gap_direction}({gap_pct:+.2f}%), "
                f"변동성={volatility}, "
                f"추천포지션={rec_max_pos}"
            )
            return self._report

        except Exception as e:
            logger.error(f"[프리마켓] 리포트 생성 오류: {e}")
            return self._create_neutral_report(now_kst())

    def get_report(self) -> Optional[PreMarketReport]:
        """현재 리포트 반환"""
        return self._report

    def reset_daily_state(self):
        """일일 상태 초기화"""
        self._snapshots.clear()
        self._report = None
        self._nxt_available = None
        self._circuit_breaker_active = False
        self._circuit_breaker_reason = ""
        logger.info("[프리마켓] 일일 상태 초기화 완료")

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _check_circuit_breaker(self):
        """
        전일 지수 등락률 기반 서킷브레이커 체크

        조건1: 전일 KOSPI 또는 KOSDAQ -2% 이상 하락 → 매수 완전 중단
        """
        from config.strategy_settings import StrategySettings
        pm = StrategySettings.PreMarket
        threshold = pm.CIRCUIT_BREAKER_PREV_DAY_PCT

        try:
            prev_day_ret = self._get_prev_day_index_returns()
            if prev_day_ret is None:
                logger.info("[서킷브레이커] 전일 지수 데이터 없음 - 서킷브레이커 미적용")
                return

            kospi_ret = prev_day_ret.get('kospi_ret', 0)
            kosdaq_ret = prev_day_ret.get('kosdaq_ret', 0)
            worst_ret = min(kospi_ret, kosdaq_ret)

            logger.info(
                f"[서킷브레이커] 전일 지수: KOSPI {kospi_ret:+.2f}%, KOSDAQ {kosdaq_ret:+.2f}% "
                f"(임계값: {threshold}%)"
            )

            if worst_ret <= threshold:
                self._circuit_breaker_active = True
                idx_name = "KOSPI" if kospi_ret <= kosdaq_ret else "KOSDAQ"
                self._circuit_breaker_reason = (
                    f"전일 {idx_name} {worst_ret:+.2f}% (임계값 {threshold}%)"
                )
                logger.warning(
                    f"[서킷브레이커] 발동! {self._circuit_breaker_reason} -> 매수 완전 중단"
                )

        except Exception as e:
            logger.error(f"[서킷브레이커] 전일 지수 체크 오류: {e}")

    def _check_circuit_breaker_with_gap(self, nxt_gap_pct: float) -> bool:
        """
        전일 하락 + NXT 갭 복합 서킷브레이커

        조건2: 전일 -1% 이하 + NXT 갭 -0.5% 이하 → 매수 완전 중단
        (5년 검증: 적중률 61.3%, 손익비 2.60)
        """
        from config.strategy_settings import StrategySettings
        pm = StrategySettings.PreMarket

        try:
            prev_day_ret = self._get_prev_day_index_returns()
            if prev_day_ret is None:
                return False

            worst_ret = min(prev_day_ret.get('kospi_ret', 0), prev_day_ret.get('kosdaq_ret', 0))

            if (worst_ret <= pm.CIRCUIT_BREAKER_PREV_DAY_PCT_WITH_GAP and
                    nxt_gap_pct <= pm.CIRCUIT_BREAKER_NXT_GAP_PCT):
                self._circuit_breaker_active = True
                self._circuit_breaker_reason = (
                    f"전일 {worst_ret:+.2f}% + NXT갭 {nxt_gap_pct:+.2f}% "
                    f"(임계값: 전일{pm.CIRCUIT_BREAKER_PREV_DAY_PCT_WITH_GAP}% + 갭{pm.CIRCUIT_BREAKER_NXT_GAP_PCT}%)"
                )
                logger.warning(
                    f"[서킷브레이커] 복합 조건 발동! {self._circuit_breaker_reason} -> 매수 완전 중단"
                )
                return True

        except Exception as e:
            logger.error(f"[서킷브레이커] 복합 조건 체크 오류: {e}")

        return False

    def _get_prev_day_index_returns(self) -> Optional[Dict[str, float]]:
        """
        전일 KOSPI/KOSDAQ 등락률 조회 (daily_candles DB)

        Returns:
            {'kospi_ret': float, 'kosdaq_ret': float} 또는 None
        """
        try:
            import psycopg2
            from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD

            conn = psycopg2.connect(
                host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                user=PG_USER, password=PG_PASSWORD,
            )
            cur = conn.cursor()

            result = {}
            for code, key in [('KS11', 'kospi_ret'), ('KQ11', 'kosdaq_ret')]:
                cur.execute('''
                    SELECT stck_bsop_date,
                           CAST(stck_oprc AS FLOAT),
                           CAST(stck_clpr AS FLOAT)
                    FROM daily_candles
                    WHERE stock_code = %s
                    ORDER BY stck_bsop_date DESC
                    LIMIT 2
                ''', (code,))
                rows = cur.fetchall()
                if len(rows) >= 2:
                    # rows[0] = 가장 최근 (전일), rows[1] = 전전일
                    prev_close = rows[0][2]  # 전일 종가
                    prev2_close = rows[1][2]  # 전전일 종가
                    if prev2_close > 0:
                        result[key] = (prev_close / prev2_close - 1) * 100
                    else:
                        result[key] = 0.0
                else:
                    result[key] = 0.0

            conn.close()

            if not result:
                return None
            return result

        except Exception as e:
            logger.error(f"[서킷브레이커] DB 조회 오류: {e}")
            return None

    def _test_nxt_api_availability(self) -> bool:
        """NXT API 가용성 테스트 (삼성전자로 시도)"""
        try:
            from api.kis_market_api import get_inquire_price

            logger.info("[프리마켓] NXT API 가용성 테스트 시작 (005930 삼성전자)")
            result = get_inquire_price(div_code=self._nxt_div_code, itm_no="005930")

            if result is not None and not result.empty:
                price = result.iloc[0].get('stck_prpr', '0')
                if price and str(price) != '0':
                    logger.info(f"[프리마켓] NXT API 사용 가능 (삼성전자 NXT가: {price})")
                    return True

            logger.warning("[프리마켓] NXT API 응답 없음 또는 데이터 없음")
            return False

        except Exception as e:
            logger.warning(f"[프리마켓] NXT API 테스트 실패: {e}")
            return False

    def _collect_nxt_stock_prices(self) -> List[Dict]:
        """벨웨더 종목들의 NXT 현재가 수집"""
        from api.kis_market_api import get_inquire_price

        stock_data = []
        stocks_to_check = NXT_BELLWETHER_STOCKS[:self._max_stocks]

        for stock_code, stock_name in stocks_to_check:
            try:
                result = get_inquire_price(div_code=self._nxt_div_code, itm_no=stock_code)

                if result is not None and not result.empty:
                    row = result.iloc[0]
                    current_price = self._safe_int(row.get('stck_prpr', '0'))
                    prev_close = self._safe_int(row.get('stck_sdpr', '0'))
                    volume = self._safe_int(row.get('acml_vol', '0'))

                    if current_price > 0 and prev_close > 0:
                        change_pct = (current_price - prev_close) / prev_close * 100
                        stock_data.append({
                            'code': stock_code,
                            'name': stock_name,
                            'price': current_price,
                            'prev_close': prev_close,
                            'change_pct': round(change_pct, 2),
                            'volume': volume,
                        })

                # API 호출 간격 준수
                time_module.sleep(self._api_interval_ms / 1000.0)

            except Exception as e:
                logger.debug(f"[프리마켓] {stock_code}({stock_name}) NXT 조회 실패: {e}")
                continue

        logger.debug(f"[프리마켓] NXT 종목 데이터 수집: {len(stock_data)}/{len(stocks_to_check)}건")
        return stock_data

    def _calculate_sentiment_score(self) -> float:
        """
        심리 점수 계산 (-1.0 ~ +1.0)

        가중치:
        - 방향 점수 (40%): 평균 등락률 정규화
        - 폭 점수 (30%): 상승 종목 비율
        - 추세 점수 (30%): 후반 스냅샷 vs 전반 스냅샷
        - 08:30 이후 스냅샷 가중치 2배
        """
        if not self._snapshots:
            return 0.0

        # 시간 가중치 적용 스냅샷
        weighted_changes = []
        weighted_breadths = []
        weights = []

        for snap in self._snapshots:
            # 08:30 이후 가중치 2배
            weight = 2.0 if snap.timestamp.hour == 8 and snap.timestamp.minute >= 30 else 1.0
            weights.append(weight)
            weighted_changes.append(snap.avg_change_pct * weight)

            total = snap.up_count + snap.down_count + snap.unchanged_count
            if total > 0:
                breadth = (snap.up_count - snap.down_count) / total
                weighted_breadths.append(breadth * weight)

        total_weight = sum(weights) if weights else 1.0

        # 1) 방향 점수 (40%): 가중 평균 등락률 → [-1, 1] 정규화
        avg_change = sum(weighted_changes) / total_weight
        direction_score = max(-1.0, min(1.0, avg_change / 1.0))  # ±1%를 ±1.0으로

        # 2) 폭 점수 (30%): 가중 평균 상승비율
        avg_breadth = sum(weighted_breadths) / total_weight if weighted_breadths else 0.0
        breadth_score = max(-1.0, min(1.0, avg_breadth))

        # 3) 추세 점수 (30%): 후반 vs 전반 비교
        trend_score = 0.0
        if len(self._snapshots) >= 2:
            mid = len(self._snapshots) // 2
            first_half_avg = sum(s.avg_change_pct for s in self._snapshots[:mid]) / mid
            second_half_avg = sum(s.avg_change_pct for s in self._snapshots[mid:]) / (len(self._snapshots) - mid)
            diff = second_half_avg - first_half_avg
            trend_score = max(-1.0, min(1.0, diff / 0.5))  # ±0.5% 차이를 ±1.0으로

        # 가중 합산
        score = direction_score * 0.4 + breadth_score * 0.3 + trend_score * 0.3

        logger.debug(
            f"[프리마켓] 심리 점수: 방향={direction_score:.2f}(40%), "
            f"폭={breadth_score:.2f}(30%), 추세={trend_score:.2f}(30%) → {score:.2f}"
        )
        return round(max(-1.0, min(1.0, score)), 2)

    def _score_to_sentiment(self, score: float) -> str:
        """점수를 심리 문자열로 변환"""
        from config.strategy_settings import StrategySettings
        pm = StrategySettings.PreMarket

        if score <= pm.BEARISH_THRESHOLD:
            return 'bearish'
        elif score >= pm.BULLISH_THRESHOLD:
            return 'bullish'
        else:
            return 'neutral'

    def _calculate_expected_gap(self) -> float:
        """최근 스냅샷 기반 예상 갭 (%)"""
        if not self._snapshots:
            return 0.0

        # 가장 최근 스냅샷의 평균 등락률을 갭 추정치로 사용
        recent = self._snapshots[-1]
        return round(recent.avg_change_pct, 2)

    def _calculate_volatility_level(self) -> str:
        """스냅샷 간 변동성 수준 판단"""
        if len(self._snapshots) < 2:
            return 'normal'

        changes = [s.avg_change_pct for s in self._snapshots]
        avg = sum(changes) / len(changes)
        variance = sum((c - avg) ** 2 for c in changes) / len(changes)
        std_dev = variance ** 0.5

        if std_dev > 0.5:
            return 'high'
        elif std_dev < 0.1:
            return 'low'
        else:
            return 'normal'

    def _get_top_movers(self) -> List[Dict]:
        """NXT 상위 종목 추출 (최근 스냅샷 기준, 변동률 절대값 상위 5개)"""
        if not self._snapshots:
            return []

        recent = self._snapshots[-1]
        sorted_stocks = sorted(
            recent.active_stocks,
            key=lambda s: abs(s['change_pct']),
            reverse=True
        )
        return sorted_stocks[:5]

    def _create_neutral_report(self, report_time: datetime) -> PreMarketReport:
        """중립 기본 리포트 생성"""
        from config.strategy_settings import StrategySettings
        pm = StrategySettings.PreMarket

        return PreMarketReport(
            report_time=report_time,
            market_sentiment='neutral',
            sentiment_score=0.0,
            gap_direction='flat',
            expected_gap_pct=0.0,
            volatility_level='normal',
            recommended_max_positions=pm.FALLBACK_MAX_POSITIONS,
            recommended_stop_loss_pct=0.04,
            recommended_take_profit_pct=0.05,
            nxt_available=False,
            snapshot_count=0,
            log_lines=["NXT 데이터 없음 - 기본 설정 사용"],
        )

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        """안전한 정수 변환"""
        if value is None or value == '':
            return default
        try:
            return int(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return default
