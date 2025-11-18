import numpy as np
from scipy import stats
import sys

sys.stdout.reconfigure(encoding='utf-8')

# 승리/패배 거래 통계
win_total = 216
loss_total = 211

# 위꼬리 통계
win_upper_tail_avg = 0.321
loss_upper_tail_avg = 0.381
win_upper_std = 0.321 * 0.25
loss_upper_std = 0.381 * 0.25

# 종가 위치 통계
win_close_pos_avg = 0.597
loss_close_pos_avg = 0.503
win_close_std = 0.597 * 0.15
loss_close_std = 0.503 * 0.15

print('='*100)
print('필터 조합 효과 분석')
print('='*100)
print()
print(f'원래 승률: {win_total/(win_total+loss_total)*100:.1f}% (승리 {win_total}건 / 패배 {loss_total}건)')
print()

print('='*100)
print('개별 필터 효과')
print('='*100)
print()

print('필터 1: 위꼬리 비율 < 35%')
print('-' * 100)
win_pass_1 = stats.norm.cdf(0.35, win_upper_tail_avg, win_upper_std)
loss_pass_1 = stats.norm.cdf(0.35, loss_upper_tail_avg, loss_upper_std)

win_remain_1 = int(win_total * win_pass_1)
loss_remain_1 = int(loss_total * loss_pass_1)
winrate_1 = win_remain_1 / (win_remain_1 + loss_remain_1) * 100 if (win_remain_1 + loss_remain_1) > 0 else 0

print(f'승리 거래 통과: {win_pass_1*100:.1f}% ({win_remain_1}/{win_total}건)')
print(f'패배 거래 통과: {loss_pass_1*100:.1f}% ({loss_remain_1}/{loss_total}건)')
print(f'필터 후 승률: {winrate_1:.1f}%')
print(f'승률 개선: {winrate_1 - 50.6:+.1f}%p')
print()

print('필터 2: 종가 위치 > 55%')
print('-' * 100)
win_pass_2 = 1 - stats.norm.cdf(0.55, win_close_pos_avg, win_close_std)
loss_pass_2 = 1 - stats.norm.cdf(0.55, loss_close_pos_avg, loss_close_std)

win_remain_2 = int(win_total * win_pass_2)
loss_remain_2 = int(loss_total * loss_pass_2)
winrate_2 = win_remain_2 / (win_remain_2 + loss_remain_2) * 100 if (win_remain_2 + loss_remain_2) > 0 else 0

print(f'승리 거래 통과: {win_pass_2*100:.1f}% ({win_remain_2}/{win_total}건)')
print(f'패배 거래 통과: {loss_pass_2*100:.1f}% ({loss_remain_2}/{loss_total}건)')
print(f'필터 후 승률: {winrate_2:.1f}%')
print(f'승률 개선: {winrate_2 - 50.6:+.1f}%p')
print()

print('='*100)
print('필터 조합: 위꼬리 < 35% AND 종가위치 > 55%')
print('='*100)
print()

# 독립 가정
win_pass_both = win_pass_1 * win_pass_2
loss_pass_both = loss_pass_1 * loss_pass_2

win_remain_both = int(win_total * win_pass_both)
loss_remain_both = int(loss_total * loss_pass_both)

if (win_remain_both + loss_remain_both) > 0:
    winrate_both = win_remain_both / (win_remain_both + loss_remain_both) * 100
    print(f'승리 거래 통과: {win_pass_both*100:.1f}% ({win_remain_both}/{win_total}건)')
    print(f'패배 거래 통과: {loss_pass_both*100:.1f}% ({loss_remain_both}/{loss_total}건)')
    print(f'필터 후 승률: {winrate_both:.1f}%')
    print(f'승률 개선: {winrate_both - 50.6:+.1f}%p')
    print(f'거래 빈도: {(win_remain_both + loss_remain_both)/(win_total + loss_total)*100:.1f}% (원래 대비)')
else:
    print('필터가 너무 엄격하여 거래 없음')

print()
print('='*100)
print('다양한 필터 기준 시뮬레이션')
print('='*100)
print()

print(f"{'필터 조건':30s} | {'승리통과':>10s} | {'패배통과':>10s} | {'필터후승률':>11s} | {'개선효과':>10s}")
print('-' * 100)

filters = [
    ('위꼬리 < 40%', 0.40, 'upper', True),
    ('위꼬리 < 35%', 0.35, 'upper', True),
    ('위꼬리 < 30%', 0.30, 'upper', True),
    ('종가위치 > 50%', 0.50, 'close', False),
    ('종가위치 > 55%', 0.55, 'close', False),
    ('종가위치 > 60%', 0.60, 'close', False),
]

for name, threshold, metric, is_less_than in filters:
    if metric == 'upper':
        if is_less_than:
            win_pass = stats.norm.cdf(threshold, win_upper_tail_avg, win_upper_std)
            loss_pass = stats.norm.cdf(threshold, loss_upper_tail_avg, loss_upper_std)
        else:
            win_pass = 1 - stats.norm.cdf(threshold, win_upper_tail_avg, win_upper_std)
            loss_pass = 1 - stats.norm.cdf(threshold, loss_upper_tail_avg, loss_upper_std)
    else:  # close
        if is_less_than:
            win_pass = stats.norm.cdf(threshold, win_close_pos_avg, win_close_std)
            loss_pass = stats.norm.cdf(threshold, loss_close_pos_avg, loss_close_std)
        else:
            win_pass = 1 - stats.norm.cdf(threshold, win_close_pos_avg, win_close_std)
            loss_pass = 1 - stats.norm.cdf(threshold, loss_close_pos_avg, loss_close_std)

    win_r = int(win_total * win_pass)
    loss_r = int(loss_total * loss_pass)

    if (win_r + loss_r) > 0:
        new_wr = win_r / (win_r + loss_r) * 100
        improvement = new_wr - 50.6
        print(f'{name:30s} | {win_pass*100:9.1f}% | {loss_pass*100:9.1f}% | {new_wr:10.1f}% | {improvement:+9.1f}%p')
