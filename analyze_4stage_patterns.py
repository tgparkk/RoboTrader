"""
4단계 패턴별 OHLCV 및 거래량 상세 분석
"""
import json
import glob
from collections import defaultdict
import statistics


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


def analyze_stage_patterns(all_data):
    """각 단계별 패턴 분석"""

    # 각 단계별 통계 저장
    stage1_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0, 'volumes': [], 'price_gains': []})
    stage2_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0, 'volumes': [], 'declines': []})
    stage3_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0, 'volumes': [], 'vol_ratios': []})
    stage4_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0, 'volumes': []})

    for data in all_data:
        trade_result = data.get('trade_result', {})
        profit = trade_result.get('profit_rate', 0)

        pattern_stages = data.get('pattern_stages', {})

        # === 1단계: 상승 구간 분석 ===
        uptrend = pattern_stages.get('1_uptrend') or pattern_stages.get('uptrend', {})
        if uptrend:
            candle_count = uptrend.get('candle_count', 0)
            price_gain_str = uptrend.get('price_gain', '0%')

            try:
                price_gain = float(price_gain_str.replace('%', ''))
            except:
                price_gain = 0

            # 캔들 개수로 분류
            if candle_count <= 5:
                bucket = '짧음(<=5봉)'
            elif candle_count <= 10:
                bucket = '보통(6-10봉)'
            else:
                bucket = '김(>10봉)'

            stage1_stats[bucket]['total_profit'] += profit
            stage1_stats[bucket]['price_gains'].append(price_gain)
            if profit > 0:
                stage1_stats[bucket]['wins'] += 1
            else:
                stage1_stats[bucket]['losses'] += 1

            # 거래량 분석
            candles = uptrend.get('candles', [])
            if candles:
                volumes = [c.get('volume', 0) for c in candles]
                if volumes:
                    avg_vol = sum(volumes) / len(volumes)
                    max_vol = max(volumes)
                    stage1_stats[bucket]['volumes'].append((avg_vol, max_vol))

        # === 2단계: 하락 구간 분석 ===
        decline = pattern_stages.get('2_decline') or pattern_stages.get('decline', {})
        if decline:
            candle_count = decline.get('candle_count', 0)
            decline_pct_str = decline.get('decline_pct', '0%')

            try:
                decline_pct = float(decline_pct_str.replace('%', ''))
            except:
                decline_pct = 0

            # 캔들 개수로 분류
            if candle_count <= 2:
                bucket = '짧음(<=2봉)'
            elif candle_count <= 4:
                bucket = '보통(3-4봉)'
            else:
                bucket = '김(>4봉)'

            stage2_stats[bucket]['total_profit'] += profit
            stage2_stats[bucket]['declines'].append(decline_pct)
            if profit > 0:
                stage2_stats[bucket]['wins'] += 1
            else:
                stage2_stats[bucket]['losses'] += 1

            # 거래량 분석
            candles = decline.get('candles', [])
            if candles:
                volumes = [c.get('volume', 0) for c in candles]
                if volumes:
                    avg_vol = sum(volumes) / len(volumes)
                    stage2_stats[bucket]['volumes'].append(avg_vol)

        # === 3단계: 지지 구간 분석 ===
        support = pattern_stages.get('3_support') or pattern_stages.get('support', {})
        if support:
            candle_count = support.get('candle_count', 0)
            vol_ratio_str = support.get('avg_volume_ratio', '0%')

            try:
                vol_ratio = float(vol_ratio_str.replace('%', ''))
            except:
                vol_ratio = None

            # 캔들 개수로 분류
            if candle_count <= 2:
                bucket = '짧음(<=2봉)'
            elif candle_count <= 4:
                bucket = '보통(3-4봉)'
            else:
                bucket = '김(>4봉)'

            stage3_stats[bucket]['total_profit'] += profit
            if vol_ratio is not None:
                stage3_stats[bucket]['vol_ratios'].append(vol_ratio)
            if profit > 0:
                stage3_stats[bucket]['wins'] += 1
            else:
                stage3_stats[bucket]['losses'] += 1

            # 거래량 분석
            candles = support.get('candles', [])
            if candles:
                volumes = [c.get('volume', 0) for c in candles]
                if volumes:
                    avg_vol = sum(volumes) / len(volumes)
                    stage3_stats[bucket]['volumes'].append(avg_vol)

        # === 4단계: 돌파 구간 분석 ===
        breakout = pattern_stages.get('4_breakout') or pattern_stages.get('breakout', {})
        if breakout:
            candle = breakout.get('candle', {})
            volume = candle.get('volume', 0)

            open_price = candle.get('open', 0)
            close_price = candle.get('close', 0)

            # 양봉/음봉 분류
            if close_price > open_price:
                bucket = '양봉'
            elif close_price < open_price:
                bucket = '음봉'
            else:
                bucket = '평봉'

            stage4_stats[bucket]['total_profit'] += profit
            stage4_stats[bucket]['volumes'].append(volume)
            if profit > 0:
                stage4_stats[bucket]['wins'] += 1
            else:
                stage4_stats[bucket]['losses'] += 1

    return stage1_stats, stage2_stats, stage3_stats, stage4_stats


def print_stage_stats(stage_name, stats, include_volumes=True):
    """단계별 통계 출력"""
    print("="*80)
    print(f"{stage_name} 패턴 분석")
    print("="*80)
    print(f"{'패턴':<20} {'거래수':>8} {'승률':>8} {'총수익':>10} {'평균':>8}")
    print("-"*80)

    for bucket, data in sorted(stats.items()):
        total = data['wins'] + data['losses']
        if total == 0:
            continue

        winrate = (data['wins'] / total * 100) if total > 0 else 0
        avg_profit = data['total_profit'] / total if total > 0 else 0

        print(f"{bucket:<20} {total:>8} {winrate:>7.1f}% {data['total_profit']:>9.2f}% {avg_profit:>7.2f}%")

    print()

    # 거래량 통계
    if include_volumes:
        print(f"[{stage_name} 거래량 분석]")
        for bucket, data in sorted(stats.items()):
            if not data['volumes']:
                continue

            if stage_name == "1단계: 상승 구간":
                # (avg_vol, max_vol) 튜플
                avg_vols = [v[0] for v in data['volumes'] if v[0] > 0]
                max_vols = [v[1] for v in data['volumes'] if v[1] > 0]

                if avg_vols:
                    print(f"  {bucket}: 평균거래량 {statistics.mean(avg_vols):,.0f}, "
                          f"최대거래량 {statistics.mean(max_vols):,.0f}")
            else:
                # 단일 거래량
                volumes = [v for v in data['volumes'] if v > 0]
                if volumes:
                    print(f"  {bucket}: 평균거래량 {statistics.mean(volumes):,.0f}")

        print()

        # 추가 통계 (가격 변화, 거래량 비율 등)
        if stage_name == "1단계: 상승 구간":
            print(f"[상승률 통계]")
            for bucket, data in sorted(stats.items()):
                if data['price_gains']:
                    print(f"  {bucket}: 평균 상승 {statistics.mean(data['price_gains']):.2f}%")
            print()

        elif stage_name == "2단계: 하락 구간":
            print(f"[하락률 통계]")
            for bucket, data in sorted(stats.items()):
                if data['declines']:
                    print(f"  {bucket}: 평균 하락 {statistics.mean(data['declines']):.2f}%")
            print()

        elif stage_name == "3단계: 지지 구간":
            print(f"[거래량 비율 통계 (기준 대비 %)]")
            for bucket, data in sorted(stats.items()):
                if data['vol_ratios']:
                    print(f"  {bucket}: 평균 {statistics.mean(data['vol_ratios']):.1f}%")
            print()


# 메인 실행
print("데이터 로딩 중...")
all_data = load_all_pattern_data()
print(f"총 {len(all_data)}건 로드\n")

stage1_stats, stage2_stats, stage3_stats, stage4_stats = analyze_stage_patterns(all_data)

print_stage_stats("1단계: 상승 구간", stage1_stats)
print_stage_stats("2단계: 하락 구간", stage2_stats)
print_stage_stats("3단계: 지지 구간", stage3_stats)
print_stage_stats("4단계: 돌파 구간", stage4_stats)

# 종합 인사이트
print("="*80)
print("종합 인사이트")
print("="*80)
print()

# 각 단계별 최고 패턴 찾기
def find_best_pattern(stats):
    best = None
    best_score = 0

    for bucket, data in stats.items():
        total = data['wins'] + data['losses']
        if total < 100:  # 최소 100건 이상
            continue

        winrate = (data['wins'] / total * 100) if total > 0 else 0
        avg_profit = data['total_profit'] / total if total > 0 else 0

        # 점수 = 승률 * 평균수익
        score = winrate * avg_profit

        if score > best_score:
            best_score = score
            best = (bucket, winrate, avg_profit, total)

    return best

print("각 단계별 최고 성과 패턴 (최소 100건 이상):")
print()

for stage_name, stats in [
    ("1단계 (상승)", stage1_stats),
    ("2단계 (하락)", stage2_stats),
    ("3단계 (지지)", stage3_stats),
    ("4단계 (돌파)", stage4_stats)
]:
    best = find_best_pattern(stats)
    if best:
        bucket, winrate, avg_profit, total = best
        print(f"{stage_name}: {bucket}")
        print(f"  - 승률: {winrate:.1f}%, 평균수익: {avg_profit:.2f}%, 거래: {total}건")
    else:
        print(f"{stage_name}: 충분한 데이터 없음")

print()
