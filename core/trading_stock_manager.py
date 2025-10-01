"""
종목 거래 상태 통합 관리 모듈
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import threading
from collections import defaultdict

from .models import TradingStock, StockState, OrderType, OrderStatus, Order
from .intraday_stock_manager import IntradayStockManager
from .data_collector import RealTimeDataCollector
from .order_manager import OrderManager
from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open


class TradingStockManager:
    """
    종목 거래 상태 통합 관리자
    
    주요 기능:
    1. 종목별 거래 상태 통합 관리
    2. 상태 변화에 따른 자동 처리
    3. 매수/매도 후보 관리
    4. 포지션 및 주문 상태 동기화
    5. 리스크 관리 및 모니터링
    """
    
    def __init__(self, intraday_manager: IntradayStockManager, 
                 data_collector: RealTimeDataCollector,
                 order_manager: OrderManager,
                 telegram_integration=None):
        """
        초기화
        
        Args:
            intraday_manager: 장중 종목 관리자
            data_collector: 실시간 데이터 수집기
            order_manager: 주문 관리자
            telegram_integration: 텔레그램 알림 (선택)
        """
        self.intraday_manager = intraday_manager
        self.data_collector = data_collector
        self.order_manager = order_manager
        self.telegram = telegram_integration
        self.logger = setup_logger(__name__)
        
        # 종목 상태 관리
        self.trading_stocks: Dict[str, TradingStock] = {}
        self.stocks_by_state: Dict[StockState, Dict[str, TradingStock]] = {
            state: {} for state in StockState
        }
        
        # 동기화
        self._lock = threading.RLock()
        
        # 모니터링 설정
        self.is_monitoring = False
        self.monitor_interval = 3  # 3초마다 상태 체크 (체결 확인 빠르게)
        
        # 재거래 설정
        self.enable_re_trading = True  # 매도 완료 후 재거래 허용 (COMPLETED 상태에서 직접 매수 판단)
        
        
        # 🆕 decision_engine은 나중에 설정됨 (순환 참조 방지)
        self.decision_engine = None

        self.logger.info("🎯 종목 거래 상태 통합 관리자 초기화 완료")
        # 주문 관리자에 역참조 등록 (정정 시 주문ID 동기화용)
        try:
            if hasattr(self.order_manager, 'set_trading_manager'):
                self.order_manager.set_trading_manager(self)
        except Exception:
            pass

    def set_decision_engine(self, decision_engine):
        """매매 판단 엔진 설정 (순환 참조 방지를 위해 별도 메서드)"""
        self.decision_engine = decision_engine
        self.logger.debug("✅ TradingStockManager에 decision_engine 연결 완료")
    
    async def add_selected_stock(self, stock_code: str, stock_name: str, 
                                selection_reason: str = "", prev_close: float = 0.0) -> bool:
        """
        조건검색으로 선정된 종목 추가 (비동기)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            selection_reason: 선정 사유
            prev_close: 전날 종가 (일봉 기준)
            
        Returns:
            bool: 추가 성공 여부
        """
        try:
            with self._lock:
                current_time = now_kst()
                
                # 이미 존재하는 종목인지 확인
                if stock_code in self.trading_stocks:
                    trading_stock = self.trading_stocks[stock_code]
                    # 재진입 허용: COMPLETED/FAILED → SELECTED로 재등록
                    if trading_stock.state in (StockState.COMPLETED, StockState.FAILED):
                        # 상태 변경 및 메타 업데이트
                        trading_stock.selected_time = current_time
                        trading_stock.selection_reason = selection_reason
                        # 포지션/주문 정보는 정리
                        trading_stock.clear_position()
                        trading_stock.clear_current_order()
                        self._change_stock_state(stock_code, StockState.SELECTED, f"재선정: {selection_reason}")
                        
                        # 🆕 IntradayStockManager에 다시 추가 (비동기 대기)
                        success = await self.intraday_manager.add_selected_stock(
                            stock_code, stock_name, selection_reason
                        )
                        if success:
                            self.logger.info(
                                f"✅ {stock_code}({stock_name}) 재선정 완료 - 시간: {current_time.strftime('%H:%M:%S')}"
                            )
                            return True
                        else:
                            self.logger.warning(f"⚠️ {stock_code} 재선정 실패 - Intraday 등록 실패")
                            return False
                    
                    # 그 외 상태에서는 기존 관리 유지
                    #self.logger.debug(f"📊 {stock_code}({stock_name}): 이미 관리 중 (상태: {trading_stock.state.value})")
                    return True
                
                # 신규 등록
                trading_stock = TradingStock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    state=StockState.SELECTED,
                    selected_time=current_time,
                    selection_reason=selection_reason,
                    prev_close=prev_close
                )
                
                # 등록
                self._register_stock(trading_stock)
            
            # 🆕 IntradayStockManager에 추가 (비동기 대기)
            success = await self.intraday_manager.add_selected_stock(
                stock_code, stock_name, selection_reason
            )
            
            if success:
                self.logger.info(f"✅ {stock_code}({stock_name}) 선정 완료 - "
                               f"시간: {current_time.strftime('%H:%M:%S')}")
                return True
            else:
                # 실패 시 제거
                with self._lock:
                    self._unregister_stock(stock_code)
                return False
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 종목 추가 오류: {e}")
            return False
    

    
    async def execute_buy_order(self, stock_code: str, quantity: int, 
                               price: float, reason: str = "") -> bool:
        """
        매수 주문 실행
        
        Args:
            stock_code: 종목코드
            quantity: 주문 수량
            price: 주문 가격
            reason: 매수 사유
            
        Returns:
            bool: 주문 성공 여부
        """
        try:
            with self._lock:
                if stock_code not in self.trading_stocks:
                    self.logger.warning(f"⚠️ {stock_code}: 관리 중이지 않은 종목")
                    return False
                
                trading_stock = self.trading_stocks[stock_code]
                
                # 🆕 중복 매수 방지: 이미 매수 진행 중인지 확인
                if trading_stock.is_buying:
                    self.logger.warning(f"⚠️ {stock_code}: 이미 매수 진행 중 (중복 매수 방지)")
                    return False

                # 🆕 25분 매수 쿨다운 확인
                if trading_stock.is_buy_cooldown_active():
                    remaining_minutes = trading_stock.get_remaining_cooldown_minutes()
                    self.logger.warning(f"⚠️ {stock_code}: 매수 쿨다운 활성화 (남은 시간: {remaining_minutes}분)")
                    return False
                
                # 상태 검증 (SELECTED 또는 COMPLETED에서 직접 매수 가능)
                if trading_stock.state not in [StockState.SELECTED, StockState.COMPLETED]:
                    self.logger.warning(f"⚠️ {stock_code}: 매수 가능 상태가 아님 (현재: {trading_stock.state.value})")
                    return False
                
                # 🆕 매수 진행 플래그 설정
                trading_stock.is_buying = True
                trading_stock.order_processed = False  # 새 주문이므로 리셋
                
                # 매수 주문 중 상태로 변경
                self._change_stock_state(stock_code, StockState.BUY_PENDING, f"매수 주문: {reason}")
                
                # 데이터 수집기에 후보 종목으로 추가 (실시간 모니터링)
                self.data_collector.add_candidate_stock(stock_code, trading_stock.stock_name)
            
            # 매수 주문 실행
            order_id = await self.order_manager.place_buy_order(stock_code, quantity, price)
            
            if order_id:
                with self._lock:
                    trading_stock = self.trading_stocks[stock_code]
                    trading_stock.add_order(order_id)
                
                # 🆕 쿨다운 설정 (매수 주문 성공 시)
                if hasattr(self, 'decision_engine') and self.decision_engine:
                    self.decision_engine.set_buy_cooldown(stock_code)
                
                self.logger.info(f"📈 {stock_code} 매수 주문 성공: {order_id}")
                return True
            else:
                # 주문 실패 시 원래 상태로 되돌림 (SELECTED 또는 COMPLETED)
                with self._lock:
                    trading_stock = self.trading_stocks[stock_code]
                    # 🆕 매수 진행 플래그 리셋
                    trading_stock.is_buying = False
                    
                    # 원래 상태 추정: 재거래면 COMPLETED, 신규면 SELECTED
                    original_state = StockState.COMPLETED if "재거래" in reason else StockState.SELECTED
                    self._change_stock_state(stock_code, original_state, "매수 주문 실패")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 매수 주문 오류: {e}")
            # 오류 시 원래 상태로 되돌림
            with self._lock:
                if stock_code in self.trading_stocks:
                    original_state = StockState.COMPLETED if "재거래" in reason else StockState.SELECTED
                    self._change_stock_state(stock_code, original_state, f"매수 주문 오류: {e}")
            return False
    
    def move_to_sell_candidate(self, stock_code: str, reason: str = "") -> bool:
        """
        포지션 종목을 매도 후보로 변경
        
        Args:
            stock_code: 종목코드
            reason: 변경 사유
            
        Returns:
            bool: 변경 성공 여부
        """
        try:
            with self._lock:
                if stock_code not in self.trading_stocks:
                    self.logger.warning(f"⚠️ {stock_code}: 관리 중이지 않은 종목")
                    return False
                
                trading_stock = self.trading_stocks[stock_code]
                
                # 상태 검증 (POSITIONED 또는 SELL_CANDIDATE에서 매도 시도 가능)
                if trading_stock.state not in [StockState.POSITIONED, StockState.SELL_CANDIDATE]:
                    self.logger.warning(f"⚠️ {stock_code}: 매도 가능 상태가 아님 (현재: {trading_stock.state.value})")
                    return False
                
                # 포지션 확인
                if not trading_stock.position:
                    self.logger.warning(f"⚠️ {stock_code}: 포지션 정보 없음")
                    return False
                
                # 상태 변경
                self._change_stock_state(stock_code, StockState.SELL_CANDIDATE, reason)
                
                self.logger.info(f"📉 {stock_code} 매도 후보로 변경: {reason}")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 매도 후보 변경 오류: {e}")
            return False
    
    async def execute_sell_order(self, stock_code: str, quantity: int, 
                                price: float, reason: str = "", market: bool = False) -> bool:
        """
        매도 주문 실행
        
        Args:
            stock_code: 종목코드
            quantity: 주문 수량
            price: 주문 가격
            reason: 매도 사유
            
        Returns:
            bool: 주문 성공 여부
        """
        try:
            with self._lock:
                if stock_code not in self.trading_stocks:
                    self.logger.warning(f"⚠️ {stock_code}: 관리 중이지 않은 종목")
                    return False
                
                trading_stock = self.trading_stocks[stock_code]
                
                # 상태 검증
                if trading_stock.state != StockState.SELL_CANDIDATE:
                    self.logger.warning(f"⚠️ {stock_code}: 매도 후보 상태가 아님 (현재: {trading_stock.state.value})")
                    return False
                
                # 매도 주문 중 상태로 변경
                self._change_stock_state(stock_code, StockState.SELL_PENDING, f"매도 주문: {reason}")
            
            # 매도 주문 실행
            order_id = await self.order_manager.place_sell_order(stock_code, quantity, price, market=market)
            
            if order_id:
                with self._lock:
                    trading_stock = self.trading_stocks[stock_code]
                    trading_stock.add_order(order_id)
                
                self.logger.info(f"📉 {stock_code} 매도 주문 성공: {order_id}")
                return True
            else:
                # 주문 실패 시 매도 후보로 되돌림
                with self._lock:
                    self._change_stock_state(stock_code, StockState.SELL_CANDIDATE, "매도 주문 실패")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 매도 주문 오류: {e}")
            # 오류 시 매도 후보로 되돌림
            with self._lock:
                if stock_code in self.trading_stocks:
                    self._change_stock_state(stock_code, StockState.SELL_CANDIDATE, f"매도 주문 오류: {e}")
            return False
    
    async def start_monitoring(self):
        """종목 상태 모니터링 시작"""
        self.is_monitoring = True
        self.logger.info("🔍 종목 상태 모니터링 시작")
        
        while self.is_monitoring:
            try:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                await self._monitor_stock_states()
                await asyncio.sleep(self.monitor_interval)
                
            except Exception as e:
                self.logger.error(f"❌ 종목 상태 모니터링 오류: {e}")
                await asyncio.sleep(10)
    
    async def _monitor_stock_states(self):
        """종목 상태 모니터링"""
        try:
            self.logger.debug("🔄 종목 상태 모니터링 실행")
            
            # 주문 완료 확인
            await self._check_order_completions()
            
            # 포지션 현재가 업데이트
            await self._update_position_prices()
            
            
        except Exception as e:
            self.logger.error(f"❌ 종목 상태 모니터링 중 오류: {e}")
    
    async def _check_order_completions(self):
        """주문 완료 확인 및 상태 업데이트"""
        try:
            # 매수 주문 중인 종목들 확인
            buy_pending_stocks = list(self.stocks_by_state[StockState.BUY_PENDING].values())
            for trading_stock in buy_pending_stocks:
                await self._check_buy_order_completion(trading_stock)
            
            # 매도 주문 중인 종목들 확인
            sell_pending_stocks = list(self.stocks_by_state[StockState.SELL_PENDING].values())
            for trading_stock in sell_pending_stocks:
                await self._check_sell_order_completion(trading_stock)
                
        except Exception as e:
            self.logger.error(f"❌ 주문 완료 확인 오류: {e}")
    
    async def _check_buy_order_completion(self, trading_stock: TradingStock):
        """매수 주문 완료 확인"""
        try:
            if not trading_stock.current_order_id:
                return
            
            #self.logger.debug(f"🔍 매수 주문 체결 확인 시작: {trading_stock.stock_code} - 주문ID: {trading_stock.current_order_id}")
            
            # 주문 관리자에서 완료된 주문 확인
            completed_orders = self.order_manager.get_completed_orders()
            #self.logger.debug(f"📋 전체 완료 주문 수: {len(completed_orders)}")
            
            for order in completed_orders:
                if (order.order_id == trading_stock.current_order_id and 
                    order.stock_code == trading_stock.stock_code):
                    
                    #self.logger.info(f"✅ 매칭된 완료 주문 발견: {order.order_id} - 상태: {order.status.value}")
                    
                    if order.status == OrderStatus.FILLED:
                        # 매수 완료 - 포지션 상태로 변경
                        with self._lock:
                            trading_stock.set_position(order.quantity, order.price)
                            trading_stock.clear_current_order()
                            # 🆕 매수 시간 기록
                            from utils.korean_time import now_kst
                            trading_stock.set_buy_time(now_kst())

                            self._change_stock_state(
                                trading_stock.stock_code,
                                StockState.POSITIONED,
                                f"매수 완료: {order.quantity}주 @{order.price:,.0f}원"
                            )
                        # 실거래 매수 기록 저장
                        try:
                            from db.database_manager import DatabaseManager
                            # DatabaseManager는 main에서 생성되어 전달되었을 수도 있으나, 안전하게 새 인스턴스 사용
                            db = DatabaseManager()
                            db.save_real_buy(
                                stock_code=trading_stock.stock_code,
                                stock_name=trading_stock.stock_name,
                                price=float(order.price),
                                quantity=int(order.quantity),
                                strategy=trading_stock.selection_reason,
                                reason="체결"
                            )
                        except Exception as db_err:
                            self.logger.warning(f"⚠️ 실거래 매수 기록 저장 실패: {db_err}")
                        
                        self.logger.info(f"✅ {trading_stock.stock_code} 매수 완료")
                        
                    elif order.status in [OrderStatus.CANCELLED, OrderStatus.FAILED]:
                        # 매수 실패 - 매수 후보로 되돌림
                        with self._lock:
                            trading_stock.clear_current_order()
                            # 매수 실패 시 원래 상태로 복귀
                            original_state = StockState.COMPLETED if "재거래" in trading_stock.selection_reason else StockState.SELECTED
                            self._change_stock_state(
                                trading_stock.stock_code, 
                                original_state, 
                                f"매수 실패: {order.status.value}"
                            )
                    
                    break
                    
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 주문 완료 확인 오류: {e}")
    
    async def _check_sell_order_completion(self, trading_stock: TradingStock):
        """매도 주문 완료 확인"""
        try:
            if not trading_stock.current_order_id:
                return
            
            # 주문 관리자에서 완료된 주문 확인
            completed_orders = self.order_manager.get_completed_orders()
            for order in completed_orders:
                if (order.order_id == trading_stock.current_order_id and 
                    order.stock_code == trading_stock.stock_code):
                    
                    if order.status == OrderStatus.FILLED:
                        # 매도 완료 - 완료 상태로 변경
                        with self._lock:
                            trading_stock.clear_position()
                            trading_stock.clear_current_order()
                            self._change_stock_state(
                                trading_stock.stock_code, 
                                StockState.COMPLETED, 
                                f"매도 완료: {order.quantity}주 @{order.price:,.0f}원"
                            )
                        # 실거래 매도 기록 저장 (매칭된 매수와 손익 계산)
                        profit_rate = 0.0
                        try:
                            from db.database_manager import DatabaseManager
                            db = DatabaseManager()
                            buy_id = db.get_last_open_real_buy(trading_stock.stock_code)
                            
                            # 수익률 계산을 위해 매수가 조회
                            buy_price = None
                            if buy_id and trading_stock.position and trading_stock.position.avg_price:
                                buy_price = trading_stock.position.avg_price
                                profit_rate = ((float(order.price) - buy_price) / buy_price) * 100
                            
                            db.save_real_sell(
                                stock_code=trading_stock.stock_code,
                                stock_name=trading_stock.stock_name,
                                price=float(order.price),
                                quantity=int(order.quantity),
                                strategy=trading_stock.selection_reason,
                                reason="체결",
                                buy_record_id=buy_id
                            )
                            
                            
                        except Exception as db_err:
                            self.logger.warning(f"⚠️ 실거래 매도 기록 저장 실패: {db_err}")
                        
                        self.logger.info(f"✅ {trading_stock.stock_code} 매도 완료 (수익률: {profit_rate:.2f}%)")
                        
                        # 매도 완료 후 즉시 재거래 준비 (COMPLETED 상태 유지)
                        if self.enable_re_trading:
                            self.logger.info(f"🔄 {trading_stock.stock_code} 즉시 재거래 준비 완료 (COMPLETED 상태 유지)")
                        
                    elif order.status in [OrderStatus.CANCELLED, OrderStatus.FAILED]:
                        # 매도 실패 - 매도 후보로 되돌림
                        with self._lock:
                            trading_stock.clear_current_order()
                            self._change_stock_state(
                                trading_stock.stock_code, 
                                StockState.SELL_CANDIDATE, 
                                f"매도 실패: {order.status.value}"
                            )
                    
                    break
                    
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매도 주문 완료 확인 오류: {e}")
    
    async def _update_position_prices(self):
        """포지션 현재가 업데이트"""
        try:
            positioned_stocks = list(self.stocks_by_state[StockState.POSITIONED].values())
            
            for trading_stock in positioned_stocks:
                if trading_stock.position:
                    # 현재가 조회
                    price_data = self.data_collector.get_stock(trading_stock.stock_code)
                    if price_data and price_data.last_price > 0:
                        trading_stock.position.update_current_price(price_data.last_price)
                        
        except Exception as e:
            self.logger.error(f"❌ 포지션 현재가 업데이트 오류: {e}")
    

    
    def _register_stock(self, trading_stock: TradingStock):
        """종목 등록"""
        stock_code = trading_stock.stock_code
        state = trading_stock.state
        
        self.trading_stocks[stock_code] = trading_stock
        self.stocks_by_state[state][stock_code] = trading_stock
    
    def _unregister_stock(self, stock_code: str):
        """종목 등록 해제"""
        if stock_code in self.trading_stocks:
            trading_stock = self.trading_stocks[stock_code]
            state = trading_stock.state
            
            del self.trading_stocks[stock_code]
            if stock_code in self.stocks_by_state[state]:
                del self.stocks_by_state[state][stock_code]
    
    def _change_stock_state(self, stock_code: str, new_state: StockState, reason: str = ""):
        """종목 상태 변경"""
        if stock_code not in self.trading_stocks:
            return
        
        trading_stock = self.trading_stocks[stock_code]
        old_state = trading_stock.state
        
        # 기존 상태에서 제거
        if stock_code in self.stocks_by_state[old_state]:
            del self.stocks_by_state[old_state][stock_code]
        
        # 새 상태로 변경
        trading_stock.change_state(new_state, reason)
        self.stocks_by_state[new_state][stock_code] = trading_stock
        
        # 🆕 상세 상태 변화 로깅
        self._log_detailed_state_change(trading_stock, old_state, new_state, reason)
    
    def _log_detailed_state_change(self, trading_stock: TradingStock, old_state: StockState, new_state: StockState, reason: str):
        """상세 상태 변화 로깅"""
        try:
            from utils.korean_time import now_kst
            current_time = now_kst().strftime('%H:%M:%S')
            
            # 기본 정보
            log_parts = [
                f"🔄 [{current_time}] {trading_stock.stock_code}({trading_stock.stock_name})",
                f"상태변경: {old_state.value} → {new_state.value}",
                f"사유: {reason}"
            ]
            
            # 포지션 정보
            if trading_stock.position:
                log_parts.append(f"포지션: {trading_stock.position.quantity}주 @{trading_stock.position.avg_price:,.0f}원")
                if trading_stock.position.current_price > 0:
                    profit_rate = ((trading_stock.position.current_price - trading_stock.position.avg_price) / trading_stock.position.avg_price) * 100
                    log_parts.append(f"현재가: {trading_stock.position.current_price:,.0f}원 ({profit_rate:+.2f}%)")
            else:
                log_parts.append("포지션: 없음")
            
            # 주문 정보
            if trading_stock.current_order_id:
                log_parts.append(f"현재주문: {trading_stock.current_order_id}")
            else:
                log_parts.append("현재주문: 없음")
            
            # 선정 사유 및 시간
            log_parts.append(f"선정사유: {trading_stock.selection_reason}")
            log_parts.append(f"선정시간: {trading_stock.selected_time.strftime('%H:%M:%S')}")
            
            # 상태별 특별 정보
            if new_state == StockState.BUY_PENDING:
                log_parts.append("⏳ 매수 주문 실행됨 - 체결 대기 중")
            elif new_state == StockState.POSITIONED:
                log_parts.append("✅ 매수 체결 완료 - 포지션 보유 중")
            elif new_state == StockState.SELL_CANDIDATE:
                log_parts.append("📉 매도 신호 발생 - 주문 대기 중")
            elif new_state == StockState.SELL_PENDING:
                log_parts.append("⏳ 매도 주문 실행됨 - 체결 대기 중")
            elif new_state == StockState.COMPLETED:
                log_parts.append("🎉 거래 완료")
            
            # 로그 출력
            self.logger.info("\n".join(f"  {part}" for part in log_parts))
            
        except Exception as e:
            self.logger.debug(f"❌ 상세 상태 변화 로깅 오류: {e}")
            # 기본 로그는 여전히 출력
            self.logger.info(f"🔄 {trading_stock.stock_code} 상태 변경: {old_state.value} → {new_state.value}")
    
    def get_stocks_by_state(self, state: StockState) -> List[TradingStock]:
        """특정 상태의 종목들 조회"""
        with self._lock:
            return list(self.stocks_by_state[state].values())
    
    def get_trading_stock(self, stock_code: str) -> Optional[TradingStock]:
        """종목 정보 조회"""
        return self.trading_stocks.get(stock_code)

    def update_current_order(self, stock_code: str, new_order_id: str) -> None:
        """정정 등으로 새 주문이 생성되었을 때 현재 주문ID를 최신값으로 동기화"""
        try:
            with self._lock:
                if stock_code in self.trading_stocks:
                    trading_stock = self.trading_stocks[stock_code]
                    trading_stock.current_order_id = new_order_id
                    trading_stock.order_history.append(new_order_id)
                    self.logger.debug(f"🔄 {stock_code} 현재 주문ID 업데이트: {new_order_id}")
        except Exception as e:
            self.logger.warning(f"⚠️ 현재 주문ID 업데이트 실패({stock_code}): {e}")
    
    async def on_order_filled(self, order: 'Order'):
        """주문 체결 시 즉시 호출되는 콜백 메서드"""
        try:
            from .models import OrderType, OrderStatus
            
            self.logger.info(f"🔔 주문 체결 콜백 수신: {order.order_id} - {order.stock_code} ({order.order_type.value})")
            
            with self._lock:
                if order.stock_code not in self.trading_stocks:
                    self.logger.warning(f"⚠️ 체결 콜백: 관리되지 않는 종목 {order.stock_code}")
                    return
                
                trading_stock = self.trading_stocks[order.stock_code]

                # 🆕 추가: 이미 POSITIONED 상태라면 중복 처리 방지
                if (order.order_type == OrderType.BUY and
                    trading_stock.state == StockState.POSITIONED):
                    self.logger.debug(f"⚠️ {order.stock_code} 이미 POSITIONED 상태 (중복 콜백 방지)")
                    return

                # 🆕 레이스 컨디션 방지: 이미 처리된 주문인지 확인
                if trading_stock.order_processed:
                    self.logger.debug(f"⚠️ 이미 처리된 주문 (중복 방지): {order.order_id}")
                    return
                
                if order.order_type == OrderType.BUY:
                    # 매수 체결
                    if trading_stock.state == StockState.BUY_PENDING:
                        # 🆕 체결 처리 플래그 설정
                        trading_stock.order_processed = True
                        trading_stock.is_buying = False  # 매수 완료
                        
                        trading_stock.set_position(order.quantity, order.price)
                        trading_stock.clear_current_order()
                        # 🆕 매수 시간 기록 (콜백)
                        from utils.korean_time import now_kst
                        trading_stock.set_buy_time(now_kst())

                        self._change_stock_state(
                            trading_stock.stock_code,
                            StockState.POSITIONED,
                            f"매수 체결 (콜백): {order.quantity}주 @{order.price:,.0f}원"
                        )
                        
                        # 실거래 매수 기록 저장
                        try:
                            from db.database_manager import DatabaseManager
                            db = DatabaseManager()
                            db.save_real_buy(
                                stock_code=trading_stock.stock_code,
                                stock_name=trading_stock.stock_name,
                                price=float(order.price),
                                quantity=int(order.quantity),
                                strategy=trading_stock.selection_reason,
                                reason="체결(콜백)"
                            )
                        except Exception as db_err:
                            self.logger.warning(f"⚠️ 실거래 매수 기록 저장 실패: {db_err}")
                        
                        self.logger.info(f"✅ 매수 체결 처리 완료 (콜백): {trading_stock.stock_code}")
                    else:
                        self.logger.warning(f"⚠️ 예상치 못한 상태에서 매수 체결: {trading_stock.state.value}")
                
                elif order.order_type == OrderType.SELL:
                    # 매도 체결
                    if trading_stock.state == StockState.SELL_PENDING:
                        # 🆕 체결 처리 플래그 설정
                        trading_stock.order_processed = True
                        trading_stock.is_selling = False  # 매도 완료
                        
                        trading_stock.clear_position()
                        trading_stock.clear_current_order()
                        self._change_stock_state(
                            trading_stock.stock_code, 
                            StockState.COMPLETED, 
                            f"매도 체결 (콜백): {order.quantity}주 @{order.price:,.0f}원"
                        )
                        
                        # 실거래 매도 기록 저장
                        profit_rate = 0.0
                        try:
                            from db.database_manager import DatabaseManager
                            db = DatabaseManager()
                            buy_id = db.get_last_open_real_buy(trading_stock.stock_code)
                            
                            # 수익률 계산을 위해 매수가 조회 (콜백 매도)
                            buy_price = None
                            if buy_id and trading_stock.position and trading_stock.position.avg_price:
                                buy_price = trading_stock.position.avg_price
                                profit_rate = ((float(order.price) - buy_price) / buy_price) * 100
                            
                            db.save_real_sell(
                                stock_code=trading_stock.stock_code,
                                stock_name=trading_stock.stock_name,
                                price=float(order.price),
                                quantity=int(order.quantity),
                                strategy=trading_stock.selection_reason,
                                reason="체결(콜백)",
                                buy_record_id=buy_id
                            )
                            
                            
                        except Exception as db_err:
                            self.logger.warning(f"⚠️ 실거래 매도 기록 저장 실패: {db_err}")
                        
                        self.logger.info(f"✅ 매도 체결 처리 완료 (콜백): {trading_stock.stock_code} (수익률: {profit_rate:.2f}%)")
                        
                        # 매도 완료 후 즉시 재거래 준비 (COMPLETED 상태 유지)
                        if self.enable_re_trading:
                            self.logger.info(f"🔄 {trading_stock.stock_code} 즉시 재거래 준비 완료 (COMPLETED 상태 유지)")
                    else:
                        self.logger.warning(f"⚠️ 예상치 못한 상태에서 매도 체결: {trading_stock.state.value}")
                        
        except Exception as e:
            self.logger.error(f"❌ 주문 체결 콜백 처리 오류: {e}")
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """포트폴리오 전체 현황"""
        try:
            with self._lock:
                summary = {
                    'total_stocks': len(self.trading_stocks),
                    'by_state': {},
                    'positions': [],
                    'pending_orders': [],
                    'current_time': now_kst().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # 상태별 종목 수
                for state in StockState:
                    count = len(self.stocks_by_state[state])
                    summary['by_state'][state.value] = count
                
                # 포지션 정보
                positioned_stocks = self.stocks_by_state[StockState.POSITIONED]
                total_value = 0
                total_pnl = 0
                
                for trading_stock in positioned_stocks.values():
                    if trading_stock.position:
                        position_value = trading_stock.position.current_price * trading_stock.position.quantity
                        total_value += position_value
                        total_pnl += trading_stock.position.unrealized_pnl
                        
                        summary['positions'].append({
                            'stock_code': trading_stock.stock_code,
                            'stock_name': trading_stock.stock_name,
                            'quantity': trading_stock.position.quantity,
                            'avg_price': trading_stock.position.avg_price,
                            'current_price': trading_stock.position.current_price,
                            'unrealized_pnl': trading_stock.position.unrealized_pnl,
                            'position_value': position_value
                        })
                
                summary['total_position_value'] = total_value
                summary['total_unrealized_pnl'] = total_pnl
                
                # 미체결 주문 정보
                for state in [StockState.BUY_PENDING, StockState.SELL_PENDING]:
                    for trading_stock in self.stocks_by_state[state].values():
                        if trading_stock.current_order_id:
                            summary['pending_orders'].append({
                                'stock_code': trading_stock.stock_code,
                                'stock_name': trading_stock.stock_name,
                                'order_id': trading_stock.current_order_id,
                                'state': state.value
                            })
                
                return summary
                
        except Exception as e:
            self.logger.error(f"❌ 포트폴리오 요약 생성 오류: {e}")
            return {}
    
    def stop_monitoring(self):
        """모니터링 중단"""
        self.is_monitoring = False
        self.logger.info("🔍 종목 상태 모니터링 중단")
    
    def set_re_trading_config(self, enable: bool):
        """
        재거래 설정 변경
        
        Args:
            enable: 재거래 활성화 여부 (COMPLETED 상태에서 직접 매수 판단)
        """
        self.enable_re_trading = enable
        
        status = "활성화" if enable else "비활성화"
        self.logger.info(f"🔄 재거래 설정 변경: {status} (즉시 재거래 방식)")
    
    def get_re_trading_config(self) -> Dict[str, Any]:
        """재거래 설정 조회"""
        return {
            "enable_re_trading": self.enable_re_trading
        }
    
    
    def remove_stock(self, stock_code: str, reason: str = "") -> bool:
        """종목 제거"""
        try:
            with self._lock:
                if stock_code not in self.trading_stocks:
                    return False
                
                trading_stock = self.trading_stocks[stock_code]
                
                # 상태 변경 후 제거
                self._change_stock_state(stock_code, StockState.COMPLETED, f"제거: {reason}")
                
                # 관련 관리자에서도 제거
                self.intraday_manager.remove_stock(stock_code)
                self.data_collector.remove_candidate_stock(stock_code)
                
                self.logger.info(f"🗑️ {stock_code} 거래 관리에서 제거: {reason}")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 제거 오류: {e}")
            return False
    
    async def handle_order_timeout(self, order):
        """
        OrderManager에서 타임아웃/취소된 주문 처리
        
        BUY_PENDING 상태인 종목을 다시 매수 가능한 상태로 복구합니다.
        
        Args:
            order: 타임아웃된 주문 객체 (Order)
        """
        try:
            stock_code = order.stock_code
            
            with self._lock:
                if stock_code not in self.trading_stocks:
                    self.logger.warning(f"⚠️ 타임아웃 처리할 종목 없음: {stock_code}")
                    return
                
                trading_stock = self.trading_stocks[stock_code]
                
                # BUY_PENDING 상태인 경우에만 처리
                if trading_stock.state != StockState.BUY_PENDING:
                    self.logger.warning(f"⚠️ {stock_code} 예상치 못한 상태에서 타임아웃 처리: {trading_stock.state.value}")
                    return
                
                # 매수 진행 플래그 해제
                trading_stock.is_buying = False
                trading_stock.current_order_id = None
                trading_stock.order_processed = False
                
                # 재거래가 활성화된 경우 COMPLETED로, 비활성화된 경우 SELECTED로 복구
                if self.enable_re_trading:
                    self._change_stock_state(stock_code, StockState.COMPLETED, 
                                          f"주문 타임아웃 복구 (재거래 가능)")
                    self.logger.info(f"🔄 {stock_code} 타임아웃 복구 완료: BUY_PENDING → COMPLETED (재거래 가능)")
                else:
                    self._change_stock_state(stock_code, StockState.SELECTED, 
                                          f"주문 타임아웃 복구")
                    self.logger.info(f"🔄 {stock_code} 타임아웃 복구 완료: BUY_PENDING → SELECTED (매수 재시도 가능)")
                
        except Exception as e:
            self.logger.error(f"❌ {order.stock_code if hasattr(order, 'stock_code') else 'Unknown'} 타임아웃 처리 오류: {e}")