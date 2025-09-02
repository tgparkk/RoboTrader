"""
매매 판단 엔진 - 전략 기반 매수/매도 의사결정
"""
from typing import Tuple, Optional, Dict, Any
import pandas as pd
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.indicators.pullback_candle_pattern import SignalType
from core.timeframe_converter import TimeFrameConverter


class TradingDecisionEngine:
    """
    매매 판단 엔진
    
    주요 기능:
    1. 가격박스 + 이등분선 전략
    2. 볼린저밴드 + 이등분선 전략
    3. 다중 볼린저밴드 전략
    4. 손절/수익실현 조건 검증
    5. 가상 매매 실행
    """
    
    def __init__(self, db_manager=None, telegram_integration=None, trading_manager=None, api_manager=None, intraday_manager=None):
        """
        초기화
        
        Args:
            db_manager: 데이터베이스 관리자
            telegram_integration: 텔레그램 연동
            trading_manager: 거래 종목 관리자
            api_manager: API 관리자 (계좌 정보 조회용)
            intraday_manager: 장중 종목 관리자
        """
        self.logger = setup_logger(__name__)
        self.db_manager = db_manager
        self.telegram = telegram_integration
        self.trading_manager = trading_manager
        self.api_manager = api_manager
        self.intraday_manager = intraday_manager
        
        # 가상 매매 설정
        self.is_virtual_mode = False  # 🆕 가상매매 모드 여부 (False: 실제매매, True: 가상매매)
        
        # 🆕 가상매매 관리자 초기화
        from core.virtual_trading_manager import VirtualTradingManager
        self.virtual_trading = VirtualTradingManager(db_manager=db_manager, api_manager=api_manager)
        
        self.logger.info("🧠 매매 판단 엔진 초기화 완료")
    
    async def analyze_buy_decision(self, trading_stock, combined_data) -> Tuple[bool, str, dict]:
        """
        매수 판단 분석 (가격, 수량 계산 포함)
        
        Args:
            trading_stock: 거래 종목 객체
            combined_data: 1분봉 데이터 (기본 데이터)
            
        Returns:
            Tuple[매수신호여부, 매수사유, 매수정보딕셔너리]
            매수정보: {'buy_price': float, 'quantity': int, 'max_buy_amount': float}
        """
        try:
            stock_code = trading_stock.stock_code
            buy_info = {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
            
            if combined_data is None or len(combined_data) < 10:
                return False, "데이터 부족", buy_info
            
            # 보유 종목 여부 확인 - 이미 보유 중인 종목은 매수하지 않음
            if self._is_already_holding(stock_code):
                return False, f"이미 보유 중인 종목 (매수 제외)", buy_info
            
            # 당일 손실 2회 이상이면 신규 매수 차단 (해제됨)
            # try:
            #     if self.db_manager and hasattr(self.db_manager, 'get_today_real_loss_count'):
            #         today_losses = self.db_manager.get_today_real_loss_count(stock_code)
            #         if today_losses >= 2:
            #             return False, "당일 손실 2회 초과(매수 제한)", buy_info
            # except Exception:
            #     # 조회 실패 시 차단하지 않음
            #     pass
            
            # 🆕 현재 처리 중인 종목 코드 저장 (디버깅용)
            self._current_stock_code = stock_code
            
            # 전략 4: 눌림목 캔들패턴 매수 신호 (3분봉 사용)
            signal_result, reason, price_info = self._check_pullback_candle_buy_signal(combined_data)
            if signal_result and price_info:
                # 매수 신호 발생 시 가격과 수량 계산
                buy_price = price_info['buy_price']
                if buy_price <= 0:
                    # 3/5가 계산 실패시 현재가 사용
                    buy_price = combined_data['close'].iloc[-1]
                    self.logger.debug(f"⚠️ 3/5가 계산 실패, 현재가 사용: {buy_price:,.0f}원")
                
                max_buy_amount = self._get_max_buy_amount()
                quantity = int(max_buy_amount // buy_price) if buy_price > 0 else 0
                
                if quantity > 0:
                    buy_info = {
                        'buy_price': buy_price,
                        'quantity': quantity,
                        'max_buy_amount': max_buy_amount,
                        'entry_low': price_info.get('entry_low', 0),  # 손절 기준
                        'target_profit': price_info.get('target_profit', 0.015)  # 목표 수익률
                    }
                    
                    # 🆕 목표 수익률 저장
                    if hasattr(trading_stock, 'target_profit_rate'):
                        trading_stock.target_profit_rate = price_info.get('target_profit', 0.015)
                    
                    return True, f"눌림목캔들패턴: {reason}", buy_info
                else:
                    return False, "수량 계산 실패", buy_info
            
            return False, f"매수 조건 미충족 (눌림목패턴: {reason})" if reason else "매수 조건 미충족", buy_info
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 판단 오류: {e}")
            return False, f"오류: {e}", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
    
    def _calculate_buy_price(self, combined_data) -> float:
        """매수가 계산 (3/5가 또는 현재가)
        
        @deprecated: generate_improved_signals에서 직접 계산하도록 변경됨
        """
        try:
            current_price = combined_data['close'].iloc[-1]
            
            # 3/5가 계산 시도
            try:
                from core.price_calculator import PriceCalculator
                
                data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
                three_fifths_price, entry_low = PriceCalculator.calculate_three_fifths_price(data_3min, self.logger)
                
                if three_fifths_price is not None:
                    self.logger.debug(f"🎯 3/5가 계산 성공: {three_fifths_price:,.0f}원")
                    return three_fifths_price
                else:
                    self.logger.debug(f"⚠️ 3/5가 계산 실패 → 현재가 사용: {current_price:,.0f}원")
                    return current_price
                    
            except Exception as e:
                self.logger.debug(f"3/5가 계산 오류: {e} → 현재가 사용")
                return current_price
                
        except Exception as e:
            self.logger.error(f"❌ 매수가 계산 오류: {e}")
            return 0
    
    def _get_max_buy_amount(self) -> float:
        """최대 매수 가능 금액 조회 (계좌 잔고의 10%)"""
        max_buy_amount = 500000  # 기본값
        
        try:
            if self.api_manager:
                account_info = self.api_manager.get_account_balance()
                if account_info and hasattr(account_info, 'available_amount'):
                    available_balance = float(account_info.available_amount)
                    max_buy_amount = min(5000000, available_balance * 0.1)  # 최대 500만원
                    self.logger.debug(f"💰 계좌 가용금액: {available_balance:,.0f}원, 투자금액: {max_buy_amount:,.0f}원")
                elif hasattr(account_info, 'total_balance'):
                    total_balance = float(account_info.total_balance)
                    max_buy_amount = min(5000000, total_balance * 0.1)  # 최대 500만원
                    self.logger.debug(f"💰 총 자산: {total_balance:,.0f}원, 투자금액: {max_buy_amount:,.0f}원")
        except Exception as e:
            self.logger.warning(f"⚠️ 계좌 잔고 조회 실패: {e}, 기본값 사용")
        
        return max_buy_amount
    
    async def analyze_sell_decision(self, trading_stock, combined_data) -> Tuple[bool, str]:
        """
        매도 판단 분석
        
        Args:
            trading_stock: 거래 종목 객체
            combined_data: 분봉 데이터
            
        Returns:
            Tuple[매도신호여부, 매도사유]
        """
        try:
            if combined_data is None or len(combined_data) < 30:
                return False, "데이터 부족"
            
            # 🆕 캐시된 실시간 현재가 사용 (매도 판단용)
            stock_code = trading_stock.stock_code
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            
            if current_price_info is not None:
                current_price = current_price_info['current_price']
                self.logger.debug(f"📈 {stock_code} 캐시된 실시간 현재가 사용: {current_price:,.0f}원")
            else:
                # 현재가 정보 없으면 분봉 데이터의 마지막 가격 사용 (폴백)
                current_price = combined_data['close'].iloc[-1]
                self.logger.debug(f"📊 {stock_code} 분봉 데이터 현재가 사용: {current_price:,.0f}원 (캐시 없음)")
            
            # 가상 포지션 정보 복원 (DB에서 미체결 포지션 조회)
            if not trading_stock.position and self.db_manager:
                open_positions = self.db_manager.get_virtual_open_positions()
                stock_positions = open_positions[open_positions['stock_code'] == trading_stock.stock_code]
                
                if not stock_positions.empty:
                    latest_position = stock_positions.iloc[0]
                    buy_record_id = latest_position['id']
                    buy_price = latest_position['buy_price']
                    quantity = latest_position['quantity']
                    
                    # 가상 포지션 정보를 trading_stock에 복원
                    trading_stock.set_virtual_buy_info(buy_record_id, buy_price, quantity)
                    trading_stock.set_position(quantity, buy_price)
                    
                    self.logger.debug(f"🔄 가상 포지션 복원: {trading_stock.stock_code} {quantity}주 @{buy_price:,.0f}원")
            
            # 손절 조건 확인
            stop_loss_signal, stop_reason = self._check_stop_loss_conditions(trading_stock, combined_data)
            if stop_loss_signal:
                return True, f"손절: {stop_reason}"
            
            # 수익실현 조건 확인 (두 전략 모두)
            profit_signal, profit_reason = self._check_profit_target(trading_stock, current_price)
            if profit_signal:
                return True, profit_reason
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매도 판단 오류: {e}")
            return False, f"오류: {e}"
    
    async def execute_real_buy(self, trading_stock, buy_reason, buy_price, quantity):
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
            
            # buy_price가 지정된 경우 사용, 아니면 3/5가 계산 로직 사용
            if buy_price is not None:
                current_price = buy_price
                self.logger.debug(f"📊 {stock_code} 지정된 매수가로 매수: {current_price:,.0f}원")
            else:
                current_price = combined_data['close'].iloc[-1]
                self.logger.debug(f"📊 {stock_code} 현재가로 매수 (기본값): {current_price:,.0f}원")
                
                # 3/5가 계산 (별도 클래스 사용)
                try:
                    from core.price_calculator import PriceCalculator
                    data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
                    
                    three_fifths_price, entry_low = PriceCalculator.calculate_three_fifths_price(data_3min, self.logger)
                    
                    if three_fifths_price is not None:
                        current_price = three_fifths_price
                        self.logger.debug(f"🎯 3/5가로 매수: {stock_code} @{current_price:,.0f}원")
                        
                        # 진입 저가 저장
                        if entry_low is not None:
                            try:
                                setattr(trading_stock, '_entry_low', entry_low)
                            except Exception:
                                pass
                    else:
                        self.logger.debug(f"⚠️ 3/5가 계산 실패 → 현재가 사용: {current_price:,.0f}원")
                        
                except Exception as e:
                    self.logger.debug(f"3/5가 계산 오류: {e} → 현재가 사용")
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
                
                # 신호 강도에 따른 목표수익률 설정
                if "눌림목" in buy_reason:
                    try:
                        target_rate = self._get_target_profit_rate(data_3min, buy_reason)
                        trading_stock.target_profit_rate = target_rate
                        self.logger.info(f"📊 목표수익률 설정: {target_rate*100:.0f}% ({buy_reason})")
                    except Exception as e:
                        self.logger.warning(f"목표수익률 설정 실패, 기본값 사용: {e}")
                        trading_stock.target_profit_rate = 0.02
                
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
            
            # 🆕 캐시된 실시간 현재가 사용 (매도 실행용)
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            
            if current_price_info is not None:
                current_price = current_price_info['current_price']
                self.logger.debug(f"📈 {stock_code} 실시간 현재가로 매도 실행: {current_price:,.0f}원")
            else:
                # 현재가 정보 없으면 분봉 데이터의 마지막 가격 사용 (폴백)
                current_price = combined_data['close'].iloc[-1]
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
                    import sqlite3
                    with sqlite3.connect(self.db_manager.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT strategy FROM virtual_trading_records 
                            WHERE id = ? AND action = 'BUY'
                        ''', (buy_record_id,))
                        
                        result = cursor.fetchone()
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
                    
                    # 가상 포지션 정보 정리
                    trading_stock.clear_virtual_buy_info()
                    
                    # 포지션 정리
                    trading_stock.clear_position()
                    
                    # 손익 계산 (로깅용)
                    profit_loss = (current_price - buy_price) * quantity if buy_price and buy_price > 0 else 0
                    profit_rate = ((current_price - buy_price) / buy_price) * 100 if buy_price and buy_price > 0 else 0
                    profit_sign = "+" if profit_loss >= 0 else ""
                    
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
    
    def _check_stop_loss_conditions(self, trading_stock, data) -> Tuple[bool, str]:
        """손절 조건 확인 (신호강도별 손익비 2:1 적용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            current_price = data['close'].iloc[-1]
            buy_price = trading_stock.position.avg_price
            
            # 신호강도별 손절 기준 (signal_replay.py와 동일)
            target_profit_rate = getattr(trading_stock, 'target_profit_rate', 0.02)  # 기본값 2%
            stop_loss_rate = target_profit_rate / 2.0  # 손익비 2:1
            
            loss_rate = (current_price - buy_price) / buy_price
            if loss_rate <= -stop_loss_rate:
                return True, f"신호강도별손절 {loss_rate*100:.1f}% (기준: -{stop_loss_rate*100:.1f}%)"
            
            # 매수 사유에 따른 추가 기술적 손절 조건 (신호강도별 손절과 병행)
            if "눌림목캔들패턴" in trading_stock.selection_reason:
                technical_stop, technical_reason = self._check_pullback_candle_stop_loss(trading_stock, data, buy_price, current_price)
                if technical_stop:
                    return True, f"기술적손절: {technical_reason}"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 손절 조건 확인 오류: {e}")
            return False, ""
    
    
    def _get_target_profit_rate(self, data_3min: pd.DataFrame, signal_type: str) -> float:
        """신호 강도에 따른 목표수익률 계산"""
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern
            
            # 신호 강도 정보 계산
            signals_improved = PullbackCandlePattern.generate_trading_signals(
                data_3min,
                enable_candle_shrink_expand=False,
                enable_divergence_precondition=False,
                enable_overhead_supply_filter=True,
                use_improved_logic=True,  # 개선된 로직 사용으로 신호 강도 정보 포함
                candle_expand_multiplier=1.10,
                overhead_lookback=10,
                overhead_threshold_hits=2,
                debug=False,
            )
            
            if signals_improved.empty:
                return 0.015  # 기본값 1.5%
            
            # 마지막 신호의 강도 정보 확인
            last_row = signals_improved.iloc[-1]
            
            if 'signal_type' in signals_improved.columns:
                signal_type_val = last_row['signal_type']
                if signal_type_val == SignalType.STRONG_BUY.value:
                    return 0.025  # 최고신호: 2.5%
                elif signal_type_val == SignalType.CAUTIOUS_BUY.value:
                    return 0.02  # 중간신호: 2.0%
            
            # target_profit 컬럼이 있으면 직접 사용
            if 'target_profit' in signals_improved.columns:
                target = last_row['target_profit']
                if pd.notna(target) and target > 0:
                    return float(target)
                    
            return 0.015  # 기본신호: 1.5%
            
        except Exception as e:
            self.logger.warning(f"목표수익률 계산 실패, 기본값 사용: {e}")
            return 0.015
    
    def _check_profit_target(self, trading_stock, current_price) -> Tuple[bool, str]:
        """수익실현 조건 확인 (신뢰도별 차등 목표수익 적용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            buy_price = trading_stock.position.avg_price
            profit_rate = (current_price - buy_price) / buy_price
            
            # 신뢰도별 차등 목표수익률 사용
            target_rate = getattr(trading_stock, 'target_profit_rate', 0.02)
            
            if profit_rate >= target_rate:
                return True, f"매수가 대비 +{target_rate*100:.0f}% 수익실현"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 수익실현 조건 확인 오류: {e}")
            return False, ""
    
    def _is_already_holding(self, stock_code: str) -> bool:
        """
        현재 보유 중인 종목인지 확인
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 보유 중이면 True, 아니면 False
        """
        try:
            if not self.trading_manager:
                # TradingManager가 없으면 안전하게 False 반환
                return False
            
            # TradingStockManager를 통해 보유 종목 확인
            from core.models import StockState
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            
            # 해당 종목이 보유 종목 목록에 있는지 확인
            for stock in positioned_stocks:
                if stock.stock_code == stock_code:
                    self.logger.info(f"📋 보유 종목 확인: {stock_code} (매수 제외)")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 보유 종목 확인 오류 ({stock_code}): {e}")
            # 오류 발생시 안전하게 False 반환 (매수 허용)
            return False
    
    
    

    def _check_pullback_candle_buy_signal(self, data) -> Tuple[bool, str, Optional[Dict[str, float]]]:
        """전략 4: 눌림목 캔들패턴 매수 신호 확인 (3분봉 기준)
        
        Returns:
            Tuple[bool, str, Optional[Dict]]: (신호여부, 사유, 가격정보)
            가격정보: {'buy_price': float, 'entry_low': float, 'target_profit': float}
        """
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
            
            # 필요한 컬럼 확인
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in data.columns for col in required_cols):
                return False, "필요한 데이터 컬럼 부족", None
            
            # 1분봉 데이터를 3분봉으로 변환
            data_3min = TimeFrameConverter.convert_to_3min_data(data)
            if data_3min is None or len(data_3min) < 5:
                self.logger.warning(f"📊 3분봉 데이터 부족: {len(data_3min) if data_3min is not None else 0}개 (최소 5개 필요)")
                return False, f"3분봉 데이터 부족 ({len(data_3min) if data_3min is not None else 0}/5)", None
            
            # 🆕 3분봉 확정 확인 (signal_replay 방식)
            if not self._is_candle_confirmed(data_3min):
                return False, "3분봉 미확정", None
            
            # 🆕 개선된 신호 생성 로직 사용 (3/5가 계산 포함)
            signal_strength = PullbackCandlePattern.generate_improved_signals(
                data_3min,
                stock_code=getattr(self, '_current_stock_code', 'UNKNOWN'),
                debug=True
            )
            
            if signal_strength is None:
                return False, "신호 계산 실패", None
            
            # 매수 신호 확인
            if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                # 신호 이유 생성
                reasons = ' | '.join(signal_strength.reasons)
                signal_desc = f"{signal_strength.signal_type.value} (신뢰도: {signal_strength.confidence:.0f}%)"
                
                # 가격 정보 생성
                price_info = {
                    'buy_price': signal_strength.buy_price,
                    'entry_low': signal_strength.entry_low,
                    'target_profit': signal_strength.target_profit
                }
                
                self.logger.info(f"📊 매수 신호 발생: {signal_desc} - {reasons}")
                self.logger.info(f"💰 매수가격: {signal_strength.buy_price:,.0f}원, 진입저가: {signal_strength.entry_low:,.0f}원")
                
                return True, f"{signal_desc} - {reasons}", price_info
            
            # 매수 신호가 아닌 경우
            if signal_strength.signal_type == SignalType.AVOID:
                reasons = ' | '.join(signal_strength.reasons)
                return False, f"회피신호: {reasons}", None
            elif signal_strength.signal_type == SignalType.WAIT:
                reasons = ' | '.join(signal_strength.reasons)
                return False, f"대기신호: {reasons}", None
            else:
                return False, "신호 조건 미충족", None
            
        except Exception as e:
            self.logger.error(f"❌ 눌림목 캔들패턴 매수 신호 확인 오류: {e}")
            return False, "", None
    
    def _is_candle_confirmed(self, data_3min) -> bool:
        """3분봉 확정 여부 확인 (signal_replay.py와 완전히 동일한 방식)"""
        try:
            if data_3min is None or data_3min.empty or 'datetime' not in data_3min.columns:
                return False
            
            from utils.korean_time import now_kst, KST
            import pandas as pd
            
            current_time = now_kst()
            last_candle_time = pd.to_datetime(data_3min['datetime'].iloc[-1])
            
            # timezone 통일: last_candle_time을 KST로 변환
            if last_candle_time.tz is None:
                last_candle_time = last_candle_time.tz_localize(KST)
            elif last_candle_time.tz != KST:
                last_candle_time = last_candle_time.tz_convert(KST)
            
            # signal_replay.py와 동일한 방식: 라벨 + 3분 경과 후 확정
            # 라벨(ts_3min)은 구간 시작 시각이므로 [라벨, 라벨+2분]을 포함하고,
            # 라벨+3분 경과 후에 봉이 확정됨
            candle_end_time = last_candle_time + pd.Timedelta(minutes=3)
            is_confirmed = current_time >= candle_end_time
            
            self.logger.debug(f"📊 3분봉 확정 체크 (signal_replay 방식): 마지막캔들={last_candle_time.strftime('%H:%M')}, "
                             f"확정시간={candle_end_time.strftime('%H:%M')}, 현재={current_time.strftime('%H:%M')}, "
                             f"확정여부={is_confirmed}")
            
            return is_confirmed
            
        except Exception as e:
            self.logger.debug(f"3분봉 확정 확인 오류: {e}")
            return False
    
    def _log_signal_debug_info(self, data_3min: pd.DataFrame, signals: pd.DataFrame):
        """신호 상태 디버깅 정보 로깅 (signal_replay와 비교용)"""
        try:
            if data_3min.empty or signals.empty:
                return
            
            # 최근 캔들 정보
            last_candle = data_3min.iloc[-1]
            current_time = now_kst().strftime('%H:%M:%S')
            
            # 신호 상태
            buy_pullback = bool(signals['buy_pullback_pattern'].iloc[-1])
            buy_bisector = bool(signals['buy_bisector_recovery'].iloc[-1])
            
            # 이등분선 값
            bisector_val = float(signals['bisector_line'].iloc[-1]) if 'bisector_line' in signals.columns else None
            
            # 디버깅 정보 로깅
            bisector_str = f"{bisector_val:.0f}" if bisector_val is not None else "N/A"
            self.logger.debug(
                f"🔍 신호디버그 [{current_time}]:\n"
                f"  - 3분봉 데이터: {len(data_3min)}개\n"
                f"  - 최근캔들: O={last_candle['open']:.0f} H={last_candle['high']:.0f} "
                f"L={last_candle['low']:.0f} C={last_candle['close']:.0f} V={last_candle['volume']:,.0f}\n"
                f"  - 이등분선: {bisector_str}\n"
                f"  - 매수신호: pullback={buy_pullback}, bisector_recovery={buy_bisector}"
            )
            
        except Exception as e:
            self.logger.debug(f"❌ 신호 디버깅 정보 로깅 오류: {e}")
    
    def verify_signal_consistency(self, stock_code: str, data_3min: pd.DataFrame, target_time: str = None) -> Dict[str, Any]:
        """signal_replay.py와 동일한 방식으로 신호 확인하여 일관성 검증
        
        Args:
            stock_code: 종목 코드
            data_3min: 3분봉 데이터
            target_time: 확인할 시간 (HH:MM 형식, None이면 최신)
            
        Returns:
            Dict: 신호 확인 결과
        """
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern
            
            if data_3min is None or data_3min.empty:
                return {'error': '데이터 없음'}
            
            # signal_replay와 동일한 방식으로 신호 계산
            signals = PullbackCandlePattern.generate_trading_signals(
                data_3min,
                enable_candle_shrink_expand=False,  # ✅ signal_replay.py와 일치
                enable_divergence_precondition=False,  # ✅ signal_replay.py와 일치
                enable_overhead_supply_filter=True,
                candle_expand_multiplier=1.10,
                overhead_lookback=10,
                overhead_threshold_hits=2,
            )
            
            if signals.empty:
                return {'error': '신호 계산 실패'}
            
            # 시간 지정이 없으면 최신 데이터 사용
            if target_time is None:
                idx = len(data_3min) - 1
            else:
                # target_time에 해당하는 인덱스 찾기 (signal_replay.py의 locate_row_for_time과 유사)
                if 'datetime' in data_3min.columns:
                    target_datetime = pd.Timestamp(f"2023-01-01 {target_time}:00")  # 임시 날짜
                    time_diffs = (data_3min['datetime'] - target_datetime).abs()
                    idx = int(time_diffs.idxmin())
                else:
                    idx = len(data_3min) - 1
            
            if idx < 0 or idx >= len(data_3min):
                return {'error': '인덱스 범위 오류'}
            
            # signal_replay와 동일한 방식으로 신호 확인
            buy_pullback = bool(signals['buy_pullback_pattern'].iloc[idx])
            buy_bisector = bool(signals['buy_bisector_recovery'].iloc[idx])
            has_signal = buy_pullback or buy_bisector
            
            signal_types = []
            if buy_pullback:
                signal_types.append("buy_pullback_pattern")
            if buy_bisector:
                signal_types.append("buy_bisector_recovery")
            
            # 미충족 조건 분석 (signal_replay의 analyze_unmet_conditions_at과 유사)
            unmet_conditions = []
            if not has_signal:
                unmet_conditions = self._analyze_unmet_conditions(data_3min, idx)
            
            return {
                'stock_code': stock_code,
                'index': idx,
                'time': target_time or 'latest',
                'has_signal': has_signal,
                'signal_types': signal_types,
                'unmet_conditions': unmet_conditions,
                'data_length': len(data_3min),
                'candle_info': {
                    'open': float(data_3min['open'].iloc[idx]),
                    'high': float(data_3min['high'].iloc[idx]),
                    'low': float(data_3min['low'].iloc[idx]),
                    'close': float(data_3min['close'].iloc[idx]),
                    'volume': float(data_3min['volume'].iloc[idx])
                }
            }
            
        except Exception as e:
            return {'error': f'검증 오류: {e}'}
    
    def _analyze_unmet_conditions(self, data_3min: pd.DataFrame, idx: int) -> list:
        """미충족 조건 분석 (signal_replay의 analyze_unmet_conditions_at과 유사)"""
        try:
            from core.indicators.bisector_line import BisectorLine
            
            unmet = []
            
            if idx < 0 or idx >= len(data_3min):
                return ["인덱스 범위 오류"]
            
            # 이등분선 계산
            bisector_line = BisectorLine.calculate_bisector_line(data_3min['high'], data_3min['low'])
            
            # 현재 캔들 정보
            row = data_3min.iloc[idx]
            current_open = float(row['open'])
            current_close = float(row['close'])
            current_volume = float(row['volume'])
            
            # 이등분선 관련
            bl = float(bisector_line.iloc[idx]) if not pd.isna(bisector_line.iloc[idx]) else None
            above_bisector = (bl is not None) and (current_close >= bl)
            crosses_bisector_up = (bl is not None) and (current_open <= bl <= current_close)
            
            is_bullish = current_close > current_open
            
            # 저거래 조정 확인 (최근 2봉)
            retrace_lookback = 2
            low_vol_ratio = 0.25
            
            if idx >= retrace_lookback:
                window = data_3min.iloc[idx - retrace_lookback:idx]
                baseline_now = float(data_3min['volume'].iloc[max(0, idx - 50):idx + 1].max())
                low_volume_all = bool((window['volume'] < baseline_now * low_vol_ratio).all()) if baseline_now > 0 else False
                close_diff = window['close'].diff().fillna(0)
                downtrend_all = bool((close_diff.iloc[1:] < 0).all()) if len(close_diff) >= 2 else False
                is_low_volume_retrace = low_volume_all and downtrend_all
            else:
                is_low_volume_retrace = False
            
            # 거래량 회복 확인
            if idx > 0:
                max_low_vol = float(data_3min['volume'].iloc[max(0, idx - retrace_lookback):idx].max())
                avg_recent_vol = float(data_3min['volume'].iloc[max(0, idx - 10):idx].mean())
                volume_recovers = (current_volume > max_low_vol) or (current_volume > avg_recent_vol)
            else:
                volume_recovers = False
            
            # 미충족 항목 기록
            if not is_low_volume_retrace:
                unmet.append("저거래 하락 조정 미충족")
            if not is_bullish:
                unmet.append("회복 양봉 아님")
            if not volume_recovers:
                unmet.append("거래량 회복 미충족")
            if not (above_bisector or crosses_bisector_up):
                unmet.append("이등분선 지지/회복 미충족")
            
            return unmet
            
        except Exception as e:
            return [f"분석 오류: {e}"]
    
    def _check_pullback_candle_stop_loss(self, trading_stock, data, buy_price, current_price) -> Tuple[bool, str]:
        """눌림목 캔들패턴 전략 손절 조건 (실시간 가격 + 3분봉 기준)"""
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern
            
            # 1단계: 실시간 가격 기반 신호강도별 손절/익절 체크 (30초마다 체크용)
            if buy_price and buy_price > 0:
                profit_rate = (current_price - buy_price) / buy_price
                
                # 신호강도별 목표수익률 및 손절기준 가져오기 (손익비 2:1)
                target_profit_rate = getattr(trading_stock, 'target_profit_rate', 0.02)  # 기본값 2%
                stop_loss_rate = target_profit_rate / 2.0  # 손익비 2:1
                
                # 신호강도별 손절
                if profit_rate <= -stop_loss_rate:
                    return True, f"⚡신호강도별손절 {profit_rate*100:.1f}% (기준: -{stop_loss_rate*100:.1f}%)"
                
                # 신호강도별 익절
                if profit_rate >= target_profit_rate:
                    return True, f"⚡신호강도별익절 {profit_rate*100:.1f}% (기준: +{target_profit_rate*100:.1f}%)"
                
                # 진입저가 실시간 체크
                entry_low_value = getattr(trading_stock, '_entry_low', None)
                if entry_low_value and entry_low_value > 0:
                    if current_price < entry_low_value * 0.998:  # -0.2%
                        return True, f"⚡실시간진입저가이탈 ({current_price:.0f}<{entry_low_value*0.998:.0f})"
            
            # 2단계: 3분봉 기반 정밀 분석 (기존 로직 유지)
            # 1분봉 데이터를 3분봉으로 변환
            data_3min = TimeFrameConverter.convert_to_3min_data(data)
            if data_3min is None or len(data_3min) < 15:
                return False, ""
            
            # 매도 신호 직접 계산 (in_position 비의존)
            entry_low_value = None
            try:
                entry_low_value = getattr(trading_stock, '_entry_low', None)
            except Exception:
                entry_low_value = None
            sell_signals = PullbackCandlePattern.generate_sell_signals(
                data_3min,
                entry_low=entry_low_value
            )
            
            if sell_signals is None or sell_signals.empty:
                return False, ""
            
            # 손절 조건 1: 이등분선 이탈 (0.2% 기준)
            if 'sell_bisector_break' in sell_signals.columns and bool(sell_signals['sell_bisector_break'].iloc[-1]):
                return True, "📈이등분선이탈(0.2%)"
            
            # 손절 조건 2: 지지 저점 이탈
            if 'sell_support_break' in sell_signals.columns and bool(sell_signals['sell_support_break'].iloc[-1]):
                return True, "📈지지저점이탈"
            
            # 손절 조건 3: 진입 양봉 저가 0.2% 이탈 (entry_low 전달 시에만 유효)
            if 'stop_entry_low_break' in sell_signals.columns and bool(sell_signals['stop_entry_low_break'].iloc[-1]):
                return True, "📈진입양봉저가이탈(0.2%)"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 눌림목 캔들패턴 손절 조건 확인 오류: {e}")
            return False, ""