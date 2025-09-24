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
from core.intraday_stock_manager import IntradayStockManager
from core.trading_stock_manager import TradingStockManager
from core.trading_decision_engine import TradingDecisionEngine
from core.fund_manager import FundManager
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from config.settings import load_trading_config
from utils.logger import setup_logger
from utils.korean_time import now_kst, get_market_status, is_market_open, KST
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
        self.fund_manager = FundManager()  # 🆕 자금 관리자
        self.chart_generator = None  # 🆕 장 마감 후 차트 생성기 (지연 초기화)
        
        
        # 신호 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

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
            
            # 4. 후보 종목 설정 (동적 선정을 위해 초기화만 수행)
            # TODO: 매일 장전 동적으로 후보 종목 선정 로직 구현
            
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
            
            # 병렬 실행할 태스크들
            tasks = [
                self._data_collection_task(),
                self._order_monitoring_task(),
                self.trading_manager.start_monitoring(),
                self._trading_decision_task(),
                self._system_monitoring_task(),
                self._telegram_task()
            ]
            
            # 모든 태스크 실행
            await asyncio.gather(*tasks, return_exceptions=True)
            
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

            #await self._check_condition_search()

            self.logger.info("🤖 매매 의사결정 태스크 시작")
            
            last_condition_check = datetime(2000, 1, 1, tzinfo=KST)  # 초기값
            
            while self.is_running:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                current_time = now_kst()
                
                # 🚨 15시 시장가 일괄매도 체크
                if current_time.hour >= 15 and current_time.minute >= 0:
                    await self._execute_end_of_day_liquidation()
                    break  # 매도 완료 후 루프 종료
                
                # 🆕 장중 조건검색 체크 (오전 09:00 ~ 15:00)
                if (9 <= current_time.hour < 15 and 
                    (current_time - last_condition_check).total_seconds() >= 10):  # 10초
                    await self._check_condition_search()
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
        """매매 판단 시스템 실행

        Args:
            available_funds: 사용 가능한 자금 (미리 계산된 값)
        """
        try:
            # 자금 정보 로깅
            if available_funds is not None:
                self.logger.debug(f"💰 전달된 가용 자금: {available_funds:,.0f}원")

            # TradingStockManager에서 관리 중인 종목들 확인
            from core.models import StockState
            
            selected_stocks = self.trading_manager.get_stocks_by_state(StockState.SELECTED)
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            buy_pending_stocks = self.trading_manager.get_stocks_by_state(StockState.BUY_PENDING)
            sell_pending_stocks = self.trading_manager.get_stocks_by_state(StockState.SELL_PENDING)
            completed_stocks = self.trading_manager.get_stocks_by_state(StockState.COMPLETED)
            
            self.logger.info(
                f"📦 종목 상태 현황:\n"
                f"  - SELECTED: {len(selected_stocks)}개 (매수 판단 대상)\n"
                f"  - COMPLETED: {len(completed_stocks)}개 (재거래 가능)\n"
                f"  - BUY_PENDING: {len(buy_pending_stocks)}개 (매수 주문 중)\n"
                f"  - POSITIONED: {len(positioned_stocks)}개 (보유중)\n"
                f"  - SELL_PENDING: {len(sell_pending_stocks)}개 (매도 주문 중)"
            )
            
            # 매수 주문 중인 종목 상세 정보
            if buy_pending_stocks:
                for stock in buy_pending_stocks:
                    self.logger.info(f"  📊 매수 체결 대기: {stock.stock_code}({stock.stock_name}) - 주문ID: {stock.current_order_id}")
            
            # 매수 판단: 선정된 종목들 + 재거래 가능한 완료 종목들
            buy_decision_candidates = selected_stocks + completed_stocks
            
            # 15시 이후 매수 금지 체크
            current_time = now_kst()
            is_after_Npm = current_time.hour >= 15
            
            if buy_decision_candidates and not is_after_Npm:
                self.logger.debug(f"🔍 매수 판단 대상: SELECTED={len(selected_stocks)}개, COMPLETED={len(completed_stocks)}개 (총 {len(buy_decision_candidates)}개)")
                for trading_stock in buy_decision_candidates:
                    await self._analyze_buy_decision(trading_stock, available_funds)
            else:
                if is_after_Npm:
                    self.logger.debug("📊 15시 이후이므로 매수 금지")
                else:
                    self.logger.debug("📊 매수 판단 대상 종목 없음 (SELECTED + COMPLETED 상태 종목 없음)")

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
            
            self.logger.debug(f"🔍 매수 판단 시작: {stock_code}({stock_name})")
            
            # 추가 안전 검증: 현재 보유 중인 종목인지 다시 한번 확인
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            if any(pos_stock.stock_code == stock_code for pos_stock in positioned_stocks):
                self.logger.info(f"⚠️ 보유 중인 종목 매수 신호 무시: {stock_code}({stock_name})")
                return
            
            # 분봉 데이터 가져오기
            combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
            if combined_data is None:
                self.logger.debug(f"❌ {stock_code} 1분봉 데이터 없음 (None)")
                return
            if len(combined_data) < 15:
                self.logger.debug(f"❌ {stock_code} 1분봉 데이터 부족: {len(combined_data)}개 (최소 15개 필요)")
                
                # 데이터 부족 시 자동 수집 시도
                try:
                    from trade_analysis.data_sufficiency_checker import check_and_collect_data
                    from utils.korean_time import now_kst
                    
                    today = now_kst().strftime('%Y%m%d')
                    self.logger.info(f"🔄 {stock_code} 데이터 부족으로 자동 수집 시도...")
                    
                    if check_and_collect_data(stock_code, today, 15):
                        # 수집 후 다시 데이터 확인
                        combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                        if combined_data is None or len(combined_data) < 15:
                            self.logger.warning(f"❌ {stock_code} 자동 수집 후에도 데이터 부족: {len(combined_data) if combined_data is not None else 0}개")
                            return
                        else:
                            self.logger.info(f"✅ {stock_code} 자동 수집 완료: {len(combined_data)}개")
                    else:
                        self.logger.warning(f"❌ {stock_code} 자동 수집 실패")
                        return
                        
                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 자동 수집 중 오류: {e}")
                    return
            
            # 🆕 3분봉 변환 시 완성된 봉만 자동 필터링됨 (TimeFrameConverter에서 처리)
            from core.timeframe_converter import TimeFrameConverter
            from utils.korean_time import now_kst
            
            data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
            
            if data_3min is None or len(data_3min) < 5:
                self.logger.debug(f"❌ {stock_code} 3분봉 데이터 부족: {len(data_3min) if data_3min is not None else 0}개 (최소 5개 필요)")
                return
                
            current_time = now_kst()
            last_3min_time = data_3min['datetime'].iloc[-1] if not data_3min.empty else None
            
            #self.logger.debug(f"📊 {stock_code} 매수판단 - 현재: {current_time.strftime('%H:%M:%S')}, "
            #                f"마지막 완성된 3분봉: {last_3min_time.strftime('%H:%M:%S') if last_3min_time else 'None'} "
            #                f"(총 {len(data_3min)}개 3분봉)")
            
            # 매매 판단 엔진으로 매수 신호 확인 (완성된 3분봉 데이터 사용)
            buy_signal, buy_reason, buy_info = await self.decision_engine.analyze_buy_decision(trading_stock, data_3min)
            
            self.logger.debug(f"💡 {stock_code} 매수 판단 결과: signal={buy_signal}, reason='{buy_reason}'")
            if buy_signal and buy_info:
                self.logger.debug(f"💰 {stock_code} 매수 정보: 가격={buy_info['buy_price']:,.0f}원, 수량={buy_info['quantity']:,}주, 투자금={buy_info['max_buy_amount']:,.0f}원")
          
            
            if buy_signal and buy_info.get('quantity', 0) > 0:
                self.logger.info(f"🚀 {stock_code}({stock_name}) 매수 신호 발생: {buy_reason}")

                # 🆕 매수 전 자금 확인 (전달받은 available_funds 활용)
                if available_funds is not None:
                    # 전달받은 가용 자금 기준으로 종목당 최대 투자 금액 계산 (10%)
                    fund_status = self.fund_manager.get_status()
                    max_buy_amount = min(available_funds, fund_status['total_funds'] * 0.1)
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
                # try:
                #     # 3분 단위로 정규화된 캔들 시점을 전달하여 중복 신호 방지
                #     raw_candle_time = data_3min['datetime'].iloc[-1]
                #     minute_normalized = (raw_candle_time.minute // 3) * 3
                #     current_candle_time = raw_candle_time.replace(minute=minute_normalized, second=0, microsecond=0)
                #     await self.decision_engine.execute_real_buy(
                #         trading_stock, 
                #         buy_reason, 
                #         buy_info['buy_price'], 
                #         buy_info['quantity'],
                #         candle_time=current_candle_time
                #     )
                #     # 상태는 주문 처리 로직에서 자동으로 변경됨 (SELECTED -> BUY_PENDING -> POSITIONED)
                #     self.logger.info(f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}")
                # except Exception as e:
                #     self.logger.error(f"❌ 실제 매수 처리 오류: {e}")
                    
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
                success = self.trading_manager.move_to_sell_candidate(stock_code, sell_reason)
                if success:
                    # # [실제 매도 주문 실행 - 활성화]
                    # try:
                    #     await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                    #     self.logger.info(f"📉 실제 매도 주문 완료: {stock_code}({stock_name}) - {sell_reason}")
                    # except Exception as e:
                    #     self.logger.error(f"❌ 실제 매도 처리 오류: {e}")
                    
                    # [가상매매 코드 - 주석처리]
                    try:
                        await self.decision_engine.execute_virtual_sell(trading_stock, combined_data, sell_reason)
                        self.logger.info(f"📉 가상 매도 완료 처리: {stock_code}({stock_name}) - {sell_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 가상 매도 처리 오류: {e}")
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
    
    async def _system_monitoring_task(self):
        """시스템 모니터링 태스크"""
        try:
            self.logger.info("🔥 DEBUG: _system_monitoring_task 시작됨")  # 디버깅용
            self.logger.info("📡 시스템 모니터링 태스크 시작")
            
            last_api_refresh = now_kst()
            last_market_check = now_kst()
            last_intraday_update = now_kst()  # 🆕 장중 데이터 업데이트 시간
            last_chart_generation = datetime(2000, 1, 1, tzinfo=KST)  # 🆕 장 마감 후 차트 생성 시간
            chart_generation_count = 0  # 🆕 차트 생성 횟수 카운터
            last_chart_reset_date = now_kst().date()  # 🆕 차트 카운터 리셋 기준 날짜

            self.logger.info("🔥 DEBUG: while 루프 진입 시도")  # 디버깅용
            while self.is_running:
                #self.logger.info(f"🔥 DEBUG: while 루프 실행 중 - is_running: {self.is_running}")  # 디버깅용
                current_time = now_kst()
                
                # API 24시간마다 재초기화
                if (current_time - last_api_refresh).total_seconds() >= 86400:  # 24시간
                    await self._refresh_api()
                    last_api_refresh = current_time

                # 🆕 장중 종목 실시간 데이터 업데이트
                if (current_time - last_intraday_update).total_seconds() >= 10:  # 10초
                    if is_market_open():
                        await self._update_intraday_data()
                    last_intraday_update = current_time
                
                # 장마감 청산 로직 제거: 15:00 시장가 매도로 대체됨
                
                # 🆕 차트 생성 카운터 매일 리셋
                current_date = current_time.date()
                if current_date != last_chart_reset_date:
                    chart_generation_count = 0  # 새로운 날이면 카운터 리셋
                    last_chart_reset_date = current_date
                    self.logger.info(f"📅 새로운 날 - 차트 생성 카운터 리셋 ({current_date})")
                
                # 🆕 장 마감 후 차트 생성 (16:00~24:00 시간대에 실행)
                current_hour = current_time.hour
                is_chart_time = (16 <= current_hour <= 23) and current_time.weekday() < 5  # 평일 16~24시
                if is_chart_time and chart_generation_count < 2:  # 16~24시 시간대에만, 최대 2번
                    if (current_time - last_chart_generation).total_seconds() >= 1 * 60:  # 1분 간격으로 체크
                        #self.logger.info(f"🔥 DEBUG: 차트 생성 실행 시작 ({chart_generation_count + 1}/2)")  # 디버깅용
                        await self._generate_post_market_charts()
                        #self.logger.info(f"🔥 DEBUG: 차트 생성 실행 완료 ({chart_generation_count + 1}/2)")  # 디버깅용
                        last_chart_generation = current_time
                        chart_generation_count += 1
                        
                        if chart_generation_count >= 1:
                            self.logger.info("✅ 장 마감 후 차트 생성 완료 (1회 실행 완료)")
                
                # 시스템 모니터링 루프 대기 (30초 주기)
                await asyncio.sleep(30)  
                
                # 30분마다 시스템 상태 로깅
                if (current_time - last_market_check).total_seconds() >= 30 * 60:  # 30분
                    await self._log_system_status()
                    last_market_check = current_time
                
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
                    moved = self.trading_manager.move_to_sell_candidate(stock_code, "장마감 일괄청산")
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
        """15시 모든 보유 종목 시장가 일괄매도"""
        try:
            from core.models import StockState
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            
            if not positioned_stocks:
                self.logger.info("📦 15시 시장가 매도: 보유 포지션 없음")
                return
            
            self.logger.info(f"🚨 15시 시장가 일괄매도 시작: {len(positioned_stocks)}종목")
            
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
                    moved = self.trading_manager.move_to_sell_candidate(stock_code, "15시 시장가 일괄매도")
                    if moved:
                        await self.trading_manager.execute_sell_order(
                            stock_code, quantity, current_price, "15시 시장가 일괄매도", market=True
                        )
                        self.logger.info(f"🚨 15시 시장가 매도: {stock_code}({stock_name}) {quantity}주 시장가 주문")
                    
                except Exception as se:
                    self.logger.error(f"❌ 15시 시장가 매도 개별 처리 오류({trading_stock.stock_code}): {se}")
            
            # 가상 포지션 처리 제거 (실제 매매 모드)
            
            self.logger.info("✅ 15시 시장가 일괄매도 요청 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 15시 시장가 매도 오류: {e}")
    
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
    
   
    async def _check_condition_search(self):
        """장중 조건검색 체크"""
        try:
            #self.logger.debug("🔍 장중 조건검색 체크 시작")
            
            # 조건검색 seq 리스트 (필요에 따라 여러 조건 추가 가능)
            #condition_seqs = ["0", "1", "2"]  # 예: 0, 1, 2번 조건
            condition_seqs = ["0"]
            
            all_condition_results = []
            
            for seq in condition_seqs:
                try:
                    # 조건검색 결과 조회 (단순 조회만)
                    condition_results = self.candidate_selector.get_condition_search_candidates(seq=seq)
                    
                    if condition_results:
                        all_condition_results.extend(condition_results)
                        #self.logger.debug(f"✅ 조건검색 {seq}번: {len(condition_results)}개 종목 발견")
                        #self.logger.debug(f"🔍 조건검색 {seq}번 결과: {condition_results}")
                    else:
                        self.logger.debug(f"ℹ️ 조건검색 {seq}번: 해당 종목 없음")
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ 조건검색 {seq}번 오류: {e}")
                    continue
            
            # 결과가 있으면 알림 발송
            #self.logger.debug(f"🔍 조건검색 전체 결과: {len(all_condition_results)}개 종목")
            if all_condition_results:
                
                # 🆕 장중 선정 종목 관리자에 추가 (과거 분봉 데이터 포함)
                #self.logger.debug(f"🎯 장중 선정 종목 관리자에 {len(all_condition_results)}개 종목 추가 시작")
                candidates_to_save = []
                for stock_data in all_condition_results:
                    stock_code = stock_data.get('code', '')
                    stock_name = stock_data.get('name', '')
                    change_rate = stock_data.get('chgrate', '')
                    
                    if stock_code:
                        # 전날 종가 조회 (일봉 데이터) - 주말 안전 처리
                        prev_close = 0.0
                        try:
                            # 충분한 기간의 데이터 요청 (주말 고려하여 7일)
                            daily_data = self.api_manager.get_ohlcv_data(stock_code, "D", 7)
                            if daily_data is not None and len(daily_data) >= 2:
                                if hasattr(daily_data, 'iloc'):  # DataFrame
                                    # 데이터 정렬 (날짜순)
                                    daily_data = daily_data.sort_values('stck_bsop_date')
                                    
                                    # 오늘 데이터가 있는지 확인
                                    last_date = daily_data.iloc[-1]['stck_bsop_date']
                                    if isinstance(last_date, str):
                                        last_date = datetime.strptime(last_date, '%Y%m%d').date()
                                    elif hasattr(last_date, 'date'):
                                        last_date = last_date.date()
                                    
                                    # 오늘 데이터가 있으면 전날(iloc[-2]), 없으면 마지막 거래일(iloc[-1]) 사용
                                    if last_date == now_kst().date() and len(daily_data) >= 2:
                                        prev_close = float(daily_data.iloc[-2]['stck_clpr'])
                                        self.logger.debug(f"📊 {stock_code}: 전날 종가 {prev_close} (오늘 데이터 제외)")
                                    else:
                                        prev_close = float(daily_data.iloc[-1]['stck_clpr'])
                                        self.logger.debug(f"📊 {stock_code}: 전날 종가 {prev_close} (마지막 거래일)")
                                elif len(daily_data) >= 2:  # List
                                    prev_close = daily_data[-2].close_price
                        except Exception as e:
                            self.logger.debug(f"⚠️ {stock_code} 전날 종가 조회 실패: {e}")
                        
                        # 거래 상태 통합 관리자에 추가 (분봉 데이터 수집 + 거래 상태 관리)
                        selection_reason = f"조건검색 급등주 (등락률: {change_rate}%)"
                        success = await self.trading_manager.add_selected_stock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            selection_reason=selection_reason,
                            prev_close=prev_close
                        )
                        
                        if success:
                            #self.logger.debug(f"🎯 거래 종목 추가: {stock_code}({stock_name}) - {selection_reason}")
                            # 🆕 후보 종목 DB 저장용 리스트 구성
                            try:
                                score_val = 0.0
                                if isinstance(change_rate, (int, float)):
                                    score_val = float(change_rate)
                                else:
                                    # 문자열인 경우 숫자만 추출 시도 (예: '3.2')
                                    score_val = float(str(change_rate).replace('%', '').strip()) if str(change_rate).strip() else 0.0
                            except Exception:
                                score_val = 0.0
                            candidates_to_save.append(
                                CandidateStock(
                                    code=stock_code,
                                    name=stock_name,
                                    market=stock_data.get('market', 'KOSPI'),
                                    score=score_val,
                                    reason=selection_reason
                                )
                            )
                # 🆕 후보 종목 DB 저장
                try:
                    if candidates_to_save:
                        self.db_manager.save_candidate_stocks(candidates_to_save)
                        #self.logger.debug(f"🗄️ 후보 종목 DB 저장 완료: {len(candidates_to_save)}건")
                except Exception as db_err:
                    self.logger.error(f"❌ 후보 종목 DB 저장 오류: {db_err}")
            else:
                self.logger.debug("ℹ️ 장중 조건검색: 발견된 종목 없음")
            
        except Exception as e:
            self.logger.error(f"❌ 장중 조건검색 체크 오류: {e}")
            await self.telegram.notify_error("Condition Search", e)
    
    async def _update_intraday_data(self):
        """장중 종목 실시간 데이터 업데이트 (완성된 분봉만 수집)"""
        try:
            from utils.korean_time import now_kst
            current_time = now_kst()
            
            # 🆕 완성된 봉만 수집하는 것을 로깅
            #self.logger.debug(f"🔄 실시간 데이터 업데이트 시작: {current_time.strftime('%H:%M:%S')} "
            #                f"(모든 관리 종목 - 재거래 대응)")
            
            # 모든 관리 종목의 실시간 데이터 업데이트 (재거래를 위해 COMPLETED, FAILED 상태도 포함)
            await self.intraday_manager.batch_update_realtime_data()
            
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
            self.logger.info("🔧 긴급 포지션 동기화 시작")

            # 실제 잔고 조회
            loop = asyncio.get_event_loop()
            balance = await loop.run_in_executor(
                None,
                self.api_manager.get_account_balance
            )
            if not balance or not balance.positions:
                self.logger.info("📊 보유 종목 없음")
                return

            held_stocks = {p['stock_code']: p for p in balance.positions if p.get('quantity', 0) > 0}

            self.logger.info(f"📊 실제 계좌 보유 종목: {list(held_stocks.keys())}")
            self.logger.info(f"📊 시스템 관리 종목: {list(self.trading_manager.trading_stocks.keys())}")

            # 시스템에서 누락된 포지션 찾기
            missing_positions = []
            unmanaged_stocks = []
            for code, balance_stock in held_stocks.items():
                if code in self.trading_manager.trading_stocks:
                    ts = self.trading_manager.trading_stocks[code]
                    if ts.state != StockState.POSITIONED:
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

                                # missing_positions에도 추가하여 통합 처리
                                missing_positions.append((code, balance_stock, ts))

                    except Exception as e:
                        self.logger.error(f"❌ {code} 미관리 종목 복구 실패: {e}")

            if not missing_positions:
                self.logger.info("✅ 모든 포지션이 정상 동기화됨")
                return

            # 누락된 포지션들 복구
            for code, balance_stock, ts in missing_positions:
                # 포지션 복원
                quantity = balance_stock['quantity']
                avg_price = balance_stock['avg_price']
                ts.set_position(quantity, avg_price)
                ts.clear_current_order()
                ts.is_buying = False
                ts.order_processed = True

                # 매수가 기준 고정 비율로 목표가격 계산 (로깅용)
                buy_price = avg_price
                target_price = buy_price * 1.03    # +3% 목표
                stop_loss = buy_price * 0.98       # -2% 손절

                # 상태 변경
                self.trading_manager._change_stock_state(code, StockState.POSITIONED,
                    f"잔고복구: {quantity}주 @{buy_price:,.0f}원, 목표: +3%/-2%")

                self.logger.info(f"✅ {code} 복구완료: 매수 {buy_price:,.0f} → "
                               f"목표 {target_price:,.0f} / 손절 {stop_loss:,.0f}")

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