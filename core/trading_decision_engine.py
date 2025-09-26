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
        
        # 🆕 설정 파일에서 쿨다운 시간 로드
        from config.settings import load_trading_config
        self.trading_config = load_trading_config()
        self.buy_cooldown_minutes = self.trading_config.order_management.buy_cooldown_minutes
        
        # 🆕 쿨다운 관리
        self.stock_cooldown_end = {}  # 종목별 쿨다운 종료 시간 추적
        
        # 🆕 일봉 기반 패턴 필터 초기화
        try:
            from core.indicators.daily_pattern_filter import DailyPatternFilter
            self.daily_pattern_filter = DailyPatternFilter(logger=self.logger)
            self.use_daily_filter = True
            self.logger.info("📊 일봉 기반 패턴 필터 초기화 완료")
        except Exception as e:
            self.logger.warning(f"⚠️ 일봉 패턴 필터 초기화 실패: {e}")
            self.daily_pattern_filter = None
            self.use_daily_filter = False

        # 🆕 간단한 패턴 필터 초기화 (시뮬과 동일)
        try:
            from core.indicators.simple_pattern_filter import SimplePatternFilter
            self.simple_pattern_filter = SimplePatternFilter(logger=self.logger)
            self.use_simple_filter = True
            self.logger.info("🛡️ 간단한 패턴 필터 초기화 완료")
        except Exception as e:
            self.logger.warning(f"⚠️ 간단한 패턴 필터 초기화 실패: {e}")
            self.simple_pattern_filter = None
            self.use_simple_filter = False
        
        # ML 설정 로드 (실시간에서는 비활성화)
        try:
            from config.ml_settings import MLSettings
            self.use_ml_filter = False  # 실시간에서는 ML 필터 비활성화
            self.use_hardcoded_ml = False  # 실시간에서는 하드코딩 ML 비활성화
            self.ml_settings = MLSettings
        except ImportError:
            self.use_ml_filter = False
            self.use_hardcoded_ml = False
            self.ml_settings = None
        
        # ML 예측기 초기화 (비활성화)
        self.ml_predictor = None
        self.hardcoded_ml_predictor = None
        
        # 실시간에서는 ML 사용하지 않음
        # if self.use_hardcoded_ml:
        #     self._initialize_hardcoded_ml()
        # elif self.use_ml_filter:
        #     self._initialize_ml_predictor()
        
        self.logger.info("🧠 매매 판단 엔진 초기화 완료")

    def _initialize_hardcoded_ml(self):
        """하드코딩된 경량 ML 예측기 초기화"""
        try:
            from trade_analysis.hardcoded_ml_predictor import HardcodedMLPredictor
            
            self.hardcoded_ml_predictor = HardcodedMLPredictor()
            
            if self.hardcoded_ml_predictor.is_ready:
                self.logger.info("⚡ 하드코딩된 경량 ML 예측기 초기화 완료")
            else:
                self.logger.warning("⚠️ 하드코딩된 ML 예측기 준비 실패")
                self.use_hardcoded_ml = False
                
        except Exception as e:
            self.logger.error(f"❌ 하드코딩된 ML 예측기 초기화 실패: {e}")
            self.use_hardcoded_ml = False
            self.hardcoded_ml_predictor = None
    
    # 기존 ML 관련 메소드들 (현재 비활성화)
    # def _initialize_ml_predictor(self):
    #     """ML 예측기 초기화 (선택적) - 현재 비활성화"""  
    #     pass
    
    async def _apply_hardcoded_ml_filter(self, trading_stock, signal_type: str = "pullback_pattern") -> Tuple[bool, str, Dict[str, Any]]:
        """
        하드코딩된 경량 ML 필터 적용 (빠른 예측)
        
        Returns:
            Tuple[통과여부, 사유, ML예측결과]
        """
        try:
            if not self.use_hardcoded_ml or not self.hardcoded_ml_predictor:
                return True, "하드코딩된 ML 비활성화", {}
            
            stock_code = trading_stock.stock_code
            
            # 실제 특성 추출 (2단계 구현)
            real_features = await self._extract_real_time_features(trading_stock)
            
            # 빠른 예측 실행
            ml_result = self.hardcoded_ml_predictor.predict_trade_outcome_fast(real_features)
            
            if "error" in ml_result:
                self.logger.warning(f"⚠️ {stock_code} 하드코딩 ML 예측 오류: {ml_result['error']}")
                return True, "ML 예측 오류 - 신호 통과", {}
            
            # 예측 결과 분석
            recommendation = ml_result.get('recommendation', {})
            action = recommendation.get('action', 'SKIP')
            win_probability = recommendation.get('win_probability', 0.0)
            expected_profit = recommendation.get('expected_profit', 0.0)
            
            # 필터링 조건 (완화된 임계값)
            if action in ['STRONG_BUY', 'BUY']:
                return True, f"⚡ML승인: {action} (승률:{win_probability:.1%})", ml_result
            elif action == 'WEAK_BUY' and win_probability >= 0.45:  # 55% → 45%로 완화
                return True, f"⚡ML조건부승인: {action} (승률:{win_probability:.1%})", ml_result
            else:
                return False, f"⚡ML차단: {action} (승률:{win_probability:.1%})", ml_result
                
        except Exception as e:
            self.logger.error(f"❌ 하드코딩 ML 필터 적용 오류: {e}")
            return True, "ML 필터 오류 - 신호 통과", {}
    
    async def _extract_real_time_features(self, trading_stock) -> Dict[str, float]:
        """
        실시간 특성 추출 (2단계 구현)
        
        Args:
            trading_stock: 거래 종목 객체
            
        Returns:
            69개 특성 딕셔너리
        """
        try:
            # 실시간 특성 추출기 import
            from trade_analysis.realtime_feature_extractor import RealtimeFeatureExtractor
            
            extractor = RealtimeFeatureExtractor()
            stock_code = trading_stock.stock_code
            
            # 분봉 데이터 가져오기 (가능한 경우)
            minute_data = None
            current_price = None
            
            # intraday_manager에서 분봉 데이터 조회 시도
            if self.intraday_manager:
                try:
                    # 캐시된 분봉 데이터 조회
                    minute_data = self.intraday_manager.get_cached_minute_data(stock_code)
                    
                    # 캐시된 현재가 조회
                    current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
                    if current_price_info:
                        current_price = current_price_info.get('current_price')
                        
                except Exception as e:
                    self.logger.debug(f"분봉 데이터 조회 실패 ({stock_code}): {e}")
            
            # 일봉 데이터 조회 (intraday_manager에서 캐시된 데이터 사용)
            daily_data = None
            
            # intraday_manager에서 캐시된 일봉 데이터 조회
            if self.intraday_manager:
                try:
                    # StockMinuteData 객체에서 daily_data 필드 조회
                    if hasattr(self.intraday_manager, 'selected_stocks') and stock_code in self.intraday_manager.selected_stocks:
                        stock_data = self.intraday_manager.selected_stocks[stock_code]
                        daily_data = stock_data.daily_data
                        if daily_data is not None and not daily_data.empty:
                            self.logger.debug(f"📊 {stock_code} 캐시된 일봉 데이터 사용: {len(daily_data)}개")
                        else:
                            self.logger.debug(f"⚠️ {stock_code} 캐시된 일봉 데이터 없음")
                    else:
                        self.logger.debug(f"⚠️ {stock_code} 종목이 intraday_manager에 등록되지 않음")
                except Exception as e:
                    self.logger.debug(f"캐시된 일봉 데이터 조회 실패 ({stock_code}): {e}")
            
            # 캐시된 데이터가 없으면 폴백 (시뮬레이션용)
            if daily_data is None or daily_data.empty:
                try:
                    from trade_analysis.ml_data_collector import MLDataCollector
                    collector = MLDataCollector()
                    daily_data = collector.collect_daily_data(stock_code, 60)
                    if daily_data is not None:
                        self.logger.debug(f"📊 {stock_code} 폴백 일봉 데이터 수집 성공: {len(daily_data)}개")
                    else:
                        self.logger.debug(f"⚠️ {stock_code} 폴백 일봉 데이터 수집 실패")
                except Exception as e:
                    self.logger.debug(f"⚠️ {stock_code} 폴백 일봉 데이터 수집 오류: {e}")
            
            # 분봉 데이터가 있으면 실제 특성 추출
            if minute_data is not None and len(minute_data) > 10:
                self.logger.debug(f"🔄 {stock_code} 실제 특성 추출 (분봉: {len(minute_data)}개, 일봉: {len(daily_data) if daily_data is not None else 0}개)")
                features = extractor.extract_features_from_minute_data(minute_data, daily_data, current_price)
                
                # 특성 품질 로깅 (주요 특성만)
                if len(features) >= 10:
                    self.logger.debug(f"   주요 특성: 가격={features['feature_0']:.3f}, "
                                    f"변화율={features['feature_1']:.3f}, "
                                    f"볼륨={features['feature_20']:.3f}, "
                                    f"일봉MA5={features['feature_60']:.3f}")
                
                return features
            else:
                # 데이터가 없으면 기본 특성 사용 (1단계 방식)
                self.logger.debug(f"⚠️ {stock_code} 분봉 데이터 부족, 기본 특성 사용")
                return {f'feature_{i}': 0.5 for i in range(69)}
                
        except Exception as e:
            self.logger.warning(f"❌ 실시간 특성 추출 실패 ({stock_code}): {e}")
            # 에러 시 기본 특성 반환
            return {f'feature_{i}': 0.5 for i in range(69)}
    
    # 기존 ML 필터 (비활성화)
    # async def _apply_ml_filter(self, trading_stock, signal_type: str = "pullback_pattern") -> Tuple[bool, str, Dict[str, Any]]:
    #     """기존 ML 필터 - 현재 비활성화 (백테스팅 전용)"""
    #     return True, "기존 ML 필터 비활성화", {}

    def _safe_float_convert(self, value):
        """쉼표가 포함된 문자열을 안전하게 float로 변환"""
        if pd.isna(value) or value is None:
            return 0.0
        try:
            # 문자열로 변환 후 쉼표 제거
            str_value = str(value).replace(',', '')
            return float(str_value)
        except (ValueError, TypeError):
            return 0.0
    
    async def analyze_buy_decision(self, trading_stock, combined_data) -> Tuple[bool, str, dict]:
        """
        매수 판단 분석 (가격, 수량 계산 포함)
        
        Args:
            trading_stock: 거래 종목 객체
            combined_data: 3분봉 데이터 (기본 데이터)
            
        Returns:
            Tuple[매수신호여부, 매수사유, 매수정보딕셔너리]
            매수정보: {'buy_price': float, 'quantity': int, 'max_buy_amount': float}
        """
        try:
            stock_code = trading_stock.stock_code
            buy_info = {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
            
            if combined_data is None or len(combined_data) < 5:
                return False, "데이터 부족", buy_info
            
            # 보유 종목 여부 확인 - 이미 보유 중인 종목은 매수하지 않음
            if self._is_already_holding(stock_code):
                return False, f"이미 보유 중인 종목 (매수 제외)", buy_info
            
            # 🆕 30분 쿨다운 체크
            current_time = now_kst()
            if stock_code in self.stock_cooldown_end:
                cooldown_end_time = self.stock_cooldown_end[stock_code]
                if current_time < cooldown_end_time:
                    remaining_minutes = int((cooldown_end_time - current_time).total_seconds() / 60)
                    return False, f"30분 쿨다운 중 ({remaining_minutes}분 남음)", buy_info
            
            # 동일 캔들 중복 신호 차단 - 3분 단위로 정규화해서 비교
            raw_candle_time = combined_data['datetime'].iloc[-1]
            # 3분 단위로 정규화 (09:00, 09:03, 09:06...)
            minute_normalized = (raw_candle_time.minute // 3) * 3
            current_candle_time = raw_candle_time.replace(minute=minute_normalized, second=0, microsecond=0)
            
            if (trading_stock.last_signal_candle_time and 
                trading_stock.last_signal_candle_time == current_candle_time):
                return False, f"동일 캔들 중복신호 차단 ({current_candle_time.strftime('%H:%M')})", buy_info
            
            # 당일 손실 2회 이상이면 신규 매수 차단 (해제됨)
            # try:
            #     if self.db_manager and hasattr(self.db_manager, 'get_today_real_loss_count'):
            #         today_losses = self.db_manager.get_today_real_loss_count(stock_code)
            #         if today_losses >= 2:
            #             return False, "당일 손실 2회 초과(매수 제한)", buy_info
            # except Exception:
            #     # 조회 실패 시 차단하지 않음
            #     pass

            # 🆕 전일 종가 대비 22% 이상 상승 종목 매수 금지
            current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
            prev_close = getattr(trading_stock, 'prev_close', 0.0)

            
            # prev_close가 없으면 intraday_manager에서 가져오기 시도
            if prev_close <= 0 and self.intraday_manager:
                try:
                    stock_data = self.intraday_manager.get_stock_data(stock_code)
                    if stock_data and hasattr(stock_data, 'prev_close'):
                        prev_close = stock_data.prev_close
                except Exception:
                    pass

            if prev_close > 0:
                price_change_pct = ((current_price - prev_close) / prev_close) * 100
                if price_change_pct >= 22.0:
                    return False, f"전일대비 {price_change_pct:.1f}% 상승으로 매수 제한 (22% 초과)", buy_info
            

            # 🆕 현재 처리 중인 종목 코드 저장 (디버깅용)
            self._current_stock_code = stock_code
            
            # 전략 4: 눌림목 캔들패턴 매수 신호 (3분봉 사용)
            signal_result, reason, price_info = self._check_pullback_candle_buy_signal(combined_data, trading_stock)
            if signal_result and price_info:
                # 매수 신호 발생 시 가격과 수량 계산
                buy_price = price_info['buy_price']
                if buy_price <= 0:
                    # 3/5가 계산 실패시 현재가 사용
                    buy_price = self._safe_float_convert(combined_data['close'].iloc[-1])
                    self.logger.debug(f"⚠️ 3/5가 계산 실패, 현재가 사용: {buy_price:,.0f}원")
                
                max_buy_amount = self._get_max_buy_amount(trading_stock.stock_code)
                quantity = int(max_buy_amount // buy_price) if buy_price > 0 else 0
                
                if quantity > 0:
                    # 🆕 일봉 기반 패턴 필터 적용
                    if self.use_daily_filter and self.daily_pattern_filter:
                        current_time = now_kst()
                        signal_date = current_time.strftime("%Y%m%d")
                        signal_time = current_time.strftime("%H:%M")

                        filter_result = self.daily_pattern_filter.apply_filter(
                            stock_code, signal_date, signal_time
                        )

                        if not filter_result.passed:
                            self.logger.debug(f"🚫 {stock_code} 일봉 필터 차단: {filter_result.reason}")
                            return False, f"눌림목캔들패턴: {reason} + 일봉필터차단: {filter_result.reason}", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                        else:
                            self.logger.debug(f"✅ {stock_code} 일봉 필터 통과: {filter_result.reason} (점수: {filter_result.score:.2f})")

                    # 🆕 간단한 패턴 필터 적용 (시뮬과 동일)
                    if self.use_simple_filter and self.simple_pattern_filter:
                        should_filter, filter_reason = self.simple_pattern_filter.should_filter_out(
                            stock_code, signal_strength, data_3min
                        )

                        if should_filter:
                            self.logger.debug(f"🚫 {stock_code} 간단한 패턴 필터 차단: {filter_reason}")
                            return False, f"눌림목캔들패턴: {reason} + 패턴필터차단: {filter_reason}", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                        else:
                            self.logger.debug(f"✅ {stock_code} 간단한 패턴 필터 통과: {filter_reason}")

                    # ML 필터 적용 (매수 정보 생성 전에)
                    
                    ml_pass, ml_reason, ml_result = await self._apply_hardcoded_ml_filter(trading_stock, "pullback_pattern")
                    if not ml_pass:
                        return False, f"눌림목캔들패턴: {reason} + ML차단: {ml_reason}", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                    
                    # 매수 정보 생성 (ML 승인 후)
                    buy_info = {
                        'buy_price': buy_price,
                        'quantity': quantity,
                        'max_buy_amount': max_buy_amount,
                        'entry_low': price_info.get('entry_low', 0),  # 손절 기준
                        'target_profit': price_info.get('target_profit', 0.03),  # 목표 수익률
                        #'ml_prediction': ml_result  # ML 예측 결과 추가
                    }
                    
                    # 🆕 목표 수익률 저장
                    if hasattr(trading_stock, 'target_profit_rate'):
                        trading_stock.target_profit_rate = price_info.get('target_profit', 0.03)
                    
                    # ML 승인 정보를 매수 사유에 추가
                    final_reason = f"눌림목캔들패턴: {reason} + {ml_reason}"
                    
                    return True, final_reason, buy_info
                else:
                    return False, "수량 계산 실패", buy_info
            
            return False, f"매수 조건 미충족 (눌림목패턴: {reason})" if reason else "매수 조건 미충족", buy_info
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 판단 오류: {e}")
            return False, f"오류: {e}", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
    
    def set_buy_cooldown(self, stock_code: str, cooldown_minutes: int = None):
        """매수 성공 시 쿨다운 설정"""
        from datetime import timedelta
        current_time = now_kst()
        
        # 설정 파일의 값을 사용 (파라미터가 없으면)
        if cooldown_minutes is None:
            cooldown_minutes = self.buy_cooldown_minutes
            
        cooldown_end_time = current_time + timedelta(minutes=cooldown_minutes)
        self.stock_cooldown_end[stock_code] = cooldown_end_time
        self.logger.info(f"⏰ {stock_code} {cooldown_minutes}분 쿨다운 설정: {cooldown_end_time.strftime('%H:%M')}까지")
    
    def _calculate_buy_price(self, combined_data) -> float:
        """매수가 계산 (3/5가 또는 현재가)
        
        @deprecated: generate_improved_signals에서 직접 계산하도록 변경됨
        """
        try:
            current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
            
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
    
    def _get_max_buy_amount(self, stock_code: str = "") -> float:
        """최대 매수 가능 금액 조회"""
        # 🆕 자금 관리 시스템 사용 (임시 주석 - 아직 연동 안됨)
        # if hasattr(self, 'fund_manager') and self.fund_manager:
        #     return self.fund_manager.get_max_buy_amount(stock_code)
        
        # 🆕 기존 방식 (현재 사용 중)
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
    
    async def analyze_sell_decision(self, trading_stock, combined_data=None) -> Tuple[bool, str]:
        """
        매도 판단 분석 (간단한 손절/익절 로직)
        
        Args:
            trading_stock: 거래 종목 객체
            combined_data: 분봉 데이터 (사용하지 않음, 호환성을 위해 유지)
            
        Returns:
            Tuple[매도신호여부, 매도사유]
        """
        try:
            # 실시간 현재가 정보만 사용 (간단한 손절/익절 로직)
            stock_code = trading_stock.stock_code
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            
            if current_price_info is None:
                return False, "실시간 현재가 정보 없음"
            
            current_price = current_price_info['current_price']
            
            # 가상 포지션 정보 복원 (DB에서 미체결 포지션 조회) - 주석 처리
            # if not trading_stock.position and self.db_manager:
            #     open_positions = self.db_manager.get_virtual_open_positions()
            #     stock_positions = open_positions[open_positions['stock_code'] == trading_stock.stock_code]
            #     
            #     if not stock_positions.empty:
            #         latest_position = stock_positions.iloc[0]
            #         buy_record_id = latest_position['id']
            #         buy_price = latest_position['buy_price']
            #         quantity = latest_position['quantity']
            #         
            #         # 가상 포지션 정보를 trading_stock에 복원
            #         trading_stock.set_virtual_buy_info(buy_record_id, buy_price, quantity)
            #         trading_stock.set_position(quantity, buy_price)
            #         
            #         self.logger.debug(f"🔄 가상 포지션 복원: {trading_stock.stock_code} {quantity}주 @{buy_price:,.0f}원")
            
            # 간단한 손절/익절 조건 확인 (+3% 익절, -2% 손절)
            stop_profit_signal, stop_reason = self._check_simple_stop_profit_conditions(trading_stock, current_price)
            if stop_profit_signal:
                return True, f"손익절: {stop_reason}"
            
            # 기존 복잡한 손절 조건 확인 (백업용)
            # stop_loss_signal, stop_reason = self._check_stop_loss_conditions(trading_stock, combined_data)
            # if stop_loss_signal:
            #     return True, f"손절: {stop_reason}"
            
            # 수익실현 조건 확인 (복잡한 로직 - 주석 처리)
            # profit_signal, profit_reason = self._check_profit_target(trading_stock, current_price)
            # if profit_signal:
            #     return True, profit_reason
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매도 판단 오류: {e}")
            return False, f"오류: {e}"
    
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
            
            # buy_price가 지정된 경우 사용, 아니면 3/5가 계산 로직 사용
            if buy_price is not None:
                current_price = buy_price
                self.logger.debug(f"📊 {stock_code} 지정된 매수가로 매수: {current_price:,.0f}원")
            else:
                current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
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
            
            # 🆕 캐시된 실시간 현재가 사용 (매도 실행용)
            current_price_info = self.intraday_manager.get_cached_current_price(stock_code)
            
            if current_price_info is not None:
                current_price = current_price_info['current_price']
                self.logger.debug(f"📈 {stock_code} 실시간 현재가로 매도 실행: {current_price:,.0f}원")
            else:
                # 현재가 정보 없으면 분봉 데이터의 마지막 가격 사용 (폴백)
                current_price = self._safe_float_convert(combined_data['close'].iloc[-1])
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
    
    def _check_simple_stop_profit_conditions(self, trading_stock, current_price) -> Tuple[bool, str]:
        """간단한 손절/익절 조건 확인 (매수가격 기준 +3% 익절, -2% 손절)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            # 매수가격 안전하게 변환 (current_price는 이미 float로 전달됨)
            buy_price = self._safe_float_convert(trading_stock.position.avg_price)
            
            if buy_price <= 0:
                return False, "매수가격 정보 없음"
            
            # 수익률 계산 (HTS 방식과 동일: 백분율로 계산)
            profit_rate_percent = (current_price - buy_price) / buy_price * 100
            
            # 익절 조건: +3% 이상
            if profit_rate_percent >= 3.0:
                return True, f"익절 {profit_rate_percent:.1f}% (기준: +3.0%)"
            
            # 손절 조건: -2% 이하
            if profit_rate_percent <= -2.0:
                return True, f"손절 {profit_rate_percent:.1f}% (기준: -2.0%)"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 간단한 손절/익절 조건 확인 오류: {e}")
            return False, ""
    
    def _check_stop_loss_conditions(self, trading_stock, data) -> Tuple[bool, str]:
        """손절 조건 확인 (신호강도별 손익비 2:1 적용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            current_price = data['close'].iloc[-1]
            buy_price = trading_stock.position.avg_price
            
            # 임시 고정: 익절 +3%, 손절 -2%
            target_profit_rate = 0.03  # 3% 고정
            stop_loss_rate = 0.02      # 2% 고정
            
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
                return 0.02  # 기본값 2.0% (기존 1.5% → 2.0%로 상향)
            
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
                    
            return 0.02  # 기본신호: 2.0% (기존 1.5% → 2.0%로 상향)
            
        except Exception as e:
            self.logger.warning(f"목표수익률 계산 실패, 기본값 사용: {e}")
            return 0.02
    
    def _check_profit_target(self, trading_stock, current_price) -> Tuple[bool, str]:
        """수익실현 조건 확인 (신뢰도별 차등 목표수익 적용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            buy_price = trading_stock.position.avg_price
            profit_rate = (current_price - buy_price) / buy_price
            
            # 신뢰도별 차등 목표수익률 사용
            target_rate = getattr(trading_stock, 'target_profit_rate', 0.03)
            
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
    
    
    

    def _check_pullback_candle_buy_signal(self, data, trading_stock=None) -> Tuple[bool, str, Optional[Dict[str, float]]]:
        """전략 4: 눌림목 캔들패턴 매수 신호 확인 (3분봉 기준)
        
        Args:
            data: 이미 3분봉으로 변환된 데이터 (중복 변환 방지)
            
        Returns:
            Tuple[bool, str, Optional[Dict]]: (신고여부, 사유, 가격정보)
            가격정보: {'buy_price': float, 'entry_low': float, 'target_profit': float}
        """
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern, SignalType
            
            # 필요한 컬럼 확인
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in data.columns for col in required_cols):
                return False, "필요한 데이터 컬럼 부족", None
            
            # ❌ 중복 변환 제거: data는 이미 3분봉으로 변환된 상태
            # ❌ 중복 검증 제거: 상위 함수에서 이미 길이 확인함
            data_3min = data  # main.py에서 이미 변환됨
            
            # 🆕 3분봉 확정 확인 (signal_replay 방식) - 로그는 확정될 때만
            if not self._is_candle_confirmed(data_3min):
                return False, "3분봉 미확정", None
            
            # 일봉 데이터 가져오기 (intraday_manager에서)
            daily_data = None
            if self.intraday_manager:
                try:
                    stock_data = self.intraday_manager.get_stock_data(trading_stock.stock_code)
                    if stock_data and hasattr(stock_data, 'daily_data'):
                        daily_data = stock_data.daily_data
                        if daily_data is not None and not daily_data.empty:
                            self.logger.debug(f"📊 {trading_stock.stock_code} 일봉 데이터 전달: {len(daily_data)}개")
                except Exception as e:
                    self.logger.debug(f"⚠️ {trading_stock.stock_code} 일봉 데이터 조회 실패: {e}")

            # 🆕 개선된 신호 생성 로직 사용 (3/5가 계산 포함 + 일봉 데이터)
            signal_strength = PullbackCandlePattern.generate_improved_signals(
                data_3min,
                #stock_code=getattr(self, '_current_stock_code', 'UNKNOWN'),
                stock_code=trading_stock.stock_code,
                debug=True,
                daily_data=daily_data
            )
            
            if signal_strength is None:
                return False, "신호 계산 실패", None
            
            # 매수 신호 확인
            if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                # 🎯 간단한 패턴 필터 적용 (시뮬레이션과 동일 - 명백히 약한 패턴만 차단)
                try:
                    from core.indicators.simple_pattern_filter import SimplePatternFilter

                    pattern_filter = SimplePatternFilter(logger=self.logger)

                    # 약한 패턴 필터링 (시뮬레이션과 동일한 로직)
                    should_filter, filter_reason = pattern_filter.should_filter_out(
                        trading_stock.stock_code, signal_strength, data_3min
                    )

                    if should_filter:
                        self.logger.info(f"🚫 {trading_stock.stock_code} 약한 패턴으로 매수 차단: {filter_reason}")
                        return False, f"간단한패턴필터차단: {filter_reason}", None
                    else:
                        self.logger.debug(f"✅ {trading_stock.stock_code} 패턴 필터 통과: {filter_reason}")

                except Exception as e:
                    self.logger.warning(f"⚠️ {trading_stock.stock_code} 패턴 필터 오류: {e}")
                    # 필터 오류 시에도 매수 신호 진행 (안전장치)

                # 신호 이유 생성
                reasons = ' | '.join(signal_strength.reasons)
                signal_desc = f"{signal_strength.signal_type.value} (신뢰도: {signal_strength.confidence:.0f}%)"

                # 가격 정보 생성 (안전한 타입 변환)
                price_info = {
                    'buy_price': self._safe_float_convert(signal_strength.buy_price),
                    'entry_low': self._safe_float_convert(signal_strength.entry_low),
                    'target_profit': self._safe_float_convert(signal_strength.target_profit)
                }
                
                # 🆕 매수 신호 발생 상세 로깅 (데이터 정보 포함)
                from utils.korean_time import now_kst
                current_time = now_kst()
                last_3min_time = data_3min['datetime'].iloc[-1]
                data_count = len(data_3min)
                
                self.logger.info(f"🚀 매수 신호 발생!")
                self.logger.info(f"📊 신호 발생 데이터:")
                self.logger.info(f"  - 현재 시간: {current_time.strftime('%H:%M:%S')}")
                self.logger.info(f"  - 3분봉 개수: {data_count}개")
                self.logger.info(f"  - 신호 근거 3분봉: {last_3min_time}")
                
                # 최근 2개 봉 정보만 간단히
                if data_count >= 2:
                    for i in range(2):
                        idx = -(2-i)
                        row = data_3min.iloc[idx]
                        # 문자열을 숫자로 변환하여 포맷팅
                        close_price = self._safe_float_convert(row['close'])
                        volume = int(self._safe_float_convert(row['volume']))
                        self.logger.info(f"  - 3분봉[{i+1}]: {row['datetime'].strftime('%H:%M')} C:{close_price:,.0f} V:{volume:,}")
                
                self.logger.info(f"💡 신호 상세:")
                self.logger.info(f"  - 신호 유형: {signal_desc}")
                self.logger.info(f"  - 신호 이유: {reasons}")
                # 안전한 타입 변환
                buy_price = self._safe_float_convert(signal_strength.buy_price)
                entry_low = self._safe_float_convert(signal_strength.entry_low)
                self.logger.info(f"  - 매수 가격: {buy_price:,.0f}원 (3/5가)")
                self.logger.info(f"  - 진입 저가: {entry_low:,.0f}원")
                self.logger.info(f"  - 목표수익률: {signal_strength.target_profit:.1f}%")
                
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
            
            # 🆕 3분봉 확정될 때만 상세 로깅 (로그 길이 최적화)
            if is_confirmed:
                time_diff_sec = (current_time - candle_end_time).total_seconds()
                
                self.logger.info(f"📊 3분봉 확정 완료!")
                self.logger.info(f"  - 확정된 3분봉: {last_candle_time.strftime('%H:%M:%S')} ~ {candle_end_time.strftime('%H:%M:%S')}")
                self.logger.info(f"  - 현재 시간: {current_time.strftime('%H:%M:%S')} (확정 후 {time_diff_sec:.1f}초 경과)")
            
            return is_confirmed
            
        except Exception as e:
            self.logger.debug(f"3분봉 확정 확인 오류: {e}")
            return False
    
    def _check_pullback_candle_stop_loss(self, trading_stock, data, buy_price, current_price) -> Tuple[bool, str]:
        """눌림목 캔들패턴 전략 손절 조건 (실시간 가격 + 3분봉 기준)"""
        try:
            from core.indicators.pullback_candle_pattern import PullbackCandlePattern
            
            # 1단계: 실시간 가격 기반 신호강도별 손절/익절 체크 (30초마다 체크용)
            if buy_price and buy_price > 0:
                profit_rate = (current_price - buy_price) / buy_price
                
                # 임시 고정: 익절 +3%, 손절 -2%
                target_profit_rate = 0.03  # 3% 고정
                stop_loss_rate = 0.02      # 2% 고정
                
                # 신호강도별 손절
                if profit_rate <= -stop_loss_rate:
                    return True, f"⚡신호강도별손절 {profit_rate*100:.1f}% (기준: -{stop_loss_rate*100:.1f}%)"
                
                # 신호강도별 익절
                if profit_rate >= target_profit_rate:
                    return True, f"⚡신호강도별익절 {profit_rate*100:.1f}% (기준: +{target_profit_rate*100:.1f}%)"
                
                # 진입저가 실시간 체크 (주석처리: 손익비로만 판단)
                # entry_low_value = getattr(trading_stock, '_entry_low', None)
                # if entry_low_value and entry_low_value > 0:
                #     if current_price < entry_low_value * 0.998:  # -0.2%
                #         return True, f"⚡실시간진입저가이탈 ({current_price:.0f}<{entry_low_value*0.998:.0f})"
            
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