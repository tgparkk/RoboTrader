"""
패배 거래 분석 및 OHLCV 기반 개선 지표 도출

325개 거래 중 156개 패배를 분석하여 OHLCV 데이터 기반 개선 방안 제시
"""

import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
import re
from collections import defaultdict
from datetime import datetime, timedelta
import sys

# 콘솔 인코딩 설정
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class LosingTradeAnalyzer:
    def __init__(self, signal_log_dir, minute_data_dir, daily_data_dir):
        self.signal_log_dir = Path(signal_log_dir)
        self.minute_data_dir = Path(minute_data_dir)
        self.daily_data_dir = Path(daily_data_dir)
        self.losing_trades = []
        self.winning_trades = []

    def parse_trade_logs(self):
        """거래 로그 파싱하여 승패 거래 분리"""
        print("📁 거래 로그 파싱 중...")

        for log_file in sorted(self.signal_log_dir.glob("signal_new2_replay_*.txt")):
            if log_file.name.startswith("statistics"):
                continue

            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 날짜 추출
            date_match = re.search(r'(\d{8})', log_file.name)
            if not date_match:
                continue
            trade_date = date_match.group(1)

            # 파일 시작부의 요약 부분에서 거래 추출
            lines = content.split('\n')

            for line in lines[:50]:  # 처음 50줄 내에서만 검색
                # "🟢 484810 09:36 매수 → +3.50%" 형태 파싱
                # "🔴 462310 09:30 매수 → -2.50%" 형태 파싱
                if ('🟢' in line or '🔴' in line) and '매수' in line and '→' in line:
                    # 승패 판단
                    if '🟢' in line:
                        result = "win"
                    else:
                        result = "loss"

                    # 종목코드 추출 (6자리 숫자)
                    code_match = re.search(r'(\d{6})', line)
                    # 시간 추출 (HH:MM)
                    time_match = re.search(r'(\d{2}:\d{2})', line)
                    # 수익률 추출 (+3.50% 또는 -2.50%)
                    profit_match = re.search(r'→\s*([+-]\d+\.\d+)%', line)

                    if code_match and time_match and profit_match:
                        stock_code = code_match.group(1)
                        buy_time = time_match.group(1)
                        profit = float(profit_match.group(1))

                        trade_info = {
                            'date': trade_date,
                            'stock_code': stock_code,
                            'buy_time': buy_time,
                            'profit': profit,
                            'result': result,
                            'log_file': log_file.name
                        }

                        if result == "loss":
                            self.losing_trades.append(trade_info)
                        else:
                            self.winning_trades.append(trade_info)

        print(f"✅ 패배 거래: {len(self.losing_trades)}개")
        print(f"✅ 승리 거래: {len(self.winning_trades)}개")

    def convert_to_3min_candles(self, minute_df):
        """1분봉을 3분봉으로 변환"""
        if minute_df is None or len(minute_df) == 0:
            return None

        # datetime 기준으로 3분 단위로 리샘플링
        minute_df = minute_df.set_index('datetime')

        # 3분봉 생성
        candle_3min = minute_df.resample('3T').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'amount': 'sum'
        }).dropna()

        candle_3min = candle_3min.reset_index()
        return candle_3min

    def load_ohlcv_data(self, stock_code, date):
        """OHLCV 데이터 로드"""
        # 분봉 데이터 (1분봉)
        minute_file = self.minute_data_dir / f"{stock_code}_{date}.pkl"
        if minute_file.exists():
            with open(minute_file, 'rb') as f:
                minute_df_1m = pickle.load(f)
            # 1분봉을 3분봉으로 변환
            minute_df = self.convert_to_3min_candles(minute_df_1m)
        else:
            minute_df = None

        # 일봉 데이터
        daily_file = self.daily_data_dir / f"{stock_code}_{date}_daily.pkl"
        if daily_file.exists():
            with open(daily_file, 'rb') as f:
                daily_df = pickle.load(f)
        else:
            daily_df = None

        return minute_df, daily_df

    def calculate_technical_indicators(self, df):
        """기술적 지표 계산"""
        if df is None or len(df) < 20:
            return {}

        indicators = {}

        # 1. 이동평균선
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()

        # 2. 볼린저 밴드
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)

        # 3. RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # 4. 거래량 이동평균
        df['volume_ma5'] = df['volume'].rolling(window=5).mean()
        df['volume_ma20'] = df['volume'].rolling(window=20).mean()

        # 5. 가격 변동성 (ATR 간소화 버전)
        df['price_range'] = df['high'] - df['low']
        df['atr'] = df['price_range'].rolling(window=14).mean()

        return df

    def analyze_buy_point_characteristics(self, trade, minute_df):
        """매수 시점의 특성 분석"""
        if minute_df is None:
            return {}

        # 매수 시간 찾기
        buy_time_str = f"{trade['date'][:4]}-{trade['date'][4:6]}-{trade['date'][6:]} {trade['buy_time']}:00"
        buy_time = pd.to_datetime(buy_time_str)

        # 매수 시점 전후 데이터 추출
        buy_idx = minute_df[minute_df['datetime'] <= buy_time].index[-1] if len(minute_df[minute_df['datetime'] <= buy_time]) > 0 else 0

        # 최소 5개 봉만 있으면 분석 가능하도록 완화
        if buy_idx < 5:  # 최소 5개 3분봉 필요 (15분)
            return {}

        # 매수 시점 기준 분석
        current = minute_df.iloc[buy_idx]

        # 가용 데이터에 맞춰 유연하게 계산
        available_candles = buy_idx + 1

        # 5개 이상 있으면 5개 사용
        if available_candles >= 5:
            prev_5 = minute_df.iloc[buy_idx-5:buy_idx]
            use_5 = True
        else:
            prev_5 = minute_df.iloc[0:buy_idx]
            use_5 = False

        # 20개 이상 있으면 20개 사용
        if available_candles >= 20:
            prev_20 = minute_df.iloc[buy_idx-20:buy_idx]
            use_20 = True
        else:
            prev_20 = None
            use_20 = False

        analysis = {
            'buy_price': current['close'],
            'buy_volume': current['volume'],

            # 가격 위치 (rolling으로 계산되므로 NaN일 수 있음)
            'price_vs_ma5': (current['close'] - current['ma5']) / current['ma5'] * 100 if pd.notna(current['ma5']) else None,
            'price_vs_ma20': (current['close'] - current['ma20']) / current['ma20'] * 100 if pd.notna(current['ma20']) else None,

            # 볼린저 밴드 위치
            'bb_position': None,
            'rsi': current['rsi'] if pd.notna(current['rsi']) else None,

            # 거래량 분석
            'volume_vs_ma5': (current['volume'] / current['volume_ma5']) if pd.notna(current['volume_ma5']) and current['volume_ma5'] > 0 else None,
            'volume_vs_ma20': (current['volume'] / current['volume_ma20']) if pd.notna(current['volume_ma20']) and current['volume_ma20'] > 0 else None,

            # 직전 5봉 거래량 추세
            'volume_trend_5': (prev_5['volume'].iloc[-1] / prev_5['volume'].iloc[0]) if len(prev_5) > 0 and prev_5['volume'].iloc[0] > 0 else None,

            # 가격 변동성
            'atr': current['atr'] if pd.notna(current['atr']) else None,
            'atr_ratio': (current['price_range'] / current['atr']) if pd.notna(current['atr']) and current['atr'] > 0 else None,

            # 직전 가격 추세
            'price_change_5': ((current['close'] - prev_5['close'].iloc[0]) / prev_5['close'].iloc[0] * 100) if len(prev_5) > 0 and prev_5['close'].iloc[0] > 0 else None,
            'price_change_20': ((current['close'] - prev_20['close'].iloc[0]) / prev_20['close'].iloc[0] * 100) if use_20 and len(prev_20) > 0 and prev_20['close'].iloc[0] > 0 else None,
        }

        # 볼린저 밴드 위치 계산
        if pd.notna(current['bb_upper']) and pd.notna(current['bb_lower']):
            bb_range = current['bb_upper'] - current['bb_lower']
            if bb_range > 0:
                analysis['bb_position'] = (current['close'] - current['bb_lower']) / bb_range * 100

        return analysis

    def analyze_daily_context(self, trade, daily_df):
        """일봉 데이터 기반 추세 분석"""
        if daily_df is None or len(daily_df) < 20:
            return {}

        # 최근 데이터 (거래일 당일이 첫번째)
        recent = daily_df.iloc[:20]

        # 일봉 종가 기준 이동평균
        daily_close = pd.to_numeric(recent['stck_clpr'], errors='coerce')

        ma5 = daily_close.rolling(window=5).mean().iloc[0]
        ma20 = daily_close.rolling(window=20).mean().iloc[0]

        current_price = daily_close.iloc[0]

        # 일봉 거래량
        daily_volume = pd.to_numeric(recent['acml_vol'], errors='coerce')
        volume_ma5 = daily_volume.rolling(window=5).mean().iloc[0]

        analysis = {
            'daily_ma5': ma5,
            'daily_ma20': ma20,
            'daily_price_vs_ma5': (current_price - ma5) / ma5 * 100 if pd.notna(ma5) and ma5 > 0 else None,
            'daily_price_vs_ma20': (current_price - ma20) / ma20 * 100 if pd.notna(ma20) and ma20 > 0 else None,
            'daily_volume_vs_ma5': (daily_volume.iloc[0] / volume_ma5) if pd.notna(volume_ma5) and volume_ma5 > 0 else None,

            # 5일 추세
            'daily_trend_5': (daily_close.iloc[0] - daily_close.iloc[4]) / daily_close.iloc[4] * 100 if len(daily_close) > 4 else None,
        }

        return analysis

    def analyze_all_trades(self):
        """모든 거래 분석"""
        print("\n📊 거래 특성 분석 중...")

        losing_analyses = []
        winning_analyses = []

        # 패배 거래 분석
        for trade in self.losing_trades:
            minute_df, daily_df = self.load_ohlcv_data(trade['stock_code'], trade['date'])

            if minute_df is not None:
                minute_df = self.calculate_technical_indicators(minute_df)
                buy_analysis = self.analyze_buy_point_characteristics(trade, minute_df)
                daily_analysis = self.analyze_daily_context(trade, daily_df)

                analysis = {**trade, **buy_analysis, **daily_analysis}
                losing_analyses.append(analysis)

        # 승리 거래 분석
        for trade in self.winning_trades:
            minute_df, daily_df = self.load_ohlcv_data(trade['stock_code'], trade['date'])

            if minute_df is not None:
                minute_df = self.calculate_technical_indicators(minute_df)
                buy_analysis = self.analyze_buy_point_characteristics(trade, minute_df)
                daily_analysis = self.analyze_daily_context(trade, daily_df)

                analysis = {**trade, **buy_analysis, **daily_analysis}
                winning_analyses.append(analysis)

        self.losing_df = pd.DataFrame(losing_analyses)
        self.winning_df = pd.DataFrame(winning_analyses)

        print(f"✅ 패배 거래 분석 완료: {len(self.losing_df)}건")
        print(f"✅ 승리 거래 분석 완료: {len(self.winning_df)}건")

    def compare_and_report(self):
        """승패 거래 비교 및 리포트 생성"""
        print("\n" + "="*80)
        print("📈 OHLCV 기반 승패 거래 비교 분석 결과")
        print("="*80)

        # 비교할 주요 지표들
        key_indicators = [
            ('price_vs_ma5', '5분봉 이평 대비 가격위치(%)'),
            ('price_vs_ma20', '20분봉 이평 대비 가격위치(%)'),
            ('bb_position', '볼린저밴드 위치(%)'),
            ('rsi', 'RSI'),
            ('volume_vs_ma5', '5분봉 거래량비(배)'),
            ('volume_vs_ma20', '20분봉 거래량비(배)'),
            ('volume_trend_5', '직전5봉 거래량추세'),
            ('atr_ratio', '현재봉/ATR 비율'),
            ('price_change_5', '5봉전 대비 가격변화(%)'),
            ('price_change_20', '20봉전 대비 가격변화(%)'),
            ('daily_price_vs_ma5', '일봉5이평 대비(%)'),
            ('daily_price_vs_ma20', '일봉20이평 대비(%)'),
            ('daily_volume_vs_ma5', '일봉거래량비(배)'),
            ('daily_trend_5', '5일 추세(%)'),
        ]

        print("\n🔍 주요 지표별 승패 비교:")
        print("-" * 80)

        recommendations = []

        for indicator, name in key_indicators:
            if indicator in self.losing_df.columns and indicator in self.winning_df.columns:
                losing_values = self.losing_df[indicator].dropna()
                winning_values = self.winning_df[indicator].dropna()

                if len(losing_values) > 0 and len(winning_values) > 0:
                    losing_mean = losing_values.mean()
                    winning_mean = winning_values.mean()
                    losing_median = losing_values.median()
                    winning_median = winning_values.median()

                    diff_mean = winning_mean - losing_mean
                    diff_pct = (diff_mean / abs(losing_mean) * 100) if losing_mean != 0 else 0

                    print(f"\n📌 {name}")
                    print(f"   패배: 평균 {losing_mean:.2f} | 중앙값 {losing_median:.2f}")
                    print(f"   승리: 평균 {winning_mean:.2f} | 중앙값 {winning_median:.2f}")
                    print(f"   차이: {diff_mean:+.2f} ({diff_pct:+.1f}%)")

                    # 의미있는 차이 판단 (10% 이상)
                    if abs(diff_pct) > 10:
                        direction = "높을 때" if diff_mean > 0 else "낮을 때"
                        strength = "강한" if abs(diff_pct) > 30 else "중간"

                        recommendation = {
                            'indicator': name,
                            'losing_mean': losing_mean,
                            'winning_mean': winning_mean,
                            'diff': diff_mean,
                            'diff_pct': diff_pct,
                            'direction': direction,
                            'strength': strength
                        }
                        recommendations.append(recommendation)

        # 개선 제안
        print("\n\n" + "="*80)
        print("💡 OHLCV 기반 매수 조건 개선 제안")
        print("="*80)

        if recommendations:
            # 차이가 큰 순으로 정렬
            recommendations.sort(key=lambda x: abs(x['diff_pct']), reverse=True)

            print("\n🎯 승률 향상을 위한 필터 추가 권장사항:\n")

            for i, rec in enumerate(recommendations[:10], 1):  # 상위 10개만
                print(f"{i}. {rec['indicator']}")
                print(f"   → {rec['strength']} 신호: 값이 {rec['direction']} 승률 높음")
                print(f"   → 패배시 평균: {rec['losing_mean']:.2f}, 승리시 평균: {rec['winning_mean']:.2f}")
                print(f"   → 차이: {rec['diff_pct']:+.1f}%")

                # 구체적 필터 제안
                if rec['indicator'] == 'RSI':
                    if rec['winning_mean'] < rec['losing_mean']:
                        print(f"   ✅ 제안: RSI < {rec['winning_mean'] + 5:.0f} 일 때만 매수")
                    else:
                        print(f"   ✅ 제안: RSI > {rec['winning_mean'] - 5:.0f} 일 때만 매수")

                elif 'volume' in rec['indicator'].lower():
                    if rec['winning_mean'] > rec['losing_mean']:
                        print(f"   ✅ 제안: 거래량이 평균 대비 {rec['winning_mean']:.1f}배 이상일 때 매수")
                    else:
                        print(f"   ✅ 제안: 거래량이 평균 대비 {rec['winning_mean']:.1f}배 이하일 때 매수")

                elif 'bb_position' in rec['indicator']:
                    print(f"   ✅ 제안: 볼린저밴드 {rec['winning_mean']:.0f}% 부근에서 매수")

                elif 'price_vs' in rec['indicator']:
                    if rec['winning_mean'] > 0:
                        print(f"   ✅ 제안: 이동평균선 위에 있을 때 매수")
                    else:
                        print(f"   ✅ 제안: 이동평균선 -{abs(rec['winning_mean']):.1f}% 이내 근접시 매수")

                print()

        else:
            print("⚠️ 명확한 패턴을 찾지 못했습니다.")

        # CSV 저장
        output_file = "D:/GIT/RoboTrader/trade_analysis_results.csv"
        comparison_df = pd.DataFrame(recommendations)
        comparison_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n💾 상세 분석 결과 저장: {output_file}")

        # 패배/승리 거래 상세 데이터도 저장
        self.losing_df.to_csv("D:/GIT/RoboTrader/losing_trades_detail.csv", index=False, encoding='utf-8-sig')
        self.winning_df.to_csv("D:/GIT/RoboTrader/winning_trades_detail.csv", index=False, encoding='utf-8-sig')
        print(f"💾 패배 거래 상세: D:/GIT/RoboTrader/losing_trades_detail.csv")
        print(f"💾 승리 거래 상세: D:/GIT/RoboTrader/winning_trades_detail.csv")

def main():
    analyzer = LosingTradeAnalyzer(
        signal_log_dir="D:/GIT/RoboTrader/signal_replay_log",
        minute_data_dir="D:/GIT/RoboTrader/cache/minute_data",
        daily_data_dir="D:/GIT/RoboTrader/cache/daily"
    )

    analyzer.parse_trade_logs()
    analyzer.analyze_all_trades()
    analyzer.compare_and_report()

if __name__ == "__main__":
    main()
