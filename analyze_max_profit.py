"""장중 최고 수익률 기준 그룹별 분석"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from simulate_with_screener import run_simulation, apply_daily_limit
import pandas as pd

trades_df = run_simulation(
    start_date='20250224',
    end_date='20260305',
    config={
        'entry_start_pct': 0.01, 'entry_end_pct': 0.03,
        'stop_loss': 0.04, 'take_profit': 0.05,
        'entry_start_hour': 9, 'entry_start_minute': 0,
        'entry_end_hour': 12, 'entry_end_minute': 0,
        'use_advanced_filter': True,
        'volatility_threshold': 0.008, 'momentum_threshold': 0.02,
    },
    verbose=False,
)

df = apply_daily_limit(trades_df, 5)
total = len(df)

print()
print('=' * 80)
print('  장중 최고 수익률(max_profit_pct) 기준 그룹별 분석 (동시보유 5종목)')
print('=' * 80)

bins = [
    ('5.0%+ (익절 도달)', df['max_profit_pct'] >= 5.0),
    ('4.0~4.9%', (df['max_profit_pct'] >= 4.0) & (df['max_profit_pct'] < 5.0)),
    ('3.0~3.9%', (df['max_profit_pct'] >= 3.0) & (df['max_profit_pct'] < 4.0)),
    ('2.0~2.9%', (df['max_profit_pct'] >= 2.0) & (df['max_profit_pct'] < 3.0)),
    ('1.0~1.9%', (df['max_profit_pct'] >= 1.0) & (df['max_profit_pct'] < 2.0)),
    ('0.0~0.9%', (df['max_profit_pct'] >= 0.0) & (df['max_profit_pct'] < 1.0)),
    ('마이너스', df['max_profit_pct'] < 0.0),
]

header = f"{'그룹':<22} {'건수':>6} {'비율':>7} {'실현PnL':>9} {'승률':>7} {'보유봉':>7} {'시가대비':>8}"
print(f'\n전체 거래: {total}건')
print(header)
print('-' * 70)

for label, mask in bins:
    g = df[mask]
    if len(g) == 0:
        continue
    cnt = len(g)
    pct = cnt / total * 100
    avg_pnl = g['pnl'].mean()
    win_rate = (g['result'] == 'WIN').sum() / cnt * 100
    avg_hold = g['holding_candles'].mean()
    avg_open_pct = g['pct_from_open'].mean()
    print(f'{label:<22} {cnt:>5}건 {pct:>6.1f}% {avg_pnl:>+8.2f}% {win_rate:>6.1f}% {avg_hold:>6.0f}봉 {avg_open_pct:>+7.2f}%')

# 청산 사유 교차분석
print()
print('=' * 80)
print('  그룹별 청산 사유 분포')
print('=' * 80)
hdr2 = f"{'그룹':<22} {'익절':>8} {'장마감':>8} {'손절':>8}"
print(hdr2)
print('-' * 50)

for label, mask in bins:
    g = df[mask]
    if len(g) == 0:
        continue
    tp = (g['exit_reason'] == '익절').sum() / len(g) * 100
    mc = (g['exit_reason'] == '장마감').sum() / len(g) * 100
    sl = (g['exit_reason'] == '손절').sum() / len(g) * 100
    print(f'{label:<22} {tp:>6.1f}% {mc:>7.1f}% {sl:>7.1f}%')

# 4~4.9% 아깝게 놓친 그룹 상세
near_miss = df[(df['max_profit_pct'] >= 4.0) & (df['max_profit_pct'] < 5.0)]
if len(near_miss) > 0:
    print()
    print('=' * 80)
    print(f'  아깝게 익절 못한 그룹 (최고 4.0~4.9%): {len(near_miss)}건')
    print('=' * 80)
    print('  실현 수익률 분포:')
    for lo, hi, label in [(3,4,'+3~+4%'), (2,3,'+2~+3%'), (1,2,'+1~+2%'), (0,1,'0~+1%'), (-99,0,'마이너스')]:
        m = (near_miss['pnl'] >= lo) & (near_miss['pnl'] < hi)
        print(f'    {label}: {m.sum()}건 ({m.sum()/len(near_miss)*100:.1f}%)')
    avg_max = near_miss['max_profit_pct'].mean()
    avg_real = near_miss['pnl'].mean()
    print(f'  평균 최고이익: +{avg_max:.2f}%')
    print(f'  평균 실현이익: +{avg_real:.2f}%')
    print(f'  -> 평균 {avg_max - avg_real:.2f}%p 반납')

# 3~3.9% 그룹도 상세
mid_group = df[(df['max_profit_pct'] >= 3.0) & (df['max_profit_pct'] < 4.0)]
if len(mid_group) > 0:
    print()
    print('=' * 80)
    print(f'  중간 그룹 (최고 3.0~3.9%): {len(mid_group)}건')
    print('=' * 80)
    print('  실현 수익률 분포:')
    for lo, hi, label in [(2,3,'+2~+3%'), (1,2,'+1~+2%'), (0,1,'0~+1%'), (-99,0,'마이너스')]:
        m = (mid_group['pnl'] >= lo) & (mid_group['pnl'] < hi)
        print(f'    {label}: {m.sum()}건 ({m.sum()/len(mid_group)*100:.1f}%)')
    avg_max = mid_group['max_profit_pct'].mean()
    avg_real = mid_group['pnl'].mean()
    print(f'  평균 최고이익: +{avg_max:.2f}%')
    print(f'  평균 실현이익: +{avg_real:.2f}%')
    print(f'  -> 평균 {avg_max - avg_real:.2f}%p 반납')

# 전체 요약: 만약 익절 목표를 바꾸면?
print()
print('=' * 80)
print('  익절 목표별 시나리오 비교 (현재 데이터 기반 추정)')
print('=' * 80)
for tp_target in [3.0, 3.5, 4.0, 4.5, 5.0]:
    # tp_target에 도달한 거래 = 익절 처리, 아닌 건 그대로
    reached = df[df['max_profit_pct'] >= tp_target]
    not_reached = df[df['max_profit_pct'] < tp_target]
    # 도달한 건 tp_target으로 수익, 미도달건은 기존 pnl 유지
    total_pnl = reached.shape[0] * tp_target + not_reached['pnl'].sum()
    avg_pnl = total_pnl / total
    tp_rate = len(reached) / total * 100
    print(f'  익절 {tp_target:.1f}%: 도달 {len(reached)}건({tp_rate:.1f}%), 평균PnL {avg_pnl:+.2f}%')

print('\nDone!')
