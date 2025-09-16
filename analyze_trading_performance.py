#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
09/08~09/16 매매 기록 종합 분석 및 개선된 신호 생성 함수 생성
승패 패턴을 분석하여 generate_improved_signals_new 함수를 생성합니다.
"""

import os
import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pickle
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

class TradingPerformanceAnalyzer:
    """매매 성과 종합 분석기"""

    def __init__(self):
        self.signal_replay_dir = r"C:\GIT\RoboTrader\signal_replay_log"
        self.cache_dir = r"C:\GIT\RoboTrader\cache"
        self.trades_data = []
        self.signal_analysis = []
        self.market_data_cache = {}

    def load_market_data(self, stock_code, date):
        """캐시된 시장 데이터 로드"""
        cache_key = f"{stock_code}_{date}"
        if cache_key in self.market_data_cache:
            return self.market_data_cache[cache_key]

        # 분봉 데이터 로드
        minute_file = os.path.join(self.cache_dir, "minute_data", f"{stock_code}_{date}.pkl")
        if os.path.exists(minute_file):
            with open(minute_file, 'rb') as f:
                minute_data = pickle.load(f)
            self.market_data_cache[cache_key] = minute_data
            return minute_data

        return None

    def load_daily_data(self, stock_code):
        """일봉 데이터 로드"""
        daily_file = os.path.join(self.cache_dir, "daily_data", f"{stock_code}_daily.pkl")
        if os.path.exists(daily_file):
            with open(daily_file, 'rb') as f:
                return pickle.load(f)
        return None

    def parse_signal_replay_file(self, file_path):
        """매매 기록 파일 상세 파싱"""
        trades = []
        signals = []

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 파일명에서 날짜 추출
        filename = os.path.basename(file_path)
        date_match = re.search(r'(\d{8})', filename)
        if not date_match:
            return trades, signals

        date_str = date_match.group(1)

        # 종목별 섹션 분리
        sections = re.split(r'=== (\d{6}) - \d{8}.*?신호 재현 ===', content)

        for i in range(1, len(sections), 2):
            if i + 1 >= len(sections):
                break

            stock_code = sections[i]
            section_content = sections[i + 1]

            # 승패 정보 추출
            win_loss_match = re.search(r'승패: (\d+)승 (\d+)패', section_content)
            if not win_loss_match:
                continue

            wins = int(win_loss_match.group(1))
            losses = int(win_loss_match.group(2))

            # 체결 시뮬레이션 추출 - 더 정확한 패턴
            execution_pattern = r'(\d{2}:\d{2}) 매수\[(.*?)\] @([0-9,]+) → (\d{2}:\d{2}) 매도\[(.*?)\] @([0-9,]+) \(([+-]?\d+\.?\d*)%\)'
            execution_matches = re.findall(execution_pattern, section_content)

            # 상세 3분봉 분석에서 신호 정보 추출
            signal_pattern = r'(\d{2}:\d{2})→(\d{2}:\d{2}): 종가:([0-9,]+) \| 거래량:([0-9,]+) \| (.+?) \| 신뢰도:(\d+)%'
            signal_matches = re.findall(signal_pattern, section_content)

            # 체결된 거래 기록
            for execution in execution_matches:
                buy_time, signal_type, buy_price, sell_time, sell_reason, sell_price, profit_pct = execution

                trade = {
                    'date': date_str,
                    'stock_code': stock_code,
                    'buy_time': buy_time,
                    'sell_time': sell_time,
                    'signal_type': signal_type,
                    'buy_price': int(buy_price.replace(',', '')),
                    'sell_price': int(sell_price.replace(',', '')),
                    'profit_pct': float(profit_pct),
                    'sell_reason': sell_reason,
                    'is_profit': float(profit_pct) > 0,
                    'wins': wins,
                    'losses': losses
                }
                trades.append(trade)

            # 모든 신호 기록 (성공/실패 모두)
            for signal in signal_matches:
                start_time, end_time, close_price, volume, status, confidence = signal

                # 신호 타입 분류
                is_buy_signal = '🟢' in status or 'STRONG_BUY' in status or 'CAUTIOUS_BUY' in status
                is_avoid = '🔴회피' in status or 'AVOID' in status

                signal_record = {
                    'date': date_str,
                    'stock_code': stock_code,
                    'time': start_time,
                    'close_price': int(close_price.replace(',', '')),
                    'volume': int(volume.replace(',', '')),
                    'status': status,
                    'confidence': int(confidence),
                    'is_buy_signal': is_buy_signal,
                    'is_avoid': is_avoid,
                    'wins': wins,
                    'losses': losses
                }
                signals.append(signal_record)

        return trades, signals

    def analyze_all_files(self):
        """09/08~09/16 기간의 모든 파일 분석"""
        print("📊 09/08~09/16 매매 기록 종합 분석 시작...")

        # 분석 대상 날짜 목록
        target_dates = [
            '20250908', '20250909', '20250910', '20250911', '20250912',
            '20250915', '20250916'
        ]

        for date_str in target_dates:
            file_pattern = f"signal_new2_replay_{date_str}_9_00_0.txt"
            file_path = os.path.join(self.signal_replay_dir, file_pattern)

            if os.path.exists(file_path):
                print(f"  📁 분석 중: {file_pattern}")
                trades, signals = self.parse_signal_replay_file(file_path)
                self.trades_data.extend(trades)
                self.signal_analysis.extend(signals)
            else:
                print(f"  ❌ 파일 없음: {file_pattern}")

        print(f"✅ 총 {len(self.trades_data)}개 거래, {len(self.signal_analysis)}개 신호 기록 수집 완료")

        return pd.DataFrame(self.trades_data), pd.DataFrame(self.signal_analysis)

    def analyze_win_loss_factors(self, trades_df, signals_df):
        """승패 요인 상세 분석"""
        print("\n🎯 승패 요인 분석...")

        if trades_df.empty:
            print("분석할 거래 데이터가 없습니다.")
            return {}

        # 기본 통계
        total_trades = len(trades_df)
        profit_trades = trades_df[trades_df['is_profit'] == True]
        loss_trades = trades_df[trades_df['is_profit'] == False]

        win_rate = len(profit_trades) / total_trades * 100 if total_trades > 0 else 0

        print(f"📈 기본 통계:")
        print(f"  총 거래: {total_trades}건")
        print(f"  승리: {len(profit_trades)}건 ({win_rate:.1f}%)")
        print(f"  패배: {len(loss_trades)}건 ({100-win_rate:.1f}%)")

        # 수익률 분석
        if not profit_trades.empty:
            avg_profit = profit_trades['profit_pct'].mean()
            max_profit = profit_trades['profit_pct'].max()
            print(f"  평균 수익률: {avg_profit:.2f}%")
            print(f"  최대 수익률: {max_profit:.2f}%")

        if not loss_trades.empty:
            avg_loss = loss_trades['profit_pct'].mean()
            max_loss = loss_trades['profit_pct'].min()
            print(f"  평균 손실률: {avg_loss:.2f}%")
            print(f"  최대 손실률: {max_loss:.2f}%")

        # 시간대별 승률 분석
        trades_df['buy_hour'] = pd.to_datetime(trades_df['buy_time'], format='%H:%M').dt.hour
        hourly_analysis = trades_df.groupby('buy_hour').agg({
            'is_profit': ['count', 'sum', 'mean'],
            'profit_pct': ['mean', 'std']
        }).round(2)

        print(f"\n⏰ 시간대별 분석:")
        for hour in hourly_analysis.index:
            count = hourly_analysis.loc[hour, ('is_profit', 'count')]
            win_rate_hour = hourly_analysis.loc[hour, ('is_profit', 'mean')] * 100
            avg_profit_hour = hourly_analysis.loc[hour, ('profit_pct', 'mean')]
            print(f"  {hour:02d}시: {count}건, 승률 {win_rate_hour:.1f}%, 평균수익률 {avg_profit_hour:.2f}%")

        # 매도 사유별 분석
        sell_reason_analysis = trades_df.groupby('sell_reason').agg({
            'is_profit': ['count', 'mean'],
            'profit_pct': 'mean'
        }).round(2)

        print(f"\n🚪 매도 사유별 분석:")
        for reason in sell_reason_analysis.index:
            count = sell_reason_analysis.loc[reason, ('is_profit', 'count')]
            win_rate_reason = sell_reason_analysis.loc[reason, ('is_profit', 'mean')] * 100
            avg_profit_reason = sell_reason_analysis.loc[reason, ('profit_pct', 'mean')]
            print(f"  {reason}: {count}건, 승률 {win_rate_reason:.1f}%, 평균수익률 {avg_profit_reason:.2f}%")

        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'hourly_analysis': hourly_analysis,
            'sell_reason_analysis': sell_reason_analysis,
            'profit_trades': profit_trades,
            'loss_trades': loss_trades
        }

    def analyze_market_conditions(self, trades_df):
        """시장 환경별 성과 분석"""
        print(f"\n🌍 시장 환경별 성과 분석...")

        market_analysis = {}

        for _, trade in trades_df.iterrows():
            stock_code = trade['stock_code']
            date = trade['date']

            # 일봉 데이터로 시장 환경 분석
            daily_data = self.load_daily_data(stock_code)
            if daily_data is None:
                continue

            # 거래일 전후 5일 데이터로 추세 판단
            trade_date = datetime.strptime(date, '%Y%m%d')

            # 5일 이평선 기울기로 추세 판단
            if len(daily_data) >= 10:
                recent_data = daily_data.tail(10)
                ma5 = recent_data['close'].rolling(5).mean()

                if len(ma5) >= 2:
                    ma5_slope = (ma5.iloc[-1] - ma5.iloc[-2]) / ma5.iloc[-2] * 100

                    if ma5_slope > 0.5:
                        market_condition = '상승장'
                    elif ma5_slope < -0.5:
                        market_condition = '하락장'
                    else:
                        market_condition = '횡보장'

                    if market_condition not in market_analysis:
                        market_analysis[market_condition] = {'trades': [], 'profits': []}

                    market_analysis[market_condition]['trades'].append(trade['is_profit'])
                    market_analysis[market_condition]['profits'].append(trade['profit_pct'])

        print(f"💹 시장 환경별 성과:")
        for condition, data in market_analysis.items():
            if len(data['trades']) > 0:
                win_rate = sum(data['trades']) / len(data['trades']) * 100
                avg_profit = np.mean(data['profits'])
                print(f"  {condition}: {len(data['trades'])}건, 승률 {win_rate:.1f}%, 평균수익률 {avg_profit:.2f}%")

        return market_analysis

    def identify_winning_patterns(self, trades_df, signals_df):
        """승리 패턴 식별"""
        print(f"\n🏆 승리 패턴 식별...")

        if trades_df.empty:
            return {}

        profit_trades = trades_df[trades_df['is_profit'] == True]
        loss_trades = trades_df[trades_df['is_profit'] == False]

        patterns = {}

        # 1. 신호 타입별 승률
        signal_type_analysis = trades_df.groupby('signal_type').agg({
            'is_profit': ['count', 'mean'],
            'profit_pct': 'mean'
        }).round(2)

        patterns['signal_types'] = {}
        for signal_type in signal_type_analysis.index:
            count = signal_type_analysis.loc[signal_type, ('is_profit', 'count')]
            win_rate = signal_type_analysis.loc[signal_type, ('is_profit', 'mean')] * 100
            avg_profit = signal_type_analysis.loc[signal_type, ('profit_pct', 'mean')]

            patterns['signal_types'][signal_type] = {
                'count': count,
                'win_rate': win_rate,
                'avg_profit': avg_profit
            }

            print(f"  📊 {signal_type}: {count}건, 승률 {win_rate:.1f}%, 평균수익률 {avg_profit:.2f}%")

        # 2. 가격대별 승률 분석
        trades_df['price_range'] = pd.cut(trades_df['buy_price'], bins=5, labels=['매우저가', '저가', '중가', '고가', '매우고가'])
        price_analysis = trades_df.groupby('price_range').agg({
            'is_profit': ['count', 'mean'],
            'profit_pct': 'mean'
        }).round(2)

        patterns['price_ranges'] = {}
        print(f"\n💰 가격대별 분석:")
        for price_range in price_analysis.index:
            if pd.isna(price_range):
                continue
            count = price_analysis.loc[price_range, ('is_profit', 'count')]
            win_rate = price_analysis.loc[price_range, ('is_profit', 'mean')] * 100
            avg_profit = price_analysis.loc[price_range, ('profit_pct', 'mean')]

            patterns['price_ranges'][price_range] = {
                'count': count,
                'win_rate': win_rate,
                'avg_profit': avg_profit
            }

            print(f"  {price_range}: {count}건, 승률 {win_rate:.1f}%, 평균수익률 {avg_profit:.2f}%")

        return patterns

    def generate_improvement_recommendations(self, analysis_results, patterns):
        """개선 방안 도출"""
        print(f"\n💡 개선 방안 도출...")

        recommendations = {}

        # 1. 시간대 필터링
        hourly_data = analysis_results.get('hourly_analysis')
        if hourly_data is not None:
            good_hours = []
            bad_hours = []

            for hour in hourly_data.index:
                win_rate = hourly_data.loc[hour, ('is_profit', 'mean')] * 100
                count = hourly_data.loc[hour, ('is_profit', 'count')]

                if count >= 3:  # 충분한 샘플이 있는 경우만
                    if win_rate >= 60:
                        good_hours.append(hour)
                    elif win_rate <= 30:
                        bad_hours.append(hour)

            recommendations['time_filter'] = {
                'good_hours': good_hours,
                'bad_hours': bad_hours
            }

            print(f"⏰ 시간대 필터:")
            print(f"  추천 시간대: {good_hours}")
            print(f"  회피 시간대: {bad_hours}")

        # 2. 신호 타입 개선
        signal_types = patterns.get('signal_types', {})
        good_signals = []
        bad_signals = []

        for signal_type, data in signal_types.items():
            if data['count'] >= 3:  # 충분한 샘플
                if data['win_rate'] >= 60:
                    good_signals.append(signal_type)
                elif data['win_rate'] <= 30:
                    bad_signals.append(signal_type)

        recommendations['signal_filter'] = {
            'good_signals': good_signals,
            'bad_signals': bad_signals
        }

        print(f"📊 신호 타입 필터:")
        print(f"  강화할 신호: {good_signals}")
        print(f"  약화할 신호: {bad_signals}")

        # 3. 추가 필터 조건
        sell_reasons = analysis_results.get('sell_reason_analysis')
        if sell_reasons is not None:
            stop_loss_trades = 0
            profit_taking_trades = 0

            for reason in sell_reasons.index:
                count = sell_reasons.loc[reason, ('is_profit', 'count')]
                if '손절' in reason or 'BREAK' in reason or '이탈' in reason:
                    stop_loss_trades += count
                elif '익절' in reason or 'PROFIT' in reason or '3%' in reason:
                    profit_taking_trades += count

            recommendations['risk_management'] = {
                'stop_loss_ratio': stop_loss_trades / (stop_loss_trades + profit_taking_trades) if (stop_loss_trades + profit_taking_trades) > 0 else 0,
                'profit_taking_ratio': profit_taking_trades / (stop_loss_trades + profit_taking_trades) if (stop_loss_trades + profit_taking_trades) > 0 else 0
            }

            print(f"🛡️ 리스크 관리:")
            print(f"  손절 비율: {recommendations['risk_management']['stop_loss_ratio']:.1%}")
            print(f"  익절 비율: {recommendations['risk_management']['profit_taking_ratio']:.1%}")

        return recommendations

    def create_improved_signal_function(self, recommendations):
        """개선된 신호 생성 함수 생성"""
        print(f"\n🚀 개선된 신호 생성 함수 생성 중...")

        # pullback_candle_pattern.py 읽기
        pattern_file = r"C:\GIT\RoboTrader\core\indicators\pullback_candle_pattern.py"
        with open(pattern_file, 'r', encoding='utf-8') as f:
            original_code = f.read()

        # generate_improved_signals_new 함수 생성
        new_function = '''
    @staticmethod
    def generate_improved_signals_new(
        data: pd.DataFrame,
        stock_code: str = "UNKNOWN",
        debug: bool = False,
        entry_price: Optional[float] = None,
        entry_low: Optional[float] = None,
        logger: Optional[logging.Logger] = None,
        return_risk_signals: bool = False,
        prev_close: Optional[float] = None
    ) -> Union[Optional[SignalStrength], Tuple[SignalStrength, List[RiskSignal]]]:
        """
        개선된 신호 생성 로직 NEW - 09/08~09/16 매매 기록 분석 결과 반영

        주요 개선사항:
        1. 시간대별 필터링 강화
        2. 시장 환경 고려
        3. 신호 신뢰도 임계값 조정
        4. 일봉 데이터 활용한 추세 필터
        5. 거래량 조건 강화
        """

        # 기존 함수와 동일한 기본 검증
        data = data.copy()
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']

        for col in numeric_columns:
            if col in data.columns:
                if pd.api.types.is_numeric_dtype(data[col]):
                    data[col] = data[col].astype(float)
                else:
                    data[col] = pd.to_numeric(data[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0.0)

        if len(data) < 5:
            result = SignalStrength(SignalType.AVOID, 0, 0, ['데이터 부족'], 0, BisectorStatus.BROKEN) if return_risk_signals else None
            return (result, []) if return_risk_signals else result

        # 로거 설정
        if logger is None:
            logger = setup_logger(f"pullback_pattern_new_{stock_code}")
            logger._stock_code = stock_code

        try:
            current = data.iloc[-1]

            # 📊 NEW: 시간대 필터링 (분석 결과 반영)
            if 'datetime' in data.columns:
                try:
                    current_time = pd.to_datetime(current['datetime'])
                    current_hour = current_time.hour

                    # 분석 결과에 따른 회피 시간대'''

        # 분석 결과에 따른 시간대 필터 추가
        good_hours = recommendations.get('time_filter', {}).get('good_hours', [])
        bad_hours = recommendations.get('time_filter', {}).get('bad_hours', [])

        if bad_hours:
            new_function += f'''
                    bad_hours = {bad_hours}
                    if current_hour in bad_hours:
                        result = SignalStrength(SignalType.AVOID, 0, 0,
                                              [f"저성과시간대회피({current_hour}시)"], 0, BisectorStatus.BROKEN)
                        return (result, []) if return_risk_signals else result'''

        if good_hours:
            new_function += f'''

                    # 고성과 시간대에서는 신뢰도 보너스 적용
                    good_hours = {good_hours}
                    time_bonus = 10 if current_hour in good_hours else 0'''
        else:
            new_function += '''
                    time_bonus = 0'''

        new_function += '''
                except:
                    time_bonus = 0
            else:
                time_bonus = 0

            # 💹 NEW: 일봉 데이터를 활용한 시장 환경 필터
            daily_trend_filter_passed = True
            trend_bonus = 0

            try:
                # 현재 종가 기준 5일 이평선 추세 확인
                if len(data) >= 5:
                    ma5 = data['close'].rolling(5).mean()
                    if len(ma5) >= 2 and not pd.isna(ma5.iloc[-1]) and not pd.isna(ma5.iloc[-2]):
                        ma5_slope = (ma5.iloc[-1] - ma5.iloc[-2]) / ma5.iloc[-2] * 100

                        # 강한 하락 추세에서는 거래 회피
                        if ma5_slope < -2.0:  # 2% 이상 하락 추세
                            daily_trend_filter_passed = False
                        elif ma5_slope > 1.0:  # 1% 이상 상승 추세
                            trend_bonus = 10
            except:
                pass

            if not daily_trend_filter_passed:
                result = SignalStrength(SignalType.AVOID, 0, 0,
                                      ["강한하락추세-거래회피"], 0, BisectorStatus.BROKEN)
                return (result, []) if return_risk_signals else result

            # 🔧 기존 로직 실행 (기본 분석)
            baseline_volumes = PullbackUtils.calculate_daily_baseline_volume(data)

            try:
                from core.indicators.bisector_line import BisectorLine
                bisector_line_series = BisectorLine.calculate_bisector_line(data['high'], data['low'])
                bisector_line = bisector_line_series.iloc[-1] if bisector_line_series is not None and not bisector_line_series.empty else None
            except:
                bisector_line = None

            period = min(10, len(data) - 1)
            volume_analysis = PullbackUtils.analyze_volume(data, period, baseline_volumes)
            candle_analysis = PullbackUtils.analyze_candle(data, period, prev_close)
            recent_low = PullbackUtils.find_recent_low(data) or 0

            # 위험 신호 체크
            risk_signals = PullbackUtils.check_risk_signals(
                current, bisector_line, entry_low, recent_low, entry_price,
                volume_analysis, candle_analysis
            )

            if risk_signals:
                signal_strength = SignalStrength(
                    SignalType.SELL if return_risk_signals else SignalType.AVOID,
                    100 if return_risk_signals else 0,
                    0,
                    [f'위험신호: {r.value}' for r in risk_signals],
                    volume_analysis.volume_ratio,
                    PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN
                )
                return (signal_strength, risk_signals) if return_risk_signals else signal_strength

            # 🚀 NEW: 거래량 조건 강화
            enhanced_volume_filter = True
            current_volume = float(current['volume'])
            baseline_volume = float(baseline_volumes.iloc[-1]) if len(baseline_volumes) > 0 else 0

            if baseline_volume > 0:
                volume_ratio = current_volume / baseline_volume
                # 최소 거래량 조건 강화 (기존 25% → 35%)
                if volume_ratio < 0.35:
                    enhanced_volume_filter = False
                elif volume_ratio > 1.5:  # 대량 거래 시 보너스
                    trend_bonus += 5

            # 기본 매수 조건들 체크 (기존 로직과 동일)
            if len(data) > 0:
                daily_open = float(data['open'].iloc[0])
                current_close = float(current['close'])

                if current_close <= daily_open:
                    result = SignalStrength(SignalType.AVOID, 0, 0,
                                          ["당일시가이하위치-매수금지"],
                                          volume_analysis.volume_ratio,
                                          PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN)
                    return (result, []) if return_risk_signals else result

            # 이등분선 체크 (기존과 동일)
            if bisector_line is not None:
                current_open = float(current['open'])
                current_close = float(current['close'])
                current_bisector = float(bisector_line)

                breakout_body_high = max(current_open, current_close)

                if breakout_body_high < current_bisector:
                    result = SignalStrength(SignalType.AVOID, 0, 0,
                                          [f"돌파봉몸통최고점({breakout_body_high:.0f})이 이등분선({current_bisector:.0f}) 아래"],
                                          volume_analysis.volume_ratio,
                                          BisectorStatus.BROKEN)
                    return (result, []) if return_risk_signals else result

            # 대형 캔들 체크 (기존과 동일)
            baseline_price = prev_close if prev_close and prev_close > 0 else (float(data['close'].iloc[0]) if len(data) > 0 else float(data['open'].iloc[0]))

            if baseline_price > 0:
                candle_bodies = abs(data['close'] - data['open'])
                candle_body_pcts = (candle_bodies / baseline_price * 100)
                has_large_candle = (candle_body_pcts >= 1.5).any()
            else:
                has_large_candle = False

            if not has_large_candle:
                result = SignalStrength(SignalType.AVOID, 0, 0,
                                      ["1.5%이상봉없음-매수금지"],
                                      volume_analysis.volume_ratio,
                                      PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN)
                return (result, []) if return_risk_signals else result

            # 지지 패턴 분석 (기존과 동일하지만 신뢰도 임계값 조정)
            support_pattern_info = PullbackCandlePattern.analyze_support_pattern(data, debug)

            # 🎯 NEW: 신뢰도 임계값 상향 조정 (70% → 75%)
            if support_pattern_info['has_support_pattern'] and support_pattern_info['confidence'] >= 75:
                # 추가 보너스 적용
                final_confidence = support_pattern_info['confidence'] + time_bonus + trend_bonus

                # 🔒 NEW: 강화된 거래량 필터 적용
                if not enhanced_volume_filter:
                    final_confidence *= 0.7  # 거래량 부족 페널티

                bisector_status = PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN

                signal_strength = SignalStrength(
                    signal_type=SignalType.STRONG_BUY if final_confidence >= 85 else SignalType.CAUTIOUS_BUY,
                    confidence=min(final_confidence, 95),  # 최대 95%로 제한
                    target_profit=3.0,
                    reasons=support_pattern_info['reasons'] + ["NEW개선로직"] +
                           ([f"시간대보너스(+{time_bonus})"] if time_bonus > 0 else []) +
                           ([f"추세보너스(+{trend_bonus})"] if trend_bonus > 0 else []),
                    volume_ratio=volume_analysis.volume_ratio,
                    bisector_status=bisector_status,
                    buy_price=support_pattern_info.get('entry_price'),
                    entry_low=support_pattern_info.get('entry_price')
                )

                return (signal_strength, []) if return_risk_signals else signal_strength

            # 기존 로직 (더 보수적으로 적용)
            has_prior_uptrend = support_pattern_info.get('has_support_pattern', False)
            pullback_quality = PullbackCandlePattern.analyze_pullback_quality(data, baseline_volumes)

            # 회피 조건 체크 (기존과 동일)
            has_selling_pressure = PullbackCandlePattern.check_heavy_selling_pressure(data, baseline_volumes)
            has_bearish_restriction = PullbackCandlePattern.check_bearish_volume_restriction(data, baseline_volumes)
            bisector_volume_ok = PullbackCandlePattern.check_bisector_breakout_volume(data)

            risk_score = 0
            if has_selling_pressure:
                risk_score += 30
            if has_bearish_restriction:
                risk_score += 25
            if not bisector_volume_ok:
                risk_score += 15
            if not enhanced_volume_filter:
                risk_score += 20  # NEW: 거래량 부족 페널티

            # 🎯 NEW: 더 보수적인 위험도 임계값 (50 → 40)
            risk_threshold = 0 if return_risk_signals else 40

            if risk_score > risk_threshold:
                avoid_result = PullbackUtils.handle_avoid_conditions(
                    has_selling_pressure, has_bearish_restriction, bisector_volume_ok,
                    current, volume_analysis, bisector_line, data, debug, logger
                )
                if avoid_result:
                    return (avoid_result, []) if return_risk_signals else avoid_result

            # 기존 매수 신호 계산 (더 보수적 접근)
            is_recovery_candle = candle_analysis.is_bullish
            volume_recovers = PullbackUtils.check_volume_recovery(data)
            has_retrace = PullbackUtils.check_low_volume_retrace(data)
            crosses_bisector_up = PullbackUtils.check_bisector_cross_up(data) if bisector_line else False
            has_overhead_supply = PullbackUtils.check_overhead_supply(data)

            bisector_status = PullbackUtils.get_bisector_status(current['close'], bisector_line) if bisector_line else BisectorStatus.BROKEN

            # 이등분선 아래 위치 시 신호 차단
            if bisector_line and current['close'] < bisector_line:
                result = SignalStrength(SignalType.AVOID, 0, 0,
                                      ["이등분선아래위치-매수금지"],
                                      volume_analysis.volume_ratio,
                                      BisectorStatus.BROKEN)
                return (result, []) if return_risk_signals else result

            # 신호 강도 계산
            signal_strength = PullbackUtils.calculate_signal_strength(
                volume_analysis, bisector_status, is_recovery_candle, volume_recovers,
                has_retrace, crosses_bisector_up, has_overhead_supply, data
            )

            # 필수 조건 검증 (더 엄격하게)
            mandatory_failed = []

            if not has_prior_uptrend:
                mandatory_failed.append("선행상승미충족")
            if not is_recovery_candle:
                mandatory_failed.append("회복양봉미충족")
            if not volume_recovers:
                mandatory_failed.append("거래량회복미충족")
            if not enhanced_volume_filter:  # NEW: 거래량 조건 추가
                mandatory_failed.append("거래량조건미충족")

            # 4단계 패턴 강제 요구
            pullback_condition_met = (has_prior_uptrend and is_recovery_candle and pullback_quality['has_quality_pullback'] and enhanced_volume_filter)

            if not pullback_condition_met or len(mandatory_failed) > 0:
                avoid_reasons = mandatory_failed if mandatory_failed else ["기본조건미충족"]
                result = SignalStrength(SignalType.AVOID, 0, 0,
                                       avoid_reasons,
                                       volume_analysis.volume_ratio,
                                       PullbackUtils.get_bisector_status(current['close'], bisector_line))
                return (result, []) if return_risk_signals else result

            # 보너스 적용
            signal_strength.confidence += time_bonus + trend_bonus

            # 대량 매물 필터
            high_volume_decline_filter = PullbackCandlePattern.check_high_volume_decline_recovery(data, baseline_volumes)
            if high_volume_decline_filter['should_avoid']:
                result = SignalStrength(SignalType.AVOID, 0, 0,
                                      [f"대량매물미회복: {high_volume_decline_filter['reason']}"],
                                      volume_analysis.volume_ratio,
                                      PullbackUtils.get_bisector_status(current['close'], bisector_line))
                return (result, []) if return_risk_signals else result

            # 🎯 NEW: 신뢰도 임계값 상향 조정 (45% → 55%)
            confidence_threshold = 55

            if signal_strength.confidence < confidence_threshold:
                result = SignalStrength(SignalType.AVOID, 0, 0,
                                      [f"신뢰도부족({signal_strength.confidence:.0f}%)"] + signal_strength.reasons,
                                      volume_analysis.volume_ratio,
                                      signal_strength.bisector_status)
                return (result, []) if return_risk_signals else result

            # 매수 신호 발생시 3/5가 계산 (기존과 동일)
            if signal_strength.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY]:
                if is_recovery_candle and volume_recovers:
                    sig_high = float(data['high'].iloc[-1])
                    sig_low = float(data['low'].iloc[-1])

                    three_fifths_price = sig_low + (sig_high - sig_low) * 0.8

                    if three_fifths_price > 0 and sig_low <= three_fifths_price <= sig_high:
                        signal_strength.buy_price = three_fifths_price
                        signal_strength.entry_low = sig_low
                    else:
                        signal_strength.buy_price = float(current['close'])
                        signal_strength.entry_low = float(current['low'])
                else:
                    signal_strength.buy_price = float(current['close'])
                    signal_strength.entry_low = float(current['low'])

            return (signal_strength, []) if return_risk_signals else signal_strength

        except Exception as e:
            if debug and logger:
                logger.error(f"NEW 신호 생성 중 오류: {e}")
            result = SignalStrength(SignalType.AVOID, 0, 0, [f'오류: {str(e)}'], 0, BisectorStatus.BROKEN) if return_risk_signals else None
            return (result, []) if return_risk_signals else result
'''

        # 기존 파일에 새 함수 추가
        new_code = original_code + new_function

        # 파일 저장
        with open(pattern_file, 'w', encoding='utf-8') as f:
            f.write(new_code)

        print(f"✅ generate_improved_signals_new 함수가 {pattern_file}에 추가되었습니다!")

        return new_function

def main():
    """메인 실행 함수"""
    print("🚀 09/08~09/16 매매 성과 종합 분석 시작...")

    analyzer = TradingPerformanceAnalyzer()

    # 1. 모든 파일 분석
    trades_df, signals_df = analyzer.analyze_all_files()

    if trades_df.empty:
        print("❌ 분석할 거래 데이터가 없습니다.")
        return

    # 2. 승패 요인 분석
    win_loss_analysis = analyzer.analyze_win_loss_factors(trades_df, signals_df)

    # 3. 시장 환경별 분석
    market_analysis = analyzer.analyze_market_conditions(trades_df)

    # 4. 승리 패턴 식별
    patterns = analyzer.identify_winning_patterns(trades_df, signals_df)

    # 5. 개선 방안 도출
    recommendations = analyzer.generate_improvement_recommendations(win_loss_analysis, patterns)

    # 6. 개선된 신호 함수 생성
    new_function = analyzer.create_improved_signal_function(recommendations)

    # 7. 결과 저장
    trades_df.to_csv('trading_performance_analysis.csv', index=False, encoding='utf-8-sig')
    signals_df.to_csv('signal_analysis.csv', index=False, encoding='utf-8-sig')

    # 분석 보고서 생성
    report = f"""
📊 09/08~09/16 매매 성과 분석 보고서
{'='*50}

🏆 주요 지표:
- 총 거래수: {len(trades_df)}건
- 승률: {win_loss_analysis['win_rate']:.1f}%
- 평균 수익률: {trades_df[trades_df['is_profit']]['profit_pct'].mean():.2f}% (승리시)
- 평균 손실률: {trades_df[~trades_df['is_profit']]['profit_pct'].mean():.2f}% (패배시)

💡 주요 개선사항:
1. 시간대 필터링 강화
   - 추천 시간대: {recommendations.get('time_filter', {}).get('good_hours', [])}
   - 회피 시간대: {recommendations.get('time_filter', {}).get('bad_hours', [])}

2. 신뢰도 임계값 조정
   - 기존 70% → 신규 75% (지지패턴)
   - 기존 45% → 신규 55% (일반신호)

3. 거래량 조건 강화
   - 최소 거래량 비율: 25% → 35%
   - 대량 거래 보너스 추가

4. 일봉 추세 필터 추가
   - 강한 하락장에서 거래 회피
   - 상승장에서 신뢰도 보너스

📁 생성된 파일:
- trading_performance_analysis.csv: 거래 분석 결과
- signal_analysis.csv: 신호 분석 결과
- pullback_candle_pattern.py: 개선된 함수 추가됨

🔧 사용법:
기존 generate_improved_signals() 대신 generate_improved_signals_new()를 사용하세요.
"""

    with open('trading_analysis_report.txt', 'w', encoding='utf-8') as f:
        f.write(report)

    print(report)
    print(f"\n✅ 분석 완료! 상세 보고서는 trading_analysis_report.txt를 확인하세요.")

if __name__ == "__main__":
    main()