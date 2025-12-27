"""
4단계 패턴 구간 데이터 로거
각 구간(상승, 하락, 지지, 돌파)의 상세 데이터를 JSON 파일로 저장
"""

import json
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class PatternDataLogger:
    """4단계 패턴 구간 데이터 로깅"""

    def __init__(self, log_dir: str = "pattern_data_log", simulation_date: Optional[str] = None):
        """
        Args:
            log_dir: 로그 디렉토리 경로
            simulation_date: 시뮬레이션 날짜 (YYYYMMDD 형식, None이면 실시간 날짜 사용)
        """
        # ⭐ 동적 손익비 설정에 따라 다른 폴더 사용
        from config.dynamic_profit_loss_config import DynamicProfitLossConfig

        if DynamicProfitLossConfig.is_dynamic_enabled():
            # 동적 손익비 사용 시 별도 폴더
            if log_dir == "pattern_data_log":
                log_dir = "pattern_data_log_dynamic"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # 날짜별 로그 파일 (시뮬레이션 날짜 또는 실시간 날짜)
        if simulation_date:
            today = simulation_date
        else:
            today = datetime.now().strftime('%Y%m%d')
        self.log_file = self.log_dir / f"pattern_data_{today}.jsonl"

        # 🆕 중복 방지를 위한 기존 패턴 ID 로드
        self.existing_pattern_ids = self._load_existing_pattern_ids()

    def log_pattern_data(
        self,
        stock_code: str,
        signal_type: str,
        confidence: float,
        support_pattern_info: Dict[str, Any],
        data_3min: pd.DataFrame,
        data_1min: Optional[pd.DataFrame] = None  # 🆕 1분봉 데이터 추가
    ) -> str:
        """
        4단계 패턴 구간 데이터 로깅

        Args:
            stock_code: 종목 코드
            signal_type: 신호 타입 (STRONG_BUY, CAUTIOUS_BUY 등)
            confidence: 신뢰도
            support_pattern_info: analyze_support_pattern 함수의 리턴값
            data_3min: 3분봉 데이터
            data_1min: 1분봉 데이터 (매수 시점 스냅샷 및 기술적 지표 계산용)

        Returns:
            pattern_id: 패턴 고유 ID
        """
        # 🆕 매수 시점 타임스탬프 (실제 신호 발생 시점)
        # support_pattern_info에 signal_time이 있으면 사용 (실시간에서 전달됨)
        if 'signal_time' in support_pattern_info:
            signal_time_str = support_pattern_info['signal_time']
            try:
                signal_time = pd.to_datetime(signal_time_str)
            except:
                signal_time = datetime.now()
        else:
            # 시뮬레이션: 마지막 3분봉의 완성 시점 사용
            if data_3min is not None and len(data_3min) > 0:
                last_candle_time = data_3min.iloc[-1]['datetime']
                # 3분봉 시작 시간에 3분을 더해 완성 시점 계산
                signal_time = last_candle_time + pd.Timedelta(minutes=3)
            else:
                signal_time = datetime.now()

        # 패턴 고유 ID 생성 (매수 시점 기준)
        pattern_id = f"{stock_code}_{signal_time.strftime('%Y%m%d_%H%M%S')}"

        # 디버그 정보 추출
        debug_info = support_pattern_info.get('debug_info', {})

        # 4개 구간 데이터 추출
        uptrend_info = debug_info.get('uptrend', {})
        decline_info = debug_info.get('decline', {})
        support_info = debug_info.get('support', {})
        breakout_info = debug_info.get('breakout', {})

        # 각 구간의 캔들 데이터 추출
        uptrend_candles = self._extract_candle_data(
            data_3min,
            uptrend_info.get('start_idx'),
            uptrend_info.get('end_idx')
        ) if uptrend_info else []

        decline_candles = self._extract_candle_data(
            data_3min,
            decline_info.get('start_idx'),
            decline_info.get('end_idx')
        ) if decline_info else []

        support_candles = self._extract_candle_data(
            data_3min,
            support_info.get('start_idx'),
            support_info.get('end_idx')
        ) if support_info else []

        breakout_candle = self._extract_single_candle(
            data_3min,
            breakout_info.get('idx')
        ) if breakout_info else None

        # breakout_idx 추출 (기술적 지표 계산용)
        breakout_idx = breakout_info.get('idx') if breakout_info else None

        # 🆕 매수 시점의 기술적 지표 계산 (3분봉 기준)
        technical_indicators_3min = {}
        if breakout_idx is not None:
            technical_indicators_3min = self._calculate_technical_indicators(data_3min, breakout_idx)

        # 🆕 1분봉 기반 상세 지표 (1분봉 데이터가 있는 경우)
        technical_indicators_1min = {}
        lookback_sequence_1min = []
        if data_1min is not None and not data_1min.empty:
            # 1분봉에서 신호 시점 찾기
            signal_1min_data = data_1min[data_1min['datetime'] <= signal_time]
            if not signal_1min_data.empty:
                signal_1min_idx = len(signal_1min_data) - 1
                technical_indicators_1min = self._calculate_technical_indicators(data_1min, signal_1min_idx)

                # 1시간 lookback 시퀀스 (60개 1분봉)
                lookback_sequence_1min = self._extract_lookback_sequence(
                    data_1min,
                    signal_time,
                    lookback_minutes=60
                )

        # 로그 레코드 생성
        log_record = {
            'pattern_id': pattern_id,
            'signal_time': signal_time.strftime('%Y-%m-%d %H:%M:%S'),  # 🆕 매수 신호 시간
            'log_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # 🆕 로깅 시간 (구분)
            'stock_code': stock_code,
            'signal_info': {
                'signal_type': signal_type,
                'confidence': float(confidence) if confidence is not None else 0.0,
                'has_pattern': support_pattern_info.get('has_support_pattern', False),
                'reasons': support_pattern_info.get('reasons', []),
                'ml_prob': support_pattern_info.get('ml_prob', None)  # 🆕 ML 예측값 추가
            },
            # 🆕 매수 시점 스냅샷
            'signal_snapshot': {
                'technical_indicators_3min': technical_indicators_3min,
                'technical_indicators_1min': technical_indicators_1min,
                'lookback_sequence_1min': lookback_sequence_1min  # 과거 60분 1분봉 시퀀스
            },
            'pattern_stages': {
                '1_uptrend': {
                    'start_idx': uptrend_info.get('start_idx'),
                    'end_idx': uptrend_info.get('end_idx'),
                    'candle_count': len(uptrend_candles),
                    # 🔄 숫자형 필드 우선 사용 (gain_pct, max_volume_numeric), 없으면 문자열 변환
                    'max_volume': self._safe_float(uptrend_info.get('max_volume_numeric', uptrend_info.get('max_volume'))),
                    'volume_avg': self._safe_float(uptrend_info.get('avg_volume', uptrend_info.get('volume_avg'))),
                    'max_volume_ratio_vs_avg': self._safe_float(uptrend_info.get('max_volume_ratio_vs_avg')),
                    'price_gain': self._safe_float(uptrend_info.get('gain_pct', uptrend_info.get('price_gain'))),
                    'high_price': self._safe_float(uptrend_info.get('high_price')),
                    'candles': uptrend_candles
                },
                '2_decline': {
                    'start_idx': decline_info.get('start_idx'),
                    'end_idx': decline_info.get('end_idx'),
                    'candle_count': len(decline_candles),
                    # 🔄 decline_pct는 문자열로 올 수 있음 (예: "2.73%")
                    'decline_pct': self._safe_float(decline_info.get('decline_pct')),
                    'max_decline_price': self._safe_float(decline_info.get('max_decline_price')),
                    'avg_volume_ratio': self._safe_float(decline_info.get('avg_volume_ratio')),
                    # ML용 추가 통계
                    'avg_volume': self._safe_float(decline_info.get('avg_volume')),
                    'candles': decline_candles
                },
                '3_support': {
                    'start_idx': support_info.get('start_idx'),
                    'end_idx': support_info.get('end_idx'),
                    'candle_count': len(support_candles),
                    'support_price': self._safe_float(support_info.get('support_price')),
                    'price_volatility': self._safe_float(support_info.get('price_volatility')),
                    'avg_volume_ratio': self._safe_float(support_info.get('avg_volume_ratio')),
                    # ML용 추가 통계
                    'avg_volume': self._safe_float(support_info.get('avg_volume')),
                    'candles': support_candles
                },
                '4_breakout': {
                    'idx': breakout_info.get('idx'),
                    'body_size': self._safe_float(breakout_info.get('body_size')),
                    'volume': self._safe_float(breakout_info.get('volume')),
                    'volume_ratio_vs_prev': self._safe_float(breakout_info.get('volume_ratio_vs_prev')),
                    'body_increase_vs_support': self._safe_float(breakout_info.get('body_increase_vs_support')),
                    'candle': breakout_candle
                }
            },
            'trade_result': None  # 나중에 업데이트
        }

        # 🆕 중복 체크
        if pattern_id in self.existing_pattern_ids:
            print(f"[스킵] 중복 패턴 ID: {pattern_id}")
            return pattern_id

        # JSONL 형식으로 저장 (파일 잠금 및 예외 처리)
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                json_str = json.dumps(log_record, ensure_ascii=False)
                # JSON이 유효한지 한번 더 검증
                json.loads(json_str)  # 파싱 테스트
                f.write(json_str + '\n')
                f.flush()  # 즉시 디스크에 쓰기

            # 🆕 저장 성공 시 메모리에 추가
            self.existing_pattern_ids.add(pattern_id)

        except Exception as e:
            # 로깅 실패해도 패턴 ID는 반환 (시뮬레이션 계속 진행)
            print(f"[경고] 패턴 데이터 로깅 실패 ({pattern_id}): {e}")

        return pattern_id

    def _safe_float(self, value, default=0.0):
        """문자열 또는 숫자를 안전하게 float로 변환"""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 쉼표와 퍼센트 기호 제거
            value = value.replace(',', '').replace('%', '').strip()
            try:
                return float(value)
            except:
                return default
        return default

    def _extract_candle_data(self, data: pd.DataFrame, start_idx: Optional[int], end_idx: Optional[int]) -> list:
        """구간의 캔들 데이터 추출"""
        if start_idx is None or end_idx is None:
            return []

        try:
            candles = []
            for idx in range(start_idx, end_idx + 1):
                if idx < len(data):
                    row = data.iloc[idx]
                    candle = {
                        'datetime': row['datetime'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(row.get('datetime')) else str(idx),
                        'open': float(row['open']) if pd.notna(row['open']) else 0.0,
                        'high': float(row['high']) if pd.notna(row['high']) else 0.0,
                        'low': float(row['low']) if pd.notna(row['low']) else 0.0,
                        'close': float(row['close']) if pd.notna(row['close']) else 0.0,
                        'volume': int(float(row['volume'])) if pd.notna(row['volume']) else 0
                    }
                    candles.append(candle)
            return candles
        except Exception as e:
            print(f"캔들 데이터 추출 오류: {e}")
            return []

    def _extract_single_candle(self, data: pd.DataFrame, idx: Optional[int]) -> Optional[dict]:
        """단일 캔들 데이터 추출"""
        if idx is None or idx >= len(data):
            return None

        try:
            row = data.iloc[idx]
            return {
                'datetime': row['datetime'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(row.get('datetime')) else str(idx),
                'open': float(row['open']) if pd.notna(row['open']) else 0.0,
                'high': float(row['high']) if pd.notna(row['high']) else 0.0,
                'low': float(row['low']) if pd.notna(row['low']) else 0.0,
                'close': float(row['close']) if pd.notna(row['close']) else 0.0,
                'volume': int(float(row['volume'])) if pd.notna(row['volume']) else 0
            }
        except Exception as e:
            print(f"캔들 데이터 추출 오류: {e}")
            return None

    def _calculate_technical_indicators(self, data: pd.DataFrame, signal_idx: int) -> Dict[str, float]:
        """
        매수 시점의 기술적 지표 계산

        Args:
            data: 분봉 데이터 (3분봉 또는 1분봉)
            signal_idx: 신호 발생 인덱스

        Returns:
            기술적 지표 딕셔너리
        """
        indicators = {}

        try:
            # 신호 시점까지의 데이터만 사용
            data_until_signal = data.iloc[:signal_idx+1].copy()

            if len(data_until_signal) < 14:
                return indicators  # 데이터 부족

            # RSI 계산 (14봉)
            close_prices = data_until_signal['close'].values
            rsi = self._calculate_rsi(close_prices, period=14)
            indicators['rsi_14'] = rsi

            # 이동평균 계산
            ma_5 = close_prices[-5:].mean() if len(close_prices) >= 5 else close_prices[-1]
            ma_10 = close_prices[-10:].mean() if len(close_prices) >= 10 else close_prices[-1]
            ma_20 = close_prices[-20:].mean() if len(close_prices) >= 20 else close_prices[-1]

            indicators['ma_5'] = float(ma_5)
            indicators['ma_10'] = float(ma_10)
            indicators['ma_20'] = float(ma_20)

            # 현재가 대비 이동평균 위치 (%)
            current_price = close_prices[-1]
            indicators['price_vs_ma5_pct'] = ((current_price - ma_5) / ma_5 * 100) if ma_5 > 0 else 0
            indicators['price_vs_ma20_pct'] = ((current_price - ma_20) / ma_20 * 100) if ma_20 > 0 else 0

            # 거래량 이동평균
            volumes = data_until_signal['volume'].values
            volume_ma_20 = volumes[-20:].mean() if len(volumes) >= 20 else volumes[-1]
            current_volume = volumes[-1]
            indicators['volume_ma_20'] = float(volume_ma_20)
            indicators['volume_vs_ma_ratio'] = (current_volume / volume_ma_20) if volume_ma_20 > 0 else 1.0

            # ATR (평균 진폭) - 14봉
            if len(data_until_signal) >= 14:
                atr = self._calculate_atr(data_until_signal, period=14)
                indicators['atr_14'] = atr
                indicators['atr_pct'] = (atr / current_price * 100) if current_price > 0 else 0

        except Exception as e:
            print(f"기술적 지표 계산 오류: {e}")

        return indicators

    def _calculate_rsi(self, prices: 'np.ndarray', period: int = 14) -> float:
        """RSI 계산"""
        try:
            import numpy as np

            if len(prices) < period + 1:
                return 50.0  # 기본값

            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)

            avg_gain = gains[-period:].mean()
            avg_loss = losses[-period:].mean()

            if avg_loss == 0:
                return 100.0

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return float(rsi)
        except Exception:
            return 50.0

    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> float:
        """ATR (Average True Range) 계산"""
        try:
            import numpy as np

            if len(data) < period + 1:
                return 0.0

            high = data['high'].values
            low = data['low'].values
            close = data['close'].values

            # True Range 계산
            tr1 = high[1:] - low[1:]  # 고가 - 저가
            tr2 = np.abs(high[1:] - close[:-1])  # 고가 - 전일종가
            tr3 = np.abs(low[1:] - close[:-1])   # 저가 - 전일종가

            tr = np.maximum(tr1, np.maximum(tr2, tr3))

            # ATR = TR의 이동평균
            atr = tr[-period:].mean() if len(tr) >= period else tr.mean()

            return float(atr)
        except Exception:
            return 0.0

    def _extract_lookback_sequence(
        self,
        data: pd.DataFrame,
        signal_time: datetime,
        lookback_minutes: int = 60
    ) -> list:
        """
        매수 시점 이전 N분간의 분봉 시퀀스 추출

        Args:
            data: 1분봉 또는 3분봉 데이터
            signal_time: 매수 신호 발생 시간
            lookback_minutes: 과거 몇 분을 볼지 (기본 60분 = 1시간)

        Returns:
            분봉 OHLCV 리스트
        """
        try:
            # 신호 시점 이전 데이터만 필터링
            data_before_signal = data[data['datetime'] <= signal_time].copy()

            if data_before_signal.empty:
                return []

            # 최근 N개 캔들 추출 (1분봉이면 60개, 3분봉이면 20개)
            candle_interval = 1 if 'datetime' in data_before_signal.columns else 3
            lookback_count = lookback_minutes // candle_interval

            recent_data = data_before_signal.tail(lookback_count)

            # OHLCV 시퀀스로 변환
            sequence = []
            for _, row in recent_data.iterrows():
                candle = {
                    'datetime': row['datetime'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(row.get('datetime')) else '',
                    'open': float(row['open']) if pd.notna(row['open']) else 0.0,
                    'high': float(row['high']) if pd.notna(row['high']) else 0.0,
                    'low': float(row['low']) if pd.notna(row['low']) else 0.0,
                    'close': float(row['close']) if pd.notna(row['close']) else 0.0,
                    'volume': int(float(row['volume'])) if pd.notna(row['volume']) else 0
                }
                sequence.append(candle)

            return sequence
        except Exception as e:
            print(f"분봉 시퀀스 추출 오류: {e}")
            return []

    def _analyze_post_trade_trajectory(self, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        매수~매도 구간 가격 궤적 분석

        Args:
            trade_data: 매매 상세 데이터

        Returns:
            분석 결과 딕셔너리
        """
        try:
            import numpy as np
            import pandas as pd

            buy_price = trade_data.get('buy_price', 0)
            sell_price = trade_data.get('sell_price', 0)
            buy_time = trade_data.get('buy_time')
            sell_time = trade_data.get('sell_time')
            df_1min = trade_data.get('df_1min_during_trade')

            if buy_price == 0 or df_1min is None or df_1min.empty:
                return {}

            # 매수~매도 구간 1분봉만 추출
            trade_candles = df_1min[
                (df_1min['datetime'] > buy_time) &
                (df_1min['datetime'] <= sell_time)
            ].copy()

            if trade_candles.empty:
                return {}

            # 시간대별 수익률 궤적
            trajectory = []
            checkpoints = [5, 10, 30, 60, 120]  # 5분, 10분, 30분, 1시간, 2시간

            for minutes in checkpoints:
                # 매수 후 N분까지의 데이터
                cutoff_time = buy_time + pd.Timedelta(minutes=minutes)
                candles_until = trade_candles[trade_candles['datetime'] <= cutoff_time]

                if candles_until.empty:
                    continue

                max_high = candles_until['high'].max()
                min_low = candles_until['low'].min()

                max_profit = ((max_high - buy_price) / buy_price) * 100
                max_loss = ((min_low - buy_price) / buy_price) * 100

                trajectory.append({
                    'minutes_after': minutes,
                    'max_profit': round(max_profit, 2),
                    'max_loss': round(max_loss, 2)
                })

            # 최고/최저 수익률 시점 찾기
            all_highs = trade_candles['high'].values
            all_lows = trade_candles['low'].values
            all_times = trade_candles['datetime'].values

            profit_rates = ((all_highs - buy_price) / buy_price) * 100
            loss_rates = ((all_lows - buy_price) / buy_price) * 100

            peak_idx = np.argmax(profit_rates)
            worst_idx = np.argmin(loss_rates)

            peak_profit_rate = profit_rates[peak_idx]
            worst_drawdown = loss_rates[worst_idx]

            # 시점 계산 (매수 후 몇 분)
            peak_time = all_times[peak_idx]
            worst_time = all_times[worst_idx]

            peak_minutes = int((peak_time - buy_time).total_seconds() / 60)
            worst_minutes = int((worst_time - buy_time).total_seconds() / 60)

            # 거래량 패턴 분석
            volumes = trade_candles['volume'].values
            volume_at_peak = trade_candles.iloc[peak_idx]['volume']
            volume_at_worst = trade_candles.iloc[worst_idx]['volume']
            avg_volume = volumes.mean()

            # 매수 직후 (첫 5분) 거래량 급증 여부
            first_5min = trade_candles.head(5) if len(trade_candles) >= 5 else trade_candles
            immediate_volume = first_5min['volume'].mean()
            immediate_volume_spike = (immediate_volume / avg_volume) if avg_volume > 0 else 1.0

            analysis = {
                # 가격 궤적
                'profit_trajectory': trajectory,

                # 주요 이벤트
                'peak_profit_reached_at': peak_minutes,
                'peak_profit_rate': round(peak_profit_rate, 2),
                'worst_drawdown': round(worst_drawdown, 2),
                'worst_drawdown_at': worst_minutes,

                # 매도 정보
                'holding_duration_minutes': int((sell_time - buy_time).total_seconds() / 60),
                'final_profit_rate': round(((sell_price - buy_price) / buy_price) * 100, 2),

                # 거래량 패턴
                'volume_pattern': {
                    'immediate_spike_ratio': round(immediate_volume_spike, 2),
                    'avg_volume_during_trade': int(avg_volume),
                    'volume_at_peak': int(volume_at_peak),
                    'volume_at_worst': int(volume_at_worst)
                },

                # 매수~매도 구간 1분봉 저장 (선택사항 - 용량 고려)
                # 'trade_candles': trade_candles.to_dict('records')  # 필요시 활성화
            }

            return analysis

        except Exception as e:
            print(f"가격 궤적 분석 오류: {e}")
            return {}

    def update_trade_result(
        self,
        pattern_id: str,
        trade_executed: bool,
        profit_rate: Optional[float] = None,
        sell_reason: Optional[str] = None,
        trade_data: Optional[Dict[str, Any]] = None  # 🆕 매수~매도 구간 데이터
    ):
        """
        매매 결과 업데이트

        Args:
            pattern_id: 패턴 고유 ID
            trade_executed: 거래 실행 여부
            profit_rate: 수익률
            sell_reason: 매도 사유
            trade_data: 매수~매도 구간 상세 데이터 (옵션)
                {
                    'buy_time': datetime,
                    'sell_time': datetime,
                    'buy_price': float,
                    'sell_price': float,
                    'max_profit_rate': float,
                    'max_loss_rate': float,
                    'duration_minutes': int,
                    'df_1min_during_trade': DataFrame  # 매수~매도 구간 1분봉
                }
        """
        if not self.log_file.exists():
            return

        try:
            # 전체 로그 읽기 (예외 처리)
            records = []
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if line.strip():
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            # 파싱 실패한 라인은 스킵
                            print(f"[경고] 패턴 업데이트 중 라인 {line_num} 파싱 실패: {e}")
                            continue

            # 해당 pattern_id 찾아서 업데이트
            updated = False
            for record in records:
                if record.get('pattern_id') == pattern_id:
                    # 기본 매매 결과
                    result_data = {
                        'trade_executed': trade_executed,
                        'profit_rate': profit_rate,
                        'sell_reason': sell_reason,
                        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }

                    # 🆕 매수~매도 구간 상세 분석 추가
                    if trade_data is not None:
                        post_trade_analysis = self._analyze_post_trade_trajectory(trade_data)
                        result_data['post_trade_analysis'] = post_trade_analysis

                    record['trade_result'] = result_data
                    updated = True
                    break

            if updated:
                # 파일 다시 쓰기 (예외 처리)
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    for record in records:
                        try:
                            json_str = json.dumps(record, ensure_ascii=False)
                            # JSON이 유효한지 검증
                            json.loads(json_str)
                            f.write(json_str + '\n')
                        except Exception as e:
                            print(f"[경고] 레코드 쓰기 실패 ({record.get('pattern_id', 'unknown')}): {e}")
                            continue
                    f.flush()
        except Exception as e:
            print(f"[경고] 패턴 업데이트 실패 ({pattern_id}): {e}")

    def _load_existing_pattern_ids(self) -> set:
        """
        기존 패턴 파일에서 이미 저장된 패턴 ID 로드
        중복 방지용

        Returns:
            set: 기존 패턴 ID 집합
        """
        existing_ids = set()

        if not self.log_file.exists():
            return existing_ids

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        pattern_id = record.get('pattern_id')
                        if pattern_id:
                            existing_ids.add(pattern_id)
                    except json.JSONDecodeError:
                        # 손상된 라인은 무시
                        continue

            print(f"[패턴로거] 기존 패턴 ID {len(existing_ids)}개 로드 완료")

        except Exception as e:
            print(f"[경고] 기존 패턴 ID 로드 실패: {e}")

        return existing_ids
