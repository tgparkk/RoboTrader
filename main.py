"""
주식 단타 거래 시스템 메인 실행 파일
"""
import asyncio
import signal
import sys
import os
from datetime import datetime
from pathlib import Path
import pandas as pd

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from core.models import TradingConfig, StockState
from core.data_collector import RealTimeDataCollector
from core.order_manager import OrderManager
from core.telegram_integration import TelegramIntegration
from core.candidate_selector import CandidateSelector, CandidateStock
from core.stock_screener import StockScreener
from core.pre_market_analyzer import PreMarketAnalyzer
from core.intraday_stock_manager import IntradayStockManager
from core.trading_stock_manager import TradingStockManager
from core.trading_decision_engine import TradingDecisionEngine
from core.fund_manager import FundManager
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from config.settings import load_trading_config
from utils.logger import setup_logger
from utils.korean_time import now_kst, get_market_status, is_market_open, KST
from config.market_hours import MarketHours
from post_market_chart_generator import PostMarketChartGenerator


_global_decision_engine = None

def get_decision_engine():
    """전역 decision_engine 접근 (순환참조 방지)"""
    return _global_decision_engine


class DayTradingBot:
    """주식 단타 거래 봇"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.is_running = False
        self.pid_file = Path("bot.pid")
        self._last_eod_liquidation_date = None  # 장마감 일괄청산 실행 일자
        self._last_paper_morning_exit_date = None  # macd_cross paper morning exit 실행 일자 (Fix B)
        
        # 프로세스 중복 실행 방지
        self._check_duplicate_process()
        
        # 설정 초기화
        self.config = self._load_config()
        
        # 핵심 모듈 초기화
        self.api_manager = KISAPIManager()
        self.telegram = TelegramIntegration(trading_bot=self)
        self.data_collector = RealTimeDataCollector(self.config, self.api_manager)
        self.order_manager = OrderManager(self.config, self.api_manager, self.telegram)
        self.candidate_selector = CandidateSelector(self.config, self.api_manager)
        self.intraday_manager = IntradayStockManager(self.api_manager)  # 🆕 장중 종목 관리자
        # macd_cross universe (top_n=30) 등록 가능하도록 cap 확장
        try:
            from config.strategy_settings import StrategySettings as _SS_IM
            if _SS_IM.ACTIVE_STRATEGY == 'macd_cross':
                self.intraday_manager.max_stocks = max(
                    self.intraday_manager.max_stocks,
                    _SS_IM.MacdCross.UNIVERSE_TOP_N,
                )
        except Exception:
            pass
        self.trading_manager = TradingStockManager(
            self.intraday_manager, self.data_collector, self.order_manager, self.telegram
        )  # 🆕 거래 상태 통합 관리자
        self.db_manager = DatabaseManager()
        self.decision_engine = TradingDecisionEngine(
            db_manager=self.db_manager,
            telegram_integration=self.telegram,
            trading_manager=self.trading_manager,
            api_manager=self.api_manager,
            intraday_manager=self.intraday_manager
        )  # 🆕 매매 판단 엔진
        global _global_decision_engine
        _global_decision_engine = self.decision_engine

        # 🔧 일별 시가 캐시 초기화 (TradingDecisionEngine class-level cache)
        TradingDecisionEngine.reset_daily_trades()
        self.logger.info("🔄 일별 시가 캐시 초기화 완료")

        # 🔧 emergency_sync 서킷 브레이커 (같은 종목 반복 복구 방지, 버그 수정 2026-02-24)
        self._sync_restore_count: dict = {}  # {stock_code: count}


        # 실시간 종목 스크리너
        self.stock_screener = StockScreener(config=self._build_screener_config())

        # NXT 프리마켓 분석기
        self.pre_market_analyzer = PreMarketAnalyzer(config=self._build_pre_market_config())

        # 🆕 TradingStockManager에 decision_engine 연결 (쿨다운 설정용)
        self.trading_manager.set_decision_engine(self.decision_engine)

        # 자금 관리자 — macd_cross 운영: BUY_BUDGET_RATIO 소스 = MacdCross.BUY_BUDGET_RATIO
        try:
            from config.strategy_settings import StrategySettings as _SS_FM
            if _SS_FM.ACTIVE_STRATEGY == 'macd_cross':
                _fm_ratio = _SS_FM.MacdCross.BUY_BUDGET_RATIO
            else:
                _fm_ratio = self.config.order_management.buy_budget_ratio
        except Exception:
            _fm_ratio = self.config.order_management.buy_budget_ratio
        self.fund_manager = FundManager(buy_budget_ratio=_fm_ratio)
        self.chart_generator = None  # 🆕 장 마감 후 차트 생성기 (지연 초기화)
        
        
        # 신호 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _build_screener_config(self) -> dict:
        """스크리너 설정 구성"""
        from config.strategy_settings import StrategySettings
        sc = StrategySettings.Screener
        return {
            'min_change_rate': sc.MIN_CHANGE_RATE,
            'max_change_rate': sc.MAX_CHANGE_RATE,
            'min_price': sc.MIN_PRICE,
            'max_price': sc.MAX_PRICE,
            'min_trading_amount': sc.MIN_TRADING_AMOUNT,
            'min_pct_from_open': sc.MIN_PCT_FROM_OPEN,
            'max_pct_from_open': sc.MAX_PCT_FROM_OPEN,
            'max_gap_pct': sc.MAX_GAP_PCT,
            'min_gap_down_pct': sc.MIN_GAP_DOWN_PCT,
            'max_phase3_checks': sc.MAX_PHASE3_CHECKS,
            'max_candidates_per_scan': sc.MAX_CANDIDATES_PER_SCAN,
            'max_total_candidates': sc.MAX_TOTAL_CANDIDATES,
            'min_score': sc.MIN_SCORE,
        }

    def _build_pre_market_config(self) -> dict:
        """프리마켓 분석기 설정 구성"""
        from config.strategy_settings import StrategySettings
        pm = StrategySettings.PreMarket
        return {
            'enabled': pm.ENABLED,
            'snapshot_interval': pm.SNAPSHOT_INTERVAL_SECONDS,
            'max_bellwether_stocks': pm.MAX_BELLWETHER_STOCKS,
            'nxt_div_code': pm.NXT_DIV_CODE,
            'api_call_interval_ms': pm.API_CALL_INTERVAL_MS,
        }

    def _is_screening_time(self, current_time: datetime) -> bool:
        """스크리너 실행 가능 시간 확인"""
        from config.strategy_settings import StrategySettings
        sc = StrategySettings.Screener
        t = current_time.hour * 60 + current_time.minute
        start = sc.SCAN_START_HOUR * 60 + sc.SCAN_START_MINUTE
        end = sc.SCAN_END_HOUR * 60 + sc.SCAN_END_MINUTE
        return start <= t <= end

    def _round_to_tick(self, price: float) -> float:
        """KRX 정확한 호가단위에 맞게 반올림 - kis_order_api 함수 사용"""
        try:
            from api.kis_order_api import _round_to_krx_tick
            
            if price <= 0:
                return 0.0
            
            original_price = price
            rounded_price = _round_to_krx_tick(price)
            
            # 로깅으로 가격 조정 확인
            if abs(rounded_price - original_price) > 0:
                self.logger.debug(f"💰 호가단위 조정: {original_price:,.0f}원 → {rounded_price:,.0f}원")
            
            return float(rounded_price)
            
        except Exception as e:
            self.logger.error(f"❌ 호가단위 조정 오류: {e}")
            return float(int(price))


    
    def _check_duplicate_process(self):
        """프로세스 중복 실행 방지"""
        try:
            if self.pid_file.exists():
                # 기존 PID 파일 읽기
                existing_pid = int(self.pid_file.read_text().strip())
                
                # Windows에서 프로세스 존재 여부 확인
                try:
                    import psutil
                    if psutil.pid_exists(existing_pid):
                        process = psutil.Process(existing_pid)
                        if 'python' in process.name().lower() and 'main.py' in ' '.join(process.cmdline()):
                            self.logger.error(f"이미 봇이 실행 중입니다 (PID: {existing_pid})")
                            print(f"오류: 이미 거래 봇이 실행 중입니다 (PID: {existing_pid})")
                            print("기존 프로세스를 먼저 종료해주세요.")
                            sys.exit(1)
                except ImportError:
                    # psutil이 없는 경우 간단한 체크
                    self.logger.warning("psutil 모듈이 없어 정확한 중복 실행 체크를 할 수 없습니다")
                except Exception:
                    # 기존 PID가 존재하지 않으면 PID 파일 삭제
                    self.pid_file.unlink(missing_ok=True)
            
            # 현재 프로세스 PID 저장
            current_pid = os.getpid()
            self.pid_file.write_text(str(current_pid))
            self.logger.info(f"프로세스 PID 등록: {current_pid}")
            
        except Exception as e:
            self.logger.warning(f"중복 실행 체크 중 오류: {e}")
    
    def _load_config(self) -> TradingConfig:
        """거래 설정 로드"""
        config = load_trading_config()
        self.logger.info(f"거래 설정 로드 완료: 후보종목 {len(config.data_collection.candidate_stocks)}개")
        return config
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러 (Ctrl+C 등)"""
        self.logger.info(f"종료 신호 수신: {signum}")
        self.is_running = False
    
    async def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            self.logger.info("🚀 주식 단타 거래 시스템 초기화 시작")

            # 0. 오늘 거래시간 정보 출력 (특수일 확인)
            today_info = MarketHours.get_today_info('KRX')
            self.logger.info(f"📅 오늘 거래시간 정보:\n{today_info}")

            # 1. API 초기화
            self.logger.info("📡 API 매니저 초기화 시작...")
            if not self.api_manager.initialize():
                self.logger.error("❌ API 초기화 실패")
                return False
            self.logger.info("✅ API 매니저 초기화 완료")

            # 1.5. 자금 관리자 초기화 (API 초기화 후)
            balance_info = self.api_manager.get_account_balance()
            if balance_info:
                total_funds = float(balance_info.account_balance) if hasattr(balance_info, 'account_balance') else 10000000
                self.fund_manager.update_total_funds(total_funds)
                self.logger.info(f"💰 자금 관리자 초기화 완료: {total_funds:,.0f}원")
            else:
                self.logger.warning("⚠️ 잔고 조회 실패 - 기본값 1천만원으로 설정")
                self.fund_manager.update_total_funds(10000000)

            # 2. 시장 상태 확인
            market_status = get_market_status()
            self.logger.info(f"📊 현재 시장 상태: {market_status}")
            
            # 3. 텔레그램 초기화
            await self.telegram.initialize()
            
            # 4. DB에서 오늘 날짜의 후보 종목 복원
            await self._restore_todays_candidates()

            # 5. 장중 재시작 시 DB에서 프리마켓 리포트 복원
            await self._restore_pre_market_report()

            # 6. 장중 재시작 시 macd_cross 페이퍼 universe 1회 트리거
            #    (08:55 정상 경로는 _pre_market_task 내부, 09:00 이후 시작 시 누락됨)
            await self._late_start_macd_cross_recovery()

            self.logger.info("✅ 시스템 초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 초기화 실패: {e}")
            return False
    
    async def run_daily_cycle(self):
        """일일 거래 사이클 실행"""
        try:
            self.is_running = True
            self.logger.info("📈 일일 거래 사이클 시작")
            
            # 병렬 실행할 태스크들 (이름 매핑)
            task_factories = {
                'pre_market': self._pre_market_task,
                'data_collection': self._data_collection_task,
                'order_monitoring': self._order_monitoring_task,
                'stock_monitoring': self.trading_manager.start_monitoring,
                'trading_decision': self._trading_decision_task,
                'system_monitoring': self._system_monitoring_task,
                'telegram': self._telegram_task,
            }

            running_tasks: dict = {}
            for name, factory in task_factories.items():
                running_tasks[name] = asyncio.create_task(factory(), name=name)

            # 감시 루프: 죽은 태스크 감지 + 재시작
            while self.is_running:
                await asyncio.sleep(10)
                for name, task in list(running_tasks.items()):
                    if task.done():
                        exc = task.exception() if not task.cancelled() else None
                        if exc:
                            self.logger.error(f"🔥 태스크 '{name}' 예외로 사망: {exc}")
                            import traceback
                            self.logger.error(f"상세: {''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}")
                        else:
                            self.logger.warning(f"⚠️ 태스크 '{name}' 종료됨 (예외 없음)")
                        # 재시작
                        if self.is_running and name in task_factories:
                            self.logger.info(f"🔄 태스크 '{name}' 재시작 시도")
                            running_tasks[name] = asyncio.create_task(task_factories[name](), name=name)

            # 종료 시 모든 태스크 취소
            for task in running_tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*running_tasks.values(), return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 일일 거래 사이클 실행 중 오류: {e}")
        finally:
            await self.shutdown()
    
    async def _data_collection_task(self):
        """데이터 수집 태스크"""
        try:
            self.logger.info("📊 데이터 수집 태스크 시작")
            await self.data_collector.start_collection()
        except Exception as e:
            self.logger.error(f"❌ 데이터 수집 태스크 오류: {e}")
    
    async def _order_monitoring_task(self):
        """주문 모니터링 태스크"""
        try:
            self.logger.info("🔍 주문 모니터링 태스크 시작")
            await self.order_manager.start_monitoring()
        except Exception as e:
            self.logger.error(f"❌ 주문 모니터링 태스크 오류: {e}")
    
    async def _trading_decision_task(self):
        """매매 의사결정 태스크"""
        try:

            self.logger.info("🤖 매매 의사결정 태스크 시작")

            last_condition_check = datetime(2000, 1, 1, tzinfo=KST)  # 초기값
            preload_done_today = None  # 프리로드 실행 날짜 추적

            while self.is_running:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue

                # 전일 상위 종목 프리로드 (장 시작 시 1회)
                today_date = now_kst().date()
                if preload_done_today != today_date:
                    preload_done_today = today_date
                    await self._preload_stock_candidates()
                
                current_time = now_kst()

                # 🆕 macd_cross D+2 morning exit (09:01~05) — backtest exit_signal 동등
                # paper/live 양쪽 모두 동일 시간대에 trigger. dispatcher 가 모드 분기.
                try:
                    _hhmm = current_time.hour * 100 + current_time.minute
                    if (
                        self._macd_cross_mode() != 'off'
                        and 901 <= _hhmm <= 905
                        and self._last_paper_morning_exit_date != current_time.date()
                    ):
                        await self._macd_cross_exit_dispatcher()
                        self._last_paper_morning_exit_date = current_time.date()
                except Exception as e:
                    self.logger.error(f"❌ macd_cross morning exit 트리거 실패: {e}")

                # 🚨 장마감 시간 시장가 일괄매도 체크 (한 번만 실행) - 동적 시간 적용
                if MarketHours.is_eod_liquidation_time('KRX', current_time):
                    today_date = current_time.date()
                    if self._last_eod_liquidation_date != today_date:
                        await self._execute_end_of_day_liquidation()
                        # macd_cross 만료 청산 (EOD 직후 1회) — paper/live dispatcher
                        try:
                            if self._macd_cross_mode() != 'off':
                                await self._macd_cross_exit_dispatcher()
                        except Exception as e:
                            self.logger.error(f"❌ macd_cross exit 트리거 실패: {e}")
                        # macd_cross 실거래 킬 스위치 체크 (EOD 정산 후)
                        try:
                            self._check_macd_cross_kill_switch_thresholds()
                        except Exception as e:
                            self.logger.error(f"❌ macd_cross 킬 스위치 체크 실패: {e}")
                        # macd_cross paper 일일 보고 + safety stop 체크 (Task 11)
                        try:
                            if StrategySettings.PAPER_STRATEGY == 'macd_cross':
                                await self._macd_cross_paper_daily_report()
                        except Exception as e:
                            self.logger.error(f"❌ macd_cross 일일 보고 트리거 실패: {e}")
                        self._last_eod_liquidation_date = today_date

                    # 청산 시간 이후에는 매매 판단 건너뛰고 모니터링만 계속
                    # (장마감 후 데이터 저장을 위해 루프 계속 실행)
                    await asyncio.sleep(5)
                    continue
                
                # 장중 실시간 종목 스크리닝
                from config.strategy_settings import StrategySettings
                sc = StrategySettings.Screener
                if (sc.ENABLED and
                    is_market_open(current_time) and
                    not MarketHours.is_eod_liquidation_time('KRX', current_time) and
                    self._is_screening_time(current_time) and
                    (current_time - last_condition_check).total_seconds() >= sc.SCAN_INTERVAL_SECONDS):
                    await self._run_stock_screener()
                    last_condition_check = current_time
                
                # 매매 판단 시스템 실행 (5초 주기)
                # 실시간 잔고 조회 후 자금 관리자 업데이트
                loop = asyncio.get_event_loop()
                balance_info = await loop.run_in_executor(None, self.api_manager.get_account_balance)
                if balance_info:
                    self.fund_manager.update_total_funds(float(balance_info.account_balance))

                # 현재 가용 자금 계산 (총 자금의 10% 기준)
                fund_status = self.fund_manager.get_status()
                current_available_funds = fund_status['available_funds']
                max_investment_per_stock = fund_status['total_funds'] * 0.1  # 종목당 최대 10%

                self.logger.debug(f"💰 현재 자금 상황: 가용={current_available_funds:,.0f}원, 종목당최대={max_investment_per_stock:,.0f}원")

                await self._execute_trading_decision(current_available_funds)
                await asyncio.sleep(5)  # 5초 주기
                
        except Exception as e:
            self.logger.error(f"❌ 매매 의사결정 태스크 오류: {e}")
    
    async def _execute_trading_decision(self, available_funds: float = None):
        """매매 판단 시스템 실행 (매도 판단 + 포지션 동기화)

        Args:
            available_funds: 사용 가능한 자금 (미리 계산된 값) - 현재 미사용
        """
        try:
            # TradingStockManager에서 관리 중인 종목들 확인
            from core.models import StockState

            selected_stocks = self.trading_manager.get_stocks_by_state(StockState.SELECTED)
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            buy_pending_stocks = self.trading_manager.get_stocks_by_state(StockState.BUY_PENDING)
            sell_pending_stocks = self.trading_manager.get_stocks_by_state(StockState.SELL_PENDING)
            completed_stocks = self.trading_manager.get_stocks_by_state(StockState.COMPLETED)

            # 상태 변경 시에만 로그 출력 (노이즈 감소)
            current_status = (len(selected_stocks), len(completed_stocks), len(buy_pending_stocks), len(positioned_stocks), len(sell_pending_stocks))
            if not hasattr(self, '_last_stock_status') or self._last_stock_status != current_status:
                self._last_stock_status = current_status
                self.logger.info(
                    f"📦 종목 상태 현황: SELECTED={len(selected_stocks)}, COMPLETED={len(completed_stocks)}, "
                    f"BUY_PENDING={len(buy_pending_stocks)}, POSITIONED={len(positioned_stocks)}, SELL_PENDING={len(sell_pending_stocks)}"
                )

            # 매수 주문 중인 종목 상세 정보
            if buy_pending_stocks:
                for stock in buy_pending_stocks:
                    self.logger.info(f"  📊 매수 체결 대기: {stock.stock_code}({stock.stock_name}) - 주문ID: {stock.current_order_id}")

            # 🆕 매수 판단은 _update_intraday_data()에서 데이터 업데이트 직후 실행됨 (3분봉 + 10초 타이밍)
            # 이 함수에서는 매도 판단과 포지션 동기화만 수행

            # 🔧 긴급 포지션 동기화 (주석 처리됨 - 필요시 활성화)
            await self.emergency_sync_positions()

            # 실제 거래 모드: 실제 포지션만 매도 판단
            if positioned_stocks:
                self.logger.debug(f"💰 매도 판단 대상 {len(positioned_stocks)}개 종목: {[f'{s.stock_code}({s.stock_name})' for s in positioned_stocks]}")
                for trading_stock in positioned_stocks:
                    # 실제 포지션인지 확인
                    if trading_stock.position and trading_stock.position.quantity > 0:
                        await self._analyze_sell_decision(trading_stock)
                    else:
                        self.logger.warning(f"⚠️ {trading_stock.stock_code} 포지션 정보 없음 (매도 판단 건너뜀)")

            # SELL_CANDIDATE 매도 재시도 (타임아웃 복구 등으로 SELL_CANDIDATE에 빠진 종목)
            sell_candidate_stocks = self.trading_manager.get_stocks_by_state(StockState.SELL_CANDIDATE)
            for trading_stock in sell_candidate_stocks:
                if trading_stock.position and trading_stock.position.quantity > 0:
                    self.logger.info(f"🔄 {trading_stock.stock_code} SELL_CANDIDATE 매도 재시도")
                    await self._analyze_sell_decision(trading_stock)

            if not positioned_stocks and not sell_candidate_stocks:
                self.logger.debug("📊 매도 판단 대상 종목 없음 (POSITIONED/SELL_CANDIDATE 상태 종목 없음)")

        except Exception as e:
            self.logger.error(f"❌ 매매 판단 시스템 오류: {e}")
    
    def _count_open_paper_positions(self, strategy: str) -> int:
        """현재 미체결 paper 포지션 개수 (특정 strategy)."""
        try:
            df = self.db_manager.get_virtual_open_positions()
            if df is None or df.empty:
                return 0
            return int((df['strategy'] == strategy).sum())
        except Exception as e:
            self.logger.debug(f"_count_open_paper_positions 실패: {e}")
            return 0

    def _get_macd_cross_paper_open_codes(self) -> set:
        """현재 미체결 macd_cross 가상 포지션의 종목 코드 집합 (EOD 격리용)."""
        try:
            df = self.db_manager.get_virtual_open_positions()
            if df is None or df.empty:
                return set()
            return set(df.loc[df['strategy'] == 'macd_cross', 'stock_code'].tolist())
        except Exception as e:
            self.logger.debug(f"_get_macd_cross_paper_open_codes 실패: {e}")
            return set()

    def _count_krx_trading_days_between(self, buy_date, today_date) -> int:
        """KRX 실거래일 기준 buy_date (exclusive) ~ today_date (inclusive) 영업일 수.

        backtests.common.trading_day.count_trading_days_between 와 동일 의미.

        구현 노트 (2026-04-26 fix — off-by-one 제거):
          daily_candles 는 EOD 후 post_market_data_saver 에서 갱신되므로
          today (D2) row 가 09:01 시점에는 아직 없다. 단순히
          `WHERE date <= today` 로 카운트하면 D2 09:01 morning trigger 에서
          백테스트 대비 1일 적게 카운트되어 exit 1일 지연 (체계적 버그).

          해결: 과거 거래일은 daily_candles (어제까지) 에서 count, 오늘 영업일
          여부는 minute_candles (실시간 09:00 부터 갱신) 에 today row 존재
          여부로 판정. 미래 데이터 미참조 — backtest 의 분봉 trade_date
          nunique 와 의미 1:1 동등.

        Args:
            buy_date: 매수일 (date 객체).
            today_date: 오늘 날짜 (date 객체).
        Returns:
            거래일 수 (int). DB 오류 시 보수적으로 0 (만료 안 함).
        """
        try:
            from datetime import timedelta
            buy_str = buy_date.strftime('%Y%m%d')
            yesterday_str = (today_date - timedelta(days=1)).strftime('%Y%m%d')
            today_str = today_date.strftime('%Y%m%d')

            # (a) 어제까지 EOD 마감된 과거 거래일 수
            row_past = self.db_manager._fetchone(
                """SELECT COUNT(DISTINCT stck_bsop_date) FROM daily_candles
                   WHERE stck_bsop_date > %s AND stck_bsop_date <= %s""",
                (buy_str, yesterday_str),
            )
            past_count = int(row_past[0]) if row_past else 0

            # (b) today 가 영업일이면 +1 — minute_candles 에 today row 가 있으면 영업일.
            #     09:00 부터 분봉 수집되므로 휴일에는 row 가 없고 영업일에는 있음.
            row_today = self.db_manager._fetchone(
                "SELECT 1 FROM minute_candles WHERE trade_date = %s LIMIT 1",
                (today_str,),
            )
            today_count = 1 if row_today else 0

            return past_count + today_count
        except Exception as e:
            self.logger.warning(f"_count_krx_trading_days_between DB 오류 → 0 반환: {e}")
            return 0

    def _has_macd_cross_buy_today(self, stock_code: str) -> bool:
        """오늘 macd_cross 로 이미 진입했는지. DB 오류 시 보수적으로 True (차단)."""
        try:
            today = now_kst().strftime('%Y-%m-%d')
            row = self.db_manager._fetchone(
                """SELECT COUNT(*) FROM virtual_trading_records
                   WHERE stock_code=%s AND action='BUY'
                     AND strategy='macd_cross'
                     AND DATE(timestamp) = %s""",
                (stock_code, today),
            )
            return (row[0] if row else 0) > 0
        except Exception as e:
            self.logger.warning(f"_has_macd_cross_buy_today DB 오류 → 보수적 차단: {e}")
            return True

    def _count_today_macd_cross_real_buys(self) -> int:
        """오늘 macd_cross 실거래 BUY 건수 (real_trading_records 기준)."""
        try:
            today = now_kst().strftime('%Y-%m-%d')
            row = self.db_manager._fetchone(
                """SELECT COUNT(*) FROM real_trading_records
                   WHERE action='BUY' AND strategy='macd_cross'
                     AND DATE(timestamp) = %s""",
                (today,),
            )
            return int(row[0] if row else 0)
        except Exception as e:
            self.logger.debug(f"_count_today_macd_cross_real_buys 실패: {e}")
            return 0

    def _has_macd_cross_real_buy_today(self, stock_code: str) -> bool:
        """오늘 macd_cross 실거래로 이미 진입했는지. DB 오류 시 보수적으로 True (차단)."""
        try:
            today = now_kst().strftime('%Y-%m-%d')
            row = self.db_manager._fetchone(
                """SELECT COUNT(*) FROM real_trading_records
                   WHERE stock_code=%s AND action='BUY'
                     AND strategy='macd_cross'
                     AND DATE(timestamp) = %s""",
                (stock_code, today),
            )
            return (row[0] if row else 0) > 0
        except Exception as e:
            self.logger.warning(f"_has_macd_cross_real_buy_today DB 오류 → 보수적 차단: {e}")
            return True

    def _is_macd_cross_kill_switch_active(self) -> bool:
        """디스크 기반 킬 스위치 상태 확인 (config/macd_cross_kill_switch.json).

        파일이 존재하고 disabled=True 면 macd_cross 실거래 정지.
        수동 복구 = 파일 삭제 후 봇 재시작.
        """
        try:
            import json
            from pathlib import Path
            ks_path = Path(__file__).parent / 'config' / 'macd_cross_kill_switch.json'
            if not ks_path.exists():
                return False
            with open(ks_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            return bool(state.get('disabled', False))
        except Exception as e:
            self.logger.debug(f"[macd_cross.killswitch] state 읽기 실패: {e}")
            return False

    def _trigger_macd_cross_kill_switch(self, reason: str) -> None:
        """킬 스위치 발동: 디스크에 disabled 상태 저장 + 텔레그램 알림.

        Spec: 누적 -5% 또는 5연속 손실 시 영구 정지 (수동 복구만).
        파일 형식: {"disabled": true, "reason": "...", "triggered_at": "..."}
        """
        try:
            import json
            from pathlib import Path
            ks_path = Path(__file__).parent / 'config' / 'macd_cross_kill_switch.json'
            ks_path.parent.mkdir(exist_ok=True)
            state = {
                'disabled': True,
                'reason': reason,
                'triggered_at': now_kst().strftime('%Y-%m-%d %H:%M:%S'),
            }
            with open(ks_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            self.logger.error(f"🛑 [macd_cross.killswitch] 발동! {reason}")
            # 텔레그램 긴급 알림 (best-effort)
            try:
                msg = (
                    f"🛑 *macd_cross 킬 스위치 발동*\n"
                    f"사유: {reason}\n"
                    f"매수 영구 정지. 복구는 `{ks_path}` 삭제 후 봇 재시작."
                )
                import asyncio
                asyncio.create_task(self.telegram.notify_system_status(msg))
            except Exception as te:
                self.logger.warning(f"킬 스위치 텔레그램 알림 실패: {te}")
        except Exception as e:
            self.logger.error(f"❌ 킬 스위치 디스크 저장 실패: {e}")

    def _check_macd_cross_kill_switch_thresholds(self) -> None:
        """누적 -5% 또는 5연속 손실 시 킬 스위치 발동.

        실거래 모드만 평가. real_trading_records.strategy='macd_cross' AND action='SELL'.
        """
        try:
            if self._macd_cross_mode() != 'real':
                return
            if self._is_macd_cross_kill_switch_active():
                return  # 이미 발동됨
            # SELL 레코드 시간순 조회
            with self.db_manager._pool_obj.connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT timestamp, net_profit
                    FROM real_trading_records
                    WHERE strategy='macd_cross' AND action='SELL'
                      AND net_profit IS NOT NULL
                    ORDER BY timestamp ASC
                """)
                rows = cur.fetchall()
            if not rows:
                return
            # 누적 net P&L
            cumulative = sum(float(r[1]) for r in rows)
            # 연속 손실 (시간역순으로 음수 카운트)
            consec_losses = 0
            for r in reversed(rows):
                if float(r[1]) < 0:
                    consec_losses += 1
                else:
                    break
            # 기준 자본 (현재 fund_manager.total_funds)
            fund_status = self.fund_manager.get_status()
            base_capital = float(fund_status.get('total_funds', 0))
            if base_capital <= 0:
                return
            cumulative_pct = (cumulative / base_capital) * 100
            self.logger.info(
                f"[macd_cross.killswitch] check: 누적 P&L {cumulative:+,.0f}원 "
                f"({cumulative_pct:+.2f}%), 연속손실 {consec_losses}건"
            )
            # 임계값
            if cumulative_pct <= -5.0:
                self._trigger_macd_cross_kill_switch(
                    f"누적 손실 {cumulative_pct:+.2f}% <= -5.0% (자본 {base_capital:,.0f})"
                )
                return
            if consec_losses >= 5:
                self._trigger_macd_cross_kill_switch(
                    f"연속 손실 {consec_losses}건 >= 5건"
                )
                return
        except Exception as e:
            self.logger.error(f"❌ 킬 스위치 체크 실패: {e}")

    def _macd_cross_circuit_breaker_blocks(self, current_time) -> bool:
        """전일 KOSPI/KOSDAQ -3% 서킷브레이커 inherit 체크 (macd_cross 실거래 전용).

        Spec G1 + 사용자 결정: 다른 안전망 (NXT, 갭업, 동적SL, 성과게이트) 미적용.
        오직 -3% prev-day 만 자본 보호 absolute 안전망으로 inherit.

        결과 캐시 (당일 1회). 전일 데이터 없으면 보수적으로 False (차단 안 함).
        """
        try:
            from config.strategy_settings import StrategySettings
            threshold = StrategySettings.PreMarket.CIRCUIT_BREAKER_PREV_DAY_PCT
            today = current_time.date()
            cache = getattr(self, '_macd_cross_cb_cache', None)
            if cache and cache.get('date') == today:
                return cache['blocked']

            ret = self.pre_market_analyzer._get_prev_day_index_returns()
            if ret is None:
                self._macd_cross_cb_cache = {'date': today, 'blocked': False}
                return False
            kospi = ret.get('kospi_ret', 0)
            kosdaq = ret.get('kosdaq_ret', 0)
            worst = min(kospi, kosdaq)
            blocked = worst <= threshold
            self._macd_cross_cb_cache = {'date': today, 'blocked': blocked}
            if blocked:
                idx = "KOSPI" if kospi <= kosdaq else "KOSDAQ"
                self.logger.warning(
                    f"🚫 [macd_cross.cb] 전일 {idx} {worst:+.2f}% "
                    f"(임계 {threshold}%) → 매수 차단"
                )
            return blocked
        except Exception as e:
            self.logger.warning(f"[macd_cross.cb] 체크 실패 → 차단 안 함: {e}")
            return False

    def _macd_cross_mode(self) -> str:
        """macd_cross 운영 모드 결정.

        Returns:
            'real'    : ACTIVE_STRATEGY=='macd_cross' AND VIRTUAL_ONLY=False → 실 주문
            'virtual' : ACTIVE_STRATEGY=='macd_cross' AND VIRTUAL_ONLY=True  → 가상 (실거래 진입 전 테스트)
                       또는 PAPER_STRATEGY=='macd_cross' (기존 페이퍼 운영)
            'off'     : 둘 다 비활성
        """
        from config.strategy_settings import StrategySettings
        cfg_mc = StrategySettings.MacdCross
        if StrategySettings.ACTIVE_STRATEGY == 'macd_cross':
            if cfg_mc.VIRTUAL_ONLY:
                return 'virtual'
            # 실거래 모드 — 킬 스위치 발동 시 전면 정지
            if self._is_macd_cross_kill_switch_active():
                return 'off'
            return 'real'
        if StrategySettings.PAPER_STRATEGY == 'macd_cross':
            return 'virtual'
        return 'off'

    async def _evaluate_macd_cross_window(self, current_time):
        """macd_cross 진입 평가 (14:31~15:00).

        모드별 분기 (`_macd_cross_mode`):
        - 'virtual': db_manager.save_virtual_buy 직접 호출 (백테스트 마찰 적용, VTM 우회)
        - 'real'   : decision_engine.execute_real_buy 호출 (KIS 시장가 주문)
        - 'off'    : 즉시 return

        공통:
        - decision_engine.macd_cross_strategy 의 캐시된 universe 만 평가
        - 시그널 hit 시점은 14:31:00+ (백테스트 next_bar_open 정렬)
        - 백테스트 가드 적용: 가격제한 buffer + 거래량 feasibility (실거래에도 동일 적용)
        """
        from config.strategy_settings import StrategySettings
        from backtests.common.execution_model import (
            BUY_COMMISSION, SLIPPAGE_ONE_WAY, ExecutionModel,
        )

        mode = self._macd_cross_mode()
        if mode == 'off' or self.decision_engine.macd_cross_strategy is None:
            return
        is_virtual = (mode == 'virtual')

        cfg_mc = StrategySettings.MacdCross
        hhmm = current_time.hour * 100 + current_time.minute
        if not (cfg_mc.ENTRY_HHMM_MIN <= hhmm <= cfg_mc.ENTRY_HHMM_MAX):
            return

        # 🚨 실거래 모드 한정: 전일 -3% 서킷브레이커 inherit (자본 보호 absolute)
        # paper 모드는 G1 (백테스트 100% 재현) 원칙으로 미적용.
        if not is_virtual and self._macd_cross_circuit_breaker_blocks(current_time):
            return

        strategy = self.decision_engine.macd_cross_strategy
        universe_codes = list(strategy._cache.keys()) if hasattr(strategy, '_cache') else []
        if not universe_codes:
            return

        # 일일 진입 한도 체크 (모드별 카운팅)
        def _today_buy_count() -> int:
            return (self._count_open_paper_positions('macd_cross')
                    if is_virtual
                    else self._count_today_macd_cross_real_buys())

        def _has_buy_today(code: str) -> bool:
            return (self._has_macd_cross_buy_today(code)
                    if is_virtual
                    else self._has_macd_cross_real_buy_today(code))

        if _today_buy_count() >= cfg_mc.MAX_DAILY_POSITIONS:
            return

        for stock_code in universe_codes:
            try:
                if not strategy.check_entry(stock_code, hhmm):
                    continue
                if _has_buy_today(stock_code):
                    continue
                if _today_buy_count() >= cfg_mc.MAX_DAILY_POSITIONS:
                    break

                price_info = self.intraday_manager.get_cached_current_price(stock_code)
                if not price_info:
                    continue
                current_price = float(price_info.get('current_price', 0))
                if current_price <= 0:
                    continue

                # 가격 제한 (상한가 buffer) — paper/real 동일
                prev_close, prev_trading_value = strategy.get_daily_meta(stock_code)
                if prev_close and not ExecutionModel.is_price_limit_safe(
                    current_price, prev_close, side="buy"
                ):
                    self.logger.debug(
                        f"[macd_cross] {stock_code} 상한가 buffer 위반 → skip"
                    )
                    continue

                ts = self.trading_manager.get_trading_stock(stock_code)
                stock_name = ts.stock_name if ts else f"MC_{stock_code}"

                if is_virtual:
                    # === Virtual path (paper 또는 live 진입 전 테스트) ===
                    # 백테스트 마찰: 슬리피지 + 매수 수수료
                    buy_fill = current_price * (1 + SLIPPAGE_ONE_WAY)
                    buy_price_effective = buy_fill * (1 + BUY_COMMISSION)
                    budget = cfg_mc.VIRTUAL_CAPITAL * cfg_mc.BUY_BUDGET_RATIO
                    quantity = int(budget / buy_price_effective)
                    if quantity <= 0:
                        self.logger.debug(
                            f"[macd_cross] {stock_code} buy_price {buy_price_effective:,.0f} > "
                            f"budget {budget:,.0f} → quantity 0 → skip"
                        )
                        continue
                    order_value = buy_price_effective * quantity
                    if prev_trading_value and not ExecutionModel.is_volume_feasible(
                        order_value, prev_trading_value
                    ):
                        self.logger.debug(
                            f"[macd_cross] {stock_code} 거래량 한도 위반 "
                            f"(주문 {order_value:,.0f} > {prev_trading_value*0.02:,.0f}) → skip"
                        )
                        continue
                    buy_record_id = self.db_manager.save_virtual_buy(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        price=buy_price_effective,
                        quantity=quantity,
                        strategy='macd_cross',
                        reason=f"macd_cross_signal_hhmm{hhmm}",
                    )
                    if buy_record_id:
                        self.logger.info(
                            f"👻 [macd_cross] 가상 매수: {stock_code} {quantity}주 "
                            f"@{buy_price_effective:,.0f} (mid={current_price:,.0f}, id={buy_record_id})"
                        )
                    else:
                        self.logger.warning(
                            f"⚠️ [macd_cross] 가상 매수 실패: {stock_code} {quantity}주"
                        )
                else:
                    # === Real path (실 계좌 시장가 주문) ===
                    # 자금: (가용잔고) / (남은 슬롯) — 자본의 1/N 동적 분할
                    # MAX_DAILY_POSITIONS=5 의 남은 슬롯 수 = 5 - 오늘 진입 건수
                    # 첫 진입: 6.43M / 5 = 1.286M, 두번째: 5.14M / 4 = 1.285M ...
                    fund_status = self.fund_manager.get_status()
                    remaining_slots = cfg_mc.MAX_DAILY_POSITIONS - _today_buy_count()
                    if remaining_slots <= 0:
                        break
                    budget = fund_status['available_funds'] / remaining_slots
                    # 안전 캡: 단일 포지션 최대 = total × BUY_BUDGET_RATIO
                    budget = min(budget, fund_status['total_funds'] * cfg_mc.BUY_BUDGET_RATIO)
                    if budget <= 0 or current_price <= 0:
                        continue
                    quantity = int(budget / current_price)
                    if quantity <= 0:
                        self.logger.debug(
                            f"[macd_cross] {stock_code} budget {budget:,.0f} / price "
                            f"{current_price:,.0f} → quantity 0 → skip"
                        )
                        continue
                    # 거래량 feasibility (실거래도 동일 가드 적용)
                    order_value = current_price * quantity
                    if prev_trading_value and not ExecutionModel.is_volume_feasible(
                        order_value, prev_trading_value
                    ):
                        self.logger.debug(
                            f"[macd_cross] {stock_code} 거래량 한도 위반 "
                            f"(주문 {order_value:,.0f} > {prev_trading_value*0.02:,.0f}) → skip"
                        )
                        continue
                    if ts is None:
                        self.logger.warning(
                            f"⚠️ [macd_cross] {stock_code} trading_stock 미등록 → skip"
                        )
                        continue
                    ok = await self.decision_engine.execute_real_buy(
                        ts,
                        f"macd_cross_signal_hhmm{hhmm}",
                        current_price,
                        quantity,
                        candle_time=current_time,
                        strategy_tag='macd_cross',
                        market=True,
                    )
                    if ok:
                        self.logger.info(
                            f"🔥 [macd_cross] 실 매수 주문: {stock_code} {quantity}주 "
                            f"@~{current_price:,.0f} (시장가, 예산 {budget:,.0f})"
                        )
                    else:
                        self.logger.warning(
                            f"⚠️ [macd_cross] 실 매수 주문 실패: {stock_code} {quantity}주"
                        )
            except Exception as e:
                self.logger.error(f"❌ [macd_cross] {stock_code} 평가 오류: {e}")

    async def _analyze_buy_decision(self, trading_stock, available_funds: float = None):
        """매수 판단 분석 (완성된 1분봉 기준)

        Args:
            trading_stock: 거래 대상 주식
            available_funds: 사용 가능한 자금 (미리 계산된 값)
        """
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name

            #self.logger.debug(f"🔍 매수 판단 시작: {stock_code}({stock_name})")

            # 추가 안전 검증: 현재 보유 중인 종목인지 다시 한번 확인
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            if any(pos_stock.stock_code == stock_code for pos_stock in positioned_stocks):
                self.logger.info(f"⚠️ 보유 중인 종목 매수 신호 무시: {stock_code}({stock_name})")
                return

            # 25분 매수 쿨다운 확인
            if trading_stock.is_buy_cooldown_active():
                remaining_minutes = trading_stock.get_remaining_cooldown_minutes()
                self.logger.debug(f"⚠️ {stock_code}: 매수 쿨다운 활성화 (남은 시간: {remaining_minutes}분)")
                return

            # 🆕 타이밍 체크는 _update_intraday_data()에서 이미 수행됨 (3분봉 완성 + 10초 후)
            # 여기서는 종목별 매수 판단만 수행

            # 분봉 데이터 가져오기
            combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
            if combined_data is None:
                self.logger.debug(f"❌ {stock_code} 1분봉 데이터 없음 (None)")
                return
            if len(combined_data) < 10:
                self.logger.debug(f"❌ {stock_code} 1분봉 데이터 부족: {len(combined_data)}개 (최소 10개 필요) - 실시간 데이터 대기 중")
                # 실시간 환경에서는 메모리에 있는 데이터만 사용 (캐시 파일 체크 불필요)
                return
            
            # macd_cross 단일 운영: 1분봉 직접 사용
            from config.strategy_settings import StrategySettings
            analysis_data = combined_data

            # 매매 판단 엔진으로 매수 신호 확인
            buy_signal, buy_reason, buy_info = await self.decision_engine.analyze_buy_decision(trading_stock, analysis_data)
            
            self.logger.debug(f"💡 {stock_code} 매수 판단 결과: signal={buy_signal}, reason='{buy_reason}'")
            if buy_signal and buy_info:
                self.logger.debug(f"💰 {stock_code} 매수 정보: 가격={buy_info['buy_price']:,.0f}원, 수량={buy_info['quantity']:,}주, 투자금={buy_info['max_buy_amount']:,.0f}원")
          
            
            if buy_signal and buy_info.get('quantity', 0) > 0:
                self.logger.info(f"🚀 {stock_code}({stock_name}) 매수 신호 발생: {buy_reason}")

                # 매수 전 자금 확인 (FundManager 기준 — macd_cross 는 MacdCross.BUY_BUDGET_RATIO 적용)
                if available_funds is not None:
                    fund_status = self.fund_manager.get_status()
                    buy_budget_ratio = self.config.order_management.buy_budget_ratio
                    max_buy_amount = min(available_funds, fund_status['total_funds'] * buy_budget_ratio)
                else:
                    max_buy_amount = self.fund_manager.get_max_buy_amount(stock_code)

                required_amount = buy_info['buy_price'] * buy_info['quantity']

                if required_amount > max_buy_amount:
                    self.logger.warning(f"⚠️ {stock_code} 자금 부족: 필요={required_amount:,.0f}원, 가용={max_buy_amount:,.0f}원")
                    # 가용 자금에 맞게 수량 조정
                    if max_buy_amount > 0:
                        adjusted_quantity = int(max_buy_amount / buy_info['buy_price'])
                        if adjusted_quantity > 0:
                            buy_info['quantity'] = adjusted_quantity
                            self.logger.info(f"💰 {stock_code} 수량 조정: {adjusted_quantity}주 (투자금: {adjusted_quantity * buy_info['buy_price']:,.0f}원)")
                        else:
                            self.logger.warning(f"❌ {stock_code} 매수 포기: 최소 1주도 매수 불가")
                            return
                    else:
                        self.logger.warning(f"❌ {stock_code} 매수 포기: 가용 자금 없음")
                        return

                # 🆕 매수 전 종목 상태 확인
                current_stock = self.trading_manager.get_trading_stock(stock_code)
                if current_stock:
                    self.logger.debug(f"🔍 매수 전 상태 확인: {stock_code} 현재상태={current_stock.state.value}")
                
                # macd_cross 단일 운영: 실거래만, 1분봉 단위
                is_virtual = False
                try:
                    raw_candle_time = analysis_data['datetime'].iloc[-1]
                    minute_normalized = raw_candle_time.minute  # 1분 단위
                    current_candle_time = raw_candle_time.replace(minute=minute_normalized, second=0, microsecond=0)

                    if is_virtual:
                        await self.decision_engine.execute_virtual_buy(
                            trading_stock,
                            analysis_data,
                            buy_reason,
                            buy_price=buy_info['buy_price'],
                        )
                        # 가상 체결 후 POSITIONED 로 상태 전이 (매도 판단 루프 포함)
                        try:
                            self.trading_manager._change_stock_state(
                                stock_code, StockState.POSITIONED, "가상 매수 체결"
                            )
                        except Exception:
                            pass
                        self.logger.info(
                            f"👻 가상 매수 완료: {stock_code}({stock_name}) - {buy_reason}"
                        )
                    else:
                        await self.decision_engine.execute_real_buy(
                            trading_stock,
                            buy_reason,
                            buy_info['buy_price'],
                            buy_info['quantity'],
                            candle_time=current_candle_time
                        )
                        # 상태는 주문 처리 로직에서 자동으로 변경됨 (SELECTED -> BUY_PENDING -> POSITIONED)
                        self.logger.info(
                            f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}"
                        )
                except Exception as e:
                    self.logger.error(f"❌ 매수 처리 오류 (virtual={is_virtual}): {e}")
                    
            else:
                #self.logger.debug(f"📊 {stock_code}({stock_name}) 매수 신호 없음")
                pass
                        
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 판단 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류 정보: {traceback.format_exc()}")
    
    async def _analyze_sell_decision(self, trading_stock):
        """매도 판단 분석 (간단한 손절/익절 로직)"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 실시간 현재가 정보만 확인 (간단한 손절/익절 로직)
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            if current_price_info is None:
                # 폴백: 캐시 없으면 API로 직접 조회 (재시작 직후 매도 판단 보장)
                try:
                    current_price_info = self.intraday_manager.get_current_price_for_sell(stock_code)
                    if current_price_info is None:
                        return
                    # 조회 결과를 캐시에도 저장
                    if stock_code in self.intraday_manager.selected_stocks:
                        self.intraday_manager.selected_stocks[stock_code].current_price_info = current_price_info
                except Exception:
                    return
            
            # 매매 판단 엔진으로 매도 신호 확인 (combined_data 불필요)
            sell_signal, sell_reason = await self.decision_engine.analyze_sell_decision(trading_stock, None)
            
            if sell_signal:
                # 🆕 매도 전 종목 상태 확인
                self.logger.debug(f"🔍 매도 전 상태 확인: {stock_code} 현재상태={trading_stock.state.value}")
                if trading_stock.position:
                    self.logger.debug(f"🔍 포지션 정보: {trading_stock.position.quantity}주 @{trading_stock.position.avg_price:,.0f}원")
                
                # 매도 후보로 변경 (이미 SELL_CANDIDATE이면 건너뜀)
                if trading_stock.state == StockState.SELL_CANDIDATE:
                    success = True
                else:
                    success = await self.trading_manager.move_to_sell_candidate(stock_code, sell_reason)
                if success:
                    # [실제 매도 주문 실행 - 활성화]
                    try:
                        await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                        self.logger.info(f"📉 실제 매도 주문 완료: {stock_code}({stock_name}) - {sell_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 실제 매도 처리 오류: {e}")
                    
                    # [가상매매 코드 - 주석처리]
                    # try:
                    #     await self.decision_engine.execute_virtual_sell(trading_stock, combined_data, sell_reason)
                    #     self.logger.info(f"📉 가상 매도 완료 처리: {stock_code}({stock_name}) - {sell_reason}")
                    # except Exception as e:
                    #     self.logger.error(f"❌ 가상 매도 처리 오류: {e}")
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매도 판단 오류: {e}")
    
    # 가상매매 포지션 분석 함수 비활성화 (실제 매매 모드)
    # async def _analyze_virtual_positions_for_sell(self):
    #     """DB에서 미체결 가상 포지션을 조회하여 매도 판단 (signal_replay 방식)"""
    #     pass
    
    async def _telegram_task(self):
        """텔레그램 태스크"""
        try:
            self.logger.info("📱 텔레그램 태스크 시작")
            
            # 텔레그램 봇 폴링과 주기적 상태 알림을 병렬 실행
            telegram_tasks = [
                self.telegram.start_telegram_bot(),
                self.telegram.periodic_status_task()
            ]
            
            await asyncio.gather(*telegram_tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 텔레그램 태스크 오류: {e}")
    
    async def _pre_market_task(self):
        """NXT 프리마켓 인텔리전스 수집 태스크 (08:00-09:00)"""
        try:
            from config.strategy_settings import StrategySettings
            pm = StrategySettings.PreMarket

            if not pm.ENABLED:
                self.logger.info("[프리마켓] 프리마켓 분석 비활성화 상태")
                return

            self.logger.info("[프리마켓] NXT 프리마켓 인텔리전스 태스크 시작")

            last_snapshot = datetime(2000, 1, 1, tzinfo=KST)
            report_generated_today = None
            market_open_gap_checked_today = None  # 장 시작 갭 체크 완료 날짜

            while self.is_running:
                current_time = now_kst()
                today = current_time.date()

                # 새로운 날이면 상태 초기화
                if report_generated_today and report_generated_today != today:
                    self.pre_market_analyzer.reset_daily_state()
                    report_generated_today = None
                    market_open_gap_checked_today = None

                # NXT 프리마켓 시간만 활성 (08:00-09:00 평일)
                if not MarketHours.is_nxt_pre_market_time(current_time):
                    await asyncio.sleep(30)
                    continue

                # 오늘 리포트 이미 생성됨
                if report_generated_today == today:
                    await asyncio.sleep(60)
                    continue

                t = current_time.hour * 60 + current_time.minute
                analysis_start = pm.ANALYSIS_START_HOUR * 60 + pm.ANALYSIS_START_MINUTE
                analysis_end = pm.ANALYSIS_END_HOUR * 60 + pm.ANALYSIS_END_MINUTE

                # 스냅샷 수집 (5분 간격)
                if analysis_start <= t <= analysis_end:
                    if (current_time - last_snapshot).total_seconds() >= pm.SNAPSHOT_INTERVAL_SECONDS:
                        loop = asyncio.get_event_loop()
                        snapshot = await loop.run_in_executor(
                            None, self.pre_market_analyzer.collect_snapshot
                        )
                        last_snapshot = current_time

                # 08:55 이후 리포트 생성
                if t >= pm.ANALYSIS_END_HOUR * 60 + pm.ANALYSIS_END_MINUTE:
                    if report_generated_today != today:
                        # 스냅샷이 없으면 한 번 수집 시도 후 리포트 생성
                        if not self.pre_market_analyzer._snapshots:
                            self.logger.info("[프리마켓] 스냅샷 없음 - 수집 1회 시도 후 리포트 생성")
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(
                                None, self.pre_market_analyzer.collect_snapshot
                            )
                        loop = asyncio.get_event_loop()
                        report = await loop.run_in_executor(
                            None, self.pre_market_analyzer.generate_report
                        )
                        report_generated_today = today

                        # 매매 엔진에 리포트 전달
                        self.decision_engine.set_pre_market_report(report)

                        # macd_cross universe 준비 (active 또는 paper 모드 모두)
                        try:
                            if (
                                self.decision_engine.macd_cross_strategy is not None
                                and (
                                    StrategySettings.ACTIVE_STRATEGY == 'macd_cross'
                                    or StrategySettings.PAPER_STRATEGY == 'macd_cross'
                                )
                            ):
                                await self._prepare_macd_cross_universe(current_time)
                        except Exception as e:
                            self.logger.error(f"❌ [macd_cross] universe 준비 실패: {e}")

                        self.logger.info(
                            f"[프리마켓] 리포트 완료: "
                            f"심리={report.market_sentiment}({report.sentiment_score:+.2f}), "
                            f"갭={report.gap_direction}({report.expected_gap_pct:+.2f}%), "
                            f"추천포지션={report.recommended_max_positions}"
                        )

                        # 텔레그램 모닝 브리핑
                        await self._send_morning_briefing(report)

                # 장 시작 후 실제 지수 갭 체크 (09:01 이후 1회)
                if (report_generated_today == today and
                        market_open_gap_checked_today != today and
                        current_time.hour == 9 and
                        current_time.minute >= pm.MARKET_OPEN_GAP_CHECK_MINUTE):
                    market_open_gap_checked_today = today
                    self.logger.info("[장시작갭] 실제 지수 갭 체크 시작...")
                    loop = asyncio.get_event_loop()
                    updated_report = await loop.run_in_executor(
                        None, self.pre_market_analyzer.check_market_open_gap
                    )
                    if updated_report:
                        # 서킷브레이커/갭업필터 발동 → 매매 엔진에 업데이트된 리포트 재전달
                        self.decision_engine.set_pre_market_report(updated_report)
                        is_gap_up = updated_report.market_sentiment == 'gap_up_filter'
                        label = "갭업필터" if is_gap_up else "서킷브레이커"
                        self.logger.warning(
                            f"[장시작갭] {label} 발동! "
                            f"추천포지션={updated_report.recommended_max_positions}"
                        )
                        # 텔레그램 긴급 알림
                        gap_msg = (
                            f"[장시작갭 {label}]\n"
                            f"매수 중단! 포지션={updated_report.recommended_max_positions}\n"
                            f"{updated_report.log_lines[0] if updated_report.log_lines else ''}"
                        )
                        await self.telegram.notify_system_status(gap_msg)

                await asyncio.sleep(10)

        except Exception as e:
            self.logger.error(f"[프리마켓] 태스크 오류: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    async def _prepare_macd_cross_universe(self, current_time):
        """macd_cross 페이퍼 universe + daily history 주입 (08:55).

        - stock_screener.preload_macd_cross_universe(top_n=30) 로 universe 선정
        - trading_manager.add_selected_stock 으로 intraday_manager 등록
        - 각 종목의 daily history 를 macd_cross_strategy 에 주입 → MACD hist 캐시
        """
        from config.strategy_settings import StrategySettings

        cfg = StrategySettings.MacdCross
        loop = asyncio.get_event_loop()

        # 1. universe 선정
        candidates = await loop.run_in_executor(
            None,
            lambda: self.stock_screener.preload_macd_cross_universe(top_n=cfg.UNIVERSE_TOP_N),
        )
        if not candidates:
            self.logger.warning("[macd_cross] universe 없음 → prep skip")
            return

        # 2. trading_manager / intraday_manager 등록
        registered = 0
        for stock in candidates:
            try:
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock.code,
                    stock_name=stock.name,
                    selection_reason=stock.reason,
                    prev_close=stock.current_price,
                )
                if success:
                    self.stock_screener.mark_stock_added(stock.code)
                    registered += 1
            except Exception as e:
                self.logger.debug(f"[macd_cross] 등록 실패 {stock.code}: {e}")

        # 3. daily history 주입 → MACD hist 캐시 (단일 connection 사용)
        today_str = current_time.strftime("%Y%m%d")
        strategy = self.decision_engine.macd_cross_strategy
        if strategy is None:
            self.logger.warning("[macd_cross] strategy 미초기화 → daily 주입 skip")
            return

        codes = [s.code for s in candidates]
        cached_count = await loop.run_in_executor(
            None, self._load_macd_cross_daily_batch, codes, today_str, strategy
        )

        self.logger.info(
            f"🎯 [macd_cross] universe 준비 완료: 등록={registered}, "
            f"daily 캐시={cached_count}/{len(candidates)}"
        )

    def _load_macd_cross_daily_batch(self, stock_codes, today_yyyymmdd: str, strategy) -> int:
        """macd_cross 일괄 daily history 로드 + 캐시 주입 (option B: 단일 connection).

        Args:
            stock_codes: 종목 코드 리스트.
            today_yyyymmdd: 오늘 (YYYYMMDD). daily_prices 조회 상한 기준.
            strategy: MacdCrossStrategy 인스턴스.
        Returns:
            성공 캐시된 종목 수.
        """
        import psycopg2
        import pandas as pd
        from config.settings import (
            PG_HOST, PG_PORT, PG_DATABASE_QUANT, PG_USER, PG_PASSWORD,
        )

        # MACD warmup: slow * 3 + signal = 34*3 + 12 = 114 영업일 → 150 fetch 로 여유 확보
        lookback = 150
        today_iso = f"{today_yyyymmdd[:4]}-{today_yyyymmdd[4:6]}-{today_yyyymmdd[6:]}"

        try:
            conn = psycopg2.connect(
                host=PG_HOST, port=PG_PORT, database=PG_DATABASE_QUANT,
                user=PG_USER, password=PG_PASSWORD, connect_timeout=5,
            )
        except Exception as e:
            self.logger.error(f"[macd_cross] daily DB 연결 실패: {e}")
            return 0

        cached = 0
        try:
            for code in stock_codes:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """SELECT REPLACE(date, '-', '') AS trade_date, close, trading_value
                           FROM daily_prices
                           WHERE stock_code = %s AND date < %s AND close IS NOT NULL
                           ORDER BY date DESC
                           LIMIT %s""",
                        [code, today_iso, lookback],
                    )
                    rows = cur.fetchall()
                    cur.close()
                    if not rows:
                        continue
                    df = pd.DataFrame(rows, columns=["trade_date", "close", "trading_value"])
                    df["close"] = df["close"].astype(float)
                    prev_tv = float(rows[0][2]) if rows[0][2] is not None else 0.0
                    df = df.iloc[::-1].reset_index(drop=True)
                    strategy.set_daily_history(
                        code, df, today_yyyymmdd, prev_trading_value=prev_tv
                    )
                    cached += 1
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    self.logger.debug(f"[macd_cross] daily prep {code}: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return cached

    async def _send_morning_briefing(self, report):
        """프리마켓 모닝 브리핑 텔레그램 발송"""
        try:
            lines = [
                f"=== 모닝 브리핑 ({report.report_time.strftime('%H:%M')}) ===",
                f"시장 심리: {report.market_sentiment.upper()} ({report.sentiment_score:+.2f})",
                f"예상 갭: {report.gap_direction} ({report.expected_gap_pct:+.2f}%)",
                f"변동성: {report.volatility_level}",
                f"NXT 데이터: {'사용 가능' if report.nxt_available else '사용 불가'}",
                "",
                f"오늘 설정:",
                f"  최대 보유: {report.recommended_max_positions}종목",
                f"  손절: {report.recommended_stop_loss_pct:.1%}",
                f"  익절: {report.recommended_take_profit_pct:.1%}",
            ]

            if report.top_movers:
                lines.append("")
                lines.append("NXT 상위 종목:")
                for mover in report.top_movers[:5]:
                    lines.append(
                        f"  {mover['code']}({mover['name']}): "
                        f"{mover['change_pct']:+.2f}% vol={mover['volume']:,}"
                    )

            message = "\n".join(lines)
            await self.telegram.notify_system_status(message)

        except Exception as e:
            self.logger.error(f"[프리마켓] 모닝 브리핑 발송 오류: {e}")

    async def _system_monitoring_task(self):
        """시스템 모니터링 태스크"""
        try:
            self.logger.info("🔥 DEBUG: _system_monitoring_task 시작됨")  # 디버깅용
            self.logger.info("📡 시스템 모니터링 태스크 시작")
            
            last_api_refresh = now_kst()
            last_market_check = now_kst()
            last_intraday_update = now_kst()  # 🆕 장중 데이터 업데이트 시간
            last_intraday_index_check = now_kst()  # 장중 지수 체크 시간
            post_market_data_saved_date = None  # 장 마감 후 데이터 저장 완료 날짜
            expanded_minute_saved_date = None  # 분봉 확대 수집 완료 날짜 (15:45 1회 실행)
            # last_chart_generation = datetime(2000, 1, 1, tzinfo=KST)  # 🆕 장 마감 후 차트 생성 시간 (주석처리)
            # chart_generation_count = 0  # 🆕 차트 생성 횟수 카운터 (주석처리)
            # last_chart_reset_date = now_kst().date()  # 🆕 차트 카운터 리셋 기준 날짜 (주석처리)

            self.logger.info("🔥 DEBUG: while 루프 진입 시도")  # 디버깅용
            while self.is_running:
                #self.logger.info(f"🔥 DEBUG: while 루프 실행 중 - is_running: {self.is_running}")  # 디버깅용
                current_time = now_kst()
                
                # API 24시간마다 재초기화
                if (current_time - last_api_refresh).total_seconds() >= 86400:  # 24시간
                    await self._refresh_api()
                    last_api_refresh = current_time

                # 장중 종목 실시간 데이터 업데이트 (매분 3~55초 사이에 실행)
                # 캔들 완성 후 빠른 감지를 위해 3초부터 시작 (기존 13초 → 3초)
                # 장 마감 후 분봉 조회는 불필요 (데이터 저장은 아래 별도 블록에서 처리)
                if 3 <= current_time.second <= 55 and (current_time - last_intraday_update).total_seconds() >= 5:
                    if is_market_open():
                        await self._update_intraday_data()
                        last_intraday_update = current_time

                # 장 마감 후 데이터 저장 (장 마감 1~15분 후 1회 실행)
                if current_time.weekday() < 5:
                    current_date = current_time.date()
                    if post_market_data_saved_date != current_date:
                        market_hours_info = MarketHours.get_market_hours('KRX', current_time)
                        close_time = market_hours_info['market_close']
                        minutes_after_close = (current_time.hour * 60 + current_time.minute) - (close_time.hour * 60 + close_time.minute)
                        if 1 <= minutes_after_close <= 15:
                            # 1단계: 데이터 저장
                            try:
                                self.logger.info("🏁 장 마감 후 데이터 저장 시작...")
                                self.intraday_manager.data_saver.save_all_data(self.intraday_manager)
                                self.logger.info("✅ 장 마감 후 데이터 저장 완료")
                            except Exception as e:
                                self.logger.error(f"❌ 장 마감 후 데이터 저장 실패: {e}")
                            # 2단계: 가상 추적 처리
                            try:
                                if self.decision_engine and hasattr(self.decision_engine, 'performance_gate'):
                                    if self.decision_engine.performance_gate:
                                        self.decision_engine.performance_gate.process_shadow_entries()
                            except Exception as e:
                                self.logger.warning(f"⚠️ 가상 추적 처리 실패: {e}")
                            # 두 단계 모두 시도 후 날짜 플래그 설정
                            post_market_data_saved_date = current_date

                # 🆕 분봉 확대 수집 (15:45 1회 실행, 평일만)
                # 목적: 거래대금 상위 300종목의 당일 분봉을 수집하여 시뮬-실거래 괴리 해소
                if current_time.weekday() < 5:
                    current_date = current_time.date()
                    if expanded_minute_saved_date != current_date:
                        # 15:45~16:00 사이 1회 실행
                        if current_time.hour == 15 and 45 <= current_time.minute < 60:
                            try:
                                self.logger.info("📦 분봉 확대 수집 시작 (상위 300종목)")
                                from core.expanded_minute_collector import ExpandedMinuteCollector
                                collector = ExpandedMinuteCollector(logger=self.logger)
                                stats = await collector.run_async(
                                    target_date=current_time.strftime('%Y%m%d'),
                                    top_n=300,
                                )
                                self.logger.info(
                                    f"✅ 분봉 확대 수집 완료: "
                                    f"성공 {stats['collected']}/{stats['target_count']}, "
                                    f"실패 {stats['failed']}, "
                                    f"소요 {stats['elapsed_sec']:.0f}초"
                                )
                                # 텔레그램 알림
                                try:
                                    if self.telegram:
                                        success_rate = (
                                            stats['collected'] / stats['target_count'] * 100
                                            if stats['target_count'] > 0 else 0
                                        )
                                        notify_msg = (
                                            f"[분봉 확대 수집 완료]\n"
                                            f"대상: {stats['target_count']}종목 "
                                            f"(스킵 {stats['skipped']})\n"
                                            f"성공: {stats['collected']}건 ({success_rate:.0f}%)\n"
                                            f"실패: {stats['failed']}건\n"
                                            f"소요: {stats['elapsed_sec']:.0f}초"
                                        )
                                        await self.telegram.notify_system_status(notify_msg)
                                except Exception as te:
                                    self.logger.debug(f"텔레그램 알림 실패: {te}")
                            except Exception as e:
                                self.logger.error(f"❌ 분봉 확대 수집 실패: {e}")
                            expanded_minute_saved_date = current_date

                # 장마감 청산 로직 제거: 15:00 시장가 매도로 대체됨
                
                # 🆕 차트 생성 카운터 매일 리셋 (주석처리)
                # current_date = current_time.date()
                # if current_date != last_chart_reset_date:
                #     chart_generation_count = 0  # 새로운 날이면 카운터 리셋
                #     last_chart_reset_date = current_date
                #     self.logger.info(f"📅 새로운 날 - 차트 생성 카운터 리셋 ({current_date})")

                # 🆕 장 마감 후 차트 생성 (16:00~24:00 시간대에 실행) - 주석처리
                # current_hour = current_time.hour
                # is_chart_time = (16 <= current_hour <= 23) and current_time.weekday() < 5  # 평일 16~24시
                # if is_chart_time and chart_generation_count < 2:  # 16~24시 시간대에만, 최대 2번
                #     if (current_time - last_chart_generation).total_seconds() >= 1 * 60:  # 1분 간격으로 체크
                #         #self.logger.info(f"🔥 DEBUG: 차트 생성 실행 시작 ({chart_generation_count + 1}/2)")  # 디버깅용
                #         await self._generate_post_market_charts()
                #         #self.logger.info(f"🔥 DEBUG: 차트 생성 실행 완료 ({chart_generation_count + 1}/2)")  # 디버깅용
                #         last_chart_generation = current_time
                #         chart_generation_count += 1
                #
                #         if chart_generation_count >= 1:
                #             self.logger.info("✅ 장 마감 후 차트 생성 완료 (1회 실행 완료)")
                
                # 시스템 모니터링 루프 대기 (5초 주기)
                await asyncio.sleep(5)  
                
                # 30분마다 시스템 상태 로깅
                if (current_time - last_market_check).total_seconds() >= 30 * 60:  # 30분
                    await self._log_system_status()
                    last_market_check = current_time

                # 장중 지수 모니터링 (30분 주기, 09:30~ 장중에만)
                from config.strategy_settings import StrategySettings
                pm_cfg = StrategySettings.PreMarket
                if (pm_cfg.INTRADAY_INDEX_CHECK_ENABLED and
                        is_market_open() and
                        current_time.hour >= 9 and current_time.minute >= 30 and
                        (current_time - last_intraday_index_check).total_seconds() >= pm_cfg.INTRADAY_INDEX_CHECK_INTERVAL_MINUTES * 60):
                    last_intraday_index_check = current_time
                    try:
                        loop = asyncio.get_event_loop()
                        updated_report = await loop.run_in_executor(
                            None, self.pre_market_analyzer.check_intraday_index
                        )
                        if updated_report:
                            self.decision_engine.set_pre_market_report(updated_report)
                            status = updated_report.market_sentiment
                            max_pos = updated_report.recommended_max_positions
                            self.logger.info(
                                f"[장중지수] 리포트 업데이트: {status}, 포지션={max_pos}"
                            )
                            # 텔레그램 알림 (서킷브레이커 발동/해제 시)
                            msg = (
                                f"[장중지수 모니터링]\n"
                                f"상태: {status.upper()}, 최대포지션: {max_pos}\n"
                                f"{updated_report.log_lines[0] if updated_report.log_lines else ''}"
                            )
                            await self.telegram.notify_system_status(msg)
                    except Exception as e:
                        self.logger.error(f"[장중지수] 체크 오류: {e}")
                
        except Exception as e:
            self.logger.error(f"❌ 시스템 모니터링 태스크 오류: {e}")
            # 텔레그램 오류 알림
            await self.telegram.notify_error("SystemMonitoring", e)

    async def _liquidate_all_positions_end_of_day(self):
        """장 마감 직전 보유 포지션 전량 시장가 일괄 청산"""
        try:
            from core.models import StockState
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            
            # 실제 매매 모드: 실제 포지션만 처리
            if not positioned_stocks:
                self.logger.info("📦 장마감 일괄청산: 보유 포지션 없음")
                return
                
            self.logger.info(f"🛎️ 장마감 일괄청산 시작: {len(positioned_stocks)}종목")
            
            # 실제 포지션 매도
            for trading_stock in positioned_stocks:
                try:
                    if not trading_stock.position or trading_stock.position.quantity <= 0:
                        continue
                    stock_code = trading_stock.stock_code
                    quantity = int(trading_stock.position.quantity)
                    # 가격 산정: 가능한 경우 최신 분봉 종가, 없으면 현재가 조회
                    sell_price = 0.0
                    combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                    if combined_data is not None and len(combined_data) > 0:
                        sell_price = float(combined_data['close'].iloc[-1])
                    else:
                        price_obj = self.api_manager.get_current_price(stock_code)
                        if price_obj:
                            sell_price = float(price_obj.current_price)
                    sell_price = self._round_to_tick(sell_price)
                    # 상태 전환 후 시장가 매도 주문 실행
                    moved = await self.trading_manager.move_to_sell_candidate(stock_code, "장마감 일괄청산")
                    if moved:
                        await self.trading_manager.execute_sell_order(
                            stock_code, quantity, sell_price, "장마감 일괄청산", market=True
                        )
                        self.logger.info(
                            f"🧹 장마감 청산 주문: {stock_code} {quantity}주 시장가 @{sell_price:,.0f}원"
                        )
                except Exception as se:
                    self.logger.error(f"❌ 장마감 청산 개별 처리 오류({trading_stock.stock_code}): {se}")
            
            # 가상 포지션 매도 처리 제거 (실제 매매 모드)
            
            self.logger.info("✅ 장마감 일괄청산 요청 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 장마감 일괄청산 오류: {e}")
    
    async def _macd_cross_exit_dispatcher(self):
        """macd_cross 청산 dispatcher — virtual/real 모드 분기.

        모드 매트릭스 (`_macd_cross_mode`):
          - 'virtual': `_macd_cross_paper_exit_task` (virtual_trading_records)
          - 'real'   : `_macd_cross_live_exit_task` (real_trading_records + KIS 시장가)
          - 'off'    : no-op
        """
        mode = self._macd_cross_mode()
        if mode == 'virtual':
            await self._macd_cross_paper_exit_task()
        elif mode == 'real':
            await self._macd_cross_live_exit_task()

    async def _macd_cross_live_exit_task(self):
        """macd_cross 실거래 포지션 hold_days=2 만료 시장가 청산.

        - real_trading_records 에서 strategy='macd_cross' AND 미매칭 BUY 조회
        - KRX 영업일 기준 hold_days >= HOLD_DAYS=2 인 종목 시장가 매도
        - trading_manager.execute_sell_order(market=True) 경유 (price=0)
        - D+2 morning(09:01~05) + EOD(15:00 직후) 양쪽 트리거 → idempotent
          (체결 시 SELL 레코드 자동 저장 → 다음 호출 시 미매칭 제외)
        """
        try:
            from config.strategy_settings import StrategySettings
            from datetime import datetime
            from core.models import StockState
            cfg = StrategySettings.MacdCross

            rows = self.db_manager.get_open_real_buys_by_strategy('macd_cross')
            if not rows:
                return

            today = now_kst().date()
            for row in rows:
                stock_code = row['stock_code']
                quantity = row['quantity']
                buy_ts = row['timestamp']

                # 영업일 기준 hold_days
                if hasattr(buy_ts, 'date'):
                    buy_date = buy_ts.date()
                else:
                    buy_date = datetime.strptime(str(buy_ts)[:10], '%Y-%m-%d').date()
                days_held = self._count_krx_trading_days_between(buy_date, today)
                if days_held < cfg.HOLD_DAYS:
                    continue

                # trading_manager 상태 확인 (재시작 후 emergency_sync 미완 시 skip)
                ts = self.trading_manager.get_trading_stock(stock_code)
                if ts is None:
                    self.logger.warning(
                        f"[macd_cross.live.exit] {stock_code} trading_stock 미등록 → skip (다음 사이클 재시도)"
                    )
                    continue
                if ts.state == StockState.POSITIONED:
                    moved = await self.trading_manager.move_to_sell_candidate(
                        stock_code, f"macd_cross hold_limit_days={days_held}"
                    )
                    if not moved:
                        self.logger.debug(
                            f"[macd_cross.live.exit] {stock_code} move_to_sell_candidate 실패 → skip"
                        )
                        continue
                elif ts.state != StockState.SELL_CANDIDATE:
                    # BUY_PENDING / SELL_PENDING / FAILED 등은 skip (다음 사이클 재평가)
                    self.logger.debug(
                        f"[macd_cross.live.exit] {stock_code} 상태={ts.state.value} → skip"
                    )
                    continue

                ok = await self.trading_manager.execute_sell_order(
                    stock_code, quantity, 0.0,
                    f"macd_cross hold_limit_days={days_held}", market=True,
                )
                if ok:
                    self.logger.info(
                        f"🔥 [macd_cross.live] 시장가 청산 주문: {stock_code} {quantity}주 "
                        f"(hold {days_held}d)"
                    )
                else:
                    self.logger.warning(
                        f"⚠️ [macd_cross.live] 청산 주문 실패: {stock_code} {quantity}주"
                    )
        except Exception as e:
            self.logger.error(f"❌ macd_cross live exit 실패: {e}")

    async def _macd_cross_paper_exit_task(self):
        """macd_cross 가상 포지션 hold_days=2 만료 청산.

        Fix B (2026-04-26): 청산 시점을 D2 장 시작 직후 (~09:01~05) 로 이동 — backtest
        의 exit_signal 이 D2 첫 분봉에서 fire 하는 것과 동등. EOD (15:00) 후에도
        한 번 더 호출되어 morning 트리거 실패 대비 안전망. save_virtual_sell 의
        dup-prevention (buy_record_id × action='SELL' 중복 차단) 으로 idempotent.

        Fix A 적용: 백테스트 마찰 동등 — sell_eff = current * (1 - SLIPPAGE) * (1 - SELL_COMMISSION)
        Fix C 적용: 하한가 buffer 위반 종목은 skip
        """
        try:
            from config.strategy_settings import StrategySettings
            from datetime import datetime
            from backtests.common.execution_model import (
                SELL_COMMISSION, SLIPPAGE_ONE_WAY, ExecutionModel,
            )

            cfg = StrategySettings.MacdCross
            df = self.db_manager.get_virtual_open_positions()
            if df is None or df.empty:
                return
            df_mc = df[df['strategy'] == 'macd_cross']
            if df_mc.empty:
                return

            strategy = self.decision_engine.macd_cross_strategy
            today = now_kst().date()
            for _, row in df_mc.iterrows():
                buy_time = row['buy_time']
                if isinstance(buy_time, str):
                    buy_dt = datetime.strptime(buy_time, "%Y-%m-%d %H:%M:%S")
                else:
                    buy_dt = buy_time
                days_held = self._count_krx_trading_days_between(buy_dt.date(), today)
                if days_held < cfg.HOLD_DAYS:
                    continue

                stock_code = row['stock_code']
                stock_name = row['stock_name']
                buy_record_id = int(row['id'])
                quantity = int(row['quantity'])

                # 현재가 (intraday_manager 캐시 — 09:01~05 morning 트리거 시점에 활성)
                price_info = self.intraday_manager.get_cached_current_price(stock_code)
                if not price_info:
                    self.logger.warning(f"[macd_cross.exit] {stock_code} 가격 없음 → skip")
                    continue
                current_price = float(price_info.get('current_price', 0))
                if current_price <= 0:
                    continue

                # Fix C: 하한가 buffer 체크 (sell side)
                prev_close, _ = (
                    strategy.get_daily_meta(stock_code) if strategy is not None else (None, None)
                )
                if prev_close and not ExecutionModel.is_price_limit_safe(
                    current_price, prev_close, side="sell"
                ):
                    self.logger.debug(
                        f"[macd_cross.exit] {stock_code} 하한가 buffer 위반 → skip (다음 사이클 재시도)"
                    )
                    continue

                # Fix A: 매도 슬리피지 + 수수료/세금 적용 (backtest 동등)
                #   sell_eff = current * (1 - SLIPPAGE) * (1 - SELL_COMMISSION)
                #   pnl = (sell_eff - buy_eff) * qty 가 backtest proceed-cost 와 일치
                sell_fill = current_price * (1 - SLIPPAGE_ONE_WAY)
                sell_price_effective = sell_fill * (1 - SELL_COMMISSION)

                ok = self.db_manager.save_virtual_sell(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=sell_price_effective,
                    quantity=quantity,
                    strategy='macd_cross',
                    reason=f"hold_limit_days={days_held}",
                    buy_record_id=buy_record_id,
                )
                if ok:
                    self.logger.info(
                        f"👻 [macd_cross] 가상 청산: {stock_code} {quantity}주 "
                        f"@{sell_price_effective:,.0f} (mid={current_price:,.0f}, hold {days_held}d)"
                    )
                else:
                    self.logger.warning(
                        f"⚠️ [macd_cross] 가상 청산 DB 저장 실패: {stock_code}"
                    )
        except Exception as e:
            self.logger.error(f"❌ macd_cross paper exit 실패: {e}")

    async def _macd_cross_paper_daily_report(self):
        """macd_cross 페이퍼 일일 KPI 집계 + 텔레그램 알림 + safety stop 체크.

        EOD 직후 (paper exit 끝난 다음) 1회 호출. KPI 계산은 KPI 모듈
        (core.strategies.macd_cross_kpi.MacdCrossKpi) 에 위임.
        """
        try:
            from config.strategy_settings import StrategySettings
            from core.strategies.macd_cross_kpi import MacdCrossKpi

            cfg = StrategySettings.MacdCross
            kpi = MacdCrossKpi(virtual_capital=cfg.VIRTUAL_CAPITAL)

            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                None,
                lambda: self.db_manager.get_virtual_paired_trades(strategy='macd_cross'),
            )

            metrics = kpi.compute(df) if df is not None else kpi.compute(pd.DataFrame())
            gates = kpi.evaluate_gates(metrics)
            safety = kpi.should_safety_stop(metrics)

            target_trades = 30  # paper 종료 조건
            progress_pct = (metrics['trade_count'] / target_trades * 100) if target_trades else 0

            lines = [
                "📊 macd_cross 페이퍼 일일 보고",
                f"진행: {metrics['trade_count']} trades / {progress_pct:.0f}% (목표 {target_trades})",
                f"return: {metrics['return']*100:+.2f}% | MDD: {metrics['mdd']*100:+.2f}% | win: {metrics['win_rate']*100:.1f}%",
                f"Calmar: {metrics['calmar']:.1f} | top1: {metrics['top1_share']*100:.1f}% | streak: {metrics['max_consec_losses']}",
                "—",
                f"게이트: {sum(1 for g in gates['gates'].values() if g['pass'])}/6 통과",
            ]
            for k, g in gates["gates"].items():
                mark = "✓" if g["pass"] else "✗"
                # value 포맷: 비율은 %, 정수는 그대로
                if k in ('return', 'mdd', 'win_rate', 'top1_share'):
                    val_str = f"{g['value']*100:.2f}%"
                elif k == 'calmar':
                    val_str = f"{g['value']:.1f}"
                else:
                    val_str = str(g['value'])
                lines.append(f"  {mark} {g['label']} → {val_str}")
            if safety:
                lines.append("⚠️ SAFETY STOP 충족 — paper 즉시 중단 권고. PAPER_STRATEGY=None 으로 설정.")

            msg = "\n".join(lines)
            if self.telegram is not None:
                try:
                    await self.telegram.notify_system_status(msg)
                except Exception as e:
                    self.logger.warning(f"[macd_cross.report] 텔레그램 전송 실패: {e}")
            self.logger.info(msg)
        except Exception as e:
            self.logger.error(f"❌ macd_cross 일일 보고 실패: {e}")

    async def _execute_end_of_day_liquidation(self):
        """장마감 시간 모든 보유 종목 시장가 일괄매도 (동적 시간 적용).

        macd_cross 분기:
          - paper (PAPER_STRATEGY='macd_cross'): 가상 포지션 자연 격리 (trading_manager 등록 안 됨)
          - live  (ACTIVE_STRATEGY='macd_cross', VIRTUAL_ONLY=False):
              days_held < HOLD_DAYS=2 인 포지션 스킵 → D+2 morning exit 가 청산
        """
        try:
            from config.strategy_settings import StrategySettings
            from core.models import StockState

            # 동적 청산 시간 가져오기
            current_time = now_kst()
            market_hours = MarketHours.get_market_hours('KRX', current_time)
            eod_hour = market_hours['eod_liquidation_hour']
            eod_minute = market_hours['eod_liquidation_minute']

            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            sell_candidate_stocks = self.trading_manager.get_stocks_by_state(StockState.SELL_CANDIDATE)
            all_liquidation_targets = positioned_stocks + sell_candidate_stocks

            # 🆕 macd_cross 페이퍼 포지션은 EOD 강제청산에서 격리 (Spec §5)
            # paper 가상 포지션은 hold_days=2 만료 시 별도 경로로 청산되며
            # 라이브 EOD 흐름에 들어오지 않아야 한다. trading_manager 에 가상매매
            # 포지션이 등록되지 않아 자연 격리되지만, 방어적으로 필터링.
            try:
                from config.strategy_settings import StrategySettings
                if (
                    StrategySettings.PAPER_STRATEGY == 'macd_cross'
                    and all_liquidation_targets
                ):
                    paper_codes = self._get_macd_cross_paper_open_codes()
                    if paper_codes:
                        before = len(all_liquidation_targets)
                        all_liquidation_targets = [
                            ts for ts in all_liquidation_targets
                            if ts.stock_code not in paper_codes
                        ]
                        excluded = before - len(all_liquidation_targets)
                        if excluded > 0:
                            self.logger.info(
                                f"🌙 macd_cross paper 포지션 EOD 격리: {excluded}종목 "
                                f"(hold_days=2 만료 전까지 유지)"
                            )
            except Exception as e:
                self.logger.warning(f"⚠️ macd_cross EOD 격리 실패: {e} — 정상 청산 진행")

            # 🆕 macd_cross 실거래 포지션 EOD 격리 (D+2 까지 보유)
            # ACTIVE_STRATEGY='macd_cross' AND VIRTUAL_ONLY=False 일 때만 동작.
            # trading_stock.strategy_tag == 'macd_cross' 로 식별 (P1-3 propagation).
            # days_held < HOLD_DAYS=2 인 포지션 skip → 익일 09:01~05 morning exit 가 청산.
            try:
                from config.strategy_settings import StrategySettings
                if (
                    StrategySettings.ACTIVE_STRATEGY == 'macd_cross'
                    and not StrategySettings.MacdCross.VIRTUAL_ONLY
                    and all_liquidation_targets
                ):
                    import numpy as np
                    max_days = StrategySettings.MacdCross.HOLD_DAYS
                    today = current_time.date()
                    held_over = []
                    to_close = []
                    for ts in all_liquidation_targets:
                        tag = getattr(ts, 'strategy_tag', None)
                        if tag != 'macd_cross':
                            to_close.append(ts)
                            continue
                        buy_time = getattr(ts, 'buy_time', None)
                        if buy_time is None:
                            # 매수 시각 미상 → 보수적으로 청산
                            to_close.append(ts)
                            continue
                        days_held = int(np.busday_count(buy_time.date(), today))
                        if days_held < max_days:
                            held_over.append((ts, days_held))
                        else:
                            to_close.append(ts)
                    if held_over:
                        self.logger.info(
                            f"🌙 macd_cross live overnight 보유: {len(held_over)}종목 "
                            f"(days < {max_days}): "
                            + ", ".join(f"{ts.stock_code}={d}/{max_days}" for ts, d in held_over[:10])
                        )
                    all_liquidation_targets = to_close
            except Exception as e:
                self.logger.warning(f"⚠️ macd_cross live EOD 격리 실패: {e} — 정상 청산 진행")

            if not all_liquidation_targets:
                self.logger.info(f"📦 {eod_hour}:{eod_minute:02d} 시장가 매도: 청산 대상 포지션 없음")
                return

            self.logger.info(f"🚨 {eod_hour}:{eod_minute:02d} 시장가 일괄매도 시작: {len(all_liquidation_targets)}종목 (POSITIONED={len(positioned_stocks)}, SELL_CANDIDATE={len(sell_candidate_stocks)})")

            # 모든 보유 종목 시장가 매도
            for trading_stock in all_liquidation_targets:
                try:
                    if not trading_stock.position or trading_stock.position.quantity <= 0:
                        continue

                    stock_code = trading_stock.stock_code
                    stock_name = trading_stock.stock_name
                    quantity = int(trading_stock.position.quantity)

                    # 시장가 매도를 위해 현재가 조회 (시장가는 가격 0으로 주문)
                    current_price = 0.0  # 시장가는 0원으로 주문

                    # 상태를 매도 대기로 변경 후 시장가 매도 주문
                    # SELL_CANDIDATE는 이미 매도 후보 상태이므로 move 불필요
                    if trading_stock.state == StockState.SELL_CANDIDATE:
                        moved = True
                    else:
                        moved = await self.trading_manager.move_to_sell_candidate(stock_code, f"{eod_hour}:{eod_minute:02d} 시장가 일괄매도")
                    if moved:
                        await self.trading_manager.execute_sell_order(
                            stock_code, quantity, current_price, f"{eod_hour}:{eod_minute:02d} 시장가 일괄매도", market=True
                        )
                        self.logger.info(f"🚨 {eod_hour}:{eod_minute:02d} 시장가 매도: {stock_code}({stock_name}) {quantity}주 시장가 주문")

                except Exception as se:
                    self.logger.error(f"❌ {eod_hour}:{eod_minute:02d} 시장가 매도 개별 처리 오류({trading_stock.stock_code}): {se}")

            # 가상 포지션 처리 제거 (실제 매매 모드)

            self.logger.info(f"✅ {eod_hour}:{eod_minute:02d} 시장가 일괄매도 요청 완료")

        except Exception as e:
            self.logger.error(f"❌ 장마감 시장가 매도 오류: {e}")

    async def _log_system_status(self):
        """시스템 상태 로깅"""
        try:
            current_time = now_kst()
            market_status = get_market_status()
            
            # 주문 요약
            order_summary = self.order_manager.get_order_summary()
            
            # 데이터 수집 상태
            candidate_stocks = self.data_collector.get_candidate_stocks()
            data_counts = {stock.code: len(stock.ohlcv_data) for stock in candidate_stocks}
            
            self.logger.info(
                f"📊 시스템 상태 [{current_time.strftime('%H:%M:%S')}]\n"
                f"  - 시장 상태: {market_status}\n"
                f"  - 미체결 주문: {order_summary['pending_count']}건\n"
                f"  - 완료 주문: {order_summary['completed_count']}건\n"
                f"  - 데이터 수집: {data_counts}"
            )
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 상태 로깅 오류: {e}")
    
    async def _refresh_api(self):
        """API 재초기화"""
        try:
            self.logger.info("🔄 API 24시간 주기 재초기화 시작")
            
            # API 매니저 재초기화
            if not self.api_manager.initialize():
                self.logger.error("❌ API 재초기화 실패")
                await self.telegram.notify_error("API Refresh", "API 재초기화 실패")
                return False
                
            self.logger.info("✅ API 재초기화 완료")
            await self.telegram.notify_system_status("API 재초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ API 재초기화 오류: {e}")
            await self.telegram.notify_error("API Refresh", e)
            return False
    
    async def _restore_todays_candidates(self):
        """DB에서 오늘 날짜의 후보 종목 복원"""
        try:
            # 오늘 날짜
            today = now_kst().strftime('%Y-%m-%d')
            
            # PostgreSQL에서 조회 (connection pool 사용)
            rows = self.db_manager._fetchall('''
                SELECT DISTINCT stock_code, stock_name, score, reasons 
                FROM candidate_stocks 
                WHERE CAST(selection_date AS DATE) = %s
                ORDER BY score DESC
            ''', (today,))
            
            if not rows:
                self.logger.info(f"📊 오늘({today}) 후보 종목 없음")
                return
            
            self.logger.info(f"🔄 오늘({today}) 후보 종목 {len(rows)}개 복원 시작")
            
            restored_count = 0
            skipped_condition = 0
            for row in rows:
                stock_code = row[0]
                stock_name = row[1] or f"Stock_{stock_code}"
                score = row[2] or 0.0
                reason = row[3] or "DB 복원"

                # 과거 조건검색(HTS) 종목 건너뛰기 — 스크리너 선정 종목만 복원
                if reason and '조건검색' in reason:
                    skipped_condition += 1
                    continue

                # 전날 종가 조회
                prev_close = 0.0
                try:
                    daily_data = self.api_manager.get_ohlcv_data(stock_code, "D", 7)
                    if daily_data is not None and len(daily_data) >= 2:
                        if hasattr(daily_data, 'iloc'):
                            daily_data = daily_data.sort_values('stck_bsop_date')
                            last_date = daily_data.iloc[-1]['stck_bsop_date']
                            if isinstance(last_date, str):
                                from datetime import datetime
                                last_date = datetime.strptime(last_date, '%Y%m%d').date()
                            elif hasattr(last_date, 'date'):
                                last_date = last_date.date()
                            
                            if last_date == now_kst().date() and len(daily_data) >= 2:
                                prev_close = float(daily_data.iloc[-2]['stck_clpr'])
                            else:
                                prev_close = float(daily_data.iloc[-1]['stck_clpr'])
                except Exception as e:
                    self.logger.debug(f"⚠️ {stock_code} 전날 종가 조회 실패: {e}")
                
                # 거래 상태 관리자에 추가
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selection_reason=f"DB복원: {reason} (점수: {score})",
                    prev_close=prev_close
                )
                
                if success:
                    restored_count += 1
            
            if skipped_condition > 0:
                self.logger.info(f"✅ 오늘 후보 종목 {restored_count}/{len(rows)}개 복원 완료 (조건검색 {skipped_condition}개 제외)")
            else:
                self.logger.info(f"✅ 오늘 후보 종목 {restored_count}/{len(rows)}개 복원 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 오늘 후보 종목 복원 실패: {e}")

    async def _late_start_macd_cross_recovery(self):
        """장중 재시작 시 macd_cross universe + daily history prep 1회 트리거.

        정상 경로는 `_pre_market_task` 내 08:55 분기에서 실행되는데,
        09:00 이후 봇 시작 시 NXT 프리마켓 시간 가드에 막혀 영영 트리거되지 않음.
        macd_cross 가 active 또는 paper 모드일 때 1회 보강 (진입창 15:00 까지 의미 있음).
        """
        try:
            if self._macd_cross_mode() == 'off':
                return
            if self.decision_engine.macd_cross_strategy is None:
                return
            now = now_kst()
            t = now.hour * 60 + now.minute
            # 08:55 ~ 15:00 사이 (진입창 마감까지). 그 이후는 prep 무의미.
            if t < (8 * 60 + 55) or t >= (15 * 60):
                return
            self.logger.info("[macd_cross] 장중 재시작 감지 — universe 준비 1회 트리거")
            await self._prepare_macd_cross_universe(now)
        except Exception as e:
            self.logger.error(f"❌ [macd_cross] 장중 재시작 prep 실패: {e}")

    async def _restore_pre_market_report(self):
        """장중 재시작 시 DB에서 당일 프리마켓 리포트 복원"""
        try:
            now = now_kst()
            # 09:00 이전이면 복원 불필요 — 정상 프리마켓 루틴이 실행됨
            if now.hour < 9:
                return

            trade_date = now.strftime('%Y%m%d')
            data = self.db_manager.get_today_nxt_report(trade_date)
            if not data:
                self.logger.info("[프리마켓] DB에 당일 리포트 없음 — 복원 건너뜀")
                return

            from core.pre_market_analyzer import PreMarketReport
            report = PreMarketReport(
                report_time=now,
                market_sentiment=data['market_sentiment'],
                sentiment_score=data['sentiment_score'],
                gap_direction='flat',
                expected_gap_pct=data['expected_gap_pct'],
                volatility_level='normal',
                recommended_max_positions=data['recommended_max_positions'],
                recommended_stop_loss_pct=0.05,
                recommended_take_profit_pct=0.06,
                nxt_available=True,
            )
            self.decision_engine.set_pre_market_report(report)
            self.logger.info(
                f"[프리마켓] DB에서 리포트 복원: "
                f"sentiment={data['market_sentiment']}, "
                f"max_positions={data['recommended_max_positions']}"
            )
        except Exception as e:
            self.logger.error(f"❌ 프리마켓 리포트 복원 실패: {e}")

    async def _run_stock_screener(self):
        """장중 실시간 종목 스크리닝"""
        try:
            # 스크리너 실행 (동기 → run_in_executor로 비동기 래핑)
            loop = asyncio.get_event_loop()
            screened_stocks = await loop.run_in_executor(
                None, self.stock_screener.scan
            )

            if not screened_stocks:
                return

            self.logger.info(
                f"[스크리너] {len(screened_stocks)}개 종목 발견, 거래 풀 추가 시작"
            )

            candidates_to_save = []
            for stock in screened_stocks:
                if not stock.code:
                    continue

                # 전날 종가 조회 (기존 패턴 재사용)
                prev_close = 0.0
                try:
                    daily_data = self.api_manager.get_ohlcv_data(
                        stock.code, "D", 7
                    )
                    if daily_data is not None and len(daily_data) >= 2:
                        if hasattr(daily_data, 'iloc'):
                            daily_data = daily_data.sort_values('stck_bsop_date')
                            last_date = daily_data.iloc[-1]['stck_bsop_date']
                            if isinstance(last_date, str):
                                last_date = datetime.strptime(
                                    last_date, '%Y%m%d'
                                ).date()
                            elif hasattr(last_date, 'date'):
                                last_date = last_date.date()
                            if (last_date == now_kst().date()
                                    and len(daily_data) >= 2):
                                prev_close = float(
                                    daily_data.iloc[-2]['stck_clpr']
                                )
                            else:
                                prev_close = float(
                                    daily_data.iloc[-1]['stck_clpr']
                                )
                except Exception as e:
                    self.logger.debug(
                        f"[스크리너] {stock.code} 전날 종가 조회 실패: {e}"
                    )

                # 거래 상태 관리자에 추가
                selection_reason = (
                    f"스크리너: {stock.reason}"
                )
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock.code,
                    stock_name=stock.name,
                    selection_reason=selection_reason,
                    prev_close=prev_close
                )

                if success:
                    self.stock_screener.mark_stock_added(stock.code)
                    candidates_to_save.append(
                        CandidateStock(
                            code=stock.code,
                            name=stock.name,
                            market=stock.market,
                            score=stock.score,
                            reason=selection_reason
                        )
                    )

            # 후보 종목 DB 저장
            if candidates_to_save:
                try:
                    self.db_manager.save_candidate_stocks(candidates_to_save)
                    self.logger.info(
                        f"[스크리너] 후보 종목 DB 저장 완료: "
                        f"{len(candidates_to_save)}건"
                    )
                except Exception as db_err:
                    self.logger.error(
                        f"[스크리너] 후보 종목 DB 저장 오류: {db_err}"
                    )

        except Exception as e:
            self.logger.error(f"[스크리너] 스크리닝 오류: {e}")
            await self.telegram.notify_error("Stock Screener", e)

    async def _preload_stock_candidates(self):
        """전일 거래대금 상위 종목을 장 시작 전 프리로드

        시뮬 분석: 09:00 진입이 가장 수익률 높음 (전체 거래의 55%, 평균 +1.66%)
        기존 스크리너 첫 스캔 09:05 → 실제 진입 09:15+ → 최적 타이밍 놓침
        프리로드로 09:00 첫 분봉부터 매수 판단 가능
        """
        try:
            from core.candidate_selector import CandidateStock

            self.logger.info("[프리로드] 전일 상위 종목 프리로드 시작")

            # 🆕 E: _added_stocks 일일 리셋 (시뮬 screen_for_day_strict 과 정합 —
            # 매일 독립 pool. 전일 스크리너가 추가한 종목이 당일 프리로드에서 스킵되는 버그 방지)
            self.stock_screener.reset_daily_state()
            self.logger.info("[프리로드] _added_stocks 일일 리셋 완료")

            # 🆕 F: 전일 분봉 종목 수 체크 + 부족하면 백필 (ExpandedMinuteCollector 15:45 스킵 대비)
            try:
                from datetime import timedelta
                import psycopg2
                from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
                _ct = now_kst()
                _prev = _ct - timedelta(days=1)
                while _prev.weekday() >= 5:
                    _prev -= timedelta(days=1)
                _prev_date = _prev.strftime('%Y%m%d')
                with psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                                      user=PG_USER, password=PG_PASSWORD, connect_timeout=5) as _c:
                    with _c.cursor() as _cur:
                        _cur.execute(
                            "SELECT COUNT(DISTINCT stock_code) FROM minute_candles WHERE trade_date=%s",
                            [_prev_date],
                        )
                        _cnt = int(_cur.fetchone()[0] or 0)
                if _cnt < 200:
                    self.logger.warning(
                        f"⚠ 전일({_prev_date}) 분봉 종목 수 {_cnt}개 < 200 → 백필 트리거"
                    )
                    from core.expanded_minute_collector import ExpandedMinuteCollector
                    _collector = ExpandedMinuteCollector(logger=self.logger)
                    await _collector.run_async(target_date=_prev_date, top_n=300)
                    self.logger.info(f"📦 전일({_prev_date}) 분봉 백필 완료")
                else:
                    self.logger.info(f"✓ 전일({_prev_date}) 분봉 종목 수 {_cnt}개 확인")
            except Exception as _be:
                self.logger.warning(f"⚠ 전일 분봉 백필 체크 실패: {_be}")

            preload_top_n = 30

            loop = asyncio.get_event_loop()
            preloaded = await loop.run_in_executor(
                None, self.stock_screener.preload_previous_day_stocks, preload_top_n
            )

            if not preloaded:
                self.logger.info("[프리로드] 프리로드 대상 종목 없음")
                return

            added_count = 0
            candidates_to_save = []
            for stock in preloaded:
                if not stock.code:
                    continue

                # 전날 종가 = 프리로드 시 current_price에 저장해둔 값
                prev_close = float(stock.current_price) if stock.current_price else 0.0

                selection_reason = f"프리로드: {stock.reason}"
                success = await self.trading_manager.add_selected_stock(
                    stock_code=stock.code,
                    stock_name=stock.name,
                    selection_reason=selection_reason,
                    prev_close=prev_close
                )

                if success:
                    self.stock_screener.mark_stock_added(stock.code)
                    added_count += 1
                    candidates_to_save.append(
                        CandidateStock(
                            code=stock.code,
                            name=stock.name,
                            market=stock.market,
                            score=stock.score,
                            reason=selection_reason
                        )
                    )

            # DB 저장
            if candidates_to_save:
                try:
                    self.db_manager.save_candidate_stocks(candidates_to_save)
                except Exception as db_err:
                    self.logger.error(f"[프리로드] DB 저장 오류: {db_err}")

            self.logger.info(f"[프리로드] {added_count}개 종목 거래 풀 추가 완료")

        except Exception as e:
            self.logger.error(f"[프리로드] 오류: {e}")

    async def _update_intraday_data(self):
        """장중 종목 실시간 데이터 업데이트 + 매수 판단 실행 (완성된 분봉만 수집)"""
        try:
            from utils.korean_time import now_kst
            from core.data_reconfirmation import reconfirm_intraday_data
            current_time = now_kst()

            # 🆕 완성된 봉만 수집하는 것을 로깅
            #self.logger.debug(f"🔄 실시간 데이터 업데이트 시작: {current_time.strftime('%H:%M:%S')} "
            #                f"(모든 관리 종목 - 재거래 대응)")

            # 모든 관리 종목의 실시간 데이터 업데이트 (재거래를 위해 COMPLETED, FAILED 상태도 포함)
            await self.intraday_manager.batch_update_realtime_data()

            # 데이터 수집 후 0.3초 대기 (reconfirm이 2차 검증하므로 최소 대기)
            await asyncio.sleep(0.3)

            # 🆕 최근 3분 데이터 재확인 (volume=0 but price changed 감지 및 재조회)
            updated_stocks = await reconfirm_intraday_data(
                self.intraday_manager,
                minutes_back=3
            )
            if updated_stocks:
                self.logger.info(f"🔄 데이터 재확인 완료: {len(updated_stocks)}개 종목 업데이트됨")

            # n분봉 완성 + 3초 후 시점 체크 (전략 설정 기반)
            from config.strategy_settings import get_candle_interval
            candle_interval = get_candle_interval()

            minute_in_cycle = current_time.minute % candle_interval
            current_second = current_time.second

            # n분봉 사이클의 첫 번째 분이고 5초 이후일 때만 매수 판단
            # 기존 10초 → 5초: 슬리피지 감소 + 데이터 안정성 균형
            is_candle_completed = (minute_in_cycle == 0 and current_second >= 5)

            if not is_candle_completed:
                self.logger.debug(f"⏱️ {candle_interval}분봉 미완성 또는 5초 미경과: {current_time.strftime('%H:%M:%S')} - 매수 판단 건너뜀")
                return

            # 🆕 macd_cross 진입 평가 — should_stop_buy 게이트 우회 (G1: 14:31~15:00 진입창)
            # virtual/real 모드 분기는 _evaluate_macd_cross_window 내부 _macd_cross_mode() 가 결정.
            try:
                await self._evaluate_macd_cross_window(current_time)
            except Exception as e:
                self.logger.error(f"❌ macd_cross 평가 트리거 실패: {e}")

            # 데이터 업데이트 직후 매수 판단 실행
            # 매수 중단 시간 전이고 SELECTED/COMPLETED 상태 종목만 매수 판단 - 동적 시간 적용
            should_stop_buy = MarketHours.should_stop_buying('KRX', current_time)

            if not should_stop_buy:

                # 가용 자금 계산
                loop = asyncio.get_event_loop()
                balance_info = await loop.run_in_executor(None, self.api_manager.get_account_balance)
                if balance_info:
                    self.fund_manager.update_total_funds(float(balance_info.account_balance))

                fund_status = self.fund_manager.get_status()
                available_funds = fund_status['available_funds']

                # SELECTED + COMPLETED 상태 종목 가져오기
                selected_stocks = self.trading_manager.get_stocks_by_state(StockState.SELECTED)
                completed_stocks = self.trading_manager.get_stocks_by_state(StockState.COMPLETED)
                buy_candidates = selected_stocks + completed_stocks

                if buy_candidates:
                    self.logger.info(f"🎯 {candle_interval}분봉 완성 후 매수 판단 실행: {current_time.strftime('%H:%M:%S')} - {len(buy_candidates)}개 종목")

                    for trading_stock in buy_candidates:
                        await self._analyze_buy_decision(trading_stock, available_funds)

        except Exception as e:
            self.logger.error(f"❌ 장중 종목 실시간 데이터 업데이트 오류: {e}")
            await self.telegram.notify_error("Intraday Data Update", e)
    
    async def _generate_post_market_charts(self):
        """장 마감 후 선정 종목 차트 생성 (15:30 이후)"""
        try:
            # 차트 생성기 지연 초기화
            if self.chart_generator is None:
                self.chart_generator = PostMarketChartGenerator()
                if not self.chart_generator.initialize():
                    self.logger.error("❌ 차트 생성기 초기화 실패")
                    return
            
            # PostMarketChartGenerator의 통합 메서드 호출
            results = await self.chart_generator.generate_post_market_charts_for_intraday_stocks(
                intraday_manager=self.intraday_manager,
                telegram_integration=self.telegram
            )
            
            # 결과 로깅
            if results.get('success', False):
                success_count = results.get('success_count', 0)
                total_stocks = results.get('total_stocks', 0)
                self.logger.info(f"🎯 장 마감 후 차트 생성 완료: {success_count}/{total_stocks}개 성공")
            else:
                message = results.get('message', '알 수 없는 오류')
                self.logger.info(f"ℹ️ 장 마감 후 차트 생성: {message}")
            
        except Exception as e:
            self.logger.error(f"❌ 장 마감 후 차트 생성 오류: {e}")
            await self.telegram.notify_error("Post Market Chart Generation", e)

    async def emergency_sync_positions(self):
        """긴급 포지션 동기화 - 매수가 기준 3%/2% 고정 비율"""
        try:
            self.logger.debug("🔧 긴급 포지션 동기화 시작")

            # 실제 잔고 조회
            loop = asyncio.get_event_loop()
            balance = await loop.run_in_executor(
                None,
                self.api_manager.get_account_balance
            )
            if not balance or not balance.positions:
                self.logger.debug("📊 보유 종목 없음")
                return

            held_stocks = {p['stock_code']: p for p in balance.positions if p.get('quantity', 0) > 0}

            self.logger.debug(f"📊 실제 계좌 보유 종목: {list(held_stocks.keys())}")
            self.logger.debug(f"📊 시스템 관리 종목: {list(self.trading_manager.trading_stocks.keys())}")

            # 시스템에서 누락된 포지션 찾기
            missing_positions = []
            unmanaged_stocks = []
            for code, balance_stock in held_stocks.items():
                if code in self.trading_manager.trading_stocks:
                    ts = self.trading_manager.trading_stocks[code]
                    if ts.state != StockState.POSITIONED:
                        # BUY_PENDING/SELL_PENDING = 주문 진행 중 → 복구 금지
                        # current_order_id 유무와 무관하게 state만으로 판단
                        # (매도 API 호출 중 current_order_id가 일시적으로 None일 수 있음)
                        if ts.state in (StockState.BUY_PENDING, StockState.SELL_PENDING):
                            self.logger.debug(
                                f"⏳ {code}: {ts.state.value} 상태 - "
                                f"주문 처리 중, 복구 건너뜀 (order_id={ts.current_order_id})"
                            )
                            continue
                        missing_positions.append((code, balance_stock, ts))
                        self.logger.info(f"🔍 {code}: 보유중이지만 상태가 {ts.state.value} (복구 필요)")
                    else:
                        self.logger.info(f"✅ {code}: 정상 동기화됨 (상태: {ts.state.value})")
                else:
                    unmanaged_stocks.append((code, balance_stock))
                    self.logger.warning(f"⚠️ {code}: 보유중이지만 시스템에서 관리되지 않음")

            # 미관리 보유 종목을 시스템에 추가
            if unmanaged_stocks:
                self.logger.warning(f"🚨 미관리 보유 종목 발견: {[code for code, _ in unmanaged_stocks]}")
                for code, balance_stock in unmanaged_stocks:
                    try:
                        stock_name = balance_stock.get('stock_name', f'Stock_{code}')
                        quantity = balance_stock['quantity']
                        avg_price = balance_stock['avg_price']

                        self.logger.info(f"🔄 미관리 종목 시스템 추가: {code}({stock_name}) {quantity}주 @{avg_price:,.0f}")

                        # 거래 상태 관리자에 추가 (POSITIONED 상태로 즉시 설정)
                        success = await self.trading_manager.add_selected_stock(
                            stock_code=code,
                            stock_name=stock_name,
                            selection_reason=f"보유종목 자동복구 ({quantity}주 @{avg_price:,.0f})",
                            prev_close=avg_price  # 전날종가는 매수가로 대체
                        )

                        if success:
                            # 추가된 종목을 즉시 POSITIONED 상태로 설정
                            ts = self.trading_manager.get_trading_stock(code)
                            if ts:
                                # 🌙 entry_time 복원: DB의 실제 매수 시각 사용 (오버나이트 청산 안전화)
                                # — 락 밖에서 DB I/O 수행(락 블로킹 회피)
                                db_entry_time = None
                                try:
                                    from db.database_manager import DatabaseManager as _DBM
                                    db_entry_time = _DBM().get_open_buy_timestamp(code)
                                except Exception as e:
                                    self.logger.warning(f"⚠️ {code} DB timestamp 조회 예외: {e}")

                                # 🆕 strategy_tag 복원 (재시작 후 EOD overnight 격리 + macd_cross 식별)
                                db_strategy = None
                                try:
                                    from db.database_manager import DatabaseManager as _DBM
                                    db_strategy = _DBM().get_open_real_buy_strategy(code)
                                except Exception as e:
                                    self.logger.warning(f"⚠️ {code} DB strategy 조회 예외: {e}")

                                async with self.trading_manager._lock:
                                    ts.set_position(quantity, avg_price, entry_time=db_entry_time)
                                    ts.clear_current_order()
                                    ts.is_buying = False
                                    ts.order_processed = True
                                    if db_strategy:
                                        setattr(ts, 'strategy_tag', db_strategy)
                                    self.trading_manager._change_stock_state(code, StockState.POSITIONED,
                                        f"미관리종목 복구: {quantity}주 @{avg_price:,.0f}원")

                                self.logger.info(
                                    f"✅ {code} 미관리 종목 복구 완료 "
                                    f"(strategy_tag={db_strategy or '미상'})"
                                )

                                if db_entry_time is None:
                                    self.logger.warning(
                                        f"⚠️ {code} DB 미매칭 BUY 없음 → entry_time=now() 폴백 "
                                        f"(오버나이트 청산 시 당일 진입으로 오판 가능, 수동 확인 필요)"
                                    )
                                    try:
                                        await self.telegram.notify_error(
                                            "EntryTimeRestore",
                                            f"⚠️ {code} DB 미매칭 BUY 없음 — 수동 확인 필요"
                                        )
                                    except Exception:
                                        pass

                                # 매수 기록이 DB에 없으면 저장
                                try:
                                    from db.database_manager import DatabaseManager
                                    db = DatabaseManager()
                                    existing_buy = db.get_last_open_real_buy(code)
                                    if not existing_buy:
                                        db.save_real_buy(
                                            stock_code=code,
                                            stock_name=stock_name,
                                            price=float(avg_price),
                                            quantity=int(quantity),
                                            strategy="미관리종목복구",
                                            reason="긴급동기화"
                                        )
                                        self.logger.info(f"✅ {code} 매수 기록 보완 저장 (긴급동기화)")
                                except Exception as db_err:
                                    self.logger.warning(f"⚠️ {code} 매수 기록 보완 실패: {db_err}")

                                # missing_positions에도 추가하여 통합 처리
                                missing_positions.append((code, balance_stock, ts))

                    except Exception as e:
                        self.logger.error(f"❌ {code} 미관리 종목 복구 실패: {e}")

            if not missing_positions:
                self.logger.info("✅ 모든 포지션이 정상 동기화됨")
                return

            # 누락된 포지션들 복구
            for code, balance_stock, ts in missing_positions:
                # 이중 안전장치: 복구 시점에 주문 상태가 변경되었을 수 있음 (레이스 컨디션)
                # current_order_id 유무와 무관하게 state만으로 판단
                if ts.state in (StockState.BUY_PENDING, StockState.SELL_PENDING):
                    self.logger.info(
                        f"⏳ {code}: 복구 시점에 주문 처리 중 "
                        f"({ts.state.value}, order_id={ts.current_order_id}) - 복구 건너뜀"
                    )
                    continue

                # 🔧 서킷 브레이커: 같은 종목 3회 이상 복구 시 중단
                restore_count = self._sync_restore_count.get(code, 0)
                if restore_count >= 3:
                    self.logger.error(
                        f"🚨 {code} 서킷 브레이커 발동: {restore_count}회 복구 시도됨 - "
                        f"더 이상 복구하지 않음 (수동 확인 필요)"
                    )
                    # 텔레그램 긴급 알림
                    try:
                        await self.telegram.notify_error(
                            "CircuitBreaker",
                            f"🚨 {code} 서킷 브레이커 발동: {restore_count}회 복구 반복 - 수동 확인 필요"
                        )
                    except Exception:
                        pass
                    continue
                self._sync_restore_count[code] = restore_count + 1

                # 포지션 복원
                quantity = balance_stock['quantity']
                avg_price = balance_stock['avg_price']

                # 매수가 기준 고정 비율로 목표가격 계산 (로깅용 - config에서 읽기)
                buy_price = avg_price
                take_profit_ratio = self.config.risk_management.take_profit_ratio
                stop_loss_ratio = self.config.risk_management.stop_loss_ratio
                target_price = buy_price * (1 + take_profit_ratio)
                stop_loss = buy_price * (1 - stop_loss_ratio)

                # 🌙 entry_time 복원: DB의 실제 매수 시각 사용 (오버나이트 청산 안전화)
                # — 락 밖에서 DB I/O 수행(락 블로킹 회피)
                db_entry_time = None
                try:
                    from db.database_manager import DatabaseManager as _DBM
                    db_entry_time = _DBM().get_open_buy_timestamp(code)
                except Exception as e:
                    self.logger.warning(f"⚠️ {code} DB timestamp 조회 예외: {e}")

                # 상태 변경 (락 획득하여 원자적 처리)
                async with self.trading_manager._lock:
                    # TOCTOU 방지: 락 내부에서 상태 재확인 (SELL_CANDIDATE도 이미 추적 중이므로 건너뜀)
                    if ts.state in (StockState.BUY_PENDING, StockState.SELL_PENDING, StockState.POSITIONED, StockState.SELL_CANDIDATE, StockState.COMPLETED):
                        self.logger.debug(f"⏳ {code}: 복구 시점에 상태 변경됨 ({ts.state.value}) - 건너뜀")
                        continue
                    ts.set_position(quantity, avg_price, entry_time=db_entry_time)
                    ts.clear_current_order()
                    ts.is_buying = False
                    ts.order_processed = True
                    self.trading_manager._change_stock_state(code, StockState.POSITIONED,
                        f"잔고복구: {quantity}주 @{buy_price:,.0f}원, 목표: +{take_profit_ratio*100:.1f}%/-{stop_loss_ratio*100:.1f}%")

                self.logger.info(f"✅ {code} 복구완료: 매수 {buy_price:,.0f} → "
                               f"목표 {target_price:,.0f} / 손절 {stop_loss:,.0f}")

                if db_entry_time is None:
                    self.logger.warning(
                        f"⚠️ {code} DB 미매칭 BUY 없음 → entry_time=now() 폴백 "
                        f"(오버나이트 청산 시 당일 진입으로 오판 가능, 수동 확인 필요)"
                    )
                    try:
                        await self.telegram.notify_error(
                            "EntryTimeRestore",
                            f"⚠️ {code} DB 미매칭 BUY 없음 — 수동 확인 필요"
                        )
                    except Exception:
                        pass

                # 매수 기록이 DB에 없으면 저장 (buy_pending→positioned 복구 시 누락 방지)
                try:
                    from db.database_manager import DatabaseManager
                    db = DatabaseManager()
                    existing_buy = db.get_last_open_real_buy(code)
                    if not existing_buy:
                        stock_name = ts.stock_name or f'Stock_{code}'
                        db.save_real_buy(
                            stock_code=code,
                            stock_name=stock_name,
                            price=float(avg_price),
                            quantity=int(quantity),
                            strategy=ts.selection_reason or "잔고복구",
                            reason="잔고동기화복구"
                        )
                        self.logger.info(f"✅ {code} 매수 기록 보완 저장 (잔고동기화)")
                except Exception as db_err:
                    self.logger.warning(f"⚠️ {code} 매수 기록 보완 실패: {db_err}")

            self.logger.info(f"🔧 총 {len(missing_positions)}개 종목 긴급 복구 완료")

            # 텔레그램 알림
            if missing_positions:
                message = f"🔧 포지션 동기화 복구\n"
                message += f"복구된 종목: {len(missing_positions)}개\n"
                for code, balance_stock, _ in missing_positions[:3]:  # 최대 3개만
                    quantity = balance_stock['quantity']
                    avg_price = balance_stock['avg_price']
                    message += f"- {code}: {quantity}주 @{avg_price:,.0f}원\n"
                await self.telegram.notify_system_status(message)

        except Exception as e:
            self.logger.error(f"❌ 긴급 포지션 동기화 실패: {e}")
            await self.telegram.notify_error("Emergency Position Sync", e)

    async def shutdown(self):
        """시스템 종료"""
        try:
            self.logger.info("🛑 시스템 종료 시작")
            
            # 데이터 수집 중단
            self.data_collector.stop_collection()
            
            # 주문 모니터링 중단
            self.order_manager.stop_monitoring()
            
            # 텔레그램 통합 종료
            await self.telegram.shutdown()
            
            # API 매니저 종료
            self.api_manager.shutdown()
            
            # PID 파일 삭제
            if self.pid_file.exists():
                self.pid_file.unlink()
                self.logger.info("PID 파일 삭제 완료")
            
            self.logger.info("✅ 시스템 종료 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 종료 중 오류: {e}")


async def main():
    """메인 함수"""
    bot = DayTradingBot()
    
    # 시스템 초기화
    if not await bot.initialize():
        sys.exit(1)
    
    # 일일 거래 사이클 실행
    await bot.run_daily_cycle()


if __name__ == "__main__":
    try:
        # 로그 디렉토리 생성
        Path("logs").mkdir(exist_ok=True)
        
        # 메인 실행
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"시스템 오류: {e}")
        sys.exit(1)