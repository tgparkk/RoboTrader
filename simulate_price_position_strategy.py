"""
가격 위치 기반 전략 시뮬레이션

PricePositionStrategy 클래스를 사용하여 백테스트 실행
"""

import psycopg2
import pandas as pd
from datetime import datetime
from collections import defaultdict
import argparse

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


def print_stats(trades_df, daily_results, label: str):
    """거래 통계 출력"""
    if len(trades_df) == 0:
        print(f'\n[{label}] 거래 없음')
        return

    wins = (trades_df['result'] == 'WIN').sum()
    losses = (trades_df['result'] == 'LOSS').sum()
    total = len(trades_df)
    winrate = wins / total * 100
    total_pnl = trades_df['pnl'].sum()
    avg_pnl = trades_df['pnl'].mean()

    avg_win = trades_df[trades_df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
    avg_loss = trades_df[trades_df['result'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print('\n' + '=' * 80)
    print(f'전체 통계 [{label}]')
    print('=' * 80)
    print(f'총 거래: {total}건 ({wins}승 {losses}패)')
    print(f'승률: {winrate:.1f}%')
    print(f'총 수익률: {total_pnl:+.1f}%')
    print(f'평균 수익률: {avg_pnl:+.2f}%')
    print(f'평균 승리: {avg_win:+.2f}% | 평균 손실: {avg_loss:.2f}%')
    print(f'손익비: {pl_ratio:.2f}:1')

    # 요일별 통계
    print('\n' + '=' * 80)
    print(f'요일별 통계 [{label}]')
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
    print(f'시간대별 통계 [{label}]')
    print('=' * 80)
    trades_df = trades_df.copy()
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
    print(f'월별 통계 [{label}]')
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
    print(f'청산 사유별 통계 [{label}]')
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
    print(f'일별 상세 (최근 20일) [{label}]')
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
    print(f'수익 예상 (건당 100만원 기준) [{label}]')
    print('=' * 80)
    dates = sorted(trades_df['date'].unique())
    num_months = len(set(d[:6] for d in dates))
    monthly_trades = total / max(num_months, 1)
    monthly_profit = (total_pnl / max(num_months, 1)) * 10000

    print(f'분석 기간: {dates[0]} ~ {dates[-1]} ({num_months}개월)')
    print(f'월평균 거래: {monthly_trades:.0f}건')
    print(f'월평균 수익: {monthly_profit:+,.0f}원')


def apply_daily_limit(trades_df, max_daily):
    """동시 보유 제한 적용 (시간순 진입, 청산 시 새 매수 가능)

    각 거래의 entry_time/exit_time을 기반으로 동시 보유 수를 추적.
    동시 보유 < max_daily 일 때만 새로운 진입을 허용.
    """
    limited = []
    for date in trades_df['date'].unique():
        day_trades = trades_df[trades_df['date'] == date].copy()
        day_trades = day_trades.sort_values('entry_time')

        accepted = []  # (entry_time, exit_time) 리스트
        for _, trade in day_trades.iterrows():
            entry_t = str(trade['entry_time']).zfill(6)
            exit_t = str(trade['exit_time']).zfill(6)

            # 현재 진입 시점에 아직 청산 안 된 포지션 수 계산
            holding = sum(1 for _, et in accepted if et > entry_t)
            if holding < max_daily:
                accepted.append((entry_t, exit_t))
                limited.append(trade)

    return pd.DataFrame(limited).reset_index(drop=True) if limited else pd.DataFrame()


def run_simulation(
    start_date: str = '20250901',
    end_date: str = None,
    config: dict = None,
    max_daily: int = 5,
    verbose: bool = True,
):
    """
    전략 시뮬레이션 실행

    Args:
        start_date: 시작일 (YYYYMMDD)
        end_date: 종료일 (YYYYMMDD, None이면 전체)
        config: 전략 설정
        max_daily: 동시보유 거래수 (0이면 무제한만 표시)
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
    print(f"동시 보유 제한: {max_daily}종목" if max_daily > 0 else "동시 보유 제한: 없음")
    print(f"분석 기간: {start_date} ~", end_date if end_date else "전체")
    print('=' * 80)

    # PostgreSQL 연결
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    # 모든 종목 코드
    date_cond = "WHERE trade_date >= %s"
    params = [start_date]
    if end_date:
        date_cond += " AND trade_date <= %s"
        params.append(end_date)

    cur.execute(f'''
        SELECT DISTINCT stock_code FROM minute_candles
        {date_cond}
        ORDER BY stock_code
    ''', params)
    stock_codes = [row[0] for row in cur.fetchall()]

    print(f'\n총 종목 수: {len(stock_codes)}')

    # 결과 수집
    all_trades = []

    print('\n시뮬레이션 실행 중...')

    for idx, stock_code in enumerate(stock_codes):
        if verbose and idx % 100 == 0:
            print(f'  {idx}/{len(stock_codes)} 종목 처리 중...')

        try:
            # 해당 종목의 모든 거래일
            cur.execute(f'''
                SELECT DISTINCT trade_date FROM minute_candles
                WHERE stock_code = %s AND {date_cond.replace("WHERE ", "")}
                ORDER BY trade_date
            ''', [stock_code] + params)
            dates = cur.fetchall()

            for d in dates:
                trade_date = d[0]

                # 요일 계산
                try:
                    dt = datetime.strptime(trade_date, '%Y%m%d')
                    weekday = dt.weekday()
                except:
                    continue

                # 분봉 데이터 로드
                cur.execute('''
                    SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s
                    ORDER BY idx
                ''', [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue

                columns = ['idx', 'date', 'time', 'close', 'open', 'high', 'low', 'volume', 'amount', 'datetime']
                df = pd.DataFrame(rows, columns=columns)

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

                    # 고급 진입 필터 (변동성, 모멘텀)
                    adv_ok, adv_reason = strategy.check_advanced_conditions(
                        df=df, candle_idx=candle_idx
                    )
                    if not adv_ok:
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

                        # 거래 기록
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

        except Exception as e:
            continue

    cur.close()
    conn.close()

    # 결과 분석
    print(f'\n총 거래 수: {len(all_trades)}')

    if len(all_trades) == 0:
        print('거래 없음')
        return None

    trades_df = pd.DataFrame(all_trades)

    # === 무제한 결과 ===
    unlimited_daily = defaultdict(list)
    for t in all_trades:
        unlimited_daily[t['date']].append(t)
    print_stats(trades_df, unlimited_daily, '무제한')

    # === 동시보유 거래수 제한 결과 ===
    if max_daily > 0:
        limited_df = apply_daily_limit(trades_df, max_daily)
        limited_daily = defaultdict(list)
        for _, row in limited_df.iterrows():
            limited_daily[row['date']].append(row.to_dict())

        print('\n')
        print('#' * 80)
        print(f'#  동시보유 {max_daily}종목 제한 적용')
        print('#' * 80)
        print_stats(limited_df, limited_daily, f'동시보유 {max_daily}종목')

        # === 비교 요약 ===
        u_wins = (trades_df['result'] == 'WIN').sum()
        u_total = len(trades_df)
        u_pnl = trades_df['pnl'].sum()

        l_wins = (limited_df['result'] == 'WIN').sum()
        l_total = len(limited_df)
        l_pnl = limited_df['pnl'].sum()

        print('\n' + '=' * 80)
        print('비교 요약')
        print('=' * 80)
        print(f"{'':>20} {'무제한':>15} {'최대 '+str(max_daily)+'종목':>15}")
        print('-' * 50)
        print(f"{'거래수':>20} {u_total:>14}건 {l_total:>14}건")
        print(f"{'승률':>20} {u_wins/u_total*100:>13.1f}% {l_wins/l_total*100 if l_total else 0:>13.1f}%")
        print(f"{'총 수익률':>20} {u_pnl:>+13.1f}% {l_pnl:>+13.1f}%")
        print(f"{'평균 수익률':>20} {trades_df['pnl'].mean():>+13.2f}% {limited_df['pnl'].mean() if l_total else 0:>+13.2f}%")

    print('\nDone!')

    return {
        'trades_df': trades_df,
        'daily_results': unlimited_daily,
        'summary': {
            'total': len(trades_df),
            'wins': (trades_df['result'] == 'WIN').sum(),
            'losses': (trades_df['result'] == 'LOSS').sum(),
            'winrate': (trades_df['result'] == 'WIN').sum() / len(trades_df) * 100,
            'total_pnl': trades_df['pnl'].sum(),
            'avg_pnl': trades_df['pnl'].mean(),
        }
    }


def main():
    parser = argparse.ArgumentParser(description='가격 위치 기반 전략 시뮬레이션')
    parser.add_argument('--start', default='20250901', help='시작일 (YYYYMMDD)')
    parser.add_argument('--end', default=None, help='종료일 (YYYYMMDD)')
    parser.add_argument('--min-pct', type=float, default=2.0, help='시가 대비 최소 상승률 (%%)')
    parser.add_argument('--max-pct', type=float, default=3.0, help='시가 대비 최대 상승률 (%%)')
    parser.add_argument('--start-hour', type=int, default=9, help='진입 시작 시간')
    parser.add_argument('--end-hour', type=int, default=11, help='진입 종료 시간')
    parser.add_argument('--stop-loss', type=float, default=-3.0, help='손절 (%%)')
    parser.add_argument('--take-profit', type=float, default=5.0, help='익절 (%%)')
    parser.add_argument('--max-daily', type=int, default=5, help='동시보유 거래 종목수 (0=무제한만 표시)')
    parser.add_argument('--max-volatility', type=float, default=0.8, help='진입전 변동성 상한 (%%, 0=비활성)')
    parser.add_argument('--max-momentum', type=float, default=2.0, help='20봉 모멘텀 상한 (%%, 0=비활성)')
    parser.add_argument('--weekdays', default=None, help='허용 요일 (0=월~4=금, 쉼표구분, 예: 0,2,4)')
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
    if args.weekdays is not None:
        config['allowed_weekdays'] = [int(d) for d in args.weekdays.split(',')]
    if args.max_volatility > 0:
        config['max_pre_volatility'] = args.max_volatility
    if args.max_momentum > 0:
        config['max_pre20_momentum'] = args.max_momentum

    run_simulation(
        start_date=args.start,
        end_date=args.end,
        config=config,
        max_daily=args.max_daily,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
