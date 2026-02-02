"""
가격 위치 기반 전략 시뮬레이션

PricePositionStrategy 클래스를 사용하여 백테스트 실행
"""

import duckdb
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse

from core.strategies.price_position_strategy import PricePositionStrategy


def run_simulation(
    start_date: str = '20250901',
    end_date: str = None,
    config: dict = None,
    verbose: bool = True,
):
    """
    전략 시뮬레이션 실행

    Args:
        start_date: 시작일 (YYYYMMDD)
        end_date: 종료일 (YYYYMMDD, None이면 전체)
        config: 전략 설정
        verbose: 상세 출력 여부

    Returns:
        시뮬레이션 결과
    """
    # 전략 초기화
    strategy = PricePositionStrategy(config=config)
    info = strategy.get_strategy_info()

    print('=' * 80)
    print(f"전략 시뮬레이션: {info['name']}")
    print('=' * 80)
    print(f"진입 조건:")
    print(f"  - 시가 대비: {info['entry_conditions']['pct_from_open']}")
    print(f"  - 시간대: {info['entry_conditions']['time_range']}")
    print(f"  - 요일: {info['entry_conditions']['weekdays']}")
    print(f"청산 조건:")
    print(f"  - 손절: {info['exit_conditions']['stop_loss']}")
    print(f"  - 익절: {info['exit_conditions']['take_profit']}")
    print(f"분석 기간: {start_date} ~", end_date if end_date else "전체")
    print('=' * 80)

    # DB 연결
    conn = duckdb.connect('cache/market_data_v2.duckdb', read_only=True)

    # 모든 분봉 테이블
    tables = conn.execute('''
        SELECT table_name FROM information_schema.tables
        WHERE table_name LIKE 'minute_%'
    ''').fetchall()

    print(f'\n총 종목 수: {len(tables)}')

    # 결과 수집
    daily_results = defaultdict(list)
    all_trades = []

    print('\n시뮬레이션 실행 중...')

    for idx, t in enumerate(tables):
        if verbose and idx % 100 == 0:
            print(f'  {idx}/{len(tables)} 종목 처리 중...')

        table_name = t[0]
        stock_code = table_name.replace('minute_', '')

        try:
            # 날짜 조건
            date_cond = f"WHERE trade_date >= '{start_date}'"
            if end_date:
                date_cond += f" AND trade_date <= '{end_date}'"

            # 해당 종목의 모든 거래일
            dates = conn.execute(f'''
                SELECT DISTINCT trade_date FROM {table_name}
                {date_cond}
                ORDER BY trade_date
            ''').fetchall()

            for d in dates:
                trade_date = d[0]

                # 요일 계산
                try:
                    dt = datetime.strptime(trade_date, '%Y%m%d')
                    weekday = dt.weekday()
                except:
                    continue

                # 분봉 데이터 로드
                df = conn.execute(f'''
                    SELECT * FROM {table_name}
                    WHERE trade_date = '{trade_date}'
                    ORDER BY idx
                ''').fetchdf()

                if len(df) < 50:
                    continue

                day_open = df.iloc[0]['open']
                if day_open <= 0:
                    continue

                # 해당 날짜에 이 종목에서 이미 거래했는지 체크
                traded = False

                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    # 진입 조건 확인
                    can_enter, reason = strategy.check_entry_conditions(
                        stock_code=stock_code,
                        current_price=current_price,
                        day_open=day_open,
                        current_time=current_time,
                        trade_date=trade_date,
                        weekday=weekday,
                    )

                    if not can_enter:
                        continue

                    # 진입 시뮬레이션
                    result = strategy.simulate_trade(df, candle_idx)
                    if result:
                        pct_from_open = (current_price / day_open - 1) * 100

                        trade = {
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            **result
                        }
                        all_trades.append(trade)
                        daily_results[trade_date].append(trade)

                        # 거래 기록
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

        except Exception as e:
            continue

    conn.close()

    # 결과 분석
    print(f'\n총 거래 수: {len(all_trades)}')

    if len(all_trades) == 0:
        print('거래 없음')
        return None

    trades_df = pd.DataFrame(all_trades)

    # 전체 통계
    wins = (trades_df['result'] == 'WIN').sum()
    losses = (trades_df['result'] == 'LOSS').sum()
    total = len(trades_df)
    winrate = wins / total * 100
    total_pnl = trades_df['pnl'].sum()
    avg_pnl = trades_df['pnl'].mean()

    avg_win = trades_df[trades_df['result'] == 'WIN']['pnl'].mean()
    avg_loss = trades_df[trades_df['result'] == 'LOSS']['pnl'].mean()
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print('\n' + '=' * 80)
    print('전체 통계')
    print('=' * 80)
    print(f'총 거래: {total}건 ({wins}승 {losses}패)')
    print(f'승률: {winrate:.1f}%')
    print(f'총 수익률: {total_pnl:+.1f}%')
    print(f'평균 수익률: {avg_pnl:+.2f}%')
    print(f'평균 승리: {avg_win:+.2f}% | 평균 손실: {avg_loss:.2f}%')
    print(f'손익비: {pl_ratio:.2f}:1')

    # 요일별 통계
    print('\n' + '=' * 80)
    print('요일별 통계')
    print('=' * 80)
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    for wd in sorted(trades_df['weekday'].unique()):
        filtered = trades_df[trades_df['weekday'] == wd]
        if len(filtered) == 0:
            continue
        w = (filtered['result'] == 'WIN').sum()
        l = (filtered['result'] == 'LOSS').sum()
        rate = w / len(filtered) * 100
        pnl = filtered['pnl'].sum()
        print(f'{weekday_names[wd]}: {len(filtered)}거래, {w}승 {l}패, {rate:.1f}%, {pnl:+.1f}%')

    # 시간대별 통계
    print('\n' + '=' * 80)
    print('시간대별 통계')
    print('=' * 80)
    trades_df['hour'] = trades_df['entry_time'].apply(lambda x: int(str(x)[:2]))
    for h in sorted(trades_df['hour'].unique()):
        filtered = trades_df[trades_df['hour'] == h]
        if len(filtered) == 0:
            continue
        w = (filtered['result'] == 'WIN').sum()
        l = (filtered['result'] == 'LOSS').sum()
        rate = w / len(filtered) * 100
        pnl = filtered['pnl'].sum()
        print(f'{h}시: {len(filtered)}거래, {w}승 {l}패, {rate:.1f}%, {pnl:+.1f}%')

    # 월별 통계
    print('\n' + '=' * 80)
    print('월별 통계')
    print('=' * 80)
    trades_df['month'] = trades_df['date'].str[:6]
    for month in sorted(trades_df['month'].unique()):
        filtered = trades_df[trades_df['month'] == month]
        w = (filtered['result'] == 'WIN').sum()
        l = (filtered['result'] == 'LOSS').sum()
        rate = w / len(filtered) * 100
        pnl = filtered['pnl'].sum()
        avg = filtered['pnl'].mean()
        print(f'{month}: {len(filtered)}거래, {w}승 {l}패, {rate:.1f}%, 총 {pnl:+.1f}%, 평균 {avg:+.2f}%')

    # 청산 사유별 통계
    print('\n' + '=' * 80)
    print('청산 사유별 통계')
    print('=' * 80)
    for reason in trades_df['exit_reason'].unique():
        filtered = trades_df[trades_df['exit_reason'] == reason]
        w = (filtered['result'] == 'WIN').sum()
        l = (filtered['result'] == 'LOSS').sum()
        rate = w / len(filtered) * 100
        pnl = filtered['pnl'].sum()
        print(f'{reason}: {len(filtered)}거래, {w}승 {l}패, {rate:.1f}%, {pnl:+.1f}%')

    # 일별 상세 (최근 20일)
    print('\n' + '=' * 80)
    print('일별 상세 (최근 20일)')
    print('=' * 80)
    print(f"{'날짜':<12} {'거래':>4} {'승':>3} {'패':>3} {'승률':>7} {'수익':>10}")
    print('-' * 50)

    for date in sorted(daily_results.keys())[-20:]:
        trades = daily_results[date]
        w = sum(1 for t in trades if t['result'] == 'WIN')
        l = sum(1 for t in trades if t['result'] == 'LOSS')
        total_day = len(trades)
        rate = w / total_day * 100 if total_day > 0 else 0
        pnl = sum(t['pnl'] for t in trades)
        print(f'{date:<12} {total_day:>4} {w:>3} {l:>3} {rate:>6.1f}% {pnl:>+9.1f}%')

    # 수익 예상 (100만원/건 기준)
    print('\n' + '=' * 80)
    print('수익 예상 (건당 100만원 기준)')
    print('=' * 80)
    dates = sorted(trades_df['date'].unique())
    num_months = len(set(d[:6] for d in dates))
    monthly_trades = total / max(num_months, 1)
    monthly_profit = (total_pnl / max(num_months, 1)) * 10000

    print(f'분석 기간: {dates[0]} ~ {dates[-1]} ({num_months}개월)')
    print(f'월평균 거래: {monthly_trades:.0f}건')
    print(f'월평균 수익: {monthly_profit:+,.0f}원')

    print('\nDone!')

    return {
        'trades_df': trades_df,
        'daily_results': daily_results,
        'summary': {
            'total': total,
            'wins': wins,
            'losses': losses,
            'winrate': winrate,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'pl_ratio': pl_ratio,
        }
    }


def main():
    parser = argparse.ArgumentParser(description='가격 위치 기반 전략 시뮬레이션')
    parser.add_argument('--start', default='20250901', help='시작일 (YYYYMMDD)')
    parser.add_argument('--end', default=None, help='종료일 (YYYYMMDD)')
    parser.add_argument('--min-pct', type=float, default=2.0, help='시가 대비 최소 상승률 (%%)')
    parser.add_argument('--max-pct', type=float, default=4.0, help='시가 대비 최대 상승률 (%%)')
    parser.add_argument('--start-hour', type=int, default=10, help='진입 시작 시간')
    parser.add_argument('--end-hour', type=int, default=12, help='진입 종료 시간')
    parser.add_argument('--stop-loss', type=float, default=-2.5, help='손절 (%%)')
    parser.add_argument('--take-profit', type=float, default=3.5, help='익절 (%%)')
    parser.add_argument('--quiet', action='store_true', help='진행상황 출력 숨김')

    args = parser.parse_args()

    config = {
        'min_pct_from_open': args.min_pct,
        'max_pct_from_open': args.max_pct,
        'entry_start_hour': args.start_hour,
        'entry_end_hour': args.end_hour,
        'stop_loss_pct': args.stop_loss,
        'take_profit_pct': args.take_profit,
    }

    run_simulation(
        start_date=args.start,
        end_date=args.end,
        config=config,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
