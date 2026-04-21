"""
매매 실행 모듈

TradingDecisionEngine에서 분리된 매수/매도 실행 로직
"""
from typing import Optional
from utils.logger import setup_logger


class TradeExecutor:
    """
    매매 실행 담당 클래스

    책임:
    - 실제 매수/매도 주문 실행
    - 가상 매수/매도 실행
    - 거래 기록 관리
    """

    def __init__(self, engine):
        """
        초기화

        Args:
            engine: TradingDecisionEngine 인스턴스 (의존성 주입)
        """
        self.engine = engine
        self.logger = engine.logger
        self.db_manager = engine.db_manager
        self.telegram = engine.telegram
        self.trading_manager = engine.trading_manager
        self.api_manager = engine.api_manager
        self.intraday_manager = engine.intraday_manager
        self.virtual_trading = engine.virtual_trading
        self.config = engine.config

    async def execute_real_buy(self, trading_stock, buy_reason, buy_price, quantity, candle_time=None):
        """실제 매수 주문 실행 (사전 계산된 가격, 수량 사용)"""
        try:
            stock_code = trading_stock.stock_code

            if quantity <= 0:
                self.logger.warning(f"⚠️ {stock_code} 매수 주문 실패: 수량 0")
                return False

            if buy_price <= 0:
                self.logger.warning(f"⚠️ {stock_code} 매수 주문 실패: 가격 0")
                return False

            # 실제 매수 주문 실행
            from core.trading_stock_manager import TradingStockManager
            if hasattr(self, 'trading_manager') and isinstance(self.trading_manager, TradingStockManager):
                success = await self.trading_manager.execute_buy_order(
                    stock_code=stock_code,
                    price=buy_price,
                    quantity=quantity,
                    reason=buy_reason
                )

                if success:
                    # 매수 성공 시 신호 캔들 시점 업데이트 (중복 신호 방지)
                    if candle_time:
                        trading_stock.last_signal_candle_time = candle_time
                        self.logger.debug(f"🎯 {stock_code} 신호 캔들 시점 저장: {candle_time.strftime('%H:%M')}")

                    self.logger.info(f"🔥 {stock_code} 실제 매수 주문 완료: {quantity}주 @{buy_price:,.0f}원")
                    return True
                else:
                    self.logger.error(f"❌ {stock_code} 실제 매수 주문 실패")
                    return False
            else:
                self.logger.error(f"❌ TradingStockManager 참조 오류")
                return False

        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 실제 매수 처리 오류: {e}")
            return False

    async def execute_virtual_buy(self, trading_stock, combined_data, buy_reason, buy_price=None):
        """가상 매수 실행"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name

            # buy_price가 지정된 경우 사용, 아니면 4/5가 계산 로직 사용
            if buy_price is not None:
                current_price = buy_price
                self.logger.debug(f"📊 {stock_code} 지정된 매수가로 매수: {current_price:,.0f}원")
            else:
                current_price = self.engine._safe_float_convert(combined_data['close'].iloc[-1])
                self.logger.debug(f"📊 {stock_code} 현재가로 매수 (기본값): {current_price:,.0f}원")

                # 4/5가 계산 (별도 클래스 사용)
                try:
                    from core.price_calculator import PriceCalculator
                    from core.timeframe_converter import TimeFrameConverter
                    data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)

                    four_fifths_price, entry_low = PriceCalculator.calculate_three_fifths_price(data_3min, self.logger)

                    if four_fifths_price is not None:
                        current_price = four_fifths_price
                        self.logger.debug(f"🎯 4/5가로 매수: {stock_code} @{current_price:,.0f}원")

                        # 진입 저가 저장
                        if entry_low is not None:
                            try:
                                setattr(trading_stock, '_entry_low', entry_low)
                            except Exception:
                                pass
                    else:
                        self.logger.debug(f"⚠️ 4/5가 계산 실패 → 현재가 사용: {current_price:,.0f}원")

                except Exception as e:
                    self.logger.debug(f"4/5가 계산 오류: {e} → 현재가 사용")
                    # 계산 실패 시 현재가 유지

            # 가상 매수 수량 설정 (VirtualTradingManager 사용)
            quantity = self.virtual_trading.get_max_quantity(current_price)
            if quantity <= 0:
                self.logger.warning(f"⚠️ 매수 불가: 잔고 부족 또는 가격 오류")
                return

            # 전략명 추출
            if "가격박스" in buy_reason:
                strategy = "가격박스+이등분선"
            elif "다중볼린저밴드" in buy_reason:
                strategy = "다중볼린저밴드"
            elif "눌림목캔들패턴" in buy_reason:
                strategy = "눌림목캔들패턴"
            elif "score" in buy_reason.lower() or "weighted" in buy_reason.lower():
                strategy = "weighted_score"
            elif "종가매매" in buy_reason or "closing_trade" in buy_reason.lower():
                strategy = "closing_trade"
            else:
                strategy = "볼린저밴드+이등분선"

            # 가상 매수 실행 (VirtualTradingManager 사용)
            buy_record_id = self.virtual_trading.execute_virtual_buy(
                stock_code=stock_code,
                stock_name=stock_name,
                price=current_price,
                quantity=quantity,
                strategy=strategy,
                reason=buy_reason
            )

            if buy_record_id:
                # 가상 포지션 정보를 trading_stock에 저장
                trading_stock.set_virtual_buy_info(buy_record_id, current_price, quantity)

                # 목표수익률 설정 (기본값 사용)
                trading_stock.target_profit_rate = 0.03

                # 포지션 상태로 변경 (가상)
                trading_stock.set_position(quantity, current_price)

                # 총 매수금액 계산
                total_cost = quantity * current_price

                self.logger.info(f"🎯 가상 매수 완료: {stock_code}({stock_name}) "
                                f"{quantity}주 @{current_price:,.0f}원 총 {total_cost:,.0f}원")

                # 텔레그램 알림
                if self.telegram:
                    await self.telegram.notify_signal_detected({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'signal_type': '🔴 매수',
                        'price': current_price,
                        'reason': f"{strategy} - {buy_reason}"
                    })

        except Exception as e:
            self.logger.error(f"❌ 가상 매수 실행 오류: {e}")

    async def execute_real_sell(self, trading_stock, sell_reason):
        """실제 매도 주문 실행 (판단 로직 제외, 주문만 처리)"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name

            # 보유 포지션 확인
            if not trading_stock.position or trading_stock.position.quantity <= 0:
                self.logger.warning(f"⚠️ {stock_code} 매도 주문 실패: 보유 포지션 없음")
                return False

            quantity = trading_stock.position.quantity

            # 시장가 매도 주문 실행
            success = await self.trading_manager.execute_sell_order(
                stock_code=stock_code,
                quantity=quantity,
                price=0,  # 시장가 (가격 미지정)
                reason=sell_reason,
                market=True  # 시장가 주문 플래그
            )

            if success:
                self.logger.info(f"📉 {stock_code}({stock_name}) 시장가 매도 주문 완료: {quantity}주 - {sell_reason}")
            else:
                self.logger.error(f"❌ {stock_code} 시장가 매도 주문 실패")

            return success

        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 실제 매도 처리 오류: {e}")
            return False

    async def execute_virtual_sell(self, trading_stock, combined_data, sell_reason):
        """가상 매도 실행"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name

            # 캐시된 실시간 현재가 사용 (매도 실행용)
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)

            if current_price_info is not None:
                current_price = current_price_info['current_price']
                self.logger.debug(f"📈 {stock_code} 실시간 현재가로 매도 실행: {current_price:,.0f}원")
            else:
                # 현재가 정보 없으면 분봉 데이터의 마지막 가격 사용 (폴백)
                current_price = self.engine._safe_float_convert(combined_data['close'].iloc[-1])
                self.logger.warning(f"📊 {stock_code} 분봉 데이터로 매도 실행: {current_price:,.0f}원 (실시간 현재가 없음)")

            # 가상 매수 기록 정보 가져오기
            buy_record_id = getattr(trading_stock, '_virtual_buy_record_id', None)
            buy_price = getattr(trading_stock, '_virtual_buy_price', None)
            quantity = getattr(trading_stock, '_virtual_quantity', None)

            # DB에서 미체결 포지션 조회 (위 정보가 없는 경우)
            if not buy_record_id and self.db_manager:
                open_positions = self.db_manager.get_virtual_open_positions()
                stock_positions = open_positions[open_positions['stock_code'] == stock_code]

                if not stock_positions.empty:
                    latest_position = stock_positions.iloc[0]
                    buy_record_id = latest_position['id']
                    buy_price = latest_position['buy_price']
                    quantity = latest_position['quantity']
                else:
                    self.logger.warning(f"⚠️ {stock_code} 가상 매수 기록을 찾을 수 없음")
                    return

            # 매수 기록에서 전략명 가져오기
            strategy = None
            if buy_record_id and self.db_manager:
                try:
                    result = self.db_manager._fetchone('''
                        SELECT strategy FROM virtual_trading_records
                        WHERE id = %s AND action = 'BUY'
                    ''', (buy_record_id,))

                    if result:
                        strategy = result[0]
                        self.logger.debug(f"📊 {stock_code} 매수 기록에서 전략명 조회: {strategy}")
                except Exception as e:
                    self.logger.error(f"❌ 매수 기록 전략명 조회 오류: {e}")

            # 전략명을 찾지 못한 경우 기존 로직 사용 (fallback)
            if not strategy:
                if "가격박스" in sell_reason:
                    strategy = "가격박스+이등분선"
                elif "다중볼린저밴드" in sell_reason:
                    strategy = "다중볼린저밴드"
                elif "눌림목캔들패턴" in sell_reason:
                    strategy = "눌림목캔들패턴"
                elif "가격위치전략" in sell_reason:
                    strategy = "가격위치전략"
                else:
                    strategy = "볼린저밴드+이등분선"

            # 가상 매도 실행 (VirtualTradingManager 사용)
            if buy_record_id:
                success = self.virtual_trading.execute_virtual_sell(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=current_price,
                    quantity=quantity,
                    strategy=strategy,
                    reason=sell_reason,
                    buy_record_id=buy_record_id
                )

                if success:
                    # 손익 계산 (로깅용)
                    profit_loss = (current_price - buy_price) * quantity if buy_price and buy_price > 0 else 0
                    profit_rate = ((current_price - buy_price) / buy_price) * 100 if buy_price and buy_price > 0 else 0
                    profit_sign = "+" if profit_loss >= 0 else ""

                    # 패턴 데이터 매매 결과 업데이트
                    pattern_logger = getattr(self.engine, 'pattern_logger', None)
                    if pattern_logger and hasattr(trading_stock, 'last_pattern_id') and trading_stock.last_pattern_id:
                        try:
                            pattern_logger.update_trade_result(
                                pattern_id=trading_stock.last_pattern_id,
                                trade_executed=True,
                                profit_rate=profit_rate,
                                sell_reason=sell_reason
                            )
                            self.logger.debug(f"📝 패턴 매매 결과 업데이트 완료: {trading_stock.last_pattern_id}")
                        except Exception as log_err:
                            self.logger.warning(f"⚠️ 패턴 매매 결과 업데이트 실패: {log_err}")

                    # 가상 포지션 정보 정리
                    trading_stock.clear_virtual_buy_info()

                    # 포지션 정리
                    trading_stock.clear_position()

                    # 텔레그램 알림
                    if self.telegram:
                        await self.telegram.notify_signal_detected({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'signal_type': '🔵 매도',
                            'price': current_price,
                            'reason': f"{strategy} - {sell_reason} (손익: {profit_sign}{profit_loss:,.0f}원)"
                        })

        except Exception as e:
            self.logger.error(f"❌ 가상 매도 실행 오류: {e}")
