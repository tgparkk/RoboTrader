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

from core.pre_market_bellwether import NXT_BELLWETHER_STOCKS
from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)


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
    market_sentiment: str           # 'bullish', 'bearish', 'very_bearish', 'extreme_bearish', 'neutral', 'circuit_breaker', 'gap_up_filter'
    sentiment_score: float          # -1.0 ~ +1.0
    gap_direction: str              # 'gap_up', 'gap_down', 'flat'
    expected_gap_pct: float         # 예상 갭 %
    volatility_level: str           # 'low', 'normal', 'high'
    top_movers: List[Dict] = field(default_factory=list)
    recommended_max_positions: int = 3
    recommended_stop_loss_pct: float = 0.05
    recommended_take_profit_pct: float = 0.06
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
        self._prev_day_decline_active: bool = False

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

            # DB에 스냅샷 저장
            self._save_snapshot_to_db(snapshot, len(self._snapshots))

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

            from config.strategy_settings import StrategySettings
            pm = StrategySettings.PreMarket

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
                elif self._prev_day_decline_active:
                    # 전일 하락 감지 (로깅 전용 — SL/TP는 5%/6% 유지)
                    report.log_lines.insert(0, "전일 하락 감지 -> SL/TP 정상 유지 (03-24 멀티버스: 축소 역효과)")
                    logger.info("[프리마켓] 전일 하락 감지 (NXT 없음) — SL/TP 정상 유지")
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

            # SL/TP는 항상 5%/6% (03-24 멀티버스: 축소는 모든 시나리오에서 역효과)
            # 장중 동적 SL(지수 -0.7%→3%)만 check_intraday_index()에서 별도 적용
            rec_stop_loss = 0.05
            rec_take_profit = 0.06

            # 포지션 수만 sentiment별 조정
            if self._circuit_breaker_active:
                if gap_pct >= pm.CIRCUIT_BREAKER_RELEASE_GAP_PCT:
                    # 강한 반등 신호 → 서킷브레이커 해제, 정상 모드 복귀
                    self._circuit_breaker_active = False
                    self._prev_day_decline_active = False
                    release_reason = (
                        f"NXT 갭 {gap_pct:+.2f}% >= {pm.CIRCUIT_BREAKER_RELEASE_GAP_PCT}%로 "
                        f"서킷브레이커 해제 (정상 복귀)"
                    )
                    self._circuit_breaker_reason = release_reason
                    logger.info(f"[서킷브레이커] {release_reason}")
                    rec_max_pos = pm.FALLBACK_MAX_POSITIONS
                    sentiment = 'neutral'
                else:
                    rec_max_pos = 0
                    sentiment = 'circuit_breaker'
            elif sentiment == 'extreme_bearish':
                rec_max_pos = pm.EXTREME_BEARISH_MAX_POSITIONS
                logger.warning(
                    f"[프리마켓] 극약세 감지 (sentiment={sentiment_score:+.2f}) -> 매수 완전 중단"
                )
            elif sentiment == 'very_bearish':
                rec_max_pos = pm.VERY_BEARISH_MAX_POSITIONS
                logger.warning(
                    f"[프리마켓] 강약세 감지 (sentiment={sentiment_score:+.2f}) -> 포지션 축소(최대 {rec_max_pos}종목)"
                )
            elif sentiment == 'bearish':
                if self._check_circuit_breaker_with_gap(gap_pct):
                    rec_max_pos = 0
                    sentiment = 'circuit_breaker'
                else:
                    rec_max_pos = pm.BEARISH_MAX_POSITIONS
            else:
                rec_max_pos = pm.FALLBACK_MAX_POSITIONS

            # 로그 라인 생성
            log_lines = []
            if self._circuit_breaker_active or sentiment == 'circuit_breaker':
                log_lines.append(f"서킷브레이커: {self._circuit_breaker_reason}")
            if sentiment == 'extreme_bearish':
                log_lines.append(f"극약세: NXT sentiment {sentiment_score:+.2f} <= {pm.EXTREME_BEARISH_THRESHOLD} -> 매수 중단")
            if sentiment == 'very_bearish':
                log_lines.append(f"강약세: NXT sentiment {sentiment_score:+.2f} <= {pm.VERY_BEARISH_THRESHOLD} -> {rec_max_pos}종목 축소, SL/TP 고정")
            if self._prev_day_decline_active and sentiment not in ('circuit_breaker', 'extreme_bearish', 'very_bearish', 'bearish'):
                log_lines.append("전일 하락 감지 -> SL/TP 정상 유지")
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

            # DB에 리포트 요약 저장
            self._save_report_summary_to_db(self._report)

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
        self._prev_day_decline_active = False
        logger.info("[프리마켓] 일일 상태 초기화 완료")

    # =========================================================================
    # 장 시작 후 지수 갭 체크
    # =========================================================================

    def check_market_open_gap(self) -> Optional[PreMarketReport]:
        """
        장 시작 후 실제 KOSPI/KOSDAQ 지수 시가 갭을 확인하여
        기존 리포트를 업데이트하거나 새로운 서킷브레이커를 발동합니다.

        Returns:
            업데이트된 PreMarketReport 또는 None (체크 불필요/실패 시)
        """
        from config.strategy_settings import StrategySettings
        pm = StrategySettings.PreMarket

        if not pm.MARKET_OPEN_GAP_CHECK_ENABLED:
            return None

        try:
            # KIS API로 실시간 KOSPI/KOSDAQ 지수 조회
            gap_info = self._get_market_open_gap()
            if gap_info is None:
                logger.warning("[장시작갭] 지수 시가 갭 조회 실패")
                return None

            kospi_gap = gap_info.get('kospi_gap', 0)
            kosdaq_gap = gap_info.get('kosdaq_gap', 0)
            worst_gap = min(kospi_gap, kosdaq_gap)

            logger.info(
                f"[장시작갭] KOSPI 갭: {kospi_gap:+.2f}%, KOSDAQ 갭: {kosdaq_gap:+.2f}% "
                f"(임계값: {pm.MARKET_OPEN_GAP_THRESHOLD_PCT}%)"
            )

            # 갭업 필터: KOSPI 시가갭 >= +1.0% → 매수 중단 (데드캣바운스 회피)
            if (getattr(pm, 'MARKET_OPEN_GAP_UP_FILTER_ENABLED', False)
                    and kospi_gap >= pm.MARKET_OPEN_GAP_UP_THRESHOLD_PCT):
                reason = (
                    f"장시작 KOSPI 갭업 {kospi_gap:+.2f}% "
                    f"(임계값 +{pm.MARKET_OPEN_GAP_UP_THRESHOLD_PCT}%)"
                )
                logger.warning(f"[장시작갭업] 매수 중단! {reason}")

                if self._report:
                    self._report.recommended_max_positions = 0
                    self._report.market_sentiment = 'gap_up_filter'
                    self._report.nxt_available = True
                    self._report.log_lines.insert(0, f"갭업필터: {reason}")
                else:
                    self._report = PreMarketReport(
                        report_time=now_kst(),
                        market_sentiment='gap_up_filter',
                        sentiment_score=0.0,
                        gap_direction='gap_up',
                        expected_gap_pct=kospi_gap,
                        volatility_level='normal',
                        recommended_max_positions=0,
                        recommended_stop_loss_pct=0.05,
                        recommended_take_profit_pct=0.06,
                        nxt_available=True,
                        snapshot_count=0,
                        log_lines=[f"갭업필터: {reason}"],
                    )

                return self._report

            # 임계값 이하이면 서킷브레이커 발동 (갭다운)
            if worst_gap <= pm.MARKET_OPEN_GAP_THRESHOLD_PCT:
                idx_name = "KOSPI" if kospi_gap <= kosdaq_gap else "KOSDAQ"
                reason = (
                    f"장시작 {idx_name} 갭 {worst_gap:+.2f}% "
                    f"(임계값 {pm.MARKET_OPEN_GAP_THRESHOLD_PCT}%)"
                )
                logger.warning(f"[장시작갭] 서킷브레이커 발동! {reason}")

                # 기존 리포트가 있으면 업데이트, 없으면 새로 생성
                if self._report:
                    self._report.recommended_max_positions = 0
                    self._report.market_sentiment = 'circuit_breaker'
                    self._report.nxt_available = True
                    self._report.log_lines.insert(0, f"장시작갭 서킷브레이커: {reason}")
                    logger.info("[장시작갭] 기존 리포트 업데이트 완료")
                else:
                    self._report = PreMarketReport(
                        report_time=now_kst(),
                        market_sentiment='circuit_breaker',
                        sentiment_score=-1.0,
                        gap_direction='gap_down',
                        expected_gap_pct=worst_gap,
                        volatility_level='high',
                        recommended_max_positions=0,
                        recommended_stop_loss_pct=0.05,
                        recommended_take_profit_pct=0.06,
                        nxt_available=True,
                        snapshot_count=0,
                        log_lines=[f"장시작갭 서킷브레이커: {reason}"],
                    )
                    logger.info("[장시작갭] 새 리포트 생성 완료")

                return self._report
            else:
                logger.info(f"[장시작갭] 정상 범위 — 기존 판단 유지")
                return None

        except Exception as e:
            logger.error(f"[장시작갭] 체크 오류: {e}")
            return None

    def _get_market_open_gap(self) -> Optional[Dict[str, float]]:
        """
        KIS API로 KOSPI/KOSDAQ 시가 갭(%) 조회

        Returns:
            {'kospi_gap': float, 'kosdaq_gap': float} 또는 None
        """
        try:
            from api.kis_market_api import get_index_data

            result = {}
            for index_code, key in [('0001', 'kospi_gap'), ('1001', 'kosdaq_gap')]:
                data = get_index_data(index_code)
                if data:
                    # bstp_nmix_prpr: 현재지수, bstp_nmix_prdy_ctrt: 전일대비율(%)
                    gap_pct = float(data.get('bstp_nmix_prdy_ctrt', '0'))
                    result[key] = gap_pct
                else:
                    logger.warning(f"[장시작갭] {index_code} 지수 조회 실패")
                    return None

                time_module.sleep(0.1)  # API 호출 간격

            return result

        except Exception as e:
            logger.error(f"[장시작갭] 지수 API 조회 오류: {e}")
            return None

    # =========================================================================
    # 장중 지수 모니터링
    # =========================================================================

    def check_intraday_index(self) -> Optional[PreMarketReport]:
        """
        장중 KOSPI/KOSDAQ 지수를 확인하여 급락 시 서킷브레이커 발동,
        회복 시 매수 재개합니다.

        Returns:
            업데이트된 PreMarketReport 또는 None (변경 없음)
        """
        from config.strategy_settings import StrategySettings
        pm = StrategySettings.PreMarket

        if not pm.INTRADAY_INDEX_CHECK_ENABLED:
            return None

        try:
            gap_info = self._get_market_open_gap()
            if gap_info is None:
                logger.warning("[장중지수] 지수 조회 실패")
                return None

            kospi_gap = gap_info.get('kospi_gap', 0)
            kosdaq_gap = gap_info.get('kosdaq_gap', 0)
            worst_gap = min(kospi_gap, kosdaq_gap)

            current_sentiment = self._report.market_sentiment if self._report else 'neutral'
            is_currently_blocked = current_sentiment in ('circuit_breaker', 'gap_up_filter')

            logger.info(
                f"[장중지수] KOSPI: {kospi_gap:+.2f}%, KOSDAQ: {kosdaq_gap:+.2f}% "
                f"(현재: {current_sentiment})"
            )

            # Case 1: 급락 감지 → 서킷브레이커 발동
            if not is_currently_blocked and worst_gap <= pm.INTRADAY_INDEX_DROP_THRESHOLD_PCT:
                idx_name = "KOSPI" if kospi_gap <= kosdaq_gap else "KOSDAQ"
                reason = (
                    f"장중 {idx_name} {worst_gap:+.2f}% "
                    f"(임계값 {pm.INTRADAY_INDEX_DROP_THRESHOLD_PCT}%)"
                )
                logger.warning(f"[장중지수] 서킷브레이커 발동! {reason}")

                if self._report:
                    self._report.recommended_max_positions = 0
                    self._report.market_sentiment = 'circuit_breaker'
                    self._report.nxt_available = True
                    self._report.log_lines.insert(0, f"장중지수 서킷브레이커: {reason}")
                else:
                    self._report = PreMarketReport(
                        report_time=now_kst(),
                        market_sentiment='circuit_breaker',
                        sentiment_score=-1.0,
                        gap_direction='gap_down',
                        expected_gap_pct=worst_gap,
                        volatility_level='high',
                        recommended_max_positions=0,
                        recommended_stop_loss_pct=0.05,
                        recommended_take_profit_pct=0.06,
                        nxt_available=True,
                        snapshot_count=0,
                        log_lines=[f"장중지수 서킷브레이커: {reason}"],
                    )
                return self._report

            # Case 2: 장중 서킷브레이커 상태에서 회복 감지 → bearish 모드로 매수 재개
            if is_currently_blocked and worst_gap >= pm.INTRADAY_INDEX_RECOVERY_PCT:
                reason = (
                    f"장중 지수 회복 {worst_gap:+.2f}% "
                    f"(회복 임계값 {pm.INTRADAY_INDEX_RECOVERY_PCT}%)"
                )
                logger.info(f"[장중지수] 서킷브레이커 해제 (bearish 모드): {reason}")

                if self._report:
                    self._report.recommended_max_positions = min(2, pm.BEARISH_MAX_POSITIONS)
                    self._report.market_sentiment = 'bearish'
                    self._report.recommended_stop_loss_pct = 0.05
                    self._report.recommended_take_profit_pct = 0.06
                    self._report.log_lines.insert(0, f"장중지수 회복: {reason}")
                return self._report

            # 🌙 오버나이트 전략: 장중 동적 SL 변동 무효 (Case 3/4 스킵)
            # — closing_trade는 오버나이트 홀드 약속. SL 축소가 장중 청산 유발하면 안 됨.
            try:
                from config.strategy_settings import is_overnight_strategy as _is_overnight
                _overnight_mode = _is_overnight()
            except Exception:
                _overnight_mode = False

            # Case 3: 동적 SL — 지수 -0.7% 이하 시 SL 축소 (서킷브레이커 미만)
            if (not _overnight_mode and
                    not is_currently_blocked and
                    getattr(pm, 'INTRADAY_DYNAMIC_SL_ENABLED', False) and
                    worst_gap <= getattr(pm, 'INTRADAY_SL_TIGHTEN_THRESHOLD_PCT', -0.7) and
                    worst_gap > pm.INTRADAY_INDEX_DROP_THRESHOLD_PCT):
                tightened_sl = getattr(pm, 'INTRADAY_TIGHTENED_STOP_LOSS_RATIO', 0.03)
                reason = (
                    f"장중 지수 하락 {worst_gap:+.2f}% "
                    f"(임계값 {pm.INTRADAY_SL_TIGHTEN_THRESHOLD_PCT}%) → SL {tightened_sl:.0%}로 축소"
                )
                logger.info(f"[장중지수] 동적 SL 축소: {reason}")

                if self._report:
                    self._report.recommended_stop_loss_pct = tightened_sl
                    self._report.log_lines.insert(0, f"동적SL: {reason}")
                else:
                    self._report = PreMarketReport(
                        report_time=now_kst(),
                        market_sentiment='bearish',
                        sentiment_score=-0.5,
                        gap_direction='gap_down',
                        expected_gap_pct=worst_gap,
                        volatility_level='high',
                        recommended_max_positions=pm.FALLBACK_MAX_POSITIONS,
                        recommended_stop_loss_pct=tightened_sl,
                        recommended_take_profit_pct=0.06,
                        nxt_available=True,
                        snapshot_count=0,
                        log_lines=[f"동적SL: {reason}"],
                    )
                return self._report

            # Case 4: 동적 SL 회복 — 지수가 -0.3% 이상으로 회복 시 SL 원복
            if (not _overnight_mode and
                    not is_currently_blocked and
                    getattr(pm, 'INTRADAY_DYNAMIC_SL_ENABLED', False) and
                    self._report and
                    self._report.recommended_stop_loss_pct < 0.05 and
                    worst_gap >= getattr(pm, 'INTRADAY_SL_RECOVERY_PCT', -0.3)):
                reason = (
                    f"장중 지수 회복 {worst_gap:+.2f}% "
                    f"(회복 임계값 {pm.INTRADAY_SL_RECOVERY_PCT}%) → SL 5% 원복"
                )
                logger.info(f"[장중지수] 동적 SL 원복: {reason}")
                self._report.recommended_stop_loss_pct = 0.05
                self._report.log_lines.insert(0, f"동적SL 원복: {reason}")
                return self._report

            return None

        except Exception as e:
            logger.error(f"[장중지수] 체크 오류: {e}")
            return None

    # =========================================================================
    # DB 저장 메서드
    # =========================================================================

    def _save_snapshot_to_db(self, snapshot: PreMarketSnapshot, seq: int):
        """스냅샷을 DB에 저장"""
        try:
            from db.database_manager import DatabaseManager
            db = DatabaseManager()
            trade_date = snapshot.timestamp.strftime('%Y%m%d')
            db.save_nxt_snapshot(
                trade_date=trade_date,
                snapshot_seq=seq,
                snapshot_time=snapshot.timestamp,
                avg_change_pct=snapshot.avg_change_pct,
                up_count=snapshot.up_count,
                down_count=snapshot.down_count,
                unchanged_count=snapshot.unchanged_count,
                total_volume=snapshot.total_nxt_volume,
            )
        except Exception as e:
            logger.warning(f"[프리마켓] 스냅샷 DB 저장 실패 (무시): {e}")

    def _save_report_summary_to_db(self, report: PreMarketReport):
        """리포트 요약을 DB에 저장 (마지막 스냅샷에 업데이트)"""
        try:
            from db.database_manager import DatabaseManager
            db = DatabaseManager()
            trade_date = report.report_time.strftime('%Y%m%d')
            is_cb = report.market_sentiment == 'circuit_breaker'
            cb_reason = ''
            if is_cb and report.log_lines:
                for line in report.log_lines:
                    if '서킷브레이커' in line:
                        cb_reason = line
                        break
            db.save_nxt_report_summary(
                trade_date=trade_date,
                sentiment_score=report.sentiment_score,
                market_sentiment=report.market_sentiment,
                expected_gap_pct=report.expected_gap_pct,
                circuit_breaker=is_cb,
                circuit_breaker_reason=cb_reason,
                recommended_max_positions=report.recommended_max_positions,
            )
            logger.info(f"[프리마켓] 리포트 요약 DB 저장 완료 (date={trade_date})")
        except Exception as e:
            logger.warning(f"[프리마켓] 리포트 요약 DB 저장 실패 (무시): {e}")

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _check_circuit_breaker(self):
        """
        전일 지수 등락률 기반 서킷브레이커 체크

        조건1: 전일 KOSPI 또는 KOSDAQ -3% 이상 하락 → 매수 완전 중단
        조건1b: 전일 -1% 이하 → 로깅 전용 (SL/TP는 5%/6% 유지, 03-24 멀티버스 결과)
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
                f"(서킷브레이커 임계값: {threshold}%, 손절축소 임계값: {pm.PREV_DAY_DECLINE_THRESHOLD}%)"
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
            elif worst_ret <= pm.PREV_DAY_DECLINE_THRESHOLD:
                # 서킷브레이커는 아니지만 전일 하락 감지 (로깅 전용)
                self._prev_day_decline_active = True
                idx_name = "KOSPI" if kospi_ret <= kosdaq_ret else "KOSDAQ"
                logger.info(
                    f"[서킷브레이커] 전일 {idx_name} {worst_ret:+.2f}% "
                    f"(임계값 {pm.PREV_DAY_DECLINE_THRESHOLD}%) -> 전일 하락 감지 (SL/TP 정상 유지)"
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

        if score <= pm.EXTREME_BEARISH_THRESHOLD:
            return 'extreme_bearish'
        elif score <= pm.VERY_BEARISH_THRESHOLD:
            return 'very_bearish'
        elif score <= pm.BEARISH_THRESHOLD:
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
            recommended_stop_loss_pct=0.05,
            recommended_take_profit_pct=0.06,
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
