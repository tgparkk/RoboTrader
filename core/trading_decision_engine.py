"""
매매 판단 엔진 - 전략 기반 매수/매도 의사결정
"""
from typing import Tuple, Optional, Dict, Any
import pandas as pd
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst


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
    
    def __init__(self, db_manager=None, telegram_integration=None, trading_manager=None, api_manager=None):
        """
        초기화
        
        Args:
            db_manager: 데이터베이스 관리자
            telegram_integration: 텔레그램 연동
            trading_manager: 거래 종목 관리자
            api_manager: API 관리자 (계좌 정보 조회용)
        """
        self.logger = setup_logger(__name__)
        self.db_manager = db_manager
        self.telegram = telegram_integration
        self.trading_manager = trading_manager
        self.api_manager = api_manager
        
        # 가상 매매 설정
        self.virtual_investment_amount = 10000  # 기본값 (실제 계좌 조회 실패시 사용)
        self.virtual_balance = 0  # 가상 잔고 (실제 계좌 잔고로 초기화됨)
        self.initial_balance = 0  # 시작 잔고 (수익률 계산용)
        
        # 장 시작 전에 실제 계좌 잔고로 가상 잔고 초기화
        self._initialize_virtual_balance()
        
        self.logger.info("🧠 매매 판단 엔진 초기화 완료")
    
    async def analyze_buy_decision(self, trading_stock, combined_data) -> Tuple[bool, str]:
        """
        매수 판단 분석
        
        Args:
            trading_stock: 거래 종목 객체
            combined_data: 분봉 데이터
            
        Returns:
            Tuple[매수신호여부, 매수사유]
        """
        try:
            stock_code = trading_stock.stock_code
            
            if combined_data is None or len(combined_data) < 30:
                return False, "데이터 부족"
            
            # 보유 종목 여부 확인 - 이미 보유 중인 종목은 매수하지 않음
            if self._is_already_holding(stock_code):
                return False, f"이미 보유 중인 종목 (매수 제외)"
            
            # 전략 1: 가격박스 + 이등분선 매수 신호
            signal_result, reason = self._check_price_box_bisector_buy_signal(combined_data)
            if signal_result:
                return True, f"가격박스+이등분선: {reason}"
            
            ## 전략 2: 볼린저밴드 + 이등분선 매수 신호
            #signal_result, reason = self._check_bollinger_bisector_buy_signal(combined_data)
            #if signal_result:
            #    return True, f"볼린저밴드+이등분선: {reason}"
            
            # 전략 3: 다중 볼린저밴드 매수 신호
            signal_result, reason = self._check_multi_bollinger_buy_signal(combined_data)
            if signal_result:
                return True, f"다중볼린저밴드: {reason}"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 판단 오류: {e}")
            return False, f"오류: {e}"
    
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
            
            current_price = combined_data['close'].iloc[-1]
            
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
                    trading_stock._virtual_buy_record_id = buy_record_id
                    trading_stock._virtual_buy_price = buy_price
                    trading_stock._virtual_quantity = quantity
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
    
    async def execute_virtual_buy(self, trading_stock, combined_data, buy_reason):
        """가상 매수 실행"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            current_price = combined_data['close'].iloc[-1]
            
            # 가상 매수 수량 설정 (가상 잔고 확인)
            if self.virtual_balance < self.virtual_investment_amount:
                self.logger.warning(f"⚠️ 가상 잔고 부족: {self.virtual_balance:,.0f}원 < {self.virtual_investment_amount:,.0f}원")
                return
            
            quantity = max(1, int(self.virtual_investment_amount / current_price))
            total_cost = quantity * current_price
            
            # 전략명 추출
            if "가격박스" in buy_reason:
                strategy = "가격박스+이등분선"
            elif "다중볼린저밴드" in buy_reason:
                strategy = "다중볼린저밴드"
            else:
                strategy = "볼린저밴드+이등분선"
            
            # DB에 가상 매수 기록 저장
            if self.db_manager:
                buy_record_id = self.db_manager.save_virtual_buy(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=current_price,
                    quantity=quantity,
                    strategy=strategy,
                    reason=buy_reason
                )
                
                if buy_record_id:
                    # 가상 잔고에서 매수 금액 차감
                    self._update_virtual_balance(-total_cost, "매수")
                    
                    # 가상 포지션 정보를 trading_stock에 저장
                    trading_stock._virtual_buy_record_id = buy_record_id
                    trading_stock._virtual_buy_price = current_price
                    trading_stock._virtual_quantity = quantity
                    
                    # 포지션 상태로 변경 (가상)
                    trading_stock.set_position(quantity, current_price)
                    
                    self.logger.info(f"🎯 가상 매수 완료: {stock_code}({stock_name}) "
                                   f"{quantity}주 @{current_price:,.0f}원 총 {total_cost:,.0f}원")
                    
                    # 텔레그램 알림
                    if self.telegram:
                        await self.telegram.notify_signal_detected({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'signal_type': '가상매수',
                            'price': current_price,
                            'reason': f"{strategy} - {buy_reason}"
                        })
            
        except Exception as e:
            self.logger.error(f"❌ 가상 매수 실행 오류: {e}")
    
    async def execute_virtual_sell(self, trading_stock, combined_data, sell_reason):
        """가상 매도 실행"""
        try:
            stock_code = trading_stock.stock_code
            stock_name = trading_stock.stock_name
            current_price = combined_data['close'].iloc[-1]
            
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
            
            # 전략명 추출
            if "가격박스" in sell_reason:
                strategy = "가격박스+이등분선"
            elif "다중볼린저밴드" in sell_reason:
                strategy = "다중볼린저밴드"
            else:
                strategy = "볼린저밴드+이등분선"
            
            # DB에 가상 매도 기록 저장
            if self.db_manager and buy_record_id:
                success = self.db_manager.save_virtual_sell(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    price=current_price,
                    quantity=quantity,
                    strategy=strategy,
                    reason=sell_reason,
                    buy_record_id=buy_record_id
                )
                
                if success:
                    # 가상 잔고에 매도 금액 추가
                    total_received = quantity * current_price
                    self._update_virtual_balance(total_received, "매도")
                    
                    # 가상 포지션 정보 정리
                    for attr in ['_virtual_buy_record_id', '_virtual_buy_price', '_virtual_quantity']:
                        if hasattr(trading_stock, attr):
                            delattr(trading_stock, attr)
                    
                    # 포지션 정리
                    trading_stock.clear_position()
                    
                    # 손익 계산 및 로깅
                    profit_loss = (current_price - buy_price) * quantity
                    profit_rate = ((current_price - buy_price) / buy_price) * 100
                    profit_sign = "+" if profit_loss >= 0 else ""
                    
                    self.logger.info(f"🎯 가상 매도 완료: {stock_code}({stock_name}) "
                                   f"{quantity}주 @{current_price:,.0f}원 "
                                   f"손익: {profit_sign}{profit_loss:,.0f}원 ({profit_rate:+.2f}%)")
                    
                    # 텔레그램 알림
                    if self.telegram:
                        await self.telegram.notify_signal_detected({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'signal_type': '가상매도',
                            'price': current_price,
                            'reason': f"{strategy} - {sell_reason} (손익: {profit_sign}{profit_loss:,.0f}원)"
                        })
            
        except Exception as e:
            self.logger.error(f"❌ 가상 매도 실행 오류: {e}")
    
    def _check_price_box_bisector_buy_signal(self, data) -> Tuple[bool, str]:
        """전략 1: 가격박스 + 이등분선 매수 신호 확인"""
        try:
            from core.indicators.price_box import PriceBox
            from core.indicators.bisector_line import BisectorLine
            
            # 필요한 컬럼 확인
            required_cols = ['open', 'high', 'low', 'close']
            if not all(col in data.columns for col in required_cols):
                return False, ""
            
            # 이등분선 계산
            bisector_signals = BisectorLine.generate_trading_signals(data)
            
            # 이등분선 위에 있는지 확인 (필수 조건)
            if not bisector_signals['bullish_zone'].iloc[-1]:
                return False, "이등분선 아래"
            
            # 가격박스 신호 계산
            prices = data['close']
            box_signals = PriceBox.generate_trading_signals(prices)
            
            current_idx = len(box_signals) - 1
            
            # 매수 조건 1: 첫 박스하한선 터치 (가장 확률 높음)
            if box_signals['first_lower_touch'].iloc[-1]:
                return True, "첫 박스하한선 터치"
            
            # 매수 조건 2: 박스하한선 지지 확인 후 박스중심선 돌파
            for i in range(max(0, current_idx-5), current_idx):
                if (box_signals['support_bounce'].iloc[i] and 
                    box_signals['center_breakout_up'].iloc[-1]):
                    return True, "박스하한선 지지 후 중심선 돌파"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 가격박스+이등분선 매수 신호 확인 오류: {e}")
            return False, ""
    
    def _check_bollinger_bisector_buy_signal(self, data) -> Tuple[bool, str]:
        """전략 2: 볼린저밴드 + 이등분선 매수 신호 확인"""
        try:
            from core.indicators.bollinger_bands import BollingerBands
            from core.indicators.bisector_line import BisectorLine
            
            # 필요한 컬럼 확인
            required_cols = ['open', 'high', 'low', 'close']
            if not all(col in data.columns for col in required_cols):
                return False, ""
            
            # 이등분선 계산
            bisector_signals = BisectorLine.generate_trading_signals(data)
            
            # 이등분선 위에 있는지 확인 (필수 조건)
            if not bisector_signals['bullish_zone'].iloc[-1]:
                return False, "이등분선 아래"
            
            # 볼린저밴드 신호 계산
            prices = data['close']
            bb_signals = BollingerBands.generate_trading_signals(prices)
            
            current_idx = len(bb_signals) - 1
            
            # 밴드 폭 상태 확인 (최근 20개 기준)
            recent_band_width = bb_signals['band_width'].iloc[-20:].mean()
            total_band_width = bb_signals['band_width'].mean()
            is_squeezed = recent_band_width < total_band_width * 0.7  # 밀집 판단
            
            if is_squeezed:
                # 밴드 폭 밀집 시
                # 1. 상한선 돌파 매수
                if bb_signals['upper_breakout'].iloc[-1]:
                    return True, "상한선 돌파 (밀집)"
                
                # 2. 상한선 돌파 확인 후 조정매수 (3/4, 2/4 지점)
                for i in range(max(0, current_idx-10), current_idx):
                    if bb_signals['upper_breakout'].iloc[i]:
                        # 돌파했던 양봉의 3/4, 2/4 지점 계산
                        breakout_candle_high = data['high'].iloc[i]
                        breakout_candle_low = data['low'].iloc[i]
                        current_price = data['close'].iloc[-1]
                        
                        three_quarter = breakout_candle_low + (breakout_candle_high - breakout_candle_low) * 0.75
                        half_point = breakout_candle_low + (breakout_candle_high - breakout_candle_low) * 0.5
                        
                        if (abs(current_price - three_quarter) / three_quarter < 0.01 or
                            abs(current_price - half_point) / half_point < 0.01):
                            return True, "상한선 돌파 후 조정매수"
                        break
            else:
                # 밴드 폭 확장 시
                # 첫 하한선 지지 매수
                if bb_signals['lower_touch'].iloc[-1] or bb_signals['oversold'].iloc[-1]:
                    # 지지 확인 (반등)
                    if len(data) >= 2 and data['close'].iloc[-1] > data['close'].iloc[-2]:
                        return True, "첫 하한선 지지 (확장)"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 볼린저밴드+이등분선 매수 신호 확인 오류: {e}")
            return False, ""
    
    def _check_multi_bollinger_buy_signal(self, data) -> Tuple[bool, str]:
        """전략 3: 다중 볼린저밴드 매수 신호 확인 (5분봉 기준)"""
        try:
            from core.indicators.multi_bollinger_bands import MultiBollingerBands
            
            # 필요한 컬럼 확인
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in data.columns for col in required_cols):
                return False, "필요한 데이터 컬럼 부족"
            
            # 1분봉 데이터를 5분봉으로 변환
            data_5min = self._convert_to_5min_data(data)
            if data_5min is None or len(data_5min) < 30:
                return False, "5분봉 데이터 부족"
            
            prices = data_5min['close']
            volume_data = data_5min['volume'] if 'volume' in data_5min.columns else None
            
            # 다중 볼린저밴드 신호 계산 (5분봉 기준)
            signals = MultiBollingerBands.generate_trading_signals(prices, volume_data)
            
            current_idx = len(signals) - 1
            
            # 매수 조건: 다중볼밴 돌파신호 (새로운 강세패턴)
            if signals['buy_multi_breakout'].iloc[-1]:
                return True, "다중볼밴 돌파신호"
            
            # 기존 매수 조건들 (보조 신호로 유지)
            # 매수 조건 1: 밀집된 상한선 돌파 시 매수
            if signals['buy_breakout'].iloc[-1]:
                return True, "상한선 밀집 돌파"
            
            # 매수 조건 2: 조정 매수 (돌파 후 되돌림)
            if signals['potential_retracement_buy'].iloc[-1]:
                return True, "돌파 후 조정 매수"
            
            # 매수 조건 3: 중심선 지지 매수
            if signals['buy_center_support'].iloc[-1]:
                return True, "중심선 지지 매수"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 다중볼린저밴드 매수 신호 확인 오류: {e}")
            return False, ""
    
    def _check_stop_loss_conditions(self, trading_stock, data) -> Tuple[bool, str]:
        """손절 조건 확인"""
        try:
            if not trading_stock.position:
                return False, ""
            
            current_price = data['close'].iloc[-1]
            buy_price = trading_stock.position.avg_price
            
            # 공통 손절: 매수가 대비 -3% 손실
            loss_rate = (current_price - buy_price) / buy_price
            if loss_rate <= -0.03:
                return True, "매수가 대비 -3% 손실"
            
            # 매수 사유에 따른 개별 손절 조건
            if "가격박스" in trading_stock.selection_reason:
                return self._check_price_box_stop_loss(data, buy_price, current_price)
            elif "다중볼린저밴드" in trading_stock.selection_reason:
                return self._check_multi_bollinger_stop_loss(data, buy_price, current_price)
            elif "볼린저밴드" in trading_stock.selection_reason:
                return self._check_bollinger_stop_loss(data, buy_price, current_price, trading_stock)
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 손절 조건 확인 오류: {e}")
            return False, ""
    
    def _check_price_box_stop_loss(self, data, buy_price, current_price) -> Tuple[bool, str]:
        """가격박스 전략 손절 조건"""
        try:
            from core.indicators.price_box import PriceBox
            from core.indicators.bisector_line import BisectorLine
            
            # 박스중심선 이탈
            box_signals = PriceBox.generate_trading_signals(data['close'])
            if current_price < box_signals['center_line'].iloc[-1]:
                return True, "박스중심선 이탈"
            
            # 이등분선 이탈
            bisector_signals = BisectorLine.generate_trading_signals(data)
            if not bisector_signals['bullish_zone'].iloc[-1]:
                return True, "이등분선 이탈"
            
            # 직전저점(첫 마디 저점) 이탈 - 간단히 최근 10개 중 최저점으로 대체
            if len(data) >= 10:
                recent_low = data['low'].iloc[-10:].min()
                if current_price < recent_low:
                    return True, "직전저점 이탈"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 가격박스 손절 조건 확인 오류: {e}")
            return False, ""
    
    def _check_bollinger_stop_loss(self, data, buy_price, current_price, trading_stock) -> Tuple[bool, str]:
        """볼린저밴드 전략 손절 조건"""
        try:
            from core.indicators.bollinger_bands import BollingerBands
            
            bb_signals = BollingerBands.generate_trading_signals(data['close'])
            
            # 매수 사유별 손절
            if "상한선 돌파" in trading_stock.selection_reason:
                # 돌파 양봉의 저가 이탈 또는 중심선 이탈
                if current_price < bb_signals['sma'].iloc[-1]:
                    return True, "볼린저 중심선 이탈"
                    
                # 돌파 양봉 저가 찾기 (최근 10개 중)
                for i in range(max(0, len(data)-10), len(data)):
                    if bb_signals['upper_breakout'].iloc[i]:
                        breakout_low = data['low'].iloc[i]
                        if current_price < breakout_low:
                            return True, "돌파 양봉 저가 이탈"
                        break
                        
            elif "하한선 지지" in trading_stock.selection_reason:
                # 지지 캔들 저가 이탈
                for i in range(max(0, len(data)-10), len(data)):
                    if (bb_signals['lower_touch'].iloc[i] or bb_signals['oversold'].iloc[i]):
                        support_low = data['low'].iloc[i]
                        if current_price < support_low:
                            return True, "지지 캔들 저가 이탈"
                        break
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 볼린저밴드 손절 조건 확인 오류: {e}")
            return False, ""
    
    def _check_multi_bollinger_stop_loss(self, data, buy_price, current_price) -> Tuple[bool, str]:
        """다중 볼린저밴드 전략 손절 조건 (5분봉 기준)"""
        try:
            from core.indicators.multi_bollinger_bands import MultiBollingerBands
            
            # 1분봉 데이터를 5분봉으로 변환
            data_5min = self._convert_to_5min_data(data)
            if data_5min is None or len(data_5min) < 20:
                return False, "5분봉 데이터 부족"
            
            prices = data_5min['close']
            volume_data = data_5min['volume'] if 'volume' in data_5min.columns else None
            
            # 다중 볼린저밴드 신호 계산 (5분봉 기준)
            signals = MultiBollingerBands.generate_trading_signals(prices, volume_data)
            
            # 손절 조건 1: 이등분선 이탈
            if signals['stop_bisector'].iloc[-1]:
                return True, "이등분선 이탈"
            
            # 손절 조건 2: 중심선(20기간 SMA) 이탈
            if signals['stop_center'].iloc[-1]:
                return True, "중심선 이탈"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 다중볼린저밴드 손절 조건 확인 오류: {e}")
            return False, ""
    
    def _check_profit_target(self, trading_stock, current_price) -> Tuple[bool, str]:
        """수익실현 조건 확인 (두 전략 모두)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            buy_price = trading_stock.position.avg_price
            profit_rate = (current_price - buy_price) / buy_price
            
            # 매수가 대비 +2.5% 수익실현 (두 전략 모두)
            if profit_rate >= 0.025:
                return True, "매수가 대비 +2.5% 수익실현"
            
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
    
    def _initialize_virtual_balance(self):
        """실제 계좌 잔고로 가상 잔고 초기화"""
        try:
            if not self.api_manager:
                self.logger.warning("⚠️ API 관리자가 없어 가상 잔고를 기본값으로 설정")
                self.virtual_balance = 1000000  # 100만원 기본값
                self.initial_balance = self.virtual_balance
                return
            
            # 실제 계좌 잔고 조회
            account_info = self.api_manager.get_account_balance_quick()
            
            if account_info and account_info.available_amount > 0:
                self.virtual_balance = account_info.available_amount
                self.initial_balance = self.virtual_balance
                self.virtual_investment_amount = self.virtual_balance * 0.20  # 잔고의 20%
                
                self.logger.info(f"💰 가상 잔고 초기화: {self.virtual_balance:,.0f}원 (실제 계좌 기준)")
                self.logger.info(f"💵 건당 투자금액: {self.virtual_investment_amount:,.0f}원")
            else:
                # 계좌 조회 실패시 기본값 사용
                self.virtual_balance = 1000000  # 100만원 기본값
                self.initial_balance = self.virtual_balance
                self.logger.warning(f"⚠️ 계좌 조회 실패로 가상 잔고를 기본값으로 설정: {self.virtual_balance:,.0f}원")
                
        except Exception as e:
            # 오류 발생시 기본값 사용
            self.virtual_balance = 1000000  # 100만원 기본값
            self.initial_balance = self.virtual_balance
            self.logger.error(f"❌ 가상 잔고 초기화 오류: {e}")
            self.logger.info(f"💰 가상 잔고를 기본값으로 설정: {self.virtual_balance:,.0f}원")
    
    def _update_virtual_balance(self, amount: float, transaction_type: str):
        """가상 잔고 업데이트"""
        try:
            old_balance = self.virtual_balance
            self.virtual_balance += amount
            
            # 수익률 계산
            profit_rate = ((self.virtual_balance - self.initial_balance) / self.initial_balance) * 100 if self.initial_balance > 0 else 0
            
            self.logger.info(f"💰 가상 잔고 업데이트 ({transaction_type}): {old_balance:,.0f}원 → {self.virtual_balance:,.0f}원 "
                           f"(변동: {amount:+,.0f}원, 총수익률: {profit_rate:+.2f}%)")
            
        except Exception as e:
            self.logger.error(f"❌ 가상 잔고 업데이트 오류: {e}")
    
    def get_virtual_balance_info(self) -> dict:
        """가상 잔고 정보 반환"""
        try:
            profit_amount = self.virtual_balance - self.initial_balance
            profit_rate = (profit_amount / self.initial_balance) * 100 if self.initial_balance > 0 else 0
            
            return {
                'current_balance': self.virtual_balance,
                'initial_balance': self.initial_balance,
                'profit_amount': profit_amount,
                'profit_rate': profit_rate,
                'investment_per_trade': self.virtual_investment_amount
            }
        except Exception as e:
            self.logger.error(f"❌ 가상 잔고 정보 조회 오류: {e}")
            return {}
    
    def _convert_to_5min_data(self, data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """1분봉 데이터를 5분봉으로 변환"""
        try:
            if data is None or len(data) < 5:
                return None
            
            # 시간 컬럼 확인 및 변환
            if 'datetime' in data.columns:
                data = data.copy()
                data['datetime'] = pd.to_datetime(data['datetime'])
                data = data.set_index('datetime')
            elif 'date' in data.columns and 'time' in data.columns:
                data = data.copy()
                # date와 time을 datetime으로 결합
                data['datetime'] = pd.to_datetime(data['date'].astype(str) + ' ' + data['time'].astype(str))
                data = data.set_index('datetime')
            else:
                # datetime 인덱스가 없으면 인덱스를 생성
                data = data.copy()
                data.index = pd.date_range(start='09:00', periods=len(data), freq='1min')
            
            # HTS와 동일하게 09:00 기준 5분봉으로 리샘플링
            # 수동으로 5분 단위로 그룹핑하여 정확한 시간 맞춤
            data_5min_list = []
            
            # 5분 단위로 그룹핑 (09:00~09:05, 09:05~09:10, ...)
            for i in range(0, len(data), 5):
                group = data.iloc[i:i+5]
                if len(group) > 0:
                    # 5분봉 시간은 그룹의 마지막 시간 사용
                    end_time = group.index[-1]
                    
                    data_5min_list.append({
                        'datetime': end_time,
                        'open': group['open'].iloc[0],
                        'high': group['high'].max(),
                        'low': group['low'].min(), 
                        'close': group['close'].iloc[-1],
                        'volume': group['volume'].sum()
                    })
            
            data_5min = pd.DataFrame(data_5min_list)
            
            self.logger.debug(f"📊 HTS 방식 5분봉 변환: {len(data)}개 → {len(data_5min)}개 완료")
            if not data_5min.empty:
                self.logger.debug(f"시간 범위: {data_5min['datetime'].iloc[0]} ~ {data_5min['datetime'].iloc[-1]}")
            
            return data_5min
            
        except Exception as e:
            self.logger.error(f"❌ 5분봉 변환 오류: {e}")
            return None