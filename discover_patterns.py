"""
순수 데이터 기반 수익 패턴 발견
기존 눌림목 로직과 무관하게, 분봉 데이터만으로 수익성 있는 매매 규칙 발견
"""

import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

class PatternDiscovery:
    """데이터 기반 패턴 발견"""

    def __init__(self):
        self.conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)

    def get_all_minute_data(self, min_candles=500):
        """충분한 데이터가 있는 종목의 분봉 데이터 로드"""
        tables = self.conn.execute('''
            SELECT table_name FROM information_schema.tables
            WHERE table_name LIKE 'minute_%'
        ''').fetchall()

        all_data = []

        for t in tables:
            table_name = t[0]
            stock_code = table_name.replace('minute_', '')

            try:
                df = self.conn.execute(f'''
                    SELECT * FROM {table_name}
                    ORDER BY trade_date, idx
                ''').fetchdf()

                if len(df) >= min_candles:
                    df['stock_code'] = stock_code
                    all_data.append(df)
            except:
                continue

        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()

    def calculate_indicators(self, df):
        """기술적 지표 계산"""
        # 그룹별로 계산 (종목+날짜)
        df = df.copy()

        # 시간 파싱
        df['hour'] = df['time'].str[:2].astype(int)
        df['minute'] = df['time'].str[2:4].astype(int)

        # 당일 시가 (각 종목+날짜 그룹의 첫 번째 시가)
        df['day_open'] = df.groupby(['stock_code', 'trade_date'])['open'].transform('first')

        # 시가 대비 현재가 변화율
        df['pct_from_open'] = (df['close'] / df['day_open'] - 1) * 100

        # 당일 누적 고가/저가
        df['day_high'] = df.groupby(['stock_code', 'trade_date'])['high'].cummax()
        df['day_low'] = df.groupby(['stock_code', 'trade_date'])['low'].cummin()

        # 당일 범위 내 위치 (0=저가, 1=고가)
        df['day_position'] = (df['close'] - df['day_low']) / (df['day_high'] - df['day_low'])
        df['day_position'] = df['day_position'].fillna(0.5)

        # 당일 최대 거래량
        df['day_max_volume'] = df.groupby(['stock_code', 'trade_date'])['volume'].cummax()

        # 거래량 비율 (현재 / 당일 최대)
        df['volume_ratio'] = df['volume'] / df['day_max_volume']
        df['volume_ratio'] = df['volume_ratio'].fillna(0)

        # 이동평균 (5개 캔들)
        df['ma5'] = df.groupby(['stock_code', 'trade_date'])['close'].transform(
            lambda x: x.rolling(5, min_periods=1).mean()
        )
        df['above_ma5'] = (df['close'] > df['ma5']).astype(int)

        # 이동평균 (10개 캔들)
        df['ma10'] = df.groupby(['stock_code', 'trade_date'])['close'].transform(
            lambda x: x.rolling(10, min_periods=1).mean()
        )
        df['above_ma10'] = (df['close'] > df['ma10']).astype(int)

        # 캔들 특성
        df['is_bullish'] = (df['close'] > df['open']).astype(int)
        df['candle_body'] = abs(df['close'] - df['open'])
        df['candle_range'] = df['high'] - df['low']
        df['body_ratio'] = df['candle_body'] / df['candle_range'].replace(0, 1)

        # 연속 양봉 수
        df['bullish_streak'] = df.groupby(['stock_code', 'trade_date'])['is_bullish'].transform(
            lambda x: x.groupby((x != x.shift()).cumsum()).cumsum() * x
        )

        # 직전 캔들 대비 가격 변화
        df['pct_change'] = df.groupby(['stock_code', 'trade_date'])['close'].pct_change() * 100

        # 직전 캔들 대비 거래량 변화
        df['volume_change'] = df.groupby(['stock_code', 'trade_date'])['volume'].pct_change()

        return df

    def calculate_future_returns(self, df, forward_minutes=[10, 20, 30, 60]):
        """미래 수익률 계산"""
        df = df.copy()

        for mins in forward_minutes:
            # 같은 종목, 같은 날짜 내에서 N분 후 종가
            df[f'future_close_{mins}'] = df.groupby(['stock_code', 'trade_date'])['close'].shift(-mins)
            df[f'return_{mins}m'] = (df[f'future_close_{mins}'] / df['close'] - 1) * 100

        return df

    def analyze_patterns(self, df):
        """패턴별 수익률 분석"""
        results = []

        # 분석할 조건들
        conditions = {
            # 시가 대비 위치
            'open_below_2pct': df['pct_from_open'] < 2,
            'open_2_5pct': (df['pct_from_open'] >= 2) & (df['pct_from_open'] < 5),
            'open_5_10pct': (df['pct_from_open'] >= 5) & (df['pct_from_open'] < 10),
            'open_above_10pct': df['pct_from_open'] >= 10,

            # 시간대
            'hour_9': df['hour'] == 9,
            'hour_10': df['hour'] == 10,
            'hour_11': df['hour'] == 11,
            'hour_10_plus': df['hour'] >= 10,

            # 당일 위치
            'day_pos_high': df['day_position'] > 0.8,
            'day_pos_mid': (df['day_position'] >= 0.4) & (df['day_position'] <= 0.6),
            'day_pos_low': df['day_position'] < 0.2,

            # 거래량
            'vol_ratio_low': df['volume_ratio'] < 0.3,
            'vol_ratio_mid': (df['volume_ratio'] >= 0.3) & (df['volume_ratio'] < 0.7),
            'vol_ratio_high': df['volume_ratio'] >= 0.7,

            # 이동평균
            'above_ma5': df['above_ma5'] == 1,
            'below_ma5': df['above_ma5'] == 0,
            'above_ma10': df['above_ma10'] == 1,

            # 캔들 패턴
            'bullish_candle': df['is_bullish'] == 1,
            'bearish_candle': df['is_bullish'] == 0,
            'bullish_streak_2': df['bullish_streak'] >= 2,
            'bullish_streak_3': df['bullish_streak'] >= 3,

            # 가격 모멘텀
            'positive_momentum': df['pct_change'] > 0,
            'strong_momentum': df['pct_change'] > 0.5,

            # 거래량 증가
            'volume_surge': df['volume_change'] > 1,
            'volume_spike': df['volume_change'] > 2,
        }

        # 각 조건별 수익률 분석
        print("=== Single Condition Analysis ===\n")

        for name, cond in conditions.items():
            filtered = df[cond & df['return_30m'].notna()]
            if len(filtered) < 100:
                continue

            avg_return = filtered['return_30m'].mean()
            win_rate = (filtered['return_30m'] > 0).mean() * 100
            count = len(filtered)

            results.append({
                'condition': name,
                'count': count,
                'avg_return_30m': avg_return,
                'win_rate_30m': win_rate,
            })

        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values('avg_return_30m', ascending=False)

        print("Top conditions by 30min return:")
        print(results_df.head(15).to_string(index=False))

        return results_df

    def find_best_combinations(self, df):
        """최적 조건 조합 탐색"""
        print("\n=== Combination Analysis ===\n")

        combinations = []

        # 핵심 조건 조합 테스트
        test_combos = [
            # (name, condition)
            ("시가<2% + 10시+ + MA5위",
             (df['pct_from_open'] < 2) & (df['hour'] >= 10) & (df['above_ma5'] == 1)),

            ("시가<3% + 10시+ + 양봉",
             (df['pct_from_open'] < 3) & (df['hour'] >= 10) & (df['is_bullish'] == 1)),

            ("시가<2% + 10시+ + 거래량급증",
             (df['pct_from_open'] < 2) & (df['hour'] >= 10) & (df['volume_change'] > 1)),

            ("시가<3% + 10시+ + 연속양봉2+",
             (df['pct_from_open'] < 3) & (df['hour'] >= 10) & (df['bullish_streak'] >= 2)),

            ("시가<2% + 10시+ + 강한모멘텀",
             (df['pct_from_open'] < 2) & (df['hour'] >= 10) & (df['pct_change'] > 0.3)),

            ("시가<3% + 당일위치>80% + 10시+",
             (df['pct_from_open'] < 3) & (df['day_position'] > 0.8) & (df['hour'] >= 10)),

            ("시가<5% + MA5위 + MA10위 + 10시+",
             (df['pct_from_open'] < 5) & (df['above_ma5'] == 1) & (df['above_ma10'] == 1) & (df['hour'] >= 10)),

            ("거래량급증 + 양봉 + 10시+",
             (df['volume_change'] > 1) & (df['is_bullish'] == 1) & (df['hour'] >= 10)),

            ("시가<2% + 연속양봉3+ + 10시+",
             (df['pct_from_open'] < 2) & (df['bullish_streak'] >= 3) & (df['hour'] >= 10)),

            ("시가<1% + 양봉 + 10시+",
             (df['pct_from_open'] < 1) & (df['is_bullish'] == 1) & (df['hour'] >= 10)),

            ("당일저점 + 거래량급증 + 10시+",
             (df['day_position'] < 0.3) & (df['volume_change'] > 1) & (df['hour'] >= 10)),

            ("당일중간 + 양봉 + 10시+",
             (df['day_position'] >= 0.4) & (df['day_position'] <= 0.6) & (df['is_bullish'] == 1) & (df['hour'] >= 10)),
        ]

        for name, cond in test_combos:
            filtered = df[cond & df['return_30m'].notna()]
            if len(filtered) < 30:
                continue

            avg_10m = filtered['return_10m'].mean() if 'return_10m' in filtered else 0
            avg_20m = filtered['return_20m'].mean() if 'return_20m' in filtered else 0
            avg_30m = filtered['return_30m'].mean()
            avg_60m = filtered['return_60m'].mean() if 'return_60m' in filtered else 0

            win_30m = (filtered['return_30m'] > 0).mean() * 100
            win_tp = (filtered['return_30m'] > 2).mean() * 100  # 2% 이상 수익

            combinations.append({
                'name': name,
                'count': len(filtered),
                'return_10m': avg_10m,
                'return_20m': avg_20m,
                'return_30m': avg_30m,
                'return_60m': avg_60m,
                'win_rate': win_30m,
                'tp_2pct_rate': win_tp,
            })

        combo_df = pd.DataFrame(combinations)
        combo_df = combo_df.sort_values('return_30m', ascending=False)

        print("Best combinations by 30min return:")
        print(combo_df.to_string(index=False))

        return combo_df

    def close(self):
        self.conn.close()


def main():
    print("=" * 80)
    print("순수 데이터 기반 수익 패턴 발견")
    print("=" * 80)

    discovery = PatternDiscovery()

    print("\n1. 분봉 데이터 로드 중...")
    df = discovery.get_all_minute_data(min_candles=200)
    print(f"   로드된 데이터: {len(df):,}개 캔들")

    if len(df) == 0:
        print("데이터가 없습니다.")
        return

    print("\n2. 기술적 지표 계산 중...")
    df = discovery.calculate_indicators(df)

    print("\n3. 미래 수익률 계산 중...")
    df = discovery.calculate_future_returns(df)

    # NaN 제거
    valid_df = df[df['return_30m'].notna()].copy()
    print(f"   유효 데이터: {len(valid_df):,}개")

    print("\n4. 패턴 분석 중...")
    single_results = discovery.analyze_patterns(valid_df)

    print("\n5. 조합 분석 중...")
    combo_results = discovery.find_best_combinations(valid_df)

    # 최종 추천
    print("\n" + "=" * 80)
    print("최종 추천 매매 규칙")
    print("=" * 80)

    if len(combo_results) > 0:
        best = combo_results.iloc[0]
        print(f"\n추천 조건: {best['name']}")
        print(f"  - 거래 수: {best['count']}건")
        print(f"  - 30분 평균 수익: {best['return_30m']:+.3f}%")
        print(f"  - 승률: {best['win_rate']:.1f}%")
        print(f"  - 2% 익절 달성률: {best['tp_2pct_rate']:.1f}%")

    discovery.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
