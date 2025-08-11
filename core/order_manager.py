"""
주문 관리 및 미체결 처리 모듈
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from .models import Order, OrderType, OrderStatus, TradingConfig
from api.kis_api_manager import KISAPIManager, OrderResult
from utils.logger import setup_logger
from utils.korean_time import now_kst, is_market_open


class OrderManager:
    """주문 관리자"""
    
    def __init__(self, config: TradingConfig, api_manager: KISAPIManager, telegram_integration=None):
        self.config = config
        self.api_manager = api_manager
        self.telegram = telegram_integration
        self.logger = setup_logger(__name__)
        self.trading_manager = None  # TradingStockManager (선택 연결)
        
        self.pending_orders: Dict[str, Order] = {}  # order_id: Order
        self.order_timeouts: Dict[str, datetime] = {}  # order_id: timeout_time
        self.completed_orders: List[Order] = []  # 완료된 주문 기록
        
        self.is_monitoring = False
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    def set_trading_manager(self, trading_manager):
        """TradingStockManager 참조를 등록 (가격 정정 시 주문ID 동기화용)"""
        self.trading_manager = trading_manager
    
    async def place_buy_order(self, stock_code: str, quantity: int, price: float, 
                             timeout_seconds: int = None) -> Optional[str]:
        """매수 주문 실행"""
        try:
            timeout_seconds = timeout_seconds or self.config.order_management.buy_timeout_seconds
            
            self.logger.info(f"📈 매수 주문 시도: {stock_code} {quantity}주 @{price:,.0f}원 (타임아웃: {timeout_seconds}초)")
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            result: OrderResult = await loop.run_in_executor(
                self.executor,
                self.api_manager.place_buy_order,
                stock_code, quantity, int(price)
            )
            
            if result.success:
                order = Order(
                    order_id=result.order_id,
                    stock_code=stock_code,
                    order_type=OrderType.BUY,
                    price=price,
                    quantity=quantity,
                    timestamp=now_kst(),
                    status=OrderStatus.PENDING,
                    remaining_quantity=quantity
                )
                
                # 미체결 관리에 추가
                self.pending_orders[result.order_id] = order
                self.order_timeouts[result.order_id] = now_kst() + timedelta(seconds=timeout_seconds)
                
                self.logger.info(f"✅ 매수 주문 성공: {result.order_id} - {stock_code} {quantity}주 @{price:,.0f}원")
                
                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_order_placed({
                        'stock_code': stock_code,
                        'stock_name': f'Stock_{stock_code}',  # TODO: 실제 종목명 조회
                        'order_type': 'buy',
                        'quantity': quantity,
                        'price': price,
                        'order_id': result.order_id
                    })
                
                return result.order_id
            else:
                self.logger.error(f"❌ 매수 주문 실패: {result.message}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 매수 주문 예외: {e}")
            return None
    
    async def place_sell_order(self, stock_code: str, quantity: int, price: float,
                              timeout_seconds: int = None, market: bool = False) -> Optional[str]:
        """매도 주문 실행"""
        try:
            timeout_seconds = timeout_seconds or self.config.order_management.sell_timeout_seconds
            
            self.logger.info(f"📉 매도 주문 시도: {stock_code} {quantity}주 @{price:,.0f}원 (타임아웃: {timeout_seconds}초, 시장가: {market})")
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            result: OrderResult = await loop.run_in_executor(
                self.executor,
                self.api_manager.place_sell_order,
                stock_code, quantity, int(price), ("01" if market else "00")
            )
            
            if result.success:
                order = Order(
                    order_id=result.order_id,
                    stock_code=stock_code,
                    order_type=OrderType.SELL,
                    price=price,
                    quantity=quantity,
                    timestamp=now_kst(),
                    status=OrderStatus.PENDING,
                    remaining_quantity=quantity
                )
                
                # 미체결 관리에 추가
                self.pending_orders[result.order_id] = order
                self.order_timeouts[result.order_id] = now_kst() + timedelta(seconds=timeout_seconds)
                
                self.logger.info(f"✅ 매도 주문 성공: {result.order_id} - {stock_code} {quantity}주 @{price:,.0f}원 ({'시장가' if market else '지정가'})")
                
                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_order_placed({
                        'stock_code': stock_code,
                        'stock_name': f'Stock_{stock_code}',  # TODO: 실제 종목명 조회
                        'order_type': 'sell_market' if market else 'sell',
                        'quantity': quantity,
                        'price': price,
                        'order_id': result.order_id
                    })
                
                return result.order_id
            else:
                self.logger.error(f"❌ 매도 주문 실패: {result.message}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 매도 주문 예외: {e}")
            return None
    
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        try:
            if order_id not in self.pending_orders:
                self.logger.warning(f"취소할 주문을 찾을 수 없음: {order_id}")
                return False
            
            order = self.pending_orders[order_id]
            self.logger.info(f"주문 취소 시도: {order_id} ({order.stock_code})")
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            result: OrderResult = await loop.run_in_executor(
                self.executor,
                self.api_manager.cancel_order,
                order_id, order.stock_code
            )
            
            if result.success:
                order.status = OrderStatus.CANCELLED
                self._move_to_completed(order_id)
                self.logger.info(f"✅ 주문 취소 성공: {order_id}")
                
                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_order_cancelled({
                        'stock_code': order.stock_code,
                        'stock_name': f'Stock_{order.stock_code}',
                        'order_type': order.order_type.value
                    }, "사용자 요청")
                
                return True
            else:
                self.logger.error(f"❌ 주문 취소 실패: {order_id} - {result.message}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 주문 취소 예외: {order_id} - {e}")
            return False
    
    async def start_monitoring(self):
        """미체결 주문 모니터링 시작"""
        self.is_monitoring = True
        self.logger.info("주문 모니터링 시작")
        
        while self.is_monitoring:
            try:
                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                await self._monitor_pending_orders()
                await asyncio.sleep(10)  # 10초마다 체크
                
            except Exception as e:
                self.logger.error(f"주문 모니터링 중 오류: {e}")
                await asyncio.sleep(10)
    
    async def _monitor_pending_orders(self):
        """미체결 주문 모니터링"""
        current_time = now_kst()
        orders_to_process = list(self.pending_orders.keys())
        
        for order_id in orders_to_process:
            try:
                order = self.pending_orders[order_id]
                timeout_time = self.order_timeouts.get(order_id)
                
                # 1. 체결 상태 확인
                await self._check_order_status(order_id)
                
                # 2. 타임아웃 체크
                if timeout_time and current_time > timeout_time:
                    await self._handle_timeout(order_id)
                
                # 3. 가격 변동 시 정정 검토
                await self._check_price_adjustment(order_id)
                
            except Exception as e:
                self.logger.error(f"주문 모니터링 중 오류 {order_id}: {e}")
    
    async def _check_order_status(self, order_id: str):
        """주문 상태 확인"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            
            # API 호출을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            status_data = await loop.run_in_executor(
                self.executor,
                self.api_manager.get_order_status,
                order_id
            )
            
            if status_data:
                filled_qty = int(status_data.get('tot_ccld_qty', 0))
                remaining_qty = int(status_data.get('rmn_qty', 0))
                cancelled = status_data.get('cncl_yn', 'N')
                
                # 상태 업데이트
                order.filled_quantity = filled_qty
                order.remaining_quantity = remaining_qty
                
                if cancelled == 'Y':
                    order.status = OrderStatus.CANCELLED
                    self._move_to_completed(order_id)
                    self.logger.info(f"주문 취소 확인: {order_id}")
                elif filled_qty == order.quantity:
                    order.status = OrderStatus.FILLED
                    self._move_to_completed(order_id)
                    self.logger.info(f"✅ 주문 완전 체결: {order_id} ({order.stock_code})")
                    
                    # 텔레그램 체결 알림
                    if self.telegram:
                        await self.telegram.notify_order_filled({
                            'stock_code': order.stock_code,
                            'stock_name': f'Stock_{order.stock_code}',
                            'order_type': order.order_type.value,
                            'quantity': order.quantity,
                            'price': order.price
                        })
                elif filled_qty > 0:
                    order.status = OrderStatus.PARTIAL
                    self.logger.info(f"🔄 주문 부분 체결: {order_id} - {filled_qty}/{order.quantity}")
                
        except Exception as e:
            self.logger.error(f"주문 상태 확인 실패 {order_id}: {e}")
    
    async def _handle_timeout(self, order_id: str):
        """타임아웃 처리"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            self.logger.warning(f"⏰ 주문 타임아웃: {order_id} ({order.stock_code})")
            
            # 미체결 주문 취소
            await self.cancel_order(order_id)
            
        except Exception as e:
            self.logger.error(f"타임아웃 처리 실패 {order_id}: {e}")
    
    async def _check_price_adjustment(self, order_id: str):
        """가격 정정 검토"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            
            # 최대 정정 횟수 체크
            if order.adjustment_count >= self.config.order_management.max_adjustments:
                return
            
            # 현재가 조회
            loop = asyncio.get_event_loop()
            price_data = await loop.run_in_executor(
                self.executor,
                self.api_manager.get_current_price,
                order.stock_code
            )
            
            if not price_data:
                return
            
            current_price = price_data.current_price
            
            # 정정 로직
            should_adjust = False
            new_price = order.price
            
            if order.order_type == OrderType.BUY:
                # 매수: 현재가가 주문가보다 0.5% 이상 높으면 정정
                if current_price > order.price * 1.005:
                    new_price = current_price * 1.001  # 현재가 + 0.1%
                    should_adjust = True
            else:  # SELL
                # 매도: 현재가가 주문가보다 0.5% 이상 낮으면 정정
                if current_price < order.price * 0.995:
                    new_price = current_price * 0.999  # 현재가 - 0.1%
                    should_adjust = True
            
            if should_adjust:
                await self._adjust_order_price(order_id, new_price)
                
        except Exception as e:
            self.logger.error(f"가격 정정 검토 실패 {order_id}: {e}")
    
    async def _adjust_order_price(self, order_id: str, new_price: float):
        """주문 가격 정정"""
        try:
            if order_id not in self.pending_orders:
                return
            
            order = self.pending_orders[order_id]
            old_price = order.price
            
            self.logger.info(f"가격 정정 시도: {order_id} {old_price:,.0f}원 → {new_price:,.0f}원")
            
            # 기존 주문 취소 후 새 주문 생성 방식
            # (KIS API는 정정 API가 복잡하므로 취소 후 재주문으로 구현)
            cancel_success = await self.cancel_order(order_id)
            
            if cancel_success:
                # 새 주문 생성
                if order.order_type == OrderType.BUY:
                    new_order_id = await self.place_buy_order(
                        order.stock_code, 
                        order.remaining_quantity, 
                        new_price
                    )
                else:
                    new_order_id = await self.place_sell_order(
                        order.stock_code, 
                        order.remaining_quantity, 
                        new_price
                    )
                
                if new_order_id:
                    # 정정 횟수 증가
                    new_order = self.pending_orders[new_order_id]
                    new_order.adjustment_count = order.adjustment_count + 1
                    self.logger.info(f"✅ 가격 정정 완료: {new_order_id}")
                    # 🔄 TradingStockManager의 현재 주문ID를 신규 주문ID로 동기화
                    try:
                        if self.trading_manager is not None:
                            self.trading_manager.update_current_order(order.stock_code, new_order_id)
                    except Exception as sync_err:
                        self.logger.warning(f"⚠️ 주문ID 동기화 실패({order.stock_code}): {sync_err}")
                
        except Exception as e:
            self.logger.error(f"가격 정정 실패 {order_id}: {e}")
    
    def _move_to_completed(self, order_id: str):
        """완료된 주문으로 이동"""
        if order_id in self.pending_orders:
            order = self.pending_orders.pop(order_id)
            self.completed_orders.append(order)
            
            # 타임아웃 정보도 제거
            if order_id in self.order_timeouts:
                del self.order_timeouts[order_id]
    
    def get_pending_orders(self) -> List[Order]:
        """미체결 주문 목록 반환"""
        return list(self.pending_orders.values())
    
    def get_completed_orders(self) -> List[Order]:
        """완료된 주문 목록 반환"""
        return self.completed_orders.copy()
    
    def get_order_summary(self) -> dict:
        """주문 요약 정보"""
        return {
            'pending_count': len(self.pending_orders),
            'completed_count': len(self.completed_orders),
            'pending_orders': [
                {
                    'order_id': order.order_id,
                    'stock_code': order.stock_code,
                    'type': order.order_type.value,
                    'price': order.price,
                    'quantity': order.quantity,
                    'status': order.status.value,
                    'filled': order.filled_quantity
                }
                for order in self.pending_orders.values()
            ]
        }
    
    def stop_monitoring(self):
        """모니터링 중단"""
        self.is_monitoring = False
        self.logger.info("주문 모니터링 중단")
    
    def __del__(self):
        """소멸자"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)