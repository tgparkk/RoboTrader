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
        
        # 프리마켓 리포트 (08:55에 set_pre_market_report()로 설정됨)
        self._pre_market_report = None

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

        # 전략 설정 로드 (macd_cross 단일 운영)
        try:
            from config.strategy_settings import StrategySettings
            self.active_strategy = StrategySettings.ACTIVE_STRATEGY
            self.strategy_settings = StrategySettings
            self.logger.info(f"📈 활성 전략: {self.active_strategy}")
            # 폐기된 전략 호환 필드 (외부 참조 보호용 None 노출)
            self.closing_trade_strategy = None
            self.weighted_score_strategy = None
        except Exception as e:
            self.logger.warning(f"⚠️ 전략 설정 로드 실패: {e}")
            self.active_strategy = 'macd_cross'
            self.strategy_settings = None
            self.closing_trade_strategy = None
            self.weighted_score_strategy = None

        # 🆕 매매 실행 모듈 초기화 (리팩토링)
        try:
            from core.trade_executor import TradeExecutor
            self._trade_executor = TradeExecutor(self)
            self.logger.debug("📦 매매 실행 모듈 초기화 완료")
        except Exception as e:
            self.logger.warning(f"⚠️ 매매 실행 모듈 초기화 실패: {e}")
            self._trade_executor = None

        self.logger.info("🧠 매매 판단 엔진 초기화 완료")

        # 성과 기반 매수 게이트 (롤링승률 + 연속손실)
        from config.strategy_settings import StrategySettings
        pg_settings = StrategySettings.PerformanceGate
        if pg_settings.ENABLED:
            from core.performance_gate import PerformanceGate
            self.performance_gate = PerformanceGate(
                rolling_n=pg_settings.ROLLING_N,
                rolling_threshold=pg_settings.ROLLING_THRESHOLD,
                consec_loss_limit=pg_settings.CONSEC_LOSS_LIMIT,
                hard_cap_days=pg_settings.HARD_CAP_DAYS,
            )
            self.performance_gate.load_from_db(db_manager)
        else:
            self.performance_gate = None

        # macd_cross 어댑터 초기화 (active 또는 paper 둘 다 지원)
        try:
            from config.strategy_settings import StrategySettings
            if (StrategySettings.ACTIVE_STRATEGY == 'macd_cross'
                    or StrategySettings.PAPER_STRATEGY == 'macd_cross'):
                from core.strategies.macd_cross_strategy import MacdCrossStrategy
                cfg = StrategySettings.MacdCross
                self.macd_cross_strategy = MacdCrossStrategy(
                    fast=cfg.FAST_PERIOD,
                    slow=cfg.SLOW_PERIOD,
                    signal=cfg.SIGNAL_PERIOD,
                    entry_hhmm_min=cfg.ENTRY_HHMM_MIN,
                    entry_hhmm_max=cfg.ENTRY_HHMM_MAX,
                    logger=self.logger,
                )
                mode = ('실거래' if StrategySettings.ACTIVE_STRATEGY == 'macd_cross'
                        and not cfg.VIRTUAL_ONLY else '가상')
                self.logger.info(
                    f"📈 macd_cross 어댑터 초기화 완료 ({mode}, "
                    f"max_pos={cfg.MAX_DAILY_POSITIONS}, hold={cfg.HOLD_DAYS}d, "
                    f"entry={cfg.ENTRY_HHMM_MIN}~{cfg.ENTRY_HHMM_MAX})"
                )
            else:
                self.macd_cross_strategy = None
        except Exception as e:
            self.logger.warning(f"⚠️ macd_cross 어댑터 초기화 실패: {e}")
            self.macd_cross_strategy = None

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

    def _calc_preload_score(self, data, current_price: float,
                            day_open: float, pct_from_open: float) -> float:
        """프리로드 진입 시점 간이 점수 계산 (max 90, change_rate 제외).

        stock_screener._calculate_score와 동일 가중치이나 전일종가 없는 상황에서
        change_rate 항목(10점)은 제외. 실효 임계값은 원 T70 대비 65~67 수준이 근사.
        """
        score = 0.0

        # 1. 시가대비 위치 (max 40)
        if 1.5 <= pct_from_open <= 2.5:
            score += 40
        elif 1.0 <= pct_from_open < 1.5:
            score += 30
        elif 2.5 < pct_from_open <= 3.0:
            score += 30
        else:
            score += 20

        # 2. 당일 누적 거래대금 (max 30)
        try:
            tr_amount = float(data['amount'].sum()) if 'amount' in data.columns else 0.0
        except Exception:
            tr_amount = 0.0
        if tr_amount >= 50_000_000_000:
            score += 30
        elif tr_amount >= 20_000_000_000:
            score += 25
        elif tr_amount >= 10_000_000_000:
            score += 20
        elif tr_amount >= 5_000_000_000:
            score += 15
        else:
            score += 10

        # 3. 당일 고가 대비 현재가 위치 (max 20)
        try:
            day_high = float(data['high'].max()) if 'high' in data.columns else current_price
            day_low = float(data['low'].min()) if 'low' in data.columns else current_price
        except Exception:
            day_high = current_price
            day_low = current_price
        if day_high > day_low > 0:
            position = (current_price - day_low) / (day_high - day_low)
            score += position * 20

        return round(score, 1)

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
            
            # 🆕 현재 처리 중인 종목 코드 저장 (디버깅용)
            self._current_stock_code = stock_code

            # macd_cross 는 main.py::_evaluate_macd_cross_window 에서 직접 분기 처리.
            # 본 analyze_buy_decision 진입경로는 macd_cross 에서는 사용 안 함.
            if self.active_strategy == 'macd_cross':
                return False, "macd_cross 는 _evaluate_macd_cross_window 경로 사용", buy_info
            # 폐기된 전략 호환 (실행되지 않음 — validate_settings 가 차단)
            return False, f"미지원 전략: {self.active_strategy}", buy_info
            signal_result, reason, price_info = False, "", None  # noqa: unreachable
            if signal_result and price_info:
                # 성과 게이트 체크 (전략 신호 통과 후 — 가상 추적 정확도 보장)
                if self.performance_gate:
                    gate_allowed, gate_reason = self.performance_gate.check_gate()
                    if not gate_allowed:
                        self.logger.info(
                            f"성과 게이트 차단: {stock_code} ({gate_reason})"
                        )
                        # 가상 추적용 엔트리 기록 (전략 신호 통과 종목만, EOD에 결과 계산)
                        try:
                            trade_date = now_kst().strftime('%Y%m%d')
                            if combined_data is not None and len(combined_data) > 10:
                                entry_idx = len(combined_data) - 2
                                effective_sl = self.get_effective_stop_loss()
                                effective_tp = self.get_effective_take_profit()
                                self.performance_gate.add_shadow_entry(
                                    stock_code=stock_code,
                                    entry_price=float(combined_data.iloc[-1]['close']),
                                    entry_idx=entry_idx,
                                    trade_date=trade_date,
                                    candle_df=None,
                                    stop_loss_pct=-effective_sl * 100,
                                    take_profit_pct=effective_tp * 100,
                                )
                        except Exception as e:
                            self.logger.debug(f"가상 추적 엔트리 기록 실패: {e}")
                        return False, f"성과게이트: {gate_reason}", buy_info
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

                    # 🆕 고급 필터 적용 (pullback 전략 전용)
                    if self.use_advanced_filter and self.advanced_filter_manager and self.active_strategy == 'pullback':
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

                    # 매수 신호 승인
                    final_reason = f"눌림목캔들패턴: {reason} (ML: {ml_prob:.1%})"

                    return True, final_reason, buy_info
                else:
                    return False, "수량 계산 실패", buy_info
            
            strategy_label = {
                'weighted_score': 'weighted_score',
                'closing_trade': 'closing_trade',
            }.get(self.active_strategy, '눌림목패턴')
            return False, f"매수 조건 미충족 ({strategy_label}: {reason})" if reason else "매수 조건 미충족", buy_info
            
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
        # macd_cross: 매도는 main.py::_macd_cross_live_exit_task 가 D+2 영업일 09:01~05 +
        # EOD 안전망 경로로 처리. 본 analyze_sell_decision 는 macd_cross 에서 no-op.
        if self.active_strategy == 'macd_cross':
            return False, "macd_cross 매도는 _macd_cross_live_exit_task 경로"

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
    
    async def execute_real_buy(self, trading_stock, buy_reason, buy_price, quantity,
                               candle_time=None, strategy_tag=None, market=False):
        """실제 매수 주문 실행 (TradeExecutor 위임).

        Args:
            strategy_tag: real_trading_records.strategy 컬럼 명시 태그.
                None 이면 trading_stock.selection_reason 폴백.
            market: True 면 시장가 주문. False 면 지정가 (기본).
        """
        if self._trade_executor:
            return await self._trade_executor.execute_real_buy(
                trading_stock, buy_reason, buy_price, quantity, candle_time,
                strategy_tag=strategy_tag,
                market=market,
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
                        # 패턴 정보 없으면 기본값 (프리마켓 동적 조정 적용)
                        take_profit_percent = self.get_effective_take_profit() * 100
                        stop_loss_percent = self.get_effective_stop_loss() * 100
                else:
                    # debug_info 없으면 기본값 (프리마켓 동적 조정 적용)
                    take_profit_percent = self.get_effective_take_profit() * 100
                    stop_loss_percent = self.get_effective_stop_loss() * 100
            else:
                # 플래그가 false이거나 없으면 기본값 사용 (프리마켓 동적 조정 적용)
                take_profit_percent = self.get_effective_take_profit() * 100
                stop_loss_percent = self.get_effective_stop_loss() * 100

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
    
    
    


    # =========================================================================
    # 프리마켓 인텔리전스 연동
    # =========================================================================

    def set_pre_market_report(self, report):
        """프리마켓 인텔리전스 리포트 설정 (main.py에서 08:55에 호출)"""
        self._pre_market_report = report
        if report:
            self.logger.info(
                f"[프리마켓] 리포트 적용: 심리={report.market_sentiment}, "
                f"최대포지션={report.recommended_max_positions}, "
                f"손절={report.recommended_stop_loss_pct:.1%}, 익절={report.recommended_take_profit_pct:.1%}"
            )

    def get_pre_market_report(self):
        """현재 프리마켓 리포트 반환"""
        return self._pre_market_report

    def get_effective_max_positions(self) -> int:
        """프리마켓 분석 반영된 최대 동시 보유 종목 수.

        macd_cross 단일 운영: MacdCross.MAX_DAILY_POSITIONS (=5) 가 default.
        프리마켓 리포트가 있으면 그 값 우선 (서킷브레이커 등 시나리오).
        """
        from config.strategy_settings import StrategySettings
        default = StrategySettings.MacdCross.MAX_DAILY_POSITIONS
        if self._pre_market_report and self._pre_market_report.nxt_available:
            return self._pre_market_report.recommended_max_positions
        return default

    def get_effective_stop_loss(self) -> float:
        """[deprecated] 손절 비율. macd_cross 는 SL 없음 (HOLD_DAYS=2).

        호환용으로 trading_config 의 stop_loss_ratio (default 0.05) 반환.
        macd_cross 매도 경로(_macd_cross_live_exit_task)는 본 메서드를 사용하지 않음.
        """
        default = self.config.get('risk_management', {}).get('stop_loss_ratio', 0.05)
        if self._pre_market_report and self._pre_market_report.nxt_available:
            return self._pre_market_report.recommended_stop_loss_pct
        return default

    def get_effective_take_profit(self) -> float:
        """[deprecated] 익절 비율. macd_cross 는 TP 없음 (HOLD_DAYS=2).

        호환용으로 trading_config 의 take_profit_ratio (default 0.06) 반환.
        """
        default = self.config.get('risk_management', {}).get('take_profit_ratio', 0.06)
        if self._pre_market_report and self._pre_market_report.nxt_available:
            return self._pre_market_report.recommended_take_profit_pct
        return default

    @classmethod
    def reset_daily_trades(cls, trade_date: str = None):
        """일별 시가 캐시 초기화 (전략별 거래 기록은 해당 전략 인스턴스가 자체 관리)."""
        if trade_date:
            keys_to_remove = [k for k in cls._day_open_cache if k[1] == trade_date]
            for k in keys_to_remove:
                del cls._day_open_cache[k]
        else:
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

