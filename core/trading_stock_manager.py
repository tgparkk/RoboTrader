"""
종목 거래 상태 통합 관리 모듈
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import threading
from collections import defaultdict

from .models import TradingStock, StockState, OrderType, OrderStatus
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
        self.monitor_interval = 10  # 10초마다 상태 체크
        
        # 재거래 설정
        self.enable_re_trading = True  # 매도 완료 후 재거래 허용
        self.re_trading_wait_minutes = 0  # 매도 완료 후 재거래까지 대기 시간(분) - 즉시 재거래
        
        self.logger.info("🎯 종목 거래 상태 통합 관리자 초기화 완료")
        # 주문 관리자에 역참조 등록 (정정 시 주문ID 동기화용)
        try:
            if hasattr(self.order_manager, 'set_trading_manager'):
                self.order_manager.set_trading_manager(self)
        except Exception:
            pass
    
    async def add_selected_stock(self, stock_code: str, stock_name: str, 
                                selection_reason: str = "") -> bool:
        """
        조건검색으로 선정된 종목 추가 (비동기)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            selection_reason: 선정 사유
            
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
                    selection_reason=selection_reason
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
    
    def move_to_buy_candidate(self, stock_code: str, reason: str = "") -> bool:
        """
        선정된 종목을 매수 후보로 변경
        
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
                
                # 상태 검증
                if trading_stock.state != StockState.SELECTED:
                    self.logger.warning(f"⚠️ {stock_code}: 선정 상태가 아님 (현재: {trading_stock.state.value})")
                    return False
                
                # 상태 변경
                self._change_stock_state(stock_code, StockState.BUY_CANDIDATE, reason)
                
                # 데이터 수집기에 후보 종목으로 추가
                self.data_collector.add_candidate_stock(stock_code, trading_stock.stock_name)
                
                self.logger.info(f"📈 {stock_code} 매수 후보로 변경: {reason}")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 매수 후보 변경 오류: {e}")
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
                
                # 상태 검증
                if trading_stock.state != StockState.BUY_CANDIDATE:
                    self.logger.warning(f"⚠️ {stock_code}: 매수 후보 상태가 아님 (현재: {trading_stock.state.value})")
                    return False
                
                # 매수 주문 중 상태로 변경
                self._change_stock_state(stock_code, StockState.BUY_PENDING, f"매수 주문: {reason}")
            
            # 매수 주문 실행
            order_id = await self.order_manager.place_buy_order(stock_code, quantity, price)
            
            if order_id:
                with self._lock:
                    trading_stock = self.trading_stocks[stock_code]
                    trading_stock.add_order(order_id)
                
                self.logger.info(f"📈 {stock_code} 매수 주문 성공: {order_id}")
                return True
            else:
                # 주문 실패 시 매수 후보로 되돌림
                with self._lock:
                    self._change_stock_state(stock_code, StockState.BUY_CANDIDATE, "매수 주문 실패")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 매수 주문 오류: {e}")
            # 오류 시 매수 후보로 되돌림
            with self._lock:
                if stock_code in self.trading_stocks:
                    self._change_stock_state(stock_code, StockState.BUY_CANDIDATE, f"매수 주문 오류: {e}")
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
                
                # 상태 검증
                if trading_stock.state != StockState.POSITIONED:
                    self.logger.warning(f"⚠️ {stock_code}: 포지션 상태가 아님 (현재: {trading_stock.state.value})")
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
            
            # 주문 관리자에서 완료된 주문 확인
            completed_orders = self.order_manager.get_completed_orders()
            for order in completed_orders:
                if (order.order_id == trading_stock.current_order_id and 
                    order.stock_code == trading_stock.stock_code):
                    
                    if order.status == OrderStatus.FILLED:
                        # 매수 완료 - 포지션 상태로 변경
                        with self._lock:
                            trading_stock.set_position(order.quantity, order.price)
                            trading_stock.clear_current_order()
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
                            self._change_stock_state(
                                trading_stock.stock_code, 
                                StockState.BUY_CANDIDATE, 
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
                        try:
                            from db.database_manager import DatabaseManager
                            db = DatabaseManager()
                            buy_id = db.get_last_open_real_buy(trading_stock.stock_code)
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
                        
                        self.logger.info(f"✅ {trading_stock.stock_code} 매도 완료")
                        
                        # 매도 완료 후 재거래 스케줄링
                        if self.enable_re_trading:
                            asyncio.create_task(self._schedule_re_trading(trading_stock))
                        
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
    
    async def _schedule_re_trading(self, trading_stock: TradingStock):
        """매도 완료된 종목의 재거래 스케줄링"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            
            # 대기 시간 계산
            wait_seconds = self.re_trading_wait_minutes * 60
            
            if wait_seconds > 0:
                self.logger.info(f"🔄 {stock_code}({stock_name}) 재거래 스케줄: {self.re_trading_wait_minutes}분 후")
                # 지정된 시간만큼 대기
                await asyncio.sleep(wait_seconds)
            else:
                self.logger.info(f"🔄 {stock_code}({stock_name}) 즉시 재거래 시작")
            
            # 장 마감 시간 체크 (재거래는 시간 제한 없음)
            # if not is_market_open():
            #     self.logger.info(f"⏰ {stock_code} 재거래 취소 - 장 마감")
            #     return
            
            # 종목이 여전히 COMPLETED 상태인지 확인 (중간에 제거되거나 다른 상태로 변경될 수 있음)
            with self._lock:
                if stock_code not in self.trading_stocks:
                    self.logger.info(f"⚠️ {stock_code} 재거래 취소 - 종목이 관리 목록에서 제거됨")
                    return
                
                current_stock = self.trading_stocks[stock_code]
                if current_stock.state != StockState.COMPLETED:
                    self.logger.info(f"⚠️ {stock_code} 재거래 취소 - 상태 변경됨 (현재: {current_stock.state.value})")
                    return
                
                # SELECTED 상태로 변경하여 재거래 준비
                current_stock.selected_time = now_kst()
                current_stock.selection_reason = f"재거래 (이전: {trading_stock.selection_reason})"
                # 포지션/주문 정보는 이미 정리됨
                self._change_stock_state(stock_code, StockState.SELECTED, "자동 재거래 시작")
            
            # IntradayStockManager에 다시 추가
            success = await self.intraday_manager.add_selected_stock(
                stock_code, stock_name, f"재거래 (이전: {trading_stock.selection_reason})"
            )
            
            if success:
                self.logger.info(f"🔄 {stock_code}({stock_name}) 재거래 시작")
            else:
                # 실패 시 다시 COMPLETED 상태로 되돌림
                with self._lock:
                    if stock_code in self.trading_stocks:
                        self._change_stock_state(stock_code, StockState.COMPLETED, "재거래 시작 실패")
                self.logger.warning(f"⚠️ {stock_code} 재거래 시작 실패")
                
        except asyncio.CancelledError:
            self.logger.info(f"🔄 {trading_stock.stock_code} 재거래 스케줄 취소됨")
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 재거래 스케줄링 오류: {e}")
    
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
            if new_state == StockState.BUY_CANDIDATE:
                log_parts.append("🎯 매수 신호 발생 - 주문 대기 중")
            elif new_state == StockState.BUY_PENDING:
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
    
    def set_re_trading_config(self, enable: bool, wait_minutes: int = 5):
        """
        재거래 설정 변경
        
        Args:
            enable: 재거래 활성화 여부
            wait_minutes: 매도 완료 후 재거래까지 대기 시간(분)
        """
        self.enable_re_trading = enable
        self.re_trading_wait_minutes = max(0, wait_minutes)  # 최소 0분 (즉시 가능)
        
        status = "활성화" if enable else "비활성화"
        self.logger.info(f"🔄 재거래 설정 변경: {status}, 대기시간: {self.re_trading_wait_minutes}분")
    
    def get_re_trading_config(self) -> Dict[str, Any]:
        """재거래 설정 조회"""
        return {
            "enable_re_trading": self.enable_re_trading,
            "re_trading_wait_minutes": self.re_trading_wait_minutes
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