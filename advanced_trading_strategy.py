"""
고도화된 매매 전략 시스템

분석 결과를 바탕으로 한 개선된 매매 신호 생성:
- 현재 승률: 46.1% → 목표 승률: 55%+
- 시간대별 차별화된 전략
- 강화된 필터링 조건
- 다층 검증 시스템
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
import pickle
from pathlib import Path

class AdvancedTradingStrategy:
    """고도화된 매매 전략"""

    def __init__(self):
        self.cache_dir = Path("cache")
        self.daily_dir = self.cache_dir / "daily"
        self.minute_data_dir = self.cache_dir / "minute_data"

        # 분석 기반 최적 파라미터
        self.config = {
            # 시간대별 가중치 (분석 결과 기반)
            'time_weights': {
                'opening': 1.3,    # 56.5% 승률
                'morning': 1.1,    # 49.1% 승률
                'afternoon': 0.8,  # 32.5% 승률
                'late': 0.9        # 42.9% 승률
            },

            # 강화된 필터링 조건
            'volume_threshold': 0.20,  # 기준 거래량 20% 이하
            'bisector_range': (0.01, 0.05),  # 이등분선 위 1-5%
            'min_pattern_score': 75,   # 최소 패턴 점수
            'stop_loss_pct': -1.5,     # 1.5% 손절
            'profit_target_pct': 3.0,  # 3% 익절

            # 일봉 패턴 필터
            'require_daily_confirmation': True,
            'min_daily_volume_decline': -0.1,  # 거래량 10% 이상 감소
            'min_price_trend': 0.05,           # 가격 5% 이상 상승추세
        }

    def load_minute_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """분봉 데이터 로드"""
        file_path = self.minute_data_dir / f"{stock_code}_{date}.pkl"
        if not file_path.exists():
            return None

        try:
            with open(file_path, 'rb') as f:
                return pickle.load(f)
        except:
            return None

    def load_daily_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드"""
        try:
            date_obj = datetime.strptime(date, '%Y%m%d')
            year_month = date_obj.strftime('%Y%m')

            file_path = self.daily_dir / f"{stock_code}_{year_month}_daily.pkl"
            if not file_path.exists():
                return None

            with open(file_path, 'rb') as f:
                df = pickle.load(f)

            # 해당 날짜까지만
            df['date'] = pd.to_datetime(df['date'])
            target_date = pd.to_datetime(date)
            return df[df['date'] <= target_date].copy()
        except:
            return None

    def analyze_daily_pattern(self, daily_df: pd.DataFrame) -> Dict:
        """일봉 패턴 분석 (강화된 버전)"""
        if daily_df is None or len(daily_df) < 5:
            return {'valid': False}

        try:
            # 최근 5일 데이터
            recent_days = daily_df.tail(5).copy()

            # 가격 추세 (최근 5일)
            prices = recent_days['close'].values
            price_trend = np.polyfit(range(len(prices)), prices, 1)[0]
            price_change_pct = (prices[-1] - prices[0]) / prices[0] * 100

            # 거래량 추세 (최근 5일)
            volumes = recent_days['volume'].values
            volume_trend = np.polyfit(range(len(volumes)), volumes, 1)[0]
            volume_change_pct = (volumes[-1] - volumes[0]) / volumes[0] * 100

            # 이동평균 분석
            if len(recent_days) >= 3:
                ma3 = recent_days['close'].rolling(3).mean().iloc[-1]
                current_price = recent_days['close'].iloc[-1]
                ma_position = (current_price - ma3) / ma3 * 100
            else:
                ma_position = 0

            # 눌림목 이상적 패턴 체크
            ideal_pattern = (
                price_change_pct > self.config['min_price_trend'] and  # 가격 상승
                volume_change_pct < self.config['min_daily_volume_decline'] and  # 거래량 감소
                ma_position > 0  # 이동평균 위
            )

            return {
                'valid': True,
                'price_trend': price_trend,
                'price_change_pct': price_change_pct,
                'volume_trend': volume_trend,
                'volume_change_pct': volume_change_pct,
                'ma_position': ma_position,
                'ideal_pattern': ideal_pattern,
                'pattern_strength': self.calculate_daily_strength(
                    price_change_pct, volume_change_pct, ma_position
                )
            }

        except Exception as e:
            return {'valid': False}

    def calculate_daily_strength(self, price_change: float, volume_change: float, ma_pos: float) -> float:
        """일봉 패턴 강도 계산"""
        strength = 0

        # 가격 상승 점수 (0-40점)
        if price_change > 5:
            strength += 40
        elif price_change > 2:
            strength += 30
        elif price_change > 0:
            strength += 20

        # 거래량 감소 점수 (0-30점)
        if volume_change < -20:
            strength += 30
        elif volume_change < -10:
            strength += 25
        elif volume_change < 0:
            strength += 15

        # 이동평균 위치 점수 (0-20점)
        if ma_pos > 3:
            strength += 20
        elif ma_pos > 1:
            strength += 15
        elif ma_pos > 0:
            strength += 10

        # 추가 보너스: 이상적 조합
        if price_change > 2 and volume_change < -10 and ma_pos > 1:
            strength += 10

        return strength

    def get_time_category_and_weight(self, current_time: str) -> Tuple[str, float]:
        """시간대 분류 및 가중치 계산"""
        hour = int(current_time.split(':')[0])

        if 9 <= hour < 10:
            return "opening", self.config['time_weights']['opening']
        elif 10 <= hour < 12:
            return "morning", self.config['time_weights']['morning']
        elif 12 <= hour < 14:
            return "afternoon", self.config['time_weights']['afternoon']
        elif 14 <= hour < 15:
            return "late", self.config['time_weights']['late']
        else:
            return "other", 0.5

    def calculate_enhanced_pattern_score(self, minute_df: pd.DataFrame, current_idx: int,
                                       daily_pattern: Dict) -> Dict:
        """향상된 패턴 점수 계산"""
        try:
            current = minute_df.iloc[current_idx]

            # 기본 지표 계산
            day_high = minute_df['high'].max()
            day_low = minute_df['low'].min()
            bisector = (day_high + day_low) / 2
            base_volume = minute_df['volume'].max()

            # 1. 이등분선 위치 분석 (0-30점)
            bisector_score = 0
            if current['close'] > bisector:
                distance_ratio = (current['close'] - bisector) / bisector
                if self.config['bisector_range'][0] <= distance_ratio <= self.config['bisector_range'][1]:
                    bisector_score = 30
                elif distance_ratio < self.config['bisector_range'][0]:
                    bisector_score = 20
                elif distance_ratio > self.config['bisector_range'][1]:
                    bisector_score = 15

            # 2. 거래량 패턴 (0-25점)
            volume_score = 0
            volume_ratio = current['volume'] / base_volume if base_volume > 0 else 0
            if volume_ratio <= 0.15:
                volume_score = 25
            elif volume_ratio <= self.config['volume_threshold']:
                volume_score = 20
            elif volume_ratio <= 0.30:
                volume_score = 10

            # 3. 시간대 가중치 (0-15점)
            time_category, time_weight = self.get_time_category_and_weight(str(current['time']))
            time_score = min(15, 10 * time_weight)

            # 4. 일봉 패턴 점수 (0-20점)
            daily_score = 0
            if daily_pattern.get('valid', False):
                if daily_pattern.get('ideal_pattern', False):
                    daily_score = 20
                else:
                    daily_score = min(20, daily_pattern.get('pattern_strength', 0) / 5)

            # 5. 분봉 추세 분석 (0-10점)
            trend_score = 0
            if current_idx >= 5:
                recent_data = minute_df.iloc[current_idx-5:current_idx+1]
                if len(recent_data) >= 3:
                    trend = np.polyfit(range(len(recent_data)), recent_data['close'], 1)[0]
                    if trend > 0:
                        trend_score = 10
                    elif trend > -0.1:
                        trend_score = 5

            total_score = bisector_score + volume_score + time_score + daily_score + trend_score

            return {
                'total_score': total_score,
                'bisector_score': bisector_score,
                'volume_score': volume_score,
                'time_score': time_score,
                'daily_score': daily_score,
                'trend_score': trend_score,
                'time_category': time_category,
                'time_weight': time_weight,
                'volume_ratio': volume_ratio,
                'bisector_distance': (current['close'] - bisector) / bisector * 100,
                'meets_threshold': total_score >= self.config['min_pattern_score']
            }

        except Exception as e:
            return {'total_score': 0, 'meets_threshold': False}

    def generate_signals(self, stock_code: str, date: str, start_time: str = "12:00") -> List[Dict]:
        """향상된 매매 신호 생성"""
        # 데이터 로드
        minute_df = self.load_minute_data(stock_code, date)
        daily_df = self.load_daily_data(stock_code, date)

        if minute_df is None:
            return []

        # 일봉 패턴 분석
        daily_pattern = self.analyze_daily_pattern(daily_df)

        # 일봉 필터링 (설정에 따라)
        if self.config['require_daily_confirmation'] and not daily_pattern.get('ideal_pattern', False):
            return []

        signals = []

        try:
            # start_time 이후 데이터만 분석
            start_hour, start_min = map(int, start_time.split(':'))
            start_time_int = start_hour * 100 + start_min

            minute_df['time_int'] = minute_df['time'].astype(str).str.replace(':', '').astype(int)
            after_start = minute_df[minute_df['time_int'] >= start_time_int].copy()

            if len(after_start) < 10:
                return signals

            # 각 시점에서 신호 검사
            for i in range(5, len(after_start) - 5):  # 앞뒤 여유 확보
                pattern_analysis = self.calculate_enhanced_pattern_score(
                    minute_df, after_start.index[i], daily_pattern
                )

                if pattern_analysis['meets_threshold']:
                    current = after_start.iloc[i]

                    # 추가 검증 레이어
                    if self.additional_validation(minute_df, after_start.index[i], pattern_analysis):
                        signal = {
                            'stock_code': stock_code,
                            'date': date,
                            'time': str(current['time']),
                            'price': current['close'],
                            'signal_type': 'enhanced_pullback',
                            'pattern_score': pattern_analysis['total_score'],
                            'confidence': self.calculate_confidence(pattern_analysis, daily_pattern),
                            'daily_pattern': daily_pattern,
                            'risk_level': self.assess_risk_level(pattern_analysis),
                            **pattern_analysis
                        }

                        signals.append(signal)

        except Exception as e:
            pass

        return signals

    def additional_validation(self, minute_df: pd.DataFrame, current_idx: int, pattern: Dict) -> bool:
        """추가 검증 레이어"""
        try:
            current = minute_df.iloc[current_idx]

            # 1. 최근 거래량 패턴 검사
            if current_idx >= 3:
                recent_volumes = minute_df.iloc[current_idx-3:current_idx]['volume']
                current_volume = current['volume']

                # 거래량 급등 회피
                max_recent_volume = recent_volumes.max()
                if current_volume > max_recent_volume * 2:
                    return False

                # 거래량 지속적 감소 확인
                volume_trend = np.polyfit(range(len(recent_volumes)), recent_volumes, 1)[0]
                if volume_trend > 0:  # 거래량 증가 추세면 대기
                    return False

            # 2. 가격 변동성 체크
            if current_idx >= 5:
                recent_prices = minute_df.iloc[current_idx-5:current_idx]['close']
                price_std = recent_prices.std()
                price_mean = recent_prices.mean()
                volatility = price_std / price_mean * 100

                # 과도한 변동성 회피
                if volatility > 3:  # 3% 이상 변동성
                    return False

            # 3. 시간대별 추가 조건
            time_category = pattern.get('time_category', '')
            if time_category == 'afternoon' and pattern['total_score'] < 85:
                return False  # 오후 시간대는 더 엄격한 기준

            return True

        except:
            return False

    def calculate_confidence(self, pattern: Dict, daily_pattern: Dict) -> float:
        """신뢰도 계산"""
        confidence = 0

        # 패턴 점수 기반 (0-40)
        score_ratio = min(1.0, pattern['total_score'] / 100)
        confidence += score_ratio * 40

        # 일봉 패턴 기반 (0-30)
        if daily_pattern.get('ideal_pattern', False):
            confidence += 30
        elif daily_pattern.get('valid', False):
            daily_strength = daily_pattern.get('pattern_strength', 0)
            confidence += min(30, daily_strength / 3)

        # 시간대 기반 (0-20)
        time_weight = pattern.get('time_weight', 1.0)
        confidence += min(20, time_weight * 15)

        # 거래량 기반 (0-10)
        volume_ratio = pattern.get('volume_ratio', 1.0)
        if volume_ratio <= 0.15:
            confidence += 10
        elif volume_ratio <= 0.25:
            confidence += 7

        return min(100, confidence)

    def assess_risk_level(self, pattern: Dict) -> str:
        """리스크 레벨 평가"""
        score = pattern['total_score']
        time_weight = pattern.get('time_weight', 1.0)

        if score >= 90 and time_weight >= 1.1:
            return "LOW"
        elif score >= 80 and time_weight >= 1.0:
            return "MEDIUM"
        elif score >= 75:
            return "HIGH"
        else:
            return "VERY_HIGH"

    def simulate_strategy_performance(self, signals: List[Dict], minute_df: pd.DataFrame) -> Dict:
        """전략 성과 시뮬레이션"""
        if not signals or minute_df is None:
            return {}

        results = []

        for signal in signals:
            # 매수 시점 찾기
            signal_time = signal['time']
            minute_df['time_str'] = minute_df['time'].astype(str)
            signal_rows = minute_df[minute_df['time_str'] == signal_time]

            if signal_rows.empty:
                continue

            signal_idx = signal_rows.index[0]
            entry_price = signal['price']

            # 향후 데이터로 손익 계산
            future_data = minute_df.iloc[signal_idx+1:signal_idx+21]  # 다음 60분

            if len(future_data) == 0:
                continue

            # 손절/익절 시뮬레이션
            result = self.simulate_exit_strategy(entry_price, future_data, signal)
            if result:
                results.append(result)

        if not results:
            return {}

        # 성과 계산
        total_trades = len(results)
        winning_trades = sum(1 for r in results if r['pnl_pct'] > 0)
        win_rate = winning_trades / total_trades * 100

        avg_pnl = np.mean([r['pnl_pct'] for r in results])
        max_profit = max([r['pnl_pct'] for r in results])
        max_loss = min([r['pnl_pct'] for r in results])

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'max_profit': max_profit,
            'max_loss': max_loss,
            'results': results
        }

    def simulate_exit_strategy(self, entry_price: float, future_data: pd.DataFrame, signal: Dict) -> Optional[Dict]:
        """출구 전략 시뮬레이션"""
        stop_loss_price = entry_price * (1 + self.config['stop_loss_pct'] / 100)
        profit_target_price = entry_price * (1 + self.config['profit_target_pct'] / 100)

        for i, (_, row) in enumerate(future_data.iterrows()):
            # 손절 체크
            if row['low'] <= stop_loss_price:
                pnl_pct = self.config['stop_loss_pct']
                return {
                    'signal': signal,
                    'exit_reason': 'stop_loss',
                    'exit_time': row['time'],
                    'exit_price': stop_loss_price,
                    'pnl_pct': pnl_pct,
                    'hold_minutes': (i + 1) * 3
                }

            # 익절 체크
            if row['high'] >= profit_target_price:
                pnl_pct = self.config['profit_target_pct']
                return {
                    'signal': signal,
                    'exit_reason': 'profit_target',
                    'exit_time': row['time'],
                    'exit_price': profit_target_price,
                    'pnl_pct': pnl_pct,
                    'hold_minutes': (i + 1) * 3
                }

        # 시간 종료 (마지막 가격으로 정산)
        final_price = future_data.iloc[-1]['close']
        pnl_pct = (final_price - entry_price) / entry_price * 100

        return {
            'signal': signal,
            'exit_reason': 'time_exit',
            'exit_time': future_data.iloc[-1]['time'],
            'exit_price': final_price,
            'pnl_pct': pnl_pct,
            'hold_minutes': len(future_data) * 3
        }

def test_strategy_on_sample():
    """샘플 데이터로 전략 테스트"""
    strategy = AdvancedTradingStrategy()

    # 사용 가능한 데이터 파일 확인
    minute_files = list(strategy.minute_data_dir.glob("*.pkl"))

    if not minute_files:
        print("분봉 데이터가 없습니다.")
        return

    # 처음 10개 파일로 테스트
    test_results = []

    for i, file_path in enumerate(minute_files[:10]):
        # 파일명에서 종목코드와 날짜 추출
        filename = file_path.name
        parts = filename.replace('.pkl', '').split('_')
        if len(parts) >= 2:
            stock_code = parts[0]
            date = parts[1]

            print(f"Testing {stock_code} on {date}")

            # 신호 생성
            signals = strategy.generate_signals(stock_code, date)

            if signals:
                print(f"  Generated {len(signals)} signals")

                # 성과 시뮬레이션
                minute_df = strategy.load_minute_data(stock_code, date)
                if minute_df is not None:
                    performance = strategy.simulate_strategy_performance(signals, minute_df)
                    if performance:
                        print(f"  Win rate: {performance['win_rate']:.1f}% ({performance['winning_trades']}/{performance['total_trades']})")
                        print(f"  Avg PnL: {performance['avg_pnl']:.2f}%")
                        test_results.append(performance)

    # 전체 결과 요약
    if test_results:
        total_trades = sum(r['total_trades'] for r in test_results)
        total_wins = sum(r['winning_trades'] for r in test_results)
        overall_win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0

        print(f"\n=== 전략 테스트 결과 ===")
        print(f"총 거래: {total_trades}개")
        print(f"총 승률: {overall_win_rate:.1f}%")
        print(f"테스트 파일: {len(test_results)}개")

def main():
    print("고도화된 매매 전략 테스트")
    test_strategy_on_sample()

if __name__ == "__main__":
    main()