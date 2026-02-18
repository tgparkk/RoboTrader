"""
새로운 전략 테스트 스크립트
시가 대비 상승률, 시간대, 요일 필터 조합 테스트
"""

import duckdb
import os
import sys
from datetime import datetime, timedelta
import pandas as pd

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.indicators.pullback_candle_pattern import PullbackCandlePattern

class StrategyTester:
    """전략 테스터"""

    def __init__(self):
        self.conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)
        self.results = []

    def get_available_dates(self):
        """사용 가능한 거래일 목록"""
        tables = self.conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name LIKE 'minute_%'
            ORDER BY table_name LIMIT 50
        """).fetchall()

        all_dates = set()
        for t in tables[:50]:
            try:
                dates = self.conn.execute(f"SELECT DISTINCT trade_date FROM {t[0]}").fetchall()
                all_dates.update([d[0] for d in dates])
            except:
                continue
        return sorted(all_dates)

    def get_stocks_for_date(self, trade_date):
        """특정 날짜에 데이터가 있는 종목 목록"""
        tables = self.conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name LIKE 'minute_%'
        """).fetchall()

        stocks = []
        for t in tables:
            table_name = t[0]
            stock_code = table_name.replace('minute_', '')
            try:
                count = self.conn.execute(f"""
                    SELECT COUNT(*) FROM {table_name} WHERE trade_date = '{trade_date}'
                """).fetchone()[0]
                if count > 20:  # 최소 20개 캔들
                    stocks.append(stock_code)
            except:
                continue
        return stocks

    def get_minute_data(self, stock_code, trade_date):
        """분봉 데이터 로드"""
        try:
            df = self.conn.execute(f"""
                SELECT * FROM minute_{stock_code}
                WHERE trade_date = '{trade_date}'
                ORDER BY idx
            """).fetchdf()
            return df
        except:
            return None

    def simulate_trade(self, stock_code, trade_date, buy_idx, df,
                       stop_loss=-2.5, take_profit=3.5):
        """거래 시뮬레이션"""
        if buy_idx >= len(df) - 1:
            return None

        buy_row = df.iloc[buy_idx]
        buy_price = buy_row['close']
        buy_time = buy_row['time'][:4]

        # 이후 캔들에서 손익 확인
        for i in range(buy_idx + 1, len(df)):
            row = df.iloc[i]

            # 고가로 익절 확인
            high_pnl = (row['high'] / buy_price - 1) * 100
            if high_pnl >= take_profit:
                return {
                    'stock_code': stock_code,
                    'date': trade_date,
                    'buy_time': buy_time,
                    'buy_price': buy_price,
                    'exit_time': row['time'][:4],
                    'exit_price': buy_price * (1 + take_profit/100),
                    'pnl': take_profit,
                    'result': 'WIN'
                }

            # 저가로 손절 확인
            low_pnl = (row['low'] / buy_price - 1) * 100
            if low_pnl <= stop_loss:
                return {
                    'stock_code': stock_code,
                    'date': trade_date,
                    'buy_time': buy_time,
                    'buy_price': buy_price,
                    'exit_time': row['time'][:4],
                    'exit_price': buy_price * (1 + stop_loss/100),
                    'pnl': stop_loss,
                    'result': 'LOSS'
                }

        # 장 마감까지 미체결
        last_row = df.iloc[-1]
        last_pnl = (last_row['close'] / buy_price - 1) * 100
        return {
            'stock_code': stock_code,
            'date': trade_date,
            'buy_time': buy_time,
            'buy_price': buy_price,
            'exit_time': last_row['time'][:4],
            'exit_price': last_row['close'],
            'pnl': last_pnl,
            'result': 'WIN' if last_pnl > 0 else 'LOSS'
        }

    def test_strategy(self, strategy_name,
                      max_rise_from_open=None,  # 시가 대비 최대 상승률
                      min_hour=9,               # 최소 시간 (9=9시부터, 10=10시부터)
                      exclude_weekdays=None,    # 제외할 요일 (0=월, 1=화, ...)
                      verbose=True):
        """전략 테스트"""

        if exclude_weekdays is None:
            exclude_weekdays = []

        dates = self.get_available_dates()
        if verbose:
            print(f"\n=== Testing Strategy: {strategy_name} ===")
            print(f"Parameters: max_rise={max_rise_from_open}%, min_hour={min_hour}, exclude_days={exclude_weekdays}")
            print(f"Available dates: {len(dates)}")

        all_trades = []

        for trade_date in dates:
            # 요일 확인
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()

            if weekday in exclude_weekdays:
                continue

            stocks = self.get_stocks_for_date(trade_date)

            for stock_code in stocks:
                df = self.get_minute_data(stock_code, trade_date)
                if df is None or len(df) < 20:
                    continue

                day_open = df['open'].iloc[0]

                # 각 캔들에서 매수 신호 확인
                for idx in range(10, len(df) - 5):
                    row = df.iloc[idx]

                    # 시간 확인
                    hour = int(row['time'][:2])
                    if hour < min_hour or hour >= 12:  # 12시 이전만
                        continue

                    # 시가 대비 상승률 확인
                    current_price = row['close']
                    rise_from_open = (current_price / day_open - 1) * 100

                    if max_rise_from_open is not None and rise_from_open >= max_rise_from_open:
                        continue

                    # 눌림목 패턴 확인
                    data_slice = df.iloc[:idx+1].copy()
                    try:
                        signal = PullbackCandlePattern.generate_improved_signals(
                            data_slice, stock_code, debug=False
                        )

                        if signal and signal.signal_type in ['PULLBACK_BUY', 'BUY']:
                            # 거래 시뮬레이션
                            trade_result = self.simulate_trade(stock_code, trade_date, idx, df)
                            if trade_result:
                                trade_result['rise_from_open'] = rise_from_open
                                trade_result['hour'] = hour
                                trade_result['weekday'] = weekday
                                all_trades.append(trade_result)
                                # 같은 종목은 해당 일에 1번만
                                break
                    except:
                        continue

        # 결과 분석
        if not all_trades:
            print(f"No trades found for {strategy_name}")
            return None

        wins = [t for t in all_trades if t['result'] == 'WIN']
        losses = [t for t in all_trades if t['result'] == 'LOSS']

        total_pnl = sum(t['pnl'] for t in all_trades)
        winrate = len(wins) / len(all_trades) * 100
        avg_pnl = total_pnl / len(all_trades)

        avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
        profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # 월별 분석
        monthly = {}
        for t in all_trades:
            month = t['date'][:6]
            if month not in monthly:
                monthly[month] = {'wins': 0, 'losses': 0, 'pnl': 0}
            if t['result'] == 'WIN':
                monthly[month]['wins'] += 1
            else:
                monthly[month]['losses'] += 1
            monthly[month]['pnl'] += t['pnl']

        result = {
            'strategy': strategy_name,
            'total_trades': len(all_trades),
            'wins': len(wins),
            'losses': len(losses),
            'winrate': winrate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_loss_ratio': profit_loss_ratio,
            'monthly': monthly,
            'trades': all_trades
        }

        if verbose:
            print(f"\n--- Results for {strategy_name} ---")
            print(f"Total: {len(all_trades)} trades ({len(wins)}W {len(losses)}L)")
            print(f"Win Rate: {winrate:.1f}%")
            print(f"Total PnL: {total_pnl:+.1f}%")
            print(f"Avg PnL: {avg_pnl:+.2f}%")
            print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:.2f}%")
            print(f"Profit/Loss Ratio: {profit_loss_ratio:.2f}:1")
            print(f"\nMonthly breakdown:")
            for month in sorted(monthly.keys()):
                m = monthly[month]
                total = m['wins'] + m['losses']
                rate = m['wins'] / total * 100 if total > 0 else 0
                print(f"  {month}: {m['wins']}W {m['losses']}L ({rate:.0f}%) PnL: {m['pnl']:+.1f}%")

        return result

    def close(self):
        self.conn.close()


def main():
    """메인 실행"""
    tester = StrategyTester()

    strategies = [
        # (이름, max_rise, min_hour, exclude_weekdays)
        ("CURRENT (No Filter)", None, 9, []),
        ("NEW 1: Rise<4% Hour>=10 NotTue/Thu", 4, 10, [1, 3]),
        ("NEW 2: Rise<3% Hour>=10 NotTue/Thu", 3, 10, [1, 3]),
        ("NEW 3: Rise<5% Hour>=10 NotTue", 5, 10, [1]),
        ("NEW 4: Rise<4% Hour>=9 NotTue/Thu", 4, 9, [1, 3]),
        ("NEW 5: Rise<6% Hour>=10 NotTue", 6, 10, [1]),
        ("NEW 6: Rise<4% Hour>=10 NotTue", 4, 10, [1]),
    ]

    all_results = []

    for name, max_rise, min_hour, exclude_days in strategies:
        result = tester.test_strategy(
            name,
            max_rise_from_open=max_rise,
            min_hour=min_hour,
            exclude_weekdays=exclude_days,
            verbose=True
        )
        if result:
            all_results.append(result)

    # 최종 요약
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    print(f"{'Strategy':<40} {'Trades':>6} {'WinRate':>8} {'TotPnL':>8} {'AvgPnL':>8} {'P/L':>6}")
    print("-"*80)

    for r in all_results:
        print(f"{r['strategy']:<40} {r['total_trades']:>6} {r['winrate']:>7.1f}% {r['total_pnl']:>+7.1f}% {r['avg_pnl']:>+7.2f}% {r['profit_loss_ratio']:>5.2f}:1")

    # 월별 수익 예상 (100만원 기준)
    print("\n" + "="*80)
    print("ESTIMATED MONTHLY PROFIT (1M KRW per trade)")
    print("="*80)

    for r in all_results:
        # 5개월 데이터 기준
        monthly_trades = r['total_trades'] / 5
        monthly_profit = (r['total_pnl'] / 5) * 10000
        print(f"{r['strategy']:<40} ~{monthly_trades:>4.0f} trades/month, {monthly_profit:>+10,.0f}원/month")

    tester.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
