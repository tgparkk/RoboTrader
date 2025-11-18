"""
지지구간 거래량 비율별 성과 분석
"""
import json
import glob
from collections import defaultdict


def load_all_pattern_data():
    """모든 패턴 데이터 로드"""
    all_data = []
    pattern_files = glob.glob('pattern_data_log/pattern_data_*.jsonl')

    for file_path in sorted(pattern_files):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        trade_result = data.get('trade_result')
                        if trade_result and trade_result.get('trade_executed'):
                            all_data.append(data)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            continue

    return all_data


print("="*80)
print("지지구간 거래량 비율별 성과 분석")
print("="*80)
print()

# 데이터 로드
print("데이터 로딩 중...")
all_data = load_all_pattern_data()
print(f"총 {len(all_data)}건 로드\n")

# 거래량 비율별 집계
volume_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0})
no_volume_data = 0

for data in all_data:
    trade_result = data.get('trade_result', {})
    profit = trade_result.get('profit_rate', 0)

    pattern_stages = data.get('pattern_stages', {})
    support = pattern_stages.get('3_support') or pattern_stages.get('support', {})

    # avg_volume_ratio 추출
    avg_volume_ratio_str = support.get('avg_volume_ratio', '')

    if not avg_volume_ratio_str or avg_volume_ratio_str == 'null':
        no_volume_data += 1
        continue

    try:
        # "5.7%" -> 5.7
        volume_ratio = float(avg_volume_ratio_str.replace('%', ''))
    except:
        no_volume_data += 1
        continue

    # 비율 구간으로 분류
    if volume_ratio < 10:
        bucket = '0-10%'
    elif volume_ratio < 20:
        bucket = '10-20%'
    elif volume_ratio < 30:
        bucket = '20-30%'
    elif volume_ratio < 40:
        bucket = '30-40%'
    elif volume_ratio < 50:
        bucket = '40-50%'
    else:
        bucket = '50%+'

    volume_stats[bucket]['total_profit'] += profit
    if profit > 0:
        volume_stats[bucket]['wins'] += 1
    else:
        volume_stats[bucket]['losses'] += 1

# 결과 출력
print("="*80)
print("거래량 비율 구간별 성과")
print("="*80)
print(f"{'구간':<15} {'거래수':>8} {'승률':>8} {'총수익':>10} {'평균':>8}")
print("-"*80)

buckets = ['0-10%', '10-20%', '20-30%', '30-40%', '40-50%', '50%+']
for bucket in buckets:
    stats = volume_stats[bucket]
    total = stats['wins'] + stats['losses']

    if total == 0:
        continue

    winrate = (stats['wins'] / total * 100) if total > 0 else 0
    avg_profit = stats['total_profit'] / total if total > 0 else 0

    print(f"{bucket:<15} {total:>8} {winrate:>7.1f}% {stats['total_profit']:>9.2f}% {avg_profit:>7.2f}%")

print("-"*80)
print(f"{'거래량 데이터 없음':<15} {no_volume_data:>8}")
print()

# 세부 분석: 10% 단위로 더 자세히
print("="*80)
print("세부 분석 (5% 단위)")
print("="*80)
print(f"{'구간':<15} {'거래수':>8} {'승률':>8} {'총수익':>10} {'평균':>8}")
print("-"*80)

volume_stats_detailed = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0})

for data in all_data:
    trade_result = data.get('trade_result', {})
    profit = trade_result.get('profit_rate', 0)

    pattern_stages = data.get('pattern_stages', {})
    support = pattern_stages.get('3_support') or pattern_stages.get('support', {})

    avg_volume_ratio_str = support.get('avg_volume_ratio', '')

    if not avg_volume_ratio_str or avg_volume_ratio_str == 'null':
        continue

    try:
        volume_ratio = float(avg_volume_ratio_str.replace('%', ''))
    except:
        continue

    # 5% 단위로 분류
    if volume_ratio < 5:
        bucket = '0-5%'
    elif volume_ratio < 10:
        bucket = '5-10%'
    elif volume_ratio < 15:
        bucket = '10-15%'
    elif volume_ratio < 20:
        bucket = '15-20%'
    elif volume_ratio < 25:
        bucket = '20-25%'
    elif volume_ratio < 30:
        bucket = '25-30%'
    elif volume_ratio < 35:
        bucket = '30-35%'
    elif volume_ratio < 40:
        bucket = '35-40%'
    else:
        bucket = '40%+'

    volume_stats_detailed[bucket]['total_profit'] += profit
    if profit > 0:
        volume_stats_detailed[bucket]['wins'] += 1
    else:
        volume_stats_detailed[bucket]['losses'] += 1

detailed_buckets = ['0-5%', '5-10%', '10-15%', '15-20%', '20-25%', '25-30%', '30-35%', '35-40%', '40%+']
for bucket in detailed_buckets:
    stats = volume_stats_detailed[bucket]
    total = stats['wins'] + stats['losses']

    if total == 0:
        continue

    winrate = (stats['wins'] / total * 100) if total > 0 else 0
    avg_profit = stats['total_profit'] / total if total > 0 else 0

    marker = ""
    if winrate >= 55 and total >= 50:
        marker = " [BEST]"
    elif winrate >= 52 and total >= 100:
        marker = " [GOOD]"

    print(f"{bucket:<15} {total:>8} {winrate:>7.1f}% {stats['total_profit']:>9.2f}% {avg_profit:>7.2f}%{marker}")

print()
print("="*80)
print("권장사항")
print("="*80)
print()

# 최적 구간 찾기
best_buckets = []
for bucket in detailed_buckets:
    stats = volume_stats_detailed[bucket]
    total = stats['wins'] + stats['losses']

    if total < 50:  # 최소 50건 이상
        continue

    winrate = (stats['wins'] / total * 100) if total > 0 else 0
    avg_profit = stats['total_profit'] / total if total > 0 else 0

    if winrate >= 52 and avg_profit > 0.3:
        best_buckets.append({
            'bucket': bucket,
            'trades': total,
            'winrate': winrate,
            'avg_profit': avg_profit
        })

if best_buckets:
    best_buckets.sort(key=lambda x: x['winrate'], reverse=True)

    print("성과가 좋은 거래량 구간:")
    for b in best_buckets[:3]:
        print(f"  - {b['bucket']}: 승률 {b['winrate']:.1f}%, 평균 {b['avg_profit']:.2f}% ({b['trades']}건)")

    # 최적 임계값 제안
    if best_buckets:
        top = best_buckets[0]['bucket']
        if '0-5%' in top or '5-10%' in top:
            print(f"\n추천 필터 설정: 지지구간 거래량 10% 이하")
        elif '10-15%' in top:
            print(f"\n추천 필터 설정: 지지구간 거래량 15% 이하")
        elif '15-20%' in top:
            print(f"\n추천 필터 설정: 지지구간 거래량 20% 이하")
        elif '20-25%' in top:
            print(f"\n추천 필터 설정: 지지구간 거래량 25% 이하")
        elif '25-30%' in top:
            print(f"\n추천 필터 설정: 지지구간 거래량 30% 이하")
else:
    print("충분한 데이터가 있는 구간이 없습니다. (최소 50건 필요)")
    print("모든 구간의 평균 승률을 참고하세요.")
