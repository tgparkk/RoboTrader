"""
순수 데이터 기반 수익 패턴 발견 v2
실제 트레이딩 조건 (손절/익절) 적용
"""

import duckdb
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict

class PatternDiscoveryV2:
    """데이터 기반 패턴 발견 (실제 트레이딩 시뮬레이션)"""

    def __init__(self, stop_loss=-2.5, take_profit=3.5):
        self.conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)
        self.stop_loss = stop_loss
        self.take_profit = take_profit

    def get_stocks_and_dates(self):
        """데이터가 있는 종목+날짜 조합"""
        tables = self.conn.execute('''
            SELECT table_name FROM information_schema.tables
            WHERE table_name LIKE 'minute_%'
        ''').fetchall()

        stock_dates = []
        for t in tables:
            table_name = t[0]
            stock_code = table_name.replace('minute_', '')
            try:
                dates = self.conn.execute(f'''
                    SELECT DISTINCT trade_date FROM {table_name}
                    ORDER BY trade_date
                ''').fetchall()
                for d in dates:
                    stock_dates.append((stock_code, d[0]))
            except:
                continue

        return stock_dates

    def get_day_data(self, stock_code, trade_date):
        """특정 종목+날짜의 분봉 데이터"""
        try:
            df = self.conn.execute(f'''
                SELECT * FROM minute_{stock_code}
                WHERE trade_date = '{trade_date}'
                ORDER BY idx
            ''').fetchdf()
            return df
        except:
            return None

    def simulate_entry(self, df, entry_idx):
        """특정 시점 진입 시 손익 시뮬레이션"""
        if entry_idx >= len(df) - 5:
            return None

        entry_price = df.iloc[entry_idx]['close']
        if entry_price <= 0:
            return None

        # 이후 캔들 검사
        for i in range(entry_idx + 1, len(df)):
            row = df.iloc[i]

            # 익절 체크 (고가 기준)
            high_pnl = (row['high'] / entry_price - 1) * 100
            if high_pnl >= self.take_profit:
                return {
                    'result': 'WIN',
                    'pnl': self.take_profit,
                    'exit_idx': i
                }

            # 손절 체크 (저가 기준)
            low_pnl = (row['low'] / entry_price - 1) * 100
            if low_pnl <= self.stop_loss:
                return {
                    'result': 'LOSS',
                    'pnl': self.stop_loss,
                    'exit_idx': i
                }

        # 장 마감
        last_pnl = (df.iloc[-1]['close'] / entry_price - 1) * 100
        return {
            'result': 'WIN' if last_pnl > 0 else 'LOSS',
            'pnl': last_pnl,
            'exit_idx': len(df) - 1
        }

    def calculate_features(self, df, idx):
        """특정 시점의 특성 계산"""
        if idx < 10:
            return None

        row = df.iloc[idx]
        prev_rows = df.iloc[max(0, idx-10):idx]

        # 기본 정보
        hour = int(str(row['time'])[:2])
        minute = int(str(row['time'])[2:4])

        # 시가 (첫 번째 캔들)
        day_open = df.iloc[0]['open']
        if day_open <= 0:
            return None

        current_price = row['close']

        # 시가 대비 상승률
        pct_from_open = (current_price / day_open - 1) * 100

        # 당일 고/저가
        day_high = df.iloc[:idx+1]['high'].max()
        day_low = df.iloc[:idx+1]['low'].min()

        # 당일 범위 내 위치
        if day_high > day_low:
            day_position = (current_price - day_low) / (day_high - day_low)
        else:
            day_position = 0.5

        # 거래량 관련
        day_max_volume = df.iloc[:idx+1]['volume'].max()
        current_volume = row['volume']
        volume_ratio = current_volume / day_max_volume if day_max_volume > 0 else 0

        # 이동평균
        ma5 = prev_rows['close'].tail(5).mean() if len(prev_rows) >= 5 else current_price
        ma10 = prev_rows['close'].tail(10).mean() if len(prev_rows) >= 10 else current_price
        above_ma5 = 1 if current_price > ma5 else 0
        above_ma10 = 1 if current_price > ma10 else 0

        # 캔들 패턴
        is_bullish = 1 if row['close'] > row['open'] else 0

        # 연속 양봉
        bullish_streak = 0
        for i in range(idx, max(0, idx-5), -1):
            if df.iloc[i]['close'] > df.iloc[i]['open']:
                bullish_streak += 1
            else:
                break

        # 직전 캔들 대비 변화
        if idx > 0:
            prev_close = df.iloc[idx-1]['close']
            pct_change = (current_price / prev_close - 1) * 100 if prev_close > 0 else 0
            prev_volume = df.iloc[idx-1]['volume']
            volume_change = current_volume / prev_volume if prev_volume > 0 else 1
        else:
            pct_change = 0
            volume_change = 1

        return {
            'hour': hour,
            'minute': minute,
            'pct_from_open': pct_from_open,
            'day_position': day_position,
            'volume_ratio': volume_ratio,
            'above_ma5': above_ma5,
            'above_ma10': above_ma10,
            'is_bullish': is_bullish,
            'bullish_streak': bullish_streak,
            'pct_change': pct_change,
            'volume_change': volume_change,
        }

    def run_backtest(self, condition_func, name="Test", sample_limit=None):
        """특정 조건으로 백테스트"""
        stock_dates = self.get_stocks_and_dates()

        if sample_limit:
            stock_dates = stock_dates[:sample_limit]

        all_trades = []

        for stock_code, trade_date in stock_dates:
            df = self.get_day_data(stock_code, trade_date)
            if df is None or len(df) < 50:
                continue

            # 각 캔들에서 조건 체크
            traded_today = False
            for idx in range(10, len(df) - 10):
                if traded_today:
                    break

                features = self.calculate_features(df, idx)
                if features is None:
                    continue

                # 12시 이후는 제외
                if features['hour'] >= 12:
                    continue

                # 조건 체크
                if condition_func(features):
                    result = self.simulate_entry(df, idx)
                    if result:
                        trade = {
                            'stock_code': stock_code,
                            'date': trade_date,
                            **features,
                            **result
                        }
                        all_trades.append(trade)
                        traded_today = True  # 하루에 종목당 1번만

        return all_trades

    def close(self):
        self.conn.close()


def main():
    print("=" * 80)
    print("순수 데이터 기반 매매 규칙 발견 v2")
    print("실제 트레이딩 조건: 손절 -2.5%, 익절 +3.5%")
    print("=" * 80)

    discovery = PatternDiscoveryV2(stop_loss=-2.5, take_profit=3.5)

    # 테스트할 조건들
    conditions = {
        "기준선 (조건없음, 10시+)": lambda f: f['hour'] >= 10,

        "시가<2% + 10시+": lambda f: f['pct_from_open'] < 2 and f['hour'] >= 10,

        "시가<3% + 10시+": lambda f: f['pct_from_open'] < 3 and f['hour'] >= 10,

        "시가<4% + 10시+": lambda f: f['pct_from_open'] < 4 and f['hour'] >= 10,

        "시가<3% + 양봉 + 10시+": lambda f: f['pct_from_open'] < 3 and f['is_bullish'] == 1 and f['hour'] >= 10,

        "시가<3% + MA5위 + 10시+": lambda f: f['pct_from_open'] < 3 and f['above_ma5'] == 1 and f['hour'] >= 10,

        "시가<3% + 거래량급증 + 10시+": lambda f: f['pct_from_open'] < 3 and f['volume_change'] > 1.5 and f['hour'] >= 10,

        "시가<2% + 연속양봉2+ + 10시+": lambda f: f['pct_from_open'] < 2 and f['bullish_streak'] >= 2 and f['hour'] >= 10,

        "시가<3% + 당일고점80%+ + 10시+": lambda f: f['pct_from_open'] < 3 and f['day_position'] > 0.8 and f['hour'] >= 10,

        "거래량비율높음 + 10시+": lambda f: f['volume_ratio'] > 0.7 and f['hour'] >= 10,

        "거래량급증 + 양봉 + 10시+": lambda f: f['volume_change'] > 1.5 and f['is_bullish'] == 1 and f['hour'] >= 10,

        "시가<3% + 강한모멘텀 + 10시+": lambda f: f['pct_from_open'] < 3 and f['pct_change'] > 0.3 and f['hour'] >= 10,

        "당일저점근처 + 양봉 + 10시+": lambda f: f['day_position'] < 0.3 and f['is_bullish'] == 1 and f['hour'] >= 10,

        "MA5위 + MA10위 + 양봉 + 10시+": lambda f: f['above_ma5'] == 1 and f['above_ma10'] == 1 and f['is_bullish'] == 1 and f['hour'] >= 10,
    }

    results = []

    print("\n백테스트 실행 중...\n")

    for name, cond_func in conditions.items():
        trades = discovery.run_backtest(cond_func, name)

        if len(trades) < 20:
            continue

        wins = [t for t in trades if t['result'] == 'WIN']
        losses = [t for t in trades if t['result'] == 'LOSS']

        total = len(trades)
        winrate = len(wins) / total * 100
        total_pnl = sum(t['pnl'] for t in trades)
        avg_pnl = total_pnl / total

        avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        results.append({
            'name': name,
            'trades': total,
            'wins': len(wins),
            'losses': len(losses),
            'winrate': winrate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'pl_ratio': pl_ratio,
        })

        print(f"{name}: {total}거래, {winrate:.1f}% 승률, {total_pnl:+.1f}% 총수익")

    # 결과 정렬 및 출력
    print("\n" + "=" * 80)
    print("결과 요약 (총 수익 기준 정렬)")
    print("=" * 80)

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('total_pnl', ascending=False)

    print(f"\n{'Strategy':<35} {'Trades':>7} {'WinRate':>8} {'TotalPnL':>10} {'AvgPnL':>8} {'P/L':>6}")
    print("-" * 80)

    for _, r in results_df.iterrows():
        print(f"{r['name']:<35} {r['trades']:>7} {r['winrate']:>7.1f}% {r['total_pnl']:>+9.1f}% {r['avg_pnl']:>+7.2f}% {r['pl_ratio']:>5.2f}")

    # 최고 승률
    print("\n" + "=" * 80)
    print("최고 승률 전략 (min 50 trades)")
    print("=" * 80)

    high_winrate = results_df[results_df['trades'] >= 50].nlargest(5, 'winrate')
    for _, r in high_winrate.iterrows():
        print(f"{r['name']}: {r['winrate']:.1f}% ({r['wins']}W {r['losses']}L)")

    # 최고 수익
    print("\n" + "=" * 80)
    print("최고 수익 전략 (min 50 trades)")
    print("=" * 80)

    high_profit = results_df[results_df['trades'] >= 50].nlargest(5, 'total_pnl')
    for _, r in high_profit.iterrows():
        print(f"{r['name']}: {r['total_pnl']:+.1f}% ({r['trades']}거래)")

    discovery.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
