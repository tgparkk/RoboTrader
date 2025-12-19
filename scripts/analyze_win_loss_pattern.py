"""
승패 종목 패턴 비교 분석 스크립트
- 손절한 종목들의 공통점과 특징
- 익절한 종목들의 공통점과 특징
- 두 그룹의 차이점 분석
"""

import pandas as pd
import numpy as np
from pathlib import Path
import pickle
from datetime import datetime, timedelta
import re
from typing import Dict, List, Tuple
import json

# 전략 모듈 임포트
from core.indicators.pullback_candle_pattern import PullbackCandlePattern
from core.indicators.bisector_line import BisectorLine
from core.indicators.pullback_utils import PullbackUtils


class WinLossAnalyzer:
    """승패 패턴 분석기"""

    def __init__(self, signal_log_dir: str = "signal_replay_log",
                 minute_data_dir: str = "cache/minute_data"):
        self.signal_log_dir = Path(signal_log_dir)
        self.minute_data_dir = Path(minute_data_dir)
        self.trade_data = []

    def parse_signal_log(self, file_path: Path) -> List[Dict]:
        """신호 로그 파일 파싱 - 전체 거래 포함 (개별 종목 섹션에서 체결 시뮬레이션 파싱)"""
        trades = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            return trades

        # 날짜 추출
        date_match = re.search(r'signal_new2_replay_(\d{8})_', file_path.name)
        if not date_match:
            return trades
        trade_date = date_match.group(1)

        # 개별 종목 섹션 파싱
        stock_sections = re.findall(
            r'=== (\d{6}) - .*?체결 시뮬레이션:(.*?)(?:매수 못한 기회:|$)',
            content,
            re.DOTALL
        )

        for stock_code, simulation_text in stock_sections:
            # 체결 시뮬레이션에서 거래 파싱
            # 패턴: 14:48 매수[pullback_pattern] @224,000 → 15:00 매도[profit_3.5pct] @231,500 (+3.35%)
            trade_matches = re.findall(
                r'(\d{2}:\d{2})\s+매수.*?→.*?매도.*?\(([\+\-]\d+\.\d+)%\)',
                simulation_text
            )

            for trade_time, profit_str in trade_matches:
                profit_pct = float(profit_str)
                is_win = profit_pct > 0

                # 신뢰도 추출 시도
                confidence = 75  # 기본값

                # 해당 시간대 신호에서 신뢰도 찾기
                signal_match = re.search(
                    rf'{trade_time[:5]}.*?신뢰도:(\d+)%',
                    simulation_text
                )
                if signal_match:
                    confidence = int(signal_match.group(1))
                else:
                    # 전체 종목 섹션에서 찾기
                    stock_full_section = re.search(
                        rf'=== {stock_code} -.*?(?:===|$)',
                        content,
                        re.DOTALL
                    )
                    if stock_full_section:
                        signal_match2 = re.search(
                            rf'{trade_time[:5]}.*?신뢰도:(\d+)%',
                            stock_full_section.group(0)
                        )
                        if signal_match2:
                            confidence = int(signal_match2.group(1))

                trades.append({
                    'date': trade_date,
                    'stock_code': stock_code,
                    'time': trade_time,
                    'is_win': is_win,
                    'profit_pct': profit_pct,
                    'confidence': confidence
                })

        return trades

    def load_all_trades(self, start_date: str = "20250901", end_date: str = "20251031"):
        """모든 거래 로그 로드"""
        print(f"\n[+] 거래 로그 로딩 중... ({start_date} ~ {end_date})")

        log_files = sorted(self.signal_log_dir.glob("signal_new2_replay_*.txt"))

        for log_file in log_files:
            date_match = re.search(r'(\d{8})', log_file.name)
            if date_match:
                file_date = date_match.group(1)
                if start_date <= file_date <= end_date:
                    trades = self.parse_signal_log(log_file)
                    self.trade_data.extend(trades)

        print(f"[OK] 총 {len(self.trade_data)}개 거래 로드 완료")
        return len(self.trade_data)

    def load_minute_data(self, stock_code: str, date: str) -> pd.DataFrame:
        """분봉 데이터 로드"""
        # 여러 가능한 파일명 시도
        possible_patterns = [
            f"{stock_code}_{date}.pkl",  # 주요 형식
            f"{stock_code}_3min_{date}.pkl",
            f"{stock_code}_{date}_3min.pkl",
            f"{stock_code}_minute_{date}.pkl"
        ]

        for pattern in possible_patterns:
            file_path = self.minute_data_dir / pattern
            if file_path.exists():
                try:
                    with open(file_path, 'rb') as f:
                        data = pickle.load(f)
                    # 데이터프레임인지 확인
                    if isinstance(data, pd.DataFrame) and len(data) > 0:
                        return data
                except Exception as e:
                    continue

        return None

    def calculate_technical_features(self, data: pd.DataFrame, buy_time: str) -> Dict:
        """기술적 특징 계산 - 돌파봉 이전 패턴 분석 포함"""
        if data is None or len(data) == 0:
            return {}

        # buy_time 시점의 인덱스 찾기
        if 'datetime' in data.columns:
            data['datetime'] = pd.to_datetime(data['datetime'])
            buy_datetime = pd.to_datetime(f"{data['datetime'].iloc[0].date()} {buy_time}")
            buy_idx = data[data['datetime'] <= buy_datetime].index[-1] if len(data[data['datetime'] <= buy_datetime]) > 0 else len(data) - 1
        else:
            # datetime이 없으면 마지막 데이터 사용
            buy_idx = len(data) - 1

        # 매수 시점까지의 데이터
        data_until_buy = data.iloc[:buy_idx+1]

        if len(data_until_buy) < 10:
            return {}

        features = {}

        # 돌파봉 이전 패턴 분석 추가
        features.update(self._analyze_pre_breakout_pattern(data_until_buy))

        try:
            # 1. 거래량 분석
            baseline_volumes = PullbackUtils.calculate_daily_baseline_volume(data_until_buy)
            volume_analysis = PullbackUtils.analyze_volume(data_until_buy, min(10, len(data_until_buy)-1), baseline_volumes)

            features['volume_ratio'] = volume_analysis.volume_ratio
            features['avg_volume'] = data_until_buy['volume'].tail(10).mean()
            features['volume_std'] = data_until_buy['volume'].tail(10).std()

            # 2. 가격 분석
            candle_analysis = PullbackUtils.analyze_candle(data_until_buy, min(10, len(data_until_buy)-1))

            features['is_bullish'] = candle_analysis.is_bullish
            features['body_pct'] = candle_analysis.body_pct
            features['is_meaningful_body'] = candle_analysis.is_meaningful_body

            # 3. 이등분선 분석
            try:
                bisector_line = BisectorLine.calculate_bisector_line(data_until_buy['high'], data_until_buy['low'])
                if bisector_line is not None and len(bisector_line) > 0:
                    current_price = data_until_buy['close'].iloc[-1]
                    bisector_value = bisector_line.iloc[-1]
                    features['bisector_distance'] = (current_price - bisector_value) / bisector_value * 100
                else:
                    features['bisector_distance'] = None
            except:
                features['bisector_distance'] = None

            # 4. 가격 변화율
            if len(data_until_buy) >= 10:
                price_10ago = data_until_buy['close'].iloc[-10]
                current_price = data_until_buy['close'].iloc[-1]
                features['price_change_10candles'] = (current_price - price_10ago) / price_10ago * 100

            # 5. 시가 대비 현재가
            day_open = data_until_buy['open'].iloc[0]
            current_price = data_until_buy['close'].iloc[-1]
            features['price_from_open'] = (current_price - day_open) / day_open * 100

            # 6. 변동성 (최근 10봉)
            recent_closes = data_until_buy['close'].tail(10)
            features['price_volatility'] = (recent_closes.std() / recent_closes.mean() * 100) if recent_closes.mean() > 0 else 0

            # 7. 고점 대비 현재가 위치
            recent_high = data_until_buy['high'].tail(20).max()
            features['distance_from_high'] = (current_price - recent_high) / recent_high * 100

            # 8. 저점 대비 현재가 위치
            recent_low = data_until_buy['low'].tail(20).min()
            features['distance_from_low'] = (current_price - recent_low) / recent_low * 100

            # 9. RSI 계산 (14봉 기준)
            if len(data_until_buy) >= 15:
                closes = data_until_buy['close'].tail(15)
                deltas = closes.diff()
                gain = deltas.where(deltas > 0, 0).rolling(window=14).mean()
                loss = -deltas.where(deltas < 0, 0).rolling(window=14).mean()
                rs = gain / loss
                features['rsi'] = (100 - (100 / (1 + rs))).iloc[-1] if not rs.iloc[-1] == 0 else 50
            else:
                features['rsi'] = None

        except Exception as e:
            print(f"  ⚠️ 특징 계산 오류: {e}")

        return features

    def _analyze_pre_breakout_pattern(self, data: pd.DataFrame) -> Dict:
        """돌파봉 이전 패턴 분석 - 승패 종목 간 차이점 발견

        Args:
            data: 매수 시점까지의 분봉 데이터

        Returns:
            돌파 전 패턴 특징 딕셔너리
        """
        features = {}

        if len(data) < 15:
            return features

        try:
            # 돌파봉을 마지막 봉으로 가정
            breakout_idx = len(data) - 1

            # 1. 돌파 직전 5봉 거래량 패턴 분석
            pre_breakout_5 = data.iloc[-6:-1]  # 돌파봉 직전 5개 봉

            if len(pre_breakout_5) >= 5:
                volumes = pre_breakout_5['volume'].values

                # 거래량 하락 추세 확인 (눌림목 특징)
                volume_decreasing_count = sum(1 for i in range(len(volumes)-1) if volumes[i+1] < volumes[i])
                features['pre_volume_decreasing_ratio'] = volume_decreasing_count / (len(volumes) - 1)

                # 평균 거래량 대비 최소 거래량 비율
                avg_vol = volumes.mean()
                min_vol = volumes.min()
                features['pre_min_volume_ratio'] = min_vol / avg_vol if avg_vol > 0 else 0

                # 거래량 표준편차 (변동성)
                features['pre_volume_std'] = volumes.std()

                # 최종 봉 vs 평균 거래량 비율
                features['pre_last_vs_avg_volume'] = volumes[-1] / avg_vol if avg_vol > 0 else 0

            # 2. 돌파 직전 5봉 가격 패턴 분석
            if len(pre_breakout_5) >= 5:
                closes = pre_breakout_5['close'].values
                highs = pre_breakout_5['high'].values
                lows = pre_breakout_5['low'].values

                # 가격 횡보/하락 확인 (눌림목 특징)
                price_range = (closes.max() - closes.min()) / closes.mean() * 100
                features['pre_price_consolidation_pct'] = price_range

                # 저점 지지 확인 (저점이 얼마나 안정적인가)
                low_std = lows.std()
                low_mean = lows.mean()
                features['pre_support_stability'] = (low_std / low_mean * 100) if low_mean > 0 else 0

                # 고점 하락 여부 (고점이 내려오는 패턴)
                high_decreasing_count = sum(1 for i in range(len(highs)-1) if highs[i+1] < highs[i])
                features['pre_high_decreasing_ratio'] = high_decreasing_count / (len(highs) - 1)

            # 3. 상승 구간 (10~20봉 전) 분석
            if len(data) >= 20:
                uptrend_zone = data.iloc[-20:-6]  # 돌파 전 14봉 (20봉 전부터 6봉 전까지)

                # 상승 구간 가격 상승폭
                uptrend_start = uptrend_zone['close'].iloc[0]
                uptrend_end = uptrend_zone['close'].iloc[-1]
                features['uptrend_price_gain_pct'] = (uptrend_end - uptrend_start) / uptrend_start * 100

                # 상승 구간 평균 거래량
                features['uptrend_avg_volume'] = uptrend_zone['volume'].mean()

                # 상승 구간 거래량 추세 (초반 vs 후반)
                uptrend_first_half = uptrend_zone['volume'].iloc[:len(uptrend_zone)//2].mean()
                uptrend_second_half = uptrend_zone['volume'].iloc[len(uptrend_zone)//2:].mean()
                features['uptrend_volume_trend'] = (uptrend_second_half - uptrend_first_half) / uptrend_first_half if uptrend_first_half > 0 else 0

            # 4. 지지 구간 거래량 급감 정도
            if len(data) >= 15:
                # 최근 10봉 기준거래량 (상승 시점 거래량)
                baseline_volumes = data['volume'].iloc[-15:-5].values
                baseline_max = baseline_volumes.max()

                # 눌림목 구간 최소 거래량
                support_zone = data.iloc[-5:-1]
                support_min = support_zone['volume'].min()

                # 급감 비율
                features['volume_drop_ratio'] = support_min / baseline_max if baseline_max > 0 else 0

            # 5. 돌파봉 특성
            breakout_candle = data.iloc[-1]
            prev_candle = data.iloc[-2]

            # 돌파봉 거래량 vs 직전 평균
            prev_5_avg_volume = data['volume'].iloc[-6:-1].mean()
            features['breakout_volume_vs_prev'] = breakout_candle['volume'] / prev_5_avg_volume if prev_5_avg_volume > 0 else 0

            # 돌파봉 캔들 몸통 크기
            breakout_body = abs(breakout_candle['close'] - breakout_candle['open'])
            breakout_body_pct = breakout_body / breakout_candle['open'] * 100
            features['breakout_body_pct'] = breakout_body_pct

            # 돌파봉 vs 직전봉 크기 비율
            prev_body = abs(prev_candle['close'] - prev_candle['open'])
            features['breakout_vs_prev_body'] = breakout_body / prev_body if prev_body > 0 else 0

            # 6. 전체 패턴 (상승→눌림목→돌파) 특성
            if len(data) >= 20:
                # 전체 가격 변화
                total_price_change = (data['close'].iloc[-1] - data['close'].iloc[-20]) / data['close'].iloc[-20] * 100
                features['total_pattern_price_change'] = total_price_change

                # 최고 거래량 대비 돌파봉 거래량
                max_volume_in_pattern = data['volume'].iloc[-20:].max()
                features['breakout_vs_max_volume'] = breakout_candle['volume'] / max_volume_in_pattern if max_volume_in_pattern > 0 else 0

        except Exception as e:
            print(f"  [WARNING] 돌파 전 패턴 분석 오류: {e}")

        return features

    def analyze_pattern_differences(self, morning_only=False):
        """승패 패턴 차이 분석

        Args:
            morning_only: True면 12시 이전 거래만 분석
        """
        print("\n" + "="*80)
        if morning_only:
            print("[*] 12시 이전 매수 종목 패턴 비교 분석")
        else:
            print("[*] 승패 종목 패턴 비교 분석")
        print("="*80)

        # 거래 데이터를 DataFrame으로 변환
        df = pd.DataFrame(self.trade_data)

        # 12시 이전 거래만 필터링
        if morning_only:
            df['hour'] = df['time'].str[:2].astype(int)
            df = df[df['hour'] < 12].copy()
            print(f"\n[*] 12시 이전 거래만 분석: {len(df)}개")

        # 기본 통계
        wins = df[df['is_win'] == True]
        losses = df[df['is_win'] == False]

        print(f"\n[*] 기본 통계:")
        print(f"  총 거래: {len(df)}개")
        print(f"  승리: {len(wins)}개 ({len(wins)/len(df)*100:.1f}%)")
        print(f"  패배: {len(losses)}개 ({len(losses)/len(df)*100:.1f}%)")

        # 신뢰도 비교
        print(f"\n[*] 신호 신뢰도 비교:")
        print(f"  승리 평균: {wins['confidence'].mean():.1f}%")
        print(f"  패배 평균: {losses['confidence'].mean():.1f}%")
        print(f"  차이: {wins['confidence'].mean() - losses['confidence'].mean():.1f}%p")

        # 신뢰도 구간별 승률
        print(f"\n[*] 신뢰도 구간별 승률:")
        for threshold in [70, 75, 80, 85, 90]:
            high_conf = df[df['confidence'] >= threshold]
            if len(high_conf) > 0:
                win_rate = len(high_conf[high_conf['is_win']]) / len(high_conf) * 100
                print(f"  {threshold}% 이상: {win_rate:.1f}% (거래 {len(high_conf)}개)")

        # 시간대별 승률
        print(f"\n[*] 시간대별 승률:")
        df['hour'] = df['time'].str[:2].astype(int)
        for hour in sorted(df['hour'].unique()):
            hour_df = df[df['hour'] == hour]
            win_rate = len(hour_df[hour_df['is_win']]) / len(hour_df) * 100
            print(f"  {hour:02d}시: {win_rate:.1f}% (거래 {len(hour_df)}개)")

        # 기술적 특징 수집
        print(f"\n[*] 기술적 특징 수집 중...")

        win_features = []
        loss_features = []

        total_trades = len(df)
        for idx, trade in df.iterrows():
            if (idx + 1) % 50 == 0:
                print(f"  진행률: {idx+1}/{total_trades} ({(idx+1)/total_trades*100:.1f}%)")

            data = self.load_minute_data(trade['stock_code'], trade['date'])
            if data is None:
                continue

            features = self.calculate_technical_features(data, trade['time'])
            if not features:
                continue

            # 신뢰도 추가
            features['confidence'] = trade['confidence']
            features['profit_pct'] = trade['profit_pct']

            if trade['is_win']:
                win_features.append(features)
            else:
                loss_features.append(features)

        print(f"[OK] 수집 완료: 승리 {len(win_features)}개, 패배 {len(loss_features)}개")

        # 특징 비교
        if len(win_features) > 0 and len(loss_features) > 0:
            self._compare_features(win_features, loss_features)

        # 상세 결과 저장
        self._save_detailed_results(df, win_features, loss_features)

    def _compare_features(self, win_features: List[Dict], loss_features: List[Dict]):
        """특징 비교 분석"""
        print("\n" + "="*80)
        print("[*] 기술적 특징 비교")
        print("="*80)

        win_df = pd.DataFrame(win_features)
        loss_df = pd.DataFrame(loss_features)

        # 수치형 특징만 선택
        numeric_features = ['confidence', 'volume_ratio', 'body_pct', 'bisector_distance',
                           'price_change_10candles', 'price_from_open', 'price_volatility',
                           'distance_from_high', 'distance_from_low', 'rsi',
                           # 돌파 전 패턴 특징
                           'pre_volume_decreasing_ratio', 'pre_min_volume_ratio', 'pre_volume_std',
                           'pre_last_vs_avg_volume', 'pre_price_consolidation_pct',
                           'pre_support_stability', 'pre_high_decreasing_ratio',
                           'uptrend_price_gain_pct', 'uptrend_avg_volume', 'uptrend_volume_trend',
                           'volume_drop_ratio', 'breakout_volume_vs_prev', 'breakout_body_pct',
                           'breakout_vs_prev_body', 'total_pattern_price_change', 'breakout_vs_max_volume']

        print(f"\n{'특징':<25} {'승리 평균':>12} {'패배 평균':>12} {'차이':>12} {'유의성':>8}")
        print("-" * 80)

        significant_features = []

        for feature in numeric_features:
            if feature in win_df.columns and feature in loss_df.columns:
                win_mean = win_df[feature].dropna().mean()
                loss_mean = loss_df[feature].dropna().mean()
                diff = win_mean - loss_mean

                # 표준편차 기반 유의성 판단
                win_std = win_df[feature].dropna().std()
                loss_std = loss_df[feature].dropna().std()

                # 차이가 표준편차의 0.3배 이상이면 유의미
                is_significant = abs(diff) > (win_std + loss_std) * 0.15

                significance = "[*]" if is_significant else ""

                print(f"{feature:<25} {win_mean:>12.2f} {loss_mean:>12.2f} {diff:>12.2f} {significance:>8}")

                if is_significant:
                    significant_features.append({
                        'feature': feature,
                        'win_mean': win_mean,
                        'loss_mean': loss_mean,
                        'diff': diff
                    })

        # 유의미한 특징 요약
        if significant_features:
            print("\n" + "="*80)
            print("[*] 유의미한 차이를 보이는 특징 (중요도 순)")
            print("="*80)

            # 차이가 큰 순으로 정렬
            significant_features.sort(key=lambda x: abs(x['diff']), reverse=True)

            for i, feat in enumerate(significant_features[:10], 1):
                direction = "높음" if feat['diff'] > 0 else "낮음"
                print(f"\n{i}. {feat['feature']}")
                print(f"   승리: {feat['win_mean']:.2f} / 패배: {feat['loss_mean']:.2f}")
                print(f"   → 승리 종목이 {abs(feat['diff']):.2f} {direction}")

    def _save_detailed_results(self, df: pd.DataFrame, win_features: List[Dict], loss_features: List[Dict]):
        """상세 결과 저장"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # CSV 저장
        csv_path = f"win_loss_analysis_{timestamp}.csv"
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\n[*] 거래 데이터 저장: {csv_path}")

        # JSON 저장
        results = {
            'summary': {
                'total_trades': len(df),
                'wins': len(df[df['is_win']]),
                'losses': len(df[~df['is_win']]),
                'win_rate': len(df[df['is_win']]) / len(df) * 100
            },
            'win_features_avg': pd.DataFrame(win_features).mean().to_dict() if win_features else {},
            'loss_features_avg': pd.DataFrame(loss_features).mean().to_dict() if loss_features else {},
            'timestamp': timestamp
        }

        json_path = f"win_loss_analysis_{timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[*] 분석 결과 저장: {json_path}")


def main():
    """메인 실행"""
    analyzer = WinLossAnalyzer()

    # 거래 로그 로드
    analyzer.load_all_trades(start_date="20250901", end_date="20251031")

    if len(analyzer.trade_data) == 0:
        print("[!] 거래 데이터가 없습니다.")
        return

    # 패턴 분석 (12시 이전 거래만)
    analyzer.analyze_pattern_differences(morning_only=True)

    print("\n" + "="*80)
    print("[OK] 분석 완료!")
    print("="*80)


if __name__ == "__main__":
    main()
