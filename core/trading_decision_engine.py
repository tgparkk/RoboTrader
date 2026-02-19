"""
매매 판단 엔진 - 전략 기반 매수/매도 의사결정
"""
from typing import Tuple, Optional, Dict, Any
import pandas as pd
from datetime import datetime

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.timeframe_converter import TimeFrameConverter


class TradingDecisionEngine:
    # 가격 위치 전략 일별 거래 기록 (클래스 변수)
    _price_position_daily_trades: Dict[str, set] = {}
    # 종목별 당일 시가 캐시 (클래스 변수) - {(stock_code, date): open_price}
    _day_open_cache: Dict[tuple, float] = {}
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

        # 설정 파일 로드
        import json
        import os
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'trading_config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except Exception as e:
            self.logger.warning(f"⚠️ 설정 파일 로드 실패: {e}")
            self.config = {}
        
        # 가상 매매 설정
        self.is_virtual_mode = False  # 🆕 가상매매 모드 여부 (False: 실제매매, True: 가상매매)
        
        # 🆕 가상매매 관리자 초기화
        from core.virtual_trading_manager import VirtualTradingManager
        self.virtual_trading = VirtualTradingManager(db_manager=db_manager, api_manager=api_manager)
        
        # 쿨다운은 TradingStock 모델에서 관리 (is_buy_cooldown_active 메서드 사용)
        
        # 🆕 일봉 기반 패턴 필터 초기화
        try:
            from core.indicators.daily_pattern_filter import DailyPatternFilter
            self.daily_pattern_filter = DailyPatternFilter(logger=self.logger)
            self.use_daily_filter = True
            self.logger.info("📊 일봉 기반 패턴 필터 초기화 완료")
        except Exception as e:
            self.logger.debug(f"일봉 패턴 필터 미설치 (비활성화): {e}")
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

        # 🆕 고급 필터 초기화 (승률 개선 필터)
        try:
            from core.indicators.advanced_filters import AdvancedFilterManager
            from config.advanced_filter_settings import AdvancedFilterSettings
            self.use_advanced_filter = AdvancedFilterSettings.ENABLED
            if self.use_advanced_filter:
                self.advanced_filter_manager = AdvancedFilterManager()
                active_filters = self.advanced_filter_manager.get_active_filters()
                self.logger.info(f"🔰 고급 필터 초기화 완료: {', '.join(active_filters) if active_filters else '없음'}")
            else:
                self.advanced_filter_manager = None
                self.logger.info("🔰 고급 필터 비활성화 (설정에서 ENABLED=False)")
        except Exception as e:
            self.logger.warning(f"⚠️ 고급 필터 초기화 실패: {e}")
            self.advanced_filter_manager = None
            self.use_advanced_filter = False

        # ML 설정 로드
        try:
            from config.ml_settings import MLSettings
            self.use_ml_filter = MLSettings.USE_ML_FILTER
            self.ml_threshold = MLSettings.ML_THRESHOLD
            self.ml_settings = MLSettings
            self.logger.info(f"🤖 ML 필터 설정 로드 완료 (임계값: {self.ml_threshold:.1%})")
        except ImportError:
            self.use_ml_filter = False
            self.ml_threshold = 0.5
            self.ml_settings = None
            self.logger.warning("⚠️ ML 설정 로드 실패 - ML 필터 비활성화")

        # ML 예측기 초기화
        self.ml_predictor = None

        if self.use_ml_filter:
            self._initialize_ml_predictor()

        # 🆕 패턴 데이터 로거 초기화 (설정 파일 또는 환경 변수로 제어)
        import os
        # 우선순위: 1) 환경 변수, 2) 설정 파일
        enable_from_env = os.getenv('ENABLE_PATTERN_LOGGING', '').lower()
        if enable_from_env in ['true', 'false']:
            enable_pattern_logging = enable_from_env == 'true'
        else:
            # 설정 파일에서 읽기
            enable_pattern_logging = self.config.get('logging', {}).get('enable_pattern_logging', False)

        if enable_pattern_logging:
            try:
                from core.pattern_data_logger import PatternDataLogger
                self.pattern_logger = PatternDataLogger()
                self.logger.info("📊 패턴 데이터 로거 초기화 완료")
            except Exception as e:
                self.logger.warning(f"⚠️ 패턴 데이터 로거 초기화 실패: {e}")
                self.pattern_logger = None
        else:
            self.pattern_logger = None
            self.logger.info("📊 패턴 데이터 로거 비활성화 (실시간 성능 최적화)")

        # 🆕 전략 설정 로드
        try:
            from config.strategy_settings import StrategySettings
            self.active_strategy = StrategySettings.ACTIVE_STRATEGY
            self.strategy_settings = StrategySettings
            self.logger.info(f"📈 활성 전략: {self.active_strategy}")

            # 가격 위치 전략 초기화
            if self.active_strategy == 'price_position':
                from core.strategies.price_position_strategy import PricePositionStrategy
                pp_config = {
                    'min_pct_from_open': StrategySettings.PricePosition.MIN_PCT_FROM_OPEN,
                    'max_pct_from_open': StrategySettings.PricePosition.MAX_PCT_FROM_OPEN,
                    'entry_start_hour': StrategySettings.PricePosition.ENTRY_START_HOUR,
                    'entry_end_hour': StrategySettings.PricePosition.ENTRY_END_HOUR,
                    'allowed_weekdays': StrategySettings.PricePosition.ALLOWED_WEEKDAYS,
                    'stop_loss_pct': -self.config.get('risk_management', {}).get('stop_loss_ratio', 0.025) * 100,
                    'take_profit_pct': self.config.get('risk_management', {}).get('take_profit_ratio', 0.035) * 100,
                }
                self.price_position_strategy = PricePositionStrategy(config=pp_config, logger=self.logger)
                self.logger.info(f"   진입조건: 시가+{pp_config['min_pct_from_open']}%~{pp_config['max_pct_from_open']}%, "
                               f"{pp_config['entry_start_hour']}시~{pp_config['entry_end_hour']}시, 월/수/금")
            else:
                self.price_position_strategy = None

        except Exception as e:
            self.logger.warning(f"⚠️ 전략 설정 로드 실패: {e}, 기본 전략(pullback) 사용")
            self.active_strategy = 'pullback'
            self.strategy_settings = None
            self.price_position_strategy = None

        # 🆕 매매 실행 모듈 초기화 (리팩토링)
        try:
            from core.trade_executor import TradeExecutor
            self._trade_executor = TradeExecutor(self)
            self.logger.debug("📦 매매 실행 모듈 초기화 완료")
        except Exception as e:
            self.logger.warning(f"⚠️ 매매 실행 모듈 초기화 실패: {e}")
            self._trade_executor = None

        self.logger.info("🧠 매매 판단 엔진 초기화 완료")

    def _initialize_ml_predictor(self):
        """ML 예측기 초기화"""
        try:
            from core.ml_predictor import get_ml_predictor

            self.ml_predictor = get_ml_predictor(model_path="ml_model.pkl")

            if self.ml_predictor and self.ml_predictor.is_loaded:
                self.logger.info("🤖 ML 예측기 초기화 완료")
                self.logger.info(f"   모델 버전: {self.ml_predictor.model_version}")
                self.logger.info(f"   특성 수: {len(self.ml_predictor.feature_names)}개")
            else:
                self.logger.warning("⚠️ ML 예측기 로드 실패 - ML 필터 비활성화")
                self.use_ml_filter = False

        except Exception as e:
            self.logger.error(f"❌ ML 예측기 초기화 실패: {e}")
            self.use_ml_filter = False
            self.ml_predictor = None
    
    def _get_day_open_price(self, stock_code: str, trade_date: str, data) -> Optional[float]:
        """
        종목의 당일 시가(장 시작 가격) 조회

        09:00 캔들의 open 값을 사용. 시가는 불변값이므로 캐시하여 재사용.
        data.iloc[0]에 의존하지 않고, 09:00~09:03 구간의 첫 캔들을 명시적으로 찾음.
        """
        cache_key = (stock_code, trade_date)

        # 캐시에 있으면 즉시 반환
        if cache_key in TradingDecisionEngine._day_open_cache:
            return TradingDecisionEngine._day_open_cache[cache_key]

        day_open = None

        # 09:00~09:03 구간 캔들에서 시가 추출 (09:00 3분봉 = 장 시작 캔들)
        if 'time' in data.columns:
            time_col = data['time'].astype(str).str.zfill(6)
            early_candles = data[time_col <= '090300']
            if len(early_candles) > 0:
                day_open = self._safe_float_convert(early_candles.iloc[0]['open'])

        if day_open and day_open > 0:
            TradingDecisionEngine._day_open_cache[cache_key] = day_open
            return day_open

        # 09:00 시가 없음 → 매매 제외 (잘못된 시가로 매매하면 안 됨)
        first_time = str(data.iloc[0].get('time', '?')).zfill(6) if len(data) > 0 else '?'
        self.logger.warning(f"⚠️ {stock_code} 09:00~09:03 시가 데이터 없음 (첫 봉: {first_time}) - 매매 제외")
        return None

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

            # 쿨다운 체크는 main.py에서 trading_stock.is_buy_cooldown_active()로 이미 확인됨

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

            # 🆕 현재 처리 중인 종목 코드 저장 (디버깅용)
            self._current_stock_code = stock_code

            # 🆕 전략에 따라 매수 신호 확인 분기
            if self.active_strategy == 'price_position':
                # 가격 위치 기반 전략
                signal_result, reason, price_info = self._check_price_position_buy_signal(combined_data, trading_stock)
            else:
                # 기존 눌림목 캔들패턴 전략 (기본값)
                signal_result, reason, price_info = self._check_pullback_candle_buy_signal(combined_data, trading_stock)
            if signal_result and price_info:
                # 매수 신호 발생 시 가격과 수량 계산
                buy_price = price_info['buy_price']
                if buy_price <= 0:
                    # 4/5가 계산 실패시 현재가 사용
                    buy_price = self._safe_float_convert(combined_data['close'].iloc[-1])
                    self.logger.debug(f"⚠️ 4/5가 계산 실패, 현재가 사용: {buy_price:,.0f}원")
                
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

                    # 🆕 ML 필터 적용
                    ml_prob = 0.5  # 기본값
                    if self.use_ml_filter and self.ml_predictor:
                        try:
                            # 패턴 특성 추출 (price_info에 패턴 데이터 포함되어 있어야 함)
                            pattern_features = price_info.get('pattern_data', {})

                            if pattern_features:
                                should_trade, ml_prob = self.ml_predictor.should_trade(
                                    pattern_features,
                                    threshold=self.ml_threshold,
                                    stock_code=stock_code
                                )

                                # 🆕 실시간 패턴 데이터 로깅 (시뮬과 비교용)
                                try:
                                    from core.pattern_data_logger import PatternDataLogger

                                    pattern_logger = PatternDataLogger()  # 실시간 로깅

                                    # signal_time 추가 (ML 예측에 필요)
                                    if 'signal_time' not in pattern_features:
                                        pattern_features['signal_time'] = now_kst().strftime('%Y-%m-%d %H:%M:%S')

                                    # ML 예측값 추가 (시뮬과 비교용)
                                    if 'ml_prob' not in pattern_features:
                                        pattern_features['ml_prob'] = ml_prob

                                    pattern_logger.log_pattern_data(
                                        stock_code=stock_code,
                                        signal_type=pattern_features.get('signal_info', {}).get('signal_type', 'UNKNOWN'),
                                        confidence=pattern_features.get('signal_info', {}).get('confidence', 0.0),
                                        support_pattern_info=pattern_features,
                                        data_3min=combined_data,  # 수정: data_3min → combined_data
                                        data_1min=None
                                    )
                                except Exception as log_err:
                                    self.logger.debug(f"⚠️ {stock_code} 패턴 로깅 실패: {log_err}")

                                if not should_trade:
                                    self.logger.info(f"🤖 {stock_code} ML 필터 차단: 승률 {ml_prob:.1%} < {self.ml_threshold:.1%}")
                                    return False, f"눌림목캔들패턴: {reason} + ML필터차단 (승률: {ml_prob:.1%})", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                                else:
                                    self.logger.info(f"✅ {stock_code} ML 필터 통과: 승률 {ml_prob:.1%}")
                            else:
                                self.logger.warning(f"⚠️ {stock_code} 패턴 데이터 없음 - ML 필터 건너뜀")

                        except Exception as e:
                            self.logger.error(f"❌ {stock_code} ML 필터 오류: {e} - 신호 허용")
                            # ML 오류 시 신호 허용

                    # 🆕 고급 필터 적용 (pullback 전략 전용 - price_position 전략은 제외)
                    if self.use_advanced_filter and self.advanced_filter_manager and self.active_strategy != 'price_position':
                        try:
                            signal_time = now_kst()

                            # 🆕 combined_data (3분봉)에서 직접 OHLCV 시퀀스 추출 (시뮬과 동일한 방식)
                            ohlcv_sequence = []
                            if combined_data is not None and len(combined_data) >= 5:
                                recent_candles = combined_data.tail(5)
                                for _, row in recent_candles.iterrows():
                                    ohlcv_sequence.append({
                                        'open': float(row.get('open', 0)),
                                        'high': float(row.get('high', 0)),
                                        'low': float(row.get('low', 0)),
                                        'close': float(row.get('close', 0)),
                                        'volume': float(row.get('volume', 0))
                                    })

                            # RSI와 거래량비율, pattern_stages는 pattern_data에서 추출 시도 (없으면 None)
                            pattern_features = price_info.get('pattern_data', {})
                            tech = pattern_features.get('technical_indicators_3min', {})
                            rsi = tech.get('rsi_14')
                            volume_ma_ratio = tech.get('volume_vs_ma_ratio')
                            pattern_stages = pattern_features.get('pattern_stages')

                            # 거래일 추출 (일봉 필터용)
                            trade_date = signal_time.strftime('%Y%m%d') if signal_time else None

                            # 고급 필터 체크
                            adv_result = self.advanced_filter_manager.check_signal(
                                ohlcv_sequence=ohlcv_sequence,
                                rsi=rsi,
                                stock_code=stock_code,
                                signal_time=signal_time,
                                volume_ma_ratio=volume_ma_ratio,
                                pattern_stages=pattern_stages,
                                trade_date=trade_date
                            )

                            if not adv_result.passed:
                                self.logger.info(f"🔰 {stock_code} 고급 필터 차단: {adv_result.blocked_by} - {adv_result.blocked_reason}")
                                return False, f"눌림목캔들패턴: {reason} + 고급필터차단: {adv_result.blocked_reason}", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
                            else:
                                self.logger.debug(f"✅ {stock_code} 고급 필터 통과")

                        except Exception as e:
                            self.logger.warning(f"⚠️ {stock_code} 고급 필터 오류: {e} - 신호 허용")
                            # 고급 필터 오류 시 신호 허용

                    # 매수 정보 생성
                    buy_info = {
                        'buy_price': buy_price,
                        'quantity': quantity,
                        'max_buy_amount': max_buy_amount,
                        'entry_low': price_info.get('entry_low', 0),  # 손절 기준
                        'target_profit': price_info.get('target_profit', 0.03),  # 목표 수익률
                        'ml_prob': ml_prob  # ML 예측 승률 추가
                    }

                    # 🆕 목표 수익률 저장
                    if hasattr(trading_stock, 'target_profit_rate'):
                        trading_stock.target_profit_rate = price_info.get('target_profit', 0.03)

                    # 🔧 price_position 전략: 고급 필터 통과 후 거래 기록 (버그 수정 2026-02-04)
                    if self.active_strategy == 'price_position':
                        trade_date = now_kst().strftime('%Y%m%d')
                        if trade_date not in TradingDecisionEngine._price_position_daily_trades:
                            TradingDecisionEngine._price_position_daily_trades[trade_date] = set()
                        TradingDecisionEngine._price_position_daily_trades[trade_date].add(stock_code)
                        self.logger.debug(f"📝 {stock_code} price_position 거래 기록 추가 ({len(TradingDecisionEngine._price_position_daily_trades[trade_date])}/5)")

                    # 매수 신호 승인
                    final_reason = f"눌림목캔들패턴: {reason} (ML: {ml_prob:.1%})"

                    return True, final_reason, buy_info
                else:
                    return False, "수량 계산 실패", buy_info
            
            return False, f"매수 조건 미충족 (눌림목패턴: {reason})" if reason else "매수 조건 미충족", buy_info
            
        except Exception as e:
            self.logger.error(f"❌ {trading_stock.stock_code} 매수 판단 오류: {e}")
            return False, f"오류: {e}", {'buy_price': 0, 'quantity': 0, 'max_buy_amount': 0}
    
    # set_buy_cooldown 메서드 제거: TradingStock 모델에서 last_buy_time으로 관리
    
    def _get_max_buy_amount(self, stock_code: str = "") -> float:
        """최대 매수 가능 금액 조회"""
        # 설정에서 투자 비율 가져오기 (기본값: 0.20 = 1/5)
        buy_budget_ratio = self.config.get('order_management', {}).get('buy_budget_ratio', 0.20)

        # 🆕 기존 방식 (현재 사용 중)
        max_buy_amount = 500000  # 기본값

        try:
            if self.api_manager:
                account_info = self.api_manager.get_account_balance()
                if account_info and hasattr(account_info, 'available_amount'):
                    available_balance = float(account_info.available_amount)
                    max_buy_amount = min(5000000, available_balance * buy_budget_ratio)
                    self.logger.debug(f"💰 계좌 가용금액: {available_balance:,.0f}원, 투자비율: {buy_budget_ratio:.0%}, 투자금액: {max_buy_amount:,.0f}원")
                elif hasattr(account_info, 'total_balance'):
                    total_balance = float(account_info.total_balance)
                    max_buy_amount = min(5000000, total_balance * buy_budget_ratio)
                    self.logger.debug(f"💰 총 자산: {total_balance:,.0f}원, 투자비율: {buy_budget_ratio:.0%}, 투자금액: {max_buy_amount:,.0f}원")
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
        """실제 매수 주문 실행 (TradeExecutor 위임)"""
        if self._trade_executor:
            return await self._trade_executor.execute_real_buy(
                trading_stock, buy_reason, buy_price, quantity, candle_time
            )
        else:
            self.logger.error("❌ TradeExecutor 미초기화")
            return False
    
    async def execute_virtual_buy(self, trading_stock, combined_data, buy_reason, buy_price=None):
        """가상 매수 실행 (TradeExecutor 위임)"""
        if self._trade_executor:
            return await self._trade_executor.execute_virtual_buy(
                trading_stock, combined_data, buy_reason, buy_price
            )
        else:
            self.logger.error("❌ TradeExecutor 미초기화")
    
    async def execute_real_sell(self, trading_stock, sell_reason):
        """실제 매도 주문 실행 (TradeExecutor 위임)"""
        if self._trade_executor:
            return await self._trade_executor.execute_real_sell(trading_stock, sell_reason)
        else:
            self.logger.error("❌ TradeExecutor 미초기화")
            return False
    
    async def execute_virtual_sell(self, trading_stock, combined_data, sell_reason):
        """가상 매도 실행 (TradeExecutor 위임)"""
        if self._trade_executor:
            return await self._trade_executor.execute_virtual_sell(
                trading_stock, combined_data, sell_reason
            )
        else:
            self.logger.error("❌ TradeExecutor 미초기화")
    
    def _check_simple_stop_profit_conditions(self, trading_stock, current_price) -> Tuple[bool, str]:
        """간단한 손절/익절 조건 확인 (trading_config.json의 손익비 설정 사용)"""
        try:
            if not trading_stock.position:
                return False, ""
            
            # 매수가격 안전하게 변환 (current_price는 이미 float로 전달됨)
            buy_price = self._safe_float_convert(trading_stock.position.avg_price)
            
            if buy_price <= 0:
                return False, "매수가격 정보 없음"
            
            # 수익률 계산 (HTS 방식과 동일: 백분율로 계산)
            profit_rate_percent = (current_price - buy_price) / buy_price * 100

            # 🆕 trading_config.json에서 손익비 설정 가져오기
            from config.settings import load_trading_config
            config = load_trading_config()

            # 🔧 동적 손익비 체크 (플래그가 true이고 패턴 정보가 있으면 동적 손익비 사용)
            if hasattr(config.risk_management, 'use_dynamic_profit_loss') and config.risk_management.use_dynamic_profit_loss:
                # debug_info에서 패턴 추출 시도
                from config.dynamic_profit_loss_config import DynamicProfitLossConfig

                # pattern_data 또는 debug_info 추출 시도 (여러 경로 시도)
                debug_info = None
                if hasattr(trading_stock, 'pattern_data') and trading_stock.pattern_data:
                    debug_info = trading_stock.pattern_data.get('debug_info')

                if debug_info:
                    # debug_info에서 패턴 분류 추출
                    support_volume, decline_volume = DynamicProfitLossConfig.extract_pattern_from_debug_info(debug_info)

                    if support_volume and decline_volume:
                        # 패턴 기반 동적 손익비 적용
                        ratio = DynamicProfitLossConfig.get_ratio_by_pattern(support_volume, decline_volume)
                        take_profit_percent = ratio['take_profit']
                        stop_loss_percent = abs(ratio['stop_loss'])

                        self.logger.debug(f"🔧 [동적 손익비] 패턴: {support_volume}+{decline_volume}, "
                                        f"손절 {stop_loss_percent:.1f}% / 익절 {take_profit_percent:.1f}%")
                    else:
                        # 패턴 정보 없으면 기본값
                        take_profit_percent = config.risk_management.take_profit_ratio * 100
                        stop_loss_percent = config.risk_management.stop_loss_ratio * 100
                else:
                    # debug_info 없으면 기본값
                    take_profit_percent = config.risk_management.take_profit_ratio * 100
                    stop_loss_percent = config.risk_management.stop_loss_ratio * 100
            else:
                # 플래그가 false이거나 없으면 기본값 사용
                take_profit_percent = config.risk_management.take_profit_ratio * 100  # 0.035 -> 3.5%
                stop_loss_percent = config.risk_management.stop_loss_ratio * 100      # 0.025 -> 2.5%
            
            # 익절 조건: config에서 설정한 % 이상
            if profit_rate_percent >= take_profit_percent:
                return True, f"익절 {profit_rate_percent:.1f}% (기준: +{take_profit_percent:.1f}%)"
            
            # 손절 조건: config에서 설정한 % 이하
            if profit_rate_percent <= -stop_loss_percent:
                return True, f"손절 {profit_rate_percent:.1f}% (기준: -{stop_loss_percent:.1f}%)"
            
            return False, ""
            
        except Exception as e:
            self.logger.error(f"❌ 간단한 손절/익절 조건 확인 오류: {e}")
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
            
            '''
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
            '''

            # 🆕 개선된 신호 생성 로직 사용 (4/5가 계산 포함 + 일봉 데이터 제외 - 시뮬과 동일)
            signal_strength = PullbackCandlePattern.generate_improved_signals(
                data_3min,
                #stock_code=getattr(self, '_current_stock_code', 'UNKNOWN'),
                stock_code=trading_stock.stock_code,
                debug=True
                # daily_data=daily_data  # 시뮬과 동일하게 일봉 데이터 전달 안 함
            )
            
            if signal_strength is None:
                return False, "신호 계산 실패", None
            
            # 매수 신호 확인
            if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                # 🎯 간단한 패턴 필터 적용 (시뮬레이션과 동일 - 명백히 약한 패턴만 차단)
                try:
                    from core.indicators.simple_pattern_filter import SimplePatternFilter

                    pattern_filter = SimplePatternFilter()  # 시뮬과 동일하게 logger 없이 생성

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

                # 가격 정보 생성 (안전한 타입 변환 + ML용 패턴 데이터 포함)
                price_info = {
                    'buy_price': self._safe_float_convert(signal_strength.buy_price),
                    'entry_low': self._safe_float_convert(signal_strength.entry_low),
                    'target_profit': self._safe_float_convert(signal_strength.target_profit),
                    'pattern_data': getattr(signal_strength, 'pattern_data', {})  # ML 필터용 패턴 데이터
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
                self.logger.info(f"  - 매수 가격: {buy_price:,.0f}원 (4/5가)")
                self.logger.info(f"  - 진입 저가: {entry_low:,.0f}원")
                self.logger.info(f"  - 목표수익률: {signal_strength.target_profit:.1f}%")

                # 📊 4단계 패턴 구간 데이터 로깅 및 동적 손익비용 데이터 저장
                if self.pattern_logger and hasattr(signal_strength, 'pattern_data') and signal_strength.pattern_data:
                    try:
                        pattern_id = self.pattern_logger.log_pattern_data(
                            stock_code=trading_stock.stock_code,
                            signal_type=signal_strength.signal_type.value,
                            confidence=signal_strength.confidence,
                            support_pattern_info=signal_strength.pattern_data,
                            data_3min=data_3min
                        )
                        # pattern_id를 나중에 매매 결과 업데이트에 사용
                        trading_stock.last_pattern_id = pattern_id
                        self.logger.debug(f"📝 패턴 데이터 로깅 완료: {pattern_id}")

                        # 🔧 동적 손익비를 위한 패턴 데이터 저장 (기존 코드 흐름 방해 안 함)
                        if not hasattr(trading_stock, 'pattern_data'):
                            trading_stock.pattern_data = signal_strength.pattern_data
                            self.logger.debug(f"🔧 패턴 데이터 저장 완료 (동적 손익비용)")
                    except Exception as log_err:
                        self.logger.warning(f"⚠️ 패턴 데이터 로깅 실패: {log_err}")

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

    def _check_price_position_buy_signal(self, data, trading_stock=None) -> Tuple[bool, str, Optional[Dict[str, float]]]:
        """
        가격 위치 기반 전략 매수 신호 확인

        조건:
        - 시가 대비 2~4% 상승
        - 월/수/금요일만 거래
        - 10시~12시 진입

        Returns:
            Tuple[bool, str, Optional[Dict]]: (신호여부, 사유, 가격정보)
        """
        try:
            if not self.price_position_strategy:
                return False, "가격위치전략 미초기화", None

            stock_code = trading_stock.stock_code if trading_stock else "UNKNOWN"

            # 데이터 검증
            if data is None or len(data) < 10:
                return False, "데이터 부족", None

            # 현재 시간 정보
            current_time = now_kst()
            trade_date = current_time.strftime('%Y%m%d')
            weekday = current_time.weekday()
            time_str = current_time.strftime('%H%M%S')

            # 요일 체크 (화/목 회피)
            pp_settings = self.strategy_settings.PricePosition
            if weekday not in pp_settings.ALLOWED_WEEKDAYS:
                weekday_names = ['월', '화', '수', '목', '금', '토', '일']
                return False, f"{weekday_names[weekday]}요일 거래 제외", None

            # 시간 체크
            hour = current_time.hour
            if hour < pp_settings.ENTRY_START_HOUR:
                return False, f"{pp_settings.ENTRY_START_HOUR}시 이전", None
            if hour >= pp_settings.ENTRY_END_HOUR:
                return False, f"{pp_settings.ENTRY_END_HOUR}시 이후", None

            # 당일 거래 여부 체크 (종목당 1회)
            if pp_settings.ONE_TRADE_PER_STOCK_PER_DAY:
                if trade_date in TradingDecisionEngine._price_position_daily_trades:
                    if stock_code in TradingDecisionEngine._price_position_daily_trades[trade_date]:
                        return False, "당일 이미 거래함", None

            # 동시 보유 종목 수 체크 (POSITIONED + BUY_PENDING)
            if self.trading_manager:
                from core.models import StockState
                positioned = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
                buy_pending = self.trading_manager.get_stocks_by_state(StockState.BUY_PENDING)
                current_holding = len(positioned) + len(buy_pending)
                if current_holding >= pp_settings.MAX_DAILY_POSITIONS:
                    return False, f"동시 보유 최대 {pp_settings.MAX_DAILY_POSITIONS}종목 도달 (현재 {current_holding})", None

            # 시가 계산 (09:00 캔들의 open = 장 시작 가격, 불변값)
            day_open = self._get_day_open_price(stock_code, trade_date, data)
            if day_open is None or day_open <= 0:
                return False, "시가 데이터 없음", None

            # 현재가 (마지막 캔들)
            current_price = self._safe_float_convert(data.iloc[-1]['close'])
            if current_price <= 0:
                return False, "현재가 데이터 없음", None

            # 시가 대비 상승률 계산
            pct_from_open = (current_price / day_open - 1) * 100

            # 진입 조건 확인
            can_enter, reason = self.price_position_strategy.check_entry_conditions(
                stock_code=stock_code,
                current_price=current_price,
                day_open=day_open,
                current_time=time_str,
                trade_date=trade_date,
                weekday=weekday
            )

            if not can_enter:
                return False, reason, None

            # n분봉 확정 확인 (설정된 캔들 간격 사용)
            candle_interval = pp_settings.CANDLE_INTERVAL
            if not self._is_nmin_candle_confirmed(data, candle_interval):
                return False, f"{candle_interval}분봉 미확정", None

            # 고급 진입 필터 (변동성, 모멘텀)
            adv_config = {}
            if hasattr(pp_settings, 'MAX_PRE_VOLATILITY'):
                adv_config['max_pre_volatility'] = pp_settings.MAX_PRE_VOLATILITY
            if hasattr(pp_settings, 'MAX_PRE20_MOMENTUM'):
                adv_config['max_pre20_momentum'] = pp_settings.MAX_PRE20_MOMENTUM

            if adv_config:
                # 설정값을 전략 객체에 반영
                self.price_position_strategy.config.update(adv_config)
                adv_ok, adv_reason = self.price_position_strategy.check_advanced_conditions(
                    df=data, candle_idx=len(data) - 1
                )
                if not adv_ok:
                    return False, f"고급필터: {adv_reason}", None

            # 매수 신호 승인!
            # 🔧 거래 기록은 고급 필터 통과 후로 이동 (버그 수정 2026-02-04)
            # 이전: 여기서 기록 → 고급 필터 차단 시에도 기록 남음 → "최대 5종목 도달" 오류
            # 이후: analyze_buy_decision에서 고급 필터 통과 후 기록

            # 가격 정보 생성 (trade_date 포함하여 나중에 기록할 수 있도록)
            price_info = {
                'buy_price': current_price,
                'entry_low': day_open * 0.975,  # 시가 -2.5% (손절 기준)
                'target_profit': 0.035,  # 3.5%
                'pattern_data': {
                    'pct_from_open': pct_from_open,
                    'day_open': day_open,
                    'current_price': current_price,
                    'entry_hour': hour,
                    'weekday': weekday,
                }
            }

            self.logger.info(f"🚀 [가격위치전략] 매수 신호!")
            self.logger.info(f"  - 종목: {stock_code}")
            self.logger.info(f"  - 시가: {day_open:,.0f}원")
            self.logger.info(f"  - 현재가: {current_price:,.0f}원 (시가+{pct_from_open:.1f}%)")
            self.logger.info(f"  - 시간: {current_time.strftime('%H:%M')}")

            signal_reason = f"가격위치전략: 시가+{pct_from_open:.1f}% ({pp_settings.MIN_PCT_FROM_OPEN}~{pp_settings.MAX_PCT_FROM_OPEN}%)"
            return True, signal_reason, price_info

        except Exception as e:
            self.logger.error(f"❌ 가격위치전략 매수 신호 확인 오류: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False, f"오류: {e}", None

    @classmethod
    def reset_daily_trades(cls, trade_date: str = None):
        """일별 거래 기록 및 시가 캐시 초기화 (가격위치전략용)"""
        if trade_date:
            cls._price_position_daily_trades.pop(trade_date, None)
            # 해당 날짜의 시가 캐시도 제거
            keys_to_remove = [k for k in cls._day_open_cache if k[1] == trade_date]
            for k in keys_to_remove:
                del cls._day_open_cache[k]
        else:
            cls._price_position_daily_trades.clear()
            cls._day_open_cache.clear()

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
            
            # 🆕 3분봉 확정될 때만 상세 로깅 + 지연 체크 (로그 길이 최적화)
            if is_confirmed:
                time_diff_sec = (current_time - candle_end_time).total_seconds()

                self.logger.info(f"📊 3분봉 확정 완료!")
                self.logger.info(f"  - 확정된 3분봉: {last_candle_time.strftime('%H:%M:%S')} ~ {candle_end_time.strftime('%H:%M:%S')}")
                self.logger.info(f"  - 현재 시간: {current_time.strftime('%H:%M:%S')} (확정 후 {time_diff_sec:.1f}초 경과)")

                # 🚫 HTS 분봉 누락 대비: 5분(300초) 이상 지연된 3분봉은 신호 무효
                if time_diff_sec > 300:
                    self.logger.warning(f"⚠️ 3분봉 지연 초과 ({time_diff_sec/60:.1f}분) - HTS 분봉 누락 가능성")
                    return False  # 매수 신호 차단

            return is_confirmed

        except Exception as e:
            self.logger.debug(f"3분봉 확정 확인 오류: {e}")
            return False

    def _is_nmin_candle_confirmed(self, data, interval_minutes: int) -> bool:
        """n분봉 확정 여부 확인 (범용)"""
        try:
            if data is None or data.empty or 'datetime' not in data.columns:
                return False

            from utils.korean_time import now_kst, KST
            import pandas as pd

            current_time = now_kst()
            last_candle_time = pd.to_datetime(data['datetime'].iloc[-1])

            # timezone 통일
            if last_candle_time.tz is None:
                last_candle_time = last_candle_time.tz_localize(KST)
            elif last_candle_time.tz != KST:
                last_candle_time = last_candle_time.tz_convert(KST)

            # n분봉: 라벨 + n분 경과 후 확정
            candle_end_time = last_candle_time + pd.Timedelta(minutes=interval_minutes)
            is_confirmed = current_time >= candle_end_time

            if is_confirmed:
                time_diff_sec = (current_time - candle_end_time).total_seconds()
                self.logger.debug(f"📊 {interval_minutes}분봉 확정: {last_candle_time.strftime('%H:%M')} (확정 후 {time_diff_sec:.1f}초)")

                # 5분 이상 지연된 캔들은 신호 무효
                if time_diff_sec > 300:
                    self.logger.warning(f"⚠️ {interval_minutes}분봉 지연 초과 ({time_diff_sec/60:.1f}분)")
                    return False

            return is_confirmed

        except Exception as e:
            self.logger.debug(f"{interval_minutes}분봉 확정 확인 오류: {e}")
            return False

