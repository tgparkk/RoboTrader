import os
import re

# signal_replay_log 건수
sig_counts = {}
for f in os.listdir('signal_replay_log'):
    if f.startswith('signal_new2_replay_') and f.endswith('.txt'):
        m = re.search(r'(\d{8})', f)
        if m:
            date = m.group(1)
            with open(f'signal_replay_log/{f}', 'r', encoding='utf-8') as fp:
                content = fp.read()
                count = len(re.findall(r'매수\[', content))
                sig_counts[date] = count

# pattern_data_log 건수
pdl_counts = {}
for f in os.listdir('pattern_data_log'):
    if f.endswith('.jsonl'):
        m = re.search(r'(\d{8})', f)
        if m:
            date = m.group(1)
            count = 0
            with open(f'pattern_data_log/{f}', 'r', encoding='utf-8') as fp:
                for line in fp:
                    if '"trade_result": {' in line:
                        count += 1
            pdl_counts[date] = count

# 비교
all_dates = sorted(set(sig_counts.keys()) | set(pdl_counts.keys()))
diff_dates = []
for d in all_dates:
    s = sig_counts.get(d, 0)
    p = pdl_counts.get(d, 0)
    if s != p:
        diff_dates.append((d, s, p, p-s))

print(f'전체 날짜: {len(all_dates)}')
print(f'차이 있는 날짜: {len(diff_dates)}')
print(f'signal_replay_log 합계: {sum(sig_counts.values())}')
print(f'pattern_data_log 합계: {sum(pdl_counts.values())}')
print()
print('차이 샘플 (날짜, sig, pdl, diff):')
for d, s, p, diff in diff_dates[:15]:
    print(f'  {d}: {s} vs {p} ({diff:+d})')
