"""
최대 보유시간 멀티버스 시뮬레이션

다양한 보유시간 제한에서의 성과를 비교하여 최적 보유시간을 탐색.
"""

import sys
import io
from contextlib import redirect_stdout
from simulate_with_screener import (
    run_simulation, calc_fixed_capital_returns, apply_daily_limit
)


def run_multiverse(start_date='20250224', end_date='20260311', cost_pct=0.33):
    """멀티버스 실행: 보유시간별 성과 비교"""

    scenarios = [
        {'name': '제한없음', 'max_hold': 0},
        {'name': '30분', 'max_hold': 30},
        {'name': '1시간', 'max_hold': 60},
        {'name': '1.5시간', 'max_hold': 90},
        {'name': '2시간', 'max_hold': 120},
        {'name': '3시간', 'max_hold': 180},
    ]

    results = []

    for sc in scenarios:
        print(f"\n{'='*60}")
        print(f"  시나리오: 최대 보유 {sc['name']}")
        print(f"{'='*60}")

        # 시뮬 실행 (상세 출력 억제)
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()

        trades_df = run_simulation(
            start_date=start_date,
            end_date=end_date,
            max_daily=5,
            verbose=False,
            cost_pct=cost_pct,
            max_holding_minutes=sc['max_hold'],
        )

        sys.stdout = old_stdout

        if trades_df is None or len(trades_df) == 0:
            print(f"  거래 없음")
            continue

        # 5종목 제한 적용
        limited_df = apply_daily_limit(trades_df, 5)
        if len(limited_df) == 0:
            print(f"  거래 없음 (5종목 제한 후)")
            continue

        # 통계 계산
        total = len(limited_df)
        wins = (limited_df['result'] == 'WIN').sum()
        losses = total - wins
        winrate = wins / total * 100
        avg_pnl = limited_df['pnl'].mean()
        avg_net = avg_pnl - cost_pct

        avg_win = limited_df[limited_df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
        avg_loss = limited_df[limited_df['result'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        cap = calc_fixed_capital_returns(limited_df, cost_pct=cost_pct)

        # 청산 사유별 분포
        exit_counts = limited_df['exit_reason'].value_counts().to_dict()

        avg_hold = limited_df['holding_candles'].mean()

        results.append({
            'name': sc['name'],
            'max_hold': sc['max_hold'],
            'total': total,
            'wins': wins,
            'winrate': winrate,
            'avg_pnl': avg_pnl,
            'avg_net': avg_net,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'pl_ratio': pl_ratio,
            'fixed_return': cap['total_return_pct'],
            'final_capital': cap['final_capital'],
            'avg_hold_min': avg_hold,
            'exit_counts': exit_counts,
        })

        print(f"  거래: {total}건 ({wins}승 {losses}패) | 승률: {winrate:.1f}%")
        print(f"  순평균: {avg_net:+.2f}% | 고정수익률: {cap['total_return_pct']:+.2f}%")
        print(f"  평균보유: {avg_hold:.0f}분 | 승:{avg_win:+.2f}% 패:{avg_loss:+.2f}%")
        exits_str = ', '.join(f"{k}:{v}" for k, v in sorted(exit_counts.items()))
        print(f"  청산사유: {exits_str}")

    # ===== 비교표 =====
    if not results:
        print("\n결과 없음")
        return

    print(f"\n\n{'#'*80}")
    print(f"#  멀티버스 비교표 (비용 {cost_pct:.2f}%/건, 고정자본, 5종목)")
    print(f"#  기간: {start_date} ~ {end_date}")
    print(f"{'#'*80}\n")

    header = (f"{'시나리오':>10} | {'거래':>5} | {'승률':>6} | {'순평균':>7} | "
              f"{'고정수익률':>10} | {'최종자본':>12} | {'평균보유':>7} | "
              f"{'손익비':>5} | {'익절':>4} | {'손절':>4} | {'시간청산':>6} | {'장마감':>4}")
    print(header)
    print('-' * len(header))

    baseline_return = results[0]['fixed_return'] if results else 0

    for r in results:
        diff = r['fixed_return'] - baseline_return
        diff_str = f"({diff:+.1f}%p)" if r['max_hold'] > 0 else ""

        tp = r['exit_counts'].get('익절', 0)
        sl = r['exit_counts'].get('손절', 0)
        tc = r['exit_counts'].get('시간청산', 0)
        mc = r['exit_counts'].get('장마감', 0)

        print(f"{r['name']:>10} | {r['total']:>5} | {r['winrate']:>5.1f}% | "
              f"{r['avg_net']:>+6.2f}% | {r['fixed_return']:>+9.2f}% | "
              f"{r['final_capital']/10000:>10,.0f}만 | {r['avg_hold_min']:>5.0f}분 | "
              f"{r['pl_ratio']:>5.2f} | {tp:>4} | {sl:>4} | {tc:>6} | {mc:>4}  {diff_str}")

    # 최적 시나리오
    best = max(results, key=lambda x: x['fixed_return'])
    print(f"\n최고 수익: {best['name']} ({best['fixed_return']:+.2f}%)")

    # 2시간 vs 제한없음 상세 비교
    no_limit = next((r for r in results if r['max_hold'] == 0), None)
    two_hour = next((r for r in results if r['max_hold'] == 120), None)
    if no_limit and two_hour:
        print(f"\n--- 2시간 vs 제한없음 ---")
        print(f"  수익률 차이: {two_hour['fixed_return'] - no_limit['fixed_return']:+.2f}%p")
        print(f"  거래수 차이: {two_hour['total'] - no_limit['total']:+d}건")
        print(f"  승률 차이: {two_hour['winrate'] - no_limit['winrate']:+.1f}%p")
        print(f"  평균보유 단축: {no_limit['avg_hold_min']:.0f}분 → {two_hour['avg_hold_min']:.0f}분")

    print("\nDone!")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='보유시간 멀티버스 시뮬')
    parser.add_argument('--start', default='20250224')
    parser.add_argument('--end', default='20260311')
    parser.add_argument('--cost', type=float, default=0.33)
    args = parser.parse_args()

    run_multiverse(args.start, args.end, args.cost)
