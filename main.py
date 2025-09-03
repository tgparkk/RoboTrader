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
        self.chart_generator = None  # 🆕 장 마감 후 차트 생성기 (지연 초기화)
        
        
        # 신호 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _round_to_tick(self, price: float) -> float:
        """KRX 호가단위에 맞게 반올림 (최근가에 가장 가까운 합법 틱)"""
        try:
            if price <= 0:
                return 0.0
            # 간단 테이블: 가격구간별 틱 (원)
            # 실제 KRX 호가단위와 약간 다를 수 있으나 보수적으로 적용
            brackets = [
                (0, 1000, 1),
                (1000, 5000, 5),
                (5000, 10000, 10),
                (10000, 50000, 50),
                (50000, 100000, 100),
                (100000, 500000, 500),
                (500000, float('inf'), 1000),
            ]
            tick = 1
            for low, high, t in brackets:
                if low <= price < high:
                    tick = t
                    break
            # 최근가에 가장 가까운 합법 틱
            return round(price / tick) * tick
        except Exception:
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

            await self._check_condition_search()

            self.logger.info("🤖 매매 의사결정 태스크 시작")
            
            last_condition_check = datetime(2000, 1, 1, tzinfo=KST)  # 초기값
            
            while self.is_running:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                current_time = now_kst()
                
                # 🆕 장중 조건검색 체크
                if (current_time - last_condition_check).total_seconds() >= 10:  # 10초
                    await self._check_condition_search()
                    last_condition_check = current_time
                
                # 매매 판단 시스템 실행 (5초 주기)
                await self._execute_trading_decision()
                await asyncio.sleep(5)  # 5초 주기
                
        except Exception as e:
            self.logger.error(f"❌ 매매 의사결정 태스크 오류: {e}")
    
    async def _execute_trading_decision(self):
        """매매 판단 시스템 실행"""
        try:
            # TradingStockManager에서 관리 중인 종목들 확인
            from core.models import StockState
            
            selected_stocks = self.trading_manager.get_stocks_by_state(StockState.SELECTED)
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            buy_pending_stocks = self.trading_manager.get_stocks_by_state(StockState.BUY_PENDING)
            sell_pending_stocks = self.trading_manager.get_stocks_by_state(StockState.SELL_PENDING)
            
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
            completed_stocks = self.trading_manager.get_stocks_by_state(StockState.COMPLETED)
            buy_decision_candidates = selected_stocks + completed_stocks
            
            if buy_decision_candidates:
                self.logger.debug(f"🔍 매수 판단 대상: SELECTED={len(selected_stocks)}개, COMPLETED={len(completed_stocks)}개 (총 {len(buy_decision_candidates)}개)")
                for trading_stock in buy_decision_candidates:
                    await self._analyze_buy_decision(trading_stock)
            else:
                self.logger.debug("📊 매수 판단 대상 종목 없음 (SELECTED + COMPLETED 상태 종목 없음)")
            
            # 🆕 가상매매 vs 실제거래 모드에 따른 매도 로직 분리
            if self.decision_engine.is_virtual_mode:
                # 가상매매 모드: DB에서 직접 가상 포지션 조회하여 매도 판단
                await self._analyze_virtual_positions_for_sell()
            else:
                # 실제 거래 모드: 실제 포지션만 매도 판단 (가상 포지션 제외)
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
    
    async def _analyze_buy_decision(self, trading_stock):
        """매수 판단 분석 (완성된 3분봉만 사용)"""
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
                self.logger.debug(f"❌ {stock_code} 분봉 데이터 없음 (None)")
                return
            if len(combined_data) < 5:
                self.logger.debug(f"❌ {stock_code} 분봉 데이터 부족: {len(combined_data)}개 (최소 5개 필요)")
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
            
            # 🆕 signal_replay와 일관성 검증 (완성된 3분봉 기준)
            #if hasattr(self.decision_engine, 'verify_signal_consistency'):
            #    try:
            #        # 이미 완성된 3분봉으로 변환된 data_3min 사용
            #        verification_result = self.decision_engine.verify_signal_consistency(stock_code, data_3min)
            #        
            #        # 실제 매수 신호와 검증 결과 비교
            #        verified_signal = verification_result.get('has_signal', False)
            #        if buy_signal != verified_signal:
            #            self.logger.warning(
            #                f"⚠️ 신호 불일치 감지: {stock_code}({stock_name})\n"
            #                f"  - 실제 매수 신호: {buy_signal} ({buy_reason})\n"
            #                f"  - 검증 신호: {verified_signal} ({verification_result.get('signal_types', [])})\n"
            #                f"  - 미충족 조건: {verification_result.get('unmet_conditions', [])}\n"
            #                f"  - 3분봉 개수: {len(data_3min)}개 (마지막: {last_3min_time.strftime('%H:%M:%S') if last_3min_time else 'None'})"
            #            )
            #        else:
            #            self.logger.debug(
            #                f"✅ 신호 일치 확인: {stock_code} signal={buy_signal} (완성된 3분봉 {len(data_3min)}개 기준)"
            #            )
            #    except Exception as e:
            #        self.logger.debug(f"신호 일관성 검증 오류: {e}")
            
            if buy_signal and buy_info.get('quantity', 0) > 0:
                self.logger.info(f"🚀 {stock_code}({stock_name}) 매수 신호 발생: {buy_reason}")
                
                # 🆕 매수 전 종목 상태 확인
                current_stock = self.trading_manager.get_trading_stock(stock_code)
                if current_stock:
                    self.logger.debug(f"🔍 매수 전 상태 확인: {stock_code} 현재상태={current_stock.state.value}")
                
                try:
                    await self.decision_engine.execute_real_buy(
                        trading_stock, 
                        buy_reason, 
                        buy_info['buy_price'], 
                        buy_info['quantity']
                    )
                    # 상태는 주문 처리 로직에서 자동으로 변경됨 (SELECTED -> BUY_PENDING -> POSITIONED)
                    self.logger.info(f"🔥 실제 매수 주문 완료: {stock_code}({stock_name}) - {buy_reason}")
                except Exception as e:
                    self.logger.error(f"❌ 실제 매수 처리 오류: {e}")
                    
                    # [기존 가상매매 코드 - 주석처리]
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
        """매도 판단 분석"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 분봉 데이터 가져오기
            combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
            if combined_data is None or len(combined_data) < 15:
                return
            
            # 매매 판단 엔진으로 매도 신호 확인
            sell_signal, sell_reason = await self.decision_engine.analyze_sell_decision(trading_stock, combined_data)
            
            if sell_signal:
                # 🆕 매도 전 종목 상태 확인
                self.logger.debug(f"🔍 매도 전 상태 확인: {stock_code} 현재상태={trading_stock.state.value}")
                if trading_stock.position:
                    self.logger.debug(f"🔍 포지션 정보: {trading_stock.position.quantity}주 @{trading_stock.position.avg_price:,.0f}원")
                
                # 매도 후보로 변경
                success = self.trading_manager.move_to_sell_candidate(stock_code, sell_reason)
                if success:
                    # 실제 매도 주문 실행
                    try:
                        await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                        self.logger.info(f"📉 실제 매도 주문 완료: {stock_code}({stock_name}) - {sell_reason}")
                    except Exception as e:
                        self.logger.error(f"❌ 실제 매도 처리 오류: {e}")
                    
                    # [기존 가상매매 코드 - 주석처리]
                    # try:
                    #     await self.decision_engine.execute_virtual_sell(trading_stock, combined_data, sell_reason)
                    #     self.logger.info(f"📉 가상 매도 완료 처리: {stock_code}({stock_name}) - {sell_reason}")
                    # except Exception as e:
                    #     self.logger.error(f"❌ 가상 매도 처리 오류: {e}")
                        
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매도 판단 오류: {e}")
    
    async def _analyze_virtual_positions_for_sell(self):
        """DB에서 미체결 가상 포지션을 조회하여 매도 판단 (signal_replay 방식)"""
        try:
            # DB에서 미체결 가상 포지션 조회
            open_positions = self.db_manager.get_virtual_open_positions()
            
            if open_positions.empty:
                return
            
            self.logger.info(f"🔍 미체결 가상 포지션 {len(open_positions)}개에 대해 매도 판단 실행")
            
            for _, position in open_positions.iterrows():
                stock_code = position['stock_code']
                stock_name = position['stock_name']
                buy_price = position['buy_price']
                buy_reason = position.get('reason', '')
                
                try:
                    # 실시간 현재가 조회
                    current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                    if current_price_info is None:
                        continue
                    
                    current_price = current_price_info['current_price']
                    profit_rate = (current_price - buy_price) / buy_price
                    
                    # 신호 강도별 목표수익률 설정 (signal_replay 로직과 동일)
                    target_profit_rate = 0.015  # 기본값 1.5%
                    if 'strong' in buy_reason.lower():
                        target_profit_rate = 0.025  # 최고신호: 2.5%
                    elif 'cautious' in buy_reason.lower():
                        target_profit_rate = 0.02   # 중간신호: 2.0%
                    
                    # 손익비 2:1 적용
                    stop_loss_rate = target_profit_rate / 2.0
                    
                    sell_reason = None
                    
                    # (1) 신호강도별 손절
                    if current_price <= buy_price * (1.0 - stop_loss_rate):
                        sell_reason = f'stop_loss_{stop_loss_rate*100:.1f}pct'
                    # (2) 신호강도별 익절
                    elif current_price >= buy_price * (1.0 + target_profit_rate):
                        sell_reason = f'profit_{target_profit_rate*100:.1f}pct'
                    
                    # 매도 조건 충족시 실행
                    if sell_reason:
                        self.logger.info(f"📉 실시간 손익률 매도: {stock_code}({stock_name}) "
                                       f"@{current_price:,.0f}원 ({profit_rate:+.2%}) - {sell_reason}")
                        
                        # 임시 TradingStock 객체 생성
                        from core.models import TradingStock, StockState
                        from utils.korean_time import now_kst
                        trading_stock = TradingStock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            state=StockState.POSITIONED,
                            selected_time=now_kst(),
                            selection_reason="가상매수"
                        )
                        
                        # 가상 포지션 정보 설정
                        trading_stock.set_virtual_buy_info(position['id'], buy_price, position['quantity'])
                        trading_stock.set_position(position['quantity'], buy_price)
                        
                        # 차트 데이터는 간단히 처리 (현재가만 사용하므로)
                        combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                        if combined_data is None:
                            continue
                            
                        # 실제 매도 실행
                        await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                        
                        # [기존 가상매매 코드 - 주석처리]
                        # await self.decision_engine.execute_virtual_sell(trading_stock, combined_data, sell_reason)
                        continue
                    
                    # 실시간 손익률 매도 조건 없으면 기존 전략 매도 판단 실행
                    combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                    if combined_data is None or len(combined_data) < 30:
                        continue
                    
                    # 임시 TradingStock 객체 생성
                    from core.models import TradingStock, StockState
                    from utils.korean_time import now_kst
                    trading_stock = TradingStock(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        state=StockState.POSITIONED,
                        selected_time=now_kst(),
                        selection_reason="가상매수"
                    )
                    
                    # 가상 포지션 정보 설정
                    trading_stock.set_virtual_buy_info(position['id'], buy_price, position['quantity'])
                    trading_stock.set_position(position['quantity'], buy_price)
                    
                    # 전략별 매도 판단 실행
                    sell_signal, sell_reason = await self.decision_engine.analyze_sell_decision(trading_stock, combined_data)
                    
                    if sell_signal:
                        self.logger.info(f"📉 전략 기반 매도 신호: {stock_code}({stock_name}) - {sell_reason}")
                        await self.decision_engine.execute_real_sell(trading_stock, sell_reason)
                        
                        # [기존 가상매매 코드 - 주석처리]
                        # await self.decision_engine.execute_virtual_sell(trading_stock, combined_data, sell_reason)
                        
                except Exception as e:
                    self.logger.error(f"❌ 가상 포지션 매도 판단 오류 ({stock_code}): {e}")
                    
        except Exception as e:
            self.logger.error(f"❌ 가상 포지션 매도 판단 시스템 오류: {e}")
    
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
                
                # 🆕 장 마감 직전 일괄 청산 (15:29:30 이후 1회 실행)
                try:
                    current_date = current_time.date()
                    if (
                        current_time.hour == 15 and current_time.minute == 29 and current_time.second >= 30
                        and self._last_eod_liquidation_date != current_date
                    ):
                        await self._liquidate_all_positions_end_of_day()
                        self._last_eod_liquidation_date = current_date
                except Exception as e:
                    self.logger.error(f"❌ 장마감 일괄청산 처리 오류: {e}")
                
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
            
            # 🆕 실제 매매 모드에서는 가상 포지션 처리 제외
            if self.decision_engine.is_virtual_mode:
                # 가상매매 모드일 때만 가상 포지션 처리
                virtual_positions = []
                if hasattr(self, 'db_manager') and self.db_manager:
                    try:
                        open_positions = self.db_manager.get_virtual_open_positions()
                        if not open_positions.empty:
                            virtual_positions = open_positions.to_dict('records')
                            self.logger.info(f"🛎️ 장마감 가상포지션 일괄청산: 대상 {len(virtual_positions)}종목")
                    except Exception as ve:
                        self.logger.error(f"❌ 가상 포지션 조회 오류: {ve}")
                
                if not positioned_stocks and not virtual_positions:
                    self.logger.info("📦 장마감 일괄청산: 보유 포지션 없음")
                    return
                    
                total_positions = len(positioned_stocks) + len(virtual_positions)
                self.logger.info(f"🛎️ 장마감 일괄청산 시작: 실제 {len(positioned_stocks)}종목, 가상 {len(virtual_positions)}종목")
            else:
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
            
            # 🆕 가상 포지션 매도 (가상매매 모드일 때만)
            if self.decision_engine.is_virtual_mode and 'virtual_positions' in locals():
                for position in virtual_positions:
                    try:
                        stock_code = position['stock_code']
                        stock_name = position['stock_name']
                        buy_price = position['buy_price']
                        
                        # 현재가 조회
                        current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                        if current_price_info is None:
                            # 분봉 데이터로 현재가 추정
                            combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                            if combined_data is not None and len(combined_data) > 0:
                                current_price = float(combined_data['close'].iloc[-1])
                            else:
                                self.logger.warning(f"⚠️ 장마감 가상매도 실패: {stock_code} 현재가 조회 불가")
                                continue
                        else:
                            current_price = current_price_info['current_price']
                        
                        # 임시 TradingStock 객체 생성
                        from core.models import TradingStock, StockState
                        from utils.korean_time import now_kst
                        trading_stock = TradingStock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            state=StockState.POSITIONED,
                            selected_time=now_kst(),
                            selection_reason="가상매수"
                        )
                        
                        # 가상 포지션 정보 설정
                        trading_stock.set_virtual_buy_info(position['id'], buy_price, position['quantity'])
                        trading_stock.set_position(position['quantity'], buy_price)
                        
                        # 차트 데이터
                        combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                        if combined_data is None:
                            self.logger.warning(f"⚠️ 장마감 가상매도 실패: {stock_code} 차트 데이터 없음")
                            continue
                        
                        # 가상 매도 실행 (EOD - End of Day)
                        await self.decision_engine.execute_virtual_sell(trading_stock, combined_data, "EOD")
                        
                        profit_rate = (current_price - buy_price) / buy_price
                        self.logger.info(f"🧹 장마감 가상청산: {stock_code}({stock_name}) "
                                       f"@{current_price:,.0f}원 ({profit_rate:+.2%}) - EOD")
                        
                    except Exception as ve:
                        self.logger.error(f"❌ 장마감 가상청산 개별 처리 오류({position.get('stock_code', 'Unknown')}): {ve}")
            
            self.logger.info("✅ 장마감 일괄청산 요청 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 장마감 일괄청산 오류: {e}")
    
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
            self.logger.debug("🔍 장중 조건검색 체크 시작")
            
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
                        # 거래 상태 통합 관리자에 추가 (분봉 데이터 수집 + 거래 상태 관리)
                        selection_reason = f"조건검색 급등주 (등락률: {change_rate}%)"
                        success = await self.trading_manager.add_selected_stock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            selection_reason=selection_reason
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