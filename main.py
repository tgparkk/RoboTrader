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


class DayTradingBot:
    """주식 단타 거래 봇"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.is_running = False
        self.pid_file = Path("bot.pid")
        self._last_eod_liquidation_date = None  # 장마감 일괄청산 실행 일자
        
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

        # 🔧 price_position 전략 일별 거래 기록 초기화 (버그 수정 2026-02-04)
        TradingDecisionEngine.reset_daily_trades()
        self.logger.info("🔄 price_position 일별 거래 기록 초기화 완료")

        # 🔧 emergency_sync 서킷 브레이커 (같은 종목 반복 복구 방지, 버그 수정 2026-02-24)
        self._sync_restore_count: dict = {}  # {stock_code: count}

        # 실시간 종목 스크리너
        self.stock_screener = StockScreener(config=self._build_screener_config())

        # NXT 프리마켓 분석기
        self.pre_market_analyzer = PreMarketAnalyzer(config=self._build_pre_market_config())

        # 🆕 TradingStockManager에 decision_engine 연결 (쿨다운 설정용)
        self.trading_manager.set_decision_engine(self.decision_engine)

        self.fund_manager = FundManager(
            buy_budget_ratio=self.config.order_management.buy_budget_ratio
        )  # 🆕 자금 관리자
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
            'max_phase3_checks': sc.MAX_PHASE3_CHECKS,
            'max_candidates_per_scan': sc.MAX_CANDIDATES_PER_SCAN,
            'max_total_candidates': sc.MAX_TOTAL_CANDIDATES,
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
                except:
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
            
            while self.is_running:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                current_time = now_kst()

                # 🚨 장마감 시간 시장가 일괄매도 체크 (한 번만 실행) - 동적 시간 적용
                if MarketHours.is_eod_liquidation_time('KRX', current_time):
                    today_date = current_time.date()
                    if self._last_eod_liquidation_date != today_date:
                        await self._execute_end_of_day_liquidation()
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
                balance_info = self.api_manager.get_account_balance()
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
            else:
                self.logger.debug("📊 매도 판단 대상 종목 없음 (POSITIONED 상태 종목 없음)")

        except Exception as e:
            self.logger.error(f"❌ 매매 판단 시스템 오류: {e}")
    
    async def _analyze_buy_decision(self, trading_stock, available_funds: float = None):
        """매수 판단 분석 (완성된 3분봉만 사용)

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

            # 🆕 25분 매수 쿨다운 확인
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
            if len(combined_data) < 15:
                self.logger.debug(f"❌ {stock_code} 1분봉 데이터 부족: {len(combined_data)}개 (최소 15개 필요) - 실시간 데이터 대기 중")
                # 실시간 환경에서는 메모리에 있는 데이터만 사용 (캐시 파일 체크 불필요)
                return
            
            # 🆕 전략에 따라 1분봉 또는 3분봉 사용
            from config.strategy_settings import StrategySettings

            if StrategySettings.ACTIVE_STRATEGY == 'price_position':
                # price_position 전략: 1분봉 직접 사용 (더 정밀한 진입)
                analysis_data = combined_data
                #self.logger.debug(f"📊 {stock_code} price_position 전략: 1분봉 {len(analysis_data)}개 사용")
            else:
                # pullback 전략: 3분봉 변환 후 사용
                from core.timeframe_converter import TimeFrameConverter
                data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)

                if data_3min is None or len(data_3min) < 5:
                    self.logger.debug(f"❌ {stock_code} 3분봉 데이터 부족: {len(data_3min) if data_3min is not None else 0}개 (최소 5개 필요)")
                    return

                # 3분봉 품질 검증: 경고만 표시 (시뮬레이션과 동일하게 차단하지 않음)
                if not data_3min.empty and len(data_3min) >= 2:
                    data_3min_copy = data_3min.copy()
                    data_3min_copy['datetime'] = pd.to_datetime(data_3min_copy['datetime'])

                    # 1. 시간 간격 검증 (3분봉 연속성)
                    time_diffs = data_3min_copy['datetime'].diff().dt.total_seconds().fillna(0) / 60
                    invalid_gaps = time_diffs[1:][(time_diffs[1:] != 3.0) & (time_diffs[1:] != 0.0)]

                    if len(invalid_gaps) > 0:
                        gap_indices = invalid_gaps.index.tolist()
                        gap_times = [data_3min_copy.loc[idx, 'datetime'].strftime('%H:%M') for idx in gap_indices]
                        self.logger.warning(f"⚠️ {stock_code} 3분봉 불연속 구간 발견: {', '.join(gap_times)} (간격: {invalid_gaps.values} 분) - 경고만, 진행")

                    # 2. 각 3분봉의 구성 분봉 개수 검증 (HTS 분봉 누락 감지)
                    if 'candle_count' in data_3min_copy.columns:
                        incomplete_candles = data_3min_copy[data_3min_copy['candle_count'] < 3]
                        if not incomplete_candles.empty:
                            for idx, row in incomplete_candles.iterrows():
                                candle_time = row['datetime'].strftime('%H:%M')
                                count = int(row['candle_count'])
                                self.logger.warning(f"⚠️ {stock_code} 3분봉 내부 누락: {candle_time} ({count}/3개 분봉) - HTS 분봉 누락 가능성")

                    # 3. 09:00 시작 확인
                    first_time = data_3min_copy['datetime'].iloc[0]
                    if first_time.hour == 9 and first_time.minute not in [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30]:
                        self.logger.warning(f"⚠️ {stock_code} 첫 3분봉이 정규 시간이 아님: {first_time.strftime('%H:%M')} (09:00, 09:03, 09:06... 중 하나여야 함) - 경고만, 진행")

                analysis_data = data_3min

            # 매매 판단 엔진으로 매수 신호 확인
            buy_signal, buy_reason, buy_info = await self.decision_engine.analyze_buy_decision(trading_stock, analysis_data)
            
            self.logger.debug(f"💡 {stock_code} 매수 판단 결과: signal={buy_signal}, reason='{buy_reason}'")
            if buy_signal and buy_info:
                self.logger.debug(f"💰 {stock_code} 매수 정보: 가격={buy_info['buy_price']:,.0f}원, 수량={buy_info['quantity']:,}주, 투자금={buy_info['max_buy_amount']:,.0f}원")
          
            
            if buy_signal and buy_info.get('quantity', 0) > 0:
                self.logger.info(f"🚀 {stock_code}({stock_name}) 매수 신호 발생: {buy_reason}")

                # 🆕 매수 전 자금 확인 (전달받은 available_funds 활용)
                if available_funds is not None:
                    # 전달받은 가용 자금 기준으로 종목당 최대 투자 금액 계산 (설정값 사용, 기본 20%)
                    fund_status = self.fund_manager.get_status()
                    buy_budget_ratio = self.config.order_management.buy_budget_ratio
                    max_buy_amount = min(available_funds, fund_status['total_funds'] * buy_budget_ratio)
                else:
                    # 기존 방식 (fallback)
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
                
                # [리얼매매 코드 - 활성화]
                try:
                    # 전략에 따라 캔들 시점 정규화 (중복 신호 방지)
                    raw_candle_time = analysis_data['datetime'].iloc[-1]
                    if StrategySettings.ACTIVE_STRATEGY == 'price_position':
                        minute_normalized = raw_candle_time.minute  # 1분 단위
                    else:
                        minute_normalized = (raw_candle_time.minute // 3) * 3  # 3분 단위
                    current_candle_time = raw_candle_time.replace(minute=minute_normalized, second=0, microsecond=0)
                    await self.decision_engine.execute_real_buy(
                        trading_stock,
                        buy_reason,
                        buy_info['buy_price'],
                        buy_info['quantity'],
                        candle_time=current_candle_time
                    )
                    # 상태는 주문 처리 로직에서 자동으로 변경됨 (SELECTED -> BUY_PENDING -> POSITIONED)
                    self.logger.info(f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}")
                except Exception as e:
                    self.logger.error(f"❌ 실제 매수 처리 오류: {e}")
                    
                # [가상매매 코드 - 주석처리]
                # try:
                #     await self.decision_engine.execute_virtual_buy(trading_stock, data_3min, buy_reason)
                #     # 상태를 POSITIONED로 반영하여 이후 매도 판단 루프에 포함
                #     try:
                #         self.trading_manager._change_stock_state(stock_code, StockState.POSITIONED, "가상 매수 체결")
                #     except Exception:
                #         pass
                #     self.logger.info(f"🔥 가상 매수 완료 처리: {stock_code}({stock_name}) - {buy_reason}")
                # except Exception as e:
                #     self.logger.error(f"❌ 가상 매수 처리 오류: {e}")
                    
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
                return
            
            # 매매 판단 엔진으로 매도 신호 확인 (combined_data 불필요)
            sell_signal, sell_reason = await self.decision_engine.analyze_sell_decision(trading_stock, None)
            
            if sell_signal:
                # 🆕 매도 전 종목 상태 확인
                self.logger.debug(f"🔍 매도 전 상태 확인: {stock_code} 현재상태={trading_stock.state.value}")
                if trading_stock.position:
                    self.logger.debug(f"🔍 포지션 정보: {trading_stock.position.quantity}주 @{trading_stock.position.avg_price:,.0f}원")
                
                # 매도 후보로 변경
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
                        # 서킷브레이커 발동 → 매매 엔진에 업데이트된 리포트 재전달
                        self.decision_engine.set_pre_market_report(updated_report)
                        self.logger.warning(
                            f"[장시작갭] 서킷브레이커 발동! "
                            f"추천포지션={updated_report.recommended_max_positions}"
                        )
                        # 텔레그램 긴급 알림
                        gap_msg = (
                            f"[장시작갭 서킷브레이커]\n"
                            f"매수 중단! 포지션={updated_report.recommended_max_positions}\n"
                            f"{updated_report.log_lines[0] if updated_report.log_lines else ''}"
                        )
                        await self.telegram.notify_system_status(gap_msg)

                await asyncio.sleep(10)

        except Exception as e:
            self.logger.error(f"[프리마켓] 태스크 오류: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

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

                # 🆕 장중 종목 실시간 데이터 업데이트 (매분 13~45초 사이에 실행)
                # 13~45초 구간에서는 이전 실행으로부터 최소 13초 이상 간격만 유지
                # 장 마감 후 분봉 조회는 불필요 (데이터 저장은 아래 별도 블록에서 처리)
                if 13 <= current_time.second <= 45 and (current_time - last_intraday_update).total_seconds() >= 13:
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
                            try:
                                self.logger.info("🏁 장 마감 후 데이터 저장 시작...")
                                # DuckDB 폴백 read-only 연결 정리
                                from utils.data_cache import DataCache, DailyDataCache
                                DataCache.close_all_connections()
                                DailyDataCache.close_all_connections()
                                self.logger.info("🔌 DuckDB 폴백 연결 정리 완료")
                                self.intraday_manager.data_saver.save_all_data(self.intraday_manager)
                                post_market_data_saved_date = current_date
                                self.logger.info("✅ 장 마감 후 데이터 저장 완료")
                            except Exception as e:
                                self.logger.error(f"❌ 장 마감 후 데이터 저장 실패: {e}")

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
    
    async def _execute_end_of_day_liquidation(self):
        """장마감 시간 모든 보유 종목 시장가 일괄매도 (동적 시간 적용)"""
        try:
            from core.models import StockState

            # 동적 청산 시간 가져오기
            current_time = now_kst()
            market_hours = MarketHours.get_market_hours('KRX', current_time)
            eod_hour = market_hours['eod_liquidation_hour']
            eod_minute = market_hours['eod_liquidation_minute']

            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)

            if not positioned_stocks:
                self.logger.info(f"📦 {eod_hour}:{eod_minute:02d} 시장가 매도: 보유 포지션 없음")
                return

            self.logger.info(f"🚨 {eod_hour}:{eod_minute:02d} 시장가 일괄매도 시작: {len(positioned_stocks)}종목")

            # 모든 보유 종목 시장가 매도
            for trading_stock in positioned_stocks:
                try:
                    if not trading_stock.position or trading_stock.position.quantity <= 0:
                        continue

                    stock_code = trading_stock.stock_code
                    stock_name = trading_stock.stock_name
                    quantity = int(trading_stock.position.quantity)

                    # 시장가 매도를 위해 현재가 조회 (시장가는 가격 0으로 주문)
                    current_price = 0.0  # 시장가는 0원으로 주문

                    # 상태를 매도 대기로 변경 후 시장가 매도 주문
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

            # 🆕 데이터 수집 후 1초 대기 (데이터 안정화)
            await asyncio.sleep(1)

            # 🆕 최근 3분 데이터 재확인 (volume=0 but price changed 감지 및 재조회)
            updated_stocks = await reconfirm_intraday_data(
                self.intraday_manager,
                minutes_back=3
            )
            if updated_stocks:
                self.logger.info(f"🔄 데이터 재확인 완료: {len(updated_stocks)}개 종목 업데이트됨")

            # 🆕 n분봉 완성 + 10초 후 시점 체크 (전략 설정 기반)
            from config.strategy_settings import get_candle_interval
            candle_interval = get_candle_interval()

            minute_in_cycle = current_time.minute % candle_interval
            current_second = current_time.second

            # n분봉 사이클의 첫 번째 분이고 10초 이후일 때만 매수 판단
            is_candle_completed = (minute_in_cycle == 0 and current_second >= 10)

            if not is_candle_completed:
                self.logger.debug(f"⏱️ {candle_interval}분봉 미완성 또는 10초 미경과: {current_time.strftime('%H:%M:%S')} - 매수 판단 건너뜀")
                return

            # 🆕 데이터 업데이트 직후 매수 판단 실행 (3분봉 완성 + 10초 후)
            # 매수 중단 시간 전이고 SELECTED/COMPLETED 상태 종목만 매수 판단 - 동적 시간 적용
            should_stop_buy = MarketHours.should_stop_buying('KRX', current_time)

            if not should_stop_buy:
                # 요일 체크: 비허용 요일이면 매수 판단 전체 건너뜀 (노이즈 감소)
                from config.strategy_settings import StrategySettings
                if StrategySettings.ACTIVE_STRATEGY == 'price_position':
                    weekday = current_time.weekday()
                    if weekday not in StrategySettings.PricePosition.ALLOWED_WEEKDAYS:
                        weekday_names = ['월', '화', '수', '목', '금', '토', '일']
                        if not hasattr(self, '_weekday_skip_logged'):
                            self._weekday_skip_logged = False
                        if not self._weekday_skip_logged:
                            self.logger.info(f"📅 {weekday_names[weekday]}요일 - 매수 판단 건너뜀 (허용: 월/수/금)")
                            self._weekday_skip_logged = True
                        return

                # 가용 자금 계산
                balance_info = self.api_manager.get_account_balance()
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
                                ts.set_position(quantity, avg_price)
                                ts.clear_current_order()
                                ts.is_buying = False
                                ts.order_processed = True

                                self.trading_manager._change_stock_state(code, StockState.POSITIONED,
                                    f"미관리종목 복구: {quantity}주 @{avg_price:,.0f}원")

                                self.logger.info(f"✅ {code} 미관리 종목 복구 완료")

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
                ts.set_position(quantity, avg_price)
                ts.clear_current_order()
                ts.is_buying = False
                ts.order_processed = True

                # 매수가 기준 고정 비율로 목표가격 계산 (로깅용 - config에서 읽기)
                buy_price = avg_price
                take_profit_ratio = self.config.risk_management.take_profit_ratio
                stop_loss_ratio = self.config.risk_management.stop_loss_ratio
                target_price = buy_price * (1 + take_profit_ratio)
                stop_loss = buy_price * (1 - stop_loss_ratio)

                # 상태 변경
                self.trading_manager._change_stock_state(code, StockState.POSITIONED,
                    f"잔고복구: {quantity}주 @{buy_price:,.0f}원, 목표: +{take_profit_ratio*100:.1f}%/-{stop_loss_ratio*100:.1f}%")

                self.logger.info(f"✅ {code} 복구완료: 매수 {buy_price:,.0f} → "
                               f"목표 {target_price:,.0f} / 손절 {stop_loss:,.0f}")

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